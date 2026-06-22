# Module: Topology Operations Runtime Error Drift Checker

## 范围

`research/tools/check-topology-operations-runtime-error-drift.py` 是 topology operations runtime error matrix 的 source/test/gap drift checker。本说明文件是 `research/module-topology-operations-runtime-error-drift-checker.md`。它保护 `research/module-topology-operations-runtime-error-matrix.md` 中关于 replacement shadow gossip/live-node guard、removenode transient restore/force boundary、rebuild source filters/argument errors/stream failure wrapping 和当前 distributed-test 缺口的判断。

当前基线：

- Replacement runtime evidence comes from `StorageService.prepareForReplacement()` and hostreplacement distributed tests; cross-DC replacement remains a targeted distributed gap.
- Removenode transient restore is source-backed by `getNewSourceReplicas()`、`LeavingReplica` and `restoreReplicaCount()`; `MoveTransientTest` covers range math/source filters, but no distributed removenode transient test is present.
- Rebuild runtime errors are source-backed by `Rebuild.execute()`、`StorageService.rebuild()` and `RangeStreamer` source filters; distributed tests cover success and generic stream failure, not `--sources`、non-owned ranges or concurrent rebuild.
- The checker deliberately fails if new distributed tests appear for documented gaps so the matrix can be rewritten from gap to covered scenario.

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `topology_runtime_replacement_shadow_gossip` | `prepareForReplacement()` shadow gossip, snitch validation, tokens extraction and token conflict validation. |
| `topology_runtime_replacement_live_node_guard` | live replacement failure and `HostReplacementTest` assertion. |
| `topology_runtime_replacement_cross_dc_gap` | Current absence of `replaceHostAndStart` plus multi-DC/NTS distributed coverage. |
| `topology_runtime_removenode_restore_identity` | `LeavingReplica` and removenode restore full/transient request separation. |
| `topology_runtime_removenode_force_boundary` | `forceRemoveCompletion()` last-resort/no-restore boundary. |
| `topology_runtime_removenode_transient_gap` | Current absence of distributed removenode transient replication coverage. |
| `topology_runtime_rebuild_source_filters` | `SingleDatacenterFilter`、`ExcludeLocalDatacenterFilter`、`AllowedSourcesFilter` and strict source errors. |
| `topology_runtime_rebuild_argument_errors` | rebuild local DC/exclude-local, unknown DC, token/keyspace, range ownership, local/unknown sources and concurrent guard. |
| `topology_runtime_rebuild_stream_failure_wrap` | rebuild stream failure wrapping and `StreamPrepareFailTest`. |
| `topology_runtime_existing_test_baseline` | Existing distributed/unit anchors for replacement, cross-DC removeNode, transient unit math, rebuild success/errors. |
| `topology_runtime_distributed_error_gap` | Current absence of distributed rebuild allow-list/error and removenode transient tests. |

## 设计目标

- Keep runtime error claims aligned with exact source strings and test anchors.
- Protect the distinction between source/unit coverage and real distributed nodetool/JMX coverage.
- Treat newly introduced distributed tests for currently missing scenarios as a documentation drift event.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-topology-operations-runtime-error-drift.py` | Source/doc/test-gap drift checker. |
| `StorageService` | replacement preparation, removenode restore, force remove and rebuild runtime errors. |
| `RangeStreamer` | source filters and strict source failure messages used by rebuild/bootstrap/move. |
| `RangeRelocator` | transient full/source movement boundary for move/removenode-related math. |
| `Rebuild` | nodetool rebuild argument surface. |
| `HostReplacementTest` | live/down replacement distributed assertions. |
| `UpdateSystemAuthAfterDCExpansionTest` | cross-DC removeNode baseline that is not replacement/transient RF coverage. |
| `MoveTransientTest` | transient source/filter unit baseline. |
| `RebuildStreamingTest` | distributed rebuild success and `system_views.streaming` baseline. |
| `StreamPrepareFailTest` | distributed stream failure baseline. |

## 运维关注点

- A green checker does not mean the missing dtests exist; it means the research correctly states they are missing for this checkout.
- If a true cross-DC replacement dtest lands, update `topology_runtime_replacement_cross_dc_gap` and remove the negative gap expectation.
- If a removenode transient distributed test lands, update `topology_runtime_removenode_transient_gap` and include the new test as evidence.
- If rebuild distributed error tests land for `--sources`, non-owned ranges, unknown/local sources or concurrent rebuild, update `topology_runtime_distributed_error_gap`.

## 常见故障

- `source token contract ... StorageService.java` fails: replacement, removenode restore or rebuild error strings/control flow changed.
- `source token contract ... RangeStreamer.java` fails: source filters or strict-source failure strings changed.
- `gap still open ...` fails: a new distributed test appears for a documented gap and the matrix needs to be rewritten.
- `doc token ...` fails: protected docs lost a source path, scenario ID or explicit gap statement.

## 运行方式

- `python3 research/tools/check-topology-operations-runtime-error-drift.py`
- `python3 research/tools/check-topology-operations-runtime-error-drift.py --json`
- Related validation: `python3 -m py_compile research/tools/check-topology-operations-runtime-error-drift.py`
