# Nodetool Status/Ring Observability Matrix

本矩阵补齐 `nodetool status` 与 `nodetool ring` 的运行态观测合同。两条命令都把 `StorageServiceMBean` 的 token metadata / gossip liveness / ownership / load / host id 视图和 `EndpointSnitchInfoMBean` 的 datacenter/rack 视图组合成文本输出，但输出粒度不同：`status` 面向每节点状态快照，`ring` 面向 token ring 明细。

## Source Contract

| Scenario | Contract | Source anchors | Operational meaning |
| --- | --- | --- | --- |
| `nodetool_status_command_surface_contract` | `Status` 注册为 `@Command(name = "status")`，接受可选 keyspace 参数和 `-r/--resolve-ip`，全局 `-pp/--print-port` 来自 `NodeToolCmd`。 | `src/java/org/apache/cassandra/tools/nodetool/Status.java:30`、`src/java/org/apache/cassandra/tools/nodetool/Status.java:34`、`src/java/org/apache/cassandra/tools/NodeTool.java:367` | `status` 默认按 endpoint 分组输出集群节点状态，keyspace 只影响 effective ownership 计算。 |
| `nodetool_status_jmx_snapshot_contract` | `Status.execute()` 一次性读取 joining/leaving/moving/live/unreachable、load、token-to-endpoint、hostId、snitch 和 ownership。 | `src/java/org/apache/cassandra/tools/nodetool/Status.java:55`、`src/java/org/apache/cassandra/tools/NodeProbe.java:717`、`src/java/org/apache/cassandra/tools/NodeProbe.java:722`、`src/java/org/apache/cassandra/tools/NodeProbe.java:844` | 输出是 NodeProbe 视角的 JMX 快照；不是 gossip/event 的持续订阅。 |
| `nodetool_status_state_rendering_contract` | `status` 用 `U/D/?` 表示 live/unreachable/unknown，用 `J/L/M/N` 表示 joining/leaving/moving/normal，并打印 `Status=Up/Down` 与 `State=Normal/Leaving/Joining/Moving` legend。 | `src/java/org/apache/cassandra/tools/nodetool/Status.java:107`、`src/java/org/apache/cassandra/tools/nodetool/Status.java:112`、`src/java/org/apache/cassandra/tools/nodetool/Status.java:97` | 排障时 `UN` 是 Up+Normal，`DN` 是 Down+Normal；状态列不是单一字段。 |
| `nodetool_ring_command_surface_contract` | `Ring` 注册为 `@Command(name = "ring")`，接受 keyspace 参数和 `-r/--resolve-ip`；存在 vnode warning，提示多 token 节点应使用 `status` 看节点级状态。 | `src/java/org/apache/cassandra/tools/nodetool/Ring.java:31`、`src/java/org/apache/cassandra/tools/nodetool/Ring.java:35`、`src/java/org/apache/cassandra/tools/nodetool/Ring.java:107` | `ring` 会输出每个 token，因此 vnode 集群中行数可能远大于节点数。 |
| `nodetool_ring_state_rendering_contract` | `ring` 输出列为 `Address`、`Rack`、`Status`、`State`、`Load`、`Owns`、`Token`，状态文本为 `Up/Down/?` 和 `Normal/Joining/Leaving/Moving`。 | `src/java/org/apache/cassandra/tools/nodetool/Ring.java:133`、`src/java/org/apache/cassandra/tools/nodetool/Ring.java:148`、`src/java/org/apache/cassandra/tools/nodetool/Ring.java:154` | `ring` 适合核对 token ownership 和 pending topology，不适合只看节点健康。 |
| `nodetool_status_ring_with_port_mbean_contract` | 两条命令都调用 `NodeProbe` 的 with-port 方法，最终代理到 `StorageServiceMBean` 的 `getLiveNodesWithPort()`、`getUnreachableNodesWithPort()`、`getJoiningNodesWithPort()`、`getLeavingNodesWithPort()`、`getMovingNodesWithPort()`、`getTokenToEndpointWithPortMap()`、`getLoadMapWithPort()`、`getEndpointWithPortToHostId()`、`getOwnershipWithPort()` 和 `effectiveOwnershipWithPort(String)`。 | `src/java/org/apache/cassandra/tools/NodeProbe.java:717`、`src/java/org/apache/cassandra/service/StorageServiceMBean.java:49`、`src/java/org/apache/cassandra/service/StorageServiceMBean.java:207`、`src/java/org/apache/cassandra/service/StorageServiceMBean.java:237`、`src/java/org/apache/cassandra/service/StorageServiceMBean.java:601` | Cassandra 4.0+ 的 nodetool 输出需要区分同 IP 不同端口节点；旧无端口 MBean 保留为 deprecated 兼容面。 |
| `nodetool_status_ring_tokenmetadata_source_contract` | `StorageService.getTokenToEndpointWithPortMap()` 来自 `tokenMetadata.getNormalAndBootstrappingTokenToEndpointMap()` 并按 token 排序；joining/leaving/moving 来自 token metadata；live/unreachable 来自 `Gossiper`。 | `src/java/org/apache/cassandra/service/StorageService.java:2686`、`src/java/org/apache/cassandra/service/StorageService.java:4012`、`src/java/org/apache/cassandra/service/StorageService.java:4024`、`src/java/org/apache/cassandra/service/StorageService.java:4050`、`src/java/org/apache/cassandra/service/StorageService.java:4062` | `status`/`ring` 的 ring membership 同时受到 token metadata 和 gossip 可达性影响。 |
| `nodetool_status_ring_ownership_fallback_contract` | 两条命令优先调用 `effectiveOwnershipWithPort(keyspace)`；遇到 `IllegalStateException` 时降级为 `getOwnershipWithPort()` 并打印 Note；遇到 `IllegalArgumentException` 直接报错退出。 | `src/java/org/apache/cassandra/tools/nodetool/Status.java:69`、`src/java/org/apache/cassandra/tools/nodetool/Status.java:75`、`src/java/org/apache/cassandra/tools/nodetool/Ring.java:81`、`src/java/org/apache/cassandra/tools/nodetool/Ring.java:87`、`src/java/org/apache/cassandra/service/StorageService.java:6223` | 多 keyspace replication 不一致、LocalStrategy 或 bootstrap 早期可能让 effective ownership 失效；命令会保留非 replication-aware owns 作为退路。 |
| `nodetool_status_ring_snitch_grouping_contract` | `NodeTool.getOwnershipByDcWithPort()` 用 `EndpointSnitchInfoMBean.getDatacenter(endpoint)` 分 DC；`status`/`ring` 行级 rack 来自 `EndpointSnitchInfoMBean.getRack(endpoint)`。 | `src/java/org/apache/cassandra/tools/NodeTool.java:515`、`src/java/org/apache/cassandra/tools/nodetool/Status.java:123`、`src/java/org/apache/cassandra/tools/nodetool/Ring.java:140`、`src/java/org/apache/cassandra/locator/EndpointSnitchInfoMBean.java:28` | snitch 错配会直接污染 datacenter/rack 展示和 ownership 分组，排障时要和 snitch 配置一起看。 |
| `nodetool_status_ring_distributed_test_baseline` | 当前 runtime 覆盖来自 `NodeToolTest.testCaptureConsoleOutput()` 的 ring 输出断言、`JMXFeatureTest.testShutDownAndRestartInstances()` 的 `status` Down/Up 输出断言，以及 `ClusterUtils` 的 ring parser/await helpers。 | `test/distributed/org/apache/cassandra/distributed/test/NodeToolTest.java:64`、`test/distributed/org/apache/cassandra/distributed/test/jmx/JMXFeatureTest.java:108`、`test/distributed/org/apache/cassandra/distributed/shared/ClusterUtils.java:316` | 现有测试覆盖基本可用性和状态变更，但没有专门覆盖 `-r`、`-pp`、effective ownership fallback 和 vnode warning 的完整输出矩阵。 |

## Call Graph

```text
nodetool status [keyspace]
  -> Status.execute(NodeProbe)
  -> NodeProbe getJoining/Leaving/Moving/Live/UnreachableNodes(true)
  -> NodeProbe getLoadMap(true), getTokenToEndpointMap(true), getHostIdMap(true)
  -> NodeProbe.effectiveOwnershipWithPort(keyspace)
     -> StorageService.effectiveOwnershipWithPort(keyspace)
     -> StorageService.getEffectiveOwnership(keyspace)
     -> replication strategy address replicas
  -> fallback NodeProbe.getOwnershipWithPort()
  -> NodeTool.getOwnershipByDcWithPort(...)
  -> EndpointSnitchInfoMBean.getDatacenter(endpoint)
  -> EndpointSnitchInfoMBean.getRack(endpoint)
  -> render datacenter sections and UN/DN/J/L/M rows

nodetool ring [keyspace]
  -> Ring.execute(NodeProbe)
  -> same NodeProbe status/load/token/ownership/snitch sources
  -> build endpoint -> tokens multimap
  -> NodeTool.getOwnershipByDcWithPort(...)
  -> Ring.printDc(...)
  -> render Address/Rack/Status/State/Load/Owns/Token rows
  -> warn when vnodes make ring output token-level
```

## Data Source Mapping

| Output field | Status source | Ring source | Notes |
| --- | --- | --- | --- |
| Datacenter | `NodeTool.getOwnershipByDcWithPort()` | `NodeTool.getOwnershipByDcWithPort()` | Uses `EndpointSnitchInfoMBean.getDatacenter(endpoint)`. |
| Rack | `epSnitchInfo.getRack(endpoint)` | `epSnitchInfo.getRack(endpoint)` | `ring` degrades unknown rack to `Unknown` on `UnknownHostException`; `status` throws runtime exception. |
| Status | `liveNodes` / `unreachableNodes` | `liveNodes` / `deadNodes` | Status short form is `U/D/?`; ring long form is `Up/Down/?`. |
| State | `joiningNodes` / `leavingNodes` / `movingNodes` | same | Status short form is `J/L/M/N`; ring long form is `Joining/Leaving/Moving/Normal`. |
| Load | `StorageService.getLoadMapWithPort()` | same | Source merges `LoadBroadcaster` peer data and local `getLoadString()`. |
| Owns | `effectiveOwnershipWithPort()` or fallback `getOwnershipWithPort()` | same | Effective ownership is replication-aware; fallback is token ownership. |
| Token(s) | `getTokenToEndpointWithPortMap()` grouped by endpoint | `getTokenToEndpointWithPortMap()` token rows | Token map includes normal and bootstrapping endpoints. |
| Host ID | `getEndpointWithPortToHostId()` | not printed | Host id is status-only in these commands. |

## Operational Notes

- Use `status` for node health and host id; use `ring` for token placement and ownership details.
- A Down row in `status`/`ring` reflects the querying node's failure detector/gossip view, not a cluster-global truth.
- When non-system keyspaces do not share replication settings, owns values fall back and a Note is printed. Always pass a keyspace when debugging ownership for a specific workload.
- `ring` vnode warning is intentional: it prints tokens, not just nodes.
- Snitch datacenter/rack information is an input to grouping, so topology anomalies should be checked against snitch config and `nodetool gossipinfo`.

## Tests And Gaps

- `NodeToolTest.testCaptureConsoleOutput()` proves `ring` prints datacenter and an `Up Normal` row in an in-JVM cluster.
- `JMXFeatureTest.testShutDownAndRestartInstances()` proves `status` can observe `DN` after a node stop and `UN` after restart through isolated JMX.
- `ClusterUtils.ring()` / `parseRing()` / `awaitRingStatus()` / `awaitRingState()` are distributed-test helpers that rely on the ring output shape.
- Remaining gap: add focused distributed nodetool tests for `status -r`, `ring -r`, global `-pp`, vnode warning, invalid keyspace, and effective ownership fallback Note.
