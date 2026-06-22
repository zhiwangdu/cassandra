# Flow: Operations Tools

## 目标

把常见运维入口串成调用图：nodetool 如何通过 JMX 调用服务端 MBean，metrics/tracing/logging 如何暴露观测数据，SSTable 工具如何离线读取磁盘文件。

## nodetool / JMX 调用图

```text
Shell
  -> nodetool <command> [global options]
  -> NodeTool.main()
     -> NodeTool.execute()
        -> command registry
        -> Airline parses command class
        -> NodeToolCmd.runInternal()
           -> read password if needed
           -> connect()
              -> NodeProbeFactory.create(host, port, username, password)
              -> NodeProbe.connect()
                 -> JMXConnectorFactory.connect(service:jmx:rmi...)
                 -> JMX.newMBeanProxy(StorageServiceMBean)
                 -> JMX.newMBeanProxy(StorageProxyMBean)
                 -> JMX.newMBeanProxy(CompactionManagerMBean)
                 -> JMX.newMBeanProxy(HintsServiceMBean)
                 -> JMX.newMBeanProxy(BatchlogManagerMBean)
                 -> JMX.newMBeanProxy(...)
           -> command.execute(probe)
              -> probe method
              -> MBean method
              -> output formatter / table builder
```

## Metrics 调用图

```text
Subsystem constructs metric
  -> CassandraMetricsRegistry.Metrics.counter/timer/register(...)
     -> Dropwizard metric registry
     -> MBeanWrapper.registerMBean(JmxCounter/JmxTimer/JmxMeter/...)
  -> external JMX scraper or nodetool reads attributes
  -> tablestats/tpstats/compactionstats format selected metric groups
```

## Tracing 调用图

```text
Client enables tracing or nodetool repair --trace
  -> Tracing.newSession()
  -> TracingImpl.begin(request, client, parameters)
     -> TraceKeyspace.makeStartSessionMutation()
     -> StorageProxy.mutate(..., ANY)
  -> request code calls Tracing.trace(...)
     -> TraceStateImpl.traceImpl()
     -> TraceKeyspace.makeEventMutation()
  -> outgoing internode messages include trace headers
  -> remote Tracing.initializeFromMessage()
  -> Tracing.stopSession()
     -> TraceKeyspace.makeStopSessionMutation()
```

## Logging 调用图

```text
conf/logback.xml
  -> SYSTEMLOG writes system.log at INFO+
  -> DEBUGLOG writes debug.log
  -> optional VirtualTableAppender writes system_views.system_logs

nodetool setlogginglevel
  -> SetLoggingLevel.execute()
  -> NodeProbe.setLoggingLevel()
  -> StorageServiceMBean.setLoggingLevel()
  -> StorageService.setLoggingLevel()
  -> LoggingSupportFactory.getLoggingSupport()
  -> LogbackLoggingSupport.setLoggingLevel()
```

## SSTable Tool 调用图

```text
sstable* command
  -> main()
  -> DatabaseDescriptor.toolInitialization() / Util.initDatabaseDescriptor()
  -> Schema.instance.loadFromDisk()
  -> Keyspace.openWithoutSSTables(keyspace)
  -> ColumnFamilyStore cfs
  -> directories.sstableLister() or Descriptor.fromFile()
  -> SSTableReader.openNoValidation()
  -> inspect / verify / scrub / split / upgrade / export
```

## 关键源码锚点

| 阶段 | 文件/方法 |
|---|---|
| nodetool 入口 | `NodeTool.main()` / `execute()`：`src/java/org/apache/cassandra/tools/NodeTool.java:85-98` |
| nodetool 全局参数 | `NodeToolCmd` options：`src/java/org/apache/cassandra/tools/NodeTool.java:348-367` |
| nodetool 连接 | `NodeToolCmd.connect()`：`src/java/org/apache/cassandra/tools/NodeTool.java:444-463` |
| NodeProbe JMX proxy | `NodeProbe.connect()`：`src/java/org/apache/cassandra/tools/NodeProbe.java:262-333` |
| in-JVM NodeProbe | `InternalNodeProbe.connect()`：`test/distributed/org/apache/cassandra/distributed/mock/nodetool/InternalNodeProbe.java:61-85` |
| MBean wrapper | `MBeanWrapper`：`src/java/org/apache/cassandra/utils/MBeanWrapper.java:39-130` |
| metrics registry | `CassandraMetricsRegistry`：`src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:55-60`、`src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:229-250` |
| table stats command | `TableStats.execute()`：`src/java/org/apache/cassandra/tools/nodetool/TableStats.java:79-107` |
| thread pool stats command | `TpStats.execute()`：`src/java/org/apache/cassandra/tools/nodetool/TpStats.java:36-47` |
| compaction stats command | `CompactionStats.execute()`：`src/java/org/apache/cassandra/tools/nodetool/CompactionStats.java:53-73` |
| logging command | `SetLoggingLevel.execute()`：`src/java/org/apache/cassandra/tools/nodetool/SetLoggingLevel.java:33-65` |
| logging backend | `LogbackLoggingSupport.setLoggingLevel()`：`src/java/org/apache/cassandra/utils/logging/LogbackLoggingSupport.java:96-132` |
| trace probability command | `SetTraceProbability.execute()`：`src/java/org/apache/cassandra/tools/nodetool/SetTraceProbability.java:30-38` |
| tracing session | `Tracing.newSession()` / `TraceStateImpl.traceImpl()`：`src/java/org/apache/cassandra/tracing/Tracing.java:151-190`、`src/java/org/apache/cassandra/tracing/TraceStateImpl.java:63-95` |
| trace tables | `TraceKeyspace` schema：`src/java/org/apache/cassandra/tracing/TraceKeyspace.java:69-113` |
| standalone scrub | `StandaloneScrubber.main()`：`src/java/org/apache/cassandra/tools/StandaloneScrubber.java:82-140` |
| standalone verify | `StandaloneVerifier.main()`：`src/java/org/apache/cassandra/tools/StandaloneVerifier.java:70-130` |
| standalone upgrade | `StandaloneUpgrader` main flow：`src/java/org/apache/cassandra/tools/StandaloneUpgrader.java:70-121` |
| sstable metadata | `SSTableMetadataViewer` scan/metadata flow：`src/java/org/apache/cassandra/tools/SSTableMetadataViewer.java:250-320` |

## 命令到 MBean/子系统映射

| 命令 | 主要调用 | 说明 |
|---|---|---|
| `nodetool status` | `NodeProbe.getJoiningNodes/getLiveNodes/getTokenToEndpointMap/effectiveOwnershipWithPort` | ring 状态、load、hostId、ownership，见 `src/java/org/apache/cassandra/tools/nodetool/Status.java:56-95` |
| `nodetool info` | `NodeProbe` 的 StorageService、GC、Memory、Cache proxy | 节点本地状态和 cache/heap，见 `src/java/org/apache/cassandra/tools/nodetool/Info.java:47-95` |
| `nodetool netstats` | StreamManager + MessagingService MBean | streaming、read repair、message pool，见 `src/java/org/apache/cassandra/tools/nodetool/NetStats.java:45-95` |
| `nodetool flush` | `NodeProbe.forceKeyspaceFlush()` -> `StorageServiceMBean.forceKeyspaceFlush()` | 强制 memtable flush，见 `src/java/org/apache/cassandra/tools/nodetool/Flush.java:30-52`、`src/java/org/apache/cassandra/tools/NodeProbe.java:509-512` |
| `nodetool snapshot` | `StorageServiceMBean.takeSnapshot` 系列 | snapshot options 包括 tag/skip-flush/ttl，见 `src/java/org/apache/cassandra/tools/nodetool/Snapshot.java:39-95` |
| `nodetool repair` | `NodeProbe.repairAsync()` -> `StorageServiceMBean.repairAsync` | repair options 构造成 map 并监听通知，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:519-545` |
| `nodetool tablestats` | CFS MBeans + stats printers | 支持 json/yaml/sort/top，见 `src/java/org/apache/cassandra/tools/nodetool/TableStats.java:35-107` |
| `nodetool setlogginglevel` | `StorageServiceMBean.setLoggingLevel()` | 运行时 logback 调级，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:2248-2257` |
| `nodetool settraceprobability` | `StorageServiceMBean.setTraceProbability()` | 随机 tracing 采样，见 `src/java/org/apache/cassandra/service/StorageService.java:6626-6634` |

## 排查路径

1. nodetool 连不上：检查 host/port/user/password、JMX SSL、目标进程是否注册 MBean。连接失败路径见 `src/java/org/apache/cassandra/tools/NodeTool.java:444-463`。
2. 指标缺失：确认对应模块是否构造 metrics、`CassandraMetricsRegistry` 是否注册 MBean、表是否存在对应 CFS MBean。
3. tracing 不完整：检查 trace TTL、`system_traces` RF、overload warn；trace mutation 使用 CL.ANY，见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:112-121`。
4. 动态日志没生效：确认 slf4j binding 是 logback；否则 `LoggingSupportFactory` 会使用 no-op fallback，见 `src/java/org/apache/cassandra/utils/logging/LoggingSupportFactory.java:41-58`。
5. sstable 工具失败：先用 `sstableutil` 确认文件列表，再用 `sstablemetadata` 看 descriptor/metadata，最后才考虑 `sstableverify` 或 `sstablescrub`。

## 测试用例

- `test/unit/org/apache/cassandra/tools/NodeProbeTest.java`
- `test/unit/org/apache/cassandra/tools/NodeToolCommandTest.java`
- `test/unit/org/apache/cassandra/tools/JMXToolTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/NodeToolTest.java`
- `test/unit/org/apache/cassandra/metrics/CassandraMetricsRegistryTest.java`
- `test/unit/org/apache/cassandra/tracing/TracingTest.java`
- `test/unit/org/apache/cassandra/tools/SSTableMetadataViewerTest.java`
- `test/unit/org/apache/cassandra/tools/StandaloneVerifierOnSSTablesTest.java`
