# Module: Coordination Fault Coverage And Operator Runbook

## 范围

本文是 LWT/Paxos、Counter、Hints、Batchlog 的第四轮源码/测试矩阵，聚焦四类剩余问题：

- Paxos v2 `PaxosCommitAndPrepare`、`PaxosPrepareRefresh` 的 fault coverage 边界。
- Counter tombstone、repair、compaction 的现有覆盖与缺口。
- Hints same-version encoded dispatch、cross-version decoded dispatch 与 mixed-version dtest 缺口。
- Logged batch large mutation、batchlog replay、hints backlog 的 operator runbook。

前置主线见 `research/module-coordination-lwt-counter-hints.md`、`research/module-coordination-lwt-counter-hints-internals.md`、`research/module-coordination-lwt-counter-hints-deep-dive.md`、`research/flow-lwt-paxos.md`、`research/flow-counter-write.md`、`research/flow-hints-batchlog.md`。Paxos v2 direct-fault 的 commit-and-prepare ordering、prepare-refresh self-failure/superseded response 和 direct handler gap 细分矩阵见 `research/module-coordination-paxos-direct-fault-matrix.md`；Counter tombstone + repair/compaction 的 digest、validation compaction、cache invalidation 和 distributed gap 细分矩阵见 `research/module-coordination-counter-repair-compaction-matrix.md`；Hints/batchlog durable backlog 的 admission、dispatch retry、orphan conversion、batchlog replay fsync-before-delete 和 CLI observability 细分矩阵见 `research/module-coordination-hints-batchlog-backlog-matrix.md`。

本 runbook 由 `research/tools/check-coordination-fault-coverage-drift.py` 做 source/test/gap drift check，说明见 `research/module-coordination-fault-coverage-drift-checker.md`。

## 设计目标

- 把“缺测试”拆成源码存在、已有测试、仍缺专项测试三个层级，避免把已覆盖的 message drop 场景重复标为未知。
- 给运维动作绑定源码入口：batchlog replay 不是只查 `system.batches`，还要理解 replay throttle、timeout、generated hints fsync 与 batchlog row 删除顺序。
- 区分 hints encoded fast path 和 decoded compatibility path：`HintsDispatcher` 在 hints 文件 messaging version 等于目标 messaging version 时走 `sendEncodedHint()`，否则走 `sendHint()`，见 `src/java/org/apache/cassandra/hints/HintsDispatcher.java:126-140` 和 `src/java/org/apache/cassandra/hints/HintsDispatcher.java:192-209`。
- 把 large logged batch 拆成 batch size guardrail、mutation size guardrail、batchlog store timeout 和 replay backlog 四个独立风险。

## 覆盖场景 ID

| 场景 ID | 保护内容 |
|---|---|
| `coordination_paxos_commit_prepare_fault_boundary` | `PaxosCommitAndPrepare` source path、`PAXOS2_COMMIT_AND_PREPARE_REQ` message-drop baseline 和 range-gate null response 边界。 |
| `coordination_paxos_prepare_refresh_fault_gap` | `PaxosPrepareRefresh` callbacks、local timeout、superseding ballot 与 direct handler fault tests 缺口。 |
| `coordination_counter_tombstone_repair_compaction_gap` | counter tombstone/unit baseline、empty context distributed baseline 与 counter tombstone + repair/compaction distributed 缺口。 |
| `coordination_hints_encoded_decoded_dispatch_boundary` | `HintsDispatcher` same-version encoded path、cross-version decoded path、metrics 和 serializer/reader fixtures。 |
| `coordination_hints_mixed_version_dispatch_gap` | descriptor messaging version 与目标 messaging version 不同且实际 dispatch 的 mixed-version dispatch dtest 缺口。 |
| `coordination_batchlog_large_mutation_boundary` | `batch_size_warn_threshold`、`batch_size_fail_threshold`、`max_mutation_size`、transient logged batch rejection 与现有 oversized/mixed-mode coverage。 |
| `coordination_batchlog_replay_hints_backlog_runbook` | `BatchlogManager` replay、timeout 后写 hints、hints fsync 后删除 batchlog row 和 replay counters。 |
| `coordination_operator_hints_batchlog_surface` | `replaybatchlog`、`listpendinghints`、handoff pause/resume/enable/disable/truncate 和 batchlog replay throttle 操作面。 |
| `coordination_existing_tests_baseline` | 本文引用的现有 Paxos、Counter、Hints、Batchlog 测试锚点。 |

## 解决的问题

| 问题 | 本轮结论 | 证据 |
|---|---|---|
| Paxos commit-and-prepare 是否完全无 fault 覆盖 | 不是。`CasWriteTest` 已 drop `PAXOS2_COMMIT_AND_PREPARE_REQ`，`CASTest` 的 paxos/read verb 集包含 refresh 和 commit-and-prepare，`PaxosRepairTest` 在 cleanup/reproposal race 中 drop commit-and-prepare。仍缺的是 direct handler 层的 range-gate/null response、refresh superseded ballot、local execute timeout 等细粒度单测。 | `test/distributed/org/apache/cassandra/distributed/test/CasWriteTest.java:164-179`、`test/distributed/org/apache/cassandra/distributed/test/CASTest.java:185-245`、`test/distributed/org/apache/cassandra/distributed/test/PaxosRepairTest.java:332-365` |
| Counter delete 是否已有语义覆盖 | 单 JVM 已覆盖 counter cell tombstone 和 row tombstone shadowing；distributed 覆盖 empty context/repaired metadata read；仍缺 counter delete + repair + compaction 的端到端 distributed 场景。 | `test/unit/org/apache/cassandra/db/CounterMutationTest.java:160-217`、`test/distributed/org/apache/cassandra/distributed/test/CountersTest.java:85-125` |
| Hints mixed-version dispatch 是否已有端到端覆盖 | 现有测试覆盖 encoded serializer、reader raw/decoded iterator、legacy 3.0/4.1 fixture 读取；缺一个让目标节点 messaging version 与 hints descriptor version 不同并实际 dispatch 的 distributed/upgrade 测试。 | `test/unit/org/apache/cassandra/hints/HintMessageTest.java:88-120`、`test/unit/org/apache/cassandra/hints/HintsReaderTest.java:106-170`、`test/unit/org/apache/cassandra/hints/HintsUpgradeTest.java:108-160` |
| Logged batch large mutation 是否已有覆盖 | distributed `OversizedMutationTest` 覆盖 oversized batch 触发 mutation size rejection；mixed-mode logged batch 覆盖 batchlog store timeout；仍缺大 logged batch 越过 warn、接近 fail、再结合 replay/hints 的专项运行矩阵。 | `test/distributed/org/apache/cassandra/distributed/test/OversizedMutationTest.java:46-62`、`test/distributed/org/apache/cassandra/distributed/upgrade/MixedModeBatchTestBase.java:64-155` |

## 设计取舍

- Paxos v2 把 commit 和下一轮 prepare 合在一个 verb 中减少一次往返；代价是 request 同时序列化 `Agreed` 和 prepare request，服务端必须在同一个 `PaxosState` 上先 commit 再 prepare，见 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:45-55`、`src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:97-115`、`src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:131-142`。
- Prepare refresh 只在 prepare 已有 quorum 但 quorum 中部分节点缺 latest commit 时介入；它提高 future quorum 可见性，但把 refresh success/failure 接回 prepare 状态机，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:597-635` 和 `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:104-139`。
- Counter 不写普通 mutation hint；`CounterMutation.hintOnFailure()` 返回 `null`，因为 counter write 必须先在 leader 读改写并生成全局 shard，见 `src/java/org/apache/cassandra/db/CounterMutation.java:85-98` 和 `src/java/org/apache/cassandra/db/CounterMutation.java:129-145`。
- Hints same-version dispatch 避免重复 decode/encode；cross-version dispatch 必须 decode 为 `Hint` 再 serialize 到目标版本，见 `src/java/org/apache/cassandra/hints/HintMessage.java:170-190` 和 `src/java/org/apache/cassandra/hints/HintsDispatcher.java:130-140`。
- Batchlog replay 为未投递 endpoints 写 hints，并在 hints fsync 后才删除 batchlog row；这保留 logged batch 语义，但会把 batchlog backlog 转化为 hints backlog，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:312-316` 和 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:420-445`。

## 核心类

| 类 | 责任 | 关键边界 |
|---|---|---|
| `PaxosCommitAndPrepare` | 构造 `PAXOS2_COMMIT_AND_PREPARE_REQ`，服务端执行 commit + prepare。 | range-gate 失败返回 null 并 respond failure，见 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:119-142`。 |
| `PaxosPrepareRefresh` | 对缺 latest commit 的 promised participants 提交 missing commit 并确认 promise。 | local execute 捕获 timeout/unknown，remote response 返回 nullable superseding ballot，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:116-139`、`src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:175-195`。 |
| `CounterMutation` | counter leader 读当前值、加 update context、写 global shard、更新 counter cache。 | 加锁、读 CFS、写 cache 的主线在 `src/java/org/apache/cassandra/db/CounterMutation.java:129-145`、`src/java/org/apache/cassandra/db/CounterMutation.java:207-239`。 |
| `CounterContext` | counter shard diff/merge、local/remote/global 规则、legacy local shard clear。 | inconsistent shard 返回 `DISJOINT` 让 read repair 能处理，见 `src/java/org/apache/cassandra/db/context/CounterContext.java:197-225`；merge 规则见 `src/java/org/apache/cassandra/db/context/CounterContext.java:400-444`。 |
| `HintsDispatcher` | 分页发送 hints 文件，选择 encoded 或 decoded path，统计 success/failure/timeout。 | 目标 messaging version 从 `MessagingService` 取，见 `src/java/org/apache/cassandra/hints/HintsDispatcher.java:76-82`；dispatch 结果更新 metrics，见 `src/java/org/apache/cassandra/hints/HintsDispatcher.java:144-171`。 |
| `HintMessage` | hint dispatch wire message，支持 encoded fast path。 | encoded message 只能按匹配 version serialize，接收端总是反序列化成普通 `HintMessage`，见 `src/java/org/apache/cassandra/hints/HintMessage.java:94-140`、`src/java/org/apache/cassandra/hints/HintMessage.java:170-190`。 |
| `BatchlogManager` | `system.batches` store/remove/replay、rate limit、timeout 后写 hints。 | replay 查询到期 batch，page 内等待 unfinished batches，hints fsync 后删除 batch，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:200-247`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:260-325`。 |

## 核心接口

| 接口 | 用途 | 证据 |
|---|---|---|
| `RequestCallbackWithFailure<PaxosPrepareRefresh.Response>` | prepare refresh success/failure 回调到 `PaxosPrepare`。 | `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:58-70` |
| `IVerbHandler<PaxosCommitAndPrepare.Request>` / `IVerbHandler<PaxosPrepareRefresh.Request>` | Paxos v2 verb 服务端入口。 | `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:119-142`、`src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:163-197` |
| `HintsServiceMBean` | pause/resume/delete/list pending hints 的 JMX 接口。 | `src/java/org/apache/cassandra/hints/HintsServiceMBean.java:23-52` |
| `BatchlogManagerMBean` | count all batches、total replayed、force replay。 | `src/java/org/apache/cassandra/batchlog/BatchlogManagerMBean.java:20-37` |
| `NodeTool.NodeToolCmd` hints/batchlog commands | operator CLI 入口。 | `src/java/org/apache/cassandra/tools/nodetool/ListPendingHints.java:37-95`、`src/java/org/apache/cassandra/tools/nodetool/ReplayBatchlog.java:28-41` |

## 核心数据结构

- `PaxosCommitAndPrepare.Request`：`Agreed commit`、new ballot/electorate/read/isWrite；serializer 先写 agreed commit 再写 prepare request，见 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:58-115`。
- `PaxosPrepareRefresh.Request/Response`：request 保存 promised ballot 与 missing commit；response 保存 nullable superseding ballot，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:142-161`。
- `CounterContext.ContextState`：header 标记 global/local shard，body 保存 counter id、clock、count；allocate 和 local/global/remote 判断见 `src/java/org/apache/cassandra/db/context/CounterContext.java:780-884`。
- `HintMessage.Encoded`：hostId、hint ByteBuffer、messaging version；只用于 same-version send，见 `src/java/org/apache/cassandra/hints/HintMessage.java:170-190`。
- `BatchlogManager.ReplayingBatch`：保存 batch id、version、serialized mutation list，replay 后等待 handlers 并为未投递 endpoints 写 hints，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:354-445`。

## 生命周期

1. Paxos commit-and-prepare：coordinator 从 incomplete commit/reproposal 进入 `commitAndPrepare()`，构造 request 并 `start()`；recipient range-gate 成功后 `state.commit(commit)`，再执行 prepare handler，见 `src/java/org/apache/cassandra/service/paxos/Paxos.java:994-1022` 和 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:45-55`。
2. Paxos prepare refresh：prepare 收集 promise，将缺 latest commit 的节点放入 `needLatest`；有 latest read response 时启动 refresh；refresh 成功后确认 promise 或返回 superseding ballot，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:520-635` 和 `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:81-102`。
3. Counter write：leader 构造 `CounterMutation`，按 table/key/clustering/column 加锁，读 cache/CFS 当前值，写 global shard 并更新 cache，见 `src/java/org/apache/cassandra/db/CounterMutation.java:129-145`、`src/java/org/apache/cassandra/db/CounterMutation.java:180-239`。
4. Hints dispatch：dispatch executor 取 hints descriptor，`HintsDispatcher.create()` 读取目标 messaging version，逐 page 发送 hints，成功则删除 descriptor，失败记录 offset，见 `src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:270-322`。
5. Batchlog replay：`startBatchlogReplay()` submit replay task；replay 只扫描超过 batchlog timeout 的 rows；每 page 发送并等待 unfinished batches；timeout/failure 写 hints；fsync hints 后删除 replayed batch rows，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:188-247`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:260-325`。

## 调用链

```text
Paxos.commitAndPrepare()
  -> PaxosCommitAndPrepare.commitAndPrepare()
  -> Message.out(PAXOS2_COMMIT_AND_PREPARE_REQ, request)
  -> RequestHandler.execute()
  -> PaxosState.commit()
  -> PaxosPrepare.RequestHandler.execute()
```

```text
PaxosPrepare.addResponse()
  -> needLatest/withLatest split
  -> refreshStaleParticipants()
  -> PaxosPrepareRefresh.refresh()
  -> RequestHandler.execute()
  -> callbacks.onRefreshSuccess/onRefreshFailure()
```

```text
HintsDispatchExecutor.dispatch()
  -> HintsDispatcher.create()
  -> dispatch(page)
  -> reader.descriptor().messagingVersion() == target version
     ? sendEncodedHint(ByteBuffer)
     : sendHint(Hint)
  -> HintsServiceMetrics hintsSucceeded/hintsFailed/hintsTimedOut
```

```text
nodetool replaybatchlog
  -> NodeProbe.replayBatchlog()
  -> BatchlogManager.forceBatchlogReplay()
  -> startBatchlogReplay().get()
  -> replayFailedBatches()
  -> processBatchlogEntries()
  -> ReplayingBatch.finish()
  -> HintsService.flushAndFsyncBlockingly()
  -> BatchlogManager.remove()
```

Nodetool entrypoints are in `src/java/org/apache/cassandra/tools/nodetool/ReplayBatchlog.java:28-41`; the MBean entry is `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:183-191`。

## 配置项

| 配置 | 影响 | 证据 |
|---|---|---|
| `hinted_handoff_enabled` | 是否存储 future hints。 | `conf/cassandra.yaml:68`、`src/java/org/apache/cassandra/config/Config.java:112-115` |
| `hinted_handoff_disabled_datacenters` | 禁用特定 DC 的 hints。 | `conf/cassandra.yaml:70-72`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3551-3576` |
| `max_hint_window` | 目标节点 down 超过窗口后不再保留 hints。 | `conf/cassandra.yaml:80`、`src/java/org/apache/cassandra/config/Config.java:112-115` |
| `hinted_handoff_throttle` | 每 delivery thread 的 hints 发送限速。 | `conf/cassandra.yaml:88`、`src/java/org/apache/cassandra/config/Config.java:438-439` |
| `max_hints_delivery_threads` | hints dispatch 并发。 | `conf/cassandra.yaml:93`、`src/java/org/apache/cassandra/config/Config.java:443-447` |
| `max_hints_size_per_host` | 单 host hints backlog 上限，0 表示禁用。 | `conf/cassandra.yaml:111`、`src/java/org/apache/cassandra/config/Config.java:448` |
| `auto_hints_cleanup_enabled` / `transfer_hints_on_decommission` | hints 清理与 decommission 时 transfer 行为。 | `conf/cassandra.yaml:115-120`、`src/java/org/apache/cassandra/config/Config.java:451-453` |
| `batchlog_replay_throttle` | batchlog replay 全局 KiB/s，运行时按 endpoint 数缩小。 | `conf/cassandra.yaml:157`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:229-247` |
| `batchlog_endpoint_strategy` | batchlog endpoint selection 策略。 | `conf/cassandra.yaml:183`、`src/java/org/apache/cassandra/config/Config.java:440-442` |
| `batch_size_warn_threshold` / `batch_size_fail_threshold` | batch 数据量超过 warn/fail 阈值时 warn 或拒绝。 | `src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:331-365`、`test/unit/org/apache/cassandra/config/ParseAndConvertUnitsTest.java:93-100` |
| `max_mutation_size` | 单 mutation/merged mutation 最大序列化尺寸。 | `test/distributed/org/apache/cassandra/distributed/test/OversizedMutationTest.java:31-62`、`test/unit/org/apache/cassandra/db/commitlog/CommitLogTest.java:508-565` |

## Metrics

- Hints dispatch page 结果更新 `HintsSucceeded`、`HintsFailed`、`HintsTimedOut`，见 `src/java/org/apache/cassandra/metrics/HintsServiceMetrics.java:39-63` 和 `src/java/org/apache/cassandra/hints/HintsDispatcher.java:144-171`。
- Hinted handoff per endpoint 计数包括 created hints、not stored hints、unowned range hints，见 `src/java/org/apache/cassandra/metrics/HintedHandoffMetrics.java:43-83`。
- Storage 全局 metrics 包含 `TotalHintsInProgress` 与 `TotalHints`，见 `src/java/org/apache/cassandra/metrics/StorageMetrics.java:44-48`。
- Batchlog replay count 暴露为 `BatchlogManager.getTotalBatchesReplayed()`，当前 backlog 可通过 `countAllBatches()` 读 `system.batches`，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:167-181` 和 `src/java/org/apache/cassandra/batchlog/BatchlogManagerMBean.java:20-37`。

## 日志

- Paxos commit-and-prepare trace 会记录 commit ballot 与 prepare ballot，见 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:45-55`。
- Prepare refresh trace/log 包含 refresh/confirm 目标、promise rescinded 或 confirmed，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:81-102`、`src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:182-195`。
- Hints dispatcher failure 会触发 diagnostics page failure，metrics 区分 failure/timeout；相关结果在 `src/java/org/apache/cassandra/hints/HintsDispatcher.java:144-171`。
- Batchlog replay 对 IOException 记录 skipped warning，对 replay timeout/failure 写 trace 并转 hints，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:288-316`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:372-387`。
- Batch size 超过 fail threshold 时 trace + error 并抛 `InvalidRequestException("Batch too large")`，见 `src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:349-359`。

## 运维关注点

| 场景 | 建议动作 | 源码依据 |
|---|---|---|
| Batchlog backlog 增长 | 用 `nodetool replaybatchlog` 强制 replay；同时查 `BatchlogManager.countAllBatches()` 与 `getTotalBatchesReplayed()`。 | `src/java/org/apache/cassandra/tools/nodetool/ReplayBatchlog.java:28-41`、`src/java/org/apache/cassandra/batchlog/BatchlogManagerMBean.java:20-37` |
| Replay 太慢或影响前台写 | 用 `nodetool getbatchlogreplaythrottle` / `setbatchlogreplaythrottle` 调整；注意 throttle 会按 endpoint 数缩小。 | `src/java/org/apache/cassandra/tools/nodetool/GetBatchlogReplayTrottle.java:24-32`、`src/java/org/apache/cassandra/tools/nodetool/SetBatchlogReplayThrottle.java:25-36`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:229-247` |
| Replay timeout 后 hints 堆积 | 先 `nodetool listpendinghints` 看 host/backlog/oldest/newest，再判断是否 `pausehandoff`、调 throttle 或等待目标恢复。 | `src/java/org/apache/cassandra/tools/nodetool/ListPendingHints.java:37-95`、`src/java/org/apache/cassandra/tools/nodetool/PauseHandoff.java:25-32`、`src/java/org/apache/cassandra/tools/nodetool/ResumeHandoff.java:25-32` |
| 需要清理无效 hints | `truncatehints` 可全量或按 endpoint 删除；这是不可逆操作，只适合确认目标数据不再需要 hint replay 的场景。 | `src/java/org/apache/cassandra/tools/nodetool/TruncateHints.java:27-40`、`src/java/org/apache/cassandra/hints/HintsServiceMBean.java:35-45` |
| 临时停止/恢复 future hints | `disablehandoff`/`enablehandoff` 控制是否继续存储 future hints；`pausehandoff`/`resumehandoff` 只影响 dispatch。 | `src/java/org/apache/cassandra/tools/nodetool/DisableHandoff.java:25-32`、`src/java/org/apache/cassandra/tools/nodetool/EnableHandoff.java:25-32`、`src/java/org/apache/cassandra/hints/HintsServiceMBean.java:25-33` |
| 大 logged batch 失败 | 区分 batch fail threshold 的 `Batch too large` 与 `max_mutation_size` 的 oversized mutation；两者触发点不同。 | `src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:331-365`、`src/java/org/apache/cassandra/cql3/statements/SingleTableUpdatesCollector.java:97-113` |

## 性能瓶颈

- `PaxosCommitAndPrepare` 节省一次往返，但 agreed commit 越大，combined request 序列化越重，见 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:97-115`。
- Prepare refresh 会给 stale participants 额外发送 `PAXOS2_PREPARE_REFRESH_REQ`；若 refresh 频繁，说明 prepare quorum 中 latest commit 可见性不稳定，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:617-635`。
- Counter write 在 cell 粒度 striped locks 上等待，并读取 cache/CFS 当前值；热点 counter 会受锁等待和 read-before-write 限制，见 `src/java/org/apache/cassandra/db/CounterMutation.java:158-176`、`src/java/org/apache/cassandra/db/CounterMutation.java:207-239`。
- Hints encoded path 避免 decode/encode；mixed-version dispatch 必须 decode hints，CPU 和 allocation 成本更高，见 `src/java/org/apache/cassandra/hints/HintsReader.java:43-49` 和 `src/java/org/apache/cassandra/hints/HintsDispatcher.java:130-140`。
- Batchlog replay page size 受 `system.batches` 平均 partition size 影响，并且每 page 后等待 unfinished batches，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:214-224`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:296-307`。

## 常见故障

| 故障 | 触发点 | 处理线索 |
|---|---|---|
| Paxos commit-and-prepare range gate 失败 | recipient 不应处理该 partition/table 时 `RequestHandler.execute()` 返回 null。 | 需要 direct handler/simulator 覆盖 respond failure 分支，源码见 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:131-142`。 |
| Prepare refresh promise 被更高 ballot 抢占 | `state.current(promised).latestWitnessedOrLowBound()` 晚于 promised。 | response 携带 superseding ballot，prepare 回调应转入 superseded/retry，源码见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:182-195`。 |
| Counter delete 后旧 shard 重新出现 | tombstone 必须 shadow 后续 counter increment。 | `CounterMutationTest.testDeletes()` 已覆盖 cell tombstone 与 row tombstone shadowing，见 `test/unit/org/apache/cassandra/db/CounterMutationTest.java:181-217`。 |
| Hints dispatch 到 mixed-version target 失败 | descriptor messaging version 与 target messaging version 不同，decoded path 反序列化/重序列化失败或 timeout。 | 当前缺 distributed upgrade dispatch dtest；source split 见 `src/java/org/apache/cassandra/hints/HintsDispatcher.java:126-140`。 |
| Batchlog replay 后 batchlog 清空但 hints 激增 | replay delivery timeout 后写 hints，fsync 后删除 batchlog rows。 | 同时检查 `system.batches` count 与 pending hints；源码见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:372-387`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:420-445`。 |
| Logged batch 使用 transient replication | `StorageProxy.mutateAtomically()` 直接 assertion。 | logged batches 不支持 transient replicas，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1173-1186`。 |

## 测试用例

| 区域 | 已有测试 | 仍需补的专项测试 |
|---|---|---|
| Paxos v2 commit-and-prepare / refresh | `CasWriteTest` drop v2 commit-and-prepare request/remote response；`CASTest` 把 prepare refresh 和 commit-and-prepare 放入 paxos/read drop matrix；`PaxosRepairTest` 覆盖 cleanup 与 reproposal race。 | direct handler fault tests：commit-and-prepare range gate null response、refresh local timeout、refresh superseded ballot；再和 simulator Paxos fault model 对齐。 |
| Counter tombstone / repair / compaction | `CounterMutationTest.testDeletes()` 覆盖 tombstone shadowing；`CounterContextTest.testClearLocal()` 覆盖 legacy local shard clear；`CountersTest.testEmptyContext()` 覆盖 distributed repaired metadata empty context read。 | 3-node distributed test：写 counter、flush、delete counter/row、repair、compact，再验证 delete 不被旧 shard resurrect，并检查 repaired data tracking。 |
| Hints mixed-version dispatch | `HintMessageTest.testEncodedSerializer()`、`HintsReaderTest` raw/decoded iterator、`HintsUpgradeTest` legacy fixture 读取。 | Upgrade dtest：生成旧 descriptor/version hints，目标节点 messaging version 不同，强制 dispatch，断言 decoded path 成功与 metrics/logs。 |
| Logged batch large mutation / runbook | `OversizedMutationTest.testOversizedBatch()` 覆盖 `max_mutation_size` rejection；`MixedModeLoggedBatchTest` 覆盖 mixed-version logged batch store timeout；`BatchlogManagerTest.testReplay()` 覆盖到期 batch replay 与 count。 | Large logged batch matrix：warn threshold、fail threshold、mutation size、batchlog store timeout、replay timeout -> hints backlog，并覆盖 operator runbook 的 observability assertions。 |

第四轮结论：operator runbook 和源码/测试 gap matrix 已补齐；第六轮已把 Paxos v2 direct-fault 拆到 `research/module-coordination-paxos-direct-fault-matrix.md`，并把 counter tombstone + repair/compaction 进一步拆到 `research/module-coordination-counter-repair-compaction-matrix.md`。仍未实现上述新增专项测试。
