# Coordination Hints And Batchlog Backlog Matrix

## 范围

本文是 Paxos/Counter/Hints/Batchlog 第五轮补充中的 hints/batchlog durable backlog 专项矩阵，聚焦：

- 写路径如何决定是否写 hint、如何限流/限大小、如何避免 transient replica hint。
- `HintsService`、`HintsStore`、`HintsDispatchExecutor`、`HintsDispatcher` 的 durable file lifecycle、pause/resume、retry offset、orphan conversion 和 encoded/decoded dispatch。
- `BatchlogManager` replay 如何分页、限速、等待 delivery、把失败转为 hints，并在 hints fsync 后删除 `system.batches` row。
- 当前 tests 已覆盖的 handoff controls、metrics、max size、hint window、batchlog replay 单测，以及仍缺的 mixed-version hints dispatch、batchlog replay + pending hints observability、large logged batch replay/hints backlog distributed matrix。

前置主线见 `module-coordination-lwt-counter-hints.md`、`module-coordination-lwt-counter-hints-internals.md`、`module-coordination-lwt-counter-hints-deep-dive.md`、`module-coordination-fault-coverage-runbook.md` 和 `flow-hints-batchlog.md`。本矩阵由 `research/tools/check-coordination-hints-batchlog-backlog-drift.py` 保护，checker 说明文档是 `research/module-coordination-hints-batchlog-backlog-drift-checker.md`。

## Drift Checker Scenarios

| 场景 ID | 覆盖语义 |
|---|---|
| `coordination_hints_write_admission_backpressure` | `StorageProxy.shouldHint()`、`checkHintOverload()`、`HintsService.write()`、`StorageMetrics.totalHints/totalHintsInProgress`。 |
| `coordination_hints_window_size_limits` | `max_hint_window`、persistent hint window、`max_hints_size_per_host` 和 max-size distributed baseline。 |
| `coordination_hints_dispatch_pause_retry_resume` | scheduled dispatch、pause/resume、page failure offset、retry same page and delete on success。 |
| `coordination_hints_dispatch_encoded_decoded_boundary` | same-version encoded path vs decoded compatibility path, callback outcomes and metrics。 |
| `coordination_hints_orphan_convert_excise_transfer` | orphan target conversion to RF hints, node excise cleanup and decommission transfer-hints boundary。 |
| `coordination_hints_operator_surface_gap` | nodetool handoff controls covered; `listpendinghints`/`truncatehints` distributed assertions still absent。 |
| `coordination_batchlog_replay_paging_throttle` | replay age filter、page-size calculation、per-endpoint throttle and replay task serialization。 |
| `coordination_batchlog_replay_hints_fsync_delete` | replay timeout/failure writes hints, fsyncs generated hints, then deletes batchlog rows。 |
| `coordination_hints_batchlog_metrics_observability` | hints success/failure/timeout/delay metrics, pending hints info and batchlog replay counters。 |
| `coordination_mixed_version_hints_dispatch_gap` | mixed-version dispatch dtest absent: descriptor version differs from target messaging version during real dispatch。 |
| `coordination_large_logged_batch_backlog_gap` | large logged batch replay + hints backlog distributed matrix absent。 |
| `coordination_existing_hints_batchlog_tests_baseline` | HintsService/Store/Reader/Upgrade/MaxSize/Nodetool/Metrics/BatchlogManager tests currently anchoring this matrix。 |

## 设计目标

- 把 “hints backlog” 拆成 admission、durable file、dispatch、operator control、metrics 和 batchlog replay conversion 六个层次。
- 明确 batchlog replay failure 不是静默丢弃：未投递 mutation 会写 hints，且源码要求 hints fsync 后才删除 replayed batch rows。
- 区分 encoded fast path 与 decoded compatibility path：单元测试覆盖 serializer/reader/fixtures，但真实 mixed-version dispatch dtest 仍是缺口。
- 把 operator runbook 从源码接口落到测试缺口：pause/resume/DC enable-disable 有 distributed nodetool test，`listpendinghints`/`truncatehints` 仍只有 source/JMX surface。

## 解决的问题

| 问题 | 结论 | 证据 |
|---|---|---|
| hint 是否会对所有失败 replica 写入 | 否。`shouldHint()` 过滤全局/按 DC 禁用、transient replica、本机、非 ring endpoint、hint window 超时和 per-host size cap。 | `src/java/org/apache/cassandra/service/StorageProxy.java:2423-2498` |
| hints backlog 大时如何保护写路径 | `checkHintOverload()` 用 `StorageMetrics.totalHintsInProgress` 和 per-destination in-progress 计数抛 `OverloadedException`；`max_hints_size_per_host` 进一步停止为超额 host 写新 hints。 | `src/java/org/apache/cassandra/service/StorageProxy.java:1585-1598`、`src/java/org/apache/cassandra/service/StorageProxy.java:2488-2498` |
| dispatch 失败是否从文件开头重发 | 不一定。失败时记录 `dispatcher.dispatchPosition()`，descriptor 放回队头，下次从 saved offset seek；unit `HintsServiceTest.testPageSeek()` 覆盖 offset。 | `src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:283-325`、`test/unit/org/apache/cassandra/hints/HintsServiceTest.java:155-175` |
| mixed-version hints 是否已有端到端 dispatch 覆盖 | 没有。source 选择 decoded path，`HintsUpgradeTest` 覆盖 legacy fixture 读取，但没有 distributed/upgrade test 让 descriptor messaging version 与 target version 不同并实际 dispatch。 | `src/java/org/apache/cassandra/hints/HintsDispatcher.java:126-140`、`test/unit/org/apache/cassandra/hints/HintsUpgradeTest.java:108-160` |
| batchlog replay 失败后何时删除 `system.batches` row | replay 写出 hints 后，`HintsService.flushAndFsyncBlockingly(hintedNodes)` 先 fsync，随后才 `BatchlogManager.remove()` replayed rows。 | `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:312-316`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:420-445` |
| operator 是否有完整 distributed CLI coverage | 部分有。`disablehandoff`/`enablehandoff`、`disablehintsfordc`/`enablehintsfordc`、`pausehandoff`/`resumehandoff`、hinted handoff throttle 有 dtest；`listpendinghints`、`truncatehints`、`replaybatchlog` 与 pending hints 联合观测仍无 distributed CLI test。 | `test/distributed/org/apache/cassandra/distributed/test/HintedHandoffNodetoolTest.java:80-129` |

## 设计取舍

- Hints write admission 在 coordinator 写路径做早期过滤和 overload check，避免生成无法投递的 durable backlog；代价是 `shouldHint()` 依赖 gossip downtime、host id、per-host on-disk size 和 endpoint snitch 状态，见 `src/java/org/apache/cassandra/service/StorageProxy.java:2423-2498`。
- Hints dispatch 每 10 秒触发一次，降低 mean time to delivery，也会让 metrics/retry 更频繁；pause/resume 只控制 dispatch，不影响 future hints admission，见 `src/java/org/apache/cassandra/hints/HintsService.java:217-246`。
- Same-version encoded path 避免 decode/encode，mixed-version path 必须 decode 成 `Hint` 再按目标 version serialize，见 `src/java/org/apache/cassandra/hints/HintsDispatcher.java:126-140`。
- Orphan hints conversion 在目标 host id 不再有 endpoint 时，把每条 hint 转成该 mutation 的当前 replicas hints；这避免直接丢弃，但可能把一个 host backlog 扩散到 RF targets，见 `src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:270-280`、`src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:327-338`。
- Batchlog replay 每 page 等待 unfinished batches，再把未投递 endpoints 转 hints；这保留 logged batch 语义，但 backlog 会从 `system.batches` 转移到 hints files，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:260-317`。

## 核心类

| 类 | 责任 | 关键边界 |
|---|---|---|
| `StorageProxy` | 写路径 hint admission、hint overload、CL ANY hint response、in-progress metrics。 | `sendToHintedReplicas()`、`shouldHint()`、`submitHint()`。 |
| `HintsService` | MBean、durable write facade、flush/fsync、dispatch start/pause/resume、pending info、delete/excise/transfer。 | shut down 后拒绝新 hint；`flushAndFsyncBlockingly()` 是 batchlog replay 删除前置条件。 |
| `HintsStore` | 每个 host id 的 descriptor queue、corrupted queue、dispatch positions、expiration cache、current writer。 | `markDispatchOffset()`、`deleteExpiredHints()`、`getPendingHintsInfo()`、`getTotalFileSize()`。 |
| `HintsDispatchExecutor` | per-store dispatch loop、success delete、failure offset retry、orphan conversion。 | pause stops loop；partial failure offers descriptor back to queue head。 |
| `HintsDispatcher` | 读取 page，按 descriptor/target messaging version 选择 encoded 或 decoded send path。 | page 内 callbacks 全部 await，failure/timeout aborts current file。 |
| `BatchlogManager` | `system.batches` store/remove/replay、page-size/rate-limit、timeout 转 hints。 | generated hints fsync before deleting replayed rows。 |
| `NodeProbe` / nodetool hints commands | `statushandoff`、enable/disable、pause/resume、list/truncate、throttle、batchlog replay。 | source surface 完整，distributed CLI coverage 不完整。 |

## 核心接口

| 接口 | 用途 | 证据 |
|---|---|---|
| `HintsServiceMBean` | pause/resume/delete/list pending hints。 | `src/java/org/apache/cassandra/hints/HintsServiceMBean.java:23-52` |
| `StorageServiceMBean`/`NodeProbe` hints methods | handoff enable/disable、DC allowlist、max hint window/size、in-progress count。 | `src/java/org/apache/cassandra/service/StorageProxy.java:2372-2420`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1039-1115` |
| `BatchlogManagerMBean` | count all batches、total replayed、force replay。 | `src/java/org/apache/cassandra/batchlog/BatchlogManagerMBean.java:20-37` |
| nodetool commands | operator CLI。 | `src/java/org/apache/cassandra/tools/nodetool/ReplayBatchlog.java`、`src/java/org/apache/cassandra/tools/nodetool/ListPendingHints.java`、`src/java/org/apache/cassandra/tools/nodetool/TruncateHints.java`、`src/java/org/apache/cassandra/tools/nodetool/PauseHandoff.java`、`src/java/org/apache/cassandra/tools/nodetool/ResumeHandoff.java`、`src/java/org/apache/cassandra/tools/nodetool/EnableHintsForDC.java`、`src/java/org/apache/cassandra/tools/nodetool/DisableHintsForDC.java`、`src/java/org/apache/cassandra/tools/nodetool/StatusHandoff.java`、`src/java/org/apache/cassandra/tools/nodetool/SetHintedHandoffThrottleInKB.java`。 |

## 核心数据结构

- `HintsStore.dispatchDequeue`：待发送 descriptors queue；`corruptedFiles` 保存损坏文件；`dispatchPositions` 保存 descriptor -> first undelivered page offset，见 `src/java/org/apache/cassandra/hints/HintsStore.java:60-78`。
- `PendingHintsInfo`：host id、total files、oldest/newest timestamp，`listpendinghints` 输出使用其 map 形态，见 `src/java/org/apache/cassandra/hints/HintsStore.java:107-125` 和 `src/java/org/apache/cassandra/hints/HintsService.java:296-313`。
- `HintMessage.Encoded`：same-version dispatch 的 raw hint buffer + version wrapper；接收端不会反序列化为 encoded type，而是普通 `HintMessage`，见 `src/java/org/apache/cassandra/hints/HintMessage.java:170-190`。
- `BatchlogManager.ReplayingBatch`：batch id、writtenAt、mutation list、serialized size、replay handlers；`finish()` 根据 handler failure/timeout 写 hints，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:337-390`。
- `StorageMetrics.totalHintsInProgress` / `hintsInProgress`：全局和 per-endpoint in-flight hint admission pressure，见 `src/java/org/apache/cassandra/service/StorageProxy.java:2705-2828`。

## 生命周期

```text
Write failure hint admission
  -> StorageProxy.sendToHintedReplicas()
  -> checkHintOverload(destination)
  -> shouldHint(destination)
     -> global/DC enabled
     -> full non-self ring replica
     -> max hint window / persistent oldest hint
     -> max_hints_size_per_host
  -> submitHint()
  -> HintsService.write()
  -> HintsBufferPool / HintsStore writer
  -> StorageMetrics.totalHints increment
```

```text
Hints dispatch
  -> HintsService.startDispatch()
  -> HintsDispatchTrigger every 10s
  -> HintsDispatchExecutor.DispatchHintsTask
  -> store.poll()
  -> HintsDispatcher.create(file, target messaging version)
  -> seek saved offset if any
  -> dispatch pages
     -> same version ? sendEncodedHint : sendHint
     -> wait callbacks and update metrics
  -> success: store.delete + cleanUp
  -> failure: markDispatchOffset + offerFirst
```

```text
Batchlog replay
  -> nodetool replaybatchlog / scheduled task
  -> BatchlogManager.startBatchlogReplay()
  -> replayFailedBatches()
     -> age limit = now - batchlog timeout
     -> calculate page size by system.batches mean row size
     -> set per-endpoint replay throttle
  -> processBatchlogEntries()
     -> ReplayingBatch.replay()
     -> finish page and write hints for failures/timeouts
     -> HintsService.flushAndFsyncBlockingly(hintedNodes)
     -> BatchlogManager.remove(replayed rows)
```

## 配置项

| 配置 | 影响 | 证据 |
|---|---|---|
| `hinted_handoff_enabled` | 全局 future hints admission。 | `conf/cassandra.yaml:68`、`src/java/org/apache/cassandra/config/Config.java:112` |
| `hinted_handoff_disabled_datacenters` | DC 级 hints 禁用。 | `conf/cassandra.yaml:70-72`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3554-3577` |
| `max_hint_window` | endpoint down 超过窗口后停止 hint。 | `conf/cassandra.yaml:80`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3579-3586` |
| `max_hints_size_per_host` | per-host on-disk size cap；0 disabled。 | `conf/cassandra.yaml:111`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3589-3602` |
| `hints_directory` | hints durable files location and directory collision checks。 | `conf/cassandra.yaml:97`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:644-751` |
| `max_hints_file_size` | writer rollover size。 | `conf/cassandra.yaml:106`、`src/java/org/apache/cassandra/config/Config.java:446-447` |
| `max_hints_delivery_threads` | dispatch executor concurrency。 | `conf/cassandra.yaml:93`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3707-3710` |
| `auto_hints_cleanup_enabled` | expired/corrupt hints cleanup scheduling。 | `conf/cassandra.yaml:115`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3732-3739` |
| `transfer_hints_on_decommission` | decommission transfer hints behavior。 | `conf/cassandra.yaml:120`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3742-3749` |
| `batchlog_replay_throttle` | replay KiB/s; source scales per endpoint。 | `conf/cassandra.yaml:157`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:229-247` |

## Metrics

| Metric | 更新点 | 用途 |
|---|---|---|
| `StorageMetrics.totalHints` | `HintsService.write()` and test counters。 | 观察已创建 hint 数。 |
| `StorageMetrics.totalHintsInProgress` | `StorageProxy.submitHint()` inc，`HintRunnable.finally` dec。 | admission pressure / overload。 |
| `HintsServiceMetrics.HintsSucceeded` | `HintsDispatcher.updateMetrics()`。 | dispatch success page totals。 |
| `HintsServiceMetrics.HintsFailed` | `HintsDispatcher.updateMetrics()`。 | dispatch failure totals。 |
| `HintsServiceMetrics.HintsTimedOut` | `HintsDispatcher.updateMetrics()`。 | dispatch timeout totals。 |
| `HintsService.Hint_delays` | `HintsServiceMetrics.updateDelayMetrics()`。 | hint delivery delay histogram。 |
| `BatchlogManager.getTotalBatchesReplayed()` | `finishAndClearBatches()` / empty replay rows。 | replay throughput and backlog drain。 |
| `BatchlogManager.countAllBatches()` | `system.batches` count。 | current durable batchlog backlog。 |

`HintsServiceMetricsTest` injects HINT_REQ failure/timeout and asserts success/failure/timeout/delay metrics,见 `test/distributed/org/apache/cassandra/distributed/test/metrics/HintsServiceMetricsTest.java:63-149`。

## 日志

- `HintsService.pauseDispatch()` / `resumeDispatch()` log paused/resumed dispatch,见 `src/java/org/apache/cassandra/hints/HintsService.java:232-246`。
- Dispatch success logs `Finished hinted handoff of file ...` and partial failure logs `partially` after marking offset，见 `src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:296-325`。
- Corrupted hint file marks descriptor corrupted and rethrows `FSReadError`，见 `src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java:257-263`。
- `BatchlogManager.replayFailedBatches()` logs start/finish and no-peer cancellation；replay failure logs trace then writes hints，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:200-226`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:372-387`。
- Max hints size rejection is trace-only in `StorageProxy.shouldHint()`，so production diagnosis usually needs metrics + on-disk size rather than only logs，见 `src/java/org/apache/cassandra/service/StorageProxy.java:2488-2498`。

## 运维关注点

| 场景 | 动作 | 源码依据 |
|---|---|---|
| Hints delivery should pause but writes continue | Use `nodetool pausehandoff`; confirm `HintsService.isDispatchPaused()` or status. | `src/java/org/apache/cassandra/hints/HintsService.java:232-246`、`test/distributed/org/apache/cassandra/distributed/test/HintedHandoffNodetoolTest.java:108-120` |
| Hints backlog needs inspection | Use `nodetool listpendinghints` for host id/file count/oldest/newest; supplement with `getTotalHintsSize()` for bytes. | `src/java/org/apache/cassandra/tools/nodetool/ListPendingHints.java:37-95`、`src/java/org/apache/cassandra/hints/HintsService.java:296-313` |
| Bad destination should be removed from hints | `truncatehints` deletes all or per endpoint without snapshots; use only when replay is no longer needed. | `src/java/org/apache/cassandra/tools/nodetool/TruncateHints.java:27-40`、`src/java/org/apache/cassandra/hints/HintsService.java:316-353` |
| Hints files persist after node removal | `HintsService.excise()` flushes, closes writer, interrupts dispatch and excises store. | `src/java/org/apache/cassandra/hints/HintsService.java:356-401` |
| Batchlog backlog drains into hints | Check `BatchlogManager.countAllBatches()` and pending hints together; replay can legitimately reduce system.batches while increasing hints files. | `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:260-317` |
| Hints exceed per-host budget | `max_hints_size_per_host` stops future hints only after size is over cap, so small overshoot is expected. | `src/java/org/apache/cassandra/service/StorageProxy.java:2488-2498`、`test/distributed/org/apache/cassandra/distributed/test/HintsMaxSizeTest.java:84-117` |

## 性能瓶颈

- Hint admission overload is global + per-target. A hot failed endpoint can block hint creation for that endpoint without stopping writes to healthy endpoints, but CL ANY depends on hint completion semantics,见 `src/java/org/apache/cassandra/service/StorageProxy.java:1462-1474`、`src/java/org/apache/cassandra/service/StorageProxy.java:1585-1598`。
- Same-version hints dispatch avoids decode/encode; mixed-version dispatch adds CPU and allocation by reading `page.hintsIterator()`，见 `src/java/org/apache/cassandra/hints/HintsDispatcher.java:126-140`。
- Dispatch page failure retries at page granularity. Large pages plus repeated HINT_REQ timeouts can inflate success counts because already-delivered hints in the page may be retried，见 `test/unit/org/apache/cassandra/hints/HintsServiceTest.java:134-153` 和 `test/distributed/org/apache/cassandra/distributed/test/metrics/HintsServiceMetricsTest.java:120-129`。
- Batchlog replay page size shrinks when `system.batches` mean row size grows; large logged batches therefore reduce page parallelism and can prolong backlog，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:250-258`。
- Replay throttle is divided by endpoint count. In larger rings, the per-endpoint replay rate can be much lower than configured aggregate throttle，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:235-247`。

## 常见故障

| 故障 | 触发点 | 处理线索 |
|---|---|---|
| `Too many in flight hints` | `totalHintsInProgress > maxHintsInProgress` and destination already has hints in progress. | Lower write pressure, recover target, or adjust max hints in progress via MBean only with care. |
| Hints not created for down node | disabled handoff/DC, transient/self replica, endpoint not in ring, hint window expired, or per-host size cap exceeded. | Check `statushandoff`、disabled DCs、max hint window、`max_hints_size_per_host` and `HintsService.getTotalHintsSize()`。 |
| Hints file keeps retrying | Page has failure/timeout; dispatch offset is saved and descriptor returned to queue head. | Inspect `HintsServiceMetrics.HintsFailed` / `HintsTimedOut`; target may flap or HINT_REQ is filtered. |
| Hints target host id no longer maps to endpoint | Dispatch converts each hint to current RF replicas with `writeForAllReplicas()`. | Expect backlog to move to other host ids instead of disappearing. |
| Batchlog count drops while hints grow | Replay timed out/failure wrote hints and fsynced them before deleting batchlog rows. | Treat as backlog relocation; inspect pending hints, not only `system.batches`。 |
| `listpendinghints`/`truncatehints` behavior regression | Source commands exist, but no distributed CLI test currently asserts their stdout/mutation behavior. | `coordination_hints_operator_surface_gap` remains open. |

## 测试用例

| 区域 | 已有测试 | 仍需补的专项测试 |
|---|---|---|
| Handoff controls | `HintedHandoffNodetoolTest` covers status, enable/disable, DC enable/disable, pause/resume and throttle. | Distributed `listpendinghints` and `truncatehints` stdout/effect assertions. |
| Hint dispatch retry | `HintsServiceTest.testPauseAndResume()`、`testPageRetry()`、`testPageSeek()` cover paused delivery, page retry and dispatch offset. | Distributed HINT_REQ timeout + `listpendinghints`/metrics runbook test. |
| Max hints size/window | `HintsMaxSizeTest` covers `max_hints_size_per_host`; `AbstractHintWindowTest` helpers cover total size, pause and transfer primitives used by subclasses (`test/distributed/org/apache/cassandra/distributed/test/AbstractHintWindowTest.java`). | Combined per-host size cap + persistent hint window + restart matrix. |
| Hints metrics | `HintsServiceMetricsTest` covers HINT_REQ success/failure/timeout and delay histograms. | Mixed-version decoded dispatch metrics. |
| Hints encoding/fixtures | `HintMessageTest`、`HintsReaderTest`、`HintsUpgradeTest` cover encoded serializer, raw/decoded iterator and legacy fixture reads. | Mixed-version hints dispatch dtest with descriptor version different from target messaging version. |
| Batchlog replay | `BatchlogManagerTest.testReplay()` covers count/replay of expired rows. | Distributed replaybatchlog + listpendinghints + timeout-to-hints backlog assertion. |
| Large logged batch backlog | `OversizedMutationTest` covers `max_mutation_size`; `MixedModeLoggedBatchTest` covers mixed-version logged batch store timeout. | Large logged batch replay/hints backlog matrix across warn/fail/mutation-size/replay-timeout. |

Additional source-backed test anchors: `test/distributed/org/apache/cassandra/distributed/test/HintedHandoffAddRemoveNodesTest.java` covers bootstrap with hints outstanding and hints success metrics; `test/distributed/org/apache/cassandra/distributed/test/AbstractHintWindowTest.java` provides shared hint-window primitives used by subclasses.
