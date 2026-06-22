# Streaming Transfer Compatibility Matrix

本文补齐 Repair/Streaming 第五轮源码侧缺口：mixed-version/TLS/`internode_compression` 组合下的 streaming transfer compatibility。它不重复 `module-repair-streaming-autorepair-netty.md` 的 auto-repair 与 generic failure matrix，而是把 streaming connection handshake、TLS optional fallback、messaging frame compression、SSTable payload compression、zero-copy/TLS fallback、reader/writer/observability 和当前测试缺口放在一个矩阵里。

## 结论

- Streaming 连接复用 internode handshake，但不是普通 messaging pipeline。`HandshakeProtocol.Initiate` 用 MOD bit 标记 streaming，inbound streaming pipeline 要求 `Framing.UNPROTECTED`，随后替换成 `NettyStreamingChannel` 和 `StreamDeserializingTask`，见 `src/java/org/apache/cassandra/net/HandshakeProtocol.java:55-85`、`src/java/org/apache/cassandra/net/HandshakeProtocol.java:107-120`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:431-465`。
- `internode_compression` 只决定 messaging pipeline 的 LZ4/CRC frame codec。streaming pipeline 不安装 `FrameDecoderLZ4`/`FrameDecoderCrc`；文件 payload 压缩由 `StreamCompressionSerializer` 或 SSTable table-compression 元数据决定，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:467-526`、`src/java/org/apache/cassandra/streaming/async/StreamCompressionSerializer.java:34-127`。
- TLS 影响 streaming I/O path。`AsyncStreamingOutputPlus.writeFileToChannel()` 在 pipeline 有 `SslHandler` 时读入 64 KiB user-space buffer，否则 compressed entire SSTable 可走 zero-copy `FileRegion`，见 `src/java/org/apache/cassandra/net/AsyncStreamingOutputPlus.java:147-166` 与 `src/java/org/apache/cassandra/db/streaming/package-info.java:20-50`。
- 当前测试覆盖了 stream compression serializer、file semaphore/control failure、entire vs partial、table compression on/off、netstats、`system_views.streaming`、generic stream failure logs 和普通 internode TLS；但没有一个 distributed/upgrade 场景同时覆盖 mixed-version、TLS、`internode_compression` 和 streaming file transfer。

## Compatibility Matrix

| 场景 ID | 源码合同 | 现有测试证据 | 缺口判断 |
|---|---|---|---|
| `streaming_handshake_framing_contract` | `HandshakeProtocol.Initiate.encodeFlags()` 对 streaming 连接设置 MOD bit，framing bits 与 version bounds 同包发送；inbound streaming path `assert initiate.framing == Framing.UNPROTECTED`，见 `src/java/org/apache/cassandra/net/HandshakeProtocol.java:55-85`、`src/java/org/apache/cassandra/net/HandshakeProtocol.java:107-120`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:431-465` | `test/unit/org/apache/cassandra/net/HandshakeTest.java:230-335` 覆盖 optional TLS fallback 的普通 messaging connection | 没有独立 streaming handshake negotiation exhaustive test |
| `streaming_ssl_optional_fallback_contract` | `NettyStreamingConnectionFactory.connect()` 在 encryption optional 时尝试 `SslFallbackConnectionType.values()`，只有 SSL 相关错误才 fallback，见 `src/java/org/apache/cassandra/streaming/async/NettyStreamingConnectionFactory.java:51-85`；outbound pipeline 按 `SERVER_CONFIG`/`SSL`/`MTLS` 装 `SslHandler`，见 `src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:208-239` | `HandshakeTest.testOutboundConnectionDoesntFallbackWhenErrorIsNotSSLRelated()` 与 fallback helper 证明普通 outbound 连接逻辑，见 `test/unit/org/apache/cassandra/net/HandshakeTest.java:239-335` | streaming path 复用代码但缺少 direct streaming optional-TLS dtest |
| `streaming_inbound_tls_policy_contract` | inbound initializer 在 `UNENCRYPTED` 下装 `RejectSslHandler`，`OPTIONAL` 下装 `OptionalSslHandler`，`ENCRYPTED` 下装 `SslHandler`，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:117-132` | `InternodeEncryptionOptionsTest.allInternodeEncryptionEstablishedTest()` 只证明 encrypted internode outbound view 成立，见 `test/distributed/org/apache/cassandra/distributed/test/InternodeEncryptionOptionsTest.java:197-218` | 不是 streaming transfer 场景 |
| `streaming_control_file_channel_contract` | `StreamingMultiplexedChannel` 用 control channel 发送普通 stream messages，用 file transfer executor 给 `OutgoingStreamMessage` 建 file channel；`NettyStreamingChannel.acquireOut()` 防止一个 channel 同时传多文件，见 `src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:74-89`、`src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:210-224`、`src/java/org/apache/cassandra/streaming/async/NettyStreamingChannel.java:54-88` | `StreamingMultiplexedChannelTest.FileStreamTask_BadChannelAttr()`、`FileStreamTask_HappyPath()`、`onControlMessageComplete_Exception()` 覆盖 attr、permit 释放和控制消息失败，见 `test/unit/org/apache/cassandra/streaming/async/StreamingMultiplexedChannelTest.java:83-152` | unit 覆盖足够，缺 distributed TLS/mixed-version 组合 |
| `streaming_file_semaphore_keepalive_contract` | `StreamingMultiplexedChannel.FileStreamTask.run()` 获取 file transfer semaphore，异常时 `session.onError()`，等待 permit 时周期性记录日志，见 `src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java:307-375` | `StreamingMultiplexedChannelTest.FileStreamTask_acquirePermit_closed()`、`FileStreamTask_acquirePermit_HapppyPath()` 覆盖 permit 基线，见 `test/unit/org/apache/cassandra/streaming/async/StreamingMultiplexedChannelTest.java:83-99` | 没有高并发 file permit + TLS + mixed-version dtest |
| `streaming_tls_zero_copy_fallback_contract` | entire SSTable writer 逐 component 调 `out.writeFileToChannel()`；有 `SslHandler` 时 user-space 64 KiB buffer，无 TLS 时 zero-copy，见 `src/java/org/apache/cassandra/db/streaming/CassandraEntireSSTableStreamWriter.java:66-109`、`src/java/org/apache/cassandra/net/AsyncStreamingOutputPlus.java:147-166` | `AsyncStreamingOutputPlusTest.testSuccess()` 覆盖 buffer flush 基线，见 `test/unit/org/apache/cassandra/net/AsyncStreamingOutputPlusTest.java:48-115`；`EntireSSTableStreamingCorrectFilesCountTest` 覆盖 entire file count，见 `test/unit/org/apache/cassandra/streaming/EntireSSTableStreamingCorrectFilesCountTest.java:117-142` | 没有 TLS 下 entire SSTable fallback 的 distributed assertion |
| `streaming_internode_compression_boundary` | messaging pipeline 依据 `Framing.LZ4`/`CRC` 安装 frame decoder；streaming pipeline 不走 frame decoder 且 inbound streaming assert unprotected，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:431-526`；`internode_compression` 默认见 `conf/cassandra.yaml:1730-1742`，getter 见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4039-4046` | `test/distributed/org/apache/cassandra/distributed/test/JVMDTestTest.java:119` 只触碰 `internode_compression` 配置 | 没有 streaming + `internode_compression` dtest |
| `streaming_stream_compression_format_contract` | uncompressed SSTable streaming 用 `StreamCompressionSerializer` 的 `int compressed length` + `int uncompressed length` + payload 格式，见 `src/java/org/apache/cassandra/streaming/async/StreamCompressionSerializer.java:34-127` | `StreamCompressionSerializerTest.roundTrip_HappyPath_NotReadabaleByteBuffer()` 和 `roundTrip_HappyPath_ReadabaleByteBuffer()` 覆盖 array/direct path，见 `test/unit/org/apache/cassandra/streaming/async/StreamCompressionSerializerTest.java:74-112` | 覆盖充分，但不是 internode frame compression |
| `streaming_outgoing_file_header_contract` | `CassandraOutgoingFile.makeHeader()` 写入 SSTable version/format、sections、compression info、serialization header、entire flag、component manifest、first key/table id；`CassandraStreamHeader.serializer` 负责 wire header，见 `src/java/org/apache/cassandra/db/streaming/CassandraOutgoingFile.java:72-95`、`src/java/org/apache/cassandra/db/streaming/CassandraStreamHeader.java:156-205` | `test/unit/org/apache/cassandra/db/streaming/CassandraStreamHeaderTest.java` 与 writer/receiver tests 在 existing Streaming index 中覆盖 | mixed-version header compatibility 仍需要 upgrade streaming scenario |
| `streaming_partial_uncompressed_contract` | partial uncompressed writer 读取 DATA section、checksum validate、LZ4 stream-compress；reader 用 `StreamCompressionInputStream` 解 payload 并写 `RangeAwareSSTableWriter`，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamWriter.java:76-155`、`src/java/org/apache/cassandra/db/streaming/CassandraStreamReader.java:116-188` | `LongStreamingTest` 覆盖长流式数据路径；netstats no-table-compression bootstrap/repair 间接覆盖，见 `test/distributed/org/apache/cassandra/distributed/test/NetstatsBootstrapWithoutEntireSSTablesCompressionStreamingTest.java:23-36`、`test/distributed/org/apache/cassandra/distributed/test/NetstatsRepairStreamingTest.java:38-86` | 缺 TLS/mixed-version 组合 |
| `streaming_partial_compressed_contract` | compressed SSTable partial writer fuse adjacent chunks，发送 compressed chunk+CRC 原始 bytes；reader 用 `CompressedInputStream` 按 section 读，见 `src/java/org/apache/cassandra/db/streaming/CassandraCompressedStreamWriter.java:58-141`、`src/java/org/apache/cassandra/db/streaming/CassandraCompressedStreamReader.java:55-123` | `NetstatsBootstrapWithEntireSSTablesCompressionStreamingTest` 和 repair compression test 覆盖 compression on/off 的观测输出，见 `test/distributed/org/apache/cassandra/distributed/test/NetstatsBootstrapWithEntireSSTablesCompressionStreamingTest.java:23-42`、`test/distributed/org/apache/cassandra/distributed/test/NetstatsRepairStreamingTest.java:38-86` | 缺 TLS/mixed-version 组合 |
| `streaming_entire_sstable_contract` | `CassandraOutgoingFile.computeShouldStreamEntireSSTables()` 要求 `stream_entire_sstables`、非 legacy counter shard、非 old BF format 且 sections 覆盖整表；entire reader 按 component manifest 写 zero-copy writer，见 `src/java/org/apache/cassandra/db/streaming/CassandraOutgoingFile.java:180-201`、`src/java/org/apache/cassandra/db/streaming/CassandraEntireSSTableStreamReader.java:85-200` | `EntireSSTableStreamingCorrectFilesCountTest` 和 netstats entire tests 覆盖 component count、entire/partial 观测，见 `test/unit/org/apache/cassandra/streaming/EntireSSTableStreamingCorrectFilesCountTest.java:117-142`、`test/distributed/org/apache/cassandra/distributed/test/NetstatsBootstrapWithEntireSSTablesCompressionStreamingTest.java:25-41` | 缺 TLS fallback distributed assertion |
| `streaming_state_netstats_observability_contract` | `StreamingState` 暴露 status/progress/failure/success，`StreamingVirtualTable` 输出 `failure_cause`、`success_message`、session fields，`NetStats` 打印 JMX stream status，见 `src/java/org/apache/cassandra/streaming/StreamingState.java:198-245`、`src/java/org/apache/cassandra/db/virtual/StreamingVirtualTable.java:67-103`、`src/java/org/apache/cassandra/tools/nodetool/NetStats.java:45-173` | `IndexStreamingTest` 校验 `system_views.streaming` success/progress/files/bytes，`StreamingStatsDisabledTest` 校验开关，netstats tests 校验 Receiving/Sending 解析，见 `test/distributed/org/apache/cassandra/distributed/test/sai/IndexStreamingTest.java:130-166`、`test/distributed/org/apache/cassandra/distributed/test/streaming/StreamingStatsDisabledTest.java:34-63`、`test/distributed/org/apache/cassandra/distributed/test/AbstractNetstatsStreaming.java:120-135` | 覆盖可观测性，未覆盖 TLS/compression/mixed-version 组合 |
| `streaming_receive_failure_contract` | `IncomingStreamMessage.deserialize()` 找不到 session/table 或 reader 失败时包装 `StreamReceiveException`；`StreamDeserializingTask` 捕获后调用 `session.onError()`，见 `src/java/org/apache/cassandra/streaming/messages/IncomingStreamMessage.java:37-60`、`src/java/org/apache/cassandra/streaming/StreamDeserializingTask.java:51-99` | streaming failure logs、receive abort、prepare fail tests 已在 `research/notes/source-map.md` Streaming row 索引 | generic failure 覆盖存在，兼容性组合缺失 |
| `streaming_existing_tests_baseline` | 现有覆盖分散在 async unit、db streaming unit、long streaming、netstats distributed、SAI index streaming、failure logs、ordinary internode encryption tests | `test/unit/org/apache/cassandra/streaming/async/StreamCompressionSerializerTest.java`、`test/unit/org/apache/cassandra/streaming/async/StreamingMultiplexedChannelTest.java`、`test/unit/org/apache/cassandra/streaming/EntireSSTableStreamingCorrectFilesCountTest.java`、`test/distributed/org/apache/cassandra/distributed/test/NetstatsRepairStreamingTest.java`、`test/distributed/org/apache/cassandra/distributed/test/sai/IndexStreamingTest.java`、`test/distributed/org/apache/cassandra/distributed/test/InternodeEncryptionOptionsTest.java` | 现有测试是分层 coverage，不是端到端 compatibility matrix |
| `streaming_mixed_tls_compression_gap` | 需要同时验证 upgrade/mixed-mode handshake version、server TLS optional/strict、`internode_compression` 设置、streaming file transfer 和 receiver ingest/state | 当前扫描未发现 `test/distributed` 中同时包含 streaming marker、TLS marker、`internode_compression` marker 和 mixed-version/upgrade marker 的 Java 测试 | 显式缺口，应新增 distributed/upgrade dtest 后更新本文和 checker |

## 调用图

Streaming connection negotiation：

```text
StreamingMultiplexedChannel.sendMessage(OutgoingStreamMessage)
  -> FileStreamTask.run()
     -> NettyStreamingConnectionFactory.connect(kind=FILE)
        -> OutboundConnectionInitiator.initiateStreaming(...)
           -> HandshakeProtocol.Initiate.encodeFlags(type=STREAMING, framing=UNPROTECTED)
        -> inbound InboundConnectionInitiator.setupStreamingPipeline(...)
           -> new NettyStreamingChannel(channel, CONTROL)
           -> StreamDeserializingTask.run()
```

File payload path：

```text
CassandraOutgoingFile.write(...)
  -> serialize CassandraStreamHeader
  -> if entire:
       CassandraEntireSSTableStreamWriter.write()
       -> AsyncStreamingOutputPlus.writeFileToChannel()
          -> SslHandler present ? user-space 64 KiB : zero-copy FileRegion
     else if header.isCompressed():
       CassandraCompressedStreamWriter.write()
       -> send compressed chunks + CRC bytes
       -> CassandraCompressedStreamReader.read()
     else:
       CassandraStreamWriter.write()
       -> StreamCompressionSerializer.serialize(LZ4 chunk)
       -> CassandraStreamReader.read()
          -> StreamCompressionInputStream
```

Failure and observability path：

```text
StreamDeserializingTask.run()
  -> StreamMessage.deserialize(...)
  -> IncomingStreamMessage.deserialize(...)
     -> CassandraIncomingFile.read()
        -> reader.read(...)
  -> catch Throwable
     -> session.onError(...)
     -> StreamResultFuture failure
     -> StreamingState.failureCause()
     -> system_views.streaming / nodetool netstats / StreamingMetrics
```

## 配置和运维边界

| 配置 | 作用 | 证据 |
|---|---|---|
| `server_encryption_options.internode_encryption` | 决定 internode TLS policy；streaming connection 复用 inbound/outbound TLS handler | `conf/cassandra.yaml:1641-1652`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:117-132` |
| `internode_compression` | messaging frame compression policy，不是 streaming payload compression | `conf/cassandra.yaml:1730-1742`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:467-526` |
| `stream_entire_sstables` | 是否允许 entire SSTable streaming；还受 legacy counter shard、old BF format、range section 完整性限制 | `src/java/org/apache/cassandra/config/Config.java:699`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3999-4005`、`src/java/org/apache/cassandra/db/streaming/CassandraOutgoingFile.java:180-201` |
| `stream_throughput_outbound` / `inter_dc_stream_throughput_outbound` | partial stream limiter | `src/java/org/apache/cassandra/config/Config.java:361-364`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:2600-2705` |
| `entire_sstable_stream_throughput_outbound` / `entire_sstable_inter_dc_stream_throughput_outbound` | entire SSTable stream limiter | `src/java/org/apache/cassandra/config/Config.java:366-367`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:2645-2725` |
| `streaming_stats_enabled` / `streaming_slow_events_log_timeout` | retained streaming state 和 slow event log | `src/java/org/apache/cassandra/config/Config.java:951-952`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:5018-5039` |

## Metrics, Logs, Tests

- Metrics：`StreamingMetrics.totalIncomingBytes`、`totalOutgoingBytes`、`totalOutgoingRepairBytes`、per-peer entire/partial counters 在 `src/java/org/apache/cassandra/metrics/StreamingMetrics.java:34-93` 与 `src/java/org/apache/cassandra/streaming/StreamSession.java:1039-1082`。
- Logs：inbound streaming connection established log 记录 version/framing/encryption，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:455-464`；`StreamResultFuture` 失败摘要包含 `Stream failed:`，见 `src/java/org/apache/cassandra/streaming/StreamResultFuture.java:235-252`。
- Tests：现有测试验证单层合同，但不验证四维组合。新增测试应至少覆盖：old/current 或 rolling upgrade cluster、`server_encryption_options` optional/strict、`internode_compression=dc/all`、bootstrap/rebuild/repair streaming、entire/partial/table compression 组合、`system_views.streaming`/netstats/metrics 成功和失败可见性。

## Drift Checker

`research/tools/check-streaming-transfer-compatibility-drift.py` 会保护上表的源码 token、现有测试 token、文档场景 ID，并扫描 `test/distributed` 中是否出现真正的 mixed-version + TLS + `internode_compression` + streaming 组合测试。若该组合测试被新增，checker 会失败，提示把 `streaming_mixed_tls_compression_gap` 改成具体覆盖项。
