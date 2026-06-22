# Flush Execution And Disk Pressure Matrix

## 范围

本文补齐 `research/module-memtable-flush.md`、`research/module-memtable-postflush-trigger-deep-dive.md` 和 `research/flow-flush.md` 中尚未单独成矩阵的 Flush 执行层：flush executor 拓扑、per-disk runnable、disk boundary 拆分、写入目录选择、低磁盘/不可写磁盘失败传播、PostFlush/CommitLog 清理和运维触发。

本文不重复 SkipList/ShardedSkipList/Trie memtable 实现细节；这些由 `research/module-memtable-implementation-flush-matrix.md` 覆盖。本文重点是 live memtable 已切出之后，Flush 如何把数据安全地写成 SSTable，以及磁盘压力如何影响 runnable、writer、transaction 和 CommitLog reclaim。

## 场景矩阵

| 场景 ID | 源码合同 | 测试/缺口 |
|---|---|---|
| `flush_executor_topology_contract` | `ColumnFamilyStore` 维护全局 `MemtableFlushWriter`、单线程 `MemtablePostFlush`、单线程 `MemtableReclaimMemory`，并为每个数据目录创建 `PerDiskMemtableFlushWriter_i`；local system keyspace 可使用独立 `LocalSystemKeyspacesDiskMemtableFlushWriter`。见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:199-220`、`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:3474-3530`。 | 现有测试不直接断言 executor 数量；checker 固定 source tokens 与 config tokens。 |
| `flush_force_switch_dirty_contract` | `switchMemtable()` 构造 `Flush(false)` 并提交 flush/postFlush；`forceFlush(FlushReason)` 只有发现 base 或 index current memtable 非 clean 才切换，否则等待已有 postFlush；`forceFlush(CommitLogPosition)` 只关心 commitlog dirtiness。见 `ColumnFamilyStore.java:1033-1092`。 | `ColumnFamilyStoreTest` 和 `CommitLogTest` 多处通过 `Util.flush(cfs)`、`switchMemtableIfCurrent()` 间接覆盖 dirty/clean flush。 |
| `flush_barrier_commitlog_upper_bound_contract` | `Flush` 构造阶段为 base 与 CFS-backed index memtables 创建新 memtable、调用 `switchOut(writeBarrier, commitLogUpperBound)`，设置 continuous commitlog upper bound 后 `writeBarrier.issue()`；`Flush.run()` 再 `markBlocking()`/`await()`。见 `ColumnFamilyStore.java:1175-1239`。 | `CommitLogTest` 的 out-of-order/failed flush recovery 保护失败时不能错误 discard commitlog。 |
| `flush_postflush_commitlog_discard_contract` | `PostFlush.call()` 等待 flush latch；仅当 `flushFailure == null` 且有 main memtable 时调用 `CommitLog.instance.discardCompletedSegments()`，最后递减 `pendingFlushes` 并传播失败。见 `ColumnFamilyStore.java:1123-1156`。 | `CommitLogTest` 在 flush 失败后要求 replay list 仍有数据，防止错误清理 commitlog。 |
| `flush_empty_memtable_reclaim_contract` | clean memtable 或 truncate flush 不创建 writer，直接 `replaceFlushed(memtable, Collections.emptyList())` 并通过 read barrier 异步 `memtable.discard()`。见 `ColumnFamilyStore.java:1276-1290`、`ColumnFamilyStore.java:1391-1404`。 | 现有基线主要由 CFS flush tests 间接覆盖；仍缺专门 empty flush reclaim assertion。 |
| `flush_disk_boundaries_split_contract` | `Flushing.flushRunnables()` 绑定 `LifecycleTransaction`，读取 `cfs.getDiskBoundaries()`；没有 boundaries 时单 runnable，有 boundaries 时按 `positions`/`directories` 逐段构造 runnable。见 `src/java/org/apache/cassandra/db/memtable/Flushing.java:57-96`。 | `memtable_flush_writer_disk_boundary_contract` 已记录 memtable 侧；本矩阵把低磁盘/慢盘风险单独拉出。 |
| `flush_writer_location_space_contract` | `Flushing.flushRunnable()` 对每段 flush set 估算大小；无强制 disk boundary 时调用 `getWriteableLocationAsFile(estimatedSize)`，有 boundary 时使用 `getLocationForDisk(flushLocation)`。`Directories.getWriteableLocation()` 过滤不可写目录、空间不足目录，空间不足抛 `FSDiskFullWriteError`，全不可写抛 `FSNoDiskAvailableForWriteError`。见 `Flushing.java:98-120`、`src/java/org/apache/cassandra/db/Directories.java:360-366`、`src/java/org/apache/cassandra/db/Directories.java:438-475`。 | `DirectoriesTest` 覆盖候选目录排序 helper；缺 flush 直接触发 `FSDiskFullWriteError`/`FSNoDiskAvailableForWriteError` 的组合测试。 |
| `flush_per_disk_submit_wait_contract` | `Flush.flushMemtable()` 从 `PerDiskFlushExecutors.getExecutorsFor()` 取 executor 数组，按 runnable index submit，并用 `FBUtilities.waitOnFutures(futures)` 等所有 per-disk writer 完成。见 `ColumnFamilyStore.java:1296-1315`。 | 慢盘会拖住整个 flush Future 和 PostFlush；缺多目录慢盘注入测试。 |
| `flush_runnable_write_metrics_contract` | `FlushRunnable.writeSortedContents()` 记录 `Writing ..., flushed range`，跳过 batchlog insert+delete tombstone，逐 partition `writer.append(iter)`；完成时记录文件名、字节数和 commitlog position，并递增 `TableMetrics.bytesFlushed`。见 `Flushing.java:151-184`。 | `SSTableFlushObserverTest` 覆盖 writer/observer begin、row、complete、abort 生命周期。 |
| `flush_failure_abort_transaction_contract` | 任一 runnable/writer 失败时，`Flush.flushMemtable()` 调用 `Flushing.abortRunnables()` 和 `txn.abort(t)`；writer prepare/commit 阶段失败也 abort writers/transaction，PostFlush 看到 `flushFailure` 后不 discard commitlog。见 `ColumnFamilyStore.java:1316-1346`。 | `CommitLogTest` 使用不可写目录/不可 flush memtable 验证失败后仍需 commitlog replay。 |
| `flush_secondary_index_blocking_contract` | base memtable flush 在 barrier 完成后同步调用 `indexManager.flushAllNonCFSBackedIndexesBlocking(memtable)`；该同步点会把自定义 secondary index flush latency 算入 base flush。见 `ColumnFamilyStore.java:1307-1314`。 | 现有 coverage 偏 index lifecycle；缺自定义 non-CFS-backed index 慢 flush 的 fault/perf test。 |
| `flush_storage_service_user_drain_contract` | nodetool flush 经 `Flush` command -> `NodeProbe.forceKeyspaceFlush()` -> `StorageService.forceKeyspaceFlush()` -> `forceBlockingFlush(USER_FORCED)`；drain 先停写、关闭 mutation executors，再对 non-local/system keyspaces 发 `forceFlush(DRAIN)` 并等待。见 `src/java/org/apache/cassandra/tools/nodetool/Flush.java:28-46`、`src/java/org/apache/cassandra/tools/NodeProbe.java:509-512`、`src/java/org/apache/cassandra/service/StorageService.java:4743-4764`、`StorageService.java:5835-5960`。 | `NodeToolTest.testCommands()` 覆盖 `nodetool("flush")` 成功；drain flush 主要靠集成路径覆盖。 |
| `flush_metrics_observability_contract` | Flush 相关表级观测包括 `MemtableSwitchCount`、`PendingFlushes`、`BytesFlushed` 和 `flushSizeOnDisk`；source 更新点在 `Flush`/`PostFlush`/`FlushRunnable`/writer commit。见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:101-125`、`TableMetrics.java:532`、`TableMetrics.java:631-633`。 | 缺低磁盘/慢盘下 `PendingFlushes`、`BytesFlushed`、`flushSizeOnDisk` 组合断言。 |
| `flush_existing_test_baseline` | 当前基线包括 `ColumnFamilyStoreTest` 普通 flush、`CommitLogTest` failed flush recovery、`SSTableFlushObserverTest` writer observer、`DirectoriesTest` directory candidate、`DiskFailurePolicyTest` disallowed directory、`NodeToolTest` flush command 和 streaming/compaction disk-space tests 的外围覆盖。 | checker 保护这些测试文件与关键 tokens 仍存在。 |
| `flush_disk_pressure_gap` | 仍缺真实组合压测：多 data directory 下某盘慢、某盘 near-full/不可写、disk boundaries 重算与 flush writer 并发同时发生时，验证 per-disk runnable 数量、PostFlush latch、CommitLog reclaim、metrics 和用户可见错误。 | 保留 explicit gap，避免把 source-only drift checker 误读成低磁盘/慢盘行为已经端到端验证。 |

## 设计目标

- 将 memtable switch 之后的写盘工作拆成“全局调度 + per-disk 写入”，避免单个 flush 线程串行写所有数据目录。
- 用 write barrier 定义旧写入和新 memtable 的边界，保证 flush SSTable 覆盖正确 commitlog 区间。
- 按 disk boundaries 把 token range 与数据目录绑定，减少后续 misplaced SSTable 和跨盘移动。
- 在低空间或目录被 disallowed 时尽早失败，失败后不得清理对应 commitlog segment。
- 在 PostFlush 阶段统一完成 CommitLog discard、pending flush metric 递减、失败传播和 memtable memory reclaim。

## 设计取舍

- `Flush` 构造在 `Tracker` monitor 内完成 switch，但实际等待旧写和写盘在 executor 中执行；这样减少写入停顿，但需要 `OpOrder.Barrier` 和 commitlog upper bound 共同保证边界。
- per-disk flush executor 数量与 `memtable_flush_writers` 相关，提升多盘并行度；代价是慢盘仍会让整个 `Flush` 等待所有 futures 完成。
- disk boundaries 存在时 `Flushing` 使用指定目录，不再走可写目录随机选择；这保证 range->disk contract，但低空间时会把压力集中暴露在目标目录。
- `PostFlush` 单线程执行，保证同一 CF 的 flush Future 不会早于之前 flush 完成；代价是 PostFlush 卡顿会影响后续 commitlog reclaim。
- writer 失败时 abort runnables 和 transaction，而不是尝试局部保留成功 writer；这避免半提交 SSTable 可见性复杂化。

## 核心类

| 类 | 作用 |
|---|---|
| `ColumnFamilyStore.Flush` | memtable switch、write barrier、per-CFS flushMemtable、writer commit 和 reclaim 的核心 runnable。 |
| `ColumnFamilyStore.PostFlush` | 等待 Flush 完成，成功时 discard CommitLog segment，失败时传播错误并保留 commitlog replay 能力。 |
| `ColumnFamilyStore.PerDiskFlushExecutors` | 为每个数据目录和 local system keyspace 特例维护 flush executor。 |
| `Flushing` | 把 memtable 与 `LifecycleTransaction` 绑定，按 disk boundaries 创建 `FlushRunnable` 和 SSTable writer。 |
| `Flushing.FlushRunnable` | 遍历 flush set，把 partitions 追加到 `SSTableMultiWriter`，更新 bytes flushed。 |
| `DiskBoundaries` | 持有目录与 token boundary 映射，并通过 disk/ring version 判断是否过期。 |
| `Directories` | 选择可写目录、过滤 disallowed/空间不足目录，抛出 disk full/no disk write errors。 |
| `StorageService` / `NodeProbe` / nodetool `Flush` | 运维触发 user forced flush 与 drain flush。 |
| `TableMetrics` | 暴露 `PendingFlushes`、`MemtableSwitchCount`、`BytesFlushed` 和 `flushSizeOnDisk`。 |

## 核心接口与数据结构

- `ColumnFamilyStore.switchMemtable(FlushReason)`：创建 `Flush` 并提交 flush/postFlush executors。
- `ColumnFamilyStore.forceFlush(FlushReason)` / `forceFlush(CommitLogPosition)`：按 dirty memtable 或 commitlog position 决定是否切换。
- `Memtable.switchOut(OpOrder.Barrier, AtomicReference<CommitLogPosition>)`：把 barrier 和 commitlog upper bound 交给旧 memtable。
- `Flushing.flushRunnables(ColumnFamilyStore, Memtable, LifecycleTransaction)`：生成 1 个或 N 个 per-disk runnable。
- `Directories.getWriteableLocationAsFile(long)` / `getWriteableLocation(long)`：flush writer 目录选择和低空间失败入口。
- `SSTableMultiWriter.prepareToCommit()` / `commit()` / `finished()`：writer 从临时状态进入可见 SSTable readers 的边界。
- `CommitLog.discardCompletedSegments(TableId, lower, upper)`：PostFlush 成功后的 commitlog reclaim 入口。

## 生命周期与调用链

User forced flush：

```text
nodetool flush
  -> org.apache.cassandra.tools.nodetool.Flush.execute()
  -> NodeProbe.forceKeyspaceFlush()
  -> StorageService.forceKeyspaceFlush()
  -> ColumnFamilyStore.forceBlockingFlush(USER_FORCED)
  -> ColumnFamilyStore.forceFlush(USER_FORCED)
```

Flush execution：

```text
ColumnFamilyStore.switchMemtable(reason)
  -> new ColumnFamilyStore.Flush(false)
     -> metric.pendingFlushes.inc()
     -> Keyspace.writeOrder.newBarrier()
     -> create replacement memtables for base + CFS-backed indexes
     -> oldMemtable.switchOut(writeBarrier, commitLogUpperBound)
     -> setCommitLogUpperBound()
     -> writeBarrier.issue()
     -> postFlushTask = FutureTask(PostFlush)
  -> flushExecutor.execute(flush)
  -> postFlushExecutor.execute(postFlushTask)

MemtableFlushWriter
  -> Flush.run()
     -> writeBarrier.markBlocking()
     -> writeBarrier.await()
     -> data.markFlushing(oldMemtable)
     -> metric.memtableSwitchCount.inc()
     -> flushMemtable(base, oldMemtable, flushNonCf2i=true)
```

Per-disk writer path：

```text
Flush.flushMemtable()
  -> LifecycleTransaction.offline(OperationType.FLUSH)
  -> Flushing.flushRunnables(cfs, memtable, txn)
     -> memtable.setFlushTransaction(txn)
     -> cfs.getDiskBoundaries()
     -> for each boundary directory:
        -> memtable.getFlushSet(from, to)
        -> estimate writer size
        -> cfs.getDirectories().getLocationForDisk(directory)
        -> create SSTableMultiWriter
  -> perDiskflushExecutors.getExecutorsFor(keyspace, table)
  -> submit FlushRunnable to matching executor
  -> optional indexManager.flushAllNonCFSBackedIndexesBlocking(memtable)
  -> waitOnFutures()
  -> writer.prepareToCommit()
  -> txn.prepareToCommit()
  -> writer.commit()
  -> txn.commit()
  -> writer.finished()
  -> cfs.replaceFlushed(memtable, sstables)
  -> reclaim(memtable)
```

Failure/reclaim path：

```text
FlushRunnable or writer fails
  -> Flushing.abortRunnables()
  -> LifecycleTransaction.abort()
  -> Flush.run catches throwable
  -> postFlush.flushFailure = throwable
  -> postFlush.latch.decrement()
  -> PostFlush.call()
     -> skip CommitLog.discardCompletedSegments()
     -> pendingFlushes.dec()
     -> rethrow failure
```

Drain path：

```text
StorageService.drain()
  -> stop client/messaging/mutation paths
  -> disableAutoCompaction()
  -> count non-local CFs before submitting flushes
  -> cfs.forceFlush(DRAIN) for non-local strategy keyspaces
  -> wait each future and decrement drain progress
  -> flush system keyspaces
  -> waitOnFutures(system flushes)
```

## 配置项

- `memtable_flush_writers`：定义在 `src/java/org/apache/cassandra/config/Config.java:185`；默认值和校验见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:753-763`；`DatabaseDescriptor.getFlushWriters()` 见 `DatabaseDescriptor.java:2456-2458`。
- `data_file_directories`：决定 non-local keyspace per-disk flush executor 数量和 `Directories` 候选目录。
- local system keyspace 独立目录：`PerDiskFlushExecutors` 根据 `DatabaseDescriptor.useSpecificLocationForLocalSystemData()` 为 local system keyspace 选择独立 executor。
- `memtable_cleanup_threshold`：默认 `1 / (memtable_flush_writers + 1)`；设置过低会导致更激进 flush 和更多 pending flush 压力，见 `DatabaseDescriptor.java:761-775`。

## Metrics、日志与诊断

- `TableMetrics.pendingFlushes`：`Flush` 构造递增，`PostFlush` 结束递减。
- `TableMetrics.memtableSwitchCount`：`Flush.run()` mark flushing 后递增。
- `TableMetrics.bytesFlushed`：`FlushRunnable.writeSortedContents()` 完成后按 writer bytes 递增。
- `TableMetrics.flushSizeOnDisk`：writer commit 后记录 on-disk bytes。
- flush enqueue 日志：`ColumnFamilyStore.logFlush()` 输出 keyspace/table/reason/memory usage。
- flush runnable 日志：`Flushing` 输出 `Writing ..., flushed range` 和 `Completed flushing ... for commitlog position ...`。
- drain 日志/状态：`StorageService.drain()` 通过 mode message 暴露 `flushing column families` 阶段。

## 运维关注点

- `PendingFlushes` 持续升高通常说明 flush writer、per-disk executor 或目标磁盘跟不上；同时检查 commitlog segment 是否无法回收。
- 多盘部署中，某个目录 near-full 会让对应 disk boundary 的 flush 更容易失败；没有 boundary 的表会通过 `getWriteableLocation()` 在候选目录中加权选择。
- `FSDiskFullWriteError` 表示存在目录但空间不足；`FSNoDiskAvailableForWriteError` 表示所有候选目录不可写或被 disallowed。
- drain 会在关闭写路径后等待 flush；慢盘会直接拉长 drain 和 shutdown 时间。
- 自定义 secondary index 的 non-CFS-backed flush 在 base flush 中同步执行，慢 index flush 会表现为 base table pending flush 偏高。

## 性能瓶颈

- `memtable_flush_writers` 太小会让多个 CF flush 排队；太大则可能放大随机写和磁盘队列竞争。
- per-disk runnable 数量随 disk boundaries 增加，多目录可并行，但最慢 runnable 决定整个 flush 完成时间。
- `SSTableMultiWriter.estimateSize()` 与 `Directories.getWriteableLocation()` 是写前空间选择，不能预测写入过程中空间被其他任务消耗。
- PostFlush 单线程确保 ordering，但如果前一个 flush 卡在错误传播、CommitLog discard 或 reclaim listener，会影响后续 flush Future 完成。
- 低 `memtable_cleanup_threshold` 会更早触发 flush，可能在慢盘下形成更多小 SSTables 和 compaction 压力。

## 常见故障

- Flush 报 no disk/full disk：检查 `data_file_directories` 对应文件系统可用空间、disallowed directories、磁盘挂载和 `DiskFailurePolicy`。
- CommitLog 不释放：确认 flush 是否失败；只要 `flushFailure != null`，PostFlush 不会调用 `discardCompletedSegments()`。
- drain 卡住：看 `MemtableFlushWriter`、`PerDiskMemtableFlushWriter_i` 和 `MemtablePostFlush` 线程栈，定位 barrier、writer I/O 或 PostFlush。
- SSTable 数量异常或分布不均：检查 `DiskBoundaries.isOutOfDate()`、ring version、directories version 和 misplaced SSTable 检查。
- base table flush 慢但磁盘正常：排查 non-CFS-backed secondary index `flushAllNonCFSBackedIndexesBlocking()`。

## 测试基线与缺口

- `test/unit/org/apache/cassandra/db/ColumnFamilyStoreTest.java`：普通 flush 和 memtable switch 行为基线。
- `test/unit/org/apache/cassandra/db/commitlog/CommitLogTest.java`：不可写目录/不可 flush memtable 下，失败后 commitlog 仍需 replay。
- `test/unit/org/apache/cassandra/io/sstable/SSTableFlushObserverTest.java`：flush writer observer begin/row/complete/abort 生命周期。
- `test/unit/org/apache/cassandra/db/DirectoriesTest.java`：writeable directory candidate 排序和空间 helper。
- `test/unit/org/apache/cassandra/service/DiskFailurePolicyTest.java`：best-effort disk failure 对 disallowed directory 的标记。
- `test/distributed/org/apache/cassandra/distributed/test/NodeToolTest.java`：`nodetool flush` command 可用性。
- `test/distributed/org/apache/cassandra/distributed/test/StreamsDiskSpaceTest.java`、`CompactionOverlappingSSTableTest.java`、`LeveledCompactionTaskTest.java`：外围 disk-space/flush 交互覆盖。
- gap：缺多目录低空间 + 慢盘 + boundary 重算 + flush writer saturation 的组合测试；缺 metrics/JMX 对 `PendingFlushes`、`BytesFlushed`、`flushSizeOnDisk` 的故障场景断言。
