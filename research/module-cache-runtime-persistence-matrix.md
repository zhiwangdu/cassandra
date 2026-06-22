# Cache Runtime Persistence Matrix

## 范围

本文补齐 `research/module-cache-index-view.md`、`research/module-cache-index-view-deep-dive.md` 和 `research/module-cache-index-view-vector-import-repair.md` 中偏 SSTable/index/MV 的 Cache 内容，单独固定 key cache、row cache、counter cache、chunk cache 的运行时控制、保存/加载、失效、指标、JMX/nodetool 和现有测试基线。Big/BTI key-cache on-disk 差异仍以 SSTable/Bloom/Index 文档为主；本篇聚焦通用 cache runtime contract。

## 场景矩阵

| 场景 ID | 源码合同 | 测试/缺口 |
|---|---|---|
| `cache_service_mbean_init_contract` | `CacheService` 注册 `org.apache.cassandra.db:type=Caches` MBean，构造时初始化 key/row/counter 三个 `AutoSavingCache`；`CacheType` 的 `KeyCache`、`RowCache`、`CounterCache` 名称同时是 metrics/JMX 命名边界。见 `src/java/org/apache/cassandra/service/CacheService.java:76-113`。 | JMX dump checker 覆盖 MBean 存在性；本 slice 保护 CacheService MBean method tokens。 |
| `cache_config_autosize_directory_contract` | `Config` 定义 key/row/counter cache size、save period、keys-to-save、`saved_caches_directory`、`cache_load_timeout` 和 file cache 参数；`DatabaseDescriptor` 对 key/counter cache auto sizing、saved caches 目录冲突和 chunk cache size/round-up 提供默认/校验。见 `Config.java:464-510`、`DatabaseDescriptor.java:700-752`、`:814-864`、`:3768-3818`。 | 配置解析有分散覆盖；缺 cache 配置组合的专门 matrix test。 |
| `cache_autosaving_persistence_contract` | `AutoSavingCache` 使用当前落盘版本 `g`，保存 `.db`、`.crc`、`.metadata` 三类文件；`scheduleSaving()` 取消旧任务并用 `ScheduledExecutors.optionalTasks.scheduleWithFixedDelay()` 周期提交 `submitWrite()`。见 `src/java/org/apache/cassandra/cache/AutoSavingCache.java:90-179`。 | `AutoSavingCacheTest.testSerializeAndLoadKeyCache*()` 覆盖 key cache submit/load 基础路径。 |
| `cache_save_load_serializer_contract` | `loadSaved()` 要求 data/crc/metadata 同时存在，先反序列化 metadata，再校验 schema version 和 `cache_load_timeout`，每个 entry 通过 `CacheSerializer.deserialize()` 异步加载，最后 put 回 cache；`Writer.saveCache()` 写 schema version、entry、metadata 后 sync+rename。见 `AutoSavingCache.java:199-287`、`:349-425`、`:466-540`。 | `KeyCacheTest.testKeyCacheLoad*()`、`CounterCacheTest.testSaveLoad()`、`RowCacheTest.testRowCacheDisabled()` 覆盖 key/counter/row 保存加载边界。 |
| `cache_runtime_capacity_keys_contract` | `CacheServiceMBean` 暴露 save period、keys-to-save、capacity 和 `saveCaches()`；setter 拒绝负值、更新 `DatabaseDescriptor` 并重新 `scheduleSaving()`；capacity 以 MiB 转 bytes 传给底层 cache。见 `CacheServiceMBean.java:22-66`、`CacheService.java:193-360`。 | `NodeToolTest.testSetCacheCapacityWhenDisabled()` 覆盖 row cache disabled 时 `setcachecapacity` 失败；缺 `setcachekeystosave` focused test。 |
| `cache_global_table_invalidation_contract` | 全局 invalidate 直接 `clear()` 对应 cache；table 级 invalidate 迭代 `keyIterator()` 并按 `CacheKey.sameTable()` 删除；`ColumnFamilyStore.invalidateCaches()` 在 table 级变更中同时清 key/row/counter。见 `CacheService.java:274-320`、`ColumnFamilyStore.java:2436-2442`。 | `KeyCacheTest`、`CounterCacheTest` 和 `RowCacheTest` 间接覆盖 invalidate；缺三种 nodetool invalidate 命令的专门 CLI 测试。 |
| `key_cache_entry_identity_contract` | `KeyCacheKey` 由 table id/index name、SSTable `Descriptor` 和 partition key bytes 构成；`KeyCacheSerializer` 为每个 live SSTable 写 ordinal、format/version/id metadata，entry 写 key length/key bytes 与 `AbstractRowIndexEntry.serializeForCache()`，加载时可跳过已删除 SSTable。见 `KeyCacheKey.java:29-87`、`CacheService.java:425-559`。 | `KeyCacheTest.testKeyCacheLoadShallowIndexEntry()` 与 on-heap index info variant 覆盖保存/加载后 entry position、block count 和 format。 |
| `row_cache_read_write_invalidation_contract` | 写入 memtable 后 `ColumnFamilyStore.apply()` 调 `invalidateCachedPartition()`；读取端 `SinglePartitionReadCommand.getThroughCache()` 使用 `RowCacheSentinel` 避免并发填充，统计 hit/miss/out-of-range，并只在 head/full partition 查询时填充。见 `ColumnFamilyStore.java:1475-1480`、`:2486-2497`、`SinglePartitionReadCommand.java:487-640`。 | `RowCacheTest.testRowCacheRange()` 覆盖 hit/out-of-range metrics；`RowCacheCQLTest` 覆盖 partial row cache CQL 语义。 |
| `counter_cache_read_before_write_contract` | Counter mutation 写入前如果 counter cache 有容量，先从 `ColumnFamilyStore.getCachedCounter()` 读取 clock/count；更新后 `putCachedCounter()` 写回；cache key 由 partition key、clustering、column 和 cell path 组成。见 `CounterMutation.java:207-255`、`ColumnFamilyStore.java:2499-2510`、`CounterCacheKey.java:44-150`。 | `CounterCacheTest.testReadWrite()`、`testCounterCacheInvalidate()`、`testSaveLoad()` 覆盖读写、range invalidate 和保存/加载。 |
| `chunk_cache_file_cache_contract` | `ChunkCache` 由 `file_cache_enabled` 和 `file_cache_size - 32MiB reserved pool` 决定是否创建 singleton，使用 Caffeine weighted cache、BufferPool、`ChunkCacheMetrics`，并可按 position/file invalidate。见 `src/java/org/apache/cassandra/cache/ChunkCache.java:46-213`。 | `nodetool info` 可读取 ChunkCache metrics；缺 chunk cache 文件读取/失效 focused test。 |
| `cache_metrics_virtual_table_contract` | `InstrumentingCache.get()` 标记 requests/hits/misses，`clear()` 重建 metrics；`CacheMetrics` 暴露 Capacity/Size/Entries/Hits/Misses/Requests/HitRate；`CachesTable` 将 chunks/counters/keys/rows 映射到 `system_views.caches`。见 `InstrumentingCache.java:34-123`、`CacheMetrics.java:32-114`、`CachesTable.java:27-81`。 | `CacheMetricsTest.testCacheMetrics()` 覆盖 basic counters；缺 `system_views.caches` focused virtual table test。 |
| `cache_nodetool_jmx_surface_contract` | `NodeTool` 注册 `invalidatekeycache`、`invalidaterowcache`、`invalidatecountercache`、`setcachecapacity`、`setcachekeystosave`；`NodeProbe` 代理到 CacheService MBean；`nodetool info` 输出 Key/Row/Counter/Chunk cache 指标。见 `NodeTool.java:166-207`、`NodeProbe.java:593-620`、`:688-690`、`:1088-1101`、`Info.java:91-138`。 | `NodeToolTest.testSetCacheCapacityWhenDisabled()` 覆盖 disabled row cache failure；其余 cache CLI 仍是 source-only contract。 |
| `cache_existing_tests_baseline` | 当前测试基线包括 `AutoSavingCacheTest`、`KeyCacheTest`、`CounterCacheTest`、`RowCacheTest`、`RowCacheCQLTest`、`CacheMetricsTest` 和 `NodeToolTest.testSetCacheCapacityWhenDisabled()`。 | checker 保护这些测试名和关键断言继续存在。 |
| `cache_runtime_operator_gap` | 仍缺 operator-facing cache runtime 专项测试：`setcachekeystosave` 重新 schedule、三种 invalidate nodetool 命令、`system_views.caches` rows、chunk cache file invalidation 和 save period runtime mutation。 | 保留 explicit gap；如果新增测试，应同步更新本矩阵和 checker 的 negative scan。 |

## 设计目标

- 用 key cache 降低 SSTable partition key 到 row-index entry 的定位成本，减少重复 index scan。
- 用 row cache 缓存热 partition 的前 N 行或全 partition，减少 memtable/SSTable merge 和过滤成本。
- 用 counter cache 缓存 counter cell 的 last clock/count，降低 read-before-write 的磁盘读取。
- 用 chunk cache 缓存未压缩 SSTable chunk，复用 read path 的 file buffer。
- 通过 AutoSavingCache 在重启后 warm up key/row/counter cache，避免冷启动后所有热 key 重新学习。
- 通过 MBean、nodetool、metrics 和 virtual table 暴露容量、命中率、保存周期和手动清理能力。

## 设计取舍

- Row cache 默认 0MiB，避免大 partition 或高写入 workload 下的失效开销；启用后写入会按 partition 粗粒度 invalidation。
- Key/counter cache 默认 auto sizing，分别按 heap 5%/2.5% 且 capped；这是内存占用和热路径收益之间的保守折中。
- `AutoSavingCache` 保存 hot keys 或全部 keys，由 `*_keys_to_save` 控制；保存过多会拉长 shutdown/periodic cache save，保存过少会降低重启后命中率。
- Cache load 校验 schema version；schema 变化会放弃旧 cache，而不是尝试跨 schema 恢复。
- Cache save 使用 compaction executor 的 cache-write operation type，统一进度/调度语义，但 `system_views.sstable_tasks` 显式过滤 cache save tasks。
- `setcachecapacity` 只能调整已经实例化的 cache；row cache 初始化为 `NopCacheProvider` 后，非 0 capacity 会抛 disabled-cache 错误，需要先通过 yaml 启用。

## 核心类

| 类 | 作用 |
|---|---|
| `CacheService` | 全局 singleton/MBean，初始化 key/row/counter cache，提供保存周期、keys-to-save、capacity、invalidate 和 `saveCaches()`。 |
| `CacheServiceMBean` | JMX contract，nodetool runtime cache commands 的远端接口。 |
| `AutoSavingCache` | 给底层 `ICache` 增加保存/加载、周期调度、compaction progress holder 和 cache serializer lifecycle。 |
| `InstrumentingCache` | 包装 `ICache` 并维护 requests/hits/misses metrics。 |
| `KeyCacheKey` | key cache identity：table/index、SSTable descriptor、partition key bytes。 |
| `RowCacheKey` | row cache identity：table/index、partition key bytes。 |
| `CounterCacheKey` | counter cache identity：table/index、partition key、cell name，并能回读 counter value。 |
| `ChunkCache` | SSTable chunk 的 Caffeine/BufferPool cache。 |
| `NopCacheProvider` | row cache disabled 时的 no-op implementation，禁止 runtime 设置非 0 capacity。 |
| `CachesTable` | `system_views.caches` virtual table，把 cache metrics 映射成 CQL rows。 |
| nodetool `Info`/`SetCacheCapacity`/`SetCacheKeysToSave`/`Invalidate*Cache` | operator cache 观测和控制入口。 |

## 核心接口与数据结构

- `CacheService.instance.keyCache` / `rowCache` / `counterCache`：全局 runtime cache handles。
- `CacheService.saveCaches()`：并发提交 key/row/counter cache write 并等待完成。
- `AutoSavingCache.scheduleSaving(savePeriodInSeconds, keysToSave)`：更新周期保存任务。
- `AutoSavingCache.loadSaved()` / `loadSavedAsync()`：从 saved caches 目录加载落盘 cache。
- `AutoSavingCache.Writer.saveCache()`：写 `.db`、`.crc`、`.metadata` 临时文件并 rename 成正式文件。
- `AutoSavingCache.CacheSerializer`：保存/加载 table metadata ordinal 和 cache entry。
- `ColumnFamilyStore.isRowCacheEnabled()` / `isKeyCacheEnabled()` / `isCounterCacheEnabled()`：table option + global capacity gate。
- `ColumnFamilyStore.invalidateRowCache(bounds)` / `invalidateCounterCache(bounds)`：range movement/cleanup 的 cache eviction hook。
- `SinglePartitionReadCommand.getThroughCache()`：row cache read/fill/hit/out-of-range 主路径。
- `CounterMutation.processModifications()`：counter cache read-before-write 主路径。

## 生命周期与调用链

CacheService startup：

```text
CacheService.instance
  -> CacheService()
  -> MBeanWrapper.instance.registerMBean(this, "org.apache.cassandra.db:type=Caches")
  -> initKeyCache()
       -> DatabaseDescriptor.getKeyCacheSizeInMiB()
       -> CaffeineCache.create(capacity)
       -> new AutoSavingCache(..., KEY_CACHE, KeyCacheSerializer)
       -> scheduleSaving(key_cache_save_period, key_cache_keys_to_save)
  -> initRowCache()
       -> row_cache_size > 0 ? row_cache_class_name : NopCacheProvider
       -> provider.create()
       -> new AutoSavingCache(..., ROW_CACHE, RowCacheSerializer)
       -> scheduleSaving(row_cache_save_period, row_cache_keys_to_save)
  -> initCounterCache()
       -> CaffeineCache.create(counter capacity)
       -> new AutoSavingCache(..., COUNTER_CACHE, CounterCacheSerializer)
       -> scheduleSaving(counter_cache_save_period, counter_cache_keys_to_save)
```

Periodic save/load：

```text
CacheService.setKeyCacheSavePeriodInSeconds(seconds)
  -> DatabaseDescriptor.setKeyCacheSavePeriod(seconds)
  -> keyCache.scheduleSaving(seconds, key_cache_keys_to_save)
  -> ScheduledExecutors.optionalTasks.scheduleWithFixedDelay(...)
  -> AutoSavingCache.submitWrite(keysToSave)
  -> CompactionManager.instance.submitCacheWrite(Writer)
  -> Writer.saveCache()
       -> delete old cache files
       -> write schema version
       -> CacheSerializer.serialize(key, writer, cfs)
       -> CacheSerializer.serializeMetadata(metadataWriter)
       -> move temp db/crc/metadata files into saved_caches_directory

AutoSavingCache.loadSaved()
  -> read metadata
  -> read schema version from db file
  -> reject schema mismatch
  -> deserialize entries until cache_load_timeout or EOF
  -> put loaded entries back into cache
```

Row cache read/write：

```text
write mutation
  -> ColumnFamilyStore.apply(...)
  -> Memtable.put(update, ...)
  -> invalidateCachedPartition(update.partitionKey())

read partition
  -> SinglePartitionReadCommand.queryStorage()
  -> cfs.isRowCacheEnabled() && !tracking repaired status
  -> getThroughCache()
       -> CacheService.instance.rowCache.get(RowCacheKey)
       -> hit: rowCacheHit + return filtered CachedPartition
       -> hit but filter outside cached bounds: rowCacheHitOutOfRange + read disk
       -> miss: rowCacheMiss
       -> put RowCacheSentinel
       -> full partition read from memtable/SSTable
       -> replace sentinel with CachedPartition
```

Counter write：

```text
CounterMutation.processModifications()
  -> collect CounterMark entries
  -> if counter cache capacity != 0
       -> getCachedCounter(partition, clustering, column, path)
       -> updateWithCurrentValue(mark, cached, cfs)
  -> read remaining counters from CFS
  -> for each update
       -> compute new clock/count
       -> putCachedCounter(..., ClockAndCount)
```

Operator control：

```text
nodetool setcachecapacity <key> <row> <counter>
  -> SetCacheCapacity.execute()
  -> NodeProbe.setCacheCapacities(...)
  -> CacheServiceMBean.set*CacheCapacityInMB(...)

nodetool setcachekeystosave <key> <row> <counter>
  -> NodeProbe.setCacheKeysToSave(...)
  -> CacheServiceMBean.set*CacheKeysToSave(...)
  -> AutoSavingCache.scheduleSaving(existingPeriod, newCount)

nodetool invalidatekeycache / invalidaterowcache / invalidatecountercache
  -> NodeProbe.invalidate*Cache()
  -> CacheServiceMBean.invalidate*Cache()
  -> AutoSavingCache.clear()
```

Observability：

```text
nodetool info
  -> NodeProbe.getCacheServiceMBean()
  -> NodeProbe.getCacheMetric("KeyCache"|"RowCache"|"CounterCache"|"ChunkCache", ...)
  -> Info prints entries/size/capacity/hits/requests/hit rate/save period

SELECT * FROM system_views.caches
  -> CachesTable.data()
  -> ChunkCache.instance.metrics when present
  -> CacheService.instance.counterCache/keyCache/rowCache.getMetrics()
```

## 配置项

- `key_cache_size`：key cache capacity；未设置时 auto 为 `min(max(1, heap * 5%), 100MiB)`。
- `key_cache_save_period`：key cache 周期保存，默认 `4h`。
- `key_cache_keys_to_save`：每次保存的 key cache key 数量，默认 all。
- `row_cache_class_name`：row cache provider，默认 `org.apache.cassandra.cache.OHCProvider`；row cache size 为 0 时实际使用 `NopCacheProvider`。
- `row_cache_size`：row cache capacity，默认 `0MiB`。
- `row_cache_save_period`：row cache 周期保存，默认 `0s`，即不周期保存。
- `row_cache_keys_to_save`：row cache 保存 key 数量，默认 all。
- `counter_cache_size`：counter cache capacity；未设置时 auto 为 `min(max(1, heap * 2.5%), 50MiB)`。
- `counter_cache_save_period`：counter cache 周期保存，默认 `7200s`。
- `counter_cache_keys_to_save`：counter cache 保存 key 数量，默认 all。
- `saved_caches_directory`：落盘 cache 目录，不能与 data/commitlog/hints/local_system 目录相同。
- `cache_load_timeout`：cache load 最大耗时，默认 `30s`。
- `file_cache_enabled`、`file_cache_size`、`file_cache_round_up`：chunk cache 与 buffer pool 参数。
- Table `caching` 参数：`keys` 和 `rows_per_partition` 决定每张表是否参与 key/row cache。

## Metrics、日志与诊断

- `org.apache.cassandra.metrics:type=Cache,scope=KeyCache|RowCache|CounterCache|ChunkCache,name=Capacity|Size|Entries|Hits|Misses|Requests|HitRate`：cache runtime 指标。
- `ChunkCacheMetrics.MissLatency`：chunk cache miss load latency。
- `TableMetrics.rowCacheHit` / `rowCacheMiss` / `rowCacheHitOutOfRange`：row cache table 级命中与 out-of-range 诊断。
- `system_views.caches`：以 CQL 形式暴露 chunks/counters/keys/rows 的 capacity、size、entry count、request/hit count 和 rates。
- `nodetool info`：快速查看 key/row/counter/chunk cache 容量、命中、请求、hit rate 和 save period。
- Cache save/load 日志：`Initializing ... cache`、`Reading saved cache`、`Saved ... cache`、checksum/schema mismatch 的 harmless/non-fatal log。

## 运维关注点

- Row cache 默认禁用；如果只用 `nodetool setcachecapacity` 把 disabled row cache 从 0 改为非 0，会触发 `NopCache` disabled-cache 错误，需要先在配置中启用 row cache。
- `invalidate*cache` 是全局清理；table/range 级清理由 CFS/cleanup/repair/topology 操作调用，不应把全局 invalidate 当成常规调优手段。
- `cache_load_timeout` 太低会导致重启后 cache warmup 不完整；太高会延长启动后恢复热 key 的后台开销。
- `*_keys_to_save = 0` 表示保存全部 key，不是禁用保存；禁用周期保存应设置 save period 为 0。
- Key cache 与 SSTable descriptor/format/id 绑定；SSTable 删除、format 变更或 schema mismatch 会导致部分 entry 被跳过。
- Row cache 对写多读少或大 partition workload 容易 churn；关注 `rowCacheHitOutOfRange` 与 table 级 miss/hit。
- Counter cache 有助于 counter write，但旧值不等于权威状态；cache miss 仍需回读 CFS。
- Chunk cache 和 OS page cache、buffer pool 共同影响 read latency，调大 `file_cache_size` 需要评估 heap/off-heap/IO 权衡。

## 性能瓶颈

- Auto-saving 写 cache 走 compaction cache-write executor；保存大量 key 时会占用后台资源并产生 saved_caches 目录 I/O。
- `AutoSavingCache.loadSaved()` 需要校验 crc/metadata/schema，并可能提交异步 read tasks；大量 entry 会受 `cache_load_timeout` 和 1000 futures backlog gate 影响。
- Row cache miss 后可能执行 full partition read 或 head read 并构造 `CachedBTreePartition`；大 partition 下 CPU/memory 成本高。
- 每次写入都按 partition invalidates row cache，热点写入会降低 row cache 命中率。
- Counter cache key 包含 composite cell name，复杂 clustering/path 会增加 key 内存占用。
- Chunk cache 使用 weighted Caffeine + BufferPool；chunk size、reserved pool 和 file cache size 会影响 eviction 与 allocation。

## 常见故障

- `nodetool info` Row Cache capacity 仍是 0：检查 `row_cache_size` 是否为 0；runtime `setcachecapacity` 不能从 `NopCacheProvider` 切换到真实 provider。
- 重启后 key cache 没恢复：确认 `saved_caches_directory` 可写、`.db/.crc/.metadata` 同时存在、schema version 未变化、`cache_load_timeout` 未过低。
- `system_views.caches` 没有 chunks 行：`ChunkCache.instance` 为空，通常是 `file_cache_enabled=false` 或有效 file cache size 为 0。
- Row cache hit 低且 out-of-range 高：查询 filter 超出已缓存 rows 范围，考虑调整 `rows_per_partition` 或禁用 row cache。
- Counter write latency 抖动：counter cache miss 会回读 CFS；同时检查 cache capacity、hit rate 和 counter compaction/repair 状态。
- Cache save 文件过大或保存慢：降低 keys-to-save 或增大 save period，并确认 saved_caches 目录所在磁盘不与热点 data/commitlog 争用。

## 测试基线与缺口

- `test/unit/org/apache/cassandra/cache/AutoSavingCacheTest.java`：key cache preheat、submitWrite、clear、`loadSavedAsync()`。
- `test/unit/org/apache/cassandra/io/sstable/keycache/KeyCacheTest.java`：key cache load、lost table/SSTable skip、cache load timeout、entry format/position。
- `test/unit/org/apache/cassandra/db/CounterCacheTest.java`：counter cache get/put、range invalidate、save/load、disabled load。
- `test/unit/org/apache/cassandra/db/RowCacheTest.java`：row cache disabled load、range hit/out-of-range、cache contents。
- `test/unit/org/apache/cassandra/db/RowCacheCQLTest.java`：CQL partial cache/static row correctness。
- `test/unit/org/apache/cassandra/metrics/CacheMetricsTest.java`：capacity/size/entries/hits/misses/requests/hit rate counters。
- `test/distributed/org/apache/cassandra/distributed/test/NodeToolTest.java`：`testSetCacheCapacityWhenDisabled()` 验证 row cache disabled error。
- 缺口：`setcachekeystosave` runtime reschedule、三种 invalidate cache CLI、`system_views.caches` virtual table、chunk cache file invalidation、save period mutation 和 cache metrics/JMX E2E。
