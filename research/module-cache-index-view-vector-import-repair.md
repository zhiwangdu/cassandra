# Module: Cache Index View Vector Import Repair

## 范围

本模块补齐 Cache / Secondary Index / SAI / Materialized View 第四轮源码细节：SAI vector ANN query path、`SSTableImporter` 与 streaming receive 的 SAI component validation/build failure matrix、普通 repair 下 MV write-path replay，以及 BTI 与 BigTable key-cache 差异。

不重复第一轮/第二轮已经覆盖的 cache 类型、legacy index/SAI build 基础、MV build status 和 BigTable key cache 保存/加载格式。基础入口见 `research/module-cache-index-view.md:1`，第二轮入口见 `research/module-cache-index-view-deep-dive.md:1`。

本矩阵由 `research/tools/check-cache-index-view-coverage-drift.py` 做 source/test/gap drift check，说明见 `research/module-cache-index-view-coverage-drift-checker.md`。

## 设计目标

- 把 vector ANN 查询从 CQL `ORDER BY ... ANN OF ... LIMIT` 追到 replica local index ordering、score merge、base row materialization 和 coordinator global top-K post processor。
- 明确 SAI import/streaming 的两类路径：已有 complete components 的 checksum validation，以及缺失 components 的 incremental build。
- 将 import/streaming failure 从“build 失败”拆成 missing marker、checksum corruption、build interruption、entire SSTable validation 和 non-entire SSTable flush observer failure。
- 把 ordinary repair 与 MV 的关系落到 `StreamOperation.REPAIR`、`CassandraStreamReceiver.requiresWritePath()` 和 `materialized_views_on_repair_enabled`。
- 说明 BigTable key cache 与 BTI partition trie 的格式级差异，避免把 BigTable key-cache 运维经验误套到 BTI。

## 覆盖场景 ID

| 场景 ID | 保护内容 |
|---|---|
| `cache_index_sai_vector_ann_baseline` | SAI top-K source path、score merge、coordinator post processor 和 `VectorDistributedTest` baseline。 |
| `cache_index_sai_vector_corruption_gap` | vector corrupt graph/compressed-vector fault injection 仍缺专项测试。 |
| `cache_index_sai_import_validation_build_baseline` | default import validate/build missing SAI components、build interruption 和 checksum failure baseline。 |
| `cache_index_sai_import_require_components_gap` | nodetool `import -ri` / `--require-index-components` missing-component distributed test 缺口。 |
| `cache_index_sai_streaming_failure_baseline` | entire/non-entire streaming SAI validation/build failure baseline。 |
| `cache_index_mv_repair_write_path_baseline` | `CassandraStreamReceiver.requiresWritePath()` 的 repair/MV/CDC source 和 unit baseline。 |
| `cache_index_mv_repair_correctness_gap` | repair+MV 数据正确性 distributed 场景缺口。 |
| `cache_index_big_bti_key_cache_boundary` | BigTable key cache 与 BTI partition trie/no-key-cache 边界。 |
| `cache_index_big_bti_mixed_version_gap` | Big/BTI mixed-version/legacy-format upgrade coverage 缺口。 |
| `cache_index_existing_tests_baseline` | 本文引用的 Vector、Import、Streaming、MV condition、Big/BTI key-cache baseline 测试。 |

## 解决的问题

- SAI vector 查询不是普通 SAI range scan：`StorageAttachedIndexSearcher.search()` 在 `command.isTopK()` 为 true 时构造 ANN-only query view，生成 `ScoreOrderedResultRetriever`，再用 `VectorTopKProcessor.takeTopKThenSortByPrimaryKey()` 把 score order 转回 primary-key order，见 `src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexSearcher.java:131-170`。
- ANN local ordering 有 pure ANN 与 hybrid 两条路径：只有 ANN expression 时直接 `getTopKRows(view)`；有其他 predicates 时先 materialize/filter primary keys，再用 `orderResultsBy()` 对候选 key 排序，见 `src/java/org/apache/cassandra/index/sai/plan/Operation.java:331-340`、`src/java/org/apache/cassandra/index/sai/plan/QueryController.java:367-410`。
- On-disk vector index 用 graph + ordinals mapping + optional compressed vectors：`DiskAnn` 打开 graph、compressed vectors 和 postings/ordinals map，query 时按 exact 或 approximate score function 搜索，见 `src/java/org/apache/cassandra/index/sai/disk/v1/vector/DiskAnn.java:53-75`、`src/java/org/apache/cassandra/index/sai/disk/v1/vector/DiskAnn.java:95-120`。
- Import 与 streaming 对 SAI components 的处理不同：`SSTableImporter` 先 validate，incomplete 时 build；streaming entire SSTable validate complete components，non-entire file streaming 依赖 flush observer 生成 indexes，见 `src/java/org/apache/cassandra/db/SSTableImporter.java:222-230`、`src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:243-260`。
- Ordinary repair 会在满足条件时让 base table SSTable contents 进入正常 mutation write path，以便 MV cleanup/update 与 2i 同步执行，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:185-224`。
- BTI 不实现 BigTable key cache path：format serializer 和 `TrieIndexEntry.serializeForCache()` 都直接 assertion，reader 通过 partition trie lookup 获取 `TrieIndexEntry`，见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiFormat.java:189-193`、`src/java/org/apache/cassandra/io/sstable/format/bti/TrieIndexEntry.java:61-88`、`src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java:128-160`。

## 设计取舍

- Vector ANN 在 replica 侧先按 score 找 top-K，但 read response 仍需要按 primary-key order 交给 Cassandra read path；因此 `ScoreOrderedResultRetriever` 先拉 score-sorted keys，再读 base rows，最后 `VectorTopKProcessor` 负责排序/裁剪，见 `src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexSearcher.java:613-690`、`src/java/org/apache/cassandra/index/sai/plan/VectorTopKProcessor.java:168-210`。
- Coordinator post processor 会再次计算 global top-K，因为各 replica 返回的是局部 top-K；`StorageAttachedIndexQueryPlan.postProcessor()` 在 top-K 查询时用 `consumeSortByScoreAndTakeTopK()` 扫描 rows 并按 similarity 裁剪，见 `src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexQueryPlan.java:143-154`、`src/java/org/apache/cassandra/index/sai/plan/VectorTopKProcessor.java:53-137`。
- Vector graph 搜索和 brute force 会按 key range/cardinality 切换：小候选集走 brute force，较大候选集构造 bitset 约束 graph traversal；压缩向量存在且候选数超过 rerankK 时走 two-pass approximate + exact rerank，见 `src/java/org/apache/cassandra/index/sai/disk/v1/segment/VectorIndexSegmentSearcher.java:121-180`、`src/java/org/apache/cassandra/index/sai/disk/v1/segment/VectorIndexSegmentSearcher.java:235-280`。
- Import 的默认策略偏恢复可用性：缺少 SAI attached index components 时自动增量构建；只有显式 `nodetool import --require-index-components` 才把缺失 marker 当作 precheck failure，见 `src/java/org/apache/cassandra/db/SSTableImporter.java:89-137`、`src/java/org/apache/cassandra/tools/nodetool/Import.java:83-110`。
- Streaming entire SSTable 偏完整性：收到完整 SSTable 且不走 write path 时必须 validate attached indexes；校验异常直接 abort streaming transaction，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:249-254`、`src/java/org/apache/cassandra/index/sai/StorageAttachedIndexGroup.java:354-388`。
- MV repair replay 用 write path 换一致性：它避免 repair streaming 直接 attach base SSTable 后 view cleanup/update 缺失，但会牺牲 zero-copy/attach 性能，并可能写 CommitLog/CDC，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:202-224`。
- BTI 用 partition trie 替代 BigTable primary index summary + key cache branch；这减少 key-cache 状态耦合，但 BigTable 的 `KEY_CACHE_HIT` listener/metrics 语义不适用于 BTI，见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java:223-275`、`test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java:708-727`。

## 核心类

| 类 | 作用 |
|---|---|
| `StorageAttachedIndexSearcher` | SAI replica local searcher；top-K 时构造 ANN query view、执行 score-ordered retriever 并转 primary-key order。见 `src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexSearcher.java:131-170`、`src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexSearcher.java:613-690` |
| `VectorTopKProcessor` | 对 rows 计算 vector similarity、保留 top-K、把结果按 primary key 返回；既用于 replica retriever，也用于 coordinator post processor。见 `src/java/org/apache/cassandra/index/sai/plan/VectorTopKProcessor.java:53-137`、`src/java/org/apache/cassandra/index/sai/plan/VectorTopKProcessor.java:168-210` |
| `QueryController` | ANN/hybrid 查询在 memtable indexes 与 SSTable indexes 间生成 score iterator，并把多个 segment/SSTable iterator merge。见 `src/java/org/apache/cassandra/index/sai/plan/QueryController.java:367-410` |
| `VectorMemoryIndex` | Memtable vector index，维护 on-heap graph、primary-key bounds 和 brute-force/graph-search ordering。见 `src/java/org/apache/cassandra/index/sai/memory/VectorMemoryIndex.java:70-106`、`src/java/org/apache/cassandra/index/sai/memory/VectorMemoryIndex.java:167-241` |
| `VectorIndexSegmentSearcher` | 单 SAI segment on-disk ANN searcher；处理 token range、brute force、compressed vector rerank 和 graph traversal。见 `src/java/org/apache/cassandra/index/sai/disk/v1/segment/VectorIndexSegmentSearcher.java:68-126`、`src/java/org/apache/cassandra/index/sai/disk/v1/segment/VectorIndexSegmentSearcher.java:283-337` |
| `DiskAnn` | 打开 jvector graph、compressed vectors、ordinals map，并返回 row-id scored iterator。见 `src/java/org/apache/cassandra/index/sai/disk/v1/vector/DiskAnn.java:42-75`、`src/java/org/apache/cassandra/index/sai/disk/v1/vector/DiskAnn.java:95-120` |
| `RowIdToPrimaryKeyWithScoreIterator` | 将 segment/SSTable row id + score 转成 `PrimaryKeyWithScore`，负责关闭 primary-key map 和 row-id iterator。见 `src/java/org/apache/cassandra/index/sai/disk/v1/vector/RowIdToPrimaryKeyWithScoreIterator.java:30-68` |
| `MergePrimaryKeyWithScoreIterator` | 多 memtable/SSTable/segment score iterator 的 priority-queue merge。见 `src/java/org/apache/cassandra/index/sai/utils/MergePrimaryKeyWithScoreIterator.java:32-70` |
| `SSTableImporter` | `loadNewSSTables` / nodetool import 的核心实现，负责 verify、missing-index precheck、SAI validation/build 和 tracker attach。见 `src/java/org/apache/cassandra/db/SSTableImporter.java:76-145`、`src/java/org/apache/cassandra/db/SSTableImporter.java:222-230` |
| `SecondaryIndexManager` | SSTable-attached index validation/build facade；import/streaming 通过它让 SAI failure 级联到外层操作。见 `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:502-586` |
| `StorageAttachedIndexGroup` | SAI group-level SSTable changed handling和 per-SSTable/per-column completion marker validation。见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndexGroup.java:310-388` |
| `CassandraStreamReceiver` | Streaming receive 端；决定是否走 write path、验证 attached indexes、attach SSTables、清理 row/counter cache。见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:169-200`、`src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:235-301` |
| `StreamOperation` | 标记 repair/bulk-load 等 streaming operation 是否需要 view build。见 `src/java/org/apache/cassandra/streaming/StreamOperation.java:20-74` |
| `BigTableReader` | BigTable point lookup 的 min/max、Bloom、key cache、index summary/primary index 分支。见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:255-282` |
| `BtiTableReader` | BTI partition trie lookup reader，不走 key cache。见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java:128-160`、`src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java:223-275` |

## 核心接口

- `Index.Group.validateSSTableAttachedIndexes()`：定义 incomplete marker、checksum/corruption 和 throw/no-throw 模式；SAI group override 逐 SSTable/逐 column marker 检查，见 `src/java/org/apache/cassandra/index/Index.java:876-891`、`src/java/org/apache/cassandra/index/sai/StorageAttachedIndexGroup.java:354-388`。
- `SecondaryIndexManager.buildSSTableAttachedIndexesBlocking()`：为 import/streaming 增量构建 attached indexes，失败不改 built/queryable status，而是由外层操作失败，见 `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:528-586`。
- `MemtableOrdering.orderBy()` / `orderResultsBy()`：vector memtable ANN 查询和 hybrid query 的排序接口，`VectorMemoryIndex` 实现 full-ring/range/candidate-key 三种路径，见 `src/java/org/apache/cassandra/index/sai/memory/VectorMemoryIndex.java:167-241`。
- `SSTableIndex.orderBy()` / `orderResultsBy()`：V1 SSTable index 返回 per-segment score iterator，并由 caller merge，见 `src/java/org/apache/cassandra/index/sai/disk/SSTableIndex.java:148`、`src/java/org/apache/cassandra/index/sai/disk/v1/V1SSTableIndex.java:178-196`。
- `SSTableFormat.KeyCacheValueSerializer`：BigTable 返回 serializer，BTI 返回 assertion；这是 format 级“是否支持 key cache”的硬边界，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigFormat.java:270-290`、`src/java/org/apache/cassandra/io/sstable/format/bti/BtiFormat.java:189-193`。
- `KeyCacheSupport`：BigTable reader 支持的 key-cache contract，提供 cache key、get/put cached position 和 value deserialize；BTI reader 不实现，见 `src/java/org/apache/cassandra/io/sstable/keycache/KeyCacheSupport.java:34-96`。

## 核心数据结构

### Vector ANN

| 数据 | 结构 |
|---|---|
| query vector | `Expression` 中 ANN lower value 的 float vector；reader 会 duplicate/decompose 后传给 memtable/SSTable vector index，见 `src/java/org/apache/cassandra/index/sai/disk/v1/segment/VectorIndexSegmentSearcher.java:121-125`。 |
| graph | `DiskAnn` 使用 `CachingGraphIndex` + `OnDiskGraphIndex` 打开 `TermsData` graph；memtable 用 `OnHeapGraph<PrimaryKey>`，见 `src/java/org/apache/cassandra/index/sai/disk/v1/vector/DiskAnn.java:53-61`、`src/java/org/apache/cassandra/index/sai/memory/VectorMemoryIndex.java:70-85`。 |
| compressed vectors | `CompressedVectors` 可选存在；brute-force two-pass 先 approximate score，再 full-resolution rerank，见 `src/java/org/apache/cassandra/index/sai/disk/v1/vector/DiskAnn.java:62-70`、`src/java/org/apache/cassandra/index/sai/disk/v1/segment/VectorIndexSegmentSearcher.java:244-280`。 |
| postings / ordinals | vector postings 写 node ordinal -> row id 与 row id -> ordinal 两个方向；query 用 ordinals map 忽略 deleted ordinals 并输出 row ids，见 `src/java/org/apache/cassandra/index/sai/disk/v1/vector/VectorPostingsWriter.java:34-111`、`src/java/org/apache/cassandra/index/sai/disk/v1/vector/DiskAnn.java:116-120`。 |
| score result | `RowIdWithScore` -> `PrimaryKeyWithScore`，再由 `MergePrimaryKeyWithScoreIterator` merge score order，见 `src/java/org/apache/cassandra/index/sai/disk/v1/vector/RowIdToPrimaryKeyWithScoreIterator.java:54-68`、`src/java/org/apache/cassandra/index/sai/utils/MergePrimaryKeyWithScoreIterator.java:39-62`。 |

### Import / streaming SAI validation

| marker / component | 行为 |
|---|---|
| per-SSTable complete | 缺失时 `validateSSTableAttachedIndexes(..., false, ...)` 返回 false；`throwOnIncomplete=true` 时抛 `IllegalStateException`。见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndexGroup.java:361-383` |
| per-column complete | 每个 SAI index 逐列检查；缺失时同样返回 false 或抛 `Incomplete per-column index build`。见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndexGroup.java:367-374` |
| checksum validation | marker complete 后调用 `validatePerSSTableComponents()` / `validatePerIndexComponents()`，`validateIndexChecksum` 决定是否做 checksum。见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndexGroup.java:363-370` |
| nodetool precheck | `--require-index-components` 在 verify/copy 前检查 missing per-SSTable/per-column SAI marker，缺失即失败。见 `src/java/org/apache/cassandra/db/SSTableImporter.java:105-131` |

### MV repair replay

| 数据 | 结构 |
|---|---|
| operation flag | `StreamOperation.REPAIR("Repair", true, false)` 表示 repair streaming 需要 view build，见 `src/java/org/apache/cassandra/streaming/StreamOperation.java:20-30`。 |
| global config | `materialized_views_on_repair_enabled` 默认 true；false 时 repair streaming 行为与普通 streaming 相同，见 `src/java/org/apache/cassandra/config/Config.java:598-600`。 |
| write path replay | receiver 扫 SSTable partitions，用 `Keyspace.apply(new Mutation(PartitionUpdate.fromIterator(...)))` 重新进入 mutation path，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:202-224`。 |

### Big / BTI key lookup

| format | key lookup structure |
|---|---|
| BigTable | Bloom -> key cache -> index summary -> primary index；key cache value 是 `RowIndexEntry`。见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:255-282`、`src/java/org/apache/cassandra/io/sstable/format/big/BigFormat.java:270-290` |
| BTI | Bloom -> partition trie exact/ceiling candidate -> row-index/data-file seek；不序列化 key cache value。见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java:223-275`、`src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableWriter.java:160-218` |

## 生命周期

SAI ANN pure top-K：

```text
CQL SELECT ... ORDER BY vector ANN OF query LIMIT k
  -> SelectStatement builds ReadCommand with top-K row filter
  -> StorageAttachedIndexSearcher.search()
     -> buildAnnQueryView()
     -> QueryController.maybeTriggerGuardrails()
     -> ScoreOrderedResultRetriever
        -> Operation.buildIteratorForOrder()
           -> QueryController.getTopKRows(view)
              -> VectorMemoryIndex.orderBy()
              -> V1SSTableIndex.orderBy()
                 -> Segment.orderBy()
                 -> VectorIndexSegmentSearcher.orderBy()
                    -> DiskAnn.search() or brute force
              -> MergePrimaryKeyWithScoreIterator
        -> readAndValidatePartition()
     -> VectorTopKProcessor.takeTopKThenSortByPrimaryKey()
  -> replica response
  -> StorageAttachedIndexQueryPlan.postProcessor()
     -> VectorTopKProcessor.consumeSortByScoreAndTakeTopK()
```

SAI ANN hybrid query：

```text
ANN + other indexed predicates
  -> Operation.buildIterator(controller)
     -> ordinary SAI filter tree returns candidate primary keys
  -> QueryController.getTopKRows(iterator, view)
     -> materializeKeysAndCloseSource()
     -> memtableIndex.orderResultsBy(candidateKeys)
     -> sstableIndex.orderResultsBy(candidateKeys)
     -> MergePrimaryKeyWithScoreIterator
```

Import SAI path：

```text
nodetool import / ColumnFamilyStore.loadNewSSTables()
  -> SSTableImporter.importNewSSTables()
     -> optional verify / --require-index-components precheck
     -> move/open SSTable readers
     -> validateSSTableAttachedIndexes(newSSTables, false, validateIndexChecksum)
     -> if incomplete: buildSSTableAttachedIndexesBlocking(newSSTables)
     -> Tracker.addSSTables(newSSTables)
```

Streaming receive with SAI：

```text
CassandraStreamReceiver.finished()
  -> requiresWritePath(cfs)?
     -> true: sendThroughWritePath(cfs, readers)
     -> false:
          if receivedEntireSSTable:
             validateSSTableAttachedIndexes(readers, true, true)
          finishTransaction()
          cfs.addSSTables(readers)
          invalidate row/counter cache bounds
```

Ordinary repair + MV：

```text
repair streaming session
  -> StreamOperation.REPAIR.requiresViewBuild() == true
  -> CassandraStreamReceiver.requiresWritePath()
     -> hasViews(base CFS)
     -> DatabaseDescriptor.isMaterializedViewsOnRepairEnabled()
  -> sendThroughWritePath()
     -> scan streamed SSTables
     -> PartitionUpdate.fromIterator()
     -> Keyspace.apply()
     -> normal MV update / 2i / optional CommitLog path
  -> cleanup()
     -> force flush
     -> abort/delete streamed SSTable transaction
```

BigTable vs BTI point lookup：

```text
BigTableReader.getPosition(EQ/GE)
  -> Bloom filter
  -> KeyCacheSupport.getCachedPosition()
  -> index summary / primary index

BtiTableReader.getExactPosition(EQ)
  -> min/max
  -> Bloom filter
  -> PartitionIndex.Reader.exactCandidate()
  -> row index file or data file seek
```

## 调用链

- `StorageAttachedIndexSearcher.buildAnnQueryView()` 只允许单个 ANN expression，并用 `queryController.mergeRange()` 构造 query view，见 `src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexSearcher.java:153-170`。
- `ScoreOrderedResultRetriever` 用 `Operation.buildIteratorForOrder()` 得到 score iterator，随后按 source SSTable/memtable 分组拉 base rows，并在 row 不可见时继续补 key，见 `src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexSearcher.java:631-690`。
- `VectorIndexSegmentSearcher.orderBy()` 对 full-ring 直接 graph search；对 restricted key range 先算 SSTable row-id bounds，候选少时 brute force，候选多时构建 ordinal bitset 约束 graph search，见 `src/java/org/apache/cassandra/index/sai/disk/v1/segment/VectorIndexSegmentSearcher.java:128-205`。
- `VectorIndexSegmentSearcher.orderResultsBy()` 对 hybrid candidates 先裁剪到 segment key range，再把 primary key 映射成 row id / ordinal，最后 brute force 或 bitset graph search，见 `src/java/org/apache/cassandra/index/sai/disk/v1/segment/VectorIndexSegmentSearcher.java:283-337`。
- `SSTableImporter` 的 `--require-index-components` precheck 在 copy/move 前执行；默认 import 即使缺 index marker 也可继续到 later build，见 `src/java/org/apache/cassandra/db/SSTableImporter.java:89-137`。
- `SecondaryIndexManager.buildSSTableAttachedIndexesBlocking()` 按 index build support 分组，提交 `CompactionManager.submitIndexBuild()` 并 wait futures；失败 callback 让外层 import/streaming 失败，见 `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:540-586`。
- `CassandraStreamReceiver.finished()` 在 `requiresWritePath` 为 false 且 `receivedEntireSSTable` 为 true 时 validate SAI complete components；validate 抛异常会让 streaming transaction abort，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:235-260`。
- `CassandraStreamReceiver.cleanup()` 在 write-path replay 后 force flush 并 abort streamed SSTable transaction，因为数据已经通过 mutation path 应用，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:291-301`。
- `BigTableWriter` final/early open 时按 table caching 配置设置 `KeyCache` 并转移 cached keys，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableWriter.java:168-193`。
- `BtiTableWriter.IndexWriter` 写 row-index file 与 partition-index trie，wide partition entry 存 row-index offset，narrow entry 直接在 trie 中编码 data position，见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableWriter.java:160-218`。

## 配置项

| 配置项 | 作用 |
|---|---|
| `sai_options.segment_write_buffer_size` | SAI segment writer 总内存，多个 index build 间共享；vector graph build 也受此约束。见 `conf/cassandra.yaml:1789-1799` |
| `cassandra.sai.vector_search.max_materialized_keys` | hybrid ANN 先 search 后 sort 时最多 materialize 的 primary keys，超过后切换策略。见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:467-476` |
| `cassandra.sai.vector_search.max_top_k` | vector search 最大 top-K limit，默认 1000。见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:478-479` |
| `vector_type_enabled` | 是否启用 CQL vector type，默认 true。见 `src/java/org/apache/cassandra/config/Config.java:923` |
| `vector_dimensions_warn_threshold` / `fail_threshold` | vector column dimension guardrail，默认 -1 disabled。见 `conf/cassandra.yaml:2183-2186`、`src/java/org/apache/cassandra/config/Config.java:923-925` |
| `sai_vector_term_size_warn_threshold` / `fail_threshold` | 写入 SAI vector term 的大小 guardrail，默认 16KiB/32KiB。见 `conf/cassandra.yaml:2253-2255`、`src/java/org/apache/cassandra/config/Config.java:945-946` |
| `materialized_views_on_repair_enabled` | repair streaming 是否通过 write path replay MV，默认 true。见 `src/java/org/apache/cassandra/config/Config.java:598-600`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4227-4234` |
| `nodetool import --require-index-components` | 要求待导入 SSTable 已带 complete SAI attached index components。见 `src/java/org/apache/cassandra/tools/nodetool/Import.java:83-86` |
| `nodetool import --no-index-validation` / `--quick` | 跳过 attached index checksum validation；`--quick` 会同时跳过 SSTable verify/cache invalidation/index validation。见 `src/java/org/apache/cassandra/tools/nodetool/Import.java:88-110` |
| `key_cache_size` / table `caching.keys` | 只影响 BigTable 等 `KeyCacheSupport` reader；BTI 不使用 key cache value serializer。见 `src/java/org/apache/cassandra/io/sstable/keycache/KeyCacheSupport.java:92-95`、`src/java/org/apache/cassandra/io/sstable/format/bti/BtiFormat.java:189-193` |

## Metrics

- Vector ANN 查询的成本主要反映在 SAI query metrics、referenced SSTable index guardrail、tracing 和 table read metrics；segment search 会 trace range cardinality、brute-force threshold 和 node visit expectation，见 `src/java/org/apache/cassandra/index/sai/disk/v1/segment/VectorIndexSegmentSearcher.java:154-160`、`src/java/org/apache/cassandra/index/sai/disk/v1/segment/VectorIndexSegmentSearcher.java:341-380`。
- Memtable vector hybrid path trace materialized row count、brute-force threshold、memtable graph node数和 LIMIT，见 `src/java/org/apache/cassandra/index/sai/memory/VectorMemoryIndex.java:193-208`、`src/java/org/apache/cassandra/index/sai/memory/VectorMemoryIndex.java:225-241`。
- SAI build/import/streaming failure 不只看 metrics，要结合 index queryability、CompactionManager index build task、streaming session failure 和 server logs；blocking build 的 success/failure callbacks 在 `SecondaryIndexManager` 记录，见 `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:547-586`。
- BigTable key-cache 命中会通过 reader listener 标记 `KEY_CACHE_HIT`，BTI 对同一测试期望 `INDEX_ENTRY_FOUND`，见 `test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java:708-727`。
- MV repair replay 的额外成本会落到 write/flush/commitlog/MV 相关指标；source path 中 receiver 在 write-path cleanup 时强制 flush，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:291-301`。

## 日志

- Import 入口记录 loading new SSTables、loading/building secondary indexes、done 或 failed adding SSTables，见 `src/java/org/apache/cassandra/db/SSTableImporter.java:76-80`、`src/java/org/apache/cassandra/db/SSTableImporter.java:218-243`。
- SAI incremental build 提交、失败和完成在 `SecondaryIndexManager` 记录；失败会 warning 并 fail future，见 `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:547-586`。
- Streaming receive 端在 attach SSTables 时 debug 记录 stream id、peer 和 SSTable 列表；cache invalidation 也有 debug 计数，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:258-285`。
- Vector segment search trace/debug 会记录 query expression、range rows、brute force threshold、expected/actual visited nodes 偏差，见 `src/java/org/apache/cassandra/index/sai/disk/v1/segment/VectorIndexSegmentSearcher.java:115-126`、`src/java/org/apache/cassandra/index/sai/disk/v1/segment/VectorIndexSegmentSearcher.java:341-380`。
- BTI key-cache误用会以 assertion 暴露，而不是静默降级：`BtiFormat.getKeyCacheValueSerializer()` 和 `TrieIndexEntry.serializeForCache()` 都直接抛错，见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiFormat.java:189-193`、`src/java/org/apache/cassandra/io/sstable/format/bti/TrieIndexEntry.java:61-88`。

## 运维关注点

- Vector ANN 仍有明确 warning：不推荐生产使用，且不支持高于 ONE/LOCAL_ONE 的 CL、paging、无 LIMIT、PER PARTITION LIMIT、GROUP BY、aggregation 和无 SAI index 的过滤列，见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndex.java:124-132`。
- Vector index 创建限制包括 float vector、single-dimension cosine 禁止、多 data directory 禁止；违反会在 index validate options 阶段拒绝，见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndex.java:293-305`。
- Import 大量 SSTable 且带 SAI 时，默认可能触发 blocking incremental index build；使用 `--require-index-components` 可强制要求源侧已生成完整 SAI components，使用 `--no-index-validation` 会跳过 checksum 风险自担。
- Streaming entire SSTable failure 与 non-entire file streaming failure 的根因不同：前者通常是 validate/checksum/marker 问题，后者更多是 flush observer / segment builder failure；两者都应让 repair/streaming transaction 失败并避免半导入 index。
- Repair + MV 默认走 write path，性能像重放 mutations 而不是 attach SSTables；对大修复范围要关注 write pressure、flush、view mutation 和 CDC commitlog。
- 将 `materialized_views_on_repair_enabled=false` 可恢复普通 streaming 性能，但 repair 不会 replay MV 数据；这通常只适合明确接受 MV repair 语义变化的场景。
- BigTable key cache 优化对 BTI 不生效；BTI 依赖 partition trie，排查 point read 时应看 trie/index-entry lookup，而不是 key-cache hit ratio。

## 性能瓶颈

- Vector ANN 的 pure query 会跨所有相关 memtable/SSTable/segment 做 score iterator merge；SSTable/segment 数越多，merge 和 base row materialization 越重，见 `src/java/org/apache/cassandra/index/sai/disk/v1/V1SSTableIndex.java:178-196`。
- Hybrid ANN 若候选 primary keys 不小，`materializeKeysAndCloseSource()` 和 `orderResultsBy()` 会占用内存并增加 vector comparisons；materialized key 上限由 `cassandra.sai.vector_search.max_materialized_keys` 控制，见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:467-476`。
- On-disk vector restricted range 需要 row-id bounds、ordinal bitset 和 graph traversal；小范围 brute force 会读 full vectors，较大范围 graph search 会访问节点和 postings/ordinals，见 `src/java/org/apache/cassandra/index/sai/disk/v1/segment/VectorIndexSegmentSearcher.java:128-205`。
- Import 缺 SAI components 时会在 attach 前同步增量 build；build 失败时数据不进入 tracker，吞吐取决于 compaction index build executor 和 SAI segment memory limiter，见 `src/java/org/apache/cassandra/db/SSTableImporter.java:222-230`、`src/java/org/apache/cassandra/index/SecondaryIndexManager.java:540-586`。
- MV repair replay 扫描 streamed SSTables、拆分 partition batches 并调用 mutation apply；大 partition 或大 repair range 会放大 heap/write pressure，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:202-224`。
- BTI 不支持 key cache 和 key sampling；某些 BigTable 依赖 key sample/key cache 的估算或热点优化路径在 BTI 下需要单独评估，见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java:313-319`。

## 常见故障

| 场景 | 源码行为 | 测试/缺口 |
|---|---|---|
| Vector query 无 LIMIT | 查询报 `TOPK_LIMIT_ERROR`，distributed test 覆盖 no-limit 与 paging/no-limit。见 `test/distributed/org/apache/cassandra/distributed/test/sai/VectorDistributedTest.java:138-151` | 已覆盖 |
| Vector query recall/排序异常 | memtable、single SSTable、multi-SSTable、partition restricted、token range restricted 都有 distributed recall/descending-score 断言。见 `test/distributed/org/apache/cassandra/distributed/test/sai/VectorDistributedTest.java:116-160`、`test/distributed/org/apache/cassandra/distributed/test/sai/VectorDistributedTest.java:163-200`、`test/distributed/org/apache/cassandra/distributed/test/sai/VectorDistributedTest.java:210-307` | 缺 direct corrupt graph/compressed-vector fault injection |
| Import 缺 SAI components 且未要求 `--require-index-components` | validate 返回 false，随后 blocking build missing components；成功后 add SSTables。见 `src/java/org/apache/cassandra/db/SSTableImporter.java:222-230` | `ImportIndexedSSTablesTest.testImportBuildsSSTableIndexes` 覆盖，见 `test/distributed/org/apache/cassandra/distributed/test/sai/ImportIndexedSSTablesTest.java:109-145` |
| Import build 被中断 | blocking build future failed，外层 `loadNewSSTables` 失败，base/index 查询仍为空。见 `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:563-586` | 已覆盖 `CompactionInterruptedException`，见 `test/distributed/org/apache/cassandra/distributed/test/sai/ImportIndexedSSTablesTest.java:72-107` |
| Import checksum validation 失败 | complete marker 存在但 component validation 抛 corruption，SSTable 不进入 table view。见 `src/java/org/apache/cassandra/index/sai/StorageAttachedIndexGroup.java:363-370` | 已覆盖 `CorruptIndexException`，见 `test/distributed/org/apache/cassandra/distributed/test/sai/ImportIndexedSSTablesTest.java:147-185` |
| Import `--require-index-components` 缺 marker | precheck 在 copy/move 前抛 missing SAI index error。见 `src/java/org/apache/cassandra/db/SSTableImporter.java:105-131` | 仍缺 nodetool `-ri` distributed 专项测试 |
| Streaming non-entire file SAI build failure | index 通过 flush observer/build path 写出；失败导致 repair/streaming transaction failure，SSTable 不进入 table view。见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:249-254` | 已覆盖，见 `test/distributed/org/apache/cassandra/distributed/test/sai/IndexStreamingFailureTest.java:50-64`、`test/distributed/org/apache/cassandra/distributed/test/sai/IndexStreamingFailureTest.java:102-132` |
| Streaming entire SSTable validation failure | receiver validate complete attached indexes，checksum failure aborts transaction。见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:249-254` | 已覆盖，见 `test/distributed/org/apache/cassandra/distributed/test/sai/IndexStreamingFailureTest.java:67-80`、`test/distributed/org/apache/cassandra/distributed/test/sai/IndexStreamingFailureTest.java:102-132` |
| Repair 后 MV 不一致 | 若 operation requires view build、base table has views 且 config true，则会 replay write path；若 config false 则普通 attach streaming，不负责 MV replay。见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:195-224` | `CassandraStreamReceiverTest` 覆盖 requiresWritePath 条件；仍缺数据正确性 dtest，见 `test/unit/org/apache/cassandra/db/streaming/CassandraStreamReceiverTest.java:69-152` |
| BTI key cache hit ratio 始终无意义 | BTI 不走 key cache，listener 期望 index-entry lookup；BigTable 才可能报告 `KEY_CACHE_HIT`。见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiFormat.java:189-193`、`test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java:708-727` | 已有测试区分 |

## 测试用例

- Vector ANN distributed coverage：`VectorDistributedTest` 覆盖 memtable/on-disk、paging+limit、no-limit rejection、multi-SSTable recall、partition-restricted 和 token-range restricted ANN，见 `test/distributed/org/apache/cassandra/distributed/test/sai/VectorDistributedTest.java:116-160`、`test/distributed/org/apache/cassandra/distributed/test/sai/VectorDistributedTest.java:163-200`、`test/distributed/org/apache/cassandra/distributed/test/sai/VectorDistributedTest.java:210-307`。
- Vector validation coverage：`VectorValidationTest` 覆盖多 data dirs 限制，`VectorInvalidQueryTest` / `VectorLocalTest` / `VectorUpdateDeleteTest` 覆盖 invalid query、local query 和 update/delete semantics，见 `test/distributed/org/apache/cassandra/distributed/test/sai/VectorValidationTest.java`、`test/unit/org/apache/cassandra/index/sai/cql/VectorInvalidQueryTest.java`、`test/unit/org/apache/cassandra/index/sai/cql/VectorLocalTest.java`、`test/unit/org/apache/cassandra/index/sai/cql/VectorUpdateDeleteTest.java`。
- Import coverage：`ImportIndexedSSTablesTest` 覆盖缺 components 后 build、已有 components 导入、build interruption 和 checksum validation failure，见 `test/distributed/org/apache/cassandra/distributed/test/sai/ImportIndexedSSTablesTest.java:72-185`、`test/distributed/org/apache/cassandra/distributed/test/sai/ImportIndexedSSTablesTest.java:188-228`。
- Streaming failure coverage：`IndexStreamingFailureTest` 覆盖 non-entire file streaming build failure 与 entire-file checksum validation failure，验证 repair 失败、SSTable 未进入 table view、restart 后 index 仍 queryable，见 `test/distributed/org/apache/cassandra/distributed/test/sai/IndexStreamingFailureTest.java:50-132`。
- MV repair write-path condition coverage：`CassandraStreamReceiverTest` 覆盖 repair/bulk-load、CDC、MV、config 开关对 `requiresWritePath()` 的影响，见 `test/unit/org/apache/cassandra/db/streaming/CassandraStreamReceiverTest.java:69-152`。
- Big/BTI key cache coverage：`SSTableReaderTest` 覆盖 key-cache stats/listener 行为并按 reader format 区分 BigTable 与非 BigTable；`TombstonesWithIndexedSSTableTest` 显式跳过 BTI key-cache 场景，见 `test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java:600-784`、`test/unit/org/apache/cassandra/cql3/TombstonesWithIndexedSSTableTest.java:114-118`。
