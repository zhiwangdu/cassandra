# Flow: Decommission

## 入口

Decommission 是活节点主动离开 ring 的流程。它通过 nodetool/JMX 调用当前节点的 `StorageService.decommission(force)`，先校验本节点状态、RF 与 pending ranges，再 gossip LEAVING、等待 pending range 收敛、把本节点负责的数据 stream 给未来 replicas，最后关闭客户端服务、gossip、messaging，并把本地 bootstrap state 标记为 `DECOMMISSIONED`。

## 主调用图

```text
nodetool decommission [-f]
  -> Decommission.execute(NodeProbe)
     -> StorageServiceMBean.isDecommissioning()
     -> StorageServiceMBean.getBootstrapState()
     -> NodeProbe.decommission(force)
        -> StorageServiceMBean.decommission(force)
           -> StorageService.decommission(force)
              -> validate operation mode and ring membership
              -> PendingRangeCalculatorService.blockUntilFinished()
              -> for each distributed keyspace:
                   validate RF/live-node count unless force
                   reject if pending ranges target this node
              -> startLeaving()
                 -> gossip STATUS LEAVING
                 -> tokenMetadata.addLeavingEndpoint(local)
                 -> PendingRangeCalculatorService.update()
              -> sleep max(RING_DELAY_MILLIS, batchlog timeout)
              -> unbootstrap()
              -> shutdownClientServers()
              -> Gossiper.stop()
              -> MessagingService.shutdown()
              -> Stage.shutdownNow()
              -> SystemKeyspace.setBootstrapState(DECOMMISSIONED)
              -> setMode(DECOMMISSIONED)
```

关键源码：

- `nodetool decommission` 先检查正在 decommission 和已 decommission 状态，再调用 `probe.decommission(force)`，见 `src/java/org/apache/cassandra/tools/nodetool/Decommission.java:26-55`。
- `NodeProbe.decommission()` 通过 StorageService MBean 转发，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:1011-1013`。
- `StorageService.decommission()` 的状态/RF/pending range 校验、LEAVING、unbootstrap、shutdown 和 state 标记见 `src/java/org/apache/cassandra/service/StorageService.java:5298-5416`。
- `startLeaving()` 广播 LEAVING 并更新 local token metadata，见 `src/java/org/apache/cassandra/service/StorageService.java:5282-5296`。

## 校验阶段

```text
StorageService.decommission(force)
  -> if already DECOMMISSIONED: no-op
  -> if isDecommissioning: no-op
  -> metadata = tokenMetadata.cloneAfterAllLeft()
  -> if not already LEAVING:
       require local node is ring member
       reject single-node ring
       require NORMAL or DECOMMISSION_FAILED
  -> compareAndSet isDecommissioning
  -> PendingRangeCalculatorService.blockUntilFinished()
  -> for each Schema.distributedKeyspaces():
       if !force:
          validate live normal nodes can still satisfy RF
       reject if local node currently has pending ranges
```

关键源码：

- 已 decommission / 正在 decommission / 非 ring member / 单节点 ring / 非 NORMAL 状态检查见 `src/java/org/apache/cassandra/service/StorageService.java:5298-5325`。
- RF 与 live-node 保护逻辑见 `src/java/org/apache/cassandra/service/StorageService.java:5336-5368`。
- pending ranges 拒绝逻辑见 `src/java/org/apache/cassandra/service/StorageService.java:5369-5372`。

## Unbootstrap Streaming

```text
unbootstrap()
  -> prepareUnbootstrapStreaming()
     -> for each distributed keyspace:
          getChangedReplicasForLeaving(keyspace, local, tokenMetadata, strategy)
          rangesToStream[keyspace] = local replica -> future replica
     -> returns supplier(() -> streamRanges(rangesToStream))
  -> setMode(LEAVING, replaying batch log and streaming data)
  -> repairPaxosForTopologyChange("decommission")
  -> BatchlogManager.startBatchlogReplay()
  -> startStreaming.get()
     -> streamRanges(rangesToStream)
        -> build sessionsToStreamByKeyspace
        -> skip ranges already in system.transferred_ranges
        -> new StreamPlan(StreamOperation.DECOMMISSION)
        -> streamPlan.listeners(streamStateStore)
        -> for each endpoint/keyspace/ranges:
             streamPlan.transferRanges(endpoint, keyspace, replicas)
        -> streamPlan.execute()
  -> wait batchlog replay
  -> if transfer_hints_on_decommission:
       streamHints()
     else:
       disable hinted handoff, pause dispatch, delete hints
  -> wait stream and hints futures
  -> leaveRing()
```

关键源码：

- `prepareUnbootstrapStreaming()` 计算每个 keyspace 的 leaving range movement，见 `src/java/org/apache/cassandra/service/StorageService.java:5437-5451`。
- `unbootstrap()` 串联 Paxos repair、batchlog replay、range streaming、hints transfer/delete 和 `leaveRing()`，见 `src/java/org/apache/cassandra/service/StorageService.java:5454-5488`。
- `streamRanges()` 将 local ranges 归并为 per-endpoint transfer sessions，并执行 `StreamPlan(StreamOperation.DECOMMISSION)`，见 `src/java/org/apache/cassandra/service/StorageService.java:6375-6429`。
- `StreamPlan.transferRanges()` 是实际 streaming plan 的 transfer 入口，见 `src/java/org/apache/cassandra/streaming/StreamPlan.java:91-130`。

## Leave Ring

```text
leaveRing()
  -> SystemKeyspace.setBootstrapState(NEEDS_BOOTSTRAP)
  -> tokenMetadata.removeEndpoint(local)
  -> PendingRangeCalculatorService.update()
  -> gossip STATUS LEFT with expire time
  -> sleep max(RING_DELAY_MILLIS, gossip interval * 2)
return to decommission()
  -> shutdown services
  -> SystemKeyspace.setBootstrapState(DECOMMISSIONED)
  -> setMode(DECOMMISSIONED)
```

关键源码：

- `leaveRing()` 移除 local endpoint、广播 LEFT 并等待传播，见 `src/java/org/apache/cassandra/service/StorageService.java:5424-5435`。
- decommission 完成后的服务关闭和 `DECOMMISSIONED` 标记见 `src/java/org/apache/cassandra/service/StorageService.java:5380-5397`。

## Hints 与 Batchlog

- Decommission 前先 replay batchlog，因为本节点即将不再是合法 endpoint，未完成 batchlog 可能需要转成 hints 或写到新 replicas，见 `src/java/org/apache/cassandra/service/StorageService.java:5458-5467`。
- `transfer_hints_on_decommission=true` 时调用 `streamHints()`，否则关闭 hinted handoff、暂停 dispatch 并删除本地 hints，见 `src/java/org/apache/cassandra/service/StorageService.java:5468-5481`。
- `streamHints()` 调用 `HintsService.instance.transferHints(this::getPreferredHintsStreamTarget)`，见 `src/java/org/apache/cassandra/service/StorageService.java:5490-5493`。
- 配置读取 `DatabaseDescriptor.getTransferHintsOnDecommission()` 见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3744-3749`。

## 状态与观测

- `isDecommissioning()` 被 nodetool 用来避免重复触发，调用见 `src/java/org/apache/cassandra/tools/nodetool/Decommission.java:37-43`。
- `operationMode` 在流程中从 NORMAL 到 LEAVING，再到 DECOMMISSIONED 或 DECOMMISSION_FAILED；核心 `setMode()` 调用分布在 `src/java/org/apache/cassandra/service/StorageService.java:5377-5416`。
- streaming 进度通过 `nodetool netstats` 和 StreamManager/stream events 观察，range transfer 入口见 `src/java/org/apache/cassandra/service/StorageService.java:6375-6429`。
- 已 decommission 节点重启时会被 `prepareToJoin()` 拒绝，除非显式 override，见 `src/java/org/apache/cassandra/service/StorageService.java:1145-1158`。

## 异常分支

- 单节点 ring：`decommission()` 抛出 `no other normal nodes in the ring`，见 `src/java/org/apache/cassandra/service/StorageService.java:5319-5321`。
- 非 NORMAL/DECOMMISSION_FAILED 状态：拒绝 decommission，见 `src/java/org/apache/cassandra/service/StorageService.java:5322-5324`。
- RF 不足：非 force 模式下每个 distributed keyspace 都会检查 RF 与 live nodes，失败消息提示 forceful decommission，见 `src/java/org/apache/cassandra/service/StorageService.java:5339-5368`。
- 本节点仍有 pending ranges：说明数据正在迁入本节点，decommission 被拒绝，见 `src/java/org/apache/cassandra/service/StorageService.java:5369-5372`。
- `unbootstrap()` / streaming / hints 失败：`decommission()` 捕获异常并设置 `DECOMMISSION_FAILED`，见 `src/java/org/apache/cassandra/service/StorageService.java:5400-5416`。

## 配置入口

- `transfer_hints_on_decommission` 控制 decommission 时迁移 hints 还是删除本地 hints，定义见 `src/java/org/apache/cassandra/config/Config.java:452`，读取见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3744-3749`。
- `RING_DELAY_MILLIS` 影响 LEAVING 后等待 pending ranges/gossip 收敛的时间，使用见 `src/java/org/apache/cassandra/service/StorageService.java:5375-5378` 和 `src/java/org/apache/cassandra/service/StorageService.java:5431-5435`。
- `severity_during_decommission` 会在 `startLeaving()` 中注入 dynamic snitch severity，见 `src/java/org/apache/cassandra/service/StorageService.java:5282-5285`。

## 测试锚点

- `DecommissionTest` 覆盖 decommission 失败后重试、重启后重试、已 decommission no-op 和 bootstrap state 变化，见 `test/distributed/org/apache/cassandra/distributed/test/DecommissionTest.java:64-119` 和 `test/distributed/org/apache/cassandra/distributed/test/DecommissionTest.java:143-181`。
- `DecommissionAvoidWriteTimeoutsTest` 与 `DecommissionAvoidReadTimeoutsTest` 覆盖 decommission 期间避免读写 timeout 的拓扑行为，见 `test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidWriteTimeoutsTest.java` 和 `test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidReadTimeoutsTest.java`。
- `CommunicationDuringDecommissionTest` 覆盖 decommission 期间通信行为，见 `test/distributed/org/apache/cassandra/distributed/test/ring/CommunicationDuringDecommissionTest.java`。
- `LeaveAndBootstrapTest` 覆盖 gossip leaving/bootstrap 状态跳转和 token metadata，见 `test/unit/org/apache/cassandra/service/LeaveAndBootstrapTest.java:463-522`。
