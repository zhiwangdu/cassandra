#!/usr/bin/env python3
#
# Source-only drift check for read operation monitoring research coverage.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

MONITORABLE = "src/java/org/apache/cassandra/db/monitoring/Monitorable.java"
MONITORABLE_IMPL = "src/java/org/apache/cassandra/db/monitoring/MonitorableImpl.java"
MONITORING_STATE = "src/java/org/apache/cassandra/db/monitoring/MonitoringState.java"
MONITORING_TASK = "src/java/org/apache/cassandra/db/monitoring/MonitoringTask.java"
ABSTRACT_READ_QUERY = "src/java/org/apache/cassandra/db/AbstractReadQuery.java"
READ_COMMAND = "src/java/org/apache/cassandra/db/ReadCommand.java"
READ_COMMAND_VERB_HANDLER = "src/java/org/apache/cassandra/db/ReadCommandVerbHandler.java"
STORAGE_PROXY = "src/java/org/apache/cassandra/service/StorageProxy.java"
QUERY_CANCELLED_EXCEPTION = "src/java/org/apache/cassandra/exceptions/QueryCancelledException.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
CASSANDRA_YAML = "conf/cassandra.yaml"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
CASSANDRA_RELEVANT_PROPERTIES = "src/java/org/apache/cassandra/config/CassandraRelevantProperties.java"
STORAGE_SERVICE = "src/java/org/apache/cassandra/service/StorageService.java"
NODE_PROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
SAI_QUERY_CONTEXT = "src/java/org/apache/cassandra/index/sai/QueryContext.java"
SAI_SEARCHER = "src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexSearcher.java"
SAI_INDEX_RESULT_ITERATOR = "src/java/org/apache/cassandra/index/sai/disk/IndexSearchResultIterator.java"

MONITORING_TASK_TEST = "test/unit/org/apache/cassandra/db/monitoring/MonitoringTaskTest.java"
READ_COMMAND_TEST = "test/unit/org/apache/cassandra/db/ReadCommandTest.java"
PARSE_UNITS_TEST = "test/unit/org/apache/cassandra/config/ParseAndConvertUnitsTest.java"
OLD_YAML_TEST = "test/unit/org/apache/cassandra/config/LoadOldYAMLBackwardCompatibilityTest.java"
DATABASE_DESCRIPTOR_TEST = "test/unit/org/apache/cassandra/config/DatabaseDescriptorTest.java"

MATRIX_DOC = "research/module-read-operation-monitoring-matrix.md"
CHECKER_DOC = "research/module-read-operation-monitoring-drift-checker.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"
COORDINATOR_MATRIX_DOC = "research/module-storageproxy-coordinator-timeout-matrix.md"
COORDINATOR_CHECKER = "research/tools/check-storageproxy-coordinator-drift.py"

SCENARIO_IDS = (
    "read_monitoring_interface_contract",
    "read_monitoring_state_machine_contract",
    "read_monitoring_set_time_contract",
    "read_monitoring_timeout_abort_contract",
    "read_monitoring_slow_complete_contract",
    "read_monitoring_queue_capacity_contract",
    "read_monitoring_log_aggregation_contract",
    "read_monitoring_remote_verb_contract",
    "read_monitoring_local_read_contract",
    "read_monitoring_query_cancellation_contract",
    "read_monitoring_config_contract",
    "read_monitoring_jmx_nodetool_timeout_contract",
    "read_monitoring_sai_query_context_boundary",
    "read_monitoring_tests_baseline",
    "read_monitoring_coordinator_timeout_boundary",
)

SOURCE_TOKEN_CHECKS = {
    MONITORABLE: (
        "public interface Monitorable",
        "String name();",
        "long creationTimeNanos();",
        "long timeoutNanos();",
        "long slowTimeoutNanos();",
        "boolean isInProgress();",
        "boolean isAborted();",
        "boolean isCompleted();",
        "boolean isSlow();",
        "boolean isCrossNode();",
        "boolean abort();",
        "boolean complete();",
    ),
    MONITORING_STATE: (
        "IN_PROGRESS",
        "ABORTED",
        "COMPLETED",
    ),
    MONITORABLE_IMPL: (
        "public abstract class MonitorableImpl implements Monitorable",
        "private MonitoringState state;",
        "private boolean isSlow;",
        "private long approxCreationTimeNanos = -1;",
        "private long timeoutNanos;",
        "private long slowTimeoutNanos;",
        "private boolean isCrossNode;",
        "this.state = MonitoringState.IN_PROGRESS;",
        "public void setMonitoringTime(long approxCreationTimeNanos, boolean isCrossNode, long timeoutNanos, long slowTimeoutNanos)",
        "this.approxCreationTimeNanos = approxCreationTimeNanos;",
        "this.isCrossNode = isCrossNode;",
        "this.timeoutNanos = timeoutNanos;",
        "this.slowTimeoutNanos = slowTimeoutNanos;",
        "public boolean isInProgress()",
        "public boolean isAborted()",
        "public boolean isCompleted()",
        "public boolean isSlow()",
        "check();",
        "public boolean abort()",
        "if (state == MonitoringState.IN_PROGRESS)",
        "MonitoringTask.addFailedOperation(this, approxTime.now());",
        "state = MonitoringState.ABORTED;",
        "return state == MonitoringState.ABORTED;",
        "public boolean complete()",
        "if (isSlow && slowTimeoutNanos > 0 && approxCreationTimeNanos >= 0)",
        "MonitoringTask.addSlowOperation(this, approxTime.now());",
        "state = MonitoringState.COMPLETED;",
        "return state == MonitoringState.COMPLETED;",
        "long minElapsedNanos = (approxTime.now() - approxCreationTimeNanos) - approxTime.error();",
        "if (minElapsedNanos >= slowTimeoutNanos && !isSlow)",
        "isSlow = true;",
        "if (minElapsedNanos >= timeoutNanos)",
        "abort();",
    ),
    MONITORING_TASK: (
        "A task for monitoring in progress operations, currently only read queries",
        "MONITORING_REPORT_INTERVAL_MS",
        "MONITORING_MAX_OPERATIONS",
        "static MonitoringTask instance = make(REPORT_INTERVAL_MS, MAX_OPERATIONS);",
        "static MonitoringTask make(int reportIntervalMillis, int maxTimedoutOperations)",
        "ScheduledExecutors.scheduledTasks.scheduleWithFixedDelay(() -> logOperations(approxTime.now())",
        "static void addFailedOperation(Monitorable operation, long nowNanos)",
        "static void addSlowOperation(Monitorable operation, long nowNanos)",
        "List<String> getFailedOperations()",
        "List<String> getSlowOperations()",
        "private void logOperations(long approxCurrentTimeNanos)",
        "logSlowOperations(approxCurrentTimeNanos);",
        "logFailedOperations(approxCurrentTimeNanos);",
        "noSpamLogger.warn(\"Some operations timed out, details available at debug level (debug.log)\");",
        "logger.debug(\"{} operations timed out in the last {} msecs:{}{}\"",
        "noSpamLogger.info(\"Some operations were slow, details available at debug level (debug.log)\");",
        "logger.debug(\"{} operations were slow in the last {} msecs:{}{}\"",
        "private static final class OperationsQueue",
        "if (maxOperations == 0)",
        "return; // logging of operations is disabled",
        "this.queue = maxOperations > 0 ? newBlockingQueue(maxOperations) : newBlockingQueue();",
        "numDroppedOperations.incrementAndGet();",
        "private AggregatedOperations popOperations()",
        "operations.put(operation.name(), operation);",
        "return new AggregatedOperations(operations, numDroppedOperations.getAndSet(0L));",
        "append(\" were dropped)\");",
        "private String name;",
        "name = operation.name();",
        "numTimesReported++;",
        "totalTimeNanos += operation.totalTimeNanos;",
        "NANOSECONDS.toMillis(totalTimeNanos / numTimesReported)",
        "operation.isCrossNode() ? \"msec/cross-node\" : \"msec\"",
        "return String.format(\"<%s>, total time %d msec, timeout %d %s\"",
        "return String.format(\"<%s> timed out %d times, avg/min/max %d/%d/%d msec, timeout %d %s\"",
        "return String.format(\"<%s>, time %d msec - slow timeout %d %s\"",
        "return String.format(\"<%s>, was slow %d times: avg/min/max %d/%d/%d msec - slow timeout %d %s\"",
    ),
    ABSTRACT_READ_QUERY: (
        "abstract class AbstractReadQuery extends MonitorableImpl implements ReadQuery",
    ),
    READ_COMMAND: (
        "private class QueryCancellationChecker extends StoppingTransformation<UnfilteredRowIterator>",
        "long lastCheckedAt = 0;",
        "protected UnfilteredRowIterator applyToPartition(UnfilteredRowIterator partition)",
        "protected Row applyToRow(Row row)",
        "private void maybeCancel()",
        "Since MonitorableImpl relies on approxTime",
        "if (lastCheckedAt == approxTime.now())",
        "if (isAborted())",
        "stop();",
        "throw new QueryCancelledException(ReadCommand.this);",
        "private UnfilteredPartitionIterator withQueryCancellation(UnfilteredPartitionIterator iter)",
        "return Transformation.apply(iter, new QueryCancellationChecker());",
        "private UnfilteredPartitionIterator maybeSlowDownForTesting(UnfilteredPartitionIterator iter)",
        "TEST_ITERATION_DELAY_MILLIS > 0",
        "public String name()",
        "return toCQLString();",
    ),
    READ_COMMAND_VERB_HANDLER: (
        "long timeout = message.expiresAtNanos() - message.createdAtNanos();",
        "command.setMonitoringTime(message.createdAtNanos(), message.isCrossNode(), timeout, DatabaseDescriptor.getSlowQueryTimeout(NANOSECONDS));",
        "catch (QueryCancelledException e)",
        "logger.debug(\"Query cancelled (timeout)\", e);",
        "Preconditions.checkState(!command.isCompleted(), \"Read marked as completed despite being aborted by timeout to table %s\", command.metadata());",
        "if (command.complete())",
        "MessagingService.instance().metrics.recordDroppedMessage(message, message.elapsedSinceCreated(NANOSECONDS), NANOSECONDS);",
    ),
    STORAGE_PROXY: (
        "public LocalReadRunnable(ReadCommand command, ReadCallback handler, Dispatcher.RequestTime requestTime)",
        "long deadline = requestTime.computeDeadline(verb.expiresAfterNanos());",
        "command.setMonitoringTime(requestTime.startedAtNanos(), false, deadline - requestTime.startedAtNanos(), DatabaseDescriptor.getSlowQueryTimeout(NANOSECONDS));",
        "catch (QueryCancelledException e)",
        "logger.debug(\"Query cancelled (timeout)\", e);",
        "Preconditions.checkState(!command.isCompleted(), \"Local read marked as completed despite being aborted by timeout to table %s\", command.metadata());",
        "if (command.complete())",
        "handler.response(response);",
        "MessagingService.instance().metrics.recordSelfDroppedMessage(verb, MonotonicClock.Global.preciseTime.now() - requestTime.startedAtNanos(), NANOSECONDS);",
        "handler.onFailure(FBUtilities.getBroadcastAddressAndPort(), RequestFailureReason.UNKNOWN);",
        "MessagingService.instance().latencySubscribers.add(FBUtilities.getBroadcastAddressAndPort(), MonotonicClock.Global.preciseTime.now() - requestTime.startedAtNanos(), NANOSECONDS);",
    ),
    QUERY_CANCELLED_EXCEPTION: (
        "public class QueryCancelledException extends RuntimeException",
        "public QueryCancelledException(ReadCommand command)",
        "Query cancelled for taking too long: ",
        "command.toCQLString()",
    ),
    CONFIG: (
        "public volatile DurationSpec.LongMillisecondsBound read_request_timeout = new DurationSpec.LongMillisecondsBound(\"5000ms\");",
        "public volatile DurationSpec.LongMillisecondsBound range_request_timeout = new DurationSpec.LongMillisecondsBound(\"10000ms\");",
        "@Replaces(oldName = \"slow_query_log_timeout_in_ms\"",
        "public volatile DurationSpec.LongMillisecondsBound slow_query_log_timeout = new DurationSpec.LongMillisecondsBound(\"500ms\");",
    ),
    CASSANDRA_YAML: (
        "read_request_timeout: 5000ms",
        "range_request_timeout: 10000ms",
        "slow_query_log_timeout: 500ms",
        "Set this value to zero to disable slow query logging.",
    ),
    DATABASE_DESCRIPTOR: (
        "static void checkForLowestAcceptedTimeouts(Config conf)",
        "if(conf.read_request_timeout.toMilliseconds() < LOWEST_ACCEPTED_TIMEOUT.toMilliseconds())",
        "conf.read_request_timeout = new DurationSpec.LongMillisecondsBound(\"10ms\");",
        "if(conf.range_request_timeout.toMilliseconds() < LOWEST_ACCEPTED_TIMEOUT.toMilliseconds())",
        "conf.range_request_timeout = new DurationSpec.LongMillisecondsBound(\"10ms\");",
        "public static long getReadRpcTimeout(TimeUnit unit)",
        "return conf.read_request_timeout.to(unit);",
        "public static void setReadRpcTimeout(long timeOutInMillis)",
        "conf.read_request_timeout = new DurationSpec.LongMillisecondsBound(timeOutInMillis);",
        "public static long getRangeRpcTimeout(TimeUnit unit)",
        "return conf.range_request_timeout.to(unit);",
        "public static void setRangeRpcTimeout(long timeOutInMillis)",
        "conf.range_request_timeout = new DurationSpec.LongMillisecondsBound(timeOutInMillis);",
        "public static long getSlowQueryTimeout(TimeUnit unit)",
        "return conf.slow_query_log_timeout.to(unit);",
    ),
    CASSANDRA_RELEVANT_PROPERTIES: (
        "MONITORING_MAX_OPERATIONS(\"cassandra.monitoring_max_operations\", \"50\")",
        "MONITORING_REPORT_INTERVAL_MS(\"cassandra.monitoring_report_interval_ms\", \"5000\")",
    ),
    STORAGE_SERVICE: (
        "public void setReadRpcTimeout(long value)",
        "DatabaseDescriptor.setReadRpcTimeout(value);",
        "logger.info(\"set read rpc timeout to {} ms\", value);",
        "public long getReadRpcTimeout()",
        "return DatabaseDescriptor.getReadRpcTimeout(MILLISECONDS);",
        "public void setRangeRpcTimeout(long value)",
        "DatabaseDescriptor.setRangeRpcTimeout(value);",
        "logger.info(\"set range rpc timeout to {} ms\", value);",
        "public long getRangeRpcTimeout()",
        "return DatabaseDescriptor.getRangeRpcTimeout(MILLISECONDS);",
    ),
    NODE_PROBE: (
        "public long getTimeout(String type)",
        "case \"read\":",
        "return ssProxy.getReadRpcTimeout();",
        "case \"range\":",
        "return ssProxy.getRangeRpcTimeout();",
        "public void setTimeout(String type, long value)",
        "ssProxy.setReadRpcTimeout(value);",
        "ssProxy.setRangeRpcTimeout(value);",
    ),
    SAI_QUERY_CONTEXT: (
        "Tracks state relevant to the execution of a single query, including metrics and timeout monitoring.",
        "private final ReadCommand readCommand;",
        "public final long executionQuotaNano;",
        "public boolean queryTimedOut = false;",
        "public QueryContext(ReadCommand readCommand, long executionQuotaMs)",
        "executionQuotaNano = TimeUnit.MILLISECONDS.toNanos(executionQuotaMs);",
        "public void checkpoint()",
        "if (totalQueryTimeNs() >= executionQuotaNano && !DISABLE_TIMEOUT)",
        "queryTimedOut = true;",
        "throw new QueryCancelledException(readCommand);",
    ),
    SAI_SEARCHER: (
        "long executionQuotaMs",
        "this.queryContext = new QueryContext(command, executionQuotaMs);",
    ),
    SAI_INDEX_RESULT_ITERATOR: (
        "queryContext.checkpoint();",
        "if (!(e instanceof QueryCancelledException))",
        "throw Throwables.cleaned(e);",
    ),
}

TEST_TOKEN_CHECKS = {
    MONITORING_TASK_TEST: (
        "public class MonitoringTaskTest",
        "MonitoringTask.instance = MonitoringTask.make(REPORT_INTERVAL_MS, MAX_TIMEDOUT_OPERATIONS);",
        "private static final class TestMonitor extends MonitorableImpl",
        "setMonitoringTime(timestamp, isCrossNode, timeout, slow);",
        "waitForOperationsToComplete",
        "waitForOperationsToBeReportedAsSlow",
        "public void testAbort()",
        "public void testAbortIdemPotent()",
        "public void testAbortCrossNode()",
        "public void testComplete()",
        "public void testCompleteIdemPotent()",
        "public void testReportSlow()",
        "public void testNoReportSlowIfZeroSlowTimeout()",
        "public void testReport()",
        "aborted operations are not logged as slow",
        "public void testRealScheduling()",
        "public void testMultipleThreads()",
        "public void testZeroMaxTimedoutOperations()",
        "public void testMaxTimedoutOperationsExceeded()",
        "public void testMultipleThreadsSameNameFailed()",
        "public void testMultipleThreadsSameNameSlow()",
        "public void testMultipleThreadsNoFailedOps()",
    ),
    READ_COMMAND_TEST: (
        "import org.apache.cassandra.exceptions.QueryCancelledException;",
        "public void testPartitionRangeAbort()",
        "ReadCommand readCommand = Util.cmd(cfs).build();",
        "readCommand.abort();",
        "catch (QueryCancelledException e)",
        "public void testSinglePartitionSliceAbort()",
        "public void testSinglePartitionNamesAbort()",
    ),
    PARSE_UNITS_TEST: (
        "assertEquals(new DurationSpec.LongMillisecondsBound(5000), config.read_request_timeout);",
        "assertEquals(new DurationSpec.LongMillisecondsBound(10000), config.range_request_timeout);",
        "assertEquals(new DurationSpec.LongMillisecondsBound(500), config.slow_query_log_timeout);",
    ),
    OLD_YAML_TEST: (
        "assertEquals(new DurationSpec.LongMillisecondsBound(5000), config.read_request_timeout);",
        "assertEquals(new DurationSpec.LongMillisecondsBound(10000), config.range_request_timeout);",
        "assertEquals(new DurationSpec.LongMillisecondsBound(500), config.slow_query_log_timeout);",
    ),
    DATABASE_DESCRIPTOR_TEST: (
        "public void testLowestAcceptableTimeouts()",
        "testConfig.read_request_timeout = greaterThanLowestTimeout;",
        "testConfig.range_request_timeout = greaterThanLowestTimeout;",
        "testConfig.read_request_timeout = lowerThanLowestTimeout;",
        "testConfig.range_request_timeout = lowerThanLowestTimeout;",
        "DatabaseDescriptor.checkForLowestAcceptedTimeouts(testConfig);",
        "assertEquals(testConfig.read_request_timeout, DatabaseDescriptor.LOWEST_ACCEPTED_TIMEOUT);",
        "assertEquals(testConfig.range_request_timeout, DatabaseDescriptor.LOWEST_ACCEPTED_TIMEOUT);",
    ),
}

DOC_TOKENS = (
    MATRIX_DOC,
    CHECKER_DOC,
    "research/tools/check-read-operation-monitoring-drift.py",
    COORDINATOR_MATRIX_DOC,
    COORDINATOR_CHECKER,
    "MonitorableImpl",
    "MonitoringTask",
    "ReadCommandVerbHandler",
    "StorageProxy.LocalReadRunnable",
    "QueryCancellationChecker",
    "QueryCancelledException",
    "QueryContext",
    "read_request_timeout",
    "range_request_timeout",
    "slow_query_log_timeout",
    "cassandra.monitoring_max_operations",
    "cassandra.monitoring_report_interval_ms",
    "MonitoringTaskTest",
    "ReadCommandTest",
) + SCENARIO_IDS


@dataclass(frozen=True)
class CheckResult:
    name: str
    source: str
    ok: bool
    detail: str = ""


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def contains_all(path: str, tokens: tuple[str, ...]) -> list[CheckResult]:
    text = read(path)
    return [
        CheckResult(f"token {token}", path, token in text)
        for token in tokens
    ]


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def source_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        checks.extend(contains_all(path, tokens))

    storage_service = read(STORAGE_SERVICE)
    node_probe = read(NODE_PROBE)
    checks.extend(
        [
            CheckResult("no slow query runtime setter on StorageService", STORAGE_SERVICE, "setSlowQuery" not in storage_service and "SlowQueryTimeout" not in storage_service),
            CheckResult("no slow query runtime setter on NodeProbe timeout route", NODE_PROBE, "slow_query" not in node_probe and "\"slow\"" not in node_probe),
            CheckResult("coordinator matrix exists", COORDINATOR_MATRIX_DOC, (REPO_ROOT / COORDINATOR_MATRIX_DOC).is_file()),
            CheckResult("coordinator checker exists", COORDINATOR_CHECKER, (REPO_ROOT / COORDINATOR_CHECKER).is_file()),
        ]
    )
    return checks


def test_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []
    for path, tokens in TEST_TOKEN_CHECKS.items():
        checks.extend(contains_all(path, tokens))
    return checks


def doc_checks() -> list[CheckResult]:
    matrix = read(MATRIX_DOC)
    checker = read(CHECKER_DOC)
    readme = read(README_DOC)
    source_map = read(SOURCE_MAP_DOC)
    matrix_and_checker = matrix + "\n" + checker
    all_docs = "\n".join((matrix, checker, readme, source_map))

    checks = [CheckResult(f"scenario documented {scenario}", f"{MATRIX_DOC} / {CHECKER_DOC}", documented(scenario, matrix_and_checker)) for scenario in SCENARIO_IDS]
    checks.extend(CheckResult(f"doc token {token}", "research docs", token in all_docs) for token in DOC_TOKENS)
    checks.extend(
        [
            CheckResult("README references matrix", README_DOC, MATRIX_DOC.split("/", 1)[1] in readme),
            CheckResult("README references checker", README_DOC, CHECKER_DOC.split("/", 1)[1] in readme and "check-read-operation-monitoring-drift.py" in readme),
            CheckResult("source-map references matrix", SOURCE_MAP_DOC, MATRIX_DOC in source_map),
            CheckResult("source-map references checker", SOURCE_MAP_DOC, "research/tools/check-read-operation-monitoring-drift.py" in source_map),
            CheckResult("coordinator boundary documented", MATRIX_DOC, COORDINATOR_MATRIX_DOC in matrix and "ReadCallback" in matrix),
        ]
    )
    return checks


def check() -> tuple[dict[str, object], bool]:
    sources = source_checks()
    tests = test_checks()
    docs = doc_checks()
    result = {
        "scenario_ids": list(SCENARIO_IDS),
        "source_checks": [entry.__dict__ for entry in sources],
        "test_checks": [entry.__dict__ for entry in tests],
        "doc_checks": [entry.__dict__ for entry in docs],
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in tests) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check read operation monitoring source/test/doc coverage.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    try:
        result, ok = check()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for area in ("source_checks", "test_checks", "doc_checks"):
            failed = [entry for entry in result[area] if not entry["ok"]]
            for entry in failed:
                detail = f" ({entry['detail']})" if entry.get("detail") else ""
                print(f"{area}: {entry['source']}: failed {entry['name']}{detail}")
        if ok:
            print(f"OK read operation monitoring checks passed ({len(result['scenario_ids'])} scenarios)")
        else:
            print("Read operation monitoring checks failed.", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
