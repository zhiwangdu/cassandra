# Module: Metrics Registry And Export Surface Matrix

## 范围

本矩阵补充 `module-operations-observability.md`、`module-observability-internals.md` 和 `module-observability-mapping.md` 的 Metrics 部分，聚焦 Cassandra 内置 metrics 从注册、JMX ObjectName、nodetool 读取、`system_views` virtual table 到外部 dashboard/alert 缺口的源码合同。不重复展开每个业务模块的全部指标语义。

## 场景矩阵

| 场景 ID | 源码锚点 | 现有测试 | 运维/故障含义 |
|---|---|---|---|
| `metrics_registry_dropwizard_jmx_bridge` | `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:45-263` 是全局 Dropwizard registry；`counter/meter/histogram/timer/register` 注册 metric 后同时注册 JMX MBean；Gauge/Counter/Histogram/Timer/Metered 分别包装成 `Jmx*` MBean，`gaugeCompatible` meter 额外暴露 `Value`。 | `test/unit/org/apache/cassandra/metrics/CassandraMetricsRegistryTest.java:67-145` 覆盖 JVM metrics 注册、histogram delta 和 timer reservoir。 | 监控系统读到的 JMX 属性来自 wrapper，不是直接暴露 Dropwizard 对象；Timer 默认 microseconds，histogram `RecentValues` 是自上次读取后的 delta。 |
| `metrics_name_objectname_contract` | `src/java/org/apache/cassandra/metrics/DefaultNameFactory.java:24-58` 统一 `org.apache.cassandra.metrics:type=...,scope=...,name=...`；`CassandraMetricsRegistry.MetricName` 保存 Dropwizard name 与 MBean ObjectName；`MetricName.chooseType()` 处理 class 名称。 | `CassandraMetricsRegistryTest.testChooseType()` / `testMetricName()` 覆盖 type 推导；`test/distributed/org/apache/cassandra/distributed/test/metric/TableMetricTest.java:221-230` 断言 Table/Keyspace ObjectName 字符串。 | 外部 scraper/dashboard 应以 ObjectName contract 为主；scope/keyspace/table/type 变化会直接破坏告警查询。 |
| `metrics_table_keyspace_lifecycle` | `src/java/org/apache/cassandra/metrics/TableMetrics.java:72-1328` 维护 per-table、ColumnFamily alias、global Table 聚合和 release；`src/java/org/apache/cassandra/metrics/KeyspaceMetrics.java:197-433` 从 table metrics 聚合 keyspace metrics，drop 时释放。 | `TableMetricsTest.testMetricsCleanupOnDrop()`、`testViewMetricsCleanupOnDrop()` 和 `KeyspaceMetricsTest.testMetricsCleanupOnDrop()` 覆盖 drop cleanup；distributed `TableMetricTest.userTables()` 覆盖 schema change/drop 不污染其他表。 | 表/视图/keyspace 删除后 MBean 必须消失，否则 dashboard 会出现幽灵 series；全局 Table metric 是聚合视图，不等于某个表。 |
| `metrics_client_request_scope` | `ClientRequestsMetricsHolder.java:25-53` 定义全局 Read/Write/CAS/ViewWrite 以及按 `ConsistencyLevel` 的 read/write map；`ClientRequestMetrics.java:32-78` 记录 timeout/unavailable/failure/abort/local/remote；`ClientRangeRequestMetrics.java:28-45` 增加 range round trips。 | `ClientRequestMetricsTest.java:82-177` 覆盖 write/Paxos/batch/read/range 的 local/remote request 计数和 range round trips。 | `ClientRequest` metrics 是端到端 coordinator 视角；表级 latency 不能替代读写成功率、timeout/failure 和本地/远程路由判断。 |
| `metrics_threadpool_cache_virtual_tables` | `ThreadPoolMetrics.java:31-132` 注册 active/pending/completed/blocked/max/oldest task；`ThreadPoolsTable.java:25-81` 投影到 `system_views.thread_pools`；`CacheMetrics.java:35-102` 维护 cache capacity/size/entries/hit/miss/rate，`CachesTable.java:29-93` 投影 chunks/counters/keys/rows。 | `ThreadPoolMetricsTest.testJMXEnabledThreadPoolMetricsWithBlockedThread()` 覆盖 blocked counters；`CacheMetricsTest.testCacheMetrics()` 覆盖 hit/miss/request/hitRate；virtual table 行为由 system_views tests 间接覆盖。 | thread pool blocked/current 与 cache hit ratio 是常见故障入口；virtual tables 是快照视图，仍要理解其底层 metric 类型。 |
| `metrics_cql_batch_virtual_tables` | `CQLMetricsTable.java:31-82` 暴露 prepared count/evicted/executed/ratio 和 regular executed；`BatchMetricsTable.java:35-82` 暴露 logged/unlogged/counter batch partitions histogram。 | `CQLMetricsTableTest.testUsingPrepareStmts()` / `testUsingInjectedValues()` 验证 CQL metrics rows；`BatchMetricsTableTest.testSelectAll()` 验证 3 行 batch histogram。 | prepared cache 与 batch shape 可以通过 CQL 读取，但这些表只覆盖特定指标子集，不是通用 metrics exporter。 |
| `metrics_nodeprobe_nodetool_consumers` | `NodeProbe.java:1746-2209` 用 JMX proxy 读取 cache、buffer pool、thread pools、table/keyspace/global table、client request、compaction、client、CIDR、storage metrics；`TableStats`/`CompactionStats` 依赖这些 getter。 | `NodeProbeTest`、`NodeToolCommandTest`、`TableStatsTest`、`CompactionStatsTest` 和 distributed JMX tests 覆盖 nodetool/JMX 基线；`TableMetricTest` 覆盖 table MBean 存在性。 | nodetool 输出不是独立采集系统，它复用同一 JMX ObjectName；MBean 缺失/权限不足会同时影响 nodetool 与外部 JMX scraper。 |
| `metrics_jvm_logback_bridge` | `CassandraDaemon.java:121-133` 在 logger 初始化前把 logback shared registry 的 meters 注册到 Cassandra metrics JMX；`CassandraMetricsRegistryTest.testJvmMetricsRegistration()` 覆盖 JVM metrics name 不含 `..`。 | `CassandraMetricsRegistryTest` 覆盖 `jvm.buffers`、`jvm.gc`、`jvm.memory` 注册；logback metrics 主要靠 daemon static block source contract。 | JVM/logback metrics 与 Cassandra metrics 共用 registry/JMX 面；logger 初始化顺序会影响 logback appender metrics 是否能被纳入。 |
| `metrics_global_storage_compaction_streaming` | `StorageMetrics.java:34-60` 注册 Load/Exceptions/TotalHints/invalid token counters；`CommitLogMetrics.java:31-81` 注册 commitlog wait/size/oversized mutation；`CompactionMetrics.java:42-156` 注册 pending/completed/bytes/abort；`StreamingMetrics.java:42-87` 注册全局和 peer scope streaming bytes/SSTables。 | 各模块测试通过 write/flush/compaction/streaming 间接更新；本矩阵 checker 保护 source registration token。 | 这些全局指标常用于容量和背压告警；必须按 type/scope 分清 Storage、CommitLog、Compaction、Streaming，不能只看 table metrics。 |
| `metrics_external_dashboard_gap` | 当前仓库没有 source-owned Grafana/Prometheus/JMX exporter/Alertmanager dashboard 或 alert 配置文件；只有 Cassandra 内置 JMX、nodetool 和 virtual table surfaces。 | 本矩阵 checker 对配置/dashboard 文件名做 negative scan；历史 NEWS/doc prose 提到 exporter/Grafana 不算可部署规则。 | 生产 dashboard、scrape interval、alert threshold、label mapping、retention 和 cardinality 控制仍需要部署侧定义；当前 research 只能给出内置字段合同。 |

## 运维判读

- Cassandra metrics 有三种常用读取面：JMX ObjectName、nodetool getter、`system_views` virtual table。三者共享底层 metric，但字段名、单位和覆盖范围不同。
- Table metrics 同时存在 table、legacy `ColumnFamily` alias、keyspace 聚合和 global Table 聚合。排查 drop/rename/视图问题时要确认 old MBean 是否释放。
- Timer/Histogram 的 JMX 属性包含分位数和 recent delta；外部系统采集 `RecentValues` 会改变下次读取结果，不适合多个 scraper 并行读取同一属性。
- Virtual tables 做了面向 CQL 的投影和单位转换，例如 table latency 转 ms、disk usage 转 MiB；不要把它当原始 Dropwizard/JMX 字段的逐项镜像。
- `ClientRequest` metrics 是 coordinator 端到端请求视角；`TableMetrics` 更接近本地表读写/flush/compaction 视角。故障定位通常需要两者对照。

## 当前缺口

- `metrics_external_dashboard_gap`：缺少 source-owned Prometheus/JMX exporter、Grafana dashboard、Alertmanager/alert rule 文件级对照。
- `metrics_nodeprobe_nodetool_consumers`：已有 JMX/nodetool 基线，但缺按所有 `NodeProbe.get*Metric()` getter 自动枚举 ObjectName 的 checker。
