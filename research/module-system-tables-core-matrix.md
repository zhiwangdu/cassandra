# Module: System Tables Core Matrix

## 范围

本模块补齐 `system_traces.sessions/events` 和 `system` keyspace 中非 schema/auth/virtual 表的逐表矩阵，重点是列语义、写入方、读取方、生命周期和运维风险。源码 CQL 列契约和 primary key 的机器可校验清单见 `research/module-system-table-column-contract.md`，其中也覆盖 `system_schema`；`system_auth`、`system_distributed`、`system_views` 的主体设计仍以 `research/module-system-tables.md`、`research/module-schema-cql-auth-native-deep-dive.md`、`research/module-observability-internals.md` 和 `research/module-observability-mapping.md` 为主。

## 设计目标

- 把启动前可用的本地状态、协调器恢复状态、存储观测状态和 trace 观测状态拆到不同 system tables，避免普通用户 keyspace 未打开时无法恢复节点。
- 用 `SystemKeyspace` 集中定义 `system` keyspace 的表 schema，并通过内部 CQL 或 `Mutation` 写入，入口见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:151-181`、`src/java/org/apache/cassandra/db/SystemKeyspace.java:196-209` 和 `src/java/org/apache/cassandra/db/SystemKeyspace.java:536-560`。
- 用 `TraceKeyspace` 将 query/repair tracing 落到 replicated `system_traces`，并用 TTL 控制数据保留，表定义与 metadata 见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:50-112`。
- 让 batchlog、Paxos、prepared statements、view build、repair session、range streaming 和 table estimates 在重启后可恢复或可继续清理。
- 让默认可读的系统观测表满足 driver、cqlsh、nodetool 和运维排查需求，同时不让业务请求依赖手工维护的系统表状态。

## 解决的问题

- trace 查询需要把 session metadata 与事件时间线分表保存；`TraceKeyspace` 定义 `sessions` 和 `events`，`TracingImpl` 负责 start/stop session mutation，`TraceStateImpl` 负责 event mutation，见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:73-162`、`src/java/org/apache/cassandra/tracing/TracingImpl.java:40-66` 和 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:63-121`。
- logged batch 需要在 coordinator 失败后 replay；`BatchlogManager.store()` 写 `system.batches`，replay 分页读取并删除已处理 batch，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:125-165` 和 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:188-225`。
- Paxos/LWT 需要跨重启保留 promise、proposal、commit 和 repair low bound；`SystemKeyspace.loadPaxosState()`、`savePaxos*()`、`savePaxosRepairHistory()` 覆盖这些状态，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1325-1521`。
- prepared statement cache 需要跨重启预热，同时要能在缓存逐出和无效 statement 时清理 `system.prepared_statements`，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:132-199`、`src/java/org/apache/cassandra/cql3/QueryProcessor.java:820-834` 和 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1874-1955`。
- MV build、consistent repair、bootstrap streamed ranges 和 unbootstrap transferred ranges 都需要本地 checkpoint，分别写 `view_builds_in_progress`/`built_views`、`repairs`、`available_ranges_v2`、`transferred_ranges_v2`，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:657-735`、`src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:378-417`、`src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:564-640` 和 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1672-1764`。

## 设计取舍

- `system` 使用 local keyspace 语义：启动快、无复制依赖，但节点级状态不会自动跨节点修复；`system` 表 metadata 来自 `SystemKeyspace.metadata()`，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:536-560`。
- `system_traces` 使用 replicated simple keyspace，RF 取 `cassandra.system_traces.default_rf` 与 `default_keyspace_rf` 的较大值，见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:536-542` 和 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:50-112`。
- tracing event 写入异步提交到 `Stage.TRACING` 并用 `ConsistencyLevel.ANY`，降低被观测请求的耦合，但 overload 或 TTL 可能导致 trace 不完整，见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:73-121`。
- `SystemKeyspace.parse()` 对 system tables 设置 `gcGraceSeconds(0)` 和 1 小时 memtable flush period，减少本地系统表墓碑保留成本，但要求调用方用明确的 flush/checkpoint 保证重启语义，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:527-533`。
- 只有 `batches`、`paxos`、`compaction_history`、`prepared_statements`、`repairs` 被标记为可跨多个数据盘拆分，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:177-181`。

## 核心类

| 类 | 作用 |
|---|---|
| `SystemKeyspace` | `system` 表定义、metadata、读写 helper、range serialization、Paxos/prepared/MV/range/repair 状态入口。见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:151-181`、`src/java/org/apache/cassandra/db/SystemKeyspace.java:536-560` |
| `TraceKeyspace` | `system_traces` schema、默认 RF、session/event mutation builder。见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:50-162` |
| `Tracing` / `TracingImpl` / `TraceStateImpl` | trace session map、native/internode trace propagation、start/stop/event mutation 和 async write。见 `src/java/org/apache/cassandra/tracing/Tracing.java:72-109`、`src/java/org/apache/cassandra/tracing/TracingImpl.java:40-118`、`src/java/org/apache/cassandra/tracing/TraceStateImpl.java:45-121` |
| `BatchlogManager` | `system.batches` 的 store/remove/replay/MBean owner。见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:87-225` |
| `QueryProcessor` | prepared statement cache 与 `system.prepared_statements` 的 write/preload/remove owner。见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:132-199`、`src/java/org/apache/cassandra/cql3/QueryProcessor.java:820-834` |
| `SizeEstimatesRecorder` | 周期计算并写 `system.size_estimates` 和 `system.table_estimates`。见 `src/java/org/apache/cassandra/db/SizeEstimatesRecorder.java:67-121` |
| `LocalSessions` | consistent incremental repair 的 `system.repairs` 读写与清理 owner。见 `src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:158-164`、`src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:378-417`、`src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:564-640` |

## 核心接口

- `SystemKeyspace.metadata()` / `tables()`：返回 `system` keyspace metadata 和表集合，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:536-560`。
- `TraceKeyspace.metadata()`：返回 `system_traces` replicated metadata，RF 下限来自 `SYSTEM_TRACES_DEFAULT_RF`，见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:50-112`。
- `SystemKeyspace.updateCompactionHistory()` / `getCompactionHistory()`：写入和 JMX 读取 compaction history，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:627-654`。
- `SystemKeyspace.updateViewBuildStatus()` / `getViewBuildStatus()` / `finishViewBuildStatus()`：MV 本地 build checkpoint，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:695-735`。
- `SystemKeyspace.updateAvailableRanges()` / `getAvailableRanges()` / `updateTransferredRanges()` / `getTransferredRanges()`：bootstrap 与 unbootstrap range checkpoint，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1672-1764`。
- `SystemKeyspace.writePreparedStatement()` / `loadPreparedStatements()` / `removePreparedStatement()`：prepared statement 持久化接口，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1874-1955`。
- `TraceKeyspace.makeStartSessionMutation()` / `makeStopSessionMutation()` / `makeEventMutation()`：trace row mutation builder，见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:115-162`。

## 核心数据结构

### `system_traces`

| 表 | 主键 | 关键列 | 写入方 | 读取/消费方 |
|---|---|---|---|---|
| `sessions` | `session_id` | `command`、`client`、`coordinator`、`coordinator_port`、`duration`、`parameters`、`request`、`started_at` | `TracingImpl.begin()` 写 start row，`stopSessionImpl()` 写 duration，见 `src/java/org/apache/cassandra/tracing/TracingImpl.java:40-66` | driver/cqlsh/用户查询读取 trace session；默认可读授权见 `src/java/org/apache/cassandra/service/ClientState.java:77-89` |
| `events` | `session_id`、`event_id` | `activity`、`source`、`source_port`、`source_elapsed`、`thread` | `TraceStateImpl.traceImpl()` 和 non-local `TracingImpl.trace()` 写 event，见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:63-70`、`src/java/org/apache/cassandra/tracing/TracingImpl.java:106-115` | cqlsh/driver 读取事件时间线；distributed helpers 直接查询，见 `test/distributed/org/apache/cassandra/distributed/impl/TracingUtil.java:69-97` |

兼容性细节：`coordinator_port` 和 `source_port` 只有在协议/集群版本允许时写入；builder 中的条件分支见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:115-162`。

### `system`

| 表 | 主键/关键列 | 作用 | 写入方/读取方 |
|---|---|---|---|
| `batches` | `id timeuuid`、`mutations list<blob>`、`version` | logged batch 持久化与 replay | `BatchlogManager.store/remove/replayFailedBatches()`，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:125-225` |
| `paxos` | `row_key`、`cf_id`、ballot/proposal/commit blob/version | LWT/Paxos promise、proposal、commit 状态 | `SystemKeyspace.loadPaxosState()` 和 `savePaxosWritePromise/readPromise/proposal/commit()`，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1325-1492` |
| `paxos_repair_history` | `keyspace_name`、`table_name`、`points` | Paxos repair low-bound history | `savePaxosRepairHistory()` / `loadPaxosRepairHistory()`，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1494-1521` |
| `IndexInfo` | `table_name`、`index_name` | secondary index build marker | `isIndexBuilt()`、`setIndexBuilt()`、`setIndexRemoved()`，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1202-1220` |
| `peer_events_v2` | `peer`、`peer_port`、`hints_dropped` | hints dropped per peer/time bucket | `updateHintsDropped()` 同时写 legacy 和 v2，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:888-895` |
| `compaction_history` | `id timeuuid` | compaction bytes、rows merged、properties，TTL 7 天 | `updateCompactionHistory()` 写入，`getCompactionHistory()` 读出，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:320-334`、`src/java/org/apache/cassandra/db/SystemKeyspace.java:627-654` |
| `sstable_activity_v2` | `keyspace_name`、`table_name`、`id` | SSTable read meter 恢复 | `persistSSTableReadMeter()` / `clearSSTableReadMeter()`，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1544-1592` |
| `table_estimates` | `keyspace_name`、`table_name`、`range_type`、range bounds | primary/local-primary size estimates | `SizeEstimatesRecorder` 调 `updateTableEstimates()`，见 `src/java/org/apache/cassandra/db/SizeEstimatesRecorder.java:67-121`、`src/java/org/apache/cassandra/db/SystemKeyspace.java:1620-1645` |
| `available_ranges_v2` | `keyspace_name` | bootstrap/replace 已 stream 到本机的 full/transient ranges | `updateAvailableRanges()`、`getAvailableRanges()`、reset 方法，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1672-1727` |
| `transferred_ranges_v2` | `operation`、`peer`、`peer_port`、`keyspace_name` | unbootstrap/decommission 已传输 ranges | `updateTransferredRanges()` / `getTransferredRanges()`，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1729-1764` |
| `view_builds_in_progress` | `keyspace_name`、`view_name`、range tokens | MV build checkpoint | `updateViewBuildStatus()` / `getViewBuildStatus()` / `finishViewBuildStatus()`，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:695-735` |
| `built_views` | `keyspace_name`、`view_name`、`status_replicated` | MV 本地已构建与状态复制 marker | `isViewBuilt()`、`setViewBuilt()`、`setViewBuiltReplicated()`，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:657-709` |
| `prepared_statements` | `prepared_id` | prepared cache 持久化 | `QueryProcessor.prepare()` 写入，启动时 `preloadPreparedStatements()` 读取，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:165-199`、`src/java/org/apache/cassandra/cql3/QueryProcessor.java:820-834` |
| `repairs` | `parent_id` | consistent incremental repair local sessions | `LocalSessions.start/save/load/deleteRow()`，见 `src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:378-417`、`src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:564-640` |
| `top_partitions` | `keyspace_name`、`table_name`、`top_type` | top partition tracker snapshot | `saveTopPartitions()` / `getTopPartitions()`，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1961-2003` |

Legacy 表 `peers`、`peer_events`、`transferred_ranges`、`available_ranges`、`size_estimates`、`sstable_activity` 仍在 metadata 中保留或双写，用于升级/降级兼容，定义见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:474-525`。

## 生命周期

启动路径：

```text
CassandraDaemon.setup()
  -> PaxosState.maybeRebuildUncommittedState()
  -> StorageService.cleanupSizeEstimates()
  -> schedule SizeEstimatesRecorder
  -> ActiveRepairService.start()
  -> QueryProcessor.preloadPreparedStatements()
  -> StorageService.initServer()
```

源码锚点见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:355-383`。

Trace 路径：

```text
traceable request
  -> Tracing.newSession()
  -> TracingImpl.begin()
     -> TraceKeyspace.makeStartSessionMutation()
  -> Tracing.trace(...)
     -> TraceStateImpl.executeMutation()
     -> Stage.TRACING
     -> StorageProxy.mutate(..., ANY)
  -> Tracing.stopSession()
     -> TraceKeyspace.makeStopSessionMutation()
```

源码锚点见 `src/java/org/apache/cassandra/tracing/Tracing.java:158-215`、`src/java/org/apache/cassandra/tracing/TracingImpl.java:40-66` 和 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:63-121`。

Local checkpoint 路径：

```text
component state transition
  -> SystemKeyspace helper writes system table
  -> selective forceBlockingFlush where restart correctness matters
  -> startup/background task reloads or cleans row
```

典型例子包括 MV build finish 先写 `built_views` 再删 progress row，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:695-704`；prepared statement 启动分页预热并在超出缓存阈值时提前返回，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1899-1939`。

## 调用链

- Batchlog：`StorageProxy` logged batch path 写 batchlog，`BatchlogManager` store/replay/remove `system.batches`，入口见 `src/java/org/apache/cassandra/service/StorageProxy.java:1026`、`src/java/org/apache/cassandra/service/StorageProxy.java:1301` 和 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:125-225`。
- Paxos：`PaxosState` 调用 `SystemKeyspace.savePaxos*()` 保存 promise/proposal/commit，见 `src/java/org/apache/cassandra/service/paxos/PaxosState.java:585-661` 和 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1384-1492`。
- Size estimates：daemon schedule `SizeEstimatesRecorder`，recorder 计算 primary/local-primary estimates 并写 legacy/new tables，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:364-371` 和 `src/java/org/apache/cassandra/db/SizeEstimatesRecorder.java:67-121`。
- Prepared statements：`QueryProcessor.prepare()` 写 `system.prepared_statements`，daemon setup 预热，缓存逐出删除，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:132-199`、`src/java/org/apache/cassandra/cql3/QueryProcessor.java:820-834`。
- Repair sessions：`ActiveRepairService.start()` 后 `LocalSessions.start()` 从 `system.repairs` 分页加载，并在 malformed row 时删除，见 `src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:378-417`。
- Tracing：`Tracing.traceOutgoingMessage()` 处理 internode tracing，已关闭 session 的 response 会以 non-local trace 写 `events`，见 `src/java/org/apache/cassandra/tracing/Tracing.java:260-304`。

## 配置项

| 配置项 | 作用 | 源码 |
|---|---|---|
| `trace_type_query_ttl` | query trace row TTL，默认 1d | `src/java/org/apache/cassandra/config/Config.java:550-554`、`conf/cassandra.yaml:1750-1754` |
| `trace_type_repair_ttl` | repair trace row TTL，默认 7d | `src/java/org/apache/cassandra/config/Config.java:550-554`、`conf/cassandra.yaml:1750-1754` |
| `cassandra.system_traces.default_rf` | `system_traces` RF 下限，默认 2 | `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:536-542`、`src/java/org/apache/cassandra/tracing/TraceKeyspace.java:50-112` |
| `cassandra.wait_for_tracing_events_timeout_secs` | stop session 时等待 pending trace event 的秒数，默认 0 | `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:622-627`、`src/java/org/apache/cassandra/tracing/TraceStateImpl.java:53-100` |
| `cassandra.custom_tracing_class` | 替换默认 tracing 实现 | `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:176-181`、`src/java/org/apache/cassandra/tracing/Tracing.java:111-129` |
| `cassandra.size_recorder_interval` | table estimates 周期任务间隔，0 表示不调度 | `src/java/org/apache/cassandra/service/CassandraDaemon.java:364-371` |
| `prepared_statements_cache_size` | prepared preload 的早停阈值参考，防止启动无限分页加载泄漏数据 | `src/java/org/apache/cassandra/db/SystemKeyspace.java:1905-1935` |

## Metrics

- `system` 普通本地表仍暴露常规 table metrics；对 `batches`、`paxos`、`prepared_statements`、`repairs` 这类热点表，读写压力会体现在表级 memtable/compaction/latency 指标中。
- `BatchlogManager` 有 MBean 和 replay counter，MBean 名称与 replay 方法见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:87-99`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:167-185`。
- prepared statements 还有 `CQLMetricsTable` 的 prepared count/evicted/executed/ratio 视图，定义见 `src/java/org/apache/cassandra/db/virtual/CQLMetricsTable.java:31-70`。
- tracing 没有独立 Dropwizard tracing metric；主要看 `system_traces` 行、`Stage.TRACING` 压力和 `TraceStateImpl` warning，见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:104-121`。
- table estimates 的计算成本不直接写专属 metric；`SizeEstimatesRecorder` trace 日志记录每张表估算耗时，见 `src/java/org/apache/cassandra/db/SizeEstimatesRecorder.java:113-119`。

## 日志

- `TraceStateImpl.waitForPendingEvents()` 对等待、timeout 和 throwable 分别记录 trace/error，见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:73-100`。
- trace mutation 写入遇到 overloaded nodes 时只 warn，不中断原请求，见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:112-121`。
- prepared preload 如果加载字节超过缓存阈值会 warn 并建议清理 `system.prepared_statements`，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1919-1935`。
- `LocalSessions.start()` 会记录加载 session 数，并删除 malformed repair session row，见 `src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:403-417`。
- `BatchlogManager.replayFailedBatches()` 对开始、取消、完成使用 trace 日志，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:200-226`。

## 运维关注点

- 不要把 `system` 表当业务表手工修正；这些行多数是组件 checkpoint，错误更新可能让 bootstrap、repair、Paxos、prepared cache 或 MV build 进入不一致状态。
- `system_traces` 默认对 authenticated users 可读，方便 cqlsh/driver trace，但 trace parameters 可能包含 query 文本和部分 bind values；默认可读资源见 `src/java/org/apache/cassandra/service/ClientState.java:77-89`。
- 高频 tracing 会制造大量 TTL rows；生产中应短期开启或按概率采样，TTL 配置见 `conf/cassandra.yaml:1750-1754`。
- `system.prepared_statements` 过大时会拖慢启动预热；源码已有 110% cache-size 早停和 warn，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1905-1935`。
- `system.available_ranges_v2` 和 `system.transferred_ranges_v2` 与 bootstrap/decommission resume 语义相关，手工清空会影响是否重复 stream 或跳过已完成 ranges。
- `system.repairs` 行保留 consistent repair session 状态；清理前必须确认 session 已完成且不再持有 pending repair SSTables，清理逻辑见 `src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:464-508`。

## 性能瓶颈

- tracing 每个 event 都会构造 mutation 并走 async internal write；高采样会让 `Stage.TRACING`、commitlog、memtable 和 `system_traces.events` compaction 变热，见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:63-121`。
- `system.batches` replay 需要分页扫描 token range，batchlog backlog 大时会受 replay throttle 与 hints 写入影响，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:200-225`。
- `SizeEstimatesRecorder` 每轮遍历 non-local keyspaces 和 table SSTables，估算成本随表数、SSTable 数、range 数上升，见 `src/java/org/apache/cassandra/db/SizeEstimatesRecorder.java:78-121`。
- `system.prepared_statements` 泄漏或异常膨胀会增加启动分页和 parse/prepare CPU，早停分支见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1905-1939`。
- Paxos state table 使用 LCS 与 uncommitted index，LWT 高压下 `system.paxos` 写放大会与 purge/repair 策略耦合，表定义和写入见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:223-240`、`src/java/org/apache/cassandra/db/SystemKeyspace.java:1325-1492`。

## 常见故障

- trace session 缺失或 event 不完整：可能是 TTL 到期、RF/节点不可用、`Stage.TRACING` 积压或 overloaded warning；写入路径见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:104-121`。
- batchlog backlog 不下降：检查 `system.batches` 行数、BatchlogManager replay 任务和 batchlog replay throttle；计数和 replay 查询见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:167-225`。
- 重启后 prepared statement 恢复慢：检查 `system.prepared_statements` 行数和 preload warning，加载路径见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:165-199`。
- MV build 重启后反复从头跑：检查 `view_builds_in_progress` 和 `built_views` checkpoint 是否被错误清理；finish 顺序见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:695-704`。
- incremental repair session 无法清理：检查 `system.repairs` 中 state、last_update、participants 和 pending repair SSTable 状态；加载/保存字段见 `src/java/org/apache/cassandra/repair/consistent/LocalSessions.java:564-640`。
- streaming resume 行为异常：检查 `available_ranges_v2` 与 `transferred_ranges_v2` 是否被重置或缺少 peer port 维度；读写路径见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1672-1764`。

## 测试用例

- `SystemKeyspaceTablesNamesTest` 校验 `system` 和 `system_traces` 的 metadata table name 集合与源码常量一致，见 `test/unit/org/apache/cassandra/cql3/SystemKeyspaceTablesNamesTest.java:51-72`。
- `python3 research/tools/check-system-table-column-drift.py` 校验 `system` 与 `system_traces` 的源码 CQL 列契约进入 `module-system-table-column-contract.md`。
- `BatchlogManagerTest` 覆盖 batchlog store、count、replay 和 remove 行为，见 `test/unit/org/apache/cassandra/batchlog/BatchlogManagerTest.java:133-169`、`test/unit/org/apache/cassandra/batchlog/BatchlogManagerTest.java:278-333`。
- `PstmtPersistenceTest` 覆盖 prepared statement preload、paging 和 cache-full 早停，见 `test/unit/org/apache/cassandra/cql3/PstmtPersistenceTest.java:310-377`。
- `PaxosRowsTest` 和 `PaxosRepairHistoryTest` 覆盖 Paxos state/history 的 system table 写读，见 `test/unit/org/apache/cassandra/service/paxos/uncommitted/PaxosRowsTest.java:115-130`、`test/unit/org/apache/cassandra/service/paxos/PaxosRepairHistoryTest.java:154-155`。
- `LocalSessionTest` 覆盖 `system.repairs` backed local repair session 行为，见 `test/unit/org/apache/cassandra/repair/consistent/LocalSessionTest.java:259`。
- `TraceCqlTest`、`TracingTest` 和 in-JVM tracing helper 覆盖 trace session/event 写读与 driver trace path，见 `test/unit/org/apache/cassandra/cql3/TraceCqlTest.java:61-173`、`test/unit/org/apache/cassandra/tracing/TracingTest.java:42-162`、`test/distributed/org/apache/cassandra/distributed/impl/TracingUtil.java:69-97`。
