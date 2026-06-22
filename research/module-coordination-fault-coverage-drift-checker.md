# Module: Coordination Fault Coverage Drift Checker

## 范围

`research/tools/check-coordination-fault-coverage-drift.py` 是 `research/module-coordination-fault-coverage-runbook.md` 的 source/test/gap drift checker。它保护 Paxos v2 commit-and-prepare / prepare-refresh、counter tombstone、hints mixed-version dispatch、large logged batch replay 与 hints backlog 的当前结论。

当前基线：

- `PaxosCommitAndPrepare` 与 `PaxosPrepareRefresh` 源码边界已记录，`CasWriteTest`、`CASTest`、`PaxosRepairTest` 覆盖 message-drop / cleanup race；direct handler fault tests 仍是 gap still open。
- `CounterMutationTest.testDeletes()` 和 `CounterContextTest.testClearLocal()` 覆盖单 JVM counter tombstone / local shard 语义，`CountersTest.testEmptyContext()` 覆盖 distributed repaired metadata read；counter tombstone + repair/compaction distributed test 仍是 gap still open。
- `HintsDispatcher` 的 same-version encoded path 和 cross-version decoded path 有源码保护，`HintMessageTest.testEncodedSerializer()`、`HintsReaderTest`、`HintsUpgradeTest` 覆盖 serializer/reader/legacy fixtures；mixed-version dispatch dtest 仍是 gap still open。
- `BatchlogManager` replay、`BatchlogManagerMBean`、nodetool `ReplayBatchlog` / `ListPendingHints` / handoff controls 和 batch size guardrails 有源码保护；large logged batch replay/hints backlog distributed matrix 仍是 gap still open。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `coordination_paxos_commit_prepare_fault_boundary` | `PAXOS2_COMMIT_AND_PREPARE_REQ` source path, range-gate null response, commit-before-prepare ordering, and existing distributed drop coverage. |
| `coordination_paxos_prepare_refresh_fault_gap` | `PAXOS2_PREPARE_REFRESH_REQ` callbacks, local timeout mapping, superseding ballot response, and the current absence of direct handler tests. |
| `coordination_counter_tombstone_repair_compaction_gap` | Counter delete/unit coverage, empty-context distributed coverage, and the current absence of delete + repair + compaction distributed coverage. |
| `coordination_hints_encoded_decoded_dispatch_boundary` | `HintsDispatcher` same-version encoded vs decoded compatibility branch, metrics, and serializer/reader fixtures. |
| `coordination_hints_mixed_version_dispatch_gap` | Current absence of a distributed/upgrade hints dispatch test that changes target messaging version relative to the hints descriptor. |
| `coordination_batchlog_large_mutation_boundary` | Batch size warn/fail guardrails, `max_mutation_size`, logged batch transient rejection, and existing oversized/mixed-mode batch tests. |
| `coordination_batchlog_replay_hints_backlog_runbook` | `BatchlogManager` timeout replay, hints generation, hints fsync before row deletion, and MBean replay counters. |
| `coordination_operator_hints_batchlog_surface` | nodetool `replaybatchlog`, `listpendinghints`, handoff pause/resume/enable/disable/truncate and replay throttle commands. |
| `coordination_existing_tests_baseline` | Existing `CasWriteTest`, `CASTest`, `PaxosRepairTest`, `CounterMutationTest`, `CounterContextTest`, `CountersTest`, `HintMessageTest`, `HintsReaderTest`, `HintsUpgradeTest`, `OversizedMutationTest`, `MixedModeLoggedBatchTest`, and `BatchlogManagerTest` anchors. |

## 设计目标

- Fail when source contracts for Paxos refresh, counter merge/delete, hints dispatch, batchlog replay or operator command surfaces move without updating the runbook.
- Fail when a new test lands for a documented gap so the runbook can stop calling it missing.
- Keep covered baselines separate from targeted gaps: message-drop Paxos coverage is not the same as direct handler coverage, and hints legacy fixture reads are not the same as actual mixed-version dispatch.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-coordination-fault-coverage-drift.py` | Source/test/gap drift checker. |
| `PaxosCommitAndPrepare` | Combined commit + prepare request handler and null-response failure branch. |
| `PaxosPrepareRefresh` | Refresh callback, local execute timeout mapping and superseding ballot response. |
| `CounterMutation` / `CounterContext` | Counter hint boundary, read-before-write and tombstone/shard merge semantics. |
| `HintsDispatcher` / `HintMessage.Encoded` / `HintsReader` | Encoded fast path, decoded compatibility path and fixture/reader coverage. |
| `BatchlogManager` / `BatchlogManagerMBean` | Replay scanning, write-hints-on-failure, fsync-before-delete and replay counters. |
| `NodeProbe` / nodetool hint and batchlog commands | Operator JMX/CLI surface protected by the runbook. |

## 运维关注点

- A green checker means the research matches the current source and tests; it does not mean the gap tests have been implemented.
- If direct Paxos handler tests land, move `coordination_paxos_prepare_refresh_fault_gap` from gap to covered and cite the new test.
- If a counter delete + repair + compaction distributed test lands, replace `coordination_counter_tombstone_repair_compaction_gap` with the new evidence.
- If mixed-version hints dispatch or large logged batch replay/hints tests land, update both the runbook and checker absence predicates.

## 常见故障

- `source token contract ... PaxosCommitAndPrepare.java` fails: combined Paxos v2 commit/prepare behavior changed.
- `source token contract ... HintsDispatcher.java` fails: encoded/decoded dispatch branch or metrics moved.
- `gap still open ...` fails: new test coverage has appeared and the runbook must be rewritten.
- `doc token ...` fails: protected source/test/gap language or scenario IDs were removed from the research docs.

## 运行方式

- `python3 research/tools/check-coordination-fault-coverage-drift.py`
- `python3 research/tools/check-coordination-fault-coverage-drift.py --json`
- Related validation: `python3 -m py_compile research/tools/check-coordination-fault-coverage-drift.py`
