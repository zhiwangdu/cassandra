#!/usr/bin/env python3
#
# Source-only drift check for read warning/abort threshold research coverage.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

READ_COMMAND = "src/java/org/apache/cassandra/db/ReadCommand.java"
SELECT_STATEMENT = "src/java/org/apache/cassandra/cql3/statements/SelectStatement.java"
QUERY_OPTIONS = "src/java/org/apache/cassandra/cql3/QueryOptions.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
CASSANDRA_YAML = "conf/cassandra.yaml"
PARAM_TYPE = "src/java/org/apache/cassandra/net/ParamType.java"
WARNING_CONTEXT = "src/java/org/apache/cassandra/service/reads/thresholds/WarningContext.java"
WARNINGS_SNAPSHOT = "src/java/org/apache/cassandra/service/reads/thresholds/WarningsSnapshot.java"
COORDINATOR_WARNINGS = "src/java/org/apache/cassandra/service/reads/thresholds/CoordinatorWarnings.java"
READ_CALLBACK = "src/java/org/apache/cassandra/service/reads/ReadCallback.java"
STORAGE_PROXY = "src/java/org/apache/cassandra/service/StorageProxy.java"
STORAGE_SERVICE = "src/java/org/apache/cassandra/service/StorageService.java"
TABLE_METRICS = "src/java/org/apache/cassandra/metrics/TableMetrics.java"
KEYSPACE_METRICS = "src/java/org/apache/cassandra/metrics/KeyspaceMetrics.java"
CLIENT_REQUEST_METRICS = "src/java/org/apache/cassandra/metrics/ClientRequestMetrics.java"
TOMBSTONE_ABORT_EXCEPTION = "src/java/org/apache/cassandra/exceptions/TombstoneAbortException.java"
READ_SIZE_ABORT_EXCEPTION = "src/java/org/apache/cassandra/exceptions/ReadSizeAbortException.java"
LOCAL_READ_TOO_LARGE_EXCEPTION = "src/java/org/apache/cassandra/db/filter/LocalReadSizeTooLargeException.java"
TOMBSTONE_OVERWHELMING_EXCEPTION = "src/java/org/apache/cassandra/db/filter/TombstoneOverwhelmingException.java"

COORDINATOR_READ_SIZE_TEST = "test/distributed/org/apache/cassandra/distributed/test/thresholds/CoordinatorReadSizeWarningTest.java"
LOCAL_READ_SIZE_TEST = "test/distributed/org/apache/cassandra/distributed/test/thresholds/LocalReadSizeWarningTest.java"
ABSTRACT_CLIENT_SIZE_TEST = "test/distributed/org/apache/cassandra/distributed/test/thresholds/AbstractClientSizeWarning.java"
TOMBSTONE_COUNT_TEST = "test/distributed/org/apache/cassandra/distributed/test/thresholds/TombstoneCountWarningTest.java"
READ_FAILURE_TEST = "test/distributed/org/apache/cassandra/distributed/test/ReadFailureTest.java"
DATABASE_DESCRIPTOR_TEST = "test/unit/org/apache/cassandra/config/DatabaseDescriptorTest.java"
YAML_CONFIGURATION_LOADER_TEST = "test/unit/org/apache/cassandra/config/YamlConfigurationLoaderTest.java"

MATRIX_DOC = "research/module-read-warning-abort-thresholds-matrix.md"
CHECKER_DOC = "research/module-read-warning-abort-thresholds-drift-checker.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

SCENARIO_IDS = (
    "read_warning_config_contract",
    "read_warning_query_options_snapshot_contract",
    "read_warning_replica_tombstone_warn_contract",
    "read_abort_replica_tombstone_contract",
    "read_warning_replica_local_size_contract",
    "read_abort_replica_local_size_contract",
    "read_warning_message_param_contract",
    "read_abort_snapshot_callback_contract",
    "read_warning_coordinator_result_size_contract",
    "read_warning_metrics_contract",
    "read_warning_jmx_runtime_contract",
    "read_warning_threshold_tests_baseline",
    "read_warning_speculative_race_regression",
)

SOURCE_TOKEN_CHECKS = {
    READ_COMMAND: (
        "iterator = withQuerySizeTracking(iterator);",
        "iterator = withMetricsRecording(iterator, cfs.metric, startTimeNanos);",
        "private final int failureThreshold = DatabaseDescriptor.getTombstoneFailureThreshold();",
        "private final int warningThreshold = DatabaseDescriptor.getTombstoneWarnThreshold();",
        "metric.tombstoneFailures.inc();",
        "MessageParams.remove(ParamType.TOMBSTONE_WARNING);",
        "MessageParams.add(ParamType.TOMBSTONE_FAIL, tombstones);",
        "throw new TombstoneOverwhelmingException(tombstones, query, ReadCommand.this.metadata(), currentKey, clustering);",
        "metric.tombstoneScannedHistogram.update(tombstones);",
        "metric.liveScannedHistogram.update(liveRows);",
        "MessageParams.add(ParamType.TOMBSTONE_WARNING, tombstones);",
        "metric.tombstoneWarnings.inc();",
        "logger.warn(msg);",
        "private boolean shouldTrackSize",
        "trackWarnings",
        "!SchemaConstants.isSystemKeyspace(metadata().keyspace)",
        "DatabaseDescriptor.getLocalReadSizeWarnThreshold();",
        "DatabaseDescriptor.getLocalReadSizeFailThreshold();",
        "sizeInBytes += ObjectSizes.sizeOnHeapOf(iter.partitionKey().getKey());",
        "addSize(row.unsharedHeapSize());",
        "addSize(marker.unsharedHeapSize());",
        "addSize(deletionTime.unsharedHeapSize());",
        "MessageParams.remove(ParamType.LOCAL_READ_SIZE_WARN);",
        "MessageParams.add(ParamType.LOCAL_READ_SIZE_FAIL, this.sizeInBytes);",
        "throw new LocalReadSizeTooLargeException(msg);",
        "MessageParams.add(ParamType.LOCAL_READ_SIZE_WARN, this.sizeInBytes);",
        "cfs.metric.localReadSize.update(sizeInBytes);",
    ),
    SELECT_STATEMENT: (
        "ResultSet cqlRows = result.build();",
        "maybeWarn(result, options);",
        "private void maybeWarn(ResultSetBuilder result, QueryOptions options)",
        "if (!options.isReadThresholdsEnabled())",
        "store.metric.coordinatorReadSize.update(result.getSize());",
        "result.shouldWarn(options.getCoordinatorReadSizeWarnThresholdBytes())",
        "ClientWarn.instance.warn(msg + \" with \" + loggableTokens(options, state));",
        "store.metric.coordinatorReadSizeWarnings.mark();",
        "private void maybeFail(ResultSetBuilder result, QueryOptions options)",
        "result.shouldReject(options.getCoordinatorReadSizeAbortThresholdBytes())",
        "store.metric.coordinatorReadSizeAborts.mark();",
        "new ReadSizeAbortException(clientMsg, options.getConsistency(), 0, 1, true,",
        "StorageProxy.recordReadRegularAbort(options.getConsistency(), exception);",
        "maybeFail(result, options);",
    ),
    QUERY_OPTIONS: (
        "public boolean isReadThresholdsEnabled()",
        "getCoordinatorReadSizeWarnThresholdBytes()",
        "getCoordinatorReadSizeAbortThresholdBytes()",
        "interface ReadThresholds",
        "static ReadThresholds create()",
        "!DatabaseDescriptor.isDaemonInitialized() || !DatabaseDescriptor.getReadThresholdsEnabled()",
        "DisabledReadThresholds.INSTANCE",
        "new DefaultReadThresholds(DatabaseDescriptor.getCoordinatorReadSizeWarnThreshold(), DatabaseDescriptor.getCoordinatorReadSizeFailThreshold())",
        "private enum DisabledReadThresholds implements ReadThresholds",
        "private static class DefaultReadThresholds implements ReadThresholds",
        "this.warnThresholdBytes = warnThreshold == null ? -1 : warnThreshold.toBytes();",
        "this.abortThresholdBytes = abortThreshold == null ? -1 : abortThreshold.toBytes();",
        "private final transient ReadThresholds readThresholds = ReadThresholds.create();",
    ),
    CONFIG: (
        "public volatile boolean read_thresholds_enabled = false;",
        "public volatile DataStorageSpec.LongBytesBound coordinator_read_size_warn_threshold = null;",
        "public volatile DataStorageSpec.LongBytesBound coordinator_read_size_fail_threshold = null;",
        "public volatile DataStorageSpec.LongBytesBound local_read_size_warn_threshold = null;",
        "public volatile DataStorageSpec.LongBytesBound local_read_size_fail_threshold = null;",
        "public volatile DataStorageSpec.LongBytesBound row_index_read_size_warn_threshold = null;",
        "public volatile DataStorageSpec.LongBytesBound row_index_read_size_fail_threshold = null;",
        "public volatile int tombstone_warn_threshold = 1000;",
        "public volatile int tombstone_failure_threshold = 100000;",
    ),
    DATABASE_DESCRIPTOR: (
        "applyReadThresholdsValidations(Config config)",
        "validateReadThresholds(\"coordinator_read_size\", config.coordinator_read_size_warn_threshold, config.coordinator_read_size_fail_threshold);",
        "validateReadThresholds(\"local_read_size\", config.local_read_size_warn_threshold, config.local_read_size_fail_threshold);",
        "validateReadThresholds(\"row_index_read_size\", config.row_index_read_size_warn_threshold, config.row_index_read_size_fail_threshold);",
        "getTombstoneWarnThreshold()",
        "setTombstoneWarnThreshold(int threshold)",
        "getTombstoneFailureThreshold()",
        "setTombstoneFailureThreshold(int threshold)",
        "getReadThresholdsEnabled()",
        "setReadThresholdsEnabled(boolean value)",
        "getCoordinatorReadSizeWarnThreshold()",
        "setCoordinatorReadSizeWarnThreshold",
        "getCoordinatorReadSizeFailThreshold()",
        "setCoordinatorReadSizeFailThreshold",
        "getLocalReadSizeWarnThreshold()",
        "setLocalReadSizeWarnThreshold",
        "getLocalReadSizeFailThreshold()",
        "setLocalReadSizeFailThreshold",
    ),
    CASSANDRA_YAML: (
        "tombstone_warn_threshold: 1000",
        "tombstone_failure_threshold: 100000",
        "read_thresholds_enabled: false",
        "coordinator_read_size_warn_threshold:",
        "coordinator_read_size_fail_threshold:",
        "local_read_size_warn_threshold:",
        "local_read_size_fail_threshold:",
        "row_index_read_size_warn_threshold:",
        "row_index_read_size_fail_threshold:",
    ),
    PARAM_TYPE: (
        "TOMBSTONE_FAIL",
        "TOMBSTONE_WARNING",
        "LOCAL_READ_SIZE_FAIL",
        "LOCAL_READ_SIZE_WARN",
        "ROW_INDEX_READ_SIZE_FAIL",
        "ROW_INDEX_READ_SIZE_WARN",
    ),
    WARNING_CONTEXT: (
        "EnumSet.of(ParamType.TOMBSTONE_WARNING, ParamType.TOMBSTONE_FAIL",
        "ParamType.LOCAL_READ_SIZE_WARN, ParamType.LOCAL_READ_SIZE_FAIL",
        "final WarnAbortCounter tombstones = new WarnAbortCounter();",
        "final WarnAbortCounter localReadSize = new WarnAbortCounter();",
        "case LOCAL_READ_SIZE_FAIL:",
        "reason = RequestFailureReason.READ_SIZE;",
        "case TOMBSTONE_FAIL:",
        "reason = RequestFailureReason.READ_TOO_MANY_TOMBSTONES;",
        "counter.addAbort(from, ((Number) entry.getValue()).longValue());",
        "counter.addWarning(from, ((Number) entry.getValue()).longValue());",
        "WarningsSnapshot.create(tombstones.snapshot(), localReadSize.snapshot(), rowIndexReadSize.snapshot(), indexReadSSTablesCount.snapshot())",
    ),
    WARNINGS_SNAPSHOT: (
        "public final Warnings tombstones, localReadSize, rowIndexReadSize, indexReadSSTablesCount;",
        "public static WarningsSnapshot merge(WarningsSnapshot... values)",
        "public void maybeAbort(ReadCommand command, ConsistencyLevel cl, int received, int blockFor, boolean isDataPresent, Map<InetAddressAndPort, RequestFailureReason> failureReasonByEndpoint)",
        "throw new TombstoneAbortException(tombstoneAbortMessage",
        "throw new ReadSizeAbortException(localReadSizeAbortMessage",
        "tombstoneAbortMessage",
        "tombstoneWarnMessage",
        "localReadSizeAbortMessage",
        "localReadSizeWarnMessage",
        "(see tombstone_failure_threshold)",
        "(see tombstone_warn_threshold)",
        "(see local_read_size_fail_threshold)",
        "(see local_read_size_warn_threshold)",
    ),
    COORDINATOR_WARNINGS: (
        "public static void update(ReadCommand cmd, WarningsSnapshot snapshot)",
        "WarningsSnapshot.merge(previous, snapshot)",
        "public static void done()",
        "recordAborts(merged.tombstones, cql, loggableTokens, cfs.metric.clientTombstoneAborts",
        "recordWarnings(merged.tombstones, cql, loggableTokens, cfs.metric.clientTombstoneWarnings",
        "recordAborts(merged.localReadSize, cql, loggableTokens, cfs.metric.localReadSizeAborts",
        "recordWarnings(merged.localReadSize, cql, loggableTokens, cfs.metric.localReadSizeWarnings",
        "ClientWarn.instance.warn(msg + \" with \" + loggableTokens);",
        "metric.mark();",
    ),
    READ_CALLBACK: (
        "WarningContext warnings = warningContext;",
        "WarningsSnapshot snapshot = null;",
        "snapshot = warnings.snapshot();",
        "CoordinatorWarnings.update(command, snapshot);",
        "if (snapshot != null)",
        "snapshot.maybeAbort(command, replicaPlan().consistencyLevel(), received, blockFor, resolver.isDataPresent(), failureReasonByEndpoint);",
        "new ReadFailureException",
        "new ReadTimeoutException",
    ),
    STORAGE_PROXY: (
        "public static void recordReadRegularAbort(ConsistencyLevel consistencyLevel, Throwable cause)",
        "readMetrics.markAbort(cause);",
        "readMetricsForLevel(consistencyLevel).markAbort(cause);",
    ),
    STORAGE_SERVICE: (
        "setTombstoneWarnThreshold(int threshold)",
        "setTombstoneFailureThreshold(int threshold)",
        "getCoordinatorLargeReadWarnThreshold()",
        "setCoordinatorLargeReadWarnThreshold(String threshold)",
        "getCoordinatorLargeReadAbortThreshold()",
        "setCoordinatorLargeReadAbortThreshold(String threshold)",
        "getLocalReadTooLargeWarnThreshold()",
        "setLocalReadTooLargeWarnThreshold(String threshold)",
        "getLocalReadTooLargeAbortThreshold()",
        "setLocalReadTooLargeAbortThreshold(String threshold)",
        "getRowIndexReadSizeWarnThreshold()",
        "setRowIndexReadSizeWarnThreshold(String threshold)",
    ),
    TABLE_METRICS: (
        "public final Counter tombstoneFailures;",
        "public final Counter tombstoneWarnings;",
        "public final TableMeter clientTombstoneWarnings;",
        "public final TableMeter clientTombstoneAborts;",
        "public final TableMeter coordinatorReadSizeWarnings;",
        "public final TableMeter coordinatorReadSizeAborts;",
        "public final TableHistogram coordinatorReadSize;",
        "public final TableMeter localReadSizeWarnings;",
        "public final TableMeter localReadSizeAborts;",
        "public final TableHistogram localReadSize;",
        "createTableCounter(\"TombstoneFailures\")",
        "createTableMeter(\"CoordinatorReadSizeWarnings\"",
        "createTableMeter(\"LocalReadSizeWarnings\"",
    ),
    KEYSPACE_METRICS: (
        "public final Meter coordinatorReadSizeWarnings;",
        "public final Meter coordinatorReadSizeAborts;",
        "public final Histogram coordinatorReadSize;",
        "public final Meter localReadSizeWarnings;",
        "public final Meter localReadSizeAborts;",
        "public final Histogram localReadSize;",
        "createKeyspaceMeter(\"CoordinatorReadSizeWarnings\")",
        "createKeyspaceMeter(\"LocalReadSizeWarnings\")",
    ),
    CLIENT_REQUEST_METRICS: (
        "public final Meter aborts;",
        "public final Meter tombstoneAborts;",
        "public final Meter readSizeAborts;",
        "public void markAbort(Throwable cause)",
        "if (!(cause instanceof ReadAbortException))",
        "cause instanceof TombstoneAbortException",
        "cause instanceof ReadSizeAbortException",
    ),
    TOMBSTONE_ABORT_EXCEPTION: (
        "public class TombstoneAbortException extends ReadAbortException",
        "public final int nodes;",
        "public final long tombstones;",
    ),
    READ_SIZE_ABORT_EXCEPTION: (
        "public class ReadSizeAbortException extends ReadAbortException",
    ),
    LOCAL_READ_TOO_LARGE_EXCEPTION: (
        "public class LocalReadSizeTooLargeException extends RejectException",
    ),
    TOMBSTONE_OVERWHELMING_EXCEPTION: (
        "public class TombstoneOverwhelmingException extends RejectException",
        "Scanned over %d tombstones during query",
    ),
}

TEST_TOKEN_CHECKS = {
    COORDINATOR_READ_SIZE_TEST: (
        "public class CoordinatorReadSizeWarningTest extends AbstractClientSizeWarning",
        "DatabaseDescriptor.setCoordinatorReadSizeWarnThreshold(new DataStorageSpec.LongBytesBound(1, KIBIBYTES));",
        "DatabaseDescriptor.setCoordinatorReadSizeFailThreshold(new DataStorageSpec.LongBytesBound(2, KIBIBYTES));",
        "Read on table \" + KEYSPACE + \".tbl has exceeded the size warning threshold",
        "Read on table \" + KEYSPACE + \".tbl has exceeded the size failure threshold",
        "org.apache.cassandra.metrics.keyspace.CoordinatorReadSize.",
        "org.apache.cassandra.metrics.keyspace.CoordinatorReadSizeWarnings.",
        "org.apache.cassandra.metrics.keyspace.CoordinatorReadSizeAborts.",
    ),
    LOCAL_READ_SIZE_TEST: (
        "public class LocalReadSizeWarningTest extends AbstractClientSizeWarning",
        "DatabaseDescriptor.setCoordinatorReadSizeWarnThreshold(null);",
        "DatabaseDescriptor.setCoordinatorReadSizeFailThreshold(null);",
        "DatabaseDescriptor.setLocalReadSizeWarnThreshold(new DataStorageSpec.LongBytesBound(1, KIBIBYTES));",
        "DatabaseDescriptor.setLocalReadSizeFailThreshold(new DataStorageSpec.LongBytesBound(2, KIBIBYTES));",
        "(see local_read_size_warn_threshold)",
        "(see local_read_size_fail_threshold)",
        "org.apache.cassandra.metrics.keyspace.LocalReadSize.",
        "org.apache.cassandra.metrics.keyspace.LocalReadSizeWarnings.",
        "org.apache.cassandra.metrics.keyspace.LocalReadSizeAborts.",
    ),
    ABSTRACT_CLIENT_SIZE_TEST: (
        "public abstract class AbstractClientSizeWarning extends TestBaseImpl",
        "public void noWarnings(String cql)",
        "public void warnThreshold(String cql, boolean triggerReadRepair)",
        "public void failThresholdEnabled(String cql)",
        "public void failThresholdDisabled(String cql)",
        "CoordinatorWarnings.init();",
        "catch (ReadSizeAbortException e)",
        "RequestFailureReason.READ_SIZE.code",
        "assertHistogramUpdated();",
        "assertHistogramNotUpdated();",
        "org.apache.cassandra.metrics.ClientRequest.Aborts.Read-ALL",
        "org.apache.cassandra.metrics.ClientRequest.Aborts.RangeSlice",
    ),
    TOMBSTONE_COUNT_TEST: (
        "public class TombstoneCountWarningTest extends TestBaseImpl",
        "tombstone_warn_threshold",
        "tombstone_failure_threshold",
        "private static void enable(boolean value)",
        "public void noWarningsSinglePartition()",
        "public void warnThresholdSinglePartition()",
        "public void warnThresholdScan()",
        "public void failThresholdSinglePartition()",
        "public void failThresholdScan()",
        "catch (TombstoneAbortException e)",
        "RequestFailureReason.READ_TOO_MANY_TOMBSTONES",
        "ClientTombstoneWarnings.",
        "ClientTombstoneAborts.",
        "org.apache.cassandra.metrics.ClientRequest.Aborts.Read-ALL",
    ),
    READ_FAILURE_TEST: (
        "public void testSpecExecRace()",
        "tombstone_failure_threshold",
        "TOMBSTONE_FAIL_THRESHOLD",
        "speculative_retry = '5p'",
        "READ_TOO_MANY_TOMBSTONES",
    ),
    DATABASE_DESCRIPTOR_TEST: (
        "public void testClientLargeReadWarnGreaterThanAbort()",
        "coordinator_read_size_fail_threshold (1KiB) must be greater than or equal to coordinator_read_size_warn_threshold (2KiB)",
        "public void testClientLargeReadWarnEqAbort()",
        "public void testClientLargeReadWarnEnabledAbortDisabled()",
        "public void testClientLargeReadAbortEnabledWarnDisabled()",
        "public void testLocalLargeReadWarnGreaterThanAbort()",
        "local_read_size_fail_threshold (1KiB) must be greater than or equal to local_read_size_warn_threshold (2KiB)",
        "public void testLocalLargeReadWarnEqAbort()",
        "public void testLocalLargeReadWarnEnabledAbortDisabled()",
        "public void testLocalLargeReadAbortEnabledWarnDisabled()",
    ),
    YAML_CONFIGURATION_LOADER_TEST: (
        "public void readThresholdsFromConfig()",
        "assertThat(c.read_thresholds_enabled).isTrue();",
        "assertThat(c.coordinator_read_size_warn_threshold)",
        "assertThat(c.coordinator_read_size_fail_threshold)",
        "assertThat(c.local_read_size_warn_threshold)",
        "assertThat(c.local_read_size_fail_threshold)",
        "public void readThresholdsFromMap()",
        "\"read_thresholds_enabled\", true",
        "\"coordinator_read_size_warn_threshold\", \"1024KiB\"",
        "\"local_read_size_fail_threshold\", \"1024KiB\"",
    ),
}

DOC_TOKENS = (
    MATRIX_DOC,
    CHECKER_DOC,
    "research/tools/check-read-warning-abort-thresholds-drift.py",
    "Read Warning Abort Thresholds",
) + SCENARIO_IDS


@dataclass(frozen=True)
class CheckResult:
    name: str
    source: str
    ok: bool
    detail: str = ""


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def check_tokens(group: str, mapping: dict[str, tuple[str, ...]]) -> list[CheckResult]:
    checks: list[CheckResult] = []
    for path, tokens in mapping.items():
        text = read(path)
        checks.extend(
            CheckResult(f"{group} token {token}", path, token in text)
            for token in tokens
        )
    return checks


def source_checks() -> list[CheckResult]:
    return check_tokens("source", SOURCE_TOKEN_CHECKS)


def test_checks() -> list[CheckResult]:
    return check_tokens("test", TEST_TOKEN_CHECKS)


def doc_checks() -> list[CheckResult]:
    docs = "\n".join(read(path) for path in (MATRIX_DOC, CHECKER_DOC, README_DOC, SOURCE_MAP_DOC))
    return [CheckResult(f"doc token {token}", "research docs", token in docs) for token in DOC_TOKENS]


def check() -> list[CheckResult]:
    checks: list[CheckResult] = []
    checks.extend(source_checks())
    checks.extend(test_checks())
    checks.extend(doc_checks())
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable check results")
    args = parser.parse_args()

    checks = check()
    failed = [result for result in checks if not result.ok]

    if args.json:
        json.dump(
            {
                "ok": not failed,
                "total": len(checks),
                "failed": [result.__dict__ for result in failed],
            },
            sys.stdout,
            indent=2,
            sort_keys=True,
        )
        sys.stdout.write("\n")
    elif failed:
        for result in failed:
            suffix = f" ({result.detail})" if result.detail else ""
            print(f"FAIL {result.name}: {result.source}{suffix}", file=sys.stderr)
    else:
        print(f"OK read warning/abort threshold checks passed ({len(SCENARIO_IDS)} scenarios)")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
