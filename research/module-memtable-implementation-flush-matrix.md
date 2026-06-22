# Module: Memtable Implementation And Flush Matrix

## 范围

本矩阵把 `research/module-memtable-flush.md`、`research/module-memtable-implementations.md` 和 `research/module-memtable-postflush-trigger-deep-dive.md` 中分散的 Memtable 实现、配置、flush 和测试锚点合并成可校验合同。对应 drift checker 是 `research/tools/check-memtable-implementation-flush-drift.py`，它保护源码、测试和研究文档之间的关键 token。

## 场景矩阵

| 场景 ID | 保护内容 | 源码锚点 | 测试/缺口 |
|---|---|---|---|
| `memtable_factory_durability_contract` | `Memtable.Factory` 的 durability、commitlog skip、streaming 和 metrics hook | `src/java/org/apache/cassandra/db/memtable/Memtable.java` 的 `writesShouldSkipCommitLog()`、`writesAreDurable()`、`streamToMemtable()`、`streamFromMemtable()`、`createMemtableMetrics()` | `TableParams.validate()` 保护 CDC + skip commitlog 失败路径 |
| `memtable_config_resolution_contract` | `cassandra.yaml` named configurations、default 注入、继承、短类名补包名、`factory(Map)`/`FACTORY` 反射 | `src/java/org/apache/cassandra/schema/MemtableParams.java`、`src/java/org/apache/cassandra/config/Config.java`、`conf/cassandra.yaml` | `MemtableParamsTest`、`CreateTest`、`AlterTest` |
| `memtable_skiplist_write_flush_contract` | legacy `SkipListMemtable` 的 `ConcurrentSkipListMap`、`AtomicBTreePartition.addAll()`、range iterator 和 flush set | `src/java/org/apache/cassandra/db/memtable/SkipListMemtable.java`、`SkipListMemtableFactory.java` | `MemtableQuickTest`、`CommitLogTest.testOutOfOrderFlushRecovery()` 的 `makeUnflushable()` |
| `memtable_sharded_skiplist_boundary_contract` | sharded skiplist 的 token boundary、`shards`、`serialize_writes` 和 locking variant | `AbstractShardedMemtable.java`、`ShardBoundaries.java`、`ShardedSkipListMemtable.java` | `ShardedMemtableConfigTest` 覆盖 JMX default shard count |
| `memtable_trie_single_writer_metrics_contract` | `TrieMemtable` shard lock、`InMemoryTrie`、allocated-size threshold flush 和 trie metrics | `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java`、`TrieMemtableMetricsView.java` | `TrieMemtableMetricsTest` 覆盖 regular statements、flush survival、contention 和 cleanup |
| `memtable_allocator_pool_cleaner_contract` | allocation type、on/off heap pool、cleanup threshold、blocked-on-allocation 和 cleaner thread | `AbstractAllocatorMemtable.java`、`MemtablePool.java`、`MemtableCleanerThread.java`、`DatabaseDescriptor.java` | `MemtableSizeTestBase`、`MemtableCleanerThreadTest` |
| `memtable_flush_switch_barrier_contract` | `ColumnFamilyStore.Flush` 的 new/old memtable switch、shared commitlog upper bound 和 write barrier | `src/java/org/apache/cassandra/db/ColumnFamilyStore.java` | `TrackerTest` 验证 live/flushing view transition |
| `memtable_postflush_reclaim_contract` | `PostFlush` latch、CommitLog segment discard、`pendingFlushes` decrement、`replaceFlushed()` 和 `reclaim()` | `ColumnFamilyStore.PostFlush`、`Tracker.replaceFlushed()`、`CommitLog.discardCompletedSegments()` | `CommitLogTest.testOutOfOrderFlushRecovery()` 保护失败 flush 不丢 commitlog |
| `memtable_flush_writer_disk_boundary_contract` | `Flushing.flushRunnables()`、flush transaction、disk boundaries、writer append 和 bytes flushed metrics | `src/java/org/apache/cassandra/db/memtable/Flushing.java` | `SSTableFlushObserverTest` 和 Memtable quick flush baseline |
| `memtable_table_schema_validation_contract` | 表级 `memtable`、`memtable_flush_period_in_ms`、CDC + skip commitlog 校验 | `src/java/org/apache/cassandra/schema/TableParams.java` | `CreateTest`、`AlterTest` |
| `memtable_jmx_shard_count_contract` | `DefaultShardCount` JMX 操作只影响未来未显式配置 shard 数的 memtable | `AbstractShardedMemtable`、`ShardedMemtableConfigMXBean` | `ShardedMemtableConfigTest.testDefaultShardCountSetByJMX()` |
| `memtable_existing_test_baseline` | 当前 unit coverage 对四种配置、allocation variants、metrics 和 flush transition 的覆盖边界 | `test/unit/org/apache/cassandra/db/memtable`、`test/unit/org/apache/cassandra/metrics/TrieMemtableMetricsTest.java` | 无专门 distributed Memtable compatibility dtest |
| `memtable_persistent_custom_gap` | persistent/custom memtable 只通过 factory hook 和测试注释保护；本源码树没有内置 persistent memtable 实现 | `Memtable.Factory.streamToMemtable()` / `streamFromMemtable()`、`MemtableQuickTest` 的 `persistent memtables won't flush` 注释 | 需要外部实现 compatibility matrix |

## 关键调用图

```text
Configuration:
  cassandra.yaml memtable.configurations
    -> DatabaseDescriptor.getMemtableConfigurations()
    -> MemtableParams.expandDefinitions(...)
    -> MemtableParams.get()/getWithFallback()
    -> MemtableParams.getMemtableFactory(...)
    -> ColumnFamilyStore.memtableFactory

Write:
  ColumnFamilyStore.apply(...)
    -> data.getMemtableFor(opGroup, commitLogPosition)
    -> Memtable.put(...)
       -> SkipListMemtable: ConcurrentSkipListMap + AtomicBTreePartition.addAll()
       -> ShardedSkipListMemtable: boundaries.getShardForKey() + shard skiplist
       -> TrieMemtable: boundaries.getShardForKey() + MemtableShard.writeLock + InMemoryTrie.putSingleton()

Flush trigger:
  MemtablePool.SubPool.needsCleaning()
    -> MemtableCleanerThread.trigger()
    -> AbstractAllocatorMemtable.flushLargestMemtable()
    -> owner.signalFlushRequired(..., MEMTABLE_LIMIT)

  AbstractAllocatorMemtable.scheduleFlush()
    -> flushIfPeriodExpired()
    -> owner.signalFlushRequired(..., MEMTABLE_PERIOD_EXPIRED)

  TrieMemtable.put()
    -> reachedAllocatedSizeThreshold()
    -> owner.signalFlushRequired(..., MEMTABLE_LIMIT)

Switch/flush/post-flush:
  ColumnFamilyStore.switchMemtable(reason)
    -> new ColumnFamilyStore.Flush(false)
    -> Keyspace.writeOrder.newBarrier()
    -> cfs.createMemtable(shared upper bound)
    -> data.switchMemtable(...)
    -> oldMemtable.switchOut(barrier, shared upper bound)
    -> writeBarrier.issue()
    -> Flush.run()
       -> writeBarrier.await()
       -> data.markFlushing(oldMemtable)
       -> Flushing.flushRunnables(...)
       -> writer.append(...)
       -> cfs.replaceFlushed(...)
       -> reclaim(oldMemtable)
    -> PostFlush.call()
       -> CommitLog.discardCompletedSegments(...)
       -> pendingFlushes.dec()
```

## 配置与运维边界

- `memtable.configurations` 在 `Config.MemtableOptions` 中保序解析，默认 `cassandra.yaml` 仍让 `default` 继承 `skiplist`。
- 表级 `WITH memtable = '<key>'` 是 schema 属性；所有节点必须能解析同名 key。`MemtableParams.getWithFallback()` 只是在本节点无法解析时回退默认实现，不能替代配置治理。
- `memtable_heap_space`、`memtable_offheap_space`、`memtable_cleanup_threshold` 和 `memtable_flush_writers` 决定 cleaner 触发、flush 并发和写入反压。
- `memtable_allocation_type` 影响 allocator pool 和 trie buffer placement；`MemtableSizeTestBase` 通过 heap/offheap/unslabbed 子类保护 accounting。
- `DefaultShardCount` JMX 只影响新建且未显式配置 `shards` 的 sharded memtable；已有 memtable 的 `ShardBoundaries` 在创建时固定。
- `TrieMemtableMetricsView` 的 `Uncontended memtable puts`、`Contended memtable puts`、`Contention time` 和 `Shard sizes during last flush` 是排查 trie 热 shard 的直接指标。
- `MemtablePool.BlockedOnAllocation` 非零表示写线程在等待 flush 释放内存；`PendingFlushTasks` 反映 cleaner 正在排队或运行的 flush work。

## 故障与测试缺口

- `memtable_persistent_custom_gap` 是显式缺口：本源码树只有 factory hook 和 `MemtableQuickTest` 的 persistent memtable 分支注释，没有内置 persistent memtable 实现或外部实现兼容套件。
- sharded/trie 的热点 shard 问题主要通过 trie metrics 间接观测，缺少真实 skewed workload regression。
- `CreateTest`/`AlterTest` 覆盖反射和 schema mutation，但没有 mixed-version memtable configuration rolling-upgrade dtest。
- flush failure 的 commitlog recovery 依赖 `CommitLogTest.testOutOfOrderFlushRecovery()`，还缺少低磁盘/慢盘与 memtable pool cleaner 组合故障场景。
