#!/usr/bin/env python3
"""Validate Flush execution/disk-pressure research against source tokens."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]

CFS = "src/java/org/apache/cassandra/db/ColumnFamilyStore.java"
FLUSHING = "src/java/org/apache/cassandra/db/memtable/Flushing.java"
DISK_BOUNDARIES = "src/java/org/apache/cassandra/db/DiskBoundaries.java"
DIRECTORIES = "src/java/org/apache/cassandra/db/Directories.java"
STORAGE_SERVICE = "src/java/org/apache/cassandra/service/StorageService.java"
NODETOOL_FLUSH = "src/java/org/apache/cassandra/tools/nodetool/Flush.java"
NODE_PROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
TABLE_METRICS = "src/java/org/apache/cassandra/metrics/TableMetrics.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
CASSANDRA_YAML = "conf/cassandra.yaml"

CFS_TEST = "test/unit/org/apache/cassandra/db/ColumnFamilyStoreTest.java"
COMMITLOG_TEST = "test/unit/org/apache/cassandra/db/commitlog/CommitLogTest.java"
SSTABLE_FLUSH_OBSERVER_TEST = "test/unit/org/apache/cassandra/io/sstable/SSTableFlushObserverTest.java"
DIRECTORIES_TEST = "test/unit/org/apache/cassandra/db/DirectoriesTest.java"
DISK_FAILURE_POLICY_TEST = "test/unit/org/apache/cassandra/service/DiskFailurePolicyTest.java"
NODETOOL_TEST = "test/distributed/org/apache/cassandra/distributed/test/NodeToolTest.java"
STREAMS_DISK_SPACE_TEST = "test/distributed/org/apache/cassandra/distributed/test/StreamsDiskSpaceTest.java"
COMPACTION_OVERLAP_TEST = "test/distributed/org/apache/cassandra/distributed/test/CompactionOverlappingSSTableTest.java"
LEVELED_COMPACTION_TASK_TEST = "test/distributed/org/apache/cassandra/distributed/test/LeveledCompactionTaskTest.java"

SCENARIO_IDS = (
    "flush_executor_topology_contract",
    "flush_force_switch_dirty_contract",
    "flush_barrier_commitlog_upper_bound_contract",
    "flush_postflush_commitlog_discard_contract",
    "flush_empty_memtable_reclaim_contract",
    "flush_disk_boundaries_split_contract",
    "flush_writer_location_space_contract",
    "flush_per_disk_submit_wait_contract",
    "flush_runnable_write_metrics_contract",
    "flush_failure_abort_transaction_contract",
    "flush_secondary_index_blocking_contract",
    "flush_storage_service_user_drain_contract",
    "flush_metrics_observability_contract",
    "flush_existing_test_baseline",
    "flush_disk_pressure_gap",
)

TARGET_DOCS = (
    "research/module-flush-execution-disk-pressure-matrix.md",
    "research/module-flush-execution-disk-drift-checker.md",
    "research/module-memtable-flush.md",
    "research/module-memtable-postflush-trigger-deep-dive.md",
    "research/flow-flush.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SOURCE_TOKEN_CHECKS = {
    CFS: (
        "The FlushRunnables are executed in the perDiskflushExecutors",
        "private static final ExecutorPlus flushExecutor",
        "pooled(\"MemtableFlushWriter\", getFlushWriters())",
        "private static final ExecutorPlus postFlushExecutor",
        "sequential(\"MemtablePostFlush\")",
        "private static final ExecutorPlus reclaimExecutor",
        "sequential(\"MemtableReclaimMemory\")",
        "private static final PerDiskFlushExecutors perDiskflushExecutors",
        "public Future<CommitLogPosition> switchMemtable(FlushReason reason)",
        "Flush flush = new Flush(false);",
        "flushExecutor.execute(flush);",
        "postFlushExecutor.execute(flush.postFlushTask);",
        "public Future<CommitLogPosition> forceFlush(FlushReason reason)",
        "if (!cfs.data.getView().getCurrentMemtable().isClean())",
        "public Future<?> forceFlush(CommitLogPosition flushIfDirtyBefore)",
        "if (current.mayContainDataBefore(flushIfDirtyBefore))",
        "public CommitLogPosition forceBlockingFlush(FlushReason reason)",
        "private final class PostFlush implements Callable<CommitLogPosition>",
        "CommitLog.instance.discardCompletedSegments(metadata.id, mainMemtable.getCommitLogLowerBound(), commitLogUpperBound);",
        "metric.pendingFlushes.dec();",
        "private final class Flush implements Runnable",
        "metric.pendingFlushes.inc();",
        "writeBarrier = Keyspace.writeOrder.newBarrier();",
        "oldMemtable.switchOut(writeBarrier, commitLogUpperBound);",
        "writeBarrier.issue();",
        "postFlush = new PostFlush(Iterables.get(memtables.values(), 0, null));",
        "writeBarrier.markBlocking();",
        "writeBarrier.await();",
        "entry.getKey().data.markFlushing(entry.getValue());",
        "metric.memtableSwitchCount.inc();",
        "cfs.replaceFlushed(memtable, Collections.emptyList());",
        "try (LifecycleTransaction txn = LifecycleTransaction.offline(OperationType.FLUSH))",
        "flushRunnables = Flushing.flushRunnables(cfs, memtable, txn);",
        "ExecutorPlus[] executors = perDiskflushExecutors.getExecutorsFor(getKeyspaceName(), name);",
        "futures.add(executors[i].submit(flushRunnables.get(i)));",
        "indexManager.flushAllNonCFSBackedIndexesBlocking(memtable);",
        "flushResults = Lists.newArrayList(FBUtilities.waitOnFutures(futures));",
        "t = Flushing.abortRunnables(flushRunnables, t);",
        "t = txn.abort(t);",
        "writer.setOpenResult(true).prepareToCommit();",
        "maybeFail(writer.abort(null));",
        "metric.flushSizeOnDisk.update(writer.getOnDiskBytesWritten());",
        "maybeFail(txn.commit(accumulate));",
        "cfs.replaceFlushed(memtable, sstables);",
        "reclaim(memtable);",
        "final OpOrder.Barrier readBarrier = readOrdering.newBarrier();",
        "memtable.discard();",
        "public DiskBoundaries getDiskBoundaries()",
        "private static final class PerDiskFlushExecutors",
        "private final ExecutorPlus[] nonLocalSystemflushExecutors;",
        "private final ExecutorPlus[] localSystemDiskFlushExecutors;",
        "createPerDiskFlushWriters(locationsForNonSystemKeyspaces.length, flushWriters);",
        "newThreadPool(\"PerDiskMemtableFlushWriter_\"+i, flushWriters);",
        "newThreadPool(\"LocalSystemKeyspacesDiskMemtableFlushWriter\", flushWriters)",
        "public ExecutorPlus[] getExecutorsFor(String keyspaceName, String tableName)",
        "Directories.isStoredInLocalSystemKeyspacesDataLocation(keyspaceName, tableName)",
    ),
    FLUSHING: (
        "public static List<FlushRunnable> flushRunnables(ColumnFamilyStore cfs,",
        "LifecycleTransaction ongoingFlushTransaction = memtable.setFlushTransaction(txn);",
        "Attempted to flush Memtable more than once",
        "DiskBoundaries diskBoundaries = cfs.getDiskBoundaries();",
        "List<PartitionPosition> boundaries = diskBoundaries.positions;",
        "List<Directories.DataDirectory> locations = diskBoundaries.directories;",
        "return Collections.singletonList(runnable);",
        "for (int i = 0; i < boundaries.size(); i++)",
        "FlushRunnable runnable = flushRunnable(cfs, memtable, rangeStart, t, txn, locations.get(i));",
        "Memtable.FlushablePartitionSet<?> flushSet = memtable.getFlushSet(from, to);",
        "long estimatedSize = format.getWriterFactory().estimateSize(flushSet);",
        "getWriteableLocationAsFile(estimatedSize)",
        "getLocationForDisk(flushLocation)",
        "return new FlushRunnable(flushSet, writer, cfs.metric, true);",
        "public static Throwable abortRunnables(List<FlushRunnable> runnables, Throwable t)",
        "public static class FlushRunnable implements Callable<SSTableMultiWriter>",
        "logger.info(\"Writing {}, flushed range = [{}, {})\"",
        "if (isBatchLogTable && !partition.partitionLevelDeletion().isLive() && partition.hasRows())",
        "writer.append(iter);",
        "logger.info(\"Completed flushing {} ({}) for commitlog position {}\"",
        "metrics.bytesFlushed.inc(bytesFlushed);",
        "public SSTableMultiWriter call()",
    ),
    DISK_BOUNDARIES: (
        "public class DiskBoundaries",
        "public boolean isOutOfDate()",
        "DisallowedDirectories.getDirectoriesVersion()",
        "StorageService.instance.getTokenMetadata().getRingVersion()",
        "public Directories.DataDirectory getCorrectDiskForKey(DecoratedKey key)",
        "public List<Directories.DataDirectory> getDisksInBounds(DecoratedKey first, DecoratedKey last)",
        "public boolean isEquivalentTo(DiskBoundaries oldBoundaries)",
    ),
    DIRECTORIES: (
        "public File getWriteableLocationAsFile(long writeSize)",
        "No configured data directory contains enough space to write",
        "public DataDirectory getWriteableLocation(long writeSize)",
        "if (DisallowedDirectories.isUnwritable(getLocationForDisk(dataDir)))",
        "if (candidate.availableSpace < writeSize)",
        "throw new FSDiskFullWriteError(metadata.keyspace, writeSize);",
        "throw new FSNoDiskAvailableForWriteError(metadata.keyspace);",
        "sortWriteableCandidates(candidates, totalAvailable);",
        "return pickWriteableDirectory(candidates);",
        "static final class DataDirectoryCandidate implements Comparable<DataDirectoryCandidate>",
        "this.availableSpace = dataDirectory.getAvailableSpace();",
        "void calcFreePerc(long totalAvailableSpace)",
    ),
    STORAGE_SERVICE: (
        "public void forceKeyspaceFlush(String keyspaceName, String... tableNames) throws IOException",
        "cfStore.forceBlockingFlush(ColumnFamilyStore.FlushReason.USER_FORCED);",
        "public void forceKeyspaceFlush(String keyspaceName, ColumnFamilyStore.FlushReason reason) throws IOException",
        "cfStore.forceBlockingFlush(reason);",
        "public synchronized void drain() throws IOException, InterruptedException, ExecutionException",
        "setMode(Mode.DRAINING, \"flushing column families\", false);",
        "disableAutoCompaction();",
        "count CFs first, since forceFlush could block for the flushWriter to get a queue slot empty",
        "flushes.add(cfs.forceFlush(ColumnFamilyStore.FlushReason.DRAIN));",
        "FBUtilities.waitOnFutures(flushes);",
    ),
    NODETOOL_FLUSH: (
        "@Command(name = \"flush\", description = \"Flush one or more tables\")",
        "probe.forceKeyspaceFlush(keyspace, tableNames);",
        "throw new RuntimeException(\"Error occurred during flushing\", e);",
    ),
    NODE_PROBE: (
        "public void forceKeyspaceFlush(String keyspaceName, String... tableNames)",
        "ssProxy.forceKeyspaceFlush(keyspaceName, tableNames);",
    ),
    TABLE_METRICS: (
        "public final Counter memtableSwitchCount;",
        "public final Counter pendingFlushes;",
        "public final Counter bytesFlushed;",
        "public final MovingAverage flushSizeOnDisk;",
        "memtableSwitchCount = createTableCounter(\"MemtableSwitchCount\");",
        "pendingFlushes = createTableCounter(\"PendingFlushes\");",
        "bytesFlushed = createTableCounter(\"BytesFlushed\");",
        "flushSizeOnDisk = ExpMovingAverage.decayBy1000();",
    ),
    CONFIG: (
        "public int memtable_flush_writers = 0;",
        "public Float memtable_cleanup_threshold = null;",
    ),
    DATABASE_DESCRIPTOR: (
        "if (conf.memtable_flush_writers == 0)",
        "conf.memtable_flush_writers = conf.data_file_directories.length == 1 ? 2 : 1;",
        "memtable_flush_writers must be at least 1",
        "conf.memtable_cleanup_threshold = (float) (1.0 / (1 + conf.memtable_flush_writers));",
        "public static int getFlushWriters()",
        "return conf.memtable_flush_writers;",
    ),
    CASSANDRA_YAML: (
        "memtable_flush_writers defaults to two for a single data directory.",
        "memtable_cleanup_threshold defaults to 1 / (memtable_flush_writers + 1)",
    ),
}

TEST_TOKEN_CHECKS = {
    CFS_TEST: (
        "import org.apache.cassandra.db.ColumnFamilyStore.FlushReason;",
        "Util.flush(cfs);",
        "public boolean shouldSwitch(FlushReason reason)",
    ),
    COMMITLOG_TEST: (
        "Util.markDirectoriesUnwriteable(cfs)",
        "Currently we don't attempt to re-flush a memtable that failed",
        "assertEquals(1, CommitLog.instance.resetUnsafe(false));",
        "switchMemtableIfCurrent(current, ColumnFamilyStore.FlushReason.UNIT_TESTS)",
        "while (!(t instanceof FSWriteError))",
    ),
    SSTABLE_FLUSH_OBSERVER_TEST: (
        "public class SSTableFlushObserverTest",
        "private static class FlushObserver implements SSTableFlushObserver",
        "writer.onSSTableWriterSwitched();",
        "Assert.assertTrue(observer.isWriterSwitched);",
        "Assert.assertTrue(observer.isComplete);",
        "assertThat(observer1.abortCalled).isTrue();",
    ),
    DIRECTORIES_TEST: (
        "getWriteableDirectories(DataDirectory[] dataDirectories, long writeSize)",
        "Directories.sortWriteableCandidates(candidates, totalAvailable);",
        "public static class FakeFileStore extends FileStore",
    ),
    DISK_FAILURE_POLICY_TEST: (
        "DiskFailurePolicy.best_effort",
        "DisallowedDirectories.isUnreadable",
        "assertEquals(expectJVMKilled, killerForTests.wasKilled());",
    ),
    NODETOOL_TEST: (
        "assertEquals(0, NODE.nodetool(\"flush\"));",
        "assertEquals(1, NODE.nodetool(\"not_a_legal_command\"));",
    ),
    STREAMS_DISK_SPACE_TEST: (
        "cluster.get(1).flush(KEYSPACE);",
        "getWriteableLocation(0)",
    ),
    COMPACTION_OVERLAP_TEST: (
        "cluster.get(1).flush(KEYSPACE);",
    ),
    LEVELED_COMPACTION_TASK_TEST: (
        "cluster.get(1).flush(KEYSPACE);",
    ),
}

DOC_REQUIRED_TOKENS = (
    "ColumnFamilyStore.Flush",
    "ColumnFamilyStore.PostFlush",
    "PerDiskFlushExecutors",
    "Flushing.flushRunnables",
    "FlushRunnable",
    "DiskBoundaries",
    "Directories.getWriteableLocation",
    "FSDiskFullWriteError",
    "FSNoDiskAvailableForWriteError",
    "CommitLog.discardCompletedSegments",
    "flushAllNonCFSBackedIndexesBlocking",
    "memtable_flush_writers",
    "memtable_cleanup_threshold",
    "PendingFlushes",
    "MemtableSwitchCount",
    "BytesFlushed",
    "flushSizeOnDisk",
    "NodeToolTest",
    "SSTableFlushObserverTest",
    "CommitLogTest",
    "DirectoriesTest",
    "DiskFailurePolicyTest",
    "flush_disk_pressure_gap",
    "research/tools/check-flush-execution-disk-drift.py",
)


@dataclass(frozen=True)
class Failure:
    category: str
    path: str
    token: str


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require_tokens(category: str, checks: dict[str, Iterable[str]]) -> list[Failure]:
    failures: list[Failure] = []
    for path, tokens in checks.items():
        full_path = ROOT / path
        if not full_path.exists():
            failures.append(Failure(category, path, "<missing file>"))
            continue
        text = read(path)
        for token in tokens:
            if token not in text:
                failures.append(Failure(category, path, token))
    return failures


def check_source_tokens() -> list[Failure]:
    return require_tokens("source", SOURCE_TOKEN_CHECKS)


def check_test_tokens() -> list[Failure]:
    return require_tokens("test", TEST_TOKEN_CHECKS)


def check_doc_tokens() -> list[Failure]:
    failures: list[Failure] = []
    docs: dict[str, str] = {}
    for path in TARGET_DOCS:
        full_path = ROOT / path
        if not full_path.exists():
            failures.append(Failure("doc", path, "<missing file>"))
            continue
        docs[path] = read(path)

    matrix_path = "research/module-flush-execution-disk-pressure-matrix.md"
    checker_doc_path = "research/module-flush-execution-disk-drift-checker.md"
    source_map_path = "research/notes/source-map.md"
    readme_path = "research/README.md"

    for scenario in SCENARIO_IDS:
        for path in (matrix_path, checker_doc_path, source_map_path):
            if path in docs and scenario not in docs[path]:
                failures.append(Failure("doc", path, scenario))

    combined_docs = "\n".join(docs.values())
    for token in DOC_REQUIRED_TOKENS:
        if token not in combined_docs:
            failures.append(Failure("doc", "research docs", token))

    for path in (readme_path, source_map_path):
        for token in (
            "module-flush-execution-disk-pressure-matrix.md",
            "module-flush-execution-disk-drift-checker.md",
            "research/tools/check-flush-execution-disk-drift.py",
        ):
            if path in docs and token not in docs[path]:
                failures.append(Failure("doc", path, token))

    return failures


def run_checks() -> tuple[list[Failure], dict[str, int]]:
    source_failures = check_source_tokens()
    test_failures = check_test_tokens()
    doc_failures = check_doc_tokens()
    failures = source_failures + test_failures + doc_failures
    counts = {
        "source_checks": sum(len(tokens) for tokens in SOURCE_TOKEN_CHECKS.values()),
        "test_checks": sum(len(tokens) for tokens in TEST_TOKEN_CHECKS.values()),
        "doc_checks": len(DOC_REQUIRED_TOKENS)
        + len(SCENARIO_IDS) * 3
        + 3 * 2,
        "scenario_ids": len(SCENARIO_IDS),
    }
    return failures, counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable result")
    args = parser.parse_args()

    failures, counts = run_checks()
    if args.json:
        print(json.dumps({
            "ok": not failures,
            "counts": counts,
            "failures": [failure.__dict__ for failure in failures],
        }, indent=2, sort_keys=True))
    elif failures:
        print("Flush execution/disk-pressure drift check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- [{failure.category}] {failure.path}: missing {failure.token!r}", file=sys.stderr)
    else:
        print(
            "OK Flush execution/disk-pressure drift checks passed "
            f"({counts['source_checks']} source checks, "
            f"{counts['test_checks']} test checks, "
            f"{counts['doc_checks']} doc checks, "
            f"{counts['scenario_ids']} scenarios)"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
