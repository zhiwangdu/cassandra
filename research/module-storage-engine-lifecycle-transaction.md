# Module: Storage Engine Lifecycle Transaction

## 范围

本模块覆盖 SSTable 状态切换事务：`Tracker`/`View` 如何发布 memtable 与 SSTable 集合，`LifecycleTransaction` 如何管理 compaction/cleanup/scrub/anti-compaction/streaming/flush 的新旧 SSTable 可见性，`LogTransaction` 如何保证磁盘组件在崩溃后可清理。

不重复展开完整读路径、SSTable on-disk format 或各 compaction strategy 的选择算法；这些仍分别由 `module-read-path.md`、`module-sstable-compaction.md` 和后续 strategy 深水区覆盖。

## 设计目标

Storage lifecycle transaction 的目标是把“逻辑可见性”和“物理文件删除”拆开：

- 在内存中原子替换 `ColumnFamilyStore` 的 live SSTable view，避免读路径看到半更新集合。
- 在磁盘上记录 new/remove/commit/abort，使 compaction 或 streaming 中断后可按事务状态保留旧文件或新文件。
- 在 reader 引用释放前延迟删除旧 SSTable，避免 mmap/scanner/read metrics 仍在使用文件。
- 让 compaction、flush、stream receive、offline tools 共用同一套状态机，但允许 offline 场景用 dummy tracker。

## 解决的问题

- SSTable 是不可变文件集合，compaction 会把 originals 替换成新 SSTable；`LifecycleTransaction` 用 `originals`、`staged`、`logged`、`marked` 记录这些状态，字段集中在 `src/java/org/apache/cassandra/db/lifecycle/LifecycleTransaction.java:128-151`。
- 读路径需要稳定 view；`View` 是不可变结构，更新通过 `Tracker.apply()` 的函数替换完成，注释见 `src/java/org/apache/cassandra/db/lifecycle/View.java:52-60`，锁定与 swap 见 `src/java/org/apache/cassandra/db/lifecycle/Tracker.java:153-175`。
- 磁盘文件不能只靠内存状态判断；`LogTransaction` 在事务日志中记录 ADD/REMOVE/COMMIT/ABORT 和 CRC，注释见 `src/java/org/apache/cassandra/db/lifecycle/LogTransaction.java:66-100`。
- SSTable 删除必须等引用释放；`SSTableTidier` 在 reader tidying 时清理 components，并在删除旧文件后递减 total disk space，见 `src/java/org/apache/cassandra/db/lifecycle/LogTransaction.java:350-421`。
- 启动时要处理未完成事务；`ColumnFamilyStore.scrubDataDirectories()` 调用 `LifecycleTransaction.removeUnfinishedLeftovers(metadata)`，失败会阻止启动，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:780-825`。

## 设计取舍

- `View` 选择不可变快照加 `Tracker.viewUpdateLock`，而不是让读路径持复杂锁；写侧串行执行 `apply()`，读侧读取 volatile view，见 `src/java/org/apache/cassandra/db/lifecycle/Tracker.java:82-95` 和 `src/java/org/apache/cassandra/db/lifecycle/Tracker.java:153-175`。
- `LifecycleTransaction` 把变更分成 staged 和 logged：`checkpoint()` 才让 staged 进入 live view；这支持 compaction writer 预打开新 SSTable，同时保留回滚能力，见 `src/java/org/apache/cassandra/db/lifecycle/LifecycleTransaction.java:85-126` 和 `src/java/org/apache/cassandra/db/lifecycle/LifecycleTransaction.java:339-379`。
- commit 在 transactional graph 中必须先发生；源码注释说明 commit 之后已经进入不可回滚区间，见 `src/java/org/apache/cassandra/db/lifecycle/LifecycleTransaction.java:75-80` 和 `src/java/org/apache/cassandra/db/lifecycle/LifecycleTransaction.java:229-255`。
- total disk space 不是在 live set 移除时立即下降；旧文件真正删除时才在 tidier 中递减，size tracking 说明见 `src/java/org/apache/cassandra/db/lifecycle/Tracker.java:177-227`。
- Stream receive 当前使用 offline transaction，然后手动 `cfs.addSSTables()` 发布；源码注释明确这是后续可重构点，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:79-88` 和 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:230-260`。
- Anti-compaction 多个 writer 共享同一个 transaction；`SharedTxn` 禁止各 writer 单独 `prepareToCommit()`、`checkpoint()`、`obsoleteOriginals()` 和 `commit()`，避免部分替换可见，见 `src/java/org/apache/cassandra/db/compaction/CompactionManager.java:1752-1784`。

## 核心类

| 类 | 作用 |
|---|---|
| `Tracker` | `ColumnFamilyStore` 的 lifecycle owner，持有 volatile `View`、通知订阅者、标记 compacting、替换 flushed SSTable 和更新 disk metrics；字段见 `src/java/org/apache/cassandra/db/lifecycle/Tracker.java:82-95` |
| `View` | 不可变的 memtable/SSTable 快照，包含 live/flushing memtables、compacting set、SSTable map、canonical map 和 interval tree；字段见 `src/java/org/apache/cassandra/db/lifecycle/View.java:64-84` |
| `LifecycleTransaction` | SSTable 逻辑事务，管理 originals、新 reader、obsolete reader、checkpoint、commit、abort 和 split/cancel；构造与状态字段见 `src/java/org/apache/cassandra/db/lifecycle/LifecycleTransaction.java:128-197` |
| `LogTransaction` | 磁盘事务日志，记录新增/删除 SSTable 组件并执行 crash cleanup；事务日志格式见 `src/java/org/apache/cassandra/db/lifecycle/LogTransaction.java:66-100` |
| `LogTransaction.SSTableTidier` | reader 引用完全释放后的组件删除器和 disk metric cleanup，见 `src/java/org/apache/cassandra/db/lifecycle/LogTransaction.java:350-421` |
| `SSTableRewriter` | compaction writer 侧通过 transaction update/checkpoint 发布早开 reader；compaction test 通过 stacktrace 验证 `switchWriter`/`maybeReopenEarly` 会触发 checkpoint，见 `test/unit/org/apache/cassandra/db/compaction/CompactionTaskTest.java:218-329` |
| `CompactionTask` | online compaction 持有 transaction，扫描 originals，writer finish 后提交新 SSTable 并更新 compaction history/metrics，见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:120-305` |
| `CassandraStreamReceiver` | streaming 接收端使用 offline transaction 追踪新文件，完成后根据 MV/CDC/stream-to-memtable 决定走 write path 或 addSSTables，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:103-167` 和 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:236-301` |

## 核心接口

- `ILifecycleTransaction`：transaction 对 writer 暴露的最小接口，包含 `checkpoint()`、`update()`、`current()`、`obsolete()`、`obsoleteOriginals()`、`originals()`、`isObsolete()` 和 `isOffline()`，见 `src/java/org/apache/cassandra/db/lifecycle/ILifecycleTransaction.java:27-38`。
- `LifecycleNewTracker`：writer 创建新 SSTable 前调用 `trackNew()`，不再需要时调用 `untrackNew()`，用于 LogTransaction 记录 ADD，见 `src/java/org/apache/cassandra/db/lifecycle/LifecycleNewTracker.java:25-47`。
- `SSTableMultiWriter`：flush/compaction/streaming 输出 writer 的 transaction 接口，`finish()` 返回 finished readers，定义见 `src/java/org/apache/cassandra/io/sstable/SSTableMultiWriter.java:27-51`。
- `Transactional`：`LifecycleTransaction` 和 writer 都基于 `Transactional.AbstractTransactional` 的 prepare/commit/abort/close 状态机；相关测试基类覆盖状态组合，见 `test/unit/org/apache/cassandra/db/lifecycle/LifecycleTransactionTest.java:252-410`。
- `WrappedLifecycleTransaction`：代理 transaction 调用，anti-compaction 用它构造 `SharedTxn` 来屏蔽部分提交方法，类定义见 `src/java/org/apache/cassandra/db/lifecycle/WrappedLifecycleTransaction.java:28-116`。

## 核心数据结构

- `View.liveMemtables` / `View.flushingMemtables`：memtable switch/flush 的内存可见状态，字段见 `src/java/org/apache/cassandra/db/lifecycle/View.java:64-70`。
- `View.sstables` / `sstablesMap` / `compactMap` / `intervalTree`：live SSTable 的 identity map、canonical map 和 range 查询索引，字段见 `src/java/org/apache/cassandra/db/lifecycle/View.java:72-84`。
- `LifecycleTransaction.State`：每个 transaction 内部有 `staged.update`、`staged.obsolete`、`logged.update`、`logged.obsolete`，`log()` 把 staged 合并到 logged，见 `src/java/org/apache/cassandra/db/lifecycle/LifecycleTransaction.java:85-126`。
- `LifecycleTransaction.ReaderState`：测试可见结构，记录 reader 的 logged/staged 动作、当前可见和下次 checkpoint 后可见 reader，定义见 `src/java/org/apache/cassandra/db/lifecycle/LifecycleTransaction.java:645-697`。
- `LogRecord` / transaction log file：`LogTransaction` 为 ADD/REMOVE/COMMIT/ABORT 写 CRC 记录，并在 `removeUnfinishedLeftovers()` 中按最终记录决定清理 old/new 文件，入口见 `src/java/org/apache/cassandra/db/lifecycle/LogTransaction.java:483-568`。
- `Refs<SSTableReader>`：读/compaction/streaming 用 reader refs 防止正在使用的 SSTable 被删除；compaction 主循环创建 refs，见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:199-205`，测试验证 canonical view 中 SSTable 仍可引用见 `test/unit/org/apache/cassandra/db/compaction/CompactionTaskTest.java:264-272`。

## 生命周期

```text
online compaction transaction:
  CompactionStrategyManager/CompactionManager select SSTables
    -> Tracker.tryModify(sstables, OperationType.COMPACTION)
       -> View.permitCompacting(...)
       -> View.updateCompacting(empty, originals)
       -> new LifecycleTransaction(tracker, op, originals)
    -> CompactionTask.runMayThrow()
       -> identify fully expired SSTables
       -> writer append rows
       -> writer.finish()/SSTableRewriter updates transaction
       -> transaction.prepareToCommit()
          -> checkpoint()
          -> LogTransaction.prepareToCommit()
       -> transaction.commit()
          -> LogTransaction.commit()
          -> mark obsolete originals
          -> update size tracking and notify SSTables changed
       -> post cleanup unmark compacting and close log
```

```text
abort path:
  transaction.abort()
    -> abort obsoletion tidiers
    -> LogTransaction.abort()
    -> mark new/update readers obsolete
    -> restore original reader instances
    -> Tracker.apply(updateLiveSet + updateCompacting)
    -> notify SSTables changed
    -> release refs and clear staged/logged state
```

```text
flush path:
  ColumnFamilyStore.flush()
    -> LifecycleTransaction.offline(OperationType.FLUSH)
    -> Flushing.flushRunnables(cfs, memtable, txn)
       -> memtable.setFlushTransaction(txn)
       -> createFlushWriter(..., txn, descriptor, ...)
    -> prepare/commit writers
    -> txn.prepareToCommit()
    -> txn.commit()
    -> ColumnFamilyStore.replaceFlushed(...) publishes finished SSTables
```

Flush offline transaction use is visible in `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1288-1372`; `Flushing.flushRunnables()` stores the transaction on the memtable and constructs writers with it in `src/java/org/apache/cassandra/db/memtable/Flushing.java:57-119`。

## 调用链

- `Tracker.tryModify()`：检查 `View.permitCompacting()`，把 originals 放入 compacting set，并返回 `LifecycleTransaction`；失败返回 null，见 `src/java/org/apache/cassandra/db/lifecycle/Tracker.java:115-130`。
- `LifecycleTransaction.checkpoint()`：验证 originals 当前版本未被替换，标记 fresh readers compacting，更新 live set，把 staged 合并到 logged，并 release 被替换 reader，见 `src/java/org/apache/cassandra/db/lifecycle/LifecycleTransaction.java:339-379`。
- `LifecycleTransaction.update()` / `obsolete()`：把 reader 加入 staged update 或 staged obsoletion，包含 original/non-original 与 current-version 断言，见 `src/java/org/apache/cassandra/db/lifecycle/LifecycleTransaction.java:382-421`。
- `LifecycleTransaction.prepareToCommit()`：调用 `checkpoint()`，为 obsolete originals 创建 tidiers，再 prepare log transaction，见 `src/java/org/apache/cassandra/db/lifecycle/LifecycleTransaction.java:215-227`。
- `LifecycleTransaction.commit()`：先提交 `LogTransaction`，然后 mark obsolete、更新 metrics、执行 hooks、release refs、通知 subscribers，见 `src/java/org/apache/cassandra/db/lifecycle/LifecycleTransaction.java:229-255`。
- `LifecycleTransaction.abort()`：abort log，删除新文件，恢复 originals，unmark compacting，并通知 view 变化，见 `src/java/org/apache/cassandra/db/lifecycle/LifecycleTransaction.java:259-299`。
- `Tracker.replaceFlushed()`：flush 完成后把 memtable 从 flushing set 移除、把新 SSTable 加入 live set，更新 size tracking 和 notifications，见 `src/java/org/apache/cassandra/db/lifecycle/Tracker.java:407-442`。
- `LogTransaction.removeUnfinishedLeftovers()`：启动和 standalone 工具扫描 txn log，按完整 commit/abort 或未完成状态清理临时文件，见 `src/java/org/apache/cassandra/db/lifecycle/LogTransaction.java:483-568`。
- `CassandraStreamReceiver.finished()`：不走 write path 时先 `finishTransaction()`，再 `cfs.addSSTables(readers)` 并清 row/counter cache；走 write path 时 cleanup 强制 flush 后 abort transaction 删除 streamed SSTables，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:236-301`。
- `PendingRepairManager.RepairFinishedCompactionTask`：transient repaired SSTable 完成后可 `obsoleteOriginals()` 并 `finish()`；metadata mutate 场景只用 transaction 防止被其他 compaction 抢占，最后 abort/unmark，见 `src/java/org/apache/cassandra/db/compaction/PendingRepairManager.java:516-547`。

## 配置项

| 配置项 | 定义/读取位置 | lifecycle 影响 |
|---|---|---|
| `sstable_preemptive_open_interval` | `src/java/org/apache/cassandra/config/Config.java:460-462` | 控制 compaction 输出 SSTable 早开；早开会通过 `SSTableRewriter` 触发 transaction checkpoint，测试覆盖见 `test/unit/org/apache/cassandra/db/compaction/CompactionTaskTest.java:218-329` |
| `snapshot_before_compaction` | `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:135-139` | compaction 改写前是否先 snapshot，影响 originals 被 obsolete 前的恢复/空间策略 |
| `concurrent_compactors` | `src/java/org/apache/cassandra/config/Config.java:335` | 并发 compaction 越高，同时持有 compacting set 和 transaction log 的任务越多 |
| `compaction_throughput` | `src/java/org/apache/cassandra/config/Config.java:336-337` | compaction 主循环限速，延长 transaction 持有 originals 的时间 |
| `min_free_space_per_drive` / `max_space_usable_for_compactions_in_percentage` | `src/java/org/apache/cassandra/config/Config.java:338-344` | 空间不足会影响 compaction scope，避免在旧 SSTable 删除前写出过多新文件 |
| standalone tool 运行目录 | `src/java/org/apache/cassandra/tools/StandaloneUpgrader.java:118-137`、`src/java/org/apache/cassandra/tools/StandaloneScrubber.java:166-195` | offline tool 使用 offline lifecycle transaction，结束后等待删除完成 |

## Metrics

- `StorageMetrics.load` 和 `StorageMetrics.uncompressedLoad`：`Tracker.updateSizeTracking()` 在 added/deleted SSTable 上更新全局 load，见 `src/java/org/apache/cassandra/db/lifecycle/Tracker.java:177-201`。
- `TableMetrics.liveDiskSpaceUsed`、`uncompressedLiveDiskSpaceUsed`、`totalDiskSpaceUsed`：同一方法更新表级磁盘指标；total disk 在旧文件真正删除时才递减，见 `src/java/org/apache/cassandra/db/lifecycle/Tracker.java:202-227`。
- `TableMetrics.flushSizeOnDisk`：flush 完成后 `ColumnFamilyStore` 记录本次 writer 输出大小，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1354-1362`。
- `TableMetrics.compactionBytesWritten`：compaction 完成后按 writer bytes 更新，见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:297-299`。
- `TableMetrics.bytesAnticompacted`：anti-compaction 入口记录待拆分 unrepaired SSTable 字节，见 `src/java/org/apache/cassandra/db/compaction/CompactionManager.java:1704-1706`。

## 日志

- `LifecycleTransaction` 在取消、拆分、checkpoint、update、obsolete 等状态变化处有 trace 日志，例子见 `src/java/org/apache/cassandra/db/lifecycle/LifecycleTransaction.java:339-344`、`src/java/org/apache/cassandra/db/lifecycle/LifecycleTransaction.java:382-407`、`src/java/org/apache/cassandra/db/lifecycle/LifecycleTransaction.java:518-555`。
- `LogTransaction.delete()` 对 startup cleanup 使用 trace，对运行时删除失败记录 error 并传播 FS 错误，见 `src/java/org/apache/cassandra/db/lifecycle/LogTransaction.java:244-272`。
- `LogTransaction.TransactionTidier` 在未完成事务被 GC/close 时 abort，删除失败会记录 error 并提示 GC/restart retry，见 `src/java/org/apache/cassandra/db/lifecycle/LogTransaction.java:275-335`。
- Anti-compaction 记录开始、完成、取消和异常，见 `src/java/org/apache/cassandra/db/compaction/CompactionManager.java:1694-1720` 和 `src/java/org/apache/cassandra/db/compaction/CompactionManager.java:1849-1882`。
- Stream receive 完成后 debug 记录收到的 SSTables，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:256-260`。

## 运维关注点

- 启动失败并提示 transaction leftovers 时，优先检查 data directory 中 txn log 和 SSTable component 是否一致；启动路径会调用 `LifecycleTransaction.removeUnfinishedLeftovers(metadata)`，失败抛 `StartupException`，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:780-825`。
- live disk 与 total disk 短时间不一致是正常现象：live view 已移除旧 SSTable，但 total disk 要等 tidier 删除文件后下降，见 `src/java/org/apache/cassandra/db/lifecycle/Tracker.java:202-227`。
- compaction 长时间运行会让 originals 一直在 compacting set 中，其他 compaction/repair/anti-compaction 的 `tryModify()` 会失败或等待；测试覆盖 blocked acquisition，见 `test/unit/org/apache/cassandra/db/repair/PendingAntiCompactionTest.java:452-493`。
- stream receive 遇到 MV/CDC/stream-to-memtable 会把 streamed SSTable 内容写回正常 write path，cleanup 时强制 flush 再 abort offline transaction 删除临时 SSTable，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:185-200` 和 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:291-301`。
- standalone scrub/upgrader/splitter 使用 offline transaction；运行前应确认目标表 offline 或遵循工具约束，否则 live CFS 不会自动感知 offline 改写。

## 性能瓶颈

- `Tracker.apply()` 用 fair lock 串行化 view update；flush、compaction、drop SSTables、memtable switch 在高频发生时会竞争同一个 update path，见 `src/java/org/apache/cassandra/db/lifecycle/Tracker.java:82-95` 和 `src/java/org/apache/cassandra/db/lifecycle/Tracker.java:153-175`。
- `checkpoint()` 会更新 live set、compacting set、release refs 并可能触发 subscribers；preemptive open 频率过高会增加 view churn。
- 删除旧 SSTable 依赖 reader refs 释放和 nonPeriodicTasks executor；mmap 或长 scanner 会延迟物理空间释放，retry 入口见 `src/java/org/apache/cassandra/db/lifecycle/LifecycleTransaction.java:627-643`。
- transaction log 覆盖多个 data directory 时每个目录都有 log 文件；startup cleanup 需要校验多个 final records，一致性检查失败会保守保留文件，测试覆盖见 `test/unit/org/apache/cassandra/db/lifecycle/LogTransactionTest.java:641-821`。
- anti-compaction 多 writer 共享 transaction 且关闭 early open，避免状态错乱但牺牲一部分预打开收益，见 `src/java/org/apache/cassandra/db/compaction/CompactionManager.java:1752-1784`。

## 常见故障

- `Tracker.tryModify()` 返回 null：目标 SSTable 已经 compacting、已被替换或已 marked compacted；判断逻辑在 `View.permitCompacting()`，见 `src/java/org/apache/cassandra/db/lifecycle/View.java:266-297`，测试见 `test/unit/org/apache/cassandra/db/lifecycle/TrackerTest.java:93-114`。
- transaction abort 后新 SSTable 文件消失、旧 SSTable 保留：这是 log abort 语义；测试覆盖 only-new/only-old/multiple-folder abort，见 `test/unit/org/apache/cassandra/db/lifecycle/LogTransactionTest.java:387-459`。
- commit 后旧文件仍暂时存在：reader refs 尚未释放或 deletion retry 未完成；`LifecycleTransaction.waitForDeletions()` 可等待 executor 中已排队删除，见 `src/java/org/apache/cassandra/db/lifecycle/LifecycleTransaction.java:636-643`。
- corrupted/mismatched txn log：startup cleanup 只在可以证明 final record 语义时删除文件；partial/mismatched records 测试见 `test/unit/org/apache/cassandra/db/lifecycle/LogTransactionTest.java:641-821`。
- compaction 混合 repaired/unrepaired/pending repair SSTable：`AbstractCompactionTask` 禁止混合不兼容集合，测试见 `test/unit/org/apache/cassandra/db/compaction/CompactionTaskTest.java:337-388`。
- fully expired SSTable 在 checkpoint 后过早不可引用：`CompactionTaskTest.testFullyExpiredSSTablesAreNotReleasedPrematurely` 验证 canonical view 中 SSTable 仍可 `tryRef()`，见 `test/unit/org/apache/cassandra/db/compaction/CompactionTaskTest.java:158-329`。

## 测试用例

- `test/unit/org/apache/cassandra/db/lifecycle/LifecycleTransactionTest.java`：staged/logged 状态、checkpoint 可见性、cancel/split、commit/abort 后 reader refs 与 compacting set。
- `test/unit/org/apache/cassandra/db/lifecycle/TrackerTest.java`：`tryModify()` 排他、drop SSTables、memtable replacement、notifications 和 size metrics。
- `test/unit/org/apache/cassandra/db/lifecycle/ViewTest.java`：compacting set、live set replacement、memtable switch/flush view 函数。
- `test/unit/org/apache/cassandra/db/lifecycle/LogTransactionTest.java`：new/old commit/abort、multiple data folders、startup leftover cleanup、corrupt checksum/final record 行为。
- `test/unit/org/apache/cassandra/db/lifecycle/RealTransactionsTest.java`：真实 rewrite finished/aborted 与 flush 文件结果。
- `test/unit/org/apache/cassandra/db/compaction/CompactionTaskTest.java`：compaction history id、interruption abort、checkpoint 后 canonical refs、mixed repair-state failure 和 offline compaction。
- `test/unit/org/apache/cassandra/db/repair/PendingAntiCompactionTest.java`：anti-compaction acquisition 被已有 compaction 阻塞或取消后的行为。
- `test/unit/org/apache/cassandra/db/streaming/CassandraStreamReceiverTest.java`：stream receiver write path/addSSTables/MV/CDC 相关行为。

## 待继续

- 继续补本地读路径与 `ColumnFamilyStore.ViewFragment`、row cache/key cache、memtable/SSTable merge 的细节。
- 在 SSTable/compaction 模块继续展开 STCS/LCS/TWCS/UCS 策略选择、BTI/Big format 差异和旧格式迁移。
- 可选补一个自动 drift 检查，验证 `LogTransaction.removeUnfinishedLeftovers()` 覆盖的 txn log final-record 组合与 source-map 中的测试矩阵同步。
