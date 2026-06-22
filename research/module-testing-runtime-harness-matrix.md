# Module: Testing Runtime Harness Matrix

## 范围

本模块补齐 Testing Framework 的 runtime harness 漂移保护面。`module-testing-framework.md`、`module-testing-internals.md`、`module-testing-simulator-ci.md` 已分别覆盖 CQLTester、in-JVM dtest、simulator/CI 的架构；本页把这些能力压成可校验场景矩阵，明确每类 harness 的源码合同、适用边界、已有测试锚点和仍需外部 artifact 的缺口。

## 场景矩阵

| 场景 ID | 源码合同 | 测试/文档锚点 | 风险与边界 |
|---|---|---|---|
| `testing_unit_cql_internal_harness` | `CQLTester.setUpClass()` 调 `ServerTestUtils.daemonInitialization()` / `prepareServer()`；每个测试由 `beforeTest()` 建默认 keyspace，`afterTest()` 清理 schema；`executeFormattedQuery()` 走 internal `QueryProcessor`。见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:403`、`test/unit/org/apache/cassandra/cql3/CQLTester.java:454`、`test/unit/org/apache/cassandra/cql3/CQLTester.java:1634`。 | `CQLTesterTest` 与大量 `test/unit/org/apache/cassandra/cql3` 子类复用该路径；调用图见 `research/flow-test-execution.md`。 | internal CQL 不覆盖 native protocol、auth、driver warnings 或部分 guardrails；权限/协议类断言不能只用 `execute()`。 |
| `testing_cql_native_protocol_harness` | `executeNet()` -> `sessionNet()` -> `requireNetwork()` -> `startServices()` / `startServer()`，启动 StorageService/gossip/native transport 并用 Java driver session 访问。见 `CQLTester.java:1517`、`CQLTester.java:1569`、`CQLTester.java:613`、`CQLTester.java:633`、`CQLTester.java:667`。 | `NativeProtocolTest` 验证 native readiness/RPC_READY 等 dtest 行为，见 `test/distributed/org/apache/cassandra/distributed/test/NativeProtocolTest.java:53`。 | 单 JVM native harness 仍不是多节点；适合协议/auth/paging，但不适合 bootstrap/repair/streaming。 |
| `testing_schema_loader_server_prepare` | `SchemaLoader.loadSchema()` -> `prepareServer()` -> `startGossiper()`；`ServerTestUtils.daemonInitialization()` 固定测试 snitch 并调用 `DatabaseDescriptor.daemonInitialization()`。见 `test/unit/org/apache/cassandra/SchemaLoader.java:62`、`test/unit/org/apache/cassandra/ServerTestUtils.java:66`。 | `module-testing-framework.md` 已把 `SchemaLoader` 与 `ServerTestUtils` 列为单 JVM bootstrap 层。 | 多个 test class 共享 prepared server；如果绕过清理目录或 schema cleanup，后续测试会被静态状态污染。 |
| `testing_injvm_cluster_lifecycle` | `Cluster.build()` 默认 `CURRENT_VERSION`，`AbstractCluster.AbstractBuilder` 设置 `DTEST_IS_IN_JVM_DTEST`，constructor 创建 `InstanceConfig`/`Instance`，`startup()` 等待 live member，`close()` shutdown 并审计异常。见 `Cluster.java:45`、`AbstractCluster.java:183`、`AbstractCluster.java:541`、`AbstractCluster.java:1018`、`AbstractCluster.java:1079`。 | `JVMDTestTest` 覆盖 cluster schema/logs 和 stopped instance schema agreement，见 `test/distributed/org/apache/cassandra/distributed/test/JVMDTestTest.java:51`、`:71`、`:137`。 | in-JVM dtest 是单进程多 classloader，不是多进程真实集群；生产 daemon startup order 与 dtest harness 有差异。 |
| `testing_injvm_instance_isolation` | `Instance extends IsolatedExecutor`，节点创建时写入 config/classloader/file system；`startup(ICluster)` 在隔离 classloader 内执行 Cassandra boot subset；`shutdown(boolean)` 清理 messaging、JMX、crypto provider 和 classloader executor。见 `Instance.java:175`、`Instance.java:581`、`Instance.java:841`。 | `AbstractClusterTest` 覆盖 vnode/token/initial_token 配置约束，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractClusterTest.java:39`。 | `IsolatedExecutor.transfer()` 通过序列化跨 classloader 传对象；适合控制面，不适合大量数据搬运。 |
| `testing_injvm_schema_query_harness` | `AbstractCluster.schemaChange()` 选节点、以 `ConsistencyLevel.ALL` 执行 DDL 并等待 agreement；`cluster.coordinator(n)` 返回 `Coordinator`；`Coordinator.executeWithResult()` 在目标 `Instance.sync()` 内调用 `CoordinatorHelper.unsafeExecuteInternal()`，paging 手工构造 `QueryOptions`。见 `AbstractCluster.java:823`、`Coordinator.java:59`、`Coordinator.java:92`、`Coordinator.java:115`。 | `flow-test-execution.md` 给出 dtest schema/query 调用图。 | dtest coordinator API 是 internal coordinator execution，不等于 Java driver 网络客户端；需要 driver 语义时要单独走 native protocol。 |
| `testing_injvm_message_filter_faults` | `AbstractCluster.filters()` / `verbs(Verb...)` 构造 `MessageFilters`；delivery 先过可选 `IMessageSink`，否则调用目标 `Instance.receiveMessage()`；`MessageFilters.Filter.drop()` 把匹配消息拒绝。见 `AbstractCluster.java:788`、`:793`、`:800`、`MessageFilters.java:30`、`MessageFilters.java:190`。 | Paxos/repair/streaming/hints 等 dtest 广泛使用 drop/delay 语义；`module-testing-internals.md` 已收束为 fault-injection 基础能力。 | 过滤的是 in-JVM internode 消息，不覆盖真实 TCP、TLS、socket backlog 或 OS 网络行为。 |
| `testing_injvm_nodetool_probe` | `Instance.nodetoolResult()` 在节点上下文创建 `DTestNodeTool`，用 `InternalNodeProbeFactory` 绑定本进程 MBean 实例，捕获 rc/stdout/stderr/notification。见 `Instance.java:984`、`Instance.java:1071`、`InternalNodeProbe.java:61`。 | `HintedHandoffNodetoolTest` 覆盖 `statushandoff`、disable/enable、pause/resume、throttle/window 等命令，见 `test/distributed/org/apache/cassandra/distributed/test/HintedHandoffNodetoolTest.java:82`。 | 不走远程 JMX transport；适合命令语义，不能证明 JMX auth/SSL/网络连通性。 |
| `testing_upgrade_dtest_lifecycle` | `UpgradeableCluster` 关闭 `KEY_DTEST_API_CONFIG_CHECK` 以支持 cross-version API；`UpgradeTestBase.TestCase.run()` 为每条 upgrade path 创建初始版本 cluster，逐节点 shutdown、`setVersion()`、startup、执行 before/after hook。见 `UpgradeableCluster.java:43`、`UpgradeTestBase.java:142`、`UpgradeTestBase.java:312`、`UpgradeTestBase.java:348`。 | `test/distributed/org/apache/cassandra/distributed/upgrade/*` mixed-mode tests 使用该 DSL；`build.xml:dtest-jar` 负责生成版本 jar。 | 完整 `ICluster`/`IInstanceConfig`/`NodeToolResult` 等 API 来自外部 `dtest-api-*.jar`，当前 checkout 只能证明打包和可见 API 子集。 |
| `testing_simulator_agent_schedule` | `test-simulator-dtest` 通过 `simulator-asm.jar`/`simulator-bootstrap.jar` 运行；`SimulationRunner.beforeAll()` 固定 deterministic properties；`ClusterSimulation` 接入 `SimulatedMessageDelivery`、`SimulatedFutureActionScheduler`、`ActionPlan`/`ActionSchedule`；Paxos runner 再接 history checker。见 `build.xml:1784`、`SimulationRunner.java:95`、`ClusterSimulation.java:853`、`ActionPlan.java:64`、`ActionSchedule.java:165`、`PaxosSimulationRunner.java:32`。 | `TrivialSimulationTest`、`ShortPaxosSimulationTest`、`MonitorMethodTransformerTest` 覆盖 cluster/component/synchronized/executor interleaving smoke path。 | simulator 用模型化时间/网络/线程替代真实 runtime；失败复现依赖 seed、JVM 参数和 simulator CLI options。 |
| `testing_byteman_fault_injection` | `Byteman.createFromScripts()`/`createFromText()` 抽取 `CLASS ...` 并用 Byteman `Transformer` 注入 classloader；unit tests 也使用 BMUnitRunner 注入方法返回或异常。见 `test/distributed/org/apache/cassandra/distributed/shared/Byteman.java:96`、`:112`、`:144`。 | `CompactionsBytemanTest`、`DirectIOSegmentBytemanTest`、`test/resources/byteman/stream_failure.btm` 覆盖 compaction/disk/direct I/O/stream failure 注入。 | 规则绑定类名/方法名/调用点；重构后应更新规则和本矩阵。 |
| `testing_ant_runner_targets` | `build.xml` 的 `testmacrohelper`、`test`、`test-jvm-dtest`、`test-jvm-dtest-latest`、`test-simulator-dtest`、`test-jvm-upgrade-dtest`、`dtest-jar` 是本地测试执行入口。见 `build.xml:1123`、`:1665`、`:1762`、`:1773`、`:1784`、`:1811`、`:1733`。 | `flow-test-execution.md` 把 Ant/JUnit 到各 harness 的调用链串起来。 | runner 参数决定 forkmode、logback、heap、simulator determinism 和 external API artifact；直接用 IDE/JUnit 可能绕过关键 JVM 参数。 |
| `testing_dtest_api_artifact_boundary` | `dtest-jar` 会从 `${test.lib}/jars` 解压 `dtest-api-*.jar`；POM/build deps 声明 `org.apache.cassandra:dtest-api:0.0.18`。当前 tree 未发现可解压 artifact。见 `build.xml:1741`、`.build/parent-pom-template.xml:534`、`.build/cassandra-build-deps-template.xml:85`。 | `module-testing-ci-generator-matrix.md` 与本页都把外部 artifact 标成边界。 | 拿到 artifact 后应补 public API 清单、方法签名矩阵，以及与仓库内 `test/distributed/.../api` 子集的一致性检查。 |

## 关键调用图

```text
Unit CQL internal test
  -> ant test
  -> CQLTester.setUpClass()
     -> ServerTestUtils.daemonInitialization()
     -> ServerTestUtils.prepareServer()
  -> beforeTest()
  -> createTable/schemaChange()
  -> executeFormattedQuery()
     -> QueryProcessor internal execution
  -> afterTest()
```

```text
In-JVM distributed test
  -> Cluster.build(n).withConfig(...).start()
  -> AbstractCluster.AbstractBuilder
  -> AbstractCluster constructor
     -> createInstanceConfig()
     -> newInstanceWrapperInternal()
  -> AbstractCluster.startup()
     -> Instance.startup(ICluster)
  -> schemaChange/coordinator/message filters/nodetool/logs
  -> AbstractCluster.close()
```

```text
Simulator test
  -> ant test-simulator-dtest
  -> javaagent simulator-asm.jar + bootstrap jar
  -> SimulationRunner.beforeAll()
  -> ClusterSimulation.Builder.create(seed)
  -> ClusterSimulation creates dtest Cluster and SimulatedSystems
  -> ActionPlan.iterator()
  -> ActionSchedule executes actions/consequences
```

## 配置与运行入口

| 入口 | 配置/参数 | 作用 |
|---|---|---|
| `ant test -Dtest.name=...` | `build.xml:1665`，`testmacrohelper` 输出 XML/brief formatter | 单 JVM unit/CQL/fuzz/Byteman baseline。 |
| `ant test-jvm-dtest -Dtest.name=...` | `build.xml:1762`，`forkmode=once`、dtest logback、8G heap | in-JVM distributed tests。 |
| `ant test-jvm-dtest-latest` | `build.xml:1773`，设置 latest dtest config | 触发 `InstanceConfig` latest 参数，如 Trie memtable、BTI、UCS、SAI、storage compatibility NONE。 |
| `ant test-simulator-dtest` | `build.xml:1784`，strict determinism、javaagent、bootclasspath | simulator dtests。 |
| `ant test-jvm-upgrade-dtest` | `build.xml:1811` | mixed-version upgrade dtests，需要 dtest jars。 |
| `ant dtest-jar` | `build.xml:1733` | 生成 cross-version dtest-compatible jar，并消费 `dtest-api-*.jar`。 |

## Metrics 与日志

- runtime harness 本身不定义生产 metrics；它主要暴露可断言入口。`Instance.metrics()` 返回 `InstanceMetrics`，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:978`。
- nodetool harness 的可观测输出是 `NodeToolResult` 的 rc、notifications、latestError、stdout、stderr，见 `Instance.java:984`。
- dtest/simulator 每节点日志在 `build/test/logs/${cassandra.testtag}/${suitename}/${cluster_id}/${instance_id}/system.log`；`Instance.logs()` 负责定位，见 `Instance.java:226`。
- simulator 失败以 seed、randomized config、`HistoryChecker` 输出和 `Failures` 聚合为主要证据。

## 运维关注点

- 复现普通 CQL 单测时先区分 internal execution 与 native execution；只有 `executeNet()`/driver path 覆盖协议层。
- 复现 dtest 时保留 cluster feature flags、node config、message filters、logs path 和 exact Ant target。
- 复现 simulator 时必须保留 seed、`--simulations`、network/clock/scheduler 参数，以及 javaagent/bootstrap JVM 参数。
- 升级测试失败涉及 API 类型缺失时，先检查 `test/lib/jars/dtest-api-*.jar` 与对应 `dtest-${base.version}.jar` 是否存在。

## 性能瓶颈

- `test-jvm-dtest` 在一个 JVM 内运行多节点，heap/classloader/thread 泄漏会累积到同一 fork。
- `test-simulator-dtest` `forkmode=perTest` 且 8G heap、固定 compiler 参数，单测启动成本高。
- `IsolatedExecutor.transfer()` 的序列化开销和 `Coordinator.executeWithPaging()` 的循环执行会放大大结果集测试成本。
- CircleCI filename/classname timing split 对新测试缺少历史，新增大 dtest 容易造成分片倾斜。

## 常见故障

- internal `CQLTester.execute()` 测试通过但客户端失败：检查是否遗漏 native protocol/auth/driver path。
- dtest message filter 测试偶发：检查 filter 是否在请求发出前安装，是否忘记 reset/close filter。
- nodetool dtest 通过但远程 JMX 失败：`InternalNodeProbe` 不走远程 JMX，需补 JMX feature/auth test。
- simulator 报真实时间访问：检查是否通过 `test-simulator-dtest` 加载 agent/bootstrap，或代码是否在非 intercepting thread 调时间。
- Byteman 规则无效：检查 `CLASS`、`METHOD`、`AT INVOKE` 是否仍匹配当前源码。

## Drift 检查

- `research/tools/check-testing-runtime-harness-drift.py` 保护本页的 source/test/doc baseline。
- checker 不运行 Cassandra、不运行 JUnit、不生成 CircleCI config；它只验证源码 token、已有测试锚点、`dtest-api` artifact absence 和 research 文档场景 ID。
