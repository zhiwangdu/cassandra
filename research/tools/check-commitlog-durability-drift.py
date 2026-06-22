#!/usr/bin/env python3
#
# Source/test/doc drift check for CommitLog durability, replay, CDC, and PITR research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

COMMITLOG = "src/java/org/apache/cassandra/db/commitlog/CommitLog.java"
COMMITLOG_MBEAN = "src/java/org/apache/cassandra/db/commitlog/CommitLogMBean.java"
ABSTRACT_SERVICE = "src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogService.java"
BATCH_SERVICE = "src/java/org/apache/cassandra/db/commitlog/BatchCommitLogService.java"
GROUP_SERVICE = "src/java/org/apache/cassandra/db/commitlog/GroupCommitLogService.java"
PERIODIC_SERVICE = "src/java/org/apache/cassandra/db/commitlog/PeriodicCommitLogService.java"
SEGMENT_MANAGER = "src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogSegmentManager.java"
SEGMENT_MANAGER_STANDARD = "src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerStandard.java"
SEGMENT_MANAGER_CDC = "src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java"
SEGMENT = "src/java/org/apache/cassandra/db/commitlog/CommitLogSegment.java"
READER = "src/java/org/apache/cassandra/db/commitlog/CommitLogReader.java"
READ_HANDLER = "src/java/org/apache/cassandra/db/commitlog/CommitLogReadHandler.java"
SEGMENT_READER = "src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentReader.java"
REPLAYER = "src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java"
DESCRIPTOR = "src/java/org/apache/cassandra/db/commitlog/CommitLogDescriptor.java"
ARCHIVER = "src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java"
COMPRESSED_SEGMENT = "src/java/org/apache/cassandra/db/commitlog/CompressedSegment.java"
ENCRYPTED_SEGMENT = "src/java/org/apache/cassandra/db/commitlog/EncryptedSegment.java"
DIRECT_IO_SEGMENT = "src/java/org/apache/cassandra/db/commitlog/DirectIOSegment.java"
MMAP_SEGMENT = "src/java/org/apache/cassandra/db/commitlog/MemoryMappedSegment.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
MUTATION = "src/java/org/apache/cassandra/db/Mutation.java"
TABLE_ATTRIBUTES = "src/java/org/apache/cassandra/cql3/statements/schema/TableAttributes.java"
STREAM_RECEIVER = "src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java"
COMMITLOG_METRICS = "src/java/org/apache/cassandra/metrics/CommitLogMetrics.java"
ARCHIVING_PROPERTIES = "conf/commitlog_archiving.properties"

COMMITLOG_TEST = "test/unit/org/apache/cassandra/db/commitlog/CommitLogTest.java"
COMMITLOG_READER_TEST = "test/unit/org/apache/cassandra/db/commitlog/CommitLogReaderTest.java"
COMMITLOG_BACKPRESSURE_TEST = "test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentBackpressureTest.java"
COMMITLOG_FAILURE_POLICY_TEST = "test/unit/org/apache/cassandra/db/commitlog/CommitLogFailurePolicyTest.java"
ABSTRACT_SERVICE_TEST = "test/unit/org/apache/cassandra/db/commitlog/AbstractCommitLogServiceTest.java"
BATCH_TEST = "test/unit/org/apache/cassandra/db/commitlog/BatchCommitLogTest.java"
GROUP_TEST = "test/unit/org/apache/cassandra/db/commitlog/GroupCommitLogTest.java"
CDC_MANAGER_TEST = "test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDCTest.java"
ARCHIVER_TEST = "test/unit/org/apache/cassandra/db/commitlog/CommitLogArchiverTest.java"
SEGMENT_READER_TEST = "test/unit/org/apache/cassandra/db/commitlog/SegmentReaderTest.java"
DIRECT_IO_TEST = "test/unit/org/apache/cassandra/db/commitlog/DirectIOSegmentTest.java"
DIRECT_IO_BYTEMAN_TEST = "test/unit/org/apache/cassandra/db/commitlog/DirectIOSegmentBytemanTest.java"
CDC_STATEMENT_TEST = "test/unit/org/apache/cassandra/cql3/CDCStatementTest.java"
CDC_REPAIR_TEST = "test/distributed/org/apache/cassandra/distributed/test/cdc/ToggleCDCOnRepairEnabledTest.java"
UPGRADE_TEST = "test/unit/org/apache/cassandra/db/commitlog/CommitLogUpgradeTest.java"
STRESS_TEST = "test/long/org/apache/cassandra/db/commitlog/CommitLogStressTest.java"

TARGET_DOCS = (
    "research/module-commitlog.md",
    "research/module-commitlog-deep-dive.md",
    "research/module-commitlog-cdc-pitr-runbook.md",
    "research/module-commitlog-durability-replay-matrix.md",
    "research/module-commitlog-durability-drift-checker.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "commitlog_append_record_crc",
    "commitlog_sync_strategy_modes",
    "commitlog_sync_lag_marker",
    "commitlog_segment_allocation_reclaim",
    "commitlog_segment_clean_discard",
    "commitlog_cdc_raw_backpressure",
    "commitlog_cdc_index_contract",
    "commitlog_cdc_replay_rebuild",
    "commitlog_cdc_repair_streaming",
    "commitlog_archiver_pitr_restore",
    "commitlog_replay_filter_pitr",
    "commitlog_reader_error_policy",
    "commitlog_format_compression_encryption_io",
    "commitlog_config_validation_metrics",
)

SOURCE_TOKEN_CHECKS = {
    COMMITLOG: (
        "final public AbstractCommitLogSegmentManager segmentManager;",
        "public final CommitLogArchiver archiver;",
        "final AbstractCommitLogService executor;",
        "executor = new PeriodicCommitLogService(this);",
        "executor = new BatchCommitLogService(this);",
        "executor = new GroupCommitLogService(this);",
        "metrics.attach(executor, segmentManager);",
        "synchronized public CommitLog start()",
        "public int recoverSegmentsOnDisk() throws IOException",
        "archiver.maybeRestoreArchive();",
        "public int recoverFiles(File... clogs) throws IOException",
        "public void sync(boolean flush) throws IOException",
        "executor.requestExtraSync();",
        "public CommitLogPosition add(Mutation mutation) throws CDCWriteException",
        "mutation.validateSize(MessagingService.current_version, ENTRY_OVERHEAD_SIZE);",
        "Allocation alloc = segmentManager.allocate(mutation, totalSize);",
        "executor.finishWriteFor(alloc);",
        "throw new FSWriteError(e, segmentManager.allocatingFrom().getPath());",
        "public void discardCompletedSegments(final TableId id, final CommitLogPosition lowerBound, final CommitLogPosition upperBound)",
        "segmentManager.archiveAndDiscard(segment);",
        "public static boolean handleCommitError(String message, Throwable t)",
    ),
    COMMITLOG_MBEAN: (
        "public interface CommitLogMBean",
        "public List<String> getActiveSegmentNames();",
        "long getActiveContentSize();",
        "long getActiveOnDiskSize();",
        "public Map<String, Double> getActiveSegmentCompressionRatios();",
        "boolean getCDCBlockWrites();",
        "public void setCDCBlockWrites(boolean val);",
        "boolean isCDCOnRepairEnabled();",
        "void setCDCOnRepairEnabled(boolean value);",
    ),
    ABSTRACT_SERVICE: (
        "public abstract class AbstractCommitLogService",
        "static final long DEFAULT_MARKER_INTERVAL_MILLIS = 100;",
        "if (syncIntervalNanos < 1 && !(this instanceof BatchCommitLogService))",
        "class SyncRunnable implements Interruptible.Task",
        "commitLog.sync(true);",
        "commitLog.sync(false);",
        "maybeLogFlushLag(pollStarted, now);",
        "boolean maybeLogFlushLag(long pollStarted, long now)",
        "public void finishWriteFor(Allocation alloc)",
        "maybeWaitForSync(alloc);",
        "void requestExtraSync()",
        "public void syncBlocking()",
        "void awaitSyncAt(long syncTime, Context context)",
    ),
    BATCH_SERVICE: (
        "class BatchCommitLogService extends AbstractCommitLogService",
        "requestExtraSync();",
        "alloc.awaitDiskSync(commitLog.metrics.waitingOnCommit);",
    ),
    GROUP_SERVICE: (
        "public class GroupCommitLogService extends AbstractCommitLogService",
        "DatabaseDescriptor.getCommitLogSyncGroupWindow()",
        "alloc.awaitDiskSync(commitLog.metrics.waitingOnCommit);",
    ),
    PERIODIC_SERVICE: (
        "class PeriodicCommitLogService extends AbstractCommitLogService",
        "DatabaseDescriptor.getCommitLogSyncPeriod()",
        "DatabaseDescriptor.getPeriodicCommitLogSyncBlock()",
        "awaitSyncAt(expectedSyncTime, commitLog.metrics.waitingOnCommit.time());",
    ),
    SEGMENT_MANAGER: (
        "public abstract class AbstractCommitLogSegmentManager",
        "private CommitLogSegment.Builder createSegmentBuilder(CommitLog.Configuration config)",
        "this.segmentBuilder = createSegmentBuilder(commitLog.configuration);",
        "advanceAllocatingFrom(null);",
        "availableSegment = createSegment();",
        "maybeFlushToReclaim();",
        "public abstract Allocation allocate(Mutation mutation, int size);",
        "protected CommitLogSegment createSegment()",
        "void advanceAllocatingFrom(CommitLogSegment old)",
        "void forceRecycleAll(Collection<TableId> droppedTables)",
        "archiveAndDiscard(segment);",
        "void archiveAndDiscard(final CommitLogSegment segment)",
        "public long onDiskSize()",
    ),
    SEGMENT_MANAGER_STANDARD: (
        "public class CommitLogSegmentManagerStandard extends AbstractCommitLogSegmentManager",
        "public CommitLogSegment.Allocation allocate(Mutation mutation, int size)",
        "while ( null == (alloc = segment.allocate(mutation, size)) )",
        "advanceAllocatingFrom(segment);",
        "public CommitLogSegment createSegment()",
    ),
    SEGMENT_MANAGER_CDC: (
        "public class CommitLogSegmentManagerCDC extends AbstractCommitLogSegmentManager",
        "public long deleteOldLinkedCDCCommitLogSegment(long bytesToFree)",
        "public CommitLogSegment.Allocation allocate(Mutation mutation, int size) throws CDCWriteException",
        "permitSegmentMaybe(segment);",
        "throwIfForbidden(mutation, segment);",
        "segment.setCDCState(CDCState.CONTAINS);",
        "private void permitSegmentMaybe(CommitLogSegment segment)",
        "private void throwIfForbidden(Mutation mutation, CommitLogSegment segment) throws CDCWriteException",
        "if (mutation.trackedByCDC() && segment.getCDCState() == CDCState.FORBIDDEN)",
        "throw new CDCWriteException(logMsg);",
        "public CommitLogSegment createSegment()",
        "segment.setCDCState(blocking && segmentSize + sizeInProgress.get() > allowance",
        "long remainingSize = segmentManager.deleteOldLinkedCDCCommitLogSegment(bytesToFree);",
        "private void calculateSize()",
        "public long updateCDCTotalSize()",
    ),
    SEGMENT: (
        "public enum CDCState",
        "PERMITTED",
        "FORBIDDEN",
        "CONTAINS",
        "Allocation allocate(Mutation mutation, int size)",
        "if (cdcState == CDCState.CONTAINS)",
        "writer.write(\"\\nCOMPLETED\");",
        "abstract public long onDiskSize();",
        "public CDCState getCDCState()",
        "public CDCState setCDCState(CDCState newState)",
        "if (cdcState == CDCState.CONTAINS && newState != CDCState.CONTAINS)",
        "if (cdcState == CDCState.FORBIDDEN && newState != CDCState.PERMITTED)",
    ),
    READER: (
        "public class CommitLogReader",
        "public void readAllFiles(CommitLogReadHandler handler, File[] files) throws IOException",
        "CommitLogDescriptor.readHeader(reader, DatabaseDescriptor.getEncryptionContext());",
        "public void readCommitLogSegment(CommitLogReadHandler handler,",
        "CommitLogDescriptor desc = CommitLogDescriptor.fromFileName(file.name());",
        "segmentReader = new CommitLogSegmentReader(handler, desc, reader, tolerateTruncation);",
        "for (CommitLogSegmentReader.SyncSegment syncSegment : segmentReader)",
        "private void readSection(CommitLogReadHandler handler,",
        "claimedCRC32 = CommitLogFormat.calculateClaimedCRC32(reader, desc.version);",
        "if (claimedCRC32 != checksum.getValue())",
        "protected void readMutation(CommitLogReadHandler handler,",
        "handler.handleMutation(mutation, size, entryLocation, desc);",
    ),
    READ_HANDLER: (
        "public interface CommitLogReadHandler",
        "boolean shouldSkipSegmentOnError(CommitLogReadException exception) throws IOException;",
        "void handleUnrecoverableError(CommitLogReadException exception) throws IOException;",
        "void handleMutation(Mutation m, int size, int entryLocation, CommitLogDescriptor desc);",
    ),
    SEGMENT_READER: (
        "public class CommitLogSegmentReader implements Iterable<CommitLogSegmentReader.SyncSegment>",
        "private static volatile boolean allowSkipSyncMarkerCrc = COMMITLOG_ALLOW_IGNORE_SYNC_CRC.getBoolean();",
        "segmenter = new EncryptedSegmenter(descriptor, reader);",
        "segmenter = new CompressedSegmenter(descriptor, reader);",
        "private int readSyncMarker(CommitLogDescriptor descriptor, int offset, RandomAccessReader reader) throws IOException",
        "if (allowSkipSyncMarkerCrc",
        "&& descriptor.compression == null && !descriptor.getEncryptionContext().isEnabled()",
        "static class CompressedSegmenter implements Segmenter",
        "static class EncryptedSegmenter implements Segmenter",
    ),
    REPLAYER: (
        "public class CommitLogReplayer implements CommitLogReadHandler",
        "public static MutationInitiator mutationInitiator = new MutationInitiator();",
        "private final ReplayFilter replayFilter;",
        "protected boolean sawCDCMutation;",
        "public static CommitLogReplayer construct(CommitLog commitLog, UUID localHostId)",
        "ReplayFilter replayFilter = ReplayFilter.create();",
        "private void handleCDCReplayCompletion(File f) throws IOException",
        "((CommitLogSegmentManagerCDC)CommitLog.instance.segmentManager).addCDCSize(f.length());",
        "CommitLogSegment.writeCDCIndexFile(desc, (int)f.length(), true);",
        "public int blockForWrites()",
        "public static class MutationInitiator",
        "if (commitLogReplayer.pointInTimeExceeded(mutation))",
        "Keyspace.open(newPUCollector.getKeyspaceName()).apply(newPUCollector.build(), false, true, false);",
        "abstract static class ReplayFilter",
        "String replayList = COMMIT_LOG_REPLAY_LIST.getString();",
        "private static class AlwaysReplayFilter extends ReplayFilter",
        "private static class CustomReplayFilter extends ReplayFilter",
        "protected boolean pointInTimeExceeded(Mutation fm)",
        "if (archiver.precision.toMicros(upd.maxTimestamp()) > archiver.restorePointInTimeInMicroseconds)",
        "public void handleMutation(Mutation m, int size, int entryLocation, CommitLogDescriptor desc)",
        "if (DatabaseDescriptor.isCDCEnabled() && m.trackedByCDC())",
        "public boolean shouldSkipSegmentOnError(CommitLogReadException exception) throws IOException",
        "else if (COMMITLOG_IGNORE_REPLAY_ERRORS.getBoolean())",
        "public void handleUnrecoverableError(CommitLogReadException exception) throws IOException",
    ),
    DESCRIPTOR: (
        "public class CommitLogDescriptor",
        "public static void writeHeader(ByteBuffer out, CommitLogDescriptor descriptor, Map<String, String> additionalHeaders)",
        "CRC32 crc = new CRC32();",
        "public static CommitLogDescriptor readHeader(DataInput input, EncryptionContext encryptionContext) throws IOException",
        "return new CommitLogDescriptor(version, id, parseCompression(map), EncryptionContext.createFromMap(map, encryptionContext));",
        "public static CommitLogDescriptor fromFileName(String name)",
        "public boolean equalsIgnoringCompression(CommitLogDescriptor that)",
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
        "public boolean maybeWaitForArchiving(String name)",
        "public void maybeRestoreArchive()",
        "else if (fromHeader != null && fromName != null && !fromHeader.equalsIgnoringCompression(fromName))",
        "ProcessBuilder pb = new ProcessBuilder(command.split(\" \"));",
        "return this.restorePointInTimeInMicroseconds;",
        "this.precision = timeUnit;",
    ),
    COMPRESSED_SEGMENT: (
        "public class CompressedSegment extends FileDirectSegment",
        "protected static class CompressedSegmentBuilder extends CommitLogSegment.Builder",
        "public CompressedSegment build()",
    ),
    ENCRYPTED_SEGMENT: (
        "public class EncryptedSegment extends FileDirectSegment",
        "protected static class EncryptedSegmentBuilder extends CommitLogSegment.Builder",
        "public EncryptedSegment build()",
    ),
    DIRECT_IO_SEGMENT: (
        "public class DirectIOSegment extends CommitLogSegment",
        "protected static class DirectIOSegmentBuilder extends CommitLogSegment.Builder",
        "public DirectIOSegment build()",
    ),
    MMAP_SEGMENT: (
        "public class MemoryMappedSegment extends CommitLogSegment",
        "protected static class MemoryMappedSegmentBuilder extends CommitLogSegment.Builder",
        "public MemoryMappedSegment build()",
    ),
    CONFIG: (
        "public String commitlog_directory;",
        "public DataStorageSpec.IntMebibytesBound commitlog_total_space;",
        "public CommitLogSync commitlog_sync;",
        "public DurationSpec.IntMillisecondsBound commitlog_sync_group_window",
        "public DurationSpec.IntMillisecondsBound commitlog_sync_period",
        "public DataStorageSpec.IntMebibytesBound commitlog_segment_size",
        "public ParameterizedClass commitlog_compression;",
        "public DiskAccessMode commitlog_disk_access_mode = DiskAccessMode.legacy;",
        "public DurationSpec.IntMillisecondsBound periodic_commitlog_sync_lag_block;",
        "public TransparentDataEncryptionOptions transparent_data_encryption_options",
        "public boolean cdc_enabled = false;",
        "public volatile boolean cdc_block_writes = true;",
        "public volatile boolean cdc_on_repair_enabled = true;",
        "public String cdc_raw_directory;",
        "public DataStorageSpec.IntMebibytesBound cdc_total_space",
        "public DurationSpec.IntMillisecondsBound cdc_free_space_check_interval",
    ),
    DATABASE_DESCRIPTOR: (
        "? new CommitLogSegmentManagerCDC(c, DatabaseDescriptor.getCommitLogLocation())",
        "if (conf.commitlog_sync == null)",
        "if (conf.commitlog_sync == CommitLogSync.batch)",
        "Batch sync specified, but commitlog_sync_period found.",
        "else if (conf.commitlog_sync == CommitLogSync.group)",
        "Missing value for commitlog_sync_group_window.",
        "Group sync specified, but commitlog_sync_period found.",
        "Missing value for commitlog_sync_period.",
        "if (datadir.equals(conf.commitlog_directory))",
        "commitlog_directory must not be the same as any data_file_directories",
        "commitlog_segment_size must be positive",
        "commitlog_segment_size must be smaller than 2048",
        "commitlog_segment_size must be at least twice the size of max_mutation_size / 1024",
        "commitlog_disk_access_mode can not be set to direct when direct IO is not supported by the file system.",
        "is not supported with compression or encryption. Please use 'auto' when unsure.",
        "public static int getCommitLogSegmentSize()",
        "public static Config.CommitLogSync getCommitLogSync()",
        "public static boolean isCDCEnabled()",
        "public static boolean getCDCBlockWrites()",
        "public static boolean isCDCOnRepairEnabled()",
        "public static Function<CommitLog, AbstractCommitLogSegmentManager> getCommitLogSegmentMgrProvider()",
    ),
    MUTATION: (
        "private final boolean cdcEnabled;",
        "private static boolean cdcEnabled(Iterable<PartitionUpdate> modifications)",
        "cdc |= pu.metadata().params.cdc;",
        "public boolean trackedByCDC()",
        "return cdcEnabled;",
    ),
    TABLE_ATTRIBUTES: (
        "public final class TableAttributes extends PropertyDefinitions",
        "builder.cdc(getBoolean(CDC));",
    ),
    STREAM_RECEIVER: (
        "private final boolean requiresWritePath;",
        "return cfs.metadata().params.cdc;",
        "private boolean cdcRequiresWriteCommitLog(ColumnFamilyStore cfs)",
        "return cdcRequiresWriteCommitLog(cfs)",
        "boolean writeCDCCommitLog = cdcRequiresWriteCommitLog(cfs);",
        "so they get archived into the cdc_raw folder",
    ),
    COMMITLOG_METRICS: (
        "public class CommitLogMetrics",
        "waitingOnSegmentAllocation = Metrics.timer(factory.createMetricName(\"WaitingOnSegmentAllocation\"));",
        "waitingOnCommit = Metrics.timer(factory.createMetricName(\"WaitingOnCommit\"));",
        "waitingOnFlush = Metrics.timer(factory.createMetricName(\"WaitingOnFlush\"));",
        "oversizedMutations = Metrics.meter(factory.createMetricName(\"OverSizedMutations\"));",
        "completedTasks = Metrics.register(factory.createMetricName(\"CompletedTasks\")",
        "pendingTasks = Metrics.register(factory.createMetricName(\"PendingTasks\")",
        "totalCommitLogSize = Metrics.register(factory.createMetricName(\"TotalCommitLogSize\")",
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
    ABSTRACT_SERVICE_TEST: (
        "public void testConstructorSyncIsQuantized()",
        "public void testConstructorSyncEqualsMarkerDefault()",
        "public void testConstructorSyncShouldRoundUp()",
        "public void testConstructorSyncShouldRoundDown()",
        "public void testConstructorSyncTinyValue()",
        "public void testSync()",
        "public void maybeLogFlushLag_MustLog()",
        "public void maybeLogFlushLag_NoLog()",
        "public void maybeLogFlushLag_MultipleOperations()",
    ),
    COMMITLOG_FAILURE_POLICY_TEST: (
        "public void testCommitFailurePolicy_stop()",
        "public void testCommitFailurePolicy_die()",
        "public void testCommitFailurePolicy_ignore_beforeStartup()",
        "public void testCommitFailurePolicy_ignore_afterStartup()",
        "CommitLog.handleCommitError",
        "daemon.completeSetup();",
    ),
    COMMITLOG_BACKPRESSURE_TEST: (
        "public void testCompressedCommitLogBackpressure()",
        "targetClass = \"AbstractCommitLogService$SyncRunnable\"",
        "targetLocation = \"AT INVOKE org.apache.cassandra.db.commitlog.CommitLog.sync(boolean)\"",
        "DatabaseDescriptor.setCommitLogCompression(new ParameterizedClass(\"LZ4Compressor\", ImmutableMap.of()));",
        "DatabaseDescriptor.setCommitLogMaxCompressionBuffersPerPool(3);",
        "CommitLog.instance.add(m);",
        "new ArrayList<>(clsm.getActiveSegments()).forEach( clsm::archiveAndDiscard );",
    ),
    COMMITLOG_TEST: (
        "public void testRecoveryWithIdMismatch()",
        "public void testRecoveryWithBadCompressor()",
        "public void testTruncateWithoutSnapshot()",
        "public void replaySimple()",
        "public void testReplayListProperty()",
        "public void replayWithBadSyncMarkerCRC()",
        "CommitLogSegmentReader.setAllowSkipSyncMarkerCrc(true);",
        "public void replayWithDiscard()",
        "public void testUnwriteableFlushRecovery()",
        "public void testOutOfOrderFlushRecovery()",
        "public void testOutOfOrderLogDiscard()",
    ),
    COMMITLOG_READER_TEST: (
        "public class CommitLogReaderTest",
        "CommitLogReadHandler",
        "shouldSkipSegmentOnError",
        "handleUnrecoverableError",
        "handleMutation",
    ),
    CDC_MANAGER_TEST: (
        "public void testCDCWriteFailure()",
        "expectCurrentCDCState(CDCState.FORBIDDEN);",
        "expectCurrentCDCState(CDCState.PERMITTED);",
        "public void testSegmentFlaggingOnCreation()",
        "public void testSegmentFlaggingWithNonblockingOnCreation()",
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
        "catch (CDCWriteException e)",
    ),
    ARCHIVER_TEST: (
        "public void testArchiver()",
        "public void testRestoreInDifferentPrecision()",
        "CommitLog.instance.archiver.maybeRestoreArchive();",
        "CommitLog.instance.archiver.setPrecision(TimeUnit.MILLISECONDS);",
    ),
    SEGMENT_READER_TEST: (
        "public void compressedSegmenter_LZ4()",
        "public void compressedSegmenter_Snappy()",
        "public void compressedSegmenter_Deflate()",
        "public void compressedSegmenter_Zstd()",
        "public void encryptedSegmenterRead()",
        "public void encryptedSegmenterSeek()",
        "CompressedSegmenter segmenter = new CompressedSegmenter(compressor, reader);",
        "EncryptedSegmenter segmenter = new EncryptedSegmenter(reader, context);",
    ),
    DIRECT_IO_TEST: (
        "public void testFlushBuffer()",
        "DirectIOSegment seg = new DirectIOSegment(manager, channelFactory, fsBlockSize);",
        "public void testFlushSize()",
        "public void testBuilder()",
        "DirectIOSegment.DirectIOSegmentBuilder builder = new DirectIOSegment.DirectIOSegmentBuilder(manager, 4096);",
    ),
    DIRECT_IO_BYTEMAN_TEST: (
        "public void testDirectIOUnSupportWithDirectConfig()",
        "DatabaseDescriptor.setCommitLogWriteDiskAccessMode(Config.DiskAccessMode.direct);",
        "commitlog_disk_access_mode can not be set to direct when direct IO is not supported by the file system.",
    ),
    CDC_STATEMENT_TEST: (
        "public void testEnableOnCreate()",
        "WITH cdc = true",
        "public void testEnableOnAlter()",
        "ALTER TABLE %s WITH cdc = true;",
        "public void testDisableOnAlter()",
        "ALTER TABLE %s WITH cdc = false;",
    ),
    CDC_REPAIR_TEST: (
        "public void testCDCOnRepairIsEnabled()",
        "assertTrue(\"Mutation should be added to commit log when cdc_on_repair_enabled is true\"",
        "public void testCDCOnRepairIsDisabled()",
        "assertTrue(\"No mutation should be added to commit log when cdc_on_repair_enabled is false\"",
        ".set(\"cdc_enabled\", true)",
        ".set(\"cdc_on_repair_enabled\", enabled)",
        "cluster.get(2).nodetool(\"repair\", KEYSPACE, \"tbl\");",
    ),
    UPGRADE_TEST: (
        "public void test30_encrypted()",
        "public void test3014_encrypted()",
        "public void test40_encrypted()",
        "public void test34_encrypted()",
        "test/data/legacy-commitlog/",
    ),
    STRESS_TEST: (
        "public abstract class CommitLogStressTest",
        "{null, EncryptionContextGenerator.createDisabledContext(), Config.DiskAccessMode.legacy}",
        "{null, EncryptionContextGenerator.createDisabledContext(), Config.DiskAccessMode.direct}",
        "new ParameterizedClass(LZ4Compressor.class.getName(), Collections.emptyMap())",
        "new ParameterizedClass(SnappyCompressor.class.getName(), Collections.emptyMap())",
        "new ParameterizedClass(DeflateCompressor.class.getName(), Collections.emptyMap())",
        "public void testRandomSize()",
        "public void testFixedSize()",
        "public void testDiscardedRun()",
    ),
    BATCH_TEST: (
        "public class BatchCommitLogTest",
    ),
    GROUP_TEST: (
        "public class GroupCommitLogTest",
    ),
}

DOC_TOKEN_CHECKS = {
    "research/module-commitlog-durability-replay-matrix.md": (
        "CommitLog Durability Replay Matrix",
        "commitlog_append_record_crc",
        "commitlog_sync_strategy_modes",
        "commitlog_sync_lag_marker",
        "commitlog_segment_allocation_reclaim",
        "commitlog_segment_clean_discard",
        "commitlog_cdc_raw_backpressure",
        "commitlog_cdc_index_contract",
        "commitlog_cdc_replay_rebuild",
        "commitlog_cdc_repair_streaming",
        "commitlog_archiver_pitr_restore",
        "commitlog_replay_filter_pitr",
        "commitlog_reader_error_policy",
        "commitlog_format_compression_encryption_io",
        "commitlog_config_validation_metrics",
        "CDCWriteException",
        "COMPLETED",
        "COMMITLOG_IGNORE_REPLAY_ERRORS",
        "commitlog_archiving.properties",
    ),
    "research/module-commitlog-durability-drift-checker.md": (
        "check-commitlog-durability-drift.py",
        "source/test/doc",
        "commitlog_append_record_crc",
        "commitlog_config_validation_metrics",
    ),
    "research/README.md": (
        "module-commitlog-durability-replay-matrix.md",
        "module-commitlog-durability-drift-checker.md",
        "check-commitlog-durability-drift.py",
    ),
    "research/notes/source-map.md": (
        "CommitLog durability/replay drift",
        "check-commitlog-durability-drift.py",
        "commitlog_append_record_crc",
        "commitlog_cdc_raw_backpressure",
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
            missing.append(MissingToken(relative_path, "<file missing>", category))
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
            "research/module-commitlog-durability-replay-matrix.md",
            "research/module-commitlog-durability-drift-checker.md",
            "research/tools/check-commitlog-durability-drift.py",
        ):
            required_ids = SCENARIO_IDS
        else:
            required_ids = ("commitlog_append_record_crc", "commitlog_cdc_raw_backpressure")
        for scenario_id in required_ids:
            if scenario_id not in text:
                missing.append(MissingToken(doc, scenario_id, "scenario"))
    return missing


def main():
    parser = argparse.ArgumentParser(description="Check CommitLog durability/replay research drift.")
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
        print("CommitLog durability drift check failed:")
        for missing_token in missing:
            print(f"- [{missing_token.category}] {missing_token.file_path}: {missing_token.token}")
    else:
        total_checks = sum(len(tokens) for tokens in SOURCE_TOKEN_CHECKS.values())
        total_checks += sum(len(tokens) for tokens in TEST_TOKEN_CHECKS.values())
        total_checks += sum(len(tokens) for tokens in DOC_TOKEN_CHECKS.values())
        total_checks += len(SCENARIO_IDS) * 3 + 2 * (len(TARGET_DOCS) - 3)
        print(f"OK CommitLog durability drift checks passed ({total_checks} checks, {len(SCENARIO_IDS)} scenarios)")

    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
