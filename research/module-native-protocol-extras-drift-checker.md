# Module: Native Protocol Extras Drift Checker

## 范围

`research/tools/check-native-protocol-extras-drift.py` 是 source-only drift check，用来保护 native protocol extra flags negative matrix 的 research 覆盖。它验证 `Message` 的 frame prelude gate、`Dispatcher` warning/tracking gate、`OPTIONS`/`STARTUP`/`AUTH_RESPONSE` 的非 traceable/trackable request profile、response family 的 `Message.Response` 继承关系，以及现有 Java test coverage gap。

当前基线：

- Non-traceable/non-trackable request targets: `OPTIONS`、`STARTUP`、`AUTH_RESPONSE`。
- Traceable request comparison set: `QUERY`、`PREPARE`、`EXECUTE`、`BATCH`。
- Trackable request comparison set: `QUERY`、`EXECUTE`、`BATCH`。
- Response target family: `ERROR`、`EVENT`、`SUPPORTED`、`AUTHENTICATE`、`AUTH_CHALLENGE`、`AUTH_SUCCESS`。
- Custom payload V4+ gate is enforced on both encode and decode.
- Request warning prelude is not read; response warning prelude is V4+ only.

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `native_protocol_extras_frame_prelude_contract` | response/request extra prelude order and asymmetry. |
| `native_protocol_extras_custom_payload_version_gate` | custom payload V4+ encode/decode rejection. |
| `native_protocol_extras_request_tracing_noop_matrix` | `OPTIONS`、`STARTUP`、`AUTH_RESPONSE` tracing flag no-op semantics. |
| `native_protocol_extras_request_warning_flag_negative` | request `WARNING` flag has no warning-list prelude parsing. |
| `native_protocol_extras_warning_tracking_gate` | `ClientWarn` attachment vs `CoordinatorWarnings` trackable gate. |
| `native_protocol_extras_options_startup_auth_payload_negative` | custom payload attached but not consumed by handshake/auth request execute paths. |
| `native_protocol_extras_error_event_response_matrix` | `ERROR` and `EVENT` inherit generic response extras. |
| `native_protocol_extras_auth_response_family_matrix` | `SUPPORTED` and auth response classes inherit generic response extras. |
| `native_protocol_extras_test_coverage_gap` | existing tests cover adjacent behavior but not this explicit negative matrix. |

## 设计目标

- Fail when source changes make handshake/auth request messages traceable, trackable, or payload-consuming without updating the matrix.
- Fail when generic extra prelude ordering or version gates drift.
- Keep the README/module/flow/source-map references synchronized with the new negative matrix.
- Preserve a visible test gap until explicit Java negative tests exist.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-native-protocol-extras-drift.py` | Parses source tokens and validates docs coverage. |
| `Message` | Frame extra encode/decode and request tracing defaults. |
| `Dispatcher` | Warning capture, coordinator warning gate and error warning attachment. |
| `OptionsMessage` | `OPTIONS` request target. |
| `StartupMessage` | `STARTUP` request target. |
| `AuthResponse` | `AUTH_RESPONSE` request target. |
| `ErrorMessage` / `EventMessage` | response negative matrix targets. |
| `SupportedMessage` / `AuthenticateMessage` / `AuthChallenge` / `AuthSuccess` | handshake/auth response matrix targets. |

## 核心接口

- `class_profile()`：verifies message class parent and method override profile.
- `source_checks()`：checks source token contracts and test-surface assumptions.
- `doc_checks()`：checks scenario IDs, source paths, test anchors and index links.
- `check()`：returns JSON-friendly result and pass/fail status.

## 生命周期

```text
developer changes transport source
  -> run python3 research/tools/check-native-protocol-extras-drift.py
  -> checker validates Message/Dispatcher/message-class/test-source baseline
  -> checker validates docs mention scenarios and anchors
  -> update source tests, matrix, checker baseline, or docs together
```

## 运维关注点

- This checker does not prove a driver accepts every odd flag combination; it protects the source-visible server semantics and documented test gap.
- If a request class starts consuming `getCustomPayload()`, update the negative matrix and add targeted Java tests.
- If a non-query request becomes traceable/trackable, update tracing, warning, metrics and compatibility docs together.

## 常见故障

- `request profile OPTIONS/STARTUP/AUTH_RESPONSE` fails: the class now overrides tracing/tracking or changed parent class.
- `Message response prelude order` fails: response body ABI changed.
- `Message custom payload version gates` fails: V4+ compatibility behavior changed.
- `doc scenario ...` fails: a source or docs update missed the research matrix.
- `test gap remains explicit` fails: tests changed and the matrix/checker needs to be updated to reflect new coverage.

## 测试用例

- `python3 research/tools/check-native-protocol-extras-drift.py`。
- `python3 research/tools/check-native-protocol-extras-drift.py --json`。
- Related Java anchors: `MessagePayloadTest.java`、`ProtocolNegotiationTest.java`、`RateLimitingTest.java`、`ClientResourceLimitsTest.java`、`ErrorMessageTest.java`、`AuthenticateMessageTest.java`、`AuthMessageSizeLimitTest.java`。
