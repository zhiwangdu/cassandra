# Module: Range Read Storage Engine Matrix

## 范围

本模块补齐 Storage Engine 与读取链路之间的 range read 深水区：`PartitionRangeReadCommand` 如何携带 `DataRange` 到 coordinator，`RangeCommands` 如何把 token range 拆成多个 `ReplicaPlan.ForRangeRead`，`RangeCommandIterator` 如何按动态并发发送 subrange 请求，replica 本地又如何在 `ColumnFamilyStore.ViewFragment` 中逐个 memtable/SSTable 打开 partition iterator 并做 lazy merge。

它扩展 `research/flow-range-read.md`、`research/module-read-path.md` 和 `research/module-local-read-merge-cache-deep-dive.md`。单分区 row cache/key cache、timestamp-order names-filter 和通用 single-partition merge 仍以 `module-local-read-merge-cache-deep-dive.md` 为主；本文件只覆盖跨 partition range scan 的逐分片 storage 交互。

## 场景矩阵

| 场景 ID | 源码锚点 | 设计语义 |
|---|---|---|
| `range_storage_data_range_contract` | `src/java/org/apache/cassandra/db/DataRange.java:46-59`、`src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java:66-82` | `DataRange` 同时保存 partition key range 与 clustering filter；`PartitionRangeReadCommand` 在构造时记录 `requestedSlices`，后续用它过滤 SSTable 的 covered clustering。 |
| `range_storage_paging_boundary` | `src/java/org/apache/cassandra/service/pager/PartitionRangeQueryPager.java:77-105`、`src/java/org/apache/cassandra/db/DataRange.java:391-405` | 分页续读如果还在同一 partition 内，用 `DataRange.forPaging(...)` 只调整 start key 的 clustering filter；如果已跨 partition，则退回普通 subrange。 |
| `range_storage_subrange_state_reset` | `src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java:193-208` | 第一个 subrange 保留 limits 状态，后续 continuation 使用 `limits().withoutState()`，避免把上一段分片的 per-partition 状态误带入新的 token range。 |
| `range_storage_replica_plan_split_merge` | `src/java/org/apache/cassandra/service/reads/range/ReplicaPlanIterator.java:91-120`、`src/java/org/apache/cassandra/service/reads/range/ReplicaPlanMerger.java:46-67` | `ReplicaPlanIterator` 沿 ring token 拆分用户 range，`ReplicaPlanMerger` 再合并相邻且 replica plan 等价的 range，降低请求数。 |
| `range_storage_dynamic_concurrency` | `src/java/org/apache/cassandra/service/reads/range/RangeCommands.java:45-109`、`src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:151-177` | 初始并发由 limit、rows/range 估算和 `cassandra.max_concurrent_range_requests` 决定，后续根据已返回 rows 与已查询 range 动态调整。 |
| `range_storage_local_memtable_sstable_merge` | `src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java:313-357`、`src/java/org/apache/cassandra/db/ReadCommand.java:916-928` | Replica 本地 range scan 在一个 live view 中收集所有 memtable `partitionIterator` 和 selected SSTable `partitionIterator`，通过 `InputCollector.finalizeIterators()` 与 `mergeLazily()` 输出 partition stream。 |
| `range_storage_row_cache_filter` | `src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java:403-439`、`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1916-1934` | Range read 不走单分区 row cache 快路径，但 lazy merge 输出的每个 partition 会被 `checkCacheFilter` 用 cached partition 替换，只要 cache 能覆盖当前 filter/limits。 |
| `range_storage_repaired_tracking_overread` | `src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:188-220`、`src/java/org/apache/cassandra/db/ReadCommand.java:916-928` | range read 可开启 repaired data tracking；本地 `InputCollector` 会把 repaired SSTable 单独 merge/digest 后再接回 unrepaired stream。 |
| `range_storage_sstable_reader_format_boundary` | `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:147-149`、`src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java:462-464` | Big 与 BTI reader 都实现 range `partitionIterator`，但底层 scanner 与索引格式不同；range 层只依赖 `SSTableReader.partitionIterator(...)` contract。 |
| `range_storage_metrics_observability` | `src/java/org/apache/cassandra/metrics/TableMetrics.java:555-630`、`src/java/org/apache/cassandra/metrics/ClientRangeRequestMetrics.java:34-45`、`src/java/org/apache/cassandra/db/virtual/TableMetricTables.java:72-74` | 本地 range latency、coordinator scan latency、SSTables-per-range-read 与 round trips 共同描述 range scan 放大和 coordinator 批次数。 |
| `range_storage_tests_coverage` | `test/unit/org/apache/cassandra/service/reads/range/RangeCommandIteratorTest.java:63-133`、`test/unit/org/apache/cassandra/db/PartitionRangeReadTest.java:73-146`、`test/unit/org/apache/cassandra/cql3/validation/miscellaneous/SSTablesIteratedTest.java:57-1838` | 单元测试覆盖 range count/merge、dynamic concurrency、bounds/limits 和 SSTable 迭代 histogram；分布式 fault/perf 矩阵仍是缺口。 |

## 设计目标

- 保持 CQL 层的 token/partition range 语义和 storage engine 的 memtable/SSTable iterator contract 解耦。
- 把一个大 range 拆成可独立发送、可动态并发调节、可按 consistency level 等待的 subrange 请求。
- 在 replica 本地使用同一套 `ReadCommand.executeLocally()` wrapper，复用 index searcher、tombstone/size/latency metrics 和 repaired-data tracking。
- 只在 storage 层使用 row cache 的 per-partition substitution，不把 range scan 变成多个单分区 cache lookup。
- 让 BigTable、BTI 与 memtable 实现只暴露 `partitionIterator(...)`，range 层不直接依赖具体磁盘索引结构。

## 解决的问题

- 用户 range 可能跨越多个 vnode 和多个 replica owner。`ReplicaPlanIterator.getRestrictedRanges()` 使用 ring iterator 和 `Token.maxKeyBound()` 拆分查询范围，见 `src/java/org/apache/cassandra/service/reads/range/ReplicaPlanIterator.java:91-120`。
- 分片太细会导致请求数过多。`ReplicaPlanMerger.computeNext()` 调用 `ReplicaPlans.maybeMerge(...)` 合并相邻可兼容 plan，见 `src/java/org/apache/cassandra/service/reads/range/ReplicaPlanMerger.java:46-67`。
- 第一批 range 请求不足时不能固定低并发。`RangeCommandIterator.computeConcurrencyFactor()` 会根据 `liveReturned`、`rangesQueried` 和 limit 估算下一批并发，见 `src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:151-177`。
- 本地 scan 需要在 flush/compaction 并发下拿到一致 view。`PartitionRangeReadCommand.queryStorage()` 调用 `cfs.select(View.selectLive(dataRange().keyRange()))`，然后分别访问 `view.memtables` 与 `view.sstables`，见 `src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java:313-357`。
- lazy merge 后才知道每个 partition 是否能由 row cache 覆盖。`checkCacheFilter()` 在迭代过程中调用 `cfs.getRawCachedPartition(dk)` 与 `cfs.isFilterFullyCoveredBy(...)`，见 `src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java:403-439`。

## 设计取舍

- Range read 没有普通单分区 read repair/speculation 的同级能力；`ReadCallback` 对 range command 有 contacts/blockFor 断言，主链路见 `research/flow-range-read.md`。
- Dynamic concurrency 用 rows/range 估算换吞吐，但估算来自 token 数、limit 和 index estimate，面对热点分区、tombstone 或重叠 SSTable 时会有误差。
- `limits().withoutState()` 能隔离 subrange continuation 状态，但它要求 pager 负责精确保存 `lastReturnedKey` 和 `lastReturnedRow`。
- Range read 复用 `InputCollector` repaired-data tracking，正确性边界更统一，但会增加 repaired SSTable 的 merge/digest 成本。
- Row cache 在 range path 中只是 per-partition replacement，不能像单分区读一样在 queryStorage 入口提前跳过 memtable/SSTable view selection。

## 核心类

| 类 | 作用 |
|---|---|
| `PartitionRangeReadCommand` | Range read command、subrange copy、本地 storage scan 和 cache filter。 |
| `DataRange` | Partition key bounds 与 clustering filter 的组合，含 paging/subrange 变换。 |
| `PartitionRangeQueryPager` | range read paging state，负责 last key/row 和 remaining-in-partition。 |
| `RangeCommands` | coordinator range read 入口，构造 replica plan iterator、估算并发并包装 post-reconciliation limits。 |
| `ReplicaPlanIterator` | 按 ring token 切分 query range 并生成 `ReplicaPlan.ForRangeRead`。 |
| `ReplicaPlanMerger` | 合并相邻且 replica plan 兼容的 range。 |
| `RangeCommandIterator` | 分批发送 subrange read、阻塞等待、动态调整并发、记录 coordinator metrics。 |
| `ReadCommand.InputCollector` | 本地 memtable/SSTable iterator 收集器，处理 repaired-data digest 和 final merge。 |
| `ColumnFamilyStore.ViewFragment` | 一次本地 range scan 的 live SSTable 与 memtable 快照。 |
| `BigTableReader` / `BtiTableReader` | SSTable format 的 range scanner 入口。 |

## 核心接口

- `ReadCommand.queryStorage(ColumnFamilyStore, ReadExecutionController)`：range path 由 `PartitionRangeReadCommand.queryStorage()` 实现。
- `PartitionRangeReadQuery.nextPageReadQuery(...)`：pager 通过它产生下一页 range read command。
- `Memtable.partitionIterator(ColumnFilter, DataRange, SSTableReadsListener)`：SkipList、ShardedSkipList 和 Trie memtable 的 range iterator contract。
- `SSTableReader.partitionIterator(ColumnFilter, DataRange, SSTableReadsListener)`：Big/BTI format 的 scanner contract。
- `ReplicaPlans.forRangeRead(...)`：为每个 subrange 生成 contacts 和 consistency plan。
- `ColumnFamilyStore.isFilterFullyCoveredBy(...)`：row cache per-partition substitution 的覆盖判断。

## 核心数据结构

- `DataRange.keyRange`：range read 的 partition key bounds，可能是 token range、key bounds 或 paging bounds。
- `DataRange.clusteringIndexFilter`：range 内每个 partition 使用的 clustering slice/name filter。
- `requestedSlices`：`PartitionRangeReadCommand` 从 `DataRange` 提取的 SSTable clustering coverage 过滤依据。
- `ReplicaPlan.ForRangeRead`：一个 subrange 的 contacts、full/transient replica 和 consistency metadata。
- `RangeCommandIterator.concurrencyFactor`：下一批要发送的 subrange 数。
- `ReadCommand.InputCollector<T>`：保存 selected/unrepaired/repaired iterator，并在 finalize 时做 repaired digest merge。
- `ColumnFamilyStore.ViewFragment.sstables` / `memtables`：一次 range local read 可见的 storage view。
- `CachedPartition`：`checkCacheFilter()` 可用它替换 lazy merge 输出的同 key partition。

## 生命周期

```text
SELECT range query
  -> SelectStatement.getQuery(...)
     -> PartitionRangeReadCommand.create(...)
        -> DataRange(keyRange, clusteringIndexFilter)
        -> requestedSlices = dataRange.clusteringIndexFilter.getSlices(metadata)
     -> PartitionRangeReadCommand.execute(...)
        -> StorageProxy.getRangeSlice(...)
           -> partition denylist range check
           -> RangeCommands.partitions(...)
              -> ReplicaPlanIterator(...)
                 -> getRestrictedRanges(...)
                 -> ReplicaPlans.forRangeRead(...)
              -> RangeCommands.estimateResultsPerRange(...)
              -> ReplicaPlanMerger(...)
              -> RangeCommandIterator(...)
                 -> sendNextRequests()
                    -> command.forSubRange(...)
                    -> ReadCallback/DataResolver
                    -> local Stage.READ or MessagingService RANGE_REQ
                 -> StorageProxy.concatAndBlockOnRepair(...)
              -> command.postReconciliationProcessing(...)
              -> command.limits().filter(...)
```

Replica local path:

```text
ReadCommandVerbHandler.doVerb(RANGE_REQ)
  -> command.executionController(trackRepairedStatus)
  -> PartitionRangeReadCommand.executeLocally(controller)
     -> ReadCommand.executeLocally()
        -> optional index searcher
        -> PartitionRangeReadCommand.queryStorage(cfs, controller)
           -> cfs.select(View.selectLive(dataRange.keyRange))
           -> readCountUpdater = iteratorsForRange(view, controller)
           -> for memtable in view.memtables:
              -> memtable.partitionIterator(columnFilter, dataRange, listener)
              -> readCountUpdater.addMemtableIterator(...)
           -> for sstable in view.sstables:
              -> if requestedSlices intersects coveredClustering:
                 -> sstable.partitionIterator(columnFilter, dataRange, listener)
                 -> readCountUpdater.addSSTableIterator(...)
           -> finalizedIterators = readCountUpdater.finalizeIterators(...)
           -> UnfilteredPartitionIterators.mergeLazily(finalizedIterators)
           -> checkCacheFilter(...)
              -> maybe replace partition with cached.filter(...)
```

## 配置项

| 配置项 | 定义位置 | 影响 |
|---|---|---|
| `range_request_timeout` | `src/java/org/apache/cassandra/config/Config.java:147-148`、`conf/cassandra.yaml:1326` | range request deadline，`PartitionRangeReadCommand.getTimeout()` 读取 `DatabaseDescriptor.getRangeRpcTimeout()`。 |
| `cassandra.max_concurrent_range_requests` | `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:350` | coordinator 单次 range read 最大并发 subrequest，上限由 `RangeCommands.MAX_CONCURRENT_RANGE_REQUESTS` 使用。 |
| `repaired_data_tracking_for_range_reads_enabled` | `src/java/org/apache/cassandra/config/Config.java:721`、`conf/cassandra.yaml:1952` | 允许 range read 打开 repaired-data tracking，影响本地 repaired SSTable merge/digest。 |
| `partition_denylist_enabled` / `denylist_range_reads_enabled` | `src/java/org/apache/cassandra/config/Config.java:758-765`、`conf/cassandra.yaml:1438-1442` | coordinator 在 `StorageProxy.getRangeSlice()` 入口按 range count 拒绝 denylisted partition。 |
| 表级 `caching.rows_per_partition` | `src/java/org/apache/cassandra/schema/CachingParams.java:31-109` | 影响 `ColumnFamilyStore.isFilterFullyCoveredBy(...)` 是否允许 cached partition 替换。 |

## Metrics

- `TableMetrics.rangeLatency`：replica 本地 range scan latency，`PartitionRangeReadCommand.recordLatency()` 更新，定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:117`、创建见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:630`。
- `TableMetrics.sstablesPerRangeReadHistogram`：每个 range partition iterator 实际访问 SSTable 数，更新方法 `updateSSTableIteratedInRangeRead()` 见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:890-892`。
- `TableMetrics.coordinatorScanLatency`：coordinator 端 range scan 总耗时，`RangeCommandIterator.close()` 更新，定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:218`。
- `ClientRangeRequestMetrics.roundTrips`：每次 range read 的 batches/round trips，定义见 `src/java/org/apache/cassandra/metrics/ClientRangeRequestMetrics.java:34-45`。
- `system_views` virtual metrics `local_scan_latency` 与 `coordinator_scan_latency` 来自 `src/java/org/apache/cassandra/db/virtual/TableMetricTables.java:72-74`。

## 日志与 Trace

- `RangeCommands.rangeCommandIterator()` trace `Computing ranges to query` 和 `Submitting range requests...`，用于判断 subrange 总数、估算 rows/range 和并发。
- `RangeCommandIterator.computeNext()` 捕获 `UnavailableException`、`ReadTimeoutException`、`ReadAbortException`、`ReadFailureException` 并更新 `RangeSlice` metrics。
- 本地 tombstone warning、read size abort 和 latency recording 仍由 `ReadCommand.executeLocally()` 包装产生，见 `src/java/org/apache/cassandra/db/ReadCommand.java:426-487`。
- Row cache replacement 本身无专用 metric；需要结合 tracing、`SSTablesPerRangeReadHistogram`、row cache metrics 和 per-partition cache 配置判断。

## 运维关注点

- Range read timeout 常见根因不只是网络等待，还包括 coordinator round trips 多、subrange 数大、本地 SSTable overlap 高和 tombstone 扫描重。
- `SSTablesPerRangeReadHistogram` 高时，应同时检查 compaction backlog、表的 partition/token 分布、Big/BTI reader 格式、Bloom/index summary 和 tombstone warning。
- `cassandra.max_concurrent_range_requests` 过低会增加 round trips；过高会放大跨节点请求、disk scanner 和 coordinator merge 压力。
- Denylist range read 拒绝发生在 coordinator 入口，命中时先检查 `partition_denylist_enabled`、`denylist_range_reads_enabled` 与 denylisted key count。
- Repaired-data tracking 对排查 repaired/unrepaired 不一致有价值，但可能显著提高 range scan 的 iterator 和 digest 成本。

## 性能瓶颈

- rows/range 估算依赖 token 数和 limit，面对热点 token、宽分区和二级索引估计误差时，动态并发可能先低估再补发多批。
- Range 本地 scan 会打开每个 selected SSTable 的 partition iterator，SSTable 重叠越高，scanner、merge 和 tombstone 成本越高。
- `mergeLazily()` 降低了立即 materialize 成本，但 downstream cache replacement 和 limits filtering 仍会驱动实际读。
- Row cache replacement 只在 cached partition 覆盖当前 filter/limits 时有用；非 head filter、cache 行数不足或写入频繁失效都会退回 merge 输出。
- BTI 与 BigTable 共享上层 scanner contract，但低层索引和 key cache 行为不同，mixed-format 或升级场景需要结合 SSTable format 文档排查。

## 常见故障

- Range read 返回慢：看 `ClientRangeRequestMetrics.roundTrips`、`coordinator_scan_latency`、`rangeLatency` 和 `SSTablesPerRangeReadHistogram`，再定位是 coordinator 批次、网络 replica 还是本地 storage scan。
- Range read 被 denylist 拒绝：`StorageProxy.getRangeSlice()` 调用 `partitionDenylist.getDeniedKeysInRangeCount(...)`，超过 0 会抛出 read failure 并标记 `RangeReadRejected`。
- 分页重复或漏读：重点检查 `PartitionRangeQueryPager.nextPageReadQuery()`、`DataRange.Paging.forSubRange()` 和 `PartitionRangeReadCommand.forSubRange()` 的 bounds/limits state。
- Repaired-data tracking 下读放大：`RangeCommandIterator.query()` 打开 tracking 后，本地 `InputCollector` 会对 repaired SSTable 做额外 merge/digest。
- Row cache 看似启用但 range read 未受益：range path 不是单分区入口 cache hit，而是在 lazy merge 输出 partition 时做 substitution，覆盖条件更严格。

## 测试用例

- `test/unit/org/apache/cassandra/service/reads/range/RangeCommandIteratorTest.java`：`testRangeCountWithRangeMerge`、`testRangeQueried`、`testComputeConcurrencyFactor` 覆盖 range merge、queried range 计数和并发因子。
- `test/unit/org/apache/cassandra/db/PartitionRangeReadTest.java`：`testInclusiveBounds`、`testLimits`、`testRangeSliceInclusionExclusion` 覆盖 bounds、limits 和 range slice 包含/排除。
- `test/unit/org/apache/cassandra/metrics/ClientRequestMetricsTest.java`：`testRangeRead` 覆盖 `RangeCommandIterator.rangeMetrics.roundTrips` 与 range read latency 观测。
- `test/unit/org/apache/cassandra/cql3/validation/miscellaneous/SSTablesIteratedTest.java`：`executeAndCheckRangeQuery` 覆盖 `sstablesPerRangeReadHistogram` 与 token/range query 的 SSTable iterated 数。
- `test/unit/org/apache/cassandra/service/reads/range/RangeCommandsTest.java`、`ReplicaPlanIteratorTest.java`、`ReplicaPlanMergerTest.java`：覆盖 range command 构造、plan 拆分和 merge 边界。

## 缺口

- 缺少专门的 distributed fault test 同时覆盖大量 vnode、多 remote replica、transient/full replica 和 repaired-data tracking 的 range read。
- 缺少 rows-per-range 估算误差、`cassandra.max_concurrent_range_requests`、SSTable overlap/tombstone density 的性能矩阵。
- Row cache 已有 `test/unit/org/apache/cassandra/db/RowCacheTest.java` 的 `testRowCacheRange` unit coverage，但仍缺少多 partition range lazy merge substitution 的 focused/distributed 场景。
- Big/BTI mixed-format upgrade 或 streaming 后的 range scanner 行为仍依赖 SSTable reader 通用测试，没有 range-read 专项矩阵。
