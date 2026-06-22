# Module: Cache, Index And View Deep Dive

## 范围

本模块补齐 Cache / Secondary Index / SAI / Materialized View 第二轮源码细节：BigTable key cache 命中路径、key cache 持久化格式、SAI V1 on-disk components、legacy index 与 SAI 的 build/rebuild 差异、SSTable 导入/streaming 增量 index build、MV build 状态机和 MV repair 开关。

不重复第一轮已经覆盖的基础点：cache 类型、普通 RowCache/CounterCache 主线、`Index.QueryPlan` 查询选择和 MV 正常写入生成逻辑。第一轮入口见 `research/module-cache-index-view.md:1`，Bloom/index summary 入口见 `research/module-bloom-filter-index-summary.md:1`。

## 设计目标

- 把 key cache 从“缓存 SSTable 位置”细化到 BigTable reader 的实际分支：min/max key、Bloom、key cache、index summary/primary index 的顺序。
- 明确 key cache value 与 SSTable descriptor、format version 和 table metadata 的绑定，解释删除 SSTable、格式升级和 table drop 后为什么要跳过或清理旧 cache entry。
- 将 SAI V1 component 矩阵落到源码：per-SSTable components、literal/numeric/vector per-column components、completion marker 和 open file 数。
- 对比 legacy secondary index 与 SAI build/rebuild：legacy 走隐藏 CFS + `CollatedViewIndexBuilder`，SAI 走 SSTable-attached components + `StorageAttachedIndexBuilder`。
- 补齐 MV build 的本地 checkpoint、分布式状态、nodetool 状态读取和 repair/auto-repair 配置交互。

## 解决的问题

- Key cache 不是 Bloom filter 的替代品：BigTable point read 先用 Bloom 排除不存在 key，再查 key cache；命中后直接返回 `RowIndexEntry`，否则再走 index summary 和 primary index，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:255-282`。
- Key cache 只支持实现 `KeyCacheSupport` 的 SSTable format；BigTable reader 在 online open 或 early open 时按 table `caching.cacheKeys()` 设置 `KeyCache`，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigSSTableReaderLoadingBuilder.java:70-80`、`src/java/org/apache/cassandra/io/sstable/format/big/BigTableWriter.java:170-180`。
- SAI 的“index built”不是一个布尔值：per-SSTable `GroupComplete` 和 per-column `ColumnComplete` marker 同时决定 SSTable/column index 是否完整，见 `src/java/org/apache/cassandra/index/sai/disk/format/IndexComponent.java:63-113`、`src/java/org/apache/cassandra/index/sai/disk/v1/V1OnDiskFormat.java:175-186`。
- `rebuild_index` 对 legacy index 和 SAI 的成本模型不同：legacy 需要读 base partition 并写 hidden index table，SAI 需要扫描 SSTable 并写 attached component files；入口都汇聚到 `SecondaryIndexManager.rebuildIndexesBlocking()`，见 `src/java/org/apache/cassandra/tools/nodetool/RebuildIndex.java:31-42`、`src/java/org/apache/cassandra/index/SecondaryIndexManager.java:381-429`。
- MV build 不是普通 repair：它写 `system.view_builds_in_progress` checkpoint 和 `system_distributed.view_build_status` host status，并通过 `viewbuildstatus` 汇总到 operator，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:411-421`、`src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:165-173`、`src/java/org/apache/cassandra/tools/nodetool/ViewBuildStatus.java:34-85`。

## 设计取舍

- BigTable key cache value 缓存的是 `AbstractRowIndexEntry`，命中可跳过 index summary/primary index，但仍只在 `EQ`/`GE` 且 key 是有效 `DecoratedKey` 时使用；`GT` 不走 key cache，读行为由 `BigTableReader` 分支决定，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:265-282`。
- key cache 持久化保存 SSTable format name、version、descriptor id 和 table metadata；恢复时如果 SSTable 不存在、format 不支持或 cache 禁用，entry 会被跳过，见 `src/java/org/apache/cassandra/service/CacheService.java:431-529`。
- SAI 将 token/partition/clustering row mapping 放到 per-SSTable components，将 term/postings/tree/vector 放到 per-column components；这样多个列 index 可共享 row mapping，源码 README 也强调 row-based column index level 和 per-SSTable shared offset/token 信息，见 `src/java/org/apache/cassandra/index/sai/README.md:27-35`。
- SAI segment build 用全局 memory limiter 控制 compaction/index build 的 on-heap segment buffering；flush 时如果是 memtable flush 且初始化 build 已开始，则使用 memtable index writer，否则从 SSTable contents 构建，见 `src/java/org/apache/cassandra/index/sai/disk/v1/V1OnDiskFormat.java:98-173`。
- MV build 通过分 range 的 compaction task 获得进度、可取消性和 compaction 视图；代价是首次 build 会 flush base table 并逐 key 读旧数据生成 view mutation，见 `src/java/org/apache/cassandra/db/view/ViewBuilder.java:84-107`、`src/java/org/apache/cassandra/db/view/ViewBuilderTask.java:92-118`。

## 核心类

| 类 | 作用 |
|---|---|
| `BigTableReader` | BigTable point/range lookup，包含 Bloom、key cache、index summary/primary index 分支。见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:255-282` |
| `KeyCacheSupport` | SSTable reader key cache contract，构造 `KeyCacheKey`、读取/写入 cached position、定义 cache value 反序列化入口。见 `src/java/org/apache/cassandra/io/sstable/keycache/KeyCacheSupport.java:40-93` |
| `CacheService.KeyCacheSerializer` | key cache metadata、entry serialize/deserialize 和 missing SSTable skip 逻辑。见 `src/java/org/apache/cassandra/service/CacheService.java:425-529` |
| `IndexComponent` | SAI V1 on-disk component 枚举和 component type 生成。见 `src/java/org/apache/cassandra/index/sai/disk/format/IndexComponent.java:31-132` |
| `V1OnDiskFormat` | SAI V1 component set、completion marker 判断、component validation、writer factory 和 open file 数。见 `src/java/org/apache/cassandra/index/sai/disk/v1/V1OnDiskFormat.java:57-173`、`src/java/org/apache/cassandra/index/sai/disk/v1/V1OnDiskFormat.java:263-292` |
| `SSTableComponentsWriter` | SAI per-SSTable row-to-token、row-to-partition、partition/clustering key block writer。见 `src/java/org/apache/cassandra/index/sai/disk/v1/SSTableComponentsWriter.java:38-128` |
| `SSTableIndexWriter` | SAI compaction/rebuild per-column writer，收集 term + primary key + row id 并 flush segment metadata/completion marker。见 `src/java/org/apache/cassandra/index/sai/disk/v1/SSTableIndexWriter.java:46-160` |
| `SegmentBuilder` | SAI segment 内存结构，literal/numeric 用 trie buffer，vector 用 on-heap graph，flush 成 segment metadata。见 `src/java/org/apache/cassandra/index/sai/disk/v1/segment/SegmentBuilder.java:37-165` |
| `StorageAttachedIndexBuildingSupport` | SAI build task supplier，非 full rebuild 时跳过已有 per-column complete marker 的 SSTable。见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndexBuildingSupport.java:36-70` |
| `StorageAttachedIndexBuilder` | SAI SSTable 扫描 builder，负责 per-SSTable lock、per-index component build、component registration 和 view update。见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndexBuilder.java:60-120`、`src/java/org/apache/cassandra/index/sai/StorageAttachedIndexBuilder.java:131-235` |
| `SecondaryIndexManager` | index lifecycle、queryability/writability、full rebuild 和 SSTable-added incremental build 管理。见 `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:100-137`、`src/java/org/apache/cassandra/index/SecondaryIndexManager.java:381-429` |
| `CollatedViewIndexBuilder` | legacy hidden-table index rebuild，逐 base partition 读取并调用 indexer。见 `src/java/org/apache/cassandra/index/internal/CollatedViewIndexBuilder.java:38-116` |
| `ViewBuilder` | MV build coordinator，加载 status、拆分 local ranges、提交 `ViewBuilderTask`、更新 distributed status。见 `src/java/org/apache/cassandra/db/view/ViewBuilder.java:57-225` |
| `ViewBuilderTask` | 单 range MV build task，从 SSTable canonical set 迭代 key、读 base row、生成 view mutation。见 `src/java/org/apache/cassandra/db/view/ViewBuilderTask.java:66-195` |

## 核心接口

- `SSTableFormat.KeyCacheValueSerializer`：BigTable format 的 key cache value skip/serialize/deserialize contract，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigFormat.java:270-290`。
- `KeyCacheSupport.getCachedPosition()` / `cacheKey()`：读/写 `AbstractRowIndexEntry`，并断言 cached entry format 与 reader format 一致，见 `src/java/org/apache/cassandra/io/sstable/keycache/KeyCacheSupport.java:60-87`。
- `Index.IndexBuildingSupport.getIndexBuildTask()`：`SecondaryIndexManager` 以此把不同 index implementation 分组构建；默认实现返回 `CollatedViewIndexBuilder`，SAI override 返回 `StorageAttachedIndexBuilder`，见 `src/java/org/apache/cassandra/index/Index.java:184-224`、`src/java/org/apache/cassandra/index/sai/StorageAttachedIndexBuildingSupport.java:39-70`。
- `SecondaryIndexBuilder.build()`：CompactionManager 的 index build executor 执行该方法，并用 compaction holder 提供进度/停止信号，见 `src/java/org/apache/cassandra/db/compaction/CompactionManager.java:1898-1926`。
- `PerSSTableIndexWriter` / `PerColumnIndexWriter` / `SegmentWriter`：SAI writer 层的三段 contract；`SegmentWriter.writeCompleteSegment()` 将 sorted term/postings 写入总体 SSTable component files，见 `src/java/org/apache/cassandra/index/sai/disk/v1/segment/SegmentWriter.java:26-42`。
- `ViewBuilderTask.call()`：MV build 的 compaction task contract，返回 range 内已构建 key 数，并在停止/中断时通过 compaction exception 暴露状态，见 `src/java/org/apache/cassandra/db/view/ViewBuilderTask.java:121-195`。

## 核心数据结构

### key cache

| 数据 | 结构 |
|---|---|
| key | `KeyCacheKey(tableMetadata, descriptor, keyBytes)`，由 reader metadata、SSTable descriptor 和 partition key bytes 组成，见 `src/java/org/apache/cassandra/io/sstable/keycache/KeyCacheSupport.java:46-55`。 |
| value | `AbstractRowIndexEntry` / BigTable `RowIndexEntry`，通过 `serializeForCache()` 保存，BigTable serializer 见 `src/java/org/apache/cassandra/io/sstable/format/big/BigFormat.java:270-290`。 |
| metadata | 每个 saved SSTable 写入 CFS、format name、version、descriptor id；恢复时对 live readers 建 `(id, version, format)` map，见 `src/java/org/apache/cassandra/service/CacheService.java:431-481`。 |
| deletion cleanup | 删除 BigTable SSTable 时，如开启 keycache-on-delete 清理，会遍历 key cache 并移除 descriptor 匹配的 entry，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigFormat.java:245-263`。 |

### SAI V1 components

| 范围 | components | 说明 |
|---|---|---|
| skinny per-SSTable | `GroupComplete`、`GroupMeta`、`RowToToken`、`RowToPartition`、`PartitionKeyBlocks`、`PartitionKeyBlockOffsets` | 无 clustering 的 row mapping；open files 为 4，见 `src/java/org/apache/cassandra/index/sai/disk/v1/V1OnDiskFormat.java:61-78`、`src/java/org/apache/cassandra/index/sai/disk/v1/V1OnDiskFormat.java:263-283`。 |
| wide per-SSTable | skinny set + `PartitionToSize`、`ClusteringKeyBlocks`、`ClusteringKeyBlockOffsets` | 有 clustering 的 row mapping；open files 为 6，见 `src/java/org/apache/cassandra/index/sai/disk/v1/V1OnDiskFormat.java:69-78`、`src/java/org/apache/cassandra/index/sai/disk/v1/SSTableComponentsWriter.java:54-84`。 |
| literal per-column | `ColumnComplete`、`Meta`、`TermsData`、`PostingLists` | Terms dictionary + postings；literal writer 写 trie terms 和 postings offsets，见 `src/java/org/apache/cassandra/index/sai/disk/v1/V1OnDiskFormat.java:80-84`、`src/java/org/apache/cassandra/index/sai/disk/v1/trie/LiteralIndexWriter.java:38-90`。 |
| numeric per-column | `ColumnComplete`、`Meta`、`BalancedTree`、`PostingLists` | Balanced tree + auxiliary postings；numeric writer 写 tree attributes 和 postings metadata，见 `src/java/org/apache/cassandra/index/sai/disk/v1/V1OnDiskFormat.java:85-89`、`src/java/org/apache/cassandra/index/sai/disk/v1/bbtree/NumericIndexWriter.java:41-165`。 |
| vector per-column | `ColumnComplete`、`Meta`、`CompressedVectors`、`TermsData`、`PostingLists` | On-heap graph flush 写 compressed vectors/terms/postings；vector postings 存 node ordinal -> row id 和 row id -> ordinal 映射，见 `src/java/org/apache/cassandra/index/sai/disk/v1/V1OnDiskFormat.java:91-96`、`src/java/org/apache/cassandra/index/sai/disk/v1/segment/SegmentBuilder.java:109-135`、`src/java/org/apache/cassandra/index/sai/disk/v1/vector/VectorPostingsWriter.java:34-111`。 |

### MV build status

| 表 | 列与语义 |
|---|---|
| `system.view_builds_in_progress` | `keyspace_name`、`view_name`、`start_token`、`end_token`、`last_token`、`keys_built`，primary key 是 `((keyspace_name), view_name, start_token, end_token)`；用于本地 checkpoint，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:411-421`。 |
| `system.built_views` | `finishViewBuildStatus()` 先写 built view，再删除 in-progress rows 并 flush，避免失败后从头重建，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:695-705`。 |
| `system_distributed.view_build_status` | `keyspace_name`、`view_name`、`host_id`、`status`，用于跨节点 `STARTED`/`SUCCESS` 状态，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:165-173`、`src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:379-398`。 |

## 生命周期

Key cache hit：

```text
BigTableReader.getPosition(key, EQ)
  -> min/max key skip
  -> Bloom filter skip
  -> KeyCacheSupport.getCachedPosition(decoratedKey)
     -> KeyCache.get(KeyCacheKey)
  -> if cached RowIndexEntry format matches:
       return cached RowIndexEntry
  -> else indexSummary.binarySearch()
  -> primary index scan
```

Key cache save/load：

```text
CacheService.saveCaches()
  -> keyCache.submitWrite(keysToSave)
  -> KeyCacheSerializer.serializeMetadata()
     -> CFS + SSTable format + version + descriptor id
  -> KeyCacheSerializer.serialize()
     -> key bytes + RowIndexEntry.serializeForCache()

CacheService startup load
  -> KeyCacheSerializer.deserializeMetadata()
     -> map live readers by SSTable id/version/format
  -> deserialize()
     -> skip missing/disabled reader entries
     -> reader.deserializeKeyCacheValue()
     -> reader.getCacheKey(key)
```

SAI rebuild：

```text
nodetool rebuild_index ks table idx...
  -> NodeProbe.rebuildIndex()
  -> StorageService.rebuildSecondaryIndex()
  -> ColumnFamilyStore.rebuildSecondaryIndex()
  -> SecondaryIndexManager.rebuildIndexesBlocking()
  -> IndexBuildingSupport.getIndexBuildTask()
     -> legacy: CollatedViewIndexBuilder
     -> SAI: StorageAttachedIndexBuilder
  -> CompactionManager.submitIndexBuild()
```

MV build：

```text
View.startBuild()
  -> ViewBuilder.start()
  -> SystemDistributedKeyspace.startViewBuild()
  -> baseCfs.forceBlockingFlush(VIEW_BUILD_STARTED)
  -> load system.view_builds_in_progress
  -> split local ranges
  -> CompactionManager.submitViewBuilder(ViewBuilderTask)
  -> ViewBuilderTask reads base rows and emits view mutations
  -> SystemKeyspace.updateViewBuildStatus()
  -> SystemKeyspace.finishViewBuildStatus()
  -> SystemDistributedKeyspace.successfulViewBuild()
```

## 调用链

- BigTable key-cache branch：Bloom miss returns null; key cache hit calls `notifySelected(KEY_CACHE_HIT)` and returns cached `RowIndexEntry`; cache miss proceeds to index summary,见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:255-282`。
- key-cache deserialize skip：if reader is missing or key cache disabled, serializer skips value with format-specific serializer and returns null,见 `src/java/org/apache/cassandra/service/CacheService.java:496-529`。
- SAI initialization：startup validates existing components; if all live SSTables are indexed, index is made queryable and initial build is skipped; otherwise `startInitialBuild()` runs,见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndex.java:330-359`。
- SAI initial build：interrupts compactions, flushes memtables, finds non-indexed SSTables, groups by size and submits build groups to compaction manager,见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndex.java:864-908`。
- SAI full/manual rebuild：`StorageAttachedIndexBuildingSupport` drops index SSTables and, unless full rebuild, filters out SSTables already having complete per-column components,见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndexBuildingSupport.java:55-70`。
- SAI builder scan：`StorageAttachedIndexBuilder` refs SSTable, opens data reader, optionally writes per-SSTable files, deletes old per-column files, iterates keys, seeks into data, passes rows to index writer, then registers components and refreshes the SAI view,见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndexBuilder.java:131-198`、`src/java/org/apache/cassandra/index/sai/StorageAttachedIndexBuilder.java:281-324`。
- legacy index build：`CassandraIndex.buildBlocking()` flushes base table, references canonical SSTables, builds via `CollatedViewIndexBuilder`, waits, then flushes hidden index CFS,见 `src/java/org/apache/cassandra/index/internal/CassandraIndex.java:688-716`。
- incremental SSTable-attached build：streaming/import callers use `buildSSTableAttachedIndexesBlocking()`; it builds SAI for specified SSTables without updating built/queryable status and lets failure cascade to the containing operation,见 `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:528-586`。
- SSTable-added notification：non-memtable SSTables trigger non-SSTable-attached index build for legacy indexes; memtable flush SSTables are already indexed through the write/flush observer path,见 `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:1824-1839`。
- MV status read：`viewbuildstatus` calls `NodeProbe.getViewBuildStatuses()`, which maps `system_distributed.view_build_status` host id rows to endpoints and returns `UNKNOWN` for missing hosts,见 `src/java/org/apache/cassandra/tools/nodetool/ViewBuildStatus.java:63-85`、`src/java/org/apache/cassandra/service/StorageService.java:6246-6270`。

## 配置项

| 配置项 | 作用 |
|---|---|
| `key_cache_size` / `key_cache_save_period` | key cache 容量和保存周期；auto 容量为 heap 5% 与 100MiB 的较小值，见 `src/java/org/apache/cassandra/config/Config.java:467-470`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:814-828`。 |
| `concurrent_index_builders` | index build executor 并发；StorageService setter 同步更新 DatabaseDescriptor 和 CompactionManager，见 `src/java/org/apache/cassandra/config/Config.java:350`、`src/java/org/apache/cassandra/service/StorageService.java:1989-2002`、`src/java/org/apache/cassandra/db/compaction/CompactionManager.java:2154-2159`。 |
| `sai_sstable_indexes_per_query_warn_threshold` / `fail_threshold` | SAI 查询引用 SSTable index 数 guardrail，默认 warn 32、fail -1，见 `src/java/org/apache/cassandra/config/Config.java:939-940`、`conf/cassandra.yaml:2240-2243`。 |
| `concurrent_materialized_view_builders` | MV build executor 并发，默认 1；StorageService setter 更新 CompactionManager view build executor，见 `src/java/org/apache/cassandra/config/Config.java:346`、`src/java/org/apache/cassandra/service/StorageService.java:2031-2042`。 |
| `materialized_views_enabled` | MV 创建总开关，默认 false，见 `src/java/org/apache/cassandra/config/Config.java:596`、`conf/cassandra.yaml:1981`。 |
| `materialized_views_on_repair_enabled` | repair 是否处理 MV 数据，默认 true；与 auto-repair MV repair setting 组合时会阻止 incremental auto-repair，见 `src/java/org/apache/cassandra/config/Config.java:600`、`src/java/org/apache/cassandra/service/AutoRepairService.java:85-99`。 |
| `sai_segment_write_buffer_space_mb` | SAI segment build 全局 memory limiter 来源，见 `src/java/org/apache/cassandra/index/sai/disk/v1/V1OnDiskFormat.java:98-113`。 |

## Metrics

- Key cache 继续使用 `CacheMetrics` 和 virtual `caches` 表；第二轮关键是 BigTable reader 通过 listener 区分 `KEY_CACHE_HIT` 与 `INDEX_ENTRY_FOUND`，相关测试见 `test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java:600-784`。
- SAI V1 build 暴露 global gauges：`SegmentBufferSpaceUsedBytes`、`SegmentBufferSpaceLimitBytes`、`ColumnIndexBuildsInProgress`，见 `src/java/org/apache/cassandra/index/sai/disk/v1/V1OnDiskFormat.java:115-125`。
- SAI table state metrics 暴露 `DiskUsedBytes`、`DiskPercentageOfBaseTable`、`TotalIndexCount`、`TotalQueryableIndexCount`、`TotalIndexBuildsInProgress`，见 `src/java/org/apache/cassandra/index/sai/metrics/TableStateMetrics.java:27-45`。
- SAI per-index metrics 包含 memtable write latency、memtable/compaction flush counters、segments per compaction、SSTable cell count、disk/file cache bytes，见 `src/java/org/apache/cassandra/index/sai/metrics/IndexMetrics.java:29-61`。
- MV 关键指标仍是 base table `viewLockAcquireTime` 和 `viewReadTime`；前者在 view lock acquire 后更新，后者在读旧 base row 后更新，见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:155-168`、`src/java/org/apache/cassandra/db/Keyspace.java:616-624`、`src/java/org/apache/cassandra/db/view/TableViews.java:160-168`。

## 日志

- key cache serializer 在 value 反序列化失败时记录 descriptor/reader 位置，见 `src/java/org/apache/cassandra/service/CacheService.java:518-529`。
- SAI flush observer 创建失败会把表上所有 SAI 标记 non-queryable，需要 rebuild，见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndexGroup.java:203-218`。
- SAI initial build 会记录停止 compaction、提交并行 initial builds、无法更新 view 的错误，见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndex.java:873-908`、`src/java/org/apache/cassandra/index/sai/StorageAttachedIndexBuilder.java:315-323`。
- MV build failure 会 5 分钟后重试；distributed status 更新失败也会 5 分钟后重试，见 `src/java/org/apache/cassandra/db/view/ViewBuilder.java:188-224`。
- `viewbuildstatus` 在任一 host 非 SUCCESS 时输出未完成并以非 0 退出，见 `src/java/org/apache/cassandra/tools/nodetool/ViewBuildStatus.java:63-85`。

## 运维关注点

- BigTable key cache 命中适合 point read 热点；BTI 格式不使用同样的 BigTable key cache path，相关测试显式假设 BTI 不走 key cache，见 `test/unit/org/apache/cassandra/cql3/TombstonesWithIndexedSSTableTest.java:117`。
- 删除 SSTable 时是否清 key cache 取决于 `DatabaseDescriptor.shouldInvalidateKeycacheOnSSTableDeletion()`；未清理时旧 entry 仍会在 reader/descriptor 不匹配时失效或跳过，但会占用 cache 空间，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigFormat.java:245-263`。
- SAI rebuild 是 compaction executor 上的 index build，`nodetool stop INDEX_BUILD` 类操作可能中断；initial build 被中断会失败，非 initial build 可停止，见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndexBuilder.java:167-224`。
- Streaming/import 带 SAI 时应优先关注 `buildSSTableAttachedIndexesBlocking()` 失败，因为它会级联失败到包含操作，而不是只标记 index failed，见 `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:528-586`。
- MV build status 有本地 checkpoint 和 distributed host status 两层；本地完成但 distributed update 失败时会重试，`viewbuildstatus` 可能显示 UNKNOWN/SUCCESS 混合。
- auto-repair 的 MV repair 开关和全局 `materialized_views_on_repair_enabled` 同时启用时，incremental auto-repair 会被拒绝，见 `src/java/org/apache/cassandra/service/AutoRepairService.java:85-99`。

## 性能瓶颈

- key cache miss-heavy workload 会落回 index summary/primary index；SSTable 数多时每个 SSTable 都要执行 min/max、Bloom 和可能的 key cache lookup。
- key cache save/load 会遍历 saved entries 并匹配 live readers；大量旧 SSTable descriptor 或 dropped table entry 会增加启动加载扫描和 skip 成本，见 `src/java/org/apache/cassandra/service/CacheService.java:448-529`。
- SAI compaction/rebuild writer 用 segment memory limiter；多个 column indexes 并发构建时，每个 builder 的 minimum flush bytes 会按 active builder 数下降，见 `src/java/org/apache/cassandra/index/sai/disk/v1/segment/SegmentBuilder.java:49-57`、`src/java/org/apache/cassandra/index/sai/disk/v1/segment/SegmentBuilder.java:143-150`。
- SAI full rebuild 会删除并重写 per-column components；如果 per-SSTable files incomplete、full rebuild 或 checksum fail，还会重写 shared per-SSTable files，见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndexBuilder.java:257-279`。
- Legacy index rebuild 逐 partition 分页读 base table，再写 hidden index CFS；wide partition 和高 tombstone 表会拉高 rebuild 时间，见 `src/java/org/apache/cassandra/index/internal/CollatedViewIndexBuilder.java:70-116`、`src/java/org/apache/cassandra/index/SecondaryIndexManager.java:1018-1120`。
- MV build 每个 key 都执行 view select read 和 `StorageProxy.mutateMV()`；大表首次 build 的瓶颈是 base SSTable key iteration、read old row、view mutation 写入和 view build executor 并发，见 `src/java/org/apache/cassandra/db/view/ViewBuilderTask.java:92-118`。

## 常见故障

- Key cache 保存后加载不到：SSTable 不存在、format 不认识、reader 不是 `KeyCacheSupport` 或 key cache disabled 都会让 entry skip，见 `src/java/org/apache/cassandra/service/CacheService.java:448-529`。
- Key cache 统计不如预期：只有 BigTable `EQ`/`GE` 有效 row key 才查 key cache；`GT`、Bloom miss、min/max skip、wide partition 无法 cache 等都会绕开命中分支，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:255-282`。
- SAI 查询 non-queryable：flush observer 创建失败、component corruption、completion marker 缺失或 build failure 都会让 index 不可查询，需要 rebuild 或 restart validation，见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndexGroup.java:203-218`、`src/java/org/apache/cassandra/index/sai/disk/v1/V1OnDiskFormat.java:175-186`。
- `rebuild_index` 无效果：传入 index 名不存在时 `SecondaryIndexManager` 记录 no defined indexes 并返回；传 hidden index table name 时 StorageService 会转换成 index name，见 `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:391-404`、`src/java/org/apache/cassandra/service/StorageService.java:6606-6614`。
- MV build 卡住或反复重试：检查 `system.view_builds_in_progress` checkpoint、`system_distributed.view_build_status` host status、schema agreement 和 view build executor；任务失败会延迟 5 分钟重试，见 `src/java/org/apache/cassandra/db/view/ViewBuilder.java:175-224`。
- Incremental auto-repair 被拒绝：若 auto-repair config 的 MV repair enabled 且全局 `materialized_views_on_repair_enabled` 也启用，会抛配置错误，见 `src/java/org/apache/cassandra/service/AutoRepairService.java:85-99`。

## 测试用例

- Key cache：`KeyCacheCqlTest` 覆盖 CQL/2i key cache paths，`KeyCacheTest` 覆盖 key cache save/load/lost table，`SSTableReaderTest` 覆盖 key cache listener selection/skipping，见 `test/unit/org/apache/cassandra/cql3/KeyCacheCqlTest.java:237-529`、`test/unit/org/apache/cassandra/io/sstable/keycache/KeyCacheTest.java:125-360`、`test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java:600-784`。
- Legacy/rebuild：`SecondaryIndexManagerTest` 覆盖 rebuild 并发/failure/queryable writable 状态，`CassandraIndexTest` 覆盖 rebuild 后 built status，distributed `SecondaryIndexTest` 覆盖小 memtable 下 rebuild，见 `test/unit/org/apache/cassandra/index/SecondaryIndexManagerTest.java:140-260`、`test/unit/org/apache/cassandra/index/internal/CassandraIndexTest.java:592-593`、`test/distributed/org/apache/cassandra/distributed/test/SecondaryIndexTest.java:138-158`。
- SAI components/build：`IndexDescriptorTest` 覆盖 `GroupComplete` / `ColumnComplete` component detection，`StorageAttachedIndexDDLTest` 覆盖 rebuild/corruption/segment memory limiter，`NodeStartupTest` 覆盖启动时 SAI build completion，见 `test/unit/org/apache/cassandra/index/sai/disk/format/IndexDescriptorTest.java:69-82`、`test/unit/org/apache/cassandra/index/sai/cql/StorageAttachedIndexDDLTest.java:876-955`、`test/unit/org/apache/cassandra/index/sai/disk/NodeStartupTest.java:325-331`。
- SAI disk structures：`SegmentFlushTest`、`TermsReaderTest`、`NumericIndexWriterTest`、`PostingsTest`、`KeyLookupTest` 覆盖 segment/terms/balanced tree/postings/key lookup，见 `test/unit/org/apache/cassandra/index/sai/disk/v1/SegmentFlushTest.java:111-182`、`test/unit/org/apache/cassandra/index/sai/disk/v1/TermsReaderTest.java:73-97`、`test/unit/org/apache/cassandra/index/sai/disk/v1/bbtree/NumericIndexWriterTest.java:55-62`、`test/unit/org/apache/cassandra/index/sai/disk/v1/postings/PostingsTest.java:48-54`、`test/unit/org/apache/cassandra/index/sai/disk/v1/keystore/KeyLookupTest.java:60-65`。
- SAI streaming/import：`IndexStreamingTest`、`IndexStreamingFailureTest`、`ImportIndexedSSTablesTest` 覆盖 rebuild/streaming/import index component 行为，见 `test/distributed/org/apache/cassandra/distributed/test/sai/IndexStreamingTest.java:128-128`、`test/distributed/org/apache/cassandra/distributed/test/sai/IndexStreamingFailureTest.java:156-156`、`test/distributed/org/apache/cassandra/distributed/test/sai/ImportIndexedSSTablesTest.java:237-237`。
- MV build：`ViewBuilderTaskTest` 覆盖 range task 返回 built key 数，`ViewTest` 用 Byteman 阻塞/释放 view builder tasks，`ActiveCompactionsTest` 覆盖 view build compaction info，见 `test/unit/org/apache/cassandra/db/view/ViewBuilderTaskTest.java:98-99`、`test/unit/org/apache/cassandra/cql3/ViewTest.java:652-684`、`test/unit/org/apache/cassandra/db/compaction/ActiveCompactionsTest.java:181-181`。

## 待继续

- 第三轮已在 `research/module-cache-index-view-vector-import-repair.md:1` 展开 SAI vector ANN graph/compressed vectors/top-K post processor、`SSTableImporter` 与 streaming receive task 的 SAI validation/build failure matrix、ordinary MV repair write-path replay，以及 BTI/Big key-cache 差异。
- 后续优先补测试缺口：SAI vector corrupt graph/compressed-vector fault injection、nodetool `import -ri` missing-component distributed test、repair+MV 数据正确性 dtest，以及更完整 BTI/Big format 差异和旧格式迁移。
