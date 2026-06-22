# Module: Prepared Statement Compatibility Drift Checker

## 范围

`research/tools/check-prepared-statement-compat-drift.py` 是 source-only drift check，用来保护 prepared statement protocol/cache/persistence compatibility matrix 的 research 覆盖。它解析 prepared path 的关键 source baseline，并验证 `module-prepared-statement-compatibility-matrix.md`、Schema/CQL/Auth/Native docs、native flow 和 source map 包含相同场景、源码路径、配置项、metrics 和测试锚点。

当前基线：

- Prepared upgrade behavior version: `4.0.2`。
- Preload page size: `5000`。
- `ResultSet.Flag` order: `GLOBAL_TABLES_SPEC`、`HAS_MORE_PAGES`、`NO_METADATA`、`METADATA_CHANGED`。
- `system.prepared_statements` columns: `prepared_id`、`logged_keyspace`、`query_string`。
- CQL prepared metrics: `PreparedStatementsExecuted`、`PreparedStatementsEvicted`、`PreparedStatementsCount`、`PreparedStatementsRatio`。
- Config keys: `prepared_statements_cache_size` and `force_new_prepared_statement_behaviour`。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `prepared_prepare_v5_keyspace_flag` | V5+ PREPARE keyspace flag and keyspace clone path。 |
| `prepared_execute_v5_result_metadata_id` | V5+ EXECUTE result metadata id and metadata changed/skip logic。 |
| `prepared_result_prepared_v5_result_metadata_id` | RESULT PREPARED V5+ result metadata id。 |
| `prepared_id_four_hash_matrix` | QueryProcessor four-hash statement id compatibility behavior。 |
| `prepared_new_behaviour_upgrade_gate` | 4.0.2 min version and config override gate。 |
| `prepared_cache_persistence_contract` | cache, system table, preload and eviction persistence path。 |
| `prepared_schema_invalidation_contract` | schema/function invalidation listener coverage。 |
| `prepared_metadata_flag_contract` | ResultSet metadata flags and version-specific serde。 |
| `prepared_metrics_and_logs_contract` | metrics/log warning surface for operations。 |
| `prepared_test_coverage_surface` | required Java test anchors。 |
| `prepared_external_driver_gap` | explicit remaining external driver matrix gap。 |

## 设计目标

- Keep prepared statement compatibility prose synchronized with source-visible ABI and operational behavior.
- Fail when V5 keyspace/result metadata id handling, statement id rules, metadata flags, persistence columns, config or metrics drift.
- Make the remaining external driver gap explicit rather than hidden behind unit-test coverage.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-prepared-statement-compat-drift.py` | Parses prepared source contracts and docs coverage。 |
| `PrepareMessage` | V5 prepare keyspace flag and prepare execution path。 |
| `ExecuteMessage` | V5 execute metadata id and result metadata flags。 |
| `QueryProcessor` | prepared cache, id matrix, upgrade gate, persistence, invalidation。 |
| `ResultMessage.Prepared` | wire prepared response。 |
| `ResultSet` | prepared/result metadata serde and flags。 |
| `SystemKeyspace` | `system.prepared_statements` table and preload helpers。 |
| `CQLMetrics` | prepared execution/cache metrics。 |

## 运维关注点

- A green checker does not prove every driver handles every protocol version; it proves the source matrix is documented.
- If a source change intentionally alters prepared statement id behavior, update this checker, the matrix and driver upgrade notes together.
- If `system.prepared_statements` columns change, startup/restart compatibility needs explicit upgrade testing.

## 常见故障

- `ResultSet.Flag order matches baseline` fails: metadata flag bit order changed and protocol docs/tests must be updated.
- `system.prepared_statements columns match baseline` fails: persistence ABI changed.
- `source token contract ... QueryProcessor.java` fails: statement id, preload, upgrade or invalidation semantics drifted.
- `doc token ...` fails: source/test/config/metric detail is missing from research docs.

## 测试用例

- `python3 research/tools/check-prepared-statement-compat-drift.py`。
- `python3 research/tools/check-prepared-statement-compat-drift.py --json`。
- Java coverage anchors: `PreparedStatementsTest.java`、`PstmtPersistenceTest.java`、`PreparedStatementTest.java`、`PrepareMessageTest.java`、`SerDeserTest.java`、`PrepareBatchStatementsTest.java`。
