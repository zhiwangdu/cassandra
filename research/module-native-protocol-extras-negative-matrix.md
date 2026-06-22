# Module: Native Protocol Extras Negative Matrix

## 范围

本模块补齐 native protocol extra flags 在非查询消息上的负例矩阵：`OPTIONS`、`STARTUP`、`AUTH_RESPONSE` request，以及 `ERROR`、`EVENT`、`SUPPORTED`、`AUTHENTICATE`、`AUTH_CHALLENGE`、`AUTH_SUCCESS` response family。目标是明确哪些 extra 是 frame-level 通用能力，哪些只在 query-like request 上产生语义。

当前源码基线：

- Request tracing flag 解码后只设置 `Request.tracingRequested`，真正创建 trace session 必须 `isTraceable()` 为 true，见 `src/java/org/apache/cassandra/transport/Message.java:221`、`src/java/org/apache/cassandra/transport/Message.java:241`、`src/java/org/apache/cassandra/transport/Message.java:267`。
- Request warnings 不从 request body 读取；`Message.Decoder.decodeMessage()` 对 request 使用 `isRequest || !hasWarning`，见 `src/java/org/apache/cassandra/transport/Message.java:430` 和 `src/java/org/apache/cassandra/transport/Message.java:435`。
- Custom payload 是 request/response frame prelude，V4+ 允许，V3 及更低在 encode/decode 均拒绝，见 `src/java/org/apache/cassandra/transport/Message.java:359`、`src/java/org/apache/cassandra/transport/Message.java:438`。
- `Dispatcher` 对 V4+ request 捕获 `ClientWarn` 并给 response 设置 warnings，但 `CoordinatorWarnings` 只在 `request.isTrackable()` 为 true 时启用，见 `src/java/org/apache/cassandra/transport/Dispatcher.java:370`、`src/java/org/apache/cassandra/transport/Dispatcher.java:375`、`src/java/org/apache/cassandra/transport/Dispatcher.java:421`。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `native_protocol_extras_frame_prelude_contract` | response prefix order 是 tracing UUID、warnings list、custom payload map；request prefix 只有 custom payload map，request tracing flag 无 body。 |
| `native_protocol_extras_custom_payload_version_gate` | request/response custom payload 都是 V4+；V3 encode/decode 均抛 protocol error。 |
| `native_protocol_extras_request_tracing_noop_matrix` | `OPTIONS`、`STARTUP`、`AUTH_RESPONSE` 接受 tracing flag 但不创建 trace session/id。 |
| `native_protocol_extras_request_warning_flag_negative` | request `WARNING` flag 不读取 warning-list prelude，也不生成 request warnings。 |
| `native_protocol_extras_warning_tracking_gate` | `CoordinatorWarnings` 只服务 trackable request；`Dispatcher` 仍可能把 backpressure/queue warnings 附到任意 V4+ response。 |
| `native_protocol_extras_options_startup_auth_payload_negative` | `OPTIONS`、`STARTUP`、`AUTH_RESPONSE` custom payload 可被解码并挂到 message，但 execute path 不消费它。 |
| `native_protocol_extras_error_event_response_matrix` | `ERROR`、`EVENT` 作为 `Message.Response` 继承通用 response extras；实际 producer 通常不会为 event 设置 extras。 |
| `native_protocol_extras_auth_response_family_matrix` | `SUPPORTED`、`AUTHENTICATE`、`AUTH_CHALLENGE`、`AUTH_SUCCESS` 继承 response extras，body codec 只处理自身业务字段。 |
| `native_protocol_extras_test_coverage_gap` | 现有测试覆盖 query-like payload、V3 rejection、warnings 和 auth/error codec，但缺少本矩阵消息族的显式 extra negative tests。 |

## Source Contract

### Frame Prelude

| Direction | Flag | Body prelude | Version gate | Source |
|---|---|---|---|---|
| Request | `TRACING` | None; only header flag and `Request.tracingRequested` | all decoded versions | `src/java/org/apache/cassandra/transport/Message.java:385`、`src/java/org/apache/cassandra/transport/Message.java:452` |
| Request | `WARNING` | None; request decode ignores warning-list prelude | no explicit rejection | `src/java/org/apache/cassandra/transport/Message.java:435` |
| Request | `CUSTOM_PAYLOAD` | bytes map before message body | V4+ only | `src/java/org/apache/cassandra/transport/Message.java:387`、`src/java/org/apache/cassandra/transport/Message.java:438` |
| Response | `TRACING` | trace UUID before warnings/payload/body | all response versions when set | `src/java/org/apache/cassandra/transport/Message.java:341`、`src/java/org/apache/cassandra/transport/Message.java:366` |
| Response | `WARNING` | string list after tracing UUID | V4+ emitted; lower versions log and drop | `src/java/org/apache/cassandra/transport/Message.java:345`、`src/java/org/apache/cassandra/transport/Message.java:371` |
| Response | `CUSTOM_PAYLOAD` | bytes map after warnings | V4+ only | `src/java/org/apache/cassandra/transport/Message.java:359`、`src/java/org/apache/cassandra/transport/Message.java:376` |

`native_protocol_extras_frame_prelude_contract` is therefore asymmetric: a response can have three prelude fields, while a request only has custom payload bytes; request tracing and warning bits are header-only from the server decoder perspective.

### Request Negative Matrix

| Message.Type | Class | `isTraceable()` | `isTrackable()` | Custom payload effect | Tracing flag effect | Warning flag effect |
|---|---|---:|---:|---|---|---|
| `OPTIONS` | `OptionsMessage` | false inherited | false inherited | Decoded and attached by `Message.Decoder`, then ignored by `OptionsMessage.execute()`; `SUPPORTED` response is built from static supported maps. | `tracingRequested=true`, but no trace session/id because `Request.execute()` gate stays false. | Decoder ignores warning list for requests; no request warning semantics. |
| `STARTUP` | `StartupMessage` | false inherited | false inherited | Decoded and attached, then ignored while startup options drive compression/auth/ready. | No trace session/id. | Decoder ignores warning list; startup body parser expects string map. |
| `AUTH_RESPONSE` | `AuthResponse` | false inherited | false inherited | Decoded and attached, then ignored by SASL token evaluation. | No trace session/id. | Decoder ignores warning list; auth body parser expects value bytes. |

Source anchors:

- `OptionsMessage` extends `Message.Request`, has zero-length body codec, and returns `SupportedMessage`, see `src/java/org/apache/cassandra/transport/messages/OptionsMessage.java:37`、`src/java/org/apache/cassandra/transport/messages/OptionsMessage.java:50`、`src/java/org/apache/cassandra/transport/messages/OptionsMessage.java:78`。
- `StartupMessage` extends `Message.Request`, decodes a string map, and returns `AuthenticateMessage` or `ReadyMessage`, see `src/java/org/apache/cassandra/transport/messages/StartupMessage.java:122`、`src/java/org/apache/cassandra/transport/messages/StartupMessage.java:133`、`src/java/org/apache/cassandra/transport/messages/StartupMessage.java:208`。
- `AuthResponse` extends `Message.Request`, rejects SASL on V1, and returns `AuthSuccess`、`AuthChallenge` or `ErrorMessage`, see `src/java/org/apache/cassandra/transport/messages/AuthResponse.java:36`、`src/java/org/apache/cassandra/transport/messages/AuthResponse.java:42`、`src/java/org/apache/cassandra/transport/messages/AuthResponse.java:85`。

Contrast with query-like requests:

| Message.Type | Traceable | Trackable | Custom payload consumed |
|---|---:|---:|---|
| `QUERY` | true | true | `QueryHandler.process(..., customPayload, ...)` via `QueryMessage.execute()` |
| `PREPARE` | true | false inherited | `QueryHandler.prepare(..., customPayload)` via `PrepareMessage.execute()` |
| `EXECUTE` | true | true | `QueryHandler.processPrepared(..., customPayload, ...)` via `ExecuteMessage.execute()` |
| `BATCH` | true | true | `QueryHandler.processBatch(..., customPayload, ...)` via `BatchMessage.execute()` |

The current implementation makes `native_protocol_extras_options_startup_auth_payload_negative` explicit: frame-level payload is legal for V4+ but semantically unused outside the query handler path.

### Response Matrix

| Response type | Producer path | Body codec | Generic extras status |
|---|---|---|---|
| `ERROR` | `ErrorMessage.fromException()` and dispatcher catch paths | error code + message + type-specific details | Can carry tracing id, warnings and custom payload if fields are set; dispatcher attaches warnings on normal and error paths. |
| `EVENT` | registered event fanout, stream id `-1` | serialized `Event` body | Inherits response extras, but normal async event producers do not set tracing/warnings/custom payload. |
| `SUPPORTED` | `OptionsMessage.execute()` | string-to-string-list map | Inherits response extras; normal OPTIONS path does not set payload/tracing. |
| `AUTHENTICATE` | `StartupMessage.execute()` through authenticator | authenticator FQCN string | Inherits response extras; normal startup auth challenge does not set payload/tracing. |
| `AUTH_CHALLENGE` | `AuthResponse.execute()` incomplete SASL | token value | Inherits response extras; body codec only writes token. |
| `AUTH_SUCCESS` | `AuthResponse.execute()` complete SASL | optional token value | Inherits response extras; body codec only writes token. |

Source anchors:

- `ErrorMessage` extends `Message.Response`, codec starts at `src/java/org/apache/cassandra/transport/messages/ErrorMessage.java:44` and `src/java/org/apache/cassandra/transport/messages/ErrorMessage.java:48`。
- `EventMessage` extends `Message.Response` and sets stream id `-1`, see `src/java/org/apache/cassandra/transport/messages/EventMessage.java:26`、`src/java/org/apache/cassandra/transport/messages/EventMessage.java:52`。
- `SupportedMessage` extends `Message.Response`, see `src/java/org/apache/cassandra/transport/messages/SupportedMessage.java:32`。
- `AuthenticateMessage` extends `Message.Response`, see `src/java/org/apache/cassandra/transport/messages/AuthenticateMessage.java:29`。
- `AuthChallenge` extends `Message.Response`, see `src/java/org/apache/cassandra/transport/messages/AuthChallenge.java:30`。
- `AuthSuccess` extends `Message.Response`, see `src/java/org/apache/cassandra/transport/messages/AuthSuccess.java:33`。

## 设计目标

- 防止把 frame-level custom payload 误认为所有 request 的业务级 payload。
- 防止把 request `TRACING` flag 误认为所有 request 都会生成 trace session 和 response trace id。
- 明确 `WARNING` flag 的 response-only 正常语义，以及 request-side flag 没有 warning prelude 解析。
- 把 query-like request coverage 与 handshake/auth/error/event coverage 分开，便于后续补测试。

## 解决的问题

- Drivers or tests can legally set `CUSTOM_PAYLOAD` on V4+ frames for message types whose execute path ignores it; this is not the same as query payload propagation.
- A tracing flag on `OPTIONS`、`STARTUP` or `AUTH_RESPONSE` does not imply `system_traces` writes or response `TRACING` UUID.
- Request warning flag handling is permissive rather than a strict protocol error; adding a warning-list body to a request can shift what the message codec reads.
- `ERROR` and auth responses inherit extras because they are `Message.Response`, but their codecs do not define message-specific payload fields beyond error/auth bodies.

## 设计取舍

- `Message` centralizes extra prelude encode/decode instead of duplicating it per message codec.
- `isTraceable()` and `isTrackable()` are opt-in hooks on request classes; default false keeps handshake/auth paths cheap and avoids coordinator warning setup.
- Warnings are captured by `Dispatcher` for V4+ connections before request execution; coordinator read/write warnings are additionally gated by `isTrackable()`.
- Custom payload version rejection is strict for V3 and lower, because older protocol versions cannot negotiate/parse the extra prelude.

## 核心类

| 类 | 作用 |
|---|---|
| `Message.Request` | Default `isTraceable=false` and `isTrackable=false`; owns trace wrapper and response trace id assignment. |
| `Message.Response` | Holds `tracingId` and `warnings`; inherits generic custom payload field from `Message`. |
| `Message.encode()` | Writes response/request extra preludes and V4 custom payload guards. |
| `Message.Decoder.decodeMessage()` | Reads inbound extras, applies request trace flag, and attaches custom payload. |
| `Dispatcher` | Captures warnings, gates `CoordinatorWarnings`, and attaches response warnings. |
| `OptionsMessage` / `StartupMessage` / `AuthResponse` | Target request messages that inherit false tracing/tracking and ignore custom payload. |
| `ErrorMessage` / `EventMessage` / auth response classes | Target response messages that inherit generic response extras. |
| `research/tools/check-native-protocol-extras-drift.py` | Source-to-doc drift checker for this matrix. |

## 核心接口

- `Message.Request.isTraceable()` / `isTrackable()`：request opt-in hooks。
- `Message.Request.execute(QueryState, RequestTime)`：starts/stops tracing only when `isTraceable()` allows it。
- `Message.Response.setTracingId()` / `setWarnings()`：response extra fields consumed by `Message.encode()`。
- `Message.setCustomPayload()` / `getCustomPayload()`：frame-level payload attached to both request and response instances。
- `QueryHandler.prepare/process/processPrepared/processBatch()`：only query-like custom payload business interface.

## 生命周期

```text
inbound frame
  -> Message.Decoder.decodeMessage()
     -> read response tracing/warnings or request custom payload prelude
     -> attach custom payload to Message
     -> if request and TRACING flag set: setTracingRequested()
  -> Dispatcher.processRequest()
     -> capture ClientWarn for V4+
     -> if request.isTrackable(): CoordinatorWarnings.init()
     -> request.execute()
        -> if request.isTraceable() and tracingRequested: start trace
     -> response.setWarnings(ClientWarn.getWarnings())
  -> Message.encode()
     -> response prefix: tracing UUID, warnings, custom payload
     -> request prefix: custom payload only
```

## 配置项

- `native_transport_allow_older_protocols` affects whether V3/V4 clients are admitted, but it does not change the V4 custom payload gate.
- Native transport queue/backpressure settings can produce `ClientWarn` warnings on any V4+ request path; coordinator warning aggregation still needs `isTrackable()`.
- Auth executor settings change where `AUTH_RESPONSE` executes, not its tracing/custom payload semantics.

## Metrics

- `AuthResponse` updates auth success/failure metrics via `ClientMetrics.markAuthSuccess()` and `markAuthFailure()`, independent of custom payload.
- Backpressure warnings can appear on response warnings and are covered by transport/client resource tests.
- Tracing metrics/session writes are absent for non-traceable request messages even when the request had a `TRACING` flag.

## 日志

- Response warnings on protocol `< V4` are logged and dropped by `Message.encode()` as a server-side bug signal.
- Custom payload on protocol `< V4` throws protocol errors with `Must not send...` or `Received frame...` wording.
- Startup compression/auth protocol errors are still ordinary `STARTUP` body errors, not extra-flag errors.

## 运维关注点

- Do not use `OPTIONS`/`STARTUP`/`AUTH_RESPONSE` custom payload as an extension API unless the server execute path is changed to consume it.
- Tracing handshakes or auth exchanges by setting the native `TRACING` flag will not produce trace rows today.
- For driver compatibility, treat request `WARNING` as unsupported/undefined even though the decoder does not explicitly reject the bit.
- Event consumers should not expect warning/custom payload metadata on normal `EVENT` fanout.

## 性能瓶颈

- Extra prelude parsing is cheap, but large custom payload maps still allocate and count toward frame/message size even when later ignored by the request execute path.
- Enabling coordinator warning tracking is avoided for `OPTIONS`、`STARTUP`、`AUTH_RESPONSE`; making them trackable would add per-request warning state.
- Response warnings/custom payload increase serialized response size before the message body.

## 常见故障

- `Received frame with CUSTOM_PAYLOAD flag for native protocol version < 4`：V3 or lower client sent custom payload.
- Missing tracing id after `OPTIONS`/`STARTUP`/`AUTH_RESPONSE` with `TRACING` flag：expected behavior because these requests are not traceable.
- Request with `WARNING` flag fails body decoding：the decoder did not consume a warning-list prelude, so the message codec may interpret those bytes as its own body.
- Custom payload appears in decoded message but has no effect：target request execute path does not call `getCustomPayload()`.

## 测试用例

- `MessagePayloadTest` covers custom payload on `QUERY`、`PREPARE`、`EXECUTE`、`BATCH`, V5 beta payload, and V3 rejection, see `test/unit/org/apache/cassandra/transport/MessagePayloadTest.java:115`、`test/unit/org/apache/cassandra/transport/MessagePayloadTest.java:195`、`test/unit/org/apache/cassandra/transport/MessagePayloadTest.java:265`。
- `ProtocolNegotiationTest` covers `OPTIONS` and `STARTUP` stream-id negotiation without extras, see `test/unit/org/apache/cassandra/transport/ProtocolNegotiationTest.java:121`、`test/unit/org/apache/cassandra/transport/ProtocolNegotiationTest.java:137`。
- `RateLimitingTest` and `ClientResourceLimitsTest` cover V4+ warning attachment for overloaded query paths, see `test/unit/org/apache/cassandra/transport/RateLimitingTest.java:220` and `test/unit/org/apache/cassandra/transport/ClientResourceLimitsTest.java:133`。
- `ErrorMessageTest` covers error body codec compatibility but not generic response extras on `ERROR`, see `test/unit/org/apache/cassandra/transport/ErrorMessageTest.java:62`。
- `AuthenticateMessageTest` and `AuthMessageSizeLimitTest` cover auth response/request bodies and limits, not extras on auth messages, see `test/unit/org/apache/cassandra/transport/messages/AuthenticateMessageTest.java:30` and `test/unit/org/apache/cassandra/transport/AuthMessageSizeLimitTest.java:102`。
- `python3 research/tools/check-native-protocol-extras-drift.py` validates this matrix against source and docs.
