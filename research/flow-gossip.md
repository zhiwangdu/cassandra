# Flow: Gossip And Failure Detection

## 目标

Gossip 链路解释一个节点如何周期性传播 endpoint state，如何通过 SYN/ACK/ACK2 合并 remote state，以及 Failure Detector 如何把心跳到达间隔转换成 endpoint DOWN/UP 事件。

## 文字版调用图

```text
Startup / join
  -> StorageService.initServer()
     -> Gossiper.instance.register(StorageService)
     -> Gossiper.instance.start(generation, appStates)
        -> buildSeedsList()
        -> maybeInitializeLocalState(generation)
        -> local EndpointState.addApplicationStates(appStates)
        -> schedule GossipTask every Gossiper.intervalInMillis
     -> MessagingService.instance().listen()

Every gossip interval
  -> GossipTask.run()
     -> MessagingService.waitUntilListening()
     -> local EndpointState.updateHeartBeat()
     -> makeGossipDigest(endpointStateMap)
     -> Message.out(GOSSIP_DIGEST_SYN, GossipDigestSyn)
     -> doGossipToLiveMember(message)
     -> maybeGossipToUnreachableMember(message)
     -> maybeGossipToSeed(message)
     -> doStatusCheck()
        -> for each non-local endpoint
           -> FailureDetector.interpret(endpoint)
           -> maybe remove fat client
           -> maybe evict expired dead state
```

Remote SYN receiver:

```text
MessagingService receives GOSSIP_DIGEST_SYN
  -> InboundSink.accept(message)
     -> GossipDigestSynVerbHandler.doVerb(message)
        -> reject if gossip disabled outside shadow round
        -> reject if cluster/partitioner mismatch
        -> if shadow round, return minimal ACK or shadow state
        -> examineGossiper(remote digests)
           -> build deltaGossipDigestList for state we need
           -> build deltaEpStateMap for state remote needs
        -> send GOSSIP_DIGEST_ACK
        -> record last processed gossip message time
```

Original sender receives ACK:

```text
GossipDigestAckVerbHandler.doVerb(message)
  -> if shadow round, maybeFinishShadowRound(...)
  -> if ACK has endpoint states
     -> Gossiper.notifyFailureDetector(epStateMap)
        -> FailureDetector.report(endpoint)
     -> Gossiper.applyStateLocally(epStateMap)
        -> compare generation and max version
        -> handle major generation changes
        -> apply newer application states
        -> markAlive() if previously down
           -> send ECHO_REQ
           -> ECHO_RSP callback realMarkAlive()
  -> for requested digests
     -> getStateForVersionBiggerThan(...)
     -> send GOSSIP_DIGEST_ACK2
```

Remote SYN receiver receives ACK2:

```text
GossipDigestAck2VerbHandler.doVerb(message)
  -> Gossiper.notifyFailureDetector(remoteEpStateMap)
  -> Gossiper.applyStateLocally(remoteEpStateMap)
  -> record last processed gossip message time
```

Failure detection:

```text
Gossip state observed from endpoint
  -> FailureDetector.report(endpoint)
     -> ArrivalWindow.add(now)

GossipTask.doStatusCheck()
  -> FailureDetector.interpret(endpoint)
     -> if local pause too long, skip conviction
     -> phi = timeSinceLastArrival / meanArrivalInterval
     -> if PHI_FACTOR * phi > phi_convict_threshold
        -> IFailureDetectionEventListener.convict(endpoint, phi)
           -> Gossiper.convict()
              -> if endpoint gossiped SHUTDOWN
                 -> markAsShutdown()
              -> else
                 -> markDead()
```

Shutdown:

```text
Gossiper.stop()
  -> if local state exists, not silent shutdown, and StorageService joined
     -> add STATUS_WITH_PORT=shutdown
     -> add STATUS=shutdown
     -> send GOSSIP_SHUTDOWN to live endpoints
     -> sleep shutdown announce delay
  -> cancel scheduled gossip task
```

## 关键源码锚点

| 阶段 | 文件/方法 |
|---|---|
| gossip task 主体 | `Gossiper.GossipTask.run()`：`src/java/org/apache/cassandra/gms/Gossiper.java:337-387` |
| gossip 启动 | `Gossiper.start()`：`src/java/org/apache/cassandra/gms/Gossiper.java:2006-2031` |
| local endpoint state 初始化 | `Gossiper.maybeInitializeLocalState()`：`src/java/org/apache/cassandra/gms/Gossiper.java:2197-2204` |
| seed list 初始化 | `Gossiper.buildSeedsList()`：`src/java/org/apache/cassandra/gms/Gossiper.java:2125-2133` |
| digest 构造 | `Gossiper.makeGossipDigest()`：`src/java/org/apache/cassandra/gms/Gossiper.java:811-832` |
| 发送 SYN | `Gossiper.sendGossip()`：`src/java/org/apache/cassandra/gms/Gossiper.java:984-1002` |
| 计算 delta | `Gossiper.examineGossiper()`：`src/java/org/apache/cassandra/gms/Gossiper.java:1940-2004` |
| SYN handler | `GossipDigestSynVerbHandler.doVerb()`：`src/java/org/apache/cassandra/gms/GossipDigestSynVerbHandler.java:42-122` |
| ACK handler | `GossipDigestAckVerbHandler.doVerb()`：`src/java/org/apache/cassandra/gms/GossipDigestAckVerbHandler.java:41-102` |
| ACK2 handler | `GossipDigestAck2VerbHandler.doVerb()`：`src/java/org/apache/cassandra/gms/GossipDigestAck2VerbHandler.java:34-52` |
| FD report | `FailureDetector.report()`：`src/java/org/apache/cassandra/gms/FailureDetector.java:313-333` |
| FD interpret | `FailureDetector.interpret()`：`src/java/org/apache/cassandra/gms/FailureDetector.java:335-378` |
| FD conviction 到 gossip | `Gossiper.convict()`：`src/java/org/apache/cassandra/gms/Gossiper.java:600-627` |
| mark alive | `Gossiper.markAlive()` / `realMarkAlive()`：`src/java/org/apache/cassandra/gms/Gossiper.java:1437-1494` |
| mark dead | `Gossiper.markDead()`：`src/java/org/apache/cassandra/gms/Gossiper.java:1501-1515` |
| 状态合并 | `Gossiper.applyStateLocally()`：`src/java/org/apache/cassandra/gms/Gossiper.java:1710-1784` |
| application state 通知 | `Gossiper.applyNewStates()`：`src/java/org/apache/cassandra/gms/Gossiper.java:1788-1844` |
| status check | `Gossiper.doStatusCheck()`：`src/java/org/apache/cassandra/gms/Gossiper.java:1126-1206` |
| shadow round | `Gossiper.doShadowRound()`：`src/java/org/apache/cassandra/gms/Gossiper.java:2039-2122` |
| shutdown gossip | `Gossiper.stop()`：`src/java/org/apache/cassandra/gms/Gossiper.java:2284-2303` |

## 状态和一致性语义

- Generation 代表 endpoint 启动代际；remote generation 更高时视为 major state change，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1736-1756`。
- 同 generation 下比较 max application state version；remote 更新时只应用 version 更高的 state，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1757-1768`、`src/java/org/apache/cassandra/gms/Gossiper.java:1788-1807`。
- `STATUS/STATUS_WITH_PORT` 先通知 subscriber，避免 token/state 处理顺序破坏 bootstrap/replace 逻辑，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1814-1827`。
- 远端从 down 到 alive 不直接标记 UP，而是发送 `ECHO_REQ`，收到响应后再 `realMarkAlive()`，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1437-1477`。
- FD 的 `isAlive()` 最终读取 `EndpointState.isAlive()`；local endpoint 总是返回 true，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:299-310`。

## 配置与观测

- `phi_convict_threshold` 定义在 `src/java/org/apache/cassandra/config/Config.java:177`，模板在 `conf/cassandra.yaml:1469-1471`。
- gossip 使用 `storage_port` 相关 internode 通信，端口配置见 `src/java/org/apache/cassandra/config/Config.java:214-215`、`conf/cassandra.yaml:958-966`。
- seed provider 配置在 `Config.seed_provider` 与 `DatabaseDescriptor.applySeedProvider()` 中，已在 `module-startup-bootstrap.md` 覆盖；本 flow 关注 `Gossiper.buildSeedsList()`。
- Failure Detector JMX MBean 为 `org.apache.cassandra.net:type=FailureDetector`，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:69-108`。
- dropped gossip/messaging 要从 `MessagingMetrics` 和 `InternodeOutboundMetrics` 观察，定义见 `src/java/org/apache/cassandra/metrics/MessagingMetrics.java:129-170`、`src/java/org/apache/cassandra/metrics/InternodeOutboundMetrics.java:117-155`。

## 排查路径

1. gossip 是否运行：看 `Gossiper.isEnabled()`，见 `src/java/org/apache/cassandra/gms/Gossiper.java:2305-2309`，再结合 `nodetool statusgossip`。
2. seed 是否可达：看 `Gossiper.buildSeedsList()` 是否排除自身并获得 seeds，见 `src/java/org/apache/cassandra/gms/Gossiper.java:2125-2133`。
3. 状态是否被拒绝：查 SYN handler 的 cluster name / partitioner mismatch 日志，见 `src/java/org/apache/cassandra/gms/GossipDigestSynVerbHandler.java:54-66`。
4. FD 是否误判：查本地 pause、PHI debug/trace、`phi_convict_threshold`、gossip stage backlog，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:342-377`、`src/java/org/apache/cassandra/gms/Gossiper.java:1134-1145`。
5. 节点从 DOWN 回 UP 慢：检查 `ECHO_REQ` 是否能收到响应，mark alive 需要 callback 成功，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1437-1477`。
6. replace/bootstrap 卡住：检查 shadow round 是否收到 sufficient ACK，见 `src/java/org/apache/cassandra/gms/Gossiper.java:2039-2122`、`src/java/org/apache/cassandra/gms/Gossiper.java:2319-2357`。

## 测试用例

- `test/unit/org/apache/cassandra/gms/FailureDetectorTest.java`
- `test/unit/org/apache/cassandra/gms/GossipDigestTest.java`
- `test/unit/org/apache/cassandra/gms/GossipShutdownTest.java`
- `test/unit/org/apache/cassandra/gms/GossiperTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/GossipTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/GossipSettlesTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/GossipShutdownTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/gossip/GossipShutdownTest.java`
