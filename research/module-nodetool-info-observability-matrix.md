# Nodetool Info Observability Matrix

本矩阵补齐 `nodetool info` 的源码级观测合同。`info` 是节点本地健康快照入口，组合了 `StorageServiceMBean`、JVM MXBeans、`EndpointSnitchInfoMBean`、cache/buffer-pool metrics、table metrics 和 bootstrap/decommission 状态；它不是 cluster-wide status，也不替代 `status` / `ring` / `tpstats` / `netstats`。

## Source Contract

| Scenario | Contract | Source anchors | Operational meaning |
| --- | --- | --- | --- |
| `nodetool_info_command_surface_contract` | `Info` 注册为 `@Command(name = "info")`，本地 option 只有 `-T/--tokens` 与 `-O/--out-of-range-ops`。 | `src/java/org/apache/cassandra/tools/nodetool/Info.java:36`、`src/java/org/apache/cassandra/tools/nodetool/Info.java:39`、`src/java/org/apache/cassandra/tools/NodeTool.java:160` | 默认输出单节点快照；token 展开和 invalid-token 计数是显式 opt-in。 |
| `nodetool_info_identity_liveness_contract` | 输出 `ID`、`Gossip active`、`Native Transport active`、`Load`、`Uncompressed load`、`Generation No`，其中 generation 只在 gossip running 时读取，否则显示 `0`。 | `src/java/org/apache/cassandra/tools/nodetool/Info.java:51`、`src/java/org/apache/cassandra/tools/NodeProbe.java:839`、`src/java/org/apache/cassandra/tools/NodeProbe.java:849`、`src/java/org/apache/cassandra/tools/NodeProbe.java:869` | `info` 的 liveness 是当前节点 MBean 视角；`Generation No` 不是系统启动次数。 |
| `nodetool_info_jvm_memory_contract` | `Uptime (seconds)` 来自 `RuntimeMXBean.getUptime()`，heap 来自 `MemoryMXBean.getHeapMemoryUsage()`，off-heap 逐 CFS 汇总 `MemtableOffHeapSize`、`BloomFilterOffHeapMemoryUsed`、`IndexSummaryOffHeapMemoryUsed`、`CompressionMetadataOffHeapMemoryUsed`。 | `src/java/org/apache/cassandra/tools/nodetool/Info.java:65`、`src/java/org/apache/cassandra/tools/nodetool/Info.java:207`、`src/java/org/apache/cassandra/tools/NodeProbe.java:874`、`src/java/org/apache/cassandra/tools/NodeProbe.java:879`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1966` | off-heap 是表级 metric 聚合，不包含所有 native/direct memory。 |
| `nodetool_info_topology_exception_contract` | `Data Center` / `Rack` 通过 `EndpointSnitchInfoMBean`，`Exceptions` 读取 `org.apache.cassandra.metrics:type=Storage,name=Exceptions` counter。 | `src/java/org/apache/cassandra/tools/nodetool/Info.java:85`、`src/java/org/apache/cassandra/tools/nodetool/Info.java:89`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1249`、`src/java/org/apache/cassandra/tools/NodeProbe.java:2212` | DC/rack 取本地 snitch 视图；exceptions 是累计 storage counter，需要结合日志判断原因。 |
| `nodetool_info_cache_contract` | Key/Row/Counter cache 打印 `Entries`、`Size`、`Capacity`、`Hits`、`Requests`、`HitRate` 和 save period；metric ObjectName 为 `org.apache.cassandra.metrics:type=Cache,scope=<Cache>,name=<metric>`。 | `src/java/org/apache/cassandra/tools/nodetool/Info.java:93`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1752`、`src/java/org/apache/cassandra/service/CacheServiceMBean.java:24`、`src/java/org/apache/cassandra/metrics/CacheMetrics.java:65` | cache 命中率是累计 ratio gauge，不是固定时间窗口；save period 来自 CacheService MBean。 |
| `nodetool_info_chunk_network_cache_contract` | Chunk Cache 读取 Cache metrics 的 `Misses`、`Requests`、`HitRate`、`MissLatency`；Network Cache 读取 `BufferPool/networking` 的 `Size`、`OverflowSize`、`Capacity`。两者在 MBean 不存在时静默跳过。 | `src/java/org/apache/cassandra/tools/nodetool/Info.java:126`、`src/java/org/apache/cassandra/tools/nodetool/Info.java:150`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1796`、`src/java/org/apache/cassandra/metrics/ChunkCacheMetrics.java:44`、`src/java/org/apache/cassandra/metrics/BufferPoolMetrics.java:50` | 这些行受配置和版本/feature availability 影响；缺失不一定代表错误。 |
| `nodetool_info_table_metric_contract` | `Percent Repaired` 使用全局 table metric `org.apache.cassandra.metrics:type=Table,name=PercentRepaired`；off-heap 汇总使用每表 metrics。 | `src/java/org/apache/cassandra/tools/nodetool/Info.java:163`、`src/java/org/apache/cassandra/tools/nodetool/Info.java:212`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1966` | `Percent Repaired` 是全局 table metric 快照，不说明某个 keyspace/table 的 repair 状态。 |
| `nodetool_info_token_join_contract` | `info` 先调用 `isJoined()`，未加入 ring 时打印 `(node is not joined to the cluster)`；单 token或 `-T` 打印全部 token，多 token默认提示 `-T/--tokens`。 | `src/java/org/apache/cassandra/tools/nodetool/Info.java:166`、`src/java/org/apache/cassandra/tools/NodeProbe.java:986`、`src/java/org/apache/cassandra/service/StorageService.java:1500` | vnode 节点默认不展开 token，避免输出过长。 |
| `nodetool_info_bootstrap_decommission_contract` | 输出 `Bootstrap state`、`Bootstrap failed`、`Decommissioning`、`Decommission failed`，直接通过 `StorageServiceMBean` 读取。 | `src/java/org/apache/cassandra/tools/nodetool/Info.java:181`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1232`、`src/java/org/apache/cassandra/service/StorageServiceMBean.java:519`、`src/java/org/apache/cassandra/service/StorageService.java:2315`、`src/java/org/apache/cassandra/service/StorageService.java:5812` | `info` 是 bootstrap/decommission 现场排查的轻量入口，但详细流量仍要看 `netstats`、logs 和 system keyspace 状态。 |
| `nodetool_info_out_of_range_ops_contract` | `-O/--out-of-range-ops` 打印每 keyspace invalid token read/write/paxos 计数，数据来自 `StorageServiceMBean.getOutOfRangeOperationCounts()`。 | `src/java/org/apache/cassandra/tools/nodetool/Info.java:187`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1737`、`src/java/org/apache/cassandra/service/StorageService.java:375`、`src/java/org/apache/cassandra/service/StorageService.java:384` | 该输出用于定位错误 token/range 请求，只在出现 out-of-range 操作后有数据。 |
| `nodetool_info_existing_test_baseline` | 当前直接 runtime 覆盖为 `NodeToolTest.testInfoOutput()`，只断言 ID/Gossip/Native/Load/Generation/Uptime/Heap 等表头；JMX getter coverage 保护 MBean 可读面。 | `test/distributed/org/apache/cassandra/distributed/test/NodeToolTest.java:121`、`test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java:63`、`test/unit/org/apache/cassandra/metrics/BufferPoolMetricsTest.java:36` | 仍缺少 `-T`、`-O`、cache/chunk/network cache 行和 bootstrap/decommission 状态的 focused output tests。 |

## Call Graph

```text
nodetool info [-T] [-O]
  -> Info.execute(NodeProbe)
  -> StorageServiceMBean: host id, gossip/native state, load, generation, join/bootstrap/decommission state
  -> RuntimeMXBean / MemoryMXBean: uptime and heap memory
  -> ColumnFamilyStoreMBean proxies + Table metrics: off-heap aggregate and PercentRepaired
  -> EndpointSnitchInfoMBean: local datacenter and rack
  -> Storage metrics JMX counter: Exceptions
  -> CacheServiceMBean + Cache metrics: key/row/counter cache lines
  -> Cache/ChunkCache metrics and BufferPool/networking metrics: optional chunk/network cache lines
  -> optional StorageServiceMBean.getOutOfRangeOperationCounts()
```

## Field Mapping

| Output field | Source | Notes |
| --- | --- | --- |
| `ID` | `StorageServiceMBean.getLocalHostId()` | Host UUID for this node. |
| `Gossip active` | `StorageServiceMBean.isGossipRunning()` | Controls whether generation is read. |
| `Native Transport active` | `StorageServiceMBean.isNativeTransportRunning()` | Native CQL listener state, not client count. |
| `Load` / `Uncompressed load` | `StorageMetrics.load` / `StorageMetrics.uncompressedLoad` via `StorageService` | Human-readable string. |
| `Uptime (seconds)` | `RuntimeMXBean.getUptime()` | JVM uptime, not ring membership duration. |
| `Heap Memory (MB)` | `MemoryMXBean.getHeapMemoryUsage()` | Used/max heap. |
| `Off Heap Memory (MB)` | Sum of CFS metrics | Limited to table-related off-heap components. |
| `Data Center` / `Rack` | `EndpointSnitchInfoMBean` | Local snitch view. |
| `Exceptions` | Storage `Exceptions` counter | Counter only; consult logs for stack traces. |
| `Key Cache` / `Row Cache` / `Counter Cache` | Cache metrics + CacheService save period | Always attempted; each line includes entries, size, capacity, hits, requests, recent hit rate and save period. |
| `Chunk Cache` | Cache metrics + chunk miss latency | Optional line; omitted if the MBean is absent. |
| `Network Cache` | BufferPool `networking` metrics | Optional line. |
| `Token` | `StorageServiceMBean.getTokens()` after `isJoined()` | Vnodes require `-T` to print all. |
| Bootstrap/decommission fields | `StorageServiceMBean` operations | State summary only. |
| `Invalid Token Ops` | `getOutOfRangeOperationCounts()` | Only printed with `-O`. |

## Tests And Gaps

- `NodeToolTest.testInfoOutput()` runs `nodetool info` in an in-JVM cluster and verifies key top-level labels.
- `JMXGetterCheckTest` exercises readable MBean attributes/operations, indirectly protecting the MBean surface used by `NodeProbe`.
- `BufferPoolMetricsTest` and cache metrics tests protect the metric primitives, not `info` formatting.
- Remaining gap: add a focused distributed nodetool test for `info -T`, `info -O`, optional chunk/network cache rows and bootstrap/decommission state transitions.
