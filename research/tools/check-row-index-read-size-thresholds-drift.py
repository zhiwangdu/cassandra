#!/usr/bin/env python3
#
# Source-only drift check for BigTable row-index read-size threshold research coverage.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

READ_COMMAND = "src/java/org/apache/cassandra/db/ReadCommand.java"
BIG_TABLE_READER = "src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java"
ROW_INDEX_ENTRY = "src/java/org/apache/cassandra/io/sstable/format/big/RowIndexEntry.java"
TRIE_INDEX_ENTRY = "src/java/org/apache/cassandra/io/sstable/format/bti/TrieIndexEntry.java"
BTI_TABLE_READER = "src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
CASSANDRA_YAML = "conf/cassandra.yaml"
STORAGE_SERVICE = "src/java/org/apache/cassandra/service/StorageService.java"
PARAM_TYPE = "src/java/org/apache/cassandra/net/ParamType.java"
WARNING_CONTEXT = "src/java/org/apache/cassandra/service/reads/thresholds/WarningContext.java"
WARNINGS_SNAPSHOT = "src/java/org/apache/cassandra/service/reads/thresholds/WarningsSnapshot.java"
COORDINATOR_WARNINGS = "src/java/org/apache/cassandra/service/reads/thresholds/CoordinatorWarnings.java"
TABLE_METRICS = "src/java/org/apache/cassandra/metrics/TableMetrics.java"
KEYSPACE_METRICS = "src/java/org/apache/cassandra/metrics/KeyspaceMetrics.java"
CLIENT_REQUEST_METRICS = "src/java/org/apache/cassandra/metrics/ClientRequestMetrics.java"

ROW_INDEX_SIZE_TEST = "test/distributed/org/apache/cassandra/distributed/test/thresholds/RowIndexSizeWarningTest.java"
ABSTRACT_CLIENT_SIZE_TEST = "test/distributed/org/apache/cassandra/distributed/test/thresholds/AbstractClientSizeWarning.java"
DATABASE_DESCRIPTOR_TEST = "test/unit/org/apache/cassandra/config/DatabaseDescriptorTest.java"
YAML_CONFIGURATION_LOADER_TEST = "test/unit/org/apache/cassandra/config/YamlConfigurationLoaderTest.java"

MATRIX_DOC = "research/module-row-index-read-size-thresholds-matrix.md"
CHECKER_DOC = "research/module-row-index-read-size-thresholds-drift-checker.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

SCENARIO_IDS = (
    "row_index_read_size_threadlocal_contract",
    "row_index_read_size_big_lookup_contract",
    "row_index_read_size_entry_shape_contract",
    "row_index_read_size_threshold_gate",
    "row_index_read_size_memory_estimate_contract",
    "row_index_read_size_warn_contract",
    "row_index_read_size_abort_contract",
    "row_index_read_size_warning_aggregation_contract",
    "row_index_read_size_metrics_contract",
    "row_index_read_size_config_jmx_contract",
    "row_index_read_size_bti_boundary",
    "row_index_read_size_tests_baseline",
    "row_index_read_size_scan_test_boundary",
)

SOURCE_TOKEN_CHECKS = {
    READ_COMMAND: (
        "private static final FastThreadLocal<ReadCommand> COMMAND = new FastThreadLocal<>();",
        "public static ReadCommand getCommand()",
        "COMMAND.set(this);",
        "COMMAND.set(null);",
    ),
    BIG_TABLE_READER: (
        "RowIndexEntry rie = getRowIndexEntry(key, SSTableReader.Operator.EQ, true, listener);",
        "if (!isPresentInFilter((IFilter.FilterKey) key))",
        "AbstractRowIndexEntry cachedPosition = getCachedPosition(decoratedKey, updateStats);",
        "notifySelected(SelectionReason.KEY_CACHE_HIT, listener, operator, updateStats, cachedPosition);",
        "int binarySearchResult = indexSummary.binarySearch(key);",
        "try (FileDataInput in = ifile.createReader(sampledPosition))",
        "RowIndexEntry indexEntry = rowIndexEntrySerializer.deserialize(in);",
        "cacheKey(decoratedKey, indexEntry);",
        "notifySelected(SelectionReason.INDEX_ENTRY_FOUND, listener, operator, updateStats, indexEntry);",
        "RowIndexEntry.Serializer.skip(in, descriptor.version);",
    ),
    ROW_INDEX_ENTRY: (
        "public class RowIndexEntry extends AbstractRowIndexEntry",
        "indexEntrySizeHistogram = Metrics.histogram(factory.createMetricName(\"IndexedEntrySize\"), false);",
        "indexInfoCountHistogram = Metrics.histogram(factory.createMetricName(\"IndexInfoCount\"), false);",
        "indexInfoGetsHistogram = Metrics.histogram(factory.createMetricName(\"IndexInfoGets\"), false);",
        "indexInfoReadsHistogram = Metrics.histogram(factory.createMetricName(\"IndexInfoReads\"), false);",
        "public static RowIndexEntry create(long dataFilePosition, long indexFilePosition,",
        "return new IndexedEntry(dataFilePosition, deletionTime, headerLength,",
        "return new ShallowIndexedEntry(dataFilePosition, indexFilePosition,",
        "return new RowIndexEntry(dataFilePosition);",
        "private final TableMetrics tableMetrics;",
        "public RowIndexEntry deserialize(DataInputPlus in, long indexFilePosition) throws IOException",
        "checkSize(columnsIndexCount, size);",
        "size <= DatabaseDescriptor.getColumnIndexCacheSize()",
        "in.skipBytes(indexedPartSize);",
        "private void checkSize(int entries, int bytes)",
        "ReadCommand command = ReadCommand.getCommand();",
        "SchemaConstants.isSystemKeyspace(command.metadata().keyspace)",
        "!DatabaseDescriptor.getReadThresholdsEnabled()",
        "DatabaseDescriptor.getRowIndexReadSizeWarnThreshold();",
        "DatabaseDescriptor.getRowIndexReadSizeFailThreshold();",
        "long estimatedMemory = estimateMaterializedIndexSize(entries, bytes);",
        "tableMetrics.rowIndexSize.update(estimatedMemory);",
        "estimatedMemory > failThreshold.toBytes()",
        "row_index_read_size_fail_threshold",
        "MessageParams.remove(ParamType.ROW_INDEX_READ_SIZE_WARN);",
        "MessageParams.add(ParamType.ROW_INDEX_READ_SIZE_FAIL, estimatedMemory);",
        "throw new RowIndexEntryReadSizeTooLargeException(msg);",
        "Long current = MessageParams.get(ParamType.ROW_INDEX_READ_SIZE_WARN);",
        "MessageParams.add(ParamType.ROW_INDEX_READ_SIZE_WARN, estimatedMemory);",
        "private static long estimateMaterializedIndexSize(int entries, int bytes)",
        "IndexInfo.EMPTY_SIZE",
        "ArrayClustering.EMPTY_SIZE",
        "DeletionTime.EMPTY_SIZE",
        "private static final class IndexedEntry extends RowIndexEntry",
        "private static final class ShallowIndexedEntry extends RowIndexEntry",
        "public interface IndexInfoRetriever extends AutoCloseable",
        "indexEntrySizeHistogram.update(serializedSize(deletionTime, headerLength, columnsIndex.length, version) + indexedPartSize);",
        "indexEntrySizeHistogram.update(indexedPartSize + fieldsSerializedSize);",
        "indexInfoReadsHistogram.update(retrievals);",
        "public static class RowIndexEntryReadSizeTooLargeException extends RejectException",
    ),
    TRIE_INDEX_ENTRY: (
        "final class TrieIndexEntry extends AbstractRowIndexEntry",
        "private static AssertionError noKeyCacheError()",
        "BTI SSTables should not use key cache",
        "throw new AssertionError(\"BTI SSTables index entries should not be persisted in any in-memory structure\");",
    ),
    BTI_TABLE_READER: (
        "protected TrieIndexEntry getRowIndexEntry",
        "return getExactPosition((DecoratedKey) key, listener, updateStats);",
        "try (PartitionIndex.Reader reader = partitionIndex.openReader())",
        "TrieIndexEntry rie = reader.ceiling",
        "notifySelected(SelectionReason.INDEX_ENTRY_FOUND, listener, operator, updateStats, rie);",
    ),
    CONFIG: (
        "public volatile boolean read_thresholds_enabled = false;",
        "public volatile DataStorageSpec.LongBytesBound row_index_read_size_warn_threshold = null;",
        "public volatile DataStorageSpec.LongBytesBound row_index_read_size_fail_threshold = null;",
    ),
    DATABASE_DESCRIPTOR: (
        "validateReadThresholds(\"row_index_read_size\", config.row_index_read_size_warn_threshold, config.row_index_read_size_fail_threshold);",
        "getRowIndexReadSizeWarnThreshold()",
        "setRowIndexReadSizeWarnThreshold",
        "getRowIndexReadSizeFailThreshold()",
        "setRowIndexReadSizeFailThreshold",
        "row_index_read_size_warn_threshold",
        "row_index_read_size_fail_threshold",
    ),
    CASSANDRA_YAML: (
        "read_thresholds_enabled: false",
        "When read_thresholds_enabled: true, this tracks the expected memory size of the RowIndexEntry",
        "row_index_read_size_warn_threshold:",
        "row_index_read_size_fail_threshold:",
    ),
    STORAGE_SERVICE: (
        "getRowIndexReadSizeWarnThreshold()",
        "setRowIndexReadSizeWarnThreshold(String threshold)",
        "getRowIndexReadSizeAbortThreshold()",
        "setRowIndexReadSizeAbortThreshold(String threshold)",
        "DatabaseDescriptor.setRowIndexReadSizeWarnThreshold(parseDataStorageSpec(threshold));",
        "DatabaseDescriptor.setRowIndexReadSizeFailThreshold(parseDataStorageSpec(threshold));",
    ),
    PARAM_TYPE: (
        "ROW_INDEX_READ_SIZE_FAIL",
        "ROW_INDEX_READ_SIZE_WARN",
    ),
    WARNING_CONTEXT: (
        "ParamType.ROW_INDEX_READ_SIZE_WARN, ParamType.ROW_INDEX_READ_SIZE_FAIL",
        "final WarnAbortCounter rowIndexReadSize = new WarnAbortCounter();",
        "case ROW_INDEX_READ_SIZE_FAIL:",
        "reason = RequestFailureReason.READ_SIZE;",
        "case ROW_INDEX_READ_SIZE_WARN:",
        "counter = rowIndexReadSize;",
        "WarningsSnapshot.create(tombstones.snapshot(), localReadSize.snapshot(), rowIndexReadSize.snapshot(), indexReadSSTablesCount.snapshot())",
    ),
    WARNINGS_SNAPSHOT: (
        "public final Warnings tombstones, localReadSize, rowIndexReadSize, indexReadSSTablesCount;",
        "if (!rowIndexReadSize.aborts.instances.isEmpty())",
        "throw new ReadSizeAbortException(rowIndexReadSizeAbortMessage",
        "rowIndexReadSizeAbortMessage",
        "rowIndexSizeWarnMessage",
        "(see row_index_size_fail_threshold)",
        "(see row_index_size_warn_threshold)",
        "public Builder rowIndexSizeWarning(Counter counter)",
        "public Builder rowIndexSizeAbort(Counter counter)",
    ),
    COORDINATOR_WARNINGS: (
        "recordAborts(merged.rowIndexReadSize, cql, loggableTokens, cfs.metric.rowIndexSizeAborts",
        "recordWarnings(merged.rowIndexReadSize, cql, loggableTokens, cfs.metric.rowIndexSizeWarnings",
        "ClientWarn.instance.warn(msg + \" with \" + loggableTokens);",
        "metric.mark();",
    ),
    TABLE_METRICS: (
        "public final TableMeter rowIndexSizeWarnings;",
        "public final TableMeter rowIndexSizeAborts;",
        "public final TableHistogram rowIndexSize;",
        "createTableMeter(\"RowIndexSizeWarnings\"",
        "createTableMeter(\"RowIndexSizeAborts\"",
        "createTableHistogram(\"RowIndexSize\"",
    ),
    KEYSPACE_METRICS: (
        "public final Meter rowIndexSizeWarnings;",
        "public final Meter rowIndexSizeAborts;",
        "public final Histogram rowIndexSize;",
        "createKeyspaceMeter(\"RowIndexSizeWarnings\")",
        "createKeyspaceMeter(\"RowIndexSizeAborts\")",
        "createKeyspaceHistogram(\"RowIndexSize\", false)",
    ),
    CLIENT_REQUEST_METRICS: (
        "public final Meter readSizeAborts;",
        "cause instanceof ReadSizeAbortException",
        "readSizeAborts.mark();",
    ),
}

TEST_TOKEN_CHECKS = {
    ROW_INDEX_SIZE_TEST: (
        "public class RowIndexSizeWarningTest extends AbstractClientSizeWarning",
        "Assume.assumeTrue(CLUSTER.get(1).callOnInstance(() -> BigFormat.isSelected()));",
        "DatabaseDescriptor.setRowIndexReadSizeWarnThreshold(new DataStorageSpec.LongBytesBound(1, KIBIBYTES));",
        "DatabaseDescriptor.setRowIndexReadSizeFailThreshold(new DataStorageSpec.LongBytesBound(2, KIBIBYTES));",
        "DatabaseDescriptor.setColumnIndexCacheSize(1 << 20);",
        "DatabaseDescriptor.setColumnIndexSizeInKiB(0);",
        "protected boolean shouldFlush()",
        "protected int warnThresholdRowCount()",
        "protected int failThresholdRowCount()",
        "Ignore Scans",
        "(see row_index_size_warn_threshold)",
        "(see row_index_size_fail_threshold)",
        "org.apache.cassandra.metrics.keyspace.RowIndexSize.",
        "org.apache.cassandra.metrics.keyspace.RowIndexSizeWarnings.",
        "org.apache.cassandra.metrics.keyspace.RowIndexSizeAborts.",
    ),
    ABSTRACT_CLIENT_SIZE_TEST: (
        "disable key cache so RowIndexEntry is read each time",
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
    DATABASE_DESCRIPTOR_TEST: (
        "public void testRowIndexSizeWarnGreaterThanAbort()",
        "row_index_read_size_fail_threshold (1KiB) must be greater than or equal to row_index_read_size_warn_threshold (2KiB)",
        "public void testRowIndexSizeWarnEqAbort()",
        "public void testRowIndexSizeWarnEnabledAbortDisabled()",
        "public void testRowIndexSizeAbortEnabledWarnDisabled()",
    ),
    YAML_CONFIGURATION_LOADER_TEST: (
        "public void readThresholdsFromConfig()",
        "assertThat(c.row_index_read_size_warn_threshold)",
        "assertThat(c.row_index_read_size_fail_threshold)",
        "public void readThresholdsFromMap()",
        "\"row_index_read_size_warn_threshold\", \"1024KiB\"",
        "\"row_index_read_size_fail_threshold\", \"1024KiB\"",
    ),
}

DOC_TOKENS = (
    MATRIX_DOC,
    CHECKER_DOC,
    "research/tools/check-row-index-read-size-thresholds-drift.py",
    "Row Index Read Size Thresholds",
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
        print(f"OK row-index read-size threshold checks passed ({len(SCENARIO_IDS)} scenarios)")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
