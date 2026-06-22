#!/usr/bin/env python3
#
# Source-only drift check for nodetool proxyhistograms client request latency research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

PROXY_HISTOGRAMS = "src/java/org/apache/cassandra/tools/nodetool/ProxyHistograms.java"
NODE_TOOL = "src/java/org/apache/cassandra/tools/NodeTool.java"
NODEPROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
CLIENT_REQUESTS_HOLDER = "src/java/org/apache/cassandra/metrics/ClientRequestsMetricsHolder.java"
CLIENT_REQUEST_METRICS = "src/java/org/apache/cassandra/metrics/ClientRequestMetrics.java"
VIEW_WRITE_METRICS = "src/java/org/apache/cassandra/metrics/ViewWriteMetrics.java"
STORAGE_PROXY = "src/java/org/apache/cassandra/service/StorageProxy.java"
RANGE_ITERATOR = "src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java"
PAXOS = "src/java/org/apache/cassandra/service/paxos/Paxos.java"

CLIENT_REQUEST_METRICS_TEST = "test/unit/org/apache/cassandra/metrics/ClientRequestMetricsTest.java"
ROW_COLUMN_METRICS_TEST = "test/unit/org/apache/cassandra/metrics/ClientRequestRowAndColumnMetricsTest.java"
JMX_GETTER_CHECK_TEST = "test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java"

MATRIX_DOC = "research/module-proxyhistograms-clientrequest-observability-matrix.md"
CHECKER_DOC = "research/module-proxyhistograms-clientrequest-drift-checker.md"
OPERATIONS_DOC = "research/module-operations-observability.md"
OBS_MAPPING_DOC = "research/module-observability-mapping.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

EXPECTED_PERCENTILES = ("50%", "75%", "95%", "98%", "99%", "Min", "Max")
EXPECTED_SCOPES = ("Read", "Write", "RangeSlice", "CASRead", "CASWrite", "ViewWrite")
EXPECTED_COLUMNS = (
    "Read Latency",
    "Write Latency",
    "Range Latency",
    "CAS Read Latency",
    "CAS Write Latency",
    "View Write Latency",
)

SCENARIO_IDS = (
    "proxyhistograms_command_surface_contract",
    "proxyhistograms_percentile_order_contract",
    "proxyhistograms_metric_scope_contract",
    "proxyhistograms_output_column_contract",
    "proxyhistograms_nodeprobe_jmx_contract",
    "proxyhistograms_read_write_update_contract",
    "proxyhistograms_range_update_contract",
    "proxyhistograms_cas_update_contract",
    "proxyhistograms_viewwrite_update_contract",
    "proxyhistograms_test_gap",
)

SOURCE_TOKEN_CHECKS = {
    PROXY_HISTOGRAMS: (
        '@Command(name = "proxyhistograms", description = "Print statistic histograms for network operations")',
        'String[] percentiles = {"50%", "75%", "95%", "98%", "99%", "Min", "Max"};',
        'probe.metricPercentilesAsArray(probe.getProxyMetric("Read"))',
        'probe.metricPercentilesAsArray(probe.getProxyMetric("Write"))',
        'probe.metricPercentilesAsArray(probe.getProxyMetric("RangeSlice"))',
        'probe.metricPercentilesAsArray(probe.getProxyMetric("CASRead"))',
        'probe.metricPercentilesAsArray(probe.getProxyMetric("CASWrite"))',
        'probe.metricPercentilesAsArray(probe.getProxyMetric("ViewWrite"))',
        '"proxy histograms"',
        '"Percentile"',
        '"Read Latency"',
        '"View Write Latency"',
        '"(micros)"',
    ),
    NODE_TOOL: (
        "ProxyHistograms.class",
    ),
    NODEPROBE: (
        "public CassandraMetricsRegistry.JmxTimerMBean getProxyMetric(String scope)",
        'new ObjectName("org.apache.cassandra.metrics:type=ClientRequest,scope=" + scope + ",name=Latency")',
        "CassandraMetricsRegistry.JmxTimerMBean.class",
        "public Double[] metricPercentilesAsArray(CassandraMetricsRegistry.JmxTimerMBean metric)",
        "metric.get50thPercentile()",
        "metric.get75thPercentile()",
        "metric.get95thPercentile()",
        "metric.get98thPercentile()",
        "metric.get99thPercentile()",
        "metric.getMin()",
        "metric.getMax()",
    ),
    CLIENT_REQUESTS_HOLDER: (
        'public static final ClientRequestMetrics readMetrics = new ClientRequestMetrics("Read");',
        'public static final ClientWriteRequestMetrics writeMetrics = new ClientWriteRequestMetrics("Write");',
        'public static final CASClientWriteRequestMetrics casWriteMetrics = new CASClientWriteRequestMetrics("CASWrite");',
        'public static final CASClientRequestMetrics casReadMetrics = new CASClientRequestMetrics("CASRead");',
        'public static final ViewWriteMetrics viewWriteMetrics = new ViewWriteMetrics("ViewWrite");',
    ),
    CLIENT_REQUEST_METRICS: (
        "public class ClientRequestMetrics extends LatencyMetrics",
        'super("ClientRequest", scope);',
        "timeouts = Metrics.meter(factory.createMetricName(\"Timeouts\"));",
        "remoteRequests = Metrics.meter(factory.createMetricName(\"RemoteRequests\"));",
    ),
    VIEW_WRITE_METRICS: (
        "public class ViewWriteMetrics extends ClientRequestMetrics",
        "public final Timer viewWriteLatency;",
        "super(scope);",
        'viewWriteLatency = Metrics.timer(factory.createMetricName("ViewWriteLatency"));',
    ),
    STORAGE_PROXY: (
        "writeMetrics.addNano(latency);",
        "readMetrics.addNano(latency);",
        "viewWriteMetrics.addNano(nanoTime() - startTime);",
        "viewWriteMetrics.viewWriteLatency.update(delay, MILLISECONDS);",
        "casWriteMetrics.addNano(latency);",
        "casReadMetrics.addNano(latency);",
    ),
    RANGE_ITERATOR: (
        'public static final ClientRangeRequestMetrics rangeMetrics = new ClientRangeRequestMetrics("RangeSlice");',
        "rangeMetrics.addNano(latency);",
        "rangeMetrics.roundTrips.update(batchesRequested);",
    ),
    PAXOS: (
        "casWriteMetrics.addNano(latency);",
        "casReadMetrics.addNano(latency);",
    ),
    CLIENT_REQUEST_METRICS_TEST: (
        "public void testRangeRead()",
        "RangeCommandIterator.rangeMetrics.latency.getCount()",
        "RangeCommandIterator.rangeMetrics.roundTrips.getCount()",
    ),
    ROW_COLUMN_METRICS_TEST: (
        "shouldRecordReadMetricsForMultiRowPartitionSelection",
        "shouldRecordWriteMetricsForSingleValueRow",
        "shouldRecordWriteMetricsForCAS",
        "shouldRecordReadMetricsOnSerialRead",
    ),
    JMX_GETTER_CHECK_TEST: (
        "testAllValidGetters(Cluster cluster)",
        "mbsc.getMBeanInfo(name)",
        "mbsc.getAttribute(name, a.getName())",
    ),
}

DOC_REQUIRED_TOKENS = (
    MATRIX_DOC,
    CHECKER_DOC,
    "check-proxyhistograms-clientrequest-drift.py",
    PROXY_HISTOGRAMS,
    NODEPROBE,
    CLIENT_REQUESTS_HOLDER,
    CLIENT_REQUEST_METRICS,
    VIEW_WRITE_METRICS,
    STORAGE_PROXY,
    RANGE_ITERATOR,
    PAXOS,
    CLIENT_REQUEST_METRICS_TEST,
    ROW_COLUMN_METRICS_TEST,
    JMX_GETTER_CHECK_TEST,
    "ProxyHistograms",
    "proxyhistograms",
    "RangeSlice",
    "ViewWriteLatency",
    "JmxTimerMBean",
    "proxyhistograms_test_gap",
) + SCENARIO_IDS + EXPECTED_PERCENTILES + EXPECTED_SCOPES + EXPECTED_COLUMNS


@dataclass(frozen=True)
class CheckResult:
    name: str
    source: str
    ok: bool
    detail: str = ""


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_files_with_proxyhistograms() -> list[str]:
    matches: list[str] = []
    for root in ("test/unit", "test/distributed", "test/simulator", "test/long"):
        root_path = REPO_ROOT / root
        if not root_path.exists():
            continue
        for path in root_path.rglob("*.java"):
            text = path.read_text(encoding="utf-8")
            if "proxyhistograms" in text or "ProxyHistograms" in text:
                matches.append(str(path.relative_to(REPO_ROOT)))
    return sorted(matches)


def source_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []

    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(CheckResult(f"source token contract {path}", path, all(token in text for token in tokens)))

    proxy = read(PROXY_HISTOGRAMS)
    checks.extend(
        [
            CheckResult("percentile labels match baseline", PROXY_HISTOGRAMS, all(f'"{label}"' in proxy for label in EXPECTED_PERCENTILES)),
            CheckResult("proxyhistograms scopes match baseline", PROXY_HISTOGRAMS, all(f'getProxyMetric("{scope}")' in proxy for scope in EXPECTED_SCOPES)),
            CheckResult("proxyhistograms columns match baseline", PROXY_HISTOGRAMS, all(f'"{column}"' in proxy for column in EXPECTED_COLUMNS)),
        ]
    )

    direct_tests = test_files_with_proxyhistograms()
    checks.append(CheckResult("direct proxyhistograms test gap still open", "test/**/*.java", not direct_tests, ", ".join(direct_tests)))
    return checks


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def doc_checks() -> list[CheckResult]:
    matrix = read(MATRIX_DOC)
    checker = read(CHECKER_DOC)
    operations = read(OPERATIONS_DOC)
    obs_mapping = read(OBS_MAPPING_DOC)
    readme = read(README_DOC)
    source_map = read(SOURCE_MAP_DOC)
    all_docs = "\n".join((matrix, checker, operations, obs_mapping, readme, source_map))
    matrix_and_checker = matrix + "\n" + checker

    checks = [CheckResult(f"scenario documented {scenario}", f"{MATRIX_DOC} / {CHECKER_DOC}", documented(scenario, matrix_and_checker)) for scenario in SCENARIO_IDS]
    checks.extend(CheckResult(f"doc token {token}", "research docs", token in all_docs) for token in DOC_REQUIRED_TOKENS)
    checks.extend(
        [
            CheckResult("README references matrix", README_DOC, MATRIX_DOC.split("/", 1)[1] in readme),
            CheckResult("README references checker", README_DOC, CHECKER_DOC.split("/", 1)[1] in readme and "check-proxyhistograms-clientrequest-drift.py" in readme),
            CheckResult("source-map references matrix", SOURCE_MAP_DOC, MATRIX_DOC in source_map),
            CheckResult("source-map references checker", SOURCE_MAP_DOC, "research/tools/check-proxyhistograms-clientrequest-drift.py" in source_map),
            CheckResult("operations docs mention ProxyHistograms", OPERATIONS_DOC, "ProxyHistograms" in operations or "proxyhistograms" in operations),
            CheckResult("observability mapping mentions ProxyHistograms", OBS_MAPPING_DOC, "ProxyHistograms" in obs_mapping),
        ]
    )
    return checks


def check() -> tuple[dict[str, object], bool]:
    sources = source_checks()
    docs = doc_checks()
    result = {
        "scenario_ids": list(SCENARIO_IDS),
        "percentiles": list(EXPECTED_PERCENTILES),
        "scopes": list(EXPECTED_SCOPES),
        "columns": list(EXPECTED_COLUMNS),
        "direct_test_candidates": test_files_with_proxyhistograms(),
        "source_checks": [entry.__dict__ for entry in sources],
        "doc_checks": [entry.__dict__ for entry in docs],
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check proxyhistograms client request source/doc coverage.")
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
            print(f"OK proxyhistograms client request checks passed ({len(result['scenario_ids'])} scenarios)")
        else:
            print("Proxyhistograms client request checks failed.", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
