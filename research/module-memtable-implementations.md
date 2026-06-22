# Module: Memtable Implementations

## 范围

本文补齐 `module-memtable-flush.md` 的实现差异缺口，覆盖 `SkipListMemtable`、`ShardedSkipListMemtable`、`TrieMemtable`、shard boundary、memtable factory/config 解析、内存分配池、实现专属 metrics 和相关测试。Flush barrier、SSTable 写出和 post-flush 事务主线仍以 `research/module-memtable-flush.md`、`research/module-memtable-postflush-trigger-deep-dive.md` 与 `research/module-storage-engine-lifecycle-transaction.md` 为准。

## 设计目标

- 让表级 schema 可以通过 `WITH memtable = '<configuration>'` 选择不同 memtable factory，而配置定义由 `cassandra.yaml` 提供。
- 保留 legacy skiplist 作为默认实现，同时提供 sharded skiplist 与 trie 以改善写入并发、GC 压力和内存密度。
- 把实现共享能力下沉到抽象基类：统计、commitlog span、allocator/memory pool、periodic flush 和 flush-on-limit。
- sharded 实现把本地 token ranges 拆分成固定 shard boundaries，使同一 memtable 生命周期内同一个 key 总是落到同一 shard。
- memtable factory 暴露 durability/streaming hook，为 persistent memtable 或自定义实现留扩展点。

## 解决的问题

- 单个全局有序 map 在高并发写入下会发生结构争用；`ShardedSkipListMemtable` 把 partition skip-list 拆成多个独立 skip-list，见 `src/java/org/apache/cassandra/db/memtable/ShardedSkipListMemtable.java:62-74`。
- legacy skiplist 把 partition 索引和 key/partition 对象主要留在堆上，GC 压力较高；`TrieMemtable` 把 partition index 放入 `InMemoryTrie` buffer，并可随 allocation type 放到 off-heap，见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:80-89`、`src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:423-436`。
- 自定义 memtable 配置需要跨 schema 传播但又不能让 schema disagreement 扩散；`MemtableParams.getWithFallback()` 在配置不可用时记录错误并回退默认 factory，见 `src/java/org/apache/cassandra/schema/MemtableParams.java:122-135`。
- 实现参数必须可校验：`MemtableParams` 通过 `factory(Map<String,String>)` 或静态 `FACTORY` 反射创建 factory，并要求 factory method 消耗所有参数，见 `src/java/org/apache/cassandra/schema/MemtableParams.java:217-258`。
- sharded memtable 的 shard 数需要可运维调整；`AbstractShardedMemtable` 注册 `ShardedMemtableConfig` MBean，默认 shard 数来自 `MEMTABLE_SHARD_COUNT` 或 CPU 数，见 `src/java/org/apache/cassandra/db/memtable/AbstractShardedMemtable.java:38-47`。

## 设计取舍

- `SkipListMemtable` 使用一个 `ConcurrentSkipListMap<PartitionPosition, AtomicBTreePartition>`，range scan 和 flush 简单，但所有 partition metadata 共享一个有序结构，见 `src/java/org/apache/cassandra/db/memtable/SkipListMemtable.java:82-138`。
- `ShardedSkipListMemtable` 仍使用 skiplist/btree partition 数据结构，但按 token boundary 选择 shard；全范围扫描需要拼接多个 shard iterator，见 `src/java/org/apache/cassandra/db/memtable/ShardedSkipListMemtable.java:121-126`、`src/java/org/apache/cassandra/db/memtable/ShardedSkipListMemtable.java:220-238`。
- `ShardedSkipListMemtable.Locking` 可以对单 shard 写入加 `synchronized`，减少并发修改浪费，但热点 shard 下写入串行化更明显，见 `src/java/org/apache/cassandra/db/memtable/ShardedSkipListMemtable.java:474-495`。
- `TrieMemtable` 每个 shard 是 single-writer trie，读可并发并提供 weakly consistent view；热点 key 或负载极不均匀时，单 shard lock contention 会成为瓶颈，见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:107-118`、`src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:458-503`。
- shard boundaries 在 memtable 创建时固定，避免拓扑变化导致同一个 key 在同一 memtable 生命周期内改变 shard；代价是 owned ranges 变化时需要通过 switch/notify 流程处理，见 `src/java/org/apache/cassandra/db/memtable/AbstractShardedMemtable.java:48-63`、`src/java/org/apache/cassandra/db/memtable/Memtable.java:173-180`。
- 默认配置仍继承 `skiplist`，让升级路径保守；`trie` 需要表级选择或修改 default configuration，见 `conf/cassandra.yaml:767-790`。

## 核心类

| 类 | 作用 |
|---|---|
| `Memtable` | 公共接口、factory contract、owner 回调、durability/streaming hook。定义见 `src/java/org/apache/cassandra/db/memtable/Memtable.java:58-180` |
| `AbstractMemtable` | 共享统计、列集合、flush transaction 和 flushable partition set 基类。定义见 `src/java/org/apache/cassandra/db/memtable/AbstractMemtable.java:41-139` |
| `AbstractMemtableWithCommitlog` | commitlog lower/upper bound、write barrier、切换后是否接受写入。定义见 `src/java/org/apache/cassandra/db/memtable/AbstractMemtableWithCommitlog.java:28-127` |
| `AbstractAllocatorMemtable` | 通过 `MemtablePool` 管理 on/off heap allocator，处理 schema-change switch、periodic flush 和 largest-memtable reclaim。定义见 `src/java/org/apache/cassandra/db/memtable/AbstractAllocatorMemtable.java:51-123` |
| `SkipListMemtable` | legacy 单 skiplist 实现，partition map 为 `ConcurrentSkipListMap`。定义见 `src/java/org/apache/cassandra/db/memtable/SkipListMemtable.java:66-138` |
| `ShardedSkipListMemtable` | token-range sharded skiplist 实现，支持 `shards` 和 `serialize_writes` 参数。定义见 `src/java/org/apache/cassandra/db/memtable/ShardedSkipListMemtable.java:62-94` |
| `TrieMemtable` | sharded trie 实现，使用 `InMemoryTrie<BTreePartitionData>` 和 merged trie view。定义见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:80-129` |
| `TrieMemtable.MemtableShard` | shard-level write lock、trie data、allocator、columns/stats 和 contention metrics。定义见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:405-456` |
| `ShardBoundaries` | token boundary 到 shard id 的映射。定义见 `src/java/org/apache/cassandra/db/memtable/ShardBoundaries.java:29-98` |
| `MemtableParams` | schema/table 参数中的 memtable configuration resolver 和 factory reflection。定义见 `src/java/org/apache/cassandra/schema/MemtableParams.java:42-105` |
| `TrieMemtableMetricsView` | trie memtable 专属 JMX/metrics。定义见 `src/java/org/apache/cassandra/metrics/TrieMemtableMetricsView.java:25-89` |

## 核心接口

- `Memtable.Factory`：创建 memtable，并暴露 `writesShouldSkipCommitLog()`、`writesAreDurable()`、`streamToMemtable()`、`streamFromMemtable()`、`createMemtableMetrics()`，见 `src/java/org/apache/cassandra/db/memtable/Memtable.java:64-151`。
- `Memtable.Owner`：由 `ColumnFamilyStore` 实现，提供 `signalFlushRequired()`、当前 memtable、index memtable、local range splits 和 ownership change 通知，见 `src/java/org/apache/cassandra/db/memtable/Memtable.java:154-180`。
- `ShardedMemtableConfigMXBean`：通过 JMX 读写 sharded memtable 默认 shard count，见 `src/java/org/apache/cassandra/db/memtable/ShardedMemtableConfigMXBean.java:21-32`。

## 核心数据结构

- `ConcurrentSkipListMap<PartitionPosition, AtomicBTreePartition>`：`SkipListMemtable` 的主索引，写入时用 cloned key 与 `AtomicBTreePartition.addAll()` 合并，见 `src/java/org/apache/cassandra/db/memtable/SkipListMemtable.java:82-138`。
- `ShardedSkipListMemtable.MemtableShard[]`：每个 shard 持有自己的 skiplist、stats、columns collector 和 allocator 引用，见 `src/java/org/apache/cassandra/db/memtable/ShardedSkipListMemtable.java:312-380`。
- `InMemoryTrie<BTreePartitionData>`：`TrieMemtable.MemtableShard` 的主索引，key 使用 prefix-free byte-comparable representation，见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:423-436`。
- `Trie.mergeDistinct(...)` merged view：`TrieMemtable` 用于 range queries 和 flush，见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:114-149`。
- `CommitLogPosition` lower/upper bound：`AbstractMemtableWithCommitlog` 在 switch 时用 write barrier 和 atomic upper bound 维护精确 commitlog span，见 `src/java/org/apache/cassandra/db/memtable/AbstractMemtableWithCommitlog.java:34-62`。
- `MemtablePool` onHeap/offHeap subpools：注册 `BlockedOnAllocation` 和 `PendingFlushTasks`，负责触发 cleaner，见 `src/java/org/apache/cassandra/utils/memory/MemtablePool.java:42-75`。
- `InheritingClass`/`ParameterizedClass` definitions：`MemtableParams.expandDefinitions()` 支持 default 注入、继承、循环检测和最终 resolved definition，见 `src/java/org/apache/cassandra/schema/MemtableParams.java:138-205`。

## 生命周期

```text
Configuration:
  cassandra.yaml memtable.configurations
    -> DatabaseDescriptor.getMemtableConfigurations()
    -> MemtableParams.expandDefinitions(...)
    -> table schema MemtableParams.get(key)
    -> reflect factory(Map) or FACTORY
    -> ColumnFamilyStore.memtableFactory

Write:
  Keyspace.applyInternal(...)
    -> cfs.getWriteHandler().write(...)
    -> ColumnFamilyStore.apply(...)
    -> data.getMemtableFor(opGroup, commitLogPosition)
    -> current Memtable.put(update, indexer, opGroup)
       -> SkipList: ConcurrentSkipListMap + AtomicBTreePartition.addAll
       -> ShardedSkipList: shard by token boundary, then same skiplist path
       -> Trie: shard by token boundary, lock shard, InMemoryTrie.putSingleton

Switch/flush trigger:
  AbstractAllocatorMemtable.scheduleFlush()
    -> flushIfPeriodExpired()
    -> owner.signalFlushRequired(..., MEMTABLE_PERIOD_EXPIRED)
  MemtablePool cleaner
    -> AbstractAllocatorMemtable.flushLargestMemtable()
    -> owner.signalFlushRequired(..., MEMTABLE_LIMIT)
  TrieMemtable.put()
    -> reachedAllocatedSizeThreshold()
    -> owner.signalFlushRequired(..., MEMTABLE_LIMIT)
```

## 调用链

- `ColumnFamilyStore` 初始化和 metadata update 会从 `metadata().params.memtable.factory()` 设置 `memtableFactory`，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:401`、`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:500`。
- 新 memtable 由 `ColumnFamilyStore.createMemtable()` 调用当前 factory 创建，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1413-1416`。
- 写入从 `Keyspace.applyInternal()` 进入每个 CFS 的 write handler，最终调用 `ColumnFamilyStore.apply()` 中的 `mt.put(update, indexer, opGroup)`，见 `src/java/org/apache/cassandra/db/Keyspace.java:625-653`、`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1475-1478`。
- `SkipListMemtable.put()` clone key、`putIfAbsent` 创建 `AtomicBTreePartition`，然后 `addAll()` 合并 update 并更新 liveDataSize/columns/stats/op count，见 `src/java/org/apache/cassandra/db/memtable/SkipListMemtable.java:107-138`。
- `ShardedSkipListMemtable.put()` 用 `boundaries.getShardForKey(key)` 找到 shard，再走 shard 的 skiplist merge；locking 版本用 `synchronized (shard)` 包裹，见 `src/java/org/apache/cassandra/db/memtable/ShardedSkipListMemtable.java:121-126`、`src/java/org/apache/cassandra/db/memtable/ShardedSkipListMemtable.java:487-495`。
- `TrieMemtable.put()` 选择 shard 后调用 `MemtableShard.put()`，当 trie allocated size 到阈值时只让一个线程请求 memtable switch，见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:183-205`。
- `TrieMemtable.MemtableShard.put()` 用 `tryLock()` 记录 uncontended/contended metrics，写 `InMemoryTrie.putSingleton()`，再按 trie on/off heap delta 调整 allocator，见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:458-503`。
- `AbstractAllocatorMemtable.flushLargestMemtable()` 遍历 active memtable 和 index memtable memory usage，选择 on/off heap ownership ratio 最大者并触发 `MEMTABLE_LIMIT` flush，见 `src/java/org/apache/cassandra/db/memtable/AbstractAllocatorMemtable.java:245-318`。

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| `memtable.configurations` | `src/java/org/apache/cassandra/config/Config.java:192-201`、`conf/cassandra.yaml:783-790` | 命名 memtable factory 定义；默认当前继承 `skiplist` |
| 表级 `memtable` | `src/java/org/apache/cassandra/schema/TableParams.java:89`、CQL 输出 `src/java/org/apache/cassandra/schema/TableParams.java:315` | `CREATE/ALTER TABLE ... WITH memtable = '<key>'` 选择命名配置 |
| `class_name` | `src/java/org/apache/cassandra/schema/MemtableParams.java:223-249` | 短类名自动补 `org.apache.cassandra.db.memtable.`，长类名按原样加载 |
| `inherits` | `src/java/org/apache/cassandra/schema/MemtableParams.java:138-205` | 配置继承与 remap，含自继承/循环检测 |
| `parameters.shards` | `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:658-679`、`src/java/org/apache/cassandra/db/memtable/ShardedSkipListMemtable.java:499-524` | 显式 shard 数；不设置时用 sharded 默认值 |
| `parameters.serialize_writes` | `src/java/org/apache/cassandra/db/memtable/ShardedSkipListMemtable.java:499-524` | sharded skiplist 是否按 shard 同步写入 |
| JMX `DefaultShardCount` | `src/java/org/apache/cassandra/db/memtable/AbstractShardedMemtable.java:65-99` | 改变未显式配置 shard 数的新 memtable 默认 shard count |
| `memtable_allocation_type` | `src/java/org/apache/cassandra/config/Config.java:524`、`conf/cassandra.yaml:814-825` | `heap_buffers`、`offheap_buffers`、`offheap_objects`；影响 allocator pool 和 trie buffer type |
| `memtable_heap_space` / `memtable_offheap_space` | `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:583-594`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4054-4066` | 全局 memtable on/off heap 空间 |
| `memtable_cleanup_threshold` | `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:761-775`、`conf/cassandra.yaml:801-812` | 触发 largest memtable clean 的比例，默认 `1 / (memtable_flush_writers + 1)` |
| `memtable_flush_writers` | `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:753-759`、`conf/cassandra.yaml:885-912` | flush 并发和同时 flushing memtable 数量 |
| `memtable_flush_period_in_ms` | `src/java/org/apache/cassandra/schema/TableParams.java:81`、`src/java/org/apache/cassandra/schema/TableParams.java:428-431` | 表级周期 flush；由 `AbstractAllocatorMemtable.scheduleFlush()` 执行 |

## Metrics

- 通用 table memtable metrics 仍由 `TableMetrics` 暴露，`module-memtable-flush.md` 已列出 `memtableOnHeapDataSize`、`memtableOffHeapDataSize`、`memtableLiveDataSize`、`memtableColumnsCount`、`memtableSwitchCount` 和 `pendingFlushes`。
- `MemtablePool.BlockedOnAllocation` 与 `MemtablePool.PendingFlushTasks` 在 `MemtablePool` 构造时注册，见 `src/java/org/apache/cassandra/utils/memory/MemtablePool.java:50-65`；YAML 也提示用 `MemtablePool.BlockedOnAllocation` 判断 flushing 是否落后，见 `conf/cassandra.yaml:895-897`。
- `TrieMemtableMetricsView` 注册 `Uncontended memtable puts`、`Contended memtable puts`、`Contention time` 和 `Shard sizes during last flush`，见 `src/java/org/apache/cassandra/metrics/TrieMemtableMetricsView.java:25-54`。
- `TrieMemtable.Factory.createMemtableMetrics()` 把 trie 专属 metrics 生命周期绑定到 table lifecycle，见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:681-686`。
- `TrieMemtable.discard()` 在释放 buffer 前记录 last flush shard sizes，见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:160-175`。

## 日志

- `AbstractAllocatorMemtable.createMemtableAllocatorPoolInternal()` 根据 allocation type 打 debug 日志，见 `src/java/org/apache/cassandra/db/memtable/AbstractAllocatorMemtable.java:93-109`。
- `flushLargestMemtable()` 选择 largest memtable 时记录 used/live/flushing/selected ownership ratio，见 `src/java/org/apache/cassandra/db/memtable/AbstractAllocatorMemtable.java:287-297`。
- `TrieMemtable.put()` 因 trie allocated size threshold 触发 flush 时记录 info，见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:192-195`。
- `ShardedMemtableConfig.setDefaultShardCount()` 解析失败时 warn，成功时 info，见 `src/java/org/apache/cassandra/db/memtable/AbstractShardedMemtable.java:65-87`。
- `MemtableParams.getWithFallback()` 在 schema 引用了本节点无法实例化的配置时记录 error 并回退默认配置，见 `src/java/org/apache/cassandra/schema/MemtableParams.java:122-135`。

## 运维关注点

- 表级 `memtable` 是 schema 属性，集群所有节点都要能解析同名配置；否则节点会 fallback 默认实现以避免 schema mismatch，但该表在不同节点上的 memtable 实现会临时不同。
- 修改 `cassandra.yaml` 的 named configuration 不会自动改变已有 memtable；新 factory 会在表 metadata 更新或新 memtable 创建时生效，`AbstractAllocatorMemtable.shouldSwitch(SCHEMA_CHANGE)` 会在 factory 变化时请求 switch，见 `src/java/org/apache/cassandra/db/memtable/AbstractAllocatorMemtable.java:130-143`。
- JMX `DefaultShardCount` 只影响未显式配置 shard 数的未来 sharded memtable；已有 memtable boundaries 在创建时固定。
- `trie` 通常降低 GC 压力和提高空间效率，但 YAML 明确提示在负载极不均匀、少量热点 partition 或 legacy secondary indexes 场景可能更差，见 `conf/cassandra.yaml:771-777`。
- `memtable_allocation_type=offheap_*` 会影响 allocator pool 和 trie buffer placement；排查内存时需要同时看 table memtable metrics 与 `MemtablePool` metrics。
- `memtable_flush_writers` 过多会产生更小更频繁 flush，增加 compaction 压力；YAML 明确提示更多不是更好，见 `conf/cassandra.yaml:904-910`。

## 性能瓶颈

- `SkipListMemtable` 的全局 skiplist 在高并发不同 key 写入下仍共享有序索引结构；其优势是实现简单、读/flush iterator 直接来自 subMap。
- `ShardedSkipListMemtable` 可降低全局 skiplist contention，但 shard 选择依赖 token distribution；如果本地 range splits 不均或热点集中，单 shard 仍可能成为瓶颈。
- `ShardedSkipListMemtable.Locking` 适合减少 lockless partition merge 的失败浪费，但热点 shard 的写延迟会上升。
- `TrieMemtable` 每个 shard 只有一个 writer lock；`contendedPuts` 和 `contentionTime` 升高说明热点 shard 或热点 partition 正在抵消 trie 的空间/GC 优势。
- `TrieMemtable` 在 range query/flush 使用 merged trie subtrie，single partition read 直接从 shard trie 取值，见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:280-316`、`src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:349-403`。
- allocator cleaner 选择 largest memtable 时会统计 base 和 index memtable ownership ratio；大量二级索引会放大同一次 flush 的内存回收决策成本，见 `src/java/org/apache/cassandra/db/memtable/AbstractAllocatorMemtable.java:264-273`。

## 常见故障

- `WITH memtable = 'unknown'`：`MemtableParams.parseConfiguration()` 抛配置不存在，测试覆盖见 `test/unit/org/apache/cassandra/cql3/validation/operations/CreateTest.java:644-646`。
- `class_name` 为空或缺失：反射前校验失败，测试覆盖见 `test/unit/org/apache/cassandra/cql3/validation/operations/CreateTest.java:616-622`。
- 未消费参数：factory method/field 创建后 `parametersCopy` 非空会失败，测试覆盖见 `test/unit/org/apache/cassandra/cql3/validation/operations/CreateTest.java:624-634`。
- factory method/field 类型错误：`InvalidMemtableFactoryMethod` 和 `InvalidMemtableFactoryField` 覆盖反射失败，见 `test/unit/org/apache/cassandra/cql3/validation/operations/CreateTest.java:585-598`、`test/unit/org/apache/cassandra/cql3/validation/operations/CreateTest.java:636-642`。
- CDC + skip commitlog memtable 不兼容：`TableParams.validate()` 在 `cdc=true` 且 factory `writesShouldSkipCommitLog()` 时失败，见 `src/java/org/apache/cassandra/schema/TableParams.java:197-201`。
- trie space exhausted：`TrieMemtable.put()` 期望 threshold 先触发 switch，真正 `SpaceExhaustedException` 会包装成 `IllegalStateException`，见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:192-205`。
- sharded memtable 不适合非 hashing partitioner：本地 API 文档明确说明 sharding 不能用于 non-hashing partitioners，见 `src/java/org/apache/cassandra/db/memtable/Memtable_API.md:190-197`。
- flushing 落后：`MemtablePool.BlockedOnAllocation` 非零说明写入线程在等 flush 释放内存，见 `conf/cassandra.yaml:895-897`。

## 测试用例

- `test/unit/org/apache/cassandra/db/memtable/MemtableQuickTest.java`：参数化覆盖 `skiplist`、`skiplist_sharded`、`skiplist_sharded_locking`、`trie` 的写、删、读、flush 和 SSTable key count，见 `test/unit/org/apache/cassandra/db/memtable/MemtableQuickTest.java:60-176`。
- `test/unit/org/apache/cassandra/db/memtable/MemtableSizeTestBase.java`：参数化覆盖 `skiplist`、`skiplist_sharded`、`trie` 的 memory accounting，并在 heap/offheap/unslabbed 子类中切 allocation type，见 `test/unit/org/apache/cassandra/db/memtable/MemtableSizeTestBase.java:72-207`。
- `test/unit/org/apache/cassandra/db/memtable/ShardedMemtableConfigTest.java`：JMX 修改 default shard count 和 `auto` 恢复 CPU 数，见 `test/unit/org/apache/cassandra/db/memtable/ShardedMemtableConfigTest.java:49-67`。
- `test/unit/org/apache/cassandra/cql3/validation/operations/CreateTest.java`：CREATE TABLE 的 memtable config 选择、短/长类名、继承、默认值和错误路径，见 `test/unit/org/apache/cassandra/cql3/validation/operations/CreateTest.java:600-657`。
- `test/unit/org/apache/cassandra/cql3/validation/operations/AlterTest.java`：ALTER TABLE 切换 memtable config、其他 ALTER 不改变 memtable、错误路径，见 `test/unit/org/apache/cassandra/cql3/validation/operations/AlterTest.java:607-679`。
- `test/unit/org/apache/cassandra/db/memtable/TestMemtable.java`：测试用 factory method 消费 `skiplist` 参数，见 `test/unit/org/apache/cassandra/db/memtable/TestMemtable.java:23-35`。

## 待继续

- `PostFlush` 如何 discard CommitLog segment、replace flushed SSTables、释放 memtable 的跨模块细节已在 `research/module-memtable-postflush-trigger-deep-dive.md` 展开。
- memtable cleanup/flush 触发源矩阵已在 `research/module-memtable-postflush-trigger-deep-dive.md` 展开。
