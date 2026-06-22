# Module: Operations And Observability

## 范围

本模块覆盖 JMX、nodetool、metrics、tracing、logging 和 SSTable tools 的运维观测层，关注入口、权限、输出和常见风险。

## 设计目标

运维观测层把 Cassandra 运行时状态暴露给管理员、自动化系统和离线工具。它不是一个单独子系统，而是由以下几层组成：

- JMX/MBean：服务端注册运行时管理接口，`nodetool` 通过 `NodeProbe` 访问。
- nodetool：命令行入口，覆盖状态、拓扑、flush/repair/compaction、hints、logging、tracing、sampling 等操作。
- Metrics：Dropwizard metrics 注册到 JMX，同时支撑 nodetool、监控系统和 virtual tables。
- Tracing：按 query/repair trace session 写 `system_traces.sessions/events`；native protocol 与 cqlsh 侧细节见 `research/module-tracing-native-cqlsh.md`。
- Logging：logback 配置、动态 log level、可选 system_logs virtual table。
- Diagnostic Events：进程内事件 pub/sub、JMX read/persistence 和生产事件 catalog 见 `research/module-diagnostic-events-catalog.md`。
- SSTable tools：直接读取或重写磁盘 SSTable 的离线/半离线工具。

## 解决的问题

- 运维操作需要稳定远程 API：`StorageService`、`StorageProxy`、`HintsService`、`BatchlogManager`、`ColumnFamilyStore` 等都注册 MBean，`NodeProbe` 通过 JMX proxy 调用，见 `src/java/org/apache/cassandra/service/StorageService.java:561-562`、`src/java/org/apache/cassandra/service/StorageProxy.java:221-224`、`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:558`。
- nodetool 需要统一连接参数和命令分发：`NodeTool` 注册所有命令，`NodeToolCmd` 提供 `--host/--port/--username/--password` 等全局参数并创建 `NodeProbe`，见 `src/java/org/apache/cassandra/tools/NodeTool.java:85-98`、`src/java/org/apache/cassandra/tools/NodeTool.java:348-455`。
- metrics 需要同时是程序内对象和 JMX MBean：`CassandraMetricsRegistry` 在创建 counter/timer/register 时注册 MBean，并把 Gauge/Counter/Histogram/Timer/Meter 包装成 JMX bean，见 `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:55-60`、`src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:120-124`、`src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:229-250`。
- tracing 需要跨线程、跨节点传播 session：`Tracing` 保存 sessions、把 trace headers 放进消息，并对入站消息恢复 trace state，见 `src/java/org/apache/cassandra/tracing/Tracing.java:107-109`、`src/java/org/apache/cassandra/tracing/Tracing.java:248-312`。
- 日志需要运行时调级和文件配置：`StorageServiceMBean` 暴露 `setLoggingLevel/getLoggingLevels`，实现转发到 `LoggingSupportFactory`，见 `src/java/org/apache/cassandra/service/StorageServiceMBean.java:560-569`、`src/java/org/apache/cassandra/service/StorageService.java:5215-5227`。
- SSTable 离线工具需要避开 daemon 生命周期，直接初始化 descriptor/schema 并打开 SSTables，例如 scrub/verify/upgrader 都使用 tool initialization/openWithoutSSTables，见 `src/java/org/apache/cassandra/tools/StandaloneScrubber.java:82-100`、`src/java/org/apache/cassandra/tools/StandaloneVerifier.java:70-99`、`src/java/org/apache/cassandra/tools/StandaloneUpgrader.java:70-88`。

## 设计取舍

- JMX 注册经由 `MBeanWrapper`，可在测试中禁用或替换实现；默认使用 platform MBean wrapper，见 `src/java/org/apache/cassandra/utils/MBeanWrapper.java:39-81`。
- `NodeProbe` 是瘦代理，但持有大量 MBean proxy，避免每个 nodetool 命令重复创建 JMX object name，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:153-178`、`src/java/org/apache/cassandra/tools/NodeProbe.java:267-333`。
- in-JVM distributed test 不走远程 JMX，而是用 `InternalNodeProbe` 直接绑定单例服务实例，见 `test/distributed/org/apache/cassandra/distributed/mock/nodetool/InternalNodeProbe.java:50-85`。
- Table metrics 同时维护 per-table 和 global 视图；`TableMetrics.createTableCounter()` 注册表级 counter，也注册全局聚合 gauge，见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:72-83`、`src/java/org/apache/cassandra/metrics/TableMetrics.java:980-1008`。
- Tracing event 写入使用 `StorageProxy.mutate(..., ANY)`，失败时只 warn，避免 tracing 本身阻塞主请求，见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:112-121`。
- logback 默认 `scan=true` 每 60 秒扫描配置；Cassandra 另有动态 JMX 调级，二者同时存在，见 `conf/logback.xml:25-44`、`src/java/org/apache/cassandra/utils/logging/LogbackLoggingSupport.java:96-132`。
- `system_logs` virtual table 不是默认开启；logback 配置中需要显式启用 `VirtualTableAppender`，见 `conf/logback.xml:112-118`、`src/java/org/apache/cassandra/utils/logging/VirtualTableAppender.java:43-72`。

## 核心类

| 类 | 作用 |
|---|---|
| `MBeanWrapper` | MBean 注册/注销抽象，支持 no-op、platform 和自定义 wrapper。见 `src/java/org/apache/cassandra/utils/MBeanWrapper.java:39-130` |
| `NodeTool` | nodetool 主入口、命令注册、全局参数处理。见 `src/java/org/apache/cassandra/tools/NodeTool.java:73-98`、`src/java/org/apache/cassandra/tools/NodeTool.java:348-455` |
| `INodeProbeFactory` | nodetool 创建 `NodeProbe` 的工厂接口。见 `src/java/org/apache/cassandra/tools/INodeProbeFactory.java:23-42` |
| `NodeProbe` | JMX client facade，创建并缓存 StorageService、StorageProxy、CompactionManager、HintsService 等 proxy。见 `src/java/org/apache/cassandra/tools/NodeProbe.java:136-178`、`src/java/org/apache/cassandra/tools/NodeProbe.java:191-333` |
| `StorageServiceMBean` | 拓扑、repair、snapshot、logging、tracing、sampling 等主 MBean 接口。logging/tracing/sampling 见 `src/java/org/apache/cassandra/service/StorageServiceMBean.java:560-572`、`src/java/org/apache/cassandra/service/StorageServiceMBean.java:924-966` |
| `ColumnFamilyStoreMBean` | 表级 compaction、sampler、SSTable 和 tombstone 观测接口。见 `src/java/org/apache/cassandra/db/ColumnFamilyStoreMBean.java:35-120`、`src/java/org/apache/cassandra/db/ColumnFamilyStoreMBean.java:300-355` |
| `CassandraMetricsRegistry` | Dropwizard metrics 注册和 JMX wrapper。见 `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:45-60`、`src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:229-250` |
| `ClientRequestsMetricsHolder` | 全局 read/write/CAS/view request metrics 和按 CL 的 metrics map。见 `src/java/org/apache/cassandra/metrics/ClientRequestsMetricsHolder.java:25-53` |
| `Tracing` / `TracingImpl` / `TraceStateImpl` | trace session 管理、跨节点传播、写 `system_traces` mutation。见 `src/java/org/apache/cassandra/tracing/Tracing.java:49-110`、`src/java/org/apache/cassandra/tracing/TracingImpl.java:38-115`、`src/java/org/apache/cassandra/tracing/TraceStateImpl.java:47-95` |
| `TraceKeyspace` | `system_traces.sessions/events` schema 与 trace mutation 构造。见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:63-145` |
| `LoggingSupportFactory` / `LogbackLoggingSupport` | 运行时日志支持实现选择与 logback 调级。见 `src/java/org/apache/cassandra/utils/logging/LoggingSupportFactory.java:26-58`、`src/java/org/apache/cassandra/utils/logging/LogbackLoggingSupport.java:47-75` |
| `VirtualTableAppender` / `LogMessagesTable` | 可选将日志写入 `system_views.system_logs` virtual table。见 `src/java/org/apache/cassandra/utils/logging/VirtualTableAppender.java:43-72`、`src/java/org/apache/cassandra/db/virtual/LogMessagesTable.java:53-90` |

## 核心接口

- `NodeToolCmd.execute(NodeProbe probe)`：每个 nodetool 命令的执行入口，抽象定义见 `src/java/org/apache/cassandra/tools/NodeTool.java:442-455`。
- `NodeProbe.getColumnFamilyStoreMBeanProxies()`：枚举所有 CFS MBean，`tablestats` 等命令基于它取表级指标，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:796-810`。
- `NodeProbe.getCfsProxy(ks, cf)`：按 keyspace/table 查找单个 `ColumnFamilyStoreMBean`，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:1198-1225`。
- `StorageServiceMBean.setTraceProbability()` / `getTraceProbability()`：运行时设置随机 tracing 采样概率，见 `src/java/org/apache/cassandra/service/StorageServiceMBean.java:924-966`。
- `StorageServiceMBean.startSamplingPartitions()` / `stopSamplingPartitions()`：top partitions sampling 入口，见 `src/java/org/apache/cassandra/service/StorageServiceMBean.java:931-961`。
- `LoggingSupport.setLoggingLevel()` / `getLoggingLevels()`：动态日志接口，调用链见 `src/java/org/apache/cassandra/service/StorageService.java:5215-5227`。

## 核心数据结构

- `ObjectName`：MBean 名称空间，例如 StorageService 使用 `org.apache.cassandra.db:type=StorageService`，`NodeProbe` 的 `ssObjName` 定义见 `src/java/org/apache/cassandra/tools/NodeProbe.java:141-143`。
- `MetricName`：metrics 生成 Dropwizard 名称和 MBean 名称，`CassandraMetricsRegistry` 用 `name.getMetricName()` 与 `name.getMBeanName()` 注册，见 `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:55-60`。
- `TraceState` / `TraceType`：trace session id、QUERY/REPAIR 类型和 TTL；类型与 TTL 定义见 `src/java/org/apache/cassandra/tracing/Tracing.java:72-100`。
- `system_traces.sessions/events`：trace 表 schema，定义见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:69-113`。
- `LogMessagesTable.LogMessage` buffer：virtual log table 的内存 buffer，表定义和 append 入口见 `src/java/org/apache/cassandra/db/virtual/LogMessagesTable.java:57-90`、`src/java/org/apache/cassandra/db/virtual/LogMessagesTable.java:129-137`。
- `Descriptor` / `Component` / `SSTableReader`：SSTable 工具解析文件名、组件并打开 reader；scrub/verify 示例见 `src/java/org/apache/cassandra/tools/StandaloneScrubber.java:120-140`、`src/java/org/apache/cassandra/tools/StandaloneVerifier.java:101-130`。

## 生命周期

JMX/nodetool：

```text
CassandraDaemon / service singleton startup
  -> MBeanWrapper.instance.registerMBean(...)
  -> MBean visible under ObjectName

nodetool command
  -> NodeTool.main()
  -> NodeTool.execute()
  -> Airline parses command
  -> NodeToolCmd.runInternal()
     -> connect()
        -> NodeProbeFactory.create(host, port, user, pass)
        -> NodeProbe.connect()
           -> JMXConnectorFactory.connect()
           -> JMX.newMBeanProxy(...) for StorageService/StorageProxy/...
     -> command.execute(probe)
```

Metrics：

```text
module constructs metric
  -> CassandraMetricsRegistry.Metrics.counter/timer/register(...)
     -> Dropwizard registry
     -> registerMBean(metric, ObjectName)
  -> NodeProbe / external JMX scraper / virtual table reads attributes
```

Tracing：

```text
coordinator enables tracing
  -> Tracing.newSession()
  -> TracingImpl.begin()
     -> TraceKeyspace.makeStartSessionMutation()
     -> StorageProxy.mutate(..., ANY)
  -> Tracing.trace(...)
     -> TraceStateImpl.traceImpl()
     -> TraceKeyspace.makeEventMutation()
  -> Tracing.stopSession()
     -> TraceKeyspace.makeStopSessionMutation()
```

Logging：

```text
logback.xml
  -> SYSTEMLOG / DEBUGLOG / STDOUT appenders
  -> optional VirtualTableAppender
nodetool setlogginglevel
  -> NodeProbe.setLoggingLevel()
  -> StorageService.setLoggingLevel()
  -> LoggingSupportFactory.getLoggingSupport()
  -> LogbackLoggingSupport.setLoggingLevel()
```

SSTable tools：

```text
sstable* command main()
  -> DatabaseDescriptor.toolInitialization() or Util.initDatabaseDescriptor()
  -> Schema.instance.loadFromDisk()
  -> Keyspace.openWithoutSSTables(...)
  -> list directories / parse Descriptor
  -> SSTableReader.openNoValidation(...)
  -> inspect, verify, scrub, split, upgrade, export, or list files
```

## 调用链

- `NodeTool.main()` 创建 `NodeTool(new NodeProbeFactory(), Output.CONSOLE)` 并调用 `execute()`，见 `src/java/org/apache/cassandra/tools/NodeTool.java:85-98`。
- `NodeToolCmd.runInternal()` 处理密码、连接、执行、关闭，见 `src/java/org/apache/cassandra/tools/NodeTool.java:380-455`。
- `NodeProbe.connect()` 创建 JMX URL、连接、构造各 MBean proxy，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:191-333`。
- `status` 读取 joining/leaving/moving/live/unreachable、load、token、hostId、ownership 和 snitch rack/DC，优先 `effectiveOwnershipWithPort()` 并在 replication 设置不适合时降级 `getOwnershipWithPort()`，见 `src/java/org/apache/cassandra/tools/nodetool/Status.java:56-95`、`src/java/org/apache/cassandra/tools/NodeProbe.java:717-769`。
- `ring` 读取同一批 with-port StorageServiceMBean/snitch 数据源，但按 token 输出 `Address/Rack/Status/State/Load/Owns/Token`，vnode 集群会打印 token-level warning，见 `src/java/org/apache/cassandra/tools/nodetool/Ring.java:51-112`、`src/java/org/apache/cassandra/tools/NodeTool.java:515-534`。
- `info` 读取 hostId、gossip/native 状态、load、uptime、heap/offheap、exceptions、cache、network cache、PercentRepaired、token、bootstrap/decommission 和 out-of-range ops；offheap 由 `getOffHeapMemoryUsed()` 汇总 CFS table metrics，见 `src/java/org/apache/cassandra/tools/nodetool/Info.java:47-197`、`src/java/org/apache/cassandra/tools/nodetool/Info.java:207-218`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1752-1818`。
- `setcachecapacity`、`setcachekeystosave`、`invalidatekeycache`、`invalidaterowcache`、`invalidatecountercache` 走 `CacheServiceMBean` 修改或清理节点本地 key/row/counter cache；keys-to-save 会触发 `AutoSavingCache.scheduleSaving()` 重新调度，见 `src/java/org/apache/cassandra/tools/nodetool/SetCacheCapacity.java:129-143`、`src/java/org/apache/cassandra/tools/nodetool/SetCacheKeysToSave.java:174-188`、`src/java/org/apache/cassandra/tools/nodetool/InvalidateKeyCache.java:25-32`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1088-1101`、`src/java/org/apache/cassandra/service/CacheService.java:240-271`。
- `getendpoints`、`describering` 和 `getsstables` 是 key/range/SSTable locator 命令：前两者走 `StorageServiceMBean.getNaturalEndpointsWithPort()` / `describeRingWithPortJMX()`，后者走 `ColumnFamilyStoreMBean.getSSTablesForKey()` / `getSSTablesForKeyWithLevel()` 并只扫描 live SSTables，见 `src/java/org/apache/cassandra/tools/nodetool/GetEndpoints.java:31-60`、`src/java/org/apache/cassandra/tools/nodetool/DescribeRing.java:30-52`、`src/java/org/apache/cassandra/tools/nodetool/GetSSTables.java:33-69`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1109-1135`。
- `netstats` 读取 streaming session、read repair、messaging pool pending/completed/dropped，见 `src/java/org/apache/cassandra/tools/nodetool/NetStats.java:45-95`。
- `tablestats` 支持 sort/top/json/yaml 并构造 `TableStatsHolder`，见 `src/java/org/apache/cassandra/tools/nodetool/TableStats.java:79-107`。
- `tablehistograms` 读取每表 `EstimatedPartitionSizeHistogram`、`EstimatedColumnCountHistogram`、`ReadLatency`、`WriteLatency` 和 `SSTablesPerReadHistogram`，以固定 50/75/95/98/99/min/max 行输出，见 `src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:43-166`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1972-2038`、`src/java/org/apache/cassandra/metrics/TableMetrics.java:533-554`。
- `profileload` / deprecated `toppartitions` 使用 `SamplerType`、`SamplingManager` 和 CFS `beginLocalSampling()` / `finishLocalSampling()` 对本地节点活动做短窗口采样；`--interval` 会注册后台 optional task 并把结果写入日志，见 `src/java/org/apache/cassandra/tools/nodetool/ProfileLoad.java:46-175`、`src/java/org/apache/cassandra/tools/nodetool/TopPartitions.java:22-25`、`src/java/org/apache/cassandra/metrics/SamplingManager.java:107-263`、`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:2055-2077`。
- `tpstats` 构造 `TpStatsHolder`，默认由 `TpStatsPrinter.DefaultPrinter` 读取 thread-pool JMX metrics 和 dropped-message queue wait latency，JSON/YAML 由 `TpStatsHolder.convert2Map()` 输出 `ThreadPools`、`DroppedMessage`、`WaitLatencies`，见 `src/java/org/apache/cassandra/tools/nodetool/TpStats.java:36-47`、`src/java/org/apache/cassandra/tools/nodetool/stats/TpStatsHolder.java:40-69`、`src/java/org/apache/cassandra/tools/nodetool/stats/TpStatsPrinter.java:52-104`。
- `proxyhistograms` 读取 `ClientRequest` JMX timer scopes `Read`、`Write`、`RangeSlice`、`CASRead`、`CASWrite`、`ViewWrite`，按 50/75/95/98/99/min/max 输出 coordinator request latency percentile，见 `src/java/org/apache/cassandra/tools/nodetool/ProxyHistograms.java:32-56`、`src/java/org/apache/cassandra/tools/NodeProbe.java:2052-2065`。
- `compactionstats` 读取 compaction manager proxy 和 compaction metrics，见 `src/java/org/apache/cassandra/tools/nodetool/CompactionStats.java:53-73`。
- `snapshot` 构造 skipFlush/ttl/tag/keyspace.table 参数，见 `src/java/org/apache/cassandra/tools/nodetool/Snapshot.java:39-95`。
- `flush` 对每个 keyspace 调用 `probe.forceKeyspaceFlush()`，见 `src/java/org/apache/cassandra/tools/nodetool/Flush.java:30-52`。
- `repair` 的 option 包括 sequential/local/dc/hosts/token range/full/preview/trace/skip-paxos/paxos-only，见 `src/java/org/apache/cassandra/tools/nodetool/Repair.java:44-106`。
- `NodeProbe` 将 flush/repair/compaction/sampling 等转发给 MBean，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:476-527`、`src/java/org/apache/cassandra/tools/NodeProbe.java:548-560`。
- `setlogginglevel` 支持 component alias 到一组 package/class，并调用 `probe.setLoggingLevel()`，见 `src/java/org/apache/cassandra/tools/nodetool/SetLoggingLevel.java:33-65`。
- `getlogginglevels` 直接打印 `probe.getLoggingLevels()`，见 `src/java/org/apache/cassandra/tools/nodetool/GetLoggingLevels.java:30-37`。
- `settraceprobability/gettraceprobability` 分别转发到 `StorageService`，见 `src/java/org/apache/cassandra/tools/nodetool/SetTraceProbability.java:30-38`、`src/java/org/apache/cassandra/tools/nodetool/GetTraceProbability.java:30-32`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1539-1542`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1677-1680`。

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| JMX host/port/user/password | nodetool global options `src/java/org/apache/cassandra/tools/NodeTool.java:351-367` | nodetool 连接远程 JVM 的参数 |
| `cassandra.disable_mbean_registration` / `mbean_registration_class` | `MBeanWrapper` 读取 relevant properties，见 `src/java/org/apache/cassandra/utils/MBeanWrapper.java:35-81` | 禁用或替换 MBean 注册 |
| `trace_type_query_ttl` / `trace_type_repair_ttl` | `src/java/org/apache/cassandra/config/Config.java:551-554`，模板 `conf/cassandra.yaml:1750-1754`，getter `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4167-4174` | `system_traces` query/repair trace TTL |
| `default_keyspace_rf` | 模板说明 `conf/cassandra.yaml:1872-1878` | `system_traces` RF 至少取 2 或默认 RF |
| logback scan / file appenders | `conf/logback.xml:25-72` | system.log/debug.log/stdout 输出和滚动策略 |
| tools logback | `conf/logback-tools.xml:20-33` | sstable tools/nodetool 类工具 stderr 日志阈值 |
| system logs virtual table appender | `conf/logback.xml:112-118` | 开启 `system_views.system_logs` 的日志入口 |

## Metrics

- registry 会把 `Counter` 包装成只暴露 `getCount()` 的 JMX counter，见 `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:471-490`；meter 暴露 count/mean/1m/5m/15m/rate unit，见 `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:493-510`。
- `ClientRequestsMetricsHolder` 定义 read/write/CAS/view 和按 CL 的 metrics，见 `src/java/org/apache/cassandra/metrics/ClientRequestsMetricsHolder.java:25-53`。
- `TableMetrics` 定义 memtable、SSTable per read、read/write/range latency、pending flush、bytes flushed 等表级 metrics，见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:86-123`。
- `TableMetrics` 构造 read/write/range latency 与 pending flush/bytes flushed，见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:628-635`。
- `ColumnFamilyStore.metricsFor()` 可按 table id 获取表 metrics，见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:3384-3387`。

## 日志

- `TraceType` 支持 `NONE/QUERY/REPAIR`，TTL 来自 `DatabaseDescriptor.getTracetype*TTL()`，见 `src/java/org/apache/cassandra/tracing/Tracing.java:72-100`。
- `TracingImpl.begin()` 写 start session，`stopSessionImpl()` 写 duration，见 `src/java/org/apache/cassandra/tracing/TracingImpl.java:40-66`。
- `TraceStateImpl.traceImpl()` 写 event mutation，`waitForPendingEvents()` 等待异步 trace 写入，见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:63-95`。
- trace event 写入异常不会抛给请求，只 warn "Too many nodes are overloaded to save trace events"，见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:112-121`。
- native protocol `TRACING` flag、response trace id 和 cqlsh `TRACING`/`SHOW SESSION` 展示链路见 `research/module-tracing-native-cqlsh.md`。
- `LogbackLoggingSupport.setLoggingLevel()` 支持空参数重载配置、空 level 清除 logger level、指定 level 设置 logger，见 `src/java/org/apache/cassandra/utils/logging/LogbackLoggingSupport.java:96-118`。
- `VirtualTableAppender` 在 virtual table 初始化前会缓冲日志，但缓冲数量有限，见 `src/java/org/apache/cassandra/utils/logging/VirtualTableAppender.java:51-72`、`src/java/org/apache/cassandra/utils/logging/VirtualTableAppender.java:121-127`。

## 运维关注点

- nodetool 绝大多数命令是 JMX 远程调用；权限、网络、SSL、JMX 端口、MBean 是否注册都会影响命令可用性。
- `tablestats` 是表级指标快照，不等同于端到端 client latency；端到端读写指标在 `ClientRequest` metrics。
- `settraceprobability 1` 会让所有请求 tracing，MBean 注释明确可能严重拖慢系统，见 `src/java/org/apache/cassandra/service/StorageServiceMBean.java:924-929`。
- repair `--trace` 写入 `system_traces.events`，命令参数说明见 `src/java/org/apache/cassandra/tools/nodetool/Repair.java:93-94`。
- 动态 log level 是进程内运行时状态；重启后由 logback 配置决定。
- SSTable standalone 工具通常应在节点停止或目标 SSTable 不被 Cassandra 正在修改时使用；源码多处使用 `openWithoutSSTables()` 和 offline transaction 来降低破坏面，见 `src/java/org/apache/cassandra/tools/StandaloneUpgrader.java:75-121`。

## 性能瓶颈

- 频繁 `tablestats/tablehistograms/top partitions` 会通过大量 CFS MBean 读取表级指标，对大 schema 集群会有管理面开销。
- Tracing 每条 event 都写 mutation 到 `system_traces`；高 trace probability 会增加 coordinator 写放大。
- Virtual log table 是内存 buffer，不是持久审计日志；高 WARN/ERROR 量下只保留有限行数。
- `sstablemetadata -s` 扫描 SSTable 内容并统计 widest/largest/tombstone leaders，比单纯读 metadata component 更重，见 `src/java/org/apache/cassandra/tools/SSTableMetadataViewer.java:250-320`。
- `sstableverify -e` extended verification 和 `sstablescrub` 都会实际读 SSTable 数据，耗 IO 并可能产生修复/重写输出。

## 常见故障

- `nodetool: Failed to connect`：`NodeToolCmd.connect()` 捕获 IO/security 异常后退出，见 `src/java/org/apache/cassandra/tools/NodeTool.java:444-463`。
- MBean 缺失：`NodeProbe.getCfsProxy()` 找不到 table MBean 会打印错误并 `System.exit(1)`，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:1198-1225`。
- 动态 log level 无效：非 logback slf4j binding 会落到 `NoOpFallbackLoggingSupport` 并 warn，见 `src/java/org/apache/cassandra/utils/logging/LoggingSupportFactory.java:41-58`。
- trace 查询缺失：`system_traces` TTL 到期或 trace writes 过载都可能导致事件不完整，TTL 定义见 `conf/cassandra.yaml:1750-1754`。
- standalone verify 默认要求 `-f/--force`，否则直接退出，见 `src/java/org/apache/cassandra/tools/StandaloneVerifier.java:70-79`。

## SSTable 工具速查

| 工具 | 作用 | 关键源码 |
|---|---|---|
| `sstableutil` | 列出 table 的 final/tmp/txn log SSTable 文件 | `src/java/org/apache/cassandra/tools/StandaloneSSTableUtil.java:83-109`、`src/java/org/apache/cassandra/tools/StandaloneSSTableUtil.java:218-239` |
| `sstablescrub` | snapshot 后打开 SSTable，尝试 scrub/修复 | `src/java/org/apache/cassandra/tools/StandaloneScrubber.java:82-140`、`src/java/org/apache/cassandra/tools/StandaloneScrubber.java:260-330` |
| `sstableverify` | 打开 SSTable 并执行 verifier，可 extended/check version/token range | `src/java/org/apache/cassandra/tools/StandaloneVerifier.java:70-130`、`src/java/org/apache/cassandra/tools/StandaloneVerifier.java:275-287` |
| `sstableupgrade` | offline lifecycle transaction 中升级 SSTable 到当前格式 | `src/java/org/apache/cassandra/tools/StandaloneUpgrader.java:70-121`、`src/java/org/apache/cassandra/tools/StandaloneUpgrader.java:214-230` |
| `sstablesplit` | 校验 SSTable 文件列表并按大小拆分，默认先 snapshot | `src/java/org/apache/cassandra/tools/StandaloneSplitter.java:70-130`、`src/java/org/apache/cassandra/tools/StandaloneSplitter.java:247-254` |
| `sstablemetadata` | 查看 metadata component，可扫描分区大小/墓碑 leader | `src/java/org/apache/cassandra/tools/SSTableMetadataViewer.java:74-113`、`src/java/org/apache/cassandra/tools/SSTableMetadataViewer.java:250-320` |
| `sstableexport` | 将 SSTable 导出 JSON，支持 key include/exclude/json-lines | `src/java/org/apache/cassandra/tools/SSTableExport.java:75-130` |

standalone 工具的安全运行条件、只读/重写/metadata mutation 分类和选项风险矩阵见 `research/module-sstable-tools-safety-runbook.md`。

## 测试用例

- JMX/nodetool：`test/unit/org/apache/cassandra/tools/NodeProbeTest.java`、`test/unit/org/apache/cassandra/tools/NodeToolCommandTest.java`、`test/distributed/org/apache/cassandra/distributed/test/NodeToolTest.java`、`test/distributed/org/apache/cassandra/distributed/test/jmx/JMXFeatureTest.java`、`test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java`。
- metrics：`test/unit/org/apache/cassandra/metrics/CassandraMetricsRegistryTest.java`、`test/unit/org/apache/cassandra/metrics/TableMetricsTest.java`、`test/unit/org/apache/cassandra/metrics/ClientRequestMetricsTest.java`、`test/distributed/org/apache/cassandra/distributed/test/MetricsTest.java`。
- tracing/logging：`test/unit/org/apache/cassandra/tracing/TracingTest.java`、`test/unit/org/apache/cassandra/cql3/TraceCqlTest.java`、`pylib/cqlshlib/test/test_cqlsh_completion.py`、`test/distributed/org/apache/cassandra/distributed/test/FailureLoggingTest.java`。
- SSTable tools：`test/unit/org/apache/cassandra/tools/SSTableExportTest.java`、`test/unit/org/apache/cassandra/tools/SSTableMetadataViewerTest.java`、`test/unit/org/apache/cassandra/tools/StandaloneVerifierOnSSTablesTest.java`、`test/unit/org/apache/cassandra/tools/StandaloneSSTableUtilTest.java`、`test/unit/org/apache/cassandra/tools/nodetool/ScrubToolTest.java`。

## 待继续

- 单独展开 virtual tables 全量清单及其与 metrics/JMX 的映射。
- 单独展开 audit log、full query log 的外部采集与保留策略。
- 单独展开 JMX auth/permission 与 nodetool 在 secure deployment 下的连接参数。
- 单独展开每个 nodetool 子命令到具体 MBean 方法的完整表。
