# Module: Observability Internals

## 范围

本模块覆盖 system_views/system_virtual_schema、audit log、full query log、diagnostic events 和 JMX auth/permission 的内部实现。

## 设计目标

本模块补齐运维观测第二轮：把 `system_views` / `system_virtual_schema` virtual tables、audit log、full query log、diagnostic events、JMX auth/permission 和 nodetool 安全连接参数放到同一张内部设计图里。它们共同解决的问题是：在不改变主读写路径语义的前提下，把运行时状态、管理操作、审计证据和故障诊断信息暴露给 CQL、JMX、日志文件和工具链。

关键边界：

- virtual tables 是 runtime view，不落盘、不参与 compaction/repair；daemon 启动时注册 `system_virtual_schema` 和 `system_views`，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:534-543`。
- audit log 订阅 CQL 与 auth 事件，把请求、登录、授权失败等写入配置的 logger，见 `src/java/org/apache/cassandra/audit/AuditLogManager.java:55-96`、`src/java/org/apache/cassandra/audit/AuditLogManager.java:242-396`。
- full query log 只记录 query/batch 载荷，作为 `QueryEvents.Listener` 写 Chronicle-backed binlog，见 `src/java/org/apache/cassandra/fql/FullQueryLogger.java:55-104`、`src/java/org/apache/cassandra/fql/FullQueryLogger.java:252-327`。
- diagnostic events 是进程内发布订阅和 JMX read API，默认由 `diagnostic_events_enabled` 关闭；生产事件 class/type/payload/publisher 全量清单见 `research/module-diagnostic-events-catalog.md`，服务入口见 `src/java/org/apache/cassandra/diag/DiagnosticEventService.java:43-102`、`conf/cassandra.yaml:1933-1936`。
- JMX auth 独立处理 `ObjectName` exact/pattern/root resource 的 permission 匹配，并维护自己的 cache，见 `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:55-73`、`src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:109-123`。

## 解决的问题

- 运行时状态需要用 CQL 查询：`SystemViewsKeyspace` 默认注册 caches、clients、settings、SSTable tasks、thread pools、internode、hints、metrics、streaming、gossip、queries、logs、snapshots、repair、SAI 等 virtual tables，见 `src/java/org/apache/cassandra/db/virtual/SystemViewsKeyspace.java:33-60`。
- virtual table 元数据需要自省：`VirtualSchemaKeyspace` 暴露 virtual keyspaces/tables/columns，数据来自已注册的 `VirtualKeyspace` metadata，见 `src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java:33-151`。
- 审计要覆盖成功与失败路径：`AuditLogManager` 处理 query/execute/batch/prepare 成功失败和 auth 成功失败，构造不同 `AuditLogEntryType`，见 `src/java/org/apache/cassandra/audit/AuditLogManager.java:242-396`。
- FQL 要保留可重放的 query/batch 细节：`FullQueryLogger.Query` 写 `QUERY` 记录，`Batch` 写 batch type、queries、values 和 weight，见 `src/java/org/apache/cassandra/fql/FullQueryLogger.java:329-467`。
- 诊断事件要避免长期持久化负担：`DiagnosticEventPersistence` 只有在 MBean enable event persistence 后订阅事件；内置 store 是固定大小的 on-heap memory store，见 `src/java/org/apache/cassandra/diag/DiagnosticEventPersistence.java:96-150`、`src/java/org/apache/cassandra/diag/store/DiagnosticEventMemoryStore.java:32-97`。
- JMX 权限不能简单套用普通 `IResource` 层级：`AuthorizationProxy` 对 pattern target 要查询所有匹配 MBean，并确认 grant 覆盖目标集合，见 `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:333-397`。

## 设计取舍

- virtual tables 牺牲普通表的完整 DDL/DML 能力，换取低侵入 runtime 暴露；registry 只保存 `VirtualKeyspace` 与 `TableId -> VirtualTable` 映射，见 `src/java/org/apache/cassandra/db/virtual/VirtualKeyspaceRegistry.java:30-80`。
- `settings` virtual table 直接反映当前配置对象，但对 `@Redacted` 字段和 password-like key 做隐藏，并把数组/集合/map 转成 JSON-like 字符串，见 `src/java/org/apache/cassandra/db/virtual/SettingsTable.java:45-120`。
- audit filter 使用 include/exclude sets，exclude 优先于 include；这使安全侧可以用排除规则兜底，见 `src/java/org/apache/cassandra/audit/AuditLogFilter.java:27-160`。
- audit log 和 FQL 都默认使用 `BinLog` 队列/roll/archive 机制；`BinLog` 维护 `currentPaths` 防止多个 binlog 使用同一路径，见 `src/java/org/apache/cassandra/utils/binlog/BinLog.java:70-180`、`src/java/org/apache/cassandra/utils/binlog/BinLog.java:431-481`。
- nodetool 为 audit/FQL 设置 archive command 需要显式打开 `allow_nodetool_archive_command`，否则服务端拒绝，见 `src/java/org/apache/cassandra/service/StorageService.java:7002-7005`、`src/java/org/apache/cassandra/service/StorageService.java:7139-7145`。
- diagnostic events 发布前同时检查全局开关和订阅者；没有订阅者时不走事件构造/持久化开销，见 `src/java/org/apache/cassandra/diag/DiagnosticEventService.java:221-265`。
- JMX auth 的 non-MBeanServer 描述型方法只需要 root `DESCRIBE`，具体 MBean 读/写/执行再映射到 `SELECT/MODIFY/EXECUTE` 等权限，见 `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:83-109`、`src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:240-330`。

## 核心类

| 类 | 作用 |
|---|---|
| `SystemViewsKeyspace` | 组装 `system_views` virtual tables 清单。见 `src/java/org/apache/cassandra/db/virtual/SystemViewsKeyspace.java:26-60` |
| `VirtualSchemaKeyspace` | 组装 `system_virtual_schema` 的 keyspaces/tables/columns 元数据表。见 `src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java:33-151` |
| `VirtualKeyspaceRegistry` | 注册/查找 virtual keyspace、metadata 和 `VirtualTable` provider。见 `src/java/org/apache/cassandra/db/virtual/VirtualKeyspaceRegistry.java:30-80` |
| `SettingsTable` | 暴露当前配置项并处理 redaction/password-like keys。见 `src/java/org/apache/cassandra/db/virtual/SettingsTable.java:45-120` |
| `QueriesTable` | 展示当前运行中的 coordinator/local query task。见 `src/java/org/apache/cassandra/db/virtual/QueriesTable.java:32-95` |
| `AuditLogManager` | audit log lifecycle、QueryEvents/AuthEvents listener 和 MBean。见 `src/java/org/apache/cassandra/audit/AuditLogManager.java:55-96` |
| `AuditLogFilter` | keyspace/category/user include/exclude 过滤器。见 `src/java/org/apache/cassandra/audit/AuditLogFilter.java:27-160` |
| `AuditLogEntry` | 审计事件字段和 log string 格式。见 `src/java/org/apache/cassandra/audit/AuditLogEntry.java:37-106` |
| `BinAuditLogger` / `FileAuditLogger` | audit log 的 Chronicle binlog 与 logback/file logger 实现。见 `src/java/org/apache/cassandra/audit/BinAuditLogger.java:34-95`、`src/java/org/apache/cassandra/audit/FileAuditLogger.java:26-59` |
| `FullQueryLogger` | FQL listener、binlog lifecycle、query/batch record encoder。见 `src/java/org/apache/cassandra/fql/FullQueryLogger.java:55-183` |
| `QueryEvents` | CQL query/execute/batch/prepare 成功失败事件分发器。见 `src/java/org/apache/cassandra/cql3/QueryEvents.java:43-230` |
| `DiagnosticEventService` | diagnostic event pub/sub、MBean 和 persistence 控制入口。见 `src/java/org/apache/cassandra/diag/DiagnosticEventService.java:43-155` |
| `DiagnosticEventPersistence` | diagnostic event persistence subscriber 与 JMX read backend。见 `src/java/org/apache/cassandra/diag/DiagnosticEventPersistence.java:38-150` |
| `JMXResource` | JMX root/mbean resource、权限集合和 ObjectName existence check。见 `src/java/org/apache/cassandra/auth/JMXResource.java:30-155` |
| `AuthorizationProxy` | JMX invocation authorization、pattern matching、cache loading。见 `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:55-123` |
| `JmxPermissionsCacheKeysTable` | 可读/可删的 JMX permission cache key virtual table。见 `src/java/org/apache/cassandra/db/virtual/JmxPermissionsCacheKeysTable.java:26-63` |

## 核心接口

- `VirtualKeyspaceRegistry.register()` / `getTableNullable()`：daemon 和 tests 注册 virtual keyspace 后，CQL read path 按 keyspace/table id 定位 provider，见 `src/java/org/apache/cassandra/db/virtual/VirtualKeyspaceRegistry.java:41-80`。
- `QueryEvents.Listener`：audit log 和 FQL 共用的 CQL 事件扩展点，分发 query/execute/batch/prepare success/failure，见 `src/java/org/apache/cassandra/cql3/QueryEvents.java:43-230`。
- `AuditLogManagerMBean`：通过 MBean 暴露 audit log options 和 enabled 状态；`NodeProbe.getAuditLogOptions()` 读取该 MBean，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:2418-2420`。
- `StorageServiceMBean.enableAuditLog()` / `disableAuditLog()`：nodetool audit 开关最终入口，服务端构造 `AuditLogOptions` 并启停 manager，见 `src/java/org/apache/cassandra/service/StorageService.java:6966-7029`。
- `StorageServiceMBean.enableFullQueryLogger()` / `resetFullQueryLogger()` / `stopFullQueryLogger()`：FQL JMX lifecycle，见 `src/java/org/apache/cassandra/service/StorageService.java:7131-7169`。
- `DiagnosticEventServiceMBean`：诊断事件 enable/disable/read/persistence 操作合同，见 `src/java/org/apache/cassandra/diag/DiagnosticEventServiceMBean.java:25-58`。
- `AuthorizationProxy.JmxPermissionsCacheMBean`：JMX permission cache 的 MBean 接口，cache 类注册新旧 MBean 名称，见 `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:551-590`。
- nodetool global JMX options：`--host/--port/--username/--password/--password-file` 由 `NodeToolCmd` 处理，见 `src/java/org/apache/cassandra/tools/NodeTool.java:348-455`。

## 核心数据结构

- `VirtualKeyspace`：virtual keyspace name + table map + metadata 容器，和 `VirtualKeyspaceRegistry` 一起形成 runtime schema。见 `src/java/org/apache/cassandra/db/virtual/VirtualKeyspaceRegistry.java:30-80`。
- `SystemViewsKeyspace` table list：包含 caches、clients、settings、system_properties、sstable tasks、thread pools、internode、hints、metrics、auth cache keys、streaming、gossip、queries、logs、snapshots、repair、SAI 等运行时视图，见 `src/java/org/apache/cassandra/db/virtual/SystemViewsKeyspace.java:33-60`。
- `AuditLogEntry`：字段包括 user、host、source、timestamp、type、category、batch、keyspace、scope、operation，格式化入口是 `getLogString()`，见 `src/java/org/apache/cassandra/audit/AuditLogEntry.java:37-106`。
- `AuditLogFilter` sets：keyspaces/categories/users 的 include/exclude set；`isFiltered` 静态方法实现基础规则，见 `src/java/org/apache/cassandra/audit/AuditLogFilter.java:27-160`。
- `BinLog`：ChronicleQueue、WeightedQueue、archiver、blocking mode 和 current path registry，见 `src/java/org/apache/cassandra/utils/binlog/BinLog.java:70-180`。
- `FullQueryLogger.AbstractLogEntry`：写 query options、protocol version、timestamp、now-in-seconds、keyspace 等共享字段，见 `src/java/org/apache/cassandra/fql/FullQueryLogger.java:468-560`。
- `DiagnosticEvent`：所有事件携带 timestamp/threadName/type/map，map 值要求可序列化，见 `src/java/org/apache/cassandra/diag/DiagnosticEvent.java:25-52`。
- `DiagnosticEventMemoryStore`：以 event id 为 key 的固定大小内存 store，`scan(from, limit)` 返回事件窗口，见 `src/java/org/apache/cassandra/diag/store/DiagnosticEventMemoryStore.java:32-97`。
- `JMXResource`：root 名称是 `mbean`，具体 MBean resource 是 `mbean/<ObjectName>`，权限集合包括 `AUTHORIZE/DESCRIBE/EXECUTE/MODIFY/SELECT`，见 `src/java/org/apache/cassandra/auth/JMXResource.java:30-155`。
- `JmxPermissionsCache`：`AuthCache<RoleResource, Set<PermissionDetails>>`，loader 从 authorizer 取所有权限后过滤 `JMXResource`，见 `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:469-483`、`src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:551-575`。

## 生命周期

Virtual tables：

```text
CassandraDaemon.setupVirtualKeyspaces()
  -> VirtualKeyspaceRegistry.register(VirtualSchemaKeyspace.instance)
  -> VirtualKeyspaceRegistry.register(SystemViewsKeyspace.instance)
  -> VirtualTableAppender flushes buffered log messages into system_logs
```

Audit log：

```text
startup or nodetool enableauditlog
  -> StorageService.enableAuditLog(...)
  -> AuditLogOptions.Builder(...)
  -> AuditLogManager.enable(options)
     -> create configured IAuditLogger
     -> reload AuditLogFilter
     -> QueryEvents.registerListener(this)
     -> AuthEvents.registerListener(this)
```

Full query log：

```text
nodetool enablefullquerylog
  -> NodeProbe.enableFullQueryLogger(...)
  -> StorageService.enableFullQueryLogger(...)
  -> FullQueryLogger.enableWithoutClean(...)
     -> BinLog.Builder(...)
     -> QueryEvents.registerListener(this)
```

Diagnostic events：

```text
DiagnosticEventService.instance()
  -> register MBean
  -> DiagnosticEventPersistence.start()
MBean enableEventPersistence(class, type)
  -> DiagnosticEventPersistence.subscribe(...)
publisher checks DiagnosticEventService.isEnabled(...)
  -> publish(event)
  -> store event and broadcast last event id
```

JMX auth：

```text
remote JMX invocation
  -> AuthorizationProxy.invoke()
  -> resolve Subject -> RoleResource
  -> reject denied/vulnerable methods
  -> map method to required Permission
  -> load cached JMXResource grants
  -> exact or wildcard ObjectName coverage check
  -> allow or throw SecurityException
```

## 调用链

- virtual keyspace registration is daemon-local：`setupVirtualKeyspaces()` 注册后，`system_views.system_logs` 还会接收启动早期 buffered log messages，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:534-543`。
- `system_views.settings` 查询当前配置，不是读取 YAML 文件；字段处理在 `SettingsTable.data()` 内完成，见 `src/java/org/apache/cassandra/db/virtual/SettingsTable.java:63-120`。
- `system_views.queries` 从 `SharedExecutorPool` running tasks 找 `DebuggableTask` 并输出 query 信息，见 `src/java/org/apache/cassandra/db/virtual/QueriesTable.java:55-95`。
- `enableauditlog` nodetool 解析 logger、include/exclude 和 binlog 参数后调用 `NodeProbe.enableAuditLog()`，见 `src/java/org/apache/cassandra/tools/nodetool/EnableAuditLog.java:28-84`、`src/java/org/apache/cassandra/tools/NodeProbe.java:2363-2380`。
- `AuditLogManager.enable()` 注册 listener，`disableAuditLog()` 注销 listener 并切回 no-op logger，见 `src/java/org/apache/cassandra/audit/AuditLogManager.java:171-240`。
- `AuditLogManager.log()` 先走 filter，再交给 `auditLogger.log()`；失败路径会标记 request/auth 错误类型，见 `src/java/org/apache/cassandra/audit/AuditLogManager.java:116-140`、`src/java/org/apache/cassandra/audit/AuditLogManager.java:242-396`。
- `enablefullquerylog` 校验 `--blocking` 后调用 `NodeProbe.enableFullQueryLogger()`，见 `src/java/org/apache/cassandra/tools/nodetool/EnableFullQueryLog.java:26-64`。
- `getfullquerylog` 从 `StorageService` 和 `FullQueryLoggerOptions` 输出启用状态、路径、roll、block、size、queue 和 archive retry，见 `src/java/org/apache/cassandra/tools/nodetool/GetFullQueryLog.java:27-47`。
- `FullQueryLogger.reset()` 停止当前 binlog、清理 YAML/JMX 路径并注销 listener，见 `src/java/org/apache/cassandra/fql/FullQueryLogger.java:185-249`。
- diagnostic event 发布会按 class+type、class、all subscribers 三层分发，见 `src/java/org/apache/cassandra/diag/DiagnosticEventService.java:72-155`。
- 具体可订阅 FQCN/type、payload 字段、source-spelled enum 名称和当前未发布 enum 值见 `research/module-diagnostic-events-catalog.md`。
- `AuthorizationProxy` 的具体 MBean 方法先映射到 permission，再用 `getPermittedResources()` 从 cache 取 grants，见 `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:275-330`。
- `invalidatejmxpermissionscache` 可删除所有 role 的 JMX permission cache，也可按 role 删除，见 `src/java/org/apache/cassandra/tools/nodetool/InvalidateJmxPermissionsCache.java:28-47`、`src/java/org/apache/cassandra/tools/NodeProbe.java:608-615`。

## 配置项

| 配置项 / 参数 | 作用 | 证据 |
|---|---|---|
| `audit_logging_options.enabled` | 启用 audit log，默认 false。 | `conf/cassandra.yaml:1891-1913`、`src/java/org/apache/cassandra/audit/AuditLogOptions.java:37-57` |
| `audit_logging_options.logger` | 默认 `BinAuditLogger`，也可用其他 `IAuditLogger`。 | `conf/cassandra.yaml:1893-1897`、`src/java/org/apache/cassandra/audit/AuditLogOptions.java:39-47` |
| `audit_logging_options.included_*` / `excluded_*` | keyspace/category/user 过滤条件。 | `conf/cassandra.yaml:1897-1903`、`src/java/org/apache/cassandra/audit/AuditLogOptions.java:41-47` |
| `audit_logging_options.roll_cycle/block/max_queue_weight/max_log_size/archive_command/max_archive_retries` | audit binlog roll、背压、大小和归档策略。 | `conf/cassandra.yaml:1904-1913` |
| `full_query_logging_options.log_dir` | FQL binlog 输出目录，nodetool enable 时必须来自 YAML 或命令参数。 | `conf/cassandra.yaml:1915-1927`、`src/java/org/apache/cassandra/service/StorageService.java:7131-7145` |
| `full_query_logging_options.allow_nodetool_archive_command` | 是否允许 nodetool 传 archive command；关闭时防止 JMX 用户触发本地命令执行。 | `conf/cassandra.yaml:1923-1927`、`src/java/org/apache/cassandra/service/StorageService.java:7139-7141` |
| `diagnostic_events_enabled` | 全局诊断事件开关，默认 false。 | `conf/cassandra.yaml:1933-1936`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4401-4408` |
| nodetool `--host/--port/--username/--password/--password-file` | JMX 连接参数；有 username 时创建带认证的 `NodeProbe`。 | `src/java/org/apache/cassandra/tools/NodeTool.java:348-455` |
| auth cache validity/update/max entries | JMX permission cache 复用普通 permissions cache 配置入口。 | `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:551-567` |

## Metrics

- `system_views` 已经把部分 metrics 变成 CQL 表：`SystemViewsKeyspace` 注册 `TableMetricTables`、`CQLMetricsTable`、`BatchMetricsTable`、`StreamingVirtualTable` 和 CIDR filtering metrics，见 `src/java/org/apache/cassandra/db/virtual/SystemViewsKeyspace.java:33-60`。
- `CQLMetricsTable` / `BatchMetricsTable` 暴露的是运行时 metrics snapshot；它们与 Dropwizard/JMX metrics 是互补入口，不替代 `CassandraMetricsRegistry`，注册关系见 `research/module-operations-observability.md`。
- `StreamingVirtualTable` 展示 active stream session 的 operation、peers、status、progress、duration、failure/success message 等，见 `src/java/org/apache/cassandra/db/virtual/StreamingVirtualTable.java:33-103`。
- audit log、FQL、diagnostic events 本身没有统一 Dropwizard metric 接口；更可靠的运行时入口是 MBean enabled/options、binlog 目录/大小和事件 store read API。
- JMX permission cache 可以通过 `system_views.jmx_permissions_cache_keys` 查看 cache key，并用 delete/truncate 做精确或全量失效，见 `src/java/org/apache/cassandra/db/virtual/JmxPermissionsCacheKeysTable.java:26-63`。

## 日志

- 普通 server logs 可进入 `system_views.system_logs`，但需要 logback 配置启用 `VirtualTableAppender`；daemon 注册 virtual keyspace 后会 flush 早期 buffer，见 `conf/logback.xml:112-118`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:534-543`。
- audit log 的文本格式由 `AuditLogEntry.getLogString()` 生成；`FileAuditLogger` 写 logback/file logger，`BinAuditLogger` 写 binary binlog，见 `src/java/org/apache/cassandra/audit/AuditLogEntry.java:37-106`、`src/java/org/apache/cassandra/audit/FileAuditLogger.java:26-59`、`src/java/org/apache/cassandra/audit/BinAuditLogger.java:34-95`。
- FQL 与 audit 都依赖 `BinLog` 的 queue/roll/archive；路径冲突会被 builder 检查，见 `src/java/org/apache/cassandra/utils/binlog/BinLog.java:431-481`。
- `QueryEvents` listener 异常通过 NoSpamLogger 记录，不把 listener 错误直接抛回 query 处理主线，见 `src/java/org/apache/cassandra/cql3/QueryEvents.java:43-230`。
- `AuthorizationProxy` 在 JMX 权限包含非法 ObjectName 时 warn，并对高风险 JDK MBean operations 直接拒绝，见 `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:344-397`、`src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:486-549`。

## 运维关注点

- `system_views.settings` 会反映运行时配置对象，不保证与磁盘 YAML 完全一致；对审计配置的覆盖测试见 `test/unit/org/apache/cassandra/db/virtual/SettingsTableTest.java:281-315`。
- `system_views.queries` 是正在运行 task 的快照，适合临时排查慢查询，不适合作为高频全表采集源。
- `enableauditlog` / `enablefullquerylog` 都可在运行时打开，但开启后每个请求进入 listener 与 binlog 队列，生产环境应先设置 roll、queue、block 和 log size。
- FQL `--path` 说明会递归删除目录内容；nodetool 参数定义见 `src/java/org/apache/cassandra/tools/nodetool/EnableFullQueryLog.java:41-47`。
- archive command 通过 nodetool 传入默认被禁止，因为这等价于允许 JMX 用户让 Cassandra 进程执行本地 shell command，模板注释见 `conf/cassandra.yaml:1923-1927`。
- diagnostic events 默认关闭；需要全局开关、订阅者和可选 persistence 同时满足，才会有可读事件。
- secure deployment 下，nodetool 连接失败不一定是 Cassandra 服务问题，也可能是 JMX username/password/password-file、SSL 或 JMX auth 权限不足；连接选择见 `src/java/org/apache/cassandra/tools/NodeTool.java:444-455`。
- JMX grants 可给 root、exact ObjectName 或 wildcard ObjectName；wildcard grant 必须覆盖 target pattern 匹配到的全部 MBean，见 `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:333-397`。

## 性能瓶颈

- virtual tables 的成本由 provider 决定；`queries` 要扫描 executor running tasks，`settings` 要遍历配置 properties，`system_logs` 读内存 buffer。
- audit/FQL 共用 binlog queue 模型，`block=false` 时高压下可能丢样本，`block=true` 时可能把 query/auth 路径阻塞在日志队列上；相关配置见 `conf/cassandra.yaml:1904-1927`。
- audit filter 虽轻量，但每个被审计事件都会构造 `AuditLogEntry` 并走 filter/logger，见 `src/java/org/apache/cassandra/audit/AuditLogManager.java:116-140`。
- FQL batch record 会计算 values/queries weight 并编码 query options；大 batch 或大量 bound values 会放大日志 payload，见 `src/java/org/apache/cassandra/fql/FullQueryLogger.java:373-560`。
- diagnostic persistence store 是 on-heap 固定大小窗口，适合故障现场，不适合替代长期事件存储，见 `src/java/org/apache/cassandra/diag/store/DiagnosticEventMemoryStore.java:32-97`。
- JMX wildcard authorization 需要查询匹配 MBean 并做集合覆盖判断；MBean 很多时，宽泛 pattern 权限检查比 exact ObjectName 更重。

## 常见故障

- audit logger class 错误：`StorageService.enableAuditLog("foobar", ...)` 会抛配置/状态异常，测试覆盖见 `test/unit/org/apache/cassandra/service/StorageServiceServerTest.java:629-663`。
- audit log 没有记录某些 keyspace/category/user：先检查 include/exclude；exclude 会覆盖 include，基础规则测试见 `test/unit/org/apache/cassandra/audit/AuditLogFilterTest.java:31-205`。
- FQL 无法开启：path 为空、roll cycle 非法、queue/log size 非法、路径不可读/写/执行都会失败，测试覆盖见 `test/unit/org/apache/cassandra/fql/FullQueryLoggerTest.java:100-179`。
- FQL reset 后文件被清理：`reset()` 会清理 last used 和配置路径，测试覆盖见 `test/unit/org/apache/cassandra/fql/FullQueryLoggerTest.java:180-220`。
- diagnostic events 没有输出：`diagnostic_events_enabled=false` 时 publish 不分发；测试覆盖见 `test/unit/org/apache/cassandra/diag/DiagnosticEventServiceTest.java:176-212`。
- JMX 权限看似授予但仍拒绝：wildcard grant 与 target wildcard 交集不足、root permission 类型不匹配、auth setup 未完成都会拒绝，测试覆盖见 `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:95-125`、`test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:260-335`、`test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:384-435`。
- JMX permission cache 修改后不生效：需要 `invalidatejmxpermissionscache` 或删除/truncate `system_views.jmx_permissions_cache_keys`，相关实现见 `src/java/org/apache/cassandra/tools/nodetool/InvalidateJmxPermissionsCache.java:28-47`、`src/java/org/apache/cassandra/db/virtual/JmxPermissionsCacheKeysTable.java:26-63`。

## 测试用例

- virtual tables：`VirtualTableTest` 覆盖 virtual table 读写和 DDL/DML 限制，`CQLMetricsTableTest`、`GossipInfoTableTest`、`LogMessagesTableTest` 覆盖典型 system_views 表，索引见 `research/notes/source-map.md`。
- settings/audit config view：`SettingsTableTest.testAuditOverride()` 验证 audit options 在 `system_views.settings` 中的展示，见 `test/unit/org/apache/cassandra/db/virtual/SettingsTableTest.java:281-315`。
- audit filter：`AuditLogFilterTest` 覆盖 include/exclude/null/mutual rules，见 `test/unit/org/apache/cassandra/audit/AuditLogFilterTest.java:31-205`。
- audit runtime：`AuditLoggerTest` 覆盖 audit log 开关、过滤、listener transition 和 query 记录，见 `test/unit/org/apache/cassandra/audit/AuditLoggerTest.java:61-180`；`BinAuditLoggerTest` 验证 prepare/select 写入 binary audit queue，见 `test/unit/org/apache/cassandra/audit/BinAuditLoggerTest.java:47-95`。
- audit nodetool：`GetAuditLogTest` 覆盖 `getauditlog` 默认、启用、复杂参数和 disable reset 输出，见 `test/unit/org/apache/cassandra/tools/nodetool/GetAuditLogTest.java:30-153`。
- FQL runtime：`FullQueryLoggerTest` 覆盖配置校验、double configure、stop/reset、query/batch record 和 StorageService archive gate，见 `test/unit/org/apache/cassandra/fql/FullQueryLoggerTest.java:100-240`、`test/unit/org/apache/cassandra/fql/FullQueryLoggerTest.java:681-745`。
- FQL nodetool：`GetFullQueryLogTest` 覆盖 enable/get/reset/default 输出，见 `test/unit/org/apache/cassandra/tools/nodetool/GetFullQueryLogTest.java:33-141`。
- diagnostic events：`DiagnosticEventServiceTest` 覆盖 subscribe by class/type/all、publish、global enabled flag，见 `test/unit/org/apache/cassandra/diag/DiagnosticEventServiceTest.java:54-212`；`DiagnosticEventMemoryStoreTest` 覆盖 scan/limit/max size，见 `test/unit/org/apache/cassandra/diag/store/DiagnosticEventMemoryStoreTest.java:32-170`。
- JMX auth：`JMXAuthTest` 覆盖 SELECT/MODIFY/EXECUTE 对 exact/pattern/root MBean grants 的行为，见 `test/unit/org/apache/cassandra/auth/jmx/JMXAuthTest.java:117-194`；`AuthorizationProxyTest` 覆盖 root permission、wildcard target、non-MBean methods 和 auth setup 未完成，见 `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:95-125`、`test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:260-335`、`test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:374-435`。
- JMX permission cache：`JmxPermissionsCacheKeysTableTest` 覆盖 cache keys virtual table 查询，见 `test/unit/org/apache/cassandra/db/virtual/JmxPermissionsCacheKeysTableTest.java:48-120`；`InvalidateJmxPermissionsCacheTest` 覆盖 nodetool help、单 role 和全量失效，见 `test/unit/org/apache/cassandra/tools/nodetool/InvalidateJmxPermissionsCacheTest.java:45-150`。

## 待补深水区

- exporter/Grafana 与 Cassandra 内置 JMX/virtual tables 的字段级对照。
- JMX MBean 完整清单与 nodetool 子命令全量映射。
