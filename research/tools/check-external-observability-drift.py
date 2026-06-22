#!/usr/bin/env python3
#
# Source-only drift check for external observability integration research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

CASSANDRA_METRICS_REGISTRY = "src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java"
DEFAULT_NAME_FACTORY = "src/java/org/apache/cassandra/metrics/DefaultNameFactory.java"
NODE_PROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
TABLE_METRIC_TABLES = "src/java/org/apache/cassandra/db/virtual/TableMetricTables.java"
CQL_METRICS_TABLE = "src/java/org/apache/cassandra/db/virtual/CQLMetricsTable.java"
BATCH_METRICS_TABLE = "src/java/org/apache/cassandra/db/virtual/BatchMetricsTable.java"
THREAD_POOLS_TABLE = "src/java/org/apache/cassandra/db/virtual/ThreadPoolsTable.java"
CACHES_TABLE = "src/java/org/apache/cassandra/db/virtual/CachesTable.java"

LOGBACK = "conf/logback.xml"
LOGBACK_TOOLS = "conf/logback-tools.xml"
VIRTUAL_TABLE_APPENDER = "src/java/org/apache/cassandra/utils/logging/VirtualTableAppender.java"
LOG_MESSAGES_TABLE = "src/java/org/apache/cassandra/db/virtual/LogMessagesTable.java"
AUDIT_LOG_MANAGER = "src/java/org/apache/cassandra/audit/AuditLogManager.java"
FULL_QUERY_LOGGER = "src/java/org/apache/cassandra/fql/FullQueryLogger.java"
BINLOG = "src/java/org/apache/cassandra/utils/binlog/BinLog.java"
EXTERNAL_ARCHIVER = "src/java/org/apache/cassandra/utils/binlog/ExternalArchiver.java"
DELETING_ARCHIVER = "src/java/org/apache/cassandra/utils/binlog/DeletingArchiver.java"
STORAGE_SERVICE_MBEAN = "src/java/org/apache/cassandra/service/StorageServiceMBean.java"

CASSANDRA_METRICS_REGISTRY_TEST = "test/unit/org/apache/cassandra/metrics/CassandraMetricsRegistryTest.java"
TABLE_METRICS_TEST = "test/unit/org/apache/cassandra/metrics/TableMetricsTest.java"
TABLE_METRIC_TEST = "test/distributed/org/apache/cassandra/distributed/test/metric/TableMetricTest.java"
CQL_METRICS_TABLE_TEST = "test/unit/org/apache/cassandra/db/virtual/CQLMetricsTableTest.java"
BATCH_METRICS_TABLE_TEST = "test/unit/org/apache/cassandra/db/virtual/BatchMetricsTableTest.java"
LOG_MESSAGES_TABLE_TEST = "test/unit/org/apache/cassandra/db/virtual/LogMessagesTableTest.java"
VIRTUAL_TABLE_LOGS_TEST = "test/distributed/org/apache/cassandra/distributed/test/VirtualTableLogsTest.java"
AUDIT_LOGGER_TEST = "test/unit/org/apache/cassandra/audit/AuditLoggerTest.java"
FULL_QUERY_LOGGER_TEST = "test/unit/org/apache/cassandra/fql/FullQueryLoggerTest.java"

TARGET_DOCS = (
    "research/module-external-observability-integration-matrix.md",
    "research/module-external-observability-drift-checker.md",
    "research/module-metrics-registry-export-matrix.md",
    "research/module-logging-audit-fql-operations-matrix.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "external_observability_jmx_metric_contract",
    "external_observability_nodeprobe_metric_contract",
    "external_observability_virtual_metrics_contract",
    "external_observability_logback_file_contract",
    "external_observability_system_logs_contract",
    "external_observability_audit_fql_contract",
    "external_observability_binlog_retention_contract",
    "external_observability_prometheus_exporter_gap",
    "external_observability_grafana_dashboard_gap",
    "external_observability_alert_rules_gap",
    "external_observability_log_collector_gap",
    "external_observability_existing_tests_baseline",
)

SOURCE_TOKEN_CHECKS = {
    CASSANDRA_METRICS_REGISTRY: (
        "public Counter counter(MetricName name)",
        "registerMBean(counter, name.getMBeanName());",
        "public Meter meter(MetricName name, boolean gaugeCompatible)",
        "registerMBean(meter, name.getMBeanName(), gaugeCompatible);",
        "public Histogram histogram(MetricName name, boolean considerZeroes)",
        "public SnapshottingTimer timer(MetricName name, TimeUnit durationUnit)",
        "public void registerMBean(Metric metric, ObjectName name, boolean gaugeCompatible)",
        "mBeanServer.registerMBean(mbean, name, MBeanWrapper.OnException.LOG);",
        "public interface JmxCounterMBean extends MetricMBean",
        "public interface JmxMeterMBean extends MetricMBean",
        "public interface JmxTimerMBean extends JmxMeterMBean",
        "long[] getRecentValues();",
        "String getDurationUnit();",
    ),
    DEFAULT_NAME_FACTORY: (
        'public static final String GROUP_NAME = "org.apache.cassandra.metrics";',
        'nameBuilder.append(":type=");',
        'nameBuilder.append(",scope=");',
        'nameBuilder.append(",name=");',
        "return new CassandraMetricsRegistry.MetricName(GROUP_NAME, type, metricName, scope, createDefaultMBeanName(type, metricName, scope));",
    ),
    NODE_PROBE: (
        "public Object getCacheMetric(String cacheType, String metricName)",
        'new ObjectName("org.apache.cassandra.metrics:type=Cache,scope=" + cacheType + ",name=" + metricName)',
        "public Object getThreadPoolMetric(String pathName, String poolName, String metricName)",
        'String name = String.format("org.apache.cassandra.metrics:type=ThreadPools,path=%s,scope=%s,name=%s"',
        "public Object getColumnFamilyMetric(String ks, String cf, String metricName)",
        'String.format("org.apache.cassandra.metrics:type=%s,keyspace=%s,scope=%s,name=%s", type, ks, cf, metricName)',
        "public CassandraMetricsRegistry.JmxTimerMBean getProxyMetric(String scope)",
        'new ObjectName("org.apache.cassandra.metrics:type=ClientRequest,scope=" + scope + ",name=Latency")',
        "public CassandraMetricsRegistry.JmxTimerMBean getMessagingQueueWaitMetrics(String verb)",
        'new ObjectName("org.apache.cassandra.metrics:name=" + verb + "-WaitLatency,type=Messaging")',
        "public Object getCompactionMetric(String metricName)",
        'new ObjectName("org.apache.cassandra.metrics:type=Compaction,name=" + metricName)',
        "public long getStorageMetric(String metricName)",
        'new ObjectName("org.apache.cassandra.metrics:type=Storage,name=" + metricName)',
    ),
    TABLE_METRIC_TABLES: (
        "public static Collection<VirtualTable> getAll(String name)",
        'new LatencyTableMetric(name, "local_read_latency", t -> t.readLatency.latency)',
        'new StorageTableMetric(name, "disk_usage", (TableMetrics t) -> t.totalDiskSpaceUsed)',
        "if (metric instanceof Counting)",
        "else if (metric instanceof Gauge)",
        "private static TableMetadata buildMetadata(String keyspace, String table",
    ),
    CQL_METRICS_TABLE: (
        "public static final String TABLE_NAME = \"cql_metrics\";",
        "CQLMetricsTable(String keyspace, CQLMetrics cqlMetrics)",
        "super(TableMetadata.builder(keyspace, TABLE_NAME)",
        "addPartitionKeyColumn(NAME_COL, UTF8Type.instance)",
        "addRegularColumn(VALUE_COL, DoubleType.instance)",
        "QueryProcessor.metrics",
    ),
    BATCH_METRICS_TABLE: (
        'super(TableMetadata.builder(keyspace, "batch_metrics")',
        'addPartitionKeyColumn("name", UTF8Type.instance)',
        "BatchStatement.metrics",
        "partitionsPerLoggedBatch",
        "partitionsPerUnloggedBatch",
        "partitionsPerCounterBatch",
    ),
    THREAD_POOLS_TABLE: (
        'super(TableMetadata.builder(keyspace, "thread_pools")',
        "Metrics.getThreadPoolMetrics(poolName)",
        "Metrics.allThreadPoolMetrics()",
        "metrics.activeTasks.getValue()",
        "metrics.pendingTasks.getValue()",
        "metrics.currentBlocked.getCount()",
    ),
    CACHES_TABLE: (
        'super(TableMetadata.builder(keyspace, "caches")',
        "CacheService.instance",
        "rowCache",
        "counterCache",
        "keyCache",
    ),
    LOGBACK: (
        '<configuration scan="true" scanPeriod="60 seconds">',
        '<appender name="SYSTEMLOG" class="ch.qos.logback.core.rolling.RollingFileAppender">',
        '<file>${cassandra.logdir}/system.log</file>',
        '<appender name="DEBUGLOG" class="ch.qos.logback.core.rolling.RollingFileAppender">',
        '<file>${cassandra.logdir}/debug.log</file>',
        '<appender name="ASYNCDEBUGLOG" class="ch.qos.logback.classic.AsyncAppender">',
        '<appender name="STDOUT" class="ch.qos.logback.core.ConsoleAppender">',
        '<appender name="LogbackMetrics" class="com.codahale.metrics.logback.InstrumentedAppender" />',
        '<appender name="CQLLOG" class="org.apache.cassandra.utils.logging.VirtualTableAppender">',
        '<root level="INFO">',
    ),
    LOGBACK_TOOLS: (
        '<appender name="STDERR" class="ch.qos.logback.core.ConsoleAppender">',
        '<target>System.err</target>',
        '<root level="WARN">',
    ),
    VIRTUAL_TABLE_APPENDER: (
        'public static final String APPENDER_NAME = "CQLLOG";',
        "private static final Set<String> forbiddenLoggers = ImmutableSet.of(FileAuditLogger.class.getName());",
        "private final List<LoggingEvent> messageBuffer = new LinkedList<>();",
        "logs = getVirtualTable();",
        "public void flushBuffer()",
        "messageBuffer.forEach(vtable::add);",
    ),
    LOG_MESSAGES_TABLE: (
        "public static final int LOGS_VIRTUAL_TABLE_MIN_ROWS = 1000;",
        "public static final int LOGS_VIRTUAL_TABLE_DEFAULT_ROWS = 50_000;",
        "public static final int LOGS_VIRTUAL_TABLE_MAX_ROWS = 100_000;",
        'public static final String TABLE_NAME = "system_logs";',
        "addPartitionKeyColumn(TIMESTAMP_COLUMN_NAME, TimestampType.instance)",
        "addClusteringColumn(ORDER_IN_MILLISECOND_COLUMN_NAME, Int32Type.instance)",
        "public void add(LoggingEvent event)",
        "public void truncate()",
        "static int resolveBufferSize()",
    ),
    AUDIT_LOG_MANAGER: (
        "public class AuditLogManager implements QueryEvents.Listener, AuthEvents.Listener, AuditLogManagerMBean",
        'public static final String MBEAN_NAME = "org.apache.cassandra.db:type=AuditLogManager";',
        "private volatile IAuditLogger auditLogger;",
        "public void initialize()",
        "MBeanWrapper.instance.registerMBean(this, MBEAN_NAME);",
        "private IAuditLogger getAuditLogger(AuditLogOptions options) throws ConfigurationException",
        "return new BinAuditLogger(options);",
        "public synchronized void disableAuditLog()",
        "public synchronized void enable(AuditLogOptions auditLogOptions) throws ConfigurationException",
        "registerAsListener();",
        "oldLogger.stop();",
    ),
    FULL_QUERY_LOGGER: (
        "public class FullQueryLogger implements QueryEvents.Listener",
        "public static final FullQueryLogger instance = new FullQueryLogger();",
        "volatile BinLog binLog;",
        "public synchronized void enable(Path path, String rollCycle, boolean blocking, int maxQueueWeight, long maxLogSize, String archiveCommand, int maxArchiveRetries)",
        "new BinLog.Builder().path(path)",
        "QueryEvents.instance.registerListener(this);",
        "public synchronized void stop()",
        "QueryEvents.instance.unregisterListener(this);",
        "public synchronized void reset(String fullQueryLogPath)",
        "public void querySuccess(CQLStatement statement,",
        "binLog.logRecord(wrappedQuery);",
    ),
    BINLOG: (
        "public class BinLog implements Runnable",
        "private static final NoSpamLogger.NoSpamLogStatement droppedSamplesStatement",
        "Thread binLogThread = new NamedThreadFactory(\"Binary Log thread\").newThread(this);",
        "final WeightedQueue<ReleaseableWriteMarshallable> sampleQueue;",
        "private final BinLogArchiver archiver;",
        "private final boolean blocking;",
        "private static final Set<Path> currentPaths = Collections.synchronizedSet(new HashSet<>());",
        "void start()",
        "public synchronized void stop() throws InterruptedException",
        "public void logRecord(ReleaseableWriteMarshallable record)",
    ),
    EXTERNAL_ARCHIVER: (
        "public class ExternalArchiver implements BinLogArchiver",
        "archiveCommand",
        "%path",
        "maxArchiveRetries",
    ),
    DELETING_ARCHIVER: (
        "public class DeletingArchiver implements BinLogArchiver",
        "maxLogSize",
        "public synchronized void onReleased(int cycle, File file)",
        "bytesInStoreFiles > maxLogSize",
        "toDelete.delete()",
    ),
    STORAGE_SERVICE_MBEAN: (
        "public void setLoggingLevel(String classQualifier, String level) throws Exception;",
        "public Map<String,String> getLoggingLevels();",
        "public void enableAuditLog(String loggerName",
        "public void enableFullQueryLogger(String path",
        "public void resetFullQueryLogger();",
        "public void stopFullQueryLogger();",
    ),
}

TEST_TOKEN_CHECKS = {
    CASSANDRA_METRICS_REGISTRY_TEST: (
        "public void testMetricName()",
        "public void testJvmMetricsRegistration()",
        "testChooseType()",
    ),
    TABLE_METRICS_TEST: (
        "public void testMetricsCleanupOnDrop()",
        "coordinatorWriteLatency",
    ),
    TABLE_METRIC_TEST: (
        "public void systemTables() throws IOException",
        "public void userTables() throws IOException",
        "assertTableMetricsExist(i, KEYSPACE, \"tbl\")",
        "assertTableMetricsDoesNotExist(i, KEYSPACE, \"tbl\")",
    ),
    CQL_METRICS_TABLE_TEST: (
        "public void testUsingPrepareStmts() throws Throwable",
        "queryAndValidateMetrics(QueryProcessor.metrics);",
    ),
    BATCH_METRICS_TABLE_TEST: (
        "public void testSelectAll() throws Throwable",
        'executeNet(format("SELECT * FROM %s.batch_metrics", KS_NAME))',
        "assertEquals(3, rowCount.get());",
    ),
    LOG_MESSAGES_TABLE_TEST: (
        "public void testTruncate()",
        "public void testLimitedCapacity()",
        "public void testMultipleLogsInSameMillisecond()",
        "public void testResolvingBufferSize()",
        'executeNet(query("select timestamp from %s"))',
    ),
    VIRTUAL_TABLE_LOGS_TEST: (
        "public void testVTableOutput() throws Throwable",
        "public void testMultipleAppendersFailToStartNode() throws Throwable",
        'cluster.coordinator(1).executeWithResult(query("select * from %s"), ONE)',
        "logback-dtest_with_vtable_appender",
    ),
    AUDIT_LOGGER_TEST: (
        "assertEquals(1, QueryEvents.instance.listenerCount());",
        "assertEquals(1, AuthEvents.instance.listenerCount());",
        "StorageService.instance.enableFullQueryLogger(",
        "options.archive_command = \"/xyz/not/null\";",
    ),
    FULL_QUERY_LOGGER_TEST: (
        "FullQueryLogger.instance.enable(BinLogTest.tempDir()",
        "FullQueryLogger.instance.binLog.logRecord(new Query(",
        "Can't enable full query log archiving via nodetool",
        "private void logQuery(String query)",
    ),
}

DOC_REQUIRED_TOKENS = (
    "research/tools/check-external-observability-drift.py",
    "research/module-external-observability-integration-matrix.md",
    "research/module-external-observability-drift-checker.md",
    "CassandraMetricsRegistry",
    "NodeProbe",
    "TableMetricTables",
    "LogMessagesTable",
    "AuditLogManager",
    "FullQueryLogger",
    "BinLog",
    "Prometheus",
    "Grafana",
    "Alertmanager",
    "Filebeat",
    "Fluent Bit",
    "Logstash",
    "Promtail",
    "external_observability_prometheus_exporter_gap",
    "external_observability_log_collector_gap",
)

CONFIG_SUFFIXES = {
    ".conf",
    ".config",
    ".json",
    ".properties",
    ".toml",
    ".xml",
    ".yaml",
    ".yml",
}

SKIP_PARTS = {
    ".git",
    ".gradle",
    ".idea",
    "build",
    "build-shaded-dtest-jar",
    "build-test",
    "research",
    "target",
}

METRICS_FILE_MARKERS = (
    "alert_rules",
    "alert-rules",
    "alertmanager",
    "dashboard",
    "grafana",
    "jmx-exporter",
    "jmx_exporter",
    "jmx_prometheus",
    "opentelemetry",
    "otel-collector",
    "otel_collector",
    "prometheus",
)

LOG_COLLECTOR_FILE_MARKERS = (
    "filebeat",
    "fluent-bit",
    "fluentbit",
    "fluentd",
    "logstash",
    "promtail",
    "vector.toml",
    "vector.yaml",
    "vector.yml",
)

METRICS_CONTENT_MARKERS = (
    ("prometheus scrape config", ("scrape_configs:", "metrics_path:")),
    ("jmx prometheus javaagent", ("jmx_prometheus_javaagent",)),
    ("prometheus jmx exporter package", ("io.prometheus.jmx",)),
    ("grafana dashboard json", ('"panels"', '"datasource"', '"templating"')),
    ("alertmanager config", ("alertmanager", "receivers:", "route:")),
    ("prometheus alert rules", ("groups:", "alert:", "expr:")),
    ("opentelemetry collector", ("receivers:", "exporters:", "service:", "otlp")),
)

LOG_COLLECTOR_CONTENT_MARKERS = (
    ("filebeat config", ("filebeat.inputs",)),
    ("fluent bit config", ("fluent-bit", "parsers_file")),
    ("fluentd config", ("<source>", "<match", "fluentd")),
    ("logstash config", ("input {", "output {", "logstash")),
    ("promtail config", ("promtail", "scrape_configs:", "clients:")),
    ("vector agent config", ("[sources.", "[sinks.")),
    ("vector.dev config", ("vector.dev",)),
)


@dataclass(frozen=True)
class Check:
    name: str
    path: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def source_checks() -> list[Check]:
    checks: list[Check] = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(Check(f"source token contract {path}", path, all(token in text for token in tokens)))
    return checks


def test_checks() -> list[Check]:
    checks: list[Check] = []
    for path, tokens in TEST_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(Check(f"test token contract {path}", path, all(token in text for token in tokens)))
    return checks


def candidate_config_files() -> list[Path]:
    files = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        files.append(path)
    return files


def marker_content_hits(path: Path, marker_sets: tuple[tuple[str, tuple[str, ...]], ...]) -> list[str]:
    if path.suffix.lower() not in CONFIG_SUFFIXES:
        return []
    text = path.read_text(encoding="utf-8", errors="ignore").lower()
    hits = []
    for label, markers in marker_sets:
        if all(marker in text for marker in markers):
            hits.append(label)
    return hits


def external_gap_checks() -> list[Check]:
    metrics_hits = []
    log_collector_hits = []

    for path in candidate_config_files():
        relative = str(path.relative_to(REPO_ROOT))
        lower_relative = relative.lower()
        lower_name = path.name.lower()

        if any(marker in lower_relative or marker in lower_name for marker in METRICS_FILE_MARKERS):
            metrics_hits.append(relative)
        else:
            metrics_content_hits = marker_content_hits(path, METRICS_CONTENT_MARKERS)
            metrics_hits.extend(f"{relative} ({label})" for label in metrics_content_hits)

        if any(marker in lower_relative or marker in lower_name for marker in LOG_COLLECTOR_FILE_MARKERS):
            log_collector_hits.append(relative)
        else:
            collector_hits = marker_content_hits(path, LOG_COLLECTOR_CONTENT_MARKERS)
            log_collector_hits.extend(f"{relative} ({label})" for label in collector_hits)

    return [
        Check(
            "gap still open: no source-owned external metrics exporter/dashboard/alert config",
            "repository config/dashboard files",
            not metrics_hits,
        ),
        Check(
            "gap still open: no source-owned external log collector configuration",
            "repository log collector config files",
            not log_collector_hits,
        ),
    ]


def doc_checks() -> list[Check]:
    docs = {path: read(path) for path in TARGET_DOCS}
    combined = "\n".join(docs.values())
    checks = [Check(f"target doc exists {path}", path, bool(text.strip())) for path, text in docs.items()]
    checks.extend(Check(f"doc token {token}", "research", token in combined) for token in DOC_REQUIRED_TOKENS)

    matrix = docs["research/module-external-observability-integration-matrix.md"]
    drift_doc = docs["research/module-external-observability-drift-checker.md"]
    for scenario in SCENARIO_IDS:
        checks.append(Check(f"scenario coverage {scenario}", "research", scenario in matrix and scenario in drift_doc))

    return checks


def run_checks() -> list[Check]:
    return source_checks() + test_checks() + external_gap_checks() + doc_checks()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check external observability research drift.")
    parser.add_argument("--json", action="store_true", help="Emit check results as JSON.")
    args = parser.parse_args()

    checks = run_checks()
    failures = [check for check in checks if not check.ok]

    if args.json:
        print(json.dumps([check.__dict__ for check in checks], indent=2, sort_keys=True))

    if failures:
        if not args.json:
            print("FAILED external observability drift checks:", file=sys.stderr)
            for check in failures:
                print(f"- {check.name} ({check.path})", file=sys.stderr)
        return 1

    if not args.json:
        print(
            "OK external observability drift checks passed "
            f"({len(SOURCE_TOKEN_CHECKS)} source files, "
            f"{len(TEST_TOKEN_CHECKS)} test files, "
            f"{len(TARGET_DOCS)} docs, "
            f"{len(SCENARIO_IDS)} scenarios)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
