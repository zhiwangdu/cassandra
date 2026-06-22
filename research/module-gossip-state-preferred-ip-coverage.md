# Module: Gossip State And Preferred IP Coverage

本页是 `module-gossip-messaging.md` / `module-gossip-messaging-deep-dive.md` 的第五轮补充，聚焦 gossip state merge、legacy/new application state 过滤、shadow round、shutdown announce、preferred IP reconnect 和测试缺口。

## 范围

- Gossip 周期任务：heartbeat、digest SYN、live/unreachable/seed 选择、status check。
- Endpoint state 合并：generation/version 比较、future generation 拒绝、major state change、same-generation incremental update。
- Application state 兼容：`STATUS`/`STATUS_WITH_PORT`、`INTERNAL_IP`/`INTERNAL_ADDRESS_AND_PORT`、`RPC_ADDRESS`/`NATIVE_ADDRESS_AND_PORT` 的 wire ordinal、过滤和通知顺序。
- Endpoint liveness：FD report、ECHO_REQ gate、alive/dead subscriber notification。
- Startup shadow round 和 shutdown announce：shadow ACK 安全检查、seed shadow round convergence、5.0 shutdown payload mixed-mode。
- Snitch preferred IP：`GossipingPropertyFileSnitch` 发布 internal address，`ReconnectableSnitchHelper` 监听 join/change/alive 并触发 `MessagingService.maybeReconnectWithNewIp()`。
- 测试覆盖和缺口：unit coverage 已覆盖状态合并、legacy 通知、shadow round、shutdown serde、reconnect authentication failure；preferred IP reconnect distributed test 仍是 gap still open。

## 覆盖场景

| 场景 ID | 当前结论 |
|---|---|
| `gossip_digest_task_baseline` | `GossipTask` 等待 messaging listen、更新本地 heartbeat、构造 digest 并 gossip 到 live/unreachable/seed 后运行 status check。 |
| `gossip_stage_mutation_guard` | 状态 mutation 受 `Stage.GOSSIP` 线程校验保护，strict runtime checks 下直接抛异常。 |
| `gossip_endpoint_state_merge` | `applyStateLocally()` 按 generation/version 合并 remote state，拒绝明显未来 generation，same-generation 只应用新版本 app states。 |
| `gossip_application_state_wire_compat` | `ApplicationState` ordinal 是 wire contract；legacy states 不可重排/删除，新 states 放在 padding 前。 |
| `gossip_status_notification_order` | `applyNewStates()` 先通知 `STATUS`/`STATUS_WITH_PORT`，且本地已有新字段时跳过 legacy status 通知。 |
| `gossip_legacy_state_filter` | 非 mixed-v3 集群过滤 legacy `STATUS`、`INTERNAL_IP`、`RPC_ADDRESS`，避免新旧字段并存造成重复/回退。 |
| `gossip_echo_mark_alive_dead` | peer 从 dead 回 alive 前先发 `ECHO_REQ`，成功响应后在 gossip stage 调 `realMarkAlive()` 并通知 subscribers；dead 走 `markDead()`。 |
| `gossip_shadow_round_startup_gate` | startup shadow round 用 empty SYN 拉取 state，ACK 必须满足 startup safety check；种子全在 shadow round 时允许退出。 |
| `gossip_shutdown_announce` | joined 节点 stop gossip 时发布 `SHUTDOWN` status，向 live endpoints 发送 `GOSSIP_SHUTDOWN` payload，并保留 4.x/5.x serde 兼容。 |
| `gossip_preferred_ip_reconnect_baseline` | snitch 发布 internal address，helper 只在 `prefer_local`、peer 非 dead、auth 通过且 same-DC 时触发 preferred IP reconnect。 |
| `gossip_preferred_ip_distributed_gap` | 当前 checkout 未发现覆盖 `prefer_local`/`ReconnectableSnitchHelper`/`maybeReconnectWithNewIp()` 的 distributed preferred-IP reconnect 测试；gap still open。 |
| `gossip_reconnect_onjoin_legacy_gap` | `ReconnectableSnitchHelper.onJoin()` 当前两次读取 `INTERNAL_ADDRESS_AND_PORT`，没有回退 legacy `INTERNAL_IP`；onChange/onAlive 有 fallback，需源码修复或测试确认。 |
| `gossip_existing_tests_baseline` | 现有 unit/distributed 测试覆盖 generation jump、duplicate state update、legacy notification、shadow round、shutdown serde、shutdown token metadata 和 reconnect auth failure。 |

## 设计目标

- 让 membership state 在无中心协调者的情况下收敛，并以 generation + heartbeat/application state version 做冲突判定。
- 保持 rolling upgrade 兼容：新旧 app state 同时存在时，新字段优先，但 wire enum ordinal 不能破坏旧节点反序列化。
- 防止误把不可达 peer 标为 alive：相同 generation 下 dead peer 要通过 `ECHO_REQ` 响应后才 `realMarkAlive()`。
- 让 startup shadow round 只读取安全状态，不污染正式 `endpointStateMap`。
- 支持云/多网卡部署：先用 broadcast/public address 建联，再通过 gossip internal address 切换 same-DC preferred IP。

## 解决的问题

- Future generation 污染：`Gossiper.applyStateLocally()` 对 remote generation 大于本地时间 + `MAX_GENERATION_DIFFERENCE` 的状态只记录 warning，不更新本地状态，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1744-1749`；`GossiperTest.testLargeGenerationJump()` 覆盖该边界，见 `test/unit/org/apache/cassandra/gms/GossiperTest.java:240-269`。
- 重复 app-state 通知：same generation 下只收集版本更高的 app states；`testDuplicatedStateUpdate()` 验证 heartbeat 变更不会重复通知同版本 `TOKENS`，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1793-1807`、`test/unit/org/apache/cassandra/gms/GossiperTest.java:280-329`。
- Legacy/new state 并存：`EndpointState.removeMajorVersion3LegacyApplicationStates()` 过滤 pre-4.0 字段，`applyNewStates()` 也跳过 legacy notification，见 `src/java/org/apache/cassandra/gms/EndpointState.java:186-225`、`src/java/org/apache/cassandra/gms/Gossiper.java:1810-1844`。
- Startup stale ACK：shadow round ACK 必须通过 `sufficientForStartupSafetyCheck()`，否则不退出 shadow round，见 `src/java/org/apache/cassandra/gms/Gossiper.java:2311-2329`。
- Preferred IP 误切换：`ReconnectableSnitchHelper.reconnect()` 先做 `OUTBOUND_PRECONNECT` auth，再要求 snitch 认为 peer 在 local DC，才调用 `maybeReconnectWithNewIp()`，见 `src/java/org/apache/cassandra/locator/ReconnectableSnitchHelper.java:66-80`。

## 设计取舍

- `ApplicationState` enum 使用 ordinal 作为 wire 编码，牺牲删除/重排自由换取紧凑协议；新增状态必须放在 padding 前，见 `src/java/org/apache/cassandra/gms/ApplicationState.java:20-75`。
- `EndpointState` 用 `AtomicReference<View>` copy-on-write 更新 app-state map，读路径无锁但写入会复制 `EnumMap`，见 `src/java/org/apache/cassandra/gms/EndpointState.java:56-83`、`src/java/org/apache/cassandra/gms/EndpointState.java:166-183`。
- same-generation merge 先写本地状态再按顺序发 notifications；这样 subscriber 读取 endpoint state 时能看到完整新字段，但要求 legacy notification 过滤足够严格。
- `markAlive()` 先把 state 标 dead 并发送 `ECHO_REQ`，可降低误活，但恢复感知依赖额外 round trip，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1437-1477`。
- Preferred IP 只做 same-DC reconnect，避免跨 DC private address 不可达；代价是跨区域部署必须保证 snitch DC 判定准确。

## 核心类

| 类 | 责任 |
|---|---|
| `Gossiper` | gossip task、endpoint state map、state merge、FD report、alive/dead transition、shadow round、shutdown announce，见 `src/java/org/apache/cassandra/gms/Gossiper.java:337-399`、`src/java/org/apache/cassandra/gms/Gossiper.java:1710-1844`、`src/java/org/apache/cassandra/gms/Gossiper.java:2284-2357`。 |
| `EndpointState` | heartbeat + app-state copy-on-write view、legacy field filtering、alive/dead marker，见 `src/java/org/apache/cassandra/gms/EndpointState.java:43-225`。 |
| `ApplicationState` | gossip app-state wire enum，新旧状态和 padding contract，见 `src/java/org/apache/cassandra/gms/ApplicationState.java:20-75`。 |
| `VersionedValue.VersionedValueFactory` | 生成 status、shutdown、internal address、native/rpc address、schema、token 等 versioned values，见 `src/java/org/apache/cassandra/gms/VersionedValue.java:274-341`。 |
| `GossipingPropertyFileSnitch` | 本地 DC/rack 来源、远端 DC/rack fallback、启动时发布 internal address 并注册 reconnect helper，见 `src/java/org/apache/cassandra/locator/GossipingPropertyFileSnitch.java:86-158`。 |
| `ReconnectableSnitchHelper` | gossip subscriber，onJoin/onChange/onAlive 处理 internal address 并触发 preferred IP reconnect，见 `src/java/org/apache/cassandra/locator/ReconnectableSnitchHelper.java:40-129`。 |
| `FailureDetector` | arrival window/phi、`Gossiper` report/convict 对接和 FD MBean；本页只引用 gossip report 边界，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1384-1435`。 |

## 核心接口

- `IEndpointStateChangeSubscriber`：`ReconnectableSnitchHelper` 直接实现该低层 gossip subscriber，处理 join/change/alive/dead/remove/restart，见 `src/java/org/apache/cassandra/locator/ReconnectableSnitchHelper.java:40-145`。
- `IEndpointSnitch`：preferred IP reconnect 的 DC gate 依赖 `snitch.getDatacenter(publicAddress)`，见 `src/java/org/apache/cassandra/locator/ReconnectableSnitchHelper.java:66-80`。
- `GossiperMBean` / `FailureDetectorMBean`：gossip/FD JMX surface 已在 `module-jmx-nodeprobe-fd-drift-checker.md` 固化；本页新增的是 state merge/preferred-IP source coverage。

## 核心数据结构

- `endpointStateMap`：正式 endpoint -> `EndpointState` 状态表；`applyStateLocally()` 只在非 shadow round 跳过 self state，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1710-1728`。
- `endpointShadowStateMap`：shadow round 暂存状态，`doShadowRound()` 返回 immutable copy，不直接污染正式状态，见 `src/java/org/apache/cassandra/gms/Gossiper.java:2039-2058`、`src/java/org/apache/cassandra/gms/Gossiper.java:2122`。
- `liveEndpoints` / `unreachableEndpoints` / `inflightEcho`：alive/dead 状态和 ECHO_REQ 去重/回调容器，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1437-1494`。
- `EndpointState.View`：`HeartBeatState` + `EnumMap<ApplicationState, VersionedValue>` 的不可变快照引用，CAS 替换，见 `src/java/org/apache/cassandra/gms/EndpointState.java:56-68`、`src/java/org/apache/cassandra/gms/EndpointState.java:166-183`。
- `seeds` / `seedsInShadowRound`：seed 列表排除本机；shadow ACK 都来自 shadowing seeds 时退出 startup wait，见 `src/java/org/apache/cassandra/gms/Gossiper.java:2125-2133`、`src/java/org/apache/cassandra/gms/Gossiper.java:2341-2354`。

## 生命周期

### Gossip round

1. `GossipTask.run()` 等待 messaging 开始监听，见 `src/java/org/apache/cassandra/gms/Gossiper.java:343-345`。
2. 更新本地 heartbeat，构造 digest，发送 `GOSSIP_DIGEST_SYN`，见 `src/java/org/apache/cassandra/gms/Gossiper.java:348-363`。
3. 继续按概率探测 unreachable peer，必要时 gossip seed，最后 `doStatusCheck()`，见 `src/java/org/apache/cassandra/gms/Gossiper.java:365-387`。
4. ACK/ACK2 state 进入 `notifyFailureDetector()` 和 `applyStateLocally()`，分别更新 FD samples 和 endpoint state，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1384-1435`、`src/java/org/apache/cassandra/gms/Gossiper.java:1710-1844`。

### State merge and notification

1. `applyStateLocally()` 先校验 mutation 线程，再按 endpoint 排序处理 remote map，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1710-1714`。
2. self state 在非 shadow round 被跳过；just removed/quarantine endpoint 被跳过，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1716-1724`。
3. 非 mixed-v3 集群先移除 remote legacy states，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1729-1731`。
4. remote generation 更大时 `handleMajorStateChange()`；generation 相同且 remote max version 更大时 `applyNewStates()`，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1750-1766`。
5. `applyNewStates()` 添加新版本 states，过滤 legacy fields，先通知 status，再通知其他非 legacy states，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1788-1844`。

### Alive/dead

```text
applyStateLocally(...)
  -> same generation and local endpoint not alive
  -> markAlive(endpoint, state)
  -> send ECHO_REQ with callback
  -> runInGossipStageBlocking(realMarkAlive)
  -> state.markAlive + liveEndpoints.add + subscriber.onAlive

FailureDetector conviction or status check
  -> markDead(endpoint, state)
  -> silentlyMarkDead
  -> subscriber.onDead
```

源码锚点：`src/java/org/apache/cassandra/gms/Gossiper.java:1437-1515`。

### Shadow round

```text
StorageService startup safety path
  -> Gossiper.doShadowRound(peers)
  -> buildSeedsList()
  -> send empty GOSSIP_DIGEST_SYN to seeds, then known peers if needed
  -> maybeFinishShadowRound(respondent, isInShadowRound, states)
  -> sufficientForStartupSafetyCheck(states)
  -> endpointShadowStateMap immutable copy
```

源码锚点：`src/java/org/apache/cassandra/gms/Gossiper.java:2034-2122`、`src/java/org/apache/cassandra/gms/Gossiper.java:2311-2357`。

### Preferred IP reconnect

```text
GossipingPropertyFileSnitch.gossiperStarting()
  -> addLocalApplicationState(INTERNAL_ADDRESS_AND_PORT)
  -> addLocalApplicationState(INTERNAL_IP)
  -> register ReconnectableSnitchHelper

Remote endpoint join/change/alive
  -> ReconnectableSnitchHelper.onJoin/onChange/onAlive
  -> reconnect(publicAddress, internalAddressValue)
  -> OutboundConnectionSettings(...).authenticator().authenticate(..., OUTBOUND_PRECONNECT)
  -> snitch.getDatacenter(publicAddress).equals(localDc)
  -> MessagingService.maybeReconnectWithNewIp(publicAddress, localAddress)
```

源码锚点：`src/java/org/apache/cassandra/locator/GossipingPropertyFileSnitch.java:136-158`、`src/java/org/apache/cassandra/locator/ReconnectableSnitchHelper.java:66-129`。

## 配置项

- `endpoint_snitch`：选择 `GossipingPropertyFileSnitch` / EC2 snitch 等，影响 DC/rack 和 preferred IP reconnect helper 注册，配置模板见 `conf/cassandra.yaml:1473-1556`。
- `cassandra-rackdc.properties` 的 `dc`、`rack`、`prefer_local`：`GossipingPropertyFileSnitch` 构造时读取，`prefer_local` 决定 helper 是否触发 reconnect，见 `src/java/org/apache/cassandra/locator/GossipingPropertyFileSnitch.java:45-59`。
- `phi_convict_threshold`：FD convict 阈值，gossip state 更新会进入 FD report/interpret 链路；模板和 `DatabaseDescriptor` 校验见 `conf/cassandra.yaml:1469-1471`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:554-556`。
- `CASSANDRA_CONFIG` / seed provider：shadow round 和 gossip seed list 依赖 configured seeds；`buildSeedsList()` 排除本机，见 `src/java/org/apache/cassandra/gms/Gossiper.java:2125-2133`。

## Metrics

- Gossip state merge 本身无专属 metric；主要通过 FD MBean/nodetool、gossip info、internode outbound metrics 和 logs 观察。
- FD MBean 暴露 endpoint state/phi/up-down count；gossip state 更新通过 `notifyFailureDetector()` 把新 generation/version 报给 FD，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1384-1435`。
- Preferred IP reconnect 成功后实际连接变化体现在 internode outbound connection state 和 system preferred IP 记录；`MessagingService.maybeReconnectWithNewIp()` 侧已有 metrics/observability 在 `module-gossip-messaging-deep-dive.md` 覆盖。

## 日志

- Gossip round 异常：`GossipTask` 捕获并记录 `Gossip error`，见 `src/java/org/apache/cassandra/gms/Gossiper.java:390-393`。
- Future generation：收到不可信 generation 时记录 warning，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1744-1749`。
- Alive/dead：`realMarkAlive()` 记录 `InetAddress ... is now UP`，`markDead()` 记录 `... is now DOWN`，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1491-1494`、`src/java/org/apache/cassandra/gms/Gossiper.java:1507-1510`。
- Shutdown announce：`stop()` 记录 `Announcing shutdown` 或 no local state/silent/not joined warning，见 `src/java/org/apache/cassandra/gms/Gossiper.java:2284-2300`。
- Preferred IP reconnect：auth 拒绝用 debug 记录，成功发起 reconnect 也用 debug 记录，见 `src/java/org/apache/cassandra/locator/ReconnectableSnitchHelper.java:70-79`。

## 运维关注点

- `nodetool gossipinfo` 中同时出现 legacy/new fields 时，要按新字段优先判断；非 mixed-v3 集群源码会过滤 legacy 字段。
- preferred IP 只对 same-DC 生效；跨 DC 节点即使 gossip 了 internal address，也不会自动切到 private IP。
- `prefer_local=true` 需要网络、snitch DC 判断和 internode authenticator 一致；auth 拒绝时不会 reconnect。
- 当前 `ReconnectableSnitchHelper.onJoin()` 没有 legacy `INTERNAL_IP` fallback；如果 peer 只发布 legacy internal IP，onJoin 不会立即 reconnect，后续 onChange/onAlive 仍可能收敛。
- Shutdown gossip 对 4.x peer serde 为 no payload；5.x peer 能读取 `GossipShutdown` endpoint state，见 `test/unit/org/apache/cassandra/gms/GossipShutdownTest.java:39-59`。

## 性能瓶颈

- `EndpointState.addApplicationStates()` 每次更新复制 `EnumMap`；状态集合小，适合读多写少，但 app-state 大量抖动会增加分配。
- Shadow round 非 seed 会把 ring delay 加倍，cluster full bounce 时更稳，但启动等待更长，见 `src/java/org/apache/cassandra/gms/Gossiper.java:2066-2070`。
- Alive 恢复需要 ECHO round trip；网络抖动时 endpoint 从 unreachable 回 live 的时间不只取决于收到 gossip state。
- Preferred IP reconnect 可能重建 outbound pool；若 internal address 频繁变化，会带来连接 churn。

## 常见故障

- `Unable to gossip with any peers`：非 seed shadow round 超时且没有 seed/peer 响应，`ShadowRoundTest.testBadAckInShadow()` 覆盖该错误，见 `src/java/org/apache/cassandra/gms/Gossiper.java:2106-2111`、`test/unit/org/apache/cassandra/gms/ShadowRoundTest.java:133-183`。
- `Attempting gossip state mutation from illegal thread`：非 gossip stage 修改状态，strict runtime checks 下抛出，见 `src/java/org/apache/cassandra/gms/Gossiper.java:321-334`。
- Preferred IP 未切换：检查 `prefer_local`、snitch DC、internode authenticator、peer 是否 dead，以及 peer 是否发布 `INTERNAL_ADDRESS_AND_PORT`。
- Legacy notification 重复：如果 `STATUS` 和 `STATUS_WITH_PORT` 都通知到 subscriber，说明 `applyNewStates()` 或 `EndpointState` legacy filter 发生 drift；`testNotFireDuplicatedNotificationsWithUpdateContainsOldAndNewState()` 是当前 baseline，见 `test/unit/org/apache/cassandra/gms/GossiperTest.java:440-493`。
- Shutdown 后 pending ranges 未清理：`GossipTest.gossipShutdownUpdatesTokenMetadata()` 保护 MOVING -> SHUTDOWN 对 token metadata 的影响，见 `test/distributed/org/apache/cassandra/distributed/test/GossipTest.java:381-428`。

## 测试用例

| 测试 | 覆盖内容 |
|---|---|
| `test/unit/org/apache/cassandra/gms/GossiperTest.java:240-269` | future generation 边界。 |
| `test/unit/org/apache/cassandra/gms/GossiperTest.java:280-329` | duplicate app-state update 不重复通知。 |
| `test/unit/org/apache/cassandra/gms/GossiperTest.java:440-493` | legacy/new status notification 过滤。 |
| `test/unit/org/apache/cassandra/gms/EndpointStateTest.java:43-170` | copy-on-write read/write consistency。 |
| `test/unit/org/apache/cassandra/gms/ShadowRoundTest.java:81-183` | shadow round ACK、SCHEMA_PULL 抑制和 bad ACK failure。 |
| `test/unit/org/apache/cassandra/gms/GossipShutdownTest.java:39-59` | 4.x/5.x `GOSSIP_SHUTDOWN` payload serde。 |
| `test/unit/org/apache/cassandra/locator/ReconnectableSnitchHelperTest.java:32-57` | internode authenticator 拒绝时 reconnect graceful failure。 |
| `test/distributed/org/apache/cassandra/distributed/test/GossipTest.java:84-146` | MOVING status gossip 到 late node 后 token metadata 保持一致。 |
| `test/distributed/org/apache/cassandra/distributed/test/GossipTest.java:381-428` | shutdown gossip 更新 token metadata pending ranges。 |

## 缺口

- `gossip_preferred_ip_distributed_gap`：当前 `test/distributed` 未发现 direct preferred-IP reconnect scenario。建议新增 in-JVM dtest：启用 `GossipingPropertyFileSnitch`/`prefer_local=true`，让 peer gossip `INTERNAL_ADDRESS_AND_PORT`，断言 `SystemKeyspace.updatePreferredIP()` 或 outbound pool preferred address 收敛，并覆盖 auth deny/same-DC gate。
- `gossip_reconnect_onjoin_legacy_gap`：`onJoin()` 当前重复读取 `INTERNAL_ADDRESS_AND_PORT`，没有 legacy `INTERNAL_IP` fallback；建议修源码并补 unit test 覆盖 join-only legacy state，或明确 5.x 不再支持该 join fallback。
- `gossip_shutdown_announce` 已有 serde/distributed token metadata coverage，但没有专门验证 mixed 4.x/5.x rolling cluster shutdown behavior 的 distributed test。

## Drift Checker

- `research/tools/check-gossip-state-preferred-ip-drift.py` 保护本页 source/test/gap baseline。
- 运行：

```bash
python3 research/tools/check-gossip-state-preferred-ip-drift.py
python3 research/tools/check-gossip-state-preferred-ip-drift.py --json
```
