# Coordination Paxos Direct Fault Matrix

## 范围

本文是 Paxos/Counter/Hints/Batchlog 第六轮补充中的 Paxos v2 direct-fault 专项矩阵，聚焦：

- `PaxosCommitAndPrepare` 如何把 incomplete commit repair 和下一轮 prepare 合并到 `PAXOS2_COMMIT_AND_PREPARE_REQ`。
- `PaxosPrepareRefresh` 如何对 stale promised participants 写入 missing commit、确认 promise 或返回 superseding ballot。
- local self-execution 如何把 `WriteTimeoutException` 映射为 `TIMEOUT`，其他 exception 映射为 `UNKNOWN`。
- 现有 distributed tests 已覆盖 message drop / timeout / cleanup race；仍缺 direct handler 层的 range-gate null response、refresh local timeout 和 superseded ballot 单测/模拟矩阵。

前置主线见 `research/module-coordination-lwt-counter-hints.md`、`research/module-coordination-lwt-counter-hints-internals.md`、`research/module-coordination-lwt-counter-hints-deep-dive.md`、`research/flow-lwt-paxos.md` 和 `research/module-coordination-fault-coverage-runbook.md`。本矩阵由 `research/tools/check-coordination-paxos-direct-fault-drift.py` 保护，checker 说明见 `research/module-coordination-paxos-direct-fault-drift-checker.md`。

## Drift Checker Scenarios

| 场景 ID | 覆盖语义 |
|---|---|
| `coordination_paxos_commit_prepare_entry` | `Paxos.begin()` 在 incomplete committed / accepted path 中进入 `commitAndPrepare()`。 |
| `coordination_paxos_commit_prepare_message_contract` | request 同时携带 `Agreed commit` 和 prepare ballot/electorate/read/isWrite，并注册到 `PAXOS2_COMMIT_AND_PREPARE_REQ/RSP`。 |
| `coordination_paxos_commit_prepare_handler_order` | handler range-gate 成功后先 `state.commit(commit)`，再 `PaxosPrepare.RequestHandler.execute(...)`。 |
| `coordination_paxos_commit_prepare_range_gate_gap` | range-gate null response -> `respondWithFailure(UNKNOWN, message)` 的 direct handler test 仍缺。 |
| `coordination_paxos_prepare_refresh_trigger` | `PaxosPrepare` 将 needLatest participants 交给 `PaxosPrepareRefresh.refresh()`。 |
| `coordination_paxos_prepare_refresh_self_failure` | self-execution maps `WriteTimeoutException` to `TIMEOUT` and other exceptions to `UNKNOWN`。 |
| `coordination_paxos_prepare_refresh_superseded` | refresh handler may return nullable superseding ballot; callback converts it to `READ_PERMITTED` or `SUPERSEDED`。 |
| `coordination_paxos_prepare_refresh_range_gate_gap` | refresh range-gate null response / local timeout / superseded ballot direct tests 仍缺。 |
| `coordination_paxos_existing_drop_tests_baseline` | `CasWriteTest`、`CASTest`、`PaxosRepairTest` 的 verb drop / cleanup race baseline。 |
| `coordination_paxos_direct_handler_test_gap` | 当前没有直接调用 `PaxosCommitAndPrepare` / `PaxosPrepareRefresh` handler 的 unit/simulator/distributed test。 |

## 设计目标

- 区分 “distributed message drop 能触发 CAS timeout” 与 “direct handler branch 被单测证明” 两种覆盖层次。
- 把 commit-and-prepare 的 commit-before-prepare ordering 固化为 source-backed contract。
- 把 prepare-refresh 的三类 fault surface 拆开：range-gate null、local exception mapping、superseding ballot response。
- 保留机器可校验缺口：若未来新增 direct handler/simulator tests，checker 会失败，迫使本矩阵从 gap 改写为覆盖事实。

## 关键结论

| 问题 | 结论 | 证据 |
|---|---|---|
| commit-and-prepare 在哪触发 | `Paxos.begin()` 发现 `FOUND_INCOMPLETE_COMMITTED` 时直接 `commitAndPrepare(incomplete.committed, ...)`；发现 incomplete accepted 且 repropose success 后也 `commitAndPrepare(repropose.agreed(), ...)`。 | `src/java/org/apache/cassandra/service/paxos/Paxos.java:990-995`、`src/java/org/apache/cassandra/service/paxos/Paxos.java:1018-1023` |
| commit-and-prepare handler 顺序是什么 | recipient range-gate 成功后用 commit 打开 `PaxosState`，先 `state.commit(commit)`，再执行 prepare handler。 | `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:131-142` |
| commit-and-prepare range 不该处理时如何响应 | `RequestHandler.execute()` 返回 null，`doVerb()` 使用 `MessagingService.instance().respondWithFailure(UNKNOWN, message)`。 | `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:119-128`、`src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:131-135` |
| prepare refresh 什么时候触发 | prepare 收到 quorum，但 quorum 中 latest commit 不足时，`refreshStaleParticipants()` 对 `needLatest` 发送 refresh。 | `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:617-635`、`src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:847-859` |
| prepare refresh self-execution 如何处理失败 | local execute 返回 null 时 silent return；`WriteTimeoutException` 映射 `TIMEOUT`，其他 exception log 后映射 `UNKNOWN`。 | `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:116-135` |
| prepare refresh superseded ballot 如何传播 | handler 写入 missing commit 后读取 current promised state；若 latest after promised，response 带 superseding ballot；callback 转为 `READ_PERMITTED` 或 `SUPERSEDED`。 | `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:175-195`、`src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:867-886` |
| 现有测试是否覆盖 direct branch | 否。现有 distributed tests drop `PAXOS2_COMMIT_AND_PREPARE_REQ` / `PAXOS2_PREPARE_REFRESH_REQ` 证明 timeout/consistency race，但没有直接调用 handler 或构造 superseded/local-timeout branch。 | `test/distributed/org/apache/cassandra/distributed/test/CasWriteTest.java:164-170`、`test/distributed/org/apache/cassandra/distributed/test/CASTest.java:185-245`、`test/distributed/org/apache/cassandra/distributed/test/PaxosRepairTest.java:332-365` |

## 核心类

| 类 | 责任 | 关键边界 |
|---|---|---|
| `Paxos` | CAS begin loop、incomplete commit/proposal handling、retry orchestration。 | `FOUND_INCOMPLETE_COMMITTED` and repropose `SUCCESS` both call commit-and-prepare. |
| `PaxosCommitAndPrepare` | Combined `Agreed commit` + prepare request serializer/handler。 | Range-gate null -> failure; state commit precedes prepare execute. |
| `PaxosPrepare` | Prepare quorum state machine、needLatest tracking、refresh callback consumer。 | `withLatest + needLatest` reaches quorum before refresh; superseded refresh may complete read permission. |
| `PaxosPrepareRefresh` | Missing commit refresh and promise confirmation。 | Remote callback, self-execution exception mapping and nullable superseding ballot response. |
| `PaxosRequestCallback` | Shared Paxos self-execution helper。 | Maps `WriteTimeoutException` to `TIMEOUT`, others to `UNKNOWN`; null response returns without callback；实现位于 `src/java/org/apache/cassandra/service/paxos/PaxosRequestCallback.java`。 |
| `Verb` | Paxos v2 verb id/stage/timeout/serializer/handler registry。 | Refresh and commit-and-prepare use `writeTimeout` and `MUTATION` stage. |

## 核心接口与数据结构

- `PaxosCommitAndPrepare.Request` extends `PaxosPrepare.AbstractRequest` and adds `Commit.Agreed commit`; serializer writes `Agreed` first and then prepare request body，见 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:58-115`。
- `PaxosPrepareRefresh.Request` carries promised ballot and missing committed value; `Response` carries nullable `isSupersededBy` ballot，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:142-161`。
- `PaxosPrepareRefresh.Callbacks` has `onRefreshFailure(...)` and `onRefreshSuccess(...)`; `PaxosPrepare` implements both，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:66-70`、`src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:861-886`。
- `PAXOS2_PREPARE_REFRESH_REQ/RSP` and `PAXOS2_COMMIT_AND_PREPARE_REQ/RSP` register serializers, handlers and response pairs in `src/java/org/apache/cassandra/net/Verb.java:190-195`。

## 生命周期

```text
Incomplete committed path
  -> Paxos.begin()
  -> prepare.awaitUntil(...)
  -> FOUND_INCOMPLETE_COMMITTED
  -> PaxosCommitAndPrepare.commitAndPrepare(...)
  -> Message.out(PAXOS2_COMMIT_AND_PREPARE_REQ, request)
  -> PaxosPrepare.start(...)
  -> recipient RequestHandler.execute()
     -> isInRangeAndShouldProcess(...)
     -> PaxosState.get(commit)
     -> state.commit(commit)
     -> PaxosPrepare.RequestHandler.execute(request, state)
```

```text
Incomplete accepted path
  -> Paxos.begin()
  -> FOUND_INCOMPLETE_ACCEPTED
  -> PaxosPropose.propose(...)
  -> proposeResult SUCCESS
  -> PaxosCommitAndPrepare.commitAndPrepare(repropose.agreed(), ...)
```

```text
Prepare refresh path
  -> PaxosPrepare.onResponse(...)
  -> withLatest + needLatest reaches consensus quorum
  -> haveReadResponseWithLatest
  -> refreshStaleParticipants()
  -> PaxosPrepareRefresh.refresh(needLatest)
     -> remote: sendWithCallback(PAXOS2_PREPARE_REFRESH_REQ)
     -> self: PAXOS2_PREPARE_REFRESH_REQ.stage.execute(executeOnSelf)
  -> RequestHandler.execute()
     -> range gate
     -> state.commit(missingCommit)
     -> latestWitnessedOrLowBound()
     -> Response(superseding ballot or null)
  -> PaxosPrepare.onRefreshSuccess(...)
```

## 配置项

| 配置 | 影响 | 证据 |
|---|---|---|
| `paxos_variant` | Enables v2 Paxos flow using commit-and-prepare/refresh verbs。 | `conf/cassandra.yaml:1594-1602`、`src/java/org/apache/cassandra/config/Config.java:1089` |
| `cas_contention_timeout` | CAS retry/contention deadline around begin/propose/commit loop。 | `conf/cassandra.yaml:1325-1329`、`src/java/org/apache/cassandra/config/Config.java:150` |
| `write_request_timeout` | Paxos v2 refresh and commit-and-prepare verbs use `writeTimeout` registry。 | `src/java/org/apache/cassandra/net/Verb.java:190-195`、`conf/cassandra.yaml:1306-1310` |
| `paxos_state_purging` | Affects Paxos state low-bound visibility and cleanup semantics around incomplete state。 | `conf/cassandra.yaml:1628-1646`、`src/java/org/apache/cassandra/config/Config.java:1091-1094` |
| `paxos_repair_enabled` | Controls Paxos repair/topology repair, adjacent to incomplete state cleanup。 | `src/java/org/apache/cassandra/config/Config.java:1096-1100` |

## Metrics And Logs

- `Paxos.begin()` increments `casWriteMetrics.unfinishedCommit` / `casReadMetrics.unfinishedCommit` when it finds incomplete accepted state before reproposal，见 `src/java/org/apache/cassandra/service/paxos/Paxos.java:999-1005`。
- `PaxosCommitAndPrepare.commitAndPrepare()` traces commit ballot and new prepare ballot，见 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:51-55`。
- `PaxosPrepareRefresh.refresh()` logs/traces refresh target, missing commit and promised ballot，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:81-102`。
- `PaxosPrepareRefresh.executeOnSelf()` logs local non-timeout exceptions as `Failed to apply paxos refresh-prepare locally`，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:125-132`。
- `PaxosPrepare.onRefreshSuccess()` logs success vs superseded response and then signals prepare outcome，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:867-886`。

## 运维关注点

| 场景 | 判断 | 操作线索 |
|---|---|---|
| CAS write times out around commit phase | Existing dtests drop `PAXOS2_COMMIT_AND_PREPARE_REQ` and expect `CasWriteTimeoutException`。 | Treat as Paxos uncertainty; serial reads/repair cleanup may finish incomplete state. |
| Repeated prepare refresh | Prepare quorum contains stale participants missing latest commit。 | Look for refresh traces; high frequency suggests commit visibility instability across quorum. |
| Commit-and-prepare range gate failure | Recipient should not process the partition/table from that sender. | Direct handler returns null and remote sees `UNKNOWN`; current tests do not directly exercise this branch. |
| Refresh returns superseding ballot | A higher ballot was witnessed after missing commit was applied. | `PaxosPrepare` either permits stable read or marks prepare superseded. |
| Local refresh timeout | Self-execution `WriteTimeoutException` maps to refresh failure `TIMEOUT`。 | Current source path is clear, but no direct fault-injection test proves it. |

## 性能瓶颈

- Commit-and-prepare saves one RTT but serializes both `Agreed commit` and prepare request in one verb; large updates increase payload and serializer cost，见 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:97-115`。
- Prepare refresh adds extra writes to stale participants before prepare can finish as promised/read-permitted; heavy refresh frequency can amplify CAS latency，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:617-635`。
- Self-execution still runs on the Paxos verb stage; local slow commit/read can consume the same timeout path as remote failures，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:100-135`。
- Handler direct branch tests are valuable because message-drop dtests do not prove commit-before-prepare ordering under local exceptions or range-gate nulls.

## 常见故障

| 故障 | 触发点 | 处理线索 |
|---|---|---|
| CAS timeout after incomplete commit | `PAXOS2_COMMIT_AND_PREPARE_REQ` dropped or failed before quorum response. | Serial read / subsequent CAS / Paxos repair can complete or clean state; see distributed baseline. |
| Unknown failure from Paxos v2 handler | Range gate returned null and handler responded failure `UNKNOWN`。 | Check ownership/range/table metadata and sender endpoint. |
| Refresh failure with TIMEOUT | Local self-execution threw `WriteTimeoutException` or remote callback failed with timeout. | Inspect write timeout, Paxos stage pressure and system.paxos/storage latency. |
| Refresh superseded by higher ballot | `latestWitnessedOrLowBound()` after commit is greater than promised ballot. | Coordinator retries/supersedes; high contention may be driving ballot churn. |
| Research checker gap fails | New direct handler/simulator test likely landed. | Update `coordination_paxos_direct_handler_test_gap` and cite the new test. |

## 测试用例

| 区域 | 已有测试 | 仍需补的专项测试 |
|---|---|---|
| Commit phase message loss | `test/distributed/org/apache/cassandra/distributed/test/CasWriteTest.java` drops `PAXOS2_COMMIT_AND_PREPARE_REQ` and expects CAS timeout. | Direct `PaxosCommitAndPrepare.RequestHandler` range-gate null / commit-before-prepare ordering test. |
| Paxos read/write drop matrix | `test/distributed/org/apache/cassandra/distributed/test/CASTest.java` includes `PAXOS2_PREPARE_REFRESH_REQ` and `PAXOS2_COMMIT_AND_PREPARE_REQ` in `paxosAndReadVerbs()`. | Direct prepare refresh superseded ballot and local timeout test. |
| Paxos cleanup/reproposal race | `test/distributed/org/apache/cassandra/distributed/test/PaxosRepairTest.java` drops `PAXOS_COMMIT_REQ` and `PAXOS2_COMMIT_AND_PREPARE_REQ` during cleanup race. | Simulator/direct handler matrix for refresh range-gate null and commit-and-prepare unknown response. |
| Paxos unit state tests | Unit tests cover state/propose/repair/uncommitted components, but not these two direct handlers. | Handler-level unit tests around `RequestHandler.execute(...)` and self-execution exception mapping. |

第六轮结论：Paxos v2 direct-fault 的 source contracts、distributed drop baseline 和 direct handler test gaps 已拆开；仍未实现 direct handler/simulator 专项测试。
