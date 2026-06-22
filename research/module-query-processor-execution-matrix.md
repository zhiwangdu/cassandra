# Module: Query Processor Execution Matrix

## 范围

本矩阵补齐 CQL text/native message 到 `QueryProcessor` 执行边界的源码视角：`QUERY`/`PREPARE`/`EXECUTE`/`BATCH` native message, `QueryHandler` 接口, `QueryProcessor` parse/process/prepare/processPrepared/processBatch, internal query helpers, prepared cache persistence, schema invalidation, `QueryEvents`, `CQLMetrics`, NODE_LOCAL and existing test coverage. Parser grammar and prepared wire compatibility details仍见 `research/module-cql-parser-raw-prepare-matrix.md` and `research/module-prepared-statement-compatibility-matrix.md`。

当前源码基线：

- `QueryMessage.execute()` rejects page size 0, optionally starts tracing, calls `ClientState.getCQLQueryHandler()`, then `parse()` and `process()` before `QueryEvents.notifyQuerySuccess()`，见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:102`。
- `PrepareMessage` protocol v5 decodes an optional keyspace flag, clones `ClientState` with that keyspace, calls `QueryHandler.prepare()` and notifies prepare listeners，见 `src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:49`、`src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:118`。
- `ExecuteMessage.execute()` looks up the prepared statement, validates bind values/page size, wraps column specifications, calls `processPrepared()` and handles V5 result metadata id / metadata changed semantics，见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:131`。
- `BatchMessage.execute()` accepts raw strings or prepared ids, prepares per-statement variables, rejects non-mutation statements and calls `processBatch()`，见 `src/java/org/apache/cassandra/transport/messages/BatchMessage.java:173`。
- `QueryProcessor.processStatement()` is the common authorize/validate/execute boundary and special-cases `ConsistencyLevel.NODE_LOCAL` for local read/write execution，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:266`。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `query_processor_query_message_contract` | Native `QUERY` path: page-size guard, tracing, parse/process, success/failure events and skip-metadata handling. |
| `query_processor_prepare_message_keyspace_contract` | Native `PREPARE` v5 keyspace flag, warning, `ClientState.cloneWithKeyspaceIfSet()` and prepare success/failure events. |
| `query_processor_execute_prepared_contract` | Native `EXECUTE` prepared lookup, missing-prepared error, keyspace mismatch warning, bind value preparation and result metadata flags. |
| `query_processor_batch_message_contract` | Native `BATCH` raw/prepared mix, per-statement variable preparation, mutation-only validation and batch events. |
| `query_processor_authorize_validate_execute_contract` | Common `processStatement()` authorize, validate, execute and void-result normalization boundary. |
| `query_processor_node_local_contract` | `NODE_LOCAL` debug consistency gate, local write/select execution and read/write latency metrics. |
| `query_processor_internal_query_contract` | `prepareInternal()` / `executeInternal()` / `executeOnceInternal()` helper split between cached internal statements and one-shot local execution. |
| `query_processor_prepared_cache_persistence_contract` | Caffeine prepared cache sizing, eviction, `system.prepared_statements` write/remove/load/reset and startup preload page size. |
| `query_processor_schema_invalidation_contract` | SchemaChangeListener invalidates table/keyspace/function/aggregate dependent prepared statements in memory and persistent system table. |
| `query_processor_query_events_contract` | Query/prepare/execute/batch success/failure listener callbacks, password obfuscation and listener failure isolation. |
| `query_processor_cql_metrics_contract` | `CQLMetrics` counters/gauges for regular/prepared execution, evictions, USE statements and prepared ratio. |
| `query_processor_existing_tests_baseline` | Current unit/network tests for prepared invalidation, metadata flags, QueryEvents, NODE_LOCAL metrics, USE guard and function/index invalidation. |
| `query_processor_native_message_matrix_gap` | Existing tests cover many pieces but do not provide one focused native-message matrix that drives QUERY/PREPARE/EXECUTE/BATCH through `QueryHandler` with listener, metric and metadata assertions together. |

## 调用图

```text
native QUERY frame
  -> QueryMessage.execute(state, requestTime, trace)
     -> page-size guard
     -> ClientState.getCQLQueryHandler()
     -> QueryProcessor.parse(query, state, options)
        -> QueryProcessor.getStatement()
        -> CQLFragmentParser + raw.prepare()
     -> QueryProcessor.process(statement, state, options, payload, requestTime)
        -> options.prepare(bind variables)
        -> regularStatementsExecuted++
        -> processStatement()
           -> statement.authorize(clientState)
           -> statement.validate(clientState)
           -> statement.execute(...) or NODE_LOCAL local path
     -> QueryEvents.notifyQuerySuccess()/notifyQueryFailure()

native PREPARE frame
  -> PrepareMessage.decode(): query + optional v5 keyspace flag
  -> PrepareMessage.execute()
     -> clone ClientState with keyspace
     -> QueryProcessor.prepare(query, clientState)
        -> parseAndPrepare()
        -> compute id with/without keyspace
        -> storePreparedStatement()
        -> SystemKeyspace.writePreparedStatement()
     -> QueryEvents.notifyPrepareSuccess()/notifyPrepareFailure()

native EXECUTE frame
  -> ExecuteMessage.execute()
     -> QueryProcessor.getPrepared(statementId)
     -> options.prepare(bind variables)
     -> QueryOptions.addColumnSpecifications()
     -> QueryProcessor.processPrepared()
        -> preparedStatementsExecuted++
        -> processStatement()
     -> metadata id / skip metadata / metadata changed handling
     -> QueryEvents.notifyExecuteSuccess()/notifyExecuteFailure()

native BATCH frame
  -> BatchMessage.execute()
     -> each query entry: raw parseAndPrepare(..., measure=false) or getPrepared(id)
     -> BatchQueryOptions.withPerStatementVariables()
     -> require ModificationStatement
     -> QueryProcessor.processBatch()
        -> batch.authorize()
        -> batch.validate()
        -> batch.execute()
     -> QueryEvents.notifyBatchSuccess()/notifyBatchFailure()
```

## 设计目标

- Keep native message decoding separate from CQL parse/prepare/execute semantics through `QueryHandler`.
- Centralize statement authorization and validation in `processStatement()` so QUERY and EXECUTE share the same guard.
- Let prepared execution avoid parse/prepare cost while preserving bind metadata and schema invalidation.
- Give internal Cassandra code a local execution helper that bypasses client metrics where appropriate.
- Expose query lifecycle events to audit/FQL/listeners without letting listener failures break the request.

## 解决的问题

- Native protocol operations are not one path: unprepared QUERY, PREPARE, EXECUTE and BATCH have different validation and metadata behavior.
- Prepared statement ids depend on keyspace qualification and upgrade state; execution must warn when an unqualified statement is used under a different keyspace.
- Schema changes can invalidate prepared plans that already captured table/function/aggregate metadata.
- Internal system queries need stable typed binding without writing every call through a network-facing QueryOptions path.
- Operators need CQL metrics and events to understand prepared cache churn and query volume.

## 设计取舍

- `QueryProcessor.process()` increments regular statement metrics for non-internal states; direct `processStatement()` callers are responsible for metrics, as noted at `src/java/org/apache/cassandra/cql3/QueryProcessor.java:99`。
- Prepared cache eviction removes `system.prepared_statements`; this favors correctness and bounded cache size over silently reusing stale plans.
- Internal statements are stored in a separate `ConcurrentMap<String, Prepared>` with no expiration, trading memory for repeated system-query speed.
- `BatchMessage` builds a synthetic `BatchStatement` from already prepared mutation statements; it intentionally rejects SELECT and other non-mutation statements.
- `QueryEvents` catches listener exceptions and only logs/no-spams them, avoiding user request failure caused by observability hooks.

## 核心类

| 类/文件 | 作用 |
|---|---|
| `QueryHandler` | Pluggable parse/process/prepare/processPrepared/processBatch contract used by native messages. |
| `QueryProcessor` | Default `QueryHandler`; owns CQL parsing boundary, execution, prepared cache, internal helpers and schema invalidation listener. |
| `QueryMessage` | Native `QUERY` request execution path. |
| `PrepareMessage` | Native `PREPARE` request and v5 keyspace option path. |
| `ExecuteMessage` | Native `EXECUTE` request, prepared lookup and result metadata id handling. |
| `BatchMessage` | Native `BATCH` request, raw/prepared statement assembly and mutation-only guard. |
| `QueryEvents` | Listener registry for query/prepare/execute/batch success/failure events. |
| `CQLMetrics` | CQL execution/prepared cache counters and gauges. |
| `SystemKeyspace` | `system.prepared_statements` persistence and preload/read/write/delete helpers. |
| `research/tools/check-query-processor-execution-drift.py` | Source/test/doc/gap drift checker for this matrix. |

## 核心接口

- `QueryHandler.parse()` / `process()` / `prepare()` / `getPrepared()` / `processPrepared()` / `processBatch()`。
- `QueryProcessor.processStatement()`、`prepareInternal()`、`parseAndPrepare()`、`executeInternal()`、`executeOnceInternal()`、`processPrepared()`、`processBatch()`。
- `QueryEvents.Listener` callback set: `querySuccess`、`queryFailure`、`prepareSuccess`、`prepareFailure`、`executeSuccess`、`executeFailure`、`batchSuccess`、`batchFailure`。
- `SystemKeyspace.writePreparedStatement()`、`removePreparedStatement()`、`resetPreparedStatements()`、`loadPreparedStatements()`。
- `QueryOptions.prepare()` and `QueryOptions.addColumnSpecifications()` bind native values to prepared variable metadata.

## 配置项

| 配置项 | Source | 语义 |
|---|---|---|
| `prepared_statements_cache_size` / legacy `prepared_statements_cache_size_mb` | `src/java/org/apache/cassandra/config/Config.java:580`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:795` | Caffeine prepared statement cache weight and preload warning threshold. |
| `force_new_prepared_statement_behaviour` | `src/java/org/apache/cassandra/config/Config.java:119`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4974`、`src/java/org/apache/cassandra/cql3/QueryProcessor.java:692` | Forces the post-4.0.2 prepared id behavior instead of waiting for `Gossiper` min-version. |
| `use_statements_enabled` | `src/java/org/apache/cassandra/config/Config.java:611`、`src/java/org/apache/cassandra/cql3/statements/UseStatement.java:59` | Runtime guard for `USE`; metrics should not increment when prohibited. |
| `cassandra.enable_nodelocal_queries` | `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:219`、`src/java/org/apache/cassandra/cql3/QueryProcessor.java:283` | Enables dangerous `NODE_LOCAL` debug reads/writes. |

## Metrics

- `org.apache.cassandra.metrics.CQLMetrics` registers `RegularStatementsExecuted`, `PreparedStatementsExecuted`, `PreparedStatementsEvicted`, `UseStatementsExecuted`, `PreparedStatementsCount` and `PreparedStatementsRatio`，见 `src/java/org/apache/cassandra/metrics/CQLMetrics.java:25`。
- `process()` increments `regularStatementsExecuted` only for non-internal client states; `processPrepared()` increments `preparedStatementsExecuted` before entering `processStatement()`。
- NODE_LOCAL read/write paths update `ClientRequestsMetricsHolder.readMetricsForLevel(NODE_LOCAL)` or `writeMetricsForLevel(NODE_LOCAL)` plus global read/write metrics.

## 日志

- Prepared cache initialization logs the configured MiB and eviction warning logs once per minute when the cache discards prepared statements.
- `PrepareMessage` warns with `NoSpamLogger` when v5 keyspace is supplied via prepare options.
- `ExecuteMessage` logs a no-spam error when an unqualified prepared statement is executed under a different keyspace.
- `QueryEvents` logs listener callback failures but keeps the request path isolated.

## 运维关注点

- `PreparedQueryNotFoundException` after schema changes is expected; clients should re-prepare.
- Prepared cache churn can come from too small `prepared_statements_cache_size` or leaking clients; inspect CQL metrics and `system.prepared_statements`.
- A network `QUERY` with page size 0 fails at native message level before CQL parsing.
- `NODE_LOCAL` should stay disabled outside emergency debugging; it bypasses normal replica coordination and is guarded by a relevant property.
- QueryEvents listeners underpin audit/FQL style observability; listener exceptions should show in logs rather than client-visible query failures.

## 性能瓶颈

- Unprepared `QUERY` pays parse, prepare, bind and validate on every request.
- Prepared `EXECUTE` avoids parse/prepare but still validates bind count/type and executes normal authorization/validation.
- Internal cached queries avoid repeated parse/prepare but can grow `internalStatements` for many distinct system query strings.
- Batch execution prepares each raw batch entry and validates all statements before constructing the synthetic `BatchStatement`.

## 常见故障

- `The page size cannot be 0`: native QUERY or EXECUTE rejected invalid paging options.
- `PreparedQueryNotFoundException`: prepared id evicted, removed by schema invalidation, missing after restart, or unknown to the node.
- `Invalid statement in batch`: native BATCH contained SELECT or a non-mutation statement.
- `Invalid amount of bind variables` / marker mismatch: QueryOptions values do not match the prepared statement variables.
- `NODE_LOCAL consistency level is highly dangerous`: operator used NODE_LOCAL without enabling the relevant property.

## 测试用例

- `PreparedStatementsTest.testInvalidatePreparedStatementsOnDrop()` covers table/keyspace drop invalidation and driver reprepare, see `test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java:58`。
- `PreparedStatementsTest.testInvalidatePreparedStatementOnAlterV4/V5()` and `testMetadataFlagsWithLWTs()` cover prepared metadata and missing-prepared behavior after schema change, see `test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java:91`、`test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java:276`。
- `QueryEventsTest.queryTest()`、`prepareExecuteTest()` and `batchTest()` cover query/prepare/execute/batch listener success/failure baselines, see `test/unit/org/apache/cassandra/cql3/QueryEventsTest.java:55`。
- `NodeLocalConsistencyTest.testModify()`、`testBatch()` and `testSelect()` cover NODE_LOCAL read/write metric updates, see `test/unit/org/apache/cassandra/cql3/NodeLocalConsistencyTest.java:40`。
- `UseTest.shouldRejectUseStatementWhenProhibited()` covers `use_statements_enabled` with `UseStatementsExecuted` not incrementing, see `test/unit/org/apache/cassandra/cql3/validation/operations/UseTest.java:40`。
- Function, aggregate and index invalidation are covered by `UFTest.testFunctionDropPreparedStatement()`、`AggregationTest.testFunctionDropPreparedStatement()` and `SecondaryIndexTest.droppingIndexInvalidatesPreparedStatements()`。
