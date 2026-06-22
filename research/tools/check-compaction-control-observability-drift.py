#!/usr/bin/env python3
"""Validate compaction control/observability research against source tokens."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]

ACTIVE_COMPACTIONS = "src/java/org/apache/cassandra/db/compaction/ActiveCompactions.java"
COMPACTION_INFO = "src/java/org/apache/cassandra/db/compaction/CompactionInfo.java"
COMPACTION_MANAGER = "src/java/org/apache/cassandra/db/compaction/CompactionManager.java"
COMPACTION_TASK = "src/java/org/apache/cassandra/db/compaction/CompactionTask.java"
COMPACTION_ITERATOR = "src/java/org/apache/cassandra/db/compaction/CompactionIterator.java"
COMPACTION_INTERRUPTED = "src/java/org/apache/cassandra/db/compaction/CompactionInterruptedException.java"
OPERATION_TYPE = "src/java/org/apache/cassandra/db/compaction/OperationType.java"
COMPACTION_MBEAN = "src/java/org/apache/cassandra/db/compaction/CompactionManagerMBean.java"
CFS = "src/java/org/apache/cassandra/db/ColumnFamilyStore.java"
NODETOOL_STOP = "src/java/org/apache/cassandra/tools/nodetool/Stop.java"
NODETOOL_COMPACTION_STATS = "src/java/org/apache/cassandra/tools/nodetool/CompactionStats.java"
NODE_PROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
SSTABLE_TASKS_TABLE = "src/java/org/apache/cassandra/db/virtual/SSTableTasksTable.java"
COMPACTION_METRICS = "src/java/org/apache/cassandra/metrics/CompactionMetrics.java"

ACTIVE_COMPACTIONS_TEST = "test/unit/org/apache/cassandra/db/compaction/ActiveCompactionsTest.java"
COMPACTION_STATS_TEST = "test/unit/org/apache/cassandra/tools/nodetool/CompactionStatsTest.java"
SSTABLE_TASKS_TABLE_TEST = "test/unit/org/apache/cassandra/db/virtual/SSTableTasksTableTest.java"
COMPACTION_ITERATOR_TEST = "test/unit/org/apache/cassandra/db/compaction/CompactionIteratorTest.java"
SECONDARY_INDEX_COMPACTION_TEST = "test/distributed/org/apache/cassandra/distributed/test/SecondaryIndexCompactionTest.java"
UPGRADE_SSTABLES_TEST = "test/distributed/org/apache/cassandra/distributed/test/UpgradeSSTablesTest.java"

SCENARIO_IDS = (
    "compaction_active_tracker_contract",
    "compaction_info_task_identity_contract",
    "compaction_stop_by_type_contract",
    "compaction_stop_by_id_contract",
    "compaction_holder_stop_poll_contract",
    "compaction_interrupt_for_sstable_contract",
    "compaction_global_pause_contract",
    "compactionstats_verbose_task_contract",
    "sstable_tasks_virtual_table_contract",
    "compaction_remaining_write_estimate_contract",
    "compaction_operation_type_stop_contract",
    "compaction_control_existing_tests_baseline",
    "compaction_live_cancel_metrics_gap",
)

TARGET_DOCS = (
    "research/module-compaction-control-observability-matrix.md",
    "research/module-compaction-control-observability-drift-checker.md",
    "research/module-compaction-operations-failure-matrix.md",
    "research/module-compaction-operations-drift-checker.md",
    "research/module-sstable-compaction.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SOURCE_TOKEN_CHECKS = {
    ACTIVE_COMPACTIONS: (
        "public class ActiveCompactions implements ActiveCompactionsTracker",
        "private final Set<CompactionInfo.Holder> compactions = Collections.synchronizedSet(Collections.newSetFromMap(new IdentityHashMap<>()));",
        "public List<CompactionInfo.Holder> getCompactions()",
        "return new ArrayList<>(compactions);",
        "public void beginCompaction(CompactionInfo.Holder ci)",
        "compactions.add(ci);",
        "public void finishCompaction(CompactionInfo.Holder ci)",
        "compactions.remove(ci);",
        "CompactionManager.instance.getMetrics().bytesCompacted.inc(ci.getCompactionInfo().getTotal());",
        "CompactionManager.instance.getMetrics().compressedBytesCompacted.inc(ci.getCompactionInfo().getTotalCompressed());",
        "CompactionManager.instance.getMetrics().totalCompactionsCompleted.mark();",
        "public Map<File, Long> estimatedRemainingWriteToDiskBytes()",
        "List<File> directories = compactionInfo.getTargetDirectories();",
        "long remainingWriteBytesPerDataDir = compactionInfo.estimatedRemainingWriteToDiskBytes() / directories.size();",
        "writeBytesPerSSTableDir.merge(directory, remainingWriteBytesPerDataDir, Long::sum);",
        "public Collection<CompactionInfo> getCompactionsForSSTable(SSTableReader sstable, OperationType compactionType)",
    ),
    COMPACTION_INFO: (
        "public static final String COMPACTION_ID = \"compactionId\";",
        "public static final String SSTABLES = \"sstables\";",
        "public static final String TARGET_DIRECTORY = \"targetDirectory\";",
        "public Map<String, String> asMap()",
        "ret.put(COMPACTION_ID, compactionId == null ? \"\" : compactionId.toString());",
        "ret.put(SSTABLES, Joiner.on(',').join(sstables));",
        "ret.put(TARGET_DIRECTORY, targetDirectory());",
        "public long estimatedRemainingWriteToDiskBytes()",
        "if (unit == Unit.BYTES && tasktype.writesData)",
        "return (long)(compressionRatio * (total - getCompleted()));",
        "boolean shouldStop(Predicate<SSTableReader> sstablePredicate)",
        "if (sstables.isEmpty())",
        "return sstables.stream().anyMatch(sstablePredicate);",
        "public static abstract class Holder",
        "private volatile boolean stopRequested = false;",
        "public void stop()",
        "stopRequested = true;",
        "public abstract boolean isGlobal();",
        "public boolean isStopRequested()",
        "return stopRequested || (isGlobal() && CompactionManager.instance.isGlobalCompactionPaused());",
    ),
    COMPACTION_MANAGER: (
        "public List<Map<String, String>> getCompactions()",
        "List<Holder> compactionHolders = active.getCompactions();",
        "out.add(ci.getCompactionInfo().asMap());",
        "public List<String> getCompactionSummary()",
        "out.add(ci.getCompactionInfo().toString());",
        "public void stopCompaction(String type)",
        "OperationType operation = OperationType.valueOf(type);",
        "if (holder.getCompactionInfo().getTaskType() == operation)",
        "holder.stop();",
        "public void stopCompactionById(String compactionId)",
        "TimeUUID holderId = holder.getCompactionInfo().getTaskId();",
        "holderId.equals(TimeUUID.fromString(compactionId))",
        "public void interruptCompactionFor(Iterable<TableMetadata> columnFamilies, Predicate<SSTableReader> sstablePredicate, boolean interruptValidation)",
        "if ((info.getTaskType() == OperationType.VALIDATION) && !interruptValidation)",
        "if (info.shouldStop(sstablePredicate))",
        "compactionHolder.stop();",
        "public List<CompactionInfo> getSSTableTasks()",
        "task.getTaskType() != OperationType.COUNTER_CACHE_SAVE",
        "task.getTaskType() != OperationType.KEY_CACHE_SAVE",
        "task.getTaskType() != OperationType.ROW_CACHE_SAVE",
        "private final AtomicInteger globalCompactionPauseCount = new AtomicInteger(0);",
        "public boolean isGlobalCompactionPaused()",
        "return globalCompactionPauseCount.get() > 0;",
        "public CompactionPauser pauseGlobalCompaction()",
        "globalCompactionPauseCount.incrementAndGet();",
    ),
    COMPACTION_TASK: (
        "activeCompactions.beginCompaction(ci);",
        "if (!controller.cfs.getCompactionStrategyManager().isActive())",
        "throw new CompactionInterruptedException(ci.getCompactionInfo());",
        "ci.setTargetDirectory(writer.getSStableDirectory().path());",
        "activeCompactions.finishCompaction(ci);",
    ),
    COMPACTION_ITERATOR: (
        "public class CompactionIterator extends CompactionInfo.Holder implements UnfilteredPartitionIterator",
        "public CompactionInfo getCompactionInfo()",
        "return new CompactionInfo(controller.cfs.metadata(),",
        "public boolean isGlobal()",
        "public void setTargetDirectory(final String targetDirectory)",
        "if (abortableIter.iter.isStopRequested())",
        "throw new CompactionInterruptedException(abortableIter.iter.getCompactionInfo());",
        "if (iter.isStopRequested())",
        "throw new CompactionInterruptedException(iter.getCompactionInfo());",
    ),
    COMPACTION_INTERRUPTED: (
        "public class CompactionInterruptedException extends RuntimeException",
        "super(\"Compaction interrupted: \" + info);",
    ),
    OPERATION_TYPE: (
        "Each modification here should be also applied to",
        "P0(\"Cancel all operations\", false, 0)",
        "COMPACTION(\"Compaction\", true, 5)",
        "INDEX_SUMMARY(\"Index summary redistribution\", false, 6)",
        "public final boolean writesData;",
        "public final int priority;",
    ),
    COMPACTION_MBEAN: (
        "public List<Map<String, String>> getCompactions();",
        "public List<String> getCompactionSummary();",
        "public void stopCompaction(String type);",
        "public void stopCompactionById(String compactionId);",
    ),
    CFS: (
        "public <V> V runWithCompactionsDisabled(Callable<V> callable, Predicate<SSTableReader> sstablesPredicate, OperationType operationType, boolean interruptValidation, boolean interruptViews, boolean interruptIndexes)",
        "CompactionManager.CompactionPauser pause = CompactionManager.instance.pauseGlobalCompaction();",
    ),
    NODETOOL_STOP: (
        "@Command(name = \"stop\", description = \"Stop compaction\")",
        "private OperationType compactionType = OperationType.UNKNOWN;",
        "name = {\"-id\", \"--compaction-id\"}",
        "probe.stopById(compactionId);",
        "probe.stop(compactionType.name());",
    ),
    NODE_PROBE: (
        "public void stop(String string)",
        "compactionProxy.stopCompaction(string);",
        "public void stopById(String compactionId)",
        "compactionProxy.stopCompactionById(compactionId);",
    ),
    NODETOOL_COMPACTION_STATS: (
        "@Command(name = \"compactionstats\", description = \"Print statistics on compactions\")",
        "name = {\"-V\", \"--vtable\"}",
        "probe.getCompactionManagerProxy().getCompactions()",
        "if (vtableOutput)",
        "table.add(\"keyspace\", \"table\", \"task id\", \"completion ratio\", \"kind\", \"progress\", \"sstables\", \"total\", \"total compressed\", \"unit\", \"target directory\");",
        "String id = c.get(CompactionInfo.COMPACTION_ID);",
        "String targetDirectory = c.get(CompactionInfo.TARGET_DIRECTORY);",
        "table.add(id, taskType, keyspace, columnFamily, progressStr, totalStr, unit, percentComplete);",
    ),
    SSTABLE_TASKS_TABLE: (
        "final class SSTableTasksTable extends AbstractVirtualTable",
        ".comment(\"current sstable tasks\")",
        ".addClusteringColumn(TASK_ID, TimeUUIDType.instance)",
        ".addRegularColumn(TARGET_DIRECTORY, UTF8Type.instance)",
        "for (CompactionInfo task : CompactionManager.instance.getSSTableTasks())",
        "double completionRatio = total == 0L ? 1.0 : (((double) completed) / total);",
        ".column(KIND, task.getTaskType().toString().toLowerCase())",
        ".column(TARGET_DIRECTORY, task.targetDirectory());",
    ),
    COMPACTION_METRICS: (
        "factory.createMetricName(\"TotalCompactionsCompleted\")",
        "factory.createMetricName(\"BytesCompacted\")",
        "factory.createMetricName(\"CompressedBytesCompacted\")",
        "factory.createMetricName(\"CompactionsReduced\")",
        "factory.createMetricName(\"SSTablesDroppedFromCompaction\")",
        "factory.createMetricName(\"CompactionsAborted\")",
    ),
}

TEST_TOKEN_CHECKS = {
    ACTIVE_COMPACTIONS_TEST: (
        "testActiveCompactionTrackingRaceWithIndexBuilder",
        "CompactionManager.instance.active.getCompactionsForSSTable(null, null);",
        "testSecondaryIndexTracking",
        "CompactionManager.instance.submitIndexBuild(builder, mockActiveCompactions).get();",
        "testIndexSummaryRedistributionTracking",
        "assertTrue(mockActiveCompactions.holder.getCompactionInfo().getSSTables().isEmpty());",
        "assertTrue(mockActiveCompactions.holder.getCompactionInfo().shouldStop((sstable) -> false));",
        "testViewBuildTracking",
    ),
    COMPACTION_STATS_TEST: (
        "public void testCompactionStats()",
        "public void testCompactionStatsVtable()",
        "public void testCompactionStatsHumanReadable()",
        "public void testCompactionStatsVtableHumanReadable()",
        "assertThat(stdout).containsPattern(\"keyspace\\\\s+table\\\\s+task id\\\\s+completion ratio\\\\s+kind\\\\s+progress\\\\s+sstables\\\\s+total\\\\s+total compressed\\\\s+unit\\\\s+target directory\");",
        "waitForNumberOfPendingTasks(2, \"compactionstats\", \"-V\");",
        "CompactionManager.instance.active.beginCompaction(compactionHolder);",
        "CompactionManager.instance.active.finishCompaction(compactionHolder);",
    ),
    SSTABLE_TASKS_TABLE_TEST: (
        "private SSTableTasksTable table;",
        "TimeUUID compactionId = nextTimeUUID();",
        "CompactionManager.instance.active.beginCompaction(compactionHolder);",
        "UntypedResultSet result = execute(\"SELECT * FROM vts.sstable_tasks\");",
        "assertRows(result, row(CQLTester.KEYSPACE, currentTable(), compactionId",
        "CompactionManager.instance.active.finishCompaction(compactionHolder);",
        "assertEmpty(result);",
    ),
    COMPACTION_ITERATOR_TEST: (
        "public void transformTest()",
        "iter.stop();",
        "fail(\"Should have thrown CompactionInterruptedException\");",
        "public void transformPartitionTest()",
    ),
    SECONDARY_INDEX_COMPACTION_TEST: (
        "public void test2iCompaction()",
        "CompactionManager.instance.active.beginCompaction(h);",
        "CompactionManager.instance.active.estimatedRemainingWriteToDiskBytes();",
        "CompactionManager.instance.active.finishCompaction(h);",
    ),
    UPGRADE_SSTABLES_TEST: (
        "new ByteBuddy().rebase(ActiveCompactions.class)",
        "if (ci.getCompactionInfo().getTaskType() == OperationType.UPGRADE_SSTABLES)",
        "if (ci.getCompactionInfo().getTaskType() == OperationType.COMPACTION)",
    ),
}

DOC_REQUIRED_TOKENS = (
    "ActiveCompactions",
    "CompactionInfo.Holder",
    "CompactionInfo.asMap",
    "stopCompactionById",
    "stopCompaction(String",
    "CompactionInterruptedException",
    "OperationType",
    "nodetool stop",
    "--compaction-id",
    "compactionstats -V",
    "SSTableTasksTable",
    "system_views.sstable_tasks",
    "estimatedRemainingWriteToDiskBytes",
    "BytesCompacted",
    "CompressedBytesCompacted",
    "TotalCompactionsCompleted",
    "ActiveCompactionsTest",
    "CompactionStatsTest",
    "SSTableTasksTableTest",
    "CompactionIteratorTest",
    "SecondaryIndexCompactionTest",
    "UpgradeSSTablesTest",
    "compaction_live_cancel_metrics_gap",
    "research/tools/check-compaction-control-observability-drift.py",
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

    matrix_path = "research/module-compaction-control-observability-matrix.md"
    checker_doc_path = "research/module-compaction-control-observability-drift-checker.md"
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
            "module-compaction-control-observability-matrix.md",
            "module-compaction-control-observability-drift-checker.md",
            "research/tools/check-compaction-control-observability-drift.py",
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
        print("Compaction control/observability drift check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- [{failure.category}] {failure.path}: missing {failure.token!r}", file=sys.stderr)
    else:
        print(
            "OK Compaction control/observability drift checks passed "
            f"({counts['source_checks']} source checks, "
            f"{counts['test_checks']} test checks, "
            f"{counts['doc_checks']} doc checks, "
            f"{counts['scenario_ids']} scenarios)"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
