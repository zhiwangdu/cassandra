# Module: Failure Detector Phi Drift Checker

## 范围

`research/tools/check-failure-detector-phi-drift.py` 是 source-only drift check，用来保护 Failure Detector phi/conviction matrix 的源码合同和文档覆盖。它检查 `FailureDetector` 算法 token、`Gossiper` report/convict gate、配置项、下游 listeners、simulator override、测试锚点和 research 索引同步。

当前基线：

- 10 个场景 ID，覆盖 arrival window、report gate、local pause、threshold/JMX scale、配置、gossip stage conviction、shutdown force conviction、repair/Paxos downstream、simulator override 和 observability/tests。
- `FailureDetector.SAMPLE_SIZE = 1000`。
- `phi_convict_threshold` 默认 8.0，启动校验范围 5..16。
- `cassandra.max_local_pause_in_ms` 默认 5000。
- `FD_INITIAL_VALUE_MS`、`FD_MAX_INTERVAL_MS`、`MAX_LOCAL_PAUSE_IN_MS` 三个 system properties。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `fd_phi_arrival_window_seed` | `ArrivalWindow` 初始 interval、bounded stats、max interval 截断和 phi 计算。 |
| `fd_report_generation_version_gate` | `Gossiper.notifyFailureDetector()` 的 generation/version gate 和 generation change `fd.remove()`。 |
| `fd_local_pause_suppression` | `MAX_LOCAL_PAUSE_IN_NANOS`、warn/debug path 和 pause 后抑制窗口。 |
| `fd_phi_threshold_and_jmx_scale` | raw phi、`PHI_FACTOR`、threshold comparison 和 JMX scaled PHI。 |
| `fd_config_limits_and_system_properties` | config default、startup range check、runtime setter 和 system properties。 |
| `fd_conviction_gossip_stage` | Gossiper 注册 listener、gossip stage blocking mutation 和 markDead/markAsShutdown。 |
| `fd_shutdown_force_conviction` | shutdown/topology path 调 `forceConviction()`。 |
| `fd_downstream_repair_confidence` | repair/active repair/Paxos cleanup listeners 和 repair `2 * threshold` confidence boundary。 |
| `fd_simulator_override` | simulator FD wrapper、override map 和 deterministic `Double.MAX_VALUE` conviction。 |
| `fd_observability_and_tests` | JMX/nodetool observability、unit/distributed/simulator test anchors。 |

## Source Contract

Checker 固定以下合同：

- `FailureDetector.java` 必须包含 `SAMPLE_SIZE = 1000`、`INITIAL_VALUE_NANOS`、`PHI_FACTOR`、`arrivalSamples`、`fdEvntListeners`、`report()`、`interpret()`、`forceConviction()`、`ArrivalWindow` 和 `ArrayBackedBoundedStats` 的关键 token。
- `Gossiper.java` 必须注册 FD listener，并在 generation/version 前进时报告 heartbeat，在 generation change 且 local state dead 时清理 FD interval。
- `DatabaseDescriptor.java` 必须保留 `phi_convict_threshold` 启动范围 5..16 和 runtime getter/setter。
- `CassandraRelevantProperties.java` 必须保留 `FD_INITIAL_VALUE_MS`、`FD_MAX_INTERVAL_MS`、`MAX_LOCAL_PAUSE_IN_MS`。
- repair/Paxos downstream 必须保留 `IFailureDetectionEventListener` 和 confidence/kill-session token。
- test anchors 必须包含 `FailureDetectorTest`、`RepairSessionTest`、`PaxosRepair2Test`、`RepairCoordinatorNeighbourDown`、`ForceRepairTest` 和 `SimulatedFailureDetector`。

## 设计目标

- 在源码变更时快速发现 FD 算法、配置、listener 或文档不同步。
- 把 Failure Detector 从 gossip/JMX 附属说明中抽出来，作为目标清单里的独立模块保护。
- 保持 source-only，可在普通 checkout 运行，不需要启动 Cassandra。

## 解决的问题

- FD 误判是运维高风险问题，文档如果只写 JMX/nodetool route，不足以解释为什么节点被 mark down 或为什么 repair 没立即失败。
- `PHI_FACTOR` 和 JMX scaled PHI 容易混淆；checker 固定这两个 token 的文档覆盖。
- 下游 listeners 对 raw phi 的处理不同；checker 防止只记录 Gossiper 而漏掉 repair/Paxos cleanup。

## 设计取舍

- 使用 token contract，不解析 Java AST。FD 源码结构重排会触发人工复核。
- 不验证数学公式正确性，只验证当前 Cassandra source contract 和 research 文档一致。
- 不运行 unit/distributed tests；测试文件名和关键方法是 source evidence，运行时 evidence 需单独执行 Java tests。

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-failure-detector-phi-drift.py` | source/test/doc drift checker。 |
| `FailureDetector` | FD 算法与 JMX MBean。 |
| `ArrivalWindow` / `ArrayBackedBoundedStats` | arrival sample window 和 phi 计算。 |
| `Gossiper` | heartbeat report gate 和 conviction state mutation。 |
| `RepairSession` / `ActiveRepairService` / `PaxosCleanupSession` | FD downstream listeners。 |
| `SimulatedFailureDetector` | deterministic simulator override。 |

## 核心接口

- `source_checks()`：验证源码和测试 token。
- `doc_checks()`：验证 matrix/checker/README/source-map 是否包含场景、路径、配置和测试锚点。
- `--json`：输出所有 checks 和 failed checks。

## 生命周期

```text
developer changes FD/gossip/repair/simulator/config
  -> run python3 research/tools/check-failure-detector-phi-drift.py
  -> checker validates source/test/docs
  -> update matrix/checker/README/source-map together
  -> run Java unit/distributed tests when behavior changed
```

## 调用链

```text
check-failure-detector-phi-drift.py
  -> read FailureDetector/Gossiper/config/downstream/test files
  -> validate token contracts
  -> read research docs and indexes
  -> validate scenario ids and source/test anchors
```

## 配置项

- 无 checker runtime config。
- 受保护的 Cassandra 配置项包括 `phi_convict_threshold`、`cassandra.max_local_pause_in_ms`、`cassandra.fd_initial_value_ms`、`cassandra.fd_max_interval_ms`。

## Metrics

- checker 输出通过/失败 check 数和 scenario 数。
- FD 本身无 Dropwizard metric；观测面通过 JMX/nodetool。

## 日志

- 成功输出 `OK Failure Detector phi drift checks passed (...)`。
- 失败输出 `FAIL ...` 并返回 1；读取/解析异常返回 2。

## 运维关注点

- 绿色 checker 不证明 FD 行为在运行时正确，只证明源码/文档合同同步。
- 如果修改 threshold、pause 或 interval 逻辑，应补 Java unit/distributed tests，而不是只更新 token baseline。

## 常见故障

- `source token contract FailureDetector.java` 失败：FD 算法/配置/log path 变了，需要重读源码。
- `source token contract Gossiper.java` 失败：report gate 或 conviction path 变了，需要更新 gossip/FD 调用链。
- `doc token ...` 失败：新合同没有进入 research matrix 或索引。

## 测试用例

- `python3 research/tools/check-failure-detector-phi-drift.py`。
- `python3 research/tools/check-failure-detector-phi-drift.py --json`。
- Java evidence: `FailureDetectorTest`、`RepairSessionTest`、`PaxosRepair2Test`、`RepairCoordinatorNeighbourDown`、`ForceRepairTest`。
