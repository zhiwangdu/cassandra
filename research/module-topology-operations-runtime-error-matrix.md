# Topology Operations Runtime Error Matrix

## 范围

本文是 topology operations 第六轮补充，聚焦真实运行路径上的错误边界和当前 distributed-test 缺口。它不替代 `module-topology-operations-test-matrix.md`，而是把 replacement、removenode transient restore 和 rebuild source controls 的异常语义单独拉成矩阵，便于后续实现专项 dtest 或排查生产操作失败。主实现仍在 `StorageService`、`RangeStreamer`、`RangeRelocator`、nodetool `Rebuild` 和 hostreplacement/removenode/rebuild tests 中。

## Drift Checker Scenarios

| 场景 ID | 覆盖语义 |
|---|---|
| `topology_runtime_replacement_shadow_gossip` | replacement 启动前必须通过 shadow gossip 找到被替换节点、校验 snitch、读取 tokens 并检测 token ownership conflict。 |
| `topology_runtime_replacement_live_node_guard` | live replacement 应抛出 `Cannot replace a live node...`，现有 hostreplacement dtest 只覆盖单 DC/同拓扑路径。 |
| `topology_runtime_replacement_cross_dc_gap` | 跨 DC replacement 专项 distributed test 仍为空；当前跨 DC 证据来自 system_auth expansion/removeNode。 |
| `topology_runtime_removenode_restore_identity` | `restoreReplicaCount()` 通过 `LeavingReplica`、`FetchReplica` 和 full/transient request sets 保留 remote source 身份。 |
| `topology_runtime_removenode_force_boundary` | `forceRemoveCompletion()` 是最后手段，源码明确不会继续 restore replicas。 |
| `topology_runtime_removenode_transient_gap` | removenode transient replication distributed test 仍为空；现有 transient 证据来自 unit range math/source filter。 |
| `topology_runtime_rebuild_source_filters` | `SingleDatacenterFilter`、`ExcludeLocalDatacenterFilter`、`AllowedSourcesFilter` 和 strict source errors 的源码合同。 |
| `topology_runtime_rebuild_argument_errors` | local source DC + exclude local、unknown DC、tokens without keyspace、non-owned range、local/unknown `--sources`、concurrent rebuild。 |
| `topology_runtime_rebuild_stream_failure_wrap` | rebuild streaming failure 通过 `ExecutionException` 被记录完整 trace，并向 JMX 返回简化 `RuntimeException`。 |
| `topology_runtime_existing_test_baseline` | `HostReplacementTest`、`UpdateSystemAuthAfterDCExpansionTest`、`MoveTransientTest`、`StorageServiceTest`、`RebuildStreamingTest`、`StreamPrepareFailTest` 当前覆盖边界。 |
| `topology_runtime_distributed_error_gap` | rebuild `--sources`、non-owned ranges、concurrent rebuild 和 removenode transient 的 distributed error coverage 仍是缺口。 |

这些场景由 `research/tools/check-topology-operations-runtime-error-drift.py` 保护；checker 还会在跨 DC replacement、removenode transient 或 rebuild allow-list/error distributed coverage 出现时失败，要求同步更新本矩阵。

## 设计目标

- 把 topology operation 的 runtime failure surface 从覆盖矩阵中拆出来，形成可直接映射到运维错误信息、JMX/nodetool 返回值和测试缺口的表。
- 区分三类证据：生产源码合同、unit/simulator 覆盖、真实 distributed/nodetool 覆盖。
- 在 checker 中保留“gap negative scan”：新 dtest 落地时让文档失败，而不是继续声明缺口。
- 给后续补测试提供最小场景清单：跨 DC replacement、removenode transient replication、rebuild `--sources`/explicit ranges/concurrent rebuild。

## Replacement Runtime Errors

| 运行阶段 | 处理点 | 错误/边界 | 当前测试锚点 | 缺口 |
|---|---|---|---|---|
| replacement 启动前 | `StorageService.prepareForReplacement()` | 已 bootstrap 的节点不能替换；`join_ring=false` 不能与 replacement 同用；unsafe replace 需要显式 property | `src/java/org/apache/cassandra/service/StorageService.java:742-754` | distributed tests 主要覆盖正常 replace，不覆盖所有 property 组合 |
| shadow gossip | `Gossiper.instance.doShadowRound()` 后读取 `EndpointState` | 被替换地址不在 gossip 中时抛 `Cannot replace_address %s because it doesn't exist in gossip` | `src/java/org/apache/cassandra/service/StorageService.java:756-764` | 多 DC gossip state 缺失场景未专项覆盖 |
| token 读取 | `ApplicationState.TOKENS` + `validateReplacementBootstrapTokens()` | 找不到 tokens 或 tokens 已被其他 endpoint 拥有时失败 | `src/java/org/apache/cassandra/service/StorageService.java:766-866` | cross-DC token/rack placement 下的 replacement conflict 未专项覆盖 |
| 空 gossip state escape hatch | `REPLACEMENT_ALLOW_EMPTY` | 允许基于 shadow round/system tables 线索继续，并临时 `initializeUnreachableNodeUnsafe()` | `src/java/org/apache/cassandra/service/StorageService.java:775-820` | 没有 multi-DC 空 state replacement dtest |
| live replacement | bootstrap prepare path | live 被替换节点会抛 `Cannot replace a live node...` | `src/java/org/apache/cassandra/service/StorageService.java:2171`、`test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementTest.java:110-146` | 当前是单 DC hostreplacement 证据 |
| 真实 helper | `ClusterUtils.replaceHostAndStart()` | 新 instance 复制被替换节点配置，设置 `REPLACE_ADDRESS_FIRST_BOOT` 后启动 | `test/distributed/org/apache/cassandra/distributed/shared/ClusterUtils.java:254-272` | `topology_runtime_replacement_cross_dc_gap`：没有 `replaceHostAndStart` + `NetworkTopologyStrategy`/dc2 的专项 dtest |

### Replacement 调用图

```text
ClusterUtils.replaceHostAndStart()
  -> new instance with replaced-node config
  -> set REPLACE_ADDRESS_FIRST_BOOT
  -> startup
  -> StorageService.prepareForReplacement()
     -> shadow gossip
     -> validate snitch and tokens
     -> validate live/dead replacement boundary during bootstrap
  -> bootstrap streaming
  -> ring/data assertions in hostreplacement tests
```

## Removenode Runtime Errors

| 运行阶段 | 处理点 | 错误/边界 | 当前测试锚点 | 缺口 |
|---|---|---|---|---|
| 参数校验 | `StorageService.removeNode(String hostIdString)` | host id not found、not a member、self remove、live node、already processing removal 都会在 restore 前失败 | `src/java/org/apache/cassandra/service/StorageService.java:5683-5708`、`test/unit/org/apache/cassandra/service/RemoveTest.java:108-179` | distributed removenode error matrix 较窄 |
| replica restore source selection | `getNewSourceReplicas()` | full target 只接受 full source；transient target 可接受 full/transient source；无 live source 时只 warn | `src/java/org/apache/cassandra/service/StorageService.java:3572-3621` | transient restore 没有 distributed 验证 |
| full/transient identity | `LeavingReplica` + `restoreReplicaCount()` | `LeavingReplica` 同时保存 leaving replica 和本节点新 replica；stream request 分成 full 和 transient ranges | `src/java/org/apache/cassandra/service/StorageService.java:3651-3752` | `topology_runtime_removenode_transient_gap` |
| restore failure | `StreamResultFuture.addCallback()` | failure 只 warn `Streaming to restore replica count failed`，仍发送 replication notification | `src/java/org/apache/cassandra/service/StorageService.java:3752-3765` | 缺少 failure-injection dtest 验证 coordinator 行为 |
| force remove | `forceRemoveCompletion()` | 最后手段；源码注释明确 `No further attempt will be made to restore replicas.` | `src/java/org/apache/cassandra/service/StorageService.java:5649-5672` | 需要 operator runbook/数据修复验证 |
| cross-DC contraction | `UpdateSystemAuthAfterDCExpansionTest` | dc2 bootstrap、NTS RF 变更、repair、force conviction、`removeNode()`、去掉 dc2 RF | `test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java:122-213` | 覆盖跨 DC removeNode，但不是 transient RF |

### Removenode 调用图

```text
nodetool removenode <hostId> or StorageService.removeNode(hostId)
  -> validate host id/member/self/live/concurrent removal
  -> mark endpoint leaving and advertise REMOVING
  -> restoreReplicaCount(endpoint, coordinator)
     -> getChangedReplicasForLeaving()
     -> getNewSourceReplicas()
     -> build StreamPlan(RESTORE_REPLICA_COUNT)
     -> request full and transient ranges separately
     -> notify coordinator on success or failure
  -> excise and advertise removed
```

## Rebuild Runtime Errors

| 输入/状态 | 处理点 | 结果 | 当前测试锚点 | distributed 缺口 |
|---|---|---|---|---|
| `--tokens` without `--keyspace` | `Rebuild.execute()` and `StorageService.rebuild()` | `IllegalArgumentException("Cannot specify tokens without keyspace.")` | `src/java/org/apache/cassandra/tools/nodetool/Rebuild.java:54-64`、`src/java/org/apache/cassandra/service/StorageService.java:1534-1537`、`test/unit/org/apache/cassandra/service/StorageServiceTest.java:347-358` | nodetool distributed negative case missing |
| local source DC + `--exclude-local-dc` | `StorageService.rebuild()` | `IllegalArgumentException("Cannot set source data center to be local data center...")` | `src/java/org/apache/cassandra/service/StorageService.java:1517-1521`、`test/unit/org/apache/cassandra/service/StorageServiceTest.java:314-325` | distributed negative case missing |
| unknown source DC | `TokenMetadata.Topology` validation | `IllegalArgumentException("Provided datacenter ... is not a valid datacenter...")` | `src/java/org/apache/cassandra/service/StorageService.java:1523-1531`、`test/unit/org/apache/cassandra/service/StorageServiceTest.java:328-344` | distributed negative case missing |
| concurrent rebuild | `isRebuilding.compareAndSet(false, true)` | `IllegalStateException("Node is still rebuilding. Check nodetool netstats.")` | `src/java/org/apache/cassandra/service/StorageService.java:1539-1543` | distributed concurrent case missing |
| source DC | `SingleDatacenterFilter` | only replicas in the named DC can be sources | `src/java/org/apache/cassandra/service/StorageService.java:1562-1564`、`src/java/org/apache/cassandra/dht/RangeStreamer.java:183-204` | multi-DC source selection negative case missing |
| `--exclude-local-dc` | `ExcludeLocalDatacenterFilter` | local DC replicas are removed from candidate sources | `src/java/org/apache/cassandra/service/StorageService.java:1565-1566`、`src/java/org/apache/cassandra/dht/RangeStreamer.java:210-231` | distributed source-exhaustion case missing |
| explicit token range not local-owned | range ownership loop | `IllegalArgumentException("The specified range %s is not a range that is owned by this node...")` | `src/java/org/apache/cassandra/service/StorageService.java:1577-1615` | distributed non-owned range case missing |
| `--sources` local address | specific source parsing | `IllegalArgumentException("This host was specified as a source for rebuilding...")` | `src/java/org/apache/cassandra/service/StorageService.java:1617-1629` | distributed negative case missing |
| `--sources` unknown host | `InetAddressAndPort.getByName()` | `IllegalArgumentException("Unknown host specified ...")` | `src/java/org/apache/cassandra/service/StorageService.java:1623-1635` | distributed negative case missing |
| `--sources` allow-list removes required strict source | `AllowedSourcesFilter` + strict source calculation | `Necessary replicas for strict consistency were removed by source filters...` or insufficient source errors | `src/java/org/apache/cassandra/dht/RangeStreamer.java:255-272`、`src/java/org/apache/cassandra/dht/RangeStreamer.java:520-591`、`test/unit/org/apache/cassandra/service/MoveTransientTest.java:440-578` | distributed `--sources` error case missing |
| streaming failure | `StreamResultFuture.get()` wrapped in `ExecutionException` | full trace logged; JMX receives `RuntimeException("Error while rebuilding node: ...")` | `src/java/org/apache/cassandra/service/StorageService.java:1643-1656`、`test/distributed/org/apache/cassandra/distributed/test/StreamPrepareFailTest.java:41-59` | existing dtest calls `StorageService.instance.rebuild(null)` rather than nodetool option matrix |
| success/failure cleanup | `finally` | `isRebuilding.set(false)` always resets guard | `src/java/org/apache/cassandra/service/StorageService.java:1657-1661` | distributed failure reset assertion missing |

### Rebuild 调用图

```text
nodetool rebuild [src-dc] -ks <ks> -ts <ranges> -s <sources> --exclude-local-dc
  -> Rebuild.execute()
     -> local tokens/keyspace guard
     -> NodeProbe.rebuild(...)
  -> StorageService.rebuild(...)
     -> source DC / exclude-local / unknown DC / concurrent guards
     -> RangeStreamer(REBUILD)
     -> add SingleDatacenterFilter / ExcludeLocalDatacenterFilter
     -> parse explicit token ranges and validate local ownership
     -> parse --sources and add AllowedSourcesFilter
     -> RangeStreamer.addRanges()
        -> calculateRangesToFetchWithPreferredEndpoints()
        -> strict source errors if filters remove required replicas
     -> fetchAsync().get()
     -> wrap streaming failure and reset isRebuilding
```

## Existing Test Baseline

| 测试 | 运行层 | 当前证明 |
|---|---|---|
| `HostReplacementTest` | distributed | down/live/seed-down replacement；live case asserts `Cannot replace a live node`。 |
| `HostReplacementAbruptDownedInstanceTest` | distributed | abrupt shutdown 后 replacement 仍能收敛并校验数据。 |
| `HostReplacementOfDownedClusterTest` | distributed | whole-cluster outage 后 seed retained tokens/gossip info 才能 replace。 |
| `UpdateSystemAuthAfterDCExpansionTest` | distributed | cross-DC system_auth expansion/removeNode/contraction，不是 replacement 或 transient RF。 |
| `MoveTransientTest` | unit | transient RF range math、full/transient source identity、down/source-filter errors。 |
| `StorageServiceTest` | unit | rebuild local DC exclusion、unknown DC、tokens without keyspace。 |
| `RebuildStreamingTest` | distributed | `nodetool rebuild --keyspace` success、zero-copy/non-zero-copy、`system_views.streaming`。 |
| `StreamPrepareFailTest` | distributed | rebuild stream prepare failure propagates `Stream failed` through runtime exception path。 |

## 运维关注点

- Replacement failure needs separating gossip visibility from liveness. `Cannot replace_address %s because it doesn't exist in gossip` means the shadow round could not discover the target state; `Cannot replace a live node...` means the target is visible and considered live.
- Removenode restore failure does not abort the coordinator notification path. After `Streaming to restore replica count failed`, operators should treat `forceRemoveCompletion()` and repair/rebuild as data-risk operations, not as a transparent recovery.
- Rebuild `--sources` is an allow-list, not a replica ownership override. If the allow-list removes strict sources or only points to the local node/unknown hosts, rebuild should fail before or during source calculation.
- `nodetool netstats` is the immediate observability surface for a concurrent rebuild guard because the user-facing error is `Node is still rebuilding. Check nodetool netstats.`

## 常见故障

- Replacement in a multi-DC cluster works through the same `REPLACE_ADDRESS_FIRST_BOOT` and shadow gossip path as single DC, but this repository baseline does not have a dedicated cross-DC replacement dtest.
- Removenode transient RF behavior is source-backed by `restoreReplicaCount()` and `MoveTransientTest`; there is no distributed transient removeNode proof in this checkout.
- Rebuild distributed success does not imply rebuild error coverage. The existing `RebuildStreamingTest` exercises `--keyspace` success and streaming vtable rows, while `--sources`/explicit range/concurrency errors are source/unit-backed only.
