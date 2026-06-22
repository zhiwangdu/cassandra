#!/usr/bin/env python3
#
# Source-only drift check for Bloom filter / index summary operations research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

TABLE_PARAMS = "src/java/org/apache/cassandra/schema/TableParams.java"
COMPACTION_PARAMS = "src/java/org/apache/cassandra/schema/CompactionParams.java"
BLOOM_CALCULATIONS = "src/java/org/apache/cassandra/utils/BloomCalculations.java"
FILTER_FACTORY = "src/java/org/apache/cassandra/utils/FilterFactory.java"
FILTER_COMPONENT = "src/java/org/apache/cassandra/io/sstable/format/FilterComponent.java"
SORTED_TABLE_WRITER = "src/java/org/apache/cassandra/io/sstable/format/SortedTableWriter.java"
SSTABLE_READER_WITH_FILTER = "src/java/org/apache/cassandra/io/sstable/format/SSTableReaderWithFilter.java"
BIG_FORMAT = "src/java/org/apache/cassandra/io/sstable/format/big/BigFormat.java"
BTI_FORMAT = "src/java/org/apache/cassandra/io/sstable/format/bti/BtiFormat.java"
BIG_TABLE_READER = "src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java"
BIG_LOADING_BUILDER = "src/java/org/apache/cassandra/io/sstable/format/big/BigSSTableReaderLoadingBuilder.java"
BTI_LOADING_BUILDER = "src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReaderLoadingBuilder.java"
BLOOM_FILTER_SERIALIZER = "src/java/org/apache/cassandra/utils/BloomFilterSerializer.java"
VERSION = "src/java/org/apache/cassandra/io/sstable/format/Version.java"
BLOOM_FILTER_METRICS = "src/java/org/apache/cassandra/io/sstable/filter/BloomFilterMetrics.java"
INDEX_SUMMARY_METRICS = "src/java/org/apache/cassandra/io/sstable/indexsummary/IndexSummaryMetrics.java"
INDEX_SUMMARY_MANAGER = "src/java/org/apache/cassandra/io/sstable/indexsummary/IndexSummaryManager.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
CASSANDRA_YAML = "conf/cassandra.yaml"
NODE_PROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
TABLE_STATS_HOLDER = "src/java/org/apache/cassandra/tools/nodetool/stats/TableStatsHolder.java"

SSTABLE_READER_TEST = "test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java"
BTI_LOADING_BUILDER_TEST = "test/unit/org/apache/cassandra/io/sstable/format/bti/LoadingBuilderTest.java"
CREATE_TABLE_VALIDATION_TEST = "test/unit/org/apache/cassandra/schema/CreateTableValidationTest.java"
INDEX_SUMMARY_MANAGER_TEST = "test/unit/org/apache/cassandra/io/sstable/indexsummary/IndexSummaryManagerTest.java"
BLOOM_FILTER_TEST = "test/unit/org/apache/cassandra/utils/BloomFilterTest.java"
BLOOM_FILTER_TRACKER_TEST = "test/unit/org/apache/cassandra/io/sstable/filter/BloomFilterTrackerTest.java"
JMX_COMPATIBILITY_TEST = "test/unit/org/apache/cassandra/tools/JMXCompatibilityTest.java"
TABLE_STATS_PRINTER_TEST = "test/unit/org/apache/cassandra/tools/nodetool/stats/TableStatsPrinterTest.java"

TARGET_DOCS = (
    "research/module-bloom-filter-index-summary.md",
    "research/module-bloom-sstable-index-deep-dive.md",
    "research/module-bloom-index-summary-operations-matrix.md",
    "research/module-bloom-index-summary-operations-drift-checker.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "bloom_ops_table_option_contract",
    "bloom_ops_filter_factory_limits",
    "bloom_ops_generated_component_contract",
    "bloom_ops_sorted_writer_filter_component",
    "bloom_ops_filter_load_rebuild_boundary",
    "bloom_ops_big_open_rebuild_matrix",
    "bloom_ops_bti_open_preload_matrix",
    "bloom_ops_reader_metrics_accounting",
    "bloom_ops_metrics_observability",
    "bloom_ops_index_summary_resize_runtime",
    "bloom_ops_legacy_mixed_version_gap",
)

SOURCE_TOKEN_CHECKS = {
    TABLE_PARAMS: (
        "public final double bloomFilterFpChance;",
        "bloomFilterFpChance = builder.bloomFilterFpChance == -1",
        "? builder.compaction.defaultBloomFilterFbChance()",
        "double minBloomFilterFpChanceValue = BloomCalculations.minSupportedBloomFilterFpChance();",
        "if (bloomFilterFpChance <= minBloomFilterFpChanceValue || bloomFilterFpChance > 1)",
        "BLOOM_FILTER_FP_CHANCE",
    ),
    COMPACTION_PARAMS: (
        "double defaultBloomFilterFbChance()",
        "return klass.equals(LeveledCompactionStrategy.class) ? 0.1 : 0.01;",
    ),
    BLOOM_CALCULATIONS: (
        "public static BloomSpecification computeBloomSpec(int maxBucketsPerElement, double maxFalsePosProb)",
        "if(maxFalsePosProb >= probs[minBuckets][minK])",
        "throw new UnsupportedOperationException(String.format(\"Unable to satisfy %s with %s buckets per element\"",
        "public static int maxBucketsPerElement(long numElements)",
        "public static double minSupportedBloomFilterFpChance()",
    ),
    FILTER_FACTORY: (
        "public static final IFilter AlwaysPresent = AlwaysPresentFilter.instance;",
        "public static IFilter getFilter(long numElements, double maxFalsePosProbability)",
        "if (maxFalsePosProbability == 1.0)",
        "return FilterFactory.AlwaysPresent;",
        "long numBits = (numElements * bucketsPer) + BITSET_EXCESS;",
        "public boolean isInformative()",
        "return false;",
    ),
    FILTER_COMPONENT: (
        "final static boolean rebuildFilterOnFPChanceChange = false;",
        "final static double filterFPChanceTolerance = 0d;",
        "if (!filterFile.exists())",
        "return null;",
        "if (filterFile.length() == 0)",
        "return FilterFactory.AlwaysPresent;",
        "BloomFilterSerializer.forVersion(descriptor.version.hasOldBfFormat()).deserialize(stream);",
        "if (!shouldUseBloomFilter(desiredFPChance))",
        "else if (!components.contains(Components.FILTER) || Double.isNaN(currentFPChance))",
        "return !(Math.abs(1 - fpChance) <= filterFPChanceTolerance);",
    ),
    SORTED_TABLE_WRITER: (
        "protected final IFilter bf;",
        "bf = FilterFactory.getFilter(b.getKeyCount(), b.getTableMetadataRef().getLocal().params.bloomFilterFpChance);",
        "if (components.contains(Components.FILTER))",
        "FilterComponent.save(bf, descriptor, true);",
        "if (FilterComponent.shouldUseBloomFilter(getTableMetadataRef().getLocal().params.bloomFilterFpChance))",
        "addComponents(ImmutableSet.of(SSTableFormat.Components.FILTER));",
    ),
    BIG_FORMAT: (
        "public static final String NAME = \"big\";",
        "public static final Component.Type PRIMARY_INDEX = Component.Type.createSingleton(\"PRIMARY_INDEX\", \"Index.db\", true, BigFormat.class);",
        "public static final Component.Type SUMMARY = Component.Type.createSingleton(\"SUMMARY\", \"Summary.db\", true, BigFormat.class);",
        "private static final Set<Component> GENERATED_ON_LOAD_COMPONENTS = ImmutableSet.of(FILTER, SUMMARY);",
        "BloomFilterMetrics.instance.getGaugeProviders()",
        "IndexSummaryMetrics.instance.getGaugeProviders()",
    ),
    BTI_FORMAT: (
        "public static final Component.Type PARTITION_INDEX = Component.Type.createSingleton(\"PARTITION_INDEX\", \"Partitions.db\", true, BtiFormat.class);",
        "public static final Component.Type ROW_INDEX = Component.Type.createSingleton(\"ROW_INDEX\", \"Rows.db\", true, BtiFormat.class);",
        "private final static Set<Component> GENERATED_ON_LOAD_COMPONENTS = ImmutableSet.of(FILTER);",
        "private final Iterable<GaugeProvider<?>> gaugeProviders = BloomFilterMetrics.instance.getGaugeProviders();",
    ),
    BIG_TABLE_READER: (
        "if (searchOp == Operator.EQ)",
        "if (!isPresentInFilter((IFilter.FilterKey) key))",
        "notifySkipped(SkippingReason.BLOOM_FILTER, listener, operator, updateStats);",
        "AbstractRowIndexEntry cachedPosition = getCachedPosition(decoratedKey, updateStats);",
        "int binarySearchResult = indexSummary.binarySearch(key);",
        "int effectiveInterval = indexSummary.getEffectiveIndexIntervalAfterIndex(sampledIndex);",
        "notifySelected(SelectionReason.INDEX_ENTRY_FOUND, listener, operator, updateStats, indexEntry);",
        "notifySkipped(SkippingReason.INDEX_ENTRY_NOT_FOUND, listener, operator, updateStats);",
    ),
    BIG_LOADING_BUILDER: (
        "boolean filterNeeded = online;",
        "builder.setFilter(loadFilter(validationMetadata));",
        "boolean rebuildFilter = filterNeeded && builder.getFilter() == null;",
        "boolean rebuildSummary = summaryNeeded && builder.getIndexSummary() == null;",
        "if (builder.getComponents().contains(Components.PRIMARY_INDEX) && (rebuildFilter || rebuildSummary))",
        "buildSummaryAndBloomFilter(indexFile, builder.getSerializationHeader(), rebuildFilter, rebuildSummary",
        "if (online)",
        "summaryComponent.save(descriptor.fileFor(Components.SUMMARY), false);",
        "FilterComponent.save(filter, descriptor, false);",
        "if (builder.getFilter() == null)",
        "builder.setFilter(FilterFactory.AlwaysPresent);",
        "private Pair<IFilter, IndexSummaryComponent> buildSummaryAndBloomFilter",
        "bf = FilterFactory.getFilter(estimatedRowsNumber, tableMetadataRef.getLocal().params.bloomFilterFpChance);",
        "summaryBuilder.maybeAddEntry(key, keyReader.keyPositionForSecondaryIndex());",
        "bf.add(key);",
    ),
    BTI_LOADING_BUILDER: (
        "boolean filterNeeded = online;",
        "builder.setFilter(loadFilter(validationMetadata));",
        "boolean rebuildFilter = filterNeeded && builder.getFilter() == null;",
        "if (builder.getComponents().contains(Components.PARTITION_INDEX) && builder.getComponents().contains(Components.ROW_INDEX) && rebuildFilter)",
        "IFilter filter = buildBloomFilter(statsComponent.statsMetadata());",
        "FilterComponent.save(filter, descriptor, false);",
        "if (builder.getFilter() == null)",
        "builder.setFilter(FilterFactory.AlwaysPresent);",
        "builder.setPartitionIndex(openPartitionIndex(!builder.getFilter().isInformative()));",
        "bf = FilterFactory.getFilter(statsMetadata.totalRows, tableMetadataRef.getLocal().params.bloomFilterFpChance);",
        "bf.add(key);",
        "private PartitionIndex openPartitionIndex(boolean preload)",
        "PartitionIndex.load(indexFile, tableMetadataRef.getLocal().partitioner, preload);",
    ),
    SSTABLE_READER_WITH_FILTER: (
        "return !filter.isInformative() && getPosition(key, Operator.EQ, false) >= 0 || filter.isPresent(key);",
        "if (!(updateStats && op == SSTableReader.Operator.EQ))",
        "filterTracker.addTruePositive();",
        "case BLOOM_FILTER:",
        "filterTracker.addTrueNegative();",
        "if (op == SSTableReader.Operator.EQ)",
        "filterTracker.addFalsePositive();",
        "public long getFilterSerializedSize()",
        "public long getFilterOffHeapSize()",
    ),
    BLOOM_FILTER_SERIALIZER: (
        "public final static BloomFilterSerializer newFormatInstance = new BloomFilterSerializer(false);",
        "public final static BloomFilterSerializer oldFormatInstance = new BloomFilterSerializer(true);",
        "public static BloomFilterSerializer forVersion(boolean oldSerializationFormat)",
        "return new BloomFilter(hashes, bs);",
    ),
    VERSION: (
        "boolean hasOldBfFormat();",
    ),
    BLOOM_FILTER_METRICS: (
        "newGaugeProvider(\"BloomFilterFalsePositives\"",
        "newGaugeProvider(\"RecentBloomFilterFalsePositives\"",
        "newGaugeProvider(\"BloomFilterDiskSpaceUsed\"",
        "newGaugeProvider(\"BloomFilterOffHeapMemoryUsed\"",
        "newGaugeProvider(\"BloomFilterFalseRatio\"",
        "newGaugeProvider(\"RecentBloomFilterFalseRatio\"",
        "return (double) falsePositiveCount / (truePositiveCount + falsePositiveCount + trueNegativeCount);",
    ),
    INDEX_SUMMARY_METRICS: (
        "if (r instanceof IndexSummarySupport<?>)",
        "newGaugeProvider(\"IndexSummaryOffHeapMemoryUsed\"",
        "r -> r.getIndexSummary().getOffHeapSize()",
    ),
    INDEX_SUMMARY_MANAGER: (
        "DatabaseDescriptor.getIndexSummaryCapacityInMiB()",
        "DatabaseDescriptor.getIndexSummaryResizeIntervalInMinutes()",
        "setMemoryPoolCapacityInMB(DatabaseDescriptor.getIndexSummaryCapacityInMiB());",
        "setResizeIntervalInMinutes(DatabaseDescriptor.getIndexSummaryResizeIntervalInMinutes());",
        "future.cancel(false);",
        "if (resizeIntervalInMinutes < 0)",
        "future = null;",
        "redistributeSummaries();",
    ),
    CONFIG: (
        "public String selected_format = BigFormat.NAME;",
        "public volatile DataStorageSpec.LongMebibytesBound index_summary_capacity;",
        "public volatile DurationSpec.IntMinutesBound index_summary_resize_interval = new DurationSpec.IntMinutesBound(\"60m\");",
        "public StorageCompatibilityMode storage_compatibility_mode;",
    ),
    DATABASE_DESCRIPTOR: (
        "indexSummaryCapacityInMiB = (conf.index_summary_capacity == null)",
        "conf.index_summary_capacity = new DataStorageSpec.LongMebibytesBound(indexSummaryCapacityInMiB);",
        "selectedSSTableFormat = getAndValidateWriteFormat(sstableFormats, sstableFormatsConfig.selected_format);",
        "return conf.index_summary_resize_interval.toMinutes();",
        "conf.index_summary_resize_interval = new DurationSpec.IntMinutesBound(value);",
    ),
    CASSANDRA_YAML: (
        "index_summary_capacity:",
        "index_summary_resize_interval: 60m",
        "#  selected_format: big",
        "storage_compatibility_mode: CASSANDRA_4",
    ),
    NODE_PROBE: (
        "case \"BloomFilterDiskSpaceUsed\":",
        "case \"BloomFilterFalsePositives\":",
        "case \"BloomFilterFalseRatio\":",
        "case \"BloomFilterOffHeapMemoryUsed\":",
        "case \"IndexSummaryOffHeapMemoryUsed\":",
        "case \"RecentBloomFilterFalsePositives\":",
        "case \"RecentBloomFilterFalseRatio\":",
    ),
    TABLE_STATS_HOLDER: (
        "bloomFilterOffHeapSize = (Long) probe.getColumnFamilyMetric(keyspaceName, tableName, \"BloomFilterOffHeapMemoryUsed\");",
        "indexSummaryOffHeapSize = (Long) probe.getColumnFamilyMetric(keyspaceName, tableName, \"IndexSummaryOffHeapMemoryUsed\");",
        "statsTable.bloomFilterFalsePositives = probe.getColumnFamilyMetric(keyspaceName, tableName, \"BloomFilterFalsePositives\");",
        "statsTable.bloomFilterFalseRatio = probe.getColumnFamilyMetric(keyspaceName, tableName, \"RecentBloomFilterFalseRatio\");",
        "statsTable.bloomFilterSpaceUsed = format((Long) probe.getColumnFamilyMetric(keyspaceName, tableName, \"BloomFilterDiskSpaceUsed\"), humanReadable);",
    ),
    SSTABLE_READER_TEST: (
        "public void testGetPositionsBloomFilterStats()",
        "assertEquals(1, sstable.getFilterTracker().getTruePositiveCount());",
        "assertEquals(1, sstable.getFilterTracker().getTrueNegativeCount());",
        "assertEquals(fpCount + 2, sstable.getFilterTracker().getFalsePositiveCount());",
        "private static void checkOpenedBigTable",
        "executeInternal(format(\"ALTER TABLE \\\"%s\\\".\\\"%s\\\" WITH bloom_filter_fp_chance = 0.3\", ks, cf));",
        "check that bloomfilter/summary ARE NOT regenerated",
        "check that bloomfilter is recreated when it doesn't exist and this causes the summary to be recreated",
        "check that summary and bloomfilter is not recreated when the INDEX is missing",
        "private static void checkOpenedBtiTable",
        "check that bloomfilter is recreated when it doesn't exist",
    ),
    BTI_LOADING_BUILDER_TEST: (
        "targetClass = \"org.apache.cassandra.io.sstable.format.bti.PartitionIndex\"",
        "targetMethod = \"load(org.apache.cassandra.io.util.FileHandle, org.apache.cassandra.dht.IPartitioner, boolean)\"",
        "CREATE TABLE %s (k int PRIMARY KEY, v int) WITH bloom_filter_fp_chance = ",
        "verifyPreloadMatches(disableBloomFilter, partitionIndexFile);",
        "assertEquals(disableBloomFilter, preload.booleanValue());",
    ),
    CREATE_TABLE_VALIDATION_TEST: (
        "public void testInvalidBloomFilterFPRatio()",
        "bloom_filter_fp_chance = 0.0000001",
        "bloom_filter_fp_chance = 1.1",
        "bloom_filter_fp_chance = 0.1",
    ),
    INDEX_SUMMARY_MANAGER_TEST: (
        "public <R extends SSTableReader & IndexSummarySupport<R>> void testChangeMinIndexInterval()",
        "public void testChangeMaxIndexInterval()",
        "IndexSummaryManager.instance.redistributeSummaries();",
        "CompactionManager.instance.stopCompaction(\"INDEX_SUMMARY\")",
    ),
    BLOOM_FILTER_TEST: (
        "public void testFalsePositivesInt()",
        "public void testFalsePositivesRandom()",
        "public void testSerialize()",
        "BloomFilterTest.testSerialize(bfInvHashes, true).close();",
        "BloomFilterTest.testSerialize(bfInvHashes, false).close();",
    ),
    BLOOM_FILTER_TRACKER_TEST: (
        "public class BloomFilterTrackerTest",
        "public void testAddingFalsePositives()",
        "public void testAddingTruePositives()",
        "public void testAddingToOneLeavesTheOtherAlone()",
        "bft.addFalsePositive();",
        "bft.addTruePositive();",
    ),
    JMX_COMPATIBILITY_TEST: (
        "IndexSummary.*",
        "when BTI format is used, index summary is not used",
    ),
    TABLE_STATS_PRINTER_TEST: (
        "Bloom filter false positives:",
        "Bloom filter false ratio:",
        "Bloom filter space used:",
        "Bloom filter off heap memory used:",
    ),
}

DOC_REQUIRED_TOKENS = (
    "research/tools/check-bloom-index-summary-operations-drift.py",
    "research/module-bloom-index-summary-operations-matrix.md",
    "research/module-bloom-index-summary-operations-drift-checker.md",
    "FilterComponent",
    "FilterFactory.AlwaysPresent",
    "BigSSTableReaderLoadingBuilder",
    "BtiTableReaderLoadingBuilder",
    "SSTableReaderWithFilter",
    "BloomFilterMetrics",
    "IndexSummaryManager",
    "LoadingBuilderTest",
    "legacy/mixed-version",
)


@dataclass(frozen=True)
class Check:
    name: str
    path: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def iter_files(*roots: str) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        files.extend(path for path in base.rglob("*.java") if path.is_file())
    return files


def files_matching(roots: tuple[str, ...], predicate) -> list[str]:
    hits: list[str] = []
    for path in iter_files(*roots):
        rel = str(path.relative_to(REPO_ROOT))
        text = path.read_text(encoding="utf-8", errors="ignore")
        if predicate(text, rel):
            hits.append(rel)
    return hits


def source_checks() -> list[Check]:
    checks: list[Check] = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(Check(f"source token contract {path}", path, all(token in text for token in tokens)))

    legacy_mixed_version_hits = files_matching(
        ("test/distributed",),
        lambda text, _path: (
            ("BloomFilter" in text or "Filter.db" in text or "bloom_filter_fp_chance" in text)
            and ("Upgrade" in text or "storage_compatibility_mode" in text or "selected_format" in text)
            and ("stream" in text.lower() or "automatic_sstable_upgrade" in text or "bti" in text.lower())
        ),
    )
    checks.append(Check(
        "gap still open: no distributed old Bloom / Big-BTI mixed-version coverage",
        "test/distributed",
        not legacy_mixed_version_hits,
    ))

    legacy_fixture_hits = files_matching(
        ("test/distributed",),
        lambda text, _path: (
            ("old Bloom" in text or "oldBf" in text or "hasOldBfFormat" in text or "old BF" in text)
            and ("Filter.db" in text or "BloomFilterSerializer" in text)
        ),
    )
    checks.append(Check(
        "gap still open: no distributed legacy old Bloom fixture coverage",
        "test/distributed",
        not legacy_fixture_hits,
    ))

    return checks


def doc_checks() -> list[Check]:
    docs = {path: read(path) for path in TARGET_DOCS}
    combined = "\n".join(docs.values())
    checks = [Check(f"target doc exists {path}", path, bool(text.strip())) for path, text in docs.items()]
    checks.extend(Check(f"doc token {token}", "research", token in combined) for token in DOC_REQUIRED_TOKENS)

    matrix = docs["research/module-bloom-index-summary-operations-matrix.md"]
    drift_doc = docs["research/module-bloom-index-summary-operations-drift-checker.md"]
    for scenario in SCENARIO_IDS:
        checks.append(Check(f"scenario coverage {scenario}", "research", scenario in matrix and scenario in drift_doc))

    return checks


def run_checks() -> list[Check]:
    return source_checks() + doc_checks()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Bloom/index-summary operations research drift.")
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
        print("FAIL Bloom/index-summary operations drift check")
        for failure in failures:
            print(f"- {failure.name}: {failure.path}")
    else:
        print(f"OK Bloom/index-summary operations drift check: {len(checks)} checks")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
