# Messaging MBean And Netstats Matrix

本矩阵补齐 `MessagingServiceMBean` 的 JMX/nodetool 观测面。`module-messaging-verb-semantics.md` 已保护 `Verb.java` 常量和 send/callback 语义；本文件只关注 MBean 方法、`NodeProbe` 路由、`nodetool netstats` 对 message pool counters 的聚合，以及 with-port 兼容测试基线。

## Source Contract

| Scenario | Contract | Source anchors | Operational meaning |
| --- | --- | --- | --- |
| `messaging_mbean_method_baseline` | `MessagingServiceMBean` 当前暴露 27 个方法：9 个 deprecated host-only pool counters、9 个 with-port pool counters、dropped messages、timeouts、removed backpressure stubs、per-endpoint version 和 TLS reload。 | `src/java/org/apache/cassandra/net/MessagingServiceMBean.java:29`、`src/java/org/apache/cassandra/net/MessagingServiceMBean.java:36`、`src/java/org/apache/cassandra/net/MessagingServiceMBean.java:148` | JMX client、nodetool 和 compatibility dump 都依赖这个接口形状；新增/删除方法必须同步文档和 checker。 |
| `messaging_mbean_registration_contract` | `MessagingServiceMBeanImpl` 使用 `org.apache.cassandra.net:type=MessagingService` 注册 MBean，并在非 test-only 构造时启动 metrics logging。 | `src/java/org/apache/cassandra/net/MessagingServiceMBeanImpl.java:34`、`src/java/org/apache/cassandra/net/MessagingServiceMBeanImpl.java:44`、`src/java/org/apache/cassandra/net/MessagingServiceMBeanImpl.java:50` | 生产默认 JMX surface 和 `JMXTool` / exporter 可见性来自该注册点。 |
| `messaging_mbean_pool_counter_mapping` | Large/Small/Gossip pool 分别映射到 `OutboundConnections.large`、`small`、`urgent`，每个 pool 暴露 pending/completed/dropped，host-only 使用 `toString(false)`，with-port 使用 `toString()`。 | `src/java/org/apache/cassandra/net/MessagingServiceMBeanImpl.java:56`、`src/java/org/apache/cassandra/net/MessagingServiceMBeanImpl.java:137`、`src/java/org/apache/cassandra/net/MessagingServiceMBeanImpl.java:191` | 多端口同 IP 测试和混合版本运维必须优先使用 with-port 方法，避免 host key 合并。 |
| `messaging_mbean_timeout_drop_contract` | Dropped messages 来自 `MessagingMetrics.getDroppedMessages()`；total timeouts 来自 `InternodeOutboundMetrics.totalExpiredCallbacks`；per-host timeouts 来自 outbound connection `expiredCallbacks()`。 | `src/java/org/apache/cassandra/net/MessagingServiceMBeanImpl.java:217`、`src/java/org/apache/cassandra/net/MessagingServiceMBeanImpl.java:223`、`src/java/org/apache/cassandra/net/MessagingServiceMBeanImpl.java:229` | `nodetool tpstats` 和 JMX timeout/drop 排障看到的是 callback expiry 与 dropped-message metrics，不是 socket send timeout。 |
| `messaging_mbean_backpressure_removed_contract` | Backpressure MBean 方法仍在接口中保持兼容，但 `getBackPressurePerHost()` / `setBackPressureEnabled()` 抛出 removed feature，`isBackPressureEnabled()` 返回 false。 | `src/java/org/apache/cassandra/net/MessagingServiceMBean.java:125`、`src/java/org/apache/cassandra/net/MessagingServiceMBeanImpl.java:257`、`test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java:45` | 历史 JMX clients 可能仍看到属性；runtime getter test 明确忽略 `BackPressurePerHost`。 |
| `messaging_mbean_nodeprobe_routes` | `NodeProbe.connect()` 建立 `MessagingServiceMBean` proxy；`getDroppedMessages()`、`reloadSslCerts()` 和 `getMessagingServiceProxy()` 分别把 tpstats、reloadssl/netstats 路由到该 proxy。 | `src/java/org/apache/cassandra/tools/NodeProbe.java:271`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1549`、`src/java/org/apache/cassandra/tools/NodeProbe.java:2348`、`src/java/org/apache/cassandra/tools/NodeProbe.java:2393` | nodetool 不直接访问 `MessagingService` singleton，生产路径走 JMX proxy。 |
| `messaging_netstats_pool_aggregation_contract` | `nodetool netstats` 在非 starting 模式读取 `getLargeMessage*WithPort()`、`getSmallMessage*WithPort()`、`getGossipMessage*WithPort()`，对每个 map values 求和，输出 `Large messages`、`Small messages`、`Gossip messages` 三行。 | `src/java/org/apache/cassandra/tools/nodetool/NetStats.java:76`、`src/java/org/apache/cassandra/tools/nodetool/NetStats.java:80`、`src/java/org/apache/cassandra/tools/nodetool/NetStats.java:91`、`src/java/org/apache/cassandra/tools/nodetool/NetStats.java:122` | `netstats` 是 cluster-wide stream 状态加本节点 internode pool 汇总，不展示 per-peer 明细。 |
| `messaging_mbean_with_port_compatibility_test` | `GossipSettlesTest` 校验 10 个 with-port 方法等于 host-only map 加 storage port；`NetStatsTest` 校验 help、`-H` 和 Gossip messages 输出；`JMXGetterCheckTest` 覆盖默认可读 JMX getters 并跳过 removed backpressure。 | `test/distributed/org/apache/cassandra/distributed/test/GossipSettlesTest.java:100`、`test/unit/org/apache/cassandra/tools/nodetool/NetStatsTest.java:55`、`test/unit/org/apache/cassandra/tools/nodetool/NetStatsTest.java:100`、`test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java:45` | 这些测试证明 with-port 兼容映射、netstats 基本输出和 JMX getter runtime surface，但不等于 TLS reload 端到端测试。 |
| `messaging_mbean_tls_reload_route` | `MessagingServiceMBean.reloadSslCertificates()` 调用 `SSLFactory.forceCheckCertFiles()`；`NodeProbe.reloadSslCerts()` 调用该 MBean proxy。 | `src/java/org/apache/cassandra/net/MessagingServiceMBeanImpl.java:275`、`src/java/org/apache/cassandra/tools/NodeProbe.java:2348`、`research/module-native-tls-reload-coverage-matrix.md` | internode/native TLS reload 的缓存和文件校验在 native TLS reload 矩阵中展开，本矩阵只固定 JMX route。 |

## Method Baseline

| Method | Category | Implementation semantics |
| --- | --- | --- |
| `getLargeMessagePendingTasks` | deprecated host-only pool counter | `OutboundConnections.large.pendingCount()` keyed by `InetAddressAndPort.toString(false)` |
| `getLargeMessagePendingTasksWithPort` | with-port pool counter | `OutboundConnections.large.pendingCount()` keyed by `InetAddressAndPort.toString()` |
| `getLargeMessageCompletedTasks` | deprecated host-only pool counter | `OutboundConnections.large.sentCount()` |
| `getLargeMessageCompletedTasksWithPort` | with-port pool counter | `OutboundConnections.large.sentCount()` |
| `getLargeMessageDroppedTasks` | deprecated host-only pool counter | `OutboundConnections.large.dropped()` |
| `getLargeMessageDroppedTasksWithPort` | with-port pool counter | `OutboundConnections.large.dropped()` |
| `getSmallMessagePendingTasks` | deprecated host-only pool counter | `OutboundConnections.small.pendingCount()` |
| `getSmallMessagePendingTasksWithPort` | with-port pool counter | `OutboundConnections.small.pendingCount()` |
| `getSmallMessageCompletedTasks` | deprecated host-only pool counter | `OutboundConnections.small.sentCount()` |
| `getSmallMessageCompletedTasksWithPort` | with-port pool counter | `OutboundConnections.small.sentCount()` |
| `getSmallMessageDroppedTasks` | deprecated host-only pool counter | `OutboundConnections.small.dropped()` |
| `getSmallMessageDroppedTasksWithPort` | with-port pool counter | `OutboundConnections.small.dropped()` |
| `getGossipMessagePendingTasks` | deprecated host-only pool counter | `OutboundConnections.urgent.pendingCount()` |
| `getGossipMessagePendingTasksWithPort` | with-port pool counter | `OutboundConnections.urgent.pendingCount()` |
| `getGossipMessageCompletedTasks` | deprecated host-only pool counter | `OutboundConnections.urgent.sentCount()` |
| `getGossipMessageCompletedTasksWithPort` | with-port pool counter | `OutboundConnections.urgent.sentCount()` |
| `getGossipMessageDroppedTasks` | deprecated host-only pool counter | `OutboundConnections.urgent.dropped()` |
| `getGossipMessageDroppedTasksWithPort` | with-port pool counter | `OutboundConnections.urgent.dropped()` |
| `getDroppedMessages` | metrics map | `MessagingMetrics.getDroppedMessages()` |
| `getTotalTimeouts` | global timeout counter | `InternodeOutboundMetrics.totalExpiredCallbacks.getCount()` |
| `getTimeoutsPerHost` | deprecated host-only timeout map | `OutboundConnections.expiredCallbacks()` keyed without port |
| `getTimeoutsPerHostWithPort` | with-port timeout map | `OutboundConnections.expiredCallbacks()` keyed with port |
| `getBackPressurePerHost` | removed compatibility attribute | throws `UnsupportedOperationException("This feature has been removed")` |
| `setBackPressureEnabled` | removed compatibility operation | throws `UnsupportedOperationException("This feature has been removed")` |
| `isBackPressureEnabled` | removed compatibility attribute | returns `false` |
| `getVersion` | endpoint messaging version lookup | delegates to `EndpointMessagingVersions.get(address)` |
| `reloadSslCertificates` | TLS reload operation | delegates to `SSLFactory.forceCheckCertFiles()` |

## Netstats Output Contract

```text
nodetool netstats
  -> NetStats.execute(NodeProbe)
  -> probe.getOperationMode()
  -> probe.getStreamStatus()
  -> print streaming sessions
  -> if !probe.isStarting()
       -> print read repair counters
       -> probe.getMessagingServiceProxy()
       -> sum Large messages pending/completed/dropped with-port maps
       -> sum Small messages pending/completed/dropped with-port maps
       -> sum Gossip messages pending/completed/dropped with-port maps
```

`netstats` has one command-local option, `-H` / `--human-readable`, which only changes stream byte formatting. The message pool table is always a node-local aggregate with `Active` rendered as `n/a`.

## Operational Notes

- `Large messages` maps to the large outbound connection, `Small messages` maps to the small outbound connection, and `Gossip messages` maps to the urgent outbound connection. The name keeps older operator wording even though the code path is priority/connection-class based.
- Prefer with-port MBean methods for automation. Host-only methods are deprecated for CASSANDRA-7544 and can collapse peers when multiple nodes share an IP with different storage ports.
- `BackPressurePerHost` is intentionally not a health signal in this branch. The feature was removed; the attribute survives only as compatibility surface and is ignored by `JMXGetterCheckTest`.
- `reloadSslCertificates` is the JMX force hook. Whether files are actually reloaded depends on `SSLFactory` cache keys, factory `shouldReload()` and validation success; those details remain in `module-native-tls-reload-coverage-matrix.md`.

## Tests And Gaps

- `NetStatsTest.testMaybeChangeDocs()` locks the help output for `netstats`, including `-H`.
- `NetStatsTest.testNetStats()` sends an `ECHO_REQ` and asserts the `Gossip messages` row appears.
- `NetStatsTest.testHumanReadable()` checks `-H` only affects stream summary byte rendering.
- `GossipSettlesTest` compares all 10 with-port MBean maps against the deprecated host-only maps plus storage port.
- `JMXGetterCheckTest` reads default Cassandra MBean getters and explicitly skips `org.apache.cassandra.net:type=MessagingService:BackPressurePerHost`.
- Remaining gap: no focused Java test asserts `reloadSslCertificates` through `NodeProbe.reloadSslCerts()` all the way to `SSLFactory.forceCheckCertFiles()`; native TLS reload research tracks this as part of the broader TLS E2E gap.
