#!/usr/bin/env python3
#
# Source-only drift check for range read storage-engine coverage research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

PARTITION_RANGE_READ_COMMAND = "src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java"
DATA_RANGE = "src/java/org/apache/cassandra/db/DataRange.java"
PARTITION_RANGE_QUERY_PAGER = "src/java/org/apache/cassandra/service/pager/PartitionRangeQueryPager.java"
RANGE_COMMANDS = "src/java/org/apache/cassandra/service/reads/range/RangeCommands.java"
RANGE_COMMAND_ITERATOR = "src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java"
REPLICA_PLAN_ITERATOR = "src/java/org/apache/cassandra/service/reads/range/ReplicaPlanIterator.java"
REPLICA_PLAN_MERGER = "src/java/org/apache/cassandra/service/reads/range/ReplicaPlanMerger.java"
READ_COMMAND = "src/java/org/apache/cassandra/db/ReadCommand.java"
COLUMN_FAMILY_STORE = "src/java/org/apache/cassandra/db/ColumnFamilyStore.java"
BIG_TABLE_READER = "src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java"
BTI_TABLE_READER = "src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java"
TRIE_MEMTABLE = "src/java/org/apache/cassandra/db/memtable/TrieMemtable.java"
SKIP_LIST_MEMTABLE = "src/java/org/apache/cassandra/db/memtable/SkipListMemtable.java"
SHARDED_SKIP_LIST_MEMTABLE = "src/java/org/apache/cassandra/db/memtable/ShardedSkipListMemtable.java"
TABLE_METRICS = "src/java/org/apache/cassandra/metrics/TableMetrics.java"
CLIENT_RANGE_REQUEST_METRICS = "src/java/org/apache/cassandra/metrics/ClientRangeRequestMetrics.java"
TABLE_METRIC_TABLES = "src/java/org/apache/cassandra/db/virtual/TableMetricTables.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
CASSANDRA_RELEVANT_PROPERTIES = "src/java/org/apache/cassandra/config/CassandraRelevantProperties.java"
STORAGE_PROXY = "src/java/org/apache/cassandra/service/StorageProxy.java"
RANGE_COMMAND_ITERATOR_TEST = "test/unit/org/apache/cassandra/service/reads/range/RangeCommandIteratorTest.java"
PARTITION_RANGE_READ_TEST = "test/unit/org/apache/cassandra/db/PartitionRangeReadTest.java"
CLIENT_REQUEST_METRICS_TEST = "test/unit/org/apache/cassandra/metrics/ClientRequestMetricsTest.java"
SSTABLES_ITERATED_TEST = "test/unit/org/apache/cassandra/cql3/validation/miscellaneous/SSTablesIteratedTest.java"

TARGET_DOCS = (
    "research/module-range-read-storage-engine-matrix.md",
    "research/module-range-read-storage-drift-checker.md",
    "research/module-read-path.md",
    "research/flow-range-read.md",
    "research/module-storage-engine.md",
    "research/module-local-read-merge-cache-deep-dive.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "range_storage_data_range_contract",
    "range_storage_paging_boundary",
    "range_storage_subrange_state_reset",
    "range_storage_replica_plan_split_merge",
    "range_storage_dynamic_concurrency",
    "range_storage_local_memtable_sstable_merge",
    "range_storage_row_cache_filter",
    "range_storage_repaired_tracking_overread",
    "range_storage_sstable_reader_format_boundary",
    "range_storage_metrics_observability",
    "range_storage_tests_coverage",
)

SOURCE_TOKEN_CHECKS = {
    PARTITION_RANGE_READ_COMMAND: (
        "protected final Slices requestedSlices;",
        "this.requestedSlices = dataRange.clusteringIndexFilter.getSlices(metadata());",
        "public PartitionRangeReadCommand forSubRange",
        "isRangeContinuation ? limits() : limits().withoutState()",
        "cfs.select(View.selectLive(dataRange().keyRange()))",
        "memtable.partitionIterator(columnFilter(), dataRange(), readCountUpdater)",
        "sstable.partitionIterator(columnFilter(), dataRange(), readCountUpdater)",
        "UnfilteredPartitionIterators.mergeLazily(finalizedIterators)",
        "return checkCacheFilter",
        "cfs.metric.updateSSTableIteratedInRangeRead(finalSelectedSSTables)",
        "CachedPartition cached = cfs.getRawCachedPartition(dk);",
        "cfs.isFilterFullyCoveredBy(filter,",
        "return Verb.RANGE_REQ;",
    ),
    DATA_RANGE: (
        "protected final AbstractBounds<PartitionPosition> keyRange;",
        "protected final ClusteringIndexFilter clusteringIndexFilter;",
        "public DataRange forPaging",
        "public DataRange forSubRange",
        "return key.equals(startKey())",
        "? clusteringIndexFilter.forPaging(comparator, lastReturned, inclusive)",
        "return range.left.equals(keyRange().left)",
        "? new Paging(range, clusteringIndexFilter, comparator, lastReturned, inclusive)",
        ": new DataRange(range, clusteringIndexFilter);",
    ),
    PARTITION_RANGE_QUERY_PAGER: (
        "private volatile DecoratedKey lastReturnedKey;",
        "private volatile PagingState.RowMark lastReturnedRow;",
        "protected PartitionRangeReadQuery nextPageReadQuery(int pageSize)",
        "fullRange.forPaging(bounds",
        "query.limits().forPaging(pageSize, lastReturnedKey.getKey(), remainingInPartition())",
        "fullRange.forSubRange(bounds)",
        "query.limits().forPaging(pageSize)",
    ),
    RANGE_COMMANDS: (
        "private static final double CONCURRENT_SUBREQUESTS_MARGIN = 0.10;",
        "MAX_CONCURRENT_RANGE_REQUESTS",
        "CassandraRelevantProperties.MAX_CONCURRENT_RANGE_REQUESTS.getInt",
        "return command.limits().filter(command.postReconciliationProcessing(rangeCommands),",
        "new ScanAllRangesCommandIterator",
        "estimateResultsPerRange(command, keyspace)",
        "resultsPerRange -= resultsPerRange * CONCURRENT_SUBREQUESTS_MARGIN;",
        "ReplicaPlanMerger mergedReplicaPlans = new ReplicaPlanMerger",
    ),
    REPLICA_PLAN_ITERATOR: (
        "getRestrictedRanges",
        "ReplicaPlans.forRangeRead",
        "TokenMetadata.ringIterator",
        "Token upperBoundToken = ringIter.next();",
        "PartitionPosition upperBound = upperBoundToken.maxKeyBound();",
        "remainder.split(upperBound)",
    ),
    REPLICA_PLAN_MERGER: (
        "ReplicaPlans.maybeMerge",
        "current.range().right.isMinimum()",
    ),
    RANGE_COMMAND_ITERATOR: (
        "public static final ClientRangeRequestMetrics rangeMetrics = new ClientRangeRequestMetrics(\"RangeSlice\");",
        "concurrencyFactor = computeConcurrencyFactor",
        "static int computeConcurrencyFactor",
        "PartitionRangeReadCommand rangeCommand = command.forSubRange(replicaPlan.range(), isFirst);",
        "DatabaseDescriptor.getRepairedDataTrackingForRangeReadsEnabled()",
        "Stage.READ.execute(new StorageProxy.LocalReadRunnable",
        "ReadCommand command = replica.isFull() ? rangeCommand : rangeCommand.copyAsTransientQuery(replica);",
        "MessagingService.instance().sendWithCallback",
        "PartitionIterator sendNextRequests()",
        "rangesQueried += replicaPlan.vnodeCount();",
        "batchesRequested++;",
        "StorageProxy.concatAndBlockOnRepair",
        "rangeMetrics.addNano(latency);",
        "rangeMetrics.roundTrips.update(batchesRequested);",
        "metric.coordinatorScanLatency.update(latency, TimeUnit.NANOSECONDS);",
    ),
    READ_COMMAND: (
        "public UnfilteredPartitionIterator executeLocally",
        "(null == searcher) ? queryStorage(cfs, executionController) : searcher.search(executionController)",
        "iterator = withMetricsRecording(iterator, cfs.metric, startTimeNanos);",
        "InputCollector<UnfilteredPartitionIterator> iteratorsForRange",
        "UnfilteredPartitionIterator repaired = UnfilteredPartitionIterators.merge",
        "return repairedDataInfo.withRepairedDataInfo(repaired);",
        "return new InputCollector<>(view, controller, merge, Function.identity());",
        "List<T> finalizeIterators",
        "repairedDataInfo.prepare",
        "repairedDataInfo.finalize",
    ),
    COLUMN_FAMILY_STORE: (
        "public boolean isFilterFullyCoveredBy",
        "public ViewFragment select",
        "return new ViewFragment(sstables, view.getAllMemtables());",
        "public CachedPartition getRawCachedPartition",
        "public static class ViewFragment",
    ),
    BIG_TABLE_READER: (
        "public ISSTableScanner partitionIterator(ColumnFilter columns, DataRange dataRange, SSTableReadsListener listener)",
        "return BigTableScanner.getScanner(this, columns, dataRange, listener);",
    ),
    BTI_TABLE_READER: (
        "public UnfilteredPartitionIterator partitionIterator(ColumnFilter columnFilter, DataRange dataRange, SSTableReadsListener listener)",
        "return BtiTableScanner.getScanner(this, columnFilter, dataRange, listener);",
    ),
    TRIE_MEMTABLE: (
        "public MemtableUnfilteredPartitionIterator partitionIterator(final ColumnFilter columnFilter,",
    ),
    SKIP_LIST_MEMTABLE: (
        "public MemtableUnfilteredPartitionIterator partitionIterator(final ColumnFilter columnFilter,",
    ),
    SHARDED_SKIP_LIST_MEMTABLE: (
        "public MemtableUnfilteredPartitionIterator partitionIterator(final ColumnFilter columnFilter,",
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
    CONFIG: (
        "public volatile DurationSpec.LongMillisecondsBound range_request_timeout",
        "public volatile boolean repaired_data_tracking_for_range_reads_enabled = false;",
        "public volatile boolean denylist_range_reads_enabled = true;",
    ),
    DATABASE_DESCRIPTOR: (
        "getRangeRpcTimeout",
        "getRepairedDataTrackingForRangeReadsEnabled",
        "getDenylistRangeReadsEnabled",
    ),
    CASSANDRA_RELEVANT_PROPERTIES: (
        "MAX_CONCURRENT_RANGE_REQUESTS(\"cassandra.max_concurrent_range_requests\")",
    ),
    STORAGE_PROXY: (
        "public static PartitionIterator getRangeSlice",
        "DatabaseDescriptor.getDenylistRangeReadsEnabled()",
        "partitionDenylist.getDeniedKeysInRangeCount",
        "RangeCommands.partitions(command, consistencyLevel, requestTime);",
    ),
    RANGE_COMMAND_ITERATOR_TEST: (
        "testRangeCountWithRangeMerge",
        "testRangeQueried",
        "testComputeConcurrencyFactor",
    ),
    PARTITION_RANGE_READ_TEST: (
        "testInclusiveBounds",
        "testLimits",
        "testRangeSliceInclusionExclusion",
    ),
    CLIENT_REQUEST_METRICS_TEST: (
        "testRangeRead",
        "RangeCommandIterator.rangeMetrics.roundTrips",
    ),
    SSTABLES_ITERATED_TEST: (
        "executeAndCheckRangeQuery",
        "((ClearableHistogram) cfs.metric.sstablesPerRangeReadHistogram.cf).clear()",
    ),
}

DOC_REQUIRED_TOKENS = (
    "research/tools/check-range-read-storage-drift.py",
    "research/module-range-read-storage-engine-matrix.md",
    "research/module-range-read-storage-drift-checker.md",
    "PartitionRangeReadCommand",
    "DataRange",
    "PartitionRangeQueryPager",
    "RangeCommands",
    "ReplicaPlanIterator",
    "ReplicaPlanMerger",
    "RangeCommandIterator",
    "ReadCommand.InputCollector",
    "ColumnFamilyStore.ViewFragment",
    "BigTableReader",
    "BtiTableReader",
    "SkipList",
    "ShardedSkipList",
    "Trie memtable",
    "range_request_timeout",
    "cassandra.max_concurrent_range_requests",
    "repaired_data_tracking_for_range_reads_enabled",
    "denylist_range_reads_enabled",
    "rangeLatency",
    "coordinatorScanLatency",
    "SSTablesPerRangeReadHistogram",
    "RoundTripsPerReadHistogram",
    "local_scan_latency",
    "coordinator_scan_latency",
    "RangeCommandIterator.rangeMetrics.roundTrips",
    "RangeCommandIteratorTest",
    "PartitionRangeReadTest",
    "ClientRequestMetricsTest",
    "SSTablesIteratedTest",
    "testRangeCountWithRangeMerge",
    "testRangeQueried",
    "testComputeConcurrencyFactor",
    "testInclusiveBounds",
    "testLimits",
    "testRangeSliceInclusionExclusion",
    "testRangeRead",
    "executeAndCheckRangeQuery",
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

    matrix = docs["research/module-range-read-storage-engine-matrix.md"]
    drift_doc = docs["research/module-range-read-storage-drift-checker.md"]
    for scenario in SCENARIO_IDS:
        checks.append(Check(f"scenario coverage {scenario}", TARGET_DOCS[0], scenario in matrix and scenario in drift_doc))

    return checks


def run_checks() -> list[Check]:
    return source_checks() + doc_checks()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check range read storage research drift.")
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
            print("FAIL range read storage drift check")
            for failure in failures:
                print(f"- {failure.name} ({failure.source})")
        else:
            print(f"OK range read storage drift check: {len(checks)} checks")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
