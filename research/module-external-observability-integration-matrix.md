# Module: External Observability Integration Matrix

## 范围

本矩阵补充 `module-metrics-registry-export-matrix.md` 与 `module-logging-audit-fql-operations-matrix.md`，只关注 Cassandra 源码仓库内已经稳定暴露给外部观测系统的接口，以及当前 checkout 没有 source-owned Prometheus/JMX exporter、Grafana dashboard、alert rule、Filebeat/Fluent Bit/Vector/Logstash/Promtail 配置的文件级缺口。不把生产部署侧自定义配置推断成 Cassandra core 行为。

## 调用图

Metrics 外部读取主线：

```text
module metric class
  -> CassandraMetricsRegistry.counter/meter/histogram/timer/register(...)
  -> CassandraMetricsRegistry.registerMBean(...)
  -> JmxGauge/JmxCounter/JmxHistogram/JmxTimer/JmxMeter wrapper
  -> org.apache.cassandra.metrics:* ObjectName
  -> NodeProbe.get*Metric(...) / JMX client / exporter
```

Virtual metrics 读取主线：

```text
CQL SELECT system_views.*
  -> virtual table provider
  -> TableMetricTables / CQLMetricsTable / BatchMetricsTable / ThreadPoolsTable / CachesTable
  -> Dropwizard metric snapshot and unit conversion
  -> CQL rows
```

日志外部采集主线：

```text
logback root appenders
  -> SYSTEMLOG / DEBUGLOG / STDOUT / optional AUDIT / optional CQLLOG
  -> local files or system_views.system_logs
  -> deployment-side collector if configured outside this repository

AuditLogManager / FullQueryLogger
  -> QueryEvents/AuthEvents listener
  -> BinAuditLogger or FullQueryLogger BinLog
  -> BinLog queue, roll cycle, local retention/archive command
  -> deployment-side collector/archiver if configured outside this repository
```

## 场景矩阵

| 场景 ID | 源码锚点 | 现有测试 | 运维/故障含义 |
|---|---|---|---|
| `external_observability_jmx_metric_contract` | `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:55-263` 把 Dropwizard `Counter`、`Meter`、`Histogram`、`Timer`、`Gauge` 包装为 JMX MBean；`JmxTimerMBean` 暴露 percentile、`RecentValues` 和 duration unit，见 `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:589-615`。 | `test/unit/org/apache/cassandra/metrics/CassandraMetricsRegistryTest.java:60-145` 覆盖 `MetricName`、JVM metrics 和 timer/histogram wrapper baseline。 | 外部 JMX exporter 应以 ObjectName 和 wrapper attribute 为 contract；`RecentValues` 会被读取者消耗，不适合作为多个 scraper 的共享指标。 |
| `external_observability_nodeprobe_metric_contract` | `src/java/org/apache/cassandra/tools/NodeProbe.java:1746-2209` 用固定 ObjectName 读取 cache、thread pool、table/keyspace/global table、ClientRequest、Messaging、Compaction、Client、CIDR、Storage metrics。 | `test/distributed/org/apache/cassandra/distributed/test/metric/TableMetricTest.java:70-230` 覆盖 system/user table ObjectName 存在和 drop cleanup；nodetool stats tests 间接依赖这些 getter。 | nodetool 与外部 JMX scraper 共用 JMX 面；ObjectName 变化会同时破坏 operator CLI、dashboard 和 alert。 |
| `external_observability_virtual_metrics_contract` | `src/java/org/apache/cassandra/db/virtual/TableMetricTables.java:68-83` 生成 table metrics virtual tables；`CQLMetricsTable.java`、`BatchMetricsTable.java`、`ThreadPoolsTable.java`、`CachesTable.java` 投影 CQL、batch、thread pool 和 cache 指标。 | `test/unit/org/apache/cassandra/db/virtual/CQLMetricsTableTest.java:83-124`、`BatchMetricsTableTest.java:56-90`、cache/thread-pool metrics tests 覆盖 virtual table baseline。 | `system_views` 是经过单位转换和字段筛选的快照视图，不是 JMX 的逐字段镜像；dashboard 映射需要明确选择 JMX 还是 CQL virtual table。 |
| `external_observability_logback_file_contract` | `conf/logback.xml:25-132` 定义 daemon `SYSTEMLOG`、`DEBUGLOG`、`ASYNCDEBUGLOG`、`STDOUT`，并保留可选 `AUDIT`、`LogbackMetrics`、`CQLLOG` appender；`conf/logback-tools.xml:20-33` 让工具默认只写 WARN+ stderr。 | `test/distributed/org/apache/cassandra/distributed/test/VirtualTableLogsTest.java:55-117` 覆盖 dtest logback virtual appender；logback daemon/tools 文件本身是配置 contract。 | 外部 log collector 的文件路径、roll/retention、debug.log 开关和 audit file logger 都来自 logback/deployment 组合，不由 metrics registry 推断。 |
| `external_observability_system_logs_contract` | `src/java/org/apache/cassandra/utils/logging/VirtualTableAppender.java:43-127` 将 logback 事件写入 `LogMessagesTable`，并排除 `FileAuditLogger`；`src/java/org/apache/cassandra/db/virtual/LogMessagesTable.java:57-151` 定义 `system_logs` 列、最大行数和 bounded buffer。 | `test/unit/org/apache/cassandra/db/virtual/LogMessagesTableTest.java:65-146` 覆盖 truncate、capacity、same-millisecond ordering 和 `cassandra.virtual.logs.max.rows`；`VirtualTableLogsTest` 覆盖 CQL 读取。 | `system_views.system_logs` 是内存窗口，只适合最近日志排障；不能替代 system/debug/audit/FQL 文件采集和长期保留。 |
| `external_observability_audit_fql_contract` | `src/java/org/apache/cassandra/audit/AuditLogManager.java:59-217` 管理 audit listener、filter、logger 切换和 MBean；`src/java/org/apache/cassandra/fql/FullQueryLogger.java:91-181` 管理 FQL `BinLog`、listener 注册和 stop。 | `test/unit/org/apache/cassandra/audit/AuditLoggerTest.java:156-180` 覆盖 listener transition；`test/unit/org/apache/cassandra/fql/FullQueryLoggerTest.java:100-260` 覆盖 enable/stop/reset/path behavior。 | audit 与 FQL 都可能记录敏感 query/user 信息；collector、retention、权限和脱敏策略必须按日志类型分别设计。 |
| `external_observability_binlog_retention_contract` | `src/java/org/apache/cassandra/utils/binlog/BinLog.java:70-190` 使用 weighted queue、binary-log 线程、`currentPaths` 冲突保护、blocking/drop 取舍和 archiver；`DeletingArchiver` 与 `ExternalArchiver` 决定本地删除或外部 archive command。 | `FullQueryLoggerTest.java:260-420` 覆盖 blocking/drop；`AuditLoggerTest.java:699-725` 覆盖 audit/FQL path conflict；`BinLogTest` 覆盖基础 binlog behavior。 | FQL/audit 的 `block=true` 可能反压 CQL/auth 路径；`block=false` 会丢样本。外部 collector 不能只看文件存在，还要对齐 queue、archive 和 disk quota。 |
| `external_observability_prometheus_exporter_gap` | 当前 checkout 没有 source-owned Prometheus scrape config、JMX exporter YAML、OpenTelemetry collector 或 metrics reporter 配置；内置面只有 JMX、nodetool 和 `system_views`。 | `research/tools/check-external-observability-drift.py` 对文件名和 config 内容做 negative scan；metrics registry checker 也保护 `metrics_external_dashboard_gap`。 | 生产 scrape interval、ObjectName allowlist、label/cardinality、unit conversion 和 retention 仍是部署侧责任。 |
| `external_observability_grafana_dashboard_gap` | 当前 checkout 没有 source-owned Grafana dashboard JSON/YAML 或 dashboard provisioning 文件。 | 新 checker 对 `grafana`、`dashboard` 等文件名和 dashboard JSON marker 做 negative scan。 | 没有仓库内 dashboard 时，research 只能给出字段 contract，不能保证 panel、legend、变量和阈值已经被版本化。 |
| `external_observability_alert_rules_gap` | 当前 checkout 没有 Prometheus alert rule、Alertmanager route/receiver 或 Cassandra alert policy 配置。 | 新 checker 对 alert rule/Alertmanager 文件名与 `groups/alert/expr`、`route/receivers` 类 config marker 做 negative scan。 | timeout、dropped message、pending compaction、disk/cdc/backlog 等告警阈值需要外部规则；源码只证明指标存在和语义。 |
| `external_observability_log_collector_gap` | 当前 checkout 没有 Filebeat、Fluent Bit、Fluentd、Vector、Logstash、Promtail 等日志采集器配置。 | logging/audit/FQL checker 与新 checker 都保护该 negative baseline；SAI `Vector*` 源码不会被当作 collector 命中。 | system.log/debug.log/audit/FQL 的采集、保留、压缩、权限和敏感字段处理仍需部署 runbook 或额外仓库证明。 |
| `external_observability_existing_tests_baseline` | 当前内置观测面由 metrics/logback/audit/FQL/unit/distributed tests 覆盖，外部 exporter/dashboard/collector 没有可运行测试。 | `CassandraMetricsRegistryTest`、`TableMetricTest`、`CQLMetricsTableTest`、`BatchMetricsTableTest`、`LogMessagesTableTest`、`VirtualTableLogsTest`、`AuditLoggerTest`、`FullQueryLoggerTest` 是现有 baseline。 | 新增任何 source-owned 外部配置后，应补最小 lint/shape checker 或 fixture test，不能只把配置文件放进仓库。 |

## 运维判读

- 外部 metrics 集成应优先绑定 `org.apache.cassandra.metrics:*` ObjectName 和 JMX wrapper attribute，而不是 Java 字段名。
- `system_views` virtual tables 更适合 CQL/人工排障和有限字段巡检；Prometheus/Grafana 类长期采集通常应走 JMX/exporter 并明确单位转换。
- 普通日志、audit log、FQL 和 `system_views.system_logs` 是不同数据面。`system_logs` 是 bounded memory buffer，audit/FQL 是可能包含敏感 payload 的持久/二进制日志。
- 当前仓库没有 dashboard、alert、exporter、collector 配置时，研究文档只能证明 Cassandra 暴露了哪些字段和文件，不能证明生产观测策略完整。
- 若后续仓库引入 source-owned Prometheus/Grafana/Alertmanager/Filebeat/Fluent Bit/Vector/Logstash/Promtail 配置，必须把配置文件、字段映射、阈值和保留策略补入本矩阵。

## 当前缺口

- `external_observability_prometheus_exporter_gap`：缺 source-owned exporter/scrape/collector 配置与 JMX ObjectName allowlist。
- `external_observability_grafana_dashboard_gap`：缺 dashboard panel 到 JMX/virtual table 字段的文件级对照。
- `external_observability_alert_rules_gap`：缺告警规则、阈值、持续时间和 runbook link 的版本化配置。
- `external_observability_log_collector_gap`：缺日志采集器、保留、脱敏和权限配置文件级对照。
