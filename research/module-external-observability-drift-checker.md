# Module: External Observability Drift Checker

## 目的

`research/tools/check-external-observability-drift.py` 是外部观测集成矩阵的 source/test/doc/gap checker。它把 Cassandra 内置 metrics/JMX/virtual table/logback/audit/FQL/BinLog surface 与当前没有 source-owned exporter/dashboard/alert/log collector 配置的事实固化下来。

## 覆盖范围

- `CassandraMetricsRegistry` 的 Dropwizard -> JMX wrapper、Timer/Histogram/Meter/Counter attribute contract。
- `NodeProbe.get*Metric()` 依赖的 JMX ObjectName 读取面。
- `TableMetricTables`、`CQLMetricsTable`、`BatchMetricsTable`、`ThreadPoolsTable`、`CachesTable` 的 virtual metrics 投影。
- `conf/logback.xml` / `conf/logback-tools.xml` 的 daemon/tools appender 和可选 `CQLLOG`/`AUDIT`/`LogbackMetrics`。
- `VirtualTableAppender` / `LogMessagesTable` 的 `system_views.system_logs` memory window。
- `AuditLogManager`、`FullQueryLogger`、`BinLog` 的 listener、queue、archive、path-conflict 和 retention contract。
- 当前缺口：Prometheus/JMX exporter、OpenTelemetry collector、Grafana dashboard、Alertmanager/alert rules、Filebeat/Fluent Bit/Fluentd/Vector/Logstash/Promtail 配置仍不存在。

## 场景 ID

- `external_observability_jmx_metric_contract`
- `external_observability_nodeprobe_metric_contract`
- `external_observability_virtual_metrics_contract`
- `external_observability_logback_file_contract`
- `external_observability_system_logs_contract`
- `external_observability_audit_fql_contract`
- `external_observability_binlog_retention_contract`
- `external_observability_prometheus_exporter_gap`
- `external_observability_grafana_dashboard_gap`
- `external_observability_alert_rules_gap`
- `external_observability_log_collector_gap`
- `external_observability_existing_tests_baseline`

## 运行方式

```bash
python3 research/tools/check-external-observability-drift.py
```

可选输出 JSON：

```bash
python3 research/tools/check-external-observability-drift.py --json
```

## 失败含义

- source token 失败：metrics/JMX/logging/audit/FQL/BinLog 暴露面发生变化，需要重新审查字段、调用链和运维语义。
- test token 失败：现有测试锚点移动或覆盖范围改变，需要更新 baseline。
- doc token 或 scenario coverage 失败：矩阵、checker 说明、README 或 source-map 没有同步。
- gap scan 失败：仓库出现了 source-owned exporter/dashboard/alert/collector 配置，必须补文件级字段映射、阈值、retention/runbook 对照，而不是放宽 negative scan。

## 维护规则

- 新增外部 metrics 配置时，更新 `external_observability_prometheus_exporter_gap`、JMX ObjectName allowlist、label/cardinality 和 scrape interval 说明。
- 新增 Grafana/alert 配置时，补 panel/query/alert expression 到 Cassandra metric 或 virtual table 字段的映射。
- 新增日志 collector 配置时，补 system/debug/audit/FQL 文件路径、roll/retention、权限、敏感字段处理和 backpressure 说明。
- 只出现文档 prose 不等于配置已存在；checker 主要扫描文件名和可部署 config 内容标记。
