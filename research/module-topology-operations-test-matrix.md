# Topology Operations Test Matrix

## 范围

本文是 topology operations 第四轮补充，聚焦测试覆盖和运行路径差异矩阵：真实 nodetool/JMX 操作、simulator topology action、distributed/unit tests 分别覆盖了什么，以及跨 DC replacement、removenode/transient replication 与 rebuild source allow-list/error handling 的剩余缺口。运行时错误信息和 operator-facing failure surface 的专项矩阵见 `module-topology-operations-runtime-error-matrix.md`。主实现和 simulator 内部细节分别见 `module-topology-operations.md`、`module-topology-operations-internals.md` 和 `flow-topology-operations.md`。

## 设计目标

- 给每个拓扑操作建立“真实入口 -> 服务端入口 -> simulator 入口 -> 测试锚点 -> 未覆盖风险”的对照，避免把 simulator action 误解成真实 nodetool 端到端覆盖。
- 明确 replacement 的真实路径依赖 shadow gossip、replace address、token conflict、same-address/host-id/DNS 处理；这些不由 simulator replace action 直接覆盖，见 `src/java/org/apache/cassandra/service/StorageService.java:742-866` 和 `src/java/org/apache/cassandra/service/StorageService.java:3273-3355`。
- 明确 removenode/transient replication 目前主要由生产源码和 unit test 支撑；distributed test 有跨 DC removeNode/system_auth 流程，但缺少 transient replication distributed 场景，见 `src/java/org/apache/cassandra/service/StorageService.java:3651-3767` 和 `test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java:122-213`。
- 明确 rebuild source allow-list/error matrix：nodetool 只做 `tokens`/`keyspace` 的前置校验，`StorageService.rebuild()` 承担 source DC、exclude local DC、range ownership、specific sources、并发 rebuild、stream failure wrapping 和 finally reset，见 `src/java/org/apache/cassandra/tools/nodetool/Rebuild.java:54-64` 和 `src/java/org/apache/cassandra/service/StorageService.java:1515-1661`。
- 明确 CI/回归时优先跑哪些测试：host replacement tests、distributed move、TopologyChangeTest、RebuildStreamingTest、RemoveTest、MoveTransientTest 和 simulator Paxos topology tests。

## Drift Checker Scenarios

| 场景 ID | 覆盖语义 |
|---|---|
| `topology_replacement_real_path` | 真实 replacement 的 shadow gossip、replace address、live replacement failure、host id/same-address 以及 hostreplacement dtests。 |
| `topology_replacement_cross_dc_gap` | 跨 DC replacement 专项 distributed test 仍是缺口；当前跨 DC 证据来自 system_auth expansion/removeNode。 |
| `topology_simulator_topology_actions` | simulator JOIN/LEAVE/REPLACE/CHANGE_RF、topology validator 和 Paxos topology repair。 |
| `topology_removenode_transient_restore_contract` | removenode restore 保留 full/transient source identity 并分开 request ranges。 |
| `topology_removenode_transient_dtest_gap` | removenode transient replication distributed test 仍是缺口。 |
| `topology_rebuild_source_filter_contract` | rebuild source DC、exclude local DC、`--sources`、non-owned range、unknown host、concurrent rebuild 和 source filter contract。 |
| `topology_rebuild_distributed_error_gap` | rebuild `--sources`、non-owned explicit ranges、concurrent rebuild 的 distributed allow-list/error matrix 仍是缺口。 |
| `topology_nodetool_jmx_surface` | nodetool `move`/`removenode`/`rebuild`/`assassinate` 与 `NodeProbe` JMX bridge。 |
| `topology_assassinate_replacement_boundary` | assassinate before replacement 的 LEFT/gossip/token failure boundary。 |
| `topology_tests_coverage_baseline` | HostReplacement、Move、Remove、MoveTransient、RebuildStreaming、StorageService rebuild errors 和 UpdateSystemAuth test anchors。 |

这些场景由 `research/tools/check-topology-operations-coverage-drift.py` 保护；checker 还会在跨 DC replacement、removenode transient 或 rebuild allow-list/error distributed coverage 出现时失败，要求同步更新本矩阵。

## 解决的问题

- 真实 replacement 测试覆盖 down/live/seed-down/abrupt/full-cluster outage/assassinated/hybrid hibernating，但这些多是单 DC 或同拓扑 token replacement；跨 DC replacement 仍没有专项 distributed test，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementTest.java:65-207`、`test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementAbruptDownedInstanceTest.java:53-103`、`test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementOfDownedClusterTest.java:63-180`。
- simulator replace 覆盖的是 pending range、Paxos repair、bootstrap 和 gossip 状态组合；真实 replacement 还要走 `replace_address_first_boot` 和 shadow gossip，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterReplace.java:56-109` 和 `test/distributed/org/apache/cassandra/distributed/shared/ClusterUtils.java:254-272`。
- removenode distributed coverage 目前在 system_auth 跨 DC 扩缩容里出现：dc2 bootstrap、NTS RF 变更、repair、force shutdown、force conviction、`StorageService.instance.removeNode()`、去掉 dc2 RF，见 `test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java:122-213`。
- transient replication coverage 集中在 move/source selection unit tests：`RangeRelocator` 和 `RangeStreamer.calculateRangesToFetchWithPreferredEndpoints` 覆盖 full/transient fetch/stream、down nodes 与 source filters，见 `test/unit/org/apache/cassandra/service/MoveTransientTest.java:171-305` 和 `test/unit/org/apache/cassandra/service/MoveTransientTest.java:392-680`。
- rebuild source filtering 已能从源码完整还原：`SingleDatacenterFilter`、`ExcludeLocalDatacenterFilter`、`AllowedSourcesFilter` 分别对应 source DC、`--exclude-local-dc`、`--sources`，但 distributed tests 目前只覆盖 `rebuild --keyspace` 的成功 streaming/metrics，不覆盖 source allow-list 的失败矩阵，见 `src/java/org/apache/cassandra/dht/RangeStreamer.java:183-274` 和 `test/distributed/org/apache/cassandra/distributed/test/streaming/RebuildStreamingTest.java:43-90`。

## 设计取舍

- distributed tests 更接近真实 nodetool/JMX，但成本较高且多数场景不组合 transient replication；unit tests 能精准覆盖 range math/source filter，但不验证 gossip、streaming、JMX status 和 coordinator 可用性。
- simulator 能把 JOIN/LEAVE/REPLACE/CHANGE_RF 纳入 Paxos simulation 的随机调度，覆盖 pending topology 与线性化检查；代价是它绕过真实 nodetool 参数校验和 replacement 启动期 shadow gossip，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/KeyspaceActions.java:182-294`。
- replacement tests 通过 `BOOTSTRAP_SKIP_SCHEMA_CHECK` 降低 down/abrupt gossip 中旧 schema version 对测试的影响，这让 replacement 主行为可测，但不等于生产可以忽略 schema divergence，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementTest.java:88-93` 和 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementAbruptDownedInstanceTest.java:85-92`。
- removenode force/assassinate 都是危险路径：真实 nodetool 暴露 force completion 和 assassinate，但 simulator 没有模拟 operator force/assassinate 的端到端流程，见 `src/java/org/apache/cassandra/tools/nodetool/RemoveNode.java:27-49` 和 `src/java/org/apache/cassandra/tools/nodetool/Assassinate.java:29-46`。
- rebuild source control 是 operator-facing allow-list，而不是 replica placement override。`--sources` 只在指定 `--tokens` 的分支里解析并添加 `AllowedSourcesFilter`；最终仍由 `RangeStreamer` strict consistency/source filters 决定是否有足够 source，见 `src/java/org/apache/cassandra/service/StorageService.java:1577-1640` 和 `src/java/org/apache/cassandra/dht/RangeStreamer.java:148-274`。

## 核心类

| 类 | 覆盖意义 | 证据 |
|---|---|---|
| `StorageService` | replace/removenode/rebuild/move 的服务端核心；replacement shadow gossip 和 removenode transient restore 都在这里 | `src/java/org/apache/cassandra/service/StorageService.java:742-866`、`src/java/org/apache/cassandra/service/StorageService.java:3651-3836` |
| `RangeStreamer` | rebuild/bootstrap/move 的 source filter 与 fetch execution 核心；定义 source filters、计算 work map、按 remote full/transient 拆分 stream request | `src/java/org/apache/cassandra/dht/RangeStreamer.java:148-274`、`src/java/org/apache/cassandra/dht/RangeStreamer.java:345-378`、`src/java/org/apache/cassandra/dht/RangeStreamer.java:697-782` |
| `Move` / `RemoveNode` / `Rebuild` / `Assassinate` | 真实 nodetool 参数入口，映射到 `NodeProbe` | `src/java/org/apache/cassandra/tools/nodetool/Move.java:29-46`、`src/java/org/apache/cassandra/tools/nodetool/RemoveNode.java:27-49`、`src/java/org/apache/cassandra/tools/nodetool/Rebuild.java:27-64`、`src/java/org/apache/cassandra/tools/nodetool/Assassinate.java:29-46` |
| `ClusterUtils` | distributed tests 的 replacement/add instance/abrupt stop helper | `test/distributed/org/apache/cassandra/distributed/shared/ClusterUtils.java:126-140`、`test/distributed/org/apache/cassandra/distributed/shared/ClusterUtils.java:160-208`、`test/distributed/org/apache/cassandra/distributed/shared/ClusterUtils.java:254-272` |
| `KeyspaceActions` | simulator 中选择 JOIN/LEAVE/REPLACE/CHANGE_RF 并构造 before/during/after topology | `test/simulator/main/org/apache/cassandra/simulator/cluster/KeyspaceActions.java:182-294` |
| `OnClusterJoin` / `OnClusterLeave` / `OnClusterReplace` / `OnClusterChangeRf` | simulator operation bodies | `test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterJoin.java:36-49`、`test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterLeave.java:43-59`、`test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterReplace.java:56-109`、`test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterChangeRf.java:49-65` |
| `PaxosTopologyChangeVerifier` | simulator/Paxos history 的 topology correctness oracle | `test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosTopologyChangeVerifier.java:28-113` |

## 核心接口

- `StorageServiceMBean` 是真实 JMX 合同；nodetool 通过 `NodeProbe` 触发 `move`、`removeNode`、`forceRemoveCompletion`、`rebuild`，第一轮文档已列出接口主线。
- `NodeProbe.rebuild(sourceDc, keyspace, tokens, specificSources, excludeLocalDatacenterNodes)` 是 nodetool 到 JMX 的五参数入口，直接委托 `StorageServiceMBean.rebuild(...)`，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:1692-1695` 和 `src/java/org/apache/cassandra/service/StorageServiceMBean.java:852-878`。
- `Cluster.bootstrap(config)` 是 distributed tests 添加 replacement/new node 的入口；`ClusterUtils.addInstance()` 从 `cluster.newInstanceConfig()` 创建新节点并放入 network topology，见 `test/distributed/org/apache/cassandra/distributed/shared/ClusterUtils.java:160-208`。
- `Cluster.filters().allVerbs().to/from(...).drop()` 是 abrupt shutdown 的测试接口；它把双向消息 drop 掉再 `stopUnchecked`，模拟 kill -9，见 `test/distributed/org/apache/cassandra/distributed/shared/ClusterUtils.java:126-140`。
- simulator 的 `TopologyChangeValidator`/Paxos validators 是 correctness oracle；它们验证 action 前后 ballot 和 topology，而不是验证 nodetool 参数。

## 核心数据结构

- `Replacement test topology`：replacement helper 复制被替换节点配置、新建 instance、设置 `auto_bootstrap=true` 和 `REPLACE_ADDRESS_FIRST_BOOT`，见 `test/distributed/org/apache/cassandra/distributed/shared/ClusterUtils.java:254-272`。
- `LeavingReplica`：removenode restore 中同时保存 leaving replica 和本节点新 replica 的 full/transient 身份，见 `src/java/org/apache/cassandra/service/StorageService.java:3651-3692`。
- `replicasToFetch`：`restoreReplicaCount()` 按 keyspace/source 聚合 `FetchReplica`，再分别构造 full 和 transient request ranges，见 `src/java/org/apache/cassandra/service/StorageService.java:3704-3752`。
- `MoveTransientTest` 的 expected endpoints：单测显式期望 full replica 和 transient replica 都作为 source 或 target 参与 fetch/stream，见 `test/unit/org/apache/cassandra/service/MoveTransientTest.java:392-409` 和 `test/unit/org/apache/cassandra/service/MoveTransientTest.java:625-678`。
- `RangeStreamer.SourceFilter` family：`FailureDetectorSourceFilter` 排除 down nodes，`SingleDatacenterFilter` 只保留指定 DC，`ExcludeLocalDatacenterFilter` 排除 local DC，`ExcludeLocalNodeFilter` 排除本机，`AllowedSourcesFilter` 只允许指定 endpoint set，见 `src/java/org/apache/cassandra/dht/RangeStreamer.java:148-274`。
- `StreamRequest.full/transientReplicas`：stream request 保留 remote source 的 full/transient 身份，便于完成后写入可 resume 的 available ranges，见 `src/java/org/apache/cassandra/streaming/StreamRequest.java:45-63`、`src/java/org/apache/cassandra/streaming/StreamRequest.java:77-117`。
- `KeyspaceActions` before/during/after topology：simulator 用 `TokenMetadata.addReplaceTokens`、`addBootstrapTokens`、`addLeavingEndpoint`、`removeEndpoint` 生成 pending/natural snapshots，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/KeyspaceActions.java:209-283`。

## 生命周期

```text
Real replacement distributed test
  -> stop target node, sometimes abruptly or after whole-cluster outage
  -> ClusterUtils.replaceHostAndStart()
  -> add new instance from target config
  -> set REPLACE_ADDRESS_FIRST_BOOT
  -> startup enters StorageService.prepareForReplacement()
  -> bootstrap/streaming/ring convergence assertions
```

Replacement helper 入口见 `test/distributed/org/apache/cassandra/distributed/shared/ClusterUtils.java:254-272`；服务端 replacement 准备见 `src/java/org/apache/cassandra/service/StorageService.java:742-837`；down/live/full outage assertions 见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementTest.java:65-207` 和 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementOfDownedClusterTest.java:63-180`。

```text
Simulator topology action
  -> KeyspaceActions.next()
  -> choose DC and action
  -> mutate TokenMetadata for pending topology
  -> OnCluster* action performs gossip/schema/bootstrap/unbootstrap/repair
  -> topology verifier validates before/after
```

Action selection and token metadata mutation见 `test/simulator/main/org/apache/cassandra/simulator/cluster/KeyspaceActions.java:182-294`；operation bodies 见 `test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterJoin.java:36-49`、`test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterLeave.java:43-59`、`test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterReplace.java:56-109`。

```text
Real rebuild with source controls
  -> nodetool rebuild [src-dc] -ks <ks> -ts <ranges> -s <sources> --exclude-local-dc
  -> Rebuild.execute() rejects tokens without keyspace
  -> NodeProbe.rebuild(...)
  -> StorageService.rebuild(...)
     -> reject local source DC + exclude-local-dc
     -> reject unknown source DC
     -> reject concurrent rebuild
     -> build RangeStreamer(REBUILD)
     -> add SingleDatacenterFilter / ExcludeLocalDatacenterFilter / AllowedSourcesFilter
     -> parse token ranges and verify local ownership
     -> fetchAsync().get()
     -> wrap ExecutionException for JMX and reset isRebuilding
```

Rebuild command and JMX hop见 `src/java/org/apache/cassandra/tools/nodetool/Rebuild.java:27-64`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1692-1695`；服务端校验、filter 和 fetch path 见 `src/java/org/apache/cassandra/service/StorageService.java:1515-1661`；source filter definitions 见 `src/java/org/apache/cassandra/dht/RangeStreamer.java:148-274`。

```text
Cross-DC system_auth contraction test
  -> start dc1
  -> reject RF to dc2 before node exists
  -> bootstrap dc2 node
  -> alter NTS to include dc2
  -> repair system_auth
  -> force shutdown dc2 node and force FD conviction
  -> StorageService.removeNode(hostId)
  -> alter NTS to remove dc2
```

完整流程见 `test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java:122-213`。

## 调用链

- real move：`nodetool move` -> `Move.execute()` -> `NodeProbe.move()` -> `StorageService.move()`；distributed test 只验证 no-vnodes ring 上 `nodetoolResult("move", token)` 成功，见 `src/java/org/apache/cassandra/tools/nodetool/Move.java:35-45` 和 `test/distributed/org/apache/cassandra/distributed/test/MoveTest.java:49-91`。
- real removenode：`nodetool removenode status|force|ID` -> `RemoveNode.execute()` -> `NodeProbe.getRemovalStatus/forceRemoveCompletion/removeNode`；unit test 覆盖 bad/local/nonmember host id 和 replication done wait，见 `src/java/org/apache/cassandra/tools/nodetool/RemoveNode.java:33-49` 和 `test/unit/org/apache/cassandra/service/RemoveTest.java:108-179`。
- real rebuild：`nodetool rebuild [src-dc] --keyspace --tokens --sources --exclude-local-dc` -> `Rebuild.execute()` -> `NodeProbe.rebuild(...)`；distributed `RebuildStreamingTest` 验证 zero-copy/non-zero-copy 和 `system_views.streaming` 行，见 `src/java/org/apache/cassandra/tools/nodetool/Rebuild.java:27-64` 和 `test/distributed/org/apache/cassandra/distributed/test/streaming/RebuildStreamingTest.java:43-95`。
- rebuild fetch：`StorageService.rebuild()` -> `RangeStreamer.addRanges()` -> `calculateRangesToFetchWithPreferredEndpoints()`/optimized work map -> `RangeStreamer.fetchAsync()` -> split remaining ranges by remote full/transient -> `StreamPlan.requestRanges()` -> `StreamSession.addStreamRequest()`，见 `src/java/org/apache/cassandra/service/StorageService.java:1553-1645`、`src/java/org/apache/cassandra/dht/RangeStreamer.java:345-378`、`src/java/org/apache/cassandra/dht/RangeStreamer.java:697-782`、`src/java/org/apache/cassandra/streaming/StreamPlan.java:72-115`。
- real assassinate：`nodetool assassinate <ip>` -> `Assassinate.execute()` -> `NodeProbe.assassinateEndpoint()`；distributed assassinate cases 验证 LEFT 后 alter keyspace 或 replacement failure，见 `src/java/org/apache/cassandra/tools/nodetool/Assassinate.java:29-46`、`test/distributed/org/apache/cassandra/distributed/test/hostreplacement/AssassinateAbruptDownedNodeTest.java:30-58`、`test/distributed/org/apache/cassandra/distributed/test/hostreplacement/BaseAssassinatedCase.java:58-99`。
- simulator replace：`KeyspaceActions.next(REPLACE)` -> `TokenMetadata.addReplaceTokens` -> `OnClusterReplace` -> mark old node down -> repair old ranges -> set joining `BOOT_REPLACING` -> schema sync -> Paxos repair -> bootstrap replacing node -> set NORMAL，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/KeyspaceActions.java:209-231` 和 `test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterReplace.java:82-109`。

## 配置项

- Replacement distributed tests set `REPLACE_ADDRESS_FIRST_BOOT` through `ClusterUtils.replaceHostAndStart()`; it also lowers `BROADCAST_INTERVAL_MS`、`RING_DELAY`、`BOOTSTRAP_SCHEMA_DELAY_MS` to make tests finish in bounded time，见 `test/distributed/org/apache/cassandra/distributed/shared/ClusterUtils.java:261-270`。
- Some replacement tests set `BOOTSTRAP_SKIP_SCHEMA_CHECK` because down/abrupt nodes can leave old schema versions in gossip，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementTest.java:88-93` 和 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementAbruptDownedInstanceTest.java:85-92`。
- `MoveTest` explicitly disables vnodes and sets `paxos_variant=v2_without_linearizable_reads` before moving a single token node，见 `test/distributed/org/apache/cassandra/distributed/test/MoveTest.java:49-55`。
- `Rebuild` command enforces `--tokens` must be paired with `--keyspace` before calling `probe.rebuild(...)`，见 `src/java/org/apache/cassandra/tools/nodetool/Rebuild.java:54-64`。
- simulator topology CLI action set comes from `--cluster-actions` in `SimulationRunner` and is interpreted by `KeyspaceActions.next()`; operation eligibility depends on per-DC prejoin/joined size and min/max RF，见 `test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java:173-174` 和 `test/simulator/main/org/apache/cassandra/simulator/cluster/KeyspaceActions.java:195-204`。

| Rebuild source control | 行为 | 证据 |
|---|---|---|
| positional `src-dc-name` | source DC 存在性校验后映射为 `RangeStreamer.SingleDatacenterFilter` | `src/java/org/apache/cassandra/tools/nodetool/Rebuild.java:30-32`、`src/java/org/apache/cassandra/service/StorageService.java:1523-1531`、`src/java/org/apache/cassandra/service/StorageService.java:1562-1564` |
| `--exclude-local-dc` | 映射为 `RangeStreamer.ExcludeLocalDatacenterFilter`，且不能与 local source DC 同用 | `src/java/org/apache/cassandra/tools/nodetool/Rebuild.java:49-52`、`src/java/org/apache/cassandra/service/StorageService.java:1517-1521`、`src/java/org/apache/cassandra/service/StorageService.java:1565-1566` |
| `--tokens` | 必须配 `--keyspace`，且每段 token range 必须属于本节点 local replicas | `src/java/org/apache/cassandra/service/StorageService.java:1534-1537`、`src/java/org/apache/cassandra/service/StorageService.java:1577-1615` |
| `--sources` | 只在 explicit token-ranges 分支解析；拒绝本机/未知 host 后安装 `AllowedSourcesFilter` | `src/java/org/apache/cassandra/tools/nodetool/Rebuild.java:44-47`、`src/java/org/apache/cassandra/service/StorageService.java:1617-1638` |

### Rebuild source/error matrix

| 输入/状态 | 处理点 | 结果 | 当前测试锚点 |
|---|---|---|---|
| `--tokens` without `--keyspace` | `Rebuild.execute()` and `StorageService.rebuild()` both guard it | `IllegalArgumentException("Cannot specify tokens without keyspace.")` | `src/java/org/apache/cassandra/tools/nodetool/Rebuild.java:54-64`、`src/java/org/apache/cassandra/service/StorageService.java:1534-1537`、`test/unit/org/apache/cassandra/service/StorageServiceTest.java:347-358` |
| `src-dc-name` equals local DC with `--exclude-local-dc` | `StorageService.rebuild()` | `IllegalArgumentException("Cannot set source data center to be local data center...")` | `src/java/org/apache/cassandra/service/StorageService.java:1517-1521`、`test/unit/org/apache/cassandra/service/StorageServiceTest.java:314-325` |
| `src-dc-name` not in token metadata topology | `StorageService.rebuild()` | `IllegalArgumentException("Provided datacenter ... is not a valid datacenter...")` | `src/java/org/apache/cassandra/service/StorageService.java:1523-1531`、`test/unit/org/apache/cassandra/service/StorageServiceTest.java:328-344` |
| Another rebuild already running | `isRebuilding.compareAndSet(false, true)` | `IllegalStateException("Node is still rebuilding. Check nodetool netstats.")` | `src/java/org/apache/cassandra/service/StorageService.java:1539-1543` |
| explicit token range not owned by local node | range ownership loop over `getLocalReplicas(keyspace)` | `IllegalArgumentException("The specified range ... is not a range that is owned by this node...")` | `src/java/org/apache/cassandra/service/StorageService.java:1596-1615` |
| `--sources` contains local broadcast address | specific source parsing | `IllegalArgumentException("This host was specified as a source for rebuilding...")` | `src/java/org/apache/cassandra/service/StorageService.java:1617-1629` |
| `--sources` contains unknown host | `InetAddressAndPort.getByName` | `IllegalArgumentException("Unknown host specified ...")` | `src/java/org/apache/cassandra/service/StorageService.java:1623-1635` |
| source filters remove required strict sources | `RangeStreamer.calculateRangesToFetchWithPreferredEndpoints()` | `IllegalStateException("Necessary replicas for strict consistency were removed by source filters...")` | `src/java/org/apache/cassandra/dht/RangeStreamer.java:521`、`test/unit/org/apache/cassandra/service/MoveTransientTest.java:440-467` |
| streaming execution fails | `StreamResultFuture.get()` throws `ExecutionException` | full trace logged; JMX receives simplified `RuntimeException("Error while rebuilding node: ...")` | `src/java/org/apache/cassandra/service/StorageService.java:1643-1656`、`test/distributed/org/apache/cassandra/distributed/test/StreamPrepareFailTest.java:52-53` |
| success or failure | `finally` | `isRebuilding.set(false)` | `src/java/org/apache/cassandra/service/StorageService.java:1657-1661` |

## Metrics

- Replacement tests mostly assert data/ring convergence, not metrics; failed bootstrap coverage does check read/CAS read unavailable metrics do not increase during role setup retry, as already noted in internals doc.
- Rebuild distributed coverage validates `system_views.streaming` operation/status/progress/files/bytes, effectively using virtual table observability as the assertion surface，见 `test/distributed/org/apache/cassandra/distributed/test/streaming/RebuildStreamingTest.java:77-95`。
- Removenode unit test uses messaging callbacks (`REPLICATION_DONE_REQ`) and token metadata leaving endpoints as progress signal rather than production metrics，见 `test/unit/org/apache/cassandra/service/RemoveTest.java:141-179`。
- Simulator topology tests rely on validator failures, history failures and logs, not JMX metrics; `OnClusterChangeTopology` runs before/after validators and `PaxosTopologyChangeVerifier` checks ballot invariants，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterChangeTopology.java:32-70` 和 `test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosTopologyChangeVerifier.java:46-113`。

## 日志

- Full-cluster replacement tests assert gossip info generation/version and token metadata before starting replacement, which are more deterministic than parsing logs，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementOfDownedClusterTest.java:83-104`。
- Replacement helper and tests depend on ring assertions via nodetool ring parsing; `ClusterUtils.ring()` runs `nodetoolResult("ring")` and parses stdout，见 `test/distributed/org/apache/cassandra/distributed/shared/ClusterUtils.java:313-335`。
- Rebuild streaming test captures virtual table rows instead of parsing streaming logs，见 `test/distributed/org/apache/cassandra/distributed/test/streaming/RebuildStreamingTest.java:77-95`。
- Rebuild logs source DC/keyspace/token scope before fetch and logs full trace on execution failure, then throws a simplified JMX-facing exception，见 `src/java/org/apache/cassandra/service/StorageService.java:1545-1551`、`src/java/org/apache/cassandra/service/StorageService.java:1651-1656`。
- Assassinate tests assert thrown messages and LEFT gossip status; `BaseAssassinatedCase` waits until seed sees LEFT before replacement failure assertion，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/BaseAssassinatedCase.java:77-99`。

## 运维关注点

- Do not use simulator replace as evidence that `replace_address` startup will work. Simulator replace covers ownership and Paxos repair; real replacement must still pass shadow gossip/token conflict/live node/same-address checks,见 `src/java/org/apache/cassandra/service/StorageService.java:742-866` 和 `src/java/org/apache/cassandra/service/StorageService.java:3273-3355`。
- Cross-DC replacement remains a targeted test gap. The current cross-DC distributed test proves NTS/system_auth expansion and contraction with removeNode, not replacement in a different DC topology，见 `test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java:122-213`。
- Transient removenode remains a targeted distributed test gap. Production restore preserves full/transient source identity，unit tests validate transient movement math, but no distributed removenode transient scenario is present in the mapped tests，见 `src/java/org/apache/cassandra/service/StorageService.java:3730-3752` 和 `test/unit/org/apache/cassandra/service/MoveTransientTest.java:392-680`。
- Rebuild allow-list failures are source-code complete but not distributed-test complete. Existing distributed rebuild tests prove streaming success and observability, while unit tests cover three argument errors; missing distributed cases include `--sources` excluding all strict sources, explicit range not owned locally, local source in `--sources`, and concurrent rebuild guard，见 `test/distributed/org/apache/cassandra/distributed/test/streaming/RebuildStreamingTest.java:43-90`、`test/unit/org/apache/cassandra/service/StorageServiceTest.java:314-358`。
- Assassinate before replacement is explicitly dangerous. Tests show LEFT/non-normal state can make replacement fail with missing token or non-existing token messages，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/BaseAssassinatedCase.java:87-99` 和 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/AssassinatedEmptyNodeTest.java:35-61`。

## 性能瓶颈

- Replacement distributed tests can be slow because they perform node shutdown/startup, ring convergence, bootstrap streaming and data validation; helper deliberately lowers ring/schema delays to keep runtime bounded，见 `test/distributed/org/apache/cassandra/distributed/shared/ClusterUtils.java:261-270`。
- Move distributed coverage is narrow because real `nodetool move` is limited to no-vnodes/single-token scenarios，见 `test/distributed/org/apache/cassandra/distributed/test/MoveTest.java:49-78`。
- Transient range math has broad unit coverage because distributed transient removenode/move tests would multiply topology, streaming, RF and failure-detector cost；the unit coverage explicitly drives down-node and source-filter variants，见 `test/unit/org/apache/cassandra/service/MoveTransientTest.java:412-467` 和 `test/unit/org/apache/cassandra/service/MoveTransientTest.java:484-578`。
- Rebuild with transient replication disables the optimized work-map path because `RangeStreamer.addRanges()` falls back when strategy has transient replicas; this preserves strict source semantics at the cost of less optimized source selection，见 `src/java/org/apache/cassandra/dht/RangeStreamer.java:361-375`。
- Simulator topology action can explore many interleavings but does not pay real external process cost; it does pay action scheduling, Paxos repair and history checker cost, as covered in testing simulator docs.

## 常见故障

- Replacement of a live node should fail with `Cannot replace a live node`; distributed test asserts this explicitly，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementTest.java:110-146`。
- Abrupt shutdown keeps old node Normal in peer ring state until replacement progresses; test asserts peers see Normal before replacement and then validates rows after new node joins，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementAbruptDownedInstanceTest.java:76-103`。
- Whole-cluster outage replacement depends on seed retaining old node tokens/gossip info; tests assert token metadata is unchanged before replacement，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementOfDownedClusterTest.java:83-104`。
- Hibernating same-address replacement failure can block a later normal join with the same address; `NodeCannotJoinAsHibernatingNodeWithoutReplaceAddressTest` asserts `"already exists, cancelling join"`，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/NodeCannotJoinAsHibernatingNodeWithoutReplaceAddressTest.java:52-88`。
- Removenode bad/local/nonmember host ids fail before restore; successful unit path waits for all `REPLICATION_DONE_REQ` notifications，见 `test/unit/org/apache/cassandra/service/RemoveTest.java:108-179`。
- Rebuild source controls fail early for local source DC with `--exclude-local-dc`、unknown source DC、tokens without keyspace、local host in `--sources`、unknown `--sources` host and non-owned token range；streaming failures are logged and wrapped for JMX，见 `src/java/org/apache/cassandra/service/StorageService.java:1517-1661`。

## 测试用例

| 操作 | Distributed coverage | Unit/simulator coverage | 缺口 |
|---|---|---|---|
| Replacement | `HostReplacementTest` down/live/seed-down；`HostReplacementAbruptDownedInstanceTest` abrupt；`HostReplacementOfDownedClusterTest` outage；assassinated/hibernating cases | `StorageServiceServerTest.isReplacingSameHostAddressAndHostIdTest`；simulator `OnClusterReplace` | 跨 DC replacement 专项 dtest；replace 与 transient replication 组合 |
| Move | `MoveTest` no-vnodes nodetool move | `MoveTest` unit pending ranges；`MoveTransientTest` transient range/source filters | distributed transient move；vnodes 不适用 |
| Removenode | `UpdateSystemAuthAfterDCExpansionTest` 跨 DC removeNode/system_auth | `RemoveTest` host id/error/replication done；production transient restore source grouping | transient replication distributed removenode |
| Rebuild | `RebuildStreamingTest` zero-copy/non-zero-copy and `system_views.streaming` | source/error matrix in this doc；`StorageServiceTest` covers local DC exclusion、unknown DC、tokens without keyspace | distributed allow-list/error matrix for `--sources`、non-owned explicit ranges、concurrent rebuild |
| Assassinate | assassinated replacement cases and abrupt down alter-keyspace regression | Gossiper/StorageService state handling in internals doc | operator runbook and recovery matrix |
| Simulator topology | Paxos simulation runs JOIN/LEAVE/REPLACE/CHANGE_RF through `KeyspaceActions` | `PaxosTopologyChangeVerifier`, `PaxosRepairValidator` | Does not validate real nodetool/JMX argument surface |

Concrete tests:

- `TopologyChangeTest.testDecommission()` validates Java driver host state down/remove after nodetool decommission，见 `test/distributed/org/apache/cassandra/distributed/test/TopologyChangeTest.java:148-167`。
- `TopologyChangeTest.testRestartNode()` validates down/up events after shutdown/startup，见 `test/distributed/org/apache/cassandra/distributed/test/TopologyChangeTest.java:170-193`。
- `HostReplacementTest` replacement core cases，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementTest.java:65-207`。
- `MoveTest` real nodetool move smoke，见 `test/distributed/org/apache/cassandra/distributed/test/MoveTest.java:49-91`。
- `UpdateSystemAuthAfterDCExpansionTest`跨 DC expansion/removeNode/contraction，见 `test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java:122-213`。
- `MoveTransientTest` transient range math/source filter matrix，见 `test/unit/org/apache/cassandra/service/MoveTransientTest.java:171-305`、`test/unit/org/apache/cassandra/service/MoveTransientTest.java:392-680`。
- `StorageServiceTest` rebuild argument errors，见 `test/unit/org/apache/cassandra/service/StorageServiceTest.java:314-358`。
- `RebuildStreamingTest` rebuild success and streaming virtual table rows，见 `test/distributed/org/apache/cassandra/distributed/test/streaming/RebuildStreamingTest.java:43-95`。
