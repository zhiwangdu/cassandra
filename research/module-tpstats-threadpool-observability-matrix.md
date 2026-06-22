# Tpstats ThreadPool Observability Matrix

本矩阵补齐 `nodetool tpstats` 的源码级观测合同。`module-metrics-registry-export-matrix.md` 已覆盖 `ThreadPoolMetrics` 与 `system_views.thread_pools` 的 registry/virtual-table 面；本文件聚焦 nodetool runtime path：`TpStats` command、`TpStatsHolder` JSON/YAML 数据形态、默认 `TpStatsPrinter` 表格输出、`NodeProbe.getThreadPoolMetric()` JMX wrapper 分支，以及 dropped message queue-wait latency。

## Source Contract

| Scenario | Contract | Source anchors | Operational meaning |
| --- | --- | --- | --- |
| `tpstats_command_format_contract` | `tpstats` 只有 `-F` / `--format` 命令本地选项，允许空值、`json`、`yaml`，其他值抛出 `IllegalArgumentException("arguments for -F are json,yaml only.")`。 | `src/java/org/apache/cassandra/tools/nodetool/TpStats.java:28`、`src/java/org/apache/cassandra/tools/nodetool/TpStats.java:31`、`src/java/org/apache/cassandra/tools/nodetool/TpStats.java:39` | 自动化脚本若传错格式会直接失败，不会回落到默认文本输出。 |
| `tpstats_holder_threadpool_map_contract` | JSON/YAML 数据的 `ThreadPools` map 来自 `probe.getThreadPools().entries()`，每个 pool 读取 `ActiveTasks`、`PendingTasks`、`CompletedTasks`、`CurrentlyBlockedTasks`、`TotalBlockedTasks`。 | `src/java/org/apache/cassandra/tools/nodetool/stats/TpStatsHolder.java:40`、`src/java/org/apache/cassandra/tools/nodetool/stats/TpStatsHolder.java:46`、`src/java/org/apache/cassandra/tools/nodetool/stats/TpStatsHolder.java:50` | 机器输出不包含 `MaxPoolSize`、`MaxTasksQueued`、`OldestTaskQueueTime`，即使底层 JMX/virtual table 有这些指标。 |
| `tpstats_holder_dropped_latency_contract` | JSON/YAML 数据包含 `DroppedMessage` 与 `WaitLatencies`；latency 来自 `probe.metricPercentilesAsArray(probe.getMessagingQueueWaitMetrics(key))`，读取失败时忽略该 message type。 | `src/java/org/apache/cassandra/tools/nodetool/stats/TpStatsHolder.java:55`、`src/java/org/apache/cassandra/tools/nodetool/stats/TpStatsHolder.java:61`、`src/java/org/apache/cassandra/tools/nodetool/stats/TpStatsHolder.java:65` | dropped count 和 queue-wait latency 是 best-effort 联合视图；latency 缺失不会让命令失败。 |
| `tpstats_default_printer_contract` | 默认文本输出先打印 `Pool Name Active Pending Completed Blocked All time blocked`，再打印 `Latencies waiting in queue (micros) per dropped message types`，后者列为 `Message type Dropped 50% 95% 99% Max`。 | `src/java/org/apache/cassandra/tools/nodetool/stats/TpStatsPrinter.java:52`、`src/java/org/apache/cassandra/tools/nodetool/stats/TpStatsPrinter.java:55`、`src/java/org/apache/cassandra/tools/nodetool/stats/TpStatsPrinter.java:70`、`src/java/org/apache/cassandra/tools/nodetool/stats/TpStatsPrinter.java:73` | 人读输出隐藏 thread-pool path，只按 pool scope 展示；dropped latency 只显示 50/95/99/max 四个分位。 |
| `tpstats_nodeprobe_threadpool_jmx_contract` | `NodeProbe.getJmxThreadPools()` 查询 `org.apache.cassandra.metrics:type=ThreadPools,*`，用 ObjectName 的 `path` 与 `scope` 构造 multimap。 | `src/java/org/apache/cassandra/tools/NodeProbe.java:1824`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1830`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1836` | `tpstats` 的 pool list 是当前 JMX 注册 surface，不是固定枚举。 |
| `tpstats_nodeprobe_metric_wrapper_contract` | `ActiveTasks`、`PendingTasks`、`CompletedTasks`、`MaxPoolSize` 走 `JmxGaugeMBean.getValue()`；`TotalBlockedTasks`、`CurrentlyBlockedTasks` 走 `JmxCounterMBean.getCount()`；未注册 metric 返回 `N/A`，未知 metric 抛 AssertionError。 | `src/java/org/apache/cassandra/tools/NodeProbe.java:1851`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1860`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1866`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1871` | thread-pool gauges 和 blocked counters 是不同 MBean wrapper 类型；formatter 不应该假定全是 long。 |
| `tpstats_threadpool_metrics_registry_contract` | `ThreadPoolMetrics` 定义并注册 8 个指标：active、pending、completed、currently blocked、total blocked、max pool size、max tasks queued、oldest task queue time；ObjectName 形态为 `type=ThreadPools,path=...,scope=...,name=...`。 | `src/java/org/apache/cassandra/metrics/ThreadPoolMetrics.java:34`、`src/java/org/apache/cassandra/metrics/ThreadPoolMetrics.java:97`、`src/java/org/apache/cassandra/metrics/ThreadPoolMetrics.java:129` | `tpstats` 只消费其中 5 个；完整 thread-pool capacity/queue-age 仍应查 JMX 或 `system_views.thread_pools`。 |
| `tpstats_threadpool_virtual_table_boundary` | `system_views.thread_pools` 从 `Metrics.getThreadPoolMetrics(poolName)` / `Metrics.allThreadPoolMetrics()` 读取 `ThreadPoolMetrics`，输出 active limit、pending、completed、blocked/current/all-time。 | `src/java/org/apache/cassandra/db/virtual/ThreadPoolsTable.java:30`、`src/java/org/apache/cassandra/db/virtual/ThreadPoolsTable.java:61`、`src/java/org/apache/cassandra/db/virtual/ThreadPoolsTable.java:70`、`src/java/org/apache/cassandra/db/virtual/ThreadPoolsTable.java:75` | virtual table 是 CQL 侧快照视图，和 `tpstats` 同源但字段名、可过滤性和输出形态不同。 |
| `tpstats_dropped_message_metrics_contract` | `MessagingMetrics.getDroppedMessages()` 按 `Verb.toString()` 返回 lifetime dropped counts；每 5 秒 `logDroppedMessages()` 输出最近窗口 dropped errors 并调用 `StatusLogger.log()`。 | `src/java/org/apache/cassandra/metrics/MessagingMetrics.java:176`、`src/java/org/apache/cassandra/metrics/MessagingMetrics.java:180`、`src/java/org/apache/cassandra/metrics/MessagingMetrics.java:187` | `tpstats` 的 dropped count 是 lifetime counter；日志窗口和 StatusLogger 是另一个最近窗口视角。 |
| `tpstats_existing_tests_baseline` | `TpStatsTest` 覆盖 help、默认输出、插入后 thread pool 变化、ECHO dropped/message row、JSON/YAML `WaitLatencies`；`ThreadPoolMetricsTest` 覆盖 blocked/current/all-time 指标；`MessagingServiceTest` 覆盖 dropped message metrics。 | `test/unit/org/apache/cassandra/tools/nodetool/TpStatsTest.java:55`、`test/unit/org/apache/cassandra/tools/nodetool/TpStatsTest.java:99`、`test/unit/org/apache/cassandra/tools/nodetool/TpStatsTest.java:142`、`test/unit/org/apache/cassandra/metrics/ThreadPoolMetricsTest.java:36`、`test/unit/org/apache/cassandra/net/MessagingServiceTest.java:155` | 现有测试证明输出基本形状和指标更新，但没有逐 pool/path 的 golden JSON schema。 |

## Output Shape

Default text path:

```text
nodetool tpstats
  -> TpStats.execute()
  -> TpStatsPrinter.DefaultPrinter.print()
  -> probe.getThreadPools()
  -> for each path/scope: get Active/Pending/Completed/CurrentlyBlocked/TotalBlocked
  -> print pool table
  -> probe.getDroppedMessages()
  -> for each message type: getMessagingQueueWaitMetrics() percentiles
  -> print dropped-message queue-wait table
```

JSON/YAML path:

```text
nodetool tpstats -F json|yaml
  -> TpStats.execute()
  -> new TpStatsHolder(probe)
  -> TpStatsHolder.convert2Map()
  -> ThreadPools: pool -> five metrics
  -> DroppedMessage: verb -> dropped count
  -> WaitLatencies: verb -> percentile array
  -> StatsPrinter.JsonPrinter / YamlPrinter
```

## Operational Notes

- `CompletedTasks` is a gauge over executor completed count, while blocked fields are counters. Formatting code should keep treating the values as generic objects.
- A missing thread-pool metric returns `N/A` from `NodeProbe.getThreadPoolMetric()`; this usually means the ObjectName is not registered, not that the pool is healthy.
- Queue-wait latency percentiles are keyed by message type. When metric lookup fails, default output prints `N/A` percentiles and JSON/YAML omits that `WaitLatencies` entry.
- `tpstats` does not expose `MaxTasksQueued` or `OldestTaskQueueTime`; use JMX or `system_views.thread_pools` for capacity and queue-age details.
- The distributed `InternalNodeProbe` explicitly does not support `getThreadPools()` / `getThreadPoolMetric()`, so production `tpstats` evidence comes from JMX-backed unit tests rather than in-JVM nodetool mock tests.

## Tests And Gaps

- `TpStatsTest.testMaybeChangeDocs()` locks help output and `-F`.
- `TpStatsTest.testTpStats()` checks default pool header, dropped latency section, write-induced thread-pool changes, and ECHO message type rows.
- `TpStatsTest.testFormatArg()` checks JSON/YAML validity and presence of `WaitLatencies`.
- `ThreadPoolMetricsTest` verifies no-blocked, blocked and SEP executor metric behavior.
- `MessagingServiceTest` checks dropped message counters through `MessagingMetrics`.
- Remaining gap: no golden JSON/YAML schema test asserts exact `ThreadPools` / `DroppedMessage` / `WaitLatencies` nested keys for a controlled fake `NodeProbe`.
