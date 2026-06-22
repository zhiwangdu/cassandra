# Repair/Streaming Transient Fault Coverage

## 范围

本文补齐 Repair/Streaming 第四轮源码侧缺口：transient repair 的同步方向、stream request 的 full/transient range ownership 校验、pending range 写入保护、transient read/write 与 repair streaming 的交叉边界，以及当前测试树对这些边界的覆盖和缺口。

基础 repair validation、Merkle diff、streaming protocol、consistent incremental repair、auto-repair 和 Netty streaming failure matrix 已分别在 `research/module-repair-streaming.md`、`research/module-repair-streaming-deep-dive.md`、`research/module-repair-streaming-autorepair-netty.md` 展开。本文不重复普通 streaming reader/writer 细节，只记录 transient replication 与故障注入直接相关的源码合同。

## 设计目标

- transient repair 必须保证 full replica 最终能拿到完整数据，同时避免把 transient replica 当成 full target。standard syncing 在本地 full 时允许 request，在远端 full 且非 pull repair 时允许 transfer；两个 transient replica 之间直接跳过，见 `src/java/org/apache/cassandra/repair/RepairJob.java:314-348`。
- optimised syncing 必须把 repair target 限制为 full replica。目标 address 是 transient 时直接跳过，其他节点只创建 fetch 任务，见 `src/java/org/apache/cassandra/repair/RepairJob.java:439-466`。
- local repair sync 要把 request/transfer flags 转成 `StreamPlan` 上的 requestRanges/transferRanges，并保证没有空 sync job。入口见 `src/java/org/apache/cassandra/repair/LocalSyncTask.java:67-103`。
- streaming prepare 必须同时校验 full ranges 和 transient ranges 是否属于本地 owned ranges。`StreamSession.processStreamRequests()` 合并 `req.full` 和 `req.transientReplicas` 后调用 `OwnedRanges.validateRangeRequest()`，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1008-1031`。
- repair validation、stream prepare、mutation receiver 的 out-of-range 行为必须共享同一运维语义：默认 log-only 可观测，开启 reject 后早失败。配置定义见 `src/java/org/apache/cassandra/config/Config.java:788-793`，getter/setter 见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:5303-5320`。
- pending range 写入必须在 bootstrap/move 期间接受即将拥有的 token，避免 topology movement 期间把合法写误判为 out-of-range。receiver 检查见 `src/java/org/apache/cassandra/db/AbstractMutationVerbHandler.java:47-80` 与 `src/java/org/apache/cassandra/service/StorageService.java:5209-5213`。

## 解决的问题

transient repair/streaming fault coverage matrix：

| 场景 ID | 源码合同 | 当前覆盖 |
|---|---|---|
| `transient_standard_sync_direction` | standard sync 跳过 transient-transient，local full request、remote full transfer、remote transient 使用 asymmetric task，见 `src/java/org/apache/cassandra/repair/RepairJob.java:314-348` | `test/unit/org/apache/cassandra/repair/RepairJobTest.java:400-452`、`test/unit/org/apache/cassandra/repair/RepairJobTest.java:532-667` |
| `transient_optimized_sync_no_target` | optimised sync 不 stream 到 transient target，local target 只 fetch，见 `src/java/org/apache/cassandra/repair/RepairJob.java:443-465` | `test/unit/org/apache/cassandra/repair/RepairJobTest.java:737-762` |
| `local_sync_request_transfer_flags` | `LocalSyncTask` 要求 request/transfer 至少一个为 true，并分别创建 request/transfer stream plan，见 `src/java/org/apache/cassandra/repair/LocalSyncTask.java:67-103` | `test/unit/org/apache/cassandra/repair/LocalSyncTaskTest.java:151-231` |
| `repair_validation_owned_range_rejection` | validation request 使用 owned ranges 校验，reject on 时返回 failure，reject off 时成功但增加 invalid-token metric，见 `src/java/org/apache/cassandra/dht/OwnedRanges.java:72-90` | `test/unit/org/apache/cassandra/repair/RepairMessageVerbHandlerOutOfRangeTest.java:154-222` |
| `stream_request_owned_range_rejection` | stream request 合并 full+transient ranges 后校验，reject on 时抛 `StreamRequestOutOfTokenRangeException`，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1020-1031` | `test/unit/org/apache/cassandra/streaming/StreamSessionOwnedRangesTest.java:95-185` |
| `mutation_pending_range_acceptance` | mutation/read-repair receiver 接受 natural 或 pending local range，既不 owned 也不 pending 才失败，见 `src/java/org/apache/cassandra/db/AbstractMutationVerbHandler.java:47-80` | `test/unit/org/apache/cassandra/db/MutationVerbHandlerOutOfRangeTest.java:102-200` |
| `transient_read_full_replica_requirement` | read availability 需要至少一个 full replica；digest request 只发 full，transient 只收 transient data request，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:98-133` 与 `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:127-185` | read-path/unit coverage 在 `research/module-consistency-replication-deep-dive.md` 已索引；本文把它列为 repair 排障前置条件 |
| `pending_bootstrap_write_distribution` | pending range calculator 期间写入应落到 pending node，join 后所有节点 row count 一致，见 `test/distributed/org/apache/cassandra/distributed/test/ring/PendingWritesTest.java:54-106` | distributed coverage，但不是 transient RF |
| `generic_repair_stream_failure_injection` | generic repair streaming failure 必须传播到 nodetool repair failure，并且不触发 disk failure policy/hidden repair exception，见 `test/distributed/org/apache/cassandra/distributed/test/RepairErrorsTest.java:89-170` | distributed generic repair failure |
| `generic_stream_failure_visibility` | stream failure 要进入 WARN log 和 `system_views.streaming.failure_cause`，见 `test/distributed/org/apache/cassandra/distributed/test/streaming/AbstractStreamFailureLogs.java:56-122` | distributed generic streaming failure |
| `distributed_transient_repair_streaming_gap` | 当前 distributed test tree 没有 transient RF `3/1`/`transient_replication_enabled` 与 repair streaming failure injection 的组合 | 只发现 bootstrap available-ranges V2 写入 `transient_ranges`，见 `test/distributed/org/apache/cassandra/distributed/test/ring/BootstrapTest.java:197-217` |

## 设计取舍

- repair sync 选择单向语义而不是在 transient/full 间做对称修复。这样能减少向 transient replica 写入完整数据的风险，但要求测试明确验证 full target 能被补齐，不能只看 task 数。
- `LocalSyncTask` 把 request/transfer 做成两个 boolean，而不是用 enum。好处是能表达 full/full 双向、full<-transient 单向、transient->full 单向；代价是 pull repair、local transient、remote transient 的组合必须靠测试矩阵守住。
- `OwnedRanges` 不直接知道 repair 或 streaming 业务语义，只判断 requested ranges 是否完全被本地 owned ranges 覆盖。这样 repair validation 与 stream prepare 共享行为，但 caller 必须传入正确的 full/transient range 集合。
- out-of-range reject 默认关闭，log 默认开启。升级或 topology movement 期间可以先观测 invalid-token metric，再收紧拒绝策略；代价是 log-only 模式下错误 stream/validation request 会继续执行。
- pending writes 接受 pending range 是 correctness 优先。bootstrap/move 期间它会扩大合法写入集合，但避免新 owner join 后缺少过渡期写入。
- 当前 dtest 覆盖把 generic repair stream failures 和 pending bootstrap writes 分开验证。它能证明 failure propagation 和 pending range 写入各自成立，但不能证明 transient RF + repair stream failure + topology movement 同时成立。

## 核心类

- `RepairJob`：根据 Merkle diff 和 transient predicate 创建 standard/optimised sync task。transient-aware standard sync 见 `src/java/org/apache/cassandra/repair/RepairJob.java:314-348`，optimised sync target gate 见 `src/java/org/apache/cassandra/repair/RepairJob.java:443-466`。
- `LocalSyncTask`：保存 `requestRanges`、`transferRanges`，构造 repair `StreamPlan` 并执行，见 `src/java/org/apache/cassandra/repair/LocalSyncTask.java:57-123`。
- `AsymmetricRemoteSyncTask` / `SymmetricRemoteSyncTask`：分别表达单向 remote stream 与 full/full symmetric remote sync，选择点见 `src/java/org/apache/cassandra/repair/RepairJob.java:342-352`。
- `OwnedRanges`：封装本地 owned ranges，校验 peer request 中的 token ranges，并根据配置 log/reject/increment metric，见 `src/java/org/apache/cassandra/dht/OwnedRanges.java:34-90`。
- `StreamSession`：streaming prepare 期间把 full/transient request ranges 合并，调用 owned-range validation，失败时抛 `StreamRequestOutOfTokenRangeException`，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1008-1031`。
- `AbstractMutationVerbHandler`：mutation/read-repair receiver 的 out-of-range 检查入口，见 `src/java/org/apache/cassandra/db/AbstractMutationVerbHandler.java:47-80`。
- `StorageService`：提供 local replicas、pending ranges、normalized owned ranges 和 write-validity 判断，见 `src/java/org/apache/cassandra/service/StorageService.java:410-455`、`src/java/org/apache/cassandra/service/StorageService.java:5209-5213`。
- `ReplicaPlans`：read 至少需要 full replica，normal write 选择 full natural + pending + 必要 transient，Paxos 禁止多个 pending movement，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:98-133`、`src/java/org/apache/cassandra/locator/ReplicaPlans.java:504-545`、`src/java/org/apache/cassandra/locator/ReplicaPlans.java:637-646`。
- `AbstractReadExecutor`、`ResponseResolver`、`DigestResolver`、`AbstractReadRepair`：transient read request/response/read-repair 的 guard，见 `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:127-185`、`src/java/org/apache/cassandra/service/reads/ResponseResolver.java:60-64`、`src/java/org/apache/cassandra/service/reads/DigestResolver.java:70-101`、`src/java/org/apache/cassandra/service/reads/repair/AbstractReadRepair.java:103-108`。

## 核心接口

- `RepairJob.createStandardSyncTasks()`：测试可见静态方法，输入 Merkle tree responses、local endpoint、transient predicate、incremental/pull repair flag，输出 sync task list，见 `src/java/org/apache/cassandra/repair/RepairJob.java:290-360`。
- `RepairJob.createOptimisedSyncingSyncTasks()`：测试可见静态方法，用 `DifferenceHolder` 和 preferred same-DC filter reduce diff，再跳过 transient target，见 `src/java/org/apache/cassandra/repair/RepairJob.java:416-466`。
- `LocalSyncTask.createStreamPlan()`：测试可见接口，用 request/transfer flags 生成 incoming/outgoing stream plan，见 `src/java/org/apache/cassandra/repair/LocalSyncTask.java:80-103`。
- `OwnedRanges.validateRangeRequest()`：repair validation 和 streaming request 的共享校验接口，见 `src/java/org/apache/cassandra/dht/OwnedRanges.java:72-90`。
- `StorageService.isEndpointValidForWrite()`：mutation/read-repair receiver 判断 natural 或 pending ownership 的接口，见 `src/java/org/apache/cassandra/service/StorageService.java:5209-5213`。
- `ReadCommand.copyAsTransientQuery()` / `copyAsDigestQuery()`：read path 区分 transient data request 与 full digest request 的接口，使用点见 `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:127-185`。

## 核心数据结构

- `TreeResponse`：Merkle validation response，`RepairJob` 两两 diff 后生成 `SyncTask`，使用点见 `src/java/org/apache/cassandra/repair/RepairJob.java:307-318`。
- `SyncTask`：repair sync 的共同父类，保存 endpoint pair、ranges 和 result future；local/remote/asymmetric/symmetric task 都由它承载。
- `StreamPlan(StreamOperation.REPAIR, ..., pendingRepair, previewKind)`：repair streaming plan，`pendingRepair == null` 时 flush before transfer，见 `src/java/org/apache/cassandra/repair/LocalSyncTask.java:85-87`。
- `RangesAtEndpoint`：stream request 中 full ranges 与 transient ranges 的载体；receiver 端用 `RangesAtEndpoint.concat(req.full, req.transientReplicas)` 合并校验，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1020-1024`。
- `OwnedRanges.ownedRanges`：本地 normalized range list，`testRanges()` 再 normalize requested ranges 并做 coverage 检查，见 `src/java/org/apache/cassandra/dht/OwnedRanges.java:45-50`、`src/java/org/apache/cassandra/dht/OwnedRanges.java:93-125`。
- `TokenMetadata.pendingRanges`：pending range movement 的写入保护基础，distributed pending write 测试从 `getPendingRanges(KEYSPACE)` 断言新 node 已进入 pending endpoints，见 `test/distributed/org/apache/cassandra/distributed/test/ring/PendingWritesTest.java:74-83`。

## 生命周期

transient repair sync：

```text
Validation/Merkle tree responses
  -> RepairJob.createStandardSyncTasks()
     -> skip transient-transient pairs
     -> local full: request ranges
     -> remote full and not pull repair: transfer ranges
     -> remote transient/full pair: AsymmetricRemoteSyncTask from transient to full
  -> LocalSyncTask.createStreamPlan()
     -> requestRanges(): incoming stream
     -> transferRanges(): outgoing stream
  -> StreamPlan(StreamOperation.REPAIR)
  -> StreamSession.processStreamRequests()
  -> OwnedRanges.validateRangeRequest(full + transient ranges)
```

optimized transient repair sync：

```text
TreeResponse list
  -> DifferenceHolder
  -> ReduceHelper.reduce(preferSameDCFilter)
  -> for each address
     -> skip if address is transient
     -> local target: LocalSyncTask(request=true, transfer=false)
     -> remote target: AsymmetricRemoteSyncTask(target, fetchFrom)
```

pending/out-of-range receiver flow：

```text
Mutation or read-repair message
  -> AbstractMutationVerbHandler.processMessage()
  -> StorageService.isEndpointValidForWrite(keyspace, token)
     -> replicationStrategy.isTokenInLocalNaturalOrPendingRange(token)
  -> if invalid: metric/log and optional failure response
```

transient read guard flow：

```text
ReplicaPlans.forRead()
  -> assureSufficientLiveReplicasForRead()
     -> blockFor satisfied and at least one full replica
  -> AbstractReadExecutor.executeAsync()
     -> full data requests to initial full replicas
     -> transient data requests to transient replicas
     -> digest requests only to full replicas
  -> ResponseResolver rejects transient digest response
  -> DigestResolver reconciles transient data with full data when present
```

## 调用链

- repair standard path：`RepairSession` receives validation trees -> `RepairJob.createStandardSyncTasks()` -> `LocalSyncTask` / `AsymmetricRemoteSyncTask` / `SymmetricRemoteSyncTask` -> `SyncTask.run()` -> `LocalSyncTask.startSync()` -> `StreamPlan.execute()`。
- repair optimized path：`RepairJob.createOptimisedSyncingSyncTasks()` -> `DifferenceHolder` -> `ReduceHelper.reduce()` -> skip transient targets -> `LocalSyncTask(true,false)` or `AsymmetricRemoteSyncTask`。
- stream request validation path：`StreamSession.prepareAsync()` -> `processStreamRequests()` -> `StorageService.getNormalizedLocalRanges()` -> `OwnedRanges.validateRangeRequest()` -> `addTransferRanges()` or `StreamRequestOutOfTokenRangeException`。
- mutation pending range path：`MutationVerbHandler` / `ReadRepairVerbHandler` -> `AbstractMutationVerbHandler.processMessage()` -> `StorageService.isEndpointValidForWrite()` -> apply mutation or send failure response。
- distributed generic stream failure path：ByteBuddy hook -> `CassandraIncomingFile.read()` / `StreamSession.onInitializationComplete()` failure -> nodetool repair/rebuild failure -> logs/virtual table/metric assertions。

## 配置项

| 配置项 | 默认 | 作用 |
|---|---:|---|
| `transient_replication_enabled` | `false` | 是否允许创建 transient RF keyspace；YAML 标注为 experimental，见 `conf/cassandra.yaml:1994-1996`，runtime getter 见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4267-4274` |
| `log_out_of_token_range_requests` | `true` | out-of-range repair/stream/write 是否 warn log，定义见 `src/java/org/apache/cassandra/config/Config.java:788-793` |
| `reject_out_of_token_range_requests` | `false` | out-of-range repair/stream/write 是否拒绝，定义见 `src/java/org/apache/cassandra/config/Config.java:788-793` |
| `repair_request_timeout` | `120000ms` | repair request timeout，定义见 `src/java/org/apache/cassandra/config/Config.java:162-163` |
| `stream_entire_sstables` | `true` | 是否允许 zero-copy entire SSTable streaming；YAML 注释说明 internode encryption 会自动禁用，见 `conf/cassandra.yaml:1269-1279` |
| `streaming_connections_per_host` | `1` | 每 peer streaming 连接上限，见 `src/java/org/apache/cassandra/config/Config.java:165` 与 `conf/cassandra.yaml:1421-1424` |
| `internode_compression` | `dc` in YAML | internode messaging frame compression，不等同于 SSTable stream payload compression，见 `conf/cassandra.yaml:1730-1742` 与 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4039-4046` |

## Metrics

- out-of-range repair validation 或 stream request 会增加 `StorageMetrics.totalOpsForInvalidToken`，触发点见 `src/java/org/apache/cassandra/dht/OwnedRanges.java:79-82`。
- startup 阶段 out-of-range operation 计入 `StorageMetrics.startupOpsForInvalidToken`，运行期计入 total，见 `src/java/org/apache/cassandra/service/StorageService.java:384-387`。
- out-of-range mutation/read repair 会增加 keyspace `outOfRangeTokenWrites`，见 `src/java/org/apache/cassandra/db/AbstractMutationVerbHandler.java:52-58`。
- repair outgoing stream 会增加 `StreamingMetrics.totalOutgoingRepairBytes` 和 `totalOutgoingRepairSSTables`，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1039-1049`。
- generic streaming failure 可通过 `system_views.streaming.failure_cause` 验证，测试查询见 `test/distributed/org/apache/cassandra/distributed/test/streaming/AbstractStreamFailureLogs.java:116-122`。

## 日志

- `OwnedRanges.validateRangeRequest()` 在 logging 开启且存在 unowned ranges 时 warn request id、request type、peer、unowned ranges 和 owned ranges，见 `src/java/org/apache/cassandra/dht/OwnedRanges.java:83-87`。
- `RepairJob` 完成 sync task 创建时记录 task 数、Merkle response 数和 parent session id，见 `src/java/org/apache/cassandra/repair/RepairJob.java:358-360`。
- `LocalSyncTask.startSync()` 记录 streaming repair range 数和 remote endpoint，并写 repair trace，见 `src/java/org/apache/cassandra/repair/LocalSyncTask.java:111-120`。
- generic stream failure log 应出现 WARN `Stream failed:`，测试断言见 `test/distributed/org/apache/cassandra/distributed/test/streaming/AbstractStreamFailureLogs.java:99-115`。
- repair remote stream failure 不应误触发 disk failure policy 或隐藏 `SomeRepairFailedException`，测试断言见 `test/distributed/org/apache/cassandra/distributed/test/RepairErrorsTest.java:114-135`。

## 运维关注点

- 开 transient replication 前先确认 `transient_replication_enabled`。默认 false 且 YAML 标注 experimental；不能把 transient RF 当成普通 RF 的无风险降本开关。
- repair 结果排障要先区分 full/transient 角色。transient replica 不应该作为完整补数目标；如果 full replica 缺数据，预期是从可用 full/transient source 单向补 full。
- pull repair 与 transient local 组合可能没有 sync task。`RepairJobTest` 覆盖 local transient + pull repair 任务为空，见 `test/unit/org/apache/cassandra/repair/RepairJobTest.java:420-445`。
- 开启 `reject_out_of_token_range_requests` 会让 validation/stream prepare/write receiver 早失败；切换前建议先看 invalid-token metric 与 WARN log。
- topology movement 期间看到 out-of-range write，要检查 token 是否在 pending range；pending endpoint 应被视为合法写目标。
- stream failure 排障要把 generic stream failure propagation 与 transient sync direction 分开。当前 dtest 只覆盖 generic repair/stream failure，不覆盖 transient RF 下的 failure injection。
- transient repair/streaming 新增 distributed test 时，至少应覆盖 RF `3/1` 或 NTS transient RF、开启 transient replication、制造 repair mismatch、注入 sender/receiver stream failure、断言 full replica 数据和 failure visibility。

## 性能瓶颈

- transient repair 的单向 sync 降低对 transient target 的写入，但可能增加从 transient/full source fetch 到 full target 的集中流量。
- optimised sync 的 `DifferenceHolder`/`ReduceHelper` 会减少重复 stream，但 target gate 意味着 transient target 永远不会成为补数终点，full replicas 承担更多修复压力。
- `OwnedRanges.testRanges()` 会 normalize range collection，源码注释明确提醒不要随意放到 hot path，见 `src/java/org/apache/cassandra/dht/OwnedRanges.java:93-120`。
- `stream_entire_sstables` 在 TLS/internode encryption 下会回退，transient repair 的故障注入测试需要同时覆盖 zero-copy 与非 zero-copy，避免只验证一个 I/O path。
- pending range 写入扩大 transition 期间的 write target 集合；bootstrap/move 高峰期可能同时放大 write fanout 和 repair/streaming 负载。

## 常见故障

- `StreamRequestOutOfTokenRangeException`：peer 请求的 full/transient ranges 不在本地 owned ranges 内。先确认 keyspace RF、pending ranges、requested ranges 和 `reject_out_of_token_range_requests`。
- validation response failure：repair validation request 的 range 不属于本节点 owned ranges；reject off 时同场景会成功但增加 invalid-token metric。
- pull repair 没有对 local transient 产生任务：这是源码设计，local transient 不 request，pull repair 又禁止 transfer，见 `src/java/org/apache/cassandra/repair/RepairJob.java:330-337`。
- repair stream failure 后节点出现 disk failure policy 日志：generic regression 应避免这种副作用，参考 `RepairErrorsTest` 的断言。
- transient read 出现 digest from transient：`ResponseResolver` 会直接拒绝 transient digest response，表示请求类型或 replica 标记出现错误。
- LWT during movement 报 pending range movement：`ReplicaPlans.forPaxos()` 禁止多个 pending endpoints，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:637-646`。

## 测试用例

- transient repair sync unit coverage：`test/unit/org/apache/cassandra/repair/RepairJobTest.java:400-452`、`test/unit/org/apache/cassandra/repair/RepairJobTest.java:532-667`、`test/unit/org/apache/cassandra/repair/RepairJobTest.java:737-762`。
- local sync stream plan coverage：`test/unit/org/apache/cassandra/repair/LocalSyncTaskTest.java:151-231`。
- repair validation owned range coverage：`test/unit/org/apache/cassandra/repair/RepairMessageVerbHandlerOutOfRangeTest.java:118-222`。
- stream request owned range coverage：`test/unit/org/apache/cassandra/streaming/StreamSessionOwnedRangesTest.java:95-185`。
- mutation/read-repair out-of-range and pending range coverage：`test/unit/org/apache/cassandra/db/MutationVerbHandlerOutOfRangeTest.java:102-200`。
- generic repair stream failure distributed coverage：`test/distributed/org/apache/cassandra/distributed/test/RepairErrorsTest.java:89-170`。
- generic stream failure visibility distributed coverage：`test/distributed/org/apache/cassandra/distributed/test/streaming/AbstractStreamFailureLogs.java:56-160`、`test/distributed/org/apache/cassandra/distributed/test/streaming/StreamFailedWhileReceivingTest.java:63-205`、`test/distributed/org/apache/cassandra/distributed/test/StreamPrepareFailTest.java:41-79`。
- pending write distributed coverage：`test/distributed/org/apache/cassandra/distributed/test/ring/PendingWritesTest.java:54-106`。
- bootstrap available range full/transient system table coverage：`test/distributed/org/apache/cassandra/distributed/test/ring/BootstrapTest.java:197-217`。

## 当前测试缺口

- `distributed_transient_repair_streaming_gap`：当前 distributed tests 没有 transient RF `3/1` 或 `transient_replication_enabled` 下的 repair streaming failure injection。已有 `RepairErrorsTest`/streaming failure tests 是 full-replica generic repair/streaming failure，已有 `PendingWritesTest` 是 pending write during bootstrap，二者没有合并。
- 缺少 mixed-version + transient repair streaming 的 compatibility test。
- 缺少 TLS/`stream_entire_sstables` fallback + transient repair streaming failure test。
- 缺少 `internode_compression` all/dc/none + transient repair streaming handshake/file-transfer matrix。

## Drift 检查

- `research/tools/check-repair-streaming-transient-coverage-drift.py` 校验 transient repair sync direction、local sync flags、owned-range validation、pending write guard、read transient guards、generic stream failure tests，以及当前 distributed test tree 中 transient repair streaming fault test 的缺口状态。
- 设计与运行方式见 `research/module-repair-streaming-transient-coverage-drift-checker.md`。
