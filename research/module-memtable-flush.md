# Module: Memtable And Flush

## 范围

本模块覆盖 memtable 写入、flush 调度、flush task 和 flush 后 SSTable 交接。`SkipListMemtable`、`ShardedSkipListMemtable`、`TrieMemtable`、factory/config 与 shard 差异已在 `research/module-memtable-implementations.md` 展开。

## 设计目标

Memtable 是 Cassandra 本地写入的内存承接层；Flush 负责把一个已切换出的 memtable 稳定写成 SSTable，并在成功后推进 CommitLog segment 清理。

设计目标：

- 写入路径快速把 `PartitionUpdate` 合并到当前 memtable。
- 在 memtable switch 时不长时间阻塞新写入。
- Flush 必须等待 switch 前已经开始的写入完成，保证写出的 SSTable 覆盖正确 CommitLog 区间。
- 支持按磁盘边界拆分 flush output，支持索引 memtable 同步 flush。
- Flush 成功后更新表级 metrics，释放 memtable 内存，标记 CommitLog clean。

## 解决的问题

- 内存写入需要可查询且可 flush：`Memtable` 同时是 `UnfilteredSource`，接口定义见 `src/java/org/apache/cassandra/db/memtable/Memtable.java:58`。
- Flush 与并发写入的边界必须明确：`ColumnFamilyStore.Flush` 创建 `OpOrder.Barrier` 并在 switch 后 issue/await，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1190-1224`、`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1234-1239`。
- Flush 前的写不能落到新 memtable，Flush 后的写不能污染旧 memtable：`data.switchMemtable()` 与 `oldMemtable.switchOut(...)` 建立边界，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1204-1215`。
- 多数据目录下 flush 需要按 disk boundaries 切分，见 `src/java/org/apache/cassandra/db/memtable/Flushing.java:67-88`。

## 设计取舍

- Flush 使用 barrier 等待旧写完成，而不是在 switch 期间阻塞全部新写；这提高写入可用性，但实现复杂。
- Memtable factory 可声明 durable/skip CommitLog，给 persistent memtable 留扩展点，但会影响 PITR/CDC/replay 语义，见 `src/java/org/apache/cassandra/db/memtable/Memtable.java:88-108`。
- `TrieMemtable` 以 shard 内锁保护 trie 写入，热点 shard 会出现 lock contention，见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:458-472`。
- Flush 对 batchlog table 有特殊 tombstone 优化，见 `src/java/org/apache/cassandra/db/memtable/Flushing.java:157-165`。

## 核心类

| 类 | 作用 |
|---|---|
| `Memtable` | memtable 接口、factory、owner、flush/read 能力。定义：`src/java/org/apache/cassandra/db/memtable/Memtable.java:58` |
| `TrieMemtable` | 基于 trie 的 memtable 实现。类定义：`src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:89` |
| `TrieMemtable.MemtableShard` | shard 内写入、allocator、stats、lock contention。写入方法见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:458-503` |
| `ColumnFamilyStore.Flush` | memtable switch、flush barrier、flush task、post flush 的核心 runnable。定义见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1167-1227` |
| `Flushing` | 构造 flush runnable、writer、按 disk boundaries 切分 flush。入口见 `src/java/org/apache/cassandra/db/memtable/Flushing.java:57-120` |
| `SSTableMultiWriter` | flush 输出 writer 抽象，`Flushing.FlushRunnable` 持有该对象，见 `src/java/org/apache/cassandra/db/memtable/Flushing.java:130-146` |

## 核心接口

- `Memtable.Factory`：创建 memtable，并声明 `writesShouldSkipCommitLog()`、`writesAreDurable()`、streaming 行为和 metrics，见 `src/java/org/apache/cassandra/db/memtable/Memtable.java:64-151`。
- `Memtable.Owner`：memtable 请求 owner flush 或查询当前 memtable，见 `src/java/org/apache/cassandra/db/memtable/Memtable.java:154-170`。
- `Callable<SSTableMultiWriter>`：`Flushing.FlushRunnable` 实现 callable，由 per-disk flush executor 执行，见 `src/java/org/apache/cassandra/db/memtable/Flushing.java:130-190`。

## 核心数据结构

- `OpOrder.Barrier`：memtable switch 和旧写完成边界，创建见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1200`。
- `AtomicReference<CommitLogPosition> commitLogUpperBound`：收集 old memtable 对应的 CommitLog 上界，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1204-1219`。
- `Memtable.FlushablePartitionSet`：flush 时遍历的 partition 集合，构造见 `src/java/org/apache/cassandra/db/memtable/Flushing.java:105`。
- `DiskBoundaries`：按 token/disk 边界拆分 flush 输出，见 `src/java/org/apache/cassandra/db/memtable/Flushing.java:67-83`。
- `InMemoryTrie<BTreePartitionData>`：`TrieMemtable.MemtableShard` 的核心数据结构，见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:435-452`。

## 生命周期

```text
Write:
  ColumnFamilyStore.apply(update, ctx, updateIndexes)
    -> data.getMemtableFor(opGroup, commitLogPosition)
    -> mt.put(update, indexer, opGroup)
       -> TrieMemtable.MemtableShard.put(...)
          -> writeLock
          -> data.putSingleton(key, update, mergePartitions, ...)
          -> allocator on/off heap adjust

Flush:
  ColumnFamilyStore.Flush()
    -> metric.pendingFlushes.inc()
    -> Keyspace.writeOrder.newBarrier()
    -> create new memtable for each base/index CFS
    -> data.switchMemtable(...)
    -> oldMemtable.switchOut(barrier, commitLogUpperBound)
    -> setCommitLogUpperBound(...)
    -> writeBarrier.issue()
  Flush.run()
    -> writeBarrier.markBlocking()
    -> writeBarrier.await()
    -> data.markFlushing(oldMemtable)
    -> flushMemtable(...)
       -> Flushing.flushRunnables(...)
       -> submit per-disk flush runnables
       -> wait futures
    -> postFlush
```

## 调用链

- 本地写入 memtable：`ColumnFamilyStore.apply()` 调用 `mt.put(update, indexer, opGroup)`，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1475-1478`。
- Trie memtable 写入：`TrieMemtable.MemtableShard.put()` 更新 trie、allocator、stats，见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:458-503`。
- Flush 构造：`ColumnFamilyStore.Flush` switch memtable 并创建 barrier，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1167-1227`。
- Flush 执行：`Flush.run()` 等 barrier、mark flushing、调用 `flushMemtable()`，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1229-1274`。
- Flush runnable：`Flushing.flushRunnables()` 选择 disk boundaries 和 writer，见 `src/java/org/apache/cassandra/db/memtable/Flushing.java:57-120`。
- 写出 partition：`FlushRunnable.writeSortedContents()` 遍历 partition 并 `writer.append(iter)`，见 `src/java/org/apache/cassandra/db/memtable/Flushing.java:151-184`。

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| `memtable_flush_writers` | `src/java/org/apache/cassandra/config/Config.java:185`，默认计算 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:753-763` | flush writer 并发 |
| `memtable_heap_space` | `src/java/org/apache/cassandra/config/Config.java:186-187`，模板 `conf/cassandra.yaml:794-799` | heap memtable 空间 |
| `memtable_offheap_space` | `src/java/org/apache/cassandra/config/Config.java:188-189`，模板 `conf/cassandra.yaml:794-799` | off-heap memtable 空间 |
| `memtable_cleanup_threshold` | `src/java/org/apache/cassandra/config/Config.java:190`，校验 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:761-775` | 触发 flush/clean 的阈值 |
| `memtable_allocation_type` | `src/java/org/apache/cassandra/config/Config.java:524`，模板 `conf/cassandra.yaml:825` | heap/offheap allocation 策略 |
| 表级 `memtable` | `src/java/org/apache/cassandra/config/Config.java:192-201` 和 `src/java/org/apache/cassandra/schema/MemtableParams.java:51` | table 选择具体 memtable factory |

## Metrics

- `TableMetrics.memtableOnHeapDataSize`、`memtableOffHeapDataSize`、`memtableLiveDataSize`：定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:86-97`。
- `TableMetrics.memtableColumnsCount`：定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:98-99`。
- `TableMetrics.memtableSwitchCount`：flush switch 后更新，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1244-1248`；定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:100-101`。
- `TableMetrics.pendingFlushes`：flush 构造时递增，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1190`；定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:120-123`。
- `TableMetrics.bytesFlushed`：`FlushRunnable.writeSortedContents()` 完成后递增，见 `src/java/org/apache/cassandra/db/memtable/Flushing.java:176-184`。
- `TrieMemtableMetricsView`：`TrieMemtable` factory 可注入实现特定 metrics，接口说明见 `src/java/org/apache/cassandra/db/memtable/Memtable.java:142-151`。

## 日志

- flush task 创建、等待 barrier、完成：trace 日志见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1183-1187`、`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1231-1242`、`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1266-1273`。
- flush 写出开始：`logger.info("Writing {}, flushed range = ...")`，见 `src/java/org/apache/cassandra/db/memtable/Flushing.java:151-154`。
- flush 完成：`logger.info("Completed flushing ... for commitlog position ...")`，见 `src/java/org/apache/cassandra/db/memtable/Flushing.java:176-182`。

## 运维关注点

- `pendingFlushes` 和 memtable 空间持续上升通常说明 flush writer 或磁盘跟不上。
- Flush 卡住可能是在等待 write barrier，代表旧写入未结束；对应 trace 在 `Flush.run()` 的 barrier wait 附近。
- 多数据目录下 flush 被 disk boundaries 拆分，某块盘慢会影响对应 range 的 flush 完成。
- 二级索引 memtable 与 base memtable 一起 switch/flush；自定义索引可能延后 clean-up。

## 性能瓶颈

- Memtable lock contention：`TrieMemtable.MemtableShard.put()` 在锁竞争时更新 contention metrics，见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:458-472`。
- Allocator 内存压力：`allocator.offHeap().adjust()`、`allocator.onHeap().adjust()` 在每次写入后调整，见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:477-485`。
- Flush writer 并发不足或磁盘 I/O 慢，会让 memtable 清理滞后并反压 CommitLog。
- 非 CFS-backed index flush 会在 base flush 中同步阻塞，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1307-1314`。

## 常见故障

- Flush 重复执行同一 memtable：`Flushing.flushRunnables()` 检查 `setFlushTransaction(txn)` 必须为 null，见 `src/java/org/apache/cassandra/db/memtable/Flushing.java:57-65`。
- Flush 过程中 writer 失败：`ColumnFamilyStore.Flush.flushMemtable()` abort runnables 和 transaction，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1316-1324`。
- Memtable 空间耗尽：`TrieMemtable.MemtableShard.put()` 可能抛出 `InMemoryTrie.SpaceExhaustedException`，方法签名见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:458`。
- pending flush 过多导致写入受限：需要联动 memtable cleanup threshold、flush writers、磁盘 I/O 和 CommitLog segment 回收。

## 测试用例

- `test/unit/org/apache/cassandra/db/memtable/MemtableQuickTest.java`
- `test/unit/org/apache/cassandra/db/memtable/MemtableSizeTestBase.java`
- `test/unit/org/apache/cassandra/db/memtable/MemtableSizeHeapBuffersTest.java`
- `test/unit/org/apache/cassandra/db/memtable/MemtableSizeOffheapBuffersTest.java`
- `test/unit/org/apache/cassandra/db/memtable/MemtableSizeOffheapObjectsTest.java`
- `test/unit/org/apache/cassandra/db/memtable/MemtableSizeUnslabbedTest.java`
- `test/unit/org/apache/cassandra/db/memtable/ShardedMemtableConfigTest.java`
- `test/unit/org/apache/cassandra/cql3/validation/operations/CreateTest.java`
- `test/unit/org/apache/cassandra/cql3/validation/operations/AlterTest.java`
- `test/unit/org/apache/cassandra/db/ColumnFamilyStoreTest.java`
- `test/unit/org/apache/cassandra/io/sstable/SSTableFlushObserverTest.java`

## 待继续

- `research/module-memtable-implementations.md` 已覆盖 `TrieMemtable`、`SkipListMemtable`、`ShardedSkipListMemtable` 的结构、配置、allocation 和 metrics 差异。
- `research/module-memtable-postflush-trigger-deep-dive.md` 已覆盖 `PostFlush` 如何 discard CommitLog segment、replace flushed SSTables、释放 memtable，以及空间阈值、手动 flush、truncate、streaming/repair flush、schema/range change 等触发源矩阵。
