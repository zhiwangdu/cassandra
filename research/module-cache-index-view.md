# Module: Cache, Secondary Index, SAI And Materialized View

## 范围

本模块覆盖 key/row/counter/chunk cache、legacy secondary index、SAI 和 materialized view 写入主线，重点放在读写路径如何接入这些辅助结构。

## 设计目标

本模块覆盖 Cassandra 5.0 中读写性能相关的三组派生结构：缓存、二级索引和物化视图。它们都不是数据模型的主存储路径，但会显著改变读写放大、内存占用、flush/compaction 交互和故障表现。

设计目标：

- Key cache、row cache、counter cache 和 chunk cache 分别优化 SSTable key lookup、热点分区读取、counter read-before-write 和 SSTable chunk 复用。
- Legacy secondary index 通过隐藏本地表维护倒排数据；SAI 通过 memtable/SSTable-attached index 维护更细粒度的 on-disk components。
- 查询时 `ReadCommand` 持有 `Index.QueryPlan`，replica 本地执行阶段选择 `Index.Searcher` 或普通 storage query。
- Materialized view 在 base replica 上读旧行、合成 view mutation，再通过 `StorageProxy.mutateMV()` 写入 paired view replica。
- Schema DDL、guardrails、配置开关和 metrics 必须能解释“为什么索引/MV 不可用、变慢或结果需要后过滤”。

## 解决的问题

- 缓存初始化和保存要统一纳入 JMX/配置：`CacheService` 注册 `org.apache.cassandra.db:type=Caches`，初始化三类 auto-saving cache，见 `src/java/org/apache/cassandra/service/CacheService.java:76-114`。
- Row cache 不能在每次写后返回旧分区：`ColumnFamilyStore` 写入 memtable 后调用 `invalidateCachedPartition(key)`，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1475-1480`。
- Counter 热点更新要减少本地 counter 读取：`ColumnFamilyStore.getCachedCounter()` 与 `putCachedCounter()` 读写 `CounterCacheKey`，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:2499-2510`。
- 二级索引读必须先选出可支持表达式的 query plan：`SecondaryIndexManager.getBestIndexQueryPlanFor()` 从 custom expression 或 index groups 中选择 plan，见 `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:1218-1275`。
- SAI 同时查询 memtable index 和 SSTable index，并根据 strict filtering/repaired status 选择 intersection/union，见 `src/java/org/apache/cassandra/index/sai/plan/QueryController.java:226-320`。
- MV 写入必须基于更新前后的 base row 判定 create/update/delete/switch：`ViewUpdateGenerator.updateAction()` 定义五种动作，见 `src/java/org/apache/cassandra/db/view/ViewUpdateGenerator.java:163-217`。

## 设计取舍

- Key cache 默认 auto，容量为 heap 的 5% 和 100MiB 的较小值；counter cache 默认 heap 的 2.5% 和 50MiB 的较小值，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:814-864`。Row cache 默认禁用，因为要缓存整行/整分区，配置说明见 `conf/cassandra.yaml:555-575`。
- Row cache 是表级 `caching.cacheRows()` 与全局容量的组合开关，且索引表不能使用 row cache，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:3259-3264`。
- Chunk cache 使用 file cache 配置并保留 32MiB buffer pool 空间，见 `src/java/org/apache/cassandra/cache/ChunkCache.java:46-55`；它是 SSTable chunk 级别，不等同于 row/key cache。
- Legacy index 的好处是实现简单、落到隐藏 CFS；代价是写时额外表写入和读时 stale entry 过滤，`CassandraIndex` 明确 stale index entries 会在读时识别和修复，见 `src/java/org/apache/cassandra/index/internal/CassandraIndex.java:124-133`。
- SAI 是非 singleton group：多个 SAI index 共享 `StorageAttachedIndexGroup`、query metrics、SSTable context manager，见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndexGroup.java:71-99` 和 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndexGroup.java:154-158`。
- MV 使用每个 base key/table 的 striped lock 防止并发更新生成不一致 view mutation；获取锁失败时可按 write timeout 抛 `WriteTimeoutException(WriteType.VIEW)`，见 `src/java/org/apache/cassandra/db/Keyspace.java:535-623`。

## 核心类

| 类 | 作用 |
|---|---|
| `CacheService` | 全局 cache MBean、key/row/counter cache 初始化、保存、清理和容量调整。定义见 `src/java/org/apache/cassandra/service/CacheService.java:76` |
| `AutoSavingCache` | 包装具体 cache，并支持周期保存/恢复；由 `CacheService` 初始化使用，见 `src/java/org/apache/cassandra/service/CacheService.java:129-133` |
| `KeyCacheKey` | key cache key，包含 table id、index name、SSTable descriptor 和 partition key bytes，见 `src/java/org/apache/cassandra/cache/KeyCacheKey.java:29-45` |
| `RowCacheKey` | row cache key，包含 table id/index name 与 partition key bytes，见 `src/java/org/apache/cassandra/cache/RowCacheKey.java:34-58` |
| `CounterCacheKey` | counter cache key，编码 partition key、clustering、column 和 cell path，见 `src/java/org/apache/cassandra/cache/CounterCacheKey.java:44-80` |
| `ChunkCache` | SSTable chunk cache，基于 Caffeine `LoadingCache` 和 buffer pool，见 `src/java/org/apache/cassandra/cache/ChunkCache.java:46-59` |
| `Index` | 二级索引主接口，包含管理、写入 `Indexer`、查询 `Searcher`、`Group` 和 `QueryPlan`，见 `src/java/org/apache/cassandra/index/Index.java:71-159` |
| `SecondaryIndexManager` | 每个 base CFS 的索引注册、构建、状态、query plan 选择和 write transaction 管理。定义见 `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:137` |
| `CassandraIndex` | legacy local table index，单列索引数据存储在隐藏本地表，见 `src/java/org/apache/cassandra/index/internal/CassandraIndex.java:67-83` |
| `StorageAttachedIndex` | SAI 单列索引实现，验证 options、注册 group、初始化构建、memtable/SSTable index 维护。定义见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndex.java:120` |
| `StorageAttachedIndexGroup` | SAI 多索引 group，管理 shared metrics、SSTable context、flush observer、notifications。定义见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndexGroup.java:75` |
| `StorageAttachedIndexQueryPlan` | SAI query plan，拆分 pre/post index filter，构建 searcher/top-K post processor，见 `src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexQueryPlan.java:39-63` |
| `ViewManager` | keyspace 级 view 管理、view lock、update affect 判断、reload/build/drop。定义见 `src/java/org/apache/cassandra/db/view/ViewManager.java:56` |
| `TableViews` | 单 base table 的 views 集合，读取旧行、生成 view mutations、调用 `mutateMV()`。定义见 `src/java/org/apache/cassandra/db/view/TableViews.java:52` |
| `View` | 单个 view 的定义、select/read query、filter 匹配和 liveness 规则。定义见 `src/java/org/apache/cassandra/db/view/View.java:65` |
| `ViewUpdateGenerator` | 根据 base row before/after 生成 view `PartitionUpdate`。定义见 `src/java/org/apache/cassandra/db/view/ViewUpdateGenerator.java:46` |

## 核心接口

- `IndexRegistry`：base table 的索引注册集合，索引通过它订阅写入事件并提供 query searcher，说明见 `src/java/org/apache/cassandra/index/IndexRegistry.java:52-60`。
- `Index.Indexer`：一次 partition update 的短生命周期写入监听器，方法包括 `begin()`、`insertRow()`、`updateRow()`、`removeRow()`、`finish()`，见 `src/java/org/apache/cassandra/index/Index.java:568-660`。
- `Index.Searcher`：一次 `ReadCommand` 的本地索引查询器，核心方法是 `search(ReadExecutionController)`，见 `src/java/org/apache/cassandra/index/Index.java:685-711`。
- `Index.Group`：兼容多个索引协同，提供 `queryPlanFor()`、`indexerFor()`、flush observer 和 SSTable-attached validation，见 `src/java/org/apache/cassandra/index/Index.java:728-902`。
- `Index.QueryPlan`：从 `RowFilter` 产生并随 `ReadCommand` 序列化/传递，`ReadCommand.indexQueryPlan()` 见 `src/java/org/apache/cassandra/db/ReadCommand.java:263-283`。

## 核心数据结构

- `CacheType`：`KEY_CACHE`、`ROW_CACHE`、`COUNTER_CACHE`，见 `src/java/org/apache/cassandra/service/CacheService.java:82-86`。
- `AbstractRowIndexEntry`：key cache value，指向 SSTable 中 partition 的索引入口；`KeyCacheSerializer` 负责保存 descriptor/table metadata，见 `src/java/org/apache/cassandra/service/CacheService.java:425-455`。
- `CachedPartition` / `IRowCacheEntry`：row cache value；恢复 row cache 时重新 full partition read，并用 `DataLimits.cqlLimits(rowsToCache)` 截断，见 `src/java/org/apache/cassandra/service/CacheService.java:392-421`。
- `IndexMetadata`：CREATE INDEX 生成的 schema 元数据，`CreateIndexStatement.apply()` 组装并写回 table metadata，见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateIndexStatement.java:180-197`。
- `RowFilter`：SELECT 的索引表达式来源，`StorageAttachedIndexQueryPlan.create()` 根据表达式选择 indexes 并拆分 post filter，见 `src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexQueryPlan.java:65-113`。
- `PrimaryKey` / `KeyRangeIterator`：SAI 查询先得到 primary key iterator，再按 key 回读 base storage，`QueryController.getIndexQueryResults()` 说明见 `src/java/org/apache/cassandra/index/sai/plan/QueryController.java:226-248`。
- `ViewMetadata`：CREATE MATERIALIZED VIEW 生成的 schema 对象，包含 base table id/name、select columns、where clause 和 view table metadata，见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateViewStatement.java:323-347`。
- `Mutation` / `PartitionUpdate`：MV 更新最终仍是普通 mutation；`TableViews.buildMutations()` 将 view updates 封装成 mutations，见 `src/java/org/apache/cassandra/db/view/TableViews.java:518-549`。

## 生命周期

缓存初始化：

```text
CassandraDaemon setup
  -> CacheService.instance constructor
     -> MBeanWrapper.registerMBean(...)
     -> initKeyCache()
        -> CaffeineCache.create(capacity)
        -> AutoSavingCache(..., KEY_CACHE, KeyCacheSerializer)
        -> scheduleSaving(...)
     -> initRowCache()
        -> OHCProvider or NopCacheProvider
        -> AutoSavingCache(..., ROW_CACHE, RowCacheSerializer)
     -> initCounterCache()
        -> CaffeineCache.create(capacity)
        -> AutoSavingCache(..., COUNTER_CACHE, CounterCacheSerializer)
```

索引生命周期：

```text
CREATE INDEX
  -> CreateIndexStatement.apply()
     -> Guardrails.createSecondaryIndexesEnabled
     -> validate table/keyspace/target/options
     -> IndexMetadata.fromIndexTargets(...)
     -> table.withSwapped(table.indexes.with(index))
Schema reload
  -> ColumnFamilyStore / SecondaryIndexManager create Index implementation
  -> index.register(IndexRegistry)
  -> SecondaryIndexManager.registerIndex(index, groupKey, groupSupplier)
  -> initialization/build task
Write path
  -> ColumnFamilyStore.newUpdateTransaction(...)
  -> Index.Group.indexerFor(...)
  -> Indexer insert/update/remove
Read path
  -> SelectStatement builds RowFilter
  -> SecondaryIndexManager.getBestIndexQueryPlanFor(rowFilter)
  -> ReadCommand.executeLocally()
     -> indexQueryPlan.searcherFor(command)
     -> searcher.search(executionController)
     -> postIndexQueryFilter()
```

MV 写入生命周期：

```text
Coordinator mutation
  -> StorageProxy.mutateWithTriggers(...)
     -> viewManager.updatesAffectView(mutations, true)
     -> mutateAtomically(..., updatesView)
Base replica apply
  -> Keyspace.applyInternal(mutation, makeDurable, updateIndexes, ...)
     -> viewManager.updatesAffectView(mutation, false)
     -> acquire MV locks
     -> for each PartitionUpdate:
        -> TableViews.pushViewReplicaUpdates(update, writeCommitLog, baseComplete)
           -> readExistingRowsCommand(...)
           -> command.executeLocally(...)
           -> generateViewUpdates(...)
           -> StorageProxy.mutateMV(baseKey, viewMutations, ...)
        -> base cfs write
     -> baseComplete timestamp set
```

## 调用链

- 缓存初始化：`CacheService` 构造函数初始化 key/row/counter cache，见 `src/java/org/apache/cassandra/service/CacheService.java:101-114`。
- Cache 清理：全局和按表清理分别由 `invalidate*` 方法处理，见 `src/java/org/apache/cassandra/service/CacheService.java:274-319`。
- 写入失效 row cache：`ColumnFamilyStore` memtable put 后调用 `invalidateCachedPartition(key)`，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1475-1480`。
- Chunk cache 包装 SSTable reader：`ChunkCache.maybeWrap()` 在启用时返回 `CachingRebufferer`，见 `src/java/org/apache/cassandra/cache/ChunkCache.java:188-199`。
- CREATE INDEX：`CreateIndexStatement.apply()` 校验 guardrail、SASI 开关、表/列限制并写 schema，见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateIndexStatement.java:116-197`。
- ReadCommand 本地索引查询：`ReadCommand.executeLocally()` 检查 queryability、构造 searcher、执行 search 并设置 post filter，见 `src/java/org/apache/cassandra/db/ReadCommand.java:426-466`。
- Legacy index 写入：`CassandraIndex.indexerFor()` 对 insert/update/remove 调用隐藏 index table 写删，见 `src/java/org/apache/cassandra/index/internal/CassandraIndex.java:341-460`。
- SAI 注册：`StorageAttachedIndex.register()` 注册到共享 `StorageAttachedIndexGroup.GROUP_KEY`，见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndex.java:311-316`。
- SAI 查询：`StorageAttachedIndexSearcher.search()` 返回普通 result retriever 或 ANN top-K retriever，见 `src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexSearcher.java:131-151`。
- CREATE VIEW：`CreateViewStatement.apply()` 检查 MV 开关、transient replication、where/PK/TTL 限制并添加 `ViewMetadata`，见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateViewStatement.java:113-347`。
- MV 更新生成：`TableViews.pushViewReplicaUpdates()` 读旧行、合成 mutations、调用 `StorageProxy.mutateMV()`，见 `src/java/org/apache/cassandra/db/view/TableViews.java:143-170`。
- MV replica 写入：`StorageProxy.mutateMV()` 根据 base/view token 找 paired endpoint，本地 apply 或写 batchlog/远端，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1010-1075`。

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| `key_cache_size` / `key_cache_save_period` / `key_cache_keys_to_save` | `src/java/org/apache/cassandra/config/Config.java:464-470`，模板 `conf/cassandra.yaml:510-543` | key cache 容量和保存周期 |
| `row_cache_class_name` / `row_cache_size` / `row_cache_save_period` | `src/java/org/apache/cassandra/config/Config.java:472-477`，模板 `conf/cassandra.yaml:545-579` | row cache provider、容量和保存周期 |
| `counter_cache_size` / `counter_cache_save_period` / `counter_cache_keys_to_save` | `src/java/org/apache/cassandra/config/Config.java:479-483`，模板 `conf/cassandra.yaml:581-607` | counter cache 容量和保存周期 |
| `file_cache_enabled` / `file_cache_size` | `src/java/org/apache/cassandra/config/Config.java:496-499`，模板 `conf/cassandra.yaml:740-753` | SSTable chunk cache/buffer pool |
| `concurrent_materialized_view_writes` | `src/java/org/apache/cassandra/config/Config.java:182`，模板 `conf/cassandra.yaml:726-728` | MV 写 executor 并发 |
| `concurrent_materialized_view_builders` | `src/java/org/apache/cassandra/config/Config.java:346`，模板 `conf/cassandra.yaml:1241-1242` | MV build task 并发 |
| `materialized_views_enabled` | `src/java/org/apache/cassandra/config/Config.java:595-596`，模板 `conf/cassandra.yaml:1979-1981` | 是否允许创建 MV |
| `materialized_views_on_repair_enabled` | `src/java/org/apache/cassandra/config/Config.java:598-600`，模板 `conf/cassandra.yaml:1988` | repair 是否处理 MV 数据 |
| `sasi_indexes_enabled` | `src/java/org/apache/cassandra/config/Config.java:605-606`，模板 `conf/cassandra.yaml:1992` | 是否允许 SASI |
| `secondary_indexes_enabled` | `src/java/org/apache/cassandra/config/Config.java:891`，模板 `conf/cassandra.yaml:2055-2056` | guardrail：是否允许创建二级索引 |
| `secondary_indexes_per_table_*` / `materialized_views_per_table_*` | `src/java/org/apache/cassandra/config/Config.java:869-872`，模板 `conf/cassandra.yaml:2050-2061` | 每表 index/MV 数量 guardrail |
| `sai_options` / `sai_sstable_indexes_per_query_*` / `sai_*_term_size_*` | `src/java/org/apache/cassandra/config/Config.java:804`、`src/java/org/apache/cassandra/config/Config.java:939-946`，模板 `conf/cassandra.yaml:1790-1796`、`conf/cassandra.yaml:2238-2255` | SAI 写入内存、查询引用 SSTable index 数、term size guardrails |

## Metrics

- `CacheMetrics`：cache capacity/size/entries/hits/misses/requests/hit rates，定义见 `src/java/org/apache/cassandra/metrics/CacheMetrics.java:32-89`。
- `ChunkCacheMetrics`：继承 `CacheMetrics`，额外记录 miss latency，定义见 `src/java/org/apache/cassandra/metrics/ChunkCacheMetrics.java:34-44`。
- `CachesTable`：虚拟表暴露 key/row/counter cache 行，见 `src/java/org/apache/cassandra/db/virtual/CachesTable.java:57-76`。
- `TableMetrics.rowCacheHit`、`rowCacheHitOutOfRange`：定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:165-167`，更新见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:530-537`。
- `TableMetrics.viewLockAcquireTime`、`viewReadTime`：定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:159-161`，更新见 `src/java/org/apache/cassandra/db/Keyspace.java:616-623` 和 `src/java/org/apache/cassandra/db/view/TableViews.java:167`。
- SAI `TableQueryMetrics`、`TableStateMetrics`、`IndexGroupMetrics`、`ColumnQueryMetrics`：定义见 `src/java/org/apache/cassandra/index/sai/metrics/TableQueryMetrics.java:31`、`src/java/org/apache/cassandra/index/sai/metrics/TableStateMetrics.java:27`、`src/java/org/apache/cassandra/index/sai/metrics/IndexGroupMetrics.java:26`、`src/java/org/apache/cassandra/index/sai/metrics/ColumnQueryMetrics.java:28`。

## 日志

- Cache 初始化日志：key/row/counter cache 初始化容量，见 `src/java/org/apache/cassandra/service/CacheService.java:121-143` 和 `src/java/org/apache/cassandra/service/CacheService.java:170-185`。
- Cache 保存日志：`saveCaches()` 记录提交 cache saves，见 `src/java/org/apache/cassandra/service/CacheService.java:350-357`。
- Secondary index rebuild/recovery：开始恢复时将 index 标记 writable 并强制 flush，见 `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:406-427`。
- 查询无可用索引：`getBestIndexQueryPlanFor()` trace `No applicable indexes found`，见 `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:1268-1272`。
- SAI flush observer 创建失败会将表上所有 SAI 标记 non-queryable，见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndexGroup.java:203-218`。
- ViewManager reload 在 StorageService 未初始化时不提交 build tasks，见 `src/java/org/apache/cassandra/db/view/ViewManager.java:115-130`。
- MV lock 获取失败 trace `Could not acquire MV lock`，见 `src/java/org/apache/cassandra/db/Keyspace.java:561-576`。
- `StorageProxy.mutateMV()` 在找不到 paired endpoint 且无 pending replica 时记录 range movement 相关 warn，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1052-1060`。

## 运维关注点

- Key cache 命中通常比 row cache 更稳健；row cache 默认关闭，只有热点整分区/静态行模式值得启用。
- Row cache 写失效是表级 partition key 粒度；高写入表上启用 row cache 可能造成缓存抖动。
- Counter cache 对 RF=1 可以跳过 read-before-write；RF>1 仍能缩短 lock hold，但 counter deletes + 低 `gc_grace_seconds` 时配置模板建议禁用，见 `conf/cassandra.yaml:581-593`。
- Chunk cache 是 off-heap/buffer pool 资源，需要和 OS page cache、SSTable compression chunk 大小、direct memory 一起看。
- Legacy secondary index 适合低基数/低写入压力的有限场景；高基数或宽查询容易放大隐藏表读写。
- SAI 建议关注 query guardrail：单次查询引用太多 SSTable index 时，`sai_sstable_indexes_per_query_*` 会 warn/fail。
- SAI ANN/vector 在源码中仍有生产使用 warning，限制包括 CL、paging、LIMIT、GROUP BY、aggregation 等，见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndex.java:124-132`。
- MV 默认 `materialized_views_enabled: false`，创建前要确认运维风险；base write 需要额外 read + view write，失败表现可能是 `WriteType.VIEW`。

## 性能瓶颈

- Cache 容量不足会表现为 hit rate 低、miss latency 上升和重复 SSTable seeks。
- Row cache 保存/加载比 key cache 昂贵，启动恢复可能触发真实分区读取，见 `src/java/org/apache/cassandra/service/CacheService.java:401-421`。
- Legacy index stale entry 需要读时回表和过滤，删除/TTL/compaction 延迟会增加误命中。
- SAI 查询先 materialize primary keys 再回读 base storage，`StorageAttachedIndexSearcher.queryStorageAndFilter()` 会记录 post-filter read latency，见 `src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexSearcher.java:496-517`。
- SAI 非 strict filtering 下为避免 unrepaired partial updates 误交集，会拆 repaired/unrepaired，读放大更明显，见 `src/java/org/apache/cassandra/index/sai/plan/QueryController.java:240-312`。
- MV 每次影响 view 的 base write 都要加锁、读旧行、生成 mutation，再执行 view write；`viewReadTime` 和 `viewLockAcquireTime` 是关键指标。

## 常见故障

- `Cannot find configured row cache provider class`：row cache provider 类名错误，抛出位置见 `src/java/org/apache/cassandra/service/CacheService.java:145-157`。
- Row cache 命中但 out-of-range：cache partition 不能覆盖当前 filter，会回退到 memtable/SSTable，指标更新见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:516-543`。
- CREATE INDEX 被 guardrail 拒绝：`CreateIndexStatement.apply()` 调用 `Guardrails.createSecondaryIndexesEnabled`，见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateIndexStatement.java:116-123`。
- SASI 未启用：SASI custom index 在配置关闭时抛 `SASI indexes are disabled`，见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateIndexStatement.java:51-53` 和 `src/java/org/apache/cassandra/cql3/statements/schema/CreateIndexStatement.java:121-123`。
- SAI vector index 不满足限制：非 float vector、单维 cosine、多 data directories 都会拒绝，见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndex.java:293-305`。
- CREATE MATERIALIZED VIEW 被拒绝：全局 MV 开关关闭或 keyspace 使用 transient replicas，见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateViewStatement.java:113-127`。
- MV 写超时：获取 view lock 超过 write timeout 时抛 `WriteTimeoutException(WriteType.VIEW)`，见 `src/java/org/apache/cassandra/db/Keyspace.java:561-576`。

## 测试用例

- Cache：`test/unit/org/apache/cassandra/cache/AutoSavingCacheTest.java`、`test/unit/org/apache/cassandra/cache/CacheProviderTest.java`、`test/unit/org/apache/cassandra/cql3/KeyCacheCqlTest.java`、`test/unit/org/apache/cassandra/db/RowCacheTest.java`、`test/unit/org/apache/cassandra/db/RowCacheCQLTest.java`、`test/unit/org/apache/cassandra/db/CounterCacheTest.java`、`test/unit/org/apache/cassandra/io/sstable/keycache/KeyCacheTest.java`、`test/unit/org/apache/cassandra/metrics/CacheMetricsTest.java`。
- Legacy/custom index：`test/unit/org/apache/cassandra/index/SecondaryIndexManagerTest.java`、`test/unit/org/apache/cassandra/index/CustomIndexTest.java`、`test/unit/org/apache/cassandra/index/internal/CassandraIndexTest.java`、`test/unit/org/apache/cassandra/cql3/validation/entities/SecondaryIndexTest.java`、`test/distributed/org/apache/cassandra/distributed/test/SecondaryIndexTest.java`、`test/distributed/org/apache/cassandra/distributed/test/SecondaryIndexCompactionTest.java`。
- SAI：`test/unit/org/apache/cassandra/index/sai/cql/StorageAttachedIndexDDLTest.java`、`test/unit/org/apache/cassandra/index/sai/cql/QueryWriteLifecycleTest.java`、`test/unit/org/apache/cassandra/index/sai/cql/MultipleColumnIndexTest.java`、`test/unit/org/apache/cassandra/index/sai/functional/CompactionTest.java`、`test/distributed/org/apache/cassandra/distributed/test/sai/StrictFilteringTest.java`、`test/distributed/org/apache/cassandra/distributed/test/sai/IndexAvailabilityTest.java`、`test/distributed/org/apache/cassandra/distributed/test/sai/IndexStreamingTest.java`。
- MV：`test/unit/org/apache/cassandra/cql3/ViewTest.java`、`test/unit/org/apache/cassandra/cql3/ViewSchemaTest.java`、`test/unit/org/apache/cassandra/cql3/ViewFiltering1Test.java`、`test/unit/org/apache/cassandra/cql3/ViewComplexUpdatesTest.java`、`test/unit/org/apache/cassandra/db/view/ViewBuilderTaskTest.java`、`test/unit/org/apache/cassandra/db/view/ViewUtilsTest.java`、`test/long/org/apache/cassandra/cql3/ViewLongTest.java`。

## 待继续

- Bloom filter/index summary/key cache 在 Big/BTI SSTable reader 中的命中路径已在 `module-bloom-sstable-index-deep-dive.md`、`module-cache-index-view-vector-import-repair.md` 和 `module-local-read-merge-cache-deep-dive.md` 展开。
- 单独展开 SAI on-disk format：segment、trie、balanced tree、postings、vector ANN graph。
- 单独展开 index build/rebuild、streaming/import、repair 与 compaction transaction 的交互。
- 单独展开 MV build、system_distributed view build status、repair MV 开关和 failed build 恢复。
