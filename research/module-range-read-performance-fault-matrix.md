# Module: Range Read Performance Fault Matrix

## 范围

本模块补齐 range read 在性能、容错和缺口测试上的专项矩阵。它不重复 `research/module-range-read-storage-engine-matrix.md` 对 `DataRange`、pager、`ReplicaPlanIterator` 和本地 storage scan 的结构性分析，而是把这些结构映射到生产可见的成本：初始 rows-per-range 估算、`cassandra.max_concurrent_range_requests` 上限、动态并发 round trips、remote/full/transient replica 请求、repaired-data tracking 读放大、row cache per-partition substitution、SSTable overlap、tombstone/read-size 阈值，以及当前测试覆盖缺口。

## 场景矩阵

| 场景 ID | 源码/测试锚点 | 设计语义 |
|---|---|---|
| `range_perf_initial_concurrency_estimate` | `src/java/org/apache/cassandra/service/reads/range/RangeCommands.java:45-136`、`test/unit/org/apache/cassandra/service/reads/range/RangeCommandsTest.java:111-184` | 初始并发由 `estimateResultsPerRange()` 估算，按 token 数和 RF 归一化，并扣除 10% margin。 |
| `range_perf_max_concurrent_guardrail` | `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:350`、`src/java/org/apache/cassandra/service/reads/range/RangeCommands.java:54-96`、`test/unit/org/apache/cassandra/service/reads/range/RangeCommandsTest.java:53-108` | `cassandra.max_concurrent_range_requests` 防止 vnode 数大时一次 range read 产生过多 subrequest，单测只覆盖上限计算，不覆盖 distributed 运行时。 |
| `range_perf_dynamic_concurrency_roundtrips` | `src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:64-177`、`test/unit/org/apache/cassandra/service/reads/range/RangeCommandIteratorTest.java:83-156`、`test/unit/org/apache/cassandra/metrics/ClientRequestMetricsTest.java:169-179` | 后续批次按 `liveReturned/rangesQueried` 重新计算并发，`RangeSlice.RoundTripsPerReadHistogram` 记录批次数。 |
| `range_perf_remote_full_transient_contacts` | `src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:188-222` | local self replica 走 `Stage.READ`，remote replica 发送 `RANGE_REQ`；transient replica 使用 `copyAsTransientQuery(replica)`，full replica 才携带 repaired tracking message flag。 |
| `range_perf_repaired_tracking_overread` | `src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:194-215`、`src/java/org/apache/cassandra/db/ReadCommand.java:916-1045`、`test/distributed/org/apache/cassandra/distributed/test/RepairDigestTrackingTest.java:83-357` | range read 可打开 repaired-data tracking；本地 `InputCollector` 会独立 merge repaired SSTable 并为 digest 额外消费 post-limit partitions。 |
| `range_perf_row_cache_substitution` | `src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java:403-439`、`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1916-1942`、`test/unit/org/apache/cassandra/db/RowCacheTest.java:404-462` | range path 没有入口 cache hit 快路径，但 lazy merge 输出的每个 partition 可由 cached partition 替换；已有 unit range row-cache 覆盖，缺少多 partition distributed/focused substitution 场景。 |
| `range_perf_sstable_overlap_density` | `src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java:313-365`、`src/java/org/apache/cassandra/metrics/TableMetrics.java:113-117`、`test/unit/org/apache/cassandra/cql3/validation/miscellaneous/SSTablesIteratedTest.java:57-70`、`test/unit/org/apache/cassandra/cql3/validation/miscellaneous/SSTablesIteratedTest.java:1828-1838` | selected SSTable 越多，scanner/merge/tombstone 成本越高；`SSTablesPerRangeReadHistogram` 可观测 token range 下的 overlap。 |
| `range_perf_tombstone_read_size_thresholds` | `src/java/org/apache/cassandra/db/ReadCommand.java:525-742`、`src/java/org/apache/cassandra/config/Config.java:526-535`、`conf/cassandra.yaml:1814-2029`、`test/distributed/org/apache/cassandra/distributed/test/ReadRepairTest.java:272-459` | range local read 复用 tombstone warning/failure 与 local read size tracking；已有 tombstone/read-repair correctness dtest，缺少 tombstone density 性能矩阵。 |
| `range_perf_denylist_rejection` | `src/java/org/apache/cassandra/service/StorageProxy.java:2277-2293`、`src/java/org/apache/cassandra/config/Config.java:758-765` | range read 在 coordinator 入口受 partition denylist range check 拦截，命中后直接抛 `InvalidRequestException`。 |
| `range_perf_existing_tests_baseline` | `RangeCommandsTest`、`RangeCommandIteratorTest`、`ClientRequestMetricsTest`、`SSTablesIteratedTest`、`RepairDigestTrackingTest`、`RowCacheTest`、`ReadRepairTest` | 当前测试基线分散覆盖估算、动态并发、metrics、SSTable overlap、repaired tracking、row cache 和 tombstone correctness。 |
| `range_perf_distributed_fault_gap` | `research/tools/check-range-read-performance-drift.py` negative scan over `test/distributed` | 当前没有一个 distributed test 同时覆盖大量 vnode、多 remote replica、repaired range tracking、range round-trip/SSTable metrics 或 max-concurrency control。 |

## 设计目标

- 在大 vnode 数和大 token range 下限制 coordinator fan-out，同时仍能逐批推进 range read。
- 用 rows-per-range 估算给第一批请求一个合理起点，再让 `RangeCommandIterator` 根据真实返回行数调整并发。
- 保持 full/transient replica 语义：full replica 可参与 repaired-data tracking，transient replica 只返回其拥有的数据子集。
- 将本地 scan 的 tombstone、read-size、latency、SSTable iterated 和 repaired tracking 统一放在 `ReadCommand.executeLocally()` wrapper 内。
- 让运维可以用 `RoundTripsPerReadHistogram`、`coordinator_scan_latency`、`local_scan_latency` 和 `SSTablesPerRangeReadHistogram` 判断瓶颈在 coordinator 批次、remote wait 还是 local scanner。

## 解决的问题

- Range read 的用户范围可能覆盖很多 vnode。`RangeCommands.rangeCommandIterator()` 先取得 `replicaPlans.size()`，再用 `MAX_CONCURRENT_RANGE_REQUESTS` 限制初始并发，见 `src/java/org/apache/cassandra/service/reads/range/RangeCommands.java:82-96`。
- 估算行数可能来自二级索引或表级 limits。`RangeCommands.estimateResultsPerRange()` 在 index plan 存在时使用 `index.getEstimatedResultRows()`，否则使用 `command.limits().estimateTotalResults(cfs)`，见 `src/java/org/apache/cassandra/service/reads/range/RangeCommands.java:125-135`。
- 如果第一批没有返回 live row，下一批不能继续低并发。`RangeCommandIterator.computeConcurrencyFactor()` 在 `liveReturned == 0` 时直接扩到剩余范围和 max concurrency 的较小值，见 `src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:159-177`。
- Repaired-data tracking 对 range read 不走 digest read 路径，只能让 full replica 附加 repaired data info。`RangeCommandIterator.query()` 只在 multiple full contacts 且 range tracking enabled 时设置 `trackRepairedStatus`，见 `src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:194-215`。
- 本地 scanner 成本不是 coordinator 能直接预测的。`PartitionRangeReadCommand.queryStorage()` 会为 intersecting SSTable 打开 `partitionIterator()` 并在 close 时更新 `SSTablesPerRangeReadHistogram`，见 `src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java:330-365`。

## 设计取舍

- 初始并发依赖均匀分布假设。源码注释明确 `estimateResultsPerRange()` 假设 ranges 和 queried data 均匀分布，热点 token、宽分区、SAI/2i 估计偏差和 tombstone 都会打破这个假设。
- `cassandra.max_concurrent_range_requests` 是 JVM system property，而不是 yaml 动态配置；它适合作为上限保险，不适合作为每表 workload 调度器。
- 动态并发按 rows/range 调整，能减少 limit query 的多余请求，但遇到 tombstone-heavy 或 empty ranges 时会倾向扩大并发，可能把 local scan 成本集中放大。
- Row cache substitution 放在 lazy merge 输出之后，避免把 range read 变成 N 个单分区 lookup，但无法提前跳过 memtable/SSTable view selection。
- Repaired-data tracking 提高不一致诊断能力，但 range read 默认关闭，因为范围查询不使用 digest read，开启后所有 range read 都会承担额外 tracking 成本。

## 核心类

| 类 | 作用 |
|---|---|
| `RangeCommands` | 计算 initial concurrency、读取 `cassandra.max_concurrent_range_requests`、估算 rows/range。 |
| `RangeCommandIterator` | 分批发送 range subrequest、跟踪 `rangesQueried`、`batchesRequested`、`liveReturned` 并记录 `RangeSlice` metrics。 |
| `PartitionRangeReadCommand` | Replica 本地 scan、SSTable overlap 选择、row cache substitution 和 per-table range metrics 更新。 |
| `ReadCommand` | 本地 read wrapper，承载 tombstone/read-size metrics、purgeable tombstone 过滤和 repaired tracking iterator merge。 |
| `ColumnFamilyStore` | row cache coverage 判断和 live view selection。 |
| `TableMetrics` / `ClientRangeRequestMetrics` | range local/coordinator latency、SSTables-per-range-read 和 round-trip histogram。 |
| `StorageProxy` | range read coordinator 入口和 denylist range rejection。 |

## 核心接口

- `RangeCommands.rangeCommandIterator(PartitionRangeReadCommand, ConsistencyLevel, RequestTime)`：range read coordinator iterator 构造入口。
- `RangeCommands.estimateResultsPerRange(PartitionRangeReadCommand, Keyspace)`：initial concurrency 的 rows-per-range 估算。
- `RangeCommandIterator.computeConcurrencyFactor(...)`：后续 batch 的并发调整函数。
- `ReadCommand.copyAsTransientQuery(Replica)`：remote transient replica 的 range query copy。
- `ColumnFamilyStore.isFilterFullyCoveredBy(...)`：row cache substitution 的 coverage gate。
- `TableMetrics.updateSSTableIteratedInRangeRead(int)`：本地 range scanner overlap 观测入口。

## 核心数据结构

- `ReplicaPlan.ForRangeRead`：一个 token subrange 的 contacts、full/transient replica、blockFor 和 vnode count。
- `RangeCommandIterator.rangesQueried`：已提交的 vnode/subrange 数，包含 merged plan 的 `vnodeCount()`。
- `RangeCommandIterator.batchesRequested`：一次 range read 的 coordinator round trips。
- `RangeCommandIterator.liveReturned`：已返回 live row 计数，用于动态并发。
- `ReadCommand.InputCollector.repairedIters` / `unrepairedIters`：repaired tracking 下本地 iterator 的成本拆分。
- `CachedPartition`：range lazy merge 输出 partition 的可替换缓存实体。

## 生命周期

```text
Coordinator range read
  -> RangeCommands.rangeCommandIterator(...)
     -> ReplicaPlanIterator.size()
     -> maxConcurrencyFactor = min(replicaPlans.size, MAX_CONCURRENT_RANGE_REQUESTS)
     -> estimateResultsPerRange(command, keyspace)
        -> command.indexQueryPlan()?.getEstimatedResultRows()
        -> command.limits().estimateTotalResults(cfs)
        -> divide by DatabaseDescriptor.getNumTokens()
        -> divide by replication factor allReplicas
     -> subtract CONCURRENT_SUBREQUESTS_MARGIN
     -> initial concurrencyFactor
  -> RangeCommandIterator.computeNext()
     -> sendNextRequests()
        -> command.forSubRange(replicaPlan.range, isFirst)
        -> local Stage.READ or remote MessagingService RANGE_REQ
        -> transient replica uses copyAsTransientQuery(replica)
     -> StorageProxy.concatAndBlockOnRepair(...)
     -> update liveReturned
     -> computeConcurrencyFactor(...)
  -> close()
     -> RangeSlice latency
     -> RangeSlice.RoundTripsPerReadHistogram
     -> table coordinatorScanLatency
```

Replica local cost path:

```text
PartitionRangeReadCommand.executeLocally(...)
  -> ReadCommand.executeLocally(...)
     -> withQuerySizeTracking(...)
     -> withoutPurgeableTombstones(...)
     -> withMetricsRecording(...)
     -> queryStorage(...)
        -> cfs.select(View.selectLive(dataRange.keyRange))
        -> memtable.partitionIterator(...)
        -> if intersects(sstable):
           -> sstable.partitionIterator(...)
           -> selectedSSTablesCnt++
        -> InputCollector.finalizeIterators(...)
           -> repairedDataInfo.prepare/finalize when tracking
        -> mergeLazily(...)
        -> checkCacheFilter(...)
     -> close iterator
        -> updateSSTableIteratedInRangeRead(selectedSSTablesCnt)
```

## 配置项

| 配置项 | 定义位置 | 影响 |
|---|---|---|
| `cassandra.max_concurrent_range_requests` | `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:350` | range read coordinator 最大并发 subrequest；默认 `availableProcessors * 10`，且至少 1。 |
| `range_request_timeout` | `src/java/org/apache/cassandra/config/Config.java:147-148`、`conf/cassandra.yaml:1326` | range request timeout，影响 remote wait 和 coordinator failure surface。 |
| `repaired_data_tracking_for_range_reads_enabled` | `src/java/org/apache/cassandra/config/Config.java:721`、`conf/cassandra.yaml:1952` | 打开 range read repaired-data tracking，默认 false。 |
| `read_thresholds_enabled` | `src/java/org/apache/cassandra/config/Config.java:526`、`conf/cassandra.yaml:2015-2029` | 允许 local/coordinator/row-index read size warning/failure 阈值生效。 |
| `local_read_size_warn_threshold` / `local_read_size_fail_threshold` | `src/java/org/apache/cassandra/config/Config.java:529-530` | range local read materialized size warning/failure。 |
| `tombstone_warn_threshold` / `tombstone_failure_threshold` | `src/java/org/apache/cassandra/config/Config.java:534-535`、`conf/cassandra.yaml:1814-1815` | range local read tombstone warning/failure。 |
| `denylist_range_reads_enabled` | `src/java/org/apache/cassandra/config/Config.java:765` | partition denylist 是否拒绝包含 denylisted key 的 range read。 |

## Metrics

- `ClientRangeRequestMetrics("RangeSlice").roundTrips`：每次 range read 的 batch 数，metric 名为 `RoundTripsPerReadHistogram`，定义见 `src/java/org/apache/cassandra/metrics/ClientRangeRequestMetrics.java:29-45`。
- `TableMetrics.coordinatorScanLatency`：coordinator 端 range scan 总耗时，`RangeCommandIterator.close()` 更新，定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:218`。
- `TableMetrics.rangeLatency`：replica 本地 range scan latency，创建见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:630`。
- `TableMetrics.sstablesPerRangeReadHistogram`：本地 range read 访问 SSTable 数，定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:113`，更新见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:890-892`。
- `tombstoneScannedHistogram`、`liveScannedHistogram` 和 local read size metrics 由 `ReadCommand.withMetricsRecording()` 与 `withQuerySizeTracking()` 更新。
- Virtual table metric 名包括 `local_scan_latency` 和 `coordinator_scan_latency`，见 `src/java/org/apache/cassandra/db/virtual/TableMetricTables.java:72-74`。

## 日志与 Trace

- `RangeCommands.rangeCommandIterator()` trace `Submitting range requests on ... ranges with a concurrency of ...`，用于确认 initial concurrency 和 rows-per-range 估算。
- `RangeCommandIterator.computeConcurrencyFactor()` 在没有 live row 时 trace `Didn't get any response rows; new concurrent requests: ...`。
- `RangeCommandIterator.sendNextRequests()` trace `Submitted ... concurrent range requests`，对应 round trip batch。
- `ReadCommand.withMetricsRecording()` 在 tombstone 超阈值时 trace/警告 `tombstone_failure_threshold` 或 `tombstone_warn_threshold`。
- `ReadCommand.withQuerySizeTracking()` 在 local read size 过大时抛 `LocalReadSizeTooLargeException`。

## 运维关注点

- `RoundTripsPerReadHistogram` 高但 `SSTablesPerRangeReadHistogram` 低：多半是 initial concurrency 低、range 数大、empty ranges 多或 max-concurrency 上限过低。
- `SSTablesPerRangeReadHistogram` 高：优先检查 compaction backlog、SSTable overlap、token range 过滤是否能 skip SSTable，以及表是否 tombstone-heavy。
- `coordinator_scan_latency` 高且 local `rangeLatency` 低：看 remote replica wait、request fan-out、consistency level 和 network/messaging queues。
- 开启 `repaired_data_tracking_for_range_reads_enabled` 后 range latency 上升：确认是否为了诊断 repaired/unrepaired inconsistency 临时开启；默认关闭是为了避免全量 range read 附带 tracking 成本。
- Row cache 对 range read 的收益只在 cached partition 覆盖当前 filter/limits 时出现；它不会消除 range local read 的 view selection。

## 性能瓶颈

- Rows-per-range 估算低估会增加 round trips；高估会放大第一批 fan-out 和 remote/local scanner 并发。
- 大量 vnode + 低 `cassandra.max_concurrent_range_requests` 会把一次 range read 切成很多 coordinator round trips。
- Tombstone-heavy ranges 可能返回 live row 很少，动态并发会扩大下一批，但本地仍要扫描大量 tombstone。
- SSTable overlap 高会让每个 subrange 打开多个 scanner，`mergeLazily()` 只能延迟 materialization，不能消除 scanner 成本。
- Repaired-data tracking 会让 repaired SSTable iterator 为 digest 额外消费 post-limit data，limit query 也可能发生读放大。

## 常见故障

- Range read timeout：同时看 `RoundTripsPerReadHistogram`、`coordinator_scan_latency`、`rangeLatency`、`SSTablesPerRangeReadHistogram`、tombstone warning 和 messaging failure/timeout。
- Range read 在空范围上仍慢：检查 empty ranges 是否导致 repeated batches；`liveReturned == 0` 分支会扩大并发，但仍受 max-concurrency 上限约束。
- Limit query 读放大：检查 repaired tracking 是否开启、SSTable overlap 是否高、以及 tombstone 是否使 live row 产出低。
- Range read 被拒绝：`StorageProxy.getRangeSlice()` 在 denylist range read enabled 时检查 denylisted key count，命中直接失败。
- Row cache 未命中或 out-of-range：查看 `ColumnFamilyStore.isFilterFullyCoveredBy(...)` 对 head filter、limits 和 cached live rows 的判断。

## 测试用例

- `test/unit/org/apache/cassandra/service/reads/range/RangeCommandsTest.java`：`tesConcurrencyFactor` 覆盖 max concurrency 上限和 0 rows/range 初始并发，`testEstimateResultsPerRange` 覆盖 RF、`num_tokens` 和 index estimate。
- `test/unit/org/apache/cassandra/service/reads/range/RangeCommandIteratorTest.java`：`testRangeQueried` 和 `testComputeConcurrencyFactor` 覆盖 vnodeCount、batch count、range merge 和动态并发。
- `test/unit/org/apache/cassandra/metrics/ClientRequestMetricsTest.java`：`testRangeRead` 覆盖 `RangeCommandIterator.rangeMetrics.roundTrips` 和 range latency 增量。
- `test/unit/org/apache/cassandra/cql3/validation/miscellaneous/SSTablesIteratedTest.java`：`executeAndCheckRangeQuery` 覆盖 `SSTablesPerRangeReadHistogram`，并用 token range 验证 0 到 4 个 SSTable overlap。
- `test/distributed/org/apache/cassandra/distributed/test/RepairDigestTrackingTest.java`：`testInconsistenciesFound`、`testRepairedReadCountNormalizationWithInitialUnderread`、`testRepairedReadCountNormalizationWithInitialOverread` 覆盖 range repaired tracking 和 overread normalization。
- `test/unit/org/apache/cassandra/db/RowCacheTest.java`：`testRowCacheRange` 覆盖 row cache range/slice、hit 和 out-of-range metrics。
- `test/distributed/org/apache/cassandra/distributed/test/ReadRepairTest.java`：range tombstone correctness 覆盖 tombstone 不应触发多余 read repair 或 resurrect purgeable tombstone。

## 缺口

- 缺少一个 distributed fault/perf test 同时覆盖大量 vnode、多 remote replica、full/transient contacts、repaired range tracking、`RoundTripsPerReadHistogram` 或 `SSTablesPerRangeReadHistogram` 观测。
- `cassandra.max_concurrent_range_requests` 目前只有 unit calculation coverage，没有 distributed 运行时验证 max concurrency 对 batches、latency 和 remote request fan-out 的影响。
- Rows-per-range estimate 缺少 skewed token、wide partition、index estimate 偏差和 empty range 的性能矩阵。
- Tombstone density/read-size threshold 缺少 range 专项性能矩阵；现有 dtest 主要验证 read repair correctness。
- Row cache 已有 `RowCacheTest.testRowCacheRange`，但缺少多 partition range lazy merge substitution 的 focused/distributed 场景。
