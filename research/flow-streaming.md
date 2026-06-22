# Flow: Streaming

## 目标

Streaming 链路解释 `StreamPlan` 如何把 range/file request 转换成 peer sessions，如何完成 prepare handshake、文件传输、ACK、receiver ingest 和 session completion。

## 文字版调用图

Repair/Bootstrap/Decommission 等调用方：

```text
caller builds StreamPlan(operation)
  -> requestRanges(from, keyspace, fullRanges, transientRanges, tables)
     -> StreamCoordinator.getOrCreateOutboundSession(from)
     -> StreamSession.addStreamRequest(...)
  -> transferRanges(to, keyspace, replicas, tables)
     -> StreamCoordinator.getOrCreateOutboundSession(to)
     -> StreamSession.addTransferRanges(...)
        -> optional flushSSTables(...)
        -> getOutgoingStreamsForRanges(...)
        -> addTransferStreams(...)
           -> per table StreamTransferTask.addTransferStream(...)
  -> execute()
     -> StreamResultFuture.createInitiator(...)
        -> session.init(future)
        -> coordinator.connect(future)
```

Prepare handshake:

```text
initiator StreamSession.onInitializationComplete()
  -> state PREPARING
  -> send PREPARE_SYN(requests, transfer summaries)

follower StreamSession.messageReceived(PREPARE_SYN)
  -> prepare(...)
     -> prepareAsync(requests, summaries)
        -> check disk space and compactions for REPAIR
        -> processStreamRequests(...)
           -> validate requested ranges are owned
           -> addTransferRanges(..., flush=true)
        -> prepareReceiving(summaries)
        -> send PREPARE_SYNACK(transfer summaries)
        -> maybeCompleted()

initiator messageReceived(PREPARE_SYNACK)
  -> prepareSynAck(...)
     -> prepare receiving tasks from summaries
     -> send PREPARE_ACK if follower can start sending
```

Streaming phase:

```text
StreamSession.startStreamingFiles(direction)
  -> state STREAMING
  -> for each StreamTransferTask
     -> getFileMessages()
     -> for each OutgoingStreamMessage
        -> add session info to header
        -> channel.sendMessage(...)
           -> StreamingMultiplexedChannel.sendMessage(...)
              -> FileStreamTask
                 -> acquire fileTransferSemaphore
                 -> write header + stream content
        -> StreamSession.streamSent(...)
           -> update outgoing metrics
           -> schedule ACK timeout

receiver StreamSession.messageReceived(STREAM)
  -> receive(IncomingStreamMessage)
     -> reject preview session file receive
     -> update incoming metrics
     -> send ReceivedMessage(tableId, sequenceNumber)
     -> StreamReceiveTask.received(stream)
        -> receiver.received(stream)
        -> if all files received: async OnCompletionRunnable
           -> receiver.finished()
           -> session.taskCompleted(receiveTask)
```

ACK and completion:

```text
sender StreamSession.messageReceived(RECEIVED)
  -> received(tableId, sequenceNumber)
     -> StreamTransferTask.complete(sequenceNumber)
        -> cancel timeout
        -> OutgoingStreamMessage.complete()
        -> if no streams left: session.taskCompleted(transferTask)

StreamSession.maybeCompleted()
  -> if receivers and transfers empty
     -> follower: state COMPLETE, send CompleteMessage, close
     -> initiator: state WAIT_COMPLETE

initiator messageReceived(COMPLETE)
  -> complete()
     -> if already WAIT_COMPLETE close COMPLETE
     -> else state WAIT_COMPLETE
```

Failure paths:

```text
outgoing stream ACK timeout
  -> StreamTransferTask.timeout(sequenceNumber)
     -> session.sessionTimeout()
        -> close session FAILED

remote sends SESSION_FAILED
  -> StreamSession.sessionFailed()
     -> close session FAILED

receiver error
  -> StreamSession.onError(...)
     -> send SESSION_FAILED
     -> close session FAILED
```

## 关键源码锚点

| 阶段 | 文件/方法 |
|---|---|
| StreamPlan 构造 | `StreamPlan`：`src/java/org/apache/cassandra/streaming/StreamPlan.java:39-70` |
| request ranges | `StreamPlan.requestRanges()`：`src/java/org/apache/cassandra/streaming/StreamPlan.java:91-114` |
| transfer ranges | `StreamPlan.transferRanges()`：`src/java/org/apache/cassandra/streaming/StreamPlan.java:126-130` |
| execute | `StreamPlan.execute()`：`src/java/org/apache/cassandra/streaming/StreamPlan.java:190-198` |
| initiator future | `StreamResultFuture.createInitiator()`：`src/java/org/apache/cassandra/streaming/StreamResultFuture.java:88-108` |
| coordinator connect | `StreamCoordinator.connect()`：`src/java/org/apache/cassandra/streaming/StreamCoordinator.java:101-107` |
| multi-connection bucketing | `StreamCoordinator.transferStreams()`：`src/java/org/apache/cassandra/streaming/StreamCoordinator.java:196-215` |
| add stream request | `StreamSession.addStreamRequest()`：`src/java/org/apache/cassandra/streaming/StreamSession.java:428-435` |
| add transfer ranges | `StreamSession.addTransferRanges()`：`src/java/org/apache/cassandra/streaming/StreamSession.java:445-457` |
| transfer task creation | `StreamSession.addTransferStreams()`：`src/java/org/apache/cassandra/streaming/StreamSession.java:508-523` |
| message dispatch | `StreamSession.messageReceived()`：`src/java/org/apache/cassandra/streaming/StreamSession.java:635-680` |
| init complete | `StreamSession.onInitializationComplete()`：`src/java/org/apache/cassandra/streaming/StreamSession.java:682-697` |
| prepare async | `StreamSession.prepareAsync()`：`src/java/org/apache/cassandra/streaming/StreamSession.java:791-822` |
| stream request range check | `StreamSession.processStreamRequests()`：`src/java/org/apache/cassandra/streaming/StreamSession.java:1020-1031` |
| stream sent metrics/timeout | `StreamSession.streamSent()`：`src/java/org/apache/cassandra/streaming/StreamSession.java:1039-1056` |
| receive stream | `StreamSession.receive()`：`src/java/org/apache/cassandra/streaming/StreamSession.java:1070-1082` |
| session completion | `StreamSession.complete()` / `maybeCompleted()`：`src/java/org/apache/cassandra/streaming/StreamSession.java:1121-1169` |
| initiator wait/complete | `StreamSession.initiatorCompleteOrWait()`：`src/java/org/apache/cassandra/streaming/StreamSession.java:1171-1179` |
| remote failure | `StreamSession.sessionFailed()`：`src/java/org/apache/cassandra/streaming/StreamSession.java:1182-1190` |
| outgoing stream task | `StreamTransferTask.addTransferStream()`：`src/java/org/apache/cassandra/streaming/StreamTransferTask.java:65-73` |
| outgoing ACK complete | `StreamTransferTask.complete()`：`src/java/org/apache/cassandra/streaming/StreamTransferTask.java:85-100` |
| outgoing ACK timeout | `StreamTransferTask.timeout()`：`src/java/org/apache/cassandra/streaming/StreamTransferTask.java:107-120` |
| incoming receive task | `StreamReceiveTask.received()`：`src/java/org/apache/cassandra/streaming/StreamReceiveTask.java:72-97` |
| receiver finish | `StreamReceiveTask.OnCompletionRunnable.run()`：`src/java/org/apache/cassandra/streaming/StreamReceiveTask.java:125-149` |
| channel split | `StreamingMultiplexedChannel` class doc：`src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:74-89` |
| control message send | `StreamingMultiplexedChannel.sendControlMessage()`：`src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:195-207` |
| file message send | `StreamingMultiplexedChannel.sendMessage()`：`src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:210-224` |
| stream message types | `StreamMessage.Type`：`src/java/org/apache/cassandra/streaming/messages/StreamMessage.java:61-72` |
| decommission caller | `StorageService.streamRanges()`：`src/java/org/apache/cassandra/service/StorageService.java:6375-6430` |

## 协议语义

- `StreamSession` 源码注释把协议分为 session init、prepare、streaming、completion 四个阶段，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:100-157`。
- 控制消息通过标准 internode messaging/控制 channel，实际文件通过 streaming connection 发送，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:159-162`、`src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:74-111`。
- `PREPARE_SYN` 同时包含本端将发送的 summaries 和希望对端发送回来的 requests，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:104-115`。
- `OutgoingStreamMessage` 发送后，sender 等待 `ReceivedMessage` ACK；每个 sequence number 都有 timeout，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1039-1056`。
- Receiver 收到所有 files 后不是立即完成 session，而是异步执行 `receiver.finished()`，让 CFS ingest、二级索引/MV build 等收尾逻辑完成，见 `src/java/org/apache/cassandra/streaming/StreamReceiveTask.java:116-149`。

## 调用方差异

- Repair local sync 使用 `StreamOperation.REPAIR`，pending repair 非空时不 flush，见 `src/java/org/apache/cassandra/repair/LocalSyncTask.java:80-103`。
- Repair remote sync 在接收 `SYNC_REQ` 的节点上构造 `StreamingRepairTask`，成功/失败后发 `SYNC_RSP` 给 initiator，见 `src/java/org/apache/cassandra/repair/StreamingRepairTask.java:82-134`。
- Decommission/unbootstrap 用 `StreamOperation.DECOMMISSION`，对每个目标 endpoint 调 `transferRanges()`，见 `src/java/org/apache/cassandra/service/StorageService.java:6410-6429`。
- Bootstrap 在 startup 文档中已覆盖入口，本质也是构建 `StreamPlan` 后 `requestRanges()` + `execute()`。

## 配置与观测

- `streaming_connections_per_host` 影响 `StreamCoordinator` 每个 peer 的 session 数，定义见 `src/java/org/apache/cassandra/config/Config.java:165`。
- `streaming_keep_alive_period` 控制 streaming keep-alive 周期，定义见 `src/java/org/apache/cassandra/config/Config.java:166-167`。
- `stream_transfer_task_timeout` 控制 ACK timeout，使用见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1051-1056`。
- `stream_throughput_outbound` 与 `inter_dc_stream_throughput_outbound` 是普通 streaming 限速，定义见 `src/java/org/apache/cassandra/config/Config.java:361-364`。
- `entire_sstable_stream_throughput_outbound` 与 `entire_sstable_inter_dc_stream_throughput_outbound` 是 entire SSTable streaming 限速，定义见 `src/java/org/apache/cassandra/config/Config.java:366-367`。
- `streaming_slow_events_log_timeout` 被 `StreamResultFuture` 用于 slow event 日志阈值，见 `src/java/org/apache/cassandra/streaming/StreamResultFuture.java:57-62`。
- `StreamingMetrics.totalIncomingBytes` / `totalOutgoingBytes` 在 receive/streamSent 中更新，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1039-1056`、`src/java/org/apache/cassandra/streaming/StreamSession.java:1077-1082`。

## 排查路径

1. 没有任何 session：检查 `StreamPlan` 是否真的添加了 request/transfer；没有 active sessions 时 `StreamResultFuture` 会立即 success，见 `src/java/org/apache/cassandra/streaming/StreamResultFuture.java:77-80`。
2. Prepare 阶段失败：看 range ownership 校验、repair disk/compaction 检查、schema/table 是否存在，入口见 `src/java/org/apache/cassandra/streaming/StreamSession.java:791-822`。
3. 文件发送慢：看 `StreamingMultiplexedChannel.FileStreamTask` 是否等待 file transfer semaphore，日志入口见 `src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:356-369`。
4. ACK timeout：检查 `stream_transfer_task_timeout`、网络连接、receiver 是否完成 ingest；timeout 入口见 `src/java/org/apache/cassandra/streaming/StreamTransferTask.java:107-120`。
5. Receiver 收到文件但 session 不完成：检查 `StreamReceiveTask.OnCompletionRunnable` 中 `receiver.finished()` 是否卡在 CFS ingest、index/MV build 或 schema dropped 分支，见 `src/java/org/apache/cassandra/streaming/StreamReceiveTask.java:125-149`。
6. Preview repair 出现 file receive：这是非法路径，`StreamSession.receive()` 会直接抛异常，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1070-1075`。

## 测试用例

- `test/unit/org/apache/cassandra/streaming/StreamingTransferTest.java`
- `test/unit/org/apache/cassandra/streaming/StreamTransferTaskTest.java`
- `test/unit/org/apache/cassandra/streaming/StreamSessionTest.java`
- `test/unit/org/apache/cassandra/streaming/StreamSessionOwnedRangesTest.java`
- `test/unit/org/apache/cassandra/streaming/StreamManagerTest.java`
- `test/unit/org/apache/cassandra/streaming/StreamRateLimiterTest.java`
- `test/unit/org/apache/cassandra/streaming/EntireSSTableStreamingCorrectFilesCountTest.java`
- `test/unit/org/apache/cassandra/streaming/async/StreamingMultiplexedChannelTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/streaming/RebuildStreamingTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/streaming/StreamFailureLogsFailureDueToSessionTimeoutTest.java`
