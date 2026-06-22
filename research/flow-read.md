# Flow: Read Path

## 目标

读取链路说明一条 SELECT 如何从 native protocol 到 coordinator，再到 replicas 的 data/digest read，最后返回 CQL rows。该文档聚焦单分区普通读；range read、read repair 细节后续单独扩展。

## 文字版调用图

```text
Client / Driver
  -> QueryMessage.execute(state, requestTime, traceRequest)
     -> ClientState.getCQLQueryHandler()
     -> queryHandler.parse(query, state, options)
     -> queryHandler.process(statement, state, options, payload, requestTime)
        -> QueryProcessor.process(...)
           -> options.prepare(bindVariables)
           -> processStatement(statement, queryState, options, requestTime)
              -> statement.authorize(clientState)
              -> statement.validate(clientState)
              -> SelectStatement.execute(...)
                 -> cl.validateForRead()
                 -> build DataLimits / selectors / column filter / row filter
                 -> getQuery(...)
                    -> if key range: getRangeCommand(...)
                    -> else: getSliceCommands(...)
                 -> query.execute(consistency, state, requestTime)
                    -> StorageProxy.read(group, consistency, requestTime)
                       -> reject unsafe bootstrap read / denylisted partition
                       -> if serial CL: readWithPaxos(...)
                       -> else: readRegular(...)
                          -> fetchRows(commands, consistency, requestTime)
                             -> for each command:
                                -> AbstractReadExecutor.getReadExecutor(...)
                                   -> ReplicaPlans.forRead(...)
                                   -> choose Never/Always/SpeculatingReadExecutor
                                -> mark local/remote request metric
                             -> executeAsync()
                                -> makeFullDataRequests(...)
                                -> makeTransientDataRequests(...)
                                -> makeDigestRequests(...)
                             -> maybeTryAdditionalReplicas()
                             -> awaitResponses()
                                -> ReadCallback.awaitResults()
                                -> DigestResolver.responsesMatch()
                                -> if match: DigestResolver.getData()
                                -> else: readRepair.startRepair(...)
                             -> maybeSendAdditionalDataRequests()
                             -> awaitReadRepair()
                             -> getResult()
                          -> concatAndBlockOnRepair(results, repairs)
                 -> SelectStatement.processResults(...)
                 -> ResultMessage.Rows
```

Replica 端：

```text
MessagingService receives READ_REQ
  -> ReadCommandVerbHandler.doVerb(message)
     -> reject if StorageService.isBootstrapMode()
     -> validate out-of-range and transient status
     -> command.setMonitoringTime(...)
     -> if message.trackWarnings(): command.trackWarnings()
     -> try ReadExecutionController
        -> command.executeLocally(controller)
           -> ReadCommand.executeLocally()
              -> Keyspace.openAndGetStore(metadata)
              -> optional indexQueryPlan.searcherFor(this)
              -> queryStorage(cfs, executionController)
                 -> SinglePartitionReadCommand.queryStorage()
                    -> if row cache enabled and not tracking repaired status:
                       -> getThroughCache(...)
                    -> else:
                       -> queryMemtableAndDisk(...)
                          -> cfs.select(live SSTables and memtables)
                          -> memtable.rowIterator(...)
                          -> for each live SSTable:
                             -> intersects/static/deletion checks
                             -> make row iterator
                          -> inputCollector.finalizeIterators(...)
              -> withQuerySizeTracking(...)
              -> withQueryCancellation(...)
              -> withoutPurgeableTombstones(...)
              -> withMetricsRecording(...)
        -> command.createResponse(iterator, repairedDataInfo)
     -> message.responseWith(response)
     -> MessagingService.send(reply, coordinator)
```

Coordinator response path:

```text
ReadCallback.onResponse(message)
  -> warning context update
  -> resolver.preprocess(message)
  -> if data is present and responses >= blockFor:
     -> condition.signalAll()

AbstractReadExecutor.awaitResponses()
  -> handler.awaitResults()
  -> if digestResolver.responsesMatch()
     -> setResult(digestResolver.getData())
  -> else
     -> readRepair.startRepair(digestResolver, setResult)
```

## 关键源码锚点

| 阶段 | 文件/方法 |
|---|---|
| Native query 执行 | `QueryMessage.execute()`：`src/java/org/apache/cassandra/transport/messages/QueryMessage.java:102-131` |
| CQL authorize/validate/execute | `QueryProcessor.processStatement()`：`src/java/org/apache/cassandra/cql3/QueryProcessor.java:266-279` |
| SELECT 执行入口 | `SelectStatement.execute()`：`src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:280-360` |
| 构造 ReadQuery | `SelectStatement.getQuery()`：`src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:395-415` |
| SELECT 读取并处理结果 | `SelectStatement.execute(ReadQuery...)`：`src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:417-430` |
| Coordinator read | `StorageProxy.read()`：`src/java/org/apache/cassandra/service/StorageProxy.java:1858-1885` |
| 常规读 metrics/异常 | `StorageProxy.readRegular()`：`src/java/org/apache/cassandra/service/StorageProxy.java:2004-2058` |
| fetch rows 协议 | `StorageProxy.fetchRows()`：`src/java/org/apache/cassandra/service/StorageProxy.java:2095-2175` |
| 创建 read executor | `AbstractReadExecutor.getReadExecutor()`：`src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:190-218` |
| data/digest requests | `AbstractReadExecutor.executeAsync()`：`src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:176-185` |
| remote/local request 发送 | `AbstractReadExecutor.makeRequests()`：`src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:134-166` |
| speculation 判断 | `AbstractReadExecutor.shouldSpeculateAndMaybeWait()`：`src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:226-253` |
| 等待与 digest mismatch | `AbstractReadExecutor.awaitResponses()`：`src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:400-444` |
| read repair 等待 | `AbstractReadExecutor.awaitReadRepair()`：`src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:446-461` |
| replica read handler | `ReadCommandVerbHandler.doVerb()`：`src/java/org/apache/cassandra/db/ReadCommandVerbHandler.java:50-129` |
| 本地 read command | `ReadCommand.executeLocally()`：`src/java/org/apache/cassandra/db/ReadCommand.java:426-470` |
| row cache 分支 | `SinglePartitionReadCommand.queryStorage()`：`src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:487-545` |
| memtable/SSTable 合并 | `SinglePartitionReadCommand.queryMemtableAndDiskInternal()`：`src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:679-840` |
| 本地 merge/cache 深水区 | `research/module-local-read-merge-cache-deep-dive.md` |

## Data/Digest 读细节

- `executeAsync()` 从 contacts 中选 full data requests，再给其他 full replicas 发 digest requests，见 `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:176-185`。
- `DigestResolver.preprocess()` 保存第一份 full data response，见 `src/java/org/apache/cassandra/service/reads/DigestResolver.java:55-62`。
- `DigestResolver.responsesMatch()` 比较 full replicas 的 digest，不比较 transient response，见 `src/java/org/apache/cassandra/service/reads/DigestResolver.java:105-128`。
- digest match 时 `getData()` 直接返回 data response 的 iterator；若 transient data 也参与，则用 `DataResolver` reconcile，见 `src/java/org/apache/cassandra/service/reads/DigestResolver.java:77-102`。
- digest mismatch 时 `readRepair.startRepair(...)`，见 `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:427-435`。

## 本地读细节

- `ReadCommand.executeLocally()` 先检查二级索引 queryability，再决定走 index searcher 或 storage query，见 `src/java/org/apache/cassandra/db/ReadCommand.java:433-452`。
- 本地读经过 query size tracking、cancellation、purgeable tombstone 过滤和 metrics recording，见 `src/java/org/apache/cassandra/db/ReadCommand.java:455-462`。
- Row cache 命中会更新 `rowCacheHit`，cache 无法覆盖 filter 会更新 `rowCacheHitOutOfRange` 并回退到 disk/memtable，见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:516-543`。
- Memtable 数据永远视为 unrepaired，并更新 repaired tracking 上下文，见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:718-732`。
- SSTable 根据 intersects/statics/partition deletion 决定是否创建 iterator，见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:757-827`。
- 本地 replica 的 row-cache sentinel、timestamp-order names-filter、repaired-data tracking 和 key-cache 边界见 `research/module-local-read-merge-cache-deep-dive.md`。

## 观测与排查

| 现象 | 重点指标/日志 | 代码依据 |
|---|---|---|
| 读 timeout | `ClientRequest.Read.Timeouts`、trace/debug "Timed out; received..." | `src/java/org/apache/cassandra/service/reads/ReadCallback.java:128-170` |
| digest mismatch | Blocking read repair 日志、read repair metrics | `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:432-441` |
| tombstone warning/abort | `tombstoneWarnings`、`tombstoneFailures`、日志 `Read X live rows and Y tombstone cells...` | `src/java/org/apache/cassandra/db/ReadCommand.java:588-649` |
| row cache 效果差 | `rowCacheHit`、`rowCacheMiss`、`rowCacheHitOutOfRange` | `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:516-543` |
| 读放大 | `sstablesPerReadHistogram`、live SSTable count | `src/java/org/apache/cassandra/metrics/TableMetrics.java:110-143` |
| speculation 过多 | `speculativeRetries`、`speculativeFailedRetries` | `src/java/org/apache/cassandra/metrics/TableMetrics.java:224-227` |
| 非本范围读 | replica warn `Received a read request...not owned...` | `src/java/org/apache/cassandra/db/ReadCommandVerbHandler.java:158-160` |

## 测试用例

- `test/unit/org/apache/cassandra/service/reads/ReadExecutorTest.java`
- `test/unit/org/apache/cassandra/service/reads/DataResolverTest.java`
- `test/unit/org/apache/cassandra/service/reads/DigestResolverTest.java`
- `test/unit/org/apache/cassandra/service/reads/repair/BlockingReadRepairTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/ReadDigestConsistencyTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/ReadSpeculationTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/SSTableSkippingReadTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/ShortReadProtectionTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/thresholds/CoordinatorReadSizeWarningTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/thresholds/LocalReadSizeWarningTest.java`
