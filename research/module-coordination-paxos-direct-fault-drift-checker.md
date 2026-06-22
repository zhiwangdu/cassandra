# Module: Coordination Paxos Direct-Fault Drift Checker

## 范围

`research/tools/check-coordination-paxos-direct-fault-drift.py` 是 `research/module-coordination-paxos-direct-fault-matrix.md` 的 source/test/gap drift checker。它保护 Paxos v2 commit-and-prepare entry/message/handler ordering、prepare-refresh trigger/self-failure/superseded response、existing distributed drop baselines and current absence of direct handler/simulator tests。

当前基线：

- `Paxos.begin()` enters `PaxosCommitAndPrepare.commitAndPrepare()` for incomplete committed state and for reproposed incomplete accepted state.
- `PaxosCommitAndPrepare.RequestHandler.execute()` range-gates, commits missing `Agreed`, and then runs `PaxosPrepare.RequestHandler.execute(...)`; null response maps to `UNKNOWN` failure.
- `PaxosPrepare.refreshStaleParticipants()` constructs `PaxosPrepareRefresh`; refresh self-execution maps `WriteTimeoutException` to `TIMEOUT` and other exceptions to `UNKNOWN`.
- `PaxosPrepareRefresh.RequestHandler.execute()` commits missing value and returns nullable superseding ballot; `PaxosPrepare.onRefreshSuccess()` turns that into `READ_PERMITTED` or `SUPERSEDED`.
- Existing distributed tests drop `PAXOS2_COMMIT_AND_PREPARE_REQ` and include `PAXOS2_PREPARE_REFRESH_REQ` in Paxos/read drop matrices, but no direct handler test is present.

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `coordination_paxos_commit_prepare_entry` | Incomplete committed/accepted Paxos paths enter commit-and-prepare. |
| `coordination_paxos_commit_prepare_message_contract` | Commit-and-prepare request/serializer/verb contract. |
| `coordination_paxos_commit_prepare_handler_order` | Range gate, commit-before-prepare ordering and null-response failure. |
| `coordination_paxos_commit_prepare_range_gate_gap` | Current absence of direct range-gate/null-response test. |
| `coordination_paxos_prepare_refresh_trigger` | `PaxosPrepare` needLatest refresh trigger. |
| `coordination_paxos_prepare_refresh_self_failure` | Self-execution timeout/unknown mapping. |
| `coordination_paxos_prepare_refresh_superseded` | Nullable superseding ballot response and callback outcome. |
| `coordination_paxos_prepare_refresh_range_gate_gap` | Current absence of refresh range-gate/local-timeout/superseded direct tests. |
| `coordination_paxos_existing_drop_tests_baseline` | Existing distributed drop/cleanup race tests. |
| `coordination_paxos_direct_handler_test_gap` | Current absence of handler-level tests for these branches. |

## 设计目标

- Fail when source contracts for commit-and-prepare or prepare-refresh move without updating the matrix.
- Fail when direct handler/simulator tests land so the matrix stops calling those cases missing.
- Keep distributed message-drop coverage separate from branch-level handler coverage.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-coordination-paxos-direct-fault-drift.py` | Source/test/gap drift checker. |
| `Paxos` | Entry points from incomplete committed/accepted state into commit-and-prepare. |
| `PaxosCommitAndPrepare` | Combined commit + prepare request, serializer and handler. |
| `PaxosPrepare` | Prepare quorum state, needLatest tracking and refresh callback handling. |
| `PaxosPrepareRefresh` | Missing commit refresh, self-execution, response and serializer. |
| `PaxosRequestCallback` | Shared self-execution exception mapping. |
| `Verb` | Paxos v2 verb registration. |
| `CasWriteTest` / `CASTest` / `PaxosRepairTest` | Existing distributed drop baseline. |

## 运维关注点

- A green checker means the current source/test/gap claims still match this checkout; it does not prove handler branches are covered.
- If direct handler tests land, update `coordination_paxos_direct_handler_test_gap` and cite the new test.
- If commit-and-prepare ordering changes, update both the lifecycle and performance/fault sections before changing source tokens.
- If prepare-refresh self-execution stops mapping `WriteTimeoutException` to `TIMEOUT`, update the failure semantics and runbook language.

## 常见故障

- `source token contract ... PaxosCommitAndPrepare.java` fails: combined request, serializer, range-gate or commit-before-prepare behavior moved.
- `source token contract ... PaxosPrepareRefresh.java` fails: refresh callback, self-execution or superseded response behavior moved.
- `source token contract ... PaxosPrepare.java` fails: needLatest refresh trigger or callback outcome changed.
- `gap still open ...` fails: direct handler/simulator coverage likely appeared and the matrix must be rewritten.
- `doc token ...` fails: protected source/test/gap language or scenario IDs disappeared.

## 运行方式

- `python3 research/tools/check-coordination-paxos-direct-fault-drift.py`
- `python3 research/tools/check-coordination-paxos-direct-fault-drift.py --json`
- Related validation: `python3 -m py_compile research/tools/check-coordination-paxos-direct-fault-drift.py`
