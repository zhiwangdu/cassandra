#!/usr/bin/env python3
#
# Source-only drift check for Cache/Index/MV coverage research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

STORAGE_ATTACHED_INDEX_SEARCHER = "src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexSearcher.java"
STORAGE_ATTACHED_INDEX_QUERY_PLAN = "src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexQueryPlan.java"
VECTOR_TOPK_PROCESSOR = "src/java/org/apache/cassandra/index/sai/plan/VectorTopKProcessor.java"
OPERATION = "src/java/org/apache/cassandra/index/sai/plan/Operation.java"
QUERY_CONTROLLER = "src/java/org/apache/cassandra/index/sai/plan/QueryController.java"
DISK_ANN = "src/java/org/apache/cassandra/index/sai/disk/v1/vector/DiskAnn.java"
VECTOR_INDEX_SEGMENT_SEARCHER = "src/java/org/apache/cassandra/index/sai/disk/v1/segment/VectorIndexSegmentSearcher.java"
VECTOR_MEMORY_INDEX = "src/java/org/apache/cassandra/index/sai/memory/VectorMemoryIndex.java"
ROWID_TO_PRIMARYKEY_WITH_SCORE = "src/java/org/apache/cassandra/index/sai/disk/v1/vector/RowIdToPrimaryKeyWithScoreIterator.java"
MERGE_PRIMARYKEY_WITH_SCORE = "src/java/org/apache/cassandra/index/sai/utils/MergePrimaryKeyWithScoreIterator.java"
SSTABLE_IMPORTER = "src/java/org/apache/cassandra/db/SSTableImporter.java"
IMPORT_CMD = "src/java/org/apache/cassandra/tools/nodetool/Import.java"
INDEX = "src/java/org/apache/cassandra/index/Index.java"
SECONDARY_INDEX_MANAGER = "src/java/org/apache/cassandra/index/SecondaryIndexManager.java"
STORAGE_ATTACHED_INDEX_GROUP = "src/java/org/apache/cassandra/index/sai/StorageAttachedIndexGroup.java"
CASSANDRA_STREAM_RECEIVER = "src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java"
STREAM_OPERATION = "src/java/org/apache/cassandra/streaming/StreamOperation.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
BIG_TABLE_READER = "src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java"
BIG_FORMAT = "src/java/org/apache/cassandra/io/sstable/format/big/BigFormat.java"
BTI_TABLE_READER = "src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java"
BTI_FORMAT = "src/java/org/apache/cassandra/io/sstable/format/bti/BtiFormat.java"
TRIE_INDEX_ENTRY = "src/java/org/apache/cassandra/io/sstable/format/bti/TrieIndexEntry.java"

VECTOR_DISTRIBUTED_TEST = "test/distributed/org/apache/cassandra/distributed/test/sai/VectorDistributedTest.java"
VECTOR_VALIDATION_TEST = "test/distributed/org/apache/cassandra/distributed/test/sai/VectorValidationTest.java"
VECTOR_INVALID_QUERY_TEST = "test/unit/org/apache/cassandra/index/sai/cql/VectorInvalidQueryTest.java"
VECTOR_LOCAL_TEST = "test/unit/org/apache/cassandra/index/sai/cql/VectorLocalTest.java"
VECTOR_UPDATE_DELETE_TEST = "test/unit/org/apache/cassandra/index/sai/cql/VectorUpdateDeleteTest.java"
IMPORT_INDEXED_SSTABLES_TEST = "test/distributed/org/apache/cassandra/distributed/test/sai/ImportIndexedSSTablesTest.java"
INDEX_STREAMING_FAILURE_TEST = "test/distributed/org/apache/cassandra/distributed/test/sai/IndexStreamingFailureTest.java"
CASSANDRA_STREAM_RECEIVER_TEST = "test/unit/org/apache/cassandra/db/streaming/CassandraStreamReceiverTest.java"
SSTABLE_READER_TEST = "test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java"
TOMBSTONES_WITH_INDEXED_SSTABLE_TEST = "test/unit/org/apache/cassandra/cql3/TombstonesWithIndexedSSTableTest.java"
BTI_LOADING_BUILDER_TEST = "test/unit/org/apache/cassandra/io/sstable/format/bti/LoadingBuilderTest.java"
STORAGE_COMPATIBILITY_MODE_TEST = "test/unit/org/apache/cassandra/utils/StorageCompatibilityModeTest.java"

TARGET_DOCS = (
    "research/module-cache-index-view-vector-import-repair.md",
    "research/module-cache-index-view-coverage-drift-checker.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "cache_index_sai_vector_ann_baseline",
    "cache_index_sai_vector_corruption_gap",
    "cache_index_sai_import_validation_build_baseline",
    "cache_index_sai_import_require_components_gap",
    "cache_index_sai_streaming_failure_baseline",
    "cache_index_mv_repair_write_path_baseline",
    "cache_index_mv_repair_correctness_gap",
    "cache_index_big_bti_key_cache_boundary",
    "cache_index_big_bti_mixed_version_gap",
    "cache_index_existing_tests_baseline",
)

SOURCE_TOKEN_CHECKS = {
    STORAGE_ATTACHED_INDEX_SEARCHER: (
        "if (!command.isTopK())",
        "try (QueryViewBuilder.QueryView queryView = buildAnnQueryView())",
        "ScoreOrderedResultRetriever result = new ScoreOrderedResultRetriever(executionController, queryView);",
        "return (UnfilteredPartitionIterator) new VectorTopKProcessor(command).takeTopKThenSortByPrimaryKey(result);",
        "private QueryViewBuilder.QueryView buildAnnQueryView()",
        "this.scoredPrimaryKeyIterator = Operation.buildIteratorForOrder(queryController, queryExpressionView);",
    ),
    STORAGE_ATTACHED_INDEX_QUERY_PLAN: (
        "private final boolean isTopK;",
        "this.isTopK = indexes.stream().anyMatch(i -> i instanceof StorageAttachedIndex && ((StorageAttachedIndex) i).termType().isVector());",
        "return partitions -> (PartitionIterator) new VectorTopKProcessor(command).consumeSortByScoreAndTakeTopK(partitions);",
    ),
    VECTOR_TOPK_PROCESSOR: (
        "consumeSortByScoreAndTakeTopK",
        "takeTopKThenSortByPrimaryKey",
        "PriorityQueue<Triple<PartitionInfo, Row, Float>> topK",
        "Comparator.comparing(Triple::getRight)",
    ),
    OPERATION: (
        "static CloseableIterator<PrimaryKeyWithScore> buildIteratorForOrder(QueryController controller, QueryViewBuilder.QueryExpressionView view)",
        "return controller.getTopKRows(view);",
        "return controller.getTopKRows(iterator, view);",
    ),
    QUERY_CONTROLLER: (
        "public CloseableIterator<PrimaryKeyWithScore> getTopKRows(QueryViewBuilder.QueryExpressionView queryExpressionView)",
        "memtableIndex.orderBy(queryContext, queryExpressionView.expression, mergeRange)",
        "sstableIndex.orderBy(queryExpressionView.expression, mergeRange, queryContext)",
        "public CloseableIterator<PrimaryKeyWithScore> getTopKRows(KeyRangeIterator source, QueryViewBuilder.QueryExpressionView queryExpressionView)",
        "memtableIndex.orderResultsBy(queryContext, sourceKeys, queryExpressionView.expression)",
        "sstableIndex.orderResultsBy(queryContext, sourceKeys, queryExpressionView.expression)",
        "new MergePrimaryKeyWithScoreIterator(intermediateResults)",
    ),
    DISK_ANN: (
        "private final CachingGraphIndex graph;",
        "private final CompressedVectors compressedVectors;",
        "new OnDiskGraphIndex<>",
        "CompressedVectors.load(reader, reader.getFilePointer())",
        "public CloseableIterator<RowIdWithScore> search(float[] queryVector, int topK, int limit, Bits acceptBits, IntConsumer nodesVisitedConsumer)",
        "OnHeapGraph.validateIndexable(queryVector, similarityFunction);",
        "new NodeScoreToRowIdWithScoreIterator(nodeScoreIterator, ordinalsMap.getRowIdsView())",
    ),
    VECTOR_INDEX_SEGMENT_SEARCHER: (
        "private CloseableIterator<RowIdWithScore> searchInternal(AbstractBounds<PartitionPosition> keyRange, float[] queryVector, int limit, int topK) throws IOException",
        "orderByBruteForce(queryVector, segmentOrdinalPairs, limit, topK)",
        "graph.search(queryVector, topK, limit, bits, nodesVisitedConsumer);",
        "if (graph.getCompressedVectors() != null && segmentOrdinalPairs.size() > topK)",
        "return orderByBruteForceTwoPass(graph.getCompressedVectors(), queryVector, segmentOrdinalPairs, limit, topK);",
        "private CloseableIterator<PrimaryKeyWithScore> toScoreSortedIterator(CloseableIterator<RowIdWithScore> rowIdIterator) throws IOException",
        "new RowIdToPrimaryKeyWithScoreIterator(column, primaryKeyMapFactory, rowIdIterator, metadata.rowIdOffset);",
    ),
    VECTOR_MEMORY_INDEX: (
        "private final OnHeapGraph<PrimaryKey> graph;",
        "graph.add(value, primaryKey, OnHeapGraph.InvalidVectorBehavior.FAIL);",
        "graph.search(qv, queryContext.limit(), bits);",
        "maxBruteForceRows",
    ),
    ROWID_TO_PRIMARYKEY_WITH_SCORE: (
        "public class RowIdToPrimaryKeyWithScoreIterator extends AbstractIterator<PrimaryKeyWithScore>",
        "RowIdWithScore rowIdWithScore = scoredRowIdIterator.next();",
        "return rowIdWithScore.toPrimaryKeyWithScore(column, sstableId, primaryKeyMap, segmentRowIdOffset);",
    ),
    MERGE_PRIMARYKEY_WITH_SCORE: (
        "public class MergePrimaryKeyWithScoreIterator extends AbstractIterator<PrimaryKeyWithScore>",
        "PriorityQueue<PeekingIterator<PrimaryKeyWithScore>> queue",
        "queue = new PriorityQueue<>(iterators.size(), (a, b) -> a.peek().compareTo(b.peek()));",
    ),
    SSTABLE_IMPORTER: (
        "if (options.verifySSTables || options.verifyTokens || options.failOnMissingIndex)",
        "if (options.failOnMissingIndex)",
        "getIndexGroup(StorageAttachedIndexGroup.GROUP_KEY)",
        "throw new IllegalStateException(String.format(\"Missing SAI index to import for SSTable %s on %s.%s\"",
        "throw new IllegalStateException(String.format(\"Missing SAI index to import for index %s on %s.%s\"",
        "if (!cfs.indexManager.validateSSTableAttachedIndexes(newSSTables, false, options.validateIndexChecksum))",
        "cfs.indexManager.buildSSTableAttachedIndexesBlocking(newSSTables);",
        "cfs.getTracker().addSSTables(newSSTables);",
    ),
    IMPORT_CMD: (
        "@Command(name = \"import\"",
        "name = {\"-ri\", \"--require-index-components\"}",
        "private boolean failOnMissingIndex = false;",
        "name = {\"-niv\", \"--no-index-validation\"}",
        "noIndexValidation = true;",
        "failOnMissingIndex, !noIndexValidation",
    ),
    INDEX: (
        "default boolean validateSSTableAttachedIndexes(Collection<SSTableReader> sstables, boolean throwOnIncomplete, boolean validateChecksum)",
    ),
    SECONDARY_INDEX_MANAGER: (
        "public boolean validateSSTableAttachedIndexes(Collection<SSTableReader> sstables, boolean throwOnIncomplete, boolean validateChecksum)",
        "complete &= group.validateSSTableAttachedIndexes(sstables, throwOnIncomplete, validateChecksum);",
        "public void buildSSTableAttachedIndexesBlocking(Collection<SSTableReader> sstables)",
        "CompactionManager.instance.submitIndexBuild(builder).addCallback(new FutureCallback<Object>()",
        "logger.warn(\"Failed to incrementally build indexes {}\", getIndexNames(groupedIndexes));",
        "FBUtilities.waitOnFutures(futures);",
    ),
    STORAGE_ATTACHED_INDEX_GROUP: (
        "public boolean validateSSTableAttachedIndexes(Collection<SSTableReader> sstables, boolean throwOnIncomplete, boolean validateChecksum)",
        "indexDescriptor.isPerSSTableIndexBuildComplete()",
        "indexDescriptor.validatePerSSTableComponents(IndexValidation.CHECKSUM, validateChecksum, true);",
        "indexDescriptor.isPerColumnIndexBuildComplete(index.identifier())",
        "indexDescriptor.validatePerIndexComponents(index.termType(), index.identifier(), IndexValidation.CHECKSUM, validateChecksum, true);",
        "Incomplete per-column index build",
        "Incomplete per-SSTable index build",
    ),
    CASSANDRA_STREAM_RECEIVER: (
        "boolean requiresWritePath(ColumnFamilyStore cfs)",
        "session.streamOperation().requiresViewBuild() && hasViews(cfs) && DatabaseDescriptor.isMaterializedViewsOnRepairEnabled()",
        "private void sendThroughWritePath(ColumnFamilyStore cfs, Collection<SSTableReader> readers)",
        "Keyspace ks = Keyspace.open(reader.getKeyspaceName());",
        "ks.apply(new Mutation(PartitionUpdate.fromIterator(throttledPartitions.next(), filter)),",
        "if (receivedEntireSSTable)",
        "cfs.indexManager.validateSSTableAttachedIndexes(readers, true, true);",
        "cfs.addSSTables(readers);",
        "if (requiresWritePath)",
        "abort();",
    ),
    STREAM_OPERATION: (
        "REPAIR(\"Repair\", true, false)",
        "private final boolean requiresViewBuild;",
        "public boolean requiresViewBuild()",
    ),
    CONFIG: (
        "public volatile boolean materialized_views_on_repair_enabled = true;",
        "public volatile boolean vector_type_enabled = true;",
        "public volatile DataStorageSpec.LongBytesBound sai_vector_term_size_warn_threshold",
    ),
    DATABASE_DESCRIPTOR: (
        "public static boolean isMaterializedViewsOnRepairEnabled()",
        "public static void setMaterializedViewsOnRepairEnabled(boolean val)",
    ),
    BIG_TABLE_READER: (
        "public class BigTableReader extends SSTableReaderWithFilter implements IndexSummarySupport<BigTableReader>,",
        "KeyCacheSupport<BigTableReader>",
        "getCachedPosition(decoratedKey, updateStats);",
        "notifySelected(SelectionReason.KEY_CACHE_HIT, listener, operator, updateStats, cachedPosition);",
        "notifySelected(SelectionReason.INDEX_ENTRY_FOUND, listener, operator, updateStats, indexEntry);",
    ),
    BIG_FORMAT: (
        "public SSTableFormat.KeyCacheValueSerializer<BigTableReader, RowIndexEntry> getKeyCacheValueSerializer()",
        "static class KeyCacheValueSerializer implements SSTableFormat.KeyCacheValueSerializer<BigTableReader, RowIndexEntry>",
        "entry.serializeForCache(output);",
    ),
    BTI_TABLE_READER: (
        "public class BtiTableReader extends SSTableReaderWithFilter",
        "reader.exactCandidate(dk);",
        "notifySelected(SelectionReason.INDEX_ENTRY_FOUND, listener, EQ, updateStats, rie);",
        "catch (IOException | IllegalArgumentException | ArrayIndexOutOfBoundsException | AssertionError e)",
    ),
    BTI_FORMAT: (
        "public SSTableFormat.KeyCacheValueSerializer<BtiTableReader, TrieIndexEntry> getKeyCacheValueSerializer()",
        "throw new AssertionError(\"BTI sstables do not use key cache\");",
    ),
    TRIE_INDEX_ENTRY: (
        "public void serializeForCache(DataOutputPlus out)",
        "throw noKeyCacheError();",
        "BTI SSTables should not use key cache",
        "BTI SSTables index entries should not be persisted in any in-memory structure",
    ),
    VECTOR_DISTRIBUTED_TEST: (
        "public void testVectorSearch()",
        "SelectStatement.TOPK_LIMIT_ERROR",
        "public void testMultiSSTablesVectorSearch()",
        "public void testPartitionRestrictedVectorSearch()",
        "public void rangeRestrictedTest()",
        "assertDescendingScore",
        "getRecall",
    ),
    VECTOR_VALIDATION_TEST: (
        "public class VectorValidationTest extends TestBaseImpl",
    ),
    VECTOR_INVALID_QUERY_TEST: (
        "public class VectorInvalidQueryTest",
    ),
    VECTOR_LOCAL_TEST: (
        "public class VectorLocalTest",
    ),
    VECTOR_UPDATE_DELETE_TEST: (
        "public class VectorUpdateDeleteTest",
        "ensureCompressedVectorsCanFlush",
    ),
    IMPORT_INDEXED_SSTABLES_TEST: (
        "public void testIndexBuildingFailureDuringImport()",
        "CompactionInterruptedException.class",
        "public void testImportBuildsSSTableIndexes()",
        "public void testValidationFailureDuringImport()",
        "CorruptIndexException.class",
        "public void testImportIncludesExistingSSTableIndexes()",
        "ColumnFamilyStore.loadNewSSTables(KEYSPACE, table)",
        "method(named(\"validateChecksum\"))",
    ),
    INDEX_STREAMING_FAILURE_TEST: (
        "public void testAvailabilityAfterFailedNonEntireFileStreaming()",
        "public void testAvailabilityAfterFailedEntireFileStreaming()",
        "DatabaseDescriptor.setStreamEntireSSTables(streamEntireSSTables)",
        "second.nodetoolResult(\"repair\", KEYSPACE).asserts().failure();",
        "SSTable should not be added to the table view",
        "second.nodetoolResult(\"repair\", KEYSPACE).asserts().success();",
        "throw new CorruptIndexException(TEST_ERROR_MESSAGE, \"Test resource\");",
    ),
    CASSANDRA_STREAM_RECEIVER_TEST: (
        "CREATE MATERIALIZED VIEW IF NOT EXISTS",
        "public void testRequiresWritePathRepair()",
        "StreamOperation.REPAIR",
        "assertTrue(receiver.requiresWritePath(cfs));",
        "DatabaseDescriptor.setMaterializedViewsOnRepairEnabled(false);",
    ),
    SSTABLE_READER_TEST: (
        "Assume.assumeTrue(KeyCacheSupport.isSupportedBy(DatabaseDescriptor.getSelectedSSTableFormat()))",
        "if (sstable instanceof BigTableReader)",
        "SelectionReason.KEY_CACHE_HIT",
        "SelectionReason.INDEX_ENTRY_FOUND",
        "GT does not engage key cache",
        "checkOpenedBtiTable",
        "components.remove(BtiFormat.Components.PARTITION_INDEX);",
    ),
    TOMBSTONES_WITH_INDEXED_SSTABLE_TEST: (
        "Assume.assumeFalse(\"BTI format does not use key cache\", BtiFormat.isSelected());",
        "BigTableReader reader = (BigTableReader) sstable;",
    ),
    BTI_LOADING_BUILDER_TEST: (
        "Assume.assumeTrue(BtiFormat.isSelected());",
        "BtiFormat.Components.PARTITION_INDEX",
    ),
    STORAGE_COMPATIBILITY_MODE_TEST: (
        "public void testBtiFormatAndStorageCompatibilityMode()",
        "SSTableFormat<?, ?> big = new BigFormat(null);",
        "SSTableFormat<?, ?> trie = new BtiFormat(null);",
        "mode.validateSstableFormat(big);",
    ),
}

DOC_REQUIRED_TOKENS = (
    "research/tools/check-cache-index-view-coverage-drift.py",
    "research/module-cache-index-view-coverage-drift-checker.md",
    "StorageAttachedIndexSearcher",
    "VectorTopKProcessor",
    "DiskAnn",
    "CompressedVectors",
    "VectorIndexSegmentSearcher",
    "SSTableImporter",
    "ImportIndexedSSTablesTest",
    "IndexStreamingFailureTest",
    "CassandraStreamReceiver",
    "CassandraStreamReceiverTest",
    "BtiFormat",
    "BigTableReader",
    "SSTableReaderTest",
    "nodetool `import -ri`",
    "repair+MV",
    "vector corrupt graph/compressed-vector",
    "Big/BTI mixed-version",
    "gap still open",
) + tuple(SOURCE_TOKEN_CHECKS.keys()) + SCENARIO_IDS


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def java_files(root: str) -> tuple[Path, ...]:
    return tuple((REPO_ROOT / root).rglob("*.java"))


def relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def files_matching(roots: tuple[str, ...], predicate) -> list[str]:
    hits: list[str] = []
    for root in roots:
        for path in java_files(root):
            text = path.read_text(encoding="utf-8")
            if predicate(text, relative(path)):
                hits.append(relative(path))
    return hits


def source_checks() -> list[Check]:
    checks: list[Check] = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(Check(f"source token contract {path}", path, all(token in text for token in tokens)))

    vector_corruption_hits = files_matching(
        ("test/unit", "test/distributed", "test/simulator"),
        lambda text, _path: (
            ("DiskAnn" in text or "CompressedVectors" in text or "VectorIndexSegmentSearcher" in text or "OnDiskGraphIndex" in text)
            and ("CorruptIndexException" in text or "corrupt" in text.lower() or "validateChecksum" in text)
        ),
    )
    checks.append(Check(
        "gap still open: no SAI vector graph/compressed-vector corruption fault test",
        "test/unit test/distributed test/simulator",
        not vector_corruption_hits,
    ))

    import_require_components_hits = files_matching(
        ("test/distributed",),
        lambda text, _path: (
            ("nodetoolResult(\"import\"" in text or ".nodetool(\"import\"" in text or "runTool(\"import\"" in text)
            and ("--require-index-components" in text or '"-ri"' in text)
        ),
    )
    checks.append(Check(
        "gap still open: no nodetool import -ri missing-component test",
        "test/unit test/distributed test/simulator",
        not import_require_components_hits,
    ))

    repair_mv_correctness_hits = files_matching(
        ("test/distributed",),
        lambda text, _path: (
            "CREATE MATERIALIZED VIEW" in text
            and ("nodetoolResult(\"repair\"" in text or ".nodetool(\"repair\"" in text or "StorageService.instance.repair" in text)
            and ("assertRows" in text or "assertThat" in text)
        ),
    )
    checks.append(Check(
        "gap still open: no repair plus materialized-view data correctness distributed test",
        "test/distributed",
        not repair_mv_correctness_hits,
    ))

    big_bti_mixed_version_hits = files_matching(
        ("test/distributed/upgrade",),
        lambda text, _path: (
            ("BtiFormat" in text or "BtiTableReader" in text or 'selected_format", "bti"' in text or "BTI" in text)
            and ("BigTableReader" in text or "KEY_CACHE_HIT" in text or "key cache" in text.lower() or "IndexSummarySupport" in text)
        ),
    )
    checks.append(Check(
        "gap still open: no Big/BTI key-cache or lookup mixed-version upgrade test",
        "test/distributed/upgrade",
        not big_bti_mixed_version_hits,
    ))

    return checks


def doc_checks() -> list[Check]:
    docs = {path: read(path) for path in TARGET_DOCS}
    combined = "\n".join(docs.values())
    checks = [Check(f"target doc exists {path}", path, bool(text.strip())) for path, text in docs.items()]
    checks.extend(Check(f"doc token {token}", "research", token in combined) for token in DOC_REQUIRED_TOKENS)

    matrix = docs["research/module-cache-index-view-vector-import-repair.md"]
    drift_doc = docs["research/module-cache-index-view-coverage-drift-checker.md"]
    for scenario in SCENARIO_IDS:
        checks.append(Check(f"scenario coverage {scenario}", "research", scenario in matrix and scenario in drift_doc))

    return checks


def run_checks() -> list[Check]:
    return source_checks() + doc_checks()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Cache/Index/MV coverage research drift.")
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
            print("FAIL Cache/Index/MV coverage drift check")
            for failure in failures:
                print(f"- {failure.name} ({failure.source})")
        else:
            print(f"OK Cache/Index/MV coverage drift check: {len(checks)} checks")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
