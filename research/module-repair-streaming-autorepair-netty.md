# Repair/Streaming Auto-Repair 与 Netty Streaming 第三轮源码研究

## 范围

本文补齐第二轮文档未展开的 Repair/Streaming 边界：auto-repair scheduler、turn assignment、history/priority/force repair 状态、token range splitter、MV/CDC incremental repair gate、Netty streaming handshake、messaging frame compression 与 streaming transfer compression 的分层，以及 streaming failure-injection 覆盖矩阵。

基础 repair validation、consistent incremental repair、pending anti-compaction、Cassandra streaming reader/writer 和 receiver ingest 已在 `research/module-repair-streaming.md` 与 `research/module-repair-streaming-deep-dive.md` 展开。普通 repair/MV write-path replay、SAI streaming/import validation 和 receiver transaction abort 已在 `research/module-cache-index-view-vector-import-repair.md` 展开。

## 设计目标

- Auto-repair 目标是在每个 repair type 上周期性、可控地触发 repair，同时避免多个节点或多个 schedule 抢同一 replica set。入口 `AutoRepair.setup()` 为每个 `RepairType` 创建 executor/state，并按 `initial_scheduler_delay` 和 `repair_check_interval` 周期调度，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:113-150`。
- Auto-repair assignment 目标是把一次 repair 限制在可观测、可重试、可跳过的工作单元中。主循环会先判定是否轮到本节点，再构造 keyspace/table plan、split assignments、逐批提交 `RepairCoordinator`，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:161-270`。
- Netty streaming 目标是让 control message 保持低延迟，让大文件 transfer 走独立 channel 和 semaphore，并在压缩/TLS/zero-copy 分支之间保持一致的 session 语义，见 `src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:74-99`。
- Streaming failure visibility 目标是把握手失败、session timeout、EOF/ClosedChannel、receiver exception 和 disk/compaction guard failure 都落到日志、`system_views.streaming` 与 metrics，而不是静默挂起，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:700-763` 与 `src/java/org/apache/cassandra/db/virtual/StreamingVirtualTable.java:37-54`。

## 解决的问题

- Manual repair 容易出现节点长期未修、repair 间隔漂移、range 过大和人工 priority 不透明。Auto-repair 使用 `system_distributed.auto_repair_history` 记录每个 host/type 的 start/finish、turn、delete vote 和 force flag，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:115-175`。
- 多个 repair type 或多个节点并发运行时，容易在同一 replica set 上制造 validation/streaming 热点。`AutoRepairUtils.getHostsBeingRepaired()` 和 `getMostEligibleHostToRepair()` 会综合当前 schedule、跨 schedule 开关、priority/force 状态与 replica overlap，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:589-707`。
- Incremental repair 与 MV repair replay、CDC repair replay 同时打开时存在重复写路径或语义风险。`AutoRepairService.checkCanRun()` 对 incremental repair 的 MV/CDC replay 开关做全局拒绝，`IncrementalRepairState` 还会过滤带 MV 或 CDC 的 base table，见 `src/java/org/apache/cassandra/service/AutoRepairService.java:85-98` 与 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairState.java:323-365`。
- Streaming 层容易混淆 `internode_compression` 的 messaging frame compression 与 SSTable transfer compression。握手在 messaging channel 上安装 LZ4/CRC frame encoder/decoder，但 streaming success 不安装 messaging frame encoder，streaming 文件 chunk 的 LZ4 是 `StreamCompressionSerializer` 的 payload 格式，见 `src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:334-379` 与 `src/java/org/apache/cassandra/streaming/async/StreamCompressionSerializer.java:34-70`。

## 设计取舍

- Auto-repair 默认双重关闭：需要 JVM property 允许 schema/MBean/scheduler 入口，还需要 YAML/config 中 `enabled` 打开。`AutoRepairService.setup()` 在 property 未启用时直接返回，system_distributed auto-repair 表也只在 property 启用时注册，见 `src/java/org/apache/cassandra/service/AutoRepairService.java:62-78` 与 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:74-88`。
- Turn election 选择系统表而非外部 coordinator。好处是所有节点可用同一 `system_distributed` 状态恢复历史；代价是要处理 stale host、delete vote、CAS insert、priority host 不在 ring 等边界，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:821-989`。
- 默认不允许同一 replica 被并发 repair，跨 schedule 并发默认允许。这样保守保护 replica 热点，但允许 full/incremental/preview 在 operator 明确配置后提升吞吐，默认值见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairConfig.java:461-483`。
- Range splitter 用 estimated bytes/partitions 切小 repair 单元。它降低单次 repair 的尾延迟，但估算依赖 SSTable metadata 和 range cardinality，且 `max_bytes_per_schedule` 可能让 full repair 的某些 range 本轮跳过，见 `src/java/org/apache/cassandra/repair/autorepair/RepairTokenRangeSplitter.java:345-413`。
- Streaming channel 握手复用 internode connection negotiation，但传输阶段不走 messaging frame compression。这样 control/file stream 可以使用 streaming 协议版本和 payload-level transfer compression，避免把 SSTable 文件流切成 128 KiB messaging frames，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:431-465` 与 `src/java/org/apache/cassandra/net/FrameEncoderLZ4.java:49-101`。
- Entire SSTable zero-copy 对 CPU 和 serialization 成本最好，但要求配置允许、SSTable section 覆盖整表、无旧 counter shard、无旧 Bloom filter format，并且 TLS 会让 zero-copy 回退，见 `src/java/org/apache/cassandra/db/streaming/CassandraOutgoingFile.java:181-201` 与 `src/java/org/apache/cassandra/db/streaming/package-info.java:20-50`。

## 核心类

- `src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java`：scheduler 与 repair main loop。`setup()` 创建 per-type scheduler，`repair()` 做 enabled/version/DC/turn/table/assignment 检查，`repairKeyspace()` 提交 `RepairCoordinator` 并处理重试/timeout，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:113-150`、`src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:161-270`、`src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:283-411`。
- `src/java/org/apache/cassandra/repair/autorepair/AutoRepairConfig.java`：全局和 per-repair-type override。默认 full/incremental/preview 均 disabled，`repair_by_keyspace=true`，单 type repair threads 为 1，parallel repair count/percentage 为 3，MV auto repair disabled，min interval 24h，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairConfig.java:47-66`、`src/java/org/apache/cassandra/repair/autorepair/AutoRepairConfig.java:73-125`、`src/java/org/apache/cassandra/repair/autorepair/AutoRepairConfig.java:461-545`。
- `src/java/org/apache/cassandra/service/AutoRepairService.java` 与 `src/java/org/apache/cassandra/service/AutoRepairServiceMBean.java`：MBean/JMX 参数面，包含 scheduler start、priority/force host、parallelism、MV repair、token splitter、retry/backoff、mixed major version 等 setter，见 `src/java/org/apache/cassandra/service/AutoRepairService.java:114-340` 与 `src/java/org/apache/cassandra/service/AutoRepairServiceMBean.java:28-78`。
- `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java`：history/priority 表 prepared statement、ring host filtering、turn election、replica contention 检查、keyspace/table/MV selection、range size estimate，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:199-228`、`src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:494-527`、`src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:631-780`、`src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:1148-1203`。
- `src/java/org/apache/cassandra/repair/autorepair/AutoRepairState.java`：per repair type state 和 metrics wrapper。`PreviewRepairedState` 创建 preview repaired option，`IncrementalRepairState` 创建 incremental option 并过滤 MV/CDC base table，`FullRepairState` 创建 full option，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairState.java:50-121` 与 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairState.java:303-385`。
- `src/java/org/apache/cassandra/repair/autorepair/PrioritizedRepairPlan.java`、`src/java/org/apache/cassandra/repair/autorepair/KeyspaceRepairPlan.java`、`src/java/org/apache/cassandra/repair/autorepair/RepairAssignment.java`、`src/java/org/apache/cassandra/repair/autorepair/KeyspaceRepairAssignments.java`、`src/java/org/apache/cassandra/repair/autorepair/RepairAssignmentIterator.java`：把 table auto-repair priority、estimated bytes、token ranges 和 assignment iterator 串起来，见 `src/java/org/apache/cassandra/repair/autorepair/PrioritizedRepairPlan.java:83-147`。
- `src/java/org/apache/cassandra/repair/autorepair/RepairTokenRangeSplitter.java` 与 `src/java/org/apache/cassandra/repair/autorepair/FixedSplitTokenRangeSplitter.java`：默认 bytes/partition based splitter 和固定份数 splitter，分别覆盖 schedule byte cap、table batching、empty SSTable、canonical SSTable refs、fixed subrange 等场景，见 `src/java/org/apache/cassandra/repair/autorepair/RepairTokenRangeSplitter.java:58-163`、`src/java/org/apache/cassandra/repair/autorepair/RepairTokenRangeSplitter.java:232-335`、`src/java/org/apache/cassandra/repair/autorepair/FixedSplitTokenRangeSplitter.java:39-153`。
- `src/java/org/apache/cassandra/streaming/async/NettyStreamingConnectionFactory.java`、`src/java/org/apache/cassandra/streaming/async/NettyStreamingChannel.java`、`src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java`：Netty streaming connection、control/file channel wrapper、multiplex/semaphore/keepalive，见 `src/java/org/apache/cassandra/streaming/async/NettyStreamingConnectionFactory.java:51-100`、`src/java/org/apache/cassandra/streaming/async/NettyStreamingChannel.java:54-88`、`src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:150-249`。
- `src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java`、`src/java/org/apache/cassandra/net/HandshakeProtocol.java`：internode Initiate/Accept handshake、streaming vs messaging branching、TLS/auth fallback 和 framing negotiation，见 `src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:80-123`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:312-361`、`src/java/org/apache/cassandra/net/HandshakeProtocol.java:42-86`。
- `src/java/org/apache/cassandra/streaming/async/StreamCompressionSerializer.java` 与 `src/java/org/apache/cassandra/db/streaming` 下 reader/writer：uncompressed SSTable stream compression、compressed SSTable chunk transfer 和 entire SSTable component transfer，见 `src/java/org/apache/cassandra/streaming/async/StreamCompressionSerializer.java:34-127`、`src/java/org/apache/cassandra/db/streaming/CassandraStreamWriter.java:76-171`、`src/java/org/apache/cassandra/db/streaming/CassandraCompressedStreamWriter.java:58-141`、`src/java/org/apache/cassandra/db/streaming/CassandraEntireSSTableStreamWriter.java:66-118`。
- `src/java/org/apache/cassandra/streaming/StreamSession.java`、`src/java/org/apache/cassandra/streaming/StreamingState.java`、`src/java/org/apache/cassandra/db/virtual/StreamingVirtualTable.java`：session lifecycle、failure cause/success message state 和 system view 暴露，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:89-142`、`src/java/org/apache/cassandra/streaming/StreamingState.java:47-93`、`src/java/org/apache/cassandra/db/virtual/StreamingVirtualTable.java:37-103`。

## 核心接口

- `src/java/org/apache/cassandra/repair/autorepair/IAutoRepairTokenRangeSplitter.java` 定义 lazy assignment iterator、custom constructor 约定和动态参数读写，见 `src/java/org/apache/cassandra/repair/autorepair/IAutoRepairTokenRangeSplitter.java:27-70`。
- `src/java/org/apache/cassandra/service/AutoRepairServiceMBean.java` 是运维参数入口，允许 runtime 设置 auto-repair enabled、thread count、priority/force host、interval、parallelism、MV repair、splitter 参数和 retry/backoff，见 `src/java/org/apache/cassandra/service/AutoRepairServiceMBean.java:28-78`。
- `src/java/org/apache/cassandra/streaming/StreamingChannel.java` 是 streaming channel 抽象；Netty 实现用 `StreamingDataOutputPlus` 包装 outbound file stream，用 inbound task 处理 control messages，见 `src/java/org/apache/cassandra/streaming/StreamingChannel.java:25-54` 与 `src/java/org/apache/cassandra/streaming/async/NettyStreamingChannel.java:127-189`。
- `src/java/org/apache/cassandra/streaming/StreamingDataOutputPlus.java` 提供 streaming output 与 rate limiter abstraction；zero-copy/TLS fallback 具体路径在 `src/java/org/apache/cassandra/net/AsyncStreamingOutputPlus.java:147-205`。
- `src/java/org/apache/cassandra/streaming/StreamEventHandler.java` 被 `StreamingState` 实现，用于把 session progress/failure 事件落到 virtual table state，见 `src/java/org/apache/cassandra/streaming/StreamingState.java:47-93`。

## 核心数据结构

- `system_distributed.auto_repair_history`：主键 `repair_type, host_id`，记录 `repair_turn`、start/finish timestamp、delete vote hosts、delete timestamp 和 force flag。schema 在 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:185-204`。
- `system_distributed.auto_repair_priority`：按 `repair_type` 保存 priority host set，schema 在 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:199-204`。
- `AutoRepairHistory` 和 `CurrentRepairStatus` 封装单 host history、current ongoing host set、force repair host set、priority set 与本节点历史，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:230-333`。
- `RepairTurn` 是 turn election 的返回语义，区分 not my turn、normal turn、priority turn、force turn、already repairing 等路径，并由 metrics 记录，使用点见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:204-220` 与 `src/java/org/apache/cassandra/metrics/AutoRepairMetrics.java:191-226`。
- `PrioritizedRepairPlan`、`KeyspaceRepairPlan`、`RepairAssignment`、`KeyspaceRepairAssignments` 表示 priority bucket、keyspace/table/range/estimated bytes 和 splitter 输出，见 `src/java/org/apache/cassandra/repair/autorepair/PrioritizedRepairPlan.java:83-147`、`src/java/org/apache/cassandra/repair/autorepair/KeyspaceRepairPlan.java:31-79`、`src/java/org/apache/cassandra/repair/autorepair/RepairAssignment.java:26-74`。
- `SizeEstimate` 由 `AutoRepairUtils.getRangeSizeEstimate()` 从 SSTable refs、metadata cardinality 和 on-disk length 估算；incremental repair 会把 total SSTable size 用作 repair size，以反映后续 anti-compaction 成本，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:1232-1297`。
- Streaming 消息结构由 `StreamMessage`、`StreamInitMessage`、`StreamMessageHeader` 和 `CassandraStreamHeader` 组成；后者包含 format/version、sections、compression info、level、table id、entire SSTable flag、first key 和 component manifest，见 `src/java/org/apache/cassandra/streaming/messages/StreamMessage.java:37-92`、`src/java/org/apache/cassandra/streaming/messages/StreamInitMessage.java:35-77`、`src/java/org/apache/cassandra/streaming/messages/StreamMessageHeader.java:34-89`、`src/java/org/apache/cassandra/db/streaming/CassandraStreamHeader.java:48-160`。
- `CompressionInfo` 和 `ComponentManifest` 区分 compressed SSTable chunk metadata 与 entire SSTable component 列表，见 `src/java/org/apache/cassandra/db/streaming/CompressionInfo.java:38-99` 与 `src/java/org/apache/cassandra/db/streaming/ComponentManifest.java:28-95`。
- `StreamingState` 与 `system_views.streaming` 保留 operation、peers、status、progress、duration、failure_cause、success_message 和 per-session fields，见 `src/java/org/apache/cassandra/streaming/StreamingState.java:198-221` 与 `src/java/org/apache/cassandra/db/virtual/StreamingVirtualTable.java:37-103`。

## 生命周期

Auto-repair scheduler 生命周期：

1. `AutoRepairService.setup()` 检查 JVM property；通过时加载 config 并注册 MBean，见 `src/java/org/apache/cassandra/service/AutoRepairService.java:62-78`。
2. `AutoRepair.setup()` 初始化 `AutoRepairUtils` prepared statements，为 FULL/INCREMENTAL/PREVIEW_REPAIRED 创建 executor、runnable executor、state，并只给 enabled 且 `checkCanRun()` 通过的 repair type 安排 fixed-delay task，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:113-150`。
3. 周期任务 `repair(repairType)` 先检查 type enabled、mixed major version、min version、ignored DC、min interval 和 turn election，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:161-220`。
4. 本节点获得 turn 后，按 keyspace/table 收集可 repair 表，按 table property 和 MV setting 决定是否加入 base table 与 views，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:222-249` 与 `src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:436-478`。
5. `PrioritizedRepairPlan.build()` 计算 priority bucket 和 range bytes，splitter 生成 `KeyspaceRepairAssignments`，随后 `repairKeyspace()` 按 assignment/range 批量提交 `RepairCoordinator` 并按配置 retry/backoff，见 `src/java/org/apache/cassandra/repair/autorepair/PrioritizedRepairPlan.java:83-147` 与 `src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:283-411`。
6. 成功、失败或跳过后，`cleanupAndUpdateStats()` 更新 scheduler stats、node/cluster last repair time、last repair finish time、in-progress flag 和 auto-repair history，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:480-519`。

Streaming connection/session 生命周期：

1. `StreamingMultiplexedChannel.create()` 创建 control channel，启动 `StreamDeserializingTask`，再按需为 file transfer 创建或复用 streaming file channel，见 `src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:150-192`。
2. `NettyStreamingConnectionFactory.connect()` 使用 `OutboundConnectionInitiator.initiateStreaming()` 发起 streaming category handshake；optional SSL 错误可 fallback，见 `src/java/org/apache/cassandra/streaming/async/NettyStreamingConnectionFactory.java:51-85`。
3. Outbound active 后发送 `HandshakeProtocol.Initiate`，Inbound 解码后选择 streaming pipeline，回复 `Accept`，安装 `NettyStreamingChannel` 并启动 stream deserializing task，见 `src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:297-315` 与 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:431-465`。
4. 非文件消息走 control channel；`OutgoingStreamMessage` 由 file transfer executor 获取 semaphore 和 channel 后 serialize，失败会 `session.onError()`，见 `src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:195-273`。
5. 发送侧 `CassandraOutgoingFile.write()` 在 entire/uncompressed/compressed 三条分支之间选择，接收侧 `CassandraIncomingFile.read()` 读 header 后选择对应 reader，见 `src/java/org/apache/cassandra/db/streaming/CassandraOutgoingFile.java:147-177` 与 `src/java/org/apache/cassandra/db/streaming/CassandraIncomingFile.java:68-88`。
6. `StreamSession.closeSession()` 在 completed/failed/aborted 时关闭 receive/transfer task 和 channel；`StreamResultFuture` 在失败 session 上记录 `Stream failed:` 并抛 `StreamException`，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:532-572` 与 `src/java/org/apache/cassandra/streaming/StreamResultFuture.java:235-252`。

## 调用链

Auto-repair 主链：

```text
AutoRepairService.setup
  -> AutoRepair.setup
  -> AutoRepairUtils.setup
  -> AutoRepair.repair(type)
  -> AutoRepairUtils.myTurnToRunRepair
  -> AutoRepair.retrieveTablesToBeRepaired
  -> PrioritizedRepairPlan.build
  -> IAutoRepairTokenRangeSplitter.getRepairAssignments
  -> AutoRepair.repairKeyspace
  -> AutoRepairState.getRepairRunnable
  -> RepairCoordinator.run
  -> AutoRepair.cleanupAndUpdateStats
```

关键锚点：scheduler 创建见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:113-150`，turn election 见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:821-989`，assignment split 见 `src/java/org/apache/cassandra/repair/autorepair/RepairTokenRangeSplitter.java:210-335`，repair runnable 创建见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairState.java:109-121`。

Netty streaming 主链：

```text
StreamingMultiplexedChannel.sendMessage
  -> NettyStreamingConnectionFactory.connect
  -> OutboundConnectionInitiator.initiateStreaming
  -> HandshakeProtocol.Initiate / HandshakeProtocol.Accept
  -> NettyStreamingChannel.acquireOut
  -> StreamMessage.serialize / CassandraOutgoingFile.write
  -> CassandraIncomingFile.read
  -> StreamSession.receive
```

关键锚点：multiplex/control/file channel 分派见 `src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:195-249`，outbound handshake result 见 `src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:334-379`，inbound streaming pipeline 见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:431-465`，receive ack/metrics 见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1070-1089`。

Repair/MV 交叉边界：

- Auto-repair 会在 `retrieveTablesToBeRepaired()` 中先看 base table 的 `autoRepair.repairEnabled(repairType)`，再按 `materialized_view_repair_enabled` 把 view table 加入同一 keyspace/table list，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:436-478` 与 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:1189-1203`。
- Incremental auto-repair 的全局 gate 更保守：如果 auto-repair MV repair 和全局 `materialized_views_on_repair_enabled` 同时打开会拒绝，CDC repair replay 同理，见 `src/java/org/apache/cassandra/service/AutoRepairService.java:85-98`。
- 普通 streaming receive 到达目标节点后，若 CDC/MV/stream-to-memtable 要求走 write path，receiver 会 apply mutation、flush 并 abort streaming transaction；否则 entire SSTable 分支会先验证 SSTable-attached index 再 add SSTables。该边界已在 `research/module-cache-index-view-vector-import-repair.md` 细化，源码锚点见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:185-291`。

## 配置项

- `auto_repair` YAML 注释说明该功能需要 JVM property 开启，且可配置 global/per-type overrides、min interval、token splitter、bytes/max schedule 等参数，见 `conf/cassandra.yaml:2336-2405`。
- `AutoRepairConfig` 默认值覆盖 `enabled=false`、`repair_by_keyspace=true`、`number_of_repair_threads=1`、parallel count/percentage、parallel replica 开关、ignored DCs、primary ranges only、force new node、table max repair time、MV repair、session timeout、min interval 和 splitter/retry defaults，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairConfig.java:461-545`。
- `AUTOREPAIR_ENABLE` 决定 scheduler/schema/MBean 是否真正暴露；`isAutoRepairSchedulingEnabled()` 同时要求 JVM property 和 config enabled，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairConfig.java:143-168`。
- `stream_entire_sstables` 默认启用，但 YAML 注释说明 internode encryption 会自动禁用 entire SSTable streaming，见 `conf/cassandra.yaml:1269-1279`。
- 普通 stream、inter-DC stream、entire SSTable stream 的 outbound throughput 分开配置，见 `conf/cassandra.yaml:1281-1304` 与 `src/java/org/apache/cassandra/streaming/StreamManager.java:61-95`。
- `internode_streaming_tcp_user_timeout`、`streaming_keep_alive_period`、`streaming_connections_per_host` 控制 socket timeout、keepalive 和 per-host session/channel 数，见 `conf/cassandra.yaml:1365-1368`、`conf/cassandra.yaml:1410-1424`。
- `streaming_state_expires`、`streaming_state_size`、`streaming_stats_enabled` 控制 streaming virtual table state 保留和统计开关，见 `conf/cassandra.yaml:1426-1434`。
- `internode_compression` 控制 messaging framing 的 LZ4/CRC negotiation，不等于 SSTable stream transfer compression，配置位置见 `conf/cassandra.yaml:1730-1742`，frame 分支见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:467-526`。
- `materialized_views_enabled` 与 `materialized_views_on_repair_enabled` 影响 repair/MV replay 和 auto-repair gate，见 `conf/cassandra.yaml:1979-1988`。

## Metrics

- Auto-repair metrics 包含 longest unrepaired、total/finished/skipped/failed token ranges、bytes already repaired、schedule plan counts、turn gauges、repair delayed by replica/schedule counters 等，见 `src/java/org/apache/cassandra/metrics/AutoRepairMetrics.java:34-188`。
- Turn election 的结果会通过 `AutoRepairState.recordTurn()` 转到 metrics，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairState.java:247-250` 与 `src/java/org/apache/cassandra/metrics/AutoRepairMetrics.java:191-226`。
- Replica/schedule contention 会分别递增 `repairDelayedByReplica` 与 `repairDelayedBySchedule`，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:631-707` 与 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:719-780`。
- Streaming global/per-peer metrics 包含 incoming/outgoing bytes、repair outgoing bytes/SSTables、incoming process timer、entire/partial streamed-in counters，见 `src/java/org/apache/cassandra/metrics/StreamingMetrics.java:42-93`。
- `StreamSession.streamSent()` 更新 outgoing/repair metrics 并安排 transfer timeout；`StreamSession.receive()` 更新 incoming metrics、发送 `ReceivedMessage` 并计时 receiver processing，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1039-1056` 与 `src/java/org/apache/cassandra/streaming/StreamSession.java:1070-1089`。
- `system_views.streaming` 暴露 stream state、failure cause、success message 和 session progress；数据来自 `StreamManager` 中的 active/retained state，见 `src/java/org/apache/cassandra/db/virtual/StreamingVirtualTable.java:67-103`。

## 日志

- Auto-repair 过早运行、assignment 跳过、max schedule cap、replica contention 会有日志或 metrics。`RepairTokenRangeSplitter.filterRepairAssignments()` 对超过 schedule byte cap 的 assignment 记录 warn/info，见 `src/java/org/apache/cassandra/repair/autorepair/RepairTokenRangeSplitter.java:345-413`。
- Auto-repair 发现候选节点与正在 repair 的 replica 重叠时会记录选择/跳过原因并更新 delayed metrics，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:719-780`。
- Outbound handshake 失败会 fail promise 并记录 `Failed to handshake`；handler 被移除时如果结果 promise 已完成会关闭 channel，见 `src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:382-435`。
- Inbound streaming pipeline 安装完成会记录 peer、version、framing、encryption 的 established streaming connection 日志，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:455-465`。
- Streaming failure 最终通过 `StreamResultFuture` 打出 `Stream failed:`，并通过 `StreamSession.onError()` 针对 EOF/ClosedChannel、SocketTimeout 和普通异常分别生成 failure cause/日志，见 `src/java/org/apache/cassandra/streaming/StreamResultFuture.java:235-252` 与 `src/java/org/apache/cassandra/streaming/StreamSession.java:700-763`。

## 运维关注点

- 启用 auto-repair 前必须明确 JVM property 和 YAML/config。property 影响 system_distributed auto-repair 表和 schema `auto_repair` 列；分布式测试覆盖了开启后建表、重启后启用、启用后再关闭的 schema 行为，见 `test/distributed/org/apache/cassandra/distributed/test/repair/AutoRepairFlagToggleTest.java:35-111`。
- Auto-repair 排障先看 type 是否 enabled、是否跨 mixed major version 被禁、节点版本是否低于 gate、是否在 ignored DC、是否 min interval 未到、是否被 replica/schedule contention 延迟，入口见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:161-220` 与 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:440-491`。
- 需要定期检查 `system_distributed.auto_repair_history` 中长期 running 的 host、force repair flag、priority host set 和 delete_hosts vote。历史/priority 读写接口集中在 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:335-430` 与 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:1064-1146`。
- Splitter 调参要同时看 `bytes_per_assignment`、`partitions_per_assignment`、`max_tables_per_assignment`、`max_bytes_per_schedule`。对 full repair，schedule cap 会让部分 assignment 本轮不修；对 incremental，估算偏向反映 anti-compaction 成本，见 `src/java/org/apache/cassandra/repair/autorepair/RepairTokenRangeSplitter.java:108-163` 与 `src/java/org/apache/cassandra/repair/autorepair/RepairTokenRangeSplitter.java:345-413`。
- Streaming 排障先区分握手/TLS/auth、control channel、file transfer semaphore、receiver ingest、disk/compaction guard 五类。control/file channel 与 semaphore 见 `src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:74-89` 与 `src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:346-375`。
- `internode_compression` 只解释 messaging frame path；对 streaming 文件内容，应看 SSTable 是否本身压缩、是否 entire SSTable、是否 TLS、是否走 `StreamCompressionSerializer`。三类 I/O path 见 `src/java/org/apache/cassandra/db/streaming/package-info.java:20-50`。
- Streaming 状态可从 `nodetool netstats`、metrics 和 `system_views.streaming` 交叉确认；Netstats bootstrap/repair 测试覆盖了 entire/partial 和 table compression 开关，见 `test/distributed/org/apache/cassandra/distributed/test/AbstractNetstatsBootstrapStreaming.java:46-88` 与 `test/distributed/org/apache/cassandra/distributed/test/NetstatsRepairStreamingTest.java:38-86`。

## 性能瓶颈

- Auto-repair range size estimate 需要遍历 canonical SSTable refs、metadata cardinality 和 on-disk size；这会把调度器的计划成本绑定到 SSTable 数量和 metadata 完整性，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:1256-1297`。
- `repair_by_keyspace=true` 会把同一 range 的多表 assignment 尽量合并，降低 repair command 数量；table-by-table 模式更细但放大 plan/command 数。实现见 `src/java/org/apache/cassandra/repair/autorepair/RepairTokenRangeSplitter.java:259-335`。
- `allow_parallel_replica_repair=false` 会保护热 replica，但在多 schedule 或 RF 高时可能让 eligible host 大量等待；delayed metrics 能看出瓶颈来自 replica 还是 schedule，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:631-780`。
- Streaming file transfer 受全局 semaphore、per-thread channel reuse、rate limiter、TCP backpressure、ACK timeout 和 receiver write path 影响，见 `src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:275-395` 与 `src/java/org/apache/cassandra/streaming/StreamTransferTask.java:107-120`。
- Uncompressed SSTable stream compression 节省网络但消耗 LZ4 CPU 和 direct buffer；compressed SSTable chunk transfer 减少重复压缩；entire SSTable zero-copy 省 CPU 但 TLS/非整表 section 会回退，见 `src/java/org/apache/cassandra/streaming/async/StreamCompressionSerializer.java:57-127`、`src/java/org/apache/cassandra/db/streaming/CassandraCompressedStreamWriter.java:58-141`、`src/java/org/apache/cassandra/net/AsyncStreamingOutputPlus.java:147-205`。
- `system_views.streaming` 保留状态有 size/TTL 上限；如果 failure storm 超过 `streaming_state_size` 或保留时间，virtual table 只能看到近期状态，配置见 `conf/cassandra.yaml:1426-1434`。

## 常见故障

- Auto-repair 不启动：JVM property 未启、global enabled 为 false、per-type enabled 为 false、`AutoRepairService.checkCanRun()` 拒绝 incremental MV/CDC replay、mixed major version disabled 或节点低于 min version gate。相关检查见 `src/java/org/apache/cassandra/service/AutoRepairService.java:62-98`、`src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:161-181`、`src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:440-491`。
- Auto-repair 一直不是本节点 turn：history 中其他 host 仍 running、parallel repair cap 已满、本节点 priority/force 状态不存在或 host 已不在 ring、replica overlap 被过滤。turn election 细节见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:821-989`。
- Full auto-repair 一直修不完整：`max_bytes_per_schedule` 对某些 range/table assignment 直接过滤，full repair 会记录 warning，因为被过滤 range 本 schedule 不会修，见 `src/java/org/apache/cassandra/repair/autorepair/RepairTokenRangeSplitter.java:345-413`。
- Auto-repair MV 预期不生效：base table 的 table property 未启用该 repair type、MV repair per-type config 未开、或 incremental + 全局 MV repair replay gate 拒绝 scheduler，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:436-478` 与 `src/java/org/apache/cassandra/service/AutoRepairService.java:85-98`。
- Streaming 握手失败：TLS/client auth requirement、optional SSL fallback、version/framing negotiation 或 timeout。outbound/inbound handshake 入口见 `src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:220-239` 与 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:100-140`。
- Streaming timeout 或中途断开：transfer ACK 超时触发 `StreamTransferTask.timeout()`，EOF/ClosedChannel 在 final message 前会变成 session failure，见 `src/java/org/apache/cassandra/streaming/StreamTransferTask.java:107-120` 与 `src/java/org/apache/cassandra/streaming/StreamSession.java:700-743`。
- Receiver 侧失败：disk 空间、pending compaction、schema drop、preview session 收到文件、SAI validation/build failure、transaction log abort 都会导致 stream/repair failure。disk/compaction guard 见 `src/java/org/apache/cassandra/streaming/StreamSession.java:795-842`，receiver transaction path 见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:185-291`。

## 测试用例

- Auto-repair unit tests 覆盖 setup guard、CDC/MV gate、NTS keyspace selection、config defaults/overrides、state metrics、history/status/priority/force host、ring filtering、delete vote、min version gate、priority plan 和 range splitter 参数/merge/filter。核心文件包括 `test/unit/org/apache/cassandra/repair/autorepair/AutoRepairTest.java:66-161`、`test/unit/org/apache/cassandra/repair/autorepair/AutoRepairConfigTest.java:80-499`、`test/unit/org/apache/cassandra/repair/autorepair/AutoRepairStateTest.java:78-320`、`test/unit/org/apache/cassandra/repair/autorepair/AutoRepairUtilsTest.java:93-689`、`test/unit/org/apache/cassandra/repair/autorepair/PrioritizedRepairPlanTest.java:52-181`、`test/unit/org/apache/cassandra/repair/autorepair/RepairTokenRangeSplitterTest.java:104-535`。
- Auto-repair distributed tests 覆盖 scheduler 实际运行、full/incremental replica contention、跨 schedule contention、stats bytes/plan 计数、table property/schema toggle。核心文件包括 `test/distributed/org/apache/cassandra/distributed/test/repair/AutoRepairSchedulerTest.java:63-185`、`test/distributed/org/apache/cassandra/distributed/test/repair/AutoRepairSchedulerDisallowParallelReplicaRepairAcrossSchedulesTest.java:53-133`、`test/distributed/org/apache/cassandra/distributed/test/repair/AutoRepairSchedulerStatsHelper.java:62-210`、`test/distributed/org/apache/cassandra/distributed/test/repair/AutoRepairTablePropertyTest.java:38-157`、`test/distributed/org/apache/cassandra/distributed/test/repair/AutoRepairFlagToggleTest.java:35-111`。
- Streaming async unit tests 覆盖 transfer compression roundtrip、ReadableByteChannel path、file semaphore acquire/release、control send failure、inbound object/session lookup，见 `test/unit/org/apache/cassandra/streaming/async/StreamCompressionSerializerTest.java:74-112`、`test/unit/org/apache/cassandra/streaming/async/StreamingMultiplexedChannelTest.java:83-152`、`test/unit/org/apache/cassandra/streaming/async/StreamingInboundHandlerTest.java:90-146`。
- Long streaming 覆盖 SSTable compression streaming 与 stream compression streaming 的大数据量 loader/compaction path，见 `test/long/org/apache/cassandra/streaming/LongStreamingTest.java:66-180`。

Streaming failure-injection matrix：

| 场景 | 覆盖 |
| --- | --- |
| Repair streaming zero-copy session failed | `test/distributed/org/apache/cassandra/distributed/test/streaming/StreamFailureLogsFailureDueToSessionFailedTest.java:27-31` |
| Repair streaming non-zero-copy EOF in middle | `test/distributed/org/apache/cassandra/distributed/test/streaming/StreamFailureLogsFailureInTheMiddleWithEOFTest.java:27-31` |
| Repair streaming zero-copy unknown receiver exception | `test/distributed/org/apache/cassandra/distributed/test/streaming/StreamFailureLogsFailureInTheMiddleWithUnknownTest.java:27-31` |
| Transfer task timeout | `test/distributed/org/apache/cassandra/distributed/test/streaming/StreamFailureLogsFailureDueToSessionTimeoutTest.java:50-180` |
| Receiver abort while incoming file is read | `test/distributed/org/apache/cassandra/distributed/test/streaming/StreamFailedWhileReceivingTest.java:63-205` |
| Control channel close during receive | `test/distributed/org/apache/cassandra/distributed/test/streaming/StreamDisconnectedWhileReceivingTest.java:51-114` |
| Close in middle plus bootstrap failure log/no shutdown | `test/distributed/org/apache/cassandra/distributed/test/streaming/StreamCloseInMiddleTest.java:50-195` |
| Prepare failure before streaming | `test/distributed/org/apache/cassandra/distributed/test/StreamPrepareFailTest.java:41-79` |
| Disk/compaction guard failure | `test/distributed/org/apache/cassandra/distributed/test/StreamsDiskSpaceTest.java:46-118` |

- Failure log assertions share `AbstractStreamFailureLogs`, which injects `RuntimeException("TEST")` or `ClosedChannelException` while `CassandraIncomingFile.read()` is running, then checks WARN `Stream failed:` and `system_views.streaming.failure_cause`，见 `test/distributed/org/apache/cassandra/distributed/test/streaming/AbstractStreamFailureLogs.java:56-160`。
- Netstats/bootstrap/repair streaming tests cover entire vs partial, table compression enabled/disabled, and throttling config visibility，见 `test/distributed/org/apache/cassandra/distributed/test/NetstatsBootstrapWithEntireSSTablesCompressionStreamingTest.java:23-42`、`test/distributed/org/apache/cassandra/distributed/test/NetstatsBootstrapWithoutEntireSSTablesCompressionStreamingTest.java:23-36`、`test/distributed/org/apache/cassandra/distributed/test/AbstractNetstatsStreaming.java:91-118`、`test/distributed/org/apache/cassandra/distributed/test/NetstatsRepairStreamingTest.java:38-86`。
- 当前测试缺口：缺少直接验证 repair+MV 数据正确性的 distributed 场景；缺少 transient repair/streaming 的失败注入矩阵；缺少 mixed-version/TLS/`internode_compression` 组合下的 streaming handshake/file transfer 兼容性矩阵；Netty handshake 本身主要通过 streaming integration 间接覆盖，尚无独立 exhaustive negotiation dtest。transient repair sync direction、owned-range/pending-range validation、generic stream failure coverage 和 distributed transient gap 已在 `research/module-repair-streaming-transient-fault-coverage.md` 细化。
