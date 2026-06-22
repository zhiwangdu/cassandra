# Flow: Counter Write

## 目标

解释 counter mutation 为什么不是普通 blind write：它需要在一个 leader replica 上读取当前 counter 值、加锁、生成新的 counter context，再把结果 mutation 复制给其它 replicas。

## 文字版调用图

```text
Client / Driver
  -> CQL counter UPDATE
  -> ModificationStatement.executeWithoutCondition()
     -> isCounter()
     -> validate counter write CL
     -> getMutations() builds CounterMutation
     -> StorageProxy.mutateWithTriggers()
        -> StorageProxy.mutate()
           -> mutation instanceof CounterMutation
           -> mutateCounter(counterMutation, localDataCenter, requestTime)
              -> findSuitableReplica()
                 -> choose alive RPC-ready local DC replica when possible
              -> if leader is self:
                   applyCounterMutationOnCoordinator()
              -> else:
                   send COUNTER_MUTATION_REQ to leader replica

Leader replica:
  CounterMutationVerbHandler.applyMutation()
    -> StorageProxy.applyCounterMutationOnLeader()
       -> performWrite(..., counterWritePerformer, WriteType.COUNTER)
       -> counterWriteTask()
          -> CounterMutation.applyCounterMutation()
             -> acquire striped counter locks
             -> collect counter marks
             -> fill current values from counter cache
             -> read cache misses from ColumnFamilyStore
             -> create new global counter values
             -> apply local result Mutation
          -> responseHandler.onResponse()
          -> sendToHintedReplicas(result, ...)
```

## 关键源码锚点

| 阶段 | 文件/方法 |
|---|---|
| counter CL 校验 | `ModificationStatement.executeWithoutCondition()`：`src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:511-529` |
| mutate 分流 | `StorageProxy.mutate()`：`src/java/org/apache/cassandra/service/StorageProxy.java:880-905` |
| counter performer 定义 | `StorageProxy` static block：`src/java/org/apache/cassandra/service/StorageProxy.java:232-250` |
| counter coordinator | `StorageProxy.mutateCounter()`：`src/java/org/apache/cassandra/service/StorageProxy.java:1710-1754` |
| leader replica 选择 | `StorageProxy.findSuitableReplica()`：`src/java/org/apache/cassandra/service/StorageProxy.java:1757-1802` |
| remote verb handler | `CounterMutationVerbHandler.applyMutation()`：`src/java/org/apache/cassandra/db/CounterMutationVerbHandler.java:37-53` |
| leader/coordinator apply | `applyCounterMutationOnLeader()` / `applyCounterMutationOnCoordinator()`：`src/java/org/apache/cassandra/service/StorageProxy.java:1804-1818` |
| counter task | `StorageProxy.counterWriteTask()`：`src/java/org/apache/cassandra/service/StorageProxy.java:1820-1836` |
| counter mutation class | `CounterMutation`：`src/java/org/apache/cassandra/db/CounterMutation.java:55-64` |
| counter apply 主体 | `CounterMutation.applyCounterMutation()`：`src/java/org/apache/cassandra/db/CounterMutation.java:116-156` |
| counter locks | `CounterMutation.grabCounterLocks()`：`src/java/org/apache/cassandra/db/CounterMutation.java:158-170` |
| cache/CFS 当前值 | `CounterMutation.processModifications()`：`src/java/org/apache/cassandra/db/CounterMutation.java:207-228` |
| 新 counter value | `CounterMutation.updateWithCurrentValue()`：`src/java/org/apache/cassandra/db/CounterMutation.java:231-239` |

## 与普通写的差异

- `StorageProxy.mutate()` 对 `CounterMutation` 直接走 `mutateCounter()`，普通 mutation 才走 `performWrite(..., standardWritePerformer, WriteType.SIMPLE/UNLOGGED_BATCH)`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:889-895`。
- Counter 当前只支持 non-counter cheap quorum 的额外 replica 尝试；普通写可能 `maybeTryAdditionalReplicas()`，counter 被跳过，见 `src/java/org/apache/cassandra/service/StorageProxy.java:897-902`。
- `CounterMutation.hintOnFailure()` 返回 `null`，普通 hint-on-failure 不能安全用于 counter，见 `src/java/org/apache/cassandra/db/CounterMutation.java:85-88`。
- `hintMutations()` 在 CL=ANY fallback 时也跳过 counters，见 `src/java/org/apache/cassandra/service/StorageProxy.java:960-972`。

## 配置与观测

- `counter_write_request_timeout` 定义在 `src/java/org/apache/cassandra/config/Config.java:153-154`，模板见 `conf/cassandra.yaml:1331-1334`。
- `concurrent_counter_writes` 定义在 `src/java/org/apache/cassandra/config/Config.java:179-181`，模板见 `conf/cassandra.yaml:716-724`。
- `counter_cache_size`、`counter_cache_save_period`、`counter_cache_keys_to_save` 模板说明见 `conf/cassandra.yaml:581-607`。
- counter cache size 由 `DatabaseDescriptor.getCounterCacheSizeInMiB()` 暴露，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3946-3949`。
- `StorageProxyMBean` 暴露 counter write timeout getter/setter，见 `src/java/org/apache/cassandra/service/StorageProxy.java:2839-2840`。

## 失败语义

- counter locks 在 `getTimeout()` 剩余时间内拿不到会抛 `WriteTimeoutException(WriteType.COUNTER)`，见 `src/java/org/apache/cassandra/db/CounterMutation.java:158-170`。
- coordinator 不是 replica 时，会先构造 forwarding counter write plan 做 CL 可用性检查，再发送 `COUNTER_MUTATION_REQ`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1731-1752`。
- leader replica 的 verb handler 不在当前线程等待写完成，而是用 callback 回包，避免 counter verb handler 间分布式死锁，见 `src/java/org/apache/cassandra/db/CounterMutationVerbHandler.java:42-53`。

## 排查路径

1. 热点 counter 先看 timeout 是否来自 lock 等待：`CounterMutation.applyCounterMutation()` tracing 有 `Acquiring counter locks`，见 `src/java/org/apache/cassandra/db/CounterMutation.java:134-140`。
2. 判断是否 cache miss 导致读放大：tracing 区分从 counter cache 取值和从 CFS 读取，见 `src/java/org/apache/cassandra/db/CounterMutation.java:213-222`。
3. 多 DC counter 写关注 leader 选择：本 DC 没有 alive replica 且 CL 是 local，会直接 unavailable，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1790-1799`。
4. 不要用 logged batch 包 counter；CQL validation 明确拒绝 logged counter batch，见 `src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:211-221`。

## 测试用例

- `test/distributed/org/apache/cassandra/distributed/test/CountersTest.java`
- `test/unit/org/apache/cassandra/db/CounterMutationTest.java`
- `test/unit/org/apache/cassandra/db/CounterMutationVerbHandlerOutOfRangeTest.java`
- `test/unit/org/apache/cassandra/db/CounterCacheTest.java`
- `test/unit/org/apache/cassandra/db/context/CounterContextTest.java`
- `test/unit/org/apache/cassandra/cql3/validation/entities/CountersTest.java`
