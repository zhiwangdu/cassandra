# Flow: Secondary Index And SAI Query

## 目标

索引查询链路说明一条带 indexed `WHERE` 表达式的 SELECT 如何从 CQL statement 形成 `RowFilter`，在 coordinator 选择 `Index.QueryPlan`，再由 replica 本地 `Index.Searcher` 查询索引并回读 base table。

## 文字版调用图

```text
Client SELECT ... WHERE indexed_column = ?
  -> QueryMessage.execute(...)
     -> QueryProcessor.processStatement(...)
        -> SelectStatement.execute(...)
           -> build RowFilter / ColumnFilter / DataLimits
           -> SelectStatement.getQuery(...)
              -> StorageProxy.read(...)
                 -> ReadCommand serialized with Index.QueryPlan metadata
Replica receives READ_REQ/RANGE_REQ
  -> ReadCommandVerbHandler.doVerb(...)
     -> command.executeLocally(controller)
        -> ReadCommand.executeLocally()
           -> cfs = Keyspace.openAndGetStore(metadata)
           -> indexQueryPlan = command.indexQueryPlan()
           -> if indexQueryPlan != null:
              -> cfs.indexManager.checkQueryability(indexQueryPlan)
              -> searcher = indexQueryPlan.searcherFor(command)
              -> searcher.search(executionController)
           -> withQuerySizeTracking / cancellation / tombstone purge / metrics
           -> rowFilter = indexQueryPlan.postIndexQueryFilter()
           -> filter remaining expressions
```

Legacy local-table index：

```text
CREATE INDEX ON base(col)
  -> CreateIndexStatement.apply()
     -> IndexMetadata.fromIndexTargets(...)
     -> table metadata gains index
Schema reload / CFS reload
  -> CassandraIndex(baseCfs, indexMetadata)
     -> hidden index ColumnFamilyStore
Write
  -> SecondaryIndexManager update transaction
     -> CassandraIndex.indexerFor(...)
        -> insertRow/updateRow/removeRow
        -> write/delete index table row
Read
  -> SecondaryIndexManager.getBestIndexQueryPlanFor(rowFilter)
     -> SingletonIndexQueryPlan
     -> CassandraIndex.searcherFor(command)
     -> CassandraIndexSearcher / KeysSearcher
     -> query hidden index table
     -> decode IndexEntry
     -> fetch base table row
     -> stale entry filtering/repair
```

SAI：

```text
CREATE CUSTOM INDEX ... USING 'sai'
  -> CreateIndexStatement.apply()
  -> StorageAttachedIndex.validateOptions(...)
  -> StorageAttachedIndex.register(...)
     -> SecondaryIndexManager.registerIndex(index, StorageAttachedIndexGroup.GROUP_KEY, ...)
Write / flush
  -> StorageAttachedIndexGroup.indexerFor(...)
     -> per-index indexer insert/update live rows
     -> MemtableIndexManager.index/update(...)
  -> StorageAttachedIndexGroup.getFlushObserver(...)
     -> StorageAttachedIndexWriter creates SSTable-attached components
Read
  -> StorageAttachedIndexGroup.queryPlanFor(rowFilter)
     -> StorageAttachedIndexQueryPlan.create(...)
        -> selected indexes
        -> pre-index filter and post-index filter
  -> StorageAttachedIndexQueryPlan.searcherFor(command)
     -> StorageAttachedIndexSearcher
        -> QueryController
        -> Operation.buildIterator(queryController)
        -> memtable indexes + SSTable indexes
        -> KeyRangeIterator of PrimaryKey
        -> QueryController.queryStorage(keys, controller)
        -> FilterTree post-filter
```

## 关键源码锚点

| 阶段 | 文件/方法 |
|---|---|
| CREATE INDEX schema transform | `CreateIndexStatement.apply()`：`src/java/org/apache/cassandra/cql3/statements/schema/CreateIndexStatement.java:116-197` |
| Index 主接口 | `Index` 管理/选择/验证说明：`src/java/org/apache/cassandra/index/Index.java:71-159` |
| Index query plan 选择 | `SecondaryIndexManager.getBestIndexQueryPlanFor()`：`src/java/org/apache/cassandra/index/SecondaryIndexManager.java:1218-1275` |
| ReadCommand 保存 plan | `ReadCommand.indexQueryPlan()` / `indexSearcher()`：`src/java/org/apache/cassandra/db/ReadCommand.java:263-283` |
| 本地执行索引查询 | `ReadCommand.executeLocally()`：`src/java/org/apache/cassandra/db/ReadCommand.java:426-466` |
| 序列化后重建 query plan | `ReadCommand.Serializer.deserialize()`：`src/java/org/apache/cassandra/db/ReadCommand.java:1178-1191` |
| Range read post processing | `PartitionRangeReadCommand.postReconciliationProcessing()`：`src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java:458-468` |
| Legacy index hidden table | `CassandraIndex` 定义与 backing table：`src/java/org/apache/cassandra/index/internal/CassandraIndex.java:67-83`、`src/java/org/apache/cassandra/index/internal/CassandraIndex.java:181-190` |
| Legacy index 表达式支持 | `CassandraIndex.supportsExpression()` / `getPostIndexQueryFilter()`：`src/java/org/apache/cassandra/index/internal/CassandraIndex.java:257-287` |
| Legacy index 写入 listener | `CassandraIndex.indexerFor()`：`src/java/org/apache/cassandra/index/internal/CassandraIndex.java:341-460` |
| SAI options validation | `StorageAttachedIndex.validateOptions()`：`src/java/org/apache/cassandra/index/sai/StorageAttachedIndex.java:217-308` |
| SAI group 注册 | `StorageAttachedIndex.register()`：`src/java/org/apache/cassandra/index/sai/StorageAttachedIndex.java:311-316` |
| SAI initialization/build | `StorageAttachedIndex.getInitializationTask()`：`src/java/org/apache/cassandra/index/sai/StorageAttachedIndex.java:331-359` |
| SAI group lifecycle | `StorageAttachedIndexGroup` 构造与 tracker subscribe：`src/java/org/apache/cassandra/index/sai/StorageAttachedIndexGroup.java:89-99` |
| SAI write indexer | `StorageAttachedIndexGroup.indexerFor()`：`src/java/org/apache/cassandra/index/sai/StorageAttachedIndexGroup.java:160-194` |
| SAI flush observer | `StorageAttachedIndexGroup.getFlushObserver()`：`src/java/org/apache/cassandra/index/sai/StorageAttachedIndexGroup.java:203-218` |
| SAI query plan | `StorageAttachedIndexQueryPlan.create()`：`src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexQueryPlan.java:65-113` |
| SAI searcher | `StorageAttachedIndexSearcher.search()`：`src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexSearcher.java:131-151` |
| SAI query controller | `QueryController.getIndexQueryResults()`：`src/java/org/apache/cassandra/index/sai/plan/QueryController.java:226-320` |
| SAI base row 回读 | `QueryController.queryStorage()`：`src/java/org/apache/cassandra/index/sai/plan/QueryController.java:190-223` |
| SAI post-filter | `StorageAttachedIndexSearcher.filterPartition()`：`src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexSearcher.java:528-577` |

## Query Plan 选择

- `SecondaryIndexManager.getBestIndexQueryPlanFor()` 首先处理 custom index expression；custom expression 指定 target index 时直接取对应 group 的 plan，见 `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:1245-1256`。
- 普通表达式会遍历所有 `indexGroups`，调用 `group.queryPlanFor(rowFilter)`，收集非空 plans，见 `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:1259-1266`。
- 没有可用 plan 时记录 trace 并返回 null，见 `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:1268-1272`。
- `Index.QueryPlan.getEstimatedResultRows()` 用于排序选择更“窄”的索引；接口说明见 `src/java/org/apache/cassandra/index/Index.java:471-479`。
- SAI 的估算受 `DatabaseDescriptor.getPrioritizeSAIOverLegacyIndex()` 影响，返回 `Long.MIN_VALUE` 或 `Long.MAX_VALUE`，见 `src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexQueryPlan.java:121-125`。

## Replica 本地执行

- `ReadCommand.executeLocally()` 只在本地 replica 执行 searcher；coordinator 侧仍负责发送 data/digest requests、合并和后处理。
- 有 index plan 时先 `cfs.indexManager.checkQueryability(indexQueryPlan)`，再 `indexQueryPlan.searcherFor(this)`，见 `src/java/org/apache/cassandra/db/ReadCommand.java:433-442`。
- 索引查询返回的是 `UnfilteredPartitionIterator`，后续仍经过 size tracking、cancellation、tombstone purge 和 metrics，见 `src/java/org/apache/cassandra/db/ReadCommand.java:452-462`。
- 用过索引后，主表达式由 `postIndexQueryFilter()` 去掉，剩余表达式继续 row filter，见 `src/java/org/apache/cassandra/db/ReadCommand.java:463-466`。

## SAI 查询细节

- `StorageAttachedIndexQueryPlan.create()` 逐个表达式选择支持该 column/operator 的 SAI index，并把 IN/user-defined 等无法直接翻译的表达式留在 post filter 或拒绝非 strict 查询，见 `src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexQueryPlan.java:76-105`。
- `StorageAttachedIndexSearcher` 构造 `QueryContext` 和 `QueryController`，见 `src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexSearcher.java:100-109`。
- 普通 SAI search 用 `ResultRetriever`；ANN/top-K 用 `ScoreOrderedResultRetriever` 并由 `VectorTopKProcessor` 排序/截断，见 `src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexSearcher.java:131-151`。
- `QueryController.getIndexQueryResults()` 构建 per-expression query view，搜索 memtable indexes 和 SSTable indexes，然后用 intersection 或 union 合并 primary keys，见 `src/java/org/apache/cassandra/index/sai/plan/QueryController.java:226-320`。
- 非 strict filtering 时，repaired SSTable indexes 和 unrepaired/memtable indexes 分开处理，避免 AND 交集误删 unrepaired partial update，见 `src/java/org/apache/cassandra/index/sai/plan/QueryController.java:240-312`。
- 获得 primary keys 后，`ResultRetriever.queryStorageAndFilter()` 回读 base table 并用 `FilterTree` 验证真实行，见 `src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexSearcher.java:496-517`。

## 观测与排查

| 现象 | 重点指标/日志 | 代码依据 |
|---|---|---|
| 索引查询没有走索引 | trace `No applicable indexes found`、`ALLOW FILTERING` 行为 | `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:1268-1272` |
| 索引不可查询 | index status/queryability、SAI non-queryable 日志 | `src/java/org/apache/cassandra/index/sai/StorageAttachedIndexGroup.java:203-218` |
| SAI 查询触碰太多 SSTable indexes | `sai_sstable_indexes_per_query_warn/fail_threshold` | `src/java/org/apache/cassandra/config/Config.java:939-940` |
| SAI post-filter 慢 | SAI `TableQueryMetrics.postFilteringReadLatency` | `src/java/org/apache/cassandra/index/sai/plan/StorageAttachedIndexSearcher.java:496-517` |
| Legacy index stale entries | 回表过滤、读时修复、隐藏表 compaction | `src/java/org/apache/cassandra/index/internal/CassandraIndex.java:124-133` |
| Vector top-K 结果异常或被拒绝 | ANN/vector warning、CL/paging/LIMIT 限制 | `src/java/org/apache/cassandra/index/sai/StorageAttachedIndex.java:124-141` |

## 测试用例

- `test/unit/org/apache/cassandra/index/SecondaryIndexManagerTest.java`
- `test/unit/org/apache/cassandra/index/internal/CassandraIndexTest.java`
- `test/unit/org/apache/cassandra/cql3/validation/entities/SecondaryIndexTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/SecondaryIndexTest.java`
- `test/unit/org/apache/cassandra/index/sai/cql/StorageAttachedIndexDDLTest.java`
- `test/unit/org/apache/cassandra/index/sai/cql/QueryWriteLifecycleTest.java`
- `test/unit/org/apache/cassandra/index/sai/cql/MixedIndexImplementationsTest.java`
- `test/unit/org/apache/cassandra/index/sai/cql/MultipleColumnIndexTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/sai/StrictFilteringTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/sai/IndexAvailabilityTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/sai/IndexStreamingTest.java`
