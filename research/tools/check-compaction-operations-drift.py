#!/usr/bin/env python3
#
# Source/test/doc drift check for compaction operations and failure matrix research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

COMPACTION_MANAGER = "src/java/org/apache/cassandra/db/compaction/CompactionManager.java"
COMPACTION_STRATEGY_MANAGER = "src/java/org/apache/cassandra/db/compaction/CompactionStrategyManager.java"
COMPACTION_TASK = "src/java/org/apache/cassandra/db/compaction/CompactionTask.java"
COMPACTION_ITERATOR = "src/java/org/apache/cassandra/db/compaction/CompactionIterator.java"
COMPACTION_PARAMS = "src/java/org/apache/cassandra/schema/CompactionParams.java"
COMPACTION_METRICS = "src/java/org/apache/cassandra/metrics/CompactionMetrics.java"
COMPACTION_MANAGER_MBEAN = "src/java/org/apache/cassandra/db/compaction/CompactionManagerMBean.java"
CFS_MBEAN = "src/java/org/apache/cassandra/db/ColumnFamilyStoreMBean.java"
CFS = "src/java/org/apache/cassandra/db/ColumnFamilyStore.java"
DIRECTORIES = "src/java/org/apache/cassandra/db/Directories.java"
ACTIVE_COMPACTIONS = "src/java/org/apache/cassandra/db/compaction/ActiveCompactions.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
NODE_PROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
NODETOOL_COMPACT = "src/java/org/apache/cassandra/tools/nodetool/Compact.java"
NODETOOL_FORCECOMPACT = "src/java/org/apache/cassandra/tools/nodetool/ForceCompact.java"
NODETOOL_STOP = "src/java/org/apache/cassandra/tools/nodetool/Stop.java"
NODETOOL_SET_THROUGHPUT = "src/java/org/apache/cassandra/tools/nodetool/SetCompactionThroughput.java"
NODETOOL_AUTO_DISABLE = "src/java/org/apache/cassandra/tools/nodetool/DisableAutoCompaction.java"
NODETOOL_AUTO_ENABLE = "src/java/org/apache/cassandra/tools/nodetool/EnableAutoCompaction.java"
NODETOOL_AUTO_STATUS = "src/java/org/apache/cassandra/tools/nodetool/StatusAutoCompaction.java"

COMPACTION_DISK_SPACE_TEST = "test/distributed/org/apache/cassandra/distributed/test/CompactionDiskSpaceTest.java"
COMPACTION_TASK_TEST = "test/unit/org/apache/cassandra/db/compaction/CompactionTaskTest.java"
COMPACTION_STRATEGY_MANAGER_TEST = "test/unit/org/apache/cassandra/db/compaction/CompactionStrategyManagerTest.java"
COMPACTION_ITERATOR_TEST = "test/unit/org/apache/cassandra/db/compaction/CompactionIteratorTest.java"
COMPACTION_STATS_TEST = "test/unit/org/apache/cassandra/tools/nodetool/CompactionStatsTest.java"
COMPACT_TEST = "test/unit/org/apache/cassandra/tools/nodetool/CompactTest.java"
STCS_TEST = "test/unit/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategyTest.java"
LCS_TEST = "test/unit/org/apache/cassandra/db/compaction/LeveledCompactionStrategyTest.java"
TWCS_TEST = "test/unit/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategyTest.java"
UCS_TEST = "test/unit/org/apache/cassandra/db/compaction/UnifiedCompactionStrategyTest.java"
UCS_CONTROLLER_TEST = "test/unit/org/apache/cassandra/db/compaction/unified/ControllerTest.java"
UCS_DENSITIES_TEST = "test/distributed/org/apache/cassandra/distributed/test/UnifiedCompactionDensitiesTest.java"

TARGET_DOCS = (
    "research/module-sstable-compaction.md",
    "research/module-compaction-strategies-deep-dive.md",
    "research/module-compaction-operations-failure-matrix.md",
    "research/module-compaction-operations-drift-checker.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "compaction_background_scheduler_backpressure",
    "compaction_strategy_manager_repair_promotion",
    "compaction_strategy_params_validation",
    "compaction_task_snapshot_space_reduction",
    "compaction_iterator_purge_index_cache",
    "compaction_rate_limit_bootstrap_boundary",
    "compaction_auto_upgrade_boundary",
    "compaction_metrics_observability",
    "compaction_jmx_nodetool_surface",
    "compaction_strategy_tuning_matrix",
    "compaction_disk_space_failure_coverage",
    "compaction_existing_tests_baseline",
)

SOURCE_TOKEN_CHECKS = {
    COMPACTION_MANAGER: (
        "public static final String MBEAN_OBJECT_NAME = \"org.apache.cassandra.db:type=CompactionManager\";",
        "private final RateLimiter compactionRateLimiter = RateLimiter.create(Double.MAX_VALUE);",
        "public RateLimiter getRateLimiter()",
        "setRateInBytes(DatabaseDescriptor.getCompactionThroughputBytesPerSec());",
        "if (throughput == 0 || StorageService.instance.isBootstrapMode())",
        "throughput = Double.MAX_VALUE;",
        "public List<Future<?>> submitBackground(final ColumnFamilyStore cfs)",
        "if (cfs.isAutoCompactionDisabled())",
        "int count = compactingCF.count(cfs);",
        "executor.getActiveTaskCount() >= executor.getMaximumPoolSize()",
        "executor.submitIfRunning(new BackgroundCompactionCandidate(cfs), \"background task\")",
        "class BackgroundCompactionCandidate implements Runnable",
        "strategy.getNextBackgroundTask(getDefaultGcBefore(cfs, FBUtilities.nowInSeconds()))",
        "if (DatabaseDescriptor.automaticSSTableUpgrade())",
        "boolean maybeRunUpgradeTask(CompactionStrategyManager strategy)",
        "currentlyBackgroundUpgrading.incrementAndGet() <= DatabaseDescriptor.maxConcurrentAutoUpgradeTasks()",
        "AbstractCompactionTask upgradeTask = strategy.findUpgradeSSTableTask();",
        "private AllSSTableOpStatus parallelAllSSTableOperation",
        "public void incrementAborted()",
        "public void incrementCompactionsReduced()",
        "public void incrementSstablesDropppedFromCompactions(long num)",
        "public void stopCompaction(String type)",
        "public void stopCompactionById(String compactionId)",
    ),
    COMPACTION_STRATEGY_MANAGER: (
        "public AbstractCompactionTask getNextBackgroundTask(long gcBefore)",
        "maybeReloadDiskBoundaries();",
        "if (!isEnabled())",
        "pendingRepairs.getNextRepairFinishedTask();",
        "transientRepairs.getNextRepairFinishedTask();",
        "holder.getBackgroundTaskSuppliers(gcBefore)",
        "Collections.sort(suppliers);",
        "AbstractCompactionTask findUpgradeSSTableTask()",
        "if (!isEnabled() || !DatabaseDescriptor.automaticSSTableUpgrade())",
        "cfs.getTracker().tryModify(sstable, OperationType.UPGRADE_SSTABLES)",
        "public void pause()",
        "public void resume()",
        "private void startup()",
        "private void reloadParamsFromSchema(CompactionParams newParams)",
    ),
    COMPACTION_TASK: (
        "if (DatabaseDescriptor.isSnapshotBeforeCompaction())",
        "controller.getFullyExpiredSSTables();",
        "buildCompactionCandidatesForAvailableDiskSpace(fullyExpiredSSTables, taskId)",
        "RateLimiter limiter = CompactionManager.instance.getRateLimiter();",
        "CompactionIterator ci = new CompactionIterator(compactionType, scanners.scanners, controller, nowInSec, taskId)",
        "activeCompactions.beginCompaction(ci);",
        "if (!controller.cfs.getCompactionStrategyManager().isActive())",
        "throw new CompactionInterruptedException(ci.getCompactionInfo());",
        "writer.finish();",
        "SystemKeyspace.updateCompactionHistory",
        "cfs.metric.compactionBytesWritten.inc",
        "cfs.isCompactionDiskSpaceCheckEnabled()",
        "CompactionManager.instance.active.estimatedRemainingWriteToDiskBytes();",
        "cfs.getDirectories().hasDiskSpaceForCompactionsAndStreams(expectedNewWriteSize, expectedWriteSize)",
        "if (!reduceScopeForLimitedSpace(nonExpiredSSTables, writeSize))",
        "CompactionManager.instance.incrementAborted();",
        "CompactionManager.instance.incrementCompactionsReduced();",
        "CompactionManager.instance.incrementSstablesDropppedFromCompactions(sstablesRemoved);",
        "Attempting to compact pending repair sstables with sstables from other repair",
        "throw new RuntimeException(\"Attempting to compact transient sstables with non transient sstables\");",
    ),
    COMPACTION_ITERATOR: (
        "public class CompactionIterator extends CompactionInfo.Holder implements UnfilteredPartitionIterator",
        "this.activeCompactions.beginCompaction(this);",
        "merged = Transformation.apply(merged, new GarbageSkipper(controller));",
        "isPaxos(controller.cfs) && paxosStatePurging() != legacy",
        "? new PaxosPurger(nowInSec)",
        ": new Purger(controller, nowInSec);",
        "merged = DuplicateRowChecker.duringCompaction(merged, type);",
        "controller.cfs.indexManager.handles(IndexTransaction.Type.COMPACTION)",
        "controller.cfs.invalidateCachedPartition(key);",
        "activeCompactions.finishCompaction(this);",
        "private static class GarbageSkipper extends Transformation<UnfilteredRowIterator>",
        "private class PaxosPurger extends Transformation<UnfilteredRowIterator>",
        "throw new CompactionInterruptedException(abortableIter.iter.getCompactionInfo());",
    ),
    COMPACTION_PARAMS: (
        "public enum Option",
        "CLASS",
        "ENABLED",
        "MIN_THRESHOLD",
        "MAX_THRESHOLD",
        "PROVIDE_OVERLAPPING_TOMBSTONES",
        "public enum TombstoneOption",
        "public static final int DEFAULT_MIN_THRESHOLD = 4;",
        "public static final int DEFAULT_MAX_THRESHOLD = 32;",
        "boolean isEnabled = options.containsKey(Option.ENABLED.toString())",
        "supportsThresholdParams(klass)",
        "public void validate()",
        "klass.getMethod(\"validateOptions\", Map.class).invoke(null, options);",
        "Disabling compaction by setting compaction thresholds to 0 has been removed",
        "public static Class<? extends AbstractCompactionStrategy> classFromName(String name)",
    ),
    COMPACTION_METRICS: (
        "factory.createMetricName(\"PendingTasks\")",
        "CompactionManager.instance.active.getCompactions().size()",
        "factory.createMetricName(\"PendingTasksByTableName\")",
        "factory.createMetricName(\"CompletedTasks\")",
        "factory.createMetricName(\"TotalCompactionsCompleted\")",
        "factory.createMetricName(\"BytesCompacted\")",
        "factory.createMetricName(\"CompressedBytesCompacted\")",
        "factory.createMetricName(\"CompactionsReduced\")",
        "factory.createMetricName(\"SSTablesDroppedFromCompaction\")",
        "factory.createMetricName(\"CompactionsAborted\")",
        "factory.createMetricName(\"IndexSummaryRedistributionTime\")",
    ),
    COMPACTION_MANAGER_MBEAN: (
        "public List<Map<String, String>> getCompactions();",
        "public List<String> getCompactionSummary();",
        "public TabularData getCompactionHistory();",
        "public void forceUserDefinedCompaction(String dataFiles);",
        "public void forceUserDefinedCleanup(String dataFiles);",
        "public void stopCompaction(String type);",
        "public void stopCompactionById(String compactionId);",
        "public void setCoreCompactorThreads(int number);",
        "public boolean getAutomaticSSTableUpgradeEnabled();",
        "public void setMaxConcurrentAutoUpgradeTasks(int value);",
    ),
    CFS_MBEAN: (
        "public void forceMajorCompaction",
        "public void forceCompactionForTokenRange",
        "public void forceCompactionForTokenRanges",
        "public Map<String, String> getCompactionParameters();",
        "public void setCompactionParametersJson(String options);",
        "public boolean isAutoCompactionDisabled();",
        "public boolean isCompactionDiskSpaceCheckEnabled();",
        "public void compactionDiskSpaceCheck(boolean enable);",
    ),
    CFS: (
        "public boolean isCompactionDiskSpaceCheckEnabled()",
        "public void compactionDiskSpaceCheck(boolean enable)",
    ),
    DIRECTORIES: (
        "public boolean hasDiskSpaceForCompactionsAndStreams(Map<File, Long> expectedNewWriteSizes,",
        "public static boolean hasDiskSpaceForCompactionsAndStreams(Map<FileStore, Long> totalToWrite)",
        "FileStoreUtils.tryGetSpace(fileStore, FileStore::getUsableSpace",
        "DatabaseDescriptor.getMaxSpaceForCompactionsPerDrive()",
    ),
    ACTIVE_COMPACTIONS: (
        "public Map<File, Long> estimatedRemainingWriteToDiskBytes()",
        "compactionInfo.estimatedRemainingWriteToDiskBytes()",
    ),
    CONFIG: (
        "public boolean snapshot_before_compaction = false;",
        "public volatile Integer concurrent_compactors;",
        "public volatile DataRateSpec.LongBytesPerSecondBound compaction_throughput",
        "public DataStorageSpec.IntMebibytesBound min_free_space_per_drive",
        "public volatile Double max_space_usable_for_compactions_in_percentage = .95;",
        "public volatile DataStorageSpec.IntMebibytesBound sstable_preemptive_open_interval",
        "public volatile boolean automatic_sstable_upgrade = false;",
        "public volatile int max_concurrent_automatic_sstable_upgrades = 1;",
        "public CorruptedTombstoneStrategy corrupted_tombstone_strategy = CorruptedTombstoneStrategy.disabled;",
        "public volatile int max_top_tombstone_partition_count = 10;",
        "public volatile long min_tracked_partition_tombstone_count = 5000;",
    ),
    DATABASE_DESCRIPTOR: (
        "conf.concurrent_compactors = Math.min(8, Math.max(2, Math.min(FBUtilities.getAvailableProcessors(), conf.data_file_directories.length)));",
        "if (conf.concurrent_compactors <= 0)",
        "if (conf.compaction_throughput.toMebibytesPerSecond() >= Integer.MAX_VALUE)",
        "public static double getCompactionThroughputBytesPerSec()",
        "public static boolean isSnapshotBeforeCompaction()",
        "public static boolean automaticSSTableUpgrade()",
        "public static int maxConcurrentAutoUpgradeTasks()",
        "validateMaxConcurrentAutoUpgradeTasksConf",
        "max_concurrent_automatic_sstable_upgrades can't be negative",
    ),
    NODE_PROBE: (
        "protected CompactionManagerMBean compactionProxy;",
        "compactionProxy = JMX.newMBeanProxy(mbeanServerConn, name, CompactionManagerMBean.class);",
        "public void forceUserDefinedCompaction(String datafiles)",
        "public void forceKeyspaceCompaction(boolean splitOutput, String keyspaceName, String... tableNames)",
        "public void forceKeyspaceCompactionForTokenRange",
        "public void forceKeyspaceCompactionForPartitionKey",
        "public void forceCompactionKeysIgnoringGcGrace",
        "public void disableAutoCompaction(String ks, String ... tables)",
        "public void enableAutoCompaction(String ks, String ... tableNames)",
        "public Map<String, Boolean> getAutoCompactionDisabled",
        "public void setCompactionThroughput(int value)",
        "public void stop(String string)",
        "public void stopById(String compactionId)",
        "public Object getCompactionMetric(String metricName)",
        "public TabularData getCompactionHistory()",
    ),
    NODETOOL_COMPACT: (
        "public class Compact extends NodeToolCmd",
        "private boolean splitOutput = false;",
        "private boolean userDefined = false;",
        "private String partitionKey = EMPTY;",
        "probe.forceUserDefinedCompaction(userDefinedFiles);",
        "probe.forceKeyspaceCompactionForTokenRange(keyspace, startToken, endToken, tableNames);",
        "probe.forceKeyspaceCompactionForPartitionKey(keyspace, partitionKey, tableNames);",
        "probe.forceKeyspaceCompaction(splitOutput, keyspace, tableNames);",
    ),
    NODETOOL_FORCECOMPACT: (
        "public class ForceCompact extends NodeToolCmd",
        "partitionKeysIgnoreGcGrace",
        "probe.forceCompactionKeysIgnoringGcGrace(keyspaceName, tableName, partitionKeysIgnoreGcGrace);",
    ),
    NODETOOL_STOP: (
        "private String compactionId = \"\";",
        "probe.stopById(compactionId);",
        "probe.stop(compactionType.name());",
    ),
    NODETOOL_SET_THROUGHPUT: (
        "public class SetCompactionThroughput extends NodeToolCmd",
        "probe.setCompactionThroughput(compactionThroughput);",
    ),
    NODETOOL_AUTO_DISABLE: (
        "public class DisableAutoCompaction extends NodeToolCmd",
        "probe.disableAutoCompaction(keyspace, tablenames);",
    ),
    NODETOOL_AUTO_ENABLE: (
        "public class EnableAutoCompaction extends NodeToolCmd",
        "probe.enableAutoCompaction(keyspace, tableNames);",
    ),
    NODETOOL_AUTO_STATUS: (
        "public class StatusAutoCompaction extends NodeToolCmd",
        "probe.getAutoCompactionDisabled(keyspace, tableNames);",
    ),
}

TEST_TOKEN_CHECKS = {
    COMPACTION_DISK_SPACE_TEST: (
        "public void testNoSpaceLeft()",
        "min_free_space_per_drive_in_mb",
        "Not enough space for compaction",
        "BB.estimatedRemaining.set(2000);",
        "BB.freeSpace.set(2000);",
        "cfs.forceMajorCompaction();",
        "estimatedRemainingWriteToDiskBytes()",
        "tryGetSpace(FileStore fileStore",
    ),
    COMPACTION_TASK_TEST: (
        "public void testTaskIdIsPersistedInCompactionHistory()",
        "SystemKeyspace.COMPACTION_HISTORY",
        "public void compactionInterruption()",
        "Expected CompactionInterruptedException",
        "public void testFullyExpiredSSTablesAreNotReleasedPrematurely()",
        "SSTableRewriter.class.getName()",
        "public void mixedSSTableFailure()",
        "Expected IllegalArgumentException",
        "public void testOfflineCompaction()",
        "public void testMajorCompactTask()",
    ),
    COMPACTION_STRATEGY_MANAGER_TEST: (
        "public void testAutomaticUpgradeConcurrency()",
        "DatabaseDescriptor.setAutomaticSSTableUpgradeEnabled(true);",
        "DatabaseDescriptor.setMaxConcurrentAutoUpgradeTasks(1);",
        "assertFalse(r.maybeRunUpgradeTask(mgr));",
        "public void testAutomaticUpgradeConcurrency2()",
        "public void testMutualExclusiveHolderClassification()",
        "public void groupSSTables()",
        "public void testCountsByBuckets()",
    ),
    COMPACTION_ITERATOR_TEST: (
        "public void testGcCompactionSupersedeLeft()",
        "public void testGcCompactionPartitionDeletion()",
        "CompactionIterator iter = new CompactionIterator(OperationType.COMPACTION",
        "public void transformTest()",
        "Should have thrown CompactionInterruptedException",
        "public void transformPartitionTest()",
        "public void duplicateRowsTest()",
        "DatabaseDescriptor.setSnapshotOnDuplicateRowDetection(true);",
    ),
    COMPACTION_STATS_TEST: (
        "public void testCompactionStats()",
        "CompactionManager.instance.active.beginCompaction(compactionHolder);",
        "concurrent compactors",
        "pending tasks",
        "compactions aborted",
        "compactions reduced",
        "sstables dropped from compaction",
        "compaction throughput \\\\(MiB/s\\\\)",
        "public void testCompactionStatsVtable()",
        "target directory",
    ),
    COMPACT_TEST: (
        "public void keyPresent()",
        "invokeNodetool(\"compact\", \"--partition\"",
        "public void keyNotPresent()",
        "public void tableNotFound()",
        "public void keyWrongType()",
    ),
    STCS_TEST: (
        "public void testOptionsValidation()",
        "bucket_low greater than bucket_high should be rejected",
        "public void testGetBuckets()",
        "public void testPrepBucket()",
    ),
    LCS_TEST: (
        "public void testGrouperLevels()",
        "public void testValidationMultipleSSTablePerLevel()",
        "public void testCompactionProgress()",
        "public void testDisableSTCSInL0()",
        "public void testReduceScopeL0L1()",
        "public void testNoHighLevelReduction()",
    ),
    TWCS_TEST: (
        "public void testOptionsValidation()",
        "public void testTimeWindows()",
        "public void testPrepBucket()",
        "public void testDropExpiredSSTables()",
        "public void testDropOverlappingExpiredSSTables()",
    ),
    UCS_TEST: (
        "public void testGetNextBackgroundTask",
        "public void testDropExpiredSSTables()",
    ),
    UCS_CONTROLLER_TEST: (
        "public void testValidateOptions()",
        "public void testScalingParameterConversion()",
        "Controller.validateOptions(options)",
    ),
    UCS_DENSITIES_TEST: (
        "public void testTargetSSTableSize1Node1Dir()",
        "public void testTargetSSTableSize2Nodes3Dirs()",
        "UnifiedCompactionStrategy",
        "forceCompact(KEYSPACE, \"tbl\")",
    ),
}

DOC_TOKEN_CHECKS = {
    "research/module-compaction-operations-failure-matrix.md": (
        "Compaction Operations Failure Matrix",
        "compaction_background_scheduler_backpressure",
        "compaction_strategy_manager_repair_promotion",
        "compaction_strategy_params_validation",
        "compaction_task_snapshot_space_reduction",
        "compaction_iterator_purge_index_cache",
        "compaction_rate_limit_bootstrap_boundary",
        "compaction_auto_upgrade_boundary",
        "compaction_metrics_observability",
        "compaction_jmx_nodetool_surface",
        "compaction_strategy_tuning_matrix",
        "compaction_disk_space_failure_coverage",
        "compaction_existing_tests_baseline",
        "CompactionsReduced",
        "SSTablesDroppedFromCompaction",
        "CompactionsAborted",
        "stop-by-id",
        "bootstrap limiter",
    ),
    "research/module-compaction-operations-drift-checker.md": (
        "check-compaction-operations-drift.py",
        "source/test/doc",
        "compaction_background_scheduler_backpressure",
        "compaction_disk_space_failure_coverage",
    ),
    "research/README.md": (
        "module-compaction-operations-failure-matrix.md",
        "module-compaction-operations-drift-checker.md",
        "check-compaction-operations-drift.py",
    ),
    "research/notes/source-map.md": (
        "Compaction operations/failure matrix",
        "check-compaction-operations-drift.py",
        "compaction_task_snapshot_space_reduction",
    ),
}


@dataclass(frozen=True)
class MissingToken:
    file_path: str
    token: str
    category: str


def read_text(relative_path):
    path = REPO_ROOT / relative_path
    if not path.exists():
        raise FileNotFoundError(relative_path)
    return path.read_text(encoding="utf-8")


def check_tokens(checks, category):
    missing = []
    for relative_path, tokens in checks.items():
        try:
            text = read_text(relative_path)
        except FileNotFoundError:
            missing.extend(MissingToken(relative_path, "<file missing>", category) for _ in [0])
            continue
        for token in tokens:
            if token not in text:
                missing.append(MissingToken(relative_path, token, category))
    return missing


def check_scenario_ids():
    missing = []
    for doc in TARGET_DOCS:
        try:
            text = read_text(doc)
        except FileNotFoundError:
            missing.append(MissingToken(doc, "<file missing>", "scenario"))
            continue
        if doc in (
            "research/module-compaction-operations-failure-matrix.md",
            "research/module-compaction-operations-drift-checker.md",
            "research/tools/check-compaction-operations-drift.py",
        ):
            required_ids = SCENARIO_IDS
        else:
            required_ids = ("compaction_task_snapshot_space_reduction", "compaction_disk_space_failure_coverage")
        for scenario_id in required_ids:
            if scenario_id not in text:
                missing.append(MissingToken(doc, scenario_id, "scenario"))
    return missing


def main():
    parser = argparse.ArgumentParser(description="Check compaction operations research drift.")
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    args = parser.parse_args()

    missing = []
    missing.extend(check_tokens(SOURCE_TOKEN_CHECKS, "source"))
    missing.extend(check_tokens(TEST_TOKEN_CHECKS, "test"))
    missing.extend(check_tokens(DOC_TOKEN_CHECKS, "doc"))
    missing.extend(check_scenario_ids())

    report = {
        "status": "ok" if not missing else "failed",
        "source_files": len(SOURCE_TOKEN_CHECKS),
        "test_files": len(TEST_TOKEN_CHECKS),
        "doc_files": len(DOC_TOKEN_CHECKS),
        "scenario_ids": len(SCENARIO_IDS),
        "missing": [missing_token.__dict__ for missing_token in missing],
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif missing:
        print("Compaction operations drift check failed:")
        for missing_token in missing:
            print(f"- [{missing_token.category}] {missing_token.file_path}: {missing_token.token}")
    else:
        total_checks = sum(len(tokens) for tokens in SOURCE_TOKEN_CHECKS.values())
        total_checks += sum(len(tokens) for tokens in TEST_TOKEN_CHECKS.values())
        total_checks += sum(len(tokens) for tokens in DOC_TOKEN_CHECKS.values())
        total_checks += len(SCENARIO_IDS) * 2 + 2 * (len(TARGET_DOCS) - 2)
        print(f"OK Compaction operations drift checks passed ({total_checks} checks, {len(SCENARIO_IDS)} scenarios)")

    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
