# Module: Topology Operations Coverage Drift Checker

## 范围

`research/tools/check-topology-operations-coverage-drift.py` 是 topology operations test matrix 的 source-to-doc drift checker。本说明文件是 `research/module-topology-operations-coverage-drift-checker.md`。它保护 `research/module-topology-operations-test-matrix.md` 中关于真实 nodetool/JMX、simulator topology action、distributed/unit coverage 和剩余缺口的判断，重点覆盖 replacement、removenode/transient、rebuild source allow-list/error matrix、assassinate 边界和 simulator Paxos topology repair。

当前基线：

- Real replacement coverage comes from hostreplacement distributed tests using `ClusterUtils.replaceHostAndStart()` and `REPLACE_ADDRESS_FIRST_BOOT`.
- Cross-DC replacement remains a targeted test gap: current cross-DC distributed coverage is `UpdateSystemAuthAfterDCExpansionTest`, which exercises system_auth expansion/removeNode/contraction rather than replacement.
- Removenode transient restore is source-backed in `StorageService.restoreReplicaCount()` and unit-backed by `MoveTransientTest`; no distributed removenode transient replication test is present.
- Rebuild source controls are source-backed by `StorageService.rebuild()` and `RangeStreamer` source filters; distributed tests cover rebuild success/observability but not `--sources`, non-owned explicit ranges or concurrent rebuild errors.
- Simulator topology actions cover JOIN/LEAVE/REPLACE/CHANGE_RF and Paxos topology repair, but not real nodetool argument handling or replacement shadow gossip.

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `topology_replacement_real_path` | `StorageService.prepareForReplacement()`、replacement token validation、live replacement failure、ClusterUtils replacement helper 和 hostreplacement dtests。 |
| `topology_replacement_cross_dc_gap` | Current absence of a distributed test that combines `replaceHostAndStart` with multi-DC/NTS setup. |
| `topology_simulator_topology_actions` | Simulator JOIN/LEAVE/REPLACE/CHANGE_RF actions, topology validator and Paxos repair. |
| `topology_removenode_transient_restore_contract` | `restoreReplicaCount()` preserves remote full/transient identity and request ranges separately. |
| `topology_removenode_transient_dtest_gap` | Current absence of distributed removenode transient replication coverage. |
| `topology_rebuild_source_filter_contract` | `SingleDatacenterFilter`、`ExcludeLocalDatacenterFilter`、`AllowedSourcesFilter` and rebuild argument/error contracts. |
| `topology_rebuild_distributed_error_gap` | Current absence of distributed rebuild allow-list/error coverage for `--sources`, non-owned ranges and concurrent rebuild. |
| `topology_nodetool_jmx_surface` | nodetool move/removenode/rebuild/assassinate and `NodeProbe` JMX bridge. |
| `topology_assassinate_replacement_boundary` | Assassinate as last resort and hostreplacement assassinated boundary tests. |
| `topology_tests_coverage_baseline` | HostReplacement, Move, Remove, MoveTransient, RebuildStreaming, StorageService rebuild errors and UpdateSystemAuth test anchors. |

## 设计目标

- Keep the matrix honest about what is covered by real distributed tests, what is covered only by unit/simulator/source, and what remains missing.
- Fail when new test coverage appears for a documented gap so the matrix can be updated instead of continuing to call it missing.
- Fail when nodetool/JMX or `StorageService` rebuild/removenode/replacement contracts move without research updates.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-topology-operations-coverage-drift.py` | Source/doc/test-gap drift checker. |
| `StorageService` | replacement、rebuild、removenode restore、force remove and topology Paxos repair service-side contracts. |
| `RangeStreamer` | Rebuild/bootstrap/move source filter and strict consistency source selection. |
| `ClusterUtils` | Distributed replacement/add instance/abrupt shutdown/nodetool ring helper. |
| `KeyspaceActions` / `OnCluster*` | Simulator topology operation selection and action bodies. |
| `PaxosTopologyChangeVerifier` | Simulator topology correctness oracle. |
| `Move` / `RemoveNode` / `Rebuild` / `Assassinate` | nodetool argument surface. |
| `NodeProbe` | nodetool to JMX bridge. |

## 运维关注点

- A green checker does not mean topology tests are complete; it means the current source/test coverage and explicit gaps are still documented.
- If a true cross-DC replacement dtest lands, `topology_replacement_cross_dc_gap` should move from gap to covered scenario.
- If a removenode transient replication dtest lands, `topology_removenode_transient_dtest_gap` should be rewritten with the new test as evidence.
- If rebuild distributed error tests land for `--sources`, non-owned ranges or concurrent rebuild, `topology_rebuild_distributed_error_gap` should be replaced by those anchors.

## 常见故障

- `source token contract ... StorageService.java` fails: replacement/rebuild/removenode restore source behavior changed.
- `source token contract ... RangeStreamer.java` fails: source filter or strict consistency error contract changed.
- `gap still open ...` fails: a new distributed test appears for a documented gap and the research matrix needs updating.
- `doc token ...` fails: protected docs lost a source path, test anchor, scenario ID or explicit gap statement.

## 运行方式

- `python3 research/tools/check-topology-operations-coverage-drift.py`
- `python3 research/tools/check-topology-operations-coverage-drift.py --json`
- Related validation: `python3 -m py_compile research/tools/check-topology-operations-coverage-drift.py`
