# Nodetool TableHistograms Observability Matrix

This matrix covers `nodetool tablehistograms`, the table-local histogram command. It complements `proxyhistograms`: `proxyhistograms` reads coordinator-side `ClientRequest` timers, while `tablehistograms` reads per-table metrics and SSTable-derived estimated histograms from `ColumnFamilyStore` / `TableMetrics`.

## Source Contract

| Scenario | Contract | Source anchors | Operational meaning |
| --- | --- | --- | --- |
| `tablehistograms_command_surface_contract` | `TableHistograms` is registered by `NodeTool` and exposes `@Command(name = "tablehistograms")` with only optional positional arguments: no local options beyond global nodetool/JMX options. | `src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:43`、`src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:46`、`src/java/org/apache/cassandra/tools/NodeTool.java:235` | Output is fixed text; there is no JSON/YAML format switch on this command. |
| `tablehistograms_table_selection_contract` | Arguments can be empty, `<keyspace.table>`, or `<keyspace> <table>`. Empty arguments enumerate all CFS MBeans via `getColumnFamilyStoreMBeanProxies()`, and all requested tables are validated against that MBean inventory. | `src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:53`、`src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:57`、`src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:64`、`src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:73`、`src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:83`、`src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:179` | The no-arg mode can be expensive on large schemas because it reads metrics for every table exposed over JMX. |
| `tablehistograms_metric_source_contract` | The command reads `EstimatedPartitionSizeHistogram`, `EstimatedColumnCountHistogram`, `ReadLatency`, `WriteLatency` and `SSTablesPerReadHistogram` through `NodeProbe.getColumnFamilyMetric(keyspace, table, metricName)`. | `src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:98`、`src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:99`、`src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:154`、`src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:155`、`src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:156` | These are local table metrics on the contacted node, not cluster-wide percentiles. |
| `tablehistograms_estimated_histogram_contract` | Partition size and cell count come from long-array gauges and are wrapped in `EstimatedHistogram`; empty arrays print a no-SSTable warning and produce `NaN`, overflowed histograms print an overflow warning and set affected percentiles to `NaN`. | `src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:106`、`src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:118`、`src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:121`、`src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:133`、`src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:145` | Partition/cell histograms are approximate SSTable metadata; they do not include live memtable-only data. |
| `tablehistograms_percentile_order_contract` | Percentile rows are fixed to `50%`, `75%`, `95%`, `98%`, `99%`, `Min`, `Max`; timers and histograms use the same seven-value order from `NodeProbe.metricPercentilesAsArray()`. | `src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:104`、`src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:153`、`src/java/org/apache/cassandra/tools/NodeProbe.java:2216`、`src/java/org/apache/cassandra/tools/NodeProbe.java:2227` | Script parsers should not assume a `999th` output row even though the JMX MBean exposes `get999thPercentile()`. |
| `tablehistograms_output_column_contract` | The table prints `<keyspace>/<table> histograms`, then columns `Percentile`, `Read Latency`, `Write Latency`, `SSTables`, `Partition Size`, `Cell Count`; read/write units are micros and partition size is bytes. | `src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:158`、`src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:159`、`src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java:161`、`test/unit/org/apache/cassandra/tools/nodetool/TableHistogramsTest.java:41` | `Read Latency` / `Write Latency` here are table-local latency metrics, distinct from coordinator `ClientRequest` latency. |
| `tablehistograms_nodeprobe_jmx_contract` | `NodeProbe.getColumnFamilyMetric()` maps table metrics to `org.apache.cassandra.metrics:type=Table,keyspace=<ks>,scope=<table>,name=<metric>` and returns gauge values, timer MBeans or histogram MBeans depending on metric name. Index tables use `type=IndexTable`. | `src/java/org/apache/cassandra/tools/NodeProbe.java:1972`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1979`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1999`、`src/java/org/apache/cassandra/tools/NodeProbe.java:2029`、`src/java/org/apache/cassandra/tools/NodeProbe.java:2034` | Exporters and JMX scripts need the same ObjectName/type split; wrong metric type leads to proxy/class-cast failures. |
| `tablehistograms_tablemetrics_definition_contract` | `TableMetrics` defines the exact sources: estimated partition/cell gauges combine canonical SSTable histograms, `SSTablesPerReadHistogram` is a table histogram, and read/write latencies are `LatencyMetrics("Read")` / `LatencyMetrics("Write")`. | `src/java/org/apache/cassandra/metrics/TableMetrics.java:104`、`src/java/org/apache/cassandra/metrics/TableMetrics.java:110`、`src/java/org/apache/cassandra/metrics/TableMetrics.java:533`、`src/java/org/apache/cassandra/metrics/TableMetrics.java:550`、`src/java/org/apache/cassandra/metrics/TableMetrics.java:554`、`src/java/org/apache/cassandra/metrics/TableMetrics.java:628` | Histograms reflect canonical SSTables and live query history; compaction, flush and workload shape can change values quickly. |
| `tablehistograms_jmx_percentile_mbean_contract` | `CassandraMetricsRegistry.JmxHistogramMBean` and `JmxTimerMBean` expose 50/75/95/98/99/999 percentiles plus min/max, while `tablehistograms` intentionally consumes only 50/75/95/98/99/min/max. | `src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:341`、`src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:353`、`src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:589`、`src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:599` | JMX has a wider attribute surface than the nodetool text view; dashboards can include p999 even though this command does not. |
| `tablehistograms_existing_test_baseline` | `TableHistogramsTest` verifies help text, no-arg all-table output, `<ks.table>` and `<ks> <table>` formats, and bad-argument errors. Metric primitives are covered by `ColumnFamilyMetricTest`, `EstimatedHistogramTest` and decaying histogram tests. | `test/unit/org/apache/cassandra/tools/nodetool/TableHistogramsTest.java:55`、`test/unit/org/apache/cassandra/tools/nodetool/TableHistogramsTest.java:105`、`test/unit/org/apache/cassandra/tools/nodetool/TableHistogramsTest.java:118`、`test/unit/org/apache/cassandra/tools/nodetool/TableHistogramsTest.java:134`、`test/unit/org/apache/cassandra/db/ColumnFamilyMetricTest.java:145`、`test/unit/org/apache/cassandra/utils/EstimatedHistogramTest.java:115`、`test/unit/org/apache/cassandra/metrics/DecayingEstimatedHistogramReservoirTest.java:335` | Existing tests prove command formatting and argument behavior, but do not inject non-empty histograms to assert exact percentile values. |

## Call Graph

```text
nodetool tablehistograms [<ks> <table> | <ks.table>]
  -> TableHistograms.execute(NodeProbe)
  -> NodeProbe.getColumnFamilyStoreMBeanProxies()
  -> validate requested tables against ColumnFamilyStoreMBean.getTableName()
  -> NodeProbe.getColumnFamilyMetric(ks, table, "EstimatedPartitionSizeHistogram")
  -> NodeProbe.getColumnFamilyMetric(ks, table, "EstimatedColumnCountHistogram")
  -> EstimatedHistogram(long[]).percentile/min/max
  -> NodeProbe.getColumnFamilyMetric(ks, table, "ReadLatency") as JmxTimerMBean
  -> NodeProbe.getColumnFamilyMetric(ks, table, "WriteLatency") as JmxTimerMBean
  -> NodeProbe.getColumnFamilyMetric(ks, table, "SSTablesPerReadHistogram") as JmxHistogramMBean
  -> NodeProbe.metricPercentilesAsArray(...)
  -> fixed text table with seven rows
```

## Field Mapping

| Output column | Source metric | Metric type | Notes |
| --- | --- | --- | --- |
| `Read Latency` | `ReadLatency` | `JmxTimerMBean` | Local table read latency in micros. |
| `Write Latency` | `WriteLatency` | `JmxTimerMBean` | Local table write latency in micros. |
| `SSTables` | `SSTablesPerReadHistogram` | `JmxHistogramMBean` | SSTables touched per single-partition read. |
| `Partition Size` | `EstimatedPartitionSizeHistogram` | `Gauge<long[]>` -> `EstimatedHistogram` | Approximate SSTable partition size in bytes. |
| `Cell Count` | `EstimatedColumnCountHistogram` | `Gauge<long[]>` -> `EstimatedHistogram` | Approximate cells per partition from SSTable metadata. |

## Tests And Gaps

- `TableHistogramsTest.testMaybeChangeDocs()` protects help output and argument synopsis.
- `TableHistogramsTest.testWithNoTableSpecified()` checks all system keyspaces and verifies one header per known table.
- `TableHistogramsTest.testWithOneTableSpecified()` checks both `system.local` and `system local` formats.
- `TableHistogramsTest.testWithMoreThanOneTableSpecified()` protects invalid multi-table argument handling.
- Remaining gap: add a focused test that creates reads/writes/SSTables and verifies non-empty percentile rows, empty-SSTable warning and overflow warning behavior.
