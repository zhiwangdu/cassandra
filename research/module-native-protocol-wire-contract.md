# Module: Native Protocol Wire Contract

## 范围

本模块把 native CQL binary protocol 的 wire contract 单独列出：message opcode、protocol version、envelope header flag、query option flag、server event type、error code 和相关测试锚点。目标不是替代 `module-native-protocol.md` 的执行链路，而是给驱动兼容性、跨版本升级和协议负例测试提供可 drift-check 的源码基线。`OPTIONS`/`STARTUP`/`AUTH_RESPONSE`、`ERROR`、`EVENT` 和 auth response family 的 extra flag negative matrix 见 `research/module-native-protocol-extras-negative-matrix.md`。

当前基线：

- 17 Message.Type opcodes，来自 `src/java/org/apache/cassandra/transport/Message.java:69-87`。
- 6 ProtocolVersion enum constants，其中 V3/V4/V5/V6 supported，CURRENT=V5，BETA=V6，来自 `src/java/org/apache/cassandra/transport/ProtocolVersion.java:38-83`。
- 5 Envelope.Header.Flag values，来自 `src/java/org/apache/cassandra/transport/Envelope.java:153-160`。
- 9 QueryOptions.Codec.Flag values，来自 `src/java/org/apache/cassandra/cql3/QueryOptions.java:572-583`。
- 4 Event.Type values，来自 `src/java/org/apache/cassandra/transport/Event.java:33-38`。
- 20 ExceptionCode values，来自 `src/java/org/apache/cassandra/exceptions/ExceptionCode.java:32-58`。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `native_protocol_message_opcode_baseline` | `Message.Type` opcode、direction 和 codec 注册表。 |
| `native_protocol_version_baseline` | protocol enum、supported/current/beta、known invalid DSE version 和 old protocol disable gate。 |
| `native_protocol_envelope_flag_baseline` | envelope header flag bit order，包括 `USE_BETA` gate。 |
| `native_protocol_query_option_flag_baseline` | query option flag bit order、V5+ 32-bit flag field 和 V5+ keyspace/now-in-seconds。 |
| `native_protocol_event_type_baseline` | event type minimum protocol version、topology/status/schema/trace-complete surface。 |
| `native_protocol_error_code_baseline` | binary protocol error code enum 和 value-to-code lookup。 |
| `native_protocol_payload_warning_tracing_contract` | request/response custom payload、warning、tracing id 的 flag/body placement。 |
| `native_protocol_negative_test_surface` | invalid version、wrong direction、oversize frame、unsupported CREDENTIALS、custom payload V3 rejection。 |
| `native_protocol_driver_compatibility_gap` | 当前 source/test 已覆盖 server/Java driver negotiation，但仍缺完整跨 driver compatibility matrix。 |

## Source Contract

### Message Opcodes

| Opcode | Message.Type | Direction | Codec/source |
|---:|---|---|---|
| 0 | `ERROR` | RESPONSE | `ErrorMessage.codec` |
| 1 | `STARTUP` | REQUEST | `StartupMessage.codec` |
| 2 | `READY` | RESPONSE | `ReadyMessage.codec` |
| 3 | `AUTHENTICATE` | RESPONSE | `AuthenticateMessage.codec` |
| 4 | `CREDENTIALS` | REQUEST | `UnsupportedMessageCodec.instance` |
| 5 | `OPTIONS` | REQUEST | `OptionsMessage.codec` |
| 6 | `SUPPORTED` | RESPONSE | `SupportedMessage.codec` |
| 7 | `QUERY` | REQUEST | `QueryMessage.codec` |
| 8 | `RESULT` | RESPONSE | `ResultMessage.codec` |
| 9 | `PREPARE` | REQUEST | `PrepareMessage.codec` |
| 10 | `EXECUTE` | REQUEST | `ExecuteMessage.codec` |
| 11 | `REGISTER` | REQUEST | `RegisterMessage.codec` |
| 12 | `EVENT` | RESPONSE | `EventMessage.codec` |
| 13 | `BATCH` | REQUEST | `BatchMessage.codec` |
| 14 | `AUTH_CHALLENGE` | RESPONSE | `AuthChallenge.codec` |
| 15 | `AUTH_RESPONSE` | REQUEST | `AuthResponse.codec` |
| 16 | `AUTH_SUCCESS` | RESPONSE | `AuthSuccess.codec` |

`Message.Type.fromOpcode()` rejects unknown opcode and wrong direction, so opcode drift is an externally visible compatibility change; see `src/java/org/apache/cassandra/transport/Message.java:115-128` and `test/unit/org/apache/cassandra/transport/ProtocolErrorTest.java:102-130`.

### Protocol Versions

| Version | Wire number | Description | Beta | Support state |
|---|---:|---|---|---|
| `V1` | 1 | `v1` | false | unsupported old version |
| `V2` | 2 | `v2` | false | unsupported old version |
| `V3` | 3 | `v3` | false | supported |
| `V4` | 4 | `v4` | false | supported |
| `V5` | 5 | `v5` | false | supported and CURRENT |
| `V6` | 6 | `v6-beta` | true | supported beta |

`SUPPORTED_VERSIONS` is `{ V3, V4, V5, V6 }`; `CURRENT` is `V5`; `BETA` is `Optional.of(V6)`; known invalid DSE versions are `66` and `65`. `ProtocolVersion.decode()` returns supported versions, rejects V1/V2 with a forced response version, silently handles known invalid DSE versions, and rejects supported versions lower than `CURRENT` when `native_transport_allow_older_protocols=false`; see `src/java/org/apache/cassandra/transport/ProtocolVersion.java:65-130`.

### Envelope Header Flags

| Bit order | Flag | Meaning |
|---:|---|---|
| 0 | `COMPRESSED` | Body is compressed after negotiated compression. |
| 1 | `TRACING` | Request asks for tracing; response body starts with trace UUID. |
| 2 | `CUSTOM_PAYLOAD` | Body carries bytes map before the message body. |
| 3 | `WARNING` | Response body carries warning string list before the message body. |
| 4 | `USE_BETA` | Required when using beta protocol version such as V6. |

The enum order is the bit contract. `Envelope.Decoder.decodeFlags()` rejects beta protocol frames without `USE_BETA`; see `src/java/org/apache/cassandra/transport/Envelope.java:423-430`. `Message.encode()` sets `TRACING`, `WARNING`, `CUSTOM_PAYLOAD`, and `USE_BETA` on the response path; request decode reads `TRACING` and `CUSTOM_PAYLOAD`, while custom payload on protocol `< V4` is rejected; see `src/java/org/apache/cassandra/transport/Message.java:329-417` and `src/java/org/apache/cassandra/transport/Message.java:425-463`.

### Query Option Flags

| Bit order | Flag | Meaning |
|---:|---|---|
| 0 | `VALUES` | Values or named values are present. |
| 1 | `SKIP_METADATA` | Result metadata may be omitted. |
| 2 | `PAGE_SIZE` | Page size integer is present. |
| 3 | `PAGING_STATE` | Paging state bytes are present. |
| 4 | `SERIAL_CONSISTENCY` | Serial consistency is present. |
| 5 | `TIMESTAMP` | Client timestamp is present. |
| 6 | `NAMES_FOR_VALUES` | Bind values are named. |
| 7 | `KEYSPACE` | V5+ keyspace is present. |
| 8 | `NOW_IN_SECONDS` | V5+ now-in-seconds is present. |

For V5+ query options the flag field is 32-bit; for older supported protocols it is one byte. `KEYSPACE` and `NOW_IN_SECONDS` are gathered only for V5+; see `src/java/org/apache/cassandra/cql3/QueryOptions.java:607-666` and `src/java/org/apache/cassandra/cql3/QueryOptions.java:715-738`. This means driver compatibility bugs can appear when a prepared/query path assumes V5-only keyspace or now-in-seconds fields for V3/V4 clients.

### Events

| Event.Type | Minimum version | Body enum surface |
|---|---|---|
| `TOPOLOGY_CHANGE` | `V3` | `NEW_NODE`, `REMOVED_NODE`, `MOVED_NODE` |
| `STATUS_CHANGE` | `V3` | `UP`, `DOWN` |
| `SCHEMA_CHANGE` | `V3` | `CREATED`, `UPDATED`, `DROPPED`; targets `KEYSPACE`, `TABLE`, `TYPE`, `FUNCTION`, `AGGREGATE` |
| `TRACE_COMPLETE` | `V4` | Type exists in the enum; normal `Event.deserialize()` switches only topology/status/schema. |

`REGISTER` decodes a list of `Event.Type` values and rejects any event whose minimum version is greater than the negotiated connection version; see `src/java/org/apache/cassandra/transport/messages/RegisterMessage.java:32-77`. `SerDeserTest.eventSerDeserTest()` covers topology, status and schema event bodies across supported protocol versions; see `test/unit/org/apache/cassandra/transport/SerDeserTest.java:160-212`.

### Error Codes

| Value | ExceptionCode |
|---:|---|
| `0x0000` | `SERVER_ERROR` |
| `0x000A` | `PROTOCOL_ERROR` |
| `0x0100` | `BAD_CREDENTIALS` |
| `0x1000` | `UNAVAILABLE` |
| `0x1001` | `OVERLOADED` |
| `0x1002` | `IS_BOOTSTRAPPING` |
| `0x1003` | `TRUNCATE_ERROR` |
| `0x1100` | `WRITE_TIMEOUT` |
| `0x1200` | `READ_TIMEOUT` |
| `0x1300` | `READ_FAILURE` |
| `0x1400` | `FUNCTION_FAILURE` |
| `0x1500` | `WRITE_FAILURE` |
| `0x1600` | `CDC_WRITE_FAILURE` |
| `0x1700` | `CAS_WRITE_UNKNOWN` |
| `0x2000` | `SYNTAX_ERROR` |
| `0x2100` | `UNAUTHORIZED` |
| `0x2200` | `INVALID` |
| `0x2300` | `CONFIG_ERROR` |
| `0x2400` | `ALREADY_EXISTS` |
| `0x2500` | `UNPREPARED` |

The current enum has 20 numeric entries. Source drift checker uses the actual enum entries and will fail if this table and source diverge. `ExceptionCode.fromValue()` rejects unknown codes; see `src/java/org/apache/cassandra/exceptions/ExceptionCode.java:60-79`.

## 设计目标

- 把 wire-visible enum/flag order 变成可运行 drift gate，避免只在 prose 中手工维护 opcode 和 bit contract。
- 为 driver compatibility matrix 提供源码基线：driver 必须正确处理 V3/V4/V5/V6 beta、custom payload、warnings、tracing、query option field width 和 error/event body。
- 让 protocol negative tests 的缺口可见：unsupported opcode/direction、old version、beta without `USE_BETA`、oversize body、V3 custom payload、unknown error code。

## 解决的问题

- `Message.Type` 是 request/response body codec 的注册表；新增或重排 opcode 会影响所有 drivers。
- `ProtocolVersion.CURRENT` 和 `BETA` 共同决定 Java driver negotiation 默认值与 beta opt-in 行为。
- `Envelope.Header.Flag` 和 `QueryOptions.Codec.Flag` 的 enum order 就是 bit order，不能当成普通内部 enum 改动。
- `Event.Type` 同时影响 `REGISTER` request 和 server event fanout；新增事件必须考虑 minimum version 和 serde 测试。
- `ExceptionCode` 是 ERROR response 的稳定 ABI；新增错误码需要 driver fallback 和 protocol doc 同步。

## 设计取舍

- 本模块只维护 source-level contract，不启动 Cassandra、不跑 driver integration test。
- checker 比较 enum/flag/order 的完整 baseline；对 message body 细节只检查关键 source tokens 和测试锚点。
- `TRACE_COMPLETE` 当前只作为 enum surface 被跟踪；没有把它当作普通 topology/status/schema event body 解析。
- V5 large frame 的 CRC/LZ4/fragments 已由 `module-schema-cql-auth-native-deep-dive.md` 和 `module-native-protocol.md` 覆盖，本模块只记录 V5+ query-option flag width 与 beta gate。

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `Message.Type` | opcode、direction、codec baseline，见 `src/java/org/apache/cassandra/transport/Message.java:69-128`。 |
| `ProtocolVersion` | version enum、supported/current/beta 和 decode rules，见 `src/java/org/apache/cassandra/transport/ProtocolVersion.java:38-130`。 |
| `Envelope.Header.Flag` | header flag bit order 和 beta gate，见 `src/java/org/apache/cassandra/transport/Envelope.java:153-180`。 |
| `QueryOptions.Codec.Flag` | query option bit order、V5+ 32-bit flag field、keyspace/now-in-seconds gate，见 `src/java/org/apache/cassandra/cql3/QueryOptions.java:572-738`。 |
| `Event.Type` | event minimum version surface，见 `src/java/org/apache/cassandra/transport/Event.java:33-75`。 |
| `ExceptionCode` | binary protocol error code enum，见 `src/java/org/apache/cassandra/exceptions/ExceptionCode.java:32-79`。 |
| `research/tools/check-native-protocol-wire-drift.py` | 解析上述 source baseline 并校验 research 文档覆盖。 |

## 核心接口

- `Message.Type.fromOpcode()`：opcode -> type，并验证 direction。
- `ProtocolVersion.decode()`：version byte -> supported version 或 protocol exception。
- `Envelope.Header.Flag.serialize()` / `deserialize()`：enum ordinal -> header bitset。
- `QueryOptions.Codec.decode()` / `encode()` / `gatherFlags()`：query option flag field、values/options/keyspace/now-in-seconds serde。
- `Event.serialize()` / `deserialize()`：event type minimum version 和 event body serde。
- `ExceptionCode.fromValue()`：wire int -> error code enum。

## 生命周期

```text
source changes protocol enum/flag/error/event surface
  -> run python3 research/tools/check-native-protocol-wire-drift.py
  -> checker parses Message.Type / ProtocolVersion / Envelope.Flag / QueryOptions.Flag / Event.Type / ExceptionCode
  -> checker compares source baseline and research docs
  -> update docs, tests and driver compatibility matrix before merge
```

## 调用链

```text
client frame
  -> Envelope.Decoder
     -> ProtocolVersion.decode()
     -> Envelope.Header.Flag.deserialize()
     -> Message.Type.fromOpcode()
  -> Message.Decoder.decodeMessage()
     -> read tracing/warning/custom-payload prelude
     -> Message.Type.codec.decode()
  -> QueryOptions.codec.decode() for QUERY/EXECUTE/BATCH
  -> Message.Request.execute()
  -> Message.Response.encode()
     -> write tracing/warning/custom-payload prelude
     -> set USE_BETA if response version is beta
```

## 配置项

- `native_transport_allow_older_protocols` controls whether supported versions lower than `CURRENT` are accepted by `ProtocolVersion.decode()`; see `src/java/org/apache/cassandra/config/Config.java:292` and `src/java/org/apache/cassandra/transport/ProtocolVersion.java:128-129`.
- `native_transport_max_frame_size` and `native_transport_max_message_size` influence oversize frame behavior but do not change opcode/flag baseline.
- TLS settings influence pipeline and certificate handling, not the wire enum baseline tracked here.

## Metrics

- Protocol exceptions increment client/protocol observability through the same native transport metrics described in `module-native-protocol.md`.
- `ClientMessageSizeMetrics` records body/header transfer size; flag/opcode drift changes may alter the bytes counted but not the metric names.
- The checker reports counts for message opcodes, supported versions, envelope flags, query option flags, event types and error codes.

## 日志

- Invalid protocol version, unknown opcode, wrong direction, missing beta flag and custom payload on old protocol are surfaced as protocol errors before statement execution.
- Oversize body is wrapped as request-too-big with the stream id when the envelope decoder can extract it.
- Unknown error code is rejected by `ExceptionCode.fromValue()`.

## 运维关注点

- Mixed driver fleets must be evaluated against `CURRENT=V5` and beta `V6`; Java driver negotiation tests are not a complete cross-driver matrix.
- `native_transport_allow_older_protocols=false` rejects V3/V4 even though they are in `SUPPORTED`, which can break older clients at startup.
- V5+ `KEYSPACE` and `NOW_IN_SECONDS` query option flags mean server-side behavior may differ for the same query between V4 and V5+ clients.
- `CUSTOM_PAYLOAD` is protocol V4+ only. V3 clients with custom payload should fail, and `MessagePayloadTest.testMessagePayloadVersion3` covers that rejection.
- `WARNING` is response-side only in normal server use; receiving a request with the bit set does not create request warnings because `Message.Decoder` reads warnings only for responses.
- `OPTIONS`、`STARTUP`、`AUTH_RESPONSE` custom payload/tracing/warning negative semantics are tracked in `native_protocol_extras_options_startup_auth_payload_negative` and `native_protocol_extras_request_tracing_noop_matrix`.

## 性能瓶颈

- Wire contract changes usually cost compatibility more than CPU. The hot-path cost is still flag parsing, body prelude reads and query option decode.
- V5+ 32-bit query flags add no material cost, but extra keyspace/now-in-seconds fields can affect prepared/query cache behavior.
- Custom payload and warnings add body bytes before the message body and can increase allocation/serialization cost on response-heavy workloads.

## 常见故障

- `Wrong protocol direction`：client sent a request opcode with response direction bit or the reverse; covered by `ProtocolErrorTest.testInvalidDirection`.
- `Invalid or unsupported protocol version`：version is old/unknown/disabled, or known invalid DSE version.
- `Beta version ... USE_BETA flag is unset`：client uses V6 without beta opt-in.
- `Must not send frame with CUSTOM_PAYLOAD flag for native protocol version < 4`：V3 client used custom payload.
- `Unknown error code`：ERROR body carries an int absent from `ExceptionCode`.

## 测试用例

- `python3 research/tools/check-native-protocol-wire-drift.py`：source-only native protocol wire contract drift check。
- `python3 research/tools/check-native-protocol-extras-drift.py`：source-only native protocol extra negative matrix drift check。
- `python3 research/tools/check-native-protocol-wire-drift.py --json`：输出 opcode/version/flag/event/error baseline 和失败项。
- `ProtocolVersionTest` 覆盖 decode、supported versions、CURRENT/BETA 和禁用老协议，见 `test/unit/org/apache/cassandra/transport/ProtocolVersionTest.java:31-146`。
- `ProtocolNegotiationTest` 覆盖 driver requested version、default V5、V6 beta opt-in、stream id negotiation 和 wrong version rejection，见 `test/unit/org/apache/cassandra/transport/ProtocolNegotiationTest.java:53-225`。
- `ProtocolErrorTest` 覆盖 invalid version、wrong direction、oversize body、null error string 和 unsupported `CREDENTIALS`，见 `test/unit/org/apache/cassandra/transport/ProtocolErrorTest.java:42-195`。
- `SerDeserTest.eventSerDeserTest()` 覆盖 topology/status/schema event serde，见 `test/unit/org/apache/cassandra/transport/SerDeserTest.java:160-212`。
- `SerDeserTest.queryOptionsSerDeserTest()` 覆盖 V3+ query options 和 V5+ keyspace/now-in-seconds，见 `test/unit/org/apache/cassandra/transport/SerDeserTest.java:377-449`。
- `MessagePayloadTest` 覆盖 custom payload on QUERY/PREPARE/EXECUTE/BATCH、V5 beta payload 和 V3 rejection，见 `test/unit/org/apache/cassandra/transport/MessagePayloadTest.java:115-193`、`test/unit/org/apache/cassandra/transport/MessagePayloadTest.java:195-340`。
- `ErrorMessageTest` 覆盖 V5 read/write failure、CAS timeout/unknown result 和 V4 downgrade compatibility，见 `test/unit/org/apache/cassandra/transport/ErrorMessageTest.java:62-170`。
