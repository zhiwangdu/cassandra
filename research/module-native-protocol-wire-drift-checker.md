# Module: Native Protocol Wire Drift Checker

## 范围

`research/tools/check-native-protocol-wire-drift.py` 是 source-only drift check，用来保护 native CQL protocol wire contract 在 research 文档中的覆盖。它解析 `Message.Type`、`ProtocolVersion`、`Envelope.Header.Flag`、`QueryOptions.Codec.Flag`、`Event.Type` 和 `ExceptionCode`，并验证 `module-native-protocol-wire-contract.md`、`module-native-protocol.md` 与 `flow-native-protocol.md` 包含对应场景、源码路径、测试锚点和基线 token。

当前基线：

- 17 Message.Type opcodes。
- 6 ProtocolVersion enum constants；supported set 是 V3/V4/V5/V6，CURRENT=V5，BETA=V6，known invalid versions 是 66/65。
- 5 Envelope.Header.Flag values。
- 9 QueryOptions.Codec.Flag values。
- 4 Event.Type values。
- 20 ExceptionCode wire error values。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `native_protocol_message_opcode_baseline` | `Message.Type` opcode/direction/codec tuple。 |
| `native_protocol_version_baseline` | `ProtocolVersion` enum、supported/current/beta 和 known invalid versions。 |
| `native_protocol_envelope_flag_baseline` | `Envelope.Header.Flag` bit order 和 beta flag gate。 |
| `native_protocol_query_option_flag_baseline` | `QueryOptions.Codec.Flag` bit order、V5+ 32-bit flags 和 keyspace/now-in-seconds gate。 |
| `native_protocol_event_type_baseline` | `Event.Type` minimum protocol version 和 event enum body surface。 |
| `native_protocol_error_code_baseline` | `ExceptionCode` wire values 和 lookup。 |
| `native_protocol_payload_warning_tracing_contract` | custom payload、warning、tracing body prelude 与 protocol-version guard。 |
| `native_protocol_negative_test_surface` | invalid version、wrong direction、oversize frame、unsupported credentials、V3 custom payload rejection。 |
| `native_protocol_driver_compatibility_gap` | 记录跨 driver compatibility matrix 仍是未完成的外部测试面。 |

## 设计目标

- 让 protocol enum/flag/order 变化在本地 research 校验中立即失败。
- 把 native protocol 的 source-level ABI 和测试锚点集中到一个可审查文档。
- 为后续补跨 driver/protocol compatibility matrix 提供稳定源码 baseline。

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-native-protocol-wire-drift.py` | 解析 native protocol source baseline 并检查 docs coverage。 |
| `Message.Type` | opcode/direction/codec baseline，见 `src/java/org/apache/cassandra/transport/Message.java:69-87`。 |
| `ProtocolVersion` | version/support/current/beta baseline，见 `src/java/org/apache/cassandra/transport/ProtocolVersion.java:38-83`。 |
| `Envelope.Header.Flag` | header flag bit order，见 `src/java/org/apache/cassandra/transport/Envelope.java:153-160`。 |
| `QueryOptions.Codec.Flag` | query option flag bit order，见 `src/java/org/apache/cassandra/cql3/QueryOptions.java:572-583`。 |
| `Event.Type` | event type minimum version，见 `src/java/org/apache/cassandra/transport/Event.java:33-38`。 |
| `ExceptionCode` | ERROR response code enum，见 `src/java/org/apache/cassandra/exceptions/ExceptionCode.java:32-58`。 |

## 核心接口

- `message_types()`：解析 `Message.Type` 的 `(name, opcode, direction, codec)`。
- `protocol_versions()`：解析 protocol enum entries、supported/current/beta/known-invalid baseline。
- `envelope_flags()` / `query_option_flags()`：解析 bit-order enum。
- `event_types()`：解析 event type minimum version。
- `exception_codes()`：解析 error code name/value。
- `doc_checks()`：检查 scenario ids、source paths、test anchors 和 baseline token。

## 生命周期

```text
developer changes native protocol source
  -> run python3 research/tools/check-native-protocol-wire-drift.py
  -> checker compares source against expected baseline
  -> checker validates research docs mention the changed surface
  -> update docs/baseline/tests or keep source change out
```

## 运维关注点

- 本 checker 不替代 real driver compatibility test；它只保证 research 目录不会漏掉 source-visible ABI 变化。
- `ProtocolVersion.CURRENT` / `BETA` 和 `native_transport_allow_older_protocols` 的组合仍需要升级前真实 client inventory。
- ERROR code 和 event enum 新增必须同步 driver handling、protocol docs 和 test fixtures。

## 常见故障

- `Message.Type tuples match baseline` fails：opcode/direction/codec 发生变化。
- `ProtocolVersion supported/current/beta baseline` fails：protocol support policy 发生变化。
- `Envelope.Header.Flag order matches baseline` 或 `QueryOptions.Codec.Flag order matches baseline` fails：wire bit order 变化，属于高风险兼容性改动。
- `ExceptionCode values match baseline` fails：ERROR response ABI 变化。
- `doc token ...` fails：source 变化或新增测试未进入 research 文档。

## 测试用例

- `python3 research/tools/check-native-protocol-wire-drift.py`。
- `python3 research/tools/check-native-protocol-wire-drift.py --json`。
- 与源码行为相关的 Java 测试锚点：`ProtocolVersionTest.java`、`ProtocolNegotiationTest.java`、`ProtocolErrorTest.java`、`SerDeserTest.java`、`MessagePayloadTest.java`、`ErrorMessageTest.java`。
