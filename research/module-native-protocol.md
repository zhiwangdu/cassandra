# Module: Native Protocol

## 范围

本模块覆盖 native CQL protocol 的 Envelope/Message、dispatcher、auth、背压和 client metrics。opcode/version/header flag/query option flag/event/error code 的 wire contract 和 drift checker 见 `research/module-native-protocol-wire-contract.md` 与 `research/module-native-protocol-wire-drift-checker.md`；`OPTIONS`/`STARTUP`/`AUTH_RESPONSE` 和 `ERROR`/`EVENT`/auth response family 的 extra flag 负例矩阵见 `research/module-native-protocol-extras-negative-matrix.md` 与 `research/module-native-protocol-extras-drift-checker.md`；native TLS certificate reload 的 source/test coverage matrix 见 `research/module-native-tls-reload-coverage-matrix.md` 与 `research/module-native-tls-reload-drift-checker.md`。

## 设计目标

本模块覆盖 Cassandra 5.0 native CQL binary protocol 的服务端实现：socket/bootstrap、protocol version negotiation、frame/envelope 编解码、message opcode、dispatcher、认证、背压、metrics 以及与 `QueryProcessor` 的衔接。

设计目标：

- 同时支持 V3/V4/V5/V6 beta 等协议版本，并允许通过配置禁用老版本。
- Netty pipeline 必须能处理 TLS/明文端口、pre-V5 framing、V5+ self-contained/large frames。
- 消息执行要按类型区分 auth、request、response，并支持 queue timeout、request in-flight bytes 和 queue-age backpressure。
- QUERY/PREPARE/EXECUTE/BATCH 要统一进入 CQL statement prepare/authorize/validate/execute 主线。
- 协议异常、认证成功/失败、收发字节和连接暂停要落到可观测 metrics。

## 解决的问题

- `Server` 负责 native transport 的 accept/bind、connection factory、pipeline 配置和 `Dispatcher` 生命周期，见 `src/java/org/apache/cassandra/transport/Server.java:62-117` 和 `src/java/org/apache/cassandra/transport/Server.java:206-360`。
- `ProtocolVersion` 定义 supported/current/beta 版本、decode 规则和 older-protocol 开关，见 `src/java/org/apache/cassandra/transport/ProtocolVersion.java:29-130`。
- `Envelope` 把 protocol header、flags、stream id、opcode 和 body size 统一成可编解码对象，见 `src/java/org/apache/cassandra/transport/Envelope.java:41-130` 和 `src/java/org/apache/cassandra/transport/Envelope.java:190-255`。
- `Message.Type` 维护 opcode 到 message serializer 的映射；`Message.Decoder` / `Encoder` 完成 envelope 到 request/response 的转换，并处理 request `TRACING` flag 与 response trace id，见 `src/java/org/apache/cassandra/transport/Message.java:45-143`、`src/java/org/apache/cassandra/transport/Message.java:236-270`、`src/java/org/apache/cassandra/transport/Message.java:329-417`、`src/java/org/apache/cassandra/transport/Message.java:427-463`。
- `CQLMessageHandler` 处理 V5+ frame、capacity reserve、large message、discard/backpressure 和 dispatch，见 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:56-150`、`src/java/org/apache/cassandra/transport/CQLMessageHandler.java:230-285` 和 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:480-510`。
- `Dispatcher` 将 decoded request 送到 request/auth executor，处理 timeout、flush item、warnings 和 response write，见 `src/java/org/apache/cassandra/transport/Dispatcher.java:53-130`、`src/java/org/apache/cassandra/transport/Dispatcher.java:286-330` 和 `src/java/org/apache/cassandra/transport/Dispatcher.java:355-435`。
- Native TLS reload 通过 `SSLFactory` 验证 changed files 后清理 cached `SslContext`，新 native channel 在 `PipelineConfigurator` 中取得 fresh context；完整 source/test 矩阵见 `research/module-native-tls-reload-coverage-matrix.md`。

## 设计取舍

- V5 之前沿用 `PreV5Handlers` pipeline；V5+ 走 frame decoder/message handler 层以支持 large message 和更细的 backpressure，见 `src/java/org/apache/cassandra/transport/PreV5Handlers.java:54-105` 和 `src/java/org/apache/cassandra/transport/PreV5Handlers.java:263-310`。
- `STARTUP` 不能压缩，compression 需要连接已经启用对应 compressor；`Envelope.Compressor` 明确跳过 STARTUP，见 `src/java/org/apache/cassandra/transport/Envelope.java:509-520`。
- 认证响应单独进入 auth executor/rate limiter；普通 CQL request 进入 request executor，`Dispatcher` 分离 request 与 auth 执行路径，见 `src/java/org/apache/cassandra/transport/Dispatcher.java:286-330`。
- 对 overload 可以选择抛 `OverloadedException` 或暂停 socket 施加 backpressure，配置由 native transport queue/backoff 项控制，见 `src/java/org/apache/cassandra/config/Config.java:1384-1399` 和 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:2303-2357`。
- 解析 frame 后的 CQL 执行不在 transport 层内联完成，而是进入 `QueryProcessor` 和 statement 层，避免 protocol 直接耦合 storage internals，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:266-284` 和 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:337-360`。

## 核心类

| 类 | 作用 |
|---|---|
| `Server` | native transport 服务端入口、pipeline configurator、bind/close 和 connection factory。定义见 `src/java/org/apache/cassandra/transport/Server.java:62` |
| `Connection` | 单连接状态，包括 negotiated protocol version、tracker、channel attributes。定义见 `src/java/org/apache/cassandra/transport/Connection.java:23-88` |
| `ProtocolVersion` | 协议版本枚举和 decode/compare/supported 规则。定义见 `src/java/org/apache/cassandra/transport/ProtocolVersion.java:29` |
| `Envelope` | native protocol frame 的 header/body 表示及 encoder/decoder/compressor。定义见 `src/java/org/apache/cassandra/transport/Envelope.java:41` |
| `Message` | native message 抽象、opcode enum、request/response encode/decode。定义见 `src/java/org/apache/cassandra/transport/Message.java:45` |
| `CQLMessageHandler` | V5+ frame 到 message 的 handler，包含 capacity、large message、backpressure。定义见 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:56` |
| `PreV5Handlers` | V3/V4 pipeline handlers，兼容老版本 envelope/message 处理。定义见 `src/java/org/apache/cassandra/transport/PreV5Handlers.java:54` |
| `Dispatcher` | request/auth executor dispatch、timeout、flush 和 response path。定义见 `src/java/org/apache/cassandra/transport/Dispatcher.java:53` |
| `QueryMessage` | QUERY opcode 请求，decode query/options 并调用 `QueryProcessor.process()`。定义见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:44` |
| `PrepareMessage` | PREPARE opcode 请求，V5+ 支持 keyspace 字段并调用 `QueryProcessor.prepare()`。定义见 `src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:42` |
| `ExecuteMessage` | EXECUTE opcode 请求，根据 prepared id 查 statement 并执行。定义见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:50` |
| `BatchMessage` | BATCH opcode 请求，decode statement/id 列表与 batch options。定义见 `src/java/org/apache/cassandra/transport/messages/BatchMessage.java:52` |

## 核心接口

- `Connection.Factory.newConnection()`：pipeline 在协商 protocol version 后创建连接状态，接口定义见 `src/java/org/apache/cassandra/transport/Server.java:62-77`。
- `Message.Codec.decode()` / `encode()` / `encodedSize()`：每个 native message 类型实现自己的 body 编解码，典型实现见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:44-77` 和 `src/java/org/apache/cassandra/transport/messages/BatchMessage.java:52-144`。
- `Message.Request.execute()`：所有 request message 的执行入口，`Dispatcher` 最终调用该方法生成 response；traceable request 的 session wrapper 也在这里，抽象定义和调用链见 `src/java/org/apache/cassandra/transport/Message.java:220-270`、`src/java/org/apache/cassandra/transport/Dispatcher.java:355-435`。
- `Dispatcher.FlushItemConverter`：request response 转换成可 flush envelope 的接口，V5+ handler 实现见 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:480-510`。
- `ClientResourceLimits.Limit`：native request bytes in-flight reserve/release 接口，V5+ 使用说明见 `src/java/org/apache/cassandra/transport/ClientResourceLimits.java:242`。

## 核心数据结构

- `Envelope.Header`：保存 protocol version、flags、stream id、message type 和 body size，定义见 `src/java/org/apache/cassandra/transport/Envelope.java:138-185`。
- `Envelope.Header.Flag`：表示 compression、tracing、custom payload、warning 等 header flags，flag 定义和 decode 入口见 `src/java/org/apache/cassandra/transport/Envelope.java:153-180`、`src/java/org/apache/cassandra/transport/Envelope.java:423-438`。
- `Message.Type`：opcode 到 request/response codec 的注册表，定义见 `src/java/org/apache/cassandra/transport/Message.java:45-143`。
- `QueryOptions`：承载 consistency、values、page size、serial consistency、timestamp/keyspace 等 CQL options，native message decode 后交给 `QueryProcessor`，使用见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:79-99` 和 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:106-131`。
- `ExceptionCode`：ERROR response 的 wire code enum，定义见 `src/java/org/apache/cassandra/exceptions/ExceptionCode.java:32-79`；完整 opcode/version/flag/event/error baseline 见 `research/module-native-protocol-wire-contract.md`。
- `Dispatcher.RequestTime`：记录 request creation/queue timing，用于 timeout 和 slow path 判断，使用见 `src/java/org/apache/cassandra/transport/Dispatcher.java:460-485`。

## 核心消息

- `OPTIONS`：返回 CQL version、compression、protocol versions 等 supported map，见 `src/java/org/apache/cassandra/transport/messages/OptionsMessage.java:37-86`。
- `STARTUP`：读取 startup options、设置 compression、执行 authentication handshake 或返回 READY，见 `src/java/org/apache/cassandra/transport/messages/StartupMessage.java:36-127`。
- `AUTH_RESPONSE`：继续 SASL/authenticator 交互，并记录 auth success/failure metrics，见 `src/java/org/apache/cassandra/transport/messages/AuthResponse.java:36-99`。
- `REGISTER`：注册 schema/status/topology event types，连接成为 event subscriber，见 `src/java/org/apache/cassandra/transport/messages/RegisterMessage.java:28-85`。
- `QUERY`：decode raw CQL + query options，执行 `QueryProcessor.process()`，见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:79-147`。
- `PREPARE`：decode query/keyspace，调用 prepare 并返回 prepared metadata，见 `src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:101-145`。
- `EXECUTE`：decode prepared id/options，查 prepared statement 后调用 `QueryProcessor.processPrepared()`，见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:106-190`。
- `BATCH`：decode batch type、query/id、values/options，再进入 batch statement 执行，见 `src/java/org/apache/cassandra/transport/messages/BatchMessage.java:146-190`。
- `TRACING` flag：request decode 后设置 `Request.tracingRequested`，explicit tracing response encode 时带 trace UUID；完整链路见 `research/module-tracing-native-cqlsh.md`。
- Protocol extras negative matrix：`OPTIONS`、`STARTUP`、`AUTH_RESPONSE` 继承 default `isTraceable=false` / `isTrackable=false`，V4+ custom payload 会被 frame 层解码但 execute path 不消费；`WARNING` request flag 不读取 warning-list prelude；完整矩阵见 `research/module-native-protocol-extras-negative-matrix.md`。

## 生命周期

启动：

```text
CassandraDaemon
  -> NativeTransportService / Server.Builder
  -> Server.start()
     -> configure Netty server bootstrap
     -> PipelineConfigurator.addLast(...)
     -> bind native_transport_port / native_transport_port_ssl
```

连接协商：

```text
Channel accepted
  -> InitialConnectionHandler / Envelope decoder extracts version
  -> ProtocolVersion.decode(versionByte, allowOlderProtocols)
  -> Connection.newConnection(channel, version)
  -> STARTUP message sets compression and auth state
```

请求执行：

```text
Frame bytes
  -> Envelope / CQLMessageHandler
  -> Message.Decoder
  -> Dispatcher.dispatch(channel, message, converter, backpressure)
  -> message.execute(QueryState, RequestTime, traceRequest)
  -> Message.Response.encode(protocolVersion)
  -> Flusher writes Envelope response
```

## 调用链

- Server pipeline：`Server.PipelineConfigurator` 根据 negotiated version 选择 V5+ `CQLMessageHandler` 或 pre-V5 handlers，见 `src/java/org/apache/cassandra/transport/Server.java:276-360`。
- Envelope decode：header extraction 校验 protocol、flags、stream id、opcode、body length，见 `src/java/org/apache/cassandra/transport/Envelope.java:334-438`。
- Message decode：`Message.Decoder.decode()` 从 envelope type 选择 codec 并实例化 request，同时处理 trace/custom payload/warning flags，见 `src/java/org/apache/cassandra/transport/Message.java:425-463`。
- Dispatch：`CQLMessageHandler.processRequest()` decode message 后调用 dispatcher，见 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:385-405`。
- QUERY 执行：`QueryMessage.execute()` 调用 `QueryProcessor.process()`，见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:102-147`。
- PREPARE 执行：`PrepareMessage.execute()` 调用 `QueryProcessor.prepare()` 并处理 custom payload，见 `src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:118-145`。
- EXECUTE 执行：`ExecuteMessage.execute()` 查 prepared statement、设置 keyspace/options 并执行，见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:131-190`。
- Response encode：`Message.encode()` 生成 envelope，explicit tracing response 会先写 trace UUID 并设置 `TRACING` flag，再由 handler 更新 sent bytes metrics，见 `src/java/org/apache/cassandra/transport/Message.java:329-417` 和 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:480-510`。
- Extra negative matrix：`Message.Decoder.decodeMessage()` 对 request 只设置 tracingRequested 并读取 custom payload；`Dispatcher` 对 V4+ 捕获 warnings 但仅在 trackable request 上启用 `CoordinatorWarnings`，见 `src/java/org/apache/cassandra/transport/Message.java:427-463` 和 `src/java/org/apache/cassandra/transport/Dispatcher.java:370-423`。

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| `start_native_transport` / `native_transport_port` / `native_transport_port_ssl` | `src/java/org/apache/cassandra/config/Config.java:278-283` | 是否启动 native transport 及端口 |
| `native_transport_max_threads` / `native_transport_max_auth_threads` | `src/java/org/apache/cassandra/config/Config.java:283-287` | request/auth executor 并发上限 |
| `native_transport_max_frame_size` / `native_transport_max_message_size` | `src/java/org/apache/cassandra/config/Config.java:284-288`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:619-659` | frame/message 大小限制 |
| `native_transport_max_concurrent_connections*` | `src/java/org/apache/cassandra/config/Config.java:289-290` | 全局/按 IP 连接数上限 |
| `native_transport_allow_older_protocols` | `src/java/org/apache/cassandra/config/Config.java:292` | 是否允许老 protocol version |
| `native_transport_max_request_data_in_flight*` | `src/java/org/apache/cassandra/config/Config.java:295-298`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:903-918` | request bytes in-flight 限制 |
| `native_transport_rate_limiting_enabled` / `native_transport_max_requests_per_second` | `src/java/org/apache/cassandra/config/Config.java:299-300` | native request rate limiting |
| `native_transport_receive_queue_capacity` | `src/java/org/apache/cassandra/config/Config.java:301-302` | receive queue 容量 |
| `native_transport_timeout` / queue overload backoff | `src/java/org/apache/cassandra/config/Config.java:1384-1399` | request queue timeout 和 overload backpressure |

## Metrics

- `ClientMetrics` 记录 auth success/failure、paused connections、protocol exception 等 native client 指标，见 `src/java/org/apache/cassandra/metrics/ClientMetrics.java:42-91` 和 `src/java/org/apache/cassandra/metrics/ClientMetrics.java:109-151`。
- `ClientMessageSizeMetrics` 记录收发总字节和每 request/response 字节分布，见 `src/java/org/apache/cassandra/metrics/ClientMessageSizeMetrics.java:29-35`。
- `CQLMessageHandler` 在接收/发送 frame 时更新 `ClientMessageSizeMetrics`，见 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:367-369` 和 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:487-490`。
- `AuthResponse` 根据认证结果标记 `ClientMetrics.markAuthSuccess()` / `markAuthFailure()`，见 `src/java/org/apache/cassandra/transport/messages/AuthResponse.java:72-99`。

## 日志

- protocol decode 错误可能导致 `ProtocolException` 或连接关闭，Envelope header/body decode 处理见 `src/java/org/apache/cassandra/transport/Envelope.java:238-255` 和 `src/java/org/apache/cassandra/transport/Envelope.java:357-420`。
- V5+ corrupt frame 遇到 CRC mismatch 等不可恢复错误时 fast fail 并关闭连接，见 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:706-728`。
- overload 时会记录 endpoint/global request reserve、queue capacity 与 message size，见 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:320-343`。
- Dispatcher timeout 会基于 request creation/queue 时间生成错误响应，见 `src/java/org/apache/cassandra/transport/Dispatcher.java:460-485`。

## 运维关注点

- `native_transport_allow_older_protocols=false` 会拒绝旧 driver；升级前要确认 client driver 支持当前协议。
- `native_transport_timeout` 统计的是从 request 进入 queue 起的时间，不等同于 coordinator read/write timeout；队列拥塞会先表现为 native timeout。
- 大 frame/message 限制和 request in-flight bytes 要一起调，单纯增大 frame size 可能被 max message 或 in-flight limit 拒绝。
- auth 线程太小会让登录路径排队；auth rate limiter 和 request executor 是分离的。
- V5+ large message 在 capacity 不足时会选择 discard/backpressure，但仍需要消费后续 frames，避免 TCP 层卡死。

## 性能瓶颈

- request executor 饱和会增加 native queue time，并触发 queue-age backpressure。
- 大量 prepared statement prepare/execute 混合会增加 QueryProcessor prepared cache 压力；prepared cache 细节见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:845-890`。
- 压缩会降低网络字节但增加 event loop / executor CPU，且 STARTUP 永远不压缩。
- 老协议路径和新协议路径 metrics/异常处理不完全相同，排查 mixed-version client 时要确认 negotiated protocol。

## 常见故障

- `Invalid or unsupported protocol version`：`ProtocolVersion.decode()` 拒绝未知或禁用版本，见 `src/java/org/apache/cassandra/transport/ProtocolVersion.java:85-130`。
- `Frame too long` / message size exceeded：Envelope/CQLMessageHandler 依据 frame/message 限制拒绝，配置校验见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:619-659` 和 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:903-918`。
- 认证失败：`AuthResponse.execute()` 捕获 auth 异常并返回 error，同时标记 auth failure，见 `src/java/org/apache/cassandra/transport/messages/AuthResponse.java:72-99`。
- `UNPREPARED`：`ExecuteMessage.execute()` 找不到 prepared id 时返回 unprepared 语义，见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:131-190`。
- tracing id 缺失：只有 explicit request tracing 才会在 response 中设置 id；概率采样不会回传 id，见 `src/java/org/apache/cassandra/transport/Message.java:249-268`。

## 测试用例

- `ProtocolVersionTest` 覆盖 decode、supported versions、比较和禁用老协议，见 `test/unit/org/apache/cassandra/transport/ProtocolVersionTest.java:31-146`。
- `ProtocolNegotiationTest` 覆盖 driver requested version、default newest supported/beta、stream id negotiation 和 rejected protocol，见 `test/unit/org/apache/cassandra/transport/ProtocolNegotiationTest.java:53-225`。
- `MessageDispatcherTest` 覆盖 auth rate limiter 启用/禁用路径，见 `test/unit/org/apache/cassandra/transport/MessageDispatcherTest.java:38-120`。
- `PrepareMessageTest` 覆盖 prepare message encode/decode，见 `test/unit/org/apache/cassandra/transport/messages/PrepareMessageTest.java:27-30`。
- `NativeProtocolTest` 在 in-JVM dtest 中验证 binary readiness 与 RPC readiness 的关系，见 `test/distributed/org/apache/cassandra/distributed/test/NativeProtocolTest.java:51-126`。
- `python3 research/tools/check-native-protocol-wire-drift.py` 覆盖 17 Message.Type opcodes、6 ProtocolVersion enum constants、5 Envelope.Header.Flag values、9 QueryOptions.Codec.Flag values、4 Event.Type values 和 20 ExceptionCode wire values 的 source-to-doc drift。
- `python3 research/tools/check-native-protocol-extras-drift.py` 覆盖 `OPTIONS`/`STARTUP`/`AUTH_RESPONSE` 非 traceable/trackable request、custom payload V4 gate、request WARNING negative semantics、response family extras 和 test coverage gap。
- `python3 research/tools/check-native-tls-reload-drift.py` 覆盖 native TLS reload cache/file-watch/pipeline/JMX/mTLS source contract、existing tests 和真实 E2E test gap。
- `python3 research/tools/check-prepared-statement-compat-drift.py` 覆盖 V5 PREPARE keyspace、V5 EXECUTE/RESULT PREPARED resultMetadataId、prepared 4-hash id matrix、cache/persistence/invalidation、CQL metrics 和配置项。
- `python3 research/tools/check-prepared-driver-integration-drift.py` 覆盖 Java driver reprepare/hash/keyspace/mixed-mode/fuzz runtime anchors、V4/V5 metadata boundary、protocol negotiation 非 prepared boundary、persistence/batch anchors，以及 `prepared_driver_non_java_gap` 和 `prepared_driver_protocol_matrix_gap`。

## 待补项

- V5 large message 的 fragment/CRC 数据结构细节。
- 真实 native connection TLS reload 端到端 Java test 与完整 external driver compatibility matrix；prepared source matrix 已单独展开在 `research/module-prepared-statement-compatibility-matrix.md`，Java driver runtime/protocol boundary/non-Java gap matrix 已单独展开在 `research/module-prepared-driver-integration-gap-matrix.md`，tracing id 链路已单独展开在 `research/module-tracing-native-cqlsh.md`，extra flag 负例矩阵已单独展开在 `research/module-native-protocol-extras-negative-matrix.md`，TLS reload source/test 矩阵已单独展开在 `research/module-native-tls-reload-coverage-matrix.md`。
