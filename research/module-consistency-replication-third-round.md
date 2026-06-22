# Consistency/Replication Third Round

## 范围

本文补充 `research/module-consistency-replication.md` 与 `research/module-consistency-replication-deep-dive.md` 的第三轮源码研究，覆盖四个缺口：

- multi-DC consistency level policy/guardrail 操作矩阵。
- transient repair、streaming、pending range 的 failure-injection 矩阵。
- dynamic snitch 在 topology change 下的排序漂移 runbook。
- `system_auth`、`system_traces`、`system_distributed` 与用户 keyspace RF 操作差异。

不重复第一轮 `ReplicaPlan` 基础结构，也不重新展开 repair/streaming 的协议细节；本文只记录一致性、复制和运维决策会直接依赖的边界。

第四轮 transient repair/streaming source/test 覆盖、generic failure-injection 与 distributed 缺口已单独展开在 `research/module-repair-streaming-transient-fault-coverage.md`，并由 `research/tools/check-repair-streaming-transient-coverage-drift.py` 做 source-only drift check。

## 设计目标

- 将 `ConsistencyLevel.blockFor()`、local quorum、each quorum 和 pending endpoint 加权转成可操作的多 DC CL 策略表。核心计算见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:91-191`。
- 把 read/write CL guardrail、SimpleStrategy guardrail、min/max replication factor guardrail 放到同一个治理面看待，避免只禁 CL 却允许危险 RF。guardrail 定义见 `src/java/org/apache/cassandra/db/guardrails/Guardrails.java:285`、`src/java/org/apache/cassandra/db/guardrails/Guardrails.java:310`、`src/java/org/apache/cassandra/db/guardrails/Guardrails.java:469`。
- 明确 transient repair 的方向性：full replica 可以接收补数，transient replica 不应成为修复流入目标；standard 与 optimised syncing 都在源码里排除向 transient streaming。见 `src/java/org/apache/cassandra/repair/RepairJob.java:330-348`、`src/java/org/apache/cassandra/repair/RepairJob.java:443-465`。
- 将 repair validation、stream prepare 和 mutation 接收的 out-of-range 检查统一到 pending/range movement 故障排查。通用 range 检查在 `src/java/org/apache/cassandra/dht/OwnedRanges.java:72-90`。
- 把 dynamic snitch score、severity、badness threshold 与 decommission 拓扑变化放到一个 runbook。排序分支见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:175-228`，decommission 回归测试见 `test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidTimeouts.java:80-135`。
- 区分 replicated system keyspace 和 local/virtual system keyspace：`system_auth`、`system_traces`、`system_distributed` 是 replicated system keyspaces，见 `src/java/org/apache/cassandra/schema/SchemaConstants.java:58-68`。

## 解决的问题

multi-DC CL policy matrix：

| CL | 源码语义 | 多 DC 风险 | guardrail 候选 |
|---|---|---|---|
| `ONE` | 等 1 个任意 replica，`blockFor()` 返回 1，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:137-141` | read/write 可能跨 DC，取决于 replica ordering 和 coordinator 位置 | 跨 DC 应用通常优先用 `LOCAL_ONE`；可对普通 `ONE` warn |
| `LOCAL_ONE` | 等本 DC 1 个 replica，local CL 不计远端响应，见 `src/java/org/apache/cassandra/service/DatacenterWriteResponseHandler.java:35-67` | 最弱本地保证，跨 DC 灾备不可见 | 低价值读可允许，关键写可 warn |
| `QUORUM` | 使用全 keyspace RF quorum，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:146-148` | NTS 多 DC 下可能要求远端参与，跨 DC 故障会放大 timeout | 单区域应用常 disallow/warn，改用 `LOCAL_QUORUM` |
| `LOCAL_QUORUM` | 使用本 DC RF quorum，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:151-153` | 远端 DC 数据延迟，跨 DC failover 前需要确认修复/同步 | 多 DC 在线业务默认候选 |
| `EACH_QUORUM` | 读写都要求每个 DC local quorum；写 handler 每 DC 建 counter，见 `src/java/org/apache/cassandra/service/DatacenterSyncWriteResponseHandler.java:56-76` | 任一 DC 不足都会失败，tail latency 最高 | 只给强跨 DC 写策略保留，常 disallow 读 |
| `ALL` | 等所有 replicas，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:149-150` | 任一 replica 慢/不可达即失败 | 多数生产请求 disallow 或强 warn |
| `ANY` | 只支持写，读会直接拒绝，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:208-214` | 可能只落本地 hint，读后写保证最弱 | 仅特殊写入可允许，常 disallow |
| `SERIAL` / `LOCAL_SERIAL` | 普通写非法，只能用于 conditional path；normal+serial CL 一起进写 guardrail，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:217-224`、`src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:491-497` | LWT 的跨 DC Paxos 与本地 Paxos 故障域不同 | 不使用 LWT 的 workload 可 disallow serial CL |

transient/pending failure matrix：

| 场景 | 源码边界 | 预期故障信号 |
|---|---|---|
| local full vs remote transient repair diff | local full 可 request，remote transient 不接收 transfer，见 `src/java/org/apache/cassandra/repair/RepairJob.java:330-340` | 单向 pull，`LocalSyncTask` in=1/out=0 测试见 `test/unit/org/apache/cassandra/repair/LocalSyncTaskTest.java:196-213` |
| local transient vs remote full repair diff | local transient 不 request，可向 full transfer；pull repair 下可能无任务，见 `src/java/org/apache/cassandra/repair/RepairJob.java:330-340` | `requestRanges=false` 或任务为空，覆盖见 `test/unit/org/apache/cassandra/repair/RepairJobTest.java:420-454` |
| remote transient pair | remote sync 使用 asymmetric task，只从 transient stream out，不 stream into transient，见 `src/java/org/apache/cassandra/repair/RepairJob.java:342-348` | `AsymmetricRemoteSyncTask` 覆盖见 `test/unit/org/apache/cassandra/repair/RepairJobTest.java:532-575` |
| optimised syncing | 目标 address 是 transient 时直接跳过，见 `src/java/org/apache/cassandra/repair/RepairJob.java:443-445` | 没有向 transient 的 target task |
| repair validation out of owned ranges | `RepairMessageVerbHandler.acceptMessage()` 用 local normalized ranges 校验 validation request，见 `src/java/org/apache/cassandra/repair/RepairMessageVerbHandler.java:452-465` | rejection on 时 validation response failure；off 时成功但 invalid-token metric 增加，测试见 `test/unit/org/apache/cassandra/repair/RepairMessageVerbHandlerOutOfRangeTest.java:166-222` |
| stream request out of owned ranges | `StreamSession.processStreamRequests()` 用 local normalized ranges 校验 full+transient request，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1008-1031` | `StreamRequestOutOfTokenRangeException` 或 invalid-token metric，测试见 `test/unit/org/apache/cassandra/streaming/StreamSessionOwnedRangesTest.java:110-176` |
| mutation during range movement | mutation receiver 用 `isEndpointValidForWrite()` 检查 neither owned nor pending token，见 `src/java/org/apache/cassandra/db/AbstractMutationVerbHandler.java:49-80` | failure response 或 out-of-range write metric |
| LWT with multiple pending endpoints | Paxos write plan 禁止超过一个 pending endpoint，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:630-646` | `UnavailableException` message 指向 pending range movement |

system keyspace RF matrix：

| keyspace | 默认策略/RF | 操作差异 |
|---|---|---|
| `system` / `system_schema` | Local system keyspace，固定 local/virtual 类别，见 `src/java/org/apache/cassandra/schema/SchemaConstants.java:58-64` | 不能按用户 keyspace 方式 ALTER RF |
| `system_views` / `system_virtual_schema` | Virtual system keyspace，属于 virtual table 类别且没有用户可调 RF，见 `src/java/org/apache/cassandra/schema/SchemaConstants.java:62-68` | 不参与用户 keyspace RF 操作；变更应从 virtual keyspace/table provider 入手 |
| `system_auth` | Simple RF 为 `max(cassandra.system_auth.default_rf, default_keyspace_rf)`，默认属性为 1，见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:155-163`、`src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:539` | 加 DC 后必须显式改 NTS 并 repair，否则新 DC 缺 roles |
| `system_traces` | Simple RF 为 `max(cassandra.system_traces.default_rf, default_keyspace_rf)`，默认属性为 2，见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:110-113`、`src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:541` | 测试多节点常改 NTS，生产可按 trace 保留要求调 RF |
| `system_distributed` | Simple RF 为 `max(cassandra.system_distributed.default_rf, default_keyspace_rf)`，默认属性为 3，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:213-228`、`src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:540` | 保存 repair/MV/denylist/autorepair 状态；RF 影响运维元数据可用性 |

## 设计取舍

- local CL 与 global CL 的差异不藏在 response handler 之后，而是通过 `ConsistencyLevel.isDatacenterLocal()` 直接选择 `DatacenterWriteResponseHandler`，见 `src/java/org/apache/cassandra/locator/AbstractReplicationStrategy.java:154-174`。
- pending endpoint 参与写 CL 计算是保守选择：`blockForWrite()` 对 LOCAL CL 只加本 DC pending，对 global/EACH/ALL 加所有 pending，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:172-191`。
- `EACH_QUORUM` read 不做 speculation，且按 DC 扣 quorum counter；源码注释仍承认 `{LOCAL,EACH}_QUORUM` 管理不一致，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:659-685`。
- transient repair 不双向同步所有差异，而是保证 full replica 得到完整数据、transient replica 不被当成 full target。标准 sync 方向在 `src/java/org/apache/cassandra/repair/RepairJob.java:330-348`。
- out-of-range 检查可配置为 log-only 或 reject；这是为了在升级/拓扑变更期间先观测再收紧。行为在 `src/java/org/apache/cassandra/dht/OwnedRanges.java:72-90`。
- dynamic snitch 默认保留 subsnitch 顺序，只有 badness 超阈值才切成 score order；`dynamic_snitch_badness_threshold=0` 才纯 score 排序，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:175-228`。
- replicated system keyspace 默认仍是 SimpleStrategy RF，而多 DC 测试 helper 会改 `system_auth` 和 `system_traces` 为 NTS；helper 注释明确默认 under-replicated 会导致 bootstrap source 不足，见 `test/distributed/org/apache/cassandra/distributed/test/TestBaseImpl.java:192-214`。

## 核心类

| 类 | 作用 |
|---|---|
| `ConsistencyLevel` | CL enum、blockFor、local/each quorum、read/write 合法性。见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:35-235` |
| `DatacenterWriteResponseHandler` | LOCAL_* 写只等待本 DC 响应，远端只用于 ideal CL 记录。见 `src/java/org/apache/cassandra/service/DatacenterWriteResponseHandler.java:35-67` |
| `DatacenterSyncWriteResponseHandler` | EACH_QUORUM 写每个 DC 单独建 quorum counter，并把 pending endpoints 加入对应 DC。见 `src/java/org/apache/cassandra/service/DatacenterSyncWriteResponseHandler.java:46-76` |
| `Guardrails` | CL、SimpleStrategy、min/max RF guardrail 定义。见 `src/java/org/apache/cassandra/db/guardrails/Guardrails.java:285`、`src/java/org/apache/cassandra/db/guardrails/Guardrails.java:469` |
| `RepairJob` | 根据 Merkle diff 和 transient predicate 创建 standard/optimised sync tasks。见 `src/java/org/apache/cassandra/repair/RepairJob.java:320-360`、`src/java/org/apache/cassandra/repair/RepairJob.java:404-465` |
| `LocalSyncTask` | 将 request/transfer flags 转成 repair `StreamPlan` requestRanges/transferRanges。见 `src/java/org/apache/cassandra/repair/LocalSyncTask.java:67-103` |
| `OwnedRanges` | 验证 peer request 是否完全落在本地 owned ranges 内，并更新 invalid-token metric。见 `src/java/org/apache/cassandra/dht/OwnedRanges.java:53-90` |
| `StreamSession` | streaming prepare 阶段校验 requested full/transient ranges 是否本地拥有。见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1008-1031` |
| `DynamicEndpointSnitch` | 读取 latency/severity score，按 badness threshold 改写 replica proximity order。见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:48-60` |
| `AuthKeyspace` / `TraceKeyspace` / `SystemDistributedKeyspace` | replicated system keyspace table metadata 和默认 RF。见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:155`、`src/java/org/apache/cassandra/tracing/TraceKeyspace.java:110`、`src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:213` |

## 核心接口

- `Guardrails.readConsistencyLevels.guard()` 与 `Guardrails.writeConsistencyLevels.guard()` 是 CL 策略入口；read 测试覆盖 warn/fail 和 super/system user bypass，见 `test/unit/org/apache/cassandra/db/guardrails/GuardrailReadConsistencyLevelsTest.java:68-118`。
- `Guardrails.simpleStrategyEnabled.ensureEnabled()` 在 CREATE/ALTER KEYSPACE 入口执行，见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateKeyspaceStatement.java:70-87`、`src/java/org/apache/cassandra/cql3/statements/schema/AlterKeyspaceStatement.java:81-92`。
- `ReplicationParams.validate()` 实例化并校验 strategy/RF，见 `src/java/org/apache/cassandra/schema/ReplicationParams.java:74-80`。
- `OwnedRanges.validateRangeRequest()` 是 repair validation 与 streaming request 的共同范围校验接口，见 `src/java/org/apache/cassandra/dht/OwnedRanges.java:72-90`。
- `StorageService.getNormalizedLocalRanges()` 通过 keyspace replication strategy 生成本地 owned range 视图，见 `src/java/org/apache/cassandra/service/StorageService.java:447-455`。
- `DynamicEndpointSnitch.sortedByProximity()` 是 read/range read replica ordering 的 snitch 接口，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:175-180`。
- `StorageService.repair()` 是 system_auth DC expansion test 触发 repair 的入口，测试调用见 `test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java:168-184`。

## 核心数据结构

- `ConsistencyLevel` enum code 同时服务 binary protocol 与内部策略，包含 `ANY/ONE/TWO/THREE/QUORUM/ALL/LOCAL_QUORUM/EACH_QUORUM/SERIAL/LOCAL_SERIAL/LOCAL_ONE/NODE_LOCAL`，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:35-48`。
- `ObjectIntHashMap<String>` 保存 each quorum per-DC counter；read 由 `eachQuorumForRead()` 建，write 由 `eachQuorumForWrite()` 加 pending，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:108-130`。
- `ReplicaPlan.ForWrite.pending()` 保存 pending replicas；EACH_QUORUM write handler 遍历 pending 并按 snitch DC 增加 response 需求，见 `src/java/org/apache/cassandra/service/DatacenterSyncWriteResponseHandler.java:70-75`。
- `SyncTask` 保存 repair diff ranges 和 primary/peer pair；非空 diff 会启动 streaming repair，见 `src/java/org/apache/cassandra/repair/SyncTask.java:57-96`。
- `StreamRequest` 中 full 与 transient ranges 在 receiver 端合并后校验，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1020-1024`。
- `DynamicEndpointSnitch.scores` 是 endpoint 到 score 的快照 map，score 由 median latency/max latency + severity 生成，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:303-323`。
- `SchemaConstants.REPLICATED_SYSTEM_KEYSPACE_NAMES` 保存 replicated system keyspace 集合，见 `src/java/org/apache/cassandra/schema/SchemaConstants.java:66-68`。

## 生命周期

multi-DC CL governance：

```text
cassandra.yaml / JMX guardrail config
  -> Guardrails read/write consistency sets
  -> SELECT: SelectStatement validates read CL and guards it
  -> INSERT/UPDATE/DELETE/BATCH: normal CL + serial CL guarded together
  -> ReplicaPlans / response handler enforce local/global/each semantics
  -> warnings, failures, timeout/unavailable metrics expose effect
```

transient repair and pending range failure flow：

```text
Repair validation
  -> RepairMessageVerbHandler.acceptMessage()
  -> StorageService.getNormalizedRanges(keyspace, local)
  -> OwnedRanges.validateRangeRequest()
  -> reject, log-only, or accept

Merkle diff
  -> RepairJob.create*SyncTasks()
  -> choose LocalSyncTask / AsymmetricRemoteSyncTask / SymmetricRemoteSyncTask
  -> skip streaming into transient replicas
  -> LocalSyncTask.createStreamPlan()
  -> StreamPlan requestRanges / transferRanges

Streaming prepare
  -> StreamSession.processStreamRequests()
  -> StorageService.getNormalizedLocalRanges(keyspace)
  -> OwnedRanges.validateRangeRequest(full + transient)
  -> PREPARE_SYNACK or StreamRequestOutOfTokenRangeException
```

dynamic snitch topology-change runbook：

```text
read latency + gossip severity
  -> DynamicEndpointSnitch.updateScores()
  -> sortedByProximity()
     -> threshold 0: score order
     -> threshold > 0: keep subsnitch order unless badness threshold exceeded
  -> ReplicaLayout read/range candidates
  -> during decommission, severity should push leaving endpoint later
```

system keyspace RF operation：

```text
startup / schema update
  -> AuthKeyspace.metadata() / TraceKeyspace.metadata() / SystemDistributedKeyspace.metadata()
  -> SimpleStrategy RF from default property and default_keyspace_rf
  -> multi-DC expansion requires ALTER KEYSPACE to NTS
  -> repair replicated system keyspace data
  -> only after DC removal can ALTER drop removed DC from NTS options
```

## 调用链

- Read CL guardrail path: `SelectStatement.execute()` -> `ConsistencyLevel.validateForRead()` -> `Guardrails.readConsistencyLevels.guard()`，基础入口已在 `research/module-consistency-replication-deep-dive.md` 引用。
- Write CL guardrail path: `ModificationStatement.execute()` -> build set of normal+serial CL -> `Guardrails.writeConsistencyLevels.guard()`，见 `src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:491-497`。
- CL response handler path: replication strategy `getWriteResponseHandler()` -> LOCAL_* uses `DatacenterWriteResponseHandler` -> EACH_QUORUM with NTS uses `DatacenterSyncWriteResponseHandler` -> otherwise generic handler，见 `src/java/org/apache/cassandra/locator/AbstractReplicationStrategy.java:154-174`。
- EACH_QUORUM read path: `ReplicaPlans.contactForRead()` -> `contactForEachQuorumRead()` -> per-DC counter decrement by snitch DC，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:659-685`。
- SimpleStrategy/RF guardrail path: CREATE/ALTER KEYSPACE validates strategy guardrail -> `ReplicationParams.validate()` -> `AbstractReplicationStrategy.validateReplicationStrategy()`，入口见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateKeyspaceStatement.java:70-87`、`src/java/org/apache/cassandra/schema/ReplicationParams.java:74-80`。
- Repair transient sync path: `RepairJob.createStandardSyncTasks()` -> local full/transient flags -> `LocalSyncTask` or asymmetric/symmetric remote task -> `SyncTask.run()` starts streaming only when diff ranges non-empty，见 `src/java/org/apache/cassandra/repair/RepairJob.java:320-360`、`src/java/org/apache/cassandra/repair/SyncTask.java:78-96`。
- Stream range validation path: `StreamSession.prepareAsync()` -> `processStreamRequests()` -> `OwnedRanges.validateRangeRequest()` -> reject or add transfer ranges，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1008-1031`。
- system_auth DC expansion path: create role in dc1 -> ALTER `system_auth` to NTS dc1 -> bootstrap dc2 -> ALTER NTS dc1+dc2 -> run repair -> role visible in dc2 -> cannot remove active DC from replication -> remove node -> ALTER away removed DC，见 `test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java:122-213`。

## 配置项

| 配置项 | 作用 |
|---|---|
| `read_consistency_levels_warned/disallowed` | read CL warn/fail policy；测试覆盖每个 read CL，见 `test/unit/org/apache/cassandra/db/guardrails/GuardrailReadConsistencyLevelsTest.java:68-89` |
| `write_consistency_levels_warned/disallowed` | write 与 serial CL warn/fail policy；入口见 `src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:491-497` |
| `simple_strategy_enabled` | 禁用用户 CREATE/ALTER 使用 SimpleStrategy；测试覆盖 toggle，见 `test/unit/org/apache/cassandra/db/guardrails/GuardrailSimpleStrategyTest.java:45-88` |
| `minimum_replication_factor_*` | RF 过低 warn/fail；NTS 多 DC 测试覆盖，见 `test/unit/org/apache/cassandra/db/guardrails/GuardrailMinimumReplicationFactorTest.java:174-192` |
| `maximum_replication_factor_*` | RF 过高 warn/fail；NTS 多 DC 测试覆盖，见 `test/unit/org/apache/cassandra/db/guardrails/GuardrailMaximumReplicationFactorTest.java:135-153` |
| `dynamic_snitch` / `dynamic_snitch_badness_threshold` | 是否启用动态排序及 score order 触发阈值；实现见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:58-60`、`src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:175-228` |
| `severity_during_decommission` | decommission 时通过 gossip severity 影响 dynamic snitch ordering；测试设置见 `test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidTimeouts.java:80-83` |
| `cassandra.system_auth.default_rf` | `system_auth` 默认 RF 属性，默认 1，见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:539` |
| `cassandra.system_traces.default_rf` | `system_traces` 默认 RF 属性，默认 2，见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:541` |
| `cassandra.system_distributed.default_rf` | `system_distributed` 默认 RF 属性，默认 3，见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:540` |
| `reject_out_of_token_range_requests` / `log_out_of_token_range_requests` | 控制 owned range validation 是拒绝、记录还是放行；接口见 `src/java/org/apache/cassandra/dht/OwnedRanges.java:72-90` |

## Metrics

- CL guardrail 本身主要通过 client warning/failure 暴露；没有单独的 consistency guardrail meter。读写请求后续仍落到 `ClientRequestMetrics` timeout/unavailable/failure。
- out-of-range repair/streaming request 会增加 `StorageMetrics.totalOpsForInvalidToken`，触发点在 `src/java/org/apache/cassandra/dht/OwnedRanges.java:79-82`；启动阶段走 `startupOpsForInvalidToken`，见 `src/java/org/apache/cassandra/service/StorageService.java:384-387`。
- out-of-range mutation 会增加 keyspace 级 `outOfRangeTokenWrites`，见 `src/java/org/apache/cassandra/db/AbstractMutationVerbHandler.java:52-58`。
- dynamic snitch 暴露 `DynamicEndpointSnitch` MBean scores/update/reset/badness/subsnitch，getter 见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:331-356`。
- repair sync streaming duration 会更新 table metric `repairSyncTime`，见 `src/java/org/apache/cassandra/repair/SyncTask.java:103-107`。
- streaming repair bytes/SSTables metrics 在发送 repair stream 时递增，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1039-1049`。

## 日志

- `OwnedRanges.validateRangeRequest()` 在 logging 开启且存在 unowned ranges 时 warn peer、request type、unowned ranges 和 owned ranges，见 `src/java/org/apache/cassandra/dht/OwnedRanges.java:83-87`。
- `RepairJob` 创建 sync task 时记录 task 数、Merkle response 数和 session id，见 `src/java/org/apache/cassandra/repair/RepairJob.java:358-360`。
- `SyncTask.run()` 对一致/不一致 ranges 记录 info 并打 repair tracing，见 `src/java/org/apache/cassandra/repair/SyncTask.java:82-95`。
- `LocalSyncTask` 记录 streaming repair range 数和 remote endpoint，见 `src/java/org/apache/cassandra/repair/LocalSyncTask.java:111-120`。
- dynamic snitch topology-change 主要通过 MBean scores 和 trace/request failures 排查；decommission test 用 ByteBuddy 断言 severity 非零时 leaving endpoint 应排最后，见 `test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidTimeouts.java:207-223`。
- system_auth expansion test 在关键步骤打 debug 日志，实际生产 runbook 应对 ALTER/repair/decommission 操作保留审计记录，测试流程见 `test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java:139-212`。

## 运维关注点

- 多 DC 在线读写优先用 `LOCAL_QUORUM`/`LOCAL_ONE` 表达本地可用性；普通 `QUORUM` 是 global quorum，不能当成本地 quorum。
- `EACH_QUORUM` 是跨 DC 强保证，不是“更安全的 LOCAL_QUORUM”。一个远端 DC 维护、网络抖动或 pending endpoints 都会让写失败。
- 写 guardrail 会覆盖 serial CL；如果禁了 `SERIAL`/`LOCAL_SERIAL`，LWT 也会受影响，即使 commit CL 是允许的 `LOCAL_QUORUM`。
- pending endpoints 会抬高 `blockForWrite()`；bootstrap/move/decommission 期间的 write timeout 需要先看 pending ranges，而不是只数 natural replicas。
- transient repair 不把 transient replica 当完整目标。repair runbook 要确认“补 full”还是“从 transient 取可用差异”，不能把 transient 和 full SSTable 状态混同。
- out-of-range rejection 建议先 log-only 观测，再切 reject；开启 reject 会让 repair validation/streaming prepare/写入 receiver 更早失败。
- dynamic snitch runbook要同时看 `dynamic_snitch_badness_threshold`、`Scores` MBean、gossip severity 和 topology state；write-heavy workload 可能没有足够 read samples。
- system_auth 加 DC 后必须 ALTER RF 并 repair。`UpdateSystemAuthAfterDCExpansionTest` 明确验证 bootstrap 后新 DC 先看不到 role，repair 后才可见，见 `test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java:160-188`。
- 不能在 active DC 仍存在时把它从 `system_auth` NTS options 中删掉；测试对 active dc1/dc2 删除都期望 ConfigurationException，见 `test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java:190-193`。

## 性能瓶颈

- `ALL`、`EACH_QUORUM`、global `QUORUM` 会把跨 DC tail latency 引入请求关键路径；guardrail 能防误用，但不能降低已经选择的 CL 成本。
- `EACH_QUORUM` pending endpoints 会增加每 DC response counter，topology change 期间写放大和等待数同时上升。
- transient repair 的 one-way sync 减少向 transient 写入，但如果 full replicas 缺数据，repair 仍需要 streaming 补齐 full 数据。
- `OwnedRanges.testRanges()` 会 normalize ranges 并做 coverage 检查，源码注释提示不要在 hot path 随意使用，见 `src/java/org/apache/cassandra/dht/OwnedRanges.java:93-120`。
- dynamic snitch score 更新是周期性的；score/staleness 和 reset interval 会让短暂抖动影响后续 read order。
- system keyspace RF 太低会在 bootstrap/repair/MV/denylist/auth 元数据上产生运维瓶颈；多节点 dtest helper 明确因为 under-replication 会导致 bootstrap streaming source 不足而改 RF，见 `test/distributed/org/apache/cassandra/distributed/test/TestBaseImpl.java:192-195`。

## 常见故障

- read/write 被 guardrail 拒绝：检查 `read_consistency_levels_disallowed`、`write_consistency_levels_disallowed`，并确认请求用户不是 super/system bypass；read 测试见 `test/unit/org/apache/cassandra/db/guardrails/GuardrailReadConsistencyLevelsTest.java:96-118`。
- 多 DC `QUORUM` 超时：源码按全 RF quorum 算，不是 local quorum；改为 `LOCAL_QUORUM` 前需要确认业务跨 DC 一致性要求。
- `EACH_QUORUM` 写在远端 DC 维护期间失败：每 DC quorum counter 必须清零，见 `src/java/org/apache/cassandra/service/DatacenterSyncWriteResponseHandler.java:78-97`。
- repair validation 返回失败但 prepare 成功：prepare 阶段注册 session，validation 阶段才校验 requested ranges；测试覆盖见 `test/unit/org/apache/cassandra/repair/RepairMessageVerbHandlerOutOfRangeTest.java:118-175`。
- stream prepare 抛 `StreamRequestOutOfTokenRangeException`：peer 请求 full/transient ranges 不在本地 owned ranges 内，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1020-1031`。
- LWT during movement 失败并提示 pending range movement：`ReplicaPlans.forPaxosWrite()` 禁止多个 pending endpoints，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:637-646`。
- decommission 后 read 仍优先打 leaving node：检查 dynamic snitch severity 是否传播、scores 是否更新、badness threshold 是否为 0/较低；回归测试步骤见 `test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidTimeouts.java:106-118`。
- 新 DC 登录/授权数据缺失：`system_auth` RF 未扩展或未 repair；扩展测试在 repair 前后分别断言 role absent/present，见 `test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java:160-188`。

## 测试用例

- CL guardrails：`test/unit/org/apache/cassandra/db/guardrails/GuardrailReadConsistencyLevelsTest.java`、`test/unit/org/apache/cassandra/db/guardrails/GuardrailWriteConsistencyLevelsTest.java`、`test/unit/org/apache/cassandra/db/guardrails/GuardrailConsistencyLevelsTester.java`。
- RF guardrails：`test/unit/org/apache/cassandra/db/guardrails/GuardrailSimpleStrategyTest.java`、`test/unit/org/apache/cassandra/db/guardrails/GuardrailMinimumReplicationFactorTest.java`、`test/unit/org/apache/cassandra/db/guardrails/GuardrailMaximumReplicationFactorTest.java`。
- CL/replica planning：`test/unit/org/apache/cassandra/locator/ReplicaPlansTest.java`、`test/unit/org/apache/cassandra/locator/ReplicaLayoutTest.java`、`test/unit/org/apache/cassandra/locator/ReplicationFactorTest.java`、`test/unit/org/apache/cassandra/locator/NetworkTopologyStrategyTest.java`。
- transient repair sync：`test/unit/org/apache/cassandra/repair/RepairJobTest.java`、`test/unit/org/apache/cassandra/repair/LocalSyncTaskTest.java`、`test/unit/org/apache/cassandra/repair/RepairMessageVerbHandlerOutOfRangeTest.java`。
- streaming range ownership：`test/unit/org/apache/cassandra/streaming/StreamSessionOwnedRangesTest.java`、`test/unit/org/apache/cassandra/streaming/StreamSessionTest.java`。
- pending movement/coordination：`test/distributed/org/apache/cassandra/distributed/test/ring/PendingWritesTest.java`、`test/unit/org/apache/cassandra/service/MoveTransientTest.java`、`test/unit/org/apache/cassandra/service/BootstrapTransientTest.java`。
- dynamic snitch topology change：`test/unit/org/apache/cassandra/locator/DynamicEndpointSnitchTest.java`、`test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidTimeouts.java`。
- system keyspace RF operations：`test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java`、`test/distributed/org/apache/cassandra/distributed/test/TestBaseImpl.java`。

## Drift 检查

- `research/tools/check-system-keyspace-rf-drift.py` 从 `src/java/org/apache/cassandra/schema/SchemaConstants.java`、`src/java/org/apache/cassandra/db/SystemKeyspace.java`、`src/java/org/apache/cassandra/schema/SchemaKeyspace.java`、`src/java/org/apache/cassandra/auth/AuthKeyspace.java`、`src/java/org/apache/cassandra/tracing/TraceKeyspace.java`、`src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java`、`src/java/org/apache/cassandra/config/CassandraRelevantProperties.java` 和 `src/java/org/apache/cassandra/schema/KeyspaceParams.java` 校验本章 system keyspace RF 矩阵。
- `research/tools/check-repair-streaming-transient-coverage-drift.py` 校验 transient repair sync、stream request owned-range validation、pending write guard、generic stream failure dtest 和当前 distributed transient fault-test 缺口。
- 设计与运行方式见 `research/module-system-keyspace-rf-drift-checker.md`。
