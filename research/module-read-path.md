# Module: Read Path

## 范围

本模块覆盖单分区读、range read、digest/data read、read repair 和本地 storage engine 读取主线，不展开每个索引实现细节。

## 设计目标

读取链路负责把 CQL SELECT 转换成 `ReadQuery`，由 coordinator 选择 replicas，向 replica 发送 data/digest read，在满足一致性级别后校验 digest，必要时触发 blocking read repair，最终把本地/远端数据合并成 CQL rows。

设计目标：

- 支持单分区读、range read、分页、聚合、top-K、二级索引和本地 system 查询。
- Coordinator 使用 snitch/replica plan 选择最近 replicas，并用 data/digest 模式降低网络传输。
- Local replica 从 row cache、memtable、SSTable 中读取并做 tombstone/size/latency 观测。
- Digest mismatch 时执行 read repair，保证返回数据与修复写入的顺序正确。
- 支持 speculative retry，在初始 replica 响应慢时向额外 replica 发送读请求。

## 解决的问题

- 读请求不能在 bootstrapping 节点上服务普通数据：coordinator `StorageProxy.read()` 会检查 `isSafeToPerformRead()`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1858-1885`；replica `ReadCommandVerbHandler` 也会拒绝 bootstrap 模式，见 `src/java/org/apache/cassandra/db/ReadCommandVerbHandler.java:50-55`。
- 多副本读需要避免传输所有数据：`AbstractReadExecutor.executeAsync()` 向部分 replicas 发送 full data，对其他 full replicas 发送 digest，见 `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:176-185`。
- 多副本返回可能不一致：`DigestResolver.responsesMatch()` 对 full replicas 的 digest 做比较，见 `src/java/org/apache/cassandra/service/reads/DigestResolver.java:105-128`。
- 本地读要合并 memtable 与 SSTable：`SinglePartitionReadCommand.queryMemtableAndDiskInternal()` 收集 memtable iterator 与 SSTable iterator，见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:679-840`。
- 读大分区/tombstone 需要保护：`ReadCommand.withMetricsRecording()` 统计 tombstones 并在阈值触发 warning/failure，见 `src/java/org/apache/cassandra/db/ReadCommand.java:525-653`。

## 设计取舍

- Coordinator 默认只取一个 data response，其余用 digest，减少网络与反序列化成本，但 digest mismatch 会触发额外 full data reads。
- 本地读延迟到 remote requests 发出之后执行，避免本地阻塞影响 remote 并发，见 `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:161-166`。
- Row cache 只用于单分区读，并且 tracking repaired status 时绕过 row cache，见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:487-493`。
- Speculative retry 依赖表级 speculative retry policy 和本地样本延迟；EACH_QUORUM 禁用 speculation，见 `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:190-218`。
- Range read 当前不支持 read repair/rapid read protection 的同级能力，`ReadCallback` 对 range command 有断言约束，见 `src/java/org/apache/cassandra/service/reads/ReadCallback.java:78-90`。

## 核心类

| 类 | 作用 |
|---|---|
| `QueryMessage` | native protocol query 请求入口，parse/process 并返回 response。执行方法见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:102-131` |
| `QueryProcessor` | CQL parse、authorize、validate、execute 分发。`processStatement()` 见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:266-279` |
| `SelectStatement` | SELECT statement 执行、构建 `ReadQuery`、分页、结果处理。执行入口见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:280-360` |
| `StorageProxy` | coordinator 读入口、Paxos/regular 分支、fetch rows、metrics/exception 处理。读入口见 `src/java/org/apache/cassandra/service/StorageProxy.java:1858-1885` |
| `AbstractReadExecutor` | 单分区读请求调度、data/digest requests、speculation、read repair。构造与请求发送见 `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:80-185` |
| `ReadCallback` | 等待 blockFor 响应，处理 warnings/failures，接收本地和远端 response。定义见 `src/java/org/apache/cassandra/service/reads/ReadCallback.java:58` |
| `DigestResolver` | 保存 data response、比较 digests、返回 data 或触发 repair。定义见 `src/java/org/apache/cassandra/service/reads/DigestResolver.java:44` |
| `DataResolver` | 对 full data responses 做 reconciliation、short read protection、read repair 结果生成。定义见 `src/java/org/apache/cassandra/service/reads/DataResolver.java:62` |
| `ReadCommand` | 本地读抽象，执行 index/local storage/metrics/tombstone/size tracking。定义见 `src/java/org/apache/cassandra/db/ReadCommand.java:91` |
| `SinglePartitionReadCommand` | 单分区本地读，支持 row cache、memtable/SSTable 查询。定义见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:90` |
| `ReadCommandVerbHandler` | replica 端 READ_REQ/RANGE_REQ 处理器。定义见 `src/java/org/apache/cassandra/db/ReadCommandVerbHandler.java:42` |

## 核心接口

- `ReadQuery`：`SelectStatement.getQuery()` 返回单分区或 range read query，分支见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:395-415`。
- `RequestCallback<ReadResponse>`：`ReadCallback` 实现它，用于 MessagingService 回调，见 `src/java/org/apache/cassandra/service/reads/ReadCallback.java:58`。
- `ResponseResolver`：`DigestResolver` 和 `DataResolver` 的父抽象，负责积累 read responses。
- `Index.Searcher`：`ReadCommand.executeLocally()` 若存在 index query plan，则走 index searcher，见 `src/java/org/apache/cassandra/db/ReadCommand.java:433-452`。
- `UnfilteredPartitionIterator` / `UnfilteredRowIterator`：read path 的内部数据流。

## 核心数据结构

- `ReadCommand`：包含 table metadata、column filter、row filter、limits、nowInSec、digest query 标记。
- `SinglePartitionReadCommand.Group`：StorageProxy 对一组单分区命令统一处理，入口见 `src/java/org/apache/cassandra/service/StorageProxy.java:1858`。
- `ReplicaPlan.ForTokenRead`：读副本计划，`AbstractReadExecutor.getReadExecutor()` 调用 `ReplicaPlans.forRead(...)` 创建，见 `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:190-200`。
- `ReadResponse`：可为 data response 或 digest response；工厂方法见 `src/java/org/apache/cassandra/db/ReadResponse.java:46-81`。
- `ColumnFamilyStore.ViewFragment`：本地读时持有当前 memtables 和 live SSTables，获取见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:663-665`。
- `InputCollector<UnfilteredRowIterator>`：本地读收集 memtable/SSTable iterators，并最终 merge，见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:713-840`。

## 生命周期

```text
Client SELECT
  -> QueryMessage.execute()
     -> QueryHandler.parse(query, state, options)
     -> QueryHandler.process(statement, state, options, payload, requestTime)
        -> QueryProcessor.processStatement()
           -> authorize()
           -> validate()
           -> SelectStatement.execute()
              -> cl.validateForRead()
              -> build DataLimits / ColumnFilter / RowFilter
              -> getQuery(...)
              -> query.execute(consistency, state, requestTime)
                 -> StorageProxy.read(...)
                    -> readRegular() or readWithPaxos()
                    -> fetchRows(...)
                       -> AbstractReadExecutor.getReadExecutor(...)
                       -> executeAsync()
                       -> maybeTryAdditionalReplicas()
                       -> awaitResponses()
                       -> maybeSendAdditionalDataRequests()
                       -> awaitReadRepair()
                       -> getResult()
              -> processResults(...)
```

Replica 端：

```text
MessagingService receives READ_REQ/RANGE_REQ
  -> ReadCommandVerbHandler.doVerb(message)
     -> reject if bootstrap mode
     -> validate token/transient status
     -> command.executionController(...)
     -> command.executeLocally(controller)
        -> ReadCommand.executeLocally()
           -> optional index searcher
           -> queryStorage(...)
              -> SinglePartitionReadCommand.queryStorage()
                 -> row cache if enabled and safe
                 -> queryMemtableAndDisk(...)
                    -> cfs.select(live view)
                    -> memtable.rowIterator(...)
                    -> SSTable row iterator
                    -> merge iterators
           -> size/tombstone/latency metrics
     -> command.createResponse(iterator, repairedDataInfo)
     -> send READ_RSP/RANGE_RSP
```

## 调用链

- Native CQL 入口：`QueryMessage.execute()` 调用 query handler parse/process，见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:102-131`。
- CQL statement 执行：`QueryProcessor.processStatement()` authorize/validate 后执行 statement，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:266-279`。
- SELECT 构造 read query：`SelectStatement.execute()` 调用 `getQuery()`，见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:280-360`、`src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:395-415`。
- Coordinator 读入口：`StorageProxy.read()`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1858-1885`。
- 常规读：`StorageProxy.readRegular()` 调用 `fetchRows()` 并记录 metrics，见 `src/java/org/apache/cassandra/service/StorageProxy.java:2004-2058`。
- fetch rows 读协议：注释列出 5 步 data/digest/read repair 流程，见 `src/java/org/apache/cassandra/service/StorageProxy.java:2095-2105`；实现见 `src/java/org/apache/cassandra/service/StorageProxy.java:2106-2175`。
- Replica 读：`ReadCommandVerbHandler.doVerb()` 本地执行并响应，见 `src/java/org/apache/cassandra/db/ReadCommandVerbHandler.java:50-129`。
- 本地 storage 查询：`ReadCommand.executeLocally()` 与 `SinglePartitionReadCommand.queryMemtableAndDiskInternal()`，见 `src/java/org/apache/cassandra/db/ReadCommand.java:426-470`、`src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:679-840`。

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| `read_request_timeout` | `src/java/org/apache/cassandra/config/Config.java:144-145`，模板 `conf/cassandra.yaml:1322` | 单分区读超时 |
| `range_request_timeout` | `src/java/org/apache/cassandra/config/Config.java:147-148`，模板 `conf/cassandra.yaml:1326` | range read 超时 |
| `row_cache_size` | `src/java/org/apache/cassandra/config/Config.java:472-474`，模板 `conf/cassandra.yaml:564` | row cache 容量 |
| `key_cache_size` | `src/java/org/apache/cassandra/config/Config.java:464-470`，模板 `conf/cassandra.yaml:525` | key cache 容量 |
| `tombstone_warn_threshold` | `src/java/org/apache/cassandra/config/Config.java:534`，模板 `conf/cassandra.yaml:1814` | replica 本地读 tombstone warning |
| `tombstone_failure_threshold` | `src/java/org/apache/cassandra/config/Config.java:535`，模板 `conf/cassandra.yaml:1815` | replica 本地读 tombstone abort |
| `local_read_size_warn_threshold` / `local_read_size_fail_threshold` | `src/java/org/apache/cassandra/config/Config.java:529-530`，模板 `conf/cassandra.yaml:2025-2026` | replica 本地读取数据量保护 |
| `coordinator_read_size_warn_threshold` / `coordinator_read_size_fail_threshold` | `src/java/org/apache/cassandra/config/Config.java:527-528`，模板 `conf/cassandra.yaml:2017-2022` | coordinator 结果大小保护 |
| `partition_denylist_enabled` / `denylist_reads_enabled` | `src/java/org/apache/cassandra/config/Config.java:759-763`，模板 `conf/cassandra.yaml:1438-1442` | denylist 读拒绝 |
| 表级 `speculative_retry` | `src/java/org/apache/cassandra/schema/TableParams.java:344` | 控制 read executor 是否 speculative retry |

## Metrics

- `ClientRequestMetrics.readMetrics`：timeouts/unavailables/failures/localRequests/remoteRequests，定义见 `src/java/org/apache/cassandra/metrics/ClientRequestMetrics.java:32-55`。
- `TableMetrics.readLatency`、`rangeLatency`：本地读延迟，定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:114-119`。
- `TableMetrics.coordinatorReadLatency`：coordinator 记录读延迟，更新见 `src/java/org/apache/cassandra/service/StorageProxy.java:2052-2058`。
- `TableMetrics.sstablesPerReadHistogram`、`sstablesPerRangeReadHistogram`：SSTable 读放大，定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:110-113`。
- `TableMetrics.rowCacheHit`、`rowCacheMiss`、`rowCacheHitOutOfRange`：定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:164-169`，更新见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:516-543`。
- `TableMetrics.tombstoneScannedHistogram`、`liveScannedHistogram`、`tombstoneWarnings`、`tombstoneFailures`：定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:152-177`，更新见 `src/java/org/apache/cassandra/db/ReadCommand.java:588-649`。
- `TableMetrics.speculativeRetries`、`speculativeFailedRetries`、`speculativeInsufficientReplicas`：定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:224-227`，更新见 `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:281-359`。
- `TableMetrics.localReadSizeWarnings/Aborts` 与 `coordinatorReadSizeWarnings/Aborts`：定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:274-280`。

## 日志

- CQL unexpected error：`QueryMessage.execute()` 记录 `Unexpected error during query`，见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:125-131`。
- Aggregation 无 partition key / IN restriction：`SelectStatement.execute()` 记录 warn 并发 ClientWarn，见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:519-532`。
- Read timeout/failure trace/debug：`ReadCallback.awaitResults()`，见 `src/java/org/apache/cassandra/service/reads/ReadCallback.java:161-170`。
- Blocking read repair：`AbstractReadExecutor.awaitResponses()` 可记录 `Blocking Read Repair triggered...`，见 `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:432-441`。
- Replica 收到非本范围读：`ReadCommandVerbHandler` 的 warn，见 `src/java/org/apache/cassandra/db/ReadCommandVerbHandler.java:158-160`。
- Tombstone warning：`ReadCommand.withMetricsRecording()` logger.warn，见 `src/java/org/apache/cassandra/db/ReadCommand.java:629-645`。
- Speculative retry trace：`AbstractReadExecutor.SpeculatingReadExecutor`，见 `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:345-349`。

## 运维关注点

- 读 timeout 不一定是 replica 没返回，也可能只返回了 digest 没返回 data；`ReadCallback.awaitResults()` 明确检查 `resolver.isDataPresent()`，见 `src/java/org/apache/cassandra/service/reads/ReadCallback.java:128-145`。
- Digest mismatch 会触发 blocking read repair，读延迟会被 repair reads/writes 拉高。
- Row cache 命中可显著降低 SSTable 访问，但写入会使缓存失效；row cache out-of-range 表示缓存分区不能覆盖当前 filter。
- `sstablesPerReadHistogram` 高是 compaction backlog、重叠 SSTable 或数据模型问题的信号。
- tombstone warning/failure 是读路径最常见故障之一，应结合表设计、TTL/delete、compaction 和查询模式排查。
- speculative retry 可以降低尾延迟，但会增加读放大和跨节点流量。

## 性能瓶颈

- Coordinator 等待 blockFor 响应和 digest comparison，是跨节点读的核心延迟。
- 本地读合并多个 memtable/SSTable iterator，SSTable 数越多、overlap 越大，CPU/I/O 放大越明显。
- Tombstone 多会增加扫描、内存和网络成本，并可能触发 abort。
- 二级索引查询会走 `Index.Searcher`，然后还要执行 post-index filter，见 `src/java/org/apache/cassandra/db/ReadCommand.java:433-466`。
- Range read 的 DataRange、subrange/paging、ReplicaPlan、dynamic concurrency、本地 memtable/SSTable scan、row cache filter 和 metrics 已在 `research/flow-range-read.md` 与 `research/module-range-read-storage-engine-matrix.md` 展开。

## 常见故障

- `IsBootstrappingException`：coordinator 在 bootstrap mode 下读普通表，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1861-1868`。
- `ReadTimeoutException`：`ReadCallback.awaitResults()` 没在 deadline 前收到足够且包含 data 的响应，见 `src/java/org/apache/cassandra/service/reads/ReadCallback.java:128-170`。
- Digest mismatch 导致 blocking read repair 超时：`awaitReadRepair()` 转换为原 CL 的 read timeout，见 `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:446-461`。
- Tombstone abort：超过 `tombstone_failure_threshold` 抛 `TombstoneOverwhelmingException`，见 `src/java/org/apache/cassandra/db/ReadCommand.java:588-602`。
- Read size abort：超过 `local_read_size_fail_threshold` 时在 query size tracking 中 abort，见 `src/java/org/apache/cassandra/db/ReadCommand.java:663-720`。
- 非本 token range 读：replica 端记录 out-of-range，并可按配置拒绝，见 `src/java/org/apache/cassandra/db/ReadCommandVerbHandler.java:59-79`。

## 测试用例

- `test/unit/org/apache/cassandra/service/reads/ReadExecutorTest.java`
- `test/unit/org/apache/cassandra/service/reads/DataResolverTest.java`
- `test/unit/org/apache/cassandra/service/reads/DigestResolverTest.java`
- `test/unit/org/apache/cassandra/service/reads/repair/BlockingReadRepairTest.java`
- `test/unit/org/apache/cassandra/service/reads/repair/ReadRepairTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/ReadDigestConsistencyTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/ReadFailureTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/ReadSpeculationTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/SSTableSkippingReadTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/ShortReadProtectionTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/SinglePartitionReadCommandTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/thresholds/CoordinatorReadSizeWarningTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/thresholds/LocalReadSizeWarningTest.java`

## 待继续

- Range read 已在 `research/flow-range-read.md` 与 `research/module-range-read-storage-engine-matrix.md` 展开，并由 `research/tools/check-range-read-storage-drift.py` 保护；剩余缺口是多 vnode/多 remote replica/repaired-data tracking 分布式 fault coverage、row cache per-partition substitution focused test 和 range read 性能矩阵。
- 单独展开 consistency level：`blockFor`、local/global CL、serial CL 与 transient replication。
- 单独展开 read repair：blocking vs none、repair mutation、short read protection、replica filtering protection。
- row cache/key cache 与 Memtable/SSTable merge 已在 `module-local-read-merge-cache-deep-dive.md` 展开；Bloom/index summary/BTI 细节见 `module-bloom-sstable-index-deep-dive.md`。
