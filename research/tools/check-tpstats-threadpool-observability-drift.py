#!/usr/bin/env python3
#
# Source-only drift check for nodetool tpstats thread-pool observability research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

TPSTATS = "src/java/org/apache/cassandra/tools/nodetool/TpStats.java"
TPSTATS_HOLDER = "src/java/org/apache/cassandra/tools/nodetool/stats/TpStatsHolder.java"
TPSTATS_PRINTER = "src/java/org/apache/cassandra/tools/nodetool/stats/TpStatsPrinter.java"
NODEPROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
THREAD_POOL_METRICS = "src/java/org/apache/cassandra/metrics/ThreadPoolMetrics.java"
THREAD_POOLS_TABLE = "src/java/org/apache/cassandra/db/virtual/ThreadPoolsTable.java"
MESSAGING_METRICS = "src/java/org/apache/cassandra/metrics/MessagingMetrics.java"
INTERNAL_NODE_PROBE = "test/distributed/org/apache/cassandra/distributed/mock/nodetool/InternalNodeProbe.java"

TPSTATS_TEST = "test/unit/org/apache/cassandra/tools/nodetool/TpStatsTest.java"
THREAD_POOL_METRICS_TEST = "test/unit/org/apache/cassandra/metrics/ThreadPoolMetricsTest.java"
MESSAGING_SERVICE_TEST = "test/unit/org/apache/cassandra/net/MessagingServiceTest.java"

MATRIX_DOC = "research/module-tpstats-threadpool-observability-matrix.md"
CHECKER_DOC = "research/module-tpstats-threadpool-observability-drift-checker.md"
OPERATIONS_DOC = "research/module-operations-observability.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

TPSTATS_THREAD_POOL_METRICS = (
    "ActiveTasks",
    "PendingTasks",
    "CompletedTasks",
    "CurrentlyBlockedTasks",
    "TotalBlockedTasks",
)

THREAD_POOL_METRIC_CONSTANTS = (
    "ACTIVE_TASKS",
    "PENDING_TASKS",
    "COMPLETED_TASKS",
    "CURRENTLY_BLOCKED_TASKS",
    "TOTAL_BLOCKED_TASKS",
    "MAX_POOL_SIZE",
    "MAX_TASKS_QUEUED",
    "OLDEST_TASK_QUEUE_TIME",
)

SCENARIO_IDS = (
    "tpstats_command_format_contract",
    "tpstats_holder_threadpool_map_contract",
    "tpstats_holder_dropped_latency_contract",
    "tpstats_default_printer_contract",
    "tpstats_nodeprobe_threadpool_jmx_contract",
    "tpstats_nodeprobe_metric_wrapper_contract",
    "tpstats_threadpool_metrics_registry_contract",
    "tpstats_threadpool_virtual_table_boundary",
    "tpstats_dropped_message_metrics_contract",
    "tpstats_existing_tests_baseline",
)

SOURCE_TOKEN_CHECKS = {
    TPSTATS: (
        '@Command(name = "tpstats"',
        'name = {"-F", "--format"}',
        '!"json".equals(outputFormat) && !"yaml".equals(outputFormat)',
        '"arguments for -F are json,yaml only."',
        "StatsHolder data = new TpStatsHolder(probe);",
        "StatsPrinter printer = TpStatsPrinter.from(outputFormat);",
    ),
    TPSTATS_HOLDER: (
        "public class TpStatsHolder implements StatsHolder",
        "public Map<String, Object> convert2Map()",
        'result.put("ThreadPools", threadPools);',
        "for (Map.Entry<String, Integer> entry : probe.getDroppedMessages().entrySet())",
        'result.put("DroppedMessage", droppedMessage);',
        'result.put("WaitLatencies", waitLatencies);',
        "probe.metricPercentilesAsArray(probe.getMessagingQueueWaitMetrics(key))",
        "// ignore the exceptions when fetching metrics",
    ),
    TPSTATS_PRINTER: (
        'case "json":',
        "return new StatsPrinter.JsonPrinter();",
        'case "yaml":',
        "return new StatsPrinter.YamlPrinter();",
        'poolBuilder.add("Pool Name", "Active", "Pending", "Completed", "Blocked", "All time blocked");',
        "Latencies waiting in queue (micros) per dropped message types",
        'droppedBuilder.add("Message type", "Dropped    ", "50%     ", "95%     ", "99%     ", "Max");',
        "data.probe.metricPercentilesAsArray(data.probe.getMessagingQueueWaitMetrics(entry.getKey()))",
        '"N/A", "N/A", "N/A", "N/A"',
    ),
    NODEPROBE: (
        "private static Multimap<String, String> getJmxThreadPools",
        'new ObjectName("org.apache.cassandra.metrics:type=ThreadPools,*")',
        'threadPools.put(oName.getKeyProperty("path"), oName.getKeyProperty("scope"));',
        "public Object getThreadPoolMetric(String pathName, String poolName, String metricName)",
        'String.format("org.apache.cassandra.metrics:type=ThreadPools,path=%s,scope=%s,name=%s"',
        "if (!mbeanServerConn.isRegistered(oName))",
        'return "N/A";',
        "CassandraMetricsRegistry.JmxGaugeMBean.class",
        "CassandraMetricsRegistry.JmxCounterMBean.class",
        'throw new AssertionError("Unknown ThreadPools metric name " + metricName);',
    ),
    THREAD_POOL_METRICS: (
        'public static final String ACTIVE_TASKS = "ActiveTasks";',
        'public static final String PENDING_TASKS = "PendingTasks";',
        'public static final String COMPLETED_TASKS = "CompletedTasks";',
        'public static final String CURRENTLY_BLOCKED_TASKS = "CurrentlyBlockedTasks";',
        'public static final String TOTAL_BLOCKED_TASKS = "TotalBlockedTasks";',
        'public static final String MAX_POOL_SIZE = "MaxPoolSize";',
        'public static final String MAX_TASKS_QUEUED = "MaxTasksQueued";',
        'public static final String OLDEST_TASK_QUEUE_TIME = "OldestTaskQueueTime";',
        "Metrics.register(makeMetricName(path, poolName, ACTIVE_TASKS), activeTasks);",
        "Metrics.register(makeMetricName(path, poolName, OLDEST_TASK_QUEUE_TIME), oldestTaskQueueTime);",
        'format("org.apache.cassandra.metrics:type=ThreadPools,path=%s,scope=%s,name=%s"',
    ),
    THREAD_POOLS_TABLE: (
        'super(TableMetadata.builder(keyspace, "thread_pools")',
        "Metrics.getThreadPoolMetrics(poolName)",
        "Metrics.allThreadPoolMetrics()",
        ".column(ACTIVE_TASKS, metrics.activeTasks.getValue())",
        ".column(ACTIVE_TASKS_LIMIT, metrics.maxPoolSize.getValue())",
        ".column(BLOCKED_TASKS_ALL_TIME, metrics.totalBlocked.getCount());",
    ),
    MESSAGING_METRICS: (
        "public Map<String, Integer> getDroppedMessages()",
        "map.put(entry.getKey().toString(), (int) entry.getValue().metrics.dropped.getCount());",
        "private void logDroppedMessages()",
        "if (resetAndConsumeDroppedErrors(logger::info) > 0)",
        "StatusLogger.log();",
        "public int resetAndConsumeDroppedErrors(Consumer<String> messageConsumer)",
    ),
    INTERNAL_NODE_PROBE: (
        "public Multimap<String, String> getThreadPools()",
        "throw new UnsupportedOperationException();",
        "public Object getThreadPoolMetric(String pathName, String poolName, String metricName)",
    ),
    TPSTATS_TEST: (
        "public void testMaybeChangeDocs()",
        'ToolRunner.invokeNodetool("help", "tpstats")',
        "public void testTpStats()",
        "Pool Name \\\\s+ Active Pending Completed Blocked All time blocked",
        "Latencies waiting in queue (micros) per dropped message types",
        "Message.out(ECHO_REQ, NoPayload.noPayload)",
        "ECHO_REQ\\\\D.*[1-9].*",
        "public void testFormatArg()",
        'Pair.of("-F", "json")',
        'Pair.of("--format", "yaml")',
        "WaitLatencies",
    ),
    THREAD_POOL_METRICS_TEST: (
        "public void testJMXEnabledThreadPoolMetricsWithNoBlockedThread()",
        "public void testJMXEnabledThreadPoolMetricsWithBlockedThread()",
        "public void testSEPExecutorMetrics()",
        "spinAssertEquals(2L, metrics.totalBlocked::getCount);",
    ),
    MESSAGING_SERVICE_TEST: (
        "testDroppedMessages",
        "messagingService.metrics.getDroppedMessages()",
        "assertEquals(5000",
        "assertEquals(7500",
    ),
}

DOC_REQUIRED_TOKENS = (
    MATRIX_DOC,
    CHECKER_DOC,
    "check-tpstats-threadpool-observability-drift.py",
    TPSTATS,
    TPSTATS_HOLDER,
    TPSTATS_PRINTER,
    NODEPROBE,
    THREAD_POOL_METRICS,
    THREAD_POOLS_TABLE,
    MESSAGING_METRICS,
    TPSTATS_TEST,
    THREAD_POOL_METRICS_TEST,
    MESSAGING_SERVICE_TEST,
    "ThreadPools",
    "DroppedMessage",
    "WaitLatencies",
    "Pool Name",
    "ActiveTasks",
    "PendingTasks",
    "CompletedTasks",
    "CurrentlyBlockedTasks",
    "TotalBlockedTasks",
    "MaxTasksQueued",
    "OldestTaskQueueTime",
    "system_views.thread_pools",
) + SCENARIO_IDS


@dataclass(frozen=True)
class CheckResult:
    name: str
    source: str
    ok: bool
    detail: str = ""


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def source_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []

    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(CheckResult(f"source token contract {path}", path, all(token in text for token in tokens)))

    holder = read(TPSTATS_HOLDER)
    printer = read(TPSTATS_PRINTER)
    nodeprobe = read(NODEPROBE)
    metrics = read(THREAD_POOL_METRICS)

    checks.extend(
        [
            CheckResult(
                "TpStatsHolder reads documented thread-pool metrics",
                TPSTATS_HOLDER,
                all(f'probe.getThreadPoolMetric(tp.getKey(), tp.getValue(), "{metric}")' in holder for metric in TPSTATS_THREAD_POOL_METRICS),
            ),
            CheckResult(
                "TpStatsPrinter reads documented thread-pool metrics",
                TPSTATS_PRINTER,
                all(f'data.probe.getThreadPoolMetric(tpool.getKey(), tpool.getValue(), "{metric}").toString()' in printer for metric in TPSTATS_THREAD_POOL_METRICS),
            ),
            CheckResult(
                "NodeProbe supports tpstats metrics",
                NODEPROBE,
                all(f"ThreadPoolMetrics.{constant}" in nodeprobe for constant in THREAD_POOL_METRIC_CONSTANTS[:6]),
            ),
            CheckResult(
                "ThreadPoolMetrics defines expected constants",
                THREAD_POOL_METRICS,
                all(f"public static final String {constant}" in metrics for constant in THREAD_POOL_METRIC_CONSTANTS),
            ),
        ]
    )
    return checks


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def doc_checks() -> list[CheckResult]:
    matrix = read(MATRIX_DOC)
    checker = read(CHECKER_DOC)
    operations = read(OPERATIONS_DOC)
    readme = read(README_DOC)
    source_map = read(SOURCE_MAP_DOC)
    all_docs = "\n".join((matrix, checker, operations, readme, source_map))
    matrix_and_checker = matrix + "\n" + checker

    checks = [CheckResult(f"scenario documented {scenario}", f"{MATRIX_DOC} / {CHECKER_DOC}", documented(scenario, matrix_and_checker)) for scenario in SCENARIO_IDS]
    checks.extend(CheckResult(f"doc token {token}", "research docs", token in all_docs) for token in DOC_REQUIRED_TOKENS)
    checks.extend(
        [
            CheckResult("README references matrix", README_DOC, MATRIX_DOC.split("/", 1)[1] in readme),
            CheckResult("README references checker", README_DOC, CHECKER_DOC.split("/", 1)[1] in readme and "check-tpstats-threadpool-observability-drift.py" in readme),
            CheckResult("source-map references matrix", SOURCE_MAP_DOC, MATRIX_DOC in source_map),
            CheckResult("source-map references checker", SOURCE_MAP_DOC, "research/tools/check-tpstats-threadpool-observability-drift.py" in source_map),
            CheckResult("operations doc references TpStatsHolder and printer", OPERATIONS_DOC, "TpStatsHolder" in operations and "TpStatsPrinter" in operations),
        ]
    )
    return checks


def check() -> tuple[dict[str, object], bool]:
    sources = source_checks()
    docs = doc_checks()
    result = {
        "scenario_ids": list(SCENARIO_IDS),
        "tpstats_thread_pool_metrics": list(TPSTATS_THREAD_POOL_METRICS),
        "thread_pool_metric_constants": list(THREAD_POOL_METRIC_CONSTANTS),
        "source_checks": [entry.__dict__ for entry in sources],
        "doc_checks": [entry.__dict__ for entry in docs],
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check tpstats thread-pool observability source/doc coverage.")
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
        failed_sources = [entry for entry in result["source_checks"] if not entry["ok"]]
        failed_docs = [entry for entry in result["doc_checks"] if not entry["ok"]]
        if failed_sources:
            for entry in failed_sources:
                detail = f" ({entry['detail']})" if entry.get("detail") else ""
                print(f"source: {entry['source']}: failed {entry['name']}{detail}")
        if failed_docs:
            for entry in failed_docs:
                print(f"doc: {entry['source']}: missing {entry['name']}")
        if ok:
            print(f"OK tpstats threadpool observability checks passed ({len(result['scenario_ids'])} scenarios)")
        else:
            print("Tpstats threadpool observability checks failed.", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
