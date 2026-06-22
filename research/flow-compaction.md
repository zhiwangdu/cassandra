# Flow: Compaction Path

## 目标

Compaction 链路解释后台 compaction 如何选择 SSTables、创建 scanner、合并/清理数据、写出新 SSTables，并更新 compaction history、metrics 和 SSTable lifecycle。

## 文字版调用图

```text
Trigger:
  -> memtable flush creates new SSTables
  -> compaction strategy estimates pending tasks
  -> CompactionManager.submitBackground(cfs)
     -> executor.submitIfRunning(new BackgroundCompactionCandidate(cfs))

Selection:
  -> CompactionStrategyManager
     -> current table CompactionParams
     -> holder routing by repaired/unrepaired/pending repair and token boundary
     -> concrete strategy STCS/LCS/TWCS/UCS
        -> STCS: size bucket + hotness
        -> LCS: manifest score, L0 fallback, level candidates
        -> TWCS: time-window bucket, expired SSTable check
        -> UCS: density levels, overlap buckets, shard-aware task
     -> create CompactionTask with LifecycleTransaction originals

Execution:
  -> CompactionTask.runMayThrow()
     -> if transaction.originals().isEmpty() return
     -> strategy = cfs.getCompactionStrategyManager()
     -> optional snapshot_before_compaction
     -> CompactionController controller
        -> fullyExpiredSSTables = controller.getFullyExpiredSSTables()
        -> buildCompactionCandidatesForAvailableDiskSpace(...)
        -> controller.refreshOverlaps() if scope reduced
     -> strategy.getScanners(actuallyCompact)
     -> new CompactionIterator(type, scanners, controller, nowInSec, taskId)
        -> merge scanners
        -> GarbageSkipper
        -> Purger/PaxosPurger
        -> DuplicateRowChecker.duringCompaction
     -> activeCompactions.beginCompaction(ci)
     -> getCompactionAwareWriter(...)
     -> while ci.hasNext()
        -> writer.append(ci.next())
        -> ci.setTargetDirectory(...)
        -> CompactionManager.compactionRateLimiterAcquire(...)
        -> controller.maybeRefreshOverlaps()
     -> writer.finish()
     -> activeCompactions.finishCompaction(ci)
     -> updateCompactionHistory(...)
     -> cfs.metric.compactionBytesWritten.inc(endsize)
```

## 关键源码锚点

| 阶段 | 文件/方法 |
|---|---|
| 后台提交 | `CompactionManager.submitBackground()`：`src/java/org/apache/cassandra/db/compaction/CompactionManager.java:230-258` |
| compaction task 主体 | `CompactionTask.runMayThrow()`：`src/java/org/apache/cassandra/db/compaction/CompactionTask.java:122-300` |
| 空间不足缩小 scope | `CompactionTask.reduceScopeForLimitedSpace()`：`src/java/org/apache/cassandra/db/compaction/CompactionTask.java:98-114` |
| scanner + iterator + writer loop | `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:199-245` |
| compaction history | `CompactionTask.updateCompactionHistory()`：`src/java/org/apache/cassandra/db/compaction/CompactionTask.java:311-326` |
| merge/purge pipeline | `CompactionIterator` 构造：`src/java/org/apache/cassandra/db/compaction/CompactionIterator.java:118-166` |
| strategy params | `CompactionParams`：`src/java/org/apache/cassandra/schema/CompactionParams.java:46-121` |
| strategy manager routing | `CompactionStrategyManager.getNextBackgroundTask()`：`src/java/org/apache/cassandra/db/compaction/CompactionStrategyManager.java:192-239` |
| STCS selection | `SizeTieredCompactionStrategy.getNextBackgroundSSTables()`：`src/java/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategy.java:79-107` |
| LCS selection | `LeveledManifest.getCompactionCandidates()`：`src/java/org/apache/cassandra/db/compaction/LeveledManifest.java:199-301` |
| TWCS selection | `TimeWindowCompactionStrategy.getCompactionCandidates()`：`src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategy.java:172-190` |
| UCS selection | `UnifiedCompactionStrategy.getNextCompactionPick()`：`src/java/org/apache/cassandra/db/compaction/UnifiedCompactionStrategy.java:321-344` |

## 配置与观测

- 表级 compaction params：`TableParams.compaction` 定义见 `src/java/org/apache/cassandra/schema/TableParams.java:87`。
- 默认 compaction params：`src/java/org/apache/cassandra/schema/CompactionParams.java:90-96`。
- `concurrent_compactors`：`src/java/org/apache/cassandra/config/Config.java:335`，默认/校验见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:777-781`。
- `compaction_throughput`：`src/java/org/apache/cassandra/config/Config.java:336-337`。
- `CompactionMetrics.PendingTasks`：定义见 `src/java/org/apache/cassandra/metrics/CompactionMetrics.java:44-85`。
- `TableMetrics.compactionBytesWritten`：定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:126-129`，更新见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:297-299`。
- 策略选择和调参细节见 `research/module-compaction-strategies-deep-dive.md`。

## 故障排查

- Pending tasks 长期增加：策略选择的任务多于 executor 能处理的速度，需看写入量、flush 频率、磁盘带宽和 compaction throughput。
- 空间不足：日志会出现 insufficient space，并可能 reduce scope 或 aborted，见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:98-108`。
- 读放大：看 `sstablesPerReadHistogram` 与 table 的 live SSTable count。
- tombstone 未释放：确认 compaction 是否实际覆盖相关 SSTables、是否仍有 overlap、gc grace 是否满足。

## 测试用例

- `test/unit/org/apache/cassandra/db/compaction/CompactionTaskTest.java`
- `test/unit/org/apache/cassandra/db/compaction/CompactionIteratorTest.java`
- `test/unit/org/apache/cassandra/db/compaction/CompactionStrategyManagerTest.java`
- `test/unit/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategyTest.java`
- `test/unit/org/apache/cassandra/db/compaction/LeveledCompactionStrategyTest.java`
- `test/unit/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategyTest.java`
- `test/unit/org/apache/cassandra/db/compaction/UnifiedCompactionStrategyTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/CompactionDiskSpaceTest.java`
