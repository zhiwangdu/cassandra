# Module: Row Index Read Size Thresholds Drift Checker

## 范围

`research/tools/check-row-index-read-size-thresholds-drift.py` is a source-only drift checker for `research/module-row-index-read-size-thresholds-matrix.md`. It validates BigTable `RowIndexEntry` threshold behavior, BigTable/BTI boundary, row-index warning params, coordinator aggregation, config/JMX surfaces, metrics, current dtest coverage and README/source-map inventory coverage.

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `row_index_read_size_threadlocal_contract` | `ReadCommand` thread-local command exposure to SSTable index deserialization. |
| `row_index_read_size_big_lookup_contract` | BigTable Bloom/key-cache/index-summary/primary-index lookup to serializer path. |
| `row_index_read_size_entry_shape_contract` | Plain/on-heap/shallow `RowIndexEntry` choice and `column_index_cache_size` boundary. |
| `row_index_read_size_threshold_gate` | Read threshold enablement, non-system keyspace and non-null warn/fail gating. |
| `row_index_read_size_memory_estimate_contract` | Estimated materialized index memory formula and strict greater-than threshold semantics. |
| `row_index_read_size_warn_contract` | Add-if-larger `ROW_INDEX_READ_SIZE_WARN` warning behavior. |
| `row_index_read_size_abort_contract` | `ROW_INDEX_READ_SIZE_FAIL`, local reject exception and coordinator read-size abort mapping. |
| `row_index_read_size_warning_aggregation_contract` | `WarningContext` / `WarningsSnapshot` / `CoordinatorWarnings` row-index aggregation. |
| `row_index_read_size_metrics_contract` | `Index.RowIndexEntry.*` and table/keyspace `RowIndexSize*` metrics. |
| `row_index_read_size_config_jmx_contract` | Config/YAML/DatabaseDescriptor/StorageService runtime threshold surface. |
| `row_index_read_size_bti_boundary` | BTI `TrieIndexEntry` and `BtiTableReader` boundary. |
| `row_index_read_size_tests_baseline` | RowIndexSize dtest plus shared abstract client-size and config/YAML tests. |
| `row_index_read_size_scan_test_boundary` | Current dtest scan variants remain explicitly skipped. |

## 设计目标

- Fail when BigTable row-index threshold semantics move without research updates.
- Keep row-index size distinct from local read-size and coordinator result-size.
- Preserve the BigTable-only nature of this threshold path and the BTI boundary.
- Keep checker inventory, README and source-map synchronized.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-row-index-read-size-thresholds-drift.py` | Validates source/test/doc tokens for this matrix. |
| `ReadCommand` | Current read command thread-local boundary. |
| `BigTableReader` | Primary-index lookup and `RowIndexEntry` deserialization trigger. |
| `RowIndexEntry` | Entry shape, threshold estimate and local warn/fail params. |
| `TrieIndexEntry` / `BtiTableReader` | BTI boundary. |
| `WarningContext` / `WarningsSnapshot` / `CoordinatorWarnings` | Coordinator row-index warning/abort aggregation. |

## 核心接口

- `source_checks()` validates Java source and YAML contracts.
- `test_checks()` validates current distributed and unit test anchors.
- `doc_checks()` validates matrix, checker doc, README and source-map coverage.
- `check()` returns JSON-friendly results and pass/fail status.

## 生命周期

```text
change BigTable RowIndexEntry, read threshold params or RowIndexSize metrics
  -> run python3 research/tools/check-row-index-read-size-thresholds-drift.py
  -> update source anchors, matrix, checker doc and README/source-map together
  -> if RowIndexSize scan or BTI runtime tests are added, replace the documented boundary with positive coverage
```

## 运维关注点

- This checker does not run Java tests or start Cassandra; it proves source/test/doc anchors remain aligned.
- The checker intentionally treats scan coverage as an explicit current boundary because `RowIndexSizeWarningTest` skips scan variants.
- Config names and client warning names differ for row-index thresholds; keep both forms documented.

## 常见故障

- `source token ...` fails: BigTable row-index threshold or aggregation behavior changed.
- `test token ...` fails: current dtest/config baseline was renamed or rewritten.
- `doc token ...` fails: matrix/checker/README/source-map indexing missed a scenario.
- `checker count` fails in the CI gate checker: update `EXPECTED_CHECKER_COUNT`, anchor checker list and docs inventory together.

## 测试用例

- `python3 research/tools/check-row-index-read-size-thresholds-drift.py`
- `python3 research/tools/check-row-index-read-size-thresholds-drift.py --json`
- Related focused tests: `RowIndexSizeWarningTest`、`AbstractClientSizeWarning`、`DatabaseDescriptorTest`、`YamlConfigurationLoaderTest`。
