# Module: Memtable PostFlush And Flush Triggers

## 范围

本模块补齐 memtable/flush 第二层细节：`ColumnFamilyStore.FlushReason` 的触发矩阵、`switchMemtableIfCurrent()` 与 `forceFlush()` 的分支、`Flush` 构造时如何协调 base/index memtable、`PostFlush` 如何在 flush latch 后清理 CommitLog segment、`replaceFlushed()` 如何把 flushing memtable 转为 live SSTable，以及 `reclaim()` 如何在 read barrier 后释放 memtable。具体 memtable 实现差异见 `research/module-memtable-implementations.md`，flush writer/SSTable 输出主线见 `research/module-memtable-flush.md`。

## 设计目标

- Flush reason 要覆盖 commitlog dirty、memtable 空间/周期、index build、view build、user/nodetool、startup/drain/snapshot/truncate/drop、streaming、validation、anti-compaction、schema/local range change 和测试场景；枚举见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:224-254`。
- `switchMemtable()` 只负责切换、排队 flush runnable 和排队 post-flush future；调用者等待的 future 必须等 flush 与 post-flush 清理全部完成，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1025-1043`。
- `Flush` 构造要一次性切换 base table 和所有 CFS-backed index memtable，并为它们共享同一个 write barrier 与 commitlog upper-bound decision，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1167-1227`。
- `Flush.run()` 等待 write barrier 后，才把旧 memtable 移入 flushing view、写出 SSTable、最后释放 `PostFlush` latch；执行路径见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1229-1274`。
- `PostFlush.call()` 必须在 flush 成功时才 discard completed CommitLog segments；如果 flush failure 被记录，则不清理 CommitLog，并把异常重新抛出，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1138-1163`。
- Memtable 内存释放要等 flush complete 和 read barrier，避免仍在读旧 memtable 的 reader 看到被 discard 的内存；`reclaim()` 见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1391-1404`。

## 解决的问题

- Memtable switch 不能直接删除旧 memtable：old memtable 在 flush 前仍可能被已有 read op-order 读到；`reclaim()` 为此创建 read barrier 并在 postFlush future 完成后等待，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1391-1404`。
- CommitLog segment 不能在 writer 成功前清理：`PostFlush` 只在 `flushFailure == null` 且存在 main memtable 时取 final upper bound 并 discard segment，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1147-1153`。
- 一次 flush 可能没有 SSTable 输出，例如 clean memtable、truncate 或 batchlog tombstone 优化；flushMemtable 对 clean/truncate 直接 `replaceFlushed(..., emptyList)` 并 reclaim，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1279-1285`。
- Base table 与 table-backed indexes 必须在同一 barrier 下切换，以便 post-flush future 对 switch/flush 的 ordering 有意义；构造函数遍历 `concatWithIndexes()` 见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1204-1215`。
- CommitLog dirty flush 不是普通用户 flush：`forceFlush(CommitLogPosition)` 只关心当前 memtable 是否可能包含目标位置之前的数据，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1084-1091`。
- Failed flush 不应造成数据丢失；commitlog out-of-order flush recovery 测试明确期望失败后仍有 commitlog 可 replay，见 `test/unit/org/apache/cassandra/db/commitlog/CommitLogTest.java:1120-1200`。

## 设计取舍

- `switchMemtable()` 不同步执行 flush，而是用 flush executor 和 post-flush executor 串接 future；写入线程只在必要同步块中切换 view，后续等待由 future 表达，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1025-1043`。
- `forceFlush(reason)` 如果 base/index 当前 memtable 都 clean，则不切换，只返回当前 post-flush ordering future；这避免空 flush 频繁扰动 view，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1065-1077`。
- `switchMemtableOrNotify()` 允许 schema/local range change 只通知当前 memtable，而不是强制 flush；是否切换由具体 `Memtable.shouldSwitch(reason)` 决定，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:997-1006`。
- 默认 allocator memtable 在 schema change 时只有 comparator 或 memtable factory 改变才切换，在 owned ranges change 时默认不切换；实现见 `src/java/org/apache/cassandra/db/memtable/AbstractAllocatorMemtable.java:130-143`。
- `flushLargestMemtable()` 从所有 active memtables 和 index memtables 中选择 on/off heap ownership ratio 最大者，而不是简单按字节数排序；这更贴近内存池压力，见 `src/java/org/apache/cassandra/db/memtable/AbstractAllocatorMemtable.java:249-318`。
- Non-CFS-backed secondary indexes 在 base flush barrier 完成后同步 flush；代码说明它们不能像 CFS-backed index 一样精确协调 commitlog barrier，执行见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1307-1314`。

## 核心类

| 类 | 作用 |
|---|---|
| `ColumnFamilyStore.FlushReason` | flush 触发原因枚举，覆盖 commitlog、memtable、index、view、operator、lifecycle、streaming/repair 和 tests，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:224-254` |
| `ColumnFamilyStore.Flush` | flush runnable，负责 write barrier、mark flushing、flush base/index memtable、设置 postFlush failure/latch，定义和执行见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1167-1274` |
| `ColumnFamilyStore.PostFlush` | post-flush callable，串行等待 flush latch、discard commitlog、递减 pendingFlushes、传播失败，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1123-1163` |
| `ColumnFamilyStore` | flush/switch API、trigger 接口、replace/reclaim helper 所在类，flush API 见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:997-1116` |
| `Tracker` | 把 memtable 从 live 移到 flushing，再用 flushed SSTables 替换 flushing memtable，见 `src/java/org/apache/cassandra/db/lifecycle/Tracker.java:407-427` |
| `View` | 不可变 storage view，定义 `markFlushing()` 和 `replaceFlushed()` view transform，见 `src/java/org/apache/cassandra/db/lifecycle/View.java:330-366` |
| `CommitLog` | PostFlush 调用 `discardCompletedSegments()` 标记 table 已清理的 commitlog 范围，见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:353-362` |
| `AbstractAllocatorMemtable` | 周期 flush、largest memtable flush 和 schema/range change `shouldSwitch()`，见 `src/java/org/apache/cassandra/db/memtable/AbstractAllocatorMemtable.java:220-318` |
| `TrieMemtable` | trie allocated size threshold 达到时主动请求 `MEMTABLE_LIMIT` flush，见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:183-205` |
| `MemtablePool` | 注册 `BlockedOnAllocation`/`PendingFlushTasks` 并持有 cleaner thread，见 `src/java/org/apache/cassandra/utils/memory/MemtablePool.java:55-75` |

## 核心接口

- `ColumnFamilyStore.switchMemtableIfCurrent(Memtable, FlushReason)`：只有传入 memtable 仍是 current 时才切换，否则返回当前 flush ordering future；实现见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1014-1023`。
- `ColumnFamilyStore.forceFlush(FlushReason)`：用户/系统强制 flush 入口，只有任一 base/index memtable dirty 才切换，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1065-1077`。
- `ColumnFamilyStore.forceFlush(CommitLogPosition)`：commitlog segment manager 使用的 dirty-position flush，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1084-1091`。
- `Memtable.Owner.signalFlushRequired()`：memtable 实现或 memory cleaner 反向通知 owner 触发 flush，接口见 `src/java/org/apache/cassandra/db/memtable/Memtable.java:154-170`，CFS 实现见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1436-1439`。
- `Keyspace.flush(FlushReason)`：keyspace 级 flush all tables，见 `src/java/org/apache/cassandra/db/Keyspace.java:681-686`。
- `Tracker.replaceFlushed()`：flush 成功后把 SSTables setupOnline、backup、更新 view 和 size tracking，见 `src/java/org/apache/cassandra/db/lifecycle/Tracker.java:412-427`。

## 核心数据结构

- `OpOrder.Barrier writeBarrier`：把 barrier issue 前开始的写入导向旧 memtable，并允许 flush 等待这些写完成；创建和 issue 见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1190-1224`。
- `AtomicReference<CommitLogPosition> commitLogUpperBound`：base 和 index memtable 共享的 commitlog upper-bound holder，构造时传给新 memtables 和 old memtables，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1204-1219`。
- `FutureTask<CommitLogPosition> postFlushTask`：调用者等待 flush ordering 的 future，构造和提交见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1025-1043`、`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1223-1227`。
- `CountDownLatch PostFlush.latch`：flush runnable 完成写出后释放 post-flush 清理，字段和等待见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1123-1145`。
- `View.liveMemtables` / `View.flushingMemtables` / `View.sstablesMap`：flush 前后 view transform 的目标集合，`markFlushing()`/`replaceFlushed()` 见 `src/java/org/apache/cassandra/db/lifecycle/View.java:330-366`。
- `LifecycleTransaction.offline(OperationType.FLUSH)`：flush writer commit/abort 的 transaction 边界，使用见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1292-1376`。

## 生命周期

```text
Trigger:
  -> memtable implementation / operator / subsystem calls forceFlush or signalFlushRequired
  -> ColumnFamilyStore.switchMemtable(reason)
     -> logFlush(reason)
     -> new Flush(false)
        -> pendingFlushes.inc()
        -> writeOrder.newBarrier()
        -> for base + index CFS:
           -> create new memtable(shared upper-bound)
           -> data.switchMemtable(...)
           -> oldMemtable.switchOut(writeBarrier, shared upper-bound)
        -> setCommitLogUpperBound(shared upper-bound)
        -> writeBarrier.issue()
        -> create PostFlush + FutureTask
     -> flushExecutor.execute(flush)
     -> postFlushExecutor.execute(postFlushTask)

Flush executor:
  -> writeBarrier.markBlocking()
  -> writeBarrier.await()
  -> tracker.markFlushing(oldMemtable)
  -> flushMemtable(base first, then index CFS)
     -> Flushing.flushRunnables(...)
     -> writer prepare/commit/finished
     -> cfs.replaceFlushed(oldMemtable, newSSTables)
     -> reclaim(oldMemtable)
  -> postFlush.latch.decrement()

Post-flush executor:
  -> latch.await()
  -> if no flushFailure:
     -> CommitLog.discardCompletedSegments(tableId, lower, upper)
  -> pendingFlushes.dec()
  -> throw flushFailure if present
```

## 调用链

- Space-pressure trigger：`MemtablePool` cleaner uses `AbstractAllocatorMemtable::flushLargestMemtable`, which chooses largest ownership ratio and calls `owner.signalFlushRequired(..., MEMTABLE_LIMIT)`；见 `src/java/org/apache/cassandra/db/memtable/AbstractAllocatorMemtable.java:84`、`src/java/org/apache/cassandra/db/memtable/AbstractAllocatorMemtable.java:249-318`。
- Period trigger：`AbstractAllocatorMemtable.flushIfPeriodExpired()` checks table `memtableFlushPeriodInMs` and calls `signalFlushRequired(..., MEMTABLE_PERIOD_EXPIRED)` if dirty；见 `src/java/org/apache/cassandra/db/memtable/AbstractAllocatorMemtable.java:220-241`。
- Trie threshold trigger：`TrieMemtable.put()` detects allocated-size threshold and asks owner for `MEMTABLE_LIMIT` flush once per memtable；见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:183-205`。
- Commitlog recycling trigger：`AbstractCommitLogSegmentManager` builds a per-table flush map and calls either `forceFlush(COMMITLOG_DIRTY)` or `forceFlush(maxCommitLogPosition)`；见 `src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogSegmentManager.java:463-495`。
- Operator trigger：`StorageService.forceKeyspaceFlush()` maps nodetool flush to `USER_FORCED`，见 `src/java/org/apache/cassandra/service/StorageService.java:4738-4766`。
- Drain trigger：`StorageService` queues `forceFlush(DRAIN)` during drain，见 `src/java/org/apache/cassandra/service/StorageService.java:5919-5951`。
- Streaming trigger：`StreamSession.flushSSTables()` calls `forceFlush(STREAMING)`；stream receiver calls `forceBlockingFlush(STREAMS_RECEIVED)` after receiving files，见 `src/java/org/apache/cassandra/streaming/StreamSession.java:1242-1260`、`src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:298`。
- Repair trigger：validation and anti-compaction force `VALIDATION` / `ANTICOMPACTION` flushes before reading or splitting SSTables；见 `src/java/org/apache/cassandra/db/repair/CassandraValidationIterator.java:201`、`src/java/org/apache/cassandra/db/repair/PendingAntiCompaction.java:373`。
- Index/view trigger：secondary index build/remove and view build force table/index flushes using index/view reasons；见 `src/java/org/apache/cassandra/index/SecondaryIndexManager.java:420`、`src/java/org/apache/cassandra/index/SecondaryIndexManager.java:968`、`src/java/org/apache/cassandra/db/view/ViewBuilder.java:98`。
- Truncate/drop trigger：truncate flushes dirty durable memtables before truncation; unload/drop flushes or dumps depending durability，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:2768-2790`、`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:2842-2851`。

## 配置项

| 配置项 | 定义位置 | 影响 |
|---|---|---|
| `memtable_flush_writers` | `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:753-759`、`conf/cassandra.yaml:885-912` | flush executor 并发；过大可能产生更多小 SSTable |
| `memtable_cleanup_threshold` | `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:761-775`、`conf/cassandra.yaml:801-812` | `MemtablePool` 触发 cleaner 的阈值 |
| `memtable_heap_space` / `memtable_offheap_space` | `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:583-594`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4054-4066` | largest memtable trigger 使用的内存池上限 |
| 表级 `memtable_flush_period_in_ms` | `src/java/org/apache/cassandra/schema/TableParams.java:81`、`src/java/org/apache/cassandra/schema/TableParams.java:428-431` | 周期 flush trigger |
| 表级 `durable_writes` | `src/java/org/apache/cassandra/db/Mutation.java:266-269` | truncate/drop 是否必须 flush dirty commitlog-backed memtable |
| 表级 `memtable` | `src/java/org/apache/cassandra/schema/TableParams.java:89` | schema change 是否导致当前 memtable switch 取决于 factory 是否变化 |

## Metrics

- `TableMetrics.pendingFlushes` 在 `Flush` 构造时递增、`PostFlush` 完成/失败后递减；见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1190`、`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1155`。
- `TableMetrics.memtableSwitchCount` 在 old memtable 从 live 移到 flushing 后递增，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1244-1248`。
- `TableMetrics.flushSizeOnDisk` 在每个 committed writer 后更新，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1361-1364`。
- `MemtablePool.BlockedOnAllocation` 和 `MemtablePool.PendingFlushTasks` 由 memory pool 注册，见 `src/java/org/apache/cassandra/utils/memory/MemtablePool.java:55-75`。
- `TableMetrics.bytesFlushed` 由 flush runnable 写出完成时更新，见 `src/java/org/apache/cassandra/db/memtable/Flushing.java:176-184`。
- `liveDiskSpaceUsed` 等 SSTable size metrics 在 `Tracker.replaceFlushed()` 后更新，见 `src/java/org/apache/cassandra/db/lifecycle/Tracker.java:412-427`。

## 日志

- `logFlush()` 在每次 enqueue flush 时记录 keyspace/table、reason 和当前 memtable usage，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1045-1058`。
- `Flush` 构造、等待 barrier、signal post flush 和 finish 都有 trace 日志，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1183-1187`、`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1231-1273`。
- `flushLargestMemtable()` 记录 used/live/flushing/selected ownership ratio，见 `src/java/org/apache/cassandra/db/memtable/AbstractAllocatorMemtable.java:287-297`。
- `TrieMemtable.put()` 由于 trie size limit 调度 flush 时记录 info，见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:192-195`。
- Flush 写出和完成日志在 `Flushing.FlushRunnable.writeSortedContents()`，见 `src/java/org/apache/cassandra/db/memtable/Flushing.java:151-184`。
- PostFlush 的 CommitLog segment discard 有 trace 日志，见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:353-362`。

## 运维关注点

- `pendingFlushes` 高但 `BlockedOnAllocation` 低，通常是 flush queue backlog；两者都高说明写入已经在等 memtable pool 清理。
- `CommitLog` segments 无法回收不一定是 commitlog 自身问题；若 flush failed，`PostFlush` 会刻意不 discard segments，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1147-1163`。
- Schema/range change 不总是 flush：具体 memtable 的 `shouldSwitch(reason)` 可以选择 notify 而不是 switch，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:997-1006`。
- Index build/view build 会强制 base/table-backed index flush，排查 build 卡顿时要看 flush queue 和 index flush path。
- Streaming/repair/validation 触发的 flush 会和用户 flush、commitlog dirty flush 共用 executor；运维观察要按 `FlushReason` 日志区分。
- Clean memtable 或 truncate path 可能产生 0 SSTable，但仍需要 view replace 和 reclaim，不能只用新 SSTable 数判断 flush 是否运行。

## 性能瓶颈

- Write barrier 等待时间长说明 barrier issue 前的写入没有结束，flush 会在 `writeBarrier.await()` 处停住，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1229-1242`。
- Non-CFS-backed index flush 在 base flush 中同步执行，会延长 flushMemtable 的 critical path，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1307-1314`。
- Per-disk flush runnable 并发受 `memtable_flush_writers` 和 data directory 分布影响；flush runnable 创建见 `src/java/org/apache/cassandra/db/memtable/Flushing.java:57-120`。
- `reclaim()` 等 read barrier，长读可能延迟 memtable memory 释放，即使 SSTable 已经写完，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1391-1404`。
- 如果 commitlog dirty flush 频繁触发，通常是 commitlog segment recycling 和 memtable flush 能力不匹配，触发点见 `src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogSegmentManager.java:463-495`。

## 常见故障

- Flush failure 后数据靠 CommitLog replay 恢复：`PostFlush` 不 discard segments，`CommitLogTest.testOutOfOrderFlushRecovery()` 覆盖失败后仍需 replay，见 `test/unit/org/apache/cassandra/db/commitlog/CommitLogTest.java:1120-1200`。
- `switchMemtableIfCurrent()` 返回但未实际切换目标 memtable：目标已经不是 current，方法会返回 wait-for-flushes future；见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1014-1023`。
- `forceFlush()` 不生成 SSTable：base/index memtable 都 clean，或 memtable flush 后 writer bytes 为 0；clean branch 见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1065-1077`、writer abort-empty branch 见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1332-1343`。
- Flushing memtable 卡在 view 中：需要看 `Tracker.markFlushing()` 和 `replaceFlushed()` 是否执行、flush writer 是否失败、postFlush 是否抛出；view transform 见 `src/java/org/apache/cassandra/db/lifecycle/View.java:330-366`。
- CommitLog segments 长期不回收：检查是否有 flushFailure、pending flush、dirty memtable before target position；dirty-position force flush 见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1084-1091`。
- Flush 后 memtable 内存未立即下降：`reclaim()` 还在等 read barrier 或 postFlush future，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1391-1404`。

## 测试用例

- Tracker live/flushing memtable 和 replaceFlushed view transition：`test/unit/org/apache/cassandra/db/lifecycle/TrackerTest.java:282-334`。
- CommitLog failed/out-of-order flush recovery：`test/unit/org/apache/cassandra/db/commitlog/CommitLogTest.java:1120-1200`。
- Memtable implementation quick flush/read coverage：`test/unit/org/apache/cassandra/db/memtable/MemtableQuickTest.java:60-176`。
- Memtable memory accounting under allocation variants：`test/unit/org/apache/cassandra/db/memtable/MemtableSizeTestBase.java:72-207`。
- ColumnFamilyStore flush usage and no-switch test hooks：`test/unit/org/apache/cassandra/db/ColumnFamilyStoreTest.java:760-810`。
- Flush observer/SSTable output behavior：`test/unit/org/apache/cassandra/io/sstable/SSTableFlushObserverTest.java`。
