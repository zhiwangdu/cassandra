# ProxyHistograms ClientRequest Observability Matrix

本矩阵补齐 `nodetool proxyhistograms` 的源码级观测合同。它覆盖 coordinator 侧 client request latency timer 的 JMX 读取路径、`ProxyHistograms` 输出列、`NodeProbe.getProxyMetric()` ObjectName 合同、`metricPercentilesAsArray()` percentile 顺序，以及读/写/range/CAS/MV 指标更新点。

## Source Contract

| Scenario | Contract | Source anchors | Operational meaning |
| --- | --- | --- | --- |
| `proxyhistograms_command_surface_contract` | `ProxyHistograms` 是无本地 option 的 `@Command(name = "proxyhistograms")`，描述为 network operations histograms。 | `src/java/org/apache/cassandra/tools/nodetool/ProxyHistograms.java:28`、`src/java/org/apache/cassandra/tools/NodeTool.java:183` | 输出固定为文本表，不能通过 `-F` 取得 JSON/YAML。 |
| `proxyhistograms_percentile_order_contract` | 输出 percentile 顺序固定为 `50%`、`75%`、`95%`、`98%`、`99%`、`Min`、`Max`。 | `src/java/org/apache/cassandra/tools/nodetool/ProxyHistograms.java:36`、`src/java/org/apache/cassandra/tools/NodeProbe.java:2227` | 和 `metricPercentilesAsArray(JmxTimerMBean)` 的数组顺序一一对应；改顺序会影响脚本解析。 |
| `proxyhistograms_metric_scope_contract` | 命令读取 6 个 `ClientRequest` timer scope：`Read`、`Write`、`RangeSlice`、`CASRead`、`CASWrite`、`ViewWrite`。 | `src/java/org/apache/cassandra/tools/nodetool/ProxyHistograms.java:37`、`src/java/org/apache/cassandra/tools/nodetool/ProxyHistograms.java:42`、`src/java/org/apache/cassandra/metrics/ClientRequestsMetricsHolder.java:27` | 这些是 coordinator/request 级 latency，不是每表 `TableMetrics` 或本地 storage scan latency。 |
| `proxyhistograms_output_column_contract` | 表头固定输出 `Read Latency`、`Write Latency`、`Range Latency`、`CAS Read Latency`、`CAS Write Latency`、`View Write Latency`，单位均为 micros。 | `src/java/org/apache/cassandra/tools/nodetool/ProxyHistograms.java:44`、`src/java/org/apache/cassandra/tools/nodetool/ProxyHistograms.java:47` | 该命令展示的是 microsecond percentile snapshot，适合现场粗排障，不是 rate/counter dashboard。 |
| `proxyhistograms_nodeprobe_jmx_contract` | `NodeProbe.getProxyMetric(scope)` 构造 `org.apache.cassandra.metrics:type=ClientRequest,scope=<scope>,name=Latency`，并以 `CassandraMetricsRegistry.JmxTimerMBean` 读取。 | `src/java/org/apache/cassandra/tools/NodeProbe.java:2052`、`src/java/org/apache/cassandra/tools/NodeProbe.java:2057`、`src/java/org/apache/cassandra/metrics/CassandraMetricsRegistry.java:599` | 外部 JMX/exporter 需要同样的 ObjectName；scope 拼写错误会得到不存在的 MBean。 |
| `proxyhistograms_read_write_update_contract` | 普通 write/read coordinator path 在 finally 更新 `writeMetrics.addNano(latency)` / `readMetrics.addNano(latency)`。 | `src/java/org/apache/cassandra/service/StorageProxy.java:953`、`src/java/org/apache/cassandra/service/StorageProxy.java:1995`、`src/java/org/apache/cassandra/service/StorageProxy.java:2053` | `Read`/`Write` latency 包含 coordinator 等待和异常路径 finally 更新，不代表单 replica 本地读写耗时。 |
| `proxyhistograms_range_update_contract` | Range coordinator path 使用 `RangeCommandIterator.rangeMetrics = new ClientRangeRequestMetrics("RangeSlice")`，结束时 `rangeMetrics.addNano(latency)`。 | `src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:64`、`src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:273` | `Range Latency` 对应 range query coordinator lifecycle，和 per-table `rangeLatency`/`coordinatorScanLatency` 需要区分。 |
| `proxyhistograms_cas_update_contract` | CAS write/read 使用 `casWriteMetrics` / `casReadMetrics`，普通 StorageProxy CAS path 和 Paxos path 都会更新 latency。 | `src/java/org/apache/cassandra/service/StorageProxy.java:438`、`src/java/org/apache/cassandra/service/StorageProxy.java:1996`、`src/java/org/apache/cassandra/service/paxos/Paxos.java:815`、`src/java/org/apache/cassandra/service/paxos/Paxos.java:914` | CAS percentiles 包含 Paxos/serial read cost，不能和普通 write/read 直接横向比较。 |
| `proxyhistograms_viewwrite_update_contract` | View write scope 来自 `ViewWriteMetrics("ViewWrite")`，普通 MV mutation path 更新 `viewWriteMetrics.addNano(...)`，视图 replica CL.ONE 完成延迟另有 `ViewWriteLatency`。 | `src/java/org/apache/cassandra/metrics/ViewWriteMetrics.java:27`、`src/java/org/apache/cassandra/service/StorageProxy.java:1111`、`src/java/org/apache/cassandra/service/StorageProxy.java:1439` | `proxyhistograms` 的 `View Write Latency` 是 `ClientRequest/ViewWrite/Latency`，不是 `ViewWriteLatency` timer。 |
| `proxyhistograms_test_gap` | 当前没有直接运行 `nodetool proxyhistograms` 并断言表头/percentiles/scope 的 Java test；相邻 coverage 来自 `ClientRequestMetricsTest`、`ClientRequestRowAndColumnMetricsTest`、Paxos/MV tests 和 JMX getter coverage。 | `research/tools/check-proxyhistograms-clientrequest-drift.py` negative scan、`test/unit/org/apache/cassandra/metrics/ClientRequestMetricsTest.java:169`、`test/unit/org/apache/cassandra/metrics/ClientRequestRowAndColumnMetricsTest.java:65`、`test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java:63` | checker 固定 source/doc 事实，但不证明命令文本输出在 runtime 直接可用。 |

## Call Graph

```text
nodetool proxyhistograms
  -> ProxyHistograms.execute(NodeProbe)
  -> probe.getProxyMetric("Read"|"Write"|"RangeSlice"|"CASRead"|"CASWrite"|"ViewWrite")
  -> JMX ObjectName org.apache.cassandra.metrics:type=ClientRequest,scope=<scope>,name=Latency
  -> JmxTimerMBean percentile/min/max methods
  -> NodeProbe.metricPercentilesAsArray(JmxTimerMBean)
  -> print 7 percentile rows x 6 latency columns
```

## Scope Mapping

| Output column | JMX scope | Update source |
| --- | --- | --- |
| `Read Latency` | `ClientRequest/Read/Latency` | `StorageProxy.readRegular()` and Paxos serial read update `readMetrics` |
| `Write Latency` | `ClientRequest/Write/Latency` | `StorageProxy.mutate()` / counter write / ordinary write update `writeMetrics` |
| `Range Latency` | `ClientRequest/RangeSlice/Latency` | `RangeCommandIterator.rangeMetrics` |
| `CAS Read Latency` | `ClientRequest/CASRead/Latency` | StorageProxy/Paxos CAS read path |
| `CAS Write Latency` | `ClientRequest/CASWrite/Latency` | StorageProxy/Paxos CAS write path |
| `View Write Latency` | `ClientRequest/ViewWrite/Latency` | materialized-view mutation coordinator path |

## Operational Notes

- `proxyhistograms` is a coordinator-level command. For table-local latency, use `tablehistograms`, `tablestats`, table metrics, or `system_views` metric tables.
- `RangeSlice` is the historical JMX scope spelling used by the command; it does not mean storage-engine local slice latency.
- The `View Write Latency` column comes from `ClientRequest/ViewWrite/Latency`. The separate `ViewWriteLatency` timer measures view replica write delay after base mutation and is not printed here.
- A missing or renamed scope usually fails as JMX ObjectName/proxy access, not as a graceful `N/A` like some other nodetool metrics.

## Tests And Gaps

- No direct `ProxyHistogramsTest` or `proxyhistograms` `ToolRunner.invokeNodetool()` coverage exists in this checkout.
- `ClientRequestMetricsTest.testRangeRead()` proves range request metrics update round trips and latency.
- `ClientRequestRowAndColumnMetricsTest` covers native read/write/CAS row/column metrics.
- `JMXGetterCheckTest` iterates readable Cassandra MBeans, giving runtime JMX surface evidence but not command-output evidence.
- Remaining gap: add a focused nodetool test that exercises `proxyhistograms`, asserts the six scope columns and the seven percentile rows, and verifies failure behavior when a scope is absent.
