# Module: Coordination Internals - Paxos v2, Counter Context, Hints, Batchlog

## 范围

本模块是协调路径第二轮内部研究，覆盖 Paxos v2 state/repair/uncommitted tracker、CounterContext、hints 文件格式和 batchlog endpoint strategy。

## 设计目标

本文件是 `module-coordination-lwt-counter-hints.md` 的第二轮深挖，目标是把第一轮待补的内部边界落到源码：

- Paxos v2 的 promise/accept/commit、repair、uncommitted tracker 和 state purging。
- CounterContext 的二进制 layout、shard 类型、merge/diff 规则和 counter update shard。
- Hints 文件格式、CRC、compression/encryption、reader/dispatcher 协议和 nodetool/MBean 控制。
- Batchlog endpoint strategy、dynamic snitch 选择、replay 边界和 materialized view local batchlog 边界。

## 解决的问题

- Paxos v2 的风险不在入口，而在“异步 commit 何时可认为 durable”。`Paxos` 类注释说明 accepted majority 后 commit 必须 durable，并用 replicas 本地 uncommitted log 配合 Paxos repair 清理，见 `src/java/org/apache/cassandra/service/paxos/Paxos.java:186-196`。
- `system.paxos` 不能无限保留。v2 在 state load 时按 `paxos_state_purging`、`gc_grace` 或 `repaired` low bound 过滤 promise/accepted/committed，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1329-1375`。
- Counter cell 不是一个 long，而是 `(counter id, clock, count)` shards 组成的 context；local/global/remote shard 有不同 merge 规则，见 `src/java/org/apache/cassandra/db/context/CounterContext.java:37-77`。
- Hints 不是简单 append mutation。每个文件先写 `HintsDescriptor`，descriptor 和每条 hint 都带 CRC，且 descriptor 可携带 compression/encryption 参数，见 `src/java/org/apache/cassandra/hints/HintsDescriptor.java:59-76`、`src/java/org/apache/cassandra/hints/HintsDescriptor.java:381-405`、`src/java/org/apache/cassandra/hints/HintsWriter.java:244-257`。
- Batchlog endpoint 不是 replication strategy 直接产物，而是在 local DC 内手工选择最多两个 system replicas；`ReplicaPlans.forBatchlogWrite()` 明确排除 dead/self 并倾向不同 rack，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:232-277`。
- Materialized view 的 batchlog 不是普通 logged batch endpoint strategy。view mutation 使用本地 system batchlog 和 base/view paired endpoint，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1010-1106`。

## 设计取舍

- Paxos v2 不引入 Multi-Paxos leader，而是用 fast read、read/write promise 分离、reproposal avoidance、commit+prepare/refresh 等优化降低每次单 partition Paxos 的往返；设计说明见 `src/java/org/apache/cassandra/service/paxos/Paxos.java:137-215`。
- `PaxosState` 先在内存 `ACTIVE`/`RECENT` 更新，再落 `system.paxos`。注释承认后续操作可能先看到内存状态，但认为拒绝更老 promise 是安全的，见 `src/java/org/apache/cassandra/service/paxos/PaxosState.java:64-76`、`src/java/org/apache/cassandra/service/paxos/PaxosState.java:561-618`。
- Paxos repair 的取舍是尽量不阻塞正常 Paxos：发现较新的正常 commit 就终止，发现 accepted-but-not-committed 就补 propose/commit，发现 promise-only 就用 stale ballot 提交空 proposal 进行 poison，见 `src/java/org/apache/cassandra/service/paxos/PaxosRepair.java:80-119`、`src/java/org/apache/cassandra/service/paxos/PaxosRepair.java:216-279`。
- Counter update shard 使用固定 `UPDATE_CLOCK_ID` 临时表达 CQL increment，多次 increment 可以先合并，直到 `CounterMutation.applyCounterMutation()` 读当前值后替换成当前节点 global shard，见 `src/java/org/apache/cassandra/db/context/CounterContext.java:86-130`、`src/java/org/apache/cassandra/db/CounterMutation.java:231-239`。
- Hints dispatch 优先走 raw encoded path：当 hints 文件 messaging version 与目标节点一致时跳过 decode/reencode，否则才反序列化为 `Hint` 再编码，见 `src/java/org/apache/cassandra/hints/HintsReader.java:41-51`、`src/java/org/apache/cassandra/hints/HintsDispatcher.java:126-140`。
- `batchlog_endpoint_strategy=prefer_local` 和 `dynamic` 会降低 rack failure 隔离；源码枚举注释直接说明 local rack 参与会降低 availability guarantee，见 `src/java/org/apache/cassandra/config/Config.java:1275-1316`。

## 核心类

| 类 | 作用 |
|---|---|
| `Paxos` | v2 CAS/read 总入口、participants/electorate、begin/propose/commit 调度。设计注释和 CAS 主循环见 `src/java/org/apache/cassandra/service/paxos/Paxos.java:137-216`、`src/java/org/apache/cassandra/service/paxos/Paxos.java:650-817` |
| `PaxosState` | replica 侧 promise/accept/commit 状态、内存 cache、coordinator partition lock、uncommitted/ballot tracker facade。见 `src/java/org/apache/cassandra/service/paxos/PaxosState.java:68-129` |
| `PaxosPrepare` | v2 prepare/commit+prepare 的 request callback，收集 promise/read response/latest commit/low bound 并处理 gossip electorate mismatch。见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:80-105`、`src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:442-560` |
| `PaxosRepair` | 对 partition 完成未完成 Paxos，或提交/poison 已看到的 promise/proposal。见 `src/java/org/apache/cassandra/service/paxos/PaxosRepair.java:80-120` |
| `PaxosUncommittedTracker` | 把 `system.paxos` memtable 与磁盘 uncommitted metadata 合并，向 repair 暴露 range/table key iterator。见 `src/java/org/apache/cassandra/service/paxos/uncommitted/PaxosUncommittedTracker.java:58-67`、`src/java/org/apache/cassandra/service/paxos/uncommitted/PaxosUncommittedTracker.java:155-221` |
| `CounterContext` | counter 二进制 context、diff/merge/total/clear local shards。见 `src/java/org/apache/cassandra/db/context/CounterContext.java:37-78` |
| `CounterMutation` | counter leader 读当前值、加锁、生成 global shard、写 counter cache。见 `src/java/org/apache/cassandra/db/CounterMutation.java:115-156`、`src/java/org/apache/cassandra/db/CounterMutation.java:207-239` |
| `HintsDescriptor` | hints 文件头、文件名、版本、hostId、timestamp、CRC、compression/encryption 参数。见 `src/java/org/apache/cassandra/hints/HintsDescriptor.java:65-99` |
| `HintsWriter` / `HintsReader` | hints 文件 append/read；writer 写 entry size/body CRC，reader 分 page 验 CRC 并跳过 unknown table/corrupt hint。见 `src/java/org/apache/cassandra/hints/HintsWriter.java:68-123`、`src/java/org/apache/cassandra/hints/HintsReader.java:75-96` |
| `HintsDispatcher` / `HintsDispatchExecutor` | 单文件分页投递、per-hostId 串行调度、offset 保存、target missing 时 convert。见 `src/java/org/apache/cassandra/hints/HintsDispatcher.java:45-51`、`src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:102-145` |
| `ReplicaPlans` | batchlog endpoint 选择：`forBatchlogWrite()`、random/dynamic filter。见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:238-289` |
| `BatchlogManager` | `system.batches` store/remove/replay、replay throttle、失败写 hints。见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:87-117`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:200-317` |

## 核心接口

- `PaxosState.promiseIfNewer(Ballot, boolean)`：根据 write/read promise 和 low bound 决定 `PROMISE`、`PERMIT_READ` 或 `REJECT`，并持久化 promise，见 `src/java/org/apache/cassandra/service/paxos/PaxosState.java:561-618`。
- `PaxosState.acceptIfLatest(Proposal)`：在没有更高 promise 时记录 accepted proposal，并调用 `SystemKeyspace.savePaxosProposal()`，见 `src/java/org/apache/cassandra/service/paxos/PaxosState.java:621-662`。
- `PaxosState.commit(Agreed)` / `commitDirect(Commit)`：应用 base mutation、更新 in-memory snapshot、保存 commit，见 `src/java/org/apache/cassandra/service/paxos/PaxosState.java:665-711`。
- `SystemKeyspace.loadPaxosState()` / `savePaxosWritePromise()` / `savePaxosReadPromise()` / `savePaxosProposal()` / `savePaxosCommit()`：`system.paxos` 持久化接口，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1329-1492`。
- `PaxosUncommittedTracker.uncommittedKeyIterator()`：合并 memtable supplier 和 file iterator，输出 repair 可消费的 uncommitted keys，见 `src/java/org/apache/cassandra/service/paxos/uncommitted/PaxosUncommittedTracker.java:192-221`。
- `CounterContext.diff()` / `merge()` / `total()` / `clearAllLocal()`：counter context 比较、合并、读总值、清 local shard，见 `src/java/org/apache/cassandra/db/context/CounterContext.java:197-287`、`src/java/org/apache/cassandra/db/context/CounterContext.java:296-397`、`src/java/org/apache/cassandra/db/context/CounterContext.java:572-679`。
- `HintsDescriptor.serialize()` / `deserialize()`：写 version/timestamp/hostId/params length CRC/params body CRC，见 `src/java/org/apache/cassandra/hints/HintsDescriptor.java:381-460`。
- `HintsDispatcher.dispatch()`：按 page 发送 hints，失败/timeout 则中止并由 executor 保存 offset，见 `src/java/org/apache/cassandra/hints/HintsDispatcher.java:98-164`。
- `HintsService.pauseDispatch()` / `resumeDispatch()` / `getPendingHints()` / `deleteAllHintsForEndpoint()` / `transferHints()`：MBean 运行控制，见 `src/java/org/apache/cassandra/hints/HintsService.java:232-246`、`src/java/org/apache/cassandra/hints/HintsService.java:296-353`、`src/java/org/apache/cassandra/hints/HintsService.java:419-443`。
- `ReplicaPlans.filterBatchlogEndpointsRandom()` / `filterBatchlogEndpointsDynamic()`：batchlog endpoint random 和 dynamic snitch 选择算法，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:331-430`。
- `StorageProxy.mutateMV()`：MV local batchlog、paired endpoint、pending endpoint 分发入口，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1010-1106`。

## 核心数据结构

- `PaxosState.Snapshot` 保存 `promised`、`promisedWrite`、`accepted`、`committed`，并在 merge/removeExpired 时执行 v2 read/write promise 与 purging 规则，见 `src/java/org/apache/cassandra/service/paxos/PaxosState.java:159-266`。
- `PaxosPrepare.Permitted` response 携带 outcome、lowBound、accepted-but-not-committed、latest committed、read response、gossip info 和 superseded ballot，相关字段和处理见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:951-986`、`src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:499-560`。
- `PaxosUncommittedTracker` 按 table id 管理 `UncommittedTableData`，flush/rebuild 时写 per-table files，见 `src/java/org/apache/cassandra/service/paxos/uncommitted/PaxosUncommittedTracker.java:89-132`、`src/java/org/apache/cassandra/service/paxos/uncommitted/PaxosUncommittedTracker.java:239-269`。
- Counter context header 是 2 字节元素数加 global/local shard index 列表；global index 用 `idx + Short.MIN_VALUE` 编码，body 是有序 `(CounterId, clock, count)`，见 `src/java/org/apache/cassandra/db/context/CounterContext.java:44-65`。
- `CounterContext.ContextState` 封装 context cursor，可 allocate global/local/remote count，并写 `writeGlobal()`、`writeLocal()`、`writeRemote()`，见 `src/java/org/apache/cassandra/db/context/CounterContext.java:747-900`。
- Hints 文件名格式为 `<hostId>-<timestamp>-<version>.hints` 与 `.crc32`，正则和字段见 `src/java/org/apache/cassandra/hints/HintsDescriptor.java:77-99`。
- Hints entry 格式是 `int size`、size CRC、serialized hint body、body CRC；writer 追加逻辑见 `src/java/org/apache/cassandra/hints/HintsWriter.java:232-257`，reader 校验逻辑见 `src/java/org/apache/cassandra/hints/HintsReader.java:208-264`。
- Batchlog `Batch` 保存 decoded local mutations 和 encoded remote mutations；`BatchlogManager.store()` 将它们统一序列化到 `system.batches.mutations`，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:134-165`。
- `BatchlogCleanup.mutationsWaitingFor` 在每个 mutation 达到 batch cleanup CL 后递减，为 0 时触发 batchlog remove callback，见 `src/java/org/apache/cassandra/service/BatchlogResponseHandler.java:93-116`。

## 生命周期

Paxos v2 state:

```text
Paxos.cas()
  -> PaxosState.lock(partitionKey, metadata, deadline, serialCL, isWrite)
  -> Paxos.begin()/PaxosPrepare.prepare()
  -> replica PaxosState.promiseIfNewer()
     -> SystemKeyspace.savePaxosWritePromise()/savePaxosReadPromise()
  -> PaxosPropose.propose()
  -> replica PaxosState.acceptIfLatest()
     -> SystemKeyspace.savePaxosProposal()
  -> PaxosCommit.commit()
  -> replica PaxosState.commit()
     -> Keyspace.apply(commit mutation)
     -> SystemKeyspace.savePaxosCommit()
```

Paxos repair / cleanup:

```text
system.paxos flush or repair range
  -> PaxosUncommittedTracker.flushUpdates()/uncommittedKeyIterator()
  -> StorageService.autoRepairPaxos() / repair --paxos path
  -> PaxosRepair.Querying
     -> collect latest witnessed/accepted/committed/low bound
     -> commit newest committed, re-propose accepted, or poison promise-only
  -> Paxos state below agreed low bound can be ignored/purged
```

Counter context:

```text
CQL counter increment
  -> UpdateParameters creates CounterContext.createUpdate(count)
  -> CounterMutation.applyCounterMutation()
     -> acquire striped cell locks
     -> read counter cache/CFS current ClockAndCount
     -> new clock = max(nowMicros, oldClock + 1)
     -> CounterContext.createGlobal(localCounterId, clock, oldCount + delta)
     -> local mutation apply + counter cache update
```

Hints file/dispatch:

```text
HintsService.write(hostIds, hint)
  -> HintsBufferPool.write()
  -> HintsWriteExecutor flushes to HintsWriter
  -> HintsWriter writes descriptor + entries + file CRC
HintsService.startDispatch()
  -> HintsDispatchTrigger
  -> HintsDispatchExecutor.dispatch(store)
  -> HintsDispatcher reads pages
  -> send HintMessage.Encoded or HintMessage
  -> delete descriptor on success or mark dispatch offset on partial failure
```

Batchlog:

```text
StorageProxy.mutateAtomically()
  -> ReplicaPlans.forBatchlogWrite()
  -> syncWriteToBatchlog()
  -> syncWriteBatchedMutations()
  -> BatchlogResponseHandler.ackMutation()
  -> asyncRemoveFromBatchlog()
BatchlogManager.replayFailedBatches()
  -> page old system.batches rows
  -> ReplayingBatch.sendSingleReplayMutation()
  -> direct live writes, hints for dead/undelivered replicas
  -> flushAndFsyncBlockingly(hintedNodes)
  -> remove replayed rows
```

## 调用链

- v2 CAS 主循环在 `Paxos.cas()`：`begin()` 读取当前值，条件失败时可提交 empty proposal，条件成功时生成 proposal，`propose()` 成功后 `commit()`，见 `src/java/org/apache/cassandra/service/paxos/Paxos.java:650-799`。
- SERIAL read 走 `Paxos.read()`：`begin()` 完成 in-progress writes，v2 可直接返回 linearizable read，否则提交 empty proposal，见 `src/java/org/apache/cassandra/service/paxos/Paxos.java:827-920`。
- replica prepare handler 在收到 request 后调用 `PaxosState.promiseIfNewer()`，并把 low bound、accepted/committed/read response 回给 coordinator，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:1049-1099`。
- Paxos state load 从 `system.paxos` 读 row，取 `PaxosRows.getWritePromise()`、`getPromise()`、`getAccepted()`、`getCommitted()` 并按 purgeBefore 过滤，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1329-1375`。
- `PaxosUncommittedTracker.schedulePaxosAutoRepairs()` 对有 uncommitted files 的非 replicated-system table 调用 `StorageService.instance.autoRepairPaxos(tableId)`，见 `src/java/org/apache/cassandra/service/paxos/uncommitted/PaxosUncommittedTracker.java:276-306`。
- Counter write 在 `CounterMutation.processModifications()` 中先查 counter cache，再读 CFS，cache miss 后用 `ClockAndCount.BLANK` 初始化，见 `src/java/org/apache/cassandra/db/CounterMutation.java:207-228`。
- Counter context merge 先统计 global/local/remote output count，若一边是 superset 直接返回原 context，否则再按 shard id 写 merged context，见 `src/java/org/apache/cassandra/db/context/CounterContext.java:296-397`。
- Hints reader 打开文件时先反序列化 descriptor，再根据 descriptor 升级为 compressed/encrypted input，见 `src/java/org/apache/cassandra/hints/HintsReader.java:75-96`。
- Hints dispatcher 每 page 发送并等待 callback，任何 failure/timeout 都中止当前文件；executor 保存 `dispatchPosition()` 并把 descriptor 放回队列，见 `src/java/org/apache/cassandra/hints/HintsDispatcher.java:126-164`、`src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:283-324`。
- nodetool `pausehandoff` / `resumehandoff` 直接通过 `NodeProbe` 调 `HintsServiceMBean`，命令入口见 `src/java/org/apache/cassandra/tools/nodetool/PauseHandoff.java:25-32`、`src/java/org/apache/cassandra/tools/nodetool/ResumeHandoff.java:25-32`。
- batchlog endpoint selection 入口是 `StorageProxy.mutateAtomically()` 内的 `ReplicaPlans.forBatchlogWrite(batchConsistencyLevel == ANY)`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1173-1227`。
- random batchlog filter 先 `validate()` 过滤 dead/self/local rack，再按 rack 随机选两个 endpoints，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:291-390`。
- dynamic batchlog filter 在 validate 后对所有候选 `sortByProximity()`，循环每 rack 取最快 endpoint，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:392-430`。
- MV view update 从 `TableViews.pushViewReplicaUpdates()` 生成 view mutation 后进入 `StorageProxy.mutateMV()`，见 `src/java/org/apache/cassandra/db/view/TableViews.java:135-170`。

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| `paxos_state_purging` | `src/java/org/apache/cassandra/config/Config.java:1091-1094`，默认设置在 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1011-1012` | 控制 `system.paxos` state 的 legacy/gc_grace/repaired purge 语义 |
| `paxos_repair_enabled` | `src/java/org/apache/cassandra/config/Config.java:1096-1100` | 全局开启/关闭 Paxos repair、topology change repair 和 auto repair |
| `cas_contention_timeout` | `src/java/org/apache/cassandra/config/Config.java:156-157`，最低值修正在 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1372-1375` | Paxos CAS 竞争重试 deadline |
| `counter_write_request_timeout` | `src/java/org/apache/cassandra/config/Config.java:153-154`，最低值修正在 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1378-1381` | counter lock/read-before-write/write timeout |
| `hinted_handoff_enabled` | `src/java/org/apache/cassandra/config/Config.java:112`，setter/getter 在 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3546-3551` | 是否保存新 hints |
| `hinted_handoff_disabled_datacenters` | `src/java/org/apache/cassandra/config/Config.java:113`，更新方法在 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3556-3576` | 按 DC 禁用 hints |
| `hints_directory` | `src/java/org/apache/cassandra/config/Config.java:116`，目录冲突校验在 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:644-751` | hints 文件存储目录 |
| `hinted_handoff_throttle` | `src/java/org/apache/cassandra/config/Config.java:438-439`，dispatch rate 使用在 `src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:213-221` | 每目标 hints 投递限速 |
| `batchlog_replay_throttle` | `src/java/org/apache/cassandra/config/Config.java:440-441`，replay rate 使用在 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:229-247` | batchlog replay 每 endpoint 限速 |
| `batchlog_endpoint_strategy` | `src/java/org/apache/cassandra/config/Config.java:442`、枚举在 `src/java/org/apache/cassandra/config/Config.java:1275-1334`，JMX setter 在 `src/java/org/apache/cassandra/service/StorageService.java:6359-6366` | logged batch batchlog endpoint 选择策略 |
| `cassandra.mv_enable_coordinator_batchlog` | `src/java/org/apache/cassandra/db/view/ViewManager.java:39-62` | 是否让 coordinator batchlog 参与 MV 影响判断 |

## Metrics

- `PaxosMetrics.initialize()` 在 `PaxosState.initializeTrackers()` 调用；Paxos linearizability violation counter 定义在 `src/java/org/apache/cassandra/metrics/PaxosMetrics.java:25-29`，入口见 `src/java/org/apache/cassandra/service/paxos/PaxosState.java:115-119`。
- `Paxos.cas()` 在 finally 更新 `casWriteMetrics.contention`、top partition contention、CAS/write latency，见 `src/java/org/apache/cassandra/service/paxos/Paxos.java:806-817`。
- `Paxos.read()` 更新 read、casRead、CL read metrics 和 table coordinator read latency，见 `src/java/org/apache/cassandra/service/paxos/Paxos.java:906-920`。
- Counter cache 命中直接调用 `ColumnFamilyStore.getCachedCounter()`，miss 后从 CFS read；cache 写入见 `src/java/org/apache/cassandra/db/CounterMutation.java:231-239`、cache 读取见 `src/java/org/apache/cassandra/db/CounterMutation.java:242-260`。
- Hints 写入增加 `StorageMetrics.totalHints`，见 `src/java/org/apache/cassandra/hints/HintsService.java:161-171`。
- Hints dispatch 记录 `hintsSucceeded`、`hintsFailed`、`hintsTimedOut` 和 delay metrics，见 `src/java/org/apache/cassandra/hints/HintsDispatcher.java:167-172`、`src/java/org/apache/cassandra/hints/HintsDispatcher.java:256-260`。
- Batchlog replay 总数由 `BatchlogManager.totalBatchesReplayed` 暴露，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:97-101`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:178-181`。
- MV batchlog wrapper 记录 `viewReplicasAttempted` / `viewReplicasSuccess`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:2568-2580`。

## 日志

- `PaxosRepair.Querying` trace 记录 response、success criteria、完成 accepted proposal 或 poison promise-only 的路径，见 `src/java/org/apache/cassandra/service/paxos/PaxosRepair.java:181-184`、`src/java/org/apache/cassandra/service/paxos/PaxosRepair.java:222-279`。
- `PaxosUncommittedTracker` truncate/start/auto repair 会记录 info/debug/error，见 `src/java/org/apache/cassandra/service/paxos/uncommitted/PaxosUncommittedTracker.java:108-120`、`src/java/org/apache/cassandra/service/paxos/uncommitted/PaxosUncommittedTracker.java:230-237`、`src/java/org/apache/cassandra/service/paxos/uncommitted/PaxosUncommittedTracker.java:293-304`。
- `CounterContext.compare()` 在 compaction 线程发现相同 id/clock 但 count 不同的 global/remote shard 时 warning 并选择较大 count 自愈，见 `src/java/org/apache/cassandra/db/context/CounterContext.java:461-481`、`src/java/org/apache/cassandra/db/context/CounterContext.java:503-523`。
- `HintsDescriptor.handleDescriptorIOE()` 对空文件删除、非空 corrupt 文件改名并记录 warn/error，见 `src/java/org/apache/cassandra/hints/HintsDescriptor.java:287-309`。
- `HintsReader` 对 EOF、unknown table、hint digest mismatch 打 warning 并继续/跳过，见 `src/java/org/apache/cassandra/hints/HintsReader.java:189-264`。
- `HintsDispatchExecutor` 对 corrupt hints file、完整/部分 dispatch、transfer failure 记录日志，见 `src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:166-188`、`src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:252-324`。
- `BatchlogManager` replay 跳过异常、timeout 后写 hints、更新 replay throttle 都有日志，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:288-310`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:372-387`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:235-247`。

## 运维关注点

- 开 `paxos_state_purging=repaired` 前要确认 Paxos repair/auto repair 语义，因为 `loadPaxosState()` 会用 table 的 Paxos repair low bound 减 purge grace 过滤旧 state，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1351-1357`。
- 如果 `PaxosUncommittedTracker` 不 flush 或 auto repair 被属性关闭，accepted majority 后未同步 commit 的耐久性依赖会变弱；开关读取见 `src/java/org/apache/cassandra/service/paxos/uncommitted/PaxosUncommittedTracker.java:52-56`、`src/java/org/apache/cassandra/service/paxos/uncommitted/PaxosUncommittedTracker.java:75-77`。
- CounterContext 的 local shard 清理是历史兼容逻辑；`shouldClearLocal()` 用 header count 负值标记，`clearAllLocal()` 只保留 global shard header，见 `src/java/org/apache/cassandra/db/context/CounterContext.java:586-679`。
- Hints 目录必须不能与 data/commitlog/saved_caches/local_system_data 目录重合；校验见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:719-751`。
- `pausehandoff` 只暂停 dispatch，不等于关闭未来 hints 写入；`disablehandoff` 才会经 `StorageProxy`/`DatabaseDescriptor` 禁用保存，命令入口见 `src/java/org/apache/cassandra/tools/nodetool/PauseHandoff.java:25-32`、`src/java/org/apache/cassandra/tools/nodetool/DisableHandoff.java:25-32`。
- `listpendinghints` 会把 hostId 映射到 endpoint/rack/DC/status 并展示文件数、新旧时间，见 `src/java/org/apache/cassandra/tools/nodetool/ListPendingHints.java:37-98`。
- `batchlog_endpoint_strategy=dynamic_remote` 只有动态 snitch 启用时才走 dynamic path，否则回退 random path；选择条件见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:279-289`。
- 普通 logged batch 不支持 transient replicas；`mutateAtomically()` 显式 assertion，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1182-1186`。
- MV 本地 mutation 不应产生多余 batchlog cleanup；`ViewComplexDeletionsTest.testNoBatchlogCleanupForLocalMutations()` 对 local view mutation 后 batchlog SSTable 数不变做了断言，见 `test/unit/org/apache/cassandra/cql3/ViewComplexDeletionsTest.java:254-269`。

## 性能瓶颈

- Paxos v2 的热点瓶颈仍是单 partition 串行化：`PaxosState.lock()` 用 partition key + table id 的 `ACTIVE` entry 做 coordinator locking，deadline 到期抛 CAS read/write timeout，见 `src/java/org/apache/cassandra/service/paxos/PaxosState.java:389-414`、`src/java/org/apache/cassandra/service/paxos/PaxosState.java:451-491`。
- Paxos repair auto repair 会扫描 uncommitted metadata 并提交 repair，文件越多、key 越多，repair 与 consolidation 成本越高；flush/merge/schedule 入口见 `src/java/org/apache/cassandra/service/paxos/uncommitted/PaxosUncommittedTracker.java:155-184`、`src/java/org/apache/cassandra/service/paxos/uncommitted/PaxosUncommittedTracker.java:271-306`。
- Counter merge 是按 shard id 排序双游标合并；legacy remote/local shard 多会增加 context 长度、读写字节和 compaction merge 成本，核心循环见 `src/java/org/apache/cassandra/db/context/CounterContext.java:296-397`。
- Hints writer 在 buffer 放不下 entry 时 flush channel，session close 可能 fsync 和 skip cache；大 hint 或 flush period 短会增大 IO，见 `src/java/org/apache/cassandra/hints/HintsWriter.java:200-221`、`src/java/org/apache/cassandra/hints/HintsWriter.java:265-299`。
- Hints dispatcher 每 hostId 同时只保留一个 dispatch task，以避免 per-destination rate limit 被并发破坏；这会让单目标大量 backlog 串行排空，见 `src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:102-113`。
- Batchlog dynamic strategy 排序依赖 dynamic snitch score；write-only workload 未必受益，枚举注释见 `src/java/org/apache/cassandra/config/Config.java:1290-1315`。
- Batchlog replay 按 page 读取 `system.batches`，并在每 page 后等待 unfinished batches，page size 又受平均 row size 限制，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:250-317`。

## 常见故障

- Paxos v2 `SUPERSEDED`：proposal 被更高 ballot 抢占；如果可能已有 side effect，会返回 maybe failure/timeout，否则更新 minimum ballot 重试，见 `src/java/org/apache/cassandra/service/paxos/Paxos.java:747-789`。
- Paxos prepare `ELECTORATE_MISMATCH`：prepare response 带 gossip info，coordinator 更新 gossip 后发现 electorate 改变，需要重试，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:424-496`。
- `system.paxos` descriptor/row TTL 与 purge 错误可能表现为旧 accepted/commit 被忽略；过滤边界在 `SystemKeyspace.loadPaxosState()`，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1339-1375`。
- Counter lock timeout 会抛 `WriteTimeoutException(WriteType.COUNTER)`；见 `src/java/org/apache/cassandra/db/CounterMutation.java:158-176`。
- Counter context invalid same clock/different count 只能在 compaction 中 warning 并选择较大 count，自愈不代表没有历史丢 SSTable 或 best-effort disk failure 风险，见 `src/java/org/apache/cassandra/db/context/CounterContext.java:461-481`、`src/java/org/apache/cassandra/db/context/CounterContext.java:503-523`。
- Hints descriptor CRC mismatch 直接抛 `ChecksumMismatchException("Hints Descriptor CRC Mismatch")`，见 `src/java/org/apache/cassandra/hints/HintsDescriptor.java:486-490`，测试见 `test/unit/org/apache/cassandra/hints/HintsDescriptorTest.java:68-95`。
- Hints 文件 entry size 为 0 且后续不是全 0 会视为 corrupt；reader 逻辑见 `src/java/org/apache/cassandra/hints/HintsReader.java:213-227`，测试见 `test/unit/org/apache/cassandra/hints/HintsReaderTest.java:183-210`。
- Batchlog endpoints 全不可用时 filter 返回空；非 `ANY` logged batch 随后抛 `UnavailableException`，source 和测试分别见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:257-266`、`test/unit/org/apache/cassandra/batchlog/BatchlogEndpointFilterTest.java:411-490`。
- Batchlog replay direct write timeout 后会为未投递 endpoints 写 hints；若 hints 也持续堆积，需要同时排查 HintsService pending 和 batchlog replay throttle，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:372-447`。

## 测试用例

- Paxos v2 state/propose/repair：`test/unit/org/apache/cassandra/service/paxos/PaxosStateTest.java`、`test/unit/org/apache/cassandra/service/paxos/PaxosProposeTest.java`、`test/unit/org/apache/cassandra/service/paxos/PaxosRepairTest.java`、`test/unit/org/apache/cassandra/service/paxos/uncommitted/PaxosUncommittedTrackerTest.java`、`test/unit/org/apache/cassandra/service/paxos/uncommitted/PaxosUncommittedTrackerIntegrationTest.java`。
- Paxos 分布式 repair/uncommitted：`test/distributed/org/apache/cassandra/distributed/test/PaxosRepairTest.java`、`test/distributed/org/apache/cassandra/distributed/test/PaxosRepair2Test.java`、`test/distributed/org/apache/cassandra/distributed/test/PaxosUncommittedIndexTest.java`、`test/distributed/org/apache/cassandra/distributed/test/CasWriteTest.java`。
- Counter context：`test/unit/org/apache/cassandra/db/context/CounterContextTest.java:63-574` 覆盖 allocate/diff/merge/total/clear local/find position/update shard；counter 分布式语义见 `test/distributed/org/apache/cassandra/distributed/test/CountersTest.java`。
- Hints file format：`test/unit/org/apache/cassandra/hints/HintsDescriptorTest.java:43-131` 覆盖 descriptor serializer/CRC/messaging version；`test/unit/org/apache/cassandra/hints/HintsReaderTest.java:84-260` 覆盖 writer/reader、raw buffers、corrupt EOF、dropped table。
- Hints compression/encryption：`test/unit/org/apache/cassandra/hints/HintsCompressionTest.java:31-86`、`test/unit/org/apache/cassandra/hints/HintsEncryptionTest.java:32-80`。
- Hints nodetool：`test/distributed/org/apache/cassandra/distributed/test/HintedHandoffNodetoolTest.java:81-148` 覆盖 enable/disable/status、disable/enable DC、pause/resume、throttle、max hint window。
- Batchlog endpoint strategy：`test/unit/org/apache/cassandra/batchlog/BatchlogEndpointFilterTest.java:77-258` 覆盖 local rack/random 基础，`test/unit/org/apache/cassandra/batchlog/BatchlogEndpointFilterTest.java:411-585` 覆盖全不可用/至少两活节点边界，`test/unit/org/apache/cassandra/batchlog/BatchlogEndpointFilterTest.java:720-890` 覆盖 dynamic/dynamic_remote fastest endpoint。
- Batchlog replay/store/remove：`test/unit/org/apache/cassandra/batchlog/BatchlogManagerTest.java`、`test/unit/org/apache/cassandra/batchlog/BatchlogTest.java`；MV local batchlog 边界见 `test/unit/org/apache/cassandra/cql3/ViewComplexDeletionsTest.java:254-269`。

## 待继续

- Paxos v2 还可继续补 `PaxosCommitAndPrepare`、`PaxosPrepareRefresh`、`PaxosOperationLock` 与 simulator Paxos fault model 的交叉验证。
- Counter 还需补 tombstone/delete 与 counter shard 清理在 compaction/read repair 中的完整交互。
- Hints 还需补 `HintsBuffer`/`HintsBufferPool` 内存水位、max file size rollover 和跨版本 upgrade fixtures。
- Batchlog 还需补 mixed-version logged batch、large mutation、batchlog system table compaction 和 operator runbook。
