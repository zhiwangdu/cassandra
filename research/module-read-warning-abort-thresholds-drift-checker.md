# Module: Read Warning Abort Thresholds Drift Checker

## 范围

`research/tools/check-read-warning-abort-thresholds-drift.py` is a source-only drift checker for `research/module-read-warning-abort-thresholds-matrix.md`. It validates read warning/abort threshold configuration, replica tombstone/local-size wrappers, coordinator result-size checks, warning param aggregation, abort exception mapping, metrics, JMX runtime setters, existing threshold tests and documentation index coverage.

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `read_warning_config_contract` | Config fields, YAML comments/defaults, DatabaseDescriptor validation and runtime getters/setters. |
| `read_warning_query_options_snapshot_contract` | Request-scoped `QueryOptions.ReadThresholds` enablement and coordinator threshold snapshot. |
| `read_warning_replica_tombstone_warn_contract` | Replica tombstone warning, histograms, table counter, ClientWarn/logger/message params. |
| `read_abort_replica_tombstone_contract` | Replica tombstone abort, `TOMBSTONE_FAIL`, `TombstoneOverwhelmingException` and coordinator tombstone abort mapping. |
| `read_warning_replica_local_size_contract` | Local read-size heap accounting, warning param and histogram update. |
| `read_abort_replica_local_size_contract` | Local read-size abort param, `LocalReadSizeTooLargeException` and `READ_SIZE` mapping. |
| `read_warning_message_param_contract` | `ParamType` and `WarningContext` support for tombstone/local read-size warning/abort params. |
| `read_abort_snapshot_callback_contract` | `ReadCallback` snapshot capture and `WarningsSnapshot.maybeAbort()` behavior. |
| `read_warning_coordinator_result_size_contract` | Coordinator `SelectStatement` warning/abort, metrics and `StorageProxy.recordReadRegularAbort()`. |
| `read_warning_metrics_contract` | Table/keyspace/client request metrics for tombstone and read-size warnings/aborts. |
| `read_warning_jmx_runtime_contract` | StorageService runtime threshold mutation surface. |
| `read_warning_threshold_tests_baseline` | Distributed threshold tests and unit config/YAML tests. |
| `read_warning_speculative_race_regression` | Tombstone failure speculative execution race regression. |

## 设计目标

- Fail when read warning/abort thresholds move without updating research docs.
- Keep tombstone, local read-size and coordinator read-size contracts separated.
- Preserve the distinction between replica-local reject exceptions, coordinator-facing read abort exceptions and client metrics.
- Keep README/source-map and research checker inventory synchronized when this checker exists.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-read-warning-abort-thresholds-drift.py` | Validates source/test/doc tokens for this matrix. |
| `ReadCommand` | Replica tombstone and local read-size warning/abort wrappers. |
| `SelectStatement` / `QueryOptions` | Coordinator result-size threshold checks and request-scoped threshold snapshot. |
| `WarningContext` / `WarningsSnapshot` / `CoordinatorWarnings` | Internode warning param aggregation and client-visible warnings/aborts. |
| `ReadCallback` | Wait path that converts warning snapshots to typed abort exceptions before generic failures. |

## 核心接口

- `source_checks()` validates Java source and YAML contracts.
- `test_checks()` validates current unit/distributed test anchors.
- `doc_checks()` validates matrix, checker doc, README and source-map coverage.
- `check()` returns JSON-friendly results and pass/fail status.

## 生命周期

```text
change read warning/abort threshold behavior
  -> run python3 research/tools/check-read-warning-abort-thresholds-drift.py
  -> update matrix, checker doc, README, source-map and research CI inventory together
  -> if tests are renamed or new row-index/coordinator behavior changes semantics, update scenario IDs and source tokens in the same patch
```

## 运维关注点

- This checker does not run Java tests or start Cassandra; it verifies that source, tests and docs still contain the expected contracts.
- Failures in `ReadCommand`, `SelectStatement`, `WarningContext` or `WarningsSnapshot` usually mean the warning/abort propagation model changed and the matrix needs a semantic review.
- Failures in config/JMX tokens usually mean operator-facing knobs changed and runbooks should be updated with the new names or behavior.

## 常见故障

- `source token ...` fails: the source contract changed or moved.
- `test token ...` fails: a baseline test was renamed, deleted or materially rewritten.
- `doc token ...` fails: matrix/checker/README/source-map indexing missed a scenario.
- `checker count` fails in the CI gate checker: update `EXPECTED_CHECKER_COUNT`, anchor checker list and docs inventory together.

## 测试用例

- `python3 research/tools/check-read-warning-abort-thresholds-drift.py`
- `python3 research/tools/check-read-warning-abort-thresholds-drift.py --json`
- Related focused tests: `CoordinatorReadSizeWarningTest`、`LocalReadSizeWarningTest`、`TombstoneCountWarningTest`、`ReadFailureTest`、`DatabaseDescriptorTest`、`YamlConfigurationLoaderTest`。
