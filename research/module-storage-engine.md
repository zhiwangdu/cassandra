# Module: Storage Engine Write Core

## 范围

本模块覆盖本地写入核心：Mutation/PartitionUpdate、Keyspace、ColumnFamilyStore、memtable、commitlog 和写入后续交接。

## 设计目标

本模块聚焦本地写入存储核心：`Mutation` 进入 replica 后，如何在 `Keyspace`、`CassandraKeyspaceWriteHandler`、`ColumnFamilyStore`、`Memtable` 和索引更新之间形成一致的本地写入。

设计目标：

- 以 keyspace 为单位协调一个 mutation 内多个 table 的 partition update。
- 在写 memtable 前创建 write order group，并在需要 durability 时先追加 CommitLog。
- 对 Materialized View 需要的 partition lock 和 view update 做本地同步保护。
- 通过 `ColumnFamilyStore.apply()` 把 `PartitionUpdate` 交给当前 memtable，并更新表级 metrics/cache/index。

## 解决的问题

- 多表 mutation 的本地原子顺序：`Keyspace.applyInternal()` 在一个 write context 中遍历 `mutation.getPartitionUpdates()`，见 `src/java/org/apache/cassandra/db/Keyspace.java:625-653`。
- durable write 与 memtable 写入顺序：`CassandraKeyspaceWriteHandler.beginWrite()` 先 `Keyspace.writeOrder.start()`，再按 `makeDurable` 追加 CommitLog，见 `src/java/org/apache/cassandra/db/CassandraKeyspaceWriteHandler.java:41-55`。
- 对支持持久化 memtable 的表跳过 CommitLog：`addToCommitLog()` 检查 `writesShouldSkipCommitLog()` 并可能裁剪 mutation，见 `src/java/org/apache/cassandra/db/CassandraKeyspaceWriteHandler.java:67-99`。
- MV 写锁避免并发更新破坏视图一致性：`Keyspace.applyInternal()` 对影响 view 的 mutation 获取 per-partition/table lock，见 `src/java/org/apache/cassandra/db/Keyspace.java:535-624`。

## 设计取舍

- CommitLog 是 keyspace write handler 的责任，而不是 `ColumnFamilyStore.apply()` 的责任；这样一个 mutation 内多个 table 可以共享 write context。
- MV 锁使用 try-lock + retry/deferral，避免 mutation stage 死锁。相关说明见 `src/java/org/apache/cassandra/db/Keyspace.java:494-505`、`src/java/org/apache/cassandra/db/Keyspace.java:578-587`。
- `ColumnFamilyStore.apply()` 不做跨节点一致性，只处理本地 memtable/index/cache/metrics，跨节点语义由 `StorageProxy` 和 write response handler 保证。
- 写入后立即 invalidates cached partition，避免 row cache 返回旧分区，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1477-1480`。

## 核心类

| 类 | 作用 |
|---|---|
| `Mutation` | keyspace 级 mutation，封装多个 `PartitionUpdate`；apply 方法入口见 `src/java/org/apache/cassandra/db/Mutation.java:247-274` |
| `Keyspace` | 本地 keyspace 实例，持有 table id 到 `ColumnFamilyStore` 的映射；本地 apply 入口见 `src/java/org/apache/cassandra/db/Keyspace.java:483-510` |
| `CassandraKeyspaceWriteHandler` | 创建 `WriteContext`，追加 CommitLog；类定义见 `src/java/org/apache/cassandra/db/CassandraKeyspaceWriteHandler.java:32` |
| `CassandraWriteContext` | 持有 `OpOrder.Group` 与 `CommitLogPosition`，供 CFS 写入使用 |
| `ColumnFamilyStore` | 表级本地存储入口，实现 `Memtable.Owner` 和 `SSTable.Owner`；类定义见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:194` |
| `Memtable` | 当前内存写入结构；接口定义见 `src/java/org/apache/cassandra/db/memtable/Memtable.java:58` |
| `SecondaryIndexManager` / `UpdateTransaction` | 写入时构造索引更新事务，入口见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1504-1508` |

## 核心接口

- `KeyspaceWriteHandler`：抽象 keyspace 写上下文创建；`CassandraKeyspaceWriteHandler` 实现 `beginWrite()`，见 `src/java/org/apache/cassandra/db/CassandraKeyspaceWriteHandler.java:41-65`。
- `WriteContext`：封装写入上下文，传递给 `ColumnFamilyStore.apply()`。
- `Memtable.Owner`：memtable 通过 owner 发起 flush 请求和获取当前 memtable，见 `src/java/org/apache/cassandra/db/memtable/Memtable.java:154-170`。
- `UpdateTransaction`：二级索引写事务，`ColumnFamilyStore.newUpdateTransaction()` 根据 `updateIndexes` 决定 NO_OP 或 index manager 事务，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1504-1508`。

## 核心数据结构

- `Mutation`：keyspace、decorated key、partition updates。
- `PartitionUpdate`：单表单 partition 的行/列/deletion 更新集合。
- `OpOrder.Group`：将写入与 memtable switch/flush barrier 建立顺序关系；创建位置 `src/java/org/apache/cassandra/db/CassandraKeyspaceWriteHandler.java:47`。
- `CommitLogPosition`：写入在 CommitLog 中的位置，随后传给 `ColumnFamilyStore.apply()` 用于选择 memtable 和 flush 清理，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1470-1476`。
- `TableId`：`Keyspace.applyInternal()` 用 table id 找到对应 `ColumnFamilyStore`，见 `src/java/org/apache/cassandra/db/Keyspace.java:627-633`。

## 生命周期

```text
Mutation.apply()
  -> Keyspace.apply(mutation, makeDurable, updateIndexes, isDroppable)
     -> Keyspace.applyInternal(...)
        -> getWriteHandler().beginWrite(mutation, makeDurable)
           -> Keyspace.writeOrder.start()
           -> CommitLog.instance.add(mutation) if durable
        -> for each PartitionUpdate
           -> maybe push materialized view updates
           -> ColumnFamilyStore.getWriteHandler().write(update, ctx, updateIndexes)
              -> ColumnFamilyStore.apply(update, ctx, updateIndexes)
                 -> data.getMemtableFor(opGroup, commitLogPosition)
                 -> newUpdateTransaction(...)
                 -> Memtable.put(update, indexer, opGroup)
                 -> invalidateCachedPartition(key)
                 -> update TableMetrics.writeLatency/topWritePartition*
```

## 调用链

本地 replica 写入主链：

- `MutationVerbHandler.doVerb()` 接收 `MUTATION_REQ` 并调用 `processMessage()`：`src/java/org/apache/cassandra/db/MutationVerbHandler.java:44-65`
- `MutationVerbHandler.applyMutation()` 调用 `message.payload.applyFuture()` 并在成功后响应 coordinator：`src/java/org/apache/cassandra/db/MutationVerbHandler.java:72-76`
- `Mutation.apply()` 进入 `Keyspace.apply()`：`src/java/org/apache/cassandra/db/Mutation.java:247-274`
- `Keyspace.applyInternal()` 追加 CommitLog 并写各表：`src/java/org/apache/cassandra/db/Keyspace.java:523-660`
- `ColumnFamilyStore.apply()` 写 memtable、索引、缓存和 metrics：`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1467-1508`

## 配置项

| 配置项 | 定义位置 | 影响 |
|---|---|---|
| `concurrent_writes` | `src/java/org/apache/cassandra/config/Config.java:180`，访问位置 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:2416-2425` | mutation stage 写并发相关容量 |
| `write_request_timeout` | 校验最小值见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1366-1370` | 本地 MV lock 获取超时判断使用 `DatabaseDescriptor.getWriteRpcTimeout`，见 `src/java/org/apache/cassandra/db/Keyspace.java:561-573` |
| 表级 `durable_writes` | `Keyspace.apply()` 使用 `keyspace.getMetadata().params.durableWrites`，见 `src/java/org/apache/cassandra/db/Mutation.java:266-269` | 控制是否追加 CommitLog |
| 表级 `memtable` | `Memtable.Factory` 由 `MemtableParams` 选择，说明见 `src/java/org/apache/cassandra/db/memtable/Memtable.java:64-75` | 可改变 memtable 实现和是否跳过 CommitLog |

## Metrics

- `TableMetrics.writeLatency`：`ColumnFamilyStore.apply()` 更新本地写延迟，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1483-1484`；定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:114-123`。
- `TableMetrics.topWritePartitionFrequency` 和 `topWritePartitionSize`：写入采样，更新见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1479-1482`；定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:254-259`。
- `TableMetrics.viewLockAcquireTime`：MV lock 获取耗时，更新见 `src/java/org/apache/cassandra/db/Keyspace.java:616-623`；定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:156-161`。
- `ClientRequestMetrics` 中的 `localRequests`、`remoteRequests`、`timeouts`、`failures` 由 coordinator 层更新，定义见 `src/java/org/apache/cassandra/metrics/ClientRequestMetrics.java:32-55`。

## 日志

- 写不存在表：`Keyspace.applyInternal()` 记录 `Attempting to mutate non-existant table`，见 `src/java/org/apache/cassandra/db/Keyspace.java:629-633`。
- MV 更新异常：`Unknown exception caught while attempting to update MaterializedView`，见 `src/java/org/apache/cassandra/db/Keyspace.java:641-649`。
- `ColumnFamilyStore.apply()` 捕获 RuntimeException 后补充 keyspace/table 信息，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1493-1500`。

## 运维关注点

- 写成功只表示满足一致性级别所需 replica 响应；本地存储层成功通常是 CommitLog + Memtable，不表示 SSTable 已生成。
- `durable_writes=false` 或特定 memtable factory 跳过 CommitLog 会改变崩溃恢复语义，应结合表配置和 memtable 实现审查。
- MV 写锁超时会表现为 `WriteTimeoutException(WriteType.VIEW)`，排查时应看 `viewLockAcquireTime` 和 mutation stage 是否拥塞。
- Row cache 相关问题要关注写后缓存失效是否发生，`ColumnFamilyStore.apply()` 会调用 `invalidateCachedPartition(key)`。

## 性能瓶颈

- CommitLog append 分配和 sync 是 durable write 的前置成本。
- MV 写锁会在热点 partition/table 上放大写延迟。
- Memtable 写锁或 trie/allocator 竞争会表现为 memtable 实现自身 metrics 上升，`TrieMemtable` 有 contended/uncontended put 计数，见 `src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:458-472`。
- index update 在写路径同步构造 `UpdateTransaction`，复杂二级索引会增加写放大。

## 常见故障

- 写不存在表或 schema 不一致：`columnFamilyStores.get(upd.metadata().id)` 返回 null，见 `src/java/org/apache/cassandra/db/Keyspace.java:627-633`。
- MV lock 超时：`WriteTimeoutException(WriteType.VIEW)`，见 `src/java/org/apache/cassandra/db/Keyspace.java:561-576`。
- CommitLog 写失败：`CassandraKeyspaceWriteHandler.addToCommitLog()` 调用 `CommitLog.instance.add()`，底层可能抛出 FS/CDC 相关异常，见 `src/java/org/apache/cassandra/db/CassandraKeyspaceWriteHandler.java:98-99`。
- 写入 memtable 时索引事务异常：`ColumnFamilyStore.apply()` 会重新包装 RuntimeException 并附加 keyspace/table，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1493-1500`。

## 测试用例

- `test/unit/org/apache/cassandra/service/StorageProxyTest.java`
- `test/unit/org/apache/cassandra/service/WriteResponseHandlerTest.java`
- `test/unit/org/apache/cassandra/db/ColumnFamilyStoreTest.java`
- `test/unit/org/apache/cassandra/db/memtable/MemtableQuickTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/SimpleReadWriteTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/DurableWritesTest.java`

## 待继续

- 展开二级索引和 materialized view 的完整写放大链路。
- 本地读路径、Memtable/SSTable merge、row cache/key cache 已在 `module-local-read-merge-cache-deep-dive.md` 展开。
- Range read 与 storage engine 的逐分片交互已在 `module-range-read-storage-engine-matrix.md` 展开，并由 `research/tools/check-range-read-storage-drift.py` 保护；剩余缺口是 range read 分布式 fault/perf 专项覆盖。
- SSTable 状态事务已在 `module-storage-engine-lifecycle-transaction.md` 展开。
