# Module: SSTable And Compaction

## 范围

本模块覆盖 SSTable reader/writer、metadata、compaction manager、strategy 和 compaction task 主线，不展开全部 on-disk format 版本差异。

## 设计目标

SSTable 是 Cassandra 的不可变磁盘存储文件集合；Compaction 负责把多个 SSTable 重新合并，清理过期 tombstone、合并重复行、降低读放大，并维护策略要求的层级/窗口/密度。

设计目标：

- Flush 输出不可变 SSTable，读路径可用 primary index、summary、Bloom filter 快速定位 partition。
- Compaction 在后台按策略选择 SSTables，读 scanner、merge partition、purge tombstone、写新 SSTable。
- Compaction 使用 `LifecycleTransaction` 保证 originals/new SSTables 的状态切换和失败回滚。
- 根据 compaction strategy 支持 STCS、LCS、TWCS、UCS 等不同读写放大取舍。

## 解决的问题

- Memtable flush 产生多个不可变 SSTable，读路径会出现多 SSTable merge；compaction 降低 SSTable 数量和重叠。
- 删除不是立即物理删除，tombstone 需要在 compaction 中结合 gc/grace/overlap 判断是否可清理。
- SSTable 读需要索引结构定位 key；`BigTableReader.rowIterator()` 先 `getRowIndexEntry()`，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:126-144`。
- Compaction 需要在磁盘空间不足时缩小 scope 或失败；`CompactionTask.reduceScopeForLimitedSpace()` 会尝试移除最大 SSTable，见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:98-114`。

## 设计取舍

- SSTable 不原地更新，写入简单且 crash-safe，但需要 compaction 后台维护。
- `BigTableWriter.IndexWriter.append()` 同时写 primary index、更新 Bloom filter 和 index summary，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableWriter.java:267-290`。
- Compaction 通过 iterator transformation pipeline 执行 merge、garbage skip、purger、duplicate row check，见 `src/java/org/apache/cassandra/db/compaction/CompactionIterator.java:154-165`。
- Compaction 会消耗额外磁盘空间；空间不足时可做 partial compaction，但可能牺牲策略最优性，见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:98-114`。

## 核心类

| 类 | 作用 |
|---|---|
| `SSTableReader` | SSTable 读抽象，Big 格式 reader 继承体系的一部分 |
| `BigTableReader` | Big table 格式 reader，提供 row iterator、partition scanner、key reader。类定义见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:85` |
| `BigTableWriter` | Big table 格式 writer，写 data/index/summary/bloom。类定义见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableWriter.java:69` |
| `CompactionManager` | compaction executor、提交后台/用户/validation/index/view/cache 任务。类定义见 `src/java/org/apache/cassandra/db/compaction/CompactionManager.java:140` |
| `CompactionStrategyManager` | 持有当前表的 compaction params 和策略实例，类定义见 `src/java/org/apache/cassandra/db/compaction/CompactionStrategyManager.java:106` |
| `SizeTieredCompactionStrategy`、`LeveledCompactionStrategy`、`TimeWindowCompactionStrategy`、`UnifiedCompactionStrategy` | 策略选择层，细节见 `research/module-compaction-strategies-deep-dive.md` |
| `CompactionTask` | 单个 compaction 执行任务，核心 run loop 见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:122-300` |
| `CompactionIterator` | scanner merge、purge、duplicate row check、progress 的 iterator，构造见 `src/java/org/apache/cassandra/db/compaction/CompactionIterator.java:118-166` |
| `CompactionAwareWriter` | 根据 compaction 输出策略写新 SSTable，`CompactionTask` 使用见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:212-245` |

## 核心接口

- `ISSTableScanner`：compaction 输入 scanner；`CompactionIterator` 接收 scanner list，见 `src/java/org/apache/cassandra/db/compaction/CompactionIterator.java:123-147`。
- `AbstractCompactionStrategy`：策略接口，具体 STCS/LCS/TWCS/UCS 继承它，类定义见 `src/java/org/apache/cassandra/db/compaction/AbstractCompactionStrategy.java:65`。
- `SSTableMultiWriter`：flush 与 compaction 输出 writer 的抽象。
- `CompactionInfo.Holder`：CompactionIterator 暴露进度给 metrics/nodetool compactionstats，见 `src/java/org/apache/cassandra/db/compaction/CompactionIterator.java:90`。

## 核心数据结构

- SSTable components：data、primary index、summary、filter、stats、compression metadata 等，Big writer 至少显式写 primary index/summary/Bloom，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableWriter.java:253-258`、`src/java/org/apache/cassandra/io/sstable/format/big/BigTableWriter.java:267-290`。
- `RowIndexEntry`：partition key 到 data 文件位置/索引信息的映射，reader 获取见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:126-144`。
- `IndexSummary`：primary index 的内存采样，写入 build/save 见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableWriter.java:319-324`。
- `LifecycleTransaction`：compaction/flush 对 SSTable 状态变更的事务边界，flush 使用见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1293-1324`，compaction task 持有 transaction 见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:122-128`。
- `CompactionParams`：表级 compaction class/options/enabled/tombstone option，定义见 `src/java/org/apache/cassandra/schema/CompactionParams.java:46-121`。

## 生命周期

```text
SSTable flush write:
  Flushing.FlushRunnable.call()
    -> writeSortedContents()
       -> for each Partition
          -> writer.append(UnfilteredRowIterator)
       -> writer.finish()
    -> ColumnFamilyStore.replaceFlushed(...)

Compaction:
  CompactionManager.submitBackground(cfs)
    -> BackgroundCompactionCandidate
    -> CompactionStrategyManager selects tasks
    -> CompactionTask.runMayThrow()
       -> get CompactionController
       -> identify fully expired SSTables
       -> build candidates for available disk space
       -> strategy.getScanners(...)
       -> new CompactionIterator(...)
       -> getCompactionAwareWriter(...)
       -> while ci.hasNext()
          -> writer.append(ci.next())
          -> rate limiter acquire
          -> maybe refresh overlaps
       -> writer.finish()
       -> update compaction history
       -> update metrics
```

## 调用链

- Flush 写 SSTable：`Flushing.FlushRunnable.writeSortedContents()` 遍历 partition 并 `writer.append(iter)`，见 `src/java/org/apache/cassandra/db/memtable/Flushing.java:151-184`。
- BigTable primary index：`BigTableWriter.IndexWriter.append()` 添加 Bloom filter、写 key/index entry、更新 summary，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableWriter.java:267-290`。
- SSTable point read：`BigTableReader.rowIterator()` 调用 `getRowIndexEntry()` 并返回正向/反向 iterator，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:126-144`。
- 后台 compaction 提交：`CompactionManager.submitBackground()`，见 `src/java/org/apache/cassandra/db/compaction/CompactionManager.java:230-258`。
- Compaction 执行：`CompactionTask.runMayThrow()`，见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:122-300`。
- Compaction merge/purge pipeline：`CompactionIterator` 构造函数，见 `src/java/org/apache/cassandra/db/compaction/CompactionIterator.java:154-165`。

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| 表级 `compaction` | `src/java/org/apache/cassandra/schema/TableParams.java:87`，默认 builder `src/java/org/apache/cassandra/schema/TableParams.java:369` | 指定 compaction class/options |
| `CompactionParams.DEFAULT` | `src/java/org/apache/cassandra/schema/CompactionParams.java:90-96` | 默认策略 |
| `concurrent_compactors` | `src/java/org/apache/cassandra/config/Config.java:335`，默认/校验 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:777-781` | compaction executor 并发 |
| `compaction_throughput` | `src/java/org/apache/cassandra/config/Config.java:336-337`，模板 `conf/cassandra.yaml:1223-1251` | compaction 限速 |
| `min_free_space_per_drive` | `src/java/org/apache/cassandra/config/Config.java:338-339` | compaction 可用空间判断 |
| `max_space_usable_for_compactions_in_percentage` | `src/java/org/apache/cassandra/config/Config.java:343-344` | compaction 可用空间比例 |
| `autocompaction_on_startup_enabled` | `src/java/org/apache/cassandra/config/Config.java:833` | startup 后是否自动启用 compaction |
| `snapshot_before_compaction` | 读取位置 `CompactionTask.runMayThrow()`：`src/java/org/apache/cassandra/db/compaction/CompactionTask.java:135-139` | compaction 前 snapshot |
| `column_index_size`、`column_index_cache_size` | `src/java/org/apache/cassandra/config/Config.java:324-328` | SSTable row index/index cache 行为 |
| `sstable_preemptive_open_interval` | `src/java/org/apache/cassandra/config/Config.java:460-462` | compaction/flush 输出预打开 |

## Metrics

- `TableMetrics.liveSSTableCount`、`oldVersionSSTableCount`、`liveDiskSpaceUsed`、`totalDiskSpaceUsed`：定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:130-143`。
- `TableMetrics.sstablesPerReadHistogram`、`sstablesPerRangeReadHistogram`：读放大观测，定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:110-113`。
- `TableMetrics.compactionBytesWritten`：compaction 写出字节，定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:126-129`，更新见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:297-299`。
- `CompactionMetrics.pendingTasks`、`completedTasks`、`bytesCompacted`、`compactionsReduced`、`compactionsAborted`：定义见 `src/java/org/apache/cassandra/metrics/CompactionMetrics.java:40-69`。

## 日志

- compaction 空间不足缩小范围：`logger.warn("insufficient space to compact...")`，见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:98-108`。
- compaction 开始：`logger.info("Compacting ...")`，见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:168-176`。
- fully expired SSTable 被丢弃：debug 日志见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:187-190`。
- compaction 完成统计：`logger.info(String.format("Compacted ..."))`，见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:271-289`。
- index summary 保存失败：`BigTableWriter.IndexWriter.doPrepare()` warn 日志见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableWriter.java:319-328`。

## 运维关注点

- pending compaction 高说明写入/flush 产生 SSTable 的速度超过 compaction 处理能力。
- `sstablesPerReadHistogram` 高通常意味着读放大严重，需要检查 compaction backlog、策略和热点分区。
- compaction 空间不足会缩小任务或失败，需关注 `min_free_space_per_drive`、数据目录剩余空间和 compaction 日志。
- compaction 前 snapshot 会显著增加空间压力。
- tombstone 清理依赖 compaction 和安全条件，不应把删除后空间未释放直接判断为异常。

## 性能瓶颈

- 读放大：SSTable 数量和重叠越多，单次读涉及更多 index/filter/data 文件。
- 写放大：compaction 重写数据，策略不同导致写放大不同。
- 磁盘空间：compaction 需要同时保留输入和输出，空间不足会导致 partial/aborted compaction。
- CPU/序列化：CompactionIterator 的 merge、purge、duplicate check 都在 compaction loop 中执行。
- 限速：`CompactionManager.compactionRateLimiterAcquire()` 在 compaction loop 中限制扫描速度，见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:230-233`。

## 常见故障

- compaction 失败或长期 pending：检查 `CompactionMetrics.PendingTasks`、日志中的 insufficient space/aborted。
- SSTable 损坏：reader 捕获 IOException 会 `markSuspect()` 并抛 `CorruptSSTableException`，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:172-190`。
- index summary 保存失败：日志 warn 但不一定导致数据不可读，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableWriter.java:319-328`。
- duplicate rows：可由 compaction 中 `DuplicateRowChecker.duringCompaction()` 检测，pipeline 见 `src/java/org/apache/cassandra/db/compaction/CompactionIterator.java:163-165`。

## 测试用例

- `test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java`
- `test/unit/org/apache/cassandra/io/sstable/SSTableWriterTest.java`
- `test/unit/org/apache/cassandra/io/sstable/SSTableScannerTest.java`
- `test/unit/org/apache/cassandra/io/sstable/filter/BloomFilterTrackerTest.java`
- `test/unit/org/apache/cassandra/db/compaction/CompactionTaskTest.java`
- `test/unit/org/apache/cassandra/db/compaction/CompactionIteratorTest.java`
- `test/unit/org/apache/cassandra/db/compaction/CompactionStrategyManagerTest.java`
- `test/unit/org/apache/cassandra/db/compaction/UnifiedCompactionStrategyTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/CompactionDiskSpaceTest.java`

## 待继续

- 深入 Bloom Filter、index summary、key cache、row index 和 BTI/Big 格式差异。
- STCS/LCS/TWCS/UCS 的选择逻辑、配置参数和故障特征已在 `module-compaction-strategies-deep-dive.md` 展开；本模块继续聚焦 compaction 执行骨架和 on-disk format 差异。
- `LifecycleTransaction`、`Tracker` 和 SSTable view 状态切换已在 `module-storage-engine-lifecycle-transaction.md` 展开。
- Compaction 生产运行面的 `compaction_task_snapshot_space_reduction` 与 `compaction_disk_space_failure_coverage` 场景已在 `module-compaction-operations-failure-matrix.md` 和 `research/tools/check-compaction-operations-drift.py` 中补齐。
