# Flow: Repair

## 目标

Repair 链路解释一次 repair command 如何从 `StorageService` 进入 repair coordinator，完成 prepare、validation、Merkle diff、sync streaming、finalization/cleanup。

## 文字版调用图

```text
nodetool/JMX repair
  -> StorageService.repairAsync(keyspace, repairSpec)
     -> RepairOption.parse(...)
     -> StorageService.repair(keyspace, option, listeners)
        -> fill ranges if option.ranges is empty
        -> nextRepairCommand
        -> repairCommandExecutor.submit(createRepairTask(...))
           -> RepairCoordinator.run()
              -> validate column families / neighbors / ranges
              -> maybeStoreParentRepairStart(...)
              -> prepare(columnFamilies, allNeighbors, force)
                 -> ActiveRepairService.prepareForRepair(parentSession, coordinator, endpoints, options, ...)
                    -> verify disk headroom / pending compaction threshold
                    -> registerParentRepairSession(...)
                    -> send PREPARE_MSG to participants
                    -> wait all prepare acks or timeout
              -> repair(cfnames, neighborsAndRanges)
                 -> PreviewRepairTask / IncrementalRepairTask / NormalRepairTask
```

Session fan-out:

```text
AbstractRepairTask.runRepair(parentSession, isIncremental, ...)
  -> submitRepairSessions(commonRanges)
     -> for each CommonRange
        -> ActiveRepairService.submitRepairSession(...)
           -> new RepairSession(...)
           -> sessions.put(sessionId, session)
           -> registerOnFdAndGossip(session)
           -> session.start(executor)
              -> fail early if no endpoints or dead neighbor
              -> for each table
                 -> executor.execute(new RepairJob(session, cfname))
```

Per-table validation:

```text
RepairJob.run()
  -> optional snapshot/paxos preparation
  -> validationScheduler.schedule(createSyncTasks(...))
     -> sendValidationRequest(...)
        -> for each endpoint
           -> new ValidationTask(...)
           -> session.trackValidationCompletion(desc, endpoint, task)
           -> taskExecutor.execute(task)

ValidationTask.run()
  -> send VALIDATION_REQ
     -> remote RepairMessageVerbHandler.doVerb(VALIDATION_REQ)
        -> lookup ParticipateState
        -> ColumnFamilyStore.getIfExists(...)
        -> new Validator(...)
        -> acceptMessage(range ownership)
        -> ValidationManager.submitValidation(store, validator)
           -> doValidation(cfs, validator)
              -> create MerkleTrees
              -> scan validation iterator
              -> validator.add(partition)
              -> validator.complete()
                 -> Stage.ANTI_ENTROPY execute Validator.run()
                 -> send VALIDATION_RSP
```

Diff and sync:

```text
ActiveRepairService.handleMessage(VALIDATION_RSP)
  -> RepairSession.validationComplete(desc, response)
     -> ValidationTask.treesReceived(...)
        -> RepairJob waits all TreeResponses
           -> MerkleTrees.difference(r1.trees, r2.trees)
           -> if local endpoint involved
              -> LocalSyncTask
           -> else if transient/asymmetric
              -> AsymmetricRemoteSyncTask
           -> else
              -> SymmetricRemoteSyncTask
           -> execute sync tasks

SyncTask.run()
  -> if no rangesToSync: success
  -> startSync()
     -> local: LocalSyncTask.createStreamPlan() + streamExecutor.execute(plan)
     -> remote: send SYNC_REQ
        -> remote RepairMessageVerbHandler.doVerb(SYNC_REQ)
           -> new StreamingRepairTask(...)
           -> task.run()
              -> StreamPlan(REPAIR).requestRanges(...)
              -> optionally transferRanges(...)
              -> streamExecutor.execute(streamPlan)
              -> onSuccess/onFailure sends SYNC_RSP

ActiveRepairService.handleMessage(SYNC_RSP)
  -> RepairSession.syncComplete(...)
     -> CompletableRemoteSyncTask.syncComplete(...)
```

Completion:

```text
RepairJob all sync tasks complete
  -> mark table repair job success/failure
RepairSession all RepairJobs complete
  -> RepairSessionResult
AbstractRepairTask FutureCombiner.successfulOf(allSessions)
  -> CoordinatedRepairResult
RepairCoordinator
  -> maybeStoreParentRepairSuccess / fail
  -> removeParentRepairSession
  -> update repair metrics and progress events
```

Incremental repair additions:

```text
IncrementalRepairTask.performUnsafe()
  -> register CoordinatorSession with all participants plus coordinator
  -> CoordinatorSession.execute(...)
     -> consistent prepare isolates SSTables through pending anti-compaction
     -> run normal repair against pending-repair SSTables
     -> finalizePropose()
     -> finalizeCommit()
```

## 关键源码锚点

| 阶段 | 文件/方法 |
|---|---|
| repairAsync 入口 | `StorageService.repairAsync()`：`src/java/org/apache/cassandra/service/StorageService.java:4766-4774` |
| 默认 ranges 填充 | `StorageService.repair()`：`src/java/org/apache/cassandra/service/StorageService.java:4777-4803` |
| repair coordinator 构造 | `RepairCoordinator`：`src/java/org/apache/cassandra/repair/RepairCoordinator.java:113-133` |
| prepare 调用 | `RepairCoordinator.prepare()`：`src/java/org/apache/cassandra/repair/RepairCoordinator.java:445-455` |
| repair task 分派 | `RepairCoordinator.repair()`：`src/java/org/apache/cassandra/repair/RepairCoordinator.java:458-479` |
| parent session 注册 | `ActiveRepairService.registerParentRepairSession()`：`src/java/org/apache/cassandra/service/ActiveRepairService.java:831-845` |
| prepare message/timeout | `ActiveRepairService.prepareForRepair()`：`src/java/org/apache/cassandra/service/ActiveRepairService.java:665-717` |
| session 创建 | `ActiveRepairService.submitRepairSession()`：`src/java/org/apache/cassandra/service/ActiveRepairService.java:440-480` |
| session start | `RepairSession.start()`：`src/java/org/apache/cassandra/repair/RepairSession.java:290-360` |
| job validation/sync pipeline | `RepairJob.run()`：`src/java/org/apache/cassandra/repair/RepairJob.java:112-235` |
| validation requests | `RepairJob.sendValidationRequest()`：`src/java/org/apache/cassandra/repair/RepairJob.java:493-508` |
| sequential validation | `RepairJob.sendSequentialValidationRequest()`：`src/java/org/apache/cassandra/repair/RepairJob.java:514-551` |
| DC-aware validation | `RepairJob.sendDCAwareValidationRequest()`：`src/java/org/apache/cassandra/repair/RepairJob.java:554-605` |
| validation message receiver | `RepairMessageVerbHandler` VALIDATION_REQ：`src/java/org/apache/cassandra/repair/RepairMessageVerbHandler.java:198-258` |
| validation compaction | `ValidationManager.doValidation()`：`src/java/org/apache/cassandra/repair/ValidationManager.java:97-141` |
| validator hashing | `Validator.rowHash()`：`src/java/org/apache/cassandra/repair/Validator.java:207-216` |
| validation response route | `ActiveRepairService.handleMessage()`：`src/java/org/apache/cassandra/service/ActiveRepairService.java:900-940` |
| tree response route | `RepairSession.validationComplete()`：`src/java/org/apache/cassandra/repair/RepairSession.java:224-245` |
| sync task creation | `RepairJob.createSyncTasks()`：`src/java/org/apache/cassandra/repair/RepairJob.java:305-360` |
| sync task base | `SyncTask.run()`：`src/java/org/apache/cassandra/repair/SyncTask.java:75-96` |
| local stream plan | `LocalSyncTask.createStreamPlan()`：`src/java/org/apache/cassandra/repair/LocalSyncTask.java:80-103` |
| remote sync receiver | `RepairMessageVerbHandler` SYNC_REQ：`src/java/org/apache/cassandra/repair/RepairMessageVerbHandler.java:272-300` |
| remote repair streaming | `StreamingRepairTask.run()`：`src/java/org/apache/cassandra/repair/StreamingRepairTask.java:82-90` |
| sync response route | `RepairSession.syncComplete()`：`src/java/org/apache/cassandra/repair/RepairSession.java:253-264` |
| incremental wrapper | `IncrementalRepairTask.performUnsafe()`：`src/java/org/apache/cassandra/repair/IncrementalRepairTask.java:54-68` |
| consistent repair stages | `ConsistentSession` class doc：`src/java/org/apache/cassandra/repair/consistent/ConsistentSession.java:56-105` |
| finalization propose/commit | `CoordinatorSession.finalizePropose()` / `finalizeCommit()`：`src/java/org/apache/cassandra/repair/consistent/CoordinatorSession.java:238-285` |
| repair completion cleanup | `RepairCoordinator.complete()`：`src/java/org/apache/cassandra/repair/RepairCoordinator.java:242-270` |

## 并发与一致性语义

- `RepairSession` 串行推进 validation phase，sync phase 可并发，设计说明见 `src/java/org/apache/cassandra/repair/RepairSession.java:94-107`。
- Validation scheduler 由 `RepairCoordinator` 按 `concurrent_merkle_tree_requests` 构造，见 `src/java/org/apache/cassandra/repair/RepairCoordinator.java:126-128`。
- `RepairJob` 把 validation 与 sync task 创建放进 scheduler，是为了限制同时驻留内存的 Merkle trees 数量，见 `src/java/org/apache/cassandra/repair/RepairJob.java:195-198`。
- Full repair validation 会先 flush；incremental repair validation 依赖 anti-compaction 阶段隔离好的 pending SSTables，见 `src/java/org/apache/cassandra/db/repair/CassandraValidationIterator.java:196-204`。
- Incremental repair 的 consistent prepare/finalize 状态机保证所有 participants 对 pending-repair SSTables 达成一致后才 finalize，见 `src/java/org/apache/cassandra/repair/consistent/ConsistentSession.java:64-99`。

## 排查路径

1. Repair command 没启动：看 `StorageService.repair()` 是否因 ranges 为空或 RF < 2 返回 immediate success，入口见 `src/java/org/apache/cassandra/service/StorageService.java:4797-4803`。
2. Prepare 卡住：看 `ActiveRepairService.prepareForRepair()` 是否有 dead endpoint、disk headroom、pending compaction threshold 或 prepare ack timeout，见 `src/java/org/apache/cassandra/service/ActiveRepairService.java:665-717`。
3. Validation 慢：看 `ValidationManager.doValidation()` 的 validation compaction、`repair_session_space`、`concurrent_merkle_tree_requests`、compaction backlog 和 SSTable overlap。
4. 差异范围过大：检查 Merkle tree resolution，`ValidationManager.createMerkleTrees()` 会按 `repair_session_space / RF` 限制 tree depth，见 `src/java/org/apache/cassandra/repair/ValidationManager.java:54-88`。
5. Sync 卡住：区分 local sync 与 remote sync；local 看 `StreamPlan` 执行，remote 看 `SYNC_REQ` 是否被目标节点处理并返回 `SYNC_RSP`。
6. Incremental repair prepare 失败：检查 pending anti-compaction 是否遇到 legacy SSTables、未完成 session 或冲突 anti-compaction，见 `src/java/org/apache/cassandra/db/repair/PendingAntiCompaction.java:120-164`。

## 测试用例

- `test/unit/org/apache/cassandra/repair/RepairCoordinatorTest.java`
- `test/unit/org/apache/cassandra/repair/RepairSessionTest.java`
- `test/unit/org/apache/cassandra/repair/RepairJobTest.java`
- `test/unit/org/apache/cassandra/repair/ValidationTaskTest.java`
- `test/unit/org/apache/cassandra/repair/ValidatorTest.java`
- `test/unit/org/apache/cassandra/repair/LocalSyncTaskTest.java`
- `test/unit/org/apache/cassandra/repair/StreamingRepairTaskTest.java`
- `test/unit/org/apache/cassandra/repair/RepairMessageVerbHandlerOutOfRangeTest.java`
- `test/unit/org/apache/cassandra/repair/consistent/CoordinatorSessionTest.java`
- `test/unit/org/apache/cassandra/repair/consistent/LocalSessionTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/repair/ConcurrentValidationRequestsTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/repair/ForceRepairTest.java`
