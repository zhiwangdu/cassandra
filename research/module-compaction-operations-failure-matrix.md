# Module: Compaction Operations Failure Matrix

## 范围

本模块补齐 compaction 的生产运行面：后台调度、限速、磁盘空间失败、任务缩小、自动 SSTable upgrade、JMX/nodetool 操作入口、全局 metrics，以及现有测试覆盖和缺口。策略如何选择 SSTable 已在 `research/module-compaction-strategies-deep-dive.md` 展开；SSTable merge/purge/write 骨架已在 `research/module-sstable-compaction.md` 和 `research/flow-compaction.md` 展开。

## 设计目标

- 后台 compaction 由 `CompactionManager.submitBackground()` 做轻量排队和 backpressure，避免同一表已经 compact 且没有空闲线程时继续堆积候选任务；入口见 `src/java/org/apache/cassandra/db/compaction/CompactionManager.java:230-258`。
- 表级策略选择由 `CompactionStrategyManager.getNextBackgroundTask()` 统一处理 repair-finished cleanup、holder 排序和 concrete strategy task 获取；见 `src/java/org/apache/cassandra/db/compaction/CompactionStrategyManager.java:192-239`。
- 单个任务在 `CompactionTask.runMayThrow()` 中执行 snapshot、fully expired SSTable 判断、磁盘空间检查、scanner/iterator/writer 循环、history/metrics 更新；主循环见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:122-300`。
- 磁盘空间不足时优先缩小 compaction scope；无法缩小时增加 `CompactionsAborted` 并抛出异常，逻辑见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:384-456`。
- `CompactionIterator` 负责把 merge 后的 partition 经过 `GarbageSkipper`、`Purger`/`PaxosPurger`、`DuplicateRowChecker`、index cleanup 和 row cache invalidation；构造 pipeline 见 `src/java/org/apache/cassandra/db/compaction/CompactionIterator.java:154-165`。
- JMX/nodetool 需要既能发起 major/user-defined/token/partition-key compaction，又能调整 throughput、auto compaction、停止任务、查看 compactionstats/history；JMX interface 见 `src/java/org/apache/cassandra/db/compaction/CompactionManagerMBean.java:27-74`，NodeProbe 入口见 `src/java/org/apache/cassandra/tools/NodeProbe.java:471-506`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1595-1644`。

## 场景矩阵

| 场景 ID | 运行语义 | 源码锚点 | 测试/缺口 |
|---|---|---|---|
| `compaction_background_scheduler_backpressure` | `submitBackground()` 在 autocompaction disabled 时 no-op；同一 CFS 正在 compact 且 executor 已满时跳过，避免队列堆积 | `src/java/org/apache/cassandra/db/compaction/CompactionManager.java:230-258` | 现有策略/任务单测覆盖 task 选择，缺少 focused executor saturation 单测 |
| `compaction_strategy_manager_repair_promotion` | background 选择先处理 pending/transient repair finished task，再按 holder estimated remaining tasks 降序选择普通任务 | `src/java/org/apache/cassandra/db/compaction/CompactionStrategyManager.java:192-239` | `test/unit/org/apache/cassandra/db/compaction/CompactionStrategyManagerTest.java:317-430` 覆盖 holder exclusivity/grouping/count buckets |
| `compaction_strategy_params_validation` | 表级 `CompactionParams` 解析 class/enabled/min/max/provide_overlapping_tombstones，禁止 threshold=0 关闭 compaction | `src/java/org/apache/cassandra/schema/CompactionParams.java:121-145`、`src/java/org/apache/cassandra/schema/CompactionParams.java:188-255` | STCS/LCS/TWCS/UCS options 单测分散在各 strategy test；缺少统一 schema-level negative matrix |
| `compaction_task_snapshot_space_reduction` | task 可在 compaction 前 snapshot；空间不足时尝试 `reduceScopeForLimitedSpace()`，否则 `incrementAborted()` 并抛异常 | `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:135-139`、`src/java/org/apache/cassandra/db/compaction/CompactionTask.java:384-456` | `test/distributed/org/apache/cassandra/distributed/test/CompactionDiskSpaceTest.java:49-110` 覆盖 no-space/recovered/shared filestore |
| `compaction_iterator_purge_index_cache` | iterator pipeline 清理 gc-able tombstone、Paxos tombstone、duplicate row，同时处理 2i compaction indexer 和 empty partition cache invalidation | `src/java/org/apache/cassandra/db/compaction/CompactionIterator.java:154-165`、`src/java/org/apache/cassandra/db/compaction/CompactionIterator.java:218-222`、`src/java/org/apache/cassandra/db/compaction/CompactionIterator.java:341-366` | `test/unit/org/apache/cassandra/db/compaction/CompactionIteratorTest.java:89-178`、`:461-510` 覆盖 GC merge 和 duplicate row snapshot |
| `compaction_rate_limit_bootstrap_boundary` | rate limiter 每次读取 `DatabaseDescriptor.getCompactionThroughputBytesPerSec()`；throughput=0 或 bootstrap mode 时设置为 `Double.MAX_VALUE` | `src/java/org/apache/cassandra/db/compaction/CompactionManager.java:192-223` | nodetool compactionstats 断言 throughput disabled 文案；缺少 bootstrap-mode limiter focused test |
| `compaction_auto_upgrade_boundary` | 普通 compaction 无任务时可触发 `automatic_sstable_upgrade`，并由 `max_concurrent_automatic_sstable_upgrades` 限制并发 | `src/java/org/apache/cassandra/db/compaction/CompactionManager.java:360-402`、`src/java/org/apache/cassandra/db/compaction/CompactionStrategyManager.java:241-270` | `test/unit/org/apache/cassandra/db/compaction/CompactionStrategyManagerTest.java:204-277` 覆盖并发 1/2 边界 |
| `compaction_metrics_observability` | global metrics 暴露 pending/completed/bytes/compressed bytes/reduced/dropped/aborted/index summary redistribution | `src/java/org/apache/cassandra/metrics/CompactionMetrics.java:71-156` | `test/unit/org/apache/cassandra/tools/nodetool/CompactionStatsTest.java:99-303` 覆盖 nodetool 输出字段 |
| `compaction_jmx_nodetool_surface` | JMX 暴露 running/history/force/stop/thread/auto-upgrade；nodetool compact/forcecompact/stop/throughput/auto-compaction 调用 NodeProbe | `src/java/org/apache/cassandra/db/compaction/CompactionManagerMBean.java:27-180`、`src/java/org/apache/cassandra/tools/nodetool/Compact.java:33-101`、`src/java/org/apache/cassandra/tools/nodetool/Stop.java:47-49` | `test/unit/org/apache/cassandra/tools/nodetool/CompactTest.java:42-105`、`CompactionStatsTest.java:99-303` 覆盖 partition compact 和 stats，缺少 stop-by-id live assertion |
| `compaction_strategy_tuning_matrix` | STCS/LCS/TWCS/UCS 调参分别影响 size bucket、level/L0、time window/TTL、density/shard/target size | `src/java/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategy.java:79-130`、`LeveledManifest.java:199-329`、`TimeWindowCompactionStrategy.java:82-147`、`UnifiedCompactionStrategy.java:299-390` | strategy 单测覆盖 options/bucket/level/window/UCS controller；缺少跨 workload 生产调参 regression |
| `compaction_disk_space_failure_coverage` | 空间检查合并当前 task expected write 和 active compactions remaining write；Directories 按 filestore 聚合并比较 usable space | `src/java/org/apache/cassandra/db/compaction/ActiveCompactions.java:59-72`、`src/java/org/apache/cassandra/db/Directories.java:517-570`、`CompactionTask.java:409-416` | `CompactionDiskSpaceTest` 用 ByteBuddy mock `estimatedRemainingWriteToDiskBytes()` 与 `FileStoreUtils.tryGetSpace()` |
| `compaction_existing_tests_baseline` | 当前 coverage 覆盖 task history/interruption/fully expired/mixed repaired failure/offline/major、iterator GC/duplicate、nodetool stats/compact、UCS density | `test/unit/org/apache/cassandra/db/compaction/CompactionTaskTest.java:93-430`、`test/unit/org/apache/cassandra/db/compaction/CompactionIteratorTest.java:89-510`、`test/distributed/org/apache/cassandra/distributed/test/UnifiedCompactionDensitiesTest.java:41-104` | 仍缺少 executor saturation、bootstrap limiter、stop-by-id/live cancellation、空间 shrink metrics 的 focused tests |

## 调用图

```text
Flush / SSTable added / manual trigger
  -> ColumnFamilyStore / StorageService / nodetool path
  -> CompactionManager.submitBackground(cfs)
     -> reject if cfs.isAutoCompactionDisabled()
     -> reject if compactingCF.count(cfs) > 0 and executor has no idle thread
     -> executor.submitIfRunning(new BackgroundCompactionCandidate(cfs))
        -> CompactionStrategyManager.getNextBackgroundTask(gcBefore)
           -> maybeReloadDiskBoundaries()
           -> pendingRepairs.getNextRepairFinishedTask()
           -> transientRepairs.getNextRepairFinishedTask()
           -> holder.getBackgroundTaskSuppliers(gcBefore)
           -> Collections.sort(suppliers)
           -> first non-null supplier.getTask()
        -> task.execute(active)
        -> if no compaction ran and automatic_sstable_upgrade enabled
           -> maybeRunUpgradeTask(strategy)
           -> strategy.findUpgradeSSTableTask()
```

```text
CompactionTask.execute(active)
  -> runMayThrow()
     -> snapshot if DatabaseDescriptor.isSnapshotBeforeCompaction()
     -> CompactionController.getFullyExpiredSSTables()
     -> buildCompactionCandidatesForAvailableDiskSpace()
        -> getExpectedCompactedFileSize(nonExpiredSSTables)
        -> ActiveCompactions.estimatedRemainingWriteToDiskBytes()
        -> Directories.hasDiskSpaceForCompactionsAndStreams(...)
        -> reduceScopeForLimitedSpace(...) or incrementAborted()
     -> strategy.getScanners(...)
     -> active.beginCompaction(this)
     -> new CompactionIterator(...)
        -> UnfilteredPartitionIterators.merge(...)
        -> GarbageSkipper
        -> Purger or PaxosPurger
        -> DuplicateRowChecker.duringCompaction(...)
     -> getCompactionAwareWriter(...)
     -> while ci.hasNext()
        -> writer.append(ci.next())
        -> CompactionManager.compactionRateLimiterAcquire(...)
        -> controller.maybeRefreshOverlaps()
     -> writer.finish()
     -> SystemKeyspace.updateCompactionHistory(...)
     -> CompactionMetrics bytes/compressed/tasks
```

## 配置与操作面

| 类型 | 项 | 语义 |
|---|---|---|
| 全局并发 | `concurrent_compactors` | 定义在 `src/java/org/apache/cassandra/config/Config.java:335`；默认/校验在 `DatabaseDescriptor.java:777-781`；影响 compaction executor 并发 |
| 全局限速 | `compaction_throughput` | 定义在 `Config.java:337`；`DatabaseDescriptor.getCompactionThroughputBytesPerSec()` 被 `CompactionManager.getRateLimiter()` 读取 |
| 空间水位 | `min_free_space_per_drive`、`max_space_usable_for_compactions_in_percentage` | 定义在 `Config.java:338-344`；最终由 `Directories.hasDiskSpaceForCompactionsAndStreams()` 判定 |
| 前置 snapshot | `snapshot_before_compaction` | 定义在 `Config.java:312`；`CompactionTask.runMayThrow()` 在 task 开始时读取 |
| 预打开 | `sstable_preemptive_open_interval` | 定义在 `Config.java:461-462`；影响 compaction writer 中途 reopen/checkpoint |
| 自动升级 | `automatic_sstable_upgrade`、`max_concurrent_automatic_sstable_upgrades` | 定义在 `Config.java:697-698`；background no-task path 触发 upgrade |
| 表级开关 | compaction option `enabled` | `CompactionParams.create()` 解析；`CompactionStrategyManager.isEnabled()` 阻止后台任务 |
| 运行时 JMX | `CompactionManagerMBean` | running/history/force/stop/thread/auto-upgrade control |
| 运行时 nodetool | `compact`、`forcecompact`、`stop`、`setcompactionthroughput`、`disableautocompaction`、`enableautocompaction`、`compactionstats`、`compactionhistory` | 通过 `NodeProbe` 调用 StorageService/CompactionManager/Table MBeans |

## Metrics 与告警

- `Compaction.PendingTasks`：来自各 CFS estimated remaining tasks 加 active compactions，定义见 `src/java/org/apache/cassandra/metrics/CompactionMetrics.java:71-87`。持续增长通常表示 flush 速度、repair cleanup 或 compaction strategy backlog 超过处理能力。
- `PendingTasksByTableName`：把 active compactions 映射到 keyspace/table，定位热点表；见 `src/java/org/apache/cassandra/metrics/CompactionMetrics.java:87-132`。
- `CompletedTasks` 与 `TotalCompactionsCompleted`：区分 executor completed count 和 compaction meter，见 `CompactionMetrics.java:139-150`。
- `BytesCompacted`、`CompressedBytesCompacted`、`TableMetrics.compactionBytesWritten`：判断 compaction 写放大和实际吞吐；task 更新见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:271-299`。
- `CompactionsReduced`、`SSTablesDroppedFromCompaction`、`CompactionsAborted`：空间不足和 partial compaction 的一线告警，定义见 `CompactionMetrics.java:154-156`，更新见 `CompactionTask.java:441-453`。
- `compactionstats -V` 暴露 task id、kind、progress、sstable count、target directory；测试断言见 `test/unit/org/apache/cassandra/tools/nodetool/CompactionStatsTest.java:150-303`。

## 故障与排查

- 后台 compaction 不动：先看表级 auto compaction、`CompactionStrategyManager.isEnabled()`、executor active/max、是否同表已有任务；入口见 `CompactionManager.submitBackground()`。
- pending task 高但 throughput 低：检查 `compaction_throughput` 是否过低、是否处于 bootstrap mode、磁盘/CPU 是否被 repair/streaming/index build 抢占。
- 空间不足：检查 `CompactionsReduced`、`SSTablesDroppedFromCompaction`、`CompactionsAborted` 和 `Not enough space for compaction` 日志；space checker 会把 active compaction remaining write 合并到 expected write，多个数据目录共享同一 filestore 时也会失败。
- compaction 被中断：`CompactionTask` 在 strategy inactive 时抛 `CompactionInterruptedException`；`CompactionIterator` stop/abortable transform 也会抛中断，单测见 `CompactionTaskTest.compactionInterruption()` 和 `CompactionIteratorTest.transformTest()`。
- repaired/unrepaired/pending repair 混合：`CompactionTask.getPendingRepair()` 和 `getIsTransient()` 要求 originals repair metadata 一致，否则失败；单测 `mixedSSTableFailure()` 覆盖。
- duplicate row：`DuplicateRowChecker.duringCompaction()` 可触发 diagnostic snapshot；单测 `CompactionIteratorTest.duplicateRowsTest()` 覆盖。
- fully expired SSTable 与 checkpoint：fully expired SSTable 不能在 writer switch/checkpoint 期间提前失去 reference；`testFullyExpiredSSTablesAreNotReleasedPrematurely()` 覆盖 CASSANDRA-19776 边界。

## 测试缺口

- `compaction_background_scheduler_backpressure` 缺少专门模拟 executor full + same CFS compacting 的单测。
- `compaction_rate_limit_bootstrap_boundary` 缺少 bootstrap mode 下 `Double.MAX_VALUE` limiter 的 focused test。
- `compaction_jmx_nodetool_surface` 缺少 live `stop --compaction-id` 取消任务并观察 state/metrics 的测试。
- `compaction_task_snapshot_space_reduction` 已有 no-space distributed test，但缺少 metrics 级断言 `CompactionsReduced`/`SSTablesDroppedFromCompaction` 的 focused test。
- `compaction_strategy_tuning_matrix` 仍需要 workload 级 regression：STCS write-heavy、LCS read-heavy/L0 backlog、TWCS TTL out-of-order、UCS shard/target-size 组合。

