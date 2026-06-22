# Module: Gossip Messaging Deep Dive

本页是 `module-gossip-messaging.md` 的第二轮源码补充，聚焦第一轮留下的 snitch/preferred IP、endpoint lifecycle subscriber、Failure Detector JMX/nodetool、Netty internode handshake/TLS/frame、message forwarding 边界。

## 范围

- Gossip topology metadata：`DC`、`RACK`、`INTERNAL_ADDRESS_AND_PORT`、legacy `INTERNAL_IP`、`RPC_ADDRESS`/`NATIVE_ADDRESS_AND_PORT`、`NET_VERSION` 等 application state 的发布、过滤和消费。
- Snitch 与 preferred IP：`GossipingPropertyFileSnitch`、`Ec2MultiRegionSnitch`、`ReconnectableSnitchHelper` 如何把 gossip 中的 internal address 转成 `MessagingService.maybeReconnectWithNewIp()`。
- Endpoint lifecycle：低层 `IEndpointStateChangeSubscriber` 与高层 `IEndpointLifecycleSubscriber` 的职责边界。
- Failure Detector 运维入口：`FailureDetectorMBean`、`GossiperMBean`、`nodetool failuredetector/gossipinfo/statusgossip/enablegossip/disablegossip` 到 `NodeProbe`/JMX 的调用。
- Internode wire protocol：`HandshakeProtocol`、`OutboundConnectionInitiator`、`InboundConnectionInitiator`、TLS optional/reject/strict 路径、版本协商、CRC/LZ4/unprotected frame encoder/decoder。
- Cross-DC write forwarding：`Message` params、`ForwardingInfo`、`StorageProxy.sendMessagesToNonlocalDC()`、`MutationVerbHandler.forwardToLocalNodes()` 和 callback expiry。

不展开 native CQL protocol；native 协议在 `module-native-protocol.md`、`flow-native-protocol.md` 覆盖。不重复 repair streaming 的 Netty streaming 文件传输；streaming 侧 handshake 在 `module-repair-streaming-autorepair-netty.md` 覆盖。

## 设计目标

- 让 membership metadata 和 topology metadata 在没有中心协调者的情况下收敛，并让 snitch/replica planning 能读取 DC/rack 信息。
- 支持云/多区域部署：公开地址用于跨区域发现和连接，发现同 DC internal address 后切换 preferred IP，典型实现见 `src/java/org/apache/cassandra/locator/ReconnectableSnitchHelper.java:35-80`。
- 让 operator 能通过 JMX/nodetool 观察和控制 gossip、FD、messaging，而不绕过 `StorageService` 状态检查。
- 让 internode messaging 在 mixed-version、TLS optional/strict、compression policy 和 frame integrity 之间协商出可用连接。
- 降低跨 DC 写放大：coordinator 对每个远端 DC 只直接发送到一个 replica，再由该 replica 转发给同 DC 其他 replicas，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1601-1635`。

## 解决的问题

- Snitch 数据来源不一致：本地节点用配置，远端节点优先读 gossip `DC`/`RACK`，缺失时 fallback 到 `system.peers` 保存信息或 property snitch/default，见 `src/java/org/apache/cassandra/locator/GossipingPropertyFileSnitch.java:86-134`。
- Legacy application state 共存：`Gossiper.applyNewStates()` 在本地 state 已含新字段时跳过 `INTERNAL_IP` 和 `RPC_ADDRESS` legacy change notification，避免重复/回退通知，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1838-1844`。
- FD 误判：`FailureDetector.interpret()` 在本地 pause 超阈值时暂停 mark-down，并用 `PHI_FACTOR * phi` 与配置阈值比较，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:335-378`。
- TLS 迁移：inbound pipeline 根据 `server_encryption_options` 选择 `RejectSslHandler`、`OptionalSslHandler` 或 `SslHandler`，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:117-141`。
- Mixed-version 连接：`HandshakeProtocol.Initiate` 发送可接受版本上下界，`Accept` 返回 peer max 和 negotiated version，见 `src/java/org/apache/cassandra/net/HandshakeProtocol.java:55-181`、`src/java/org/apache/cassandra/net/HandshakeProtocol.java:213-274`。
- Cross-DC write callback：forwarded targets 也注册 callback；原始 forwarding message expire 时，`RequestCallbacks` 同步 expire forwarding targets，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1615-1626`、`src/java/org/apache/cassandra/net/RequestCallbacks.java:292-299`。

## 设计取舍

- Gossip subscriber 是低层状态通知，高层 lifecycle subscriber 是 `StorageService` 聚合后的 cluster event；这避免所有模块直接解释 `STATUS_WITH_PORT`、`RPC_READY`、token metadata 状态。
- Preferred IP 切换只在 internode authenticator 允许且 snitch 判断 peer 在本地 DC 时触发，避免把跨 DC 公网连接错误切到不可达私网，见 `src/java/org/apache/cassandra/locator/ReconnectableSnitchHelper.java:66-80`。
- `INTERNAL_ADDRESS_AND_PORT` 与 legacy `INTERNAL_IP` 双写保留兼容性；`GossipingPropertyFileSnitch.gossiperStarting()` 和 `Ec2MultiRegionSnitch.gossiperStarting()` 都发布两者，见 `src/java/org/apache/cassandra/locator/GossipingPropertyFileSnitch.java:136-146`、`src/java/org/apache/cassandra/locator/Ec2MultiRegionSnitch.java:76-92`。
- TLS optional 模式通过读前 5 字节检测是否 SSL；这利于滚动迁移，但要求 operator 清楚 transitional mode 的窗口，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:541-571`。
- CRC frame 和 LZ4 frame 都有 header CRC24 和 payload CRC32；unprotected frame 只保留 frame header，不做 payload protection，见 `src/java/org/apache/cassandra/net/FrameDecoderCrc.java:29-156`、`src/java/org/apache/cassandra/net/FrameDecoderLZ4.java:31-165`、`src/java/org/apache/cassandra/net/FrameEncoderUnprotected.java:28-64`。
- Cross-DC forwarding 随机选择 severity 为 0 的远端 replica 作为 forwarder；这减少 coordinator 出站 fanout，但让被选 forwarder 承担本 DC fanout，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1637-1642`。
- `MessagingService.current_version` 受 `storage_compatibility_mode` 影响，daemon 只接受 `minimum_version..current_version` 的 messaging，streaming 更严格地使用 current-only，见 `src/java/org/apache/cassandra/net/MessagingService.java:211-271`。

## 核心类

| 类 | 责任 |
|---|---|
| `Gossiper` | 管理 endpoint state map、subscribers、legacy state filtering、FD notification、本地 application state。构造时注册 FD listener/JMX/内置 release-version subscriber，见 `src/java/org/apache/cassandra/gms/Gossiper.java:404-440` |
| `GossipingPropertyFileSnitch` | 从本地 rackdc 配置和远端 gossip state 提供 DC/rack，并注册 `ReconnectableSnitchHelper`，见 `src/java/org/apache/cassandra/locator/GossipingPropertyFileSnitch.java:86-158` |
| `Ec2MultiRegionSnitch` | 使用 EC2 public IP 作为 broadcast/rpc address，gossip private IP 并注册 reconnect helper，见 `src/java/org/apache/cassandra/locator/Ec2MultiRegionSnitch.java:61-92` |
| `ReconnectableSnitchHelper` | 监听 gossip join/change/alive，解析 internal address 并调用 preferred IP reconnect，见 `src/java/org/apache/cassandra/locator/ReconnectableSnitchHelper.java:47-129` |
| `FailureDetector` | arrival window、phi 计算、MBean、conviction listener、force conviction，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:69-108`、`src/java/org/apache/cassandra/gms/FailureDetector.java:313-386` |
| `MessagingService` | internode send facade、versions、inbound/outbound pools、preferred IP reconnect、metrics/JMX facade，见 `src/java/org/apache/cassandra/net/MessagingService.java:207-335`、`src/java/org/apache/cassandra/net/MessagingService.java:541-560` |
| `HandshakeProtocol` | Initiate/Accept handshake message encode/decode、version bounds、connection type、framing、CRC，见 `src/java/org/apache/cassandra/net/HandshakeProtocol.java:41-181`、`src/java/org/apache/cassandra/net/HandshakeProtocol.java:213-274` |
| `OutboundConnectionInitiator` | outbound Netty bootstrap、preconnect auth、TLS handler、server auth、handshake decode、frame encoder insertion，见 `src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:139-181`、`src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:216-239`、`src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:336-399` |
| `InboundConnectionInitiator` | inbound Netty pipeline、TLS policy、client auth、handshake accept、frame decoder/inbound handler setup，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:100-141`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:312-362`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:467-516` |
| `FrameDecoder*` / `FrameEncoder*` | CRC/LZ4/unprotected frame layout、payload allocator、corrupt frame classification、pipeline handler name，见 `src/java/org/apache/cassandra/net/FrameDecoder.java:34-54`、`src/java/org/apache/cassandra/net/FrameEncoder.java:30-137` |
| `ForwardingInfo` | inter-DC write forwarding 的 target -> message id 容器和 serializer，见 `src/java/org/apache/cassandra/net/ForwardingInfo.java:36-114` |
| `MutationVerbHandler` | replica 端处理 mutation，转发本 DC targets 并把 response 发送回 coordinator，见 `src/java/org/apache/cassandra/db/MutationVerbHandler.java:44-93` |

## 核心接口

- `IEndpointStateChangeSubscriber`：低层 gossip state 订阅接口，包含 join/beforeChange/change/alive/dead/remove/restart，见 `src/java/org/apache/cassandra/gms/IEndpointStateChangeSubscriber.java:22-58`。
- `IEndpointLifecycleSubscriber`：高层 cluster lifecycle 订阅接口，暴露 join/leave/up/down/move，强调它不是原始 gossip join，见 `src/java/org/apache/cassandra/service/IEndpointLifecycleSubscriber.java:22-67`。
- `FailureDetectorMBean`：FD JMX 接口，暴露 inter-arrival dump、phi threshold、endpoint states、up/down count、phi values，见 `src/java/org/apache/cassandra/gms/FailureDetectorMBean.java:26-54`。
- `GossiperMBean`：gossip JMX 接口，暴露 endpoint downtime/current generation、assassinate、reload seeds、release versions、gossip vs token metadata compare，见 `src/java/org/apache/cassandra/gms/GossiperMBean.java:24-50`。
- `MessageDelivery`：response/failure response 统一发送到 `message.respondTo()`，forwarded write 依赖该抽象保持 coordinator response path，见 `src/java/org/apache/cassandra/net/MessageDelivery.java:29-35`。
- `FrameDecoder.FrameProcessor`：frame decoder 不通过 Netty pipeline 直接向上游传递 frame，而是注册 processor 并用 boolean 返回值做流控，见 `src/java/org/apache/cassandra/net/FrameDecoder.java:63-72`。

## 核心数据结构

- `EndpointState` application state：本地启动时加入 `NET_VERSION`、`HOST_ID`、`RPC_ADDRESS`、`INTERNAL_ADDRESS_AND_PORT`、`RELEASE_VERSION`，见 `src/java/org/apache/cassandra/gms/Gossiper.java:2398-2405`。
- `subscribers`：`Gossiper.register()`/`unregister()` 维护 `IEndpointStateChangeSubscriber` 集合，change notification 逐个调用，见 `src/java/org/apache/cassandra/gms/Gossiper.java:477-497`、`src/java/org/apache/cassandra/gms/Gossiper.java:1856-1863`。
- `lifecycleSubscribers`：`StorageService` 的 `CopyOnWriteArrayList`，由 `register()`/`unregister()` 管理，高层事件由 `notifyUp/Down/Joined/Moved/Left` 分发，见 `src/java/org/apache/cassandra/service/StorageService.java:498`、`src/java/org/apache/cassandra/service/StorageService.java:570-578`、`src/java/org/apache/cassandra/service/StorageService.java:3032-3065`。
- `EndpointMessagingVersions`：endpoint -> advertised messaging version map，维护 `minClusterVersion`，对外 `get()` 会 cap 到本地 current version，见 `src/java/org/apache/cassandra/net/EndpointMessagingVersions.java:31-99`。
- `AcceptVersions`：handshake 使用的 min/max version bounds，在 `Initiate` 和 inbound settings 中决定可接受协议区间，见 `src/java/org/apache/cassandra/net/HandshakeProtocol.java:92-105`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:331-339`。
- `FrameDecoder.IntactFrame` / `CorruptFrame`：完整 frame payload 与 recoverable/unrecoverable corrupt frame；header corrupt 通常不可恢复，payload corrupt 可能可跳过，见 `src/java/org/apache/cassandra/net/FrameDecoder.java:89-168`。
- `ParamType.FORWARD_TO` / `RESPOND_TO`：message params map 的 forwarding 参数，新增 params 不需要 bump messaging version，未知 params 可跳过，见 `src/java/org/apache/cassandra/net/ParamType.java:33-47`。
- `MessageFlag`：boolean flag 不放入 params，而是扩展 flags bitset；目前包含 callback-on-failure、track repaired data、track warnings，见 `src/java/org/apache/cassandra/net/MessageFlag.java:22-84`。

## 生命周期

### Gossip topology metadata

1. 启动时 `StorageService` 注册自己为 gossip subscriber，并用本地 app states 启动 gossiper，见 `src/java/org/apache/cassandra/service/StorageService.java:1216-1219`。
2. Snitch 的 `gossiperStarting()` 发布 internal address app states；`GossipingPropertyFileSnitch` 还注册可替换旧 helper 的 `ReconnectableSnitchHelper`，见 `src/java/org/apache/cassandra/locator/GossipingPropertyFileSnitch.java:136-158`。
3. 收到 remote state 后，`Gossiper.applyNewStates()` 过滤 legacy states，再调用 `doOnChangeNotifications()`，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1838-1863`。
4. `StorageService.onJoin()` 先处理 `STATUS_WITH_PORT`/`STATUS`，再处理其他 app states，确保 token metadata 成员关系先建立，见 `src/java/org/apache/cassandra/service/StorageService.java:3847-3869`。
5. `StorageService.onChange()` 将 `DC`/`RACK` 写入 peer info 并更新 topology，将 `NET_VERSION` 写入 `MessagingService.instance().versions`，见 `src/java/org/apache/cassandra/service/StorageService.java:2870-2914`、`src/java/org/apache/cassandra/service/StorageService.java:2934-2944`。
6. `RPC_READY` change 或 gossip alive/dead 触发高层 `notifyUp/notifyDown`，join/move/left 由 token metadata 状态处理后触发，见 `src/java/org/apache/cassandra/service/StorageService.java:3024-3065`、`src/java/org/apache/cassandra/service/StorageService.java:3386-3400`、`src/java/org/apache/cassandra/service/StorageService.java:3531-3536`、`src/java/org/apache/cassandra/service/StorageService.java:3872-3889`。

### Preferred IP reconnect

1. `Ec2MultiRegionSnitch` 构造时把 public IP 设置为 broadcast/rpc address，用于跨区域发现，见 `src/java/org/apache/cassandra/locator/Ec2MultiRegionSnitch.java:61-74`。
2. gossiper start 时发布 private/internal address 并注册 reconnect helper，见 `src/java/org/apache/cassandra/locator/Ec2MultiRegionSnitch.java:76-92`。
3. helper 在 onJoin/onChange/onAlive 中优先读取 `INTERNAL_ADDRESS_AND_PORT`，必要时 fallback 到 legacy `INTERNAL_IP`，见 `src/java/org/apache/cassandra/locator/ReconnectableSnitchHelper.java:88-129`。
4. `ReconnectableSnitchHelper.reconnect()` 先做 `OUTBOUND_PRECONNECT` authenticator 校验，再要求 peer DC 等于 local DC，最后调用 `MessagingService.maybeReconnectWithNewIp()`，见 `src/java/org/apache/cassandra/locator/ReconnectableSnitchHelper.java:66-80`。
5. `MessagingService.maybeReconnectWithNewIp()` 先写 `SystemKeyspace.updatePreferredIP()`，再对已存在 outbound pool 调 `reconnectWithNewIp(preferredAddress)`，见 `src/java/org/apache/cassandra/net/MessagingService.java:541-560`。

### Failure Detector 运维

1. `Gossiper` 从 ACK/ACK2 remote states 调 `notifyFailureDetector()`，只有 generation/version 条件合适时才报告 heartbeat，到达间隔进入 FD samples，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1384-1412`。
2. `FailureDetector.report()` 更新 `ArrivalWindow`，`interpret()` 计算 phi 并通知 listeners convict，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:313-378`。
3. `FailureDetector` 构造时注册 MBean `org.apache.cassandra.net:type=FailureDetector`，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:69-108`。
4. `NodeProbe` 建立 FD MBean proxy，并由 `failuredetector`/`gossipinfo` 命令读取 phi 或 endpoint states，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:268-278`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1587-1593`、`src/java/org/apache/cassandra/tools/NodeProbe.java:2331-2340`。
5. `enablegossip`/`disablegossip`/`statusgossip` 通过 `NodeProbe` 调 `StorageServiceMBean`，真实 start/stop 逻辑在 `StorageService.startGossiping()`/`stopGossiping()`，见 `src/java/org/apache/cassandra/tools/nodetool/EnableGossip.java:25-32`、`src/java/org/apache/cassandra/tools/nodetool/DisableGossip.java:25-32`、`src/java/org/apache/cassandra/tools/nodetool/StatusGossip.java:25-35`、`src/java/org/apache/cassandra/service/StorageService.java:580-629`。

### Internode handshake and frames

1. Outbound 连接先 `OUTBOUND_PRECONNECT` auth，然后创建 Netty bootstrap、connect timeout 和 handshake timeout，见 `src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:139-181`。
2. Outbound initializer 依据 encryption/fallback mode 插入 `SslHandler`，然后 server authentication、wiretrace logger、handshake handler，见 `src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:216-239`。
3. `HandshakeProtocol.Initiate` 包含 magic、flags、version bounds、connection type、framing、initiator address、CRC；outbound `channelActive()` 发送它，见 `src/java/org/apache/cassandra/net/HandshakeProtocol.java:55-181`、`src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:297-316`。
4. Inbound initializer 先处理 TLS policy 和 client auth，handshake handler 解码 `Initiate`，拒绝 required encryption 下的明文连接，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:117-141`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:312-326`。
5. Inbound 选择 messaging/streaming 的 accept bounds，返回 `Accept(useMessagingVersion, accept.max)`，版本区间不相交则记录并关闭，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:331-362`。
6. Messaging pipeline 按 framing 选择 `FrameDecoderLZ4`、`FrameDecoderCrc` 或 `FrameDecoderUnprotected`，设置 `EndpointMessagingVersions` 并加入 `InboundMessageHandler`，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:467-516`。
7. Outbound 收到 `Accept` 后校验 negotiated version，按 framing 选择 frame encoder 并插入 pipeline；不兼容则关闭并返回 retry/incompatible outcome，见 `src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:336-399`。

### Cross-DC write forwarding

1. `StorageProxy.sendToHintedReplicas()` 将 contacts 分成 local DC、remote DC groups、local write/hints，remote DC group 后续进入 forwarding，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1475-1582`。
2. 每个 remote DC 只选择一个 target 直接发送，其他 replicas 注册 callback 并写入 `ForwardingInfo`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1601-1626`。
3. `ForwardingInfo` 序列化 target endpoint 和 message id；4.0+ 起所有 forwarding targets 使用相同 message id，见 `src/java/org/apache/cassandra/net/ForwardingInfo.java:36-114`、`src/java/org/apache/cassandra/service/StorageProxy.java:1621-1625`。
4. forwarder 收到 mutation 后，`MutationVerbHandler` 复制原始 message，设置 `RESPOND_TO=original.from` 并移除 `FORWARD_TO`，再向同 DC targets 发送，见 `src/java/org/apache/cassandra/db/MutationVerbHandler.java:56-93`。
5. 原始和 forwarded replicas 都向 coordinator 响应，因为 `Message.respondTo()` 在没有 `RESPOND_TO` 时返回 `from`，有 forwarding 时返回原 coordinator，见 `src/java/org/apache/cassandra/net/Message.java:154-165`、`src/java/org/apache/cassandra/net/Message.java:496-507`。

## 调用链

Snitch and preferred IP：

```text
GossipingPropertyFileSnitch.gossiperStarting()
  -> Gossiper.addLocalApplicationState(INTERNAL_ADDRESS_AND_PORT/INTERNAL_IP)
  -> Gossiper.register(ReconnectableSnitchHelper)
Remote endpoint joins or changes state
  -> Gossiper.doOnChangeNotifications(...)
  -> ReconnectableSnitchHelper.onJoin/onChange/onAlive
  -> ReconnectableSnitchHelper.reconnect(public, internal)
  -> MessagingService.maybeReconnectWithNewIp(public, internal)
  -> OutboundConnections.reconnectWithNewIp(internal)
```

Endpoint lifecycle：

```text
Gossiper remote state apply
  -> StorageService.onJoin(...)
  -> StorageService.onChange(STATUS/DC/RACK/NET_VERSION/RPC_READY/...)
  -> token metadata / system.peers update
  -> notifyJoined / notifyMoved / notifyLeft / notifyUp / notifyDown
  -> IEndpointLifecycleSubscriber callbacks
```

Failure detector and nodetool：

```text
Gossip ACK/ACK2 remote state
  -> Gossiper.notifyFailureDetector(...)
  -> FailureDetector.report(endpoint)
GossipTask status check
  -> FailureDetector.interpret(endpoint)
  -> IFailureDetectionEventListener.convict(...)
Operator
  -> nodetool failuredetector/gossipinfo/statusgossip
  -> NodeProbe FD/StorageService MBean proxy
```

Internode messaging handshake：

```text
OutboundConnection.enqueue(message)
  -> OutboundConnectionInitiator.initiateMessaging(...)
  -> optional SslHandler + server-authentication + handshake
  -> send HandshakeProtocol.Initiate(min/max/type/framing/from)
InboundConnectionInitiator.Handler.initiate(...)
  -> decode Initiate
  -> check required encryption
  -> write Accept(useVersion, peerMax)
  -> setup FrameDecoder + InboundMessageHandler
Outbound Handler.decode(Accept)
  -> choose FrameEncoder
  -> return MessagingSuccess(channel, negotiatedVersion, allocator)
```

Cross-DC forwarding：

```text
StorageProxy.performWrite(...)
  -> sendToHintedReplicas(...)
  -> group contacts by DC
  -> sendMessagesToNonlocalDC(message, dcTargets, handler)
  -> message.withForwardTo(new ForwardingInfo(remoteLocalReplicas, ids))
Forwarder MutationVerbHandler.doVerb(message)
  -> forwardToLocalNodes(...)
  -> builder.withParam(RESPOND_TO, original.from).withoutParam(FORWARD_TO)
  -> MessagingService.send(forwardedMessage, localTarget)
Local target applies mutation
  -> responseWith/emptyResponse
  -> MessagingService.send(response, message.respondTo())
```

## 配置项

- `endpoint_snitch`：选择 topology/snitch 实现；配置模板说明 `GossipingPropertyFileSnitch` 通过 `cassandra-rackdc.properties` 定义本地 DC/rack，并经 gossip 传播到其他节点，见 `conf/cassandra.yaml:1473-1556`。
- `phi_convict_threshold`：FD mark-down phi 阈值，模板默认 8，源码限制 5..16，见 `conf/cassandra.yaml:1469-1471`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:554-556`。
- `server_encryption_options.internode_encryption` / `optional` / `require_client_auth` / `require_endpoint_verification`：决定 internode TLS policy、mutual TLS 和 endpoint verification，见 `conf/cassandra.yaml:1641-1677`。
- `internode_compression`：`all`、`dc`、`none`，`OutboundConnectionSettings.shouldCompressConnection()` 用 snitch 判断 `dc` 策略是否跨 DC，见 `conf/cassandra.yaml:1730-1742`、`src/java/org/apache/cassandra/net/OutboundConnectionSettings.java:497-500`。
- `storage_compatibility_mode`：影响 `MessagingService.current_version`，模板默认 `CASSANDRA_4`，见 `conf/cassandra.yaml:2320`、`src/java/org/apache/cassandra/net/MessagingService.java:254-271`。
- `internode_error_reporting_exclusions` / `invalid_legacy_protocol_magic_no_spam_enabled`：控制 inbound handshake/error reporting 噪声，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:144-155`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:381-391`。
- `cassandra.max_local_pause_in_ms`：FD 本地 pause 防误判窗口，读取并可记录 override warning，见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:352`、`src/java/org/apache/cassandra/gms/FailureDetector.java:80-89`。

## Metrics

- FD MBean `org.apache.cassandra.net:type=FailureDetector` 提供 `getPhiValuesWithPort()`、up/down endpoint count、endpoint state dump，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:69-108`、`src/java/org/apache/cassandra/gms/FailureDetector.java:190-238`。
- `nodetool failuredetector` 打印 endpoint/Phi，底层读取 `NodeProbe.getFailureDetectorPhilValues()`，见 `src/java/org/apache/cassandra/tools/nodetool/FailureDetectorInfo.java:30-45`、`src/java/org/apache/cassandra/tools/NodeProbe.java:2331-2340`。
- `InternodeInboundMetrics` 包括 corrupt frame recovered/unrecovered、error/expired/scheduled/processed/received/throttled bytes/count，见 `src/java/org/apache/cassandra/metrics/InternodeInboundMetrics.java:50-68`。
- `InternodeOutboundMetrics` 按 large/small/urgent 注册 pending/completed/dropped/overload/timeout/error，另有 gossip pending/completed/dropped alias 和 callbacks timeouts，见 `src/java/org/apache/cassandra/metrics/InternodeOutboundMetrics.java:117-162`。
- `MessagingService` 注释列出 system views `system_views.internode_inbound` 和 `system_views.internode_outbound`，见 `src/java/org/apache/cassandra/net/MessagingService.java:195-205`。
- Forwarding 本身无独立 metrics；它依赖 write response handler/callback expiry、tracing 和 outbound per-peer dropped/timeout metrics。

## 日志

- Preferred IP reconnect 成功路径记录 debug；authenticator 拒绝时记录 debug 并返回，见 `src/java/org/apache/cassandra/locator/ReconnectableSnitchHelper.java:66-80`。
- `StorageService.stopGossiping()`/`startGossiping()` 由 operator request 触发 warn，stop 时 native transport 仍运行会额外 warn，见 `src/java/org/apache/cassandra/service/StorageService.java:580-629`。
- FD 本地 pause 过长时 warn “Not marking nodes down...”，pause 后继续抑制时 debug，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:342-355`。
- FD phi 接近/超过阈值时 trace/debug，force conviction 记录 debug，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:356-386`。
- Inbound required encryption 下收到明文连接会 warn 并 fail handshake，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:320-326`。
- Handshake 失败会按 root cause 和 no-spam 配置记录 error/warn/debug，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:381-391`、`src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:407-439`。
- 成功建立 messaging/streaming connection 时记录 version、framing、encryption summary，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:455-464`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:510-516`。
- Forwarding trace 使用 “Enqueuing forwarded write to ...”，distributed test 依赖该 trace 验证每个 remote DC node 被转发一次，见 `src/java/org/apache/cassandra/db/MutationVerbHandler.java:88-92`、`test/distributed/org/apache/cassandra/distributed/test/MessageForwardingTest.java:96-115`。

## 运维关注点

- `nodetool statusgossip` 只反映本地 gossip 是否 enabled；endpoint up/down 还取决于 FD、RPC readiness 和 token metadata lifecycle，见 `src/java/org/apache/cassandra/tools/nodetool/StatusGossip.java:25-35`、`src/java/org/apache/cassandra/service/StorageService.java:3032-3065`。
- 停 gossip 前必须确认 node 是 normal 状态；`StorageService.stopGossiping()` 对非 normal + joinRing 直接抛 `IllegalStateException`，见 `src/java/org/apache/cassandra/service/StorageService.java:580-597`。
- `gossipinfo --resolve-ip` 来自 FD MBean endpoint state dump，不是直接读 `GossiperMBean`，见 `src/java/org/apache/cassandra/tools/nodetool/GossipInfo.java:26-36`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1587-1593`。
- Snitch 变更有数据安全约束；配置模板明确说已有数据后不能随意切到不兼容 snitch，否则可能数据丢失，见 `conf/cassandra.yaml:1484-1492`。
- `Ec2MultiRegionSnitch` 需要 public IP 作为 seeds/broadcast，并开放 public storage port；同区域流量会在建立连接后切到 private IP，见 `conf/cassandra.yaml:1535-1541`。
- TLS optional 是迁移工具，不应长期误用；明文和 TLS 同端口共存会让故障排查同时涉及 certificate、authenticator 和 protocol magic。
- `internode_compression=dc` 依赖 snitch DC 判断；DC/rack gossip 不收敛时，压缩策略和 cross-DC forwarding/fanout 观察可能与预期不一致。
- Cross-DC forwarding 的 trace/metrics 分布要按 coordinator、forwarder、final target 三类节点分开看；所有 final targets 响应 coordinator，但转发动作发生在被选 remote DC forwarder。

## 性能瓶颈

- Preferred IP reconnect 会中断/重建 outbound connections；如果 cloud metadata、snitch DC 或 authenticator 抖动，会造成连接 churn。
- Gossip application state 变化会串行通知所有 subscribers；耗时 subscriber 会拖慢 gossip stage 的状态处理。
- `FrameEncoder.Payload.MAX_SIZE` 为 128 KiB frame payload，large message 会拆 frame 并走 large connection，见 `src/java/org/apache/cassandra/net/FrameEncoder.java:39-68`。
- LZ4 frame 如果压缩后不小于原始 payload，会直接复制原始 payload 并把 uncompressed length 置 0，避免负收益压缩，见 `src/java/org/apache/cassandra/net/FrameEncoderLZ4.java:67-105`。
- CRC/LZ4 decoder 在 payload CRC mismatch 时可能产生 recoverable corrupt frame；不可恢复 frame 或 large-message 首 frame corrupt 会导致 connection/message 层更重的恢复成本，见 `src/java/org/apache/cassandra/net/FrameDecoder.java:124-168`。
- Cross-DC forwarding 降低 coordinator 出站 fanout，但远端 forwarder 需要承担额外本 DC fanout、serialization/send 和 trace 开销。
- FD sample size 固定为 1000；过低 `phi_convict_threshold` 或过窄 local-pause window 会把 GC/network tail latency 转成 membership churn，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:73-102`。

## 常见故障

- 节点 DC/rack 显示错误：检查远端 gossip 是否含 `DC`/`RACK`，否则 `GossipingPropertyFileSnitch` 会 fallback 到保存的 peer info、property snitch 或 default，见 `src/java/org/apache/cassandra/locator/GossipingPropertyFileSnitch.java:86-134`。
- Preferred IP 未切换：确认 `INTERNAL_ADDRESS_AND_PORT` 已 gossip、endpoint 未 dead、authenticator 允许 `OUTBOUND_PRECONNECT`、snitch 判断 peer 属于 local DC，见 `src/java/org/apache/cassandra/locator/ReconnectableSnitchHelper.java:88-129`。
- `enablegossip` 后仍不收敛：`startGossiping()` 会重设 gossip generation 并依赖 saved tokens；缺失 valid tokens 时 joinRing/joined 节点有断言风险，见 `src/java/org/apache/cassandra/service/StorageService.java:600-621`。
- FD phi 高但未 mark down：检查 local pause 日志和 `MAX_LOCAL_PAUSE_IN_NANOS` 抑制窗口，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:342-355`。
- 明文/TLS 不匹配：required encryption 下 inbound 明文被拒绝；unencrypted policy 下 TLS attempt 会被 `RejectSslHandler` 关闭，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:320-326`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:574-599`。
- Mixed-version 连接失败：查看 Initiate/Accept 版本区间是否相交，inbound 会记录 peer only supports higher/lower，outbound 会得到 incompatible outcome，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:346-355`、`src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:352-395`。
- CRC frame 错误：header CRC mismatch 不可恢复，payload CRC mismatch 可能可恢复；持续 corrupt frame 指向网络、TLS middlebox、buffer/codec bug 或版本/framing 不一致，见 `src/java/org/apache/cassandra/net/FrameDecoderCrc.java:106-145`。
- Cross-DC writes timeout：检查 coordinator 是否为 forwarded targets 注册 callback，原始 forwarding message 是否 expired，以及 forwarder 是否实际 trace “Enqueuing forwarded write”，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1615-1635`、`src/java/org/apache/cassandra/net/RequestCallbacks.java:292-299`、`src/java/org/apache/cassandra/db/MutationVerbHandler.java:88-92`。

## 测试用例

- `test/unit/org/apache/cassandra/gms/FailureDetectorTest.java`：FD conviction/local pause 相关边界，见 `test/unit/org/apache/cassandra/gms/FailureDetectorTest.java:50-105`。
- `test/unit/org/apache/cassandra/gms/GossiperTest.java`：gossip state、subscriber、endpoint lifecycle 基础覆盖。
- `test/unit/org/apache/cassandra/locator/GossipingPropertyFileSnitchTest.java`：gossiping property snitch DC/rack 行为。
- `test/unit/org/apache/cassandra/locator/ReconnectableSnitchHelperTest.java`：preferred IP reconnect 在 internode authentication 拒绝/null pool 时容错，见 `test/unit/org/apache/cassandra/locator/ReconnectableSnitchHelperTest.java:43-60`。
- `test/unit/org/apache/cassandra/net/HandshakeTest.java`：version negotiation 成功/不兼容矩阵、TLS optional/strict/mTLS fallback 和 non-SSL downgrade/upgrade，见 `test/unit/org/apache/cassandra/net/HandshakeTest.java:120-190`、`test/unit/org/apache/cassandra/net/HandshakeTest.java:191-335`。
- `test/unit/org/apache/cassandra/net/OutboundConnectionSettingsTest.java`：outbound settings 参数合法性、compression/encryption settings 边界。
- `test/unit/org/apache/cassandra/net/OutboundConnectionsTest.java`：gossip/large/small connection selection 和 `reconnectWithNewIp()`，见 `test/unit/org/apache/cassandra/net/OutboundConnectionsTest.java:94-166`。
- `test/unit/org/apache/cassandra/net/MessagingServiceTest.java`：dropped message、latency、inbound/outbound internode authentication failure。
- `test/distributed/org/apache/cassandra/distributed/test/LargeMessageTest.java`：超过 large-message threshold 的实际写读链路，见 `test/distributed/org/apache/cassandra/distributed/test/LargeMessageTest.java:32-45`。
- `test/distributed/org/apache/cassandra/distributed/test/MessageForwardingTest.java`：跨 DC forwarding forwarder 随机性和每个 replica exactly-once commit trace，见 `test/distributed/org/apache/cassandra/distributed/test/MessageForwardingTest.java:50-121`。
- `test/distributed/org/apache/cassandra/distributed/upgrade/MixedModeMessageForwardTest.java`：mixed-version 升级过程中非本地 DC write forwarding，见 `test/distributed/org/apache/cassandra/distributed/upgrade/MixedModeMessageForwardTest.java:82-123`。

## 待继续

- 第三轮已在 `research/module-messaging-verb-semantics.md` 补齐 repair/schema/hints/batchlog/gossip 等 internode `Verb` 的 urgent/small/large、failure callback、params、timeout 和 metrics 语义矩阵。
- 第四轮已新增 `research/tools/check-messaging-verb-matrix-drift.py` 和 `research/module-messaging-verb-drift-checker.md`，检查 `Verb.java` 常量到 messaging matrix 的 source-only 覆盖。
- 增加或取得 TLS optional/strict 与 `internode_compression=dc/all/none` 的 mixed-version distributed test，覆盖 frame negotiation 与 streaming/messaging 分层。
- 增加 preferred IP reconnect 的 distributed test，覆盖 EC2 multi-region 风格 public seed/private reconnect、authenticator reject、same-DC gate。
- 第五轮已新增 `research/tools/check-jmx-nodeprobe-fd-drift.py` 和 `research/module-jmx-nodeprobe-fd-drift-checker.md`，检查 `FailureDetectorMBean`/`GossiperMBean` 方法、NodeProbe JMX proxy baseline、JMXTool package allowlist 和 `failuredetector`/`gossipinfo`/gossip enable-disable-status nodetool 路由。
- 可选把 messaging verb drift checker 接入 CI 或 pre-commit。
