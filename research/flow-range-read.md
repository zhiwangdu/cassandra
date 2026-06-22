# Flow: Range Read

## 目标

Range read 链路解释 `SELECT` 覆盖 token range 或无法定位单 partition 时，coordinator 如何把查询拆成 token subranges，生成 range replica plans，并按动态并发批量读取、合并和修复结果。

## 文字版调用图

```text
SELECT needing partition range
  -> SelectStatement.getQuery(...)
     -> PartitionRangeReadCommand
        -> execute(consistency, state, requestTime)
           -> StorageProxy.getRangeSlice(command, CL, requestTime)
              -> partition denylist range check
              -> RangeCommands.partitions(command, CL, requestTime)
                 -> RangeCommands.rangeCommandIterator(...)
                    -> ReplicaPlanIterator(keyRange, indexPlan, keyspace, CL)
                       -> split keyRange by ring tokens
                       -> ReplicaPlans.forRangeRead(...) per subrange
                    -> estimate results per range
                    -> choose concurrencyFactor
                    -> ReplicaPlanMerger(...)
                    -> new RangeCommandIterator(...)
                 -> command.postReconciliationProcessing(rangeCommands)
                 -> command.limits().filter(...)
```

Range iterator:

```text
RangeCommandIterator.computeNext()
  -> while current batch has no more rows
     -> if no more plans, end
     -> close previous batch and update concurrency
     -> sendNextRequests()
        -> for i < concurrencyFactor
           -> next ReplicaPlan.ForRangeRead
           -> query(replicaPlan, isFirst)
              -> command.forSubRange(replicaPlan.range(), isFirst)
              -> maybe enable repaired data tracking
              -> ReplicaPlan.shared(replicaPlan)
              -> ReadRepair.create(...)
              -> DataResolver(...)
              -> ReadCallback(...)
              -> if only self contact
                 -> Stage.READ LocalReadRunnable
              -> else
                 -> for each contact
                    -> full or transient range command
                    -> MessagingService.sendWithCallback(...)
        -> StorageProxy.concatAndBlockOnRepair(concurrentQueries, readRepairs)
        -> count rows for next concurrency estimate
```

Replica:

```text
MessagingService receives RANGE_REQ
  -> ReadCommandVerbHandler.doVerb(message)
     -> PartitionRangeReadCommand.executeLocally(controller)
        -> ReadCommand.executeLocally()
           -> PartitionRangeReadCommand.queryStorage(cfs, controller)
              -> cfs.select(View.selectLive(dataRange.keyRange))
              -> memtable.partitionIterator(...)
              -> for each intersecting SSTable
                 -> sstable.partitionIterator(...)
              -> mergeLazily(...)
              -> check row cache coverage per partition
     -> send RANGE_RSP
```

Top-K special case:

```text
RangeCommands.rangeCommandIterator()
  -> if command.isTopK()
     -> ScanAllRangesCommandIterator
        -> collect all contacts from range plans
        -> ReplicaPlans.forFullRangeRead(...)
        -> send one command to every required node
        -> NoopReadRepair
```

## 关键源码锚点

| 阶段 | 文件/方法 |
|---|---|
| command 创建 | `PartitionRangeReadCommand.create()`：`src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java:86-143` |
| command 执行入口 | `PartitionRangeReadCommand.execute()`：`src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java:302-305` |
| range read timeout | `PartitionRangeReadCommand.getTimeout()`：`src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java:292-295` |
| coordinator range 入口 | `StorageProxy.getRangeSlice()`：`src/java/org/apache/cassandra/service/StorageProxy.java:2277-2294` |
| range partition iterator | `RangeCommands.partitions()`：`src/java/org/apache/cassandra/service/reads/range/RangeCommands.java:56-66` |
| range iterator 构造 | `RangeCommands.rangeCommandIterator()`：`src/java/org/apache/cassandra/service/reads/range/RangeCommands.java:68-116` |
| results/range 估算 | `RangeCommands.estimateResultsPerRange()`：`src/java/org/apache/cassandra/service/reads/range/RangeCommands.java:118-136` |
| subrange 拆分 | `ReplicaPlanIterator.getRestrictedRanges()`：`src/java/org/apache/cassandra/service/reads/range/ReplicaPlanIterator.java:87-130` |
| per subrange plan | `ReplicaPlanIterator.computeNext()`：`src/java/org/apache/cassandra/service/reads/range/ReplicaPlanIterator.java:78-85` |
| range plan 生成 | `ReplicaPlans.forRangeRead()`：`src/java/org/apache/cassandra/locator/ReplicaPlans.java:730-748` |
| range plan 合并 | `ReplicaPlanMerger.computeNext()`：`src/java/org/apache/cassandra/service/reads/range/ReplicaPlanMerger.java:45-75` |
| range batch iterator | `RangeCommandIterator.computeNext()`：`src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:101-149` |
| dynamic concurrency | `RangeCommandIterator.computeConcurrencyFactor()`：`src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:151-177` |
| subrange query | `RangeCommandIterator.query()`：`src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:188-220` |
| batch send/merge | `RangeCommandIterator.sendNextRequests()`：`src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:223-256` |
| single range response | `SingleRangeResponse.waitForResponse()`：`src/java/org/apache/cassandra/service/reads/range/SingleRangeResponse.java:31-75` |
| replica local range read | `PartitionRangeReadCommand.queryStorage()`：`src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java:312-379` |
| top-K special iterator | `ScanAllRangesCommandIterator.sendNextRequests()`：`src/java/org/apache/cassandra/service/reads/range/ScanAllRangesCommandIterator.java:74-115` |

## 一致性语义

- `ReplicaPlans.forRangeRead()` 选 contacts 时不传 `alwaysSpeculate`，并注释说明 range read 当前没有 speculation，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:730-748`。
- `ReadCallback` 对 range read 断言 `blockFor >= contacts.size()`，因为 range scan 当前不支持普通 read repair/rapid read protection，见 `src/java/org/apache/cassandra/service/reads/ReadCallback.java:78-90`。
- `RangeCommandIterator.query()` 对 full replica 发送普通 command，对 transient replica 发送 `copyAsTransientQuery()`，见 `src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:211-217`。
- `PartitionRangeReadCommand.copyAsTransientQuery()` 将 `acceptsTransient` 设置为 true，见 `src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java:244-258`。
- `SingleRangeResponse` 在迭代前调用 `handler.awaitResults()` 再 `resolver.resolve()`，见 `src/java/org/apache/cassandra/service/reads/range/SingleRangeResponse.java:53-66`。

## 配置与观测

- `range_request_timeout` 定义在 `src/java/org/apache/cassandra/config/Config.java:147-148`，模板见 `conf/cassandra.yaml:1323-1326`。
- `PartitionRangeReadCommand.getTimeout()` 使用 `DatabaseDescriptor.getRangeRpcTimeout()`，见 `src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java:292-295`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:2203-2211`。
- 最大 range 并发 subrequests 来自 system property `cassandra.max_concurrent_range_requests`，定义见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:350`，使用见 `src/java/org/apache/cassandra/service/reads/range/RangeCommands.java:47-55`。
- range repaired data tracking 配置见 `src/java/org/apache/cassandra/config/Config.java:716-722`、`conf/cassandra.yaml:1948-1953`。
- denylist range read 拒绝配置见 `src/java/org/apache/cassandra/config/Config.java:758-765`、`conf/cassandra.yaml:1438-1442`。
- `ClientRangeRequestMetrics.roundTrips` 定义见 `src/java/org/apache/cassandra/metrics/ClientRangeRequestMetrics.java:29-47`。
- `TableMetrics.rangeLatency` 与 `sstablesPerRangeReadHistogram` 定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:108-120`。

## 排查路径

1. 先确认查询为什么不是单 partition：看 CQL 是否缺少完整 partition key、是否 token/range scan、是否二级索引/SAI range query。
2. 查看 `range_request_timeout` 和 tracing 中的 “Submitting range requests...”，确认 subrange 数、并发和 rows/range 估算。
3. 如果首批 rows 不足，检查 `RangeCommandIterator.computeConcurrencyFactor()` 是否多轮提高并发，见 `src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:151-177`。
4. 如果单个 range 慢，检查对应 contacted replicas、`SSTablesPerRangeReadHistogram`、compaction backlog 和 tombstone/read size warnings。
5. 如果 range read 被拒绝，检查 partition denylist range count 和 `RangeReadRejected` meter，入口见 `src/java/org/apache/cassandra/service/StorageProxy.java:2281-2291`。
6. Top-K 查询使用 `ScanAllRangesCommandIterator`，只支持 `ONE/LOCAL_ONE` 的特殊路径，并跳过 read repair，见 `src/java/org/apache/cassandra/service/reads/range/ScanAllRangesCommandIterator.java:47-58`、`src/java/org/apache/cassandra/service/reads/range/ScanAllRangesCommandIterator.java:112-113`。

## 测试用例

- `test/unit/org/apache/cassandra/service/reads/range/RangeCommandIteratorTest.java`
- `test/unit/org/apache/cassandra/service/reads/range/RangeCommandsTest.java`
- `test/unit/org/apache/cassandra/service/reads/range/ReplicaPlanIteratorTest.java`
- `test/unit/org/apache/cassandra/service/reads/range/ReplicaPlanMergerTest.java`
- `test/unit/org/apache/cassandra/db/PartitionRangeReadTest.java`
- `test/unit/org/apache/cassandra/index/sai/cql/TokenRangeReadTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/ReadRepairRangeQueriesTest.java`
- `research/tools/check-range-read-storage-drift.py`

## 深水区

- `range_storage_data_range_contract`：`DataRange` 的 key range/clustering filter 与 `PartitionRangeReadCommand.requestedSlices` contract。
- `range_storage_paging_boundary`：`PartitionRangeQueryPager`、`DataRange.forPaging()` 和 `DataRange.Paging.forSubRange()` 的 same-partition paging 边界。
- `range_storage_subrange_state_reset`：`PartitionRangeReadCommand.forSubRange()` 对 continuation 使用 `limits().withoutState()`。
- `range_storage_replica_plan_split_merge`：`ReplicaPlanIterator` 沿 ring token 拆分 range，`ReplicaPlanMerger` 合并相邻 compatible plan。
- `range_storage_dynamic_concurrency`：`RangeCommands` 的 rows/range 估算、10% margin、`MAX_CONCURRENT_RANGE_REQUESTS` 和 `RangeCommandIterator.computeConcurrencyFactor()`。
- `range_storage_local_memtable_sstable_merge`：replica 本地 `PartitionRangeReadCommand.queryStorage()` 收集 memtable/SSTable `partitionIterator(...)` 并 `mergeLazily()`。
- `range_storage_row_cache_filter`：range lazy merge 输出后的 `checkCacheFilter()` cached partition replacement。
- `range_storage_repaired_tracking_overread`：range read repaired-data tracking 与 `ReadCommand.InputCollector` repaired merge/digest。
- `range_storage_sstable_reader_format_boundary`：Big/BTI reader 与 SkipList/ShardedSkipList/Trie memtable 的 `partitionIterator(...)` contract。
- `range_storage_metrics_observability`：`rangeLatency`、`coordinatorScanLatency`、`SSTablesPerRangeReadHistogram`、`RoundTripsPerReadHistogram`、`local_scan_latency` 和 `coordinator_scan_latency`。
- `range_storage_tests_coverage`：`RangeCommandIteratorTest`、`PartitionRangeReadTest`、`ClientRequestMetricsTest` 和 `SSTablesIteratedTest` coverage。
- 详细矩阵与缺口见 `research/module-range-read-storage-engine-matrix.md`，漂移保护见 `research/module-range-read-storage-drift-checker.md`。
