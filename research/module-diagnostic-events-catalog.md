# Module: Diagnostic Events Catalog

## 范围

本模块覆盖当前 checkout 下 `src/java` 内所有生产代码 `DiagnosticEvent` 子类、事件类型枚举、发布 helper、JMX persistence/read 入口和主要测试。测试专用 `DiagnosticEventServiceTest.TestEvent*`、microbench `DummyEvent` 不属于生产事件清单；`AuthEvents` 是 auth listener bus，不继承 `DiagnosticEvent`，也不计入本 catalog。catalog 覆盖 drift 由 `research/tools/check-diagnostic-events-catalog-drift.py` 检查，设计见 `research/module-diagnostic-events-drift-checker.md`。

## 设计目标

Diagnostic Events 的目标是在不开启长期日志、不改变主流程语义的前提下，给 bootstrap、token allocation、gossip、schema、hints、read repair、guardrails、audit 等内部路径提供可订阅的事件快照。事件默认由 `diagnostic_events_enabled` 关闭，发布方通常先用 `DiagnosticEventService.isEnabled(class, type)` 判断全局开关和订阅者，再构造事件对象，见 `src/java/org/apache/cassandra/diag/DiagnosticEventService.java:221-265`、`conf/cassandra.yaml:1933-1936`。

## 解决的问题

- 诊断消费者需要按事件 class、事件 type 或全部事件订阅，`DiagnosticEventService` 分别维护 all/class/class+type 三类订阅集合，并在 `publish()` 中按这三层分发，见 `src/java/org/apache/cassandra/diag/DiagnosticEventService.java:50-101`。
- JMX 客户端需要可轮询的短期事件窗口，`DiagnosticEventServiceMBean.readEvents()` 返回按事件 id 排序的 map，`DiagnosticEventPersistence` 为每个事件 class 建立 memory store，见 `src/java/org/apache/cassandra/diag/DiagnosticEventServiceMBean.java:41-58`、`src/java/org/apache/cassandra/diag/DiagnosticEventPersistence.java:62-94`。
- 运维人员需要知道可订阅的 FQCN 和 type 名称；本模块把当前源码中的事件类型和 payload 字段汇总为 catalog，避免只能从分散 helper 反查。
- 事件 payload 可能含 keyspace/table、CQL、token metadata、schema diff、endpoint set、repair mutation summary 和 audit user/operation，适合现场诊断，不适合作为长期外发审计流。

## 设计取舍

- 事件发布是进程内同步回调；它没有独立队列、背压或重试，换取实现简单和低延迟。订阅集合用 immutable copy-on-write map/set 更新，见 `src/java/org/apache/cassandra/diag/DiagnosticEventService.java:109-214`。
- 全局开关和订阅者检查是主要成本控制；多数 publisher helper 在构造 payload 前先检查 `isEnabled(...)`，例如 bootstrap、gossip、guardrail、read repair 和 schema helper，见 `src/java/org/apache/cassandra/dht/BootstrapDiagnostics.java:40-93`、`src/java/org/apache/cassandra/gms/GossiperDiagnostics.java:37-111`、`src/java/org/apache/cassandra/service/reads/repair/ReadRepairDiagnostics.java:41-78`。
- `DiagnosticEvent.toMap()` 要求值可序列化并尽量使用标准 Java 类型，避免 JMX 客户端需要 Cassandra 内部类，见 `src/java/org/apache/cassandra/diag/DiagnosticEvent.java:45-51`。
- Persistence 只按 event class FQCN 启停，不按 type 启停；`getEventClass()` 只允许 `org.apache.cassandra.*` 且必须继承 `DiagnosticEvent`，见 `src/java/org/apache/cassandra/diag/DiagnosticEventPersistence.java:96-149`。
- 部分事件枚举保留源码拼写和未发布值。当前源码中 `SchemaEventType.VERSION_ANOUNCED`、`TokenAllocatorEventType.*INSTANCIATED` 拼写是实际 API 字符串；`TokenMetadataEventType.PENDING_RANGE_CALCULATION_COMPLETED` 和 `TokenAllocatorEventType.TOKENS_ALLOCATED` 在当前 helper 中没有直接 publish site，见 `src/java/org/apache/cassandra/schema/SchemaEvent.java:66-88`、`src/java/org/apache/cassandra/dht/tokenallocator/TokenAllocatorEvent.java:78-87`、`src/java/org/apache/cassandra/locator/TokenMetadataDiagnostics.java:35-44`。

## 核心类

| 类 | 作用 |
|---|---|
| `DiagnosticEvent` | 所有事件的基类，携带创建时间、线程名、`getType()` 和 `toMap()` 合同。见 `src/java/org/apache/cassandra/diag/DiagnosticEvent.java:25-52` |
| `DiagnosticEventService` | pub/sub、MBean 注册、global enable 判断、publish 分发和 persistence 控制入口。见 `src/java/org/apache/cassandra/diag/DiagnosticEventService.java:43-305` |
| `DiagnosticEventServiceMBean` | JMX 暴露 `isDiagnosticsEnabled`、`disableDiagnostics`、`readEvents`、`enableEventPersistence`、`disableEventPersistence`。见 `src/java/org/apache/cassandra/diag/DiagnosticEventServiceMBean.java:25-58` |
| `DiagnosticEventPersistence` | 按 FQCN 订阅事件、写入 per-class store、读取事件 map 并广播 last id。见 `src/java/org/apache/cassandra/diag/DiagnosticEventPersistence.java:38-150` |
| `DiagnosticEventMemoryStore` | 默认 on-heap fixed-window store，默认最多 200 条/事件 class。见 `src/java/org/apache/cassandra/diag/store/DiagnosticEventMemoryStore.java:32-97` |
| `LastEventIdBroadcaster` | JMX Notification broadcaster，通知每个 event class 的最大 event id。见 `src/java/org/apache/cassandra/diag/LastEventIdBroadcaster.java:38-140` |
| `DiagnosticEventAuditLogger` / `AuditEvent` | 把 audit log entry 转成 `AuditEvent` 并走 DiagnosticEventService 发布。见 `src/java/org/apache/cassandra/audit/DiagnosticEventAuditLogger.java:23-39`、`src/java/org/apache/cassandra/audit/AuditEvent.java:31-74` |

## 核心接口

- `DiagnosticEventService.subscribe(Class, Consumer)`：订阅某个事件 class，见 `src/java/org/apache/cassandra/diag/DiagnosticEventService.java:104-117`。
- `DiagnosticEventService.subscribe(Class, Enum, Consumer)`：订阅某个事件 class 的特定 type，见 `src/java/org/apache/cassandra/diag/DiagnosticEventService.java:119-143`。
- `DiagnosticEventService.subscribeAll(Consumer)`：订阅所有事件，见 `src/java/org/apache/cassandra/diag/DiagnosticEventService.java:145-155`。
- `DiagnosticEventServiceMBean.readEvents(eventClazz, lastKey, limit)`：JMX read API，结果按 id 递增返回，见 `src/java/org/apache/cassandra/diag/DiagnosticEventServiceMBean.java:41-58`。
- 各 `*Diagnostics` helper 是生产发布接口；它们把业务对象转换为对应 `DiagnosticEvent` 子类，例如 `SchemaDiagnostics`、`GossiperDiagnostics`、`ReadRepairDiagnostics`，见 `src/java/org/apache/cassandra/schema/SchemaDiagnostics.java:28-178`、`src/java/org/apache/cassandra/gms/GossiperDiagnostics.java:31-113`、`src/java/org/apache/cassandra/service/reads/repair/ReadRepairDiagnostics.java:35-79`。

## 核心数据结构

- `subscribersAll`、`subscribersByClass`、`subscribersByClassAndType`：分别支持 all/class/class+type 三种订阅粒度，见 `src/java/org/apache/cassandra/diag/DiagnosticEventService.java:50-57`。
- event record map：`DiagnosticEventPersistence.getEvents()` 把 `toMap()` 结果扩展为 `class`、`type`、`ts`、`thread` 字段，见 `src/java/org/apache/cassandra/diag/DiagnosticEventPersistence.java:81-90`。
- `ConcurrentSkipListMap<Long, DiagnosticEvent>`：memory store 用反向 comparator 保存最新事件，并在 scan 时返回递增窗口，见 `src/java/org/apache/cassandra/diag/store/DiagnosticEventMemoryStore.java:37-82`。
- JMX last-id summary：`LastEventIdBroadcaster` 用 `Map<String, Comparable>` 保存 event class 到最大 id，并带 `last_updated_at`，见 `src/java/org/apache/cassandra/diag/LastEventIdBroadcaster.java:55-75`。

### 事件类型目录

| Event class | Types | Publisher / 入口 | Payload 摘要 |
|---|---|---|---|
| `org.apache.cassandra.audit.AuditEvent` | `SELECT`、`UPDATE`、`DELETE`、`TRUNCATE`、`CREATE_KEYSPACE`、`ALTER_KEYSPACE`、`DROP_KEYSPACE`、`CREATE_TABLE`、`DROP_TABLE`、`PREPARE_STATEMENT`、`DROP_TRIGGER`、`LIST_USERS`、`CREATE_INDEX`、`DROP_INDEX`、`GRANT`、`REVOKE`、`CREATE_TYPE`、`DROP_AGGREGATE`、`ALTER_VIEW`、`CREATE_VIEW`、`DROP_ROLE`、`CREATE_FUNCTION`、`ALTER_TABLE`、`BATCH`、`CREATE_AGGREGATE`、`DROP_VIEW`、`DROP_TYPE`、`DROP_FUNCTION`、`ALTER_ROLE`、`CREATE_TRIGGER`、`LIST_ROLES`、`LIST_PERMISSIONS`、`ALTER_TYPE`、`CREATE_ROLE`、`CREATE_IDENTITY`、`DROP_IDENTITY`、`USE_KEYSPACE`、`DESCRIBE`、`REQUEST_FAILURE`、`LOGIN_ERROR`、`UNAUTHORIZED_ATTEMPT`、`LOGIN_SUCCESS`。见 `src/java/org/apache/cassandra/audit/AuditLogEntryType.java:21-73` | `AuditEvent.create()`；通常由 `DiagnosticEventAuditLogger` 作为 audit logger 调用。见 `src/java/org/apache/cassandra/audit/AuditEvent.java:40-48` | `keyspace`、`operation`、`scope`、`user`，见 `src/java/org/apache/cassandra/audit/AuditEvent.java:66-74` |
| `org.apache.cassandra.db.guardrails.GuardrailEvent` | `WARNED`、`FAILED`，见 `src/java/org/apache/cassandra/db/guardrails/GuardrailEvent.java:31-34` | `GuardrailsDiagnostics.warned/failed()`，见 `src/java/org/apache/cassandra/db/guardrails/GuardrailsDiagnostics.java:41-61` | `name`、`message`，见 `src/java/org/apache/cassandra/db/guardrails/GuardrailEvent.java:65-72` |
| `org.apache.cassandra.dht.BootstrapEvent` | `BOOTSTRAP_USING_SPECIFIED_TOKENS`、`BOOTSTRAP_USING_RANDOM_TOKENS`、`TOKENS_ALLOCATED`，见 `src/java/org/apache/cassandra/dht/BootstrapEvent.java:62-67` | `BootstrapDiagnostics.useSpecifiedTokens/useRandomTokens/tokensAllocated()`，见 `src/java/org/apache/cassandra/dht/BootstrapDiagnostics.java:40-93` | token metadata、allocation keyspace、RF、numTokens、tokens，见 `src/java/org/apache/cassandra/dht/BootstrapEvent.java:75-85` |
| `org.apache.cassandra.dht.tokenallocator.TokenAllocatorEvent` | `REPLICATION_AWARE_TOKEN_ALLOCATOR_INSTANCIATED`、`NO_REPLICATION_AWARE_TOKEN_ALLOCATOR_INSTANCIATED`、`UNIT_ADDED`、`UNIT_REMOVED`、`TOKEN_INFOS_CREATED`、`RANDOM_TOKENS_GENERATED`、`TOKENS_ALLOCATED`，见 `src/java/org/apache/cassandra/dht/tokenallocator/TokenAllocatorEvent.java:78-87` | `TokenAllocatorDiagnostics` publishes all listed values except no direct current helper publish for `TOKENS_ALLOCATED` in this file，见 `src/java/org/apache/cassandra/dht/tokenallocator/TokenAllocatorDiagnostics.java:49-193` | partitioner、strategy、replicas、numTokens、sorted units/tokens、unitToTokens、tokens、unit、tokenInfo，见 `src/java/org/apache/cassandra/dht/tokenallocator/TokenAllocatorEvent.java:94-112` |
| `org.apache.cassandra.gms.GossiperEvent` | `MARKED_AS_SHUTDOWN`、`CONVICTED`、`REPLACEMENT_QUARANTINE`、`REPLACED_ENDPOINT`、`EVICTED_FROM_MEMBERSHIP`、`REMOVED_ENDPOINT`、`QUARANTINED_ENDPOINT`、`MARKED_ALIVE`、`REAL_MARKED_ALIVE`、`MARKED_DEAD`、`MAJOR_STATE_CHANGE_HANDLED`、`SEND_GOSSIP_DIGEST_SYN`，见 `src/java/org/apache/cassandra/gms/GossiperEvent.java:52-66` | `GossiperDiagnostics` methods publish one event per membership/state transition，见 `src/java/org/apache/cassandra/gms/GossiperDiagnostics.java:37-111` | endpoint、quarantine expiration、local state、endpoint state map、shadow round、removed/live/seeds/unreachable sets，见 `src/java/org/apache/cassandra/gms/GossiperEvent.java:94-110` |
| `org.apache.cassandra.hints.HintEvent` | enum contains `DISPATCHING_STARTED`、`DISPATCHING_PAUSED`、`DISPATCHING_RESUMED`、`DISPATCHING_SHUTDOWN`、`DISPATCHER_CREATED`、`DISPATCHER_CLOSED`、`DISPATCHER_PAGE`、`DISPATCHER_HINT_RESULT`、`ABORT_REQUESTED`，见 `src/java/org/apache/cassandra/hints/HintEvent.java:34-48` | `HintDiagnostics` publishes dispatcher-level values: created/closed/page/abort/result，见 `src/java/org/apache/cassandra/hints/HintDiagnostics.java:36-82` | target host/address、dispatch result、page success/failure/timeout counts，见 `src/java/org/apache/cassandra/hints/HintEvent.java:87-100` |
| `org.apache.cassandra.hints.HintsServiceEvent` | `DISPATCHING_STARTED`、`DISPATCHING_PAUSED`、`DISPATCHING_RESUMED`、`DISPATCHING_SHUTDOWN`，见 `src/java/org/apache/cassandra/hints/HintsServiceEvent.java:31-37` | `HintsServiceDiagnostics.dispatching*()`，见 `src/java/org/apache/cassandra/hints/HintsServiceDiagnostics.java:36-62` | dispatch paused/shutdown/executor state booleans，见 `src/java/org/apache/cassandra/hints/HintsServiceEvent.java:61-70` |
| `org.apache.cassandra.locator.TokenMetadataEvent` | `PENDING_RANGE_CALCULATION_STARTED`、`PENDING_RANGE_CALCULATION_COMPLETED`，见 `src/java/org/apache/cassandra/locator/TokenMetadataEvent.java:32-36` | current `TokenMetadataDiagnostics` publishes `PENDING_RANGE_CALCULATION_STARTED` only，见 `src/java/org/apache/cassandra/locator/TokenMetadataDiagnostics.java:35-44` | keyspace、tokenMetadata string，见 `src/java/org/apache/cassandra/locator/TokenMetadataEvent.java:54-61` |
| `org.apache.cassandra.schema.SchemaAnnouncementEvent` | `SCHEMA_MUTATIONS_ANNOUNCED`、`SCHEMA_TRANSFORMATION_ANNOUNCED`、`SCHEMA_MUTATIONS_RECEIVED`，见 `src/java/org/apache/cassandra/schema/SchemaAnnouncementEvent.java:50-55` | `SchemaAnnouncementDiagnostics` publishes announced/received/transformation events，见 `src/java/org/apache/cassandra/schema/SchemaAnnouncementDiagnostics.java:35-58` | destination/ignored endpoints、statement audit log context、sender，见 `src/java/org/apache/cassandra/schema/SchemaAnnouncementEvent.java:76-103` |
| `org.apache.cassandra.schema.SchemaEvent` | `KS_METADATA_LOADED`、`KS_METADATA_RELOADED`、`KS_METADATA_REMOVED`、`VERSION_UPDATED`、`VERSION_ANOUNCED`、`KS_CREATING`、`KS_CREATED`、`KS_ALTERING`、`KS_ALTERED`、`KS_DROPPING`、`KS_DROPPED`、`TABLE_CREATING`、`TABLE_CREATED`、`TABLE_ALTERING`、`TABLE_ALTERED`、`TABLE_DROPPING`、`TABLE_DROPPED`、`SCHEMATA_LOADING`、`SCHEMATA_LOADED`、`SCHEMATA_CLEARED`，见 `src/java/org/apache/cassandra/schema/SchemaEvent.java:66-88` | `SchemaDiagnostics` publishes metadata/version/keyspace/table/schema lifecycle events，见 `src/java/org/apache/cassandra/schema/SchemaDiagnostics.java:34-175` | keyspace/table collections、index table map、schema version、keyspace/table/diff payloads，见 `src/java/org/apache/cassandra/schema/SchemaEvent.java:126-154` |
| `org.apache.cassandra.service.PendingRangeCalculatorServiceEvent` | `TASK_STARTED`、`TASK_FINISHED_SUCCESSFULLY`、`TASK_EXECUTION_REJECTED`、`TASK_COUNT_CHANGED`，见 `src/java/org/apache/cassandra/service/PendingRangeCalculatorServiceEvent.java:36-42` | `PendingRangeCalculatorServiceDiagnostics.task*()`，见 `src/java/org/apache/cassandra/service/PendingRangeCalculatorServiceDiagnostics.java:35-64` | optional `taskCount`，见 `src/java/org/apache/cassandra/service/PendingRangeCalculatorServiceEvent.java:66-74` |
| `org.apache.cassandra.service.reads.repair.ReadRepairEvent` | `START_REPAIR`、`SPECULATED_READ`，见 `src/java/org/apache/cassandra/service/reads/repair/ReadRepairEvent.java:57-61` | `ReadRepairDiagnostics.startRepair/speculatedRead()`，见 `src/java/org/apache/cassandra/service/reads/repair/ReadRepairDiagnostics.java:41-56` | keyspace、table、CQL command、consistency、speculative retry、destination/all endpoints、optional digests，见 `src/java/org/apache/cassandra/service/reads/repair/ReadRepairEvent.java:82-113` |
| `org.apache.cassandra.service.reads.repair.PartitionRepairEvent` | `SEND_INITIAL_REPAIRS`、`SPECULATED_WRITE`、`UPDATE_OVERSIZED`，见 `src/java/org/apache/cassandra/service/reads/repair/PartitionRepairEvent.java:52-57` | `ReadRepairDiagnostics.sendInitialRepair/speculatedWrite/speculatedWriteOversized()`，见 `src/java/org/apache/cassandra/service/reads/repair/ReadRepairDiagnostics.java:59-78` | keyspace、partition key hex、token、consistency、destination、mutation summary，见 `src/java/org/apache/cassandra/service/reads/repair/PartitionRepairEvent.java:85-101` |

## 生命周期

```text
DiagnosticEventService.instance()
  -> constructor registers org.apache.cassandra.diag:type=DiagnosticEventService
  -> DiagnosticEventPersistence.start()
     -> LastEventIdBroadcaster.instance() registers its MBean

subscriber or MBean persistence setup
  -> subscribe(class), subscribe(class,type), subscribeAll()
  -> optional enableEventPersistence(FQCN) subscribes persistence consumer

publisher helper
  -> isEnabled(event class, event type)
  -> construct DiagnosticEvent
  -> DiagnosticEventService.publish(event)
  -> dispatch class+type subscribers
  -> dispatch class subscribers
  -> dispatch all subscribers
  -> persistence consumer stores event and updates last id
```

## 调用链

- `publish()` 先检查 `DatabaseDescriptor.diagnosticEventsEnabled()`，关闭时直接返回，见 `src/java/org/apache/cassandra/diag/DiagnosticEventService.java:72-78`。
- `publish()` 会在 trace 日志中调用 `event.toMap()`，所以生产 publisher 更应该在构造事件前用 `isEnabled(...)` 避免无订阅者时生成复杂 payload，见 `src/java/org/apache/cassandra/diag/DiagnosticEventService.java:72-101`。
- `enableEventPersistence(FQCN)` 会按 class 订阅 persistence consumer；收到事件后写 per-class store，再调用 `LastEventIdBroadcaster.setLastEventId()`，见 `src/java/org/apache/cassandra/diag/DiagnosticEventPersistence.java:96-129`。
- `readEvents(FQCN, lastKey, limit)` 使用 `scan(key, limit + 1)` 排除 last key 本身，并把事件扩展为 JMX-friendly map，见 `src/java/org/apache/cassandra/diag/DiagnosticEventPersistence.java:62-94`。
- Distributed test helper `Listen` 订阅 `SchemaEvent.VERSION_UPDATED` 和 `GossiperEvent.REAL_MARKED_ALIVE`，说明 diagnostic events 也被 in-JVM test harness 当作内部同步信号，见 `test/distributed/org/apache/cassandra/distributed/impl/Listen.java:37-48`。

## 配置项

| 配置项 / API | 默认值 | 作用 |
|---|---:|---|
| `diagnostic_events_enabled` | `false` | 全局开关；模板说明事件经 JMX 供客户端访问，见 `conf/cassandra.yaml:1933-1936`、`src/java/org/apache/cassandra/config/Config.java:704-708` |
| `DatabaseDescriptor.diagnosticEventsEnabled()` | 读取当前 config | publish/isEnabled 的 runtime 判断入口，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4401-4408` |
| `DiagnosticEventServiceMBean.disableDiagnostics()` | runtime 操作 | 运行时 kill switch；永久化仍需改 YAML，见 `src/java/org/apache/cassandra/diag/DiagnosticEventServiceMBean.java:30-39` |
| `DiagnosticEventServiceMBean.enableEventPersistence(FQCN)` | 按需启用 | 开启某个 event class 的短期 memory persistence，见 `src/java/org/apache/cassandra/diag/DiagnosticEventServiceMBean.java:48-58` |

## Metrics

- Diagnostic Events 没有独立 Dropwizard metric registry；主要观测入口是 `DiagnosticEventServiceMBean`、`LastEventIdBroadcasterMBean` 和 `readEvents()` 返回窗口。
- 性能基准存在于 microbench：`DiagnosticEventServiceBench` 用 0/1/12 个 subscriber 评估 publish 成本，`DiagnosticEventPersistenceBench` 评估 persistence consumer 成本，见 `test/microbench/org/apache/cassandra/test/microbench/DiagnosticEventServiceBench.java:50-83`、`test/microbench/org/apache/cassandra/test/microbench/DiagnosticEventPersistenceBench.java:50-72`。
- 如果需要把事件数量纳入外部监控，当前更可靠的 source 是 JMX broadcaster 的 last-id summary，而不是 Dropwizard counter。

## 日志

- `DiagnosticEventService.publish()` 在 trace level 打印事件 class 和 `toMap()` payload，见 `src/java/org/apache/cassandra/diag/DiagnosticEventService.java:72-78`。
- `DiagnosticEventPersistence` 在 debug level 记录 enable/disable/read 数量，在 trace level 记录 persistence consumer 收到事件，见 `src/java/org/apache/cassandra/diag/DiagnosticEventPersistence.java:92-126`。
- `LastEventIdBroadcaster` 通过 JMX Notification `"event_last_id_summary"` 发出 last-id summary，不写普通日志作为主通道，见 `src/java/org/apache/cassandra/diag/LastEventIdBroadcaster.java:126-140`。

## 运维关注点

- 启用事件前先确认消费者需要的 FQCN 和 type；JMX persistence 入参是事件 class FQCN，例如 `org.apache.cassandra.schema.SchemaEvent`。
- 事件 payload 可能含用户、CQL operation、schema statement context、repair mutation summary、token/ring 状态或 endpoint sets。不要把 Diagnostic Events 当作无敏感数据的公共遥测流。
- Persistence 是 on-heap、固定窗口、per-class store；默认每个 event class 最多 200 条，节点重启或 store 被覆盖后不可恢复，见 `src/java/org/apache/cassandra/diag/store/DiagnosticEventMemoryStore.java:39-57`。
- class/type 订阅和 all 订阅会同步执行 consumer；慢 consumer 会拖住发布线程。
- 枚举名称按源码拼写订阅，尤其是 `VERSION_ANOUNCED`、`REPLICATION_AWARE_TOKEN_ALLOCATOR_INSTANCIATED` 和 `NO_REPLICATION_AWARE_TOKEN_ALLOCATOR_INSTANCIATED`。

## 性能瓶颈

- 高频事件如果配合 all subscriber 或 persistence，会把每个事件同步送给更多 consumer；`DiagnosticEventServiceTest.testPublish()` 覆盖同一事件被 class/type/all 多路消费的行为，见 `test/unit/org/apache/cassandra/diag/DiagnosticEventServiceTest.java:176-203`。
- `toMap()` 可能做字符串化快照，例如 schema diff、token metadata、gossiper endpoint state、mutation summary；这些 payload 不应该在无订阅者时构造。
- Memory store 使用 `ConcurrentSkipListMap` 并在写入时清理超出窗口的尾部；高频事件 class 会持续维护排序 map 和 truncate，见 `src/java/org/apache/cassandra/diag/store/DiagnosticEventMemoryStore.java:50-78`。
- AuditEvent 会跟随 audit logger 进入 request/auth 路径；如果用 `DiagnosticEventAuditLogger`，事件订阅和 persistence 成本会叠加到审计路径。

## 常见故障

- 没有收到事件：先检查 `diagnostic_events_enabled`，关闭时 `publish()` 直接返回；测试覆盖见 `test/unit/org/apache/cassandra/diag/DiagnosticEventServiceTest.java:205-212`。
- JMX `enableEventPersistence()` 报 class 错：FQCN 必须以 `org.apache.cassandra.` 开头且继承 `DiagnosticEvent`，见 `src/java/org/apache/cassandra/diag/DiagnosticEventPersistence.java:132-144`。
- 订阅 type 名称无效：按源码 enum 字符串匹配，拼写修正后的名称不会命中当前代码。
- `readEvents()` 只返回最近窗口：超过 memory store max size 的旧事件会被清理，`DiagnosticEventMemoryStoreTest.testMaxElements()` 覆盖该行为，见 `test/unit/org/apache/cassandra/diag/store/DiagnosticEventMemoryStoreTest.java:133-169`。
- Hints dispatcher/service 事件容易混淆：`HintEvent` enum 里有 `DISPATCHING_*`，但当前 service-level publish 入口在 `HintsServiceEvent`，dispatcher-level publish 入口在 `HintDiagnostics`。

## 测试用例

- `DiagnosticEventServiceTest` 覆盖 class/type/all 订阅、unsubscribe、cleanup、publish fan-out 和 global enabled flag，见 `test/unit/org/apache/cassandra/diag/DiagnosticEventServiceTest.java:54-240`。
- `DiagnosticEventMemoryStoreTest` 覆盖 empty/single/identity/limit/seek/max elements，见 `test/unit/org/apache/cassandra/diag/store/DiagnosticEventMemoryStoreTest.java:32-170`。
- `DiagEventsBlockingReadRepairTest` 开启 `diagnostic_events_enabled`，订阅 `ReadRepairEvent` 和 `PartitionRepairEvent`，验证 read repair destinations、all endpoints 和 mutation summary，见 `test/unit/org/apache/cassandra/service/reads/repair/DiagEventsBlockingReadRepairTest.java:62-199`。
- `CQLUserAuditTest` 用 `DiagnosticEventAuditLogger` 把 audit log 变成 `AuditEvent` 并订阅事件队列，见 `test/unit/org/apache/cassandra/transport/CQLUserAuditTest.java:70-90`。
- `GuardrailTester` 在 guardrail tests 中订阅/注销 `GuardrailEvent`，见 `test/unit/org/apache/cassandra/db/guardrails/GuardrailTester.java:145-156`。
- Distributed `Listen` helper 订阅 schema/gossip diagnostic events，见 `test/distributed/org/apache/cassandra/distributed/impl/Listen.java:37-48`。
- `python3 research/tools/check-diagnostic-events-catalog-drift.py` 检查生产 `DiagnosticEvent` class/type 与本 catalog 的覆盖同步，见 `research/module-diagnostic-events-drift-checker.md`。
