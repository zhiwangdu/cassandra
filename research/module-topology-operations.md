# Module: Topology Operations

## 范围

本模块覆盖替换节点、移动 token、移除死亡节点、重建数据和最后手段的 assassinate。它补齐 bootstrap/decommission 第一轮文档之外的拓扑变更深水区：同一套 ring metadata、gossip state、pending ranges、streaming、Paxos topology repair 和 JMX/nodetool 入口如何组合成不同运维动作。

## 设计目标

- 让节点在不破坏复制因子和一致性假设的前提下进入、离开或改变 token ownership。`StorageServiceMBean.move()` 明确描述 move 会卸载旧数据并 bootstrap 到新 token，`removeNode()`/`forceRemoveCompletion()` 暴露死亡节点移除与强制完成入口，见 `src/java/org/apache/cassandra/service/StorageServiceMBean.java:528-550`。
- 让已经在 ring 中的节点可以通过 rebuild 从其他节点重新拉取自己负责的 ranges，而不是重新 bootstrap 或全量 repair；JMX 接口说明 rebuild 类似 bootstrap，但目标是已在集群中的节点，见 `src/java/org/apache/cassandra/service/StorageServiceMBean.java:848-878`。
- 对 replace/move/bootstrap 使用 strict range movement 防止多个拓扑变更同时改变同一批 pending ranges；`useStrictConsistency` 默认取自 `cassandra.consistent.rangemovement`，见 `src/java/org/apache/cassandra/service/StorageService.java:502-506` 和 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:171-177`。

## 解决的问题

- Replace 解决“同一 token/host id 对应的旧节点已经不可用，但 ring 仍需要保持复制布局”的问题。`prepareForReplacement()` 从 shadow gossip 读取被替换节点的 tokens、校验 snitch 与 token 冲突，并在同地址替换时复用旧 host id，见 `src/java/org/apache/cassandra/service/StorageService.java:742-837` 和 `src/java/org/apache/cassandra/service/StorageService.java:839-866`。
- Move 解决单 token 节点重新定位的问题。`StorageService.move()` 拒绝 vnodes、多 token、目标 token 冲突和本节点已有 incoming pending ranges 的情况，然后进入 MOVING 状态并调用 `RangeRelocator` 计算 stream/fetch，见 `src/java/org/apache/cassandra/service/StorageService.java:5527-5612`。
- Removenode 解决死亡节点无法自发 decommission 时的 replica restoration。`removeNode()` 拒绝 live/self/non-member 目标，计算需要确认的 `replicatingNodes`，广播 REMOVING_TOKEN，等待 REPLICATION_DONE，再 excise token，见 `src/java/org/apache/cassandra/service/StorageService.java:5654-5770`。
- Rebuild 解决“节点已经在 ring 中但缺数据”的恢复问题。它按 source DC、keyspace、token ranges 和 source allow-list 构建 `RangeStreamer`，再等待 streaming 完成，见 `src/java/org/apache/cassandra/service/StorageService.java:1515-1661`。
- Assassinate 解决 removenode 也无法推进时的最后手段：nodetool 描述明确说它不重新复制数据，`Gossiper.assassinateEndpoint()` 直接把 endpoint 推成 LEFT 状态，见 `src/java/org/apache/cassandra/tools/nodetool/Assassinate.java:29-46` 和 `src/java/org/apache/cassandra/gms/Gossiper.java:914-965`。

## 设计取舍

- Replace 选择从 gossip shadow round 获取被替换节点信息，而不是只依赖本地 system tables。这样能在启动早期发现 live replacement 和 token ownership 冲突；代价是被替换节点的 gossip 状态缺失时需要 `cassandra.allow_empty_replace_address` 这类 escape hatch，见 `src/java/org/apache/cassandra/service/StorageService.java:756-820` 和 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:412-419`。
- Move 只支持单 token 节点。源码直接说明 vnodes 环境中 move 没有意义，并在本地 token 数大于 1 时抛出，见 `src/java/org/apache/cassandra/service/StorageService.java:5555-5563`。
- Removenode 由存活节点恢复 replica count，而 decommission 由离开的 live node 先主动 stream 自己的数据。`getChangedReplicasForLeaving()` 被注释为同时服务 graceful decommission 和 restoreReplicaCount/removeNode，因此两者共享范围计算，但数据源方向不同，见 `src/java/org/apache/cassandra/service/StorageService.java:3770-3833`。
- Force remove 和 assassinate 都是可用性优先的危险入口。`forceRemoveCompletion()` 明确不会继续恢复 replicas，`Assassinate` 命令描述也明确不 re-replicate，见 `src/java/org/apache/cassandra/service/StorageService.java:5649-5672` 和 `src/java/org/apache/cassandra/tools/nodetool/Assassinate.java:29-46`。

## 核心类

- `StorageService` 是 topology operation 的中心实现：replace/bootstrap 在启动路径执行，move/removenode/rebuild/decommission 通过 JMX/nodetool 调用，见 `src/java/org/apache/cassandra/service/StorageService.java:742-837`、`src/java/org/apache/cassandra/service/StorageService.java:1515-1661`、`src/java/org/apache/cassandra/service/StorageService.java:5527-5770`。
- `RangeRelocator` 专用于 move。它持有 `StreamPlan(StreamOperation.RELOCATION)`、本地地址、move 前后 token metadata 克隆和 keyspace 列表，见 `src/java/org/apache/cassandra/service/RangeRelocator.java:54-75`。
- `RangeStreamer` 被 bootstrap/rebuild/move 的 fetch 侧复用。`RangeRelocator` 通过 `RangeStreamer.calculateRangesToFetchWithPreferredEndpoints()` 和 source filters 选择 fetch sources，见 `src/java/org/apache/cassandra/service/RangeRelocator.java:86-105`。
- `Gossiper` 负责对外广播 removal 状态。`advertiseRemoving()` 写入 REMOVING_TOKEN 与 REMOVAL_COORDINATOR，`advertiseTokenRemoved()` 切成 REMOVED_TOKEN，见 `src/java/org/apache/cassandra/gms/Gossiper.java:854-898`。
- `NodeProbe` 和 nodetool 命令是运维入口。`move`、`removenode`、`rebuild`、`assassinate` 都是薄封装，最终调用 JMX MBean 或 Gossiper MBean，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:1016-1038`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1692-1694`、`src/java/org/apache/cassandra/tools/nodetool/Move.java:29-45`、`src/java/org/apache/cassandra/tools/nodetool/RemoveNode.java:27-50`、`src/java/org/apache/cassandra/tools/nodetool/Rebuild.java:27-64`。

## 核心接口

- `StorageServiceMBean` 是 JMX 合同，定义 `decommission`、`move`、`removeNode`、`getRemovalStatusWithPort`、`forceRemoveCompletion`、`rebuild` 和 `resumeBootstrap`，见 `src/java/org/apache/cassandra/service/StorageServiceMBean.java:504-550`、`src/java/org/apache/cassandra/service/StorageServiceMBean.java:848-878`、`src/java/org/apache/cassandra/service/StorageServiceMBean.java:1079-1085`。
- `NodeProbe` 将 nodetool 调用映射到 `StorageServiceMBean`，例如 `move()`、`removeNode()`、`forceRemoveCompletion()`、`rebuild()`，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:1016-1033` 和 `src/java/org/apache/cassandra/tools/NodeProbe.java:1692-1694`。
- `StreamManagerMBean` 不是 topology 专用接口，但拓扑操作中的 streaming 状态通过 `StreamManager` 暴露；`StreamManager` 注释说明它管理当前运行的 `StreamResultFuture` 并提供状态和进度，见 `src/java/org/apache/cassandra/streaming/StreamManager.java:51-75`。

## 核心数据结构

- `TokenMetadata` 保存 normal/bootstrap/leaving/moving endpoints。replace 校验 token ownership，bootstrap/move/removenode 都在此基础上计算 pending ranges 和最终 ownership，见 `src/java/org/apache/cassandra/service/StorageService.java:839-866`、`src/java/org/apache/cassandra/service/StorageService.java:2108-2119`、`src/java/org/apache/cassandra/service/StorageService.java:5732-5737`。
- `EndpointsByReplica` 表示“旧 replica 到新 replica”的 changed ranges。`restoreReplicaCount()` 和 `removeNode()` 通过它找到需要 fetch 的新 owners，见 `src/java/org/apache/cassandra/service/StorageService.java:3710-3728` 和 `src/java/org/apache/cassandra/service/StorageService.java:5711-5728`。
- `RangesAtEndpoint` / `RangesByEndpoint` 表示 move 中本节点要 fetch 和要 stream 的 ranges。`RangeRelocator.calculateStreamAndFetchRanges()` 返回 `toStream` 与 `toFetch`，见 `src/java/org/apache/cassandra/service/RangeRelocator.java:235-266`。
- `StreamPlan` 是实际传输计划。move 使用 `StreamOperation.RELOCATION`，removenode restore 使用 `RESTORE_REPLICA_COUNT`，rebuild 使用 `REBUILD`，见 `src/java/org/apache/cassandra/service/RangeRelocator.java:54-60`、`src/java/org/apache/cassandra/service/StorageService.java:3730-3752`、`src/java/org/apache/cassandra/service/StorageService.java:1553-1561`。

## 生命周期

- Replace 生命周期：启动时读取 `cassandra.replace_address` 或 `cassandra.replace_address_first_boot`，`prepareToJoin()` 进入 replacement 分支，`prepareForReplacement()` 收集被替换节点的 tokens，然后 `prepareForBootstrap()` 等待并拒绝 live replacement，最后通过 bootstrap streaming 加入 ring，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:2122-2136`、`src/java/org/apache/cassandra/service/StorageService.java:1160-1188`、`src/java/org/apache/cassandra/service/StorageService.java:2092-2195`、`src/java/org/apache/cassandra/service/StorageService.java:2207-2263`。
- Move 生命周期：nodetool -> NodeProbe -> `StorageService.move(String)`；校验 token 后设置 MOVING gossip state，等待 ring delay，`RangeRelocator` 计算并执行 stream/fetch，Paxos topology repair 后 `setTokens()` 完成，见 `src/java/org/apache/cassandra/tools/nodetool/Move.java:29-45`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1016-1018`、`src/java/org/apache/cassandra/service/StorageService.java:5527-5612`。
- Removenode 生命周期：nodetool 支持 `status`、`force`、host id 三种模式；普通 remove 计算 surviving endpoints、广播 REMOVING_TOKEN、执行 `restoreReplicaCount()`、等待 `confirmReplication()`，再 excise 并广播 REMOVED_TOKEN，见 `src/java/org/apache/cassandra/tools/nodetool/RemoveNode.java:27-50` 和 `src/java/org/apache/cassandra/service/StorageService.java:5683-5770`。
- Rebuild 生命周期：nodetool 参数校验后调用 JMX；服务端校验 source DC/keyspace/tokens/source list，构建 `RangeStreamer`，按本地 replicas 或指定 subranges 发起 fetch，等待结果并复位 `isRebuilding`，见 `src/java/org/apache/cassandra/tools/nodetool/Rebuild.java:27-64` 和 `src/java/org/apache/cassandra/service/StorageService.java:1515-1661`。
- Assassinate 生命周期：nodetool 直接调用 `GossiperMBean.assassinateEndpoint()`；Gossiper 校验心跳/generation 没变化后写入 LEFT 状态并触发 major state change，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:1036-1038` 和 `src/java/org/apache/cassandra/gms/Gossiper.java:914-965`。

## 调用链

```text
nodetool move <token>
  -> Move.execute()
  -> NodeProbe.move()
  -> StorageServiceMBean.move()
  -> StorageService.move(String)
  -> RangeRelocator.calculateToFromStreams()
  -> StreamPlan.transferRanges/requestRanges
  -> RangeRelocator.stream().get()
  -> StorageService.setTokens(newToken)
```

Move 的关键调用链证据见 `src/java/org/apache/cassandra/tools/nodetool/Move.java:35-45`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1016-1018`、`src/java/org/apache/cassandra/service/StorageService.java:5527-5612`、`src/java/org/apache/cassandra/service/RangeRelocator.java:164-233`、`src/java/org/apache/cassandra/service/RangeRelocator.java:314-322`。

```text
nodetool removenode <hostId>
  -> RemoveNode.execute()
  -> NodeProbe.removeNode()
  -> StorageService.removeNode()
  -> getChangedReplicasForLeaving()
  -> Gossiper.advertiseRemoving()
  -> restoreReplicaCount()
  -> sendReplicationNotification()
  -> confirmReplication()
  -> excise()
  -> Gossiper.advertiseTokenRemoved()
```

Removenode 的关键调用链证据见 `src/java/org/apache/cassandra/tools/nodetool/RemoveNode.java:33-49`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1021-1033`、`src/java/org/apache/cassandra/service/StorageService.java:5683-5770`、`src/java/org/apache/cassandra/service/StorageService.java:3704-3767`、`src/java/org/apache/cassandra/gms/Gossiper.java:854-898`。

## 配置项

- `auto_bootstrap`、`initial_token`、`num_tokens`、`allocate_tokens_for_keyspace` 和 `allocate_tokens_for_local_replication_factor` 影响 bootstrap/replace token 选择，见 `src/java/org/apache/cassandra/config/Config.java:111-136`。
- `cassandra.replace_address` / `cassandra.replace_address_first_boot` 是 replacement 入口，`DatabaseDescriptor.getReplaceAddress()` 会优先解析这两个 system properties，见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:417-419` 和 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:2122-2136`。
- `cassandra.allow_unsafe_replace` 允许不 bootstrap 的 replacement，但源码错误信息明确说这会冒破坏一致性风险，见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:49-50` 和 `src/java/org/apache/cassandra/service/StorageService.java:750-754`。
- `cassandra.allow_empty_replace_address` 允许 replacement 在 gossip state 为空时基于 shadow round/system table 线索继续，见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:412-417` 和 `src/java/org/apache/cassandra/service/StorageService.java:775-820`。
- `cassandra.consistent.rangemovement` 默认 true，限制 bootstrap/leaving/moving 并发；`cassandra.consistent.simultaneousmoves.allow` 是 escape hatch，见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:171-177` 和 `src/java/org/apache/cassandra/service/StorageService.java:895-913`。
- `cassandra.reset_bootstrap_progress` 会在 bootstrap/replacement 时重置已有 streamed ranges 进度，见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:427-429` 和 `src/java/org/apache/cassandra/service/StorageService.java:2237-2241`。

## Metrics

- topology 操作本身没有独立的 `TopologyMetrics`，主要复用 streaming 观测。`StreamingMetrics` 暴露 total incoming/outgoing bytes、repair outgoing bytes、peer incoming/outgoing bytes、incoming process time 和 entire/partial SSTable counters，见 `src/java/org/apache/cassandra/metrics/StreamingMetrics.java:31-94`。
- `nodetool netstats` 输出当前 operation mode 和 `StreamState` sessions，适用于 move/rebuild/bootstrap/decommission/removenode restore 的 streaming 进度，见 `src/java/org/apache/cassandra/tools/nodetool/NetStats.java:45-74`。
- `system_views.streaming` 来自 `StreamingVirtualTable`，包含 operation、peers、status、progress、duration、failure/success message 和 session 列，见 `src/java/org/apache/cassandra/db/virtual/StreamingVirtualTable.java:33-103`。
- JMX progress notification 由 `StreamEventJMXNotifier` 把 STREAM_PREPARED、STREAM_COMPLETE、FILE_PROGRESS、success/failure 转成 notifications，见 `src/java/org/apache/cassandra/streaming/management/StreamEventJMXNotifier.java:39-92`。

## 日志

- Replace 会记录 replacement 信息收集、gossip state 缺失、同地址替换写转发风险，见 `src/java/org/apache/cassandra/service/StorageService.java:756-820` 和 `src/java/org/apache/cassandra/service/StorageService.java:1179-1187`。
- Move 通过 `setMode(Mode.MOVING, ...)` 暴露 moving、ring delay、streaming/no-streaming 状态，最终 debug 记录成功 token，见 `src/java/org/apache/cassandra/service/StorageService.java:5576-5611`。
- Rebuild 记录 source DC/keyspace/tokens，失败时写 error 并通过 RuntimeException 返回给 JMX 调用者，见 `src/java/org/apache/cassandra/service/StorageService.java:1545-1551` 和 `src/java/org/apache/cassandra/service/StorageService.java:1651-1656`。
- Removenode 会记录无法参与 re-replication 的 down endpoints、未确认 force remove、unexpected REPLICATION_FINISHED，见 `src/java/org/apache/cassandra/service/StorageService.java:5718-5728`、`src/java/org/apache/cassandra/service/StorageService.java:5654-5672`、`src/java/org/apache/cassandra/service/StorageService.java:5757-5770`。

## 运维关注点

- 活节点下线优先 decommission；`removeNode()` 源码遇到 live member 会直接提示使用 decommission，见 `src/java/org/apache/cassandra/service/StorageService.java:5699-5701`。
- Move 不适用于 vnodes。要检查本地 token 数；源码对多 token 节点抛 `UnsupportedOperationException`，见 `src/java/org/apache/cassandra/service/StorageService.java:5558-5563`。
- Removenode 卡住时先看 `nodetool removenode status` 和 `nodetool netstats`。状态字符串列出仍待确认的 replication endpoints，见 `src/java/org/apache/cassandra/service/StorageService.java:5614-5647`；netstats 输出 streaming 状态，见 `src/java/org/apache/cassandra/tools/nodetool/NetStats.java:45-74`。
- 同地址 replacement 会进入 hibernate 状态，源码提示旧节点 down 超过 max hint window 后 replacement 完成仍需要 repair，见 `src/java/org/apache/cassandra/service/StorageService.java:1179-1187`。
- Rebuild 指定 `--tokens` 必须同时指定 keyspace，指定 source 不能包含本机，见 `src/java/org/apache/cassandra/tools/nodetool/Rebuild.java:54-64` 和 `src/java/org/apache/cassandra/service/StorageService.java:1534-1537`、`src/java/org/apache/cassandra/service/StorageService.java:1617-1638`。

## 性能瓶颈

- move、replace、rebuild、removenode restore 都受 streaming throughput、source selection、disk flush/compaction 和 network bandwidth 影响。`RangeStreamer`/`StreamPlan` 是核心执行点，`StreamManager` 负责 rate limiter 和状态跟踪，见 `src/java/org/apache/cassandra/streaming/StreamManager.java:51-75` 和 `src/java/org/apache/cassandra/streaming/StreamManager.java:217-286`。
- Move 的瓶颈来自对每个 distributed keyspace 计算 stream/fetch ranges，并同时执行 transfer/request。计算点见 `src/java/org/apache/cassandra/service/RangeRelocator.java:164-233`。
- Removenode restore 的瓶颈来自每个 surviving endpoint 的 fetch plan；`restoreReplicaCount()` 注释也承认该方法效率不高但调用很少，见 `src/java/org/apache/cassandra/service/StorageService.java:3694-3704` 和 `src/java/org/apache/cassandra/service/StorageService.java:3710-3752`。
- Rebuild 支持按 keyspace/token/source 缩小范围；若不指定 keyspace 会对所有 distributed keyspaces 拉取本地 replicas，见 `src/java/org/apache/cassandra/service/StorageService.java:1568-1576`。

## 常见故障

- Replace 活节点会失败。`prepareForBootstrap()` 会等待并检查被替换 token 的 endpoint 是否最近更新或仍 alive，然后抛 `Cannot replace a live node`，见 `src/java/org/apache/cassandra/service/StorageService.java:2135-2178`。
- Replace token 冲突会失败。`validateReplacementBootstrapTokens()` 发现被替换节点 gossip tokens 已被其他 peer 拥有会抛冲突异常，见 `src/java/org/apache/cassandra/service/StorageService.java:839-866`。
- Bootstrap/replace/move/decommission 并发会被 strict range movement 拦截。启动 shadow gossip 和 bootstrap 准备阶段都会检查 bootstrapping/leaving/moving 状态，见 `src/java/org/apache/cassandra/service/StorageService.java:895-913` 和 `src/java/org/apache/cassandra/service/StorageService.java:2108-2119`。
- Removenode 对 live/self/non-member/unknown host id 会失败，且同时只能处理一个 removal，见 `src/java/org/apache/cassandra/service/StorageService.java:5683-5708`。
- Rebuild 参数不合法或并发 rebuild 会失败：source DC 不存在、tokens 缺 keyspace、指定 source 为本机、已有 rebuild 都会抛异常，见 `src/java/org/apache/cassandra/service/StorageService.java:1517-1543` 和 `src/java/org/apache/cassandra/service/StorageService.java:1617-1638`。
- Assassinate 可能让后续 replacement 启动失败。分布式测试说明先 assassinate 再 replace 会导致节点因 non-normal status 无法启动，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/AssassinateAbruptDownedNodeTest.java:30-58`。

## 测试用例

- `HostReplacementTest` 覆盖 down host replacement、live host replacement 失败、seed 先 down 再 replacement 的场景，并校验 replacement 后数据仍可读，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementTest.java:65-145` 和 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementTest.java:149-195`。
- `MoveTest` 分布式测试在无 vnodes 的 4 节点 ring 上执行 `nodetool move`，覆盖正向和反向移动，见 `test/distributed/org/apache/cassandra/distributed/test/MoveTest.java:49-91`。
- 单元 `MoveTest` 覆盖 SimpleStrategy/NetworkTopologyStrategy 下 pending ranges 计算，见 `test/unit/org/apache/cassandra/service/MoveTest.java:208-337` 和 `test/unit/org/apache/cassandra/service/MoveTest.java:403-520`。
- `MoveTransientTest` 覆盖 transient replication 下 `RangeRelocator` 的 fetch/stream 计算和 down/source-filter 异常，见 `test/unit/org/apache/cassandra/service/MoveTransientTest.java:59-63`、`test/unit/org/apache/cassandra/service/MoveTransientTest.java:171-305`、`test/unit/org/apache/cassandra/service/MoveTransientTest.java:392-675`。
- `RemoveTest` 覆盖 unknown/local/non-member host id 失败，以及 removeNode 等待 `REPLICATION_DONE_REQ` 后完成 leaving endpoint 清理，见 `test/unit/org/apache/cassandra/service/RemoveTest.java:108-179`。
- `UpdateSystemAuthAfterDCExpansionTest` 覆盖强制关闭节点后由其他节点 `StorageService.instance.removeNode()` 再修改 system_auth RF 的运维流，见 `test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java:188-213`。
- `RebuildStreamingTest` 覆盖 zero-copy 与非 zero-copy rebuild，并通过 `system_views.streaming` 验证 streaming 状态，见 `test/distributed/org/apache/cassandra/distributed/test/streaming/RebuildStreamingTest.java:43-85`。
- `AssassinateAbruptDownedNodeTest` 覆盖 abrupt down 后 assassinate 的 gossip/DDL 边界，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/AssassinateAbruptDownedNodeTest.java:30-58`。

## 待补

- 第二轮补充见 `module-topology-operations-internals.md`，已覆盖 simulator JOIN/LEAVE/REPLACE/CHANGE_RF、Paxos topology repair、replacement 故障边界和 transient replica restore 语义。
- 仍需补真正的跨 DC replacement 专项 dtest；当前跨 DC 证据主要来自 system_auth DC expansion/removeNode 流程。
- 仍需补 removenode 与 transient replication 的完整 distributed test 对照；当前主要是生产源码语义和 `MoveTransientTest` 单测。
