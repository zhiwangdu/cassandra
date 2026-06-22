# Flow: Native Protocol Request

## 入口

Native protocol 请求从 Netty channel 的 inbound bytes 开始，到 `Message.Request.execute()` 进入 CQL 或认证逻辑结束。该 flow 补充 `flow-cql-request.md`，重点是 frame/dispatcher 层。

## STARTUP / OPTIONS / AUTH

```text
Client connects to native_transport_port
  -> Server.PipelineConfigurator.initChannel()
     -> choose pre-V5 or V5+ protocol handlers
  -> Envelope header decode
     -> ProtocolVersion.decode(versionByte, allowOlderProtocols)
  -> OPTIONS
     -> OptionsMessage.execute()
     -> SupportedMessage(CQL_VERSION, COMPRESSION, PROTOCOL_VERSIONS)
  -> STARTUP
     -> StartupMessage.execute()
     -> set compression / driver metadata / connection state
     -> if authenticator requires auth:
          AuthenticateMessage
        else:
          ReadyMessage
  -> AUTH_RESPONSE
     -> AuthResponse.execute()
     -> AuthenticatedUser / QueryState updated
```

关键源码：

- Pipeline 配置在 `Server.PipelineConfigurator`，见 `src/java/org/apache/cassandra/transport/Server.java:276-360`。
- protocol version decode 与 older-protocol 开关在 `ProtocolVersion.decode()`，见 `src/java/org/apache/cassandra/transport/ProtocolVersion.java:85-130`。
- `OPTIONS` 支持项由 `OptionsMessage.execute()` 返回，见 `src/java/org/apache/cassandra/transport/messages/OptionsMessage.java:62-86`。
- `STARTUP` 处理 compression/auth/ready，见 `src/java/org/apache/cassandra/transport/messages/StartupMessage.java:63-127`。
- `AUTH_RESPONSE` 执行认证 continuation 并标记 metrics，见 `src/java/org/apache/cassandra/transport/messages/AuthResponse.java:72-99`。

## QUERY

```text
Frame bytes
  -> Envelope.Decoder / CQLMessageHandler
  -> Message.Decoder
     -> Message.Type.QUERY.codec.decode(body, version)
     -> QueryMessage(query, QueryOptions)
  -> Dispatcher.dispatch(...)
     -> request executor
     -> QueryMessage.execute(queryState, requestTime, traceRequest)
       -> if request TRACING flag was set, Message.Request wrapper owns trace session/id
        -> QueryProcessor.process(query, queryState, options, customPayload, requestTime)
        -> CQLStatement authorize/validate/execute
  -> Message.Response.encode(protocolVersion)
  -> Envelope response flushed to channel
```

关键源码：

- Envelope header/body decode 见 `src/java/org/apache/cassandra/transport/Envelope.java:334-438`。
- `Message.Decoder` 根据 opcode 选择 serializer，并处理 trace/custom payload/warning flags，见 `src/java/org/apache/cassandra/transport/Message.java:425-463`。
- `CQLMessageHandler.processRequest()` decode 后交给 dispatcher，见 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:385-405`。
- `QueryMessage` decode/execute 见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:79-147`。
- `QueryProcessor.process()` 进入 statement 主线，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:266-284` 和 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:337-360`。
- native tracing flag/session/id 细节见 `research/module-tracing-native-cqlsh.md`。

## Extra Flags Negative Matrix

```text
Request envelope extras
  -> Message.Decoder.decodeMessage()
     -> TRACING flag only sets tracingRequested
     -> WARNING flag is not read as request prelude
     -> CUSTOM_PAYLOAD map is attached for V4+
  -> OPTIONS / STARTUP / AUTH_RESPONSE
     -> inherit isTraceable=false and isTrackable=false
     -> execute path does not consume getCustomPayload()
  -> Response
     -> Dispatcher may attach ClientWarn warnings
     -> Message.encode() writes tracing UUID, warnings, custom payload before body
```

关键源码：

- `OPTIONS`、`STARTUP`、`AUTH_RESPONSE` 的 payload/tracing/warning 负例矩阵见 `research/module-native-protocol-extras-negative-matrix.md`。
- Request 默认 traceable/trackable false 和 tracing wrapper 见 `src/java/org/apache/cassandra/transport/Message.java:221-270`。
- request/response extra prelude decode 见 `src/java/org/apache/cassandra/transport/Message.java:427-463`。
- warning capture 与 `CoordinatorWarnings` gate 见 `src/java/org/apache/cassandra/transport/Dispatcher.java:370-423`。

## PREPARE / EXECUTE

```text
PREPARE
  -> PrepareMessage.decode(query, keyspace?)
  -> Dispatcher request executor
  -> QueryProcessor.prepare(...)
  -> ResultMessage.Prepared(id, metadata)

EXECUTE
  -> ExecuteMessage.decode(preparedId, QueryOptions)
  -> QueryProcessor lookup prepared statement
  -> processPrepared(statement, queryState, options, customPayload, requestTime)
  -> ResultMessage.Rows / Void / SchemaChange / error
```

关键源码：

- V5+ `PrepareMessage` 支持 keyspace 字段，decode 见 `src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:42-99`。
- Prepare execute 见 `src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:118-145`。
- Execute decode 和 prepared lookup/execute 见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:50-104` 和 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:131-190`。
- prepared cache 和 invalidation 入口在 `QueryProcessor`，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:845-890`。

## BATCH

```text
BATCH frame
  -> BatchMessage.decode(type, queryOrId list, values, options)
  -> Dispatcher request executor
  -> BatchMessage.execute()
     -> QueryProcessor.processBatch(...)
     -> BatchStatement authorize/validate/execute
```

关键源码：

- Batch message decode/size validation 见 `src/java/org/apache/cassandra/transport/messages/BatchMessage.java:52-144`。
- Batch execute 见 `src/java/org/apache/cassandra/transport/messages/BatchMessage.java:173-190`。

## REGISTER Events

```text
REGISTER frame
  -> RegisterMessage.decode(event types)
  -> RegisterMessage.execute()
     -> connection event registration
     -> ReadyMessage / error
Schema/status/topology changes
  -> Event message delivered to registered connection
```

关键源码：

- Register message decode/execute 见 `src/java/org/apache/cassandra/transport/messages/RegisterMessage.java:28-85`。
- `Message.Type.EVENT` opcode 注册在 `Message.Type`，见 `src/java/org/apache/cassandra/transport/Message.java:45-143`。

## V5+ 背压与 large message

```text
CQLMessageHandler.onFrame(frame)
  -> extract Envelope.Header
  -> reserve endpoint/global request bytes
  -> if queue has capacity:
       processRequest(...)
     else if throw_on_overload:
       discard request and return overloaded
     else:
       pause channel / apply backpressure
  -> if large message:
       collect subsequent frames
       assemble envelope after full body received
```

关键源码：

- capacity reserve 和 queue/discard 处理见 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:230-285`。
- large message first/subsequent frame 处理见 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:513-651`。
- queue-age / request overload 判断和 connection pause 见 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:580-631`。
- native overload/backoff 配置读取见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:2303-2357`。

## Response Path

```text
Message.Response
  -> Message.Response.encode(protocolVersion)
  -> Envelope(responseHeader, encodedBody)
  -> CQLMessageHandler.toFlushItem()
  -> Dispatcher flusher
  -> Netty channel write
```

关键源码：

- response encode 见 `src/java/org/apache/cassandra/transport/Message.java:329-417`；explicit tracing response 的 UUID 写入和 `TRACING` flag 设置见 `src/java/org/apache/cassandra/transport/Message.java:341-370`。
- V5+ response flush item 和 bytes-sent metrics 更新见 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:480-510`。
- Dispatcher flush 和 timeout 处理见 `src/java/org/apache/cassandra/transport/Dispatcher.java:355-435` 和 `src/java/org/apache/cassandra/transport/Dispatcher.java:460-485`。

## 异常分支

- Protocol version 不支持：`ProtocolVersion.decode()` 抛 protocol error，见 `src/java/org/apache/cassandra/transport/ProtocolVersion.java:85-130`。
- Frame/header/body 不合法：Envelope decoder 生成 protocol error 或关闭连接，见 `src/java/org/apache/cassandra/transport/Envelope.java:357-420`。
- Corrupt V5 frame：`CQLMessageHandler.processCorruptFrame()` fast fail，见 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:706-728`。
- Prepared id 不存在：`ExecuteMessage.execute()` 返回 unprepared，见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:131-190`。
- Request queue 超时：`Dispatcher` 依据 request timeout 返回超时响应，见 `src/java/org/apache/cassandra/transport/Dispatcher.java:460-485`。

## 观测点

- Auth success/failure、protocol exception、paused connections：`src/java/org/apache/cassandra/metrics/ClientMetrics.java:42-151`。
- 收发字节与 request/response size histogram：`src/java/org/apache/cassandra/metrics/ClientMessageSizeMetrics.java:29-35`。
- V5+ handler 接收/发送 metrics 更新：`src/java/org/apache/cassandra/transport/CQLMessageHandler.java:367-369` 和 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:487-490`。

## 测试锚点

- Protocol decode/禁用老版本：`test/unit/org/apache/cassandra/transport/ProtocolVersionTest.java:31-146`。
- Driver negotiation：`test/unit/org/apache/cassandra/transport/ProtocolNegotiationTest.java:53-225`。
- Dispatcher auth rate limiter：`test/unit/org/apache/cassandra/transport/MessageDispatcherTest.java:38-120`。
- PREPARE encode/decode：`test/unit/org/apache/cassandra/transport/messages/PrepareMessageTest.java:27-30`。
- in-JVM native readiness：`test/distributed/org/apache/cassandra/distributed/test/NativeProtocolTest.java:51-126`。
- Wire contract drift：`python3 research/tools/check-native-protocol-wire-drift.py`，覆盖 opcode/version/header flag/query option flag/event/error code baseline。
- Extras negative drift：`python3 research/tools/check-native-protocol-extras-drift.py`，覆盖 OPTIONS/STARTUP/AUTH_RESPONSE、ERROR/EVENT/auth response family 的 custom payload/tracing/warning negative matrix。
