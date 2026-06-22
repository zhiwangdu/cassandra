# Module: Metrics Registry Drift Checker

## 目的

`research/tools/check-metrics-registry-drift.py` 固化 Metrics registry/export surface 的源码与文档合同，防止后续修改遗漏：

- `CassandraMetricsRegistry` 的 Dropwizard -> JMX wrapper、timer/histogram reservoir、alias、thread pool registry。
- `DefaultNameFactory` / `MetricNameFactory` / `MetricName` 的 ObjectName 命名规则。
- `TableMetrics` / `KeyspaceMetrics` 的 table、alias、global/keyspace 聚合与 release。
- `ClientRequestsMetricsHolder`、`ClientRequestMetrics`、`ClientRangeRequestMetrics` 的 global、CL scope、local/remote/round-trip 计数。
- `ThreadPoolMetrics`、`CacheMetrics`、`CommitLogMetrics`、`StorageMetrics`、`CompactionMetrics`、`StreamingMetrics` 等代表性全局指标。
- `SystemViewsKeyspace`、`TableMetricTables`、`CQLMetricsTable`、`BatchMetricsTable`、`ThreadPoolsTable`、`CachesTable` 的 virtual table 投影。
- `NodeProbe` metrics getter 的 JMX ObjectName 消费路径。
- 外部 dashboard/alert/exporter 配置仍不存在的 gap baseline。

## 场景 ID

- `metrics_registry_dropwizard_jmx_bridge`
- `metrics_name_objectname_contract`
- `metrics_table_keyspace_lifecycle`
- `metrics_client_request_scope`
- `metrics_threadpool_cache_virtual_tables`
- `metrics_cql_batch_virtual_tables`
- `metrics_nodeprobe_nodetool_consumers`
- `metrics_jvm_logback_bridge`
- `metrics_global_storage_compaction_streaming`
- `metrics_external_dashboard_gap`

## 运行

```bash
python3 research/tools/check-metrics-registry-drift.py
python3 research/tools/check-metrics-registry-drift.py --json
```

检查器只读当前 checkout，不启动 Cassandra，不依赖外部服务。失败时会列出缺失的 source token、doc token 或外部 dashboard/exporter gap 状态变化。若仓库将来引入 source-owned Prometheus/JMX exporter/Grafana/Alertmanager 配置，应更新 `metrics_external_dashboard_gap` 和运维对照，而不是简单放宽 negative scan。

## 维护规则

- 新增 metrics 类型或 JMX wrapper 时，更新 `metrics_registry_dropwizard_jmx_bridge`。
- 改动 ObjectName/type/scope/name 规则时，更新 `metrics_name_objectname_contract`、`NodeProbe` getter 对照和外部 dashboard 字段。
- 新增 `system_views` metrics virtual table 时，更新 `metrics_threadpool_cache_virtual_tables` 或 `metrics_cql_batch_virtual_tables`。
- 删除、改名或新增 deployment dashboard/alert/exporter 配置时，更新 `metrics_external_dashboard_gap`。
