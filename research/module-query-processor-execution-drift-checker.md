# Module: Query Processor Execution Drift Checker

## 范围

`research/tools/check-query-processor-execution-drift.py` is a source-only drift checker for `research/module-query-processor-execution-matrix.md`. It validates native message entrypoints, `QueryProcessor` execution/prepared/internal paths, prepared cache persistence, schema invalidation, QueryEvents, CQL metrics, existing tests and the explicit native message matrix gap.

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `query_processor_query_message_contract` | `QueryMessage` page-size guard, parse/process path, query events and skip metadata. |
| `query_processor_prepare_message_keyspace_contract` | `PrepareMessage` v5 keyspace flag, warning, cloned client state and prepare events. |
| `query_processor_execute_prepared_contract` | `ExecuteMessage` prepared lookup, missing id, keyspace mismatch warning, bind specs and metadata flags. |
| `query_processor_batch_message_contract` | `BatchMessage` raw/prepared mix, bind-count validation, mutation-only guard and batch events. |
| `query_processor_authorize_validate_execute_contract` | `QueryProcessor.processStatement()` authorize/validate/execute boundary. |
| `query_processor_node_local_contract` | NODE_LOCAL relevant property gate and local read/write metrics. |
| `query_processor_internal_query_contract` | Internal cached and one-shot query helpers. |
| `query_processor_prepared_cache_persistence_contract` | Caffeine prepared cache, eviction and `system.prepared_statements` persistence/preload. |
| `query_processor_schema_invalidation_contract` | Table/keyspace/function/aggregate prepared invalidation. |
| `query_processor_query_events_contract` | QueryEvents listener lifecycle and callbacks. |
| `query_processor_cql_metrics_contract` | CQL metrics counters/gauges. |
| `query_processor_existing_tests_baseline` | PreparedStatements, QueryEvents, NodeLocal, USE, function/index invalidation test anchors. |
| `query_processor_native_message_matrix_gap` | Explicit absence of one focused native message matrix test covering QUERY/PREPARE/EXECUTE/BATCH together. |

## 设计目标

- Fail when QueryProcessor/native message execution boundaries move without research updates.
- Keep tests, matrix, README, source-map and checker inventory synchronized.
- Preserve the distinction between source-proven contracts and missing focused runtime coverage.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-query-processor-execution-drift.py` | Validates source/test/doc/gap tokens. |
| `QueryMessage` / `PrepareMessage` / `ExecuteMessage` / `BatchMessage` | Native protocol request entrypoints. |
| `QueryProcessor` / `QueryHandler` | CQL execution contract and implementation. |
| `QueryEvents` / `CQLMetrics` | Observability hooks for CQL execution. |
| `SystemKeyspace` | Prepared statement persistence. |

## 核心接口

- `source_checks()` validates Java source contracts and expected CQL metrics.
- `test_checks()` validates existing focused unit/network tests.
- `doc_checks()` validates matrix, checker doc, README and source-map coverage.
- `gap_checks()` keeps `query_processor_native_message_matrix_gap` explicit until a focused test appears.
- `check()` returns JSON-friendly results and pass/fail status.

## 生命周期

```text
change QueryProcessor/native message/prepared cache behavior
  -> run python3 research/tools/check-query-processor-execution-drift.py
  -> update source anchors, matrix, checker doc and README/source-map together
  -> if a focused native message matrix test is added, replace the gap check with a positive test contract
```

## 运维关注点

- This checker does not start Cassandra or run Java tests; it proves source/test/doc anchors remain aligned.
- Existing tests cover many request paths through the driver or SimpleClient, but not one single native-message matrix with listener, metrics and metadata assertions.
- If `system.prepared_statements` schema or CQL metric names change, update this checker and prepared compatibility docs together.

## 常见故障

- `source token ...` fails: a Java execution path changed or moved.
- `test token ...` fails: a baseline test was renamed or removed.
- `doc token ...` fails: matrix/checker/README/source-map indexing missed a scenario.
- `native message matrix gap remains explicit` fails: a focused test likely appeared; update the documented coverage state instead of keeping the gap.

## 测试用例

- `python3 research/tools/check-query-processor-execution-drift.py`
- `python3 research/tools/check-query-processor-execution-drift.py --json`
- Related focused tests: `PreparedStatementsTest`、`QueryEventsTest`、`NodeLocalConsistencyTest`、`UseTest`、`UFTest`、`AggregationTest`、`SecondaryIndexTest`。
