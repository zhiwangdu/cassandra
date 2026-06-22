# Module: Repair And Streaming

## 范围

本模块覆盖 repair validation/Merkle diff/sync task 和 streaming protocol/session/task/configuration，说明反熵与数据传输如何协作。

## 设计目标

Repair 负责在副本之间发现并修复数据差异；Streaming 是 Repair、bootstrap、decommission、range move 等流程复用的数据搬运层。

本轮覆盖目标：

- 从 `nodetool repair`/JMX 入口走到 `RepairCoordinator`、`RepairSession`、`RepairJob`。
- 解释 validation compaction 如何构造 Merkle trees，coordinator 如何比较 trees 并生成 sync tasks。
- 区分 local sync、remote sync、full repair、incremental repair、preview repair。
- 解释 `StreamPlan`、`StreamCoordinator`、`StreamSession`、`StreamTransferTask`、`StreamReceiveTask` 的职责边界。
- 列出 repair/streaming 的主要配置、metrics、日志和测试入口。

## 解决的问题

- Repair 不能只比较单行 digest：`RepairJob` 先请求各副本生成 Merkle trees，然后用 `MerkleTrees.difference()` 找出 out-of-sync ranges，见 `src/java/org/apache/cassandra/repair/RepairJob.java:305-340`。
- Validation 本身是只读 compaction：`ValidationManager.doValidation()` 通过 `ValidationPartitionIterator` 扫描完整行并填充 Merkle trees，不写出合并结果，见 `src/java/org/apache/cassandra/repair/ValidationManager.java:97-141`。
- 多 vnode/RF 场景会产生大量 per-range sessions：`ParentRepairSession` 注释说明 256 vnode、RF=3 时可能有 768 个 `RepairSession`，但只保留一个 parent session 避免重复 anti-compaction，见 `src/java/org/apache/cassandra/service/ActiveRepairService.java:942-947`。
- Streaming 协议要同时处理控制消息和大文件传输：`StreamingMultiplexedChannel` 用 control channel 发送非文件消息，用文件 channel 发送 `OutgoingStreamMessage`，见 `src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:74-111`。
- Incremental repair 必须隔离 pending repair SSTables：`PendingAntiCompaction` 在 prepare 阶段把 unrepaired SSTables 隔离到 pending repair group，见 `src/java/org/apache/cassandra/db/repair/PendingAntiCompaction.java:64-68`。

## 设计取舍

- `RepairSession` 的 validation phase 在同一个 session 中按 job 串行推进，避免同一 replica 同时为同一 range 创建多个 Merkle tree；sync phase 可以并发，见 `src/java/org/apache/cassandra/repair/RepairSession.java:94-107`。
- `RepairCoordinator` 把 repair 模式分派给 `PreviewRepairTask`、`IncrementalRepairTask` 或 `NormalRepairTask`，避免在 session/job 内部到处判断模式，见 `src/java/org/apache/cassandra/repair/RepairCoordinator.java:458-479`。
- Local sync 直接创建 `StreamPlan(StreamOperation.REPAIR)`；remote sync 发送 `SYNC_REQ` 给参与节点，由参与节点创建 `StreamingRepairTask` 并最终发回 `SYNC_RSP`，见 `src/java/org/apache/cassandra/repair/LocalSyncTask.java:80-123`、`src/java/org/apache/cassandra/repair/RepairMessageVerbHandler.java:272-300`。
- Full repair 默认在 transfer 前 flush；incremental repair 的 pending-repair SSTables 已在 prepare/anti-compaction 阶段隔离，所以 repair stream plan 会 `flushBeforeTransfer(false)`，见 `src/java/org/apache/cassandra/repair/LocalSyncTask.java:85-100`、`src/java/org/apache/cassandra/repair/StreamingRepairTask.java:93-105`。
- Streaming session 的协议状态机在一个类中集中处理：`StreamSession.messageReceived()` 根据 `StreamMessage.Type` 分发 prepare、stream、received、complete、failed，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:635-680`。
- Stream transfer task 逐个 sequence number 等待 ACK 并设置 timeout；超时会失败 session，见 `src/java/org/apache/cassandra/streaming/StreamTransferTask.java:85-120`。

## 核心类

| 类 | 作用 |
|---|---|
| `StorageService` | repair JMX/StorageService 入口，解析 `RepairOption` 并提交 repair command executor。见 `src/java/org/apache/cassandra/service/StorageService.java:4766-4803` |
| `RepairCoordinator` | repair 命令级 coordinator，负责 prepare、模式分派、进度事件、父 repair 记录。定义见 `src/java/org/apache/cassandra/repair/RepairCoordinator.java:94-133` |
| `ActiveRepairService` | repair session registry、parent session、prepare message、VALIDATION/SYNC response 分发。定义见 `src/java/org/apache/cassandra/service/ActiveRepairService.java:140-170` |
| `AbstractRepairTask` | 将 common ranges fan out 成多个 `RepairSession`。见 `src/java/org/apache/cassandra/repair/AbstractRepairTask.java:57-103` |
| `RepairSession` | 单个 common range 的修复生命周期，跟踪 validation tasks 和 remote sync tasks。见 `src/java/org/apache/cassandra/repair/RepairSession.java:109-170` |
| `RepairJob` | 单表 repair job，调度 validation、比较 Merkle trees、生成 sync tasks。见 `src/java/org/apache/cassandra/repair/RepairJob.java:67-120` |
| `RepairMessageVerbHandler` | repair 消息入口，处理 prepare/snapshot/validation/sync/cleanup/consistent repair messages。见 `src/java/org/apache/cassandra/repair/RepairMessageVerbHandler.java:60-110` |
| `ValidationManager` | 执行 validation compaction，创建 Merkle trees，并提交到 table repair manager。见 `src/java/org/apache/cassandra/repair/ValidationManager.java:46-54`、`src/java/org/apache/cassandra/repair/ValidationManager.java:182-213` |
| `Validator` | 扫描 partition 时计算 row hash 并填入 Merkle tree，完成后发送 validation response。见 `src/java/org/apache/cassandra/repair/Validator.java:61-114` |
| `SyncTask` | repair sync task 抽象，空差异直接成功，非空差异触发 streaming。见 `src/java/org/apache/cassandra/repair/SyncTask.java:43-96` |
| `LocalSyncTask` | coordinator 参与的 repair streaming。见 `src/java/org/apache/cassandra/repair/LocalSyncTask.java:48-78` |
| `StreamingRepairTask` | 两个远端 replica 之间的 repair streaming。见 `src/java/org/apache/cassandra/repair/StreamingRepairTask.java:49-80` |
| `StreamPlan` | streaming plan builder，收集 request/transfer ranges 并执行。见 `src/java/org/apache/cassandra/streaming/StreamPlan.java:39-70` |
| `StreamCoordinator` | 管理 peer sessions、连接策略和每 host 多连接分桶。见 `src/java/org/apache/cassandra/streaming/StreamCoordinator.java:41-66` |
| `StreamSession` | 单 peer streaming protocol state machine。见 `src/java/org/apache/cassandra/streaming/StreamSession.java:100-163` |
| `StreamTransferTask` | 每 table outgoing streams、sequence number、ACK timeout。见 `src/java/org/apache/cassandra/streaming/StreamTransferTask.java:45-73` |
| `StreamReceiveTask` | 每 table incoming streams，收完后调用 receiver finished 并完成 session task。见 `src/java/org/apache/cassandra/streaming/StreamReceiveTask.java:39-97` |

## 核心接口

- `ActiveRepairService.submitRepairSession()`：创建 `RepairSession`、注册 FD/Gossip listener、完成后移除 session，见 `src/java/org/apache/cassandra/service/ActiveRepairService.java:440-480`。
- `ActiveRepairService.prepareForRepair()`：注册 parent session、发送 `PrepareMessage`、等待参与节点 ack，并设置 prepare timeout，见 `src/java/org/apache/cassandra/service/ActiveRepairService.java:665-717`。
- `RepairSession.validationComplete()` / `syncComplete()`：处理 `VALIDATION_RSP` 和 `SYNC_RSP`，见 `src/java/org/apache/cassandra/repair/RepairSession.java:224-264`。
- `RepairMessageVerbHandler` 的 `VALIDATION_REQ` 分支：创建 `Validator` 并调用 `ctx.validationManager().submitValidation(store, validator)`，见 `src/java/org/apache/cassandra/repair/RepairMessageVerbHandler.java:198-258`。
- `StreamPlan.requestRanges()` / `transferRanges()`：分别添加 inbound request 和 outbound transfer，见 `src/java/org/apache/cassandra/streaming/StreamPlan.java:91-130`。
- `StreamPlan.execute()`：创建 `StreamResultFuture` 并启动所有 sessions，见 `src/java/org/apache/cassandra/streaming/StreamPlan.java:190-198`、`src/java/org/apache/cassandra/streaming/StreamResultFuture.java:88-108`。
- `StreamSession.onInitializationComplete()`：发送 `PrepareSynMessage` 开始 prepare phase，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:682-697`。
- `StreamSession.prepareAsync()`：处理对端 requests/summaries，准备 receiving 和 transfer summaries，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:791-822`。

## 核心数据结构

- `ParentRepairSession`：保存 keyspace、CFS map、ranges、incremental/global/repairedAt/preview/coordinator 和 snapshot 标记，见 `src/java/org/apache/cassandra/service/ActiveRepairService.java:947-1017`。
- `RepairJobDesc`：贯穿 validation/sync 消息的 parent session、session id、keyspace/table/ranges 描述。
- `ValidationTask`：coordinator 等待某个 endpoint 返回 Merkle tree；`RepairSession.validating` 以 `(RepairJobDesc, endpoint)` 为 key 跟踪，见 `src/java/org/apache/cassandra/repair/RepairSession.java:127-130`。
- `MerkleTrees`：validation compaction 输出；`ValidationManager.createMerkleTrees()` 按 repair session memory budget 和 RF 计算每 range 深度，见 `src/java/org/apache/cassandra/repair/ValidationManager.java:54-88`。
- `TreeResponse`：coordinator 收到的 endpoint + Merkle trees，`RepairJob` 在 pairwise diff 后释放 trees，见 `src/java/org/apache/cassandra/repair/RepairJob.java:305-357`。
- `StreamRequest` / `StreamSummary` / `OutgoingStreamMessage` / `IncomingStreamMessage`：stream prepare 与文件传输协议对象，消息类型枚举见 `src/java/org/apache/cassandra/streaming/messages/StreamMessage.java:61-72`。
- `StreamState` / `SessionInfo`：`StreamResultFuture` 汇总的 streaming 进度和最终状态，`StreamResultFuture` 定义见 `src/java/org/apache/cassandra/streaming/StreamResultFuture.java:53-80`。

## 生命周期

Repair command：

```text
StorageService.repairAsync(keyspace, repairSpec)
  -> RepairOption.parse(...)
  -> StorageService.repair(keyspace, option, listeners)
     -> fill default ranges from primary/local replicas when needed
     -> repairCommandExecutor.submit(createRepairTask(...))
        -> RepairCoordinator.run()
           -> prepare(columnFamilies, allNeighbors, force)
              -> ActiveRepairService.prepareForRepair(...)
           -> choose PreviewRepairTask / IncrementalRepairTask / NormalRepairTask
           -> task.perform(...)
```

Repair session/job：

```text
AbstractRepairTask.runRepair(parentSession, isIncremental, ...)
  -> submitRepairSessions(commonRanges)
     -> ActiveRepairService.submitRepairSession(...)
        -> new RepairSession(...)
        -> RepairSession.start(executor)
           -> for each table: executor.execute(new RepairJob(session, cfname))
              -> RepairJob.run()
                 -> validationScheduler.schedule(createSyncTasks(...))
                    -> send validation requests
                    -> wait TreeResponse list
                    -> MerkleTrees.difference(...)
                    -> create LocalSyncTask / SymmetricRemoteSyncTask / AsymmetricRemoteSyncTask
                 -> execute sync tasks
```

Streaming protocol：

```text
StreamPlan.requestRanges/transferRanges
  -> StreamCoordinator.getOrCreateOutboundSession(peer)
  -> StreamPlan.execute()
     -> StreamResultFuture.createInitiator(...)
        -> session.init(future)
        -> coordinator.connect(...)
           -> StreamSession.onInitializationComplete()
              -> PREPARE_SYN
           -> follower prepareAsync()
              -> PREPARE_SYNACK
           -> initiator prepareSynAck()
              -> PREPARE_ACK if needed
           -> startStreamingFiles()
              -> OutgoingStreamMessage
              -> ReceivedMessage
           -> CompleteMessage / session failure
```

## 调用链

- Repair JMX 入口：`StorageService.repairAsync()` 解析 `RepairOption` 并提交 repair command，见 `src/java/org/apache/cassandra/service/StorageService.java:4766-4803`。
- Repair coordinator：`RepairCoordinator.run()` 执行 prepare、选择 full/incremental/preview task 并发布 progress，见 `src/java/org/apache/cassandra/repair/RepairCoordinator.java:164-270`。
- Validation：`RepairMessageVerbHandler` 收到 `VALIDATION_REQ` 后创建 `Validator` 并提交 `ValidationManager`，见 `src/java/org/apache/cassandra/repair/RepairMessageVerbHandler.java:198-258`。
- Diff 与 sync：`RepairJob` 收集 `TreeResponse`、执行 Merkle diff，并创建 local/remote sync tasks，见 `src/java/org/apache/cassandra/repair/RepairJob.java:305-357`。
- Streaming plan：`LocalSyncTask` 和 `StreamingRepairTask` 创建 `StreamPlan` 并 request/transfer ranges，见 `src/java/org/apache/cassandra/repair/LocalSyncTask.java:85-100` 和 `src/java/org/apache/cassandra/repair/StreamingRepairTask.java:82-105`。
- Streaming protocol：`StreamPlan.execute()` 创建 `StreamResultFuture`，`StreamSession.messageReceived()` 分发 prepare/stream/received/complete/failed，见 `src/java/org/apache/cassandra/streaming/StreamPlan.java:190-198` 和 `src/java/org/apache/cassandra/streaming/StreamSession.java:635-680`。

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| `repair_request_timeout` | `src/java/org/apache/cassandra/config/Config.java:162-163`、`conf/cassandra.yaml:1320-1322` | repair RPC/prepare 等请求超时 |
| `repair_session_space` | `src/java/org/apache/cassandra/config/Config.java:206-208`、`conf/cassandra.yaml:840-856` | repair Merkle trees 内存预算 |
| `repair_session_max_tree_depth` | `src/java/org/apache/cassandra/config/Config.java:206`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:596-606` | 已 deprecated 的 Merkle tree 深度上限 |
| `concurrent_merkle_tree_requests` | `src/java/org/apache/cassandra/config/Config.java:210`、`conf/cassandra.yaml:861` | validation scheduler 并发 Merkle tree 请求数 |
| `concurrent_validations` | `src/java/org/apache/cassandra/config/Config.java:671`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1073-1088` | validation executor 并发，默认关联 `concurrent_compactors` |
| `repair_command_pool_size` / `repair_command_pool_full_strategy` | `src/java/org/apache/cassandra/config/Config.java:672-673`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4423-4428` | repair command executor 容量与满载策略 |
| `streaming_connections_per_host` | `src/java/org/apache/cassandra/config/Config.java:165`、`conf/cassandra.yaml:1424` | 每 host streaming 连接数 |
| `streaming_keep_alive_period` | `src/java/org/apache/cassandra/config/Config.java:166-167`、`conf/cassandra.yaml:1419` | streaming keep-alive 周期 |
| `stream_transfer_task_timeout` | `src/java/org/apache/cassandra/config/Config.java:175`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4010` | outgoing stream ACK timeout |
| `stream_throughput_outbound` / `inter_dc_stream_throughput_outbound` | `src/java/org/apache/cassandra/config/Config.java:361-364`、`conf/cassandra.yaml:1297-1304` | streaming 普通/跨 DC outbound 限速 |
| `stream_entire_sstables` | `src/java/org/apache/cassandra/config/Config.java:699`、`conf/cassandra.yaml:1279` | 是否启用 entire SSTable streaming |
| `entire_sstable_stream_throughput_outbound` / `entire_sstable_inter_dc_stream_throughput_outbound` | `src/java/org/apache/cassandra/config/Config.java:366-367`、`conf/cassandra.yaml:1285-1290` | entire SSTable streaming 限速 |
| `internode_streaming_tcp_user_timeout` | `src/java/org/apache/cassandra/config/Config.java:275-276`、`conf/cassandra.yaml:1368` | streaming socket TCP user timeout |
| `streaming_slow_events_log_timeout` | `src/java/org/apache/cassandra/config/Config.java:952`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:5031-5039` | slow stream events 日志阈值 |

## Metrics

- `StorageMetrics.repairExceptions` 在 repair command 错误时递增，见 `src/java/org/apache/cassandra/repair/RepairCoordinator.java:164-183`。
- `Keyspace.metric.repairPrepareTime` 记录 repair prepare 耗时，见 `src/java/org/apache/cassandra/repair/RepairCoordinator.java:445-455`。
- `Keyspace.metric.repairTime` 记录 repair command 总耗时，见 `src/java/org/apache/cassandra/repair/RepairCoordinator.java:242-270`。
- `ColumnFamilyStore.metric.repairsCompleted` 在 repair job 成功/失败 callback 中更新，见 `src/java/org/apache/cassandra/repair/RepairJob.java:200-235`。
- `ColumnFamilyStore.metric.validationTime` 包裹 `ValidationManager.doValidation()`，见 `src/java/org/apache/cassandra/repair/ValidationManager.java:186-195`。
- `TableMetrics.bytesValidated`、`partitionsValidated`、`bytesPreviewed` 在 validation finally block 中更新，见 `src/java/org/apache/cassandra/repair/ValidationManager.java:143-153`。
- `ColumnFamilyStore.metric.repairSyncTime` 在 `SyncTask.finished()` 中更新，见 `src/java/org/apache/cassandra/repair/SyncTask.java:103-107`。
- `StreamingMetrics.totalIncomingBytes`、`totalOutgoingBytes`、repair-specific outgoing metrics 在 `StreamSession.streamSent()`/`receive()` 更新，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1039-1056`、`src/java/org/apache/cassandra/streaming/StreamSession.java:1070-1082`。

## 日志

- Repair command failure 通过 `RepairCoordinator.notifyError()` 记录 warn/error 并发进度事件，见 `src/java/org/apache/cassandra/repair/RepairCoordinator.java:164-187`。
- `RepairSession.start()` 记录 parent session、range、tables，并在成功后记录 session completed，见 `src/java/org/apache/cassandra/repair/RepairSession.java:290-360`。
- `RepairJob.sendValidationRequest()` 记录 “Requesting merkle trees...”，见 `src/java/org/apache/cassandra/repair/RepairJob.java:493-508`。
- `ValidationManager.doValidation()` debug 记录 validation partitions/bytes/duration，见 `src/java/org/apache/cassandra/repair/ValidationManager.java:154-162`。
- `StreamingRepairTask.run()` 记录 remote repair streaming range 数和 stream plan 创建耗时，见 `src/java/org/apache/cassandra/repair/StreamingRepairTask.java:82-90`。
- `StreamingMultiplexedChannel` 在等待 file transfer semaphore 时周期性记录等待 permit，见 `src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:356-369`。

## 运维关注点

- Full repair 会在 validation 前 flush，以尽量让各节点验证的数据接近一致，见 `src/java/org/apache/cassandra/db/repair/CassandraValidationIterator.java:196-204`。
- Incremental repair 的 validation 只选择 `pendingRepair == parentId` 的 SSTables，见 `src/java/org/apache/cassandra/db/repair/CassandraValidationIterator.java:124-132`。
- Preview repair 不真正接收文件；`StreamSession.receive()` 会拒绝 preview session 的文件接收，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1070-1075`。
- Repair 比普通 FD 更保守：parent coordinator failure 只有在 `phi >= 2 * phi_convict_threshold` 时才 abort parent sessions，见 `src/java/org/apache/cassandra/service/ActiveRepairService.java:1054-1070`。
- Streaming request 会校验 owned ranges，越界时抛 `StreamRequestOutOfTokenRangeException`，入口见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1020-1031`。
- `streaming_connections_per_host` > 1 时 `StreamCoordinator.transferStreams()` 会把 outgoing streams 分桶到多个 sessions，见 `src/java/org/apache/cassandra/streaming/StreamCoordinator.java:196-215`。

## 性能瓶颈

- Validation compaction 是全量扫描相关 SSTables，瓶颈通常在 disk read、compaction backlog、wide partitions、tombstones 和 Merkle tree memory。
- `repair_session_space` 会限制 Merkle tree resolution；空间太小可能导致差异范围粗、streaming 放大。
- `concurrent_merkle_tree_requests` 限制 coordinator 同时要求多少 Merkle tree，过大时会放大 heap/disk 压力。
- Sync task 数量是 endpoints 两两比较的结果；RF 高、差异范围多时会放大 remote streaming tasks。
- Streaming 受 outbound throughput、inter-DC throughput、file transfer semaphore、ACK timeout、receiver disk ingest 和 secondary index/MV build 影响。
- Entire SSTable streaming 减少 serialization/row-level filtering 成本，但受 whole-file 可用条件和单独限速配置影响。

## 常见故障

- `RepairOutOfTokenRangeException`：repair validation request range 不属于接收节点时触发，检查 range ownership 和拓扑变化，入口见 `src/java/org/apache/cassandra/repair/RepairMessageVerbHandler.java:452-465`。
- Validation hanging：如果 validation 异常没有发送失败响应，coordinator 会一直等待；`ValidationManager.submitValidation()` 明确在异常时调用 `validator.fail(e)`，见 `src/java/org/apache/cassandra/repair/ValidationManager.java:196-205`。
- Incremental repair prepare 失败：遇到 legacy SSTables、未完成 pending repair SSTables 或冲突 anti-compaction 会拒绝，见 `src/java/org/apache/cassandra/db/repair/PendingAntiCompaction.java:120-164`。
- Streaming timeout：`StreamTransferTask.timeout()` 移除 stream 并调用 `session.sessionTimeout()`，见 `src/java/org/apache/cassandra/streaming/StreamTransferTask.java:107-120`。
- Streaming session failed：收到 `SESSION_FAILED` 会 close session 为 failed，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1182-1190`。
- Schema dropped during receive：`StreamReceiveTask.OnCompletionRunnable` 发现 CFS 不存在会 abort receiver 并完成 task，见 `src/java/org/apache/cassandra/streaming/StreamReceiveTask.java:125-139`。

## 测试用例

- `test/unit/org/apache/cassandra/repair/RepairSessionTest.java`
- `test/unit/org/apache/cassandra/repair/RepairJobTest.java`
- `test/unit/org/apache/cassandra/repair/ValidationTaskTest.java`：validation task failure/abort 行为见 `test/unit/org/apache/cassandra/repair/ValidationTaskTest.java:40-70`。
- `test/unit/org/apache/cassandra/repair/ValidatorTest.java`
- `test/unit/org/apache/cassandra/repair/RepairMessageVerbHandlerOutOfRangeTest.java`
- `test/unit/org/apache/cassandra/repair/LocalSyncTaskTest.java`：full/incremental/transient stream plan 断言见 `test/unit/org/apache/cassandra/repair/LocalSyncTaskTest.java:152-193`、`test/unit/org/apache/cassandra/repair/LocalSyncTaskTest.java:200-232`。
- `test/unit/org/apache/cassandra/repair/StreamingRepairTaskTest.java`：remote repair stream plan flush 策略见 `test/unit/org/apache/cassandra/repair/StreamingRepairTaskTest.java:64-89`。
- `test/unit/org/apache/cassandra/streaming/StreamingTransferTest.java`：empty/request/transfer stream plan 行为见 `test/unit/org/apache/cassandra/streaming/StreamingTransferTest.java:115-155`、`test/unit/org/apache/cassandra/streaming/StreamingTransferTest.java:238-266`。
- `test/unit/org/apache/cassandra/streaming/StreamTransferTaskTest.java`：ACK timeout 与 completion 行为见 `test/unit/org/apache/cassandra/streaming/StreamTransferTaskTest.java:94-137`。
- `test/unit/org/apache/cassandra/streaming/StreamSessionOwnedRangesTest.java`：stream request owned range 校验见 `test/unit/org/apache/cassandra/streaming/StreamSessionOwnedRangesTest.java:143-170`。
- `test/distributed/org/apache/cassandra/distributed/test/repair/ConcurrentValidationRequestsTest.java`：验证 concurrent Merkle requests 不超过 RF * 配置值，见 `test/distributed/org/apache/cassandra/distributed/test/repair/ConcurrentValidationRequestsTest.java:85-120`。
- `test/distributed/org/apache/cassandra/distributed/test/streaming/StreamFailureLogsFailureDueToSessionTimeoutTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/streaming/RebuildStreamingTest.java`

## 待继续

- Consistent incremental repair 的 `LocalSessions`/`CoordinatorSession` 状态机、`system.repairs`、repair_admin、pending anti-compaction 和 streaming reader/writer 细节已在 `research/module-repair-streaming-deep-dive.md` 补齐。
- Auto-repair scheduler/assignment/history、Repair/MV gate、Netty streaming handshake/frame compression 和 streaming failure-injection matrix 已在 `research/module-repair-streaming-autorepair-netty.md` 补齐。
- Rebuild/bootstrap/remove/move/decommission 对 `StreamPlan` 的不同调用参数已在 `research/module-topology-operations.md` 和 `research/module-topology-operations-internals.md` 补齐。
- 后续保留测试侧缺口：repair+MV 数据正确性 distributed 场景、transient repair/streaming failure-injection、mixed-version/TLS/`internode_compression` streaming compatibility。
