# Module: Failure Detector Phi And Conviction Matrix

## 范围

本模块补齐 Failure Detector 的核心算法和下游影响。已有 `module-gossip-messaging.md`、`module-gossip-messaging-deep-dive.md` 和 `module-jmx-nodeprobe-fd-drift-checker.md` 已覆盖 gossip 总览、FD JMX/nodetool route；本页聚焦 `FailureDetector.report()` / `interpret()`、`ArrivalWindow`、本地 pause 抑制、phi 阈值、Gossiper conviction、repair/Paxos cleanup 下游 listener 和 simulator override。

当前源码基线：

- `FailureDetector` 实现 `IFailureDetector` 和 `FailureDetectorMBean`，注册 MBean `org.apache.cassandra.net:type=FailureDetector`。
- 每个 endpoint 维护一个 `ArrivalWindow`，内部是 `ArrayBackedBoundedStats`，样本数固定为 1000。
- 初始 interval 默认 `Gossiper.intervalInMillis * 2`，可用 `cassandra.fd_initial_value_ms` 覆盖。
- arrival interval 超过 `cassandra.fd_max_interval_ms` 或初始 interval 默认值时被忽略，避免长分区后快速适应错误的慢心跳。
- conviction 使用 `PHI_FACTOR * phi > phi_convict_threshold`；这里的 `phi` 是 `tnow - tLast / mean`，`PHI_FACTOR = 1 / ln(10)` 是历史兼容缩放。
- `cassandra.max_local_pause_in_ms` 默认 5000ms，local pause 超过阈值时暂不 mark down，pause 后一个窗口内继续抑制。

## 场景矩阵

| 场景 ID | 源码锚点 | 现有测试 | 运维/故障含义 |
|---|---|---|---|
| `fd_phi_arrival_window_seed` | `SAMPLE_SIZE = 1000`、`INITIAL_VALUE_NANOS`、`ArrivalWindow.add()` 首个样本写入初始 interval，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:72-101`、`:476-527`。 | `FailureDetectorTest.testMaxIntervalCalculation()` 验证 default/max interval 计算，见 `test/unit/org/apache/cassandra/gms/FailureDetectorTest.java:95-124`。 | 初始 interval 偏大是为了避免新 endpoint 心跳不足时误判 down；启动后 FD 会随真实 gossip heartbeat 重学均值。 |
| `fd_report_generation_version_gate` | `Gossiper.notifyFailureDetector()` 只在 remote generation 更大或同 generation 且 heartbeat version 更新时调用 `fd.report(endpoint)`；dead endpoint generation 变化时先 `fd.remove(endpoint)`，见 `src/java/org/apache/cassandra/gms/Gossiper.java:1385-1429`。 | gossip state/preferred-IP checker 已保护 state merge；本页 checker 保护 FD report gate token。 | FD 样本不是每个 gossip message 都入窗，只有可证明的 heartbeat 前进才更新，避免重复旧 state 拉低 phi。 |
| `fd_local_pause_suppression` | `FailureDetector.interpret()` 用 `lastInterpret` 计算本地 pause；超过 `MAX_LOCAL_PAUSE_IN_NANOS` 时 warn 并设置 `lastPause`，随后一个 pause window 内 debug 并返回，见 `FailureDetector.java:335-355`。 | `FailureDetectorTest.setup()` 把 `MAX_LOCAL_PAUSE_IN_MS` 拉到 20000，避免慢单测误触发 pause 防护，见 `FailureDetectorTest.java:50-53`。 | 大 GC pause 或调度停顿后不要把所有 peer 判 down；若日志出现 “Not marking nodes down due to local pause”，排障应先看本机 STW/CPU steal。 |
| `fd_phi_threshold_and_jmx_scale` | `ArrivalWindow.phi()` 保存 `lastReportedPhi = t / mean()`；`interpret()` 使用 `PHI_FACTOR * phi > getPhiConvictThreshold()`；JMX `getPhiValues()` 返回 `phi * PHI_FACTOR`，见 `FailureDetector.java:213-231`、`:356-377`、`:533-538`。 | `module-jmx-nodeprobe-fd-drift-checker.md` 保护 `FailureDetectorMBean.getPhiValues*` 方法面。 | nodetool/JMX 看到的是缩放后的 PHI，与 `phi_convict_threshold` 同尺度；源码回调 listener 收到的是未缩放 `phi`。 |
| `fd_config_limits_and_system_properties` | `Config.phi_convict_threshold = 8.0`；`DatabaseDescriptor` 启动校验范围 5..16；运行时 setter 不重复校验；`FD_INITIAL_VALUE_MS`、`FD_MAX_INTERVAL_MS`、`MAX_LOCAL_PAUSE_IN_MS` 定义在 `CassandraRelevantProperties`，见 `Config.java:177`、`DatabaseDescriptor.java:554-556`、`:2390-2398`、`CassandraRelevantProperties.java:225-226`、`:352`。 | `FailureDetectorTest.testMaxIntervalCalculation()` 验证 `cassandra.fd_max_interval_ms` override；JMX/nodetool route checker 保护 threshold getter/setter。 | 调低阈值会更快下线但更容易因网络尾延迟/GC 误判；运行时 JMX setter 可绕过启动范围校验，操作要谨慎。 |
| `fd_conviction_gossip_stage` | `Gossiper` 构造时注册为 FD listener；`Gossiper.convict()` 用 `runInGossipStageBlocking()` 串行执行，跳过 missing/dead state，然后 `markDead()` 或 `markAsShutdown()` 并发出 diagnostics，见 `Gossiper.java:405-408`、`:600-627`。 | `FailureDetectorTest.testConvictAfterLeft()` 设置 threshold 为 0，证明 LEFT endpoint 的 FD history 不会被清空，`interpret()` 后 endpoint 不再 alive，见 `FailureDetectorTest.java:61-91`。 | FD 本身不改 token metadata；它通知 Gossiper，由 gossip stage 改 endpoint alive/down 并驱动 subscribers。 |
| `fd_shutdown_force_conviction` | shutdown state path 调 `FailureDetector.instance.forceConviction(endpoint)`；`forceConviction()` 直接用 `getPhiConvictThreshold()` 通知 listeners，见 `Gossiper.java:628-675`、`FailureDetector.java:380-386`。 | distributed host replacement/assassinate/system-auth tests 有直接 force/convict 场景；本 checker 保护 shutdown force token。 | 有些 operator/topology path 不等待 phi 自然跨阈值，而是把已知 shutdown/remove 事件同步给 FD listeners。 |
| `fd_downstream_repair_confidence` | `RepairSession` / `ActiveRepairService` 实现 `IFailureDetectionEventListener`，只有 `phi >= 2 * phi_convict_threshold` 才失败 repair；`PaxosCleanupSession` 则直接 kill cleanup session，见 `src/java/org/apache/cassandra/repair/RepairSession.java:413-430`、`src/java/org/apache/cassandra/service/ActiveRepairService.java:1063-1067`、`src/java/org/apache/cassandra/service/paxos/cleanup/PaxosCleanupSession.java:234-237`。 | `RepairSessionTest`、`PaxosRepair2Test`、`RepairCoordinatorNeighbourDown` 等覆盖 FD down 对 repair/Paxos 场景的影响。 | repair 错误失败代价高，所以比 Gossiper conviction 要求更高置信；Paxos cleanup 的 session 生命周期更直接。 |
| `fd_simulator_override` | `SimulatedFailureDetector.Instance` 包装真实 FD，但允许 per-address override，并在 `markDown()` 时把 `Double.MAX_VALUE` conviction 发给 listeners，见 `test/simulator/main/org/apache/cassandra/simulator/systems/SimulatedFailureDetector.java:44-107`。 | simulator topology/repair 测试可用该 override 构造 deterministic down event。 | simulator 不依赖 wall-clock phi 收敛，能稳定测试 FD 下游 reaction；这与生产 FD 算法证据不同。 |
| `fd_observability_and_tests` | JMX `getAllEndpointStates*`、`getSimpleStates*`、`getPhiValues*`、`dumpInterArrivalTimes()` 和 nodetool `failuredetector` 提供观测面，见 `FailureDetector.java:117-286`、`src/java/org/apache/cassandra/tools/NodeProbe.java:2331-2340`。 | `GossipInfoTest`、`JMXGetterCheckTest`、`module-jmx-nodeprobe-fd-drift-checker.md` 覆盖 JMX/nodetool surface；本页补算法/source matrix。 | 排查误判时要把 PHI、inter-arrival dump、endpoint state、local pause 日志和 gossip stage backlog 一起看。 |

## 设计目标

- 用 gossip heartbeat 到达间隔估计 endpoint failure suspicion，而不是依赖 TCP disconnect 或固定超时。
- 避免 GC/STW 或本机调度 pause 导致集群级误判。
- 把 membership state mutation 限定在 Gossiper/gossip stage，FD 只负责 suspicion 和 listener callback。
- 给 repair、Paxos cleanup、simulator 等下游提供统一 failure signal。

## 解决的问题

- 网络长尾和 gossip message loss 不能靠单次 missed heartbeat 判断；FD 用 bounded window 均值让 suspicion 随未收到 heartbeat 的时间增长。
- 长分区恢复后如果把超长 interval 纳入均值，后续真实故障会被掩盖；`FD_MAX_INTERVAL_MS` 防止这种“学坏”。
- 大 GC pause 后本机没有运行 `interpret()`，不能把“本机没调度”误解为“所有 peer down”。
- repair/Paxos cleanup 对 FD 的容忍度不同；统一 listener 模型允许下游自行加阈值或终止策略。

## 设计取舍

- Cassandra 这里保留历史 `PHI_FACTOR = 1 / ln(10)` 缩放，用户已有 `phi_convict_threshold` 调参不用重算。
- `setPhiConvictThreshold()` 运行时不做 5..16 校验；启动校验和 operator discipline 是安全边界。
- `ArrivalWindow` 不是线程安全类，但 `add()` 同步；window 实例存放在 concurrent map，由 FD 单点维护。
- `isAlive(local)` 永远 true，避免本机被 FD 误判；未知 endpoint 记录 error 并返回 false。

## 核心类

| 类/文件 | 作用 |
|---|---|
| `FailureDetector` | FD 主实现、JMX MBean、arrival sample map、listener list、report/interpret/forceConviction，见 `src/java/org/apache/cassandra/gms/FailureDetector.java:64-412`。 |
| `ArrivalWindow` | 每 endpoint 的到达间隔窗口、max interval 截断、phi 计算，见 `FailureDetector.java:461-546`。 |
| `ArrayBackedBoundedStats` | 固定大小 ring buffer，维护均值，见 `FailureDetector.java:421-459`。 |
| `IFailureDetector` | report/interpret/remove/force/listener 注册接口，见 `src/java/org/apache/cassandra/gms/IFailureDetector.java:38-80`。 |
| `IFailureDetectionEventListener` | FD conviction 回调接口，见 `src/java/org/apache/cassandra/gms/IFailureDetectionEventListener.java:28-36`。 |
| `Gossiper` | FD listener 和 heartbeat report gate，见 `src/java/org/apache/cassandra/gms/Gossiper.java:405-408`、`:600-627`、`:1385-1429`。 |
| `RepairSession` / `ActiveRepairService` / `PaxosCleanupSession` | FD 下游 listeners，见 `RepairSession.java:413-430`、`ActiveRepairService.java:1063-1067`、`PaxosCleanupSession.java:234-237`。 |
| `SimulatedFailureDetector` | simulator override 和 deterministic down injection，见 `test/simulator/main/org/apache/cassandra/simulator/systems/SimulatedFailureDetector.java:44-107`。 |

## 核心接口

- `report(InetAddressAndPort ep)`：heartbeat arrival sample entry。
- `interpret(InetAddressAndPort ep)`：计算 phi、本地 pause 防护和 listener callback。
- `remove(InetAddressAndPort ep)`：endpoint reboot/generation change 时清理旧 samples。
- `forceConviction(InetAddressAndPort ep)`：topology/shutdown/测试路径直接触发 listeners。
- `registerFailureDetectionEventListener(...)` / `unregisterFailureDetectionEventListener(...)`：Gossiper、repair、Paxos cleanup 等订阅入口。
- `FailureDetectorMBean`：JMX/nodetool 观测和 threshold setter/getter。

## 核心数据结构

| 数据结构 | 字段 | 语义 |
|---|---|---|
| `arrivalSamples` | endpoint -> `ArrivalWindow` | 每个 endpoint 的心跳间隔窗口。 |
| `fdEvntListeners` | `CopyOnWriteArrayList<IFailureDetectionEventListener>` | conviction subscribers。 |
| `ArrivalWindow` | `tLast`、`ArrayBackedBoundedStats`、`lastReportedPhi`、`MAX_INTERVAL_IN_NANO` | 计算未收到 heartbeat 的 suspicion。 |
| `ArrayBackedBoundedStats` | `arrivalIntervals`、`sum`、`index`、`isFilled`、`mean` | 固定 1000 样本 ring buffer。 |
| `EndpointState` | `isAlive`、heartbeat generation/version、application states | Gossiper 根据 FD callback 改 alive/down。 |

## 生命周期

```text
GossipDigestAckVerbHandler / GossipDigestAck2VerbHandler / Paxos cleanup gossip info
  -> Gossiper.notifyFailureDetector(remoteEpStateMap)
  -> generation/version gate passes
  -> FailureDetector.report(endpoint)
  -> ArrivalWindow.add(now, endpoint)

periodic gossip task
  -> FailureDetector.interpret(endpoint)
  -> local pause guard
  -> phi = (now - lastArrival) / meanArrivalInterval
  -> PHI_FACTOR * phi > phi_convict_threshold
  -> IFailureDetectionEventListener.convict(endpoint, phi)
  -> Gossiper.convict()
  -> markDead() / markAsShutdown()
```

## 调用链

```text
remote heartbeat advances
  -> Gossiper.notifyFailureDetector(endpoint, remoteState)
  -> fd.report(endpoint)
  -> arrivalSamples[endpoint].add(now, endpoint)
```

```text
endpoint heartbeat absent long enough
  -> FailureDetector.interpret(endpoint)
  -> ArrivalWindow.phi(now)
  -> listeners.convict(endpoint, rawPhi)
     -> Gossiper.convict(endpoint, rawPhi)
     -> RepairSession.convict(endpoint, rawPhi)
     -> ActiveRepairService.convict(endpoint, rawPhi)
     -> PaxosCleanupSession.convict(endpoint, rawPhi)
```

## 配置项

| 配置 | 定义 | 默认/限制 | 作用 |
|---|---|---|---|
| `phi_convict_threshold` | `src/java/org/apache/cassandra/config/Config.java:177` | 默认 8.0；启动校验 5..16，见 `DatabaseDescriptor.java:554-556` | FD conviction 阈值。 |
| `cassandra.max_local_pause_in_ms` | `CassandraRelevantProperties.java:352` | 默认 5000 | 本机 pause 超过该值时暂不 mark down peers。 |
| `cassandra.fd_initial_value_ms` | `CassandraRelevantProperties.java:225` | 默认 `Gossiper.intervalInMillis * 2` | 新 endpoint 初始到达间隔。 |
| `cassandra.fd_max_interval_ms` | `CassandraRelevantProperties.java:226` | 默认初始 interval | 进入 window 的最大 arrival interval。 |

## Metrics

- FD 没有 Dropwizard metric；主要观测面是 JMX/nodetool PHI、endpoint states、up/down count 和 inter-arrival dump。
- `GossiperDiagnostics.convicted(...)` 产生 diagnostic event，配合 gossip diagnostics catalog 使用。
- repair/Paxos cleanup 的 failure metrics 属于对应模块，不属于 FD 自身。

## 日志

- `FailureDetector.getMaxLocalPause()` 在 system property override 时 warn。
- `FailureDetector.getInitialValue()` / `ArrivalWindow.getMaxInterval()` 在 FD init/max interval override 时 info。
- `interpret()` 在本地 pause 超阈值时 warn，pause 后窗口内 debug。
- phi 接近阈值时 debug，trace 级别输出 phi、intervals、mean。
- `forceConviction()` debug，`Gossiper.convict()` debug。

## 运维关注点

- 误判 DOWN：优先检查本机 GC/STW、`cassandra.max_local_pause_in_ms`、gossip stage backlog、网络抖动、PHI 和 endpoint state。
- 大范围节点同时被判 down 通常不是所有 peer 同时故障，更可能是本机 pause、防护窗口过短或 gossip stage 卡住。
- `phi_convict_threshold` 运行时可调但不重新校验；不要把低于 5 的值留在生产。
- repair 失败不一定和 Gossiper down 同步，repair listener 要求更高 raw phi。

## 性能瓶颈

- `arrivalSamples` 随已知 endpoint 数增长；每个 endpoint 固定 1000 个 long interval。
- `getAllEndpointStates*` 和 `dumpInterArrivalTimes()` 在大集群上输出大，适合排障而不是高频采集。
- 过多 listeners 或 listener 中阻塞会扩大 conviction propagation 成本；Gossiper 通过 gossip stage 串行保护 state mutation。

## 常见故障

- `FailureDetector.interpret()` 一直不 convict：检查是否没有 `report()` 样本、local pause 抑制窗口仍在、threshold 过高、remote generation/version 未前进。
- JMX/nodetool PHI 和 listener raw phi 不一致：JMX 返回的是 `phi * PHI_FACTOR`。
- endpoint reboot 后仍保留旧 interval：检查 `Gossiper.notifyFailureDetector()` 是否走到 generation change `fd.remove(endpoint)`。
- repair 因 FD 失败晚于 gossip DOWN：这是 `2 * phi_convict_threshold` 设计取舍。
- simulator 中 endpoint down 立即生效：`SimulatedFailureDetector.markDown()` 直接发 `Double.MAX_VALUE` conviction，不代表生产 phi 收敛时间。

## 测试用例

- `python3 research/tools/check-failure-detector-phi-drift.py`：source/test/doc drift check。
- `python3 research/tools/check-failure-detector-phi-drift.py --json`：输出 scenario ids 和失败项。
- `FailureDetectorTest.testConvictAfterLeft()`：LEFT endpoint FD history/conviction，见 `test/unit/org/apache/cassandra/gms/FailureDetectorTest.java:61-91`。
- `FailureDetectorTest.testMaxIntervalCalculation()`：`FD_MAX_INTERVAL_MS` default/override，见 `FailureDetectorTest.java:95-124`。
- `RepairSessionTest`：repair session FD conviction path，见 `test/unit/org/apache/cassandra/repair/RepairSessionTest.java:73`。
- `PaxosRepair2Test`、`RepairCoordinatorNeighbourDown`、`ForceRepairTest`：distributed FD down 对 Paxos/repair 的影响，见 `test/distributed/org/apache/cassandra/distributed/test/PaxosRepair2Test.java:252`、`test/distributed/org/apache/cassandra/distributed/test/RepairCoordinatorNeighbourDown.java:95`、`test/distributed/org/apache/cassandra/distributed/test/repair/ForceRepairTest.java:96`。
- `SimulatedFailureDetector`：simulator deterministic FD override，见 `test/simulator/main/org/apache/cassandra/simulator/systems/SimulatedFailureDetector.java:44-107`。
