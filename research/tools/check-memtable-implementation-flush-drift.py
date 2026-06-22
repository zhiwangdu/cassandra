#!/usr/bin/env python3
#
# Source/test/doc drift check for Memtable implementation and flush research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

MEMTABLE = "src/java/org/apache/cassandra/db/memtable/Memtable.java"
ABSTRACT_MEMTABLE = "src/java/org/apache/cassandra/db/memtable/AbstractMemtable.java"
ABSTRACT_MEMTABLE_WITH_COMMITLOG = "src/java/org/apache/cassandra/db/memtable/AbstractMemtableWithCommitlog.java"
ABSTRACT_ALLOCATOR_MEMTABLE = "src/java/org/apache/cassandra/db/memtable/AbstractAllocatorMemtable.java"
SKIP_LIST_FACTORY = "src/java/org/apache/cassandra/db/memtable/SkipListMemtableFactory.java"
SKIP_LIST_MEMTABLE = "src/java/org/apache/cassandra/db/memtable/SkipListMemtable.java"
ABSTRACT_SHARDED_MEMTABLE = "src/java/org/apache/cassandra/db/memtable/AbstractShardedMemtable.java"
SHARD_BOUNDARIES = "src/java/org/apache/cassandra/db/memtable/ShardBoundaries.java"
SHARDED_SKIP_LIST_MEMTABLE = "src/java/org/apache/cassandra/db/memtable/ShardedSkipListMemtable.java"
TRIE_MEMTABLE = "src/java/org/apache/cassandra/db/memtable/TrieMemtable.java"
TRIE_MEMTABLE_METRICS_VIEW = "src/java/org/apache/cassandra/metrics/TrieMemtableMetricsView.java"
MEMTABLE_PARAMS = "src/java/org/apache/cassandra/schema/MemtableParams.java"
TABLE_PARAMS = "src/java/org/apache/cassandra/schema/TableParams.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
CASSANDRA_YAML = "conf/cassandra.yaml"
COLUMN_FAMILY_STORE = "src/java/org/apache/cassandra/db/ColumnFamilyStore.java"
FLUSHING = "src/java/org/apache/cassandra/db/memtable/Flushing.java"
MEMTABLE_POOL = "src/java/org/apache/cassandra/utils/memory/MemtablePool.java"
MEMTABLE_CLEANER_THREAD = "src/java/org/apache/cassandra/utils/memory/MemtableCleanerThread.java"

MEMTABLE_PARAMS_TEST = "test/unit/org/apache/cassandra/schema/MemtableParamsTest.java"
CREATE_TEST = "test/unit/org/apache/cassandra/cql3/validation/operations/CreateTest.java"
ALTER_TEST = "test/unit/org/apache/cassandra/cql3/validation/operations/AlterTest.java"
TEST_MEMTABLE = "test/unit/org/apache/cassandra/db/memtable/TestMemtable.java"
MEMTABLE_QUICK_TEST = "test/unit/org/apache/cassandra/db/memtable/MemtableQuickTest.java"
MEMTABLE_SIZE_TEST_BASE = "test/unit/org/apache/cassandra/db/memtable/MemtableSizeTestBase.java"
SHARDED_MEMTABLE_CONFIG_TEST = "test/unit/org/apache/cassandra/db/memtable/ShardedMemtableConfigTest.java"
TRIE_MEMTABLE_METRICS_TEST = "test/unit/org/apache/cassandra/metrics/TrieMemtableMetricsTest.java"
MEMTABLE_CLEANER_THREAD_TEST = "test/unit/org/apache/cassandra/utils/memory/MemtableCleanerThreadTest.java"
TRACKER_TEST = "test/unit/org/apache/cassandra/db/lifecycle/TrackerTest.java"
COMMITLOG_TEST = "test/unit/org/apache/cassandra/db/commitlog/CommitLogTest.java"

TARGET_DOCS = (
    "research/module-memtable-flush.md",
    "research/module-memtable-implementations.md",
    "research/module-memtable-postflush-trigger-deep-dive.md",
    "research/module-memtable-implementation-flush-matrix.md",
    "research/module-memtable-implementation-flush-drift-checker.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "memtable_factory_durability_contract",
    "memtable_config_resolution_contract",
    "memtable_skiplist_write_flush_contract",
    "memtable_sharded_skiplist_boundary_contract",
    "memtable_trie_single_writer_metrics_contract",
    "memtable_allocator_pool_cleaner_contract",
    "memtable_flush_switch_barrier_contract",
    "memtable_postflush_reclaim_contract",
    "memtable_flush_writer_disk_boundary_contract",
    "memtable_table_schema_validation_contract",
    "memtable_jmx_shard_count_contract",
    "memtable_existing_test_baseline",
    "memtable_persistent_custom_gap",
)

SOURCE_TOKEN_CHECKS = {
    MEMTABLE: (
        "public interface Memtable extends Comparable<Memtable>, UnfilteredSource, CellSourceIdentifier",
        "interface Factory",
        "default boolean writesShouldSkipCommitLog()",
        "default boolean writesAreDurable()",
        "default boolean streamToMemtable()",
        "default boolean streamFromMemtable()",
        "default TableMetrics.ReleasableMetric createMemtableMetrics(TableMetadataRef metadataRef)",
        "interface Owner",
        "Future<CommitLogPosition> signalFlushRequired(Memtable memtable, ColumnFamilyStore.FlushReason reason);",
        "Memtable getCurrentMemtable();",
        "long put(PartitionUpdate update, UpdateTransaction indexer, OpOrder.Group opGroup);",
        "FlushablePartitionSet<?> getFlushSet(PartitionPosition from, PartitionPosition to);",
        "interface FlushablePartitionSet<P extends Partition> extends Iterable<P>, SSTableWriter.SSTableSizeParameters",
        "void switchOut(OpOrder.Barrier writeBarrier, AtomicReference<CommitLogPosition> commitLogUpperBound);",
        "boolean shouldSwitch(ColumnFamilyStore.FlushReason reason);",
    ),
    ABSTRACT_MEMTABLE: (
        "public abstract class AbstractMemtable implements Memtable",
        "protected final ColumnsCollector columnsCollector;",
        "protected final StatsCollector statsCollector = new StatsCollector();",
        "public long operationCount()",
        "public LifecycleTransaction setFlushTransaction(LifecycleTransaction flushTransaction)",
        "protected abstract class AbstractFlushablePartitionSet<P extends Partition> implements FlushablePartitionSet<P>",
    ),
    ABSTRACT_MEMTABLE_WITH_COMMITLOG: (
        "public abstract class AbstractMemtableWithCommitlog extends AbstractMemtable",
        "public void discard()",
    ),
    ABSTRACT_ALLOCATOR_MEMTABLE: (
        "public abstract class AbstractAllocatorMemtable extends AbstractMemtableWithCommitlog",
        "MemtableCleaner cleaner = AbstractAllocatorMemtable::flushLargestMemtable;",
        "public static MemtablePool createMemtableAllocatorPoolInternal",
        "this.initialFactory = metadata().params.memtable.factory();",
        "scheduleFlush();",
        "public boolean shouldSwitch(ColumnFamilyStore.FlushReason reason)",
        "|| !initialFactory.equals(metadata().params.memtable.factory());",
        "private void flushIfPeriodExpired()",
        "public static Future<Boolean> flushLargestMemtable()",
    ),
    SKIP_LIST_FACTORY: (
        "public class SkipListMemtableFactory implements Memtable.Factory",
        "public static final SkipListMemtableFactory INSTANCE = new SkipListMemtableFactory();",
    ),
    SKIP_LIST_MEMTABLE: (
        "public class SkipListMemtable extends AbstractAllocatorMemtable",
        "public static final Factory FACTORY = SkipListMemtableFactory.INSTANCE;",
        "private final ConcurrentNavigableMap<PartitionPosition, AtomicBTreePartition> partitions = new ConcurrentSkipListMap<>();",
        "public long put(PartitionUpdate update, UpdateTransaction indexer, OpOrder.Group opGroup)",
        "AtomicBTreePartition previous = partitions.get(update.partitionKey());",
        "AtomicBTreePartition empty = new AtomicBTreePartition(metadata, cloneKey, allocator);",
        "public MemtableUnfilteredPartitionIterator partitionIterator(final ColumnFilter columnFilter,",
        "Map<PartitionPosition, AtomicBTreePartition> toFlush = getPartitionsSubMap(from, true, to, false);",
        "public void makeUnflushable()",
    ),
    ABSTRACT_SHARDED_MEMTABLE: (
        "public static final String SHARDS_OPTION = \"shards\";",
        "protected final ShardBoundaries boundaries;",
        "this.boundaries = owner.localRangeSplits(shardCount);",
    ),
    SHARD_BOUNDARIES: (
        "private final Token[] boundaries;",
        "public ShardBoundaries(Token[] boundaries, long ringVersion)",
        "public int getShardForKey(PartitionPosition key)",
        "return boundaries.length + 1;",
    ),
    SHARDED_SKIP_LIST_MEMTABLE: (
        "public class ShardedSkipListMemtable extends AbstractShardedMemtable",
        "public static final String LOCKING_OPTION = \"serialize_writes\";",
        "final MemtableShard[] shards;",
        "MemtableShard shard = shards[boundaries.getShardForKey(key)];",
        "public MemtableUnfilteredPartitionIterator partitionIterator(final ColumnFilter columnFilter,",
        "private final ConcurrentNavigableMap<PartitionPosition, AtomicBTreePartition> partitions = new ConcurrentSkipListMap<>();",
        "static class Locking extends ShardedSkipListMemtable",
        "synchronized (shard)",
        "public static Factory factory(Map<String, String> optionsCopy)",
        "String shardsString = optionsCopy.remove(SHARDS_OPTION);",
        "boolean isLocking = Boolean.parseBoolean(optionsCopy.remove(LOCKING_OPTION));",
    ),
    TRIE_MEMTABLE: (
        "public class TrieMemtable extends AbstractShardedMemtable",
        "private final MemtableShard[] shards;",
        "private final TrieMemtableMetricsView metrics;",
        "private static Trie<BTreePartitionData> makeMergedTrie(MemtableShard[] shards)",
        "MemtableShard shard = shards[boundaries.getShardForKey(key)];",
        "if (shard.data.reachedAllocatedSizeThreshold() && !switchRequested.getAndSet(true))",
        "catch (InMemoryTrie.SpaceExhaustedException e)",
        "public MemtableUnfilteredPartitionIterator partitionIterator(final ColumnFilter columnFilter,",
        "final InMemoryTrie<BTreePartitionData> data;",
        "this.data = new InMemoryTrie<>(BUFFER_TYPE);",
        "public long put(DecoratedKey key, PartitionUpdate update, UpdateTransaction indexer, OpOrder.Group opGroup) throws InMemoryTrie.SpaceExhaustedException",
        "boolean locked = writeLock.tryLock();",
        "metrics.uncontendedPuts.inc();",
        "metrics.contendedPuts.inc();",
        "public static Factory factory(Map<String, String> optionsCopy)",
        "public TableMetrics.ReleasableMetric createMemtableMetrics(TableMetadataRef metadataRef)",
    ),
    TRIE_MEMTABLE_METRICS_VIEW: (
        "public class TrieMemtableMetricsView",
        "private static final String UNCONTENDED_PUTS = \"Uncontended memtable puts\";",
        "private static final String CONTENDED_PUTS = \"Contended memtable puts\";",
        "public final Counter uncontendedPuts;",
        "public final Counter contendedPuts;",
        "public TrieMemtableMetricsView(String keyspace, String table)",
        "uncontendedPuts = Metrics.counter(factory.createMetricName(UNCONTENDED_PUTS));",
        "contendedPuts = Metrics.counter(factory.createMetricName(CONTENDED_PUTS));",
    ),
    MEMTABLE_PARAMS: (
        "public final class MemtableParams",
        "private static final String DEFAULT_CONFIGURATION_KEY = \"default\";",
        "private static final Memtable.Factory DEFAULT_MEMTABLE_FACTORY = SkipListMemtableFactory.INSTANCE;",
        "CONFIGURATION_DEFINITIONS = expandDefinitions(DatabaseDescriptor.getMemtableConfigurations());",
        "public static MemtableParams getWithFallback(String key)",
        "static Map<String, ParameterizedClass> expandDefinitions(Map<String, InheritingClass> memtableConfigurations)",
        "return ImmutableMap.of(DEFAULT_CONFIGURATION_KEY, DEFAULT_CONFIGURATION);",
        "private static MemtableParams parseConfiguration(String configurationKey)",
        "private static Memtable.Factory getMemtableFactory(ParameterizedClass options)",
        "className = className.contains(\".\") ? className : \"org.apache.cassandra.db.memtable.\" + className;",
        "factory = (Memtable.Factory) factoryMethod.invoke(null, parametersCopy);",
        "Field factoryField = clazz.getDeclaredField(\"FACTORY\");",
        "does not accept any futher parameters",
    ),
    TABLE_PARAMS: (
        "MEMTABLE,",
        "MEMTABLE_FLUSH_PERIOD_IN_MS,",
        "public final int memtableFlushPeriodInMs;",
        "public final MemtableParams memtable;",
        "if (cdc && memtable.factory().writesShouldSkipCommitLog())",
        "CDC cannot work if writes skip the commit log. Check your memtable configuration.",
    ),
    CONFIG: (
        "public int memtable_flush_writers = 0;",
        "public DataStorageSpec.IntMebibytesBound memtable_heap_space;",
        "public DataStorageSpec.IntMebibytesBound memtable_offheap_space;",
        "public Float memtable_cleanup_threshold = null;",
        "public static class MemtableOptions",
        "public MemtableOptions memtable;",
        "public MemtableAllocationType memtable_allocation_type = MemtableAllocationType.heap_buffers;",
        "public enum MemtableAllocationType",
    ),
    DATABASE_DESCRIPTOR: (
        "if (conf.memtable_flush_writers == 0)",
        "conf.memtable_cleanup_threshold = (float) (1.0 / (1 + conf.memtable_flush_writers));",
        "public static Config.MemtableAllocationType getMemtableAllocationType()",
        "public static Map<String, InheritingClass> getMemtableConfigurations()",
    ),
    CASSANDRA_YAML: (
        "# Supported memtable implementations and selected default.",
        "# - SkipListMemtable is the legacy memtable implementation provided by earlier",
        "# - TrieMemtable is a new memtable that utilizes a trie data structure.",
        "memtable:",
        "class_name: SkipListMemtable",
        "class_name: TrieMemtable",
        "inherits: skiplist",
        "memtable_allocation_type: heap_buffers",
        "# You can tell if flushing is falling behind using the MemtablePool.BlockedOnAllocation",
        "# memtable_flush_writers: 2",
    ),
    COLUMN_FAMILY_STORE: (
        "public enum FlushReason",
        "private volatile Memtable.Factory memtableFactory;",
        "memtableFactory = metadata().params.memtable.factory();",
        "return memtableFactory.writesShouldSkipCommitLog();",
        "return memtableFactory.writesAreDurable();",
        "return memtableFactory.streamToMemtable();",
        "return memtableFactory.streamFromMemtable();",
        "private void switchMemtableOrNotify(FlushReason reason, Consumer<Memtable> elseNotify)",
        "public Future<CommitLogPosition> switchMemtableIfCurrent(Memtable memtable, FlushReason reason)",
        "public Future<CommitLogPosition> switchMemtable(FlushReason reason)",
        "private final class PostFlush implements Callable<CommitLogPosition>",
        "CommitLog.instance.discardCompletedSegments(metadata.id, mainMemtable.getCommitLogLowerBound(), commitLogUpperBound);",
        "metric.pendingFlushes.dec();",
        "private final class Flush implements Runnable",
        "writeBarrier = Keyspace.writeOrder.newBarrier();",
        "Memtable newMemtable = cfs.createMemtable(commitLogUpperBound);",
        "Memtable oldMemtable = cfs.data.switchMemtable(truncate, newMemtable);",
        "oldMemtable.switchOut(writeBarrier, commitLogUpperBound);",
        "writeBarrier.markBlocking();",
        "writeBarrier.await();",
        "cfs.replaceFlushed(memtable, Collections.emptyList());",
        "cfs.replaceFlushed(memtable, sstables);",
        "public Memtable createMemtable(AtomicReference<CommitLogPosition> commitLogUpperBound)",
        "public Future<CommitLogPosition> signalFlushRequired(Memtable memtable, FlushReason reason)",
        "public void apply(PartitionUpdate update, CassandraWriteContext context, boolean updateIndexes)",
    ),
    FLUSHING: (
        "public class Flushing",
        "public static List<FlushRunnable> flushRunnables(ColumnFamilyStore cfs,",
        "LifecycleTransaction ongoingFlushTransaction = memtable.setFlushTransaction(txn);",
        "DiskBoundaries diskBoundaries = cfs.getDiskBoundaries();",
        "public static class FlushRunnable implements Callable<SSTableMultiWriter>",
        "private final SSTableMultiWriter writer;",
        "private void writeSortedContents()",
        "writer.append(iter);",
        "long bytesFlushed = writer.getBytesWritten();",
        "logger.info(\"Completed flushing {} ({}) for commitlog position {}\",",
        "metrics.bytesFlushed.inc(bytesFlushed);",
        "public static SSTableMultiWriter createFlushWriter(ColumnFamilyStore cfs,",
    ),
    MEMTABLE_POOL: (
        "public abstract class MemtablePool",
        "final MemtableCleanerThread<?> cleaner;",
        "public final SubPool onHeap;",
        "public final SubPool offHeap;",
        "blockedOnAllocating = CassandraMetricsRegistry.Metrics.timer(nameFactory.createMetricName(\"BlockedOnAllocation\"));",
        "numPendingTasks = CassandraMetricsRegistry.Metrics.register(nameFactory.createMetricName(\"PendingFlushTasks\"),",
        "SubPool getSubPool(long limit, float cleanThreshold)",
        "public class SubPool",
        "if (needsCleaning() && cleaner != null)",
        "cleaner.trigger();",
    ),
    MEMTABLE_CLEANER_THREAD: (
        "public class MemtableCleanerThread<P extends MemtablePool> implements Interruptible",
        "final MemtableCleaner cleaner;",
        "cleaner.clean().addCallback(this::apply);",
    ),
}

TEST_TOKEN_CHECKS = {
    MEMTABLE_PARAMS_TEST: (
        "public class MemtableParamsTest",
        "config.put(\"skiplist\", new InheritingClass(\"skiplistOnSteroids\", \"SkipListMemtable\", ImmutableMap.of(\"e\", \"f\")));",
        "config.put(\"trie\", new InheritingClass(null, \"TrieMemtable\", null));",
        "assertTrue(map.get(\"skiplist\").parameters.containsKey(\"e\"));",
        "Note: The factories constructed from these parameters are tested in the CreateTest and AlterTest.",
    ),
    TEST_MEMTABLE: (
        "public class TestMemtable",
        "public static Memtable.Factory factory(Map<String, String> options)",
        "String skiplist = options.remove(\"skiplist\");",
    ),
    CREATE_TEST: (
        "public class CreateTest extends CQLTester",
        "public static class InvalidMemtableFactoryMethod",
        "public static class InvalidMemtableFactoryField",
        "testMemtableConfig(\"skiplist\", SkipListMemtable.FACTORY, SkipListMemtable.class);",
        "testMemtableConfig(\"trie\", MemtableParams.get(\"trie\").factory(), TrieMemtable.class);",
        "testMemtableConfig(\"test_fullname\", TestMemtable.FACTORY, SkipListMemtable.class);",
        "Memtable class org.apache.cassandra.db.memtable.SkipListMemtable does not accept any futher parameters",
        "private void testMemtableConfig(String memtableConfig, Memtable.Factory factoryInstance, Class<? extends Memtable> memtableClass) throws Throwable",
    ),
    ALTER_TEST: (
        "public class AlterTest extends CQLTester",
        "testMemtableConfig(\"skiplist\", SkipListMemtable.FACTORY, SkipListMemtable.class);",
        "testMemtableConfig(\"test_fullname\", TestMemtable.FACTORY, SkipListMemtable.class);",
        "verify memtable does not change on other ALTER",
        "Memtable class org.apache.cassandra.db.memtable.SkipListMemtable does not accept any futher parameters",
        "private void testMemtableConfig(String memtableConfig, Memtable.Factory factoryInstance, Class<? extends Memtable> memtableClass) throws Throwable",
    ),
    MEMTABLE_QUICK_TEST: (
        "public class MemtableQuickTest extends CQLTester",
        "public static List<Object> parameters()",
        "return ImmutableList.of(\"skiplist\",",
        "\"skiplist_sharded\",",
        "\"skiplist_sharded_locking\",",
        "\"trie\");",
        "public void testMemtable() throws Throwable",
        "if (sstables.isEmpty()) // persistent memtables won't flush",
    ),
    MEMTABLE_SIZE_TEST_BASE: (
        "public abstract class MemtableSizeTestBase extends CQLTester",
        "public static List<Object> parameters()",
        "conf.memtable_allocation_type = allocationType;",
        "conf.memtable_cleanup_threshold = 0.8f;",
        "public void testSize() throws Throwable",
        "Memtable.MemoryUsage usage = Memtable.getMemoryUsage(memtable);",
        "long trie_overhead = memtable instanceof TrieMemtable ? ((TrieMemtable) memtable).unusedReservedMemory() : 0;",
    ),
    SHARDED_MEMTABLE_CONFIG_TEST: (
        "public class ShardedMemtableConfigTest extends CQLTester",
        "public void testDefaultShardCountSetByJMX()",
        "jmxConnection.setAttribute(new ObjectName(SHARDED_MEMTABLE_CONFIG_OBJECT_NAME), new Attribute(\"DefaultShardCount\", \"7\"));",
        "jmxConnection.setAttribute(new ObjectName(SHARDED_MEMTABLE_CONFIG_OBJECT_NAME), new Attribute(\"DefaultShardCount\", \"auto\"));",
    ),
    TRIE_MEMTABLE_METRICS_TEST: (
        "public class TrieMemtableMetricsTest extends SchemaLoader",
        "WITH MEMTABLE = 'test_memtable_metrics';",
        "testRegularStatementsAreCounted",
        "testFlushRelatedMetrics",
        "verify that metrics survive flush / memtable switching",
        "testContentionMetrics",
        "testMetricsCleanupOnDrop",
        "logger.info(\"forcing flush\");",
        "logger.info(\"table flushed\");",
    ),
    MEMTABLE_CLEANER_THREAD_TEST: (
        "public class MemtableCleanerThreadTest",
        "public void testCleanerInvoked() throws Exception",
        "cleanerThread.trigger();",
        "assertEquals(1, cleanerThread.numPendingTasks());",
        "public void testCleanerError() throws Exception",
    ),
    TRACKER_TEST: (
        "public class TrackerTest",
        "tracker.markFlushing(prev2);",
        "tracker.replaceFlushed(prev1, Collections.emptyList());",
        "tracker.replaceFlushed(prev2, singleton(reader));",
        "MemtableDiscardedNotification",
    ),
    COMMITLOG_TEST: (
        "public abstract class CommitLogTest",
        "public void testOutOfOrderFlushRecovery(BiConsumer<ColumnFamilyStore, Memtable> flushAction, boolean performCompaction)",
        "((SkipListMemtable) current).makeUnflushable();",
        "public void testOutOfOrderFlushRecovery()",
        "public void testOutOfOrderFlushRecoveryWithCompaction()",
    ),
}

DOC_REQUIRED_TOKENS = (
    "research/tools/check-memtable-implementation-flush-drift.py",
    "research/module-memtable-implementation-flush-matrix.md",
    "research/module-memtable-implementation-flush-drift-checker.md",
    "Memtable.Factory",
    "SkipListMemtable",
    "ShardedSkipListMemtable",
    "TrieMemtable",
    "MemtableParams",
    "TableParams.validate()",
    "MemtablePool.BlockedOnAllocation",
    "TrieMemtableMetricsView",
    "ColumnFamilyStore.Flush",
    "PostFlush",
    "Flushing.flushRunnables()",
    "MemtableQuickTest",
    "MemtableSizeTestBase",
    "ShardedMemtableConfigTest",
    "TrieMemtableMetricsTest",
    "MemtableCleanerThreadTest",
    "TrackerTest",
    "CommitLogTest.testOutOfOrderFlushRecovery()",
    "persistent memtables won't flush",
)


@dataclass(frozen=True)
class CheckResult:
    category: str
    target: str
    token: str


def read_repo_file(path: str) -> str:
    full_path = REPO_ROOT / path
    if not full_path.exists():
        raise AssertionError(f"missing file: {path}")
    return full_path.read_text(encoding="utf-8")


def require_tokens(category: str, path: str, tokens: tuple[str, ...]) -> list[CheckResult]:
    content = read_repo_file(path)
    results = []
    for token in tokens:
        if token not in content:
            raise AssertionError(f"{category} token missing in {path}: {token}")
        results.append(CheckResult(category, path, token))
    return results


def require_doc_tokens(tokens: tuple[str, ...]) -> list[CheckResult]:
    doc_content = "\n".join(read_repo_file(path) for path in TARGET_DOCS)
    results = []
    for token in tokens:
        if token not in doc_content:
            raise AssertionError(f"doc token missing in research docs: {token}")
        results.append(CheckResult("doc", "research docs", token))
    return results


def run_checks() -> list[CheckResult]:
    results: list[CheckResult] = []

    for path in TARGET_DOCS:
        read_repo_file(path)
        results.append(CheckResult("doc-exists", path, path))

    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        results.extend(require_tokens("source", path, tokens))

    for path, tokens in TEST_TOKEN_CHECKS.items():
        results.extend(require_tokens("test", path, tokens))

    results.extend(require_doc_tokens(DOC_REQUIRED_TOKENS + SCENARIO_IDS))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Memtable implementation/flush research drift")
    parser.add_argument("--json", action="store_true", help="emit JSON result details")
    args = parser.parse_args()

    try:
        results = run_checks()
    except AssertionError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([result.__dict__ for result in results], indent=2, sort_keys=True))
    else:
        source_count = sum(1 for result in results if result.category == "source")
        test_count = sum(1 for result in results if result.category == "test")
        doc_count = sum(1 for result in results if result.category.startswith("doc"))
        print(
            f"OK Memtable implementation/flush drift checks passed "
            f"({source_count} source checks, {test_count} test checks, {doc_count} doc checks, "
            f"{len(SCENARIO_IDS)} scenarios)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
