# Module: LWT, Paxos, Counter, Hints, Batchlog

## 范围

本模块覆盖 LWT/Paxos、counter 写、hinted handoff 和 batchlog 的协调与恢复语义，重点关注 coordinator 到 replica 的调用链和失败补偿。

## 设计目标

本模块补齐 coordinator 写路径中最容易和普通 mutation 混淆的四类机制：

- LWT/CAS 用 Paxos 在单 partition 范围内线性化条件判断和写入。
- Counter 写先在一个 leader replica 上读改写计数器上下文，再把结果复制到其它 replicas。
- Hinted Handoff 在 replica 不可达时保存后续可重放的 hint，但 counters 不走普通 hint 重试。
- Batchlog 为 logged batch 和 materialized view paired writes 提供失败后重放能力。

## 解决的问题

- 条件更新不能只在 coordinator 本地判断条件。`ModificationStatement.execute()` 在 `hasConditions()` 时进入 `executeWithCondition()`，再调用 `StorageProxy.cas()`，见 `src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:500-502`、`src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:538-552`。
- Paxos 不是全环共识，而是 partition key 对应 replicas 的 cohort。legacy 注释明确 cohort 是给定 key 的 replicas，见 `src/java/org/apache/cassandra/service/StorageProxy.java:269-307`。
- Counter mutation 不能安全地像普通 mutation 一样盲写重试；`CounterMutation.hintOnFailure()` 返回 `null`，并且 `hintMutations()` 明确跳过 counters，见 `src/java/org/apache/cassandra/db/CounterMutation.java:85-88`、`src/java/org/apache/cassandra/service/StorageProxy.java:960-972`。
- Hints 需要窗口、DC 禁用、transient replica/self 过滤、目标 hostId、磁盘大小和过载保护；判断集中在 `shouldHint()` 与 `checkHintOverload()`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1585-1599`、`src/java/org/apache/cassandra/service/StorageProxy.java:2428-2498`。
- Logged batch 的原子性依赖先写 batchlog，再写各 mutation，最后由 response handler 触发 batchlog remove；入口见 `StorageProxy.mutateAtomically()`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1173-1227`。
- Batchlog 未删除的记录由 `BatchlogManager` 周期扫描 `system.batches` 并重放，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:110-117`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:200-226`。

## 设计取舍

- Cassandra 的 Paxos 没有 Multi-Paxos distinguished proposer；每次操作执行自己的 Paxos instance，见 `src/java/org/apache/cassandra/service/paxos/Paxos.java:137-145`。
- Paxos v2 优化读/写往返，但默认配置仍从 `paxos_variant = v1` 起步；变体定义和语义见 `src/java/org/apache/cassandra/config/Config.java:969-1005`、`src/java/org/apache/cassandra/config/Config.java:1048-1051`。
- CAS 条件不满足时仍可能需要提出 empty proposal，确保条件拒绝也被线性化；v2 代码注释见 `src/java/org/apache/cassandra/service/paxos/Paxos.java:689-718`。
- Counter 写选择一个 suitable replica 做 leader：coordinator 如果自己是 replica 就本地执行，否则转发给一个本 DC 或 snitch 选出的 replica，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1710-1754`、`src/java/org/apache/cassandra/service/StorageProxy.java:1757-1802`。
- Hints 按 hostId 写入本地 hints store，并用后台 dispatch 周期投递；`HintsService` 是 front-end，持有 catalog/write executor/dispatch executor/buffer pool，见 `src/java/org/apache/cassandra/hints/HintsService.java:61-70`。
- Batchlog replay 失败时不无限阻塞整个 replay；发送失败会为未投递 endpoints 写 hints，并在 hints fsync 后删除 batchlog 记录，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:312-316`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:372-387`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:420-447`。

## 核心类

| 类 | 作用 |
|---|---|
| `ModificationStatement` | CQL UPDATE/INSERT/DELETE 执行入口，按 condition/counter 分支到 CAS 或普通写。条件入口见 `src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:491-552` |
| `StorageProxy` | coordinator 写、CAS、counter、hints、batchlog 编排核心。CAS 入口见 `src/java/org/apache/cassandra/service/StorageProxy.java:308-328` |
| `Paxos` | Paxos v2 入口、优化和 CAS/read 执行。类注释与 `cas()` 入口见 `src/java/org/apache/cassandra/service/paxos/Paxos.java:137-216`、`src/java/org/apache/cassandra/service/paxos/Paxos.java:626-636` |
| `CounterMutation` | Counter 的 read-before-write、cell lock、counter cache、本地 apply。定义与 apply 流程见 `src/java/org/apache/cassandra/db/CounterMutation.java:55-64`、`src/java/org/apache/cassandra/db/CounterMutation.java:116-156` |
| `CounterMutationVerbHandler` | 非 replica coordinator 转发 counter mutation 后，leader replica 的 verb handler。见 `src/java/org/apache/cassandra/db/CounterMutationVerbHandler.java:30-53` |
| `HintsService` | hints catalog/write executor/dispatch executor/buffer pool 的 facade 和 MBean。见 `src/java/org/apache/cassandra/hints/HintsService.java:61-77` |
| `HintsStore` | 单 hostId 的 hints 文件队列、dispatch offset、writer 与过期删除。见 `src/java/org/apache/cassandra/hints/HintsStore.java:52-81` |
| `HintsDispatchExecutor` | 每 hostId 串行 dispatch hints，支持 transfer 和失败 offset 记录。见 `src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:49-73`、`src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:202-324` |
| `BatchlogManager` | batchlog MBean、store/remove、周期 replay 和 replay throttle。见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:87-117` |
| `Batch` | batchlog 网络/磁盘保存的 batch 容器，区分 decoded local 与 encoded remote mutations。见 `src/java/org/apache/cassandra/batchlog/Batch.java:37-74` |
| `BatchlogResponseHandler` | 包装每个 mutation 的 write handler，在足够 mutation 完成后触发 batchlog cleanup。见 `src/java/org/apache/cassandra/service/BatchlogResponseHandler.java:38-56`、`src/java/org/apache/cassandra/service/BatchlogResponseHandler.java:93-116` |

## 核心接口

- `StorageProxy.cas(...)`：CAS coordinator 入口，按 `Paxos.useV2()` 选择 v2 或 legacy，见 `src/java/org/apache/cassandra/service/StorageProxy.java:308-328`。
- `Paxos.cas(...)`：v2 CAS 入口，读取 CAS request、校验 CL、获取 `PaxosOperationLock`，见 `src/java/org/apache/cassandra/service/paxos/Paxos.java:650-669`。
- `StorageProxy.doPaxos(...)`：legacy Paxos prepare/propose/commit/retry 主循环，见 `src/java/org/apache/cassandra/service/StorageProxy.java:483-568`。
- `StorageProxy.mutateCounter(...)`：counter coordinator 入口，先选择 leader replica，再本地执行或转发，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1723-1754`。
- `CounterMutation.applyCounterMutation()`：获取 counter locks、补当前值、写入结果 mutation，见 `src/java/org/apache/cassandra/db/CounterMutation.java:129-150`。
- `StorageProxy.sendToHintedReplicas(...)`：普通 mutation 的 local/remote/hint 分发入口，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1475-1564`。
- `HintsService.write(...)`：把 hint 写入 buffer pool 并增加 `StorageMetrics.totalHints`，见 `src/java/org/apache/cassandra/hints/HintsService.java:161-171`。
- `StorageProxy.syncWriteToBatchlog(...)` / `asyncRemoveFromBatchlog(...)`：logged batch 的 store/remove 消息，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1286-1321`。
- `BatchlogManager.store(...)` / `remove(...)`：写入和删除 `system.batches`，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:125-165`。

## 核心数据结构

- `Ballot` / `Commit` / `Proposal`：legacy 与 v2 Paxos 的 ballot、prepare/proposal/commit 内容。legacy prepare/proposal 创建见 `src/java/org/apache/cassandra/service/StorageProxy.java:597-607`、`src/java/org/apache/cassandra/service/StorageProxy.java:525-534`。
- `CASRequest` / `CQL3CasRequest`：CQL 条件、read command、updates 生成器；`ModificationStatement` 创建 request 后交给 `StorageProxy.cas()`，见 `src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:538-552`。
- `CounterContext.ClockAndCount`：counter 当前本地 clock/count 被读取后生成新 global counter value，见 `src/java/org/apache/cassandra/db/CounterMutation.java:231-239`。
- `HintsDescriptor` / `HintsStore.dispatchDequeue` / `HintsWriter`：hints 文件及 dispatch 队列；writer 创建见 `src/java/org/apache/cassandra/hints/HintsStore.java:295-314`。
- `Batch.id` / `creationTime` / `decodedMutations` / `encodedMutations`：batchlog 保存的 mutation 集合，见 `src/java/org/apache/cassandra/batchlog/Batch.java:41-55`。
- `BatchlogCleanup.mutationsWaitingFor`：每个 mutation 到达 cleanup 阈值后递减，为 0 时调用 remove callback，见 `src/java/org/apache/cassandra/service/BatchlogResponseHandler.java:93-116`。

## 生命周期

LWT/CAS：

```text
ModificationStatement.execute()
  -> hasConditions()
  -> executeWithCondition()
  -> StorageProxy.cas(keyspace, table, key, request, serialCL, commitCL, ...)
     -> Paxos.useV2() ? Paxos.cas(...) : legacyCas(...)
     -> prepare/begin
     -> read current values and evaluate CAS condition
     -> propose real update or empty proposal
     -> commit accepted proposal
     -> return null when applied, or current rows when condition failed
```

Counter write：

```text
ModificationStatement.executeWithoutCondition()
  -> isCounter() validates counter CL
  -> StorageProxy.mutateWithTriggers()
  -> StorageProxy.mutate()
     -> mutation instanceof CounterMutation
     -> mutateCounter()
        -> findSuitableReplica()
        -> if self replica: applyCounterMutationOnCoordinator()
        -> else send COUNTER_MUTATION_REQ to leader replica
     -> CounterMutation.applyCounterMutation()
        -> lock counter cells
        -> read counter cache / CFS current values
        -> write updated Mutation locally
        -> send result to hinted replicas
```

Hints：

```text
StorageProxy.sendToHintedReplicas()
  -> for each contacted replica
     -> if alive: send or apply locally
     -> else: responseHandler.expired(); shouldHint()
  -> submitHint()
     -> Stage.MUTATION writes HintsService.write(hostIds, Hint)
HintsService.startDispatch()
  -> HintsDispatchTrigger every 10s
  -> HintsDispatchExecutor.dispatch(store)
  -> HintsDispatcher.dispatch()
  -> delete file on full success, remember offset on partial failure
```

Logged batch / batchlog：

```text
BatchStatement.executeWithoutConditions()
  -> mutateAtomic = isLogged() && mutations.size() > 1
  -> StorageProxy.mutateWithTriggers(..., mutateAtomic)
  -> StorageProxy.mutateAtomically()
     -> build BatchlogCleanup
     -> syncWriteToBatchlog()
     -> syncWriteBatchedMutations()
        -> each mutation ack decrements BatchlogCleanup
     -> asyncRemoveFromBatchlog()
BatchlogManager.replayFailedBatches()
  -> read old system.batches rows
  -> ReplayingBatch.replay()
  -> direct writes when possible, hints for undelivered endpoints
  -> flush/fsync hints
  -> remove replayed batch rows
```

## 调用链

- Conditional CQL 进入 CAS：`ModificationStatement.execute()` 和 `executeWithCondition()`，见 `src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:491-552`。
- Internal conditional execution 使用本地 read 与 `casInternal()`，见 `src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:696-720`。
- legacy CAS 在 `legacyCas()` 读取当前值、判断条件、生成 updates、执行 triggers，再调用 `doPaxos()`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:335-395`。
- legacy `doPaxos()` 构造 `ReplicaPlans.forPaxos()`、`beginAndRepairPaxos()`、`Commit.newProposal()`、`proposePaxos()`、`commitPaxos()`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:493-568`。
- legacy prepare/propose/commit 消息分别见 `src/java/org/apache/cassandra/service/StorageProxy.java:695-731`、`src/java/org/apache/cassandra/service/StorageProxy.java:739-774`、`src/java/org/apache/cassandra/service/StorageProxy.java:776-803`。
- SERIAL read 也会走 Paxos read path，legacy 会用 empty update 完成/阻止未完成 proposal 后再 fetch rows，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1898-1956`。
- v2 CAS 在 `Paxos.cas()` 中 `begin()` 后读取当前值，条件失败时可提出 empty proposal，条件成功时生成 updates 并 `propose()`，见 `src/java/org/apache/cassandra/service/paxos/Paxos.java:650-760`。
- 普通写分支在 `StorageProxy.mutate()` 里识别 `CounterMutation` 并调用 `mutateCounter()`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:880-905`。
- counter leader 执行 `performWrite(..., counterWritePerformer, WriteType.COUNTER)`，随后 `counterWriteTask()` 调用 `applyCounterMutation()` 并复制结果，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1804-1836`。
- hints 提交时构造 hostIds、creation time，并写入 `HintsService.instance.write(...)`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:2776-2828`。
- hints dispatch 每 hostId 只安排一个任务，成功删除 descriptor，失败保存 offset 并放回队列，见 `src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:102-113`、`src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:283-324`。
- CQL logged batch 不允许包含 counter statement，见 `src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:180-221`。
- `BatchStatement.executeWithoutConditions()` 只有 logged 且 mutation 数大于 1 时走 atomic batch，见 `src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:434-445`。
- remote batchlog store/remove verb handlers 分别调用 `BatchlogManager.store()` 和 `BatchlogManager.remove()`，见 `src/java/org/apache/cassandra/batchlog/BatchStoreVerbHandler.java:24-32`、`src/java/org/apache/cassandra/batchlog/BatchRemoveVerbHandler.java:24-31`。

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| `cas_contention_timeout` | `src/java/org/apache/cassandra/config/Config.java:156-157`，模板 `conf/cassandra.yaml:1335-1339`，getter `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:2233-2240` | CAS contended proposal retry deadline |
| `paxos_variant` | `src/java/org/apache/cassandra/config/Config.java:969-1005`、`src/java/org/apache/cassandra/config/Config.java:1048-1051`，模板 `conf/cassandra.yaml:1590-1602` | v1/v2 Paxos 语义与优化选择 |
| `paxos_state_purging` | `src/java/org/apache/cassandra/config/Config.java:1017-1040` | Paxos state 清理策略；`repaired` 允许更低 commit RT |
| `paxos_on_linearizability_violations` | `src/java/org/apache/cassandra/config/Config.java:1066-1089` | 线性化异常检测后的 fail/log/ignore 策略 |
| `counter_write_request_timeout` | `src/java/org/apache/cassandra/config/Config.java:153-154`，模板 `conf/cassandra.yaml:1331-1334` | counter 写专用 timeout |
| `concurrent_counter_writes` | `src/java/org/apache/cassandra/config/Config.java:179-181`，模板 `conf/cassandra.yaml:716-724`，getter `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:2428-2440` | counter mutation stage 并发 |
| `counter_cache_size` / save options | `src/java/org/apache/cassandra/config/Config.java:479-483`，模板 `conf/cassandra.yaml:581-607` | counter read-before-write 热点优化 |
| `hinted_handoff_enabled` / disabled DCs / max window | `src/java/org/apache/cassandra/config/Config.java:112-117`，模板 `conf/cassandra.yaml:68-80` | 是否生成 hints、按 DC 禁用、最大 hint 窗口 |
| `hinted_handoff_throttle` / delivery threads / flush / file size | `src/java/org/apache/cassandra/config/Config.java:438-448`，模板 `conf/cassandra.yaml:82-111` | hints 投递和落盘速率/文件约束 |
| `hint_window_persistent_enabled` | `src/java/org/apache/cassandra/config/Config.java:117`，模板 `conf/cassandra.yaml:140-152` | 用最旧 hint 时间维持窗口，避免反复重启无限积累 |
| `batchlog_replay_throttle` | `src/java/org/apache/cassandra/config/Config.java:440-441`，模板 `conf/cassandra.yaml:157`，getter `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3681-3688` | batchlog replay 限速 |
| `batchlog_endpoint_strategy` | `src/java/org/apache/cassandra/config/Config.java:442`、`src/java/org/apache/cassandra/config/Config.java:1278-1320`，模板 `conf/cassandra.yaml:159-183` | batchlog 存储 endpoint 选择策略 |

## Metrics

- CAS request metrics 扩展了 `ClientRequestMetrics`，包括 `ContentionHistogram`、`UnfinishedCommit`、`UnknownResult`，见 `src/java/org/apache/cassandra/metrics/CASClientRequestMetrics.java:27-39`。
- CAS write metrics 包括 `MutationSizeHistogram` 和 `ConditionNotMet`，见 `src/java/org/apache/cassandra/metrics/CASClientWriteRequestMetrics.java:30-45`。
- CAS write/read 在 timeout/failure/unavailable/latency 上分别更新 `casWriteMetrics` 和 `casReadMetrics`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:398-440`、`src/java/org/apache/cassandra/service/StorageProxy.java:1956-1998`。
- Paxos linearizability violation counter 定义在 `PaxosMetrics`，见 `src/java/org/apache/cassandra/metrics/PaxosMetrics.java:25-29`。
- Hints 全局 counters 为 `StorageMetrics.totalHintsInProgress` 和 `StorageMetrics.totalHints`，见 `src/java/org/apache/cassandra/metrics/StorageMetrics.java:44-46`。
- Hinted handoff metrics 包括 created/not stored/unowned ranges，见 `src/java/org/apache/cassandra/metrics/HintedHandoffMetrics.java:36-70`。
- Hints delivery 成功/失败/timeout meter 定义在 `HintsServiceMetrics`，见 `src/java/org/apache/cassandra/metrics/HintsServiceMetrics.java:35-43`。
- Batch metrics 记录 logged/unlogged/counter batch 的 partition 数，见 `src/java/org/apache/cassandra/metrics/BatchMetrics.java:25-37`，更新见 `src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:449-456`。

## 日志

- CAS legacy 在读取 precondition、条件不满足、提出更新、preempted 时调用 tracing，见 `src/java/org/apache/cassandra/service/StorageProxy.java:346-367`、`src/java/org/apache/cassandra/service/StorageProxy.java:525-543`。
- Counter apply tracing 包括获取 counter locks、从 cache/CFS 取值，见 `src/java/org/apache/cassandra/db/CounterMutation.java:134-140`、`src/java/org/apache/cassandra/db/CounterMutation.java:213-222`。
- Hints 对 hint window/disabled DC/max size 的拒绝原因打 tracing，见 `src/java/org/apache/cassandra/service/StorageProxy.java:2449-2498`。
- Hints dispatch 成功和部分失败会记录 info 日志，见 `src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:296-324`。
- Batchlog replay 开始/结束与跳过异常会记录日志，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:200-226`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:288-310`。

## 运维关注点

- `SERIAL` 与 `LOCAL_SERIAL` 决定 Paxos prepare/propose 的 quorum 范围；legacy CAS 读取当前值时把 `LOCAL_SERIAL` 映射为 `LOCAL_QUORUM`，否则使用 `QUORUM`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:346-354`。
- v2 Paxos 升级不只是性能开关；配置模板要求先全量 `nodetool repair --full -pr` 再滚动设置，见 `conf/cassandra.yaml:1594-1602`。
- Counter 热点会同时受 `concurrent_counter_writes`、counter cache 命中率和 leader replica 选择影响。
- Counter 不建议依赖普通 hinted handoff 重试；失败恢复更多依赖上层重试、repair 和 counter cache/lock 正确性。
- Hints 只能覆盖短时间不可达；超过 `max_hint_window` 或单 host size limit 时不再创建新 hints。
- Hints pending 多时要同时看 in-flight backpressure 和 dispatch throttle；`checkHintOverload()` 可对目标节点抛 `OverloadedException`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1585-1599`。
- Logged batch 是跨 partition 原子性工具，不是批量吞吐优化；unlogged 多 partition batch 会有告警文案，见 `src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:85-93`。
- Batchlog replay 依赖 `gc_grace_seconds` 作为 TTL 上界；低 gcgs 可能导致 batchlog entry 未 replay 前过期，警告文案见 `src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:89-93`。

## 性能瓶颈

- LWT/CAS 的瓶颈是单 partition 竞争、Paxos RT、contention retry 和 serial consistency 跨 DC 范围。
- v1 Paxos 注释期望写 4RT、读 2/3RT；v2 注释期望写 2RT、读 1/2RT，见 `src/java/org/apache/cassandra/config/Config.java:973-1005`。
- Counter 写有 read-before-write 和 cell-level striped lock；热点 counter cell 会增加 lock 等待和 CFS read。
- Hints 写入会消耗 mutation stage、hints buffer/file IO，dispatch 又受 per destination throttle 限制。
- Batchlog 写会增加一次 batchlog replica 写入，成功后还要 remove；大量 logged batch 会提高 `system.batches` 与 replay 压力。

## 常见故障

- `CasWriteTimeoutException`：CAS prepare/propose/commit 未在 contention timeout 或 write timeout 内完成，legacy `doPaxos()` 最终抛出见 `src/java/org/apache/cassandra/service/StorageProxy.java:550-568`。
- `CasWriteUnknownResultException`：propose 部分接受但未达明确结果时抛出，见 `src/java/org/apache/cassandra/service/StorageProxy.java:767-773`。
- Counter `WriteTimeoutException(WriteType.COUNTER)`：counter locks 未按 timeout 获取，见 `src/java/org/apache/cassandra/db/CounterMutation.java:158-170`。
- Hints `OverloadedException`：总 in-flight hints 超阈值且目标已有 in-flight hints，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1585-1599`。
- Hints 停止写入：目标不在 ring、超过 hint window、超过 max hints size 或 DC 被禁用，见 `src/java/org/apache/cassandra/service/StorageProxy.java:2428-2498`。
- Batchlog replay 残留：目标反复不可达时 replay 会写 hints 并保留失败状态；可通过 `BatchlogManager.forceBatchlogReplay()` 触发，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:183-191`。

## 测试用例

- LWT/Paxos：`test/distributed/org/apache/cassandra/distributed/test/CASTest.java`、`test/distributed/org/apache/cassandra/distributed/test/CASContentionTest.java`、`test/distributed/org/apache/cassandra/distributed/test/LegacyCASTest.java`、`test/unit/org/apache/cassandra/service/paxos/PaxosProposeTest.java`、`test/unit/org/apache/cassandra/service/paxos/PaxosRepairTest.java`。
- Counter：`test/distributed/org/apache/cassandra/distributed/test/CountersTest.java`、`test/unit/org/apache/cassandra/db/CounterMutationTest.java`、`test/unit/org/apache/cassandra/db/CounterMutationVerbHandlerOutOfRangeTest.java`、`test/unit/org/apache/cassandra/db/CounterCacheTest.java`、`test/unit/org/apache/cassandra/cql3/validation/entities/CountersTest.java`。
- Hinted Handoff：`test/unit/org/apache/cassandra/hints/HintsServiceTest.java`、`test/unit/org/apache/cassandra/hints/HintsStoreTest.java`、`test/unit/org/apache/cassandra/hints/HintsReaderTest.java`、`test/distributed/org/apache/cassandra/distributed/test/HintsMaxWindowTest.java`、`test/distributed/org/apache/cassandra/distributed/test/HintedHandoffNodetoolTest.java`。
- Batchlog：`test/unit/org/apache/cassandra/batchlog/BatchlogManagerTest.java`、`test/unit/org/apache/cassandra/batchlog/BatchlogTest.java`、`test/unit/org/apache/cassandra/batchlog/BatchlogEndpointFilterTest.java`、`test/unit/org/apache/cassandra/cql3/validation/operations/BatchTest.java`、`test/distributed/org/apache/cassandra/distributed/test/PrepareBatchStatementsTest.java`。

## 待继续

- 第二轮内部细节已沉淀到 `research/module-coordination-lwt-counter-hints-internals.md`：覆盖 Paxos v2 state/repair/uncommitted tracker、counter context、hints 文件格式与 batchlog endpoint strategy。
- 后续继续补 `PaxosCommitAndPrepare`/`PaxosPrepareRefresh` 的逐方法细节、counter tombstone/delete 与 compaction 交互、HintsBuffer rollover/upgrade fixtures、mixed-version logged batch 和 operator runbook。
