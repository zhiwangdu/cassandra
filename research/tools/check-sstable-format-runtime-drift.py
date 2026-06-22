#!/usr/bin/env python3
#
# Source/test/doc drift check for SSTable format/runtime research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

SSTABLE_FORMAT = "src/java/org/apache/cassandra/io/sstable/format/SSTableFormat.java"
ABSTRACT_SSTABLE_FORMAT = "src/java/org/apache/cassandra/io/sstable/format/AbstractSSTableFormat.java"
VERSION = "src/java/org/apache/cassandra/io/sstable/format/Version.java"
DESCRIPTOR = "src/java/org/apache/cassandra/io/sstable/Descriptor.java"
COMPONENT = "src/java/org/apache/cassandra/io/sstable/Component.java"
SSTABLE = "src/java/org/apache/cassandra/io/sstable/SSTable.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
STORAGE_COMPATIBILITY_MODE = "src/java/org/apache/cassandra/utils/StorageCompatibilityMode.java"
CASSANDRA_YAML = "conf/cassandra.yaml"

SSTABLE_READER = "src/java/org/apache/cassandra/io/sstable/format/SSTableReader.java"
SSTABLE_READER_LOADING_BUILDER = "src/java/org/apache/cassandra/io/sstable/format/SSTableReaderLoadingBuilder.java"
SSTABLE_READER_WITH_FILTER = "src/java/org/apache/cassandra/io/sstable/format/SSTableReaderWithFilter.java"
SSTABLE_WRITER = "src/java/org/apache/cassandra/io/sstable/format/SSTableWriter.java"
SORTED_TABLE_WRITER = "src/java/org/apache/cassandra/io/sstable/format/SortedTableWriter.java"
DATA_COMPONENT = "src/java/org/apache/cassandra/io/sstable/format/DataComponent.java"
STATS_COMPONENT = "src/java/org/apache/cassandra/io/sstable/format/StatsComponent.java"
COMPRESSION_INFO_COMPONENT = "src/java/org/apache/cassandra/io/sstable/format/CompressionInfoComponent.java"
TOC_COMPONENT = "src/java/org/apache/cassandra/io/sstable/format/TOCComponent.java"

METADATA_TYPE = "src/java/org/apache/cassandra/io/sstable/metadata/MetadataType.java"
METADATA_COLLECTOR = "src/java/org/apache/cassandra/io/sstable/metadata/MetadataCollector.java"
METADATA_SERIALIZER = "src/java/org/apache/cassandra/io/sstable/metadata/MetadataSerializer.java"
STATS_METADATA = "src/java/org/apache/cassandra/io/sstable/metadata/StatsMetadata.java"
VALIDATION_METADATA = "src/java/org/apache/cassandra/io/sstable/metadata/ValidationMetadata.java"
COMPACTION_METADATA = "src/java/org/apache/cassandra/io/sstable/metadata/CompactionMetadata.java"

BIG_FORMAT = "src/java/org/apache/cassandra/io/sstable/format/big/BigFormat.java"
BIG_READER = "src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java"
BIG_WRITER = "src/java/org/apache/cassandra/io/sstable/format/big/BigTableWriter.java"
BIG_LOADING = "src/java/org/apache/cassandra/io/sstable/format/big/BigSSTableReaderLoadingBuilder.java"
BTI_FORMAT = "src/java/org/apache/cassandra/io/sstable/format/bti/BtiFormat.java"
BTI_READER = "src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java"
BTI_WRITER = "src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableWriter.java"
BTI_LOADING = "src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReaderLoadingBuilder.java"
PARTITION_INDEX = "src/java/org/apache/cassandra/io/sstable/format/bti/PartitionIndex.java"
TRIE_INDEX_ENTRY = "src/java/org/apache/cassandra/io/sstable/format/bti/TrieIndexEntry.java"

SSTABLE_FORMAT_TEST = "test/unit/org/apache/cassandra/io/sstable/SSTableFormatTest.java"
STORAGE_COMPATIBILITY_MODE_TEST = "test/unit/org/apache/cassandra/utils/StorageCompatibilityModeTest.java"
SSTABLE_READER_TEST = "test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java"
SSTABLE_WRITER_TEST = "test/unit/org/apache/cassandra/io/sstable/SSTableWriterTest.java"
SSTABLE_WRITER_TRANSACTION_TEST = "test/unit/org/apache/cassandra/io/sstable/SSTableWriterTransactionTest.java"
METADATA_SERIALIZER_TEST = "test/unit/org/apache/cassandra/io/sstable/metadata/MetadataSerializerTest.java"
CQL_SSTABLE_WRITER_TEST = "test/unit/org/apache/cassandra/io/sstable/CQLSSTableWriterTest.java"
BTI_LOADING_TEST = "test/unit/org/apache/cassandra/io/sstable/format/bti/LoadingBuilderTest.java"
VERIFY_TEST = "test/unit/org/apache/cassandra/io/sstable/VerifyTest.java"
SCRUB_TEST = "test/unit/org/apache/cassandra/io/sstable/ScrubTest.java"
LEGACY_SSTABLE_TEST = "test/unit/org/apache/cassandra/io/sstable/LegacySSTableTest.java"
SSTABLE_LOADER_LEGACY_TEST = "test/unit/org/apache/cassandra/io/sstable/SSTableLoaderLegacyTest.java"

TARGET_DOCS = (
    "research/module-sstable-compaction.md",
    "research/module-bloom-sstable-index-deep-dive.md",
    "research/module-bloom-index-summary-operations-matrix.md",
    "research/module-sstable-format-runtime-matrix.md",
    "research/module-sstable-format-runtime-drift-checker.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "sstable_format_registry_config_contract",
    "sstable_descriptor_component_contract",
    "sstable_reader_open_components_contract",
    "sstable_writer_finish_toc_contract",
    "sstable_metadata_stats_mutation_contract",
    "sstable_big_format_components_contract",
    "sstable_bti_format_components_contract",
    "sstable_filter_keycache_metrics_contract",
    "sstable_verify_scrub_contract",
    "sstable_cql_writer_format_contract",
    "sstable_legacy_compatibility_contract",
    "sstable_runtime_gap_contract",
)

SOURCE_TOKEN_CHECKS = {
    SSTABLE_FORMAT: (
        "public interface SSTableFormat<R extends SSTableReader, W extends SSTableWriter>",
        "SSTableWriterFactory<W, ?> getWriterFactory();",
        "SSTableReaderFactory<R, ?> getReaderFactory();",
        "Set<Component> primaryComponents();",
        "Set<Component> generatedOnLoadComponents();",
        "IScrubber getScrubber(ColumnFamilyStore cfs,",
        "public static final Component.Type DATA = Component.Type.createSingleton(\"DATA\", \"Data.db\", true, null);",
        "public static final Component.Type STATS = Component.Type.createSingleton(\"STATS\", \"Statistics.db\", true, null);",
        "public static final Component.Type FILTER = Component.Type.createSingleton(\"FILTER\", \"Filter.db\", true, null);",
        "public static final Component.Type TOC = Component.Type.createSingleton(\"TOC\", \"TOC.txt\", false, null);",
        "interface Factory",
        "SSTableFormat<?, ?> getInstance(@Nonnull Map<String, String> options);",
    ),
    ABSTRACT_SSTABLE_FORMAT: (
        "public abstract class AbstractSSTableFormat<R extends SSTableReader, W extends SSTableWriter> implements SSTableFormat<R, W>",
        "public final String name;",
        "protected final Map<String, String> options;",
        "return name + \":\" + options;",
    ),
    VERSION: (
        "public abstract class Version",
        "public abstract boolean hasOldBfFormat();",
        "public static boolean validate(String ver)",
        "abstract public boolean isCompatible();",
        "abstract public boolean isCompatibleForStreaming();",
    ),
    DESCRIPTOR: (
        "public class Descriptor",
        "private final File baseFile;",
        "private String filenameFor(Component component)",
        "public File baseFile()",
        "public static Descriptor fromFile(File file)",
        "public static Pair<Descriptor, Component> fromFileWithComponent(File file)",
        "private static SSTableInfo validateAndExtractInfo(File file)",
        "if (!Version.validate(versionString))",
        "if (!version.isCompatible())",
        "public boolean isCompatible()",
    ),
    COMPONENT: (
        "public class Component",
        "private static void registerType(Type type)",
        "throw new AssertionError(\"Type named \" + type.name + \" is already registered\");",
    ),
    SSTABLE: (
        "public abstract class SSTable",
        "public static void validateRepairedMetadata(long repairedAt, TimeUUID pendingRepair, boolean isTransient)",
        "TOCComponent.updateTOC(descriptor, componentsToAdd);",
        "public synchronized void registerComponents(Collection<Component> newComponents, Tracker tracker)",
        "public synchronized void unregisterComponents(Collection<Component> removeComponents, Tracker tracker)",
    ),
    CONFIG: (
        "public String selected_format = BigFormat.NAME;",
        "public StorageCompatibilityMode storage_compatibility_mode;",
    ),
    DATABASE_DESCRIPTOR: (
        "private static volatile SSTableFormat<?, ?> selectedSSTableFormat;",
        "private static void applySSTableFormats()",
        "ServiceLoader<SSTableFormat.Factory> loader = ServiceLoader.load(SSTableFormat.Factory.class, DatabaseDescriptor.class.getClassLoader());",
        "factories = ImmutableList.of(new BigFormat.BigFormatFactory());",
        "private static void applySSTableFormats(Iterable<SSTableFormat.Factory> factories, Config.SSTableConfig sstableFormatsConfig)",
        "selectedSSTableFormat = getAndValidateWriteFormat(sstableFormats, sstableFormatsConfig.selected_format);",
        "sstableFormats.values().forEach(SSTableFormat::allComponents);",
        "public static void resetSSTableFormats(Iterable<SSTableFormat.Factory> factories, Config.SSTableConfig config)",
        "public static ImmutableMap<String, SSTableFormat<?, ?>> getSSTableFormats()",
        "public static SSTableFormat<?, ?> getSelectedSSTableFormat()",
    ),
    STORAGE_COMPATIBILITY_MODE: (
        "public enum StorageCompatibilityMode",
        "public void validateSstableFormat(SSTableFormat<?, ?> selectedFormat)",
        "if (selectedFormat.name().equals(BtiFormat.NAME) && this == StorageCompatibilityMode.CASSANDRA_4)",
    ),
    CASSANDRA_YAML: (
        "# The sstable formats configuration. SSTable formats implementations are",
        "# The default format is \"big\", the legacy SSTable format in use since Cassandra 3.0.",
        "# Cassandra versions 5.0 and later also support the trie-indexed \"bti\" format,",
        "#  selected_format: big",
        "storage_compatibility_mode: CASSANDRA_4",
    ),
    SSTABLE_READER: (
        "public abstract class SSTableReader extends SSTable implements UnfilteredSource, SelfRefCounted<SSTableReader>, Comparable<SSTableReader>",
        "public static SSTableReader open(SSTable.Owner owner, Descriptor descriptor)",
        "public static SSTableReader open(Owner owner,",
        "return builder.build(owner, validate, !isOffline);",
        "public abstract void releaseInMemoryComponents();",
        "public void mutateLevelAndReload(int newLevel) throws IOException",
        "public void mutateRepairedAndReload(long newRepairedAt, TimeUUID newPendingRepair, boolean isTransient) throws IOException",
        "this.sstableMetadata = StatsComponent.load(descriptor).statsMetadata();",
    ),
    SSTABLE_READER_LOADING_BUILDER: (
        "public abstract class SSTableReaderLoadingBuilder<R extends SSTableReader, B extends SSTableReader.Builder<R, B>>",
        "this.components = builder.getComponents() != null ? ImmutableSet.copyOf(builder.getComponents()) : TOCComponent.loadOrCreate(this.descriptor);",
        "public R build(SSTable.Owner owner, boolean validate, boolean online)",
        "checkArgument(components.contains(Components.DATA), \"Data component is missing for sstable %s\", descriptor);",
        "checkArgument(this.components.containsAll(descriptor.getFormat().primaryComponents()),",
        "CompressionInfoComponent.verifyCompressionInfoExistenceIfApplicable(descriptor, builder.getComponents());",
        "openComponents(builder, owner, validate, online);",
        "protected abstract void openComponents(B builder, SSTable.Owner owner, boolean validate, boolean online) throws IOException;",
    ),
    SSTABLE_READER_WITH_FILTER: (
        "public abstract class SSTableReaderWithFilter extends SSTableReader",
        "private final IFilter filter;",
        "private final BloomFilterTracker filterTracker;",
        "return !filter.isInformative() && getPosition(key, Operator.EQ, false) >= 0 || filter.isPresent(key);",
        "filterTracker.addTruePositive();",
        "filterTracker.addTrueNegative();",
        "filterTracker.addFalsePositive();",
    ),
    SSTABLE_WRITER: (
        "public abstract class SSTableWriter extends SSTable implements Transactional",
        "protected final MetadataCollector metadataCollector;",
        "public abstract AbstractRowIndexEntry append(UnfilteredRowIterator iterator);",
        "public abstract SSTableReader openFinalEarly();",
        "public SSTableReader finish(boolean openResult)",
        "observers.forEach(SSTableFlushObserver::complete);",
        "protected Map<MetadataType, MetadataComponent> finalizeMetadata()",
        "new StatsComponent(finalizeMetadata()).save(descriptor);",
        "TOCComponent.updateTOC(descriptor, components);",
        "addComponents(ImmutableSet.of(Components.DATA, Components.STATS, Components.DIGEST, Components.TOC));",
    ),
    SORTED_TABLE_WRITER: (
        "public abstract class SortedTableWriter<P extends SortedTablePartitionWriter, I extends SortedTableWriter.AbstractIndexWriter> extends SSTableWriter",
        "private final FileHandle.Builder dataFileBuilder = new FileHandle.Builder(descriptor.fileFor(Components.DATA));",
        "public final AbstractRowIndexEntry append(UnfilteredRowIterator partition)",
        "long finishResult = partitionWriter.finish();",
        "if (components.contains(Components.FILTER))",
        "public B addDefaultComponents(Collection<Index.Group> indexGroups)",
    ),
    DATA_COMPONENT: (
        "public class DataComponent",
        "return new CompressedSequentialWriter(descriptor.fileFor(Components.DATA),",
        "return new ChecksummedSequentialWriter(descriptor.fileFor(Components.DATA),",
    ),
    STATS_COMPONENT: (
        "public class StatsComponent",
        "public static StatsComponent load(Descriptor descriptor) throws IOException",
        "public static StatsComponent load(Descriptor descriptor, MetadataType... types) throws IOException",
        "throw new CorruptSSTableException(e, descriptor.fileFor(Components.STATS));",
    ),
    COMPRESSION_INFO_COMPONENT: (
        "public class CompressionInfoComponent",
        "public static CompressionMetadata load(Descriptor descriptor)",
        "public static void verifyCompressionInfoExistenceIfApplicable(Descriptor descriptor, Set<Component> actualComponents) throws CorruptSSTableException, FSReadError",
    ),
    TOC_COMPONENT: (
        "public class TOCComponent",
        "public static Set<Component> loadOrCreate(Descriptor descriptor)",
        "Set<Component> components = descriptor.discoverComponents();",
        "TOCComponent.updateTOC(descriptor, components);",
    ),
    METADATA_TYPE: (
        "public enum MetadataType",
        "VALIDATION(ValidationMetadata.serializer)",
        "COMPACTION(CompactionMetadata.serializer)",
        "STATS(StatsMetadata.serializer)",
        "HEADER((IMetadataComponentSerializer)SerializationHeader.serializer);",
    ),
    METADATA_COLLECTOR: (
        "public class MetadataCollector implements PartitionStatisticsCollector",
        "protected EstimatedHistogram estimatedPartitionSize = defaultPartitionSizeHistogram();",
        "protected IntervalSet<CommitLogPosition> commitLogIntervals = IntervalSet.empty();",
        "public MetadataCollector commitLogIntervals(IntervalSet<CommitLogPosition> commitLogIntervals)",
        "public MetadataCollector sstableLevel(int sstableLevel)",
        "public Map<MetadataType, MetadataComponent> finalizeMetadata(String partitioner, double bloomFilterFPChance, long repairedAt, TimeUUID pendingRepair, boolean isTransient, SerializationHeader header, ByteBuffer firstKey, ByteBuffer lastKey)",
        "components.put(MetadataType.VALIDATION, new ValidationMetadata(partitioner, bloomFilterFPChance));",
        "components.put(MetadataType.STATS, new StatsMetadata(estimatedPartitionSize,",
        "components.put(MetadataType.COMPACTION, new CompactionMetadata(cardinality));",
        "components.put(MetadataType.HEADER, header.toComponent());",
    ),
    METADATA_SERIALIZER: (
        "public class MetadataSerializer implements IMetadataSerializer",
        "public void serialize(Map<MetadataType, MetadataComponent> components, DataOutputPlus out, Version version) throws IOException",
        "public Map<MetadataType, MetadataComponent> deserialize(Descriptor descriptor, EnumSet<MetadataType> types) throws IOException",
        "public void mutateLevel(Descriptor descriptor, int newLevel) throws IOException",
        "public void mutateRepairMetadata(Descriptor descriptor, long newRepairedAt, TimeUUID newPendingRepair, boolean isTransient) throws IOException",
        "private void mutate(Descriptor descriptor, UnaryOperator<StatsMetadata> transform) throws IOException",
        "public void rewriteSSTableMetadata(Descriptor descriptor, Map<MetadataType, MetadataComponent> currentComponents) throws IOException",
    ),
    STATS_METADATA: (
        "public class StatsMetadata extends MetadataComponent",
        "public final EstimatedHistogram estimatedPartitionSize;",
        "public final IntervalSet<CommitLogPosition> commitLogIntervals;",
        "public final long minTimestamp;",
        "public final long maxTimestamp;",
        "public final int sstableLevel;",
        "public final long repairedAt;",
        "public final TimeUUID pendingRepair;",
        "public final boolean isTransient;",
        "public StatsMetadata mutateLevel(int newLevel)",
        "public StatsMetadata mutateRepairedMetadata(long newRepairedAt, TimeUUID newPendingRepair, boolean newIsTransient)",
        "public void serialize(Version version, StatsMetadata component, DataOutputPlus out) throws IOException",
        "public StatsMetadata deserialize(Version version, DataInputPlus in) throws IOException",
    ),
    VALIDATION_METADATA: (
        "public class ValidationMetadata extends MetadataComponent",
        "public static final IMetadataComponentSerializer serializer = new ValidationMetadataSerializer();",
        "return MetadataType.VALIDATION;",
    ),
    COMPACTION_METADATA: (
        "public class CompactionMetadata extends MetadataComponent",
        "public static final IMetadataComponentSerializer serializer = new CompactionMetadataSerializer();",
        "return MetadataType.COMPACTION;",
    ),
    BIG_FORMAT: (
        "public class BigFormat extends AbstractSSTableFormat<BigTableReader, BigTableWriter>",
        "public static final String NAME = \"big\";",
        "public static final Component.Type PRIMARY_INDEX = Component.Type.createSingleton(\"PRIMARY_INDEX\", \"Index.db\", true, BigFormat.class);",
        "public static final Component.Type SUMMARY = Component.Type.createSingleton(\"SUMMARY\", \"Summary.db\", true, BigFormat.class);",
        "private static final Set<Component> PRIMARY_COMPONENTS = ImmutableSet.of(DATA,",
        "private static final Set<Component> GENERATED_ON_LOAD_COMPONENTS = ImmutableSet.of(FILTER, SUMMARY);",
        "private static final Set<Component> MUTABLE_COMPONENTS = ImmutableSet.of(STATS,",
        "public Set<Component> generatedOnLoadComponents()",
        "static class BigTableReaderFactory implements SSTableReaderFactory<BigTableReader, BigTableReader.Builder>",
        "static class BigTableWriterFactory implements SSTableWriterFactory<BigTableWriter, BigTableWriter.Builder>",
    ),
    BIG_READER: (
        "public class BigTableReader extends SSTableReaderWithFilter implements IndexSummarySupport<BigTableReader>,",
        "public UnfilteredRowIterator rowIterator(DecoratedKey key,",
        "RowIndexEntry rie = getRowIndexEntry(key, SSTableReader.Operator.EQ, true, listener);",
        "public RowIndexEntry getRowIndexEntry(PartitionPosition key,",
        "notifySkipped(SkippingReason.BLOOM_FILTER, listener, operator, updateStats);",
        "notifySkipped(SkippingReason.PARTITION_INDEX_LOOKUP, listener, operator, updateStats);",
        "markSuspect();",
        "new IndexSummaryComponent(newSummary, getFirst(), getLast()).save(descriptor.fileFor(Components.SUMMARY), true);",
    ),
    BIG_WRITER: (
        "public class BigTableWriter extends SortedTableWriter<BigFormatPartitionWriter, BigTableWriter.IndexWriter>",
        "indexWriter.append(key, entry, dataWriter.position(), partitionWriter.buffer());",
        "protected static class IndexWriter extends SortedTableWriter.AbstractIndexWriter",
        "writer = new SequentialWriter(b.descriptor.fileFor(Components.PRIMARY_INDEX), b.getIOOptions().writerOptions);",
        "public void append(DecoratedKey key, RowIndexEntry indexEntry, long dataEnd, ByteBuffer indexInfo) throws IOException",
        "new IndexSummaryComponent(indexSummary, first, last).save(descriptor.fileFor(Components.SUMMARY), true);",
        "addComponents(ImmutableSet.of(Components.PRIMARY_INDEX, Components.SUMMARY));",
    ),
    BIG_LOADING: (
        "public class BigSSTableReaderLoadingBuilder extends SortedTableReaderLoadingBuilder<BigTableReader, BigTableReader.Builder>",
        "StatsComponent statsComponent = StatsComponent.load(descriptor, MetadataType.STATS, MetadataType.HEADER, MetadataType.VALIDATION);",
        "if (builder.getComponents().contains(Components.PRIMARY_INDEX) && (rebuildFilter || rebuildSummary))",
        "summaryComponent.save(descriptor.fileFor(Components.SUMMARY), false);",
        "public long estimateRowsFromIndex(FileHandle indexFile) throws IOException",
    ),
    BTI_FORMAT: (
        "public class BtiFormat extends AbstractSSTableFormat<BtiTableReader, BtiTableWriter>",
        "public static final String NAME = \"bti\";",
        "public static final Component.Type PARTITION_INDEX = Component.Type.createSingleton(\"PARTITION_INDEX\", \"Partitions.db\", true, BtiFormat.class);",
        "public static final Component.Type ROW_INDEX = Component.Type.createSingleton(\"ROW_INDEX\", \"Rows.db\", true, BtiFormat.class);",
        "private final static Set<Component> PRIMARY_COMPONENTS = ImmutableSet.of(DATA,",
        "private final static Set<Component> GENERATED_ON_LOAD_COMPONENTS = ImmutableSet.of(FILTER);",
        "static final BtiTableReaderFactory readerFactory = new BtiTableReaderFactory();",
        "static final BtiTableWriterFactory writerFactory = new BtiTableWriterFactory();",
    ),
    BTI_READER: (
        "public class BtiTableReader extends SSTableReaderWithFilter",
        "private final PartitionIndex partitionIndex;",
        "protected TrieIndexEntry getRowIndexEntry(PartitionPosition key,",
        "TrieIndexEntry rie = reader.ceiling(searchKey, (pos, assumeNoMatch, compareKey) -> retrieveEntryIfAcceptable(searchOp, compareKey, pos, assumeNoMatch));",
        "TrieIndexEntry getExactPosition(DecoratedKey dk,",
        "long indexPos = reader.exactCandidate(dk);",
        "notifySkipped(SkippingReason.PARTITION_INDEX_LOOKUP, listener, EQ, updateStats);",
        "TrieIndexEntry rie = indexPos >= 0 ? TrieIndexEntry.deserialize(in, in.getFilePointer(), descriptor.version)",
        "public UnfilteredRowIterator rowIterator(DecoratedKey key,",
    ),
    BTI_WRITER: (
        "public class BtiTableWriter extends SortedTableWriter<BtiFormatPartitionWriter, BtiTableWriter.IndexWriter>",
        "protected static class IndexWriter extends SortedTableWriter.AbstractIndexWriter",
        "private final PartitionIndexBuilder partitionIndex;",
        "final SequentialWriter rowIndexWriter;",
    ),
    BTI_LOADING: (
        "public class BtiTableReaderLoadingBuilder extends SortedTableReaderLoadingBuilder<BtiTableReader, BtiTableReader.Builder>",
        "StatsComponent statsComponent = StatsComponent.load(descriptor, MetadataType.STATS, MetadataType.HEADER, MetadataType.VALIDATION);",
        "if (builder.getComponents().contains(Components.PARTITION_INDEX) && builder.getComponents().contains(Components.ROW_INDEX) && rebuildFilter)",
        "builder.setPartitionIndex(openPartitionIndex(!builder.getFilter().isInformative()));",
        "private PartitionIndex openPartitionIndex(boolean preload) throws IOException",
        "return PartitionIndex.load(indexFile, tableMetadataRef.getLocal().partitioner, preload);",
    ),
    PARTITION_INDEX: (
        "public class PartitionIndex implements SharedCloseable",
        "static final PartitionIndexSerializer TRIE_SERIALIZER = new PartitionIndexSerializer();",
        "public static PartitionIndex load(FileHandle fh, IPartitioner partitioner, boolean preload) throws IOException",
        "public long exactCandidate(DecoratedKey key)",
        "public <ResultType> ResultType ceiling(PartitionPosition key, Acceptor<PartitionPosition, ResultType> acceptor) throws IOException",
    ),
    TRIE_INDEX_ENTRY: (
        "final class TrieIndexEntry extends AbstractRowIndexEntry",
        "public TrieIndexEntry(long position)",
        "public static TrieIndexEntry create(long dataStartPosition,",
        "public static TrieIndexEntry deserialize(DataInputPlus in, long basePosition, Version version) throws IOException",
    ),
}

TEST_TOKEN_CHECKS = {
    SSTABLE_FORMAT_TEST: (
        "public class SSTableFormatTest",
        "selected_format = \"aaa\";",
        "assertThat(format.name).isEqualTo(name);",
        "Multiple sstable format implementations with the same name",
        "Configuration contains options of unknown sstable formats",
        "Selected sstable format",
    ),
    STORAGE_COMPATIBILITY_MODE_TEST: (
        "public class StorageCompatibilityModeTest",
        "public void testBtiFormatAndStorageCompatibilityMode()",
        "mode.validateSstableFormat(big);",
        "mode.validateSstableFormat(trie);",
        "case CASSANDRA_4:",
        "Assertions.assertThatThrownBy(() -> mode.validateSstableFormat(trie))",
    ),
    SSTABLE_READER_TEST: (
        "public class SSTableReaderTest",
        "public void testGetPositionsKeyCacheStats()",
        "public void testGetPositionsBloomFilterStats()",
        "SSTableReaderWithFilter sstable = prepareGetPositions();",
        "Mockito.verify(listener).onSSTableSkipped(sstable, SSTableReadsListener.SkippingReason.BLOOM_FILTER);",
        "Mockito.verify(listener).onSSTableSkipped(sstable, SSTableReadsListener.SkippingReason.PARTITION_INDEX_LOOKUP);",
        "checkOpenedBigTable(ks, cf, store, desc);",
        "checkOpenedBtiTable(ks, cf, store, desc);",
        "Summary was not recreated",
        "check that bloomfilter is not recreated when the INDEX is missing",
    ),
    SSTABLE_WRITER_TEST: (
        "public class SSTableWriterTest extends SSTableWriterTestBase",
        "writer.append(builder.build().unfilteredIterator());",
        "SSTableReader sstable = writer.finish(true);",
        "private static void assertValidRepairMetadata(long repairedAt, TimeUUID pendingRepair, boolean isTransient)",
        "private static void assertInvalidRepairMetadata(long repairedAt, TimeUUID pendingRepair, boolean isTransient)",
    ),
    SSTABLE_WRITER_TRANSACTION_TEST: (
        "public class SSTableWriterTransactionTest extends AbstractTransactionalTest",
        "writer.append(update.build().unfilteredIterator());",
        "assertNotExists(descriptor.version.format.generatedOnLoadComponents());",
        "assertExists(descriptor.version.format.generatedOnLoadComponents());",
    ),
    METADATA_SERIALIZER_TEST: (
        "public class MetadataSerializerTest",
        "StatsMetadata originalStats = (StatsMetadata) originalMetadata.get(MetadataType.STATS);",
        "StatsMetadata deserializedStats = (StatsMetadata) deserialized.get(MetadataType.STATS);",
    ),
    CQL_SSTABLE_WRITER_TEST: (
        "public abstract class CQLSSTableWriterTest",
        "BigFormat format = BigFormat.getInstance();",
        "SSTableFormat<?, ?> btiFormat = new BtiFormat.BtiFormatFactory().getInstance(Collections.emptyMap());",
        "private void testWritingSstableWithFormat(SSTableFormat<?, ?> format) throws Exception",
        ".withFormat(format)",
        "assertEquals(format, descriptor.version.format);",
    ),
    BTI_LOADING_TEST: (
        "public class LoadingBuilderTest extends CQLTester",
        "public static Map<String, Boolean> preloadsMap = new ConcurrentHashMap<>();",
        "Assume.assumeTrue(BtiFormat.isSelected());",
        "WITH bloom_filter_fp_chance = ",
        "verifyPreloadMatches(disableBloomFilter, partitionIndexFile);",
        "assertEquals(disableBloomFilter, preload.booleanValue());",
    ),
    VERIFY_TEST: (
        "public class VerifyTest",
        "verifier.verify();",
        "if (BigFormat.isSelected())",
        "testBrokenComponentHelper(BigFormat.Components.PRIMARY_INDEX);",
        "else if (BtiFormat.isSelected())",
        "testBrokenComponentHelper(BtiFormat.Components.PARTITION_INDEX);",
    ),
    SCRUB_TEST: (
        "public class ScrubTest",
        "IScrubber scrubber = sstable.descriptor.getFormat().getScrubber(cfs, txn, new OutputHandler.LogOutput(), new IScrubber.Options.Builder().checkData().build())",
        "scrubResult = scrubber.scrubWithResult();",
        "if (BigFormat.is(reader.descriptor.getFormat()))",
        "reader.descriptor.fileFor(BigFormat.Components.PRIMARY_INDEX)",
        "if (BtiFormat.is(reader.descriptor.getFormat()))",
        "reader.descriptor.fileFor(BtiFormat.Components.PARTITION_INDEX)",
        "reader.descriptor.fileFor(BtiFormat.Components.ROW_INDEX)",
    ),
    LEGACY_SSTABLE_TEST: (
        "public class LegacySSTableTest",
        "public static String[] legacyVersions = null;",
        "loadLegacyTables(legacyVersion);",
        "verifyReads(legacyVersion);",
        "verifyCache(legacyVersion, startCount);",
        "streamLegacyTables(legacyVersion);",
        "compactLegacyTables(legacyVersion);",
        "SSTableFormat<?, ?> format = DatabaseDescriptor.getSelectedSSTableFormat();",
    ),
    SSTABLE_LOADER_LEGACY_TEST: (
        "public class SSTableLoaderLegacyTest",
        "Tests SSTableLoader with legacy sstables from Cassandra 3.x",
        "Zero-copy streaming is automatically disabled for legacy sstables that use the old bloom filter format.",
        "assertTrue(\"Zero-copy streaming should be enabled by default\",",
        "assertTrue(\"Data should be loaded from legacy sstable\",",
    ),
}

DOC_REQUIRED_TOKENS = (
    "research/tools/check-sstable-format-runtime-drift.py",
    "research/module-sstable-format-runtime-matrix.md",
    "research/module-sstable-format-runtime-drift-checker.md",
    "SSTableFormat",
    "Descriptor",
    "TOCComponent",
    "SSTableReaderLoadingBuilder",
    "SSTableWriter",
    "StatsMetadata",
    "MetadataSerializer",
    "BigFormat",
    "BtiFormat",
    "SSTableReaderWithFilter",
    "CQLSSTableWriterTest",
    "LegacySSTableTest",
    "SSTableLoaderLegacyTest",
    "storage_compatibility_mode",
    "sstable.selected_format",
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
    parser = argparse.ArgumentParser(description="Check SSTable format/runtime research drift")
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
            f"OK SSTable format/runtime drift checks passed "
            f"({source_count} source checks, {test_count} test checks, {doc_count} doc checks, "
            f"{len(SCENARIO_IDS)} scenarios)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
