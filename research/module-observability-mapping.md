# Module: Observability Mapping

## 范围

本模块覆盖 system_views 每表读成本、JMX metric wrapper/exporter 字段、NodeProbe MBean 清单和 nodetool 分组映射。

## 设计目标

本模块补齐运维观测第三轮的源码侧映射：把 `system_views` 每类 virtual table、Dropwizard/JMX metrics 暴露形态、`JMXTool` 可枚举 MBean 包、`NodeProbe` 代理清单和 nodetool 命令分组放到同一张表里。目标不是描述某个外部 exporter 的配置，而是明确 Cassandra 进程实际暴露的字段和管理入口，后续才能把它们稳定映射到 Prometheus/Grafana、巡检脚本或 runbook。

关键边界：

- `system_views` 由 `SystemViewsKeyspace` 构造，包含 caches、clients、settings、system properties、SSTable tasks、thread pools、internode、pending hints、table metrics、auth cache keys、CQL/batch metrics、streaming、gossip、queries、logs、snapshots、repair、CIDR 和 SAI 视图，见 `src/java/org/apache/cassandra/db/virtual/SystemViewsKeyspace.java:31-56`。
- virtual table 的全表扫描调用 `data()`，单分区读取只有在 provider 覆盖 `data(DecoratedKey)` 时才更便宜；默认实现会退回全量 `data()`，见 `src/java/org/apache/cassandra/db/virtual/AbstractVirtualTable.java:63-94`。
- Cassandra metrics 先注册 Dropwizard metric，再按 metric 类型包装成 JMX MBean；wrapper 类型决定 exporter 能读到 `Count`、rate、percentile、`Value` 等属性，见 `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:229-264`。
- `NodeProbe.connect()` 是 nodetool 实际依赖的服务 MBean 清单，包含 StorageService、MessagingService、StreamManager、CompactionManager、FailureDetector、CacheService、StorageProxy、HintsService、BatchlogManager、RepairService、AuditLog、Auth/CIDR/Guardrails/AutoRepair 等代理，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:262-321`。
- `tools/bin/jmxtool` 通过 `JMXTool` 枚举 `org.apache.cassandra.metrics`、`org.apache.cassandra.db`、`org.apache.cassandra.hints`、`org.apache.cassandra.internal`、`org.apache.cassandra.net`、`org.apache.cassandra.request`、`org.apache.cassandra.service` 包下的 MBean，见 `src/java/org/apache/cassandra/tools/JMXTool.java:84-92`、`src/java/org/apache/cassandra/tools/JMXTool.java:425-445`。

## 解决的问题

- 运维人员需要知道 `system_views` 哪些表能安全频繁查询，哪些表会枚举全部表、全部连接、全部 SSTable index 或快照目录。
- exporter/Grafana 字段要落到稳定 JMX attribute，而不是只看 Java 字段名；`Counter` 只有 `Count`，`Meter` 有 `Count/MeanRate/OneMinuteRate/FiveMinuteRate/FifteenMinuteRate/RateUnit`，`Timer` 再加 percentile 和 duration unit，见 `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:471-615`。
- nodetool 命令太多，不能只写“走 JMX”；`NodeTool` 注册命令范围从 `AutoRepairStatus` 到 `ForceCompact`，代表性命令需要按目标 MBean/子系统分组，见 `src/java/org/apache/cassandra/tools/NodeTool.java:98-245`。
- virtual table 与 JMX/metrics 不是一一对应：`TableMetricTables` 明确说明它是 metrics 的视图而非直接 JMX wrapper，见 `src/java/org/apache/cassandra/db/virtual/TableMetricTables.java:46-50`。
- CQL 查询 virtual table 仍走权限系统；虚拟表只是不落盘，不表示可绕过 `system_views` 的 SELECT 授权，权限测试见 `test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java:485-487`。

## 设计取舍

- virtual table 牺牲普通表的存储/索引/repair 语义，换取实时进程内状态读取；不可变表的默认 `apply()` / `truncate()` 直接拒绝修改，见 `src/java/org/apache/cassandra/db/virtual/AbstractVirtualTable.java:125-135`。
- 少数 virtual table 是可变控制面：`AbstractMutableVirtualTable` 将 DELETE/TRUNCATE 映射成 provider 的 cache invalidation 或 buffer 清理，见 `src/java/org/apache/cassandra/db/virtual/AbstractMutableVirtualTable.java:46-95`。
- 表级 metrics virtual table 为人读做单位转换和简化：latency 从 ns 转 ms、storage byte 转 MiB、histogram 只暴露 p50/p99/max/rate，而不是完整 JMX histogram attribute set，见 `src/java/org/apache/cassandra/db/virtual/TableMetricTables.java:103-156`、`src/java/org/apache/cassandra/db/virtual/TableMetricTables.java:188-224`。
- JMX ObjectName 采用 `org.apache.cassandra.metrics:type=<type>,scope=<scope>,name=<name>` 形式；`DefaultNameFactory` 构造默认 metric MBean 名称，见 `src/java/org/apache/cassandra/metrics/DefaultNameFactory.java:42-65`。
- nodetool 的 in-JVM dtest 不走远程 JMX，而是用 `InternalNodeProbe` 绑定本地单例服务；这让命令行为可测，但不是生产连接模型，见 `test/distributed/org/apache/cassandra/distributed/mock/nodetool/InternalNodeProbe.java:50-85`、`test/distributed/org/apache/cassandra/distributed/impl/Instance.java:1071-1082`。

## 核心类

| 类 | 作用 |
|---|---|
| `SystemViewsKeyspace` | `system_views` virtual table 注册清单。见 `src/java/org/apache/cassandra/db/virtual/SystemViewsKeyspace.java:31-56` |
| `AbstractVirtualTable` | 定义全表/单分区 select 与默认拒绝 mutation/truncate。见 `src/java/org/apache/cassandra/db/virtual/AbstractVirtualTable.java:63-135` |
| `AbstractMutableVirtualTable` | 将 CQL delete/truncate 转给 provider，实现 cache key 失效和日志表清理。见 `src/java/org/apache/cassandra/db/virtual/AbstractMutableVirtualTable.java:46-95` |
| `TableMetricTables` | 生成表级 latency/histogram/storage virtual tables。见 `src/java/org/apache/cassandra/db/virtual/TableMetricTables.java:68-82` |
| `LocalRepairTables` | 生成 repair/repair_sessions/repair_jobs/repair_participates/repair_validations。见 `src/java/org/apache/cassandra/db/virtual/LocalRepairTables.java:58-66` |
| `StorageAttachedIndexTables` | 生成 SAI column/index/SSTable segment 视图。见 `src/java/org/apache/cassandra/index/sai/virtual/StorageAttachedIndexTables.java:31-35` |
| `CassandraMetricsRegistry` | Dropwizard metric 到 JMX MBean wrapper 的中心注册器。见 `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:229-264` |
| `DefaultNameFactory` | 默认 metric ObjectName 生成器。见 `src/java/org/apache/cassandra/metrics/DefaultNameFactory.java:42-65` |
| `JMXTool` | 枚举并 dump/diff Cassandra JMX metadata 的工具入口。见 `src/java/org/apache/cassandra/tools/JMXTool.java:84-92`、`src/java/org/apache/cassandra/tools/JMXTool.java:425-445` |
| `NodeTool` | nodetool 命令注册和全局连接参数。见 `src/java/org/apache/cassandra/tools/NodeTool.java:85-98`、`src/java/org/apache/cassandra/tools/NodeTool.java:348-455` |
| `NodeProbe` | nodetool JMX facade 与 MBean proxy 缓存。见 `src/java/org/apache/cassandra/tools/NodeProbe.java:136-178`、`src/java/org/apache/cassandra/tools/NodeProbe.java:262-321` |

## 核心接口

- `VirtualTable.data()` / `data(DecoratedKey)` / `apply()` / `truncate()`：virtual table 的查询和可选控制面合同；默认单分区读取回落全表，默认修改拒绝，见 `src/java/org/apache/cassandra/db/virtual/AbstractVirtualTable.java:63-135`。
- `CassandraMetricsRegistry.JmxGaugeMBean`：只暴露 `Value`，见 `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:319-338`。
- `JmxCounterMBean`：只暴露 `Count`，见 `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:471-490`。
- `JmxMeterMBean`：暴露 `Count`、mean/1m/5m/15m rate 和 rate unit，见 `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:493-555`。
- `JmxHistogramMBean` / `JmxTimerMBean`：暴露 count/min/max/mean/stddev/percentile/recent values；timer 还暴露 duration unit，见 `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:341-367`、`src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:589-615`。
- `NodeToolCmd.execute(NodeProbe)`：所有普通 nodetool 命令的统一入口，连接与关闭由 `runInternal()` 包办，见 `src/java/org/apache/cassandra/tools/NodeTool.java:380-455`。
- `MBeanServerConnection.queryNames()`：`JMXTool.load()` 与 `NodeProbe` 的部分动态查询都依赖它枚举 ObjectName，见 `src/java/org/apache/cassandra/tools/JMXTool.java:425-445`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1204-1213`。

## 核心数据结构

### system_views 表族

| 表族 | 字段语义 | 数据源与读成本 |
|---|---|---|
| `caches` | cache name、capacity/size/entry/request/hit/hit ratio、15m request/hit rate。 | 固定枚举 chunk/counter/key/row cache，成本低。见 `src/java/org/apache/cassandra/db/virtual/CachesTable.java:41-80` |
| `clients` | client address/port/user/protocol/options/driver/SSL/keyspace/request_count。 | 枚举 `ClientMetrics.instance.allConnectedClients()`，成本随连接数增长。见 `src/java/org/apache/cassandra/db/virtual/ClientsTable.java:47-93` |
| `settings` / `system_properties` | 当前配置对象、Cassandra 相关 env/system properties。 | `settings` 支持单 key 分区查询并 redacts password-like 字段；全表枚举配置 properties。见 `src/java/org/apache/cassandra/db/virtual/SettingsTable.java:64-124`、`src/java/org/apache/cassandra/db/virtual/SystemPropertiesTable.java:46-79` |
| `sstable_tasks` | task id、kind、progress/total/compressed total、completion ratio、target directory。 | 枚举 `CompactionManager.instance.getSSTableTasks()`，成本随 active SSTable tasks 增长。见 `src/java/org/apache/cassandra/db/virtual/SSTableTasksTable.java:46-90` |
| `thread_pools` | active/pending/completed/blocked/current limit。 | 支持按 pool partition 读取，也可枚举全部 thread pool metrics。见 `src/java/org/apache/cassandra/db/virtual/ThreadPoolsTable.java:42-84` |
| `internode_outbound` / `internode_inbound` | 每 peer 的 bytes/count/error/expired/connection/throttle 统计。 | 支持按 address+port 分区读取；全表枚举 channelManagers 或 messageHandlers。见 `src/java/org/apache/cassandra/db/virtual/InternodeOutboundTable.java:63-110`、`src/java/org/apache/cassandra/db/virtual/InternodeInboundTable.java:62-110` |
| `pending_hints` | host id、endpoint/rack/dc/status、files、newest/oldest。 | 从 HintsService、StorageService host id map、snitch 和 failure detector 组合快照，成本随 pending host 数增长。见 `src/java/org/apache/cassandra/db/virtual/PendingHintsTable.java:57-113` |
| 表级 metric tables | `local_read_latency`、`coordinator_write_latency`、`disk_usage`、`max_partition_size` 等按 keyspace/table 行输出。 | 枚举 `ColumnFamilyStore.all()` 并读取每表 metrics；大 schema 集群全表扫描成本高。见 `src/java/org/apache/cassandra/db/virtual/TableMetricTables.java:68-82`、`src/java/org/apache/cassandra/db/virtual/TableMetricTables.java:188-224` |
| `cql_metrics` / `batch_metrics` / `cidr_filtering_metrics_*` | prepared/regular statement 计数与比率、batch partition histogram、CIDR counts/latencies。 | 固定 metric set，成本低；CIDR 表另注册 MBean 供 nodetool 读取。见 `src/java/org/apache/cassandra/db/virtual/CQLMetricsTable.java:53-74`、`src/java/org/apache/cassandra/db/virtual/BatchMetricsTable.java:43-74`、`src/java/org/apache/cassandra/db/virtual/CIDRFilteringMetricsTable.java:55-190` |
| `streaming` | stream id、operation、peers、status、progress、duration、failure/success、session 细节。 | 支持按 stream id 分区读取；全表枚举 active streaming states。见 `src/java/org/apache/cassandra/db/virtual/StreamingVirtualTable.java:67-103` |
| `gossip_info` | endpoint heartbeat generation/version、ApplicationState value/version。 | 全表复制当前 endpoint state 快照，成本随 gossip endpoint 数和 application states 增长。见 `src/java/org/apache/cassandra/db/virtual/GossipInfoTable.java:87-109` |
| `queries` | executor thread id、queued/running micros、task description。 | 枚举 `SharedExecutorPool.SHARED.runningTasks()`，适合现场排查，不适合高频采集。见 `src/java/org/apache/cassandra/db/virtual/QueriesTable.java:68-94` |
| `system_logs` | timestamp、order_in_millisecond、logger、level、message。 | 有界内存 buffer，默认 50k 行，可 truncate；需要 logback VirtualTableAppender。见 `src/java/org/apache/cassandra/db/virtual/LogMessagesTable.java:40-99` |
| `snapshots` | snapshot tag、keyspace/table、true size、size on disk、created/expires、ephemeral。 | 枚举 snapshot manager 并计算 size，可能触达目录元数据。见 `src/java/org/apache/cassandra/db/virtual/SnapshotsTable.java:45-80` |
| auth/cache key tables | credentials、permissions、roles、network permissions、JMX permissions cache keys。 | 可 DELETE/TRUNCATE 失效 cache；读出当前 cache key 集。见 `src/java/org/apache/cassandra/db/virtual/CredentialsCacheKeysTable.java:36-77`、`src/java/org/apache/cassandra/db/virtual/PermissionsCacheKeysTable.java:33-71`、`src/java/org/apache/cassandra/db/virtual/JmxPermissionsCacheKeysTable.java:30-62` |
| cache runtime | `system_views.caches`、`CacheServiceMBean`、nodetool cache commands。 | `setcachecapacity` / `setcachekeystosave` / `invalidatekeycache` / `invalidaterowcache` / `invalidatecountercache` mutate node-local key/row/counter cache through `CacheServiceMBean`; `system_views.caches` and `nodetool info` expose the same capacity/request/hit state. 见 `src/java/org/apache/cassandra/db/virtual/CachesTable.java:41-80`、`src/java/org/apache/cassandra/service/CacheServiceMBean.java:22-67`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1088-1101` |
| repair tables | repair summary/session/job/participate/validation 状态。 | 从 `ActiveRepairService` 当前 in-memory repair state 组装，部分表支持按 id 读取。见 `src/java/org/apache/cassandra/db/virtual/LocalRepairTables.java:58-66`、`src/java/org/apache/cassandra/db/virtual/LocalRepairTables.java:116-130`、`src/java/org/apache/cassandra/db/virtual/LocalRepairTables.java:213-259`、`src/java/org/apache/cassandra/db/virtual/LocalRepairTables.java:292-369` |
| SAI tables | `sai_column_indexes`、`sai_sstable_indexes`、`sai_sstable_index_segments`。 | 枚举用户 keyspace/table、SAI index group、SSTable index view 和 segments，成本随 SAI 索引与 SSTable 数增长。见 `src/java/org/apache/cassandra/index/sai/virtual/StorageAttachedIndexTables.java:31-35`、`src/java/org/apache/cassandra/index/sai/virtual/ColumnIndexesSystemView.java:76-110`、`src/java/org/apache/cassandra/index/sai/virtual/SSTableIndexesSystemView.java:81-133`、`src/java/org/apache/cassandra/index/sai/virtual/SegmentsSystemView.java:85-116` |

### JMX / exporter 字段形态

| Dropwizard 类型 | JMX attributes | 采集含义 |
|---|---|---|
| Gauge | `Value` | 当前值快照；类型由 metric provider 决定。见 `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:319-338` |
| Counter | `Count` | 单调或可变计数取决于 provider 语义。见 `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:471-490` |
| Meter | `Count`、`MeanRate`、`OneMinuteRate`、`FiveMinuteRate`、`FifteenMinuteRate`、`RateUnit` | exporter 应把 count 与 rate 分开建模；rate unit 默认为 events/second。见 `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:493-555` |
| Histogram | `Count`、min/max/mean/stddev、p50/p75/p95/p98/p99/p999、values/recent values | 用于大小、墓碑、SSTable per read 等分布。见 `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:341-367` |
| Timer | Meter attributes + histogram percentile + `DurationUnit` | latency 类 metric，同时有请求计数、速率和耗时分布。见 `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:589-645` |

## 生命周期

Virtual table registration：

```text
CassandraDaemon.setupVirtualKeyspaces()
  -> VirtualKeyspaceRegistry.register(VirtualSchemaKeyspace.instance)
  -> VirtualKeyspaceRegistry.register(SystemViewsKeyspace.instance)
  -> CQL SELECT system_views.<table>
     -> VirtualTable.select(...)
     -> provider.data() or provider.data(partitionKey)
```

JMX metric registration：

```text
module creates metric name
  -> DefaultNameFactory.createMetricName(type, name, scope)
  -> CassandraMetricsRegistry.Metrics.counter/timer/register(...)
  -> CassandraMetricsRegistry.registerMBean(metric, objectName)
  -> JmxGauge/JmxCounter/JmxMeter/JmxHistogram/JmxTimer wrapper
  -> JMX scraper / JMXTool / nodetool reads attributes
```

nodetool execution：

```text
NodeTool.main()
  -> NodeTool.execute()
  -> command registry
  -> NodeToolCmd.runInternal()
  -> NodeProbe.connect()
  -> command.execute(probe)
  -> NodeProbe method
  -> service MBean or metric ObjectName
```

## 调用链

- virtual schema introspection：`system_virtual_schema` 枚举 `VirtualKeyspaceRegistry.instance.virtualKeyspacesMetadata()` 来输出 virtual keyspaces/tables/columns，见 `src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java:56-151`。
- CQL virtual table read：`AbstractVirtualTable.select(partitionKey, ...)` 调 `data(partitionKey)`，range/full read 调 `data()`，见 `src/java/org/apache/cassandra/db/virtual/AbstractVirtualTable.java:77-123`。
- CQL virtual table mutation：`VirtualMutation.apply()` 按 table id 找 provider 并调用 `VirtualTable.apply(update)`，见 `src/java/org/apache/cassandra/db/virtual/VirtualMutation.java:59-61`。
- JMX dump：`JMXTool.load()` 连接 JMX、按包名 queryNames、对每个注册 MBean 取 `MBeanInfo`，见 `src/java/org/apache/cassandra/tools/JMXTool.java:425-445`。
- nodetool command registry：`NodeTool.execute()` 把命令类加入 Airline builder，见 `src/java/org/apache/cassandra/tools/NodeTool.java:96-252`。
- nodetool metrics reads：`Info` 直接读取 cache/buffer/storage/table metrics，`ProxyHistograms` 读取 StorageProxy client request timer，`TableHistograms` 读取 CFS histogram/timer，`profileload`/`toppartitions` 通过 `SamplingManager` 和 table samplers 做短窗口 top-K profiling，见 `src/java/org/apache/cassandra/tools/nodetool/Info.java:89-165`、`src/java/org/apache/cassandra/tools/nodetool/ProxyHistograms.java:32-50`、`src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:50-166`、`src/java/org/apache/cassandra/tools/nodetool/ProfileLoad.java:46-175`、`src/java/org/apache/cassandra/metrics/SamplingManager.java:67-263`。
- nodetool vtable-backed stats：`CIDRFilteringStats` 通过 `NodeProbe.getCountsMetricsFromVtable()` / `getLatenciesMetricsFromVtable()` 读取 CIDR filtering virtual table MBean，见 `src/java/org/apache/cassandra/tools/nodetool/CIDRFilteringStats.java:38-87`、`src/java/org/apache/cassandra/db/virtual/CIDRFilteringMetricsTable.java:194-205`。

## 配置项

| 配置 / 属性 | 影响 | 证据 |
|---|---|---|
| `cassandra.disable_mbean_registration` | 禁用 MBean 注册时，JMX/nodetool/exporter 可见面会消失或缩小。 | `src/java/org/apache/cassandra/utils/MBeanWrapper.java:35-81` |
| `mbean_registration_class` | 替换默认 platform MBean wrapper，常用于测试或嵌入式环境。 | `src/java/org/apache/cassandra/utils/MBeanWrapper.java:35-81` |
| nodetool `--host/--port/--username/--password/--password-file` | 控制 JMX 连接目标和认证。 | `src/java/org/apache/cassandra/tools/NodeTool.java:348-455` |
| `cassandra.logs_virtual_table_min_rows` / `cassandra.logs_virtual_table_max_rows` / `cassandra.logs_virtual_table_default_rows` 相关 property | 控制 `system_views.system_logs` buffer 边界；非法值回落默认值由测试覆盖。 | `src/java/org/apache/cassandra/db/virtual/LogMessagesTable.java:57-91`、`test/unit/org/apache/cassandra/db/virtual/LogMessagesTableTest.java:125-151` |
| `conf/logback.xml` 中 `VirtualTableAppender` | 决定 server log 是否进入 `system_views.system_logs`。 | `conf/logback.xml:112-118` |
| `cassandra.jmx.local.port` / JMX SSL property | 影响 JMX server 和 nodetool/JMXTool 连接。 | `src/java/org/apache/cassandra/utils/JMXServerUtils.java:114-146`、`src/java/org/apache/cassandra/tools/NodeProbe.java:241-260` |

## Metrics

- JMX metrics 的稳定命名来自 `DefaultNameFactory` 和 `MetricName.getMBeanName()`：默认 group 是 `org.apache.cassandra.metrics`，type/scope/name 拼成 ObjectName，见 `src/java/org/apache/cassandra/metrics/DefaultNameFactory.java:42-65`、`src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:897-974`。
- Client request dashboards应优先看 `ClientRequest` read/write/CAS/view 和按 CL 的 metrics；这些 holder 在启动时为每个 `ConsistencyLevel` 建 read/write metrics map，见 `src/java/org/apache/cassandra/metrics/ClientRequestsMetricsHolder.java:25-53`。
- 表级容量、memtable、read/write/range latency、pending flush、bytes flushed、compaction pending 等来自 `TableMetrics`，见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:86-135`、`src/java/org/apache/cassandra/metrics/TableMetrics.java:628-648`。
- `system_views` 表级 metric tables 只暴露精选指标，适合人读和轻量 SQL 巡检；完整属性和 exporter 采集仍应读 JMX MBean。见 `src/java/org/apache/cassandra/db/virtual/TableMetricTables.java:68-82`、`src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:229-264`。
- `JMXTool` 的包清单提供了源码内置的 MBean discovery baseline，适合生成/对比 exporter allowlist，见 `src/java/org/apache/cassandra/tools/JMXTool.java:84-92`。
- `research/tools/check-jmx-nodeprobe-fd-drift.py` 把 `NodeProbe.connect()` 的 23 个 service MBean proxies、2 个 platform MXBean proxies、`JMXTool.METRIC_PACKAGES` 的 7 个 package、`FailureDetectorMBean` 的 14 个方法和 `GossiperMBean` 的 10 个方法固化为 source-to-doc drift check。

## 日志

- `system_views.system_logs` 是有界内存表，不是审计日志；它默认最多 50k 行，超出时移除最老记录，见 `src/java/org/apache/cassandra/db/virtual/LogMessagesTable.java:40-91`。
- `VirtualTableAppender` 需要 logback 配置启用；daemon 注册 virtual keyspaces 后 flush 早期 buffered log messages，见 `conf/logback.xml:112-118`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:534-543`。
- `JMXTool dump/diff` 的输出可作为 release/upgrade 中 JMX surface 回归证据；序列化/反序列化测试见 `test/unit/org/apache/cassandra/tools/JMXToolTest.java:40-51`、兼容性 dump/diff 测试见 `test/unit/org/apache/cassandra/tools/JMXCompatibilityTest.java:99-140`。

## 运维关注点

- 对 `system_views` 做全表扫描前先看 provider：`settings`、`thread_pools`、internode、streaming 支持单分区读取；`clients`、`gossip_info`、`queries`、SAI 表全扫会枚举运行时集合。
- `system_views` 与 JMX 都是节点本地视图；从某个节点查到的是该进程看到的连接、thread pool、gossip map、repair state 和 snapshots，不是全集群聚合。
- exporter 应避免把 Timer 的 percentile attribute 当 counter；Timer 同时有 count/rates 和 duration distribution，见 `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:589-645`。
- 大 schema 集群上，`TableMetricTables.data()` 枚举 `ColumnFamilyStore.all()`；高频采集时应按具体 JMX ObjectName 或更低频巡检处理，见 `src/java/org/apache/cassandra/db/virtual/TableMetricTables.java:188-224`。
- SAI system views 会走所有用户 keyspace/table 和 index view；它们适合定位索引元数据，不适合秒级 scrape，见 `src/java/org/apache/cassandra/index/sai/virtual/ColumnIndexesSystemView.java:76-110`、`src/java/org/apache/cassandra/index/sai/virtual/SSTableIndexesSystemView.java:81-133`、`src/java/org/apache/cassandra/index/sai/virtual/SegmentsSystemView.java:85-116`。
- nodetool 输出不等于 MBean 全量：`NodeProbe.connect()` 只创建常用服务 proxy，单个命令还会动态 query metrics ObjectName 或 CFS MBean，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:262-321`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1763-2210`。

## 性能瓶颈

- `queries` 每次扫描 shared executor running tasks，并计算 queued/running micros；排查慢请求有价值，高频采集会打到执行器元数据，见 `src/java/org/apache/cassandra/db/virtual/QueriesTable.java:68-94`。
- `snapshots` 读取 snapshot manager 并计算 true size / size on disk，可能触达文件系统元数据，见 `src/java/org/apache/cassandra/db/virtual/SnapshotsTable.java:60-80`。
- `tablehistograms` 从每个 CFS metric 读 estimated partition/column histograms 和 latency percentile，见 `src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:50-166`。
- `compactionstats --vtable` 可读 virtual table 输出，但 compaction metrics 仍来自 CompactionManager 和 JMX metrics，见 `src/java/org/apache/cassandra/tools/nodetool/CompactionStats.java:54-118`。
- CIDR filtering stats 通过 MBean 反查 virtual table rows；它比普通 JMX counter 多一层 CQL internal select，见 `src/java/org/apache/cassandra/db/virtual/CIDRFilteringMetricsTable.java:194-205`。

## 常见故障

- `system_views.system_logs` 为空：通常是 logback 未启用 `VirtualTableAppender`，或只查到当前节点本地 buffer；配置入口见 `conf/logback.xml:112-118`。
- virtual table 修改失败：不可变表默认抛 `Modification is not supported`，只有继承 `AbstractMutableVirtualTable` 的 cache key/log 表支持 DELETE/TRUNCATE 语义，见 `src/java/org/apache/cassandra/db/virtual/AbstractVirtualTable.java:125-135`、`src/java/org/apache/cassandra/db/virtual/AbstractMutableVirtualTable.java:59-95`。
- exporter 找不到 metric：先用 `JMXTool` 或 JMX query 确认 ObjectName 包是否在 `METRIC_PACKAGES` 范围内，再确认 metric provider 是否创建并注册 MBean，见 `src/java/org/apache/cassandra/tools/JMXTool.java:84-92`、`src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:229-264`。
- nodetool 命令能连上但输出缺项：命令可能走动态 CFS/Metrics ObjectName 查询；表名、keyspace、index 或 MBean 类型不匹配会导致查询为空或命令失败，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:1204-1225`、`src/java/org/apache/cassandra/tools/NodeProbe.java:2639-2645`。
- secure deployment 下 JMX query 被拒绝：`AuthorizationProxy` 会按 ObjectName 和方法映射到 SELECT/MODIFY/EXECUTE/DESCRIBE，已在观测第二轮文档覆盖；测试见 `test/unit/org/apache/cassandra/auth/jmx/JMXAuthTest.java:117-194`。

## 测试用例

- virtual table 基础限制：`VirtualTableTest` 覆盖 virtual table DDL/DML/read 规则，见 `test/unit/org/apache/cassandra/cql3/validation/entities/VirtualTableTest.java:72-220`。
- `system_views.settings` 远程/分区查询：`VirtualTableFromInternodeTest` 覆盖 coordinator 通过 internode 读 settings 全表、单 key 和 IN 查询，见 `test/distributed/org/apache/cassandra/distributed/test/VirtualTableFromInternodeTest.java:62-128`。
- clients/logs/queries/streaming：`ClientsTableTest`、`VirtualTableLogsTest`、`QueriesTableTest`、`RebuildStreamingTest` 覆盖连接、日志、运行中 query 和 streaming 表，见 `test/unit/org/apache/cassandra/db/virtual/ClientsTableTest.java:55-73`、`test/distributed/org/apache/cassandra/distributed/test/VirtualTableLogsTest.java:39-117`、`test/distributed/org/apache/cassandra/distributed/test/QueriesTableTest.java:92-161`、`test/distributed/org/apache/cassandra/distributed/test/streaming/RebuildStreamingTest.java:79-100`。
- metrics virtual tables：`CQLMetricsTableTest`、`BatchMetricsTableTest`、`CIDRFilteringMetricsTableTest`、`SSTableTasksTableTest` 覆盖 CQL/batch/CIDR/SSTable task rows，见 `test/unit/org/apache/cassandra/db/virtual/CQLMetricsTableTest.java:50-85`、`test/unit/org/apache/cassandra/db/virtual/BatchMetricsTableTest.java:51-55`、`test/unit/org/apache/cassandra/db/virtual/CIDRFilteringMetricsTableTest.java:97-180`、`test/unit/org/apache/cassandra/db/virtual/SSTableTasksTableTest.java:59-64`。
- repair/snapshot/SAI system views：`LocalRepairTablesTest`、`SnapshotsTableTest`、`IndexesSystemViewTest` 覆盖 repair state、snapshot rows 和 SAI virtual tables，见 `test/unit/org/apache/cassandra/db/virtual/LocalRepairTablesTest.java:82-197`、`test/unit/org/apache/cassandra/db/virtual/SnapshotsTableTest.java:67-104`、`test/unit/org/apache/cassandra/index/sai/virtual/IndexesSystemViewTest.java:53-132`。
- JMX surface：`JMXToolTest` 覆盖 dump/diff serde，`JMXCompatibilityTest` 用历史 dump 文件检查兼容性，`JMXGetterCheckTest` 验证可读 getters，见 `test/unit/org/apache/cassandra/tools/JMXToolTest.java:40-51`、`test/unit/org/apache/cassandra/tools/JMXCompatibilityTest.java:99-140`、`test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java:63-94`。
- nodetool mapping：`NodeToolCommandTest`、`NodeToolTest`、`TableStatsTest`、`TpStatsTest`、`CompactionStatsTest`、`ClientStatsTest`、`NetStatsTest`、`CIDRFilteringStatsTest` 覆盖命令注册/执行和代表性输出，见 `test/unit/org/apache/cassandra/tools/NodeToolCommandTest.java:38-77`、`test/distributed/org/apache/cassandra/distributed/test/NodeToolTest.java:55-145`、`test/unit/org/apache/cassandra/tools/nodetool/TableStatsTest.java:143-252`、`test/unit/org/apache/cassandra/tools/nodetool/TpStatsTest.java:101-154`、`test/unit/org/apache/cassandra/tools/nodetool/CompactionStatsTest.java:126-304`、`test/unit/org/apache/cassandra/tools/nodetool/ClientStatsTest.java:140-200`、`test/unit/org/apache/cassandra/tools/nodetool/NetStatsTest.java:106-106`、`test/unit/org/apache/cassandra/tools/nodetool/CIDRFilteringStatsTest.java:111-133`。

## 待继续

- 外部 Prometheus exporter 和 Grafana dashboard 不在当前仓库内；本轮已完成源码侧 JMX/virtual table 字段锚点，后续若引入具体 exporter 配置再补采集规则文件对照。
- nodetool command/option 覆盖已拆到 `module-observability-runbook-virtual-schema.md`、`module-nodetool-drift-checker.md`、`module-nodetool-option-risk-matrix.md` 和 `module-nodetool-option-drift-checker.md`；后续主要是把 observability drift checkers 接入 CI。
- 仍需补 `system_virtual_schema.columns` 对每张 virtual table 的机器生成列清单，用于后续自动化文档校验。
