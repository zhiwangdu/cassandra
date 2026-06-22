# Flow: Hinted Handoff And Batchlog

## 目标

说明普通写失败恢复的两条不同链路：

- Hinted Handoff：某个 replica 不可达时，为该 replica 保存一条未来可投递的 hint。
- Batchlog：logged batch 或 MV paired writes 先保存 batchlog，写入完成后删除；未删除的 batchlog 由后台 replay。

## Hinted Handoff 调用图

```text
StorageProxy.performWrite()
  -> standardWritePerformer
     -> sendToHintedReplicas(mutation, replicaPlan, responseHandler, localDC, ...)
        -> prepare serialized mutation buffer
        -> for each contact
           -> checkHintOverload(destination)
           -> if alive and self: local apply on Stage.MUTATION
           -> if alive and remote: MessagingService.send(...)
           -> if down:
                responseHandler.expired()
                shouldHint(destination)
                add to endpointsToHint
        -> submitHint(mutation, endpointsToHint, responseHandler)
           -> increment StorageMetrics.totalHintsInProgress
           -> Stage.MUTATION.submit(HintRunnable)
              -> resolve hostIds
              -> HintsService.write(hostIds, Hint.create(...))
              -> CL.ANY may count hint as response

HintsService.startDispatch()
  -> schedule HintsDispatchTrigger every 10s
  -> HintsDispatchExecutor.dispatch(store)
     -> one dispatch task per hostId
     -> poll HintsDescriptor
     -> deliver with HintsDispatcher
        -> full success: store.delete(descriptor), cleanup
        -> partial failure: mark dispatch offset, offer descriptor first
```

## Batchlog 调用图

```text
BatchStatement.executeWithoutConditions()
  -> verifyBatchSize()
  -> verifyBatchType()
  -> mutateAtomic = isLogged() && mutations.size() > 1
  -> StorageProxy.mutateWithTriggers(..., mutateAtomic)
     -> if mutateAtomic or updatesView:
          StorageProxy.mutateAtomically()
             -> select batchlog replica plan
             -> create batchUUID and BatchlogCleanup
             -> wrap each mutation response handler
             -> syncWriteToBatchlog()
                -> Batch.createLocal()
                -> send BATCH_STORE_REQ or BatchlogManager.store() locally
                -> wait for batchlog acks
             -> syncWriteBatchedMutations()
                -> each mutation ack decrements BatchlogCleanup
                -> when all required mutations ack: asyncRemoveFromBatchlog()
                   -> send BATCH_REMOVE_REQ or BatchlogManager.remove() locally

BatchlogManager background:
  -> start() schedules replayFailedBatches()
  -> query system.batches rows older than timeout
  -> processBatchlogEntries()
     -> ReplayingBatch.replay()
        -> deserialize mutations
        -> skip expired/truncated data
        -> direct deliver live replicas
        -> write hints for down/undelivered replicas
     -> flushAndFsyncBlockingly(hintedNodes)
     -> remove replayed batch rows
```

## 关键源码锚点

| 阶段 | 文件/方法 |
|---|---|
| ordinary write hints 分发 | `StorageProxy.sendToHintedReplicas()`：`src/java/org/apache/cassandra/service/StorageProxy.java:1475-1564` |
| hints 过载保护 | `StorageProxy.checkHintOverload()`：`src/java/org/apache/cassandra/service/StorageProxy.java:1585-1599` |
| hints JMX 开关 | `StorageProxy.get/setHintedHandoffEnabled()` 等：`src/java/org/apache/cassandra/service/StorageProxy.java:2372-2420` |
| shouldHint 过滤 | `StorageProxy.shouldHint()`：`src/java/org/apache/cassandra/service/StorageProxy.java:2423-2498` |
| submitHint | `StorageProxy.submitHint()`：`src/java/org/apache/cassandra/service/StorageProxy.java:2776-2828` |
| hints service 组成 | `HintsService` constructor：`src/java/org/apache/cassandra/hints/HintsService.java:101-128` |
| hints write | `HintsService.write()`：`src/java/org/apache/cassandra/hints/HintsService.java:161-171` |
| hints dispatch 启动 | `HintsService.startDispatch()`：`src/java/org/apache/cassandra/hints/HintsService.java:217-230` |
| dispatch executor | `HintsDispatchExecutor.dispatch()`：`src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:97-113` |
| hints deliver | `HintsDispatchExecutor.deliver()`：`src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:283-324` |
| logged batch 分流 | `BatchStatement.executeWithoutConditions()`：`src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:434-445` |
| counter batch validation | `BatchStatement` validation：`src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:180-221` |
| atomic batch | `StorageProxy.mutateAtomically()`：`src/java/org/apache/cassandra/service/StorageProxy.java:1173-1227` |
| batchlog store/remove | `syncWriteToBatchlog()` / `asyncRemoveFromBatchlog()`：`src/java/org/apache/cassandra/service/StorageProxy.java:1286-1321` |
| cleanup ack | `BatchlogResponseHandler`：`src/java/org/apache/cassandra/service/BatchlogResponseHandler.java:38-56`、`src/java/org/apache/cassandra/service/BatchlogResponseHandler.java:93-116` |
| batch store/remove verbs | `BatchStoreVerbHandler` / `BatchRemoveVerbHandler`：`src/java/org/apache/cassandra/batchlog/BatchStoreVerbHandler.java:24-32`、`src/java/org/apache/cassandra/batchlog/BatchRemoveVerbHandler.java:24-31` |
| batchlog store/remove local | `BatchlogManager.store()` / `remove()`：`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:125-165` |
| batchlog replay schedule | `BatchlogManager.start()`：`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:110-117` |
| batchlog replay scan | `BatchlogManager.replayFailedBatches()`：`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:200-226` |
| replay process | `processBatchlogEntries()`：`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:260-316` |
| replay delivery/hints | `ReplayingBatch`：`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:354-390`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:420-510` |

## Hints 语义边界

- `sendToHintedReplicas()` 注释区分 HH on/off 与 CL>=1/ANY 的行为；CL=ANY 下 hint 可以计入 consistency，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1465-1469`。
- `shouldHint()` 拒绝全局 disabled、transient/self replica、disabled DC、非 ring endpoint、超过 hint window 和超过 per-host hints size，见 `src/java/org/apache/cassandra/service/StorageProxy.java:2428-2498`。
- Hints 使用 hostId 而不是 endpoint 作为磁盘归属；`submitHint()` 会从 endpoint 解析 hostId 后写入，见 `src/java/org/apache/cassandra/service/StorageProxy.java:2790-2812`。
- Hints dispatch 对同一个 hostId 不并发，避免破坏 per-destination rate limit，见 `src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:102-113`。

## Batchlog 语义边界

- 只有 logged batch 且 mutation 数大于 1 才通过 `mutateAtomically()` 写 batchlog；单 mutation logged batch 不需要 batchlog，见 `src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:442-445`。
- Counter 不能放入 logged batch，也不能和 non-counter 混合，见 `src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:211-221`。
- batchlog row 存在 `system.batches`，`store()` 将每个 mutation 序列化到 `mutations` 列，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:139-165`。
- replay 会跳过已过 gc grace 或已 truncate 的 mutation，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:361-363`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:407-417`。
- replay 直接投递 live remote replicas，并为 down/未投递 endpoints 写 hints，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:463-510`。

## 配置与观测

- `hinted_handoff_enabled`、`max_hint_window`、`hinted_handoff_throttle`、`max_hints_delivery_threads`、`hints_flush_period`、`max_hints_file_size` 的模板说明见 `conf/cassandra.yaml:68-125`。
- persistent hint window 说明见 `conf/cassandra.yaml:140-152`。
- `DatabaseDescriptor` 暴露 hinted handoff 开关、disabled DC、max hint window，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3544-3588`。
- `batchlog_replay_throttle` 和 `batchlog_endpoint_strategy` 模板见 `conf/cassandra.yaml:157-183`。
- hints 总数和 in-flight counters 定义在 `src/java/org/apache/cassandra/metrics/StorageMetrics.java:44-46`。
- hints created/not stored/unowned ranges metrics 定义在 `src/java/org/apache/cassandra/metrics/HintedHandoffMetrics.java:36-70`。
- batch partition histograms 定义在 `src/java/org/apache/cassandra/metrics/BatchMetrics.java:25-37`。

## 排查路径

1. 普通写 timeout 后先判断是否产生 hint：看目标是否通过 `shouldHint()`，再看 `StorageMetrics.TotalHints` 与 `TotalHintsInProgress`。
2. 如果写入因 hints 过载失败，重点看单目标 hints in-flight 和 `maxHintsInProgress`，触发点见 `src/java/org/apache/cassandra/service/StorageProxy.java:1585-1599`。
3. Hints 堆积时区分写入端与投递端：写入端看 hints files/total hints，投递端看 dispatch 是否 paused、目标是否 alive、throttle 是否过低。
4. Logged batch timeout 后如果原始 writes 可能已经部分成功，关注 `system.batches` 是否残留和 `BatchlogManager.getTotalBatchesReplayed()`，MBean 定义见 `src/java/org/apache/cassandra/batchlog/BatchlogManagerMBean.java:20-37`。
5. Batchlog replay 后仍有目标不可达，会先写 hints 并 fsync，再删除 batchlog；这时 consistency 修复转移到 hinted handoff/repair。

## 测试用例

- `test/unit/org/apache/cassandra/hints/HintsServiceTest.java`
- `test/unit/org/apache/cassandra/hints/HintsStoreTest.java`
- `test/unit/org/apache/cassandra/hints/HintsReaderTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/HintsDisabledTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/HintsMaxWindowTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/HintedHandoffNodetoolTest.java`
- `test/unit/org/apache/cassandra/batchlog/BatchlogManagerTest.java`
- `test/unit/org/apache/cassandra/batchlog/BatchlogEndpointFilterTest.java`
- `test/unit/org/apache/cassandra/batchlog/BatchlogTest.java`
- `test/unit/org/apache/cassandra/cql3/validation/operations/BatchTest.java`
