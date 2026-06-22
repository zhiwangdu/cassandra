# Module: Tracing Native Cqlsh Drift Checker

## 范围

`research/tools/check-tracing-native-cqlsh-drift.py` 是 source-only drift check，用来保护 tracing native/cqlsh operations matrix 的 research 覆盖。它验证 native frame `TRACING` flag contract、request tracing wrapper、QUERY/PREPARE/EXECUTE/BATCH trace begin 参数、probabilistic sampling、`system_traces` async writes、internode propagation、cqlsh display path、测试锚点和 frame-level gap。

当前基线：

- `Envelope.Header.Flag.TRACING` bit order is stable and documented.
- Request `TRACING` flag is header-only; response `TRACING` flag has a UUID prelude.
- Explicit request tracing returns a trace id; probabilistic sampling does not.
- QUERY/PREPARE/EXECUTE/BATCH are traceable request classes.
- `TraceStateImpl` writes asynchronously through `Stage.TRACING` and `ConsistencyLevel.ANY`.
- cqlsh supports `TRACING ON/OFF` and `SHOW SESSION`, with recursion guard for `system_traces`.
- Existing tests cover driver-level trace parameters and tracing lifecycle, but not direct native frame encode/decode assertions.

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `tracing_native_flag_decode_encode` | Native header flag order, request decode/encode flag handling and response trace UUID prelude. |
| `tracing_request_wrapper_lifecycle` | Explicit/probabilistic session creation, `finally stopSession()`, and response trace id gating. |
| `tracing_query_prepare_execute_batch_begin` | CQL request classes and trace begin parameter maps. |
| `tracing_probabilistic_sampling_boundary` | StorageService probability gate and nodetool argument validation. |
| `tracing_system_traces_mutation_async` | TraceKeyspace schema/mutation builders and async ANY writes. |
| `tracing_internode_propagation` | TRACE_SESSION/TRACE_TYPE propagation and outbound message trace. |
| `tracing_cqlsh_toggle_show_session` | cqlsh toggle/show/fetch/format/partial-session behavior. |
| `tracing_config_ttl_wait_custom_class` | TTL/default RF/wait timeout/custom tracing class/max trace wait config surface. |
| `tracing_test_coverage_and_frame_gap` | Existing source tests plus explicit frame-level gap marker. |

## 设计目标

- Fail when native frame tracing semantics drift without updating the matrix.
- Fail when a CQL request class changes traceability, trace request names, or parameters.
- Keep `README.md`、`notes/source-map.md`、matrix and drift checker docs synchronized.
- Preserve a visible frame-level test gap until explicit transport tests exist.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-tracing-native-cqlsh-drift.py` | Validates source tokens, query message profiles, docs coverage and test gap baseline. |
| `Envelope.Header.Flag` | Native header flag order. |
| `Message.Request` / `Message.encode()` / `Message.Decoder.decodeMessage()` | Tracing lifecycle and frame prelude contract. |
| `QueryMessage` / `PrepareMessage` / `ExecuteMessage` / `BatchMessage` | CQL trace begin metadata. |
| `Tracing` / `TracingImpl` / `TraceStateImpl` / `TraceKeyspace` | Session lifecycle, propagation and writes. |
| `StorageService` / `SetTraceProbability` | Probability sampling operator interface. |
| `cqlshlib.cqlshmain` / `cqlshlib.tracing` | Shell toggle, fetch and formatting. |

## 核心接口

- `source_checks()`：checks exact source tokens in Java/Python implementation files.
- `query_message_profile_checks()`：parses message classes and validates traceable/trackable profile.
- `doc_checks()`：validates scenario IDs, source/test paths and index links across research docs.
- `test_gap_checks()`：keeps the native frame-level test gap explicit.
- `check()`：returns JSON-friendly results and an aggregate pass/fail status.

## 生命周期

```text
developer changes tracing/native/cqlsh source
  -> run python3 research/tools/check-tracing-native-cqlsh-drift.py
  -> checker validates native flag/wrapper/source/test baseline
  -> checker validates matrix, drift doc, README and source-map references
  -> update source tests, matrix, checker baseline, and indexes together
```

## 运维关注点

- This checker does not execute a Cassandra node or cqlsh; it protects source-visible contracts and documented gaps.
- If explicit native frame tests are added, update `tracing_test_coverage_and_frame_gap` and the negative test-gap check instead of suppressing the failure.
- If probabilistic sampling starts returning trace ids to clients, update native protocol compatibility and driver-facing docs together.
- If `system_traces` write consistency or async behavior changes, revisit performance and failure-mode sections.

## 常见故障

- `source token ...` fails: a source contract moved or behavior changed; update matrix and checker tokens after reviewing semantics.
- `query profile ...` fails: QUERY/PREPARE/EXECUTE/BATCH traceable/trackable behavior changed.
- `doc token ...` fails: README/source-map/matrix drifted from source coverage.
- `frame-level gap remains explicit` fails: tests now mention native frame tracing internals; add real coverage notes and adjust the checker.

## 测试用例

- `python3 research/tools/check-tracing-native-cqlsh-drift.py`。
- `python3 research/tools/check-tracing-native-cqlsh-drift.py --json`。
- Related test anchors: `test/unit/org/apache/cassandra/cql3/TraceCqlTest.java`、`test/unit/org/apache/cassandra/tracing/TracingTest.java`、`pylib/cqlshlib/test/test_cqlsh_completion.py`、`test/distributed/org/apache/cassandra/distributed/impl/Coordinator.java`、`test/distributed/org/apache/cassandra/distributed/impl/TracingUtil.java`。
