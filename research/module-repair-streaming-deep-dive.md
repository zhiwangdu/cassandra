# Repair And Streaming Deep Dive

## 范围

本文补 `module-repair-streaming.md` 和 `flow-repair.md`、`flow-streaming.md` 的第二轮源码细节：consistent incremental repair 的协调/本地状态机，`system.repairs` 持久化和 `repair_admin` 运维入口，pending anti-compaction 的 SSTable 隔离与 cleanup，Cassandra storage streaming 的 reader/writer/entire-SSTable 分支，以及 TLS、压缩、zero-copy 与 receiver ingest 的关键边界。基础 repair validation、Merkle diff、sync task、StreamPlan/session 骨架仍以 `research/module-repair-streaming.md`、`research/flow-repair.md` 和 `research/flow-streaming.md` 为主。

## 设计目标

consistent incremental repair 的目标是把一次 incremental repair 拆成可恢复的 prepare、repair、finalize/fail 阶段，确保参与节点在同一个 parent repair session 下隔离同一批 unrepaired SSTables，并在所有参与者确认后再让后台 compaction 把 pending repair 数据转成 repaired 或 unrepaired 状态。四阶段和失败恢复在 `src/java/org/apache/cassandra/repair/consistent/ConsistentSession.java:57` 直接写成类级说明，状态转换由 `PREPARING`、`PREPARED`、`REPAIRING`、`FINALIZE_PROMISED`、`FINALIZED`、`FAILED` 约束在 `src/java/org/apache/cassandra/repair/consistent/ConsistentSession.java:149`。

streaming 的目标是给 repair、bootstrap、rebuild、move、decommission 等调用方提供同一套 table-scoped outgoing/incoming stream 抽象：正常分片 streaming 可以只传 token ranges，compressed SSTable 可按压缩块传输，eligible full-range SSTable 可走 entire-SSTable zero-copy 分支。Cassandra storage 层 hook 由 `src/java/org/apache/cassandra/streaming/TableStreamManager.java:27` 定义，默认实现由 `src/java/org/apache/cassandra/db/streaming/CassandraStreamManager.java:59` 绑定到 CFS 和 SSTable。

## 解决的问题

incremental repair 的最大问题不是如何比较 Merkle tree，而是如何避免 repair 期间和 repair 之后的 SSTable 集合被普通 compaction 混入错误 repaired 状态。`PendingAntiCompaction` 在 prepare 阶段把交叉 token ranges 的 unrepaired SSTables 隔离成 pending repair group，避免它们和其他 SSTables 混合 compaction，类注释在 `src/java/org/apache/cassandra/db/repair/PendingAntiCompaction.java:63`。后续 `PendingRepairManager` 负责防止 pending repair SSTables 与普通 SSTables 混合，并在 session 完成后通过 repair-finished compaction 做重分类，见 `src/java/org/apache/cassandra/db/compaction/PendingRepairManager.java:54`。

streaming 解决的是跨节点 SSTable 数据移动的两个冲突目标：一方面 repair/bootstrap 需要按 token/range 精确转移，另一方面大 SSTable 转移需要尽可能少的反序列化和堆内拷贝。`CassandraStreamManager.createOutgoingStreams()` 先按 requested replicas 转成 key ranges，再选择 SSTables、pending repair 过滤和 full/transient range 规则，最后构造 `CassandraOutgoingFile`，入口在 `src/java/org/apache/cassandra/db/streaming/CassandraStreamManager.java:89`。

## 设计取舍

consistent repair finalization 不直接把 SSTables 标成 repaired。`LocalSessions.handleFinalizeCommitMessage()` 只把本地 session 从 `FINALIZE_PROMISED` 改成 `FINALIZED`，注释明确说明 pending SSTables 的 promoted/demoted 由 compaction 后续处理，见 `src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:1018`。这个取舍避免和正在进行的 compaction 争抢 SSTable lifecycle transaction，但会带来运维上的“session finalized 但 SSTable 仍 pending”的短期状态。

anti-compaction 的取舍是先 flush，再在禁用/停止 compaction 的窗口内获取 refs 和 `LifecycleTransaction`。`PendingAntiCompaction.run()` 对每个 CFS 先 `forceBlockingFlush(ANTICOMPACTION)` 再提交 acquisition task，见 `src/java/org/apache/cassandra/db/repair/PendingAntiCompaction.java:368`；acquisition 阶段如果遇到 compaction disable race 会按 `ACQUIRE_RETRY_SECONDS` 重试，见 `src/java/org/apache/cassandra/db/repair/PendingAntiCompaction.java:222`。

streaming 的取舍是把 normal/compressed/entire SSTable 三条 I/O 路径分开，而不是在一个 writer 内分支。`CassandraOutgoingFile.write()` 在 entire 分支持有 SSTable lock、重建 component manifest 并调用 `CassandraEntireSSTableStreamWriter`；否则写 header 后根据 `header.isCompressed()` 选择 compressed 或 normal writer，见 `src/java/org/apache/cassandra/db/streaming/CassandraOutgoingFile.java:147`。zero-copy 仅在 Netty channel 没有 `SslHandler` 时使用，TLS 下回退到 buffer path，见 `src/java/org/apache/cassandra/net/AsyncStreamingOutputPlus.java:147` 和 `src/java/org/apache/cassandra/net/AsyncStreamingOutputPlus.java:157`。

## 核心类

`ConsistentSession` 是 coordinator/local consistent session 的状态模型和阶段说明，`CoordinatorSession` 管 coordinator 侧参与者状态、prepare/finalize futures 和 fail fanout，`LocalSessions` 管本地 session registry、`system.repairs` 持久化、prepare/finalize/fail/status 消息处理、cleanup 和 `repair_admin` 查询数据。核心入口分别在 `src/java/org/apache/cassandra/repair/consistent/ConsistentSession.java:53`、`src/java/org/apache/cassandra/repair/consistent/CoordinatorSession.java:61`、`src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:127`。

`PendingAntiCompaction` 负责 incremental repair prepare 阶段的 SSTable 隔离，`CompactionManager` 负责 actual anticompaction 和 fully-contained SSTable metadata mutate，`PendingRepairManager` 负责 session 完成后的 repair-finished compaction cleanup。对应入口在 `src/java/org/apache/cassandra/db/repair/PendingAntiCompaction.java:63`、`src/java/org/apache/cassandra/db/compaction/CompactionManager.java:817`、`src/java/org/apache/cassandra/db/compaction/PendingRepairManager.java:267`。

`CassandraStreamManager`、`CassandraOutgoingFile`、`CassandraIncomingFile`、`CassandraStreamHeader` 是 Cassandra storage streaming 的主干。normal writer 是 `CassandraStreamWriter`，compressed writer 是 `CassandraCompressedStreamWriter`，entire SSTable writer/reader 是 `CassandraEntireSSTableStreamWriter` 和 `CassandraEntireSSTableStreamReader`，receiver 是 `CassandraStreamReceiver`，入口分别见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamManager.java:89`、`src/java/org/apache/cassandra/db/streaming/CassandraOutgoingFile.java:43`、`src/java/org/apache/cassandra/db/streaming/CassandraIncomingFile.java:67`、`src/java/org/apache/cassandra/db/streaming/CassandraStreamHeader.java:48`、`src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:79`。

## 核心接口

repair 侧关键接口是 `KeyspaceRepairManager.prepareIncrementalRepair()` 和 `TableRepairManager.incrementalSessionCompleted()`。Cassandra 实现把 prepare 映射到 `PendingAntiCompaction(...).run()`，见 `src/java/org/apache/cassandra/db/repair/CassandraKeyspaceRepairManager.java:42`；table 级完成回调要求实现者通过 `LocalSessions` 判断 session 成功/失败，且 `repairedAt == 0` 时应 demote 为 unrepaired，见 `src/java/org/apache/cassandra/repair/TableRepairManager.java:48`。

streaming 侧关键接口是 `TableStreamManager` 提供的 `prepareIncomingStream()`、`createStreamReceiver()`、`createOutgoingStreams()` 三组方法，见 `src/java/org/apache/cassandra/streaming/TableStreamManager.java:27`。generic streaming 层通过 `OutgoingStreamMessage` 把 table、sender、plan/session、sequence、`repairedAt` 和 `pendingRepair` 放进 `StreamMessageHeader`，见 `src/java/org/apache/cassandra/streaming/messages/OutgoingStreamMessage.java:65` 和 `src/java/org/apache/cassandra/streaming/messages/StreamMessageHeader.java:34`；接收侧 `IncomingStreamMessage` 反序列化 header 后查 session 并委派给 table stream manager，见 `src/java/org/apache/cassandra/streaming/messages/IncomingStreamMessage.java:37`。

## 核心数据结构

consistent repair 的持久化表是 `system.repairs`，schema 包含 `parent_id`、`started_at`、`last_update`、`repaired_at`、`state`、`coordinator`、`coordinator_port`、`participants`、`participants_wp`、`ranges`、`cfids`，定义在 `src/java/org/apache/cassandra/db/SystemKeyspace.java:457`。`LocalSessions.save()` 写这些列，`load()` 读回并拒绝缺少 `participants_wp` 的旧/坏记录，见 `src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:564` 和 `src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:605`。

anti-compaction 使用 `AcquireResult` 同时持有 CFS、SSTable refs 和 `LifecycleTransaction`；predicate 会排除不相交、已 repaired、旧格式无 pending repair 支持、属于未 finalized pending session 或正在 anti-compaction 的 SSTable，见 `src/java/org/apache/cassandra/db/repair/PendingAntiCompaction.java:74` 和 `src/java/org/apache/cassandra/db/repair/PendingAntiCompaction.java:105`。实际 repair-finished cleanup 会把 pending session 的 SSTables 从 pending repaired/transient managers 转回普通 compaction 管理，见 `src/java/org/apache/cassandra/db/compaction/PendingRepairManager.java:516`。

streaming header 包含 SSTable format/version、estimated keys、sections、compression info、level、serialization header、table id、`isEntireSSTable`、first key 和 component manifest。序列化逻辑只在 entire SSTable 时写 manifest/firstKey，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamHeader.java:48` 和 `src/java/org/apache/cassandra/db/streaming/CassandraStreamHeader.java:160`。

## 生命周期

consistent incremental repair 生命周期：

1. `ActiveRepairService.prepareForRepair()` 注册 parent repair session，计算 `repairedAt`，向参与者发送 `PrepareMessage`，见 `src/java/org/apache/cassandra/service/ActiveRepairService.java:665` 和 `src/java/org/apache/cassandra/service/ActiveRepairService.java:616`。
2. coordinator 通过 `CoordinatorSessions.registerSession()` 创建 `CoordinatorSession`，并在 `CoordinatorSession.prepare()` 向所有 participants 发送 `PREPARE_CONSISTENT_REQ`，见 `src/java/org/apache/cassandra/repair/consistent/CoordinatorSessions.java:63` 和 `src/java/org/apache/cassandra/repair/consistent/CoordinatorSession.java:175`。
3. participant 的 `LocalSessions.handlePrepareMessage()` 创建 `LocalSession`、持久化为 `PREPARING`，运行 pending anti-compaction，成功后转 `PREPARED` 并回包，失败则 fail session，见 `src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:845`。
4. coordinator 在 prepare 成功后 `setRepairing()`，运行普通 validation/sync repair，再执行 `finalizePropose()` 和 `finalizeCommit()`；失败 callback 调 `fail()`，见 `src/java/org/apache/cassandra/repair/consistent/CoordinatorSession.java:341`。
5. participant 收到 `FinalizePropose` 后转 `FINALIZE_PROMISED` 并 flush `system.repairs`，收到 `FinalizeCommit` 后转 `FINALIZED`；完成回调让每个表的 repair manager 触发 background compaction，见 `src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:965`、`src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:1005`、`src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:1018`。
6. `LocalSessions.cleanup()` 定时 auto-fail、status request、auto-delete completed sessions，并可由 `repair_admin cleanup/cancel` 手动介入，见 `src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:473`。

streaming 生命周期：

1. `StreamSession.addTransferRanges()` flush/prepare ranges，然后 `getOutgoingStreamsForRanges()` 委派到每个 CFS 的 table stream manager，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:445` 和 `src/java/org/apache/cassandra/streaming/StreamSession.java:489`。
2. `CassandraStreamManager.createOutgoingStreams()` 选择 SSTables、sections、pending repair 过滤和 repaired/unrepaired range 规则，并创建 `CassandraOutgoingFile`，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamManager.java:89`。
3. `OutgoingStreamMessage.serialize()` 写 stream message header 后调用 outgoing stream 的 `write()`，见 `src/java/org/apache/cassandra/streaming/messages/OutgoingStreamMessage.java:65`。
4. 发送侧 `CassandraOutgoingFile.write()` 选择 entire/normal/compressed writer，normal writer 按 data sections 流式读取并可对传输 chunk 再做 LZ4 transfer compression，compressed writer 按压缩 chunk 区间传输，entire writer 按 component manifest 传 component 文件，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamWriter.java:76`、`src/java/org/apache/cassandra/db/streaming/CassandraCompressedStreamWriter.java:58`、`src/java/org/apache/cassandra/db/streaming/CassandraEntireSSTableStreamWriter.java:66`。
5. 接收侧 `CassandraIncomingFile.read()` 读 `CassandraStreamHeader` 后选择 entire/compressed/normal reader，见 `src/java/org/apache/cassandra/db/streaming/CassandraIncomingFile.java:67`。
6. normal/compressed reader 写 `RangeAwareSSTableWriter`，entire reader 写 `SSTableZeroCopyWriter` 并 mutate level/repaired/pending metadata，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReader.java:117`、`src/java/org/apache/cassandra/db/streaming/CassandraCompressedStreamReader.java:55`、`src/java/org/apache/cassandra/db/streaming/CassandraEntireSSTableStreamReader.java:85`。
7. `CassandraStreamReceiver.finished()` 根据 CDC/MV/stream-to-memtable 决定是否走 write path；否则 entire SSTable 分支先校验 SSTable-attached indexes，再 finish transaction、add SSTables、invalidate row/counter cache，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:185`、`src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:202`、`src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:236`。

## 调用链

consistent repair 主链：

`StorageService.repairAsync()` -> `ActiveRepairService.prepareForRepair()` -> `CoordinatorSessions.registerSession()` -> `CoordinatorSession.execute()` -> `CoordinatorSession.prepare()` -> participant `LocalSessions.handlePrepareMessage()` -> `CassandraKeyspaceRepairManager.prepareIncrementalRepair()` -> `PendingAntiCompaction.run()` -> 普通 `RepairSession` validation/sync -> `CoordinatorSession.finalizePropose()` -> participant `LocalSessions.handleFinalizeProposeMessage()` -> `CoordinatorSession.finalizeCommit()` -> participant `LocalSessions.handleFinalizeCommitMessage()` -> `TableRepairManager.incrementalSessionCompleted()` -> `CassandraTableRepairManager.incrementalSessionCompleted()` -> background compaction cleanup。关键源码锚点：`src/java/org/apache/cassandra/service/ActiveRepairService.java:665`、`src/java/org/apache/cassandra/repair/consistent/CoordinatorSession.java:341`、`src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:845`、`src/java/org/apache/cassandra/db/repair/CassandraKeyspaceRepairManager.java:42`、`src/java/org/apache/cassandra/db/repair/PendingAntiCompaction.java:368`、`src/java/org/apache/cassandra/db/repair/CassandraTableRepairManager.java:70`。

pending anti-compaction 主链：

`PendingAntiCompaction.run()` -> force flush -> `AcquisitionCallable.acquireTuple()` -> `tryModify(..., OperationType.ANTICOMPACTION)` -> `AcquisitionCallback.submitPendingAntiCompaction()` -> `CompactionManager.submitPendingAntiCompaction()` -> `performAnticompaction()` -> fully-contained metadata mutate 或 `doAntiCompaction()` split writer -> `PendingRepairManager.getRepairFinishedCompactionTask()` -> `RepairFinishedCompactionTask.runMayThrow()`。锚点：`src/java/org/apache/cassandra/db/repair/PendingAntiCompaction.java:192`、`src/java/org/apache/cassandra/db/repair/PendingAntiCompaction.java:264`、`src/java/org/apache/cassandra/db/compaction/CompactionManager.java:817`、`src/java/org/apache/cassandra/db/compaction/CompactionManager.java:891`、`src/java/org/apache/cassandra/db/compaction/CompactionManager.java:1688`、`src/java/org/apache/cassandra/db/compaction/PendingRepairManager.java:516`。

streaming I/O 主链：

`StreamSession.processStreamRequests()` -> `StreamSession.addTransferRanges()` -> `CassandraStreamManager.createOutgoingStreams()` -> `OutgoingStreamMessage.serialize()` -> `CassandraOutgoingFile.write()` -> `CassandraStreamWriter`/`CassandraCompressedStreamWriter`/`CassandraEntireSSTableStreamWriter` -> network channel -> `IncomingStreamMessage.deserialize()` -> `CassandraIncomingFile.read()` -> `CassandraStreamReader`/`CassandraCompressedStreamReader`/`CassandraEntireSSTableStreamReader` -> `CassandraStreamReceiver.received()` -> `CassandraStreamReceiver.finished()`。锚点：`src/java/org/apache/cassandra/streaming/StreamSession.java:1008`、`src/java/org/apache/cassandra/db/streaming/CassandraOutgoingFile.java:147`、`src/java/org/apache/cassandra/streaming/messages/IncomingStreamMessage.java:37`、`src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:102`、`src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:236`。

## 配置项

repair 相关配置与门禁主要在 `ActiveRepairService.prepareForRepair()` 周边：`getRepairedAt()` 只会在 global incremental repair 且非 force 时给非零 `repairedAt`，其他 full/non-global/forced 场景保持 unrepaired，见 `src/java/org/apache/cassandra/service/ActiveRepairService.java:616`；prepare 前还检查 pending compaction 和 disk usage 阈值，见 `src/java/org/apache/cassandra/service/ActiveRepairService.java:636`。consistent local sessions 的 cleanup 间隔、status check、auto fail 和 auto delete 常量在 `src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:127`。

streaming 配置主要有：

- `stream_entire_sstables` 默认启用，YAML 注释说明 internode encryption 会自动禁用 entire SSTable zero-copy streaming，见 `conf/cassandra.yaml:1269` 和 `src/java/org/apache/cassandra/config/Config.java:699`；运行时 getter/setter 在 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3997`。
- `entire_sstable_stream_throughput_outbound`、`entire_sstable_inter_dc_stream_throughput_outbound` 和普通 `stream_throughput_outbound`、`inter_dc_stream_throughput_outbound` 分别控制 entire/普通、local/inter-DC stream 限速，见 `conf/cassandra.yaml:1281`、`conf/cassandra.yaml:1292`、`src/java/org/apache/cassandra/config/Config.java:361`、`src/java/org/apache/cassandra/config/Config.java:366`。
- `internode_streaming_tcp_user_timeout` 控制 streaming connection 未确认数据容忍时间，见 `conf/cassandra.yaml:1364` 和 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3076`。
- `streaming_keep_alive_period` 和 `streaming_connections_per_host` 控制 control channel keepalive 与每主机 streaming 连接数，见 `conf/cassandra.yaml:1412`、`conf/cassandra.yaml:1423`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3987`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3992`。
- `server_encryption_options` 控制 internode TLS，`internode_compression` 控制节点间 compression 策略，见 `conf/cassandra.yaml:1641` 和 `conf/cassandra.yaml:1730`；Netty streaming 连接使用 `ConnectionCategory.STREAMING` 并在 optional encryption 下做 SSL fallback，见 `src/java/org/apache/cassandra/streaming/async/NettyStreamingConnectionFactory.java:51`。

## Metrics

repair metrics 在 `RepairMetrics` 中定义：preview failures、retry histogram、retry timeout/failure 以及按 retryable verb 拆分的 counters/histograms，见 `src/java/org/apache/cassandra/metrics/RepairMetrics.java:34`。retry 指标由 `RepairMessage.sendMessageWithRetries()` 更新，见 `src/java/org/apache/cassandra/repair/messages/RepairMessage.java:224`。consistent repair 的 pending/finalized/failed SSTable 统计不是 metrics，而是 `ActiveRepairService.getPendingStats()` 通过 `LocalSessions.getPendingStats()` 返回给 JMX/nodetool，见 `src/java/org/apache/cassandra/service/ActiveRepairService.java:390` 和 `src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:303`。

streaming metrics 在 `StreamingMetrics` 中定义全局 incoming/outgoing bytes、outgoing repair bytes/SSTables，以及 per-peer incoming/outgoing/incomingProcessTime 和 entire/partial streamed-in counters，见 `src/java/org/apache/cassandra/metrics/StreamingMetrics.java:34`。`StreamSession.streamSent()` 更新 outgoing/repair byte counters 并安排 ACK timeout，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1039`；`StreamSession.receive()` 统计 incoming bytes、发送 `ReceivedMessage` 并记录 incoming processing time，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1070`。

## 日志

consistent repair 关键日志分布在 coordinator 和 local session：`CoordinatorSession.execute()` 记录 incremental repair phase 开始、prepare/validation/finalization 成本和失败，见 `src/java/org/apache/cassandra/repair/consistent/CoordinatorSession.java:341`；`LocalSessions.handlePrepareMessage()` 记录 parent session 缺失、anti-compaction interrupted、prepare failed/success，见 `src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:845`；`LocalSessions.handleFinalizeProposeMessage()` 对 `system.repairs` flush 前后的 finalization promise 记录 debug/error，见 `src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:965`。

anti-compaction 的错误日志集中在 predicate 和 acquisition callback：旧格式 SSTable、交叉未完成 pending session、并发 anti-compaction 都会抛出带 repair session id 的 `SSTableAcquisitionException`，见 `src/java/org/apache/cassandra/db/repair/PendingAntiCompaction.java:105`。streaming writer/reader/receiver 都带 `[Stream #{}]` 日志，normal writer 和 compressed writer 记录开始/完成及 bytes transferred，entire reader 对每个 component 记录接收进度，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamWriter.java:76`、`src/java/org/apache/cassandra/db/streaming/CassandraCompressedStreamWriter.java:58`、`src/java/org/apache/cassandra/db/streaming/CassandraEntireSSTableStreamReader.java:85`。

## 运维关注点

`nodetool repair_admin` 是 consistent repair 运维入口。`list` 展示 session id、state、last activity、coordinator、participants 和 participants with ports，见 `src/java/org/apache/cassandra/tools/nodetool/RepairAdmin.java:48`；`summarize-pending` 和 `summarize-repaired` 展示 pending/repaired stats，见 `src/java/org/apache/cassandra/tools/nodetool/RepairAdmin.java:94` 和 `src/java/org/apache/cassandra/tools/nodetool/RepairAdmin.java:153`；`cleanup` 调 `cleanupPending()`，`cancel` 调 `failSession()`，见 `src/java/org/apache/cassandra/tools/nodetool/RepairAdmin.java:215` 和 `src/java/org/apache/cassandra/tools/nodetool/RepairAdmin.java:273`。

排查 incremental repair 卡住时，优先确认 `system.repairs` 是否存在 `PREPARING`、`PREPARED`、`REPAIRING`、`FINALIZE_PROMISED` 的老 session，再看 pending SSTable stats。`LocalSessions.cleanup()` 会对 idle session 发 status request，对超时 session auto-fail，对 completed/superseded/no-data session auto-delete，见 `src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:473`；手动 cancel 要求本地节点是 coordinator，除非使用 force，见 `src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:355`。

streaming 运维要区分三个层次：control channel 卡住、file channel 传输慢、receiver ingest 慢。`StreamingMultiplexedChannel` 明确把非文件消息放 control channel、文件消息放单独 channel，并用 semaphore 限制并发 file transfers，见 `src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:74` 和 `src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:306`。receiver 如果 CDC/MV/stream-to-memtable 需要 write path，会把 streamed SSTables 手动 apply mutation 后 flush 并 abort streaming txn，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:185`、`src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:202`、`src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:291`。

## 性能瓶颈

consistent repair 的主要瓶颈是 prepare 阶段 pending anti-compaction：它会强制 flush、抢 SSTable refs、禁用/停止 compaction 窗口、可能 split SSTables 并写出 full/transient/unrepaired 三组 writer，见 `src/java/org/apache/cassandra/db/repair/PendingAntiCompaction.java:368`、`src/java/org/apache/cassandra/db/repair/PendingAntiCompaction.java:192`、`src/java/org/apache/cassandra/db/compaction/CompactionManager.java:1722`。fully-contained SSTables 可以直接 mutate metadata，避免读写重写成本，见 `src/java/org/apache/cassandra/db/compaction/CompactionManager.java:851`。

streaming 的瓶颈取决于分支。normal writer 需要按 sections 读 Data.db 并校验 checksum chunk，compressed writer 减少解压但仍受压缩块区间读取影响，entire SSTable writer 能走 file-region zero-copy 但要求全 SSTable section、无 legacy counter shard、无旧 BF format、且配置允许 entire SSTable streaming，见 `src/java/org/apache/cassandra/db/streaming/CassandraOutgoingFile.java:180`。TLS 会让 zero-copy 回退到 64 KiB buffer path，见 `src/java/org/apache/cassandra/net/AsyncStreamingOutputPlus.java:147`；有 rate limit 时 zero-copy throttled path 以 file region chunk 写出并等待 Netty watermarks，见 `src/java/org/apache/cassandra/net/AsyncStreamingOutputPlus.java:205`。

## 常见故障

incremental repair prepare 失败的常见原因包括：旧 SSTable format 不支持 pending repair、与上一次未 finalized incremental repair 的 pending SSTables 重叠、或遇到另一个正在运行的 anti-compaction。三类失败都在 `AntiCompactionPredicate.apply()` 内抛出带操作建议的异常，见 `src/java/org/apache/cassandra/db/repair/PendingAntiCompaction.java:105`。

finalization 卡住常见于节点错过 `FinalizeCommit` 或 `FailSession`。本地 cleanup 会对 idle session 发 `StatusRequest`，收到任一 participant 的 `FAILED` 则本地 fail，收到 `FINALIZED` 则本地 finalize；未知 session 的 status request 会回 `FAILED`，见 `src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:1050`。

streaming 失败常见于 schema 被 drop、preview session 收到文件、owned ranges 校验失败、TLS/connection fallback 失败、receiver write path 或 SAI validation 失败。table 被 drop 时 normal/entire reader 都会抛 IOException，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReader.java:117` 和 `src/java/org/apache/cassandra/db/streaming/CassandraEntireSSTableStreamReader.java:85`；receive path 对 preview session 禁止接收文件，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1070`；entire SSTable receiver 会在 add 前验证 SSTable-attached indexes，失败会 abort streaming transaction，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:236`。

## 测试用例

consistent repair 主要测试在 `test/unit/org/apache/cassandra/repair/consistent/CoordinatorSessionTest.java`、`test/unit/org/apache/cassandra/repair/consistent/CoordinatorSessionsTest.java`、`test/unit/org/apache/cassandra/repair/consistent/CoordinatorMessagingTest.java`、`test/unit/org/apache/cassandra/repair/consistent/LocalSessionTest.java`、`test/unit/org/apache/cassandra/repair/consistent/PendingRepairStatTest.java`、`test/unit/org/apache/cassandra/repair/consistent/RepairStateTest.java`。其中 `CoordinatorSessionTest` 覆盖 coordinator 侧完整阶段和失败，`LocalSessionTest` 覆盖 anti-compaction 前后状态、anti-compaction 失败和 prepare 期间 fail。

anti-compaction 和 pending repair cleanup 相关测试包括 `test/unit/org/apache/cassandra/db/repair/PendingAntiCompactionTest.java`、`test/unit/org/apache/cassandra/db/repair/PendingAntiCompactionBytemanTest.java`、`test/unit/org/apache/cassandra/db/compaction/AntiCompactionTest.java`、`test/unit/org/apache/cassandra/db/compaction/CompactionStrategyManagerPendingRepairTest.java`、`test/unit/org/apache/cassandra/io/sstable/LegacySSTableTest.java`。

streaming reader/writer/entire SSTable 测试包括 `test/unit/org/apache/cassandra/db/streaming/CassandraStreamHeaderTest.java`、`test/unit/org/apache/cassandra/db/streaming/CassandraStreamManagerTest.java`、`test/unit/org/apache/cassandra/db/streaming/CassandraStreamReceiverTest.java`、`test/unit/org/apache/cassandra/db/streaming/CassandraEntireSSTableStreamWriterTest.java`、`test/unit/org/apache/cassandra/db/streaming/EntireSSTableStreamConcurrentComponentMutationTest.java`、`test/unit/org/apache/cassandra/streaming/async/StreamCompressionSerializerTest.java`、`test/unit/org/apache/cassandra/streaming/async/StreamingMultiplexedChannelTest.java`。分布式/失败注入测试包括 `test/distributed/org/apache/cassandra/distributed/test/streaming/RebuildStreamingTest.java`、`test/distributed/org/apache/cassandra/distributed/test/streaming/StreamFailedWhileReceivingTest.java`、`test/distributed/org/apache/cassandra/distributed/test/streaming/StreamDisconnectedWhileReceivingTest.java`、`test/distributed/org/apache/cassandra/distributed/test/streaming/StreamCloseInMiddleTest.java`、`test/resources/byteman/stream_failure.btm`。

## 待继续

- Auto-repair scheduler/assignment/history、priority/force repair、MV/CDC incremental gate、Netty streaming handshake、frame compression 与 streaming failure-injection matrix 已在 `research/module-repair-streaming-autorepair-netty.md` 补齐。
- `SSTableImporter`、streaming receive、SAI component validation/build failure 与 receiver transaction abort 已在 `research/module-cache-index-view-vector-import-repair.md` 补齐。
- 后续保留测试侧缺口：repair+MV 数据正确性 distributed 场景、transient repair/streaming failure-injection、mixed-version/TLS/`internode_compression` streaming compatibility。
