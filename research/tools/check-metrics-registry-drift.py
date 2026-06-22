#!/usr/bin/env python3
#
# Source-only drift check for metrics registry/export research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

CASSANDRA_METRICS_REGISTRY = "src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java"
DEFAULT_NAME_FACTORY = "src/java/org/apache/cassandra/metrics/DefaultNameFactory.java"
METRIC_NAME_FACTORY = "src/java/org/apache/cassandra/metrics/MetricNameFactory.java"
TABLE_METRICS = "src/java/org/apache/cassandra/metrics/TableMetrics.java"
KEYSPACE_METRICS = "src/java/org/apache/cassandra/metrics/KeyspaceMetrics.java"
CLIENT_REQUESTS_METRICS_HOLDER = "src/java/org/apache/cassandra/metrics/ClientRequestsMetricsHolder.java"
CLIENT_REQUEST_METRICS = "src/java/org/apache/cassandra/metrics/ClientRequestMetrics.java"
CLIENT_RANGE_REQUEST_METRICS = "src/java/org/apache/cassandra/metrics/ClientRangeRequestMetrics.java"
THREAD_POOL_METRICS = "src/java/org/apache/cassandra/metrics/ThreadPoolMetrics.java"
CACHE_METRICS = "src/java/org/apache/cassandra/metrics/CacheMetrics.java"
COMMITLOG_METRICS = "src/java/org/apache/cassandra/metrics/CommitLogMetrics.java"
STORAGE_METRICS = "src/java/org/apache/cassandra/metrics/StorageMetrics.java"
COMPACTION_METRICS = "src/java/org/apache/cassandra/metrics/CompactionMetrics.java"
STREAMING_METRICS = "src/java/org/apache/cassandra/metrics/StreamingMetrics.java"
MESSAGING_METRICS = "src/java/org/apache/cassandra/metrics/MessagingMetrics.java"
CASSANDRA_DAEMON = "src/java/org/apache/cassandra/service/CassandraDaemon.java"
NODE_PROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
TABLE_STATS = "src/java/org/apache/cassandra/tools/nodetool/TableStats.java"
TABLE_STATS_HOLDER = "src/java/org/apache/cassandra/tools/nodetool/stats/TableStatsHolder.java"
COMPACTION_STATS = "src/java/org/apache/cassandra/tools/nodetool/CompactionStats.java"

SYSTEM_VIEWS_KEYSPACE = "src/java/org/apache/cassandra/db/virtual/SystemViewsKeyspace.java"
TABLE_METRIC_TABLES = "src/java/org/apache/cassandra/db/virtual/TableMetricTables.java"
CQL_METRICS_TABLE = "src/java/org/apache/cassandra/db/virtual/CQLMetricsTable.java"
BATCH_METRICS_TABLE = "src/java/org/apache/cassandra/db/virtual/BatchMetricsTable.java"
THREAD_POOLS_TABLE = "src/java/org/apache/cassandra/db/virtual/ThreadPoolsTable.java"
CACHES_TABLE = "src/java/org/apache/cassandra/db/virtual/CachesTable.java"

CASSANDRA_METRICS_REGISTRY_TEST = "test/unit/org/apache/cassandra/metrics/CassandraMetricsRegistryTest.java"
TABLE_METRICS_TEST = "test/unit/org/apache/cassandra/metrics/TableMetricsTest.java"
KEYSPACE_METRICS_TEST = "test/unit/org/apache/cassandra/metrics/KeyspaceMetricsTest.java"
CLIENT_REQUEST_METRICS_TEST = "test/unit/org/apache/cassandra/metrics/ClientRequestMetricsTest.java"
THREAD_POOL_METRICS_TEST = "test/unit/org/apache/cassandra/metrics/ThreadPoolMetricsTest.java"
CACHE_METRICS_TEST = "test/unit/org/apache/cassandra/metrics/CacheMetricsTest.java"
CQL_METRICS_TABLE_TEST = "test/unit/org/apache/cassandra/db/virtual/CQLMetricsTableTest.java"
BATCH_METRICS_TABLE_TEST = "test/unit/org/apache/cassandra/db/virtual/BatchMetricsTableTest.java"
TABLE_METRIC_TEST = "test/distributed/org/apache/cassandra/distributed/test/metric/TableMetricTest.java"

TARGET_DOCS = (
    "research/module-operations-observability.md",
    "research/module-observability-internals.md",
    "research/module-observability-mapping.md",
    "research/module-metrics-registry-export-matrix.md",
    "research/module-metrics-registry-drift-checker.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "metrics_registry_dropwizard_jmx_bridge",
    "metrics_name_objectname_contract",
    "metrics_table_keyspace_lifecycle",
    "metrics_client_request_scope",
    "metrics_threadpool_cache_virtual_tables",
    "metrics_cql_batch_virtual_tables",
    "metrics_nodeprobe_nodetool_consumers",
    "metrics_jvm_logback_bridge",
    "metrics_global_storage_compaction_streaming",
    "metrics_external_dashboard_gap",
)

SOURCE_TOKEN_CHECKS = {
    CASSANDRA_METRICS_REGISTRY: (
        "public static final CassandraMetricsRegistry Metrics = new CassandraMetricsRegistry();",
        "public final static TimeUnit DEFAULT_TIMER_UNIT = TimeUnit.MICROSECONDS;",
        "public Counter counter(MetricName name)",
        "registerMBean(counter, name.getMBeanName());",
        "public Meter meter(MetricName name, boolean gaugeCompatible)",
        "registerMBean(meter, name.getMBeanName(), gaugeCompatible);",
        "new ClearableHistogram(new DecayingEstimatedHistogramReservoir(considerZeroes))",
        "new SnapshottingTimer(CassandraMetricsRegistry.createReservoir(durationUnit))",
        "public static SnapshottingReservoir createReservoir(TimeUnit durationUnit)",
        "public Collection<ThreadPoolMetrics> allThreadPoolMetrics()",
        "public Optional<ThreadPoolMetrics> getThreadPoolMetrics(String poolName)",
        "ThreadPoolMetrics register(ThreadPoolMetrics metrics)",
        "void remove(ThreadPoolMetrics metrics)",
        "else if (metric instanceof Timer)",
        "else if (metric instanceof Metered)",
        "new JmxMeterGaugeCompatible((Metered) metric, name, TimeUnit.SECONDS);",
        "mBeanServer.registerMBean(mbean, name, MBeanWrapper.OnException.LOG);",
        "public interface JmxHistogramMBean extends MetricMBean",
        "long[] getRecentValues();",
        "public interface JmxTimerMBean extends JmxMeterMBean",
        "public static class MetricName implements Comparable<MetricName>",
        "public static String chooseType(String type, Class<?> klass)",
    ),
    DEFAULT_NAME_FACTORY: (
        'public static final String GROUP_NAME = "org.apache.cassandra.metrics";',
        "return new CassandraMetricsRegistry.MetricName(GROUP_NAME, type, metricName, scope, createDefaultMBeanName(type, metricName, scope));",
        'nameBuilder.append(":type=");',
        'nameBuilder.append(",scope=");',
        'nameBuilder.append(",name=");',
    ),
    METRIC_NAME_FACTORY: (
        "public interface MetricNameFactory",
        "CassandraMetricsRegistry.MetricName createMetricName(String metricName);",
    ),
    TABLE_METRICS: (
        "private static final ConcurrentMap<String, Set<Metric>> ALL_TABLE_METRICS = Maps.newConcurrentMap();",
        'private static final MetricNameFactory GLOBAL_FACTORY = new AllTableMetricNameFactory("Table");',
        'private static final MetricNameFactory GLOBAL_ALIAS_FACTORY = new AllTableMetricNameFactory("ColumnFamily");',
        "factory = new TableMetricNameFactory(cfs, \"Table\");",
        "aliasFactory = new TableMetricNameFactory(cfs, \"ColumnFamily\");",
        "readLatency = createLatencyMetrics(\"Read\", cfs.keyspace.metric.readLatency, GLOBAL_READ_LATENCY);",
        "writeLatency = createLatencyMetrics(\"Write\", cfs.keyspace.metric.writeLatency, GLOBAL_WRITE_LATENCY);",
        "rangeLatency = createLatencyMetrics(\"Range\", cfs.keyspace.metric.rangeLatency, GLOBAL_RANGE_LATENCY);",
        "public void release()",
        "protected Counter createTableCounter(final String name, final String alias)",
        "Metrics.register(GLOBAL_FACTORY.createMetricName(name),",
        "static class TableMetricNameFactory implements MetricNameFactory",
        "static class AllTableMetricNameFactory implements MetricNameFactory",
        "public interface ReleasableMetric",
    ),
    KEYSPACE_METRICS: (
        "private Set<ReleasableMetric> allMetrics = Sets.newHashSet();",
        "factory = new KeyspaceMetricNameFactory(ks);",
        "memtableColumnsCount = createKeyspaceGauge(\"MemtableColumnsCount\"",
        "unreplicatedLiveDiskSpaceUsed = createKeyspaceGauge(\"UnreplicatedLiveDiskSpaceUsed\"",
        "metric -> metric.liveDiskSpaceUsed.getCount() / keyspace.getReplicationStrategy().getReplicationFactor().fullReplicas",
        "readLatency = createLatencyMetrics(\"Read\");",
        "writeLatency = createLatencyMetrics(\"Write\");",
        "rangeLatency = createLatencyMetrics(\"Range\");",
        "public void release()",
        "private Gauge<Long> createKeyspaceGauge(String name, final ToLongFunction<TableMetrics> extractor)",
        "static class KeyspaceMetricNameFactory implements MetricNameFactory",
    ),
    CLIENT_REQUESTS_METRICS_HOLDER: (
        "public static final ClientRequestMetrics readMetrics = new ClientRequestMetrics(\"Read\");",
        "public static final ClientWriteRequestMetrics writeMetrics = new ClientWriteRequestMetrics(\"Write\");",
        "public static final CASClientWriteRequestMetrics casWriteMetrics = new CASClientWriteRequestMetrics(\"CASWrite\");",
        "public static final CASClientRequestMetrics casReadMetrics = new CASClientRequestMetrics(\"CASRead\");",
        "public static final ViewWriteMetrics viewWriteMetrics = new ViewWriteMetrics(\"ViewWrite\");",
        "public static final Map<ConsistencyLevel, ClientRequestMetrics> readMetricsMap = new EnumMap<>(ConsistencyLevel.class);",
        "readMetricsMap.put(level, new ClientRequestMetrics(\"Read-\" + level.name()));",
        "writeMetricsMap.put(level, new ClientWriteRequestMetrics(\"Write-\" + level.name()));",
    ),
    CLIENT_REQUEST_METRICS: (
        "public final Meter timeouts;",
        "public final Meter unavailables;",
        "public final Meter failures;",
        "public final Meter aborts;",
        "public final Meter localRequests;",
        "public final Meter remoteRequests;",
        "public void markAbort(Throwable cause)",
        "tombstoneAborts.mark();",
        "readSizeAborts.mark();",
        "Metrics.remove(factory.createMetricName(\"RemoteRequests\"));",
    ),
    CLIENT_RANGE_REQUEST_METRICS: (
        "public class ClientRangeRequestMetrics extends ClientRequestMetrics",
        "public final Histogram roundTrips;",
        "roundTrips = Metrics.histogram(factory.createMetricName(\"RoundTripsPerReadHistogram\"), false);",
    ),
    THREAD_POOL_METRICS: (
        'public static final String ACTIVE_TASKS = "ActiveTasks";',
        'public static final String PENDING_TASKS = "PendingTasks";',
        'public static final String CURRENTLY_BLOCKED_TASKS = "CurrentlyBlockedTasks";',
        'public static final String TOTAL_BLOCKED_TASKS = "TotalBlockedTasks";',
        "public ThreadPoolMetrics register()",
        "Metrics.register(makeMetricName(path, poolName, ACTIVE_TASKS), activeTasks);",
        "return Metrics.register(this);",
        "public void release()",
        'format("org.apache.cassandra.metrics:type=ThreadPools,path=%s,scope=%s,name=%s"',
    ),
    CACHE_METRICS: (
        "public final Gauge<Long> capacity;",
        "public final Gauge<Long> size;",
        "public final Gauge<Integer> entries;",
        "public final Meter hits;",
        "public final Meter misses;",
        "public final Meter requests;",
        "public final Gauge<Double> hitRate;",
        "capacity = Metrics.register(factory.createMetricName(\"Capacity\"), cache::capacity);",
        "requests = Metrics.meter(factory.createMetricName(\"Requests\"));",
        "private static RatioGauge ratioGauge(DoubleSupplier numeratorSupplier, DoubleSupplier denominatorSupplier)",
    ),
    COMMITLOG_METRICS: (
        'public static final MetricNameFactory factory = new DefaultNameFactory("CommitLog");',
        "waitingOnSegmentAllocation = Metrics.timer(factory.createMetricName(\"WaitingOnSegmentAllocation\"));",
        "waitingOnCommit = Metrics.timer(factory.createMetricName(\"WaitingOnCommit\"));",
        "oversizedMutations = Metrics.meter(factory.createMetricName(\"OverSizedMutations\"));",
        "totalCommitLogSize = Metrics.register(factory.createMetricName(\"TotalCommitLogSize\"), new Gauge<Long>()",
    ),
    STORAGE_METRICS: (
        'private static final MetricNameFactory factory = new DefaultNameFactory("Storage");',
        "public static final Counter load = Metrics.counter(factory.createMetricName(\"Load\"));",
        "public static final Counter uncaughtExceptions = Metrics.counter(factory.createMetricName(\"Exceptions\"));",
        "public static final Counter totalHints = Metrics.counter(factory.createMetricName(\"TotalHints\"));",
        "return Metrics.register(factory.createMetricName(name),",
    ),
    COMPACTION_METRICS: (
        'public static final MetricNameFactory factory = new DefaultNameFactory("Compaction");',
        "pendingTasks = Metrics.register(factory.createMetricName(\"PendingTasks\"), new Gauge<Integer>()",
        "completedTasks = Metrics.register(factory.createMetricName(\"CompletedTasks\"), new Gauge<Long>()",
        "totalCompactionsCompleted = Metrics.meter(factory.createMetricName(\"TotalCompactionsCompleted\"));",
        "bytesCompacted = Metrics.counter(factory.createMetricName(\"BytesCompacted\"));",
        "compactionsAborted = Metrics.counter(factory.createMetricName(\"CompactionsAborted\"));",
    ),
    STREAMING_METRICS: (
        "public static final Counter activeStreamsOutbound = Metrics.counter(DefaultNameFactory.createMetricName(TYPE_NAME, \"ActiveOutboundStreams\", null));",
        "public static final Counter totalIncomingBytes = Metrics.counter(DefaultNameFactory.createMetricName(TYPE_NAME, \"TotalIncomingBytes\", null));",
        "public static final Counter totalOutgoingBytes = Metrics.counter(DefaultNameFactory.createMetricName(TYPE_NAME, \"TotalOutgoingBytes\", null));",
        "MetricNameFactory factory = new DefaultNameFactory(\"Streaming\", peer.toString().replace(':', '.'));",
        "entireSSTablesStreamedIn = Metrics.counter(factory.createMetricName(\"EntireSSTablesStreamedIn\"));",
    ),
    MESSAGING_METRICS: (
        'private static final MetricNameFactory factory = new DefaultNameFactory("Messaging");',
        "public final EnumMap<Verb, Timer> internalLatency;",
        "internalLatency.put(verb, Metrics.timer(factory.createMetricName(verb + \"-WaitLatency\")));",
        "public void recordSelfDroppedMessage(Verb verb)",
        "public void recordInternodeDroppedMessage(Verb verb, long timeElapsed, TimeUnit timeUnit)",
        "public int resetAndConsumeDroppedErrors(Consumer<String> messageConsumer)",
    ),
    CASSANDRA_DAEMON: (
        'SharedMetricRegistries.getOrCreate("logback-metrics").addListener(new MetricRegistryListener.Base()',
        "public void onMeterAdded(String metricName, Meter meter)",
        "ObjectName name = DefaultNameFactory.createMetricName(appenderName, metric, null).getMBeanName();",
        "CassandraMetricsRegistry.Metrics.registerMBean(meter, name);",
    ),
    NODE_PROBE: (
        "public Object getCacheMetric(String cacheType, String metricName)",
        'new ObjectName("org.apache.cassandra.metrics:type=Cache,scope=" + cacheType + ",name=" + metricName)',
        "private static Multimap<String, String> getJmxThreadPools(MBeanServerConnection mbeanServerConn)",
        'new ObjectName("org.apache.cassandra.metrics:type=ThreadPools,*")',
        "public Object getThreadPoolMetric(String pathName, String poolName, String metricName)",
        'String name = String.format("org.apache.cassandra.metrics:type=ThreadPools,path=%s,scope=%s,name=%s"',
        "public Object getColumnFamilyMetric(String ks, String cf, String metricName)",
        'String.format("org.apache.cassandra.metrics:type=%s,keyspace=%s,scope=%s,name=%s", type, ks, cf, metricName)',
        'String.format("org.apache.cassandra.metrics:type=Keyspace,keyspace=%s,name=%s", ks, metricName)',
        'String.format("org.apache.cassandra.metrics:type=Table,name=%s", metricName)',
        "public CassandraMetricsRegistry.JmxTimerMBean getProxyMetric(String scope)",
        'new ObjectName("org.apache.cassandra.metrics:type=ClientRequest,scope=" + scope + ",name=Latency")',
        'new ObjectName("org.apache.cassandra.metrics:name=" + verb + "-WaitLatency,type=Messaging")',
        'new ObjectName("org.apache.cassandra.metrics:type=Storage,name=" + metricName)',
    ),
    TABLE_STATS: (
        '@Command(name = "tablestats"',
        "new TableStatsHolder(probe, humanReadable, ignore, tableNames, sortKey, top, locationCheck);",
    ),
    TABLE_STATS_HOLDER: (
        "public class TableStatsHolder implements StatsHolder",
        "probe.getColumnFamilyMetric(keyspaceName, tableName, \"LiveDiskSpaceUsed\")",
        "probe.getColumnFamilyMetric(keyspaceName, tableName, \"TotalDiskSpaceUsed\")",
        "probe.getColumnFamilyMetric(keyspaceName, tableName, \"ReadLatency\")",
        "probe.getColumnFamilyMetric(keyspaceName, tableName, \"WriteLatency\")",
        "probe.getColumnFamilyMetric(keyspaceName, tableName, \"PendingFlushes\")",
    ),
    COMPACTION_STATS: (
        '@Command(name = "compactionstats"',
        "CassandraMetricsRegistry.JmxMeterMBean totalCompactionsCompletedMetrics =",
        "(CassandraMetricsRegistry.JmxMeterMBean) probe.getCompactionMetric(\"TotalCompactionsCompleted\");",
        "(CassandraMetricsRegistry.JmxCounterMBean) probe.getCompactionMetric(\"BytesCompacted\");",
        "(CassandraMetricsRegistry.JmxCounterMBean) probe.getCompactionMetric(\"CompactionsAborted\");",
    ),
    SYSTEM_VIEWS_KEYSPACE: (
        ".add(new ThreadPoolsTable(VIRTUAL_VIEWS))",
        ".addAll(TableMetricTables.getAll(VIRTUAL_VIEWS))",
        ".add(new CQLMetricsTable(VIRTUAL_VIEWS))",
        ".add(new BatchMetricsTable(VIRTUAL_VIEWS))",
        ".addAll(CIDRFilteringMetricsTable.getAll(VIRTUAL_VIEWS))",
    ),
    TABLE_METRIC_TABLES: (
        "public static Collection<VirtualTable> getAll(String name)",
        'new LatencyTableMetric(name, "local_read_latency", t -> t.readLatency.latency)',
        'new LatencyTableMetric(name, "coordinator_write_latency", t -> t.coordinatorWriteLatency)',
        'new HistogramTableMetric(name, "tombstones_per_read", t -> t.tombstoneScannedHistogram.cf)',
        'new StorageTableMetric(name, "disk_usage", (TableMetrics t) -> t.totalDiskSpaceUsed)',
        "value *= NS_TO_MS;",
        "Math.ceil(value * BYTES_TO_MIB)",
        "for (ColumnFamilyStore cfs : ColumnFamilyStore.all())",
        "if (metric instanceof Counting)",
        "if (metric instanceof Gauge)",
    ),
    CQL_METRICS_TABLE: (
        'public static final String TABLE_NAME = "cql_metrics";',
        'public static final String PREPARED_STATEMENTS_COUNT = "prepared_statements_count";',
        "addRow(result, PREPARED_STATEMENTS_EXECUTED, cqlMetrics.preparedStatementsExecuted.getCount());",
        "addRow(result, REGULAR_STATEMENTS_EXECUTED, cqlMetrics.regularStatementsExecuted.getCount());",
    ),
    BATCH_METRICS_TABLE: (
        'super(TableMetadata.builder(keyspace, "batch_metrics")',
        'private static final String PARTITIONS_PER_LOGGED_BATCH = "partitions_per_logged_batch";',
        "BatchMetrics metrics = BatchStatement.metrics;",
        "addRow(result, PARTITIONS_PER_COUNTER_BATCH, metrics.partitionsPerCounterBatch.getSnapshot());",
    ),
    THREAD_POOLS_TABLE: (
        'super(TableMetadata.builder(keyspace, "thread_pools")',
        "Metrics.getThreadPoolMetrics(poolName)",
        "Metrics.allThreadPoolMetrics()",
        ".column(BLOCKED_TASKS, metrics.currentBlocked.getCount())",
        ".column(BLOCKED_TASKS_ALL_TIME, metrics.totalBlocked.getCount());",
    ),
    CACHES_TABLE: (
        'super(TableMetadata.builder(keyspace, "caches")',
        'addRow(result, "chunks", ChunkCache.instance.metrics);',
        'addRow(result, "counters", CacheService.instance.counterCache.getMetrics());',
        'addRow(result, "keys", CacheService.instance.keyCache.getMetrics());',
        'addRow(result, "rows", CacheService.instance.rowCache.getMetrics());',
        ".column(HIT_RATIO, metrics.hitRate.getValue())",
    ),
    CASSANDRA_METRICS_REGISTRY_TEST: (
        "public void testChooseType()",
        "public void testMetricName()",
        "public void testJvmMetricsRegistration()",
        "public void testDeltaBaseCase()",
        "public void testTimer()",
        'new String[]{"jvm.buffers","jvm.gc","jvm.memory"}',
    ),
    TABLE_METRICS_TEST: (
        "public void testRegularStatementsExecuted()",
        "public void testCounterStatement()",
        "public void testMetricsCleanupOnDrop()",
        "public void testViewMetricsCleanupOnDrop()",
        "assertEquals(metrics.get().collect(Collectors.joining(\",\")), 0, metrics.get().count());",
    ),
    KEYSPACE_METRICS_TEST: (
        "public void testMetricsCleanupOnDrop()",
        "CREATE KEYSPACE %s WITH replication",
        "DROP KEYSPACE %s;",
    ),
    CLIENT_REQUEST_METRICS_TEST: (
        "public void testWriteStatement()",
        "public void testPaxosStatement()",
        "public void testBatchStatement()",
        "public void testReadStatement()",
        "public void testRangeStatement()",
        "public void testRangeRead()",
        "RangeCommandIterator.rangeMetrics.roundTrips",
    ),
    THREAD_POOL_METRICS_TEST: (
        "public void testJMXEnabledThreadPoolMetricsWithNoBlockedThread()",
        "public void testJMXEnabledThreadPoolMetricsWithBlockedThread()",
        "public void testSEPExecutorMetrics()",
        "spinAssertEquals(2L, metrics.totalBlocked::getCount);",
    ),
    CACHE_METRICS_TEST: (
        "public void testCacheMetrics()",
        "assertEquals(expectation.hits, actual.hits.getCount());",
        "assertEquals(expectation.requests(), actual.requests.getCount());",
        "assertEquals(expectation.hitRate(), actual.hitRate.getValue(), 0.001d);",
    ),
    CQL_METRICS_TABLE_TEST: (
        "public void testUsingPrepareStmts()",
        "public void testUsingInjectedValues()",
        "assertEquals(5, rowCount.get());",
        "queryAndValidateMetrics(QueryProcessor.metrics);",
    ),
    BATCH_METRICS_TABLE_TEST: (
        "public void testSelectAll()",
        'executeNet(format("SELECT * FROM %s.batch_metrics", KS_NAME))',
        "assertEquals(3, rowCount.get());",
    ),
    TABLE_METRIC_TEST: (
        "public void systemTables() throws IOException",
        "public void userTables() throws IOException",
        "assertTableMetricsExist(i, KEYSPACE, \"tbl\")",
        "assertTableMetricsDoesNotExist(i, KEYSPACE, \"tbl\")",
        'return String.format("org.apache.cassandra.metrics:type=Keyspace,keyspace=%s,name=%s", keyspace, name);',
        'return String.format("org.apache.cassandra.metrics:type=Table,keyspace=%s,scope=%s,name=%s", keyspace, table, name);',
    ),
}

DOC_REQUIRED_TOKENS = (
    "research/tools/check-metrics-registry-drift.py",
    "research/module-metrics-registry-export-matrix.md",
    "research/module-metrics-registry-drift-checker.md",
    "CassandraMetricsRegistry",
    "DefaultNameFactory",
    "MetricNameFactory",
    "TableMetrics",
    "KeyspaceMetrics",
    "ClientRequestsMetricsHolder",
    "ClientRequestMetrics",
    "ThreadPoolMetrics",
    "CacheMetrics",
    "TableMetricTables",
    "CQLMetricsTable",
    "BatchMetricsTable",
    "NodeProbe",
    "Grafana",
    "Prometheus",
    "Alertmanager",
    "metrics_external_dashboard_gap",
)

EXTERNAL_DASHBOARD_FILE_MARKERS = (
    "grafana",
    "prometheus",
    "alertmanager",
    "dashboard",
    "jmx-exporter",
    "jmx_exporter",
    "metrics-reporter",
)

CONFIG_SUFFIXES = {".yml", ".yaml", ".json", ".toml", ".conf", ".properties"}


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

    external_config_hits = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {".git", "build", "research"} for part in path.parts):
            continue
        lower_name = path.name.lower()
        relative = str(path.relative_to(REPO_ROOT))
        if any(marker in lower_name for marker in EXTERNAL_DASHBOARD_FILE_MARKERS):
            external_config_hits.append(relative)
            continue
        if path.suffix.lower() in CONFIG_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            if any(marker in text for marker in EXTERNAL_DASHBOARD_FILE_MARKERS):
                external_config_hits.append(relative)

    checks.append(Check(
        "gap still open: no source-owned external metrics dashboard/exporter/alert config",
        "repository config/dashboard files",
        not external_config_hits,
    ))
    return checks


def doc_checks() -> list[Check]:
    docs = {path: read(path) for path in TARGET_DOCS}
    combined = "\n".join(docs.values())
    checks = [Check(f"target doc exists {path}", path, bool(text.strip())) for path, text in docs.items()]
    checks.extend(Check(f"doc token {token}", "research", token in combined) for token in DOC_REQUIRED_TOKENS)

    matrix = docs["research/module-metrics-registry-export-matrix.md"]
    drift_doc = docs["research/module-metrics-registry-drift-checker.md"]
    for scenario in SCENARIO_IDS:
        checks.append(Check(f"scenario coverage {scenario}", "research", scenario in matrix and scenario in drift_doc))

    return checks


def run_checks() -> list[Check]:
    return source_checks() + doc_checks()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check metrics registry/export research drift.")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args()

    checks = run_checks()
    failures = [check for check in checks if not check.ok]

    if args.json:
        print(json.dumps(
            {
                "ok": not failures,
                "checks": [check.__dict__ for check in checks],
                "failures": [check.__dict__ for check in failures],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ))
    elif failures:
        print("FAIL metrics registry/export drift check")
        for failure in failures:
            print(f"- {failure.name}: {failure.path}")
    else:
        print(f"OK metrics registry/export drift check: {len(checks)} checks")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
