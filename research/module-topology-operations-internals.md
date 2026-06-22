# Topology Operations Internals

## 范围

本文件是 `module-topology-operations.md` 的第二轮补充，重点覆盖第一轮待补的 simulator topology actions、replacement 故障边界、Paxos topology repair、removenode/transient replica restore 语义和跨 DC 扩缩容测试锚点。第一轮的 replace/move/removenode/rebuild/assassinate 主调用链仍以 `module-topology-operations.md` 和 `flow-topology-operations.md` 为准。

## 设计目标

- simulator 要把 JOIN、LEAVE、REPLACE、CHANGE_RF 当成可随机调度的 action，并在每次拓扑变更前后校验 replica ownership；`ClusterActions.TopologyChange` 定义四类变更，`OnClusterChangeTopology` 在 before/after 调用 validator，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/ClusterActions.java:68-81` 和 `test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterChangeTopology.java:32-70`。
- topology 变更要与 Paxos v2 清理/修复绑定，避免 replica 集变化后丢失已接受或已提交 ballot；生产路径由 `StorageService.startRepairPaxosForTopologyChange()` 扫描 distributed keyspaces，simulator 由 `OnInstanceTopologyChangePaxosRepair` 调用同一入口，见 `src/java/org/apache/cassandra/service/StorageService.java:4928-4948` 和 `test/simulator/main/org/apache/cassandra/simulator/cluster/OnInstanceTopologyChangePaxosRepair.java:40-70`。
- replacement 需要处理 down、abrupt down、full-cluster outage recovery、assassinated LEFT 状态、same-address/host-id/DNS 边界；分布式 host replacement 测试覆盖这些启动和 ring 收敛场景，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementTest.java:65-207`、`test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementOfDownedClusterTest.java:63-180`、`test/distributed/org/apache/cassandra/distributed/test/hostreplacement/BaseAssassinatedCase.java:58-99`。

## 解决的问题

- 第一轮只描述了真实 `StorageService` 和 nodetool 主线，没有解释 simulator 如何构造 pending topology。`KeyspaceActions.next()` 会在本地 `TokenMetadata` 上执行 addBootstrapTokens、addReplaceTokens、addLeavingEndpoint、removeEndpoint、RF 变更，再基于 pending ranges 生成 before/during/after `Topology`，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/KeyspaceActions.java:182-283`。
- replacement 不只是“替换 down host”。`HostReplacementAbruptDownedInstanceTest` 覆盖旧节点仍被其他节点视为 Normal 的 abrupt shutdown；`HostReplacementOfDownedClusterTest` 覆盖全节点停止后只恢复 seed 再 replace，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementAbruptDownedInstanceTest.java:53-103` 和 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementOfDownedClusterTest.java:63-180`。
- removenode 在 transient replication 下必须保留 full/transient 身份信息。`restoreReplicaCount()` 把远端 full 和 transient replica 分成两组 requestRanges，`getChangedReplicasForLeaving()` 明确讨论 transient -> full 需要 streaming，见 `src/java/org/apache/cassandra/service/StorageService.java:3704-3767` 和 `src/java/org/apache/cassandra/service/StorageService.java:3769-3833`。
- 跨 DC 扩缩容的现实测试锚点在 system_auth 场景：先扩展 dc2、修改 NTS、repair，再 force shutdown dc2 节点并 `removeNode`，最后去掉 dc2 RF，见 `test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java:122-213`。

## 设计取舍

- simulator 没有直接调用 `nodetool move/removenode/rebuild`，而是用 gossip state、bootstrap/unbootstrap、schema sync、Paxos repair 和 cleanup action 组合出拓扑变更。这让 action 可被 deterministic scheduler 控制，但与真实 nodetool 参数校验仍有差异，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterJoin.java:36-49`、`test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterLeave.java:43-59`、`test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterReplace.java:82-109`。
- REPLACE 在 simulator 中选择同 DC 的 prejoin 节点接管 leaving 节点 token，先 `addReplaceTokens` 计算 during topology，再 `updateNormalTokens` 计算 after topology；这覆盖 replica movement 和 pending ranges，但不覆盖真实 replacement 的 shadow gossip 入口，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/KeyspaceActions.java:209-231`。
- Paxos topology repair 默认偏保守。`ActiveRepairService.repairPaxosForTopologyChange()` 要求每个 range 有足够 live nodes 满足 EACH_QUORUM，否则抛异常并提示 skip 配置风险，见 `src/java/org/apache/cassandra/service/ActiveRepairService.java:1122-1160`。
- replacement 测试里多处设置 `BOOTSTRAP_SKIP_SCHEMA_CHECK`，这是为了绕过 down/abrupt down 节点携带旧 schema version 的启动阻塞；这种测试取舍保留 replacement 主行为，但不等于生产上应忽略 schema divergence，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementTest.java:88-93` 和 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementAbruptDownedInstanceTest.java:85-92`。

## 核心类

| 类 | 作用 | 证据 |
|---|---|---|
| `ClusterActions` | simulator cluster action 基类和拓扑变更选项 | `test/simulator/main/org/apache/cassandra/simulator/cluster/ClusterActions.java:68-138` |
| `KeyspaceActions` | 为某个 keyspace/table 生成 topology action stream、NTS keyspace、RF 与 pending topology | `test/simulator/main/org/apache/cassandra/simulator/cluster/KeyspaceActions.java:88-180`、`test/simulator/main/org/apache/cassandra/simulator/cluster/KeyspaceActions.java:182-359` |
| `OnClusterChangeTopology` | topology action 抽象类，执行前校验 old topology，transitive closure 后校验 new topology | `test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterChangeTopology.java:32-70` |
| `OnClusterJoin` / `OnClusterLeave` / `OnClusterReplace` / `OnClusterChangeRf` | simulator 中四类拓扑变更的 action 序列 | `test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterJoin.java:26-51`、`test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterLeave.java:33-59`、`test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterReplace.java:44-116`、`test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterChangeRf.java:31-65` |
| `OnInstanceBootstrap` | 在 simulator action 中调用 `StorageService.instance.startBootstrap(tokens, replacing)` | `test/simulator/main/org/apache/cassandra/simulator/cluster/OnInstanceBootstrap.java:34-53` |
| `OnInstanceTopologyChangePaxosRepair` | simulator 中调用生产 Paxos topology repair 并把相关 verbs 标为 reliable | `test/simulator/main/org/apache/cassandra/simulator/cluster/OnInstanceTopologyChangePaxosRepair.java:40-70` |
| `PaxosTopologyChangeVerifier` | topology 变更前后读取 Paxos ballots，校验 quorum accepted/committed 不丢失 | `test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosTopologyChangeVerifier.java:28-113` |

## 核心接口

- `ClusterActionListener.TopologyChangeValidator` 是 simulator topology 校验接口；`OnClusterChangeTopology` 构造时从 listener 取 validator 并注册 transitive closure 回调，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterChangeTopology.java:40-56`。
- `StorageService.startRepairPaxosForTopologyChange(reason)` 是生产和 simulator 共享的 Paxos topology repair 入口，见 `src/java/org/apache/cassandra/service/StorageService.java:4928-4948`。
- `ActiveRepairService.repairPaxosForTopologyChange(ksName, ranges, reason)` 是每 keyspace/range/table 的实际 Paxos repair 入口，见 `src/java/org/apache/cassandra/service/ActiveRepairService.java:1122-1160`。
- `TokenMetadata.addReplaceTokens` / `addBootstrapTokens` / `addLeavingEndpoint` / `removeEndpoint` 是 simulator 构造 before/during/after topology 的核心接口，调用点见 `test/simulator/main/org/apache/cassandra/simulator/cluster/KeyspaceActions.java:209-283`。

## 核心数据结构

- `Topology` 是 simulator 对 primary keys、ring members、tokens、RF、natural replicas 和 pending replicas 的快照；`KeyspaceActions.recomputeTopology()` 从 `NetworkTopologyStrategy` 和 `PendingRangeMaps` 生成它，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/KeyspaceActions.java:330-359`。
- `NodesByDc` 在 simulator 中维护 all/prejoin/joined/left 四组节点，并支持按 DC 随机 add/remove/select；`KeyspaceActions` 初始化这些集合并按 serial CL 决定 quorum DC 成员，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/KeyspaceActions.java:102-123`。
- `Options` 保存 topologyChangeLimit、topologyChangeInterval、可选 action 集合、min/initial/max RF 和可选 Paxos variant change；当 minRf 等于 maxRf 时会移除 CHANGE_RF，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/ClusterActions.java:83-138`。
- `LeavingReplica` 在 removenode restore 中保留 leaving replica 和本节点将承担的 replica，后续按 full/transient 身份选择 source ranges，见 `src/java/org/apache/cassandra/service/StorageService.java:3651-3692`。

## 生命周期

```text
Simulator topology action
  -> KeyspaceActions.plan()
  -> create NTS keyspace and table
  -> stream() repeatedly calls next()
  -> next() mutates TokenMetadata to compute before/during/after topology
  -> OnCluster* action executes gossip/bootstrap/unbootstrap/RF repair
  -> transitiveAfter updates current topology and permits time discontinuities
```

`KeyspaceActions.plan()` 创建 pre/interleave/post action plan；`next()` 按 DC 和 prejoin/joined/RF 约束选择 REPLACE、JOIN、LEAVE 或 CHANGE_RF，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/KeyspaceActions.java:126-180` 和 `test/simulator/main/org/apache/cassandra/simulator/cluster/KeyspaceActions.java:182-294`。`scheduleAndUpdateTopologyOnCompletion()` 在 action 执行时禁止 time discontinuities，在 transitive completion 后更新 topology 并重新允许，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/KeyspaceActions.java:303-322`。

```text
Simulator replace
  -> choose prejoin node and joined node in same DC
  -> new node inherits leaving token in NodeLookup
  -> TokenMetadata.addReplaceTokens()
  -> compute during topology with pending ranges
  -> compute after topology after updateNormalTokens()
  -> OnClusterReplace: mark leaving down, repair ranges, BOOT_REPLACING, schema sync, Paxos repair, bootstrap, NORMAL
```

关键实现见 `test/simulator/main/org/apache/cassandra/simulator/cluster/KeyspaceActions.java:209-231` 和 `test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterReplace.java:56-109`。

## 调用链

- simulator join：`OnClusterJoin.performSimple()` -> `OnInstanceSetBootstrapping` -> `OnInstanceSyncSchemaForBootstrap` -> `OnInstanceTopologyChangePaxosRepair("Join")` -> `OnInstanceBootstrap` -> `OnInstanceSetNormal`，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterJoin.java:36-49`。
- simulator leave：`OnClusterLeave.performSimple()` -> `OnInstanceSetLeaving` -> `StorageService.instance.prepareUnbootstrapStreaming()` -> `OnInstanceTopologyChangePaxosRepair("Leave")` -> execute prepared unbootstrap future -> `OnInstanceSetLeft`，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterLeave.java:43-59`。
- simulator replace：`OnClusterReplace.performSimple()` -> sync gossip -> mark leaving shutdown/down -> repair old ranges with Paxos -> set joining BOOT_REPLACING -> sync schema -> Paxos topology repair -> `startBootstrap(..., replacing=true)` -> set joining NORMAL，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterReplace.java:56-109`。
- simulator RF change：`OnClusterChangeRf.performSimple()` -> ALTER KEYSPACE NTS RF -> sync pending ranges -> full repair with Paxos -> optional flush/cleanup on RF decrease，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterChangeRf.java:49-65`。
- production replacement completion：gossip BOOT_REPLACING is handled by token metadata replace state; when replacement goes NORMAL, `handleStateNormal()` removes the old endpoint if it is the pending replaced node and refuses completing replacement of a live node,见 `src/java/org/apache/cassandra/service/StorageService.java:3166-3187` 和 `src/java/org/apache/cassandra/service/StorageService.java:3327-3355`。
- removenode remote handling：收到 REMOVING_TOKEN 后 `handleStateRemoving()` 把 endpoint 标为 leaving、更新 pending ranges、找 removal coordinator，并调用 `restoreReplicaCount()`，见 `src/java/org/apache/cassandra/service/StorageService.java:3460-3515`。

## 配置项

- simulator CLI `--cluster-actions` 支持 JOIN、LEAVE、REPLACE、CHANGE_RF，`SimulationRunner.BasicCommand` 把字符串解析为 `TopologyChange[]` 并传给 builder，见 `test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java:173-174` 和 `test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java:288-289`。
- simulator topology change interval/limit 来自 `ClusterActions.Options`，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/ClusterActions.java:83-126`。
- topology Paxos repair 可通过 `skip_paxos_repair_on_topology_change` 和 keyspace allow-list 跳过；JMX getter/setter 暴露在 `StorageServiceMBean`，实现委托 `DatabaseDescriptor`，见 `src/java/org/apache/cassandra/service/StorageServiceMBean.java:1235-1239` 和 `src/java/org/apache/cassandra/service/StorageService.java:7380-7398`。
- replacement 故障测试会设置 `BOOTSTRAP_SKIP_SCHEMA_CHECK` 或 `BOOTSTRAP_SCHEMA_DELAY_MS` 控制启动期 schema 等待，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementTest.java:88-93` 和 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/BaseAssassinatedCase.java:87-97`。

## Metrics

第二轮没有发现专用 topology metrics。拓扑变更仍主要通过 streaming metrics、Paxos repair 日志/异常和测试断言观察。replacement failed bootstrap 测试专门断言 role setup 重试不会增加 read/CAS read unavailable metrics，说明启动失败期间的 auth/read side effect 需要用现有 client request metrics 观察，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/FailedBootstrapTest.java:90-101`。

## 日志

- `repairPaxosForTopologyChange()` 会记录 skip、start、retry、complete；失败时按配置重试，见 `src/java/org/apache/cassandra/service/StorageService.java:4890-4926`。
- `ActiveRepairService.repairPaxosForTopologyChange()` 在 no ranges、disabled 或 insufficient live nodes 时记录 warning/抛异常，见 `src/java/org/apache/cassandra/service/ActiveRepairService.java:1122-1160`。
- replacement completion 会记录 new owner、replacement node、same host/address/host id 和 DNS 解析异常抑制，见 `src/java/org/apache/cassandra/service/StorageService.java:3237-3265`、`src/java/org/apache/cassandra/service/StorageService.java:3273-3303`、`src/java/org/apache/cassandra/service/StorageService.java:3327-3355`。
- removenode restore 会记录 possible replicas、sorted replicas、down replica skip、找不到 live replica 和 requestRanges 的 full/transient 分组，见 `src/java/org/apache/cassandra/service/StorageService.java:3580-3621` 和 `src/java/org/apache/cassandra/service/StorageService.java:3730-3752`。

## 运维关注点

- 不要把 simulator replace 结果等同于真实 `replace_address` 启动路径。simulator 覆盖 pending topology/Paxos/bootstrap 行为，但真实路径还包括 shadow gossip、same-address hibernate、schema delay、replace token conflict 和 endpoint DNS/host id 处理，见 `src/java/org/apache/cassandra/service/StorageService.java:742-866`、`src/java/org/apache/cassandra/service/StorageService.java:3273-3303`。
- 当前已读 hostreplacement 分布式测试没有形成“跨 DC replacement 专项用例”；跨 DC 扩缩容覆盖在 `UpdateSystemAuthAfterDCExpansionTest` 的 NTS/system_auth/removeNode 流程，replacement 跨 DC 仍应作为后续测试缺口保留，见 `test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java:122-213`。
- transient replication 下 removenode 不能只看 full replicas。`restoreReplicaCount()` 为 remote full/transient 分开 request ranges，说明 source 选择和 cleanup/repaired data 都要考虑 transient 身份，见 `src/java/org/apache/cassandra/service/StorageService.java:3730-3752`。
- same-address replacement 与 host id/DNS 有特殊防护。`isReplacingSameHostAddressAndHostId()` 会在 replace address DNS 无法解析时返回 false 以避免 gossip 卡在 JOINING，测试覆盖同地址同 host id、不同 host id 和 unresolvable host，见 `src/java/org/apache/cassandra/service/StorageService.java:3273-3303` 和 `test/unit/org/apache/cassandra/service/StorageServiceServerTest.java:665-688`。

## 性能瓶颈

- simulator topology action 在执行前会禁止 time discontinuities，直到 transitive closure 完成才恢复；这降低拓扑变更期间的时钟混乱，但长拓扑 action 会阻塞其他依赖时间跳变的探索，见 `test/simulator/main/org/apache/cassandra/simulator/cluster/KeyspaceActions.java:303-322`。
- Paxos topology repair 对每个 distributed keyspace 的 local/pending ranges 创建 futures，并在每个 table/range 上检查 live quorum；大型 keyspace/table/range 组合会放大拓扑操作延迟，见 `src/java/org/apache/cassandra/service/StorageService.java:4928-4948` 和 `src/java/org/apache/cassandra/service/ActiveRepairService.java:1135-1160`。
- removenode restore 对每个 distributed keyspace 计算 changed replicas，再按 source requestRanges；源码注释称该方法效率不高但调用很少，见 `src/java/org/apache/cassandra/service/StorageService.java:3694-3704`。
- host replacement 全集群恢复场景依赖 seed 重启后仍保留被替换节点 tokens；测试显式比对重启前后 token metadata，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementOfDownedClusterTest.java:83-104`。

## 常见故障

- replace live node 会失败。分布式测试断言 `replaceHostAndStart` 对 live node 抛 `Cannot replace a live node`，生产 gossip BOOT_REPLACING 处理也拒绝 old node alive，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementTest.java:110-146` 和 `src/java/org/apache/cassandra/service/StorageService.java:3166-3169`。
- assassinate 后 replacement 可能失败。BaseAssassinatedCase 先 assassinate，再尝试 replacement，并断言 token 不在 ring 或 gossip 缺 tokens，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/BaseAssassinatedCase.java:58-99` 和 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/AssassinatedEmptyNodeTest.java:35-61`。
- hibernating/same-address join 边界会阻止普通 node join。`NodeCannotJoinAsHibernatingNodeWithoutReplaceAddressTest` 用同地址替换失败后，再以 auto_bootstrap 普通节点启动，同地址已存在导致 join 取消，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/NodeCannotJoinAsHibernatingNodeWithoutReplaceAddressTest.java:52-88`。
- removenode 对 bad host id、本地 host id、非 ring member 都失败；成功路径要等所有 replication done 确认，见 `test/unit/org/apache/cassandra/service/RemoveTest.java:108-179`。
- transient move/source filter 缺少必要 source 会失败。`MoveTransientTest` 对 down nodes 和 source filters 断言 strict consistency 所需 replicas 被移除时抛异常，见 `test/unit/org/apache/cassandra/service/MoveTransientTest.java:392-467`。

## 测试用例

- `HostReplacementTest` 覆盖 down replacement、live replacement failure、seed 先 down 后恢复再 replacement，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementTest.java:65-207`。
- `HostReplacementAbruptDownedInstanceTest` 覆盖 abrupt shutdown 后旧节点仍为 Normal 的 replacement，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementAbruptDownedInstanceTest.java:53-103`。
- `HostReplacementOfDownedClusterTest` 覆盖全节点停止、只恢复 seed、replace dead node，以及其他节点在 replace 后再启动，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementOfDownedClusterTest.java:63-180`。
- `BaseAssassinatedCase`、`AssassinatedEmptyNodeTest`、`AssassinateGracefullNodeTest` 覆盖 assassinate 后 replacement 的 token/gossip 空状态边界，见 `test/distributed/org/apache/cassandra/distributed/test/hostreplacement/BaseAssassinatedCase.java:58-99`、`test/distributed/org/apache/cassandra/distributed/test/hostreplacement/AssassinatedEmptyNodeTest.java:35-61`、`test/distributed/org/apache/cassandra/distributed/test/hostreplacement/AssassinateGracefullNodeTest.java:30-38`。
- `UpdateSystemAuthAfterDCExpansionTest` 覆盖跨 DC 扩展、system_auth RF 变更、repair、force shutdown、removeNode 和去掉 dc2 RF，见 `test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java:122-235`。
- `MoveTest` 分布式测试在无 vnodes 的 4 节点 ring 上用 `nodetool move` 覆盖正反方向移动，见 `test/distributed/org/apache/cassandra/distributed/test/MoveTest.java:49-91`。
- `MoveTransientTest` 单测覆盖 transient/full move stream/fetch、preferred endpoints、down nodes、source filters 和 `3/1` RF，见 `test/unit/org/apache/cassandra/service/MoveTransientTest.java:171-305`、`test/unit/org/apache/cassandra/service/MoveTransientTest.java:392-675`。
