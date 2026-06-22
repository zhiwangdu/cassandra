# Testing Framework Internals

## 范围

本文件是 `module-testing-framework.md` 的第二轮补充，聚焦测试基础设施内部：Ant/JUnit runner、dtest API 边界、in-JVM 节点隔离、message filter、nodetool 捕获、simulator javaagent/bootstrap、确定性调度、Byteman 注入和 CI profile。CQLTester、SchemaLoader、upgrade/fuzz 的第一轮模型仍以 `module-testing-framework.md` 和 `flow-test-execution.md` 为主。

本轮有一个明确边界：当前工作区没有发现 `test/lib/jars/dtest-api-*.jar` 或其他 dtest API artifact；仓库内只包含 `test/distributed/org/apache/cassandra/distributed/api` 的可见 cross-version API 子集。`build.xml` 的 `dtest-jar` 目标会从 `${test.lib}/jars` 解压 `dtest-api-*.jar`，说明完整 API 仍依赖外部 jar，见 `build.xml:1733-1758`。

## 设计目标

测试基础设施的目标不是单一 runner，而是把四种验证环境放到同一个源码树内：

1. 单 JVM 单元测试使用 `test/unit`、`test/long`、`test/burn`、`test/memory`、`test/microbench`。
2. in-JVM distributed test 使用 `test/distributed`，在一个 JVM 中构造多个隔离 Cassandra 节点。
3. simulator 使用 `test/simulator/main`、`test/simulator/asm`、`test/simulator/bootstrap`、`test/simulator/test`，通过 bytecode weaving、模拟时钟、模拟网络和 action scheduler 扰动并复现实例行为。
4. CI profile 通过 CircleCI 拆分文件列表，再调用 Ant `testclasslist*` targets 执行。

源码入口由 `build.xml` 显式列出：unit、long、burn、memory、microbench、distributed 和 simulator 四个目录族见 `build.xml:80-91`；`build-test` 编译这些目录并依赖 `simulator-jars`，见 `build.xml:1017-1050`。

## 解决的问题

- 多版本 dtest 要把当前源码、测试类、test config、依赖 jar 和 dtest API 合成可加载 artifact；`dtest-jar` 复制 main/test/conf，再解压 `dtest-api-*.jar` 等依赖，最后生成 `build/dtest-${base.version}.jar`，见 `build.xml:1733-1758`。
- in-JVM dtest 要让多个节点共享一个进程但隔离静态状态；`Cluster` 只是当前版本入口，实际节点 wrapper 由 `AbstractCluster` 和 `Instance` 创建，见 `test/distributed/org/apache/cassandra/distributed/Cluster.java:29-72`、`test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:541-573`、`test/distributed/org/apache/cassandra/distributed/impl/Instance.java:175-217`。
- upgrade dtest 要允许不同版本的节点只走 cross-version API；`UpgradeableCluster` 返回 `IUpgradeableInstance`，并关闭 `KEY_DTEST_API_CONFIG_CHECK`，见 `test/distributed/org/apache/cassandra/distributed/UpgradeableCluster.java:29-89`。
- simulator 要截获 JDK 并发/随机/时间入口，同时仍能用 dtest cluster 运行 Cassandra；`InterceptAgent` 说明 `simulator-asm.jar` 和 `simulator-bootstrap.jar` 是自包含 weaving jar，见 `test/simulator/asm/org/apache/cassandra/simulator/asm/InterceptAgent.java:59-70`。
- 故障注入要同时支持源码级和字节码级：dtest 有 message filters，Byteman 能替换目标方法返回值或抛异常，simulator 能用 ASM 和调度器扰动执行顺序，见 `test/distributed/org/apache/cassandra/distributed/impl/MessageFilters.java:29-64`、`test/distributed/org/apache/cassandra/distributed/shared/Byteman.java:144-172`、`test/simulator/main/org/apache/cassandra/simulator/ActionSchedule.java:60-76`。

## 设计取舍

- Ant 目标把 simulator jar 构建纳入 `build-test`，优点是普通测试编译阶段就能拿到 javaagent/bootstrap jar；代价是测试编译对 ASM、bootstrap classpath 和 JDK 编译参数更敏感，见 `build.xml:657-708`、`build.xml:792-820`、`build.xml:1017-1050`。
- dtest API 一部分源码在仓库内，一部分来自 `dtest-api-*.jar`。这样能维持跨版本稳定接口，但当前 checkout 无法仅凭源码枚举 `ICluster`、`IInstanceConfig`、`IInvokableInstance`、`NodeToolResult`、`Versions` 等完整定义；这些类型只在实现层被引用，见 `test/distributed/org/apache/cassandra/distributed/Cluster.java:40-72` 和 `test/distributed/org/apache/cassandra/distributed/impl/InstanceConfig.java:42-58`。
- `Cluster` 当前版本入口暴露 `IInvokableInstance` 便利 API，upgrade 入口只暴露 cross-version API；这降低混合版本调用风险，但升级测试要接受较窄接口，见 `test/distributed/org/apache/cassandra/distributed/Cluster.java:29-72` 和 `test/distributed/org/apache/cassandra/distributed/UpgradeableCluster.java:29-89`。
- simulator 使用 bytecode weaving 和模拟系统替代真实线程/时钟/网络，能提高可复现性和探索调度空间，但需要禁用或重定向大量 runtime 行为，比如 JMX、jemalloc、ring delay、UUID、gossip settle 和 SSL，见 `test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java:94-139`。
- Byteman 单测能精准修改目标方法返回值或执行点，适合覆盖异常路径；代价是规则绑定类名/方法名/位置，重构后容易静默失效或需要同步更新，见 `test/unit/org/apache/cassandra/db/compaction/CompactionsBytemanTest.java:47-61`、`test/unit/org/apache/cassandra/db/commitlog/DirectIOSegmentBytemanTest.java:39-64`。

## 核心类

| 类 | 作用 | 证据 |
|---|---|---|
| `Cluster` | 当前版本 in-JVM dtest cluster 入口，默认 `CURRENT_VERSION` | `test/distributed/org/apache/cassandra/distributed/Cluster.java:45-72` |
| `UpgradeableCluster` | 多版本 cluster 入口，只暴露 cross-version API | `test/distributed/org/apache/cassandra/distributed/UpgradeableCluster.java:29-89` |
| `AbstractCluster` | cluster builder、实例配置、节点生命周期、schema agreement、message sink/filter | `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:541-573`、`test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:1018-1112` |
| `Instance` | 单节点 wrapper，继承 `IsolatedExecutor` 并在隔离 classloader 内启动 Cassandra | `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:175-217`、`test/distributed/org/apache/cassandra/distributed/impl/Instance.java:581-650` |
| `InstanceConfig` | dtest 节点配置容器，生成 token、地址、目录、snitch、seed、缓存和 latest 配置差异 | `test/distributed/org/apache/cassandra/distributed/impl/InstanceConfig.java:42-118`、`test/distributed/org/apache/cassandra/distributed/impl/InstanceConfig.java:119-168` |
| `IsolatedExecutor` | 把 serializable lambda/object 序列化到节点 classloader，并管理 isolated executor shutdown | `test/distributed/org/apache/cassandra/distributed/impl/IsolatedExecutor.java:55-145`、`test/distributed/org/apache/cassandra/distributed/impl/IsolatedExecutor.java:185-260` |
| `Coordinator` | dtest CQL coordinator 实现，封装 internal execution、tracing 和 paging | `test/distributed/org/apache/cassandra/distributed/impl/Coordinator.java:50-183` |
| `MessageFilters` | inbound/outbound message drop filter 实现 | `test/distributed/org/apache/cassandra/distributed/impl/MessageFilters.java:29-207` |
| `InterceptAgent` | simulator javaagent/agentmain，weave bootstrap/JDK 类 | `test/simulator/asm/org/apache/cassandra/simulator/asm/InterceptAgent.java:73-124` |
| `ClusterSimulation` | simulator 中构造 dtest cluster、模拟时钟/网络/执行器/ballot/failure detector | `test/simulator/main/org/apache/cassandra/simulator/ClusterSimulation.java:627-850` |
| `ActionPlan` / `ActionSchedule` | simulator action 生命周期和随机/有限/无限调度 | `test/simulator/main/org/apache/cassandra/simulator/ActionPlan.java:35-89`、`test/simulator/main/org/apache/cassandra/simulator/ActionSchedule.java:60-220` |
| `Byteman` | 从脚本/text 抽取目标类，创建 Byteman transformer 并注入新 bytecode | `test/distributed/org/apache/cassandra/distributed/shared/Byteman.java:96-191` |

## 核心接口

- `ICoordinator` 是仓库内可见 cross-version CQL 接口，包含 execute、paging、tracing 和 `instance()`，见 `test/distributed/org/apache/cassandra/distributed/api/ICoordinator.java:27-72`。
- `IClassTransformer` 是仓库内可见 bytecode transformer 接口，`transform(name, bytecode)` 可返回修改后的 class bytes，见 `test/distributed/org/apache/cassandra/distributed/api/IClassTransformer.java:20-30`。
- `IMessage` 是可序列化 internode message 接口，包含 verb、payload bytes、id、version、source 和 optional expiration，见 `test/distributed/org/apache/cassandra/distributed/api/IMessage.java:24-43`。
- `QueryResult` 是完整查询结果迭代器，并警告 `Row` 有对象复用语义，跨 `hasNext()` 保存 row 引用不安全，见 `test/distributed/org/apache/cassandra/distributed/api/QueryResult.java:25-86`。
- 外部 dtest API 边界：实现代码引用 `ICluster`、`IInstanceConfig`、`IInvokableInstance`、`IUpgradeableInstance`、`IIsolatedExecutor`、`IMessageFilters`、`IMessageSink`、`NodeToolResult`、`Feature`、`Versions`、`InstanceClassLoader` 和 shared `AbstractBuilder`，但这些完整定义不在当前 checkout 的可见源码中；`dtest-jar` 对 `dtest-api-*.jar` 的打包要求见 `build.xml:1741-1742`。

## 核心数据结构

- `InstanceConfig.params` / `dtestParams`：TreeMap 保存 Cassandra yaml 参数和 dtest 参数，节点号、hostId、topology、feature flags 和 broadcast address 是 wrapper 侧基础状态，见 `test/distributed/org/apache/cassandra/distributed/impl/InstanceConfig.java:42-58`。
- `InstanceConfig` 默认参数：固定 Murmur3、native transport、低并发、单 flush writer/compactor、small memtable、periodic commitlog、distributed snitch、seed provider、diagnostic events、`auto_bootstrap=false`、固定缓存容量和 legacy commitlog disk access，见 `test/distributed/org/apache/cassandra/distributed/impl/InstanceConfig.java:80-118`。
- latest dtest 参数：`jvm_dtests.latest=true` 时启用 TrieMemtable、dynamic remote batchlog endpoint、auth 类、key cache 关闭、offheap objects、auto disk access、trickle fsync、BTI、UCS、uuid SSTable id、entire SSTable streaming、SAI 和 storage compatibility NONE，见 `test/distributed/org/apache/cassandra/distributed/impl/InstanceConfig.java:119-168`。
- `MessageFilters.Filter` 持有 from/to/verbs/matcher 和 parent list；匹配后 `permit` 返回 false，表示 drop，见 `test/distributed/org/apache/cassandra/distributed/impl/MessageFilters.java:57-138`。
- `ActionPlan` 把 simulation 分成 pre、interleave、post；`ActionSchedule.Work` 再把 work 绑定到 TIME_LIMITED、STREAM_LIMITED、FINITE、UNLIMITED 等模式，见 `test/simulator/main/org/apache/cassandra/simulator/ActionPlan.java:35-69` 和 `test/simulator/main/org/apache/cassandra/simulator/ActionSchedule.java:76-180`。
- `ClusterSimulation` 的随机化配置包括 node/DC/RF、memtable 类型、memtable allocation、clock drift/discontinuity、commitlog compression 和 disk mode，见 `test/simulator/main/org/apache/cassandra/simulator/ClusterSimulation.java:651-730`。

## 生命周期

```text
Ant test setup
  -> simulator-asm-build / simulator-bootstrap-build
  -> simulator-jars
  -> build-test compiles unit, distributed and simulator sources
  -> test-jvm-dtest or test-simulator-dtest invokes testmacro
```

`simulator-jars` 生成 `test/lib/jars/simulator-asm.jar`，manifest 指定 `Premain-Class` 和 `Agent-Class` 为 `org.apache.cassandra.simulator.asm.InterceptAgent`；同时生成 `simulator-bootstrap.jar`，见 `build.xml:792-820`。`test-simulator-dtest` 使用 `-javaagent` 和 `-Xbootclasspath/a` 加载它们，并固定 deterministic JVM 编译参数，见 `build.xml:1783-1805`。

```text
in-JVM dtest
  -> Cluster.build(...).withConfig(...).start()
  -> AbstractCluster constructor creates InstanceConfig and Instance wrappers
  -> AbstractCluster.startup installs exception handler and starts nodes
  -> Instance.startup runs Cassandra boot path inside isolated classloader
  -> test uses coordinator, message filters, nodetool, logs, metrics
  -> cluster.close shuts down instances and audits uncaught exceptions
```

`AbstractCluster.startup()` 先安装 uncaught exception handler，再启动 node 1 和 auto-bootstrap 节点，其他节点并行启动，并等待 live member 收敛，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:1018-1050`。`close()` 停节点、清目录、清 maps、恢复 exception handler 并检查 instance classloader 捕获的异常，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:1053-1112`。

```text
simulator cluster test
  -> SimulationRunner.beforeAll() installs deterministic properties
  -> ClusterSimulation.Builder creates RandomSource and SimulatedSystems
  -> ClusterSimulation creates dtest Cluster with InterceptAsClassTransformer
  -> Simulation returns ActionPlan iterator
  -> ActionSchedule advances actions, consequences, daemon waves and time
```

`SimulationTestBase.simulate` 调用 `SimulationRunner.beforeAll()`、生成 seed、创建 `ClusterSimulation`，再运行 simulation，见 `test/simulator/test/org/apache/cassandra/simulator/test/SimulationTestBase.java:147-180`。component-level simulate 会创建 `InstanceClassLoader`、`InterceptClasses`、`SimulatedTime`、`InterceptingExecutorFactory` 和 `ActionSchedule`，见 `test/simulator/test/org/apache/cassandra/simulator/test/SimulationTestBase.java:237-329`。

## 调用链

- dtest cluster 构造：`Cluster.build()` -> `Cluster.Builder` -> `AbstractCluster.AbstractBuilder` -> `AbstractCluster` constructor -> `createInstanceConfig()` -> `newInstanceWrapperInternal()`，关键入口见 `test/distributed/org/apache/cassandra/distributed/Cluster.java:45-72`、`test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:183-203`、`test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:541-621`。
- 节点启动：`AbstractCluster.startup()` -> `Instance.startup()` -> `DatabaseDescriptor.daemonInitialization()` -> `CommitLog.instance.start()` -> `SystemKeyspace.persistLocalMetadata()` -> `StorageService.instance.populateTokenMetadata()` -> `Schema.instance.loadFromDisk()` -> virtual keyspace setup，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:1018-1050` 和 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:581-650`。
- dtest CQL：`ICoordinator.executeWithResult()` -> `Coordinator.executeWithResult()` -> `Instance.sync()` -> `CoordinatorHelper.unsafeExecuteInternal()`；paging 分支构造 `QueryOptions` 并循环 `SelectStatement.execute()`，见 `test/distributed/org/apache/cassandra/distributed/api/ICoordinator.java:27-72` 和 `test/distributed/org/apache/cassandra/distributed/impl/Coordinator.java:58-180`。
- dtest nodetool：`Instance.nodetoolResult()` -> `DTestNodeTool` -> temporary `SecurityManager` 捕获 `System.exit` -> `InternalNodeProbeFactory`/`InternalNodeProbe` -> 返回 `NodeToolResult`，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:984-1134`。
- message filter：test 调用 filter builder -> `Filter.on()` 加入 inbound/outbound list -> delivery 时 `permitInbound/permitOutbound()` 命中则 drop，见 `test/distributed/org/apache/cassandra/distributed/impl/MessageFilters.java:35-64`、`test/distributed/org/apache/cassandra/distributed/impl/MessageFilters.java:120-207`。
- simulator agent：JVM 加载 `InterceptAgent.premain()` -> 注册 `ClassFileTransformer` -> transform `Object`、`Enum`、`Random`、`ThreadLocalRandom`、`ConcurrentHashMap` 和 locks -> redefine 已加载匹配类，见 `test/simulator/asm/org/apache/cassandra/simulator/asm/InterceptAgent.java:73-124`。
- simulator cluster：`ClusterSimulation` 构建 `InterceptAsClassTransformer` 和 simulated systems -> `Cluster.build(numOfNodes).withRoot(fs).withSharedClasses(...).withConfig(...).withInstanceInitializer(...).withClassTransformer(...)`，见 `test/simulator/main/org/apache/cassandra/simulator/ClusterSimulation.java:732-850`。
- Byteman helper：`createFromScripts()` 读取脚本 -> `extractClasses()` 抽取 `CLASS ...` -> `Transformer.transform()` 生成新 bytes -> reflective `defineClass` 注入目标 classloader，见 `test/distributed/org/apache/cassandra/distributed/shared/Byteman.java:96-191`。

## 配置项

- 测试源码目录由 `build.xml` 属性指定：`test.unit.src`、`test.long.src`、`test.burn.src`、`test.memory.src`、`test.microbench.src`、`test.distributed.src`、`test.simulator.src`、`test.simulator-asm.src`、`test.simulator-bootstrap.src`、`test.simulator-test.src`，见 `build.xml:80-91`。
- `test-jvm-dtest` 使用 `test/distributed`、`forkmode=once`、`logback-dtest.xml`、`cassandra.ring_delay_ms=10000`、`cassandra.skip_sync=true`、`-Xmx8G`，见 `build.xml:1762-1770`。
- `test-jvm-dtest-latest` 额外设置 `-Djvm_dtests.latest=true`，触发 `InstanceConfig` latest 配置，见 `build.xml:1773-1780` 和 `test/distributed/org/apache/cassandra/distributed/impl/InstanceConfig.java:119-168`。
- `test-simulator-dtest` 使用 `test/simulator/test`、`forkmode=perTest`、`logback-simulator.xml`、strict determinism check、ASM print 配置、javaagent、bootclasspath、固定编译线程和 8G heap，见 `build.xml:1783-1805`。
- `SimulationRunner.BasicCommand` 暴露 seed、simulation count、threads、nodes、DC、并发、topology changes、run-time、read chance、nemesis、network partition/drop/delay/latency、clock drift 等 CLI 选项，见 `test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java:141-220`。
- Byteman debug 输出由 `TEST_BYTEMAN_TRANSFORMATIONS_DEBUG` 控制；开启时会把转换前后 class 写到临时目录，见 `test/distributed/org/apache/cassandra/distributed/shared/Byteman.java:56-57` 和 `test/distributed/org/apache/cassandra/distributed/shared/Byteman.java:157-165`。
- CircleCI distributed Java tests 通过 `circleci tests glob "$HOME/cassandra/test/distributed/**/*.java"` 拆分，过滤 `Test.java` 并排除 upgrade，然后运行 `ant testclasslist ... -Dtest.classlistprefix=distributed`，见 `.circleci/config.yml:220-285`。
- CircleCI compression 和 system-keyspace-directory profile 分别运行 `testclasslist-compression`、`testclasslist-system-keyspace-directory`，并用 `test/unit/**/*.java` 拆分文件，见 `.circleci/config.yml:700-755` 和 `.circleci/config.yml:1320-1375`。

## Metrics

测试框架本身不定义生产路径 metrics；它暴露的是测试时读取和断言生产 metrics 的入口。`Instance.metrics()` 返回基于 `CassandraMetricsRegistry.Metrics` 的 `InstanceMetrics`，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:977-980`。dtest nodetool 返回的 `NodeToolResult` 则携带 command、return code、notifications、latest error、stdout 和 stderr，适合在测试中断言运维命令结果，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:984-1025`。

simulator 侧更偏向 determinism 和 failure 检测，而不是 metrics 采样。`ClusterSimulation` 给每个实例安装 leak listener、Paxos linearizability violation handler、ballot generator 和 intercepting executor factory，见 `test/simulator/main/org/apache/cassandra/simulator/ClusterSimulation.java:783-842`。

## 日志

- dtest 和 simulator 都使用 per-instance logback 文件：`build/test/logs/${cassandra.testtag}/${suitename}/${cluster_id}/${instance_id}/system.log`，配置分别见 `test/conf/logback-dtest.xml:27-32` 和 `test/conf/logback-simulator.xml:26-32`。
- `Instance.logs()` 按同一路径定位 system.log；如果测试类全局创建 cluster，则会尝试不含 suite 的备选路径，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:224-240`。
- Ant 目标通过 `-Dlogback.configurationFile` 选择 dtest 或 simulator 配置，见 `build.xml:1762-1765` 和 `build.xml:1783-1787`。
- CircleCI 会存储 `build/test/output/` 作为 JUnit test results；distributed、compression、system-keyspace-directory profile 都显式 `store_test_results` 到该路径，见 `.circleci/config.yml:284-285`、`.circleci/config.yml:754-755`、`.circleci/config.yml:1374-1375`。

## 运维关注点

- 本地跑 dtest 前先确认 `dtest-api-*.jar` 是否存在；`dtest-jar` 目标依赖该 jar，但当前 checkout 没有内置完整 artifact。缺失时，编译或打包会在解析外部 dtest API 类型时失败，相关打包规则见 `build.xml:1741-1742`。
- simulator 测试必须走 `test-simulator-dtest` 或等价 JVM 参数；少了 `-javaagent:test/lib/jars/simulator-asm.jar` 或 `-Xbootclasspath/a:test/lib/jars/simulator-bootstrap.jar`，JDK 类 weaving 和 bootstrap method replacement 不会生效，见 `build.xml:1783-1805`。
- in-JVM dtest 节点日志不在普通 `system.log`，而在 `build/test/logs/.../${cluster_id}/${instance_id}/system.log`；定位逻辑见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:224-240`。
- dtest `Instance.shutdown()` 要清 JMX、crypto provider、DeleteOnExit hooks 和 classloader；如果测试绕过 cluster close，后续测试可能被静态状态、线程或 classloader 持有污染，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:930-961`。
- simulator 使用固定 deterministic properties，包括禁用 JMX MBean registration、SSL、native file hints、jemalloc、gossip settle 等；与真实部署差异要在解释结果时显式考虑，见 `test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java:104-132`。

## 性能瓶颈

- `test-jvm-dtest` 默认 `forkmode=once`，节点都在一个 JVM 中；失败后的静态状态清理成本低于多进程，但单个 JVM heap 和 classloader 泄漏风险更高，runner 参数见 `build.xml:1762-1770`。
- `test-simulator-dtest` 默认 `forkmode=perTest` 并固定 8G heap、关闭 tiered/background compilation、限制 compiler count；这是为了 determinism，但会让单个 simulator 测试启动成本较高，见 `build.xml:1783-1805`。
- `IsolatedExecutor.transfer()` 对对象做序列化/反序列化并验证 classloader，适合测试控制面，不适合频繁传输大量数据；实现见 `test/distributed/org/apache/cassandra/distributed/impl/IsolatedExecutor.java:185-260`。
- `ActionSchedule` 同时维护 scheduled、runnable、runnableByDeadline、sequences 和 daemon wave 状态；当 actor/action 数量过多时，调度队列本身会成为测试时间的一部分，见 `test/simulator/main/org/apache/cassandra/simulator/ActionSchedule.java:125-180`。
- CircleCI 依赖 filename timing split；新测试或重命名测试在 timings 不稳定时会造成分片倾斜，分片脚本见 `.circleci/config.yml:237-242` 和 `.circleci/config.yml:707-712`。

## 常见故障

- `NoClassDefFoundError` 或编译失败涉及 `ICluster`、`IInstanceConfig`、`NodeToolResult`、`Versions` 等 dtest API 类型时，优先检查 `dtest-api-*.jar` artifact；`build.xml` 只描述打包该 jar，不在当前源码中提供完整定义，见 `build.xml:1741-1742`。
- simulator 测试没有产生预期 interleaving，先检查是否走 `test-simulator-dtest`、javaagent 和 bootstrap jar 是否加载；`MonitorMethodTransformerTest` 期望 synchronized 方法调用出现不同线程交错，见 `test/simulator/test/org/apache/cassandra/simulator/test/MonitorMethodTransformerTest.java:31-109`。
- dtest nodetool 失败但命令没有退出 JVM，是因为 `Instance.nodetoolResult()` 用临时 `SecurityManager` 把 `System.exit` 转成 return code；应查看 `NodeToolResult.rc/stdout/stderr/latestError`，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:984-1025`。
- Byteman 规则找不到目标类会在 `extractClasses` 后或 transform 阶段失败；helper 要求脚本里至少有 `CLASS ...` 行，见 `test/distributed/org/apache/cassandra/distributed/shared/Byteman.java:174-191`。
- `QueryResult` 行对象被复用；测试若把 `Row` 引用保存到集合里，可能读到后续行数据，应使用 `Row.copy()`，风险说明见 `test/distributed/org/apache/cassandra/distributed/api/QueryResult.java:25-86`。
- simulator determinism 失败时，先记录 seed、simulations、network/clock options；`SimulationRunner.BasicCommand` 的 seed 和多种扰动参数是复现入口，见 `test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java:146-220`。

## 测试用例

- `TrivialSimulationTest.trivialTest()` 演示 3 节点/1 DC simulator cluster，初始化 cluster、建 keyspace/table、执行 insert/select，见 `test/simulator/test/org/apache/cassandra/simulator/test/TrivialSimulationTest.java:40-60`。
- `TrivialSimulationTest.componentTest()` 和 `identityHashMapTest()` 演示 component-level simulator，不启动完整 Cassandra cluster，见 `test/simulator/test/org/apache/cassandra/simulator/test/TrivialSimulationTest.java:62-92`。
- `MonitorMethodTransformerTest` 验证 synchronized 方法和 executor 任务在 simulated scheduler 下出现 interleaving，同时保持临界区语义，见 `test/simulator/test/org/apache/cassandra/simulator/test/MonitorMethodTransformerTest.java:31-109`。
- `ShortPaxosSimulationTest` 通过 `PaxosSimulationRunner.main(...)` 跑短 Paxos simulation，并保留一个被忽略的 self reconcile OOM 用例，见 `test/simulator/test/org/apache/cassandra/simulator/test/ShortPaxosSimulationTest.java:30-44`。
- `CompactionsBytemanTest` 用 BMUnitRunner 注入磁盘空间不足、compaction 计数和停止 compaction 的路径，见 `test/unit/org/apache/cassandra/db/compaction/CompactionsBytemanTest.java:47-61`、`test/unit/org/apache/cassandra/db/compaction/CompactionsBytemanTest.java:80-108`、`test/unit/org/apache/cassandra/db/compaction/CompactionsBytemanTest.java:118-138`、`test/unit/org/apache/cassandra/db/compaction/CompactionsBytemanTest.java:158-180`。
- `DirectIOSegmentBytemanTest` 用 Byteman 让 `FileUtils.getBlockSize()` 返回 0，验证 direct IO 不支持时 commitlog disk access mode 抛配置异常，见 `test/unit/org/apache/cassandra/db/commitlog/DirectIOSegmentBytemanTest.java:39-64`。
- `stream_failure.btm` 是资源脚本示例，在 `StreamSession.prepareAck` 调用 `startStreamingFiles` 前按条件抛出 RuntimeException，用于流式传输失败注入，见 `test/resources/byteman/stream_failure.btm:19-31`。
