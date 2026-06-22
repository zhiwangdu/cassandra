#!/usr/bin/env python3
#
# Source-only drift check for nodetool tablehistograms observability research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

TABLE_HISTOGRAMS = "src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java"
NODE_TOOL = "src/java/org/apache/cassandra/tools/NodeTool.java"
NODEPROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
TABLE_METRICS = "src/java/org/apache/cassandra/metrics/TableMetrics.java"
CASSANDRA_METRICS_REGISTRY = "src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java"

TABLE_HISTOGRAMS_TEST = "test/unit/org/apache/cassandra/tools/nodetool/TableHistogramsTest.java"
COLUMN_FAMILY_METRIC_TEST = "test/unit/org/apache/cassandra/db/ColumnFamilyMetricTest.java"
ESTIMATED_HISTOGRAM_TEST = "test/unit/org/apache/cassandra/utils/EstimatedHistogramTest.java"
DECAYING_HISTOGRAM_TEST = "test/unit/org/apache/cassandra/metrics/DecayingEstimatedHistogramReservoirTest.java"

MATRIX_DOC = "research/module-nodetool-tablehistograms-observability-matrix.md"
CHECKER_DOC = "research/module-nodetool-tablehistograms-drift-checker.md"
OPERATIONS_DOC = "research/module-operations-observability.md"
OBS_MAPPING_DOC = "research/module-observability-mapping.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

EXPECTED_PERCENTILES = ("50%", "75%", "95%", "98%", "99%", "Min", "Max")
EXPECTED_COLUMNS = ("Read Latency", "Write Latency", "SSTables", "Partition Size", "Cell Count")
EXPECTED_METRICS = (
    "EstimatedPartitionSizeHistogram",
    "EstimatedColumnCountHistogram",
    "ReadLatency",
    "WriteLatency",
    "SSTablesPerReadHistogram",
)

SCENARIO_IDS = (
    "tablehistograms_command_surface_contract",
    "tablehistograms_table_selection_contract",
    "tablehistograms_metric_source_contract",
    "tablehistograms_estimated_histogram_contract",
    "tablehistograms_percentile_order_contract",
    "tablehistograms_output_column_contract",
    "tablehistograms_nodeprobe_jmx_contract",
    "tablehistograms_tablemetrics_definition_contract",
    "tablehistograms_jmx_percentile_mbean_contract",
    "tablehistograms_existing_test_baseline",
)

SOURCE_TOKEN_CHECKS = {
    TABLE_HISTOGRAMS: (
        '@Command(name = "tablehistograms", description = "Print statistic histograms for a given table")',
        '@Arguments(usage = "[<keyspace> <table> | <keyspace.table>]"',
        "Iterator<Map.Entry<String, ColumnFamilyStoreMBean>> tableMBeans = probe.getColumnFamilyStoreMBeanProxies();",
        "allTables.put(entry.getKey(), entry.getValue().getTableName());",
        "if (args.size() == 2 && args.stream().noneMatch(arg -> arg.contains(\".\")))",
        "Pair<String, String> ksTbPair = parseTheKsTbPair(args.get(0));",
        "tablesList = allTables;",
        'throw new IllegalArgumentException("tablehistograms requires <keyspace> <table> or <keyspace.table> format argument.");',
        "if (!allTables.containsEntry(keyspace, table))",
        'throw new IllegalArgumentException("Unknown table " + keyspace + \'.\' + table);',
        'probe.getColumnFamilyMetric(keyspace, table, "EstimatedPartitionSizeHistogram")',
        'probe.getColumnFamilyMetric(keyspace, table, "EstimatedColumnCountHistogram")',
        "EstimatedHistogram partitionSizeHist = new EstimatedHistogram(estimatedPartitionSize);",
        "EstimatedHistogram columnCountHist = new EstimatedHistogram(estimatedColumnCount);",
        "partitionSizeHist.isOverflowed()",
        "columnCountHist.isOverflowed()",
        'String[] percentiles = new String[]{"50%", "75%", "95%", "98%", "99%", "Min", "Max"};',
        'probe.getColumnFamilyMetric(keyspace, table, "ReadLatency")',
        'probe.getColumnFamilyMetric(keyspace, table, "WriteLatency")',
        'probe.getColumnFamilyMetric(keyspace, table, "SSTablesPerReadHistogram")',
        '"Percentile", "Read Latency", "Write Latency", "SSTables", "Partition Size", "Cell Count"',
        '"(micros)", "(micros)", "", "(bytes)", ""',
        "private Pair<String, String> parseTheKsTbPair(String ksAndTb)",
        'checkArgument(input.length == 2, "tablehistograms requires keyspace and table name arguments");',
    ),
    NODE_TOOL: (
        "TableHistograms.class",
    ),
    NODEPROBE: (
        "public Object getColumnFamilyMetric(String ks, String cf, String metricName)",
        'String type = cf.contains(".") ? "IndexTable" : "Table";',
        'new ObjectName(String.format("org.apache.cassandra.metrics:type=%s,keyspace=%s,scope=%s,name=%s", type, ks, cf, metricName))',
        'case "EstimatedColumnCountHistogram":',
        'case "EstimatedPartitionSizeHistogram":',
        "CassandraMetricsRegistry.JmxGaugeMBean.class).getValue();",
        'case "ReadLatency":',
        'case "WriteLatency":',
        "CassandraMetricsRegistry.JmxTimerMBean.class",
        'case "SSTablesPerReadHistogram":',
        "CassandraMetricsRegistry.JmxHistogramMBean.class",
        "public Double[] metricPercentilesAsArray(CassandraMetricsRegistry.JmxHistogramMBean metric)",
        "metric.get50thPercentile()",
        "metric.get75thPercentile()",
        "metric.get95thPercentile()",
        "metric.get98thPercentile()",
        "metric.get99thPercentile()",
        "metric.getMin()",
        "metric.getMax()",
        "public Double[] metricPercentilesAsArray(CassandraMetricsRegistry.JmxTimerMBean metric)",
    ),
    TABLE_METRICS: (
        "public final Gauge<long[]> estimatedPartitionSizeHistogram;",
        "public final Gauge<long[]> estimatedColumnCountHistogram;",
        "public final TableHistogram sstablesPerReadHistogram;",
        "public final LatencyMetrics readLatency;",
        "public final LatencyMetrics writeLatency;",
        'estimatedPartitionSizeHistogram = createTableGauge("EstimatedPartitionSizeHistogram", "EstimatedRowSizeHistogram"',
        "SSTableReader::getEstimatedPartitionSize",
        'estimatedColumnCountHistogram = createTableGauge("EstimatedColumnCountHistogram", "EstimatedColumnCountHistogram"',
        "SSTableReader::getEstimatedCellPerPartitionCount",
        'sstablesPerReadHistogram = createTableHistogram("SSTablesPerReadHistogram", cfs.keyspace.metric.sstablesPerReadHistogram, true);',
        'readLatency = createLatencyMetrics("Read", cfs.keyspace.metric.readLatency, GLOBAL_READ_LATENCY);',
        'writeLatency = createLatencyMetrics("Write", cfs.keyspace.metric.writeLatency, GLOBAL_WRITE_LATENCY);',
    ),
    CASSANDRA_METRICS_REGISTRY: (
        "public interface JmxHistogramMBean extends MetricMBean",
        "double get50thPercentile();",
        "double get75thPercentile();",
        "double get95thPercentile();",
        "double get98thPercentile();",
        "double get99thPercentile();",
        "double get999thPercentile();",
        "public interface JmxTimerMBean extends JmxMeterMBean",
        "double getMin();",
        "double getMax();",
    ),
    TABLE_HISTOGRAMS_TEST: (
        "public class TableHistogramsTest extends CQLTester",
        'private static final String INFO_ROW = "Percentile      Read Latency     Write Latency          SSTables    Partition Size        Cell Count";',
        "public void testMaybeChangeDocs()",
        'ToolRunner.ToolResult tool = invokeNodetool("help", "tablehistograms");',
        "nodetool tablehistograms - Print statistic histograms for a given table",
        "public void testWithNoTableSpecified()",
        'ToolRunner.ToolResult tool = invokeNodetool("tablehistograms");',
        "StringUtils.countMatches(tool.getStdout(), INFO_ROW)",
        "public void testWithOneTableSpecified()",
        'invokeNodetool("tablehistograms", "system.local")',
        'invokeNodetool("tablehistograms", "system", "local")',
        "public void testWithMoreThanOneTableSpecified()",
        "tablehistograms requires <keyspace> <table> or <keyspace.table> format argument",
    ),
    COLUMN_FAMILY_METRIC_TEST: (
        "public void testEstimatedColumnCountHistogramAndEstimatedRowSizeHistogram()",
        "store.metric.estimatedColumnCountHistogram.getValue()",
        "store.metric.estimatedPartitionSizeHistogram.getValue()",
    ),
    ESTIMATED_HISTOGRAM_TEST: (
        "public void testPercentile()",
        "histogram.percentile(0.99)",
    ),
    DECAYING_HISTOGRAM_TEST: (
        "public void testPercentile()",
        "toSnapshot.apply(histogram).getValue(0.99)",
    ),
}

DOC_REQUIRED_TOKENS = (
    MATRIX_DOC,
    CHECKER_DOC,
    "check-nodetool-tablehistograms-drift.py",
    TABLE_HISTOGRAMS,
    NODE_TOOL,
    NODEPROBE,
    TABLE_METRICS,
    CASSANDRA_METRICS_REGISTRY,
    TABLE_HISTOGRAMS_TEST,
    COLUMN_FAMILY_METRIC_TEST,
    ESTIMATED_HISTOGRAM_TEST,
    DECAYING_HISTOGRAM_TEST,
    "nodetool tablehistograms",
    "TableHistograms",
    "getColumnFamilyMetric",
    "EstimatedHistogram",
    "JmxHistogramMBean",
    "JmxTimerMBean",
    "tablehistograms_existing_test_baseline",
) + SCENARIO_IDS + EXPECTED_PERCENTILES + EXPECTED_COLUMNS + EXPECTED_METRICS


@dataclass(frozen=True)
class CheckResult:
    name: str
    source: str
    ok: bool
    detail: str = ""


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def source_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.extend(CheckResult(f"source token {token}", path, token in text) for token in tokens)

    tablehistograms = read(TABLE_HISTOGRAMS)
    checks.extend(
        [
            CheckResult("percentile labels match baseline", TABLE_HISTOGRAMS, all(f'"{label}"' in tablehistograms for label in EXPECTED_PERCENTILES)),
            CheckResult("metric names match baseline", TABLE_HISTOGRAMS, all(f'"{metric}"' in tablehistograms for metric in EXPECTED_METRICS)),
            CheckResult("output columns match baseline", TABLE_HISTOGRAMS, all(f'"{column}"' in tablehistograms for column in EXPECTED_COLUMNS)),
            CheckResult(
                "estimated histogram before percentile calculation",
                TABLE_HISTOGRAMS,
                tablehistograms.index("EstimatedHistogram partitionSizeHist = new EstimatedHistogram(estimatedPartitionSize);")
                < tablehistograms.index("partitionSizeHist.percentile(offsetPercentiles[i])")
                < tablehistograms.index("estimatedRowSizePercentiles[5] = partitionSizeHist.min();"),
            ),
        ]
    )

    nodeprobe = read(NODEPROBE)
    object_name_index = nodeprobe.index('new ObjectName(String.format("org.apache.cassandra.metrics:type=%s,keyspace=%s,scope=%s,name=%s", type, ks, cf, metricName))')
    switch_index = nodeprobe.index("switch(metricName)", object_name_index)
    checks.append(
        CheckResult(
            "table metric ObjectName precedes metric type switch",
            NODEPROBE,
            object_name_index
            < switch_index
            < nodeprobe.index('case "ReadLatency":', switch_index)
            < nodeprobe.index("CassandraMetricsRegistry.JmxTimerMBean.class", switch_index),
        )
    )

    table_metrics = read(TABLE_METRICS)
    checks.append(
        CheckResult(
            "TableMetrics defines estimated gauges before latency metrics",
            TABLE_METRICS,
            table_metrics.index('estimatedPartitionSizeHistogram = createTableGauge("EstimatedPartitionSizeHistogram"')
            < table_metrics.index('sstablesPerReadHistogram = createTableHistogram("SSTablesPerReadHistogram"')
            < table_metrics.index('readLatency = createLatencyMetrics("Read"'),
        )
    )
    return checks


def doc_checks() -> list[CheckResult]:
    matrix = read(MATRIX_DOC)
    checker = read(CHECKER_DOC)
    operations = read(OPERATIONS_DOC)
    obs_mapping = read(OBS_MAPPING_DOC)
    readme = read(README_DOC)
    source_map = read(SOURCE_MAP_DOC)
    all_docs = "\n".join((matrix, checker, operations, obs_mapping, readme, source_map))
    matrix_and_checker = matrix + "\n" + checker

    checks = [
        CheckResult(f"scenario documented {scenario}", f"{MATRIX_DOC} / {CHECKER_DOC}", documented(scenario, matrix_and_checker))
        for scenario in SCENARIO_IDS
    ]
    checks.extend(CheckResult(f"doc token {token}", "research docs", token in all_docs) for token in DOC_REQUIRED_TOKENS)
    checks.extend(
        [
            CheckResult("README references matrix", README_DOC, MATRIX_DOC.split("/", 1)[1] in readme),
            CheckResult("README references checker", README_DOC, CHECKER_DOC.split("/", 1)[1] in readme and "check-nodetool-tablehistograms-drift.py" in readme),
            CheckResult("source-map references matrix", SOURCE_MAP_DOC, MATRIX_DOC in source_map),
            CheckResult("source-map references checker", SOURCE_MAP_DOC, "research/tools/check-nodetool-tablehistograms-drift.py" in source_map),
            CheckResult("operations docs mention tablehistograms", OPERATIONS_DOC, "tablehistograms" in operations and "TableHistograms" in operations),
            CheckResult("observability mapping mentions tablehistograms", OBS_MAPPING_DOC, "TableHistograms" in obs_mapping and "tablehistograms" in obs_mapping),
        ]
    )
    return checks


def check() -> tuple[dict[str, object], bool]:
    sources = source_checks()
    docs = doc_checks()
    result = {
        "scenario_ids": list(SCENARIO_IDS),
        "expected_percentiles": list(EXPECTED_PERCENTILES),
        "expected_columns": list(EXPECTED_COLUMNS),
        "expected_metrics": list(EXPECTED_METRICS),
        "source_files": sorted(SOURCE_TOKEN_CHECKS),
        "matrix_doc": MATRIX_DOC,
        "checker_doc": CHECKER_DOC,
        "source_checks": [entry.__dict__ for entry in sources],
        "doc_checks": [entry.__dict__ for entry in docs],
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check nodetool tablehistograms source/doc coverage.")
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
            print(f"OK nodetool tablehistograms checks passed ({len(result['scenario_ids'])} scenarios)")
        else:
            print("Nodetool tablehistograms checks failed.", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
