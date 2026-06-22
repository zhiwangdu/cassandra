# Module: Dynamic Snitch Topology Regression

## 范围

本文补齐 consistency/replication 中 dynamic snitch topology-change 自动回归缺口。范围包括 `DynamicEndpointSnitch` 的 latency score、badness threshold、gossip severity、decommission severity 注入、remote write forwarding severity filter、batchlog dynamic endpoint selection、JMX/MBean 观测和 runtime `updateSnitch` 配置更新。它不重新展开 snitch 的 DC/rack 发现逻辑；基础 snitch、preferred IP 与 gossip lifecycle 已在 `research/module-gossip-messaging-deep-dive.md` 覆盖。

## 设计目标

- 用 `DynamicEndpointSnitch.sortedByProximity()` 的两个分支定义可回归的排序 contract：`dynamic_snitch_badness_threshold=0` 时使用纯 score order，非 0 时先保留 subsnitch order，只有 score 偏差超过阈值才切换到 score order，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:175-228`。
- 把 decommission severity 放进 read/write 避让模型：`StorageService.startLeaving()` 在 gossip leaving 状态前注入 `severity_during_decommission`，见 `src/java/org/apache/cassandra/service/StorageService.java:5289-5295`；score 计算把 severity 加进 latency ratio，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:313-323`。
- 保证 topology change 下 leaving endpoint 不被读写关键路径优先选中。decommission dtest 配置 `severity_during_decommission=10000D` 与 `dynamic_snitch_badness_threshold=0`，等待 severity gossip 后强制 `updateScores()`，见 `test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidTimeouts.java:80-112`。
- 将 source-only regression 固化为 `research/tools/check-dynamic-snitch-topology-drift.py`，让 source、测试和 research 场景矩阵同步漂移时立即失败。

## 解决的问题

dynamic snitch 排序通常被当成“读延迟优化”，但 topology change 时它还承担避免 coordinator 继续优先联系 leaving/decommissioning endpoint 的职责。这个职责横跨配置、gossip severity、latency score、ReplicaPlans、StorageProxy forwarding、batchlog endpoint strategy 和 JMX 观测。若只测试普通 score order，容易漏掉以下回归：

| 场景 ID | 回归点 | 源码/测试证据 |
|---|---|---|
| `score_order_zero_threshold` | `dynamic_snitch_badness_threshold=0` 必须直接按 score 排序。 | `DynamicEndpointSnitch.sortedByProximity()` 在 threshold 为 0 时调用 `sortedByProximityWithScore()`，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:175-190`。 |
| `badness_threshold_preserves_subsnitch` | 默认 threshold 保留基础 snitch 的 rack/DC/cache locality，只有分数差超过 `1.0 + dynamicBadnessThreshold` 才改用 score order。 | badness 分支和公式见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:193-228`；CASSANDRA-6683 score-diff 单测见 `test/unit/org/apache/cassandra/locator/DynamicEndpointSnitchTest.java:104-112`。 |
| `decommission_severity_gossip` | decommission 开始时 severity 先写 gossip，再进入 leaving state，其他节点必须能读到 `ApplicationState.SEVERITY`。 | 注入点见 `src/java/org/apache/cassandra/service/StorageService.java:5289-5295`；gossip state 读写见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:378-395`；dtest 等待 severity match 见 `test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidTimeouts.java:108-112`。 |
| `decommission_read_write_trace_regression` | read/write 在 leaving endpoint severity 非零后不能继续向该 endpoint 发送 mutation/data/digest 并导致 timeout。 | dtest 捕获 trace 中 `Sending mutation to remote replica`、`reading data from`、`reading digest from` 并过滤 decommissioning endpoint，见 `test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidTimeouts.java:120-162`。 |
| `remote_write_forwarding_severity_filter` | cross-DC write forwarding 选择 remote replica 时先过滤 severity 非零 endpoint。 | `StorageProxy.pickReplica()` 只从 `DynamicEndpointSnitch.getSeverity(endpoint) == 0` 的 healthy set 选，空集才回退，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1637-1641`。 |
| `batchlog_dynamic_snitch_selection` | `batchlog_endpoint_strategy=dynamic` / `dynamic_remote` 只在 dynamic snitch 启用时按 proximity score 选择 batchlog endpoint，并保留 rack 分散。 | config enum 和 fallback 注释见 `src/java/org/apache/cassandra/config/Config.java:1290-1322`；`ReplicaPlans.filterBatchlogEndpoints()` 分支见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:279-288`；dynamic selection 见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:392-429`；单测见 `test/unit/org/apache/cassandra/batchlog/BatchlogEndpointFilterTest.java:742-921`。 |
| `jmx_dynamic_endpoint_snitch_observability` | 运维必须能通过 MBean/JMX 看到 scores、interval、badness、subsnitch、severity。 | MBean 注册名见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:85-113`；接口见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitchMBean.java:25-61`；NodeProbe proxy 见 `src/java/org/apache/cassandra/tools/NodeProbe.java:1186-1191`。 |
| `runtime_update_snitch_config` | JMX/StorageService 更新 dynamic interval/reset/badness 或替换 snitch 后，现有 replication strategies 必须引用新 snitch 或应用 config changes。 | `StorageService.updateSnitch()` 设置 config、关闭旧 MBean、创建新 snitch、刷新 keyspace strategy snitch，并调用 `applyConfigChanges()`，见 `src/java/org/apache/cassandra/service/StorageService.java:6294-6356`。 |

## 设计取舍

- score order 与 badness threshold 是两个不同 contract。threshold 为 0 适合 topology-change/decommission 回归，因为 severity 会把 leaving endpoint 推到最后；默认 1.0 更偏向稳定性和 cache locality，见 `conf/cassandra.yaml:1566-1573`。
- severity 被放到 gossip `ApplicationState.SEVERITY`，不是本地-only flag。这样 coordinator 可以在自己的 `DynamicEndpointSnitch.getSeverity(endpoint)` 中看到远端 decommissioning 状态，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:378-395`。
- `USE_SEVERITY` 受 `cassandra.ignore_dynamic_snitch_severity` 控制，源码默认使用 severity，见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:274`、`src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:53`。
- `DecommissionAvoidTimeouts` 用 ByteBuddy 拦截 `sortedByProximity()`，直接断言 severity 非零的 decommissioning endpoint 必须排最后；这是比只检查最终请求成功更强的 topology regression，见 `test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidTimeouts.java:185-223`。
- batchlog dynamic strategy 明确说明 dynamic snitch 只跟踪 reads，不跟踪 writes；write-only workload 未必受益，见 `src/java/org/apache/cassandra/config/Config.java:1297-1300`、`src/java/org/apache/cassandra/config/Config.java:1311-1314`。

## 核心类

| 类 | 作用 |
|---|---|
| `DynamicEndpointSnitch` | 包装基础 `IEndpointSnitch`，接收 messaging latency sample，周期性计算 score，并按 score/badness threshold 排序 replicas，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:51-60`、`src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:268-323`。 |
| `DynamicEndpointSnitchMBean` | 暴露 scores、interval、badness、subsnitch、timings 和 severity 操作面，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitchMBean.java:25-61`。 |
| `DatabaseDescriptor` | 读取 `dynamic_snitch` config 并决定是否包装 dynamic snitch；提供 interval/reset/badness getter/setter 和 decommission severity getter，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1438-1444`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1665-1670`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3622-3647`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:5246-5250`。 |
| `StorageService` | decommission 时注入 severity，并通过 JMX 路径更新或替换 snitch，见 `src/java/org/apache/cassandra/service/StorageService.java:5289-5295`、`src/java/org/apache/cassandra/service/StorageService.java:6273-6356`。 |
| `StorageProxy` | remote write forwarding 选择目标时过滤 severity 非零 replica，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1637-1641`。 |
| `ReplicaPlans` | batchlog endpoint selection 在 dynamic strategy 且 current snitch 是 dynamic 时使用 score order，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:279-288`、`src/java/org/apache/cassandra/locator/ReplicaPlans.java:392-429`。 |

## 核心接口

- `DynamicEndpointSnitch.receiveTiming()`：作为 `LatencySubscribers.Subscriber` 接收 endpoint latency sample，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:268-279`。
- `DynamicEndpointSnitch.updateScores()`：订阅 messaging latency、取 median/max ratio、叠加 severity 并替换 immutable score snapshot，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:281-323`。
- `DynamicEndpointSnitch.sortedByProximity()`：read/range/batchlog proximity 的入口，按 threshold 选择 score 或 badness 分支，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:175-180`。
- `DynamicEndpointSnitch.addSeverity()` / `getSeverity()`：通过 `ApplicationState.SEVERITY` 发布和读取 severity，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:378-395`。
- `StorageService.updateSnitch()`：动态更新 endpoint snitch class、dynamic flag、interval、reset 和 badness threshold，见 `src/java/org/apache/cassandra/service/StorageService.java:6294-6356`。
- `NodeProbe.getDynamicEndpointSnitchInfoProxy()`：nodetool/JMX client 获取 `org.apache.cassandra.db:type=DynamicEndpointSnitch` proxy，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:1186-1191`。

## 核心数据结构

- `scores`：`HashMap<InetAddressAndPort, Double>` 的 volatile snapshot，排序时复制引用以保证 comparator 稳定，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:69`、`src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:183-190`。
- `samples`：endpoint 到 `ExponentiallyDecayingReservoir` 的 latency reservoir，窗口大小和 alpha 定义见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:55-70`。
- `dynamicUpdateInterval` / `dynamicResetInterval` / `dynamicBadnessThreshold`：来自 `DatabaseDescriptor` 的 runtime config snapshot，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:58-60`。
- `ApplicationState.SEVERITY`：gossip application state，存储 severity `VersionedValue`，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:378-395`。
- `Config.BatchlogEndpointStrategy`：`useDynamicSnitchScores` 和 `preferLocalRack` 两个布尔位决定 batchlog endpoint selection 行为，见 `src/java/org/apache/cassandra/config/Config.java:1318-1334`。

## 生命周期

启动和配置：

```text
cassandra.yaml endpoint_snitch + dynamic_snitch
  -> DatabaseDescriptor.applySnitch()
  -> createEndpointSnitch(dynamic, class)
  -> DynamicEndpointSnitch wraps subsnitch when enabled
  -> schedules update/reset and registers MBean after daemon init
```

score 更新：

```text
MessagingService latency callback
  -> DynamicEndpointSnitch.receiveTiming(endpoint, latency)
  -> scheduled updateScores()
  -> median latency / max latency
  -> optional getSeverity(endpoint)
  -> volatile scores snapshot
```

topology change / decommission：

```text
nodetool decommission
  -> StorageService.decommission()
  -> startLeaving()
  -> getSeverityDuringDecommission().ifPresent(DynamicEndpointSnitch::addSeverity)
  -> gossip ApplicationState.SEVERITY and leaving status
  -> other nodes updateScores()
  -> sortedByProximity() pushes decommissioning endpoint later
  -> read/write trace should not target leaving endpoint first
```

runtime config update：

```text
JMX StorageService.updateSnitch(...)
  -> set dynamic update/reset/badness config in DatabaseDescriptor
  -> optional close old DynamicEndpointSnitch MBean
  -> optional create new snitch and refresh keyspace replication strategy snitch
  -> otherwise DynamicEndpointSnitch.applyConfigChanges()
  -> updateTopology()
```

## 调用链

- Read/range/batchlog ordering: `ReplicaPlans.sortByProximity()` or snitch consumer -> `DatabaseDescriptor.getEndpointSnitch()` -> `DynamicEndpointSnitch.sortedByProximity()` -> `sortedByProximityWithScore()` or `sortedByProximityWithBadness()` -> `compareEndpoints()` fallback to subsnitch on equal scores，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:175-257`。
- Decommission severity path: `StorageService.decommission()` -> `startLeaving()` -> `DynamicEndpointSnitch.addSeverity()` -> `Gossiper.addLocalApplicationState(ApplicationState.SEVERITY, ...)` -> peer `getSeverity(endpoint)` -> score update，见 `src/java/org/apache/cassandra/service/StorageService.java:5291`、`src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:378-395`。
- Remote write forwarding path: cross-DC forwarded write -> `StorageProxy.pickReplica()` -> filter severity zero endpoints -> random among healthy or fallback target set，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1637-1641`。
- Batchlog dynamic path: `ReplicaPlans.filterBatchlogEndpoints()` -> `DatabaseDescriptor.getBatchlogEndpointStrategy().useDynamicSnitchScores` and `DatabaseDescriptor.isDynamicEndpointSnitch()` -> `filterBatchlogEndpointsDynamic()` -> `sortByProximity()` -> pick two rack-diverse endpoints，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:279-288`、`src/java/org/apache/cassandra/locator/ReplicaPlans.java:392-429`。

## 配置项

| 配置项 | 默认/位置 | 作用 |
|---|---|---|
| `endpoint_snitch` | `Config.endpoint_snitch`，YAML default `SimpleSnitch`，见 `src/java/org/apache/cassandra/config/Config.java:423`、`conf/cassandra.yaml:1556` | 基础 snitch class。 |
| `dynamic_snitch` | `true`，见 `src/java/org/apache/cassandra/config/Config.java:424` | 是否用 `DynamicEndpointSnitch` 包装基础 snitch。 |
| `dynamic_snitch_update_interval` | `100ms`，见 `src/java/org/apache/cassandra/config/Config.java:425-426`、`conf/cassandra.yaml:1558-1561` | score 计算周期。 |
| `dynamic_snitch_reset_interval` | `10m` / YAML `600000ms`，见 `src/java/org/apache/cassandra/config/Config.java:427-428`、`conf/cassandra.yaml:1562-1565` | 清空 samples，让曾经变差的 host 有恢复机会。 |
| `dynamic_snitch_badness_threshold` | `1.0`，见 `src/java/org/apache/cassandra/config/Config.java:429`、`conf/cassandra.yaml:1566-1573` | 控制何时从 subsnitch order 切换到 score order；0 表示纯 score order。 |
| `severity_during_decommission` | `0`，见 `src/java/org/apache/cassandra/config/Config.java:1378` | 大于 0 时 decommission leaving 前注入 gossip severity，getter 见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:5246-5250`。 |
| `batchlog_endpoint_strategy` | `random_remote` / latest YAML `dynamic_remote`，见 `src/java/org/apache/cassandra/config/Config.java:442`、`conf/cassandra_latest.yaml:186` | `dynamic`/`dynamic_remote` 会使用 dynamic snitch score，未启用 dynamic snitch 时 fallback。 |

## Metrics

- Dynamic snitch 没有单独 Dropwizard metric；主要 runtime 观测是 MBean scores、interval、reset、badness、subsnitch 和 severity，getter 见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:331-356`、`src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:397-399`。
- decommission 避让的用户可见信号是 read/write timeout、trace activity 和 leaving endpoint 是否仍出现在 early replica order。dtest 明确收集 timeout trace 并检查 decommissioning endpoint，见 `test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidTimeouts.java:120-162`。
- batchlog dynamic strategy 的效果可通过 batchlog endpoint test 和 coordinator trace 间接验证；source path 在 `ReplicaPlans.filterBatchlogEndpointsDynamic()`，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:392-429`。

## 日志

- `StorageService.updateSnitch()` 对新 dynamic/non-dynamic snitch 和应用 config change 都记录 info，包括 update interval、reset interval 和 badness threshold，见 `src/java/org/apache/cassandra/service/StorageService.java:6325-6352`。
- decommission dtest 不是依赖日志，而是依赖 trace activity 与 ByteBuddy order assertion。trace 过滤内容见 `test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidTimeouts.java:139-151`。
- `DynamicEndpointSnitch.dumpTimings()` 可作为 JMX 侧排查某 endpoint sample 的辅助入口，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:359-370`。

## 运维关注点

- `dynamic_snitch_badness_threshold=0` 适合验证 severity 避让是否生效，但长期生产设置过低会更频繁放弃 rack/DC/cache locality。
- `severity_during_decommission` 默认为 0；如果希望 decommission 期间强制避让 leaving endpoint，需要显式设置大于 0 的值，并确认 `cassandra.ignore_dynamic_snitch_severity` 未禁用 severity。
- write-heavy workload 可能没有足够 read latency samples；batchlog dynamic strategy 对此在配置注释中已明确提示，见 `conf/cassandra.yaml:170-181`。
- JMX 看到的 `Scores` 是带端口和不带端口两个接口；多端口同 IP 测试下旧 `Scores` getter 被 JMX getter test 忽略，见 `test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java:45-48`。
- 更新 snitch class 时要注意旧 dynamic snitch MBean 先关闭，新 snitch 构造时注册 MBean；源码顺序见 `src/java/org/apache/cassandra/service/StorageService.java:6304-6319`。

## 性能瓶颈

- `updateScores()` 被注释为 expensive，并周期性读取所有 samples 的 snapshot；interval 太低会提高后台调度成本，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:281-323`。
- `sortedByProximityWithBadness()` 会先调用 subsnitch 排序，再复制 score list 并排序进行 positional comparison；replica 数通常较小，但 batchlog dynamic 会对 validated endpoints 全量排序，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:193-228`、`src/java/org/apache/cassandra/locator/ReplicaPlans.java:403-405`。
- reset interval 过长会让坏 score 更久影响 routing；reset interval 过短会让样本不足时更依赖 severity/default score，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:98-105`。

## 常见故障

- decommission 后请求仍打到 leaving endpoint：检查 `severity_during_decommission` 是否大于 0、gossip `ApplicationState.SEVERITY` 是否传播、`updateScores()` 是否执行、`dynamic_snitch_badness_threshold` 是否允许 severity 改写排序，dtest 步骤见 `test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidTimeouts.java:106-118`。
- MBean `Scores` 缺失或冲突：检查 dynamic snitch 是否启用，以及 `updateSnitch()` 是否先关闭旧 dynamic MBean；注册/关闭见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:145-155`。
- batchlog dynamic strategy 看起来随机：如果 `DatabaseDescriptor.isDynamicEndpointSnitch()` 为 false，`ReplicaPlans.filterBatchlogEndpoints()` 会走 random 分支，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:279-288`。
- score order 和 rack locality 预期冲突：默认 threshold 的目标是避免轻微 latency 差就打散基础 snitch 顺序；只有 score 差距超过 threshold 才改写，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:211-228`。

## 测试用例

- `test/unit/org/apache/cassandra/locator/DynamicEndpointSnitchTest.java`：构造 `SimpleSnitch` wrapper，设置 badness threshold 0.1，覆盖 equal score、单 host worse、多 host worse、CASSANDRA-6683 score-diff 和 host4 default ordering，见 `test/unit/org/apache/cassandra/locator/DynamicEndpointSnitchTest.java:64-118`。
- `test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidTimeouts.java`：8 节点、2 DC/rack，配置 decommission severity 和 threshold 0，等待 severity gossip，强制 update score，drop gossip digest SYN，让 leave 继续，再用 traced read/write CL 矩阵检查没有向 decommissioning endpoint 触发 timeout，见 `test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidTimeouts.java:77-162`。
- `test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidReadTimeoutsTest.java` 与 `DecommissionAvoidWriteTimeoutsTest.java`：分别提供 SELECT 和 INSERT query，见 `test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidReadTimeoutsTest.java:21-27`、`test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidWriteTimeoutsTest.java:21-27`。
- `test/unit/org/apache/cassandra/batchlog/BatchlogEndpointFilterTest.java`：覆盖 `dynamic` 与 `dynamic_remote` 策略在本地 rack、非本地 rack 下选择最快 host，并用 `dsnitch.receiveTiming()` + `dsnitch.updateScores()` 构造 score，见 `test/unit/org/apache/cassandra/batchlog/BatchlogEndpointFilterTest.java:742-921`。
- `test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java`：JMX getter scan 中显式记录 `DynamicEndpointSnitch:Scores` 多端口模式例外，证明 MBean surface 是 JMX 覆盖面的一部分，见 `test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java:45-48`。

## Drift 检查

- `research/tools/check-dynamic-snitch-topology-drift.py` 验证 dynamic snitch ordering、severity、config、JMX、StorageService update, StorageProxy forwarding、batchlog dynamic strategy 和关键测试源码仍存在，并要求本文覆盖所有 scenario IDs。
- 设计与运行方式见 `research/module-dynamic-snitch-drift-checker.md`。
