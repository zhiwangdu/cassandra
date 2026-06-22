#!/usr/bin/env python3
#
# Source-only drift check for range read performance and fault-coverage research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

RANGE_COMMANDS = "src/java/org/apache/cassandra/service/reads/range/RangeCommands.java"
RANGE_COMMAND_ITERATOR = "src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java"
PARTITION_RANGE_READ_COMMAND = "src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java"
READ_COMMAND = "src/java/org/apache/cassandra/db/ReadCommand.java"
COLUMN_FAMILY_STORE = "src/java/org/apache/cassandra/db/ColumnFamilyStore.java"
STORAGE_PROXY = "src/java/org/apache/cassandra/service/StorageProxy.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
CASSANDRA_RELEVANT_PROPERTIES = "src/java/org/apache/cassandra/config/CassandraRelevantProperties.java"
CASSANDRA_YAML = "conf/cassandra.yaml"
TABLE_METRICS = "src/java/org/apache/cassandra/metrics/TableMetrics.java"
CLIENT_RANGE_REQUEST_METRICS = "src/java/org/apache/cassandra/metrics/ClientRangeRequestMetrics.java"
TABLE_METRIC_TABLES = "src/java/org/apache/cassandra/db/virtual/TableMetricTables.java"
RANGE_COMMANDS_TEST = "test/unit/org/apache/cassandra/service/reads/range/RangeCommandsTest.java"
RANGE_COMMAND_ITERATOR_TEST = "test/unit/org/apache/cassandra/service/reads/range/RangeCommandIteratorTest.java"
CLIENT_REQUEST_METRICS_TEST = "test/unit/org/apache/cassandra/metrics/ClientRequestMetricsTest.java"
SSTABLES_ITERATED_TEST = "test/unit/org/apache/cassandra/cql3/validation/miscellaneous/SSTablesIteratedTest.java"
REPAIR_DIGEST_TRACKING_TEST = "test/distributed/org/apache/cassandra/distributed/test/RepairDigestTrackingTest.java"
ROW_CACHE_TEST = "test/unit/org/apache/cassandra/db/RowCacheTest.java"
READ_REPAIR_TEST = "test/distributed/org/apache/cassandra/distributed/test/ReadRepairTest.java"
DISTRIBUTED_TEST_ROOT = "test/distributed"

TARGET_DOCS = (
    "research/module-range-read-performance-fault-matrix.md",
    "research/module-range-read-performance-drift-checker.md",
    "research/module-range-read-storage-engine-matrix.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "range_perf_initial_concurrency_estimate",
    "range_perf_max_concurrent_guardrail",
    "range_perf_dynamic_concurrency_roundtrips",
    "range_perf_remote_full_transient_contacts",
    "range_perf_repaired_tracking_overread",
    "range_perf_row_cache_substitution",
    "range_perf_sstable_overlap_density",
    "range_perf_tombstone_read_size_thresholds",
    "range_perf_denylist_rejection",
    "range_perf_existing_tests_baseline",
    "range_perf_distributed_fault_gap",
)

SOURCE_TOKEN_CHECKS = {
    RANGE_COMMANDS: (
        "private static final double CONCURRENT_SUBREQUESTS_MARGIN = 0.10;",
        "CassandraRelevantProperties.MAX_CONCURRENT_RANGE_REQUESTS.getInt",
        "FBUtilities.getAvailableProcessors() * 10",
        "int maxConcurrencyFactor = Math.min(replicaPlans.size(), MAX_CONCURRENT_RANGE_REQUESTS);",
        "float resultsPerRange = estimateResultsPerRange(command, keyspace);",
        "resultsPerRange -= resultsPerRange * CONCURRENT_SUBREQUESTS_MARGIN;",
        "Math.ceil(command.limits().count() / resultsPerRange)",
        "static float estimateResultsPerRange(PartitionRangeReadCommand command, Keyspace keyspace)",
        "Index.QueryPlan index = command.indexQueryPlan();",
        "command.limits().estimateTotalResults(cfs)",
        "index.getEstimatedResultRows();",
        "DatabaseDescriptor.getNumTokens()",
        "keyspace.getReplicationStrategy().getReplicationFactor().allReplicas",
    ),
    RANGE_COMMAND_ITERATOR: (
        "public static final ClientRangeRequestMetrics rangeMetrics = new ClientRangeRequestMetrics(\"RangeSlice\");",
        "int rangesQueried;",
        "int batchesRequested = 0;",
        "private int liveReturned;",
        "liveReturned += counter.counted();",
        "concurrencyFactor = computeConcurrencyFactor",
        "static int computeConcurrencyFactor(int totalRangeCount, int rangesQueried, int maxConcurrencyFactor, int limit, int liveReturned)",
        "if (liveReturned == 0)",
        "float rowsPerRange = (float) liveReturned / (float) rangesQueried;",
        "PartitionRangeReadCommand rangeCommand = command.forSubRange(replicaPlan.range(), isFirst);",
        "DatabaseDescriptor.getRepairedDataTrackingForRangeReadsEnabled()",
        "replicaPlan.contacts().filter(Replica::isFull).size() > 1",
        "Stage.READ.execute(new StorageProxy.LocalReadRunnable",
        "ReadCommand command = replica.isFull() ? rangeCommand : rangeCommand.copyAsTransientQuery(replica);",
        "command.createMessage(trackRepairedStatus && replica.isFull(), requestTime)",
        "MessagingService.instance().sendWithCallback",
        "rangesQueried += replicaPlan.vnodeCount();",
        "batchesRequested++;",
        "rangeMetrics.roundTrips.update(batchesRequested);",
        "metric.coordinatorScanLatency.update(latency, TimeUnit.NANOSECONDS);",
    ),
    PARTITION_RANGE_READ_COMMAND: (
        "cfs.select(View.selectLive(dataRange().keyRange()))",
        "memtable.partitionIterator(columnFilter(), dataRange(), readCountUpdater)",
        "int selectedSSTablesCnt = 0;",
        "boolean intersects = intersects(sstable);",
        "sstable.partitionIterator(columnFilter(), dataRange(), readCountUpdater)",
        "selectedSSTablesCnt++;",
        "inputCollector.finalizeIterators(cfs, nowInSec(), controller.oldestUnrepairedTombstone())",
        "UnfilteredPartitionIterators.mergeLazily(finalizedIterators)",
        "cfs.metric.updateSSTableIteratedInRangeRead(finalSelectedSSTables);",
        "private UnfilteredPartitionIterator checkCacheFilter",
        "CachedPartition cached = cfs.getRawCachedPartition(dk);",
        "cfs.isFilterFullyCoveredBy(filter,",
    ),
    READ_COMMAND: (
        "private UnfilteredPartitionIterator withMetricsRecording",
        "metric.tombstoneScannedHistogram.update(tombstones);",
        "tombstone_failure_threshold",
        "tombstone_warn_threshold",
        "private UnfilteredPartitionIterator withQuerySizeTracking",
        "throw new LocalReadSizeTooLargeException(msg);",
        "withoutPurgeableTombstones",
        "controller.oldestUnrepairedTombstone()",
        "InputCollector<UnfilteredPartitionIterator> iteratorsForRange",
        "return new InputCollector<>(view, controller, merge, Function.identity());",
        "repairedDataInfo.prepare(cfs, nowInSec, oldestUnrepairedTombstone);",
        "repairedDataInfo.finalize(postLimitAdditionalPartitions.apply(repairedIter));",
        "private boolean considerRepairedForTracking(SSTableReader sstable)",
        "repairedDataInfo.markInconclusive();",
    ),
    COLUMN_FAMILY_STORE: (
        "public boolean isFilterFullyCoveredBy",
        "cached.cachedLiveRows() < metadata().params.caching.rowsPerPartitionToCache()",
        "filter.isHeadFilter()",
        "filter.isFullyCoveredBy(cached)",
    ),
    STORAGE_PROXY: (
        "public static PartitionIterator getRangeSlice",
        "DatabaseDescriptor.getDenylistRangeReadsEnabled()",
        "partitionDenylist.getDeniedKeysInRangeCount",
        "RangeCommands.partitions(command, consistencyLevel, requestTime);",
    ),
    CONFIG: (
        "public volatile DurationSpec.LongMillisecondsBound range_request_timeout",
        "public volatile boolean read_thresholds_enabled = false;",
        "public volatile DataStorageSpec.LongBytesBound coordinator_read_size_warn_threshold = null;",
        "public volatile DataStorageSpec.LongBytesBound local_read_size_warn_threshold = null;",
        "public volatile DataStorageSpec.LongBytesBound row_index_read_size_warn_threshold = null;",
        "public volatile int tombstone_warn_threshold = 1000;",
        "public volatile int tombstone_failure_threshold = 100000;",
        "public volatile boolean repaired_data_tracking_for_range_reads_enabled = false;",
        "public volatile boolean denylist_range_reads_enabled = true;",
    ),
    DATABASE_DESCRIPTOR: (
        "getRangeRpcTimeout",
        "getTombstoneWarnThreshold",
        "getTombstoneFailureThreshold",
        "getRepairedDataTrackingForRangeReadsEnabled",
        "getReadThresholdsEnabled",
        "getLocalReadSizeWarnThreshold",
    ),
    CASSANDRA_RELEVANT_PROPERTIES: (
        "MAX_CONCURRENT_RANGE_REQUESTS(\"cassandra.max_concurrent_range_requests\")",
    ),
    CASSANDRA_YAML: (
        "range_request_timeout: 10000ms",
        "tombstone_warn_threshold: 1000",
        "tombstone_failure_threshold: 100000",
        "repaired_data_tracking_for_range_reads_enabled: false",
        "read_thresholds_enabled",
        "local_read_size_warn_threshold",
    ),
    TABLE_METRICS: (
        "public final TableHistogram sstablesPerRangeReadHistogram;",
        "public final LatencyMetrics rangeLatency;",
        "public final Timer coordinatorScanLatency;",
        "createTableHistogram(\"SSTablesPerRangeReadHistogram\"",
        "rangeLatency = createLatencyMetrics(\"Range\"",
        "coordinatorScanLatency = createTableTimer(\"CoordinatorScanLatency\");",
        "public void updateSSTableIteratedInRangeRead(int count)",
    ),
    CLIENT_RANGE_REQUEST_METRICS: (
        "public final Histogram roundTrips;",
        "RoundTripsPerReadHistogram",
    ),
    TABLE_METRIC_TABLES: (
        "\"local_scan_latency\"",
        "\"coordinator_scan_latency\"",
    ),
    RANGE_COMMANDS_TEST: (
        "properties = new WithProperties().set(MAX_CONCURRENT_RANGE_REQUESTS, MAX_CONCURRENCY_FACTOR);",
        "public void tesConcurrencyFactor()",
        "public void testEstimateResultsPerRange()",
        "setNumTokens(5);",
        "MockedIndex.estimatedResultRows = indexEstimate;",
        "RangeCommands.estimateResultsPerRange(command, keyspace)",
    ),
    RANGE_COMMAND_ITERATOR_TEST: (
        "testRangeCountWithRangeMerge",
        "testRangeQueried",
        "testComputeConcurrencyFactor",
        "assertEquals(batches, data.batchesRequested());",
        "assertEquals(vnodeCount, data.rangesQueried());",
    ),
    CLIENT_REQUEST_METRICS_TEST: (
        "public void testRangeRead()",
        "clearHistogram(RangeCommandIterator.rangeMetrics.roundTrips);",
        "RangeCommandIterator.rangeMetrics.roundTrips.getSnapshot().getMax()",
    ),
    SSTABLES_ITERATED_TEST: (
        "executeAndCheckRangeQuery",
        "cfs.metric.sstablesPerRangeReadHistogram",
        "SELECT * FROM %s WHERE TOKEN(pk) >=",
    ),
    REPAIR_DIGEST_TRACKING_TEST: (
        "testInconsistenciesFound",
        "StorageProxy.instance.enableRepairedDataTrackingForRangeReads();",
        "testRepairedReadCountNormalizationWithInitialUnderread",
        "testRepairedReadCountNormalizationWithInitialOverread",
        "SELECT * FROM \" + KS_TABLE + \" LIMIT 30",
    ),
    ROW_CACHE_TEST: (
        "public void testRowCacheRange()",
        "cachedStore.metric.rowCacheHit.getCount()",
        "cachedStore.metric.rowCacheHitOutOfRange.getCount()",
        "CacheService.instance.invalidateRowCache();",
    ),
    READ_REPAIR_TEST: (
        "testRangeSliceQueryWithTombstonesInMemory",
        "testRangeSliceQueryWithTombstonesOnDisk",
        "testGCableTombstoneResurrectionOnRangeSliceQuery",
        "SELECT * FROM %s.t LIMIT 100",
        "SELECT * FROM %s.t",
    ),
}

DOC_REQUIRED_TOKENS = (
    "research/tools/check-range-read-performance-drift.py",
    "research/module-range-read-performance-fault-matrix.md",
    "research/module-range-read-performance-drift-checker.md",
    "RangeCommands",
    "RangeCommandIterator",
    "PartitionRangeReadCommand",
    "ReadCommand",
    "ColumnFamilyStore",
    "StorageProxy",
    "RangeCommandsTest",
    "RangeCommandIteratorTest",
    "ClientRequestMetricsTest",
    "SSTablesIteratedTest",
    "RepairDigestTrackingTest",
    "RowCacheTest",
    "ReadRepairTest",
    "cassandra.max_concurrent_range_requests",
    "estimateResultsPerRange",
    "RoundTripsPerReadHistogram",
    "SSTablesPerRangeReadHistogram",
    "repaired_data_tracking_for_range_reads_enabled",
    "tombstone_warn_threshold",
    "tombstone_failure_threshold",
    "local_read_size_warn_threshold",
    "range_perf_distributed_fault_gap",
) + tuple(SOURCE_TOKEN_CHECKS.keys()) + SCENARIO_IDS


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def source_checks() -> list[Check]:
    checks: list[Check] = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        missing = [token for token in tokens if token not in text]
        checks.append(Check(f"source token contract {path}", path, not missing))
    return checks


def doc_checks() -> list[Check]:
    docs = {path: read(path) for path in TARGET_DOCS}
    combined = "\n".join(docs.values())
    checks = [
        Check(f"target doc exists {path}", path, bool(text.strip()))
        for path, text in docs.items()
    ]

    for token in DOC_REQUIRED_TOKENS:
        checks.append(Check(f"doc token {token}", "research", token in combined))

    matrix = docs["research/module-range-read-performance-fault-matrix.md"]
    drift_doc = docs["research/module-range-read-performance-drift-checker.md"]
    for scenario in SCENARIO_IDS:
        checks.append(Check(f"scenario coverage {scenario}", TARGET_DOCS[0], scenario in matrix and scenario in drift_doc))

    return checks


def distributed_gap_checks() -> list[Check]:
    root = REPO_ROOT / DISTRIBUTED_TEST_ROOT
    perf_fault_candidates: list[str] = []
    max_concurrency_candidates: list[str] = []

    for path in sorted(root.rglob("*.java")):
        text = path.read_text(encoding="utf-8")
        relative = str(path.relative_to(REPO_ROOT))

        repaired_tracking = (
            "enableRepairedDataTrackingForRangeReads" in text
            or "repaired_data_tracking_for_range_reads_enabled" in text
        )
        vnode_heavy = (
            "TokenSupplier.evenlyDistributedTokens" in text
            or "evenlyDistributedTokens(" in text
            or "\"num_tokens\"" in text
        )
        range_perf_metric_or_limit = (
            "RangeCommandIterator.rangeMetrics.roundTrips" in text
            or "RoundTripsPerReadHistogram" in text
            or "SSTablesPerRangeReadHistogram" in text
            or "sstablesPerRangeReadHistogram" in text
            or "cassandra.max_concurrent_range_requests" in text
            or "MAX_CONCURRENT_RANGE_REQUESTS" in text
        )

        if repaired_tracking and vnode_heavy and range_perf_metric_or_limit:
            perf_fault_candidates.append(relative)

        if "cassandra.max_concurrent_range_requests" in text or "MAX_CONCURRENT_RANGE_REQUESTS" in text:
            max_concurrency_candidates.append(relative)

    return [
        Check(
            "gap still open: no distributed test combines repaired range tracking, vnode-heavy planning, and range perf metrics",
            DISTRIBUTED_TEST_ROOT,
            not perf_fault_candidates,
        ),
        Check(
            "gap still open: no distributed max concurrent range request runtime test",
            DISTRIBUTED_TEST_ROOT,
            not max_concurrency_candidates,
        ),
    ]


def run_checks() -> list[Check]:
    return source_checks() + doc_checks() + distributed_gap_checks()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check range read performance/fault research drift.")
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
            indent=2,
            sort_keys=True,
        ))
    else:
        if failures:
            print("FAIL range read performance/fault drift check")
            for failure in failures:
                print(f"- {failure.name} ({failure.source})")
        else:
            print(f"OK range read performance/fault drift check: {len(checks)} checks")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
