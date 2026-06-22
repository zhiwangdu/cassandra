# Replication Placement And Pending Range Matrix

## 范围

本文补齐 `research/module-consistency-replication.md`、`research/module-consistency-replication-deep-dive.md` 和 `research/module-consistency-replication-third-round.md` 之外的 Replication 本体源码矩阵，聚焦四类合同：

- keyspace replication 参数解析、strategy class resolution 和 RF/transient RF 校验。
- `SimpleStrategy` 与 `NetworkTopologyStrategy` 的 natural replica placement、rack/DC 分散、full/transient replica 标记。
- `TokenMetadata` pending range 对 leave/bootstrap/move/replace 的保守计算，以及 `PendingRangeCalculatorService` 的异步触发。
- `ReplicaPlans`、`StorageProxy` 和 `StorageService` 如何把 natural/pending replicas 暴露给 read/write/MV/LWT/JMX/nodetool 路径。

本文不重复 CL guardrail、dynamic snitch score、repair/streaming transient sync direction 的细节；这些由 `research/module-consistency-guardrail-profiles.md`、`research/module-dynamic-snitch-topology-regression.md` 和 `research/module-repair-streaming-transient-fault-coverage.md` 覆盖。

## 场景矩阵

| 场景 ID | 源码合同 | 测试/缺口 |
|---|---|---|
| `replication_params_strategy_resolution_contract` | `ReplicationParams.fromMapWithDefaults()` 移除 `class`、解析 strategy class，并调用 `AbstractReplicationStrategy.prepareReplicationStrategyOptions()`；`KeyspaceMetadata.createReplicationStrategy()` 用当前 `TokenMetadata` 和 endpoint snitch 构造 strategy。见 `src/java/org/apache/cassandra/schema/ReplicationParams.java:86-94`、`src/java/org/apache/cassandra/schema/KeyspaceMetadata.java:355-361`。 | schema/DDL 测试通过 CREATE/ALTER KEYSPACE 间接覆盖；本矩阵要求 checker 保护解析入口。 |
| `replication_factor_transient_validation_contract` | `ReplicationFactor.fromString()` 支持 `N` 与 `N/T`；`validate()` 禁止负 RF、transient >= total、未启用 transient、多 token 和 mixed-version <4.0 transient。见 `src/java/org/apache/cassandra/locator/ReplicationFactor.java:62-83`、`src/java/org/apache/cassandra/locator/ReplicationFactor.java:110-118`。 | `test/unit/org/apache/cassandra/locator/ReplicationFactorTest.java:31-97` 覆盖 parse/failure/round-trip。 |
| `simple_strategy_ring_replica_contract` | `SimpleStrategy.calculateNaturalReplicas()` 在 sorted token ring 上从 first token 开始顺序选不重复 endpoint，并用 `replicas.size() < rf.fullReplicas` 标记 full/transient。见 `src/java/org/apache/cassandra/locator/SimpleStrategy.java:59-82`。 | `SimpleStrategyTest` 覆盖 endpoint 选择、pending ranges 与 RF warning；checker 固定缺少 `replication_factor` 的异常文本。 |
| `nts_dc_rack_replica_contract` | `NetworkTopologyStrategy` 为每个 DC 建 `DatacenterEndpoints`，按 DC/RF/rack count/node count 分配 replicas；rack 不足时允许有限 repeat，endpoint 不重复。见 `src/java/org/apache/cassandra/locator/NetworkTopologyStrategy.java:115-145`、`src/java/org/apache/cassandra/locator/NetworkTopologyStrategy.java:179-225`。 | `NetworkTopologyStrategyTest` 覆盖 per-DC RF、rack distribution、transient placement、invalid `replication_factor` option 和 RF>nodes warning。 |
| `nts_rf_auto_expand_validation_contract` | NTS `prepareOptions()` 可把 `replication_factor` 展开到当前 valid DC，保留 previous DC options，并删除 RF 0 的 DC；构造/validate 阶段禁止 `replication_factor` 原样进入 NTS options。见 `src/java/org/apache/cassandra/locator/NetworkTopologyStrategy.java:271-303`、`src/java/org/apache/cassandra/locator/NetworkTopologyStrategy.java:329-337`。 | `NetworkTopologyTest.noWarningForNetworkTopologyStategyConfigOnRestart` 防止重启时把合法远端 DC option 当 unrecognized。 |
| `replica_cache_range_map_contract` | `AbstractReplicationStrategy.getNaturalReplicas()` 用 `TokenMetadata` ring version 和 `cachedOnlyTokenMap()` 缓存 natural replicas；`getAddressReplicas()` / `getRangeAddresses()` 从 token ring 反推 endpoint->ranges 和 range->endpoints。见 `src/java/org/apache/cassandra/locator/AbstractReplicationStrategy.java:93-108`、`src/java/org/apache/cassandra/locator/AbstractReplicationStrategy.java:221-273`。 | `ReplicationStrategyEndpointCacheTest` 和 `StorageServiceServerTest` 覆盖 cache/range map/primary range 语义。 |
| `pending_range_leave_bootstrap_move_contract` | `TokenMetadata.calculatePendingRanges()` 对 leave 先移除所有 leaving endpoints，对 bootstrap 逐一加入 cloned metadata，对 move 同时考虑 move 前后 affected replicas，宁可多写 pending 也不漏写。见 `src/java/org/apache/cassandra/locator/TokenMetadata.java:832-855`、`src/java/org/apache/cassandra/locator/TokenMetadata.java:920-1023`。 | `PendingRangesTest.calculatePendingRangesForConcurrentReplacements()` 覆盖 concurrent replacement regression；`MoveTest`、`LeaveAndBootstrapTest` 覆盖 move/leave/bootstrap pending ranges。 |
| `pending_range_service_async_contract` | `PendingRangeCalculatorService` 用 JMX internal sequential executor 和 at-least-once trigger，只对 distributed keyspaces 重新计算 pending ranges，并提供 `blockUntilFinished()` 给测试/拓扑操作同步。见 `src/java/org/apache/cassandra/service/PendingRangeCalculatorService.java:45-90`。 | `GossipTest`、`ReadRepairTest`、`PendingWritesTest` 和 host replacement tests 显式调用 update/block。 |
| `replica_plan_write_pending_contract` | `ReplicaPlans.forWrite()` 从 `ReplicaLayout.ForTokenWrite` 拆出 live/pending/all/contacts，先 `assureSufficientLiveReplicasForWrite()` 再构造 `ReplicaPlan.ForWrite`；`writeNormal` 总是 contact pending replicas，并在 transient 模式下保证 full/pending 优先。见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:463-536`。 | `ReplicaPlansTest.testWriteEachQuorum()` 覆盖 EACH_QUORUM write with full/transient contacts；`WriteResponseHandlerTransientTest` 覆盖 transient write handler。 |
| `replica_plan_read_each_quorum_contract` | `ReplicaPlans.forRead()` 和 `forRangeRead()` 从 live natural replicas 生成 candidates/contacts；`EACH_QUORUM` + NTS 走 per-DC read contact counter，且不做 speculation。见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:670-748`。 | `AssureSufficientLiveNodesTest` 覆盖 DC add/remove/RF increase race 下 read/write 不应误判 unavailable。 |
| `replica_plan_lwt_pending_boundary` | Paxos write plan 包含 pending replicas，但如果 pending endpoints 超过一个则拒绝 LWT，避免多 range movement 下线性化参与者不稳定。见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:616-646`。 | 现有 coverage 主要在 Paxos/repair 文档中记录；仍缺专门多 pending LWT direct-fault test。 |
| `materialized_view_pending_write_contract` | `StorageProxy.mutateMV()` 在 local paired endpoint 情况下只有 pending replicas 为空才直接本地 apply；有 pending replicas 时降为普通 write，把 view mutation 发给 pending endpoint。见 `src/java/org/apache/cassandra/service/StorageProxy.java:1043-1089`。 | `PendingWritesTest` 覆盖 bootstrap/pending writes 不丢行；repair+MV correctness 仍在 gap 矩阵中。 |
| `storage_service_replica_observability_contract` | `StorageService.getLocalAndPendingRanges()` 合并 local natural ranges 与 pending ranges；MBean 提供 pending range map、range-to-address map 和 natural endpoints。见 `src/java/org/apache/cassandra/service/StorageService.java:435-443`、`src/java/org/apache/cassandra/service/StorageService.java:2520-2548`、`src/java/org/apache/cassandra/service/StorageService.java:5145-5171`。 | `StorageServiceServerTest` 覆盖 primary/local range 输出；operator 侧仍需把 pending range/natural endpoint 输出接入更多 CLI assertions。 |
| `replication_existing_test_baseline` | Unit tests 覆盖 RF parser、strategy placement、endpoint cache、pending range、ReplicaPlan read/write/live node assurance 和 StorageService range output；distributed tests 覆盖 pending writes、NTS restart warning、DC expansion/system_auth 和 topology movement。 | checker 保护这些测试文件仍存在且包含关键断言。 |
| `replication_pending_distributed_gap` | 当前 coverage 仍偏 unit 和 narrow distributed：缺跨 DC replacement + pending ranges + CL/EACH_QUORUM read/write 的组合 fault test，缺 multi-pending LWT direct-fault test，缺 JMX pending range/natural endpoint CLI 断言。 | 保留 gap，避免把 source-only checker 误读成运行时覆盖完成。 |

## 设计目标

- 把 keyspace replication CQL map 转成可缓存、可校验、可观测的 replica placement 规则。
- 在不引入全局事务的前提下，让 range movement 期间的写路径保守 contact pending endpoints，优先保证不漏写。
- 在 NTS 下按 DC 和 rack 尽量分散 replicas，同时允许 node/rack 不足时退化为实际可用 replica set。
- 支持 transient replication 的 full/transient replica 标记，但把 transient 约束提前到 RF parse、strategy validation 和 ReplicaPlan selection。
- 给运维提供 `StorageService`/MBean 的 natural/pending/range map 可见性，支撑 bootstrap、decommission、move、replace 的排障。

## 设计取舍

- `AbstractReplicationStrategy.getNaturalReplicas()` 用 ring version cache 提升读写路径性能；cache miss 时读取 `cachedOnlyTokenMap()`，不带 pending ranges。pending 只在 write layout/TokenMetadata 查询时合并，避免 natural replica cache 被拓扑过渡态污染。
- pending range 计算明确选择“多写优于漏写”：leave 先假设所有 leaving 节点离开，bootstrap/move 逐个 clone 计算最大可能范围。这会放大短期 pending range，但保证 range movement 中 mutation/MV 写不丢。
- `NetworkTopologyStrategy.prepareOptions()` 允许 `replication_factor` 自动展开到 DC，是运维便利性；但 strategy 构造和 validate 阶段严禁 `replication_factor` 原样存在，避免 NTS runtime 语义不清。
- `ReplicaPlans.writeNormal` contact pending replicas even when pending is transient，是为了完成 move 后仍满足用户看到的 write promise。
- LWT 在多 pending endpoint 时直接拒绝，是把线性化风险暴露成 unavailable，而不是让 Paxos 在不稳定 participant set 上继续。

## 核心类

| 类 | 作用 |
|---|---|
| `ReplicationParams` | CQL/schema replication map 的 immutable 表示，解析 class/options 并调用 strategy-specific prepare hook。 |
| `KeyspaceMetadata` | keyspace metadata 中创建 runtime replication strategy 的入口。 |
| `AbstractReplicationStrategy` | 所有 strategy 的 natural replica cache、range map、pending address range 和 response handler 选择基类。 |
| `SimpleStrategy` | 单 ring 顺序 RF placement，不感知 DC/rack。 |
| `NetworkTopologyStrategy` | DC/rack-aware placement，支持 RF auto-expansion 和 per-DC RF warning。 |
| `ReplicationFactor` | full/transient RF parse、validation 和 parseable string 表示。 |
| `TokenMetadata` | token->endpoint、topology、pending ranges 和 range movement state 的事实来源。 |
| `PendingRangeCalculatorService` | 异步重新计算所有 distributed keyspaces 的 pending ranges。 |
| `ReplicaPlans` | coordinator read/write/LWT/MV/read-repair contact set 构造和 CL availability gate。 |
| `StorageService` | local/pending/range/natural endpoint 运维可见性和拓扑操作入口。 |

## 核心接口与数据结构

- `AbstractReplicationStrategy.calculateNaturalReplicas(Token, TokenMetadata)`：strategy-specific placement contract，返回 `EndpointsForRange`。
- `ReplicationFactor.fromString(String)`：解析 `3` 或 `3/1`，输出 `allReplicas/fullReplicas/transientReplicas()`。
- `TokenMetadata.getPendingRangesMM(String)` / `getPendingRanges(String, InetAddressAndPort)`：range->pending endpoints 和 endpoint->pending ranges 的双向视图。
- `ReplicaLayout.ForTokenWrite`：把 natural 与 pending replicas 合并为 write layout，供 `ReplicaPlans.forWrite()` 过滤 live/contacts。
- `ReplicaPlan.ForWrite`：保存 pending、liveAndDown、live、contacts，是 write response handler 和 hint/MV/Paxos 的共享输入。
- `EndpointsForRange` / `EndpointsForToken`：保留 replica order，first replica 的 primary range 语义会被 repair/size estimate 依赖。
- `RangesByEndpoint` / `EndpointsByRange` / `RangesAtEndpoint`：StorageService/JMX/repair/streaming 的 range ownership 交换格式。

## 生命周期与调用链

Keyspace replication params：

```text
CREATE/ALTER KEYSPACE replication map
  -> ReplicationParams.fromMapWithDefaults()
  -> AbstractReplicationStrategy.getClass()
  -> AbstractReplicationStrategy.prepareReplicationStrategyOptions()
  -> KeyspaceMetadata.validate()
  -> ReplicationParams.validate()
  -> AbstractReplicationStrategy.validateReplicationStrategy()
  -> KeyspaceMetadata.createReplicationStrategy()
```

Natural replica placement：

```text
Mutation/read key token
  -> Keyspace.getReplicationStrategy()
  -> AbstractReplicationStrategy.getNaturalReplicas()
  -> ring-version cache lookup
  -> SimpleStrategy.calculateNaturalReplicas()
     or NetworkTopologyStrategy.calculateNaturalReplicas()
  -> EndpointsForToken / EndpointsForRange
```

Pending range recalculation：

```text
gossip/topology/schema state change
  -> PendingRangeCalculatorService.update()
  -> at-least-once sequential executor
  -> Schema.instance.distributedKeyspaces()
  -> TokenMetadata.calculatePendingRanges(strategy, keyspace)
  -> leave/bootstrap/move conservative PendingRangeMaps
```

Write coordinator use：

```text
StorageProxy.performWrite / MV / Paxos
  -> ReplicaLayout.forTokenWriteLiveAndDown()
  -> ReplicaPlans.forWrite()
  -> selector writeAll/writeNormal/writeReadRepair
  -> assureSufficientLiveReplicasForWrite()
  -> AbstractReplicationStrategy.getWriteResponseHandler()
  -> local mutation / messaging / hints / pending endpoint contact
```

Read coordinator use：

```text
StorageProxy read command
  -> ReplicaPlans.forRead() or forRangeRead()
  -> ReplicaLayout.forTokenReadLiveSorted()
  -> candidatesForRead()
  -> contactForRead()
  -> EACH_QUORUM per-DC selection or blockFor(+speculation)
  -> ReadCallback / RangeCommandIterator
```

Operator visibility:

```text
nodetool/JMX caller
  -> StorageServiceMBean
  -> StorageService.getPendingRangeToEndpointWithPortMap()
  -> TokenMetadata.getPendingRangesMM()
  -> StorageService.getNaturalEndpointsWithPort()
  -> AbstractReplicationStrategy.getNaturalReplicasForToken()
```

## 配置项

- `replication = {'class': 'SimpleStrategy', 'replication_factor': 'N'}`：SimpleStrategy 必填；缺失会抛 `SimpleStrategy requires a replication_factor strategy option.`。
- `replication = {'class': 'NetworkTopologyStrategy', '<dc>': 'N[/T]'}`：NTS runtime options 必须是 DC 名到 RF，不能保留 `replication_factor`。
- `replication_factor` auto-expansion：NTS `prepareOptions()` 可把空 options 或显式 `replication_factor` 展开到 `Datacenters.getValidDatacenters()`。
- `DatabaseDescriptor.getDefaultKeyspaceRF()`：SimpleStrategy/NTS prepareOptions 在省略 RF 时的默认来源。
- `DatabaseDescriptor.isTransientReplicationEnabled()` 与 `DatabaseDescriptor.getNumTokens()`：transient RF validation gate。
- guardrails：`Guardrails.minimumReplicationFactor`、`Guardrails.maximumReplicationFactor` 在 Simple/NTS `maybeWarnOnOptions()` 中执行。

## Metrics、日志与诊断事件

- Replication placement 本身没有专属 Dropwizard metrics；运行时风险主要反映在 coordinator read/write unavailable/timeout、hint/backlog、repair/streaming 和 pending range 观测上。
- `SimpleStrategy` 和 `NetworkTopologyStrategy` 在 RF 大于 node count 时通过 `ClientWarn` 和 logger warn 暴露。
- `NetworkTopologyStrategy.validateExpectedOptions()` 记录 configured datacenter replicas。
- `TokenMetadata.calculatePendingRanges()` 在 debug/trace 日志中记录 pending range calculation start/end 和 calculated ranges。
- `PendingRangeCalculatorServiceDiagnostics` 与 `TokenMetadataDiagnostics` 是 diagnostic event 入口，相关事件 catalog 已在 `research/module-diagnostic-events-catalog.md` 覆盖。

## 运维关注点

- 多 DC keyspace 使用 NTS 时，确认所有 active DC 都显式配置 RF；`system_auth` 尤其需要在 DC expansion 后 ALTER + repair。
- bootstrap/decommission/move/replace 期间，pending ranges 可能被保守放大；看 write timeout/unavailable 时要同时查 natural endpoints 和 pending range map。
- LWT 在多个 pending endpoints 时可能直接 unavailable；拓扑操作窗口内应避免重负载 LWT 或串行化 range movement。
- RF 大于实际 node count 会产生 warning，但不一定阻止创建；生产要用 min/max RF guardrail 把 warning 升级为治理策略。
- `SimpleStrategy` 不感知 DC/rack，多 DC 生产 keyspace 不应使用，除非明确是测试/临时场景。

## 性能瓶颈

- Natural replica cache miss 会重新计算 placement；频繁 ring version 变化会增加 coordinator CPU 和 cache churn。
- NTS placement 每次 scan ring 直到所有 DC 填满，large vnode + many DC 场景下 cache 命中很重要。
- Pending range 计算是重操作但只在 topology state change 时执行；连续 gossip/topology 更新由 at-least-once trigger 合并。
- Pending endpoint contact 会增加 write fanout，尤其 transient RF、MV 写和 topology movement 重叠时更明显。
- `StorageService.getRangeToAddressMap()` / pending range map 是运维/低频路径，不应放在请求热路径。

## 常见故障

- CREATE/ALTER KEYSPACE 忘记 SimpleStrategy `replication_factor`：strategy 构造阶段抛 configuration exception。
- NTS 传入 `replication_factor` 未经 prepare 展开：构造或 validate 阶段抛 `replication_factor should not appear...`。
- transient RF 在未启用 transient replication、多 token 或 mixed-version <4.0 环境：RF parse/validate 失败。
- DC expansion 后旧 schema/新 schema 并发：read/write `AssureSufficientLiveNodesTest` 覆盖 race 不应错误 unavailable，但实际数据修复仍需要 repair。
- range movement 中 MV mutation paired endpoint 不存在或 pending endpoint 存在：写入 local batchlog 或 ordinary write；排障要看 `StorageProxy` MV warning 与 pending ranges。
- JMX/nodetool 看到 pending range 空但写仍异常：确认 `PendingRangeCalculatorService.blockUntilFinished()` 是否已完成，尤其测试或运维脚本中手动注入 topology state 时。

## 测试用例索引

| 测试 | 覆盖 |
|---|---|
| `test/unit/org/apache/cassandra/locator/ReplicationFactorTest.java` | RF parse、transient RF failure 和 round-trip。 |
| `test/unit/org/apache/cassandra/locator/SimpleStrategyTest.java` | SimpleStrategy endpoint selection、pending ranges、RF warning 和 missing option。 |
| `test/unit/org/apache/cassandra/locator/NetworkTopologyStrategyTest.java` | NTS per-DC RF、rack spread、transient placement、invalid option 和 RF warning。 |
| `test/unit/org/apache/cassandra/locator/PendingRangesTest.java` | concurrent replacement、leave/bootstrap/move pending range correctness。 |
| `test/unit/org/apache/cassandra/locator/ReplicaPlansTest.java` | EACH_QUORUM write contact set、full/transient selection。 |
| `test/unit/org/apache/cassandra/locator/AssureSufficientLiveNodesTest.java` | DC add/remove/RF increase race 下 read/write availability gate。 |
| `test/unit/org/apache/cassandra/service/StorageServiceServerTest.java` | primary range、local range 和 strategy range output。 |
| `test/distributed/org/apache/cassandra/distributed/test/ring/PendingWritesTest.java` | bootstrap/pending writes 不丢失数据。 |
| `test/distributed/org/apache/cassandra/distributed/test/NetworkTopologyTest.java` | NTS DC option 重启 warning 回归。 |
| `test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java` | system_auth DC expansion ALTER + repair 运维路径。 |

## 后续缺口

- `replication_pending_distributed_gap`：补跨 DC replacement + pending ranges + EACH_QUORUM read/write 的组合 distributed fault test。
- 补多 pending endpoint 下 LWT direct-fault test，验证 `ReplicaPlans.forPaxos()` 的 unavailable 文本和参与者计数。
- 给 `StorageServiceMBean.getPendingRangeToEndpointWithPortMap()`、`getNaturalEndpointsWithPort()` 增加 nodetool/JMX CLI 层断言。
- 与 repair/streaming 工作合并后，补 transient RF + pending movement + stream validation 的端到端 dtest。
