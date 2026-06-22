# Flow: Flush Path

## 目标

Flush 链路解释一个 live memtable 如何被切换、冻结、等待旧写完成、写出 SSTable，并在 post flush 阶段释放内存和推进 CommitLog segment 清理。

## 文字版调用图

```text
Flush trigger
  -> ColumnFamilyStore.switchMemtable / forceFlush / owner signal
  -> new ColumnFamilyStore.Flush(truncate=false)
     -> metric.pendingFlushes.inc()
     -> writeBarrier = Keyspace.writeOrder.newBarrier()
     -> for cfs in concatWithIndexes()
        -> newMemtable = cfs.createMemtable(commitLogUpperBound)
        -> oldMemtable = cfs.data.switchMemtable(truncate, newMemtable)
        -> oldMemtable.switchOut(writeBarrier, commitLogUpperBound)
        -> memtables.put(cfs, oldMemtable)
     -> setCommitLogUpperBound(commitLogUpperBound)
     -> writeBarrier.issue()
     -> postFlushTask = new FutureTask<>(postFlush)

Flush writer thread:
  -> Flush.run()
     -> writeBarrier.markBlocking()
     -> writeBarrier.await()
     -> for each old memtable
        -> cfs.data.markFlushing(memtable)
     -> metric.memtableSwitchCount.inc()
     -> for each memtable
        -> flushMemtable(cfs, memtable, first)
           -> if memtable clean or truncate
              -> cfs.replaceFlushed(memtable, empty)
              -> reclaim(memtable)
           -> else
              -> LifecycleTransaction.offline(OperationType.FLUSH)
              -> Flushing.flushRunnables(cfs, memtable, txn)
                 -> memtable.setFlushTransaction(txn)
                 -> cfs.getDiskBoundaries()
                 -> memtable.getFlushSet(from, to)
                 -> create SSTable descriptor/writer
                 -> new Flushing.FlushRunnable(...)
              -> submit runnables to per-disk flush executors
              -> wait futures
              -> collect SSTable readers
     -> postFlush.latch.decrement()

Flush runnable:
  -> FlushRunnable.call()
     -> writeSortedContents()
        -> for partition in flush set
           -> writer.append(partition.unfilteredIterator())
        -> log completed flushing
        -> metrics.bytesFlushed.inc(bytes)
     -> writer.finish()

Post flush:
  -> PostFlush.call()
     -> wait flush latch
     -> if no flushFailure: CommitLog.discardCompletedSegments(...)
     -> pendingFlushes.dec()
  -> cfs.replaceFlushed(memtable, sstables)
     -> Tracker.replaceFlushed(...)
     -> View.replaceFlushed(...)
  -> reclaim(memtable)
     -> read barrier
     -> memtable.discard()
```

## 关键源码锚点

| 阶段 | 文件/方法 |
|---|---|
| Flush 构造与 memtable switch | `ColumnFamilyStore.Flush` 构造：`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1167-1227` |
| 等待 write barrier | `ColumnFamilyStore.Flush.run()`：`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1229-1243` |
| mark flushing 与 switch metric | `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1244-1248` |
| flushMemtable 主体 | `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1276-1328` |
| 构造 flush runnables | `Flushing.flushRunnables()`：`src/java/org/apache/cassandra/db/memtable/Flushing.java:57-96` |
| 构造 flush writer | `Flushing.flushRunnable()`：`src/java/org/apache/cassandra/db/memtable/Flushing.java:98-120` |
| 写出 partition | `Flushing.FlushRunnable.writeSortedContents()`：`src/java/org/apache/cassandra/db/memtable/Flushing.java:151-184` |
| PostFlush cleanup | `ColumnFamilyStore.PostFlush.call()`：`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1138-1163` |
| replace flushed view | `Tracker.replaceFlushed()` / `View.replaceFlushed()`：`src/java/org/apache/cassandra/db/lifecycle/Tracker.java:412-427`、`src/java/org/apache/cassandra/db/lifecycle/View.java:349-366` |
| reclaim memtable | `ColumnFamilyStore.Flush.reclaim()`：`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1391-1404` |
| CommitLog clean | `CommitLog.discardCompletedSegments()`：`src/java/org/apache/cassandra/db/commitlog/CommitLog.java:353-370` |
| trigger matrix | `research/module-memtable-postflush-trigger-deep-dive.md` |

## 配置与观测

- `memtable_flush_writers`：定义在 `src/java/org/apache/cassandra/config/Config.java:185`；默认计算在 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:753-763`。
- `memtable_cleanup_threshold`：定义在 `src/java/org/apache/cassandra/config/Config.java:190`；范围校验在 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:761-775`。
- `memtable_heap_space` / `memtable_offheap_space`：定义在 `src/java/org/apache/cassandra/config/Config.java:186-189`。
- `TableMetrics.pendingFlushes`、`bytesFlushed`、`memtableSwitchCount`：定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:100-123`。
- Flush completion 日志：`src/java/org/apache/cassandra/db/memtable/Flushing.java:176-184`。
- Flush reason、PostFlush 和 trigger matrix 细节见 `research/module-memtable-postflush-trigger-deep-dive.md`。

## 故障排查

- Flush 卡在等待 barrier：旧写入未结束，重点看 mutation stage、MV lock、CommitLog append。
- `pendingFlushes` 高：flush writer 或磁盘慢，或 memtable cleanup threshold 太激进。
- CommitLog 空间释放慢：flush 没有完成 post flush clean，导致 `discardCompletedSegments()` 不能释放 segment。
- 多盘 flush 不均衡：检查 disk boundaries 和每个数据目录的 I/O/空间。

## 测试用例

- `test/unit/org/apache/cassandra/db/ColumnFamilyStoreTest.java`
- `test/unit/org/apache/cassandra/db/memtable/MemtableQuickTest.java`
- `test/unit/org/apache/cassandra/io/sstable/SSTableFlushObserverTest.java`
- `test/unit/org/apache/cassandra/io/sstable/SSTableWriterTest.java`
