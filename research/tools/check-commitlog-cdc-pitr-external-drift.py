#!/usr/bin/env python3
#
# Source/test/doc drift check for CommitLog CDC/PITR external integration research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

COMMITLOG = "src/java/org/apache/cassandra/db/commitlog/CommitLog.java"
SEGMENT_MANAGER_CDC = "src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java"
SEGMENT = "src/java/org/apache/cassandra/db/commitlog/CommitLogSegment.java"
ARCHIVER = "src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java"
REPLAYER = "src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java"
COMMITLOG_MBEAN = "src/java/org/apache/cassandra/db/commitlog/CommitLogMBean.java"
COMMITLOG_METRICS = "src/java/org/apache/cassandra/metrics/CommitLogMetrics.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
MUTATION = "src/java/org/apache/cassandra/db/Mutation.java"
TABLE_ATTRIBUTES = "src/java/org/apache/cassandra/cql3/statements/schema/TableAttributes.java"
STREAM_RECEIVER = "src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java"
ARCHIVING_PROPERTIES = "conf/commitlog_archiving.properties"

CDC_STATEMENT_TEST = "test/unit/org/apache/cassandra/cql3/CDCStatementTest.java"
CDC_MANAGER_TEST = "test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDCTest.java"
ARCHIVER_TEST = "test/unit/org/apache/cassandra/db/commitlog/CommitLogArchiverTest.java"
CDC_REPAIR_TEST = "test/distributed/org/apache/cassandra/distributed/test/cdc/ToggleCDCOnRepairEnabledTest.java"
COMMITLOG_TEST = "test/unit/org/apache/cassandra/db/commitlog/CommitLogTest.java"
COMMITLOG_READER_TEST = "test/unit/org/apache/cassandra/db/commitlog/CommitLogReaderTest.java"

TARGET_DOCS = (
    "research/module-commitlog-cdc-pitr-runbook.md",
    "research/module-commitlog-durability-replay-matrix.md",
    "research/module-commitlog-cdc-pitr-external-integration-matrix.md",
    "research/module-commitlog-cdc-pitr-external-drift-checker.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "commitlog_external_cdc_table_marking_contract",
    "commitlog_external_cdc_segment_state_contract",
    "commitlog_external_cdc_index_watermark_contract",
    "commitlog_external_cdc_space_backpressure_contract",
    "commitlog_external_cdc_consumer_delete_contract",
    "commitlog_external_cdc_replay_rebuild_contract",
    "commitlog_external_cdc_repair_streaming_contract",
    "commitlog_external_archiver_command_contract",
    "commitlog_external_restore_command_contract",
    "commitlog_external_pitr_cutoff_contract",
    "commitlog_external_replay_filter_snapshot_contract",
    "commitlog_external_observability_contract",
    "commitlog_external_cdc_consumer_gap",
    "commitlog_external_pitr_rehearsal_gap",
    "commitlog_external_existing_tests_baseline",
)

SOURCE_TOKEN_CHECKS = {
    TABLE_ATTRIBUTES: (
        "builder.cdc(getBoolean(CDC));",
        "CDC",
    ),
    MUTATION: (
        "private final boolean cdcEnabled;",
        "private static boolean cdcEnabled(Iterable<PartitionUpdate> modifications)",
        "cdc |= pu.metadata().params.cdc;",
        "public boolean trackedByCDC()",
        "return cdcEnabled;",
    ),
    SEGMENT_MANAGER_CDC: (
        "public class CommitLogSegmentManagerCDC extends AbstractCommitLogSegmentManager",
        "public long deleteOldLinkedCDCCommitLogSegment(long bytesToFree)",
        "File[] files = cdcDir.tryList(f -> CommitLogDescriptor.isValid(f.name()));",
        "File cdcIndexFile = CommitLogDescriptor.inferCdcIndexFile(linkedCdcFile);",
        "public CommitLogSegment.Allocation allocate(Mutation mutation, int size) throws CDCWriteException",
        "permitSegmentMaybe(segment);",
        "throwIfForbidden(mutation, segment);",
        "segment.setCDCState(CDCState.CONTAINS);",
        "private void permitSegmentMaybe(CommitLogSegment segment)",
        "FileUtils.createHardLink(segment.logFile, segment.getCDCFile());",
        "private void throwIfForbidden(Mutation mutation, CommitLogSegment segment) throws CDCWriteException",
        "if (mutation.trackedByCDC() && segment.getCDCState() == CDCState.FORBIDDEN)",
        "throw new CDCWriteException(logMsg);",
        "public CommitLogSegment createSegment()",
        "cdcSizeTracker.processNewSegment(segment);",
        "segment.setCDCState(blocking && segmentSize + sizeInProgress.get() > allowance",
        "long remainingSize = segmentManager.deleteOldLinkedCDCCommitLogSegment(bytesToFree);",
        "submitOverflowSizeRecalculation();",
        "private void calculateSize()",
        "public long updateCDCTotalSize()",
    ),
    SEGMENT: (
        "private CDCState cdcState = CDCState.PERMITTED;",
        "public enum CDCState",
        "PERMITTED",
        "FORBIDDEN",
        "CONTAINS",
        "if (cdcState == CDCState.CONTAINS)",
        "writeCDCIndexFile(descriptor, sectionEnd, close);",
        "public static void writeCDCIndexFile(CommitLogDescriptor desc, int offset, boolean complete)",
        "writer.write(String.valueOf(offset));",
        "writer.write(\"\\nCOMPLETED\");",
    ),
    ARCHIVER: (
        "public class CommitLogArchiver",
        "public static CommitLogArchiver construct()",
        "String archiveCommand = commitlogCommands.getProperty(\"archive_command\");",
        "String restoreCommand = commitlogCommands.getProperty(\"restore_command\");",
        "String restoreDirectories = commitlogCommands.getProperty(\"restore_directories\");",
        "String precisionPropertyValue = commitlogCommands.getProperty(\"precision\", TimeUnit.MICROSECONDS.name());",
        "String targetTime = commitlogCommands.getProperty(\"restore_point_in_time\");",
        "String snapshotPosition = commitlogCommands.getProperty(\"snapshot_commitlog_position\");",
        "public void maybeArchive(final CommitLogSegment segment)",
        "segment.waitForFinalSync();",
        "command = PATH.matcher(command).replaceAll(Matcher.quoteReplacement(segment.getPath()));",
        "public void maybeRestoreArchive()",
        "CommitLogDescriptor.fromHeader(fromFile, DatabaseDescriptor.getEncryptionContext());",
        "CommitLogDescriptor.isValid(fromFile.name()) ? CommitLogDescriptor.fromFileName(fromFile.name()) : null",
        "String command = FROM.matcher(restoreCommand).replaceAll(Matcher.quoteReplacement(fromFile.path()));",
        "command = TO.matcher(command).replaceAll(Matcher.quoteReplacement(toFile.path()));",
        "ProcessBuilder pb = new ProcessBuilder(command.split(\" \"));",
    ),
    COMMITLOG: (
        "public final CommitLogArchiver archiver;",
        "public int recoverSegmentsOnDisk() throws IOException",
        "archiver.maybeArchive(file.path(), file.name());",
        "archiver.maybeWaitForArchiving(file.name());",
        "archiver.maybeRestoreArchive();",
        "Arrays.sort(files, new CommitLogSegment.CommitLogSegmentFileComparator());",
        "public CommitLogPosition add(Mutation mutation) throws CDCWriteException",
        "Allocation alloc = segmentManager.allocate(mutation, totalSize);",
        "executor.finishWriteFor(alloc);",
        "public void discardCompletedSegments(final TableId id, final CommitLogPosition lowerBound, final CommitLogPosition upperBound)",
        "segmentManager.archiveAndDiscard(segment);",
    ),
    REPLAYER: (
        "public static CommitLogReplayer construct(CommitLog commitLog, UUID localHostId)",
        "ReplayFilter replayFilter = ReplayFilter.create();",
        "final CommitLogPosition snapshotPosition = commitLog.archiver.snapshotCommitLogPosition;",
        "filter = new IntervalSet<>(CommitLogPosition.NONE, snapshotPosition);",
        "Keyspace.open(newPUCollector.getKeyspaceName()).apply(newPUCollector.build(), false, true, false);",
        "abstract static class ReplayFilter",
        "String replayList = COMMIT_LOG_REPLAY_LIST.getString();",
        "private static class AlwaysReplayFilter extends ReplayFilter",
        "private static class CustomReplayFilter extends ReplayFilter",
        "protected boolean pointInTimeExceeded(Mutation fm)",
        "if (archiver.precision.toMicros(upd.maxTimestamp()) > archiver.restorePointInTimeInMicroseconds)",
        "public void handleMutation(Mutation m, int size, int entryLocation, CommitLogDescriptor desc)",
        "if (DatabaseDescriptor.isCDCEnabled() && m.trackedByCDC())",
    ),
    STREAM_RECEIVER: (
        "private boolean cdcRequiresWriteCommitLog(ColumnFamilyStore cfs)",
        "return cfs.metadata().params.cdc;",
        "boolean writeCDCCommitLog = cdcRequiresWriteCommitLog(cfs);",
        "return cdcRequiresWriteCommitLog(cfs)",
        "so they get archived into the cdc_raw folder",
    ),
    COMMITLOG_MBEAN: (
        "public String getArchiveCommand();",
        "public String getRestoreCommand();",
        "public String getRestoreDirectories();",
        "public long getRestorePointInTime();",
        "public String getRestorePrecision();",
        "public List<String> getArchivingSegmentNames();",
        "public boolean getCDCBlockWrites();",
        "public void setCDCBlockWrites(boolean val);",
        "boolean isCDCOnRepairEnabled();",
        "void setCDCOnRepairEnabled(boolean value);",
    ),
    COMMITLOG_METRICS: (
        'public static final MetricNameFactory factory = new DefaultNameFactory("CommitLog");',
        "waitingOnSegmentAllocation = Metrics.timer(factory.createMetricName(\"WaitingOnSegmentAllocation\"));",
        "waitingOnCommit = Metrics.timer(factory.createMetricName(\"WaitingOnCommit\"));",
        "waitingOnFlush = Metrics.timer(factory.createMetricName(\"WaitingOnFlush\"));",
        "totalCommitLogSize = Metrics.register(factory.createMetricName(\"TotalCommitLogSize\"), new Gauge<Long>()",
        "pendingTasks = Metrics.register(factory.createMetricName(\"PendingTasks\"), new Gauge<Long>()",
        "completedTasks = Metrics.register(factory.createMetricName(\"CompletedTasks\"), new Gauge<Long>()",
    ),
    CONFIG: (
        "public String commitlog_directory;",
        "public boolean cdc_enabled = false;",
        "public volatile boolean cdc_block_writes = true;",
        "public volatile boolean cdc_on_repair_enabled = true;",
        "public String cdc_raw_directory;",
        "public DataStorageSpec.IntMebibytesBound cdc_total_space",
        "public DurationSpec.IntMillisecondsBound cdc_free_space_check_interval",
    ),
    DATABASE_DESCRIPTOR: (
        "public static boolean isCDCEnabled()",
        "public static boolean getCDCBlockWrites()",
        "public static boolean isCDCOnRepairEnabled()",
        "? new CommitLogSegmentManagerCDC(c, DatabaseDescriptor.getCommitLogLocation())",
        "conf.cdc_raw_directory = storagedirFor(\"cdc_raw\");",
    ),
    ARCHIVING_PROPERTIES: (
        "archive_command=",
        "restore_command=",
        "restore_directories=",
        "restore_point_in_time=",
        "snapshot_commitlog_position=",
        "precision=MICROSECONDS",
    ),
}

TEST_TOKEN_CHECKS = {
    CDC_STATEMENT_TEST: (
        "WITH cdc = true",
        "ALTER TABLE %s WITH cdc = true;",
        "ALTER TABLE %s WITH cdc = false;",
    ),
    CDC_MANAGER_TEST: (
        "public void testCDCWriteFailure()",
        "Simulate a CDC consumer reading files then deleting them",
        "expectCurrentCDCState(CDCState.FORBIDDEN);",
        "expectCurrentCDCState(CDCState.PERMITTED);",
        "public void testNonblockingShouldMaintainSteadyDiskUsage()",
        "public void testSwitchingCDCWriteModes()",
        "public void testCDCIndexFileWriteOnSync()",
        "The offset read from CDC index file should be equal or larger than the offset after sync",
        "public void testCompletedFlag()",
        "Expected COMPLETED in index file",
        "public void testDeleteLinkOnDiscardNoCDC()",
        "public void testRetainLinkOnDiscardCDC()",
        "public void testReplayLogic()",
        "Expected non-zero number of files in CDC folder after restart.",
        "New CDC index file expected to have >= offset in old.",
    ),
    ARCHIVER_TEST: (
        "public void testArchiver()",
        "public void testRestoreInDifferentPrecision()",
        "CommitLog.instance.archiver.maybeRestoreArchive();",
        "CommitLog.instance.recoverFiles(CommitLog.instance.getUnmanagedFiles());",
        "CommitLog.instance.archiver.setPrecision(TimeUnit.MILLISECONDS);",
    ),
    CDC_REPAIR_TEST: (
        "public void testCDCOnRepairIsEnabled()",
        "assertTrue(\"Mutation should be added to commit log when cdc_on_repair_enabled is true\"",
        "public void testCDCOnRepairIsDisabled()",
        "assertTrue(\"No mutation should be added to commit log when cdc_on_repair_enabled is false\"",
        ".set(\"cdc_enabled\", true)",
        ".set(\"cdc_on_repair_enabled\", enabled)",
    ),
    COMMITLOG_TEST: (
        "testReplayListProperty",
        "COMMIT_LOG_REPLAY_LIST",
    ),
    COMMITLOG_READER_TEST: (
        "public class CommitLogReaderTest",
        "CommitLogReader",
    ),
}

DOC_REQUIRED_TOKENS = (
    "research/tools/check-commitlog-cdc-pitr-external-drift.py",
    "research/module-commitlog-cdc-pitr-external-integration-matrix.md",
    "research/module-commitlog-cdc-pitr-external-drift-checker.md",
    "CommitLogSegmentManagerCDC",
    "CommitLogSegment",
    "CommitLogArchiver",
    "CommitLogReplayer",
    "CommitLogMBean",
    "CommitLogMetrics",
    "cdc_raw",
    "_cdc.idx",
    "archive_command",
    "restore_point_in_time",
    "commitlog_external_cdc_consumer_gap",
    "commitlog_external_pitr_rehearsal_gap",
)

CONFIG_SUFFIXES = {
    ".conf",
    ".config",
    ".json",
    ".properties",
    ".sh",
    ".toml",
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

KNOWN_SAMPLE_FILES = {
    "conf/commitlog_archiving.properties",
    "test/conf/commitlog_archiving.properties",
}

CDC_CONNECTOR_FILE_MARKERS = (
    "cdc-connector",
    "cdc_connector",
    "cdc-consumer",
    "cdc_consumer",
    "commitlog-consumer",
    "commitlog_consumer",
    "debezium",
    "kafka-connect",
    "kafka_connect",
)

CDC_CONNECTOR_CONTENT_MARKERS = (
    ("external cdc connector", ("debezium",)),
    ("kafka connect cdc", ("kafka", "connect", "cdc")),
    ("cdc raw checkpoint consumer", ("cdc_raw", "checkpoint", "consumer")),
    ("cdc idx checkpoint consumer", ("_cdc.idx", "checkpoint", "consumer")),
    ("commitlog consumer sink", ("commitlog", "consumer", "sink")),
)

PITR_REHEARSAL_FILE_MARKERS = (
    "commitlog-archive",
    "commitlog_archive",
    "commitlog-restore",
    "commitlog_restore",
    "pitr",
    "restore-rehearsal",
    "restore_rehearsal",
)

PITR_REHEARSAL_CONTENT_MARKERS = (
    ("pitr rehearsal", ("restore_point_in_time", "archive_command", "restore_command", "rehearsal")),
    ("pitr dry run", ("restore_point_in_time", "archive_command", "restore_command", "dry-run")),
    ("object store commitlog restore", ("restore_point_in_time", "commitlog", "s3")),
    ("object store commitlog restore", ("restore_point_in_time", "commitlog", "gsutil")),
    ("object store commitlog restore", ("restore_point_in_time", "commitlog", "rclone")),
    ("backup script commitlog archive", ("archive_command", "commitlog", "backup script")),
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


def candidate_files() -> list[Path]:
    files = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        relative = str(path.relative_to(REPO_ROOT))
        if relative in KNOWN_SAMPLE_FILES:
            continue
        files.append(path)
    return files


def marker_hits(path: Path, marker_sets: tuple[tuple[str, tuple[str, ...]], ...]) -> list[str]:
    if path.suffix.lower() not in CONFIG_SUFFIXES:
        return []
    text = path.read_text(encoding="utf-8", errors="ignore").lower()
    hits = []
    for label, markers in marker_sets:
        if all(marker in text for marker in markers):
            hits.append(label)
    return hits


def external_gap_checks() -> list[Check]:
    cdc_hits = []
    pitr_hits = []

    for path in candidate_files():
        relative = str(path.relative_to(REPO_ROOT))
        lower_relative = relative.lower()
        lower_name = path.name.lower()

        if any(marker in lower_relative or marker in lower_name for marker in CDC_CONNECTOR_FILE_MARKERS):
            cdc_hits.append(relative)
        else:
            cdc_hits.extend(f"{relative} ({label})" for label in marker_hits(path, CDC_CONNECTOR_CONTENT_MARKERS))

        if any(marker in lower_relative or marker in lower_name for marker in PITR_REHEARSAL_FILE_MARKERS):
            pitr_hits.append(relative)
        else:
            pitr_hits.extend(f"{relative} ({label})" for label in marker_hits(path, PITR_REHEARSAL_CONTENT_MARKERS))

    return [
        Check(
            "gap still open: no source-owned external CDC connector or checkpoint consumer integration",
            "repository CDC connector/consumer files",
            not cdc_hits,
        ),
        Check(
            "gap still open: no source-owned PITR backup-system rehearsal or restore dry-run config",
            "repository PITR rehearsal files",
            not pitr_hits,
        ),
    ]


def doc_checks() -> list[Check]:
    docs = {path: read(path) for path in TARGET_DOCS}
    combined = "\n".join(docs.values())
    checks = [Check(f"target doc exists {path}", path, bool(text.strip())) for path, text in docs.items()]
    checks.extend(Check(f"doc token {token}", "research", token in combined) for token in DOC_REQUIRED_TOKENS)

    matrix = docs["research/module-commitlog-cdc-pitr-external-integration-matrix.md"]
    drift_doc = docs["research/module-commitlog-cdc-pitr-external-drift-checker.md"]
    for scenario in SCENARIO_IDS:
        checks.append(Check(f"scenario coverage {scenario}", "research", scenario in matrix and scenario in drift_doc))

    return checks


def run_checks() -> list[Check]:
    return source_checks() + test_checks() + external_gap_checks() + doc_checks()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check CommitLog CDC/PITR external integration research drift.")
    parser.add_argument("--json", action="store_true", help="Emit check results as JSON.")
    args = parser.parse_args()

    checks = run_checks()
    failures = [check for check in checks if not check.ok]

    if args.json:
        print(json.dumps([check.__dict__ for check in checks], indent=2, sort_keys=True))

    if failures:
        if not args.json:
            print("FAILED CommitLog CDC/PITR external drift checks:", file=sys.stderr)
            for check in failures:
                print(f"- {check.name} ({check.path})", file=sys.stderr)
        return 1

    if not args.json:
        print(
            "OK CommitLog CDC/PITR external drift checks passed "
            f"({len(SOURCE_TOKEN_CHECKS)} source files, "
            f"{len(TEST_TOKEN_CHECKS)} test files, "
            f"{len(TARGET_DOCS)} docs, "
            f"{len(SCENARIO_IDS)} scenarios)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
