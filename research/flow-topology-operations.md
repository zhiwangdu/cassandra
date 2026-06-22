# Flow: Topology Operations

本调用图把 replace、move、removenode、rebuild、assassinate 放在同一页对照。它不重复 bootstrap/decommission 文档中的主线，而是突出这些操作如何共享 token metadata、gossip state、pending range calculation、streaming 和 nodetool/JMX 入口。

## Replace Dead Node

```text
JVM system properties
  -Dcassandra.replace_address=<dead endpoint>
  or -Dcassandra.replace_address_first_boot=<dead endpoint>
  -> DatabaseDescriptor.getReplaceAddress()
  -> CassandraDaemon.setup()
  -> StorageService.initServer()
  -> prepareToJoin()
     -> replacing branch
     -> prepareForReplacement()
        -> Gossiper.doShadowRound()
        -> read TOKENS from replaced endpoint state
        -> validateReplacementBootstrapTokens()
        -> optionally initialize empty unreachable gossip state
        -> same-address replacement reuses old host id
     -> publish TOKENS or hibernate state
  -> joinTokenRing()
     -> prepareForBootstrap()
        -> wait schema and pending ranges
        -> reject live replacement / missing token
     -> bootstrap(tokens)
        -> gossip BOOT_REPLACING
        -> repairPaxosForTopologyChange("bootstrap")
        -> startBootstrap()
        -> BootStrapper / RangeStreamer fetch pending ranges
        -> bootstrapFinished()
```

关键源码：

- Replacement property 由 `DatabaseDescriptor.getReplaceAddress()` 解析，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:2122-2136`。
- `prepareToJoin()` 拒绝旧 replace token/node 参数，进入 replacement 分支并可设置 hibernate 状态，见 `src/java/org/apache/cassandra/service/StorageService.java:1160-1188`。
- `prepareForReplacement()` 执行 shadow gossip、token 读取、empty replacement 处理和同地址 host id 复用，见 `src/java/org/apache/cassandra/service/StorageService.java:742-837`。
- token conflict 校验见 `src/java/org/apache/cassandra/service/StorageService.java:839-866`。
- `prepareForBootstrap()` 在 replacement 中等待 ring 信息，并拒绝 live/missing replacement token，见 `src/java/org/apache/cassandra/service/StorageService.java:2092-2195`。
- `bootstrap()` 对 replacement 发布 BOOT_REPLACING 或同地址 replacement 本地接管 token，然后执行 Paxos repair 和 bootstrap streaming，见 `src/java/org/apache/cassandra/service/StorageService.java:2207-2263`。

## Move Token

```text
nodetool move <newToken>
  -> Move.execute()
  -> NodeProbe.move(newToken)
  -> StorageServiceMBean.move(newToken)
  -> StorageService.move(String)
     -> token factory validate/fromString
     -> reject null/existing target token
     -> reject vnode/multiple-token node
     -> block pending range calculator
     -> reject if data is already moving to this node
     -> gossip STATUS=MOVING
     -> sleep ring delay
     -> new RangeRelocator(newToken, distributed keyspaces, tokenMetadata)
     -> RangeRelocator.calculateToFromStreams()
        -> current replicas vs pending address ranges
        -> calculate ranges to stream
        -> calculate ranges to fetch with preferred endpoints
        -> StreamPlan.transferRanges / requestRanges
     -> repairPaxosForTopologyChange("move")
     -> RangeRelocator.stream().get()
     -> setTokens(newToken)
```

关键源码：

- nodetool 和 NodeProbe 入口见 `src/java/org/apache/cassandra/tools/nodetool/Move.java:29-45` 和 `src/java/org/apache/cassandra/tools/NodeProbe.java:1016-1018`。
- `StorageService.move()` 的校验、MOVING gossip、ring delay、Paxos repair、stream 执行和 `setTokens()` 见 `src/java/org/apache/cassandra/service/StorageService.java:5527-5612`。
- `RangeRelocator` 维护 relocation stream plan 和 move 前后 token metadata clone，见 `src/java/org/apache/cassandra/service/RangeRelocator.java:54-75`。
- `calculateToFromStreams()` 为每个 distributed keyspace 计算当前/更新 replicas、stream ranges、fetch ranges，并写入 `StreamPlan`，见 `src/java/org/apache/cassandra/service/RangeRelocator.java:164-233`。
- `calculateStreamAndFetchRanges()` 对 full/transient 转换做差集计算，见 `src/java/org/apache/cassandra/service/RangeRelocator.java:235-312`。

## Removenode Dead Node

```text
nodetool removenode <hostId>
  -> RemoveNode.execute()
  -> NodeProbe.removeNode(hostId)
  -> StorageService.removeNode(hostId)
     -> resolve host id to endpoint
     -> reject unknown / non-member / self / live endpoint
     -> reject another in-flight removal
     -> for each distributed keyspace:
          getChangedReplicasForLeaving()
          add alive changed endpoints to replicatingNodes
     -> tokenMetadata.addLeavingEndpoint()
     -> PendingRangeCalculatorService.update()
     -> Gossiper.advertiseRemoving(endpoint, removedHostId, coordinatorHostId)
     -> restoreReplicaCount(endpoint, coordinator)
        -> each surviving node that becomes responsible requests ranges
        -> StreamPlan(StreamOperation.RESTORE_REPLICA_COUNT).requestRanges()
        -> sendReplicationNotification(coordinator)
     -> wait until confirmReplication() removes all replicatingNodes
     -> excise(tokens, endpoint)
     -> Gossiper.advertiseTokenRemoved(endpoint, hostId)
```

关键源码：

- nodetool 支持 `status`、`force`、`<ID>` 三种 remove operation，见 `src/java/org/apache/cassandra/tools/nodetool/RemoveNode.java:27-50`。
- NodeProbe 的 `removeNode()`、`getRemovalStatus()`、`forceRemoveCompletion()` 见 `src/java/org/apache/cassandra/tools/NodeProbe.java:1021-1033`。
- `StorageService.removeNode()` 完整流程见 `src/java/org/apache/cassandra/service/StorageService.java:5683-5770`。
- `getChangedReplicasForLeaving()` 说明它同时被 graceful decommission 和 restoreReplicaCount/removeNode 使用，见 `src/java/org/apache/cassandra/service/StorageService.java:3770-3833`。
- `restoreReplicaCount()` 构建 `RESTORE_REPLICA_COUNT` stream plan 并在 success/failure 都发送 replication notification，见 `src/java/org/apache/cassandra/service/StorageService.java:3704-3767`。
- `Gossiper.advertiseRemoving()` 和 `advertiseTokenRemoved()` 负责 REMOVING_TOKEN -> REMOVED_TOKEN 状态传播，见 `src/java/org/apache/cassandra/gms/Gossiper.java:854-898`。
- 收到 removal gossip 的其他节点在 `handleStateRemoving()` 中执行本地 restore/excise，见 `src/java/org/apache/cassandra/service/StorageService.java:3460-3515`。

## Status And Force Remove

```text
nodetool removenode status
  -> getRemovalStatusWithPort()
  -> "No token removals in process"
     or "Waiting for replication confirmation from [...]"

nodetool removenode force
  -> print current removal status
  -> forceRemoveCompletion()
     -> advertiseTokenRemoved() for leaving endpoints
     -> excise() without further restoreReplicaCount work
```

关键源码：

- `getRemovalStatus()` 展示当前 removal token 和等待确认的 `replicatingNodes`，见 `src/java/org/apache/cassandra/service/StorageService.java:5614-5647`。
- `forceRemoveCompletion()` 注释明确说这是 last resort，且不再尝试恢复 replicas，见 `src/java/org/apache/cassandra/service/StorageService.java:5649-5672`。

## Rebuild Existing Node

```text
nodetool rebuild [srcDc] [-ks keyspace] [-ts ranges] [-s sources] [--exclude-local-dc]
  -> Rebuild.execute()
  -> NodeProbe.rebuild(...)
  -> StorageService.rebuild(...)
     -> reject sourceDc == localDc with exclude-local-dc
     -> validate source DC exists
     -> reject tokens without keyspace
     -> isRebuilding CAS
     -> repairPaxosForTopologyChange("rebuild")
     -> new RangeStreamer(StreamOperation.REBUILD)
     -> optional SingleDatacenterFilter / ExcludeLocalDatacenterFilter
     -> if no keyspace:
          add all local replicas for each distributed keyspace
        else if no tokens:
          add local replicas for keyspace
        else:
          parse token ranges
          validate each range belongs to local replicas
          optional AllowedSourcesFilter
          add subranges
     -> fetchAsync().get()
     -> isRebuilding=false
```

关键源码：

- nodetool 参数和前置校验见 `src/java/org/apache/cassandra/tools/nodetool/Rebuild.java:27-64`。
- NodeProbe 调用 JMX 的入口见 `src/java/org/apache/cassandra/tools/NodeProbe.java:1692-1694`。
- `StorageService.rebuild()` 的参数校验、RangeStreamer 构造、source filters、range parsing、fetch 等待和 finally reset 见 `src/java/org/apache/cassandra/service/StorageService.java:1515-1661`。
- 分布式测试通过 `nodetool rebuild --keyspace` 覆盖 zero-copy/non-zero-copy streaming，并读取 `system_views.streaming`，见 `test/distributed/org/apache/cassandra/distributed/test/streaming/RebuildStreamingTest.java:43-85`。

## Assassinate Boundary

```text
nodetool assassinate <endpoint>
  -> Assassinate.execute()
  -> NodeProbe.assassinateEndpoint()
  -> GossiperMBean.assassinateEndpoint()
  -> Gossiper.assassinateEndpoint()
     -> resolve endpoint
     -> if state exists:
          sleep ring delay
          ensure generation/heartbeat unchanged
          force newer generation
        else:
          create synthetic endpoint state
     -> get endpoint tokens or random token fallback
     -> write STATUS=LEFT
     -> handleMajorStateChange()
     -> sleep gossip intervals
```

关键源码：

- `Assassinate` 的命令描述明确它是无法 removenode 时的最后手段，且不重新复制数据，见 `src/java/org/apache/cassandra/tools/nodetool/Assassinate.java:29-46`。
- NodeProbe 通过 `gossProxy.assassinateEndpoint()` 调用 Gossiper MBean，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:1036-1038`。
- `Gossiper.assassinateEndpoint()` 的 generation/heartbeat 防护、token fallback 和 LEFT 状态写入见 `src/java/org/apache/cassandra/gms/Gossiper.java:914-965`。
- abrupt down + assassinate 的测试说明这一入口会影响后续 replacement/DDL 边界，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/AssassinateAbruptDownedNodeTest.java:30-58`。

## Decommission / Removenode / Move 对照

| 操作 | 目标节点状态 | 数据从哪里来 | gossip 状态 | 完成信号 |
|---|---|---|---|---|
| `decommission` | 本节点 live，主动离开 | 离开节点主动 stream 自己负责的 ranges | leaving/left | 本节点 stream 完成并离开 ring |
| `removenode` | 目标节点 dead，不能主动离开 | surviving nodes 通过 `restoreReplicaCount()` 从现有 replicas 拉取 | REMOVING_TOKEN -> REMOVED_TOKEN | `REPLICATION_DONE_REQ` 确认清空 `replicatingNodes` |
| `move` | 本节点 live，只改变 token | 本节点同时 fetch 新 ranges、stream 旧 ranges | MOVING -> normal tokens | relocation stream 完成后 `setTokens()` |
| `replace` | 新进程接管 dead endpoint tokens | replacement 节点 bootstrap fetch pending ranges | BOOT_REPLACING 或同地址 hibernate | bootstrap stream 完成并 finish join |
| `rebuild` | 本节点已在 ring 内 | 本节点从其他 replicas fetch 自己负责的 ranges | 不改变 ring ownership | rebuild stream 完成 |
| `assassinate` | dead endpoint 且 removenode 无法推进 | 不恢复 replica count | LEFT | gossip major state change |

边界证据：

- `removeNode()` 遇到 live endpoint 明确要求使用 decommission，见 `src/java/org/apache/cassandra/service/StorageService.java:5699-5701`。
- `getChangedReplicasForLeaving()` 注释同时讨论 graceful decommission 与 restoreReplicaCount/removeNode，见 `src/java/org/apache/cassandra/service/StorageService.java:3770-3779`。
- `move()` 使用 `RangeRelocator` 的 relocation `StreamPlan`，完成后本地 `setTokens()`，见 `src/java/org/apache/cassandra/service/StorageService.java:5583-5608`。
- `rebuild()` 使用 `RangeStreamer` 拉取本地已拥有 ranges，不改变 ring ownership，见 `src/java/org/apache/cassandra/service/StorageService.java:1553-1645`。

## Observability

```text
nodetool netstats
  -> NodeProbe.getOperationMode()
  -> NodeProbe.getStreamStatus()
  -> prints StreamState per operation and per peer session

system_views.streaming
  -> StreamingVirtualTable.data()
  -> StreamManager.getStreamingStates()
  -> StreamingState progress/status/session counters

JMX StreamManager notifications
  -> StreamEventJMXNotifier
  -> STREAM_PREPARED / FILE_PROGRESS / STREAM_COMPLETE / success / failure
```

关键源码：

- `StorageService.getOperationMode()` 和 `isMoving()` 等 mode 查询见 `src/java/org/apache/cassandra/service/StorageService.java:5772-5815`。
- `nodetool netstats` 打印 mode 与 stream sessions，见 `src/java/org/apache/cassandra/tools/nodetool/NetStats.java:45-74`。
- `StreamManager` 注册 `StreamingState` 并跟踪当前/历史 streaming states，见 `src/java/org/apache/cassandra/streaming/StreamManager.java:217-286`。
- `StreamingVirtualTable` 暴露 operation、peers、status、progress、failure/success message 和 sessions，见 `src/java/org/apache/cassandra/db/virtual/StreamingVirtualTable.java:33-103`。
- `StreamingState` 处理 prepared/progress/success/failure 事件并累计 bytes/files，见 `src/java/org/apache/cassandra/streaming/StreamingState.java:228-306`。
- `StreamEventJMXNotifier` 发送 JMX progress 和 completion notifications，见 `src/java/org/apache/cassandra/streaming/management/StreamEventJMXNotifier.java:39-92`。

## 测试锚点

- Replacement：`HostReplacementTest` 覆盖替换 down host、替换 live host 失败和 seed 重启后替换，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementTest.java:65-195`。
- Move：分布式 `MoveTest` 执行 `nodetool move`，单元 `MoveTest`/`MoveTransientTest` 覆盖 pending ranges 与 transient fetch/stream 计算，见 `test/distributed/org/apache/cassandra/distributed/test/MoveTest.java:49-91`、`test/unit/org/apache/cassandra/service/MoveTest.java:208-337`、`test/unit/org/apache/cassandra/service/MoveTransientTest.java:171-305`。
- Removenode：`RemoveTest` 覆盖异常 host id 和 replication done 完成，见 `test/unit/org/apache/cassandra/service/RemoveTest.java:108-179`。
- Rebuild：`RebuildStreamingTest` 覆盖 rebuild streaming 和 streaming virtual table，见 `test/distributed/org/apache/cassandra/distributed/test/streaming/RebuildStreamingTest.java:43-85`。
- Assassinate：`AssassinateAbruptDownedNodeTest` 覆盖 abrupt down 后 assassinate 边界，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/AssassinateAbruptDownedNodeTest.java:30-58`。
