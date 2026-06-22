# Module: Gossip, Failure Detector, Messaging

## 范围

本模块覆盖 gossip 状态传播、failure detector 和 internode messaging 基础设施，作为启动、拓扑变更和读写复制的通信背景。

## 设计目标

Gossip、Failure Detector 和 Messaging 共同支撑 Cassandra 的分布式控制面和数据面通信：

- Gossip 传播成员状态、token、schema/version、DC/rack、native/rpc readiness、shutdown/left/moving 等 endpoint application state。
- Failure Detector 根据 gossip 心跳到达间隔判断 endpoint 是否可疑，并把 conviction 事件交给 `Gossiper` 改变 alive/down 状态。
- MessagingService 为 gossip、read、write、schema、repair、snapshot 等 verb 提供统一的 internode send/receive/callback/timeout/drop-metrics 框架。
- 启动、bootstrap、replace、decommission、read/write coordinator 都依赖这三者提供的 endpoint 可达性、状态传播和消息投递语义。

## 解决的问题

- 分布式 membership 不能依赖中心节点：`Gossiper.GossipTask` 每轮构建 digest，随机向 live/unreachable/seed 节点发送 `GOSSIP_DIGEST_SYN`，见 `src/java/org/apache/cassandra/gms/Gossiper.java:337-387`。
- 节点状态需要可增量合并：`EndpointState` 持有 `HeartBeatState` 与 `ApplicationState -> VersionedValue` map，更新时使用 immutable view + CAS，见 `src/java/org/apache/cassandra/gms/EndpointState.java:56-90`、`src/java/org/apache/cassandra/gms/EndpointState.java:151-175`。
- 网络超时不能只靠 socket close：`FailureDetector.report()` 收集到达间隔，`interpret()` 用 phi 与 `phi_convict_threshold` 比较并通知 listener，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:313-378`。
- 控制消息和数据消息需要共享连接管理，但避免大消息阻塞小消息：`MessagingService` 注释说明 urgent/small/large 三类连接，见 `src/java/org/apache/cassandra/net/MessagingService.java:91-115`。
- 请求/响应需要 timeout 和 failure callback：`sendWithCallback()` 注册 callback 后发送，`RequestCallbacks.expire()` 到期触发 failure，见 `src/java/org/apache/cassandra/net/MessagingService.java:397-407`、`src/java/org/apache/cassandra/net/RequestCallbacks.java:124-158`。

## 设计取舍

- Gossip 是 eventually consistent，不保证单轮收敛；它用 digest 比较 generation/version，只交换缺失或较新的状态，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1940-2004`。
- Failure Detector 只做 suspicion/conviction，不直接修改 token metadata；`Gossiper` 注册为 listener，收到 conviction 后在 gossip stage 标记 down，见 `src/java/org/apache/cassandra/gms/Gossiper.java:405-408`、`src/java/org/apache/cassandra/gms/Gossiper.java:600-627`。
- Gossip state mutation 被约束在 `Stage.GOSSIP`，非法线程会按严格运行时检查抛错或记录 no-spam error，见 `src/java/org/apache/cassandra/gms/Gossiper.java:316-335`。
- 新节点启动前使用 shadow round 读取 seeds/peers 的状态，但不写入本地 `endpointStateMap`，用于 replace 和 endpoint collision 检查，见 `src/java/org/apache/cassandra/gms/Gossiper.java:2039-2058`。
- Messaging callbacks 使用 `(id, peer)` 作为 key，因为 4.0+ 允许同一逻辑请求复用 request id，见 `src/java/org/apache/cassandra/net/RequestCallbacks.java:55-64`。
- P0 urgent verb 走 urgent connection，但如果消息体超过 large threshold 仍会进入 large connection 并记录 warn，见 `src/java/org/apache/cassandra/net/OutboundConnections.java:210-234`。

## 核心类

| 类 | 作用 |
|---|---|
| `Gossiper` | membership 状态机、周期 gossip、seed/live/unreachable 集合、shadow round、endpoint up/down/left 事件。启动见 `src/java/org/apache/cassandra/gms/Gossiper.java:2006-2031` |
| `EndpointState` | 单个 endpoint 的 heartbeat 与 application states。定义见 `src/java/org/apache/cassandra/gms/EndpointState.java:47-90` |
| `HeartBeatState` | gossip generation 与 heartbeat version。定义见 `src/java/org/apache/cassandra/gms/HeartBeatState.java:27-83` |
| `ApplicationState` | gossip 传播的 state key 枚举，ordinal 不能重排。定义见 `src/java/org/apache/cassandra/gms/ApplicationState.java:20-75` |
| `VersionedValue` | application state value + version，包含 `BOOT`、`NORMAL`、`LEFT`、`SHUTDOWN` 等状态字符串。定义见 `src/java/org/apache/cassandra/gms/VersionedValue.java:49-105` |
| `FailureDetector` | phi accrual failure detector、JMX MBean、arrival window 管理。定义见 `src/java/org/apache/cassandra/gms/FailureDetector.java:64-108` |
| `MessagingService` | internode messaging facade，负责 send、callback、inbound/outbound sockets、shutdown。定义见 `src/java/org/apache/cassandra/net/MessagingService.java:207-335` |
| `Verb` | internode message 类型、stage、priority、timeout、serializer、handler 和 response verb 绑定。定义见 `src/java/org/apache/cassandra/net/Verb.java:113-160` |
| `Message` | message header/payload、id、verb、created/expires time、response/failure builders。定义见 `src/java/org/apache/cassandra/net/Message.java:72-140`、`src/java/org/apache/cassandra/net/Message.java:285-315` |
| `RequestCallbacks` | outbound callback registry、timeout reaper、failure callback 调度。定义见 `src/java/org/apache/cassandra/net/RequestCallbacks.java:58-72` |
| `InboundMessageHandlers` | 每 peer inbound connection handlers、resource limits、counters 和 inbound metrics。定义见 `src/java/org/apache/cassandra/net/InboundMessageHandlers.java:43-69` |
| `OutboundConnections` | 每 peer urgent/small/large outbound pool 和 connection selection。定义见 `src/java/org/apache/cassandra/net/OutboundConnections.java:58-89` |

## 核心接口

- `IEndpointStateChangeSubscriber`：`Gossiper` 在 alive/dead/change 等状态变化时通知 subscriber；`doOnChangeNotifications()` 遍历 subscribers，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1847-1863`。
- `IFailureDetectionEventListener`：Failure Detector conviction 回调接口，`Gossiper` 实现并注册，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:394-402`。
- `IVerbHandler<T>`：MessagingService inbound dispatch 的 handler 接口，默认 sink 调用 `message.header.verb.handler().doVerb(...)`，见 `src/java/org/apache/cassandra/net/InboundSink.java:34-79`。
- `RequestCallback<T>`：send-with-callback 的成功/失败回调，由 `ResponseVerbHandler` 在 response 到达时调用，见 `src/java/org/apache/cassandra/net/ResponseVerbHandler.java:36-59`。
- `InboundMessageHandlers.MessageConsumer`：inbound handlers 处理 message 或 fail 的消费接口，见 `src/java/org/apache/cassandra/net/InboundMessageHandlers.java:83-86`。

## 核心数据结构

- `endpointStateMap`：`Gossiper` 的 endpoint -> `EndpointState` 主状态表；`applyStateLocally()` 用 remote generation/max version 决定是否接收、忽略或请求更多状态，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1710-1784`。
- `liveEndpoints` / `unreachableEndpoints` / `seeds` / `justRemovedEndpoints`：分别用于 gossip 目标选择、down endpoint 探测、seed fallback 和 removal quarantine。
- `GossipDigest`：每个 endpoint 的 `(endpoint, generation, maxVersion)` 摘要，用于决定 ACK 中发送 delta state 还是请求远端 state，见 `src/java/org/apache/cassandra/gms/Gossiper.java:811-832`。
- `EndpointState.View`：heartbeat 和 application state 的快照 view，`AtomicReference<View>` 保证更新可见性，见 `src/java/org/apache/cassandra/gms/EndpointState.java:56-90`。
- `ArrivalWindow`：Failure Detector 的 bounded arrival interval 样本，默认 sample size 1000，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:73-102`、`src/java/org/apache/cassandra/gms/FailureDetector.java:490-533`。
- `CallbackKey(id, peer)`：`RequestCallbacks` callback map key，避免同 id 不同 peer 响应冲突，见 `src/java/org/apache/cassandra/net/RequestCallbacks.java:192-215`。
- `OutboundConnections.small/large/urgent`：每 peer 三条 outbound connection，用 message size 和 verb priority 选路，见 `src/java/org/apache/cassandra/net/OutboundConnections.java:76-88`、`src/java/org/apache/cassandra/net/OutboundConnections.java:210-234`。

## 生命周期

启动时：

```text
StorageService.initServer()
  -> Gossiper.instance.register(StorageService)
  -> Gossiper.instance.start(generation, appStates)
     -> buildSeedsList()
     -> maybeInitializeLocalState()
     -> add preload application states
     -> endpoint snitch gossiperStarting()
     -> schedule GossipTask every interval
  -> MessagingService.instance().listen()
```

周期 gossip：

```text
GossipTask.run()
  -> MessagingService.waitUntilListening()
  -> update local heartbeat
  -> makeGossipDigest()
  -> send GOSSIP_DIGEST_SYN to a random live member
  -> maybe gossip to unreachable member
  -> maybe gossip to seed
  -> doStatusCheck()
     -> FailureDetector.interpret(endpoint)
     -> maybe remove fat clients / expired dead state / quarantine entries
```

Failure Detector：

```text
Gossip ACK/ACK2 contains remote EndpointState
  -> Gossiper.notifyFailureDetector(epStateMap)
     -> FailureDetector.report(endpoint)
        -> ArrivalWindow.add(now)
GossipTask.doStatusCheck()
  -> FailureDetector.interpret(endpoint)
     -> if phi crosses threshold
        -> listener.convict(endpoint, phi)
           -> Gossiper.convict()
              -> markDead() or markAsShutdown()
```

Messaging：

```text
Sender
  -> Message.out(verb, payload)
  -> MessagingService.sendWithCallback(...) or send(...)
     -> callbacks.addWithExpiration(...) when needed
     -> outboundSink.accept(...)
     -> getOutbound(peer)
     -> OutboundConnections.enqueue(...)
        -> choose urgent/small/large connection

Receiver
  -> InboundSockets / InboundMessageHandlers
  -> InboundSink.accept(message)
     -> message.verb().handler().doVerb(message)
  -> handler sends response
  -> ResponseVerbHandler removes callback and invokes onResponse/onFailure
```

## 调用链

- Gossip task 等待 messaging listen、更新 heartbeat、构造 digest 并发送 SYN，见 `src/java/org/apache/cassandra/gms/Gossiper.java:337-361`。
- live/unreachable/seed gossip 目标选择在 `doGossipToLiveMember()`、`maybeGossipToUnreachableMember()`、`maybeGossipToSeed()`，发送点在 `sendGossip()`，见 `src/java/org/apache/cassandra/gms/Gossiper.java:984-1002`。
- SYN handler 校验 cluster/partitioner、构建 ACK，并调用 `MessagingService.send()`，见 `src/java/org/apache/cassandra/gms/GossipDigestSynVerbHandler.java:42-122`。
- ACK handler 接收 remote state，先 `notifyFailureDetector()`，再 `applyStateLocally()`，然后按 digest 请求回传 ACK2，见 `src/java/org/apache/cassandra/gms/GossipDigestAckVerbHandler.java:41-102`。
- ACK2 handler 接收最终 delta state，同样通知 FD 并本地应用，见 `src/java/org/apache/cassandra/gms/GossipDigestAck2VerbHandler.java:34-52`。
- 状态合并按 generation 和 max version 决定 major state change、apply new states、mark alive 或 ignore，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1710-1784`。
- `applyNewStates()` 对 `STATUS/STATUS_WITH_PORT` 优先通知，避免 `BOOT_REPLACE` 等状态处理顺序错误，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1788-1844`。
- `markAlive()` 先发送 `ECHO_REQ`，成功响应后才 `realMarkAlive()`，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1437-1494`。
- `markDead()` 标记 down 并通知 subscribers，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1501-1515`。
- `MessagingService.send()` 走 outbound sink 和 `doSend()`，入队到 `OutboundConnections`，见 `src/java/org/apache/cassandra/net/MessagingService.java:452-485`。
- `ResponseVerbHandler.doVerb()` 按 `(message.id, from)` 移除 callback，记录 latency 并调用 response/failure callback，见 `src/java/org/apache/cassandra/net/ResponseVerbHandler.java:36-59`。

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| `storage_port` / `ssl_storage_port` | `src/java/org/apache/cassandra/config/Config.java:214-215`，模板 `conf/cassandra.yaml:958-966` | internode 普通/legacy SSL 端口 |
| `listen_address` / `broadcast_address` | `src/java/org/apache/cassandra/config/Config.java:216-220`，模板 `conf/cassandra.yaml:968-1003` | internode bind 与对外通告地址 |
| `internode_authenticator` | `src/java/org/apache/cassandra/config/Config.java:221`，模板 `conf/cassandra.yaml:1005` | server-to-server 连接认证入口 |
| `request_timeout` | `src/java/org/apache/cassandra/config/Config.java:141-142`，模板 `conf/cassandra.yaml:1346-1349` | miscellaneous/request-response 默认超时 |
| `read_request_timeout` / `range_request_timeout` / `write_request_timeout` | `src/java/org/apache/cassandra/config/Config.java:144-151`，模板 `conf/cassandra.yaml:1322-1330` | read/write verb timeout 来源 |
| `repair_request_timeout` | `src/java/org/apache/cassandra/config/Config.java:162-163` | repair verb timeout 来源 |
| `internode_timeout` | `src/java/org/apache/cassandra/config/Config.java:169-170`，模板 `conf/cassandra.yaml:1400-1408` | 是否交换跨节点 request timeout 创建时间 |
| `phi_convict_threshold` | `src/java/org/apache/cassandra/config/Config.java:177`，模板 `conf/cassandra.yaml:1469-1471` | FD conviction 阈值 |
| `failure_detector` | `src/java/org/apache/cassandra/config/Config.java:431` | FD 实现类名 |
| `internode_socket_send_buffer_size` / `internode_socket_receive_buffer_size` | `src/java/org/apache/cassandra/config/Config.java:241-246`，模板 `conf/cassandra.yaml:1111-1127` | internode socket buffer |
| `internode_application_*_queue_*` | `src/java/org/apache/cassandra/config/Config.java:249-261`，模板 `conf/cassandra.yaml:1370-1391` | outbound/inbound message queue 容量和 reserve 限制 |
| `internode_tcp_connect_timeout` / `internode_tcp_user_timeout` | `src/java/org/apache/cassandra/config/Config.java:263-272`，模板 `conf/cassandra.yaml:1351-1363` | internode TCP 建连与 unacked data timeout |
| `server_encryption_options.internode_encryption` | `src/java/org/apache/cassandra/config/Config.java:433`，模板 `conf/cassandra.yaml:1619-1655` | internode TLS 策略 |
| `internode_compression` | `src/java/org/apache/cassandra/config/Config.java:436`，模板 `conf/cassandra.yaml:1730-1742` | internode 压缩策略 |
| `consecutive_message_errors_threshold` / `internode_error_reporting_exclusions` | `src/java/org/apache/cassandra/config/Config.java:855-858` | message parse/error reporting guardrails |

## Metrics

- `FailureDetector` 暴露 MBean `org.apache.cassandra.net:type=FailureDetector`，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:69-108`。
- `MessagingMetrics.CrossNodeLatency` 与 per-DC latency timer 定义见 `src/java/org/apache/cassandra/metrics/MessagingMetrics.java:96-121`。
- 每个 verb 的 `WaitLatency` timer 在 `MessagingMetrics` 构造器中注册，见 `src/java/org/apache/cassandra/metrics/MessagingMetrics.java:103-112`。
- dropped message metrics 记录 internal/cross-node dropped latency 和 count，见 `src/java/org/apache/cassandra/metrics/MessagingMetrics.java:129-170`。
- dropped message 定期日志和 `StatusLogger.log()` 触发见 `src/java/org/apache/cassandra/metrics/MessagingMetrics.java:172-219`。
- inbound per-peer metrics 包括 received/scheduled/processed/expired/error/throttled/corrupt frame，见 `src/java/org/apache/cassandra/metrics/InternodeInboundMetrics.java:50-68`。
- outbound per-peer metrics 包括 small/large/urgent pending/completed/dropped/overload/timeout/error，见 `src/java/org/apache/cassandra/metrics/InternodeOutboundMetrics.java:35-155`。
- expired callbacks 通过 `InternodeOutboundMetrics.totalExpiredCallbacks` 和 per-peer `expiredCallbacks` 记录，见 `src/java/org/apache/cassandra/metrics/InternodeOutboundMetrics.java:35-40`、`src/java/org/apache/cassandra/net/RequestCallbacks.java:149-157`。

## 日志

- Gossip task 异常记录 `Gossip error`，见 `src/java/org/apache/cassandra/gms/Gossiper.java:390-394`。
- Gossip stage 堆积时跳过 status check 并警告不会 mark down，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1134-1145`。
- FD 本地 pause 过长时不 mark down 并记录 warn/debug，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:342-355`。
- PHI 接近或超过阈值时 trace/debug，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:356-377`。
- endpoint up/down 日志分别在 `realMarkAlive()` 和 `markDead()`，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1481-1494`、`src/java/org/apache/cassandra/gms/Gossiper.java:1501-1515`。
- SYN cluster/partitioner mismatch 记录 warn 并丢弃，见 `src/java/org/apache/cassandra/gms/GossipDigestSynVerbHandler.java:54-66`。
- `MessagingService.shutdown()` 记录 quiesce、shutdown 状态，见 `src/java/org/apache/cassandra/net/MessagingService.java:565-630`。
- dropped messages 每 5 秒聚合日志，见 `src/java/org/apache/cassandra/metrics/MessagingMetrics.java:172-219`。

## 运维关注点

- `nodetool statusgossip` 只能说明本地 gossip task 是否启用；endpoint 是否 alive 仍取决于 gossip state 和 FD arrival samples。
- `phi_convict_threshold` 调低会更快判 down，但更容易在 GC pause、网络抖动、gossip stage 堆积时误判。
- 如果看到 “Gossip stage has pending tasks; skipping status check”，短期内节点不会被 FD 标记 down，集群视图可能延迟更新。
- `GOSSIP_DIGEST_SYN` 的 cluster name 或 partitioner mismatch 会被直接忽略；跨集群误连通常表现为 gossip 不收敛。
- `internode_application_*_queue_*` 与 outbound/inbound dropped/overload metrics 要一起看；queue 太小会 drop，太大可能扩大内存占用和尾延迟。
- `internode_timeout` 依赖时钟大致同步；配置模板明确提示 Cassandra 普遍假定集群已配置 NTP，见 `conf/cassandra.yaml:1400-1408`。
- down endpoint 的 outbound connection 会延迟 close；endpoint removal 还会清理 inbound metrics，见 `src/java/org/apache/cassandra/gms/Gossiper.java:738-745`、`src/java/org/apache/cassandra/net/MessagingService.java:499-524`。
- graceful shutdown 会 gossip `SHUTDOWN` 并向 live endpoints 发送 `GOSSIP_SHUTDOWN`，见 `src/java/org/apache/cassandra/gms/Gossiper.java:2284-2303`。

## 性能瓶颈

- Gossip stage backlog 会阻塞 membership 状态合并和 FD status check，是 UP/DOWN 延迟的直接来源。
- 大量 endpoint/application state 会增加每轮 digest/state 序列化与网络开销；`EndpointStateSerializer` 序列化全部 application states，见 `src/java/org/apache/cassandra/gms/EndpointState.java:357-404`。
- urgent connection 保护 gossip/read-repair 等小控制消息，但 P0 大消息仍可能被转入 large connection 并触发 warn。
- Callback map 过大或 response 超时会增加 `Callback-Map-Reaper` 扫描成本，并提高 expired callback/dropped metrics。
- Inbound/outbound reserve capacity 用于保护内存；持续 throttle/overload 说明 message 生产速度超过消费速度。

## 常见故障

- 节点误判 DOWN：检查 GC pause、本地 pause 日志、`phi_convict_threshold`、gossip stage backlog、网络丢包和 seed 可达性。
- 新节点启动/replace 卡住：重点看 shadow round 是否能从 seed 得到非空 ACK，见 `src/java/org/apache/cassandra/gms/Gossiper.java:2039-2122`、`src/java/org/apache/cassandra/gms/Gossiper.java:2319-2357`。
- `ClusterName mismatch` / `Partitioner mismatch`：通常是配置错误或端口误连，SYN handler 会丢弃该 gossip message。
- `ReadTimeout` / `WriteTimeout` 伴随 expired callbacks：查看 `RequestCallbacks.onExpired()`、per-peer outbound `TotalTimeouts` 和相关 verb timeout 配置。
- internode dropped/overload：查看 `MessagingMetrics` dropped 日志、`InternodeOutboundMetrics` small/large/urgent dropped due to overload/timeout/error。
- gossip 不收敛但 messaging 正常：检查 seed list、`listen_address`/`broadcast_address`、firewall 的 `storage_port`、server encryption/internode compression 是否一致。

## 测试用例

- `test/unit/org/apache/cassandra/gms/FailureDetectorTest.java`
- `test/unit/org/apache/cassandra/gms/GossipDigestTest.java`
- `test/unit/org/apache/cassandra/gms/GossipShutdownTest.java`
- `test/unit/org/apache/cassandra/gms/GossiperTest.java`
- `test/unit/org/apache/cassandra/net/MessageTest.java`
- `test/unit/org/apache/cassandra/net/MessageSerializationPropertyTest.java`
- `test/unit/org/apache/cassandra/net/MessagingServiceTest.java`
- `test/unit/org/apache/cassandra/net/MockMessagingServiceTest.java`
- `test/unit/org/apache/cassandra/net/OutboundConnectionSettingsTest.java`
- `test/unit/org/apache/cassandra/net/OutboundConnectionsTest.java`
- `test/unit/org/apache/cassandra/net/OutboundMessageQueueTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/GossipTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/GossipSettlesTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/GossipShutdownTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/LargeMessageTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/MessageFiltersTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/MessageForwardingTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/MessageTimestampTest.java`

## 待继续

- 第二轮已在 `research/module-gossip-messaging-deep-dive.md` 展开 Netty inbound/outbound frame encoder/decoder、协议版本协商、TLS handshake、snitch/preferred IP、endpoint lifecycle subscriber、JMX/nodetool 和 cross-DC write forwarding。
- 第三轮已在 `research/module-messaging-verb-semantics.md` 补齐 repair/schema/hints/batchlog/gossip 等 internode `Verb` 的 stage、timeout、connection、failure callback、params 和 metrics 语义矩阵。
- 第四轮已新增 `research/tools/check-messaging-verb-matrix-drift.py` 和 `research/module-messaging-verb-drift-checker.md`，检查 `Verb.java` 的 87 个常量是否进入 messaging matrix。
- 继续补 preferred IP reconnect 的 distributed test，尤其是 public seed/private reconnect、authenticator reject 和 same-DC gate。
- 继续补 TLS optional/strict 与 `internode_compression` 的 mixed-version distributed test，确认 messaging frame negotiation 与 streaming compression 分层。
- 可选把 messaging verb drift checker 接入 CI 或 pre-commit。
