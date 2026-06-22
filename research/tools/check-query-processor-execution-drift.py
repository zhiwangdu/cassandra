#!/usr/bin/env python3
#
# Source-only drift check for QueryProcessor execution research coverage.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

QUERY_PROCESSOR = "src/java/org/apache/cassandra/cql3/QueryProcessor.java"
QUERY_HANDLER = "src/java/org/apache/cassandra/cql3/QueryHandler.java"
QUERY_EVENTS = "src/java/org/apache/cassandra/cql3/QueryEvents.java"
CQL_METRICS = "src/java/org/apache/cassandra/metrics/CQLMetrics.java"
QUERY_MESSAGE = "src/java/org/apache/cassandra/transport/messages/QueryMessage.java"
PREPARE_MESSAGE = "src/java/org/apache/cassandra/transport/messages/PrepareMessage.java"
EXECUTE_MESSAGE = "src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java"
BATCH_MESSAGE = "src/java/org/apache/cassandra/transport/messages/BatchMessage.java"
SYSTEM_KEYSPACE = "src/java/org/apache/cassandra/db/SystemKeyspace.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
CASSANDRA_RELEVANT_PROPERTIES = "src/java/org/apache/cassandra/config/CassandraRelevantProperties.java"
USE_STATEMENT = "src/java/org/apache/cassandra/cql3/statements/UseStatement.java"

PREPARED_STATEMENTS_TEST = "test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java"
QUERY_EVENTS_TEST = "test/unit/org/apache/cassandra/cql3/QueryEventsTest.java"
NODE_LOCAL_TEST = "test/unit/org/apache/cassandra/cql3/NodeLocalConsistencyTest.java"
USE_TEST = "test/unit/org/apache/cassandra/cql3/validation/operations/UseTest.java"
UF_TEST = "test/unit/org/apache/cassandra/cql3/validation/entities/UFTest.java"
AGGREGATION_TEST = "test/unit/org/apache/cassandra/cql3/validation/operations/AggregationTest.java"
SECONDARY_INDEX_TEST = "test/unit/org/apache/cassandra/cql3/validation/entities/SecondaryIndexTest.java"

MATRIX_DOC = "research/module-query-processor-execution-matrix.md"
CHECKER_DOC = "research/module-query-processor-execution-drift-checker.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

SCENARIO_IDS = (
    "query_processor_query_message_contract",
    "query_processor_prepare_message_keyspace_contract",
    "query_processor_execute_prepared_contract",
    "query_processor_batch_message_contract",
    "query_processor_authorize_validate_execute_contract",
    "query_processor_node_local_contract",
    "query_processor_internal_query_contract",
    "query_processor_prepared_cache_persistence_contract",
    "query_processor_schema_invalidation_contract",
    "query_processor_query_events_contract",
    "query_processor_cql_metrics_contract",
    "query_processor_existing_tests_baseline",
    "query_processor_native_message_matrix_gap",
)

EXPECTED_CQL_METRICS = (
    "RegularStatementsExecuted",
    "PreparedStatementsExecuted",
    "PreparedStatementsEvicted",
    "UseStatementsExecuted",
    "PreparedStatementsCount",
    "PreparedStatementsRatio",
)

SOURCE_TOKEN_CHECKS = {
    QUERY_MESSAGE: (
        "if (options.getPageSize() == 0)",
        'throw new ProtocolException("The page size cannot be 0")',
        "QueryHandler queryHandler = ClientState.getCQLQueryHandler();",
        "statement = queryHandler.parse(query, state, options);",
        "queryHandler.process(statement, state, options, getCustomPayload(), requestTime);",
        "QueryEvents.instance.notifyQuerySuccess(statement, query, options, state, queryStartTime, response);",
        "QueryEvents.instance.notifyQueryFailure(statement, query, options, state, e);",
        "((ResultMessage.Rows)response).result.metadata.setSkipMetadata();",
    ),
    PREPARE_MESSAGE: (
        "version.isGreaterOrEqualTo(ProtocolVersion.V5)",
        "int flags = (int)body.readUnsignedInt();",
        "(flags & 0x1) == 0x1",
        "Keyspace is set via query options. This is considered dangerous",
        "state.getClientState().cloneWithKeyspaceIfSet(keyspace)",
        "queryHandler.prepare(query, clientState, getCustomPayload())",
        "QueryEvents.instance.notifyPrepareSuccess",
        "QueryEvents.instance.notifyPrepareFailure",
    ),
    EXECUTE_MESSAGE: (
        "prepared = handler.getPrepared(statementId);",
        "throw new PreparedQueryNotFoundException(statementId);",
        "warnAboutUseWithPreparedStatements(statementId, prepared.keyspace)",
        "options.prepare(statement.getBindVariables());",
        'throw new ProtocolException("The page size cannot be 0")',
        "QueryOptions.addColumnSpecifications(options, prepared.statement.getBindVariables())",
        "handler.processPrepared(statement, state, queryOptions, getCustomPayload(), requestTime);",
        "QueryEvents.instance.notifyExecuteSuccess",
        "QueryEvents.instance.notifyExecuteFailure",
        "resultMetadata.setMetadataChanged();",
        "resultMetadata.setSkipMetadata();",
    ),
    BATCH_MESSAGE: (
        "p = QueryProcessor.parseAndPrepare((String) query,",
        "p = handler.getPrepared((MD5Digest)query);",
        "throw new PreparedQueryNotFoundException((MD5Digest)query);",
        "queryValues.size() != p.statement.getBindVariables().size()",
        "BatchQueryOptions.withPerStatementVariables(options, values, queryOrIdList)",
        "batchOptions.prepareStatement(i, statement.getBindVariables());",
        "if (!(statement instanceof ModificationStatement))",
        "Invalid statement in batch: only UPDATE, INSERT and DELETE statements are allowed.",
        "handler.processBatch(batch, state, batchOptions, getCustomPayload(), requestTime);",
        "QueryEvents.instance.notifyBatchSuccess",
        "QueryEvents.instance.notifyBatchFailure",
    ),
    QUERY_HANDLER: (
        "ResultMessage process(CQLStatement statement,",
        "ResultMessage.Prepared prepare(String query,",
        "QueryHandler.Prepared getPrepared(MD5Digest id);",
        "ResultMessage processPrepared(CQLStatement statement,",
        "ResultMessage processBatch(BatchStatement statement,",
        "public final MD5Digest resultMetadataId;",
        "public final String rawCQLStatement;",
        "public final boolean fullyQualified;",
    ),
    QUERY_PROCESSOR: (
        "public class QueryProcessor implements QueryHandler",
        "Caffeine.newBuilder()",
        "maximumWeight(PREPARED_STATEMENT_CACHE_SIZE_BYTES)",
        "removalListener((key, prepared, cause) -> evictPreparedStatement(key, cause))",
        "SystemKeyspace.removePreparedStatement(key);",
        "public ResultMessage processStatement(CQLStatement statement, QueryState queryState, QueryOptions options, Dispatcher.RequestTime requestTime)",
        "statement.authorize(clientState);",
        "statement.validate(clientState);",
        "options.getConsistency() == ConsistencyLevel.NODE_LOCAL",
        "ENABLE_NODELOCAL_QUERIES.getBoolean()",
        "statement.executeLocally(queryState, options)",
        "metrics.regularStatementsExecuted.inc();",
        "public static Prepared prepareInternal(String query)",
        "internalStatements.put(query, prepared);",
        "public static UntypedResultSet executeInternal(String query, Object... values)",
        "public static UntypedResultSet executeOnceInternal(String query, Object... values)",
        "public static Prepared parseAndPrepare(String query, ClientState clientState, boolean isInternal, boolean measure)",
        "SystemKeyspace.writePreparedStatement(keyspace, statementId, queryString, prepared.timestamp)",
        "metrics.preparedStatementsExecuted.inc();",
        "batch.authorize(clientState);",
        "batch.validate();",
        "return batch.execute(queryState, options, requestTime);",
        "private static class StatementInvalidatingListener implements SchemaChangeListener",
        "removeInvalidPreparedStatements(before.keyspace, before.name);",
        "removeInvalidPreparedStatements(keyspace.name, null);",
        "removeInvalidPreparedStatementsForFunction(before.name().keyspace, before.name().name);",
        "return CQLFragmentParser.parseAnyUnhandled(CqlParser::query, queryStr);",
    ),
    QUERY_EVENTS: (
        "private final Set<Listener> listeners = new CopyOnWriteArraySet<>();",
        "public void registerListener(Listener listener)",
        "public void unregisterListener(Listener listener)",
        "public void notifyQuerySuccess",
        "public void notifyQueryFailure",
        "public void notifyExecuteSuccess",
        "public void notifyExecuteFailure",
        "public void notifyBatchSuccess",
        "public void notifyBatchFailure",
        "public void notifyPrepareSuccess",
        "public void notifyPrepareFailure",
        "maybeObfuscatePassword",
        'noSpam1m.error("Failed notifying listeners", t);',
        "JVMStabilityInspector.inspectThrowable(t);",
    ),
    CQL_METRICS: tuple(f'createMetricName("{metric}")' for metric in EXPECTED_CQL_METRICS),
    SYSTEM_KEYSPACE: (
        "public static final String PREPARED_STATEMENTS = \"prepared_statements\";",
        "writePreparedStatement(String loggedKeyspace, MD5Digest key, String cql, long timestamp)",
        "INSERT INTO %s (logged_keyspace, prepared_id, query_string) VALUES (?, ?, ?) USING TIMESTAMP ?",
        "removePreparedStatement(MD5Digest key)",
        "resetPreparedStatements()",
        "loadPreparedStatements(TriFunction<MD5Digest, String, String, Prepared> onLoaded, int pageSize)",
        "SELECT prepared_id, logged_keyspace, query_string FROM %s.%s",
        "preparedBytesLoadThreshold = (long) (PREPARED_STATEMENT_CACHE_SIZE_BYTES * 1.1)",
        "Consider truncating {}.{} to clear out leaked prepared statements.",
    ),
    CONFIG: (
        "force_new_prepared_statement_behaviour",
        "prepared_statements_cache_size",
        "prepared_statements_cache_size_mb",
        "use_statements_enabled",
    ),
    DATABASE_DESCRIPTOR: (
        "getUseStatementsEnabled()",
        "setUseStatementsEnabled(boolean enabled)",
        "getForceNewPreparedStatementBehaviour()",
        "setForceNewPreparedStatementBehaviour(boolean value)",
        "preparedStatementsCacheSizeInMiB",
    ),
    CASSANDRA_RELEVANT_PROPERTIES: (
        'ENABLE_NODELOCAL_QUERIES("cassandra.enable_nodelocal_queries")',
    ),
    USE_STATEMENT: (
        "DatabaseDescriptor.getUseStatementsEnabled()",
        "USE statements prohibited",
        "QueryProcessor.metrics.useStatementsExecuted.inc();",
    ),
}

TEST_TOKEN_CHECKS = {
    PREPARED_STATEMENTS_TEST: (
        "public void testInvalidatePreparedStatementsOnDrop()",
        "public void testInvalidatePreparedStatementOnAlterV5()",
        "public void testInvalidatePreparedStatementOnAlterV4()",
        "public void testStatementRePreparationOnReconnect()",
        "public void prepareAndExecuteWithCustomExpressions()",
        "public void testMetadataFlagsWithLWTs()",
        "PreparedQueryNotFoundException",
        "METADATA_CHANGED",
    ),
    QUERY_EVENTS_TEST: (
        "public class QueryEventsTest extends CQLTester",
        "public void queryTest()",
        "listener.verify(\"querySuccess\", 1)",
        "listener.verify(newArrayList(\"querySuccess\", \"queryFailure\"), newArrayList(2, 1))",
        "public void prepareExecuteTest()",
        "listener.verify(newArrayList(\"prepareSuccess\", \"executeSuccess\"), newArrayList(1, 1))",
        "listener.verify(newArrayList(\"prepareSuccess\", \"prepareFailure\", \"executeSuccess\", \"executeFailure\"), newArrayList(2, 1, 2, 1))",
        "public void batchTest()",
        "listener.verify(newArrayList(\"prepareSuccess\", \"batchSuccess\"), newArrayList(1, 1))",
        "listener.verify(newArrayList(\"prepareSuccess\", \"batchSuccess\", \"batchFailure\"), newArrayList(1, 1, 1))",
    ),
    NODE_LOCAL_TEST: (
        "ENABLE_NODELOCAL_QUERIES.setBoolean(true)",
        "public void testModify()",
        "public void testBatch()",
        "public void testSelect()",
        "writeMetricsForLevel(NODE_LOCAL).latency.getCount()",
        "readMetricsForLevel(NODE_LOCAL).latency.getCount()",
    ),
    USE_TEST: (
        "public void shouldRejectUseStatementWhenProhibited()",
        "QueryProcessor.metrics.useStatementsExecuted.getCount()",
        "DatabaseDescriptor.setUseStatementsEnabled(false)",
        "USE statements prohibited",
    ),
    UF_TEST: (
        "public void testFunctionDropPreparedStatement()",
        "QueryProcessor.instance.prepare",
        "DROP FUNCTION",
        "Assert.assertNull(QueryProcessor.instance.getPrepared(preparedSelect1.statementId))",
    ),
    AGGREGATION_TEST: (
        "public void testFunctionDropPreparedStatement()",
        "DROP AGGREGATE",
        "assertNull(QueryProcessor.instance.getPrepared(prepared.statementId))",
    ),
    SECONDARY_INDEX_TEST: (
        "public void droppingIndexInvalidatesPreparedStatements()",
        "dropIndex(\"DROP INDEX %s.\" + indexName)",
        "assertNull(QueryProcessor.instance.getPrepared(cqlId))",
    ),
}

DOC_TOKENS = (
    MATRIX_DOC,
    CHECKER_DOC,
    "research/tools/check-query-processor-execution-drift.py",
    QUERY_PROCESSOR,
    QUERY_HANDLER,
    QUERY_EVENTS,
    CQL_METRICS,
    QUERY_MESSAGE,
    PREPARE_MESSAGE,
    EXECUTE_MESSAGE,
    BATCH_MESSAGE,
    SYSTEM_KEYSPACE,
    CONFIG,
    DATABASE_DESCRIPTOR,
    CASSANDRA_RELEVANT_PROPERTIES,
    PREPARED_STATEMENTS_TEST,
    QUERY_EVENTS_TEST,
    NODE_LOCAL_TEST,
    USE_TEST,
    "prepared_statements_cache_size",
    "force_new_prepared_statement_behaviour",
    "use_statements_enabled",
    "cassandra.enable_nodelocal_queries",
    "RegularStatementsExecuted",
    "PreparedStatementsExecuted",
    "PreparedStatementsEvicted",
    "UseStatementsExecuted",
    "PreparedStatementsCount",
    "PreparedStatementsRatio",
) + SCENARIO_IDS + EXPECTED_CQL_METRICS


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    ok: bool
    detail: str = ""


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def source_checks() -> list[Check]:
    checks: list[Check] = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.extend(Check(f"source token {token}", path, token in text) for token in tokens)

    metrics_text = read(CQL_METRICS)
    observed_metrics = tuple(metric for metric in EXPECTED_CQL_METRICS if f'createMetricName("{metric}")' in metrics_text)
    checks.append(Check("CQL metric set", CQL_METRICS, observed_metrics == EXPECTED_CQL_METRICS, ",".join(observed_metrics)))
    return checks


def test_checks() -> list[Check]:
    checks: list[Check] = []
    for path, tokens in TEST_TOKEN_CHECKS.items():
        text = read(path)
        checks.extend(Check(f"test token {token}", path, token in text) for token in tokens)
    return checks


def doc_checks() -> list[Check]:
    matrix = read(MATRIX_DOC)
    checker = read(CHECKER_DOC)
    readme = read(README_DOC)
    source_map = read(SOURCE_MAP_DOC)
    matrix_and_checker = matrix + "\n" + checker
    all_docs = "\n".join((matrix, checker, readme, source_map))

    checks = [Check(f"scenario documented {scenario}", f"{MATRIX_DOC} / {CHECKER_DOC}", documented(scenario, matrix_and_checker)) for scenario in SCENARIO_IDS]
    checks.extend(Check(f"doc token {token}", "research docs", token in all_docs) for token in DOC_TOKENS)
    checks.extend(
        [
            Check("README references matrix", README_DOC, MATRIX_DOC.split("/", 1)[1] in readme),
            Check("README references checker doc", README_DOC, CHECKER_DOC.split("/", 1)[1] in readme),
            Check("README references checker script", README_DOC, "check-query-processor-execution-drift.py" in readme),
            Check("source-map references matrix", SOURCE_MAP_DOC, MATRIX_DOC in source_map),
            Check("source-map references checker", SOURCE_MAP_DOC, "research/tools/check-query-processor-execution-drift.py" in source_map),
        ]
    )
    return checks


def gap_checks() -> list[Check]:
    test_files = [path for path in (REPO_ROOT / "test").rglob("*.java")]
    matrix_tokens = ("QueryMessage", "PrepareMessage", "ExecuteMessage", "BatchMessage", "QueryEvents", "CQLMetrics")
    focused_tests = []
    for path in test_files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if all(token in text for token in matrix_tokens):
            focused_tests.append(str(path.relative_to(REPO_ROOT)))

    return [
        Check(
            "native message matrix gap remains explicit",
            "test/**/*.java",
            not focused_tests,
            ",".join(focused_tests),
        )
    ]


def check() -> tuple[dict[str, object], bool]:
    checks = source_checks() + test_checks() + doc_checks() + gap_checks()
    failed = [c for c in checks if not c.ok]
    result = {
        "scenarios": list(SCENARIO_IDS),
        "metrics": list(EXPECTED_CQL_METRICS),
        "checks": [c.__dict__ for c in checks],
        "failed": [c.__dict__ for c in failed],
    }
    return result, not failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Check QueryProcessor execution research drift")
    parser.add_argument("--json", action="store_true", help="emit JSON result")
    args = parser.parse_args()

    result, ok = check()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif ok:
        print(f"OK query processor execution checks passed ({len(SCENARIO_IDS)} scenarios)")
    else:
        print("FAIL query processor execution checks failed", file=sys.stderr)
        for failure in result["failed"]:
            detail = f" ({failure['detail']})" if failure.get("detail") else ""
            print(f"- {failure['name']}: {failure['source']}{detail}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
