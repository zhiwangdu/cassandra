# Module: Coordination Hints/Batchlog Backlog Drift Checker

## 范围

`research/tools/check-coordination-hints-batchlog-backlog-drift.py` 是 `research/module-coordination-hints-batchlog-backlog-matrix.md` 的 source/test/gap drift checker。它保护 hints admission/backpressure、hint window/size limits、dispatch pause/retry/resume、encoded/decoded dispatch boundary、orphan conversion/excise/transfer、batchlog replay paging/throttle、hints fsync before batchlog delete、metrics observability 和当前 distributed-test 缺口。

当前基线：

- `StorageProxy.shouldHint()` 和 `HintsService.write()` source-backed admission/backpressure 已记录，`HintsMaxSizeTest` 覆盖 max per-host hints size。
- `HintsServiceTest`、`HintsStoreTest`、`HintedHandoffNodetoolTest`、`HintsServiceMetricsTest` 覆盖 pause/resume、page retry/seek、expired/pending hints info、handoff controls 和 metrics。
- `HintsDispatcher` same-version encoded path and decoded compatibility path are source-backed; serializer/reader/legacy fixtures exist, but no mixed-version dispatch dtest is present.
- `BatchlogManager` replay writes hints and fsyncs them before deleting replayed rows; `BatchlogManagerTest` covers replay counts, but no distributed replaybatchlog + listpendinghints/backlog test is present.

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `coordination_hints_write_admission_backpressure` | `StorageProxy` hint admission, in-flight overload and `HintsService.write()` durable write entry. |
| `coordination_hints_window_size_limits` | max hint window, persistent window, per-host size cap and max-size distributed baseline. |
| `coordination_hints_dispatch_pause_retry_resume` | scheduled trigger, pause/resume, page retry and dispatch offset seek. |
| `coordination_hints_dispatch_encoded_decoded_boundary` | `HintsDispatcher` encoded fast path vs decoded compatibility path and outcome metrics. |
| `coordination_hints_orphan_convert_excise_transfer` | orphan conversion, excise cleanup and transfer hints behavior. |
| `coordination_hints_operator_surface_gap` | covered handoff controls and current absence of distributed `listpendinghints` / `truncatehints` assertions. |
| `coordination_batchlog_replay_paging_throttle` | replay age filter, page-size calculation and per-endpoint throttle. |
| `coordination_batchlog_replay_hints_fsync_delete` | replay timeout/failure writes hints, fsyncs hints and then deletes batchlog rows. |
| `coordination_hints_batchlog_metrics_observability` | hints success/failure/timeout/delay metrics, pending hints info and batchlog counters. |
| `coordination_mixed_version_hints_dispatch_gap` | current absence of real mixed-version hints dispatch coverage. |
| `coordination_large_logged_batch_backlog_gap` | current absence of large logged batch replay/hints backlog distributed matrix. |
| `coordination_existing_hints_batchlog_tests_baseline` | existing unit/distributed tests anchoring the matrix. |

## 设计目标

- Fail when source contracts for durable hint admission, dispatch retry, metrics, batchlog replay or nodetool surfaces move without updating the matrix.
- Fail when a new distributed test lands for documented gaps so the matrix can stop calling them missing.
- Keep the durable backlog lifecycle separate from the broader Paxos/Counter/Hints/Batchlog fault runbook.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-coordination-hints-batchlog-backlog-drift.py` | Source/test/gap drift checker. |
| `StorageProxy` | Hint admission, overload and in-flight metrics. |
| `HintsService` | Durable write facade, dispatch control, pending info, delete/excise/transfer and fsync. |
| `HintsStore` | Descriptor queue, dispatch offset, expiration cache and pending info. |
| `HintsDispatchExecutor` | Dispatch loop, partial failure retry and orphan conversion. |
| `HintsDispatcher` | Encoded/decoded send path and per-page metrics. |
| `BatchlogManager` | Replay scanner, throttling, timeout-to-hints and fsync-before-delete ordering. |
| `HintedHandoffNodetoolTest` / `HintsServiceMetricsTest` / `HintsMaxSizeTest` / `BatchlogManagerTest` | Existing coverage baseline. |

## 运维关注点

- A green checker means source/test/gap claims match this checkout; it does not mean mixed-version hints dispatch or large logged batch backlog tests exist.
- If distributed `listpendinghints` or `truncatehints` coverage lands, update `coordination_hints_operator_surface_gap`.
- If a mixed-version hints dispatch dtest lands, update `coordination_mixed_version_hints_dispatch_gap` and cite the test.
- If replaybatchlog + pending hints or large logged batch backlog distributed tests land, update `coordination_batchlog_replay_hints_fsync_delete` and `coordination_large_logged_batch_backlog_gap`.

## 常见故障

- `source token contract ... StorageProxy.java` fails: hint admission/backpressure source moved.
- `source token contract ... HintsDispatchExecutor.java` fails: retry offset or orphan conversion semantics moved.
- `source token contract ... BatchlogManager.java` fails: replay paging/throttle or fsync-before-delete ordering moved.
- `gap still open ...` fails: new test coverage has appeared and the matrix needs to be rewritten.

## 运行方式

- `python3 research/tools/check-coordination-hints-batchlog-backlog-drift.py`
- `python3 research/tools/check-coordination-hints-batchlog-backlog-drift.py --json`
- Related validation: `python3 -m py_compile research/tools/check-coordination-hints-batchlog-backlog-drift.py`
