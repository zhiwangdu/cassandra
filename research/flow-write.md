# Flow: Write Path

## 目标

写入链路解释一条普通 CQL mutation 如何从 coordinator 进入 replicas，并在本地 replica 完成 CommitLog + Memtable 写入后向 coordinator 响应。

## 文字版调用图

```text
Client / Driver
  -> Native protocol message
  -> QueryProcessor / ModificationStatement builds Mutation
  -> StorageProxy.mutate(mutations, consistencyLevel, requestTime)
     -> for each mutation
        -> StorageProxy.performWrite(...)
           -> Keyspace.open(keyspaceName)
           -> mutation.key().getToken()
           -> ReplicaPlans.forWrite(keyspace, consistencyLevel, token, writeNormal)
           -> replicationStrategy.getWriteResponseHandler(...)
           -> standardWritePerformer.apply(...)
              -> StorageProxy.sendToHintedReplicas(...)
                 -> Mutation.serializer.prepareSerializedBuffer(...)
                 -> for destination in replicaPlan.contacts()
                    -> if destination is self
                       -> apply locally on Stage.MUTATION
                    -> else if alive
                       -> Message.outWithFlags(MUTATION_REQ, mutation, ...)
                       -> MessagingService.send(...)
                    -> else if hints allowed
                       -> submit hint
     -> responseHandler.get()
        -> success / WriteTimeoutException / WriteFailureException

Remote replica:
  MessagingService receives MUTATION_REQ
    -> MutationVerbHandler.doVerb(message)
       -> validate timeout and mutation size
       -> processMessage(...)
       -> applyMutation(message, respondToAddress)
          -> message.payload.applyFuture()
             -> Mutation.apply()
                -> Keyspace.apply(...)
                   -> getWriteHandler().beginWrite(...)
                      -> Keyspace.writeOrder.start()
                      -> CommitLog.instance.add(mutation)
                   -> for each PartitionUpdate
                      -> maybe materialized view update
                      -> ColumnFamilyStore.apply(...)
                         -> data.getMemtableFor(opGroup, commitLogPosition)
                         -> indexManager.newUpdateTransaction(...)
                         -> Memtable.put(update, indexer, opGroup)
                         -> invalidateCachedPartition(key)
                         -> update TableMetrics
          -> MessagingService.send(emptyResponse)

Coordinator:
  -> AbstractWriteResponseHandler receives enough replies for CL
  -> StorageProxy.mutate() returns to CQL/native layer
```

## 关键源码锚点

| 阶段 | 文件/方法 |
|---|---|
| coordinator 写入口 | `StorageProxy.mutate()`：`src/java/org/apache/cassandra/service/StorageProxy.java:878-930` |
| replica plan 与 handler | `StorageProxy.performWrite()`：`src/java/org/apache/cassandra/service/StorageProxy.java:1371-1395` |
| hinted/remote/local 分发 | `StorageProxy.sendToHintedReplicas()`：`src/java/org/apache/cassandra/service/StorageProxy.java:1475-1525` |
| replica verb handler | `MutationVerbHandler.doVerb()`：`src/java/org/apache/cassandra/db/MutationVerbHandler.java:44-65` |
| replica apply callback | `MutationVerbHandler.applyMutation()`：`src/java/org/apache/cassandra/db/MutationVerbHandler.java:72-76` |
| keyspace apply | `Keyspace.applyInternal()`：`src/java/org/apache/cassandra/db/Keyspace.java:523-660` |
| CommitLog append | `CassandraKeyspaceWriteHandler.addToCommitLog()`：`src/java/org/apache/cassandra/db/CassandraKeyspaceWriteHandler.java:67-99` |
| local table write | `ColumnFamilyStore.apply()`：`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1467-1508` |
| memtable put | `TrieMemtable.MemtableShard.put()`：`src/java/org/apache/cassandra/db/memtable/TrieMemtable.java:458-503` |

## 一致性和失败语义

- `performWrite()` 使用 `ReplicaPlans.forWrite(...)` 选择 contacts，并由 replication strategy 创建 write response handler，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1379-1393`。
- coordinator 在 `StorageProxy.mutate()` 最后对每个 response handler 调用 `get()`，未满足 CL 时抛 timeout/failure，见 `src/java/org/apache/cassandra/service/StorageProxy.java:904-930`。
- CL=ANY 且普通写失败时会尝试 `hintMutations(mutations)`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:908-913`。
- remote replica 如果请求已过期，会 drop message 并记录 dropped metric，见 `src/java/org/apache/cassandra/db/MutationVerbHandler.java:47-51`。

## 配置与观测

- 写并发：`concurrent_writes` 定义在 `src/java/org/apache/cassandra/config/Config.java:180`。
- 写超时：`write_request_timeout` 最小值校验见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1366-1370`。
- CommitLog sync：`commitlog_sync` 定义在 `src/java/org/apache/cassandra/config/Config.java:391`。
- 写请求 metrics：`ClientRequestMetrics` 定义 `timeouts`、`failures`、`localRequests`、`remoteRequests`，见 `src/java/org/apache/cassandra/metrics/ClientRequestMetrics.java:32-55`。
- 表写入 metrics：`TableMetrics.writeLatency` 定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:114-123`，更新见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:1483-1484`。
- tracing：`StorageProxy.mutate()` 记录 "Determining replicas for mutation"，见 `src/java/org/apache/cassandra/service/StorageProxy.java:878-882`；CommitLog append trace 在 `src/java/org/apache/cassandra/db/CassandraKeyspaceWriteHandler.java:98-99`。

## 运维排查路径

1. coordinator 写 timeout/failure：先看 `ClientRequest.Write.Timeouts/Failures` 与日志中的 received/blockFor。
2. local vs remote：看 `ClientRequestMetrics.localRequests/remoteRequests`，定义见 `src/java/org/apache/cassandra/metrics/ClientRequestMetrics.java:40-54`。
3. CommitLog 瓶颈：看 `CommitLog.WaitingOnCommit`、`WaitingOnSegmentAllocation`、`TotalCommitLogSize`，定义见 `src/java/org/apache/cassandra/metrics/CommitLogMetrics.java:35-55`。
4. Memtable/flush 瓶颈：看 `TableMetrics.pendingFlushes`、memtable sizes、`memtableSwitchCount`，定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:86-123`。
5. MV/index 写放大：看 `viewLockAcquireTime`、索引相关日志和热点 partition。

## 测试用例

- `test/unit/org/apache/cassandra/service/StorageProxyTest.java`
- `test/unit/org/apache/cassandra/service/WriteResponseHandlerTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/SimpleReadWriteTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/DurableWritesTest.java`
