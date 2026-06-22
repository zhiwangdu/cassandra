# Module: Messaging Verb Semantics Matrix

## 范围

本模块补齐 internode messaging 的 verb-specific 语义矩阵。它建立在 `research/module-gossip-messaging.md` 和 `research/module-gossip-messaging-deep-dive.md` 的基础上，专门回答每类 `Verb` 的 stage、timeout、默认连接类型、response pairing、failure callback、message flags/params、metrics 和测试覆盖。Netty handshake、TLS、frame 编解码和 preferred IP reconnect 仍以 `research/module-gossip-messaging-deep-dive.md` 为主。

## 设计目标

- 用 `Verb` enum 作为唯一事实来源，把 message id、priority、stage、timeout、serializer、handler 和 response verb 绑定在同一个 registry 中，见 `src/java/org/apache/cassandra/net/Verb.java:115-228`。
- 用 urgent/small/large 三条 outbound connection 缓解 TCP head-of-line blocking；连接选择先看强制 connection，再看 serialized size，最后才看 `P0` priority，见 `src/java/org/apache/cassandra/net/MessagingService.java:91-115`、`src/java/org/apache/cassandra/net/OutboundConnections.java:210-234`。
- 把 failure response 变成 callback contract，而不是每个 verb 的硬编码属性；`RequestCallback.invokeOnFailure()` 和 message `CALL_BACK_ON_FAILURE` flag 共同决定 timeout/remote failure 是否回调，见 `src/java/org/apache/cassandra/net/MessagingService.java:397-425`。
- 允许 read warning、forwarding、snapshot ranges、tracing 和自定义扩展通过 `ParamType`/`MessageFlag` 携带，不为每个小语义新增独立 verb，见 `src/java/org/apache/cassandra/net/ParamType.java:33-60`、`src/java/org/apache/cassandra/net/MessageFlag.java:22-32`。

## 解决的问题

- “priority 等于连接类型”的直觉不准确：源码注释说明除了 `P0` 外其他 priority 当前未真正区分，`P0` 通常走 urgent；但 oversized `P0` message 仍被路由到 large connection 并记录 warn，见 `src/java/org/apache/cassandra/net/Verb.java:110-112`、`src/java/org/apache/cassandra/net/OutboundConnections.java:215-234`。
- response verb 不靠老的 `REQUEST_RSP` 泛化：request 构造器显式传入 `responseVerb`，response verbs 的 handler 是 `ResponseVerbHandler.instance`，`isResponse()` 也以该 handler 判断，见 `src/java/org/apache/cassandra/net/Verb.java:267-315`、`src/java/org/apache/cassandra/net/Verb.java:338-341`。
- repair 的响应形态特殊：源码注释说明 repair 大多不使用 callback，而是把响应作为自己的 repair message 发送并由 session id 匹配；retry 相关 repair verbs 使用 rpc timeout 让单次请求更快失败后重试，见 `src/java/org/apache/cassandra/net/Verb.java:162-179`、`src/java/org/apache/cassandra/net/Verb.java:483-493`。
- callback map 必须按 `(id, peer)` 维度保存，因为同一 logical request 可以给多个 peer 复用 id；mutation/counter/Paxos commit 使用 write callback overload，其他 request 使用普通 callback overload，见 `src/java/org/apache/cassandra/net/RequestCallbacks.java:49-58`、`src/java/org/apache/cassandra/net/RequestCallbacks.java:96-108`。
- message params 不是任意业务状态桶：boolean 语义进 `MessageFlag`，typed value 进 `ParamType`，tracing headers 在 `Message.buildParams()` 自动注入，见 `src/java/org/apache/cassandra/net/Message.java:347-360`、`src/java/org/apache/cassandra/net/Message.java:481-530`。

## 设计取舍

- `Verb` registry 使用 supplier 延迟加载 serializer/handler，避免 enum 初始化时强制加载所有跨包依赖；字段和 accessor 见 `src/java/org/apache/cassandra/net/Verb.java:248-267`、`src/java/org/apache/cassandra/net/Verb.java:318-326`。
- `P0` 是唯一实际影响 connection selection 的 priority；`P1`、`P2`、`P3`、`P4` 仍保留在 enum 上表达相对语义和兼容指标，但默认都落到 small connection，除非 oversized，见 `src/java/org/apache/cassandra/net/Verb.java:233-240`、`src/java/org/apache/cassandra/net/OutboundConnections.java:232-234`。
- large connection 由 serialized size 控制，阈值来自 `cassandra.otcp_large_message_threshold`，再扣除 frame header/trailer overhead；该阈值不同于 send queue reserve/backpressure 配置，见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:388`、`src/java/org/apache/cassandra/net/OutboundConnections.java:68-70`。
- `sendWithCallback()` 会在 callback 要求 failure 时补 `CALL_BACK_ON_FAILURE` flag；`sendWriteWithCallback()` 则 assert message 已带该 flag，避免 write path 忘记让 remote side 发送 failure response，见 `src/java/org/apache/cassandra/net/MessagingService.java:402-425`。
- unknown params 可以被 serializer 跳过，因此新增 typed param 不要求 bump messaging version；但 enum id 不能复用或填补空洞，见 `src/java/org/apache/cassandra/net/ParamType.java:33-41`。
- custom verb id 从 VInt 两字节上界向下映射，并限制 custom id 范围，避免未来 normal verb id 与 custom verb id 冲突，见 `src/java/org/apache/cassandra/net/Verb.java:383-465`。

## Verb 语义矩阵

| Verb family | Exact verbs | Stage / timeout | 默认连接 | Failure callback / response | Params and notes |
|---|---|---|---|---|---|
| 普通 mutation/write | `MUTATION_REQ` -> `MUTATION_RSP` | `MUTATION` / `writeTimeout`；response 在 `REQUEST_RESPONSE`，见 `src/java/org/apache/cassandra/net/Verb.java:115-116` | `P3` 默认 small；oversized large | write path 使用 `sendWriteWithCallback()`，message 必须带 `CALL_BACK_ON_FAILURE`，见 `src/java/org/apache/cassandra/net/MessagingService.java:421-425` | cross-DC forwarding 可带 `FORWARD_TO`，forwarder 改写为 `RESPOND_TO`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1615-1633`、`src/java/org/apache/cassandra/db/MutationVerbHandler.java:56-92` |
| Hints | `HINT_REQ` -> `HINT_RSP` | `MUTATION` / `writeTimeout`，见 `src/java/org/apache/cassandra/net/Verb.java:117-118` | `P4` 默认 small；oversized large | 普通 callback 取决于 send site；hint dispatch 语义在 hints 模块处理 | payload 是 `HintMessage`；标准 verb 本身不带专用 param |
| Read repair write | `READ_REPAIR_REQ` -> `READ_REPAIR_RSP` | `MUTATION` / `writeTimeout`，见 `src/java/org/apache/cassandra/net/Verb.java:119-120` | `P1` 默认 small；oversized large | read repair callback 跟随 read repair send site；verb response 是空 payload | 与普通 mutation 共用 mutation serializer，专用 handler 是 `ReadRepairVerbHandler` |
| Batchlog store/remove | `BATCH_STORE_REQ` -> `BATCH_STORE_RSP`、`BATCH_REMOVE_REQ` -> `BATCH_REMOVE_RSP` | `MUTATION` / `writeTimeout`，见 `src/java/org/apache/cassandra/net/Verb.java:121-124` | `P3` 默认 small；oversized large | batchlog replay mutation 使用 failure callback 发送 mutation，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:504-509` | batch store payload 是 `Batch`，remove payload 是 `TimeUUID` |
| Paxos v1 | `PAXOS_PREPARE_REQ` -> `PAXOS_PREPARE_RSP`、`PAXOS_PROPOSE_REQ` -> `PAXOS_PROPOSE_RSP`、`PAXOS_COMMIT_REQ` -> `PAXOS_COMMIT_RSP` | `MUTATION` / `writeTimeout`；response `REQUEST_RESPONSE`，见 `src/java/org/apache/cassandra/net/Verb.java:126-131` | `P2` 默认 small；oversized large | Paxos callbacks implement failure behavior; commit message is explicitly created with `CALL_BACK_ON_FAILURE`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:792-805` | `PAXOS_COMMIT_REQ` is allowed by write callback overload，见 `src/java/org/apache/cassandra/net/RequestCallbacks.java:104-108` |
| Truncate | `TRUNCATE_REQ` -> `TRUNCATE_RSP` | `MUTATION` / `truncateTimeout`，见 `src/java/org/apache/cassandra/net/Verb.java:133-134` | `P0` urgent unless oversized large | `TruncateResponseHandler` asks for failure callback; generic send path adds flag when needed | Operator-facing timeout differs from normal write timeout |
| Counter mutation | `COUNTER_MUTATION_REQ` -> `COUNTER_MUTATION_RSP` | `COUNTER_MUTATION` / `counterTimeout`，见 `src/java/org/apache/cassandra/net/Verb.java:136-137` | `P2` 默认 small；oversized large | counter leader write sends with `CALL_BACK_ON_FAILURE` and `sendWriteWithCallback()`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1746-1752` | payload is `CounterMutation`; callback overload enforces counter verb，见 `src/java/org/apache/cassandra/net/RequestCallbacks.java:104-108` |
| Point/range reads | `READ_REQ` -> `READ_RSP`、`RANGE_REQ` -> `RANGE_RSP` | `READ` / `readTimeout` or `rangeTimeout`，见 `src/java/org/apache/cassandra/net/Verb.java:139-142` | requests `P3` small；responses `P2` small；oversized large | `ReadCallback.invokeOnFailure()` returns true; request messages include `CALL_BACK_ON_FAILURE`，见 `src/java/org/apache/cassandra/service/reads/ReadCallback.java:241-255`、`src/java/org/apache/cassandra/db/ReadCommand.java:833-845` | request may set `TRACK_WARNINGS` / `TRACK_REPAIRED_DATA`; response accumulates warning params through `MessageParams.addToMessage()`，见 `src/java/org/apache/cassandra/db/ReadCommandVerbHandler.java:105-128` |
| Gossip digest/shutdown | `GOSSIP_DIGEST_SYN`、`GOSSIP_DIGEST_ACK`、`GOSSIP_DIGEST_ACK2`、`GOSSIP_SHUTDOWN` | `GOSSIP` / `longTimeout` for digest, `rpcTimeout` for shutdown，见 `src/java/org/apache/cassandra/net/Verb.java:144-147` | `P0` urgent unless oversized large | no response verb pair for digest handshake; handlers drive gossip protocol | standard gossip payloads; no dedicated message param |
| Echo / ping | `ECHO_REQ` -> `ECHO_RSP`、`PING_REQ` -> `PING_RSP` | `GOSSIP`; echo uses `rpcTimeout`, ping uses `pingTimeout`，见 `src/java/org/apache/cassandra/net/Verb.java:149-152` | echo `P0` urgent unless oversized large；ping `P1` small unless oversized | callback depends on connectivity checker/send site | startup checker can force small/large connection explicitly，见 `src/java/org/apache/cassandra/net/StartupClusterConnectivityChecker.java:212-213` |
| Schema migration | `SCHEMA_PUSH_REQ` -> `SCHEMA_PUSH_RSP`、`SCHEMA_PULL_REQ` -> `SCHEMA_PULL_RSP`、`SCHEMA_VERSION_REQ` -> `SCHEMA_VERSION_RSP` | `MIGRATION` / `rpcTimeout`，见 `src/java/org/apache/cassandra/net/Verb.java:154-160` | `P1` 默认 small；oversized large | ordinary callback semantics where used | push/pull can be arbitrarily large, hence comment keeps them `P1`; payloads are schema mutation serializer or UUID/no payload |
| Repair messages | `VALIDATION_REQ`、`VALIDATION_RSP`、`SYNC_REQ`、`SYNC_RSP`、`PREPARE_MSG`、`SNAPSHOT_MSG`、`CLEANUP_MSG`、`PREPARE_CONSISTENT_REQ`、`PREPARE_CONSISTENT_RSP`、`FINALIZE_PROPOSE_MSG`、`FINALIZE_PROMISE_MSG`、`FINALIZE_COMMIT_MSG`、`FAILED_SESSION_MSG`、`STATUS_REQ`、`STATUS_RSP`、`REPAIR_RSP` | mostly `ANTI_ENTROPY`; timeouts are `repairTimeout` or retry-aware repair timeout functions，见 `src/java/org/apache/cassandra/net/Verb.java:164-179`、`src/java/org/apache/cassandra/net/Verb.java:483-493` | `P1` 默认 small；Merkle/validation payloads may become large and route large | many repair flows use session-id matching; retry helper can send with callback and `CALL_BACK_ON_FAILURE`，见 `src/java/org/apache/cassandra/repair/messages/RepairMessage.java:241-249` | all routed through `RepairMessageVerbHandler.instance()` except `REPAIR_RSP` response handler |
| Snapshot / replication done | `SNAPSHOT_REQ` -> `SNAPSHOT_RSP`、`REPLICATION_DONE_REQ` -> `REPLICATION_DONE_RSP` | `MISC` / `rpcTimeout`，见 `src/java/org/apache/cassandra/net/Verb.java:181-184` | `P0` urgent unless oversized large | request/response pair for snapshot and replication done | diagnostic snapshot request may include `SNAPSHOT_RANGES`; handler reads the same param，见 `src/java/org/apache/cassandra/utils/DiagnosticSnapshotService.java:141-150`、`src/java/org/apache/cassandra/service/SnapshotVerbHandler.java:49-54` |
| Paxos v2 mutation path | `PAXOS2_COMMIT_REMOTE_REQ`、`PAXOS2_COMMIT_REMOTE_RSP`、`PAXOS2_PREPARE_REQ` -> `PAXOS2_PREPARE_RSP`、`PAXOS2_PREPARE_REFRESH_REQ` -> `PAXOS2_PREPARE_REFRESH_RSP`、`PAXOS2_PROPOSE_REQ` -> `PAXOS2_PROPOSE_RSP`、`PAXOS2_COMMIT_AND_PREPARE_REQ` -> `PAXOS2_COMMIT_AND_PREPARE_RSP` | `MUTATION` / `writeTimeout`，见 `src/java/org/apache/cassandra/net/Verb.java:186-195` | `P2` 默认 small；oversized large | callbacks are implemented by Paxos v2 request classes and generic send path | `PAXOS2_COMMIT_REMOTE_REQ` responds with `MUTATION_RSP`, not its adjacent `PAXOS2_COMMIT_REMOTE_RSP` |
| Paxos v2 repair/cleanup | `PAXOS2_REPAIR_REQ` -> `PAXOS2_REPAIR_RSP`、`PAXOS2_CLEANUP_START_PREPARE_REQ` -> `PAXOS2_CLEANUP_START_PREPARE_RSP`、`PAXOS2_CLEANUP_REQ` -> `PAXOS2_CLEANUP_RSP`、`PAXOS2_CLEANUP_RSP2`、`PAXOS2_CLEANUP_FINISH_PREPARE_REQ` -> `PAXOS2_CLEANUP_FINISH_PREPARE_RSP`、`PAXOS2_CLEANUP_COMPLETE_REQ` -> `PAXOS2_CLEANUP_COMPLETE_RSP` | mostly `PAXOS_REPAIR` / `repairTimeout`; finish prepare request uses `IMMEDIATE` stage，见 `src/java/org/apache/cassandra/net/Verb.java:196-206` | `P2` 默认 small；oversized large | callbacks are Paxos cleanup/repair specific | `PAXOS2_CLEANUP_RSP2` is handled as its own cleanup response verb, not generic `REQUEST_RESPONSE` |
| Generic failure response | `FAILURE_RSP` | `REQUEST_RESPONSE` / no timeout function，见 `src/java/org/apache/cassandra/net/Verb.java:208-209` | `P0` urgent unless oversized large | created by `Message.failureResponse()` when request asked for failure reporting，见 `src/java/org/apache/cassandra/net/Message.java:297-305` | payload is `RequestFailureReason`; not a request verb |
| Dummy/deprecated/custom | `_TRACE`、`_SAMPLE`、`_TEST_1`、`_TEST_2`、`REQUEST_RSP`、`INTERNAL_RSP`、`UNUSED_CUSTOM_VERB` | tracing/internal/immediate/deprecated/custom stages as declared，见 `src/java/org/apache/cassandra/net/Verb.java:211-228` | follows declared priority and size routing | dummy verbs have null handlers; deprecated responses remain for compatibility | custom id mapping and validation are in `Verb.fromId()` / custom id helpers，见 `src/java/org/apache/cassandra/net/Verb.java:395-465` |

## 核心类

| 类 | 作用 |
|---|---|
| `Verb` | internode verb registry；每行声明 id、priority、timeout、stage、serializer、handler 和 optional response verb，见 `src/java/org/apache/cassandra/net/Verb.java:115-228`。 |
| `Message` | header/payload container、request builder、response/failure builder、flags/params accessor；request 默认根据 verb timeout 填充 expiry，见 `src/java/org/apache/cassandra/net/Message.java:210-264`、`src/java/org/apache/cassandra/net/Message.java:285-315`。 |
| `MessageFlag` | boolean header flags，目前包含 callback-on-failure、track repaired data、track warnings，见 `src/java/org/apache/cassandra/net/MessageFlag.java:22-32`。 |
| `ParamType` | typed header params registry，包括 forwarding、tracing、read warnings、custom map、snapshot ranges 和 SAI referenced-index warnings，见 `src/java/org/apache/cassandra/net/ParamType.java:43-60`。 |
| `MessagingService` | send facade，负责注册 callback、补 failure flag、发送到 outbound connection，见 `src/java/org/apache/cassandra/net/MessagingService.java:397-425`。 |
| `RequestCallbacks` | callback map、timeout reaper、failure callback executor；过期时更新 metrics 并按 callback contract 调用 `onFailure`，见 `src/java/org/apache/cassandra/net/RequestCallbacks.java:124-158`。 |
| `OutboundConnections` | 每 peer 的 urgent/small/large outbound pool 和 connection selection，见 `src/java/org/apache/cassandra/net/OutboundConnections.java:76-88`、`src/java/org/apache/cassandra/net/OutboundConnections.java:210-234`。 |
| `MessageParams` | read-side thread-local params accumulator，把 replica-side warnings 合并进 response message，见 `src/java/org/apache/cassandra/db/MessageParams.java:28-72`。 |

## 核心接口

- `IVerbHandler<T>`：inbound dispatch 的业务处理接口；每个 non-response request verb 在 `Verb` 中绑定 handler supplier。
- `RequestCallback<T>`：成功响应回调，默认 `invokeOnFailure()` 为 false，见 `src/java/org/apache/cassandra/net/RequestCallback.java:31-57`。
- `RequestCallbackWithFailure<T>`：要求 failure callback 的便捷接口，默认 `invokeOnFailure()` 为 true，见 `src/java/org/apache/cassandra/net/RequestCallbackWithFailure.java:24-37`。
- `AbstractWriteResponseHandler`：write path callback 基类，明确要求 failure callback，见 `src/java/org/apache/cassandra/service/AbstractWriteResponseHandler.java:313-317`。
- `OutboundMessageCallbacks`：`RequestCallbacks` 同时作为 outbound callback registry 和 lifecycle callback provider。

## 核心数据结构

| 数据结构 | 字段/值 | 语义 |
|---|---|---|
| `Verb.id` | normal id 或 custom-mapped id | wire-level verb id；`VerbTest.idsMatch()` 确认 `Verb.fromId(v.id)` 可逆，见 `test/unit/org/apache/cassandra/net/VerbTest.java:27-31`。 |
| `Verb.priority` | `P0..P4` | 只有 `P0` 在 connection selection 中映射 urgent；其他 priority 默认 small，见 `src/java/org/apache/cassandra/net/Verb.java:233-240`。 |
| `Verb.stage` | `MUTATION` / `READ` / `GOSSIP` / `ANTI_ENTROPY` / `REQUEST_RESPONSE` 等 | inbound execution stage；distributed test instance 通过 `Verb.fromId(verbId).stage.executor()` 调度消息。 |
| `Verb.responseVerb` | nullable `Verb` | request -> response pairing；`Message.responseWith()` 直接使用该字段，见 `src/java/org/apache/cassandra/net/Message.java:285-289`。 |
| `Message.Header.flags` | `CALL_BACK_ON_FAILURE` / `TRACK_REPAIRED_DATA` / `TRACK_WARNINGS` | boolean behavior bits；accessors 见 `src/java/org/apache/cassandra/net/Message.java:481-494`。 |
| `Message.Header.params` | `EnumMap<ParamType,Object>` | typed header params；`customParams()` 从 `CUSTOM_MAP` 读取自定义二进制 map，见 `src/java/org/apache/cassandra/net/Message.java:522-530`。 |
| `CallbackKey` | `(id, peer)` | callback registry key，避免同一 id 发往不同 peer 时冲突，见 `src/java/org/apache/cassandra/net/RequestCallbacks.java:49-58`。 |
| `ForwardingInfo` | target endpoints + target message ids | cross-DC write forwarding 的 per-target response id mapping，writer 在 `StorageProxy` 注册 forwarded callbacks 后放入 message params，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1615-1625`。 |

## 生命周期

### 普通 request/response

```text
caller builds Message.out(verb, payload)
  -> Message.withParam() computes created/expires time from verb.expiresAfterNanos()
  -> MessagingService.sendWithCallback()
     -> RequestCallbacks.addWithExpiration()
     -> add CALL_BACK_ON_FAILURE when callback asks for failure
     -> OutboundConnections.connectionTypeFor()
        -> forced connection if supplied
        -> large if serialized size exceeds threshold
        -> urgent only for P0 otherwise small
  -> peer inbound handler runs verb.handler()
  -> request handler returns message.responseWith(payload)
  -> ResponseVerbHandler removes callback and invokes onResponse()
```

Sources: `src/java/org/apache/cassandra/net/Message.java:250-264`、`src/java/org/apache/cassandra/net/MessagingService.java:397-407`、`src/java/org/apache/cassandra/net/OutboundConnections.java:210-234`、`src/java/org/apache/cassandra/net/Verb.java:318-341`。

### Failure callback

```text
callback.invokeOnFailure() == true
  -> sender carries CALL_BACK_ON_FAILURE flag
  -> remote error can create FAILURE_RSP with RequestFailureReason
  -> local RequestCallbacks.expire() also calls onFailure(TIMEOUT)
```

Sources: `src/java/org/apache/cassandra/net/MessagingService.java:402-407`、`src/java/org/apache/cassandra/net/Message.java:297-315`、`src/java/org/apache/cassandra/net/RequestCallbacks.java:149-158`。

### Read warnings and tracking params

```text
ReadCommand.createMessage(trackRepairedData, requestTime)
  -> add CALL_BACK_ON_FAILURE
  -> optionally add TRACK_WARNINGS and TRACK_REPAIRED_DATA flags
replica read path
  -> MessageParams.add(TOMBSTONE_*, LOCAL_READ_SIZE_*, ROW_INDEX_READ_SIZE_*, TOO_MANY_REFERENCED_INDEXES_*)
  -> ReadCommandVerbHandler adds params to READ_RSP/RANGE_RSP
coordinator ReadCallback reads response params into warning context
```

Sources: `src/java/org/apache/cassandra/db/ReadCommand.java:590-600`、`src/java/org/apache/cassandra/db/ReadCommand.java:629-637`、`src/java/org/apache/cassandra/db/ReadCommand.java:720-727`、`src/java/org/apache/cassandra/io/sstable/format/big/RowIndexEntry.java:398-408`、`src/java/org/apache/cassandra/index/sai/plan/QueryController.java:334-344`、`src/java/org/apache/cassandra/db/ReadCommandVerbHandler.java:105-128`。

### Cross-DC forwarding params

```text
StorageProxy groups remote replicas by DC
  -> choose one target as forwarder
  -> register callbacks for forwardTo replicas
  -> message.withForwardTo(ForwardingInfo)
MutationVerbHandler receives forwarded message
  -> build forwarded local message with RESPOND_TO=original coordinator
  -> remove FORWARD_TO
  -> send to local targets
```

Sources: `src/java/org/apache/cassandra/service/StorageProxy.java:1519-1525`、`src/java/org/apache/cassandra/service/StorageProxy.java:1615-1633`、`src/java/org/apache/cassandra/db/MutationVerbHandler.java:78-92`。

## 调用链

写入：

```text
StorageProxy.performWrite()
  -> Message.outWithFlags(MUTATION_REQ, mutation, requestTime, CALL_BACK_ON_FAILURE)
  -> sendWriteWithCallback()
  -> RequestCallbacks.addWithExpiration(AbstractWriteResponseHandler, MUTATION_REQ, Replica)
  -> MutationVerbHandler.doVerb()
  -> message.emptyResponse()
  -> ResponseVerbHandler.onResponse()
```

读：

```text
AbstractReadExecutor / RangeCommandIterator
  -> ReadCommand.createMessage()
  -> sendWithCallback(message, replica, ReadCallback)
  -> ReadCommandVerbHandler.doVerb()
  -> ReadResponse + MessageParams
  -> ReadCallback.onResponse()/onFailure()
```

Gossip：

```text
Gossiper.GossipTask
  -> Message.out(GOSSIP_DIGEST_SYN, digest)
  -> urgent connection unless oversized
  -> GossipDigestSyn/Ack/Ack2 handlers exchange endpoint state
```

Repair retry helper：

```text
RepairMessage.sendMessageWithFailureCB()
  -> Message.outWithFlag(repairVerb, request, CALL_BACK_ON_FAILURE)
  -> ctx.messaging().sendWithCallback()
  -> callback.invokeOnFailure() == true
  -> retry/failure callback updates repair metrics
```

Source anchors: `src/java/org/apache/cassandra/service/StorageProxy.java:1519-1525`、`src/java/org/apache/cassandra/db/ReadCommand.java:833-845`、`src/java/org/apache/cassandra/repair/messages/RepairMessage.java:241-249`。

## 配置项

- `cassandra.otcp_large_message_threshold`：JVM property backing `OutboundConnections.LARGE_MESSAGE_THRESHOLD` before frame overhead adjustment; default source value is `1024 * 64`, see `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:388` and `src/java/org/apache/cassandra/net/OutboundConnections.java:68-70`。
- `internode_application_send_queue_capacity`、`internode_application_send_queue_reserve_endpoint_capacity`、`internode_application_send_queue_reserve_global_capacity`：outbound application queue and reserve limits，定义在 `src/java/org/apache/cassandra/config/Config.java:249-254`，示例配置见 `conf/cassandra.yaml:1385-1388`。
- `internode_application_receive_queue_capacity` and reserve settings：inbound application queue/backpressure counterpart，示例配置见 `conf/cassandra.yaml:1389-1390`。
- verb timeout functions map to `DatabaseDescriptor` runtime config: rpc/write/read/range/counter/truncate/repair/ping and long/no timeout helpers, see `src/java/org/apache/cassandra/net/Verb.java:472-493`。

## Metrics

- `MessagingMetrics` creates per-verb wait latency timers and dropped-message metrics for every `Verb`，见 `src/java/org/apache/cassandra/metrics/MessagingMetrics.java:96-111`。
- `DroppedMessageMetrics` scopes dropped/internal-dropped/cross-node-dropped metrics by verb and preserves pre-4.0 aliases for request verbs such as `MUTATION`, `READ`, `RANGE_SLICE` and `HINT`，见 `src/java/org/apache/cassandra/metrics/DroppedMessageMetrics.java:33-89`。
- `InternodeOutboundMetrics` exposes per-peer large/small/urgent pending/completed/dropped/timeout/overload/error gauges; large-message gauges start at `LargeMessagePendingTasks`，见 `src/java/org/apache/cassandra/metrics/InternodeOutboundMetrics.java:34-37`、`src/java/org/apache/cassandra/metrics/InternodeOutboundMetrics.java:124-134`。
- `InternodeInboundMetrics` exposes per-peer inbound corrupt/error/expired/scheduled/processed/received/throttled gauges，见 `src/java/org/apache/cassandra/metrics/InternodeInboundMetrics.java:55-68`。
- Expired callbacks increment global `InternodeOutboundMetrics.totalExpiredCallbacks` and peer-level expired callback metrics through `RequestCallbacks.onExpired()`，见 `src/java/org/apache/cassandra/net/RequestCallbacks.java:149-158`。

## 日志

- Oversized urgent message emits a no-spam warn `Enqueued URGENT message which exceeds large message threshold`; trace logging includes verb, size and threshold，见 `src/java/org/apache/cassandra/net/OutboundConnections.java:215-226`。
- Callback reaper logs expired callback count at trace level，见 `src/java/org/apache/cassandra/net/RequestCallbacks.java:124-140`。
- Cross-DC forwarding logs trace entries when registering forwarded callback and sending chosen forwarder，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1615-1634`。
- `MutationVerbHandler` traces forwarded write fanout per target，见 `src/java/org/apache/cassandra/db/MutationVerbHandler.java:88-92`。

## 运维关注点

- 不要把 `P0` 等同于“永远 urgent”：大 gossip/echo/snapshot/truncate/failure response 超过 threshold 会走 large connection，并可能让 large queue/backpressure 成为瓶颈。
- `CALL_BACK_ON_FAILURE` 是 sender/receiver contract。callback 要求 failure 时 send path 会补 flag；write path assert flag 已存在。自定义或新 send site 若绕开 `MessagingService.sendWithCallback()`，必须显式维持这个 contract。
- Read warning params 只在请求带 `TRACK_WARNINGS` 时有意义；replica side 使用 `MessageParams` thread-local，handler 必须在 response 构造时调用 `MessageParams.addToMessage()`。
- 新增 `ParamType` 可以跨版本跳过未知 params，但不能复用旧 id 或填补空洞；boolean 语义应扩展 `MessageFlag`。
- 新增 normal `Verb` 时要检查 id upper bound、response verb、serializer/handler、timeout、stage、dropped metrics alias 需求，以及 `VerbTest.idsMatch()` 是否仍通过。
- Repair/Paxos cleanup verbs 不能只按 request/response pair 理解；一部分 response 是 repair session message，一部分 response handler 是 `ResponseVerbHandler`。

## 性能瓶颈

- large threshold 按 serialized size 判断；大 schema push、read response、repair validation 或 oversized urgent message 都可能进入 large connection，影响同 peer 大消息吞吐。
- small connection 仍承载绝大多数 `P1..P4` verbs；如果 read/write/schema/repair 同 peer 混杂且 payload 都未超过 threshold，priority 不会在 connection selection 中进一步细分。
- callback map 是 concurrent map 并由 scheduled reaper 扫描；高 fanout、超时堆积或 forward-to replicas 会增加 callback map 压力，见 `src/java/org/apache/cassandra/net/RequestCallbacks.java:124-158`。
- cross-DC forwarding 减少 coordinator 出站 fanout，但被选 forwarder 要承担本 DC fanout 和 response forwarding，热点取决于 `StorageProxy.pickReplica()` 选择和 replica health。
- `MessageParams` 使用 fast thread-local；handler 若漏清理或跨线程不当传播会污染 response params，因此当前读路径在 handler 内部同步添加到 response message。

## 常见故障

- Gossip/echo/truncate 等 `P0` message 出现 large queue warning：检查 payload size、`cassandra.otcp_large_message_threshold`、large connection pending bytes 和是否有异常 schema/gossip state 膨胀。
- Coordinator 等不到 failure callback：检查 callback 实现是否 `invokeOnFailure()`，message 是否经 `sendWithCallback()` 或 write path 是否显式带 `CALL_BACK_ON_FAILURE`。
- Read warning 丢失：检查 `ReadCommand.createMessage()` 是否带 `TRACK_WARNINGS`，replica handler 是否调用 `MessageParams.addToMessage()`，以及 warning param 是否在 coordinator response processing 中读取。
- Cross-DC write timeout：检查 forwarded target callback 是否注册、`FORWARD_TO` 是否被 forwarder 消费并替换为 `RESPOND_TO`、forwarder trace 是否出现本地 fanout。
- 新增 verb 在 mixed-version 或 tests 中解析失败：检查 id 是否冲突、`fromId()` custom/normal map 是否可逆、serializer/handler 是否非空，以及 response verb 是否和 callback payload 类型一致。

## 测试用例

- `test/unit/org/apache/cassandra/net/VerbTest.java`：检查所有 `Verb` 的 id round-trip，见 `test/unit/org/apache/cassandra/net/VerbTest.java:27-31`。
- `test/unit/org/apache/cassandra/net/OutboundConnectionsTest.java`：验证 gossip `P0` route urgent、oversized gossip route large、ping route small、oversized non-P0 route large，见 `test/unit/org/apache/cassandra/net/OutboundConnectionsTest.java:94-132`。
- `test/unit/org/apache/cassandra/net/MessageTest.java`：覆盖 message flag/param serialization、callback-on-failure flag、respond-to param 和 custom params round-trip，见 `test/unit/org/apache/cassandra/net/MessageTest.java:139-184`、`test/unit/org/apache/cassandra/net/MessageTest.java:220-243`。
- `test/distributed/org/apache/cassandra/distributed/test/LargeMessageTest.java`：用超过 large-message threshold 的实际写读链路验证 large message path，见 `test/distributed/org/apache/cassandra/distributed/test/LargeMessageTest.java:32-45`。
- `test/distributed/org/apache/cassandra/distributed/test/MessageForwardingTest.java` 和 `test/distributed/org/apache/cassandra/distributed/upgrade/MixedModeMessageForwardTest.java`：覆盖 cross-DC forwarding 和 mixed-version forwarding；详见 `research/module-gossip-messaging-deep-dive.md`。

## 待补项

- 已新增 `research/tools/check-messaging-verb-matrix-drift.py`，用于检查 `Verb.java` 中所有 verb 常量是否进入本矩阵；后续可接入 CI。
- 增加或取得 TLS optional/strict 与 `internode_compression=dc/all/none` 的 mixed-version distributed test，覆盖 messaging frame negotiation 与 streaming compression 分层。
- `FailureDetectorMBean` / `GossiperMBean` 的 nodetool/JMX 路由已由 `research/tools/check-jmx-nodeprobe-fd-drift.py` 保护；`MessagingServiceMBean` 方法、NodeProbe 路由和 `netstats` pool 聚合已由 `research/tools/check-messaging-mbean-netstats-drift.py` 保护。后续可把这些 checker 接入 CI。
