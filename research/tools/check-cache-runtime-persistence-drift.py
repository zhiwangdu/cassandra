#!/usr/bin/env python3
"""Validate cache runtime/persistence research against source tokens."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]

CACHE_SERVICE = "src/java/org/apache/cassandra/service/CacheService.java"
CACHE_SERVICE_MBEAN = "src/java/org/apache/cassandra/service/CacheServiceMBean.java"
AUTO_SAVING_CACHE = "src/java/org/apache/cassandra/cache/AutoSavingCache.java"
INSTRUMENTING_CACHE = "src/java/org/apache/cassandra/cache/InstrumentingCache.java"
KEY_CACHE_KEY = "src/java/org/apache/cassandra/cache/KeyCacheKey.java"
ROW_CACHE_KEY = "src/java/org/apache/cassandra/cache/RowCacheKey.java"
COUNTER_CACHE_KEY = "src/java/org/apache/cassandra/cache/CounterCacheKey.java"
CHUNK_CACHE = "src/java/org/apache/cassandra/cache/ChunkCache.java"
NOP_CACHE_PROVIDER = "src/java/org/apache/cassandra/cache/NopCacheProvider.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
CFS = "src/java/org/apache/cassandra/db/ColumnFamilyStore.java"
SINGLE_PARTITION_READ_COMMAND = "src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java"
COUNTER_MUTATION = "src/java/org/apache/cassandra/db/CounterMutation.java"
CACHE_METRICS = "src/java/org/apache/cassandra/metrics/CacheMetrics.java"
CHUNK_CACHE_METRICS = "src/java/org/apache/cassandra/metrics/ChunkCacheMetrics.java"
CACHES_TABLE = "src/java/org/apache/cassandra/db/virtual/CachesTable.java"
NODE_TOOL = "src/java/org/apache/cassandra/tools/NodeTool.java"
NODE_PROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
NODETOOL_INFO = "src/java/org/apache/cassandra/tools/nodetool/Info.java"
NODETOOL_SET_CAPACITY = "src/java/org/apache/cassandra/tools/nodetool/SetCacheCapacity.java"
NODETOOL_SET_KEYS = "src/java/org/apache/cassandra/tools/nodetool/SetCacheKeysToSave.java"
NODETOOL_INVALIDATE_KEY = "src/java/org/apache/cassandra/tools/nodetool/InvalidateKeyCache.java"
NODETOOL_INVALIDATE_ROW = "src/java/org/apache/cassandra/tools/nodetool/InvalidateRowCache.java"
NODETOOL_INVALIDATE_COUNTER = "src/java/org/apache/cassandra/tools/nodetool/InvalidateCounterCache.java"
YAML = "conf/cassandra.yaml"

AUTO_SAVING_CACHE_TEST = "test/unit/org/apache/cassandra/cache/AutoSavingCacheTest.java"
KEY_CACHE_TEST = "test/unit/org/apache/cassandra/io/sstable/keycache/KeyCacheTest.java"
COUNTER_CACHE_TEST = "test/unit/org/apache/cassandra/db/CounterCacheTest.java"
ROW_CACHE_TEST = "test/unit/org/apache/cassandra/db/RowCacheTest.java"
ROW_CACHE_CQL_TEST = "test/unit/org/apache/cassandra/db/RowCacheCQLTest.java"
CACHE_METRICS_TEST = "test/unit/org/apache/cassandra/metrics/CacheMetricsTest.java"
NODETOOL_TEST = "test/distributed/org/apache/cassandra/distributed/test/NodeToolTest.java"

SCENARIO_IDS = (
    "cache_service_mbean_init_contract",
    "cache_config_autosize_directory_contract",
    "cache_autosaving_persistence_contract",
    "cache_save_load_serializer_contract",
    "cache_runtime_capacity_keys_contract",
    "cache_global_table_invalidation_contract",
    "key_cache_entry_identity_contract",
    "row_cache_read_write_invalidation_contract",
    "counter_cache_read_before_write_contract",
    "chunk_cache_file_cache_contract",
    "cache_metrics_virtual_table_contract",
    "cache_nodetool_jmx_surface_contract",
    "cache_existing_tests_baseline",
    "cache_runtime_operator_gap",
)

TARGET_DOCS = (
    "research/module-cache-runtime-persistence-matrix.md",
    "research/module-cache-runtime-persistence-drift-checker.md",
    "research/module-cache-index-view.md",
    "research/module-cache-index-view-deep-dive.md",
    "research/module-cache-index-view-coverage-drift-checker.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SOURCE_TOKEN_CHECKS = {
    CACHE_SERVICE: (
        "public class CacheService implements CacheServiceMBean",
        "public static final String MBEAN_NAME = \"org.apache.cassandra.db:type=Caches\";",
        "KEY_CACHE(\"KeyCache\")",
        "ROW_CACHE(\"RowCache\")",
        "COUNTER_CACHE(\"CounterCache\");",
        "MBeanWrapper.instance.registerMBean(this, MBEAN_NAME);",
        "keyCache = initKeyCache();",
        "rowCache = initRowCache();",
        "counterCache = initCounterCache();",
        "private AutoSavingCache<KeyCacheKey, AbstractRowIndexEntry> initKeyCache()",
        "CaffeineCache.create(keyCacheInMemoryCapacity);",
        "new AutoSavingCache<>(kc, CacheType.KEY_CACHE, new KeyCacheSerializer())",
        "keyCache.scheduleSaving(DatabaseDescriptor.getKeyCacheSavePeriod(), keyCacheKeysToSave);",
        "? DatabaseDescriptor.getRowCacheClassName() : \"org.apache.cassandra.cache.NopCacheProvider\";",
        "new AutoSavingCache<>(rc, CacheType.ROW_CACHE, new RowCacheSerializer())",
        "rowCache.scheduleSaving(DatabaseDescriptor.getRowCacheSavePeriod(), rowCacheKeysToSave);",
        "new AutoSavingCache<>(CaffeineCache.create(capacity),",
        "CacheType.COUNTER_CACHE,",
        "new CounterCacheSerializer());",
        "cache.scheduleSaving(DatabaseDescriptor.getCounterCacheSavePeriod(), keysToSave);",
        "public void setKeyCacheSavePeriodInSeconds(int seconds)",
        "public void setRowCacheKeysToSave(int count)",
        "public void setCounterCacheKeysToSave(int count)",
        "public void invalidateKeyCache()",
        "keyCache.clear();",
        "public void invalidateKeyCacheForCf(TableMetadata tableMetadata)",
        "if (key.sameTable(tableMetadata))",
        "public void invalidateRowCache()",
        "rowCache.clear();",
        "public void invalidateCounterCache()",
        "counterCache.clear();",
        "public void setRowCacheCapacityInMB(long capacity)",
        "rowCache.setCapacity(capacity * 1024 * 1024);",
        "public void setKeyCacheCapacityInMB(long capacity)",
        "keyCache.setCapacity(capacity * 1024 * 1024);",
        "public void setCounterCacheCapacityInMB(long capacity)",
        "counterCache.setCapacity(capacity * 1024 * 1024);",
        "public void saveCaches() throws ExecutionException, InterruptedException",
        "futures.add(keyCache.submitWrite(DatabaseDescriptor.getKeyCacheKeysToSave()));",
        "futures.add(rowCache.submitWrite(DatabaseDescriptor.getRowCacheKeysToSave()));",
        "futures.add(counterCache.submitWrite(DatabaseDescriptor.getCounterCacheKeysToSave()));",
        "public static class CounterCacheSerializer extends CacheSerializer<CounterCacheKey, ClockAndCount>",
        "public static class RowCacheSerializer extends CacheSerializer<RowCacheKey, IRowCacheEntry>",
        "public static class KeyCacheSerializer extends CacheSerializer<KeyCacheKey, AbstractRowIndexEntry>",
        "assert(!cfs.isIndex());//Shouldn't have row cache entries for indexes",
        "SinglePartitionReadCommand.fullPartitionRead(cfs.metadata(), nowInSec, key);",
        "out.writeUTF(desc.version.format.name());",
        "SSTableIdFactory.instance.fromBytes(ByteBufferUtil.readWithShortLength(in));",
        "boolean skipEntry = reader.left == null || !reader.left.getKeyCache().isEnabled();",
        "if (keyLength > FBUtilities.MAX_UNSIGNED_SHORT)",
        "entry.serializeForCache(out);",
    ),
    CACHE_SERVICE_MBEAN: (
        "public int getRowCacheSavePeriodInSeconds();",
        "public void setRowCacheSavePeriodInSeconds(int rcspis);",
        "public int getKeyCacheKeysToSave();",
        "public void setCounterCacheKeysToSave(int cckts);",
        "public void invalidateKeyCache();",
        "public void invalidateRowCache();",
        "public void invalidateCounterCache();",
        "public void setRowCacheCapacityInMB(long capacity);",
        "public void setKeyCacheCapacityInMB(long capacity);",
        "public void setCounterCacheCapacityInMB(long capacity);",
        "public void saveCaches() throws ExecutionException, InterruptedException;",
    ),
    AUTO_SAVING_CACHE: (
        "public class AutoSavingCache<K extends CacheKey, V> extends InstrumentingCache<K, V>",
        "public static final Set<CacheService.CacheType> flushInProgress = new NonBlockingHashSet<CacheService.CacheType>();",
        "private static final String CURRENT_VERSION = \"g\";",
        "public File getCacheDataPath(String version)",
        "public File getCacheCrcPath(String version)",
        "public File getCacheMetadataPath(String version)",
        "public void scheduleSaving(int savePeriodInSeconds, final int keysToSave)",
        "saveTask.cancel(false); // Do not interrupt an in-progress save",
        "submitWrite(keysToSave);",
        "ScheduledExecutors.optionalTasks.scheduleWithFixedDelay(runnable,",
        "public Future<Integer> loadSavedAsync()",
        "final ExecutorPlus es = executorFactory().sequential(\"loadSavedCache\");",
        "public int loadSaved()",
        "File dataPath = getCacheDataPath(CURRENT_VERSION);",
        "File crcPath = getCacheCrcPath(CURRENT_VERSION);",
        "File metadataPath = getCacheMetadataPath(CURRENT_VERSION);",
        "if (dataPath.exists() && crcPath.exists() && metadataPath.exists())",
        "cacheLoader.deserializeMetadata(metadataIn);",
        "UUID schemaVersion = new UUID(in.readLong(), in.readLong());",
        "if (!schemaVersion.equals(Schema.instance.getVersion()))",
        "long loadByNanos = start + TimeUnit.SECONDS.toNanos(DatabaseDescriptor.getCacheLoadTimeout());",
        "Future<Pair<K, V>> entryFuture = cacheLoader.deserialize(in);",
        "if (entry != null && entry.right != null)",
        "put(entry.left, entry.right);",
        "public Future<?> submitWrite(int keysToSave)",
        "return CompactionManager.instance.submitCacheWrite(getWriter(keysToSave));",
        "public class Writer extends CompactionInfo.Holder",
        "if (keysToSave >= size || keysToSave == 0)",
        "keyIterator = hotKeyIterator(keysToSave);",
        "type = OperationType.KEY_CACHE_SAVE;",
        "type = OperationType.ROW_CACHE_SAVE;",
        "type = OperationType.COUNTER_CACHE_SAVE;",
        "public void saveCache()",
        "deleteOldCacheFiles();",
        "File dataTmpFile = getTempCacheFile(getCacheDataPath(CURRENT_VERSION));",
        "UUID schemaVersion = Schema.instance.getVersion();",
        "cacheLoader.serialize(key, writer, cfs);",
        "cacheLoader.serializeMetadata(metadataWriter);",
        "metadataWriter.sync();",
        "dataTmpFile.tryMove(dataFile)",
        "crcTmpFile.tryMove(crcFile)",
        "metadataTmpFile.tryMove(metadataFile)",
        "public static abstract class CacheSerializer<K extends CacheKey, V>",
        "protected final int getOrCreateCFSOrdinal(ColumnFamilyStore cfs)",
        "protected ColumnFamilyStore readCFS(DataInputPlus in) throws IOException",
        "protected void writeCFS(DataOutputPlus out, ColumnFamilyStore cfs) throws IOException",
        "public void serializeMetadata(DataOutputPlus out) throws IOException",
        "public void deserializeMetadata(DataInputPlus in) throws IOException",
    ),
    INSTRUMENTING_CACHE: (
        "public class InstrumentingCache<K, V>",
        "this.metrics = new CacheMetrics(type, map);",
        "public V get(K key)",
        "metrics.requests.mark();",
        "metrics.hits.mark();",
        "metrics.misses.mark();",
        "public V getInternal(K key)",
        "public void clear()",
        "map.clear();",
        "metrics = new CacheMetrics(type, map);",
        "public CacheMetrics getMetrics()",
    ),
    KEY_CACHE_KEY: (
        "public class KeyCacheKey extends CacheKey",
        "public final Descriptor desc;",
        "public final byte[] key;",
        "public KeyCacheKey(TableMetadata tableMetadata, Descriptor desc, ByteBuffer key)",
        "return tableId.equals(that.tableId)",
        "&& desc.equals(that.desc)",
        "&& Arrays.equals(key, that.key);",
        "public long unsharedHeapSize()",
    ),
    ROW_CACHE_KEY: (
        "public final class RowCacheKey extends CacheKey",
        "public final byte[] key;",
        "public RowCacheKey(TableMetadata metadata, DecoratedKey key)",
        "this.key = ByteBufferUtil.getArray(key.getKey());",
        "return tableId.equals(that.tableId)",
        "&& Arrays.equals(key, that.key);",
    ),
    COUNTER_CACHE_KEY: (
        "public final class CounterCacheKey extends CacheKey",
        "private final byte[] partitionKey;",
        "private final byte[] cellName;",
        "public static CounterCacheKey create(TableMetadata tableMetadata, ByteBuffer partitionKey, Clustering<?> clustering, ColumnMetadata c, CellPath path)",
        "private static ByteBuffer makeCellName(Clustering<?> clustering, ColumnMetadata c, CellPath path)",
        "public ByteBuffer readCounterValue(ColumnFamilyStore cfs)",
        "SinglePartitionReadCommand.create(metadata, nowInSec, key, builder.build(), filter);",
        "public void write(DataOutputPlus out)",
        "ByteArrayUtil.writeWithLength(partitionKey, out);",
        "public static CounterCacheKey read(TableMetadata tableMetadata, DataInputPlus in)",
        "ByteBufferUtil.readBytesWithLength(in)",
    ),
    CHUNK_CACHE: (
        "public class ChunkCache",
        "public static final int RESERVED_POOL_SPACE_IN_MiB = 32;",
        "public static final long cacheSize = 1024L * 1024L * Math.max(0, DatabaseDescriptor.getFileCacheSizeInMiB() - RESERVED_POOL_SPACE_IN_MiB);",
        "private static boolean enabled = DatabaseDescriptor.getFileCacheEnabled() && cacheSize > 0;",
        "public static final ChunkCache instance = enabled ? new ChunkCache(BufferPools.forChunkCache()) : null;",
        "public final ChunkCacheMetrics metrics;",
        ".maximumWeight(cacheSize)",
        ".recordStats(() -> metrics)",
        "public Buffer load(Key key)",
        "key.file.readChunk(key.position, buffer);",
        "public static RebuffererFactory maybeWrap(ChunkReader file)",
        "public void invalidatePosition(FileHandle dfile, long position)",
        "public void invalidateFile(String fileName)",
    ),
    NOP_CACHE_PROVIDER: (
        "public class NopCacheProvider implements CacheProvider<RowCacheKey, IRowCacheEntry>",
        "private static class NopCache implements ICache<RowCacheKey, IRowCacheEntry>",
        "public void setCapacity(long capacity)",
        "if (capacity != 0)",
        "is not permitted as this cache is disabled. Check your yaml settings if you want to enable it.",
    ),
    CONFIG: (
        "public String saved_caches_directory;",
        "public volatile boolean key_cache_migrate_during_compaction = true;",
        "public volatile boolean key_cache_invalidate_after_sstable_deletion = false;",
        "public volatile int key_cache_keys_to_save = Integer.MAX_VALUE;",
        "public DataStorageSpec.LongMebibytesBound key_cache_size = null;",
        "public volatile DurationSpec.IntSecondsBound key_cache_save_period = new DurationSpec.IntSecondsBound(\"4h\");",
        "public String row_cache_class_name = \"org.apache.cassandra.cache.OHCProvider\";",
        "public DataStorageSpec.LongMebibytesBound row_cache_size = new DataStorageSpec.LongMebibytesBound(\"0MiB\");",
        "public volatile DurationSpec.IntSecondsBound row_cache_save_period = new DurationSpec.IntSecondsBound(\"0s\");",
        "public volatile int row_cache_keys_to_save = Integer.MAX_VALUE;",
        "public DataStorageSpec.LongMebibytesBound counter_cache_size = null;",
        "public volatile DurationSpec.IntSecondsBound counter_cache_save_period = new DurationSpec.IntSecondsBound(\"7200s\");",
        "public volatile int counter_cache_keys_to_save = Integer.MAX_VALUE;",
        "public DurationSpec.IntSecondsBound cache_load_timeout = new DurationSpec.IntSecondsBound(\"30s\");",
        "public DataStorageSpec.IntMebibytesBound file_cache_size;",
        "public boolean file_cache_enabled = FILE_CACHE_ENABLED.getBoolean();",
        "public Boolean file_cache_round_up;",
    ),
    DATABASE_DESCRIPTOR: (
        "conf.saved_caches_directory = storagedirFor(\"saved_caches\");",
        "throw new ConfigurationException(\"saved_caches_directory must not be the same as any data_file_directories\", false);",
        "throw new ConfigurationException(\"saved_caches_directory must not be the same as the commitlog_directory\", false);",
        "throw new ConfigurationException(\"saved_caches_directory must not be the same as the hints_directory\", false);",
        "keyCacheSizeInMiB = (conf.key_cache_size == null)",
        "Math.min(Math.max(1, (int) (Runtime.getRuntime().totalMemory() * 0.05 / 1024 / 1024)), 100)",
        "counterCacheSizeInMiB = (conf.counter_cache_size == null)",
        "Math.min(Math.max(1, (int) (Runtime.getRuntime().totalMemory() * 0.025 / 1024 / 1024)), 50)",
        "public static boolean getFileCacheEnabled()",
        "return conf.file_cache_enabled;",
        "public static int getFileCacheSizeInMiB()",
        "return conf.file_cache_size.toMebibytes();",
        "public static boolean getFileCacheRoundUp()",
        "return conf.file_cache_round_up;",
        "public static int getKeyCacheSavePeriod()",
        "return conf.key_cache_save_period.toSeconds();",
        "public static void setKeyCacheKeysToSave(int keyCacheKeysToSave)",
        "public static String getRowCacheClassName()",
        "public static long getRowCacheSizeInMiB()",
        "public static void setRowCacheKeysToSave(int rowCacheKeysToSave)",
        "public static int getCounterCacheSavePeriod()",
        "public static int getCacheLoadTimeout()",
        "public static void setCounterCacheKeysToSave(int counterCacheKeysToSave)",
    ),
    CFS: (
        "Memtable mt = data.getMemtableFor(opGroup, commitLogPosition);",
        "invalidateCachedPartition(key);",
        "public void cleanupCache()",
        "for (Iterator<RowCacheKey> keyIter = CacheService.instance.rowCache.keyIterator();",
        "if (key.sameTable(metadata()) && !Range.isInRanges(dk.getToken(), ranges))",
        "for (Iterator<CounterCacheKey> keyIter = CacheService.instance.counterCache.keyIterator();",
        "CacheService.instance.counterCache.remove(key);",
        "public CachedPartition getRawCachedPartition(DecoratedKey key)",
        "CacheService.instance.rowCache.getInternal(new RowCacheKey(metadata(), key));",
        "private void invalidateCaches()",
        "CacheService.instance.invalidateKeyCacheForCf(metadata());",
        "CacheService.instance.invalidateRowCacheForCf(metadata());",
        "CacheService.instance.invalidateCounterCacheForCf(metadata());",
        "public int invalidateRowCache(Collection<Bounds<Token>> boundsToInvalidate)",
        "public int invalidateCounterCache(Collection<Bounds<Token>> boundsToInvalidate)",
        "public boolean containsCachedParition(DecoratedKey key)",
        "public void invalidateCachedPartition(RowCacheKey key)",
        "public ClockAndCount getCachedCounter(ByteBuffer partitionKey, Clustering<?> clustering, ColumnMetadata column, CellPath path)",
        "return CacheService.instance.counterCache.get(CounterCacheKey.create(metadata(), partitionKey, clustering, column, path));",
        "public void putCachedCounter(ByteBuffer partitionKey, Clustering<?> clustering, ColumnMetadata column, CellPath path, ClockAndCount clockAndCount)",
        "CacheService.instance.counterCache.put(CounterCacheKey.create(metadata(), partitionKey, clustering, column, path), clockAndCount);",
        "public boolean isRowCacheEnabled()",
        "metadata().params.caching.cacheRows() && CacheService.instance.rowCache.getCapacity() > 0",
        "public boolean isCounterCacheEnabled()",
        "public boolean isKeyCacheEnabled()",
    ),
    SINGLE_PARTITION_READ_COMMAND: (
        "protected UnfilteredPartitionIterator queryStorage(final ColumnFamilyStore cfs, ReadExecutionController executionController)",
        "cfs.isRowCacheEnabled() && !executionController.isTrackingRepairedStatus()",
        "private UnfilteredRowIterator getThroughCache(ColumnFamilyStore cfs, ReadExecutionController executionController)",
        "RowCacheKey key = new RowCacheKey(metadata(), partitionKey());",
        "IRowCacheEntry cached = CacheService.instance.rowCache.get(key);",
        "if (cached instanceof RowCacheSentinel)",
        "cfs.metric.rowCacheMiss.inc();",
        "cfs.metric.rowCacheHit.inc();",
        "cfs.metric.rowCacheHitOutOfRange.inc();",
        "boolean cacheFullPartitions = metadata().clusteringColumns().size() > 0 ?",
        "RowCacheSentinel sentinel = new RowCacheSentinel();",
        "boolean sentinelSuccess = CacheService.instance.rowCache.putIfAbsent(key, sentinel);",
        "CachedPartition toCache = CachedBTreePartition.create(toCacheIterator, nowInSec());",
        "CacheService.instance.rowCache.replace(key, sentinel, toCache);",
        "cfs.invalidateCachedPartition(key);",
    ),
    COUNTER_MUTATION: (
        "private PartitionUpdate processModifications(PartitionUpdate changes)",
        "if (CacheService.instance.counterCache.getCapacity() != 0)",
        "updateWithCurrentValuesFromCache(marks, cfs);",
        "updateWithCurrentValuesFromCFS(marks, cfs);",
        "cfs.putCachedCounter(key().getKey(), mark.clustering(), mark.column(), mark.path(), ClockAndCount.create(clock, count));",
        "private void updateWithCurrentValuesFromCache(List<PartitionUpdate.CounterMark> marks, ColumnFamilyStore cfs)",
        "ClockAndCount cached = cfs.getCachedCounter(key().getKey(), mark.clustering(), mark.column(), mark.path());",
    ),
    CACHE_METRICS: (
        "public class CacheMetrics",
        "public final Gauge<Long> capacity;",
        "public final Gauge<Long> size;",
        "public final Gauge<Integer> entries;",
        "public final Meter hits;",
        "public final Meter misses;",
        "public final Meter requests;",
        "factory = new DefaultNameFactory(\"Cache\", type);",
        "factory.createMetricName(\"Capacity\")",
        "factory.createMetricName(\"HitRate\")",
        "Metrics.meter(factory.createMetricName(\"Requests\"));",
        "public void reset()",
        "private static RatioGauge ratioGauge(DoubleSupplier numeratorSupplier, DoubleSupplier denominatorSupplier)",
    ),
    CHUNK_CACHE_METRICS: (
        "public class ChunkCacheMetrics extends CacheMetrics implements StatsCounter",
        "public final Timer missLatency;",
        "super(\"ChunkCache\", cache);",
        "factory.createMetricName(\"MissLatency\")",
        "public void recordHits(int count)",
        "public void recordMisses(int count)",
        "public void recordLoadSuccess(long loadTime)",
    ),
    CACHES_TABLE: (
        "final class CachesTable extends AbstractVirtualTable",
        ".comment(\"system caches\")",
        ".addPartitionKeyColumn(NAME, UTF8Type.instance)",
        ".addRegularColumn(CAPACITY_BYTES, LongType.instance)",
        ".addRegularColumn(REQUEST_COUNT, LongType.instance)",
        "private void addRow(SimpleDataSet result, String name, CacheMetrics metrics)",
        "result.row(name)",
        "if (null != ChunkCache.instance)",
        "addRow(result, \"chunks\", ChunkCache.instance.metrics);",
        "addRow(result, \"counters\", CacheService.instance.counterCache.getMetrics());",
        "addRow(result, \"keys\", CacheService.instance.keyCache.getMetrics());",
        "addRow(result, \"rows\", CacheService.instance.rowCache.getMetrics());",
    ),
    NODE_TOOL: (
        "InvalidateCounterCache.class,",
        "InvalidateKeyCache.class,",
        "InvalidateRowCache.class,",
        "SetCacheCapacity.class,",
        "SetCacheKeysToSave.class,",
    ),
    NODE_PROBE: (
        "name = new ObjectName(CacheService.MBEAN_NAME);",
        "cacheService = JMX.newMBeanProxy(mbeanServerConn, name, CacheServiceMBean.class);",
        "public void invalidateCounterCache()",
        "cacheService.invalidateCounterCache();",
        "public void invalidateKeyCache()",
        "cacheService.invalidateKeyCache();",
        "public void invalidateRowCache()",
        "cacheService.invalidateRowCache();",
        "public CacheServiceMBean getCacheServiceMBean()",
        "String cachePath = \"org.apache.cassandra.db:type=Caches\";",
        "public void setCacheCapacities(int keyCacheCapacity, int rowCacheCapacity, int counterCacheCapacity)",
        "cacheMBean.setKeyCacheCapacityInMB(keyCacheCapacity);",
        "cacheMBean.setRowCacheCapacityInMB(rowCacheCapacity);",
        "cacheMBean.setCounterCacheCapacityInMB(counterCacheCapacity);",
        "public void setCacheKeysToSave(int keyCacheKeysToSave, int rowCacheKeysToSave, int counterCacheKeysToSave)",
        "cacheMBean.setKeyCacheKeysToSave(keyCacheKeysToSave);",
        "cacheMBean.setRowCacheKeysToSave(rowCacheKeysToSave);",
        "cacheMBean.setCounterCacheKeysToSave(counterCacheKeysToSave);",
        "public Object getCacheMetric(String cacheType, String metricName)",
    ),
    NODETOOL_INFO: (
        "CacheServiceMBean cacheService = probe.getCacheServiceMBean();",
        "probe.getCacheMetric(\"KeyCache\", \"Entries\")",
        "cacheService.getKeyCacheSavePeriodInSeconds()",
        "probe.getCacheMetric(\"RowCache\", \"Entries\")",
        "cacheService.getRowCacheSavePeriodInSeconds()",
        "probe.getCacheMetric(\"CounterCache\", \"Entries\")",
        "cacheService.getCounterCacheSavePeriodInSeconds()",
        "probe.getCacheMetric(\"ChunkCache\", \"Entries\")",
        "probe.getCacheMetric(\"ChunkCache\", \"MissLatency\")",
    ),
    NODETOOL_SET_CAPACITY: (
        "@Command(name = \"setcachecapacity\", description = \"Set global key, row, and counter cache capacities (in MB units)\")",
        "@Arguments(title = \"<key-cache-capacity> <row-cache-capacity> <counter-cache-capacity>\",",
        "checkArgument(args.size() == 3, \"setcachecapacity requires key-cache-capacity, row-cache-capacity, and counter-cache-capacity args.\");",
        "probe.setCacheCapacities(args.get(0), args.get(1), args.get(2));",
    ),
    NODETOOL_SET_KEYS: (
        "@Command(name = \"setcachekeystosave\", description = \"Set number of keys saved by each cache for faster post-restart warmup. 0 to disable\")",
        "@Arguments(title = \"<key-cache-keys-to-save> <row-cache-keys-to-save> <counter-cache-keys-to-save>\",",
        "checkArgument(args.size() == 3, \"setcachekeystosave requires key-cache-keys-to-save, row-cache-keys-to-save, and counter-cache-keys-to-save args.\");",
        "probe.setCacheKeysToSave(args.get(0), args.get(1), args.get(2));",
    ),
    NODETOOL_INVALIDATE_KEY: (
        "@Command(name = \"invalidatekeycache\", description = \"Invalidate the key cache\")",
        "probe.invalidateKeyCache();",
    ),
    NODETOOL_INVALIDATE_ROW: (
        "@Command(name = \"invalidaterowcache\", description = \"Invalidate the row cache\")",
        "probe.invalidateRowCache();",
    ),
    NODETOOL_INVALIDATE_COUNTER: (
        "@Command(name = \"invalidatecountercache\", description = \"Invalidate the counter cache\")",
        "probe.invalidateCounterCache();",
    ),
    YAML: (
        "key_cache_size:",
        "key_cache_save_period: 4h",
        "# key_cache_keys_to_save: 100",
        "# row_cache_class_name: org.apache.cassandra.cache.OHCProvider",
        "row_cache_size: 0MiB",
        "row_cache_save_period: 0s",
        "# row_cache_keys_to_save: 100",
        "counter_cache_size:",
        "counter_cache_save_period: 7200s",
        "# counter_cache_keys_to_save: 100",
        "# saved_caches_directory: /var/lib/cassandra/saved_caches",
        "# cache_load_timeout: 30s",
        "# file_cache_enabled: false",
        "# file_cache_size: 512MiB",
    ),
}

TEST_TOKEN_CHECKS = {
    AUTO_SAVING_CACHE_TEST: (
        "public class AutoSavingCacheTest",
        "testSerializeAndLoadKeyCache0kB",
        "testSerializeAndLoadKeyCache",
        "AutoSavingCache<KeyCacheKey, AbstractRowIndexEntry> keyCache = CacheService.instance.keyCache;",
        "keyCache.submitWrite(keyCache.size()).get();",
        "keyCache.clear();",
        "keyCache.loadSavedAsync().get();",
        "Assert.assertNotNull(keyCache.get(new KeyCacheKey(cfs.metadata(), sstable.descriptor, ByteBufferUtil.bytes(\"key1\"))));",
    ),
    KEY_CACHE_TEST: (
        "public class KeyCacheTest",
        "testKeyCacheLoadShallowIndexEntry",
        "testKeyCacheLoadIndexInfoOnHeap",
        "CacheService.instance.invalidateKeyCache();",
        "CacheService.instance.keyCache.submitWrite(Integer.MAX_VALUE).get();",
        "CacheService.instance.keyCache.loadSaved();",
        "assertEquals(expected.position, actual.position);",
        "assertEquals(expected.blockCount(), actual.blockCount());",
        "assertEquals(expected.getSSTableFormat(), actual.getSSTableFormat());",
        "testKeyCacheLoadZeroCacheLoadTime",
        "testKeyCacheLoadCacheLoadTimeExceedingLimit",
    ),
    COUNTER_CACHE_TEST: (
        "public class CounterCacheTest",
        "testReadWrite",
        "testCounterCacheInvalidate",
        "testSaveLoad",
        "CacheService.instance.invalidateCounterCache();",
        "cfs.putCachedCounter(bytes(1), c1, cd, null, ClockAndCount.create(1L, 1L));",
        "assertEquals(ClockAndCount.create(1L, 1L), cfs.getCachedCounter(bytes(1), c1, cd, null));",
        "cfs.invalidateCounterCache(Collections.singleton(new Bounds<Token>(cfs.decorateKey(bytes(1)).getToken(),",
        "CacheService.instance.counterCache.submitWrite(Integer.MAX_VALUE).get();",
        "CacheService.instance.counterCache.loadSaved();",
        "CacheService.instance.setCounterCacheCapacityInMB(0);",
    ),
    ROW_CACHE_TEST: (
        "testRowCacheDisabled",
        "CacheService.instance.rowCache.submitWrite(Integer.MAX_VALUE).get();",
        "CacheService.instance.setRowCacheCapacityInMB(0);",
        "CacheService.instance.rowCache.loadSaved();",
        "testRowCacheRange",
        "long startRowCacheHits = cachedStore.metric.rowCacheHit.getCount();",
        "long startRowCacheOutOfRange = cachedStore.metric.rowCacheHitOutOfRange.getCount();",
        "CacheService.instance.invalidateRowCache();",
        "CacheService.instance.setRowCacheCapacityInMB(1);",
        "assertEquals(++startRowCacheHits, cachedStore.metric.rowCacheHit.getCount());",
        "assertEquals(++startRowCacheOutOfRange, cachedStore.metric.rowCacheHitOutOfRange.getCount());",
    ),
    ROW_CACHE_CQL_TEST: (
        "public class RowCacheCQLTest extends CQLTester",
        "test7636",
        "testPartialCache",
        "testPartialCacheWithStatic",
        "CacheService.instance.setRowCacheCapacityInMB(1);",
        "WITH CACHING = { 'keys': 'ALL', 'rows_per_partition': '1' }",
        "assertRows(execute(\"select * from %s where pk = 1 LIMIT 1\"),",
    ),
    CACHE_METRICS_TEST: (
        "public class CacheMetricsTest",
        "public void testCacheMetrics()",
        "InstrumentingCache<String,Object> cache = new InstrumentingCache<>(\"cache\", mockedCache);",
        "CacheMetrics metrics = cache.getMetrics();",
        "getFromCache(cache, \"k1\", 10);",
        "assertCacheMetrics(metrics, expect(mockedCache).hits(10).misses(0));",
        "cache.clear();",
        "metrics.reset();",
    ),
    NODETOOL_TEST: (
        "public void testSetCacheCapacityWhenDisabled() throws Throwable",
        "withConfig(c->c.set(\"row_cache_size\", \"0MiB\"))",
        "nodetoolResult(\"setcachecapacity\", \"1\", \"1\", \"1\")",
        "stderrContains(\"is not permitted as this cache is disabled\")",
    ),
}

ABSENT_TEST_TOKENS = (
    "setcachekeystosave",
    "invalidatekeycache",
    "invalidaterowcache",
    "invalidatecountercache",
    "system_views.caches",
)

DOC_TOKEN_CHECKS = {
    "research/module-cache-runtime-persistence-matrix.md": (
        "Cache Runtime Persistence Matrix",
        "CacheService",
        "AutoSavingCache",
        "CacheServiceMBean",
        "KeyCacheSerializer",
        "RowCacheSerializer",
        "CounterCacheSerializer",
        "NopCacheProvider",
        "ChunkCache",
        "CachesTable",
        "NodeToolTest.testSetCacheCapacityWhenDisabled",
        "setcachekeystosave",
        "system_views.caches",
        "cache_runtime_operator_gap",
    ),
    "research/module-cache-runtime-persistence-drift-checker.md": (
        "Cache Runtime Persistence Drift Checker",
        "research/tools/check-cache-runtime-persistence-drift.py",
        "check_absent_test_tokens()",
        "cache_runtime_operator_gap",
        "setcachekeystosave",
        "system_views.caches",
    ),
    "research/README.md": (
        "module-cache-runtime-persistence-matrix.md",
        "module-cache-runtime-persistence-drift-checker.md",
        "research/tools/check-cache-runtime-persistence-drift.py",
        "CacheService MBean",
        "AutoSavingCache",
        "system_views.caches",
        "cache_runtime_operator_gap",
    ),
    "research/notes/source-map.md": (
        "Cache runtime/persistence drift",
        "module-cache-runtime-persistence-matrix.md",
        "module-cache-runtime-persistence-drift-checker.md",
        "check-cache-runtime-persistence-drift.py",
        "cache_service_mbean_init_contract",
        "cache_runtime_operator_gap",
    ),
}


@dataclass
class Failure:
    category: str
    path: str
    token: str


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def check_file_exists(paths: Iterable[str], failures: list[Failure], category: str) -> int:
    count = 0
    for path in paths:
        count += 1
        if not (ROOT / path).exists():
            failures.append(Failure(category, path, "<exists>"))
    return count


def check_tokens(checks: dict[str, tuple[str, ...]], failures: list[Failure], category: str) -> int:
    count = 0
    for path, tokens in checks.items():
        file_path = ROOT / path
        if not file_path.exists():
            failures.append(Failure(category, path, "<exists>"))
            count += 1
            continue
        text = file_path.read_text(encoding="utf-8")
        for token in tokens:
            count += 1
            if token not in text:
                failures.append(Failure(category, path, token))
    return count


def check_doc_tokens(failures: list[Failure]) -> int:
    count = check_file_exists(TARGET_DOCS, failures, "doc-file")
    count += check_tokens(DOC_TOKEN_CHECKS, failures, "doc-token")

    docs_text = "\n".join(read_text(path) for path in TARGET_DOCS if (ROOT / path).exists())
    for scenario_id in SCENARIO_IDS:
        count += 1
        if scenario_id not in docs_text:
            failures.append(Failure("doc-scenario", "research docs", scenario_id))
    return count


def check_absent_test_tokens(failures: list[Failure]) -> int:
    test_roots = (ROOT / "test/unit", ROOT / "test/distributed")
    test_text_parts: list[str] = []
    for root in test_roots:
        for path in root.rglob("*.java"):
            test_text_parts.append(path.read_text(encoding="utf-8"))
    test_text = "\n".join(test_text_parts)

    count = 0
    for token in ABSENT_TEST_TOKENS:
        count += 1
        if token in test_text:
            failures.append(Failure("gap-closed-update-docs", "test/unit test/distributed", token))
    return count


def run_checks() -> dict[str, object]:
    failures: list[Failure] = []
    source_checks = check_tokens(SOURCE_TOKEN_CHECKS, failures, "source-token")
    test_checks = check_tokens(TEST_TOKEN_CHECKS, failures, "test-token")
    absent_gap_checks = check_absent_test_tokens(failures)
    doc_checks = check_doc_tokens(failures)
    return {
        "source_checks": source_checks,
        "test_checks": test_checks,
        "absent_gap_checks": absent_gap_checks,
        "doc_checks": doc_checks,
        "scenario_count": len(SCENARIO_IDS),
        "failures": [failure.__dict__ for failure in failures],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable check results")
    args = parser.parse_args()

    result = run_checks()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))

    failures = result["failures"]
    if failures:
        if not args.json:
            for failure in failures:
                print(f"FAIL {failure['category']}: {failure['path']} missing {failure['token']}", file=sys.stderr)
        return 1

    if not args.json:
        print(
            "OK Cache runtime/persistence drift checks passed "
            f"({result['source_checks']} source checks, "
            f"{result['test_checks']} test checks, "
            f"{result['absent_gap_checks']} explicit gap checks, "
            f"{result['doc_checks']} doc checks, "
            f"{result['scenario_count']} scenarios)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
