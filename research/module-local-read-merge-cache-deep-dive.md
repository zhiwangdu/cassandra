# Module: Local Read Merge And Cache Deep Dive

## 范围

本模块补齐 Storage Engine 的单分区本地 replica 读路径：`SinglePartitionReadCommand` 如何决定 row cache、如何选择 memtable/SSTable view、如何把 memtable 与 SSTable iterator 合并、如何在 names-filter 查询中按 SSTable timestamp 做 early stop、如何在 read repair 的 repaired-data tracking 模式下分流 repaired/unrepaired iterators，以及 key cache 在 SSTable reader 格式层的位置。Coordinator data/digest 协议和 read repair 主线见 `research/module-read-path.md`、`research/flow-read.md`；range read 的 DataRange、subrange、dynamic concurrency、本地 partitionIterator merge 和 row cache filter 见 `research/module-range-read-storage-engine-matrix.md`。

## 设计目标

- 本地读在一个 `ReadExecutionController` 中取得 read op-order，保证 memtable/SSTable view 与 flush、secondary-index stale cleanup 的并发边界一致；controller 创建见 `src/java/org/apache/cassandra/db/ReadExecutionController.java:129-148`。
- 单分区读优先使用 row cache，但只在表启用 row cache 且当前没有 repaired-data tracking 时使用；分支见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:487-493`。
- Cache miss 或 cache 不覆盖当前 filter 时，读路径必须回到 memtable/SSTable merge；row cache fallback 见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:516-642`。
- 通用 merge 策略同时收集所有可见 memtable 与相关 SSTable iterator，最后通过 `UnfilteredRowIterators.merge()` 合并；入口见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:679-840`，合并包装见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:903-929`。
- 对可证明完整的 clustering names 查询，读路径按 SSTable max timestamp 从新到旧查询并逐步缩小 filter，尽早停止访问旧 SSTable；优化入口见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:943-1073`。
- Repaired-data tracking 模式下，读路径要把 repaired SSTable merge 成单独 digest，再加回 unrepaired iterator 列表，避免简单 row cache 命中绕过 repaired digest；`InputCollector` 逻辑见 `src/java/org/apache/cassandra/db/ReadCommand.java:902-1045`。

## 解决的问题

- Row cache 缓存的是 partition 内容，不是最终 SELECT 结果；只有 cache 内容能覆盖当前 `ClusteringIndexFilter` 和 `DataLimits` 时才能直接返回，覆盖判断见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1916-1934`。
- Cache miss 并不总是填充 cache。只有全分区缓存或 head filter 查询才会放置 sentinel、做 full-partition read、生成 `CachedBTreePartition`，见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:549-642`。
- Memtable 数据永远按 unrepaired 处理，read repair 的 repaired digest 只能来自 repaired SSTable；memtable iterator 收集和 tombstone 下界更新见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:718-732`。
- 非相交 SSTable 仍可能因为 static row 或 partition-level deletion 被纳入 merge；判断分支见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:770-827`。
- 已看到的新 partition tombstone 可以让更旧 SSTable 被跳过，但 repaired tracking 需要把 digest 标记为 inconclusive；跳过逻辑见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:757-769`。
- Key cache 不是 `SinglePartitionReadCommand` 的分支；它在 SSTable reader `getPosition()` 中缓存 partition index entry。BigTable 的 key-cache path 见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:255-282`，format contract 见 `src/java/org/apache/cassandra/io/sstable/keycache/KeyCacheSupport.java:40-95`。

## 设计取舍

- Row cache 命中可以把 SSTable iterated 数更新为 0，减少磁盘读取，但写入会按 partition key 失效缓存；写路径失效见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1477-1480`，命中路径更新见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:530-543`。
- Sentinel-read-cache 序列避免多个并发 miss 同时填充同一个 partition，但如果写入使 sentinel 失效，读路径可以返回本次读到的数据但不会缓存它；sentinel 分支见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:549-636`。
- 通用 merge 保守但正确：同时打开 memtable/SSTable iterators，避免 timestamp-order early stop 在 collection、UDT、counter 或 repaired tracking 场景下漏读旧数据；优化前置条件见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:686-708`。
- Timestamp-order names-filter 优化能减少旧 SSTable 访问，但只能在查询具体 clustering names、非 counter、非 multicell、非 repaired tracking 时使用；进入条件见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:701-708`。
- Repaired-data tracking 增加 merge 成本，但它是 digest mismatch 后判断 repaired data 是否一致的依据；`ReadExecutionController.isTrackingRepairedStatus()` 和 digest 信息入口见 `src/java/org/apache/cassandra/db/ReadExecutionController.java:214-231`。
- BigTable 支持 key cache 命中，BTI 依赖 partition trie，不使用同一套 key-cache value serializer；BTI 边界见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiFormat.java:189-193`、`src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java:223-275`。

## 核心类

| 类 | 作用 |
|---|---|
| `SinglePartitionReadCommand` | 单分区本地读核心，处理 row cache、memtable/SSTable merge、timestamp-order names-filter 优化；本地 storage 入口见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:487-545` |
| `ReadCommand` | 本地读抽象，包装 index/searcher、size/tombstone/metrics，并提供 `InputCollector`；执行入口见 `src/java/org/apache/cassandra/db/ReadCommand.java:426-470` |
| `ReadExecutionController` | 持有 read op-order、index controller、write context、repaired-data digest 和 oldest unrepaired tombstone；字段与构造见 `src/java/org/apache/cassandra/db/ReadExecutionController.java:33-80` |
| `ColumnFamilyStore.ViewFragment` | 本地读 view，包含本次读取可见 SSTable 列表和 memtable iterable；定义见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:3221-3237` |
| `ColumnFamilyStore` | 提供 row cache 覆盖判断、view 选择、cache 失效和 row-cache enable 判断；相关方法见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1916-2005`、`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:2486-2496` |
| `Memtable` | 提供 `rowIterator()` 给 read path，接口定义见 `src/java/org/apache/cassandra/db/memtable/Memtable.java:58` |
| `SSTableReader` | 本地读的磁盘 reader，按 filter/intersection 创建 row iterator；selection listener 通过 `SSTableReadsListener` 记录 skip/selected 原因，见 `src/java/org/apache/cassandra/io/sstable/SSTableReadsListener.java:26-57` |
| `KeyCacheSupport` | 支持 key cache 的 SSTable reader contract，构造 `KeyCacheKey` 并读写 cached position；见 `src/java/org/apache/cassandra/io/sstable/keycache/KeyCacheSupport.java:40-95` |
| `CachedPartition` / `IRowCacheEntry` | Row cache value 与 sentinel 的抽象；row cache get/replace 使用见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:516-608` |

## 核心接口

- `ReadCommand.queryStorage()`：本地 storage 抽象入口；`SinglePartitionReadCommand` 实现 row cache 与 disk/memtable 分支，抽象定义见 `src/java/org/apache/cassandra/db/ReadCommand.java:357`。
- `ColumnFamilyStore.select(View.select(...))`：获取当前 live SSTables 与所有 memtables；select 方法见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:2001-2005`，调用见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:663-665`。
- `Memtable.rowIterator(...)`：按 partition key、slice、column filter 和方向返回 memtable iterator；调用见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:718-720`。
- `StorageHook.instance.makeRowIterator(...)`：为 SSTable 创建 row iterator，普通/跳过非静态内容两种调用见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:863-899`。
- `UnfilteredRowIterators.merge(...)`：合并 memtable、SSTable 或 timestamp-order intermediate result；通用合并见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:903-929`，timestamp-order add 合并见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:1066-1073`。
- `ColumnFamilyStore.isFilterFullyCoveredBy(...)`：判断 row cache 是否可满足当前 filter/limit；实现见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1916-1934`。

## 核心数据结构

- `RowCacheKey`：row cache key，包含 table metadata 与 partition key；使用位置见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:504-516`，定义见 `src/java/org/apache/cassandra/cache/RowCacheKey.java:34-58`。
- `CachedBTreePartition`：cache miss 后从 full partition read 中截断出可缓存行，创建见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:604-608`。
- `ColumnFamilyStore.ViewFragment`：一次本地读的 SSTable/memtable 快照；定义见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:3221-3237`。
- `InputCollector`：按 repaired status 收集 iterators，并在 finalize 时把 repaired iterators merge/digest 后加回 unrepaired 列表；构造和 finalize 见 `src/java/org/apache/cassandra/db/ReadCommand.java:942-1010`。
- `SSTableReadMetricsCollector`：统计本次读实际合并的 SSTable 数，供 `sstablesPerReadHistogram` 和 top read partition SSTable count 使用；使用见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:713-840`、`src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:903-929`。
- `ClusteringIndexNamesFilter`：timestamp-order 优化只针对具体 clustering names filter，并通过 `reduceFilter()` 移除已满足的 clustering；filter 收缩见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:1077-1157`。
- `KeyCacheKey` / `AbstractRowIndexEntry`：BigTable key cache 的 key/value；Key cache 保存/加载细节见 `research/module-cache-index-view-deep-dive.md` 和 `research/module-cache-index-view-vector-import-repair.md`。

## 生命周期

```text
ReadCommandVerbHandler.doVerb()
  -> command.executionController(trackRepairedStatus)
     -> ReadExecutionController.forCommand(...)
        -> baseCfs.readOrdering.start()
        -> optional indexCfs.readOrdering.start()
  -> command.executeLocally(controller)
     -> ReadCommand.executeLocally()
        -> queryStorage(cfs, controller)
           -> SinglePartitionReadCommand.queryStorage()
              -> if row cache enabled and repaired tracking is off:
                 -> getThroughCache(...)
                    -> row cache hit -> return cached partition iterator
                    -> sentinel miss -> fullPartitionRead(...).queryMemtableAndDisk(...)
                    -> cache out of range -> queryMemtableAndDisk(...)
              -> else:
                 -> queryMemtableAndDisk(...)
                    -> cfs.select(live SSTables, all memtables)
                    -> queryMemtableAndDiskInternal(...)
                       -> optional timestamp-order names-filter path
                       -> else generic memtable/SSTable iterator collection
                       -> inputCollector.finalizeIterators(...)
                       -> UnfilteredRowIterators.merge(...)
```

`ReadExecutionController.close()` closes the base op-order and optional index controller/write context, then records top local read query time when sampling is enabled; close path见 `src/java/org/apache/cassandra/db/ReadExecutionController.java:191-211`。

## 调用链

- Row cache decision：`SinglePartitionReadCommand.queryStorage()` checks table row cache and repaired tracking, then chooses `getThroughCache()` or `queryMemtableAndDisk()`; source见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:487-493`。
- Row cache hit：`CacheService.instance.rowCache.get()` returns `CachedPartition` and coverage succeeds, then metric `rowCacheHit` increments and `updateSSTableIterated(0)` runs; source见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:516-543`。
- Row cache fill：miss path creates `RowCacheSentinel`, reads `fullPartitionRead(...).queryMemtableAndDisk(...)`, builds `CachedBTreePartition`, replaces sentinel, then re-filters for the user query; source见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:549-625`。
- Generic local merge：`queryMemtableAndDisk()` obtains a `ViewFragment`, `queryMemtableAndDiskInternal()` reads memtables, filters SSTables, collects iterators, then merges them; source见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:658-840`。
- Timestamp-order local merge：names-filter path first merges memtables, then reads SSTables sorted by max timestamp, shrinks the filter with `reduceFilter()`, and stops when all requested rows/statics are complete; source见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:943-1190`。
- Repaired-data tracking：`InputCollector.addSSTableIterator()` sends repaired SSTables to `repairedIters`, `finalizeIterators()` merges them and updates `RepairedDataInfo`; source见 `src/java/org/apache/cassandra/db/ReadCommand.java:991-1010`。
- Key cache path：BigTable `getPosition()` runs Bloom/min-max/key-cache/index-summary/primary-index logic; key-cache hit notifies `KEY_CACHE_HIT`, source见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:255-282`、`src/java/org/apache/cassandra/io/sstable/SSTableReadsListener.java:54-57`。

## 配置项

| 配置项 | 定义位置 | 影响 |
|---|---|---|
| 表级 `caching.keys` / `caching.rows_per_partition` | `CachingParams` CQL shape 见 `src/java/org/apache/cassandra/schema/CachingParams.java:31-58`，解析见 `src/java/org/apache/cassandra/schema/CachingParams.java:89-109` | 控制 key cache 和 row cache eligibility；默认 keys=true、rows=0 |
| `row_cache_size`、`row_cache_save_period`、`row_cache_keys_to_save` | 字段见 `src/java/org/apache/cassandra/config/Config.java:472-477`，模板见 `conf/cassandra.yaml:545-579` | 控制全局 row cache 容量和保存 |
| `key_cache_size`、`key_cache_save_period`、`key_cache_keys_to_save` | 字段见 `src/java/org/apache/cassandra/config/Config.java:464-470`，模板见 `conf/cassandra.yaml:510-543` | 控制全局 key cache 容量和保存 |
| `key_cache_migrate_during_compaction` | 字段见 `src/java/org/apache/cassandra/config/Config.java:464` | compaction 后是否迁移 key cache entry |
| `tombstone_warn_threshold` / `tombstone_failure_threshold` | 字段见 `src/java/org/apache/cassandra/config/Config.java:534-535`，模板见 `conf/cassandra.yaml:1814-1815` | 本地 merge 后 tombstone 扫描保护 |
| `local_read_size_warn_threshold` / `local_read_size_fail_threshold` | 字段见 `src/java/org/apache/cassandra/config/Config.java:529-530`，模板见 `conf/cassandra.yaml:2025-2026` | 本地读数据量保护 |

## Metrics

- `TableMetrics.rowCacheHit`、`rowCacheMiss`、`rowCacheHitOutOfRange` 定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:164-169`，更新见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:516-543`。
- `TableMetrics.sstablesPerReadHistogram` 记录单分区读实际 merge 的 SSTable 数；row cache hit 也会记录 0，相关更新见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:530-543`、`src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:903-929`。
- `TableMetrics.topReadPartitionFrequency` 和 `topReadPartitionSSTableCount` 在 merged iterator 非空时采样，见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:913-925`。
- Key cache metrics 由 `KeyCache`/`AutoSavingCache` 暴露；BigTable position lookup 请求/命中测试见 `test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java:600-630`。
- Tombstone、live row 和 local read size 观测仍由 `ReadCommand.withMetricsRecording()` 与 size tracking 包装处理，主文档见 `research/module-read-path.md`。

## 日志

- Row cache hit/miss/out-of-range 通过 tracing 记录 `Row cache hit`、`Row cache miss` 和 `Ignoring row cache...`，见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:523-539`。
- Row cache fill 会 trace `Caching {} rows`，见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:604-608`。
- Generic merge 在 tracing 开启时记录跳过非相交 SSTable 和因 tombstone 纳入的数量，见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:831-833`。
- `withSSTablesIterated()` 在 partition close 时 trace merged SSTable 数，见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:919-929`。
- Row cache 无法填充时 trace query does not query from partition start，见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:640-641`。
- Tombstone warning 仍由 `ReadCommand.withMetricsRecording()` 发出 logger warning，见 `src/java/org/apache/cassandra/db/ReadCommand.java:629-645`。
- Capturing SSTable refs 长时间失败时 `ColumnFamilyStore.selectAndReference()` 通过 no-spam logger 记录 warning，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1975-1998`。

## 运维关注点

- Row cache 需要同时满足表级 `caching.rows_per_partition` 和全局 row cache capacity；`ColumnFamilyStore.isRowCacheEnabled()` 见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:3259-3264`。
- Row cache 适合热点整分区或 partition head 查询；非 head filter、cache out-of-range、limit 超过缓存行数都会回退到 memtable/SSTable 读，见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:537-642`。
- 写入会失效整个 cached partition，写多读少或高更新表容易造成 row cache churn；失效调用见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1477-1480`。
- `sstablesPerReadHistogram` 高说明本地 merge 正在访问多个 SSTable，通常要结合 compaction strategy、key cache、Bloom/index summary 和数据模型排查。
- Repaired-data tracking 读会绕过 row cache，因此 digest mismatch 后的 repair/read retry 延迟可能高于普通 cache-hit 读。
- Key cache 命中只减少 SSTable partition index lookup 成本，不跳过 Bloom/min-max/row merge，也不能替代 row cache；BigTable key-cache branch 见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:255-282`。

## 性能瓶颈

- Generic merge 会把所有相关 memtable/SSTable iterator 合入一个 partition iterator；SSTable 数量和 overlap 越高，CPU、seek 和 tombstone scan 成本越高。
- Row cache fill 使用 full-partition read，再截断到 `rows_per_partition`，大 partition 首次读可能比普通读更重；fill path 见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:549-625`。
- Timestamp-order optimization 对 names-filter 有利，但 collection、UDT、counter 和 repaired tracking 都会禁用它，回到通用 merge；禁用条件见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:686-708`。
- Partition-level deletion 会让非相交 SSTable 被纳入 merge，用于维持跨 replica 删除语义；相关分支见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:800-827`。
- BigTable key cache miss-heavy workload 仍会落回 index summary/primary index；SSTable 数多时每个 SSTable 都要重复执行这些 reader-level checks。

## 常见故障

- Row cache 命中率低：全局容量为 0、表级 rows cache 为 `NONE`、查询不是 head filter、cache out-of-range 或写入频繁失效。配置和 enable 判断见 `src/java/org/apache/cassandra/schema/CachingParams.java:74-86`、`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:3259-3264`。
- Row cache hit 但结果仍慢：cache 只能覆盖 partition 内容读取，coordinator data/digest、read repair、result processing 和 tombstone/size tracking 仍可能耗时。
- Key cache 命中率低：SSTable format 不支持、operator 为 `GT`、Bloom/min-max 已跳过、wide partition 无法有效缓存或 cache 被 compaction/deletion 清理；listener 行为测试见 `test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java:708-727`。
- Digest mismatch 后读变慢：repaired-data tracking 会绕过 row cache，并把 repaired SSTables 单独 merge/digest，见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:487-493`、`src/java/org/apache/cassandra/db/ReadCommand.java:991-1010`。
- Tombstone shadowing 异常：需要检查 partition-level deletion 是否因非相交 SSTable 分支被纳入 merge；distributed 测试覆盖见 `test/distributed/org/apache/cassandra/distributed/test/SSTableSkippingReadTest.java:35-127`。
- Wide partition 首次 row-cache fill 造成读尖刺：miss path full partition read 与 `CachedBTreePartition.create()` 在同次请求内完成，见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:569-608`。

## 测试用例

- Row cache hit/out-of-range、缓存行数和 histogram 更新：`test/unit/org/apache/cassandra/db/RowCacheTest.java:88-130`、`test/unit/org/apache/cassandra/db/RowCacheTest.java:408-522`。
- Row cache CQL 基本行为：`test/unit/org/apache/cassandra/db/RowCacheCQLTest.java`。
- Key cache CQL metrics：`test/unit/org/apache/cassandra/cql3/KeyCacheCqlTest.java:500-535`。
- Key cache save/load、compaction 后迁移/清理：`test/unit/org/apache/cassandra/io/sstable/keycache/KeyCacheTest.java:320-362`。
- BigTable key-cache/Bloom/listener selection：`test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java:600-730`。
- Single partition deletion/column/static row reconciliation：`test/distributed/org/apache/cassandra/distributed/test/SinglePartitionReadCommandTest.java:29-220`。
- SSTable skip and partition deletion shadowing：`test/distributed/org/apache/cassandra/distributed/test/SSTableSkippingReadTest.java:35-127`。
