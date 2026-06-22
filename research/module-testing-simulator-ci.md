# Testing Simulator And CI Internals

## 范围

本文是测试框架第三轮补充，聚焦当前 checkout 可直接验证的部分：simulator 的确定性执行模型、故障注入、Paxos simulation runner、Ant/Jenkins/CircleCI profile，以及 `dtest-api` 外部构件边界。`module-testing-framework.md` 仍覆盖 CQLTester/in-JVM dtest/upgrade/fuzz 的第一轮模型；`module-testing-internals.md` 覆盖 Ant/JUnit runner、in-JVM isolation、message filter、Byteman 和 simulator javaagent 的第二轮模型。

本轮明确边界：工作区没有 `dtest-api-*.jar` 文件；仓库内只保留 POM 依赖和 `dtest-jar` 打包规则。`dtest-jar` 会从 `${test.lib}/jars` 解压 `dtest-api-*.jar`，见 `build.xml:1741-1742`；POM 模板声明 `org.apache.cassandra:dtest-api:0.0.18` 为 test scope，见 `.build/parent-pom-template.xml:534-539`。因此本文不枚举外部 jar 内完整 API，只记录源码可见的交界面。

## 设计目标

- simulator 的目标是确定性伪随机执行，从代码片段到完整 Cassandra 集群都抽象为 `ActionPlan` 和 `Action`，再由 `ActionSchedule`、`RunnableActionScheduler`、`FutureActionScheduler` 决定执行顺序，见 `test/simulator/main/org/apache/cassandra/simulator/package-info.java:19-29`。
- simulator 通过 simulated systems 和 byte weaving 接管 monitor、blocking queue、thread/executor、random、time、Paxos ballots、network 和 failure detector，并通过 keyspace actions、Nemesis、monitor entry/exit 引入扰动，见 `test/simulator/main/org/apache/cassandra/simulator/package-info.java:48-55`。
- Ant 目标要生成 `simulator-asm.jar` 和 `simulator-bootstrap.jar`，再以 `-javaagent` 与 `-Xbootclasspath/a` 运行 simulator 测试，见 `build.xml:792-820` 和 `build.xml:1783-1805`。
- Paxos simulation 要把 LWT read/write、拓扑变化、Paxos variant 切换、state cache、serial consistency、history checking 和 repair/topology validators 放在同一可复现 seed 下，见 `test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosSimulationRunner.java:32-149` 和 `test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosClusterSimulation.java:74-91`。
- CI 要把同一组 Ant targets 映射到可选择 profile、split、JDK/arch 过滤和 artifact 收集；Jenkins profile 把 `simulator-dtest`、`jvm-dtest`、Python dtest、upgrade dtest 等列为阶段，见 `.jenkins/Jenkinsfile:139-149` 和 `.jenkins/Jenkinsfile:190-219`。

## 解决的问题

- 可复现性：`SimulationRunner.beforeAll()` 固定或替换时钟、JMX、jemalloc、ring delay、Paxos repair timeout、UUID、gossip settle、commitlog sync、directory listing、SSL 等行为，见 `test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java:94-139`。
- 扰动空间：`BasicCommand` 暴露 seed、simulation count、threads、node/DC 范围、key/concurrency、topology changes、run time、read/nemesis/network/clock/scheduler/debug 参数，并把它们传播到 builder，见 `test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java:146-323`。
- 集群组装：`ClusterSimulation` 在 Jimfs root、shared class predicate、class transformer、instance initializer、simulated message delivery、failure detector、snitch、ballots、time 和 future scheduler 上创建 dtest cluster，见 `test/simulator/main/org/apache/cassandra/simulator/ClusterSimulation.java:636-872`。
- 故障注入：`SimulatedFutureActionScheduler` 用 seed 驱动 drop partition、flaky partition、drop/delay/timeout/failure 和 scheduler delay，见 `test/simulator/main/org/apache/cassandra/simulator/systems/SimulatedFutureActionScheduler.java:88-206`。
- CI 一致性：Jenkins 用 profile 和 split map 决定哪些 stage 运行，`simulator-dtest` 只跑一个 split 且 large size，dtest 类 profile 标记为 Python dtest，见 `.jenkins/Jenkinsfile:203-231`。
- 外部 dtest：Jenkins 在 Python dtest 阶段 checkout `cassandra-dtest`，jvm upgrade dtest 阶段按需构建并 stash `dtest*.jar`，见 `.jenkins/Jenkinsfile:495-511`。

## 设计取舍

- 用 byte weaving 换取可控性。`InterceptAgent` 对 `Object`、`Enum`、`Random`、`ThreadLocalRandom`、`ConcurrentHashMap`、locks 做 bootstrap/JDK 类转换，能力强但对 JVM/JDK 参数敏感，见 `test/simulator/asm/org/apache/cassandra/simulator/asm/InterceptAgent.java:73-124`。
- simulator 选择固定 deterministic JVM 参数。package-info 明确要求同 JVM/JDK、固定 `ActiveProcessorCount`、heap、background compilation 和 compiler count，见 `test/simulator/main/org/apache/cassandra/simulator/package-info.java:57-78`；Ant 目标也固定这些参数，见 `build.xml:1793-1803`。
- scheduler 使用模型化网络而不是真 TCP。`SimulatedMessageDelivery` 把 dtest message sink 接到 `InterceptibleThread.interceptMessage`，实际 delivery/timeout/failure 由 simulator scheduler 决定，见 `test/simulator/main/org/apache/cassandra/simulator/systems/SimulatedMessageDelivery.java:28-41` 和 `test/simulator/main/org/apache/cassandra/simulator/systems/SimulatedFutureActionScheduler.java:146-190`。
- Paxos simulation 强制部分配置以扩大安全性检查。`PaxosClusterSimulation` 设置 `paxos_variant`、`paxos_cache_size`、`paxos_state_purging=repaired`、`paxos_on_linearizability_violations=log`，见 `test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosClusterSimulation.java:74-81`。
- CI 生成文件和 profile 文件并存。CircleCI 文档说明 `config.yml` 由模板生成，free/paid 文件控制资源和并行度；直接编辑生成文件容易丢失，见 `.circleci/readme.md:21-47` 和 `.circleci/readme.md:157-160`。

## 核心类

| 类 | 作用 | 证据 |
|---|---|---|
| `SimulationRunner` | simulator CLI、全局 deterministic property、seed/run/record/reconcile 命令 | `test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java:88-139`、`test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java:356-427` |
| `ClusterSimulation` | 在 simulator 中创建 in-JVM Cassandra cluster 和 simulated systems | `test/simulator/main/org/apache/cassandra/simulator/ClusterSimulation.java:116-143`、`test/simulator/main/org/apache/cassandra/simulator/ClusterSimulation.java:627-872` |
| `ActionPlan` | 把 pre/interleave/post 三阶段交给 `ActionSchedule` | `test/simulator/main/org/apache/cassandra/simulator/ActionPlan.java:35-89` |
| `ActionSchedule` | 管理 scheduled/runnable queues、ordering、daemon waves 和执行模式 | `test/simulator/main/org/apache/cassandra/simulator/ActionSchedule.java:60-180` |
| `RunnableActionScheduler` | 给 runnable action 生成 priority，支持 sequential/uniform/random walk | `test/simulator/main/org/apache/cassandra/simulator/RunnableActionScheduler.java:27-140` |
| `SimulatedFutureActionScheduler` | 模拟网络 delivery、timeout、failure 和 scheduler delay | `test/simulator/main/org/apache/cassandra/simulator/systems/SimulatedFutureActionScheduler.java:39-206` |
| `SimulatedTime` | 提供禁用/代理/全局模拟时钟，禁止非 simulator 线程取真实时间 | `test/simulator/main/org/apache/cassandra/simulator/systems/SimulatedTime.java:139-163` |
| `Failures` | 收集 throwable、chunk cache leak、Ref leak 等失败信号 | `test/simulator/main/org/apache/cassandra/simulator/systems/Failures.java:29-70` |
| `PaxosSimulationRunner` | Paxos simulation CLI，增加 consistency、state cache、variant 切换 | `test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosSimulationRunner.java:32-149` |
| `PaxosSimulation` | Paxos action runner、liveness check、history failure logging 和 cleanup | `test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosSimulation.java:61-280` |
| `HistoryChecker` | 每个 primary key 的线性化 witness/event/time interval 检查 | `test/simulator/main/org/apache/cassandra/simulator/paxos/HistoryChecker.java:40-349` |
| `PaxosRepairValidator` / `PaxosTopologyChangeVerifier` | repair/topology 之后验证 quorum 持久化 ballot/commit 语义 | `test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosRepairValidator.java:28-101`、`test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosTopologyChangeVerifier.java:28-113` |

## 核心接口

- `Simulation` 是 simulator 最小接口，只要求 `iterator()` 和 `run()`，并继承 `AutoCloseable`，见 `test/simulator/main/org/apache/cassandra/simulator/Simulation.java:23-27`。
- `ClusterSimulation.SimulationFactory` 把 `SimulatedSystems`、`RunnableActionScheduler`、`Cluster` 和 topology options 转成具体 simulation，见 `test/simulator/main/org/apache/cassandra/simulator/ClusterSimulation.java:132-140`。
- `FutureActionScheduler` 由 `SimulatedFutureActionScheduler` 实现，用于 message delivery、timeout、failure 和 scheduler delay 决策，见 `test/simulator/main/org/apache/cassandra/simulator/systems/SimulatedFutureActionScheduler.java:39-206`。
- `IMessageSink` 是 simulator 接入 dtest cluster message delivery 的桥；`SimulatedMessageDelivery` 在构造时 `cluster.setMessageSink(this)`，见 `test/simulator/main/org/apache/cassandra/simulator/systems/SimulatedMessageDelivery.java:28-41`。
- `ClusterActionListener.RepairValidator` 和 `TopologyChangeValidator` 是 Paxos simulator 验证 repair/topology side effect 的接口落点，见 `test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosRepairValidator.java:21-29` 和 `test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosTopologyChangeVerifier.java:21-29`。

## 核心数据结构

- `ActionPlan.pre/interleave/post`：pre/post 严格顺序，interleave 中的 action list 可随机交错；`iterator()` 转成 `ActionSchedule.Work`，见 `test/simulator/main/org/apache/cassandra/simulator/ActionPlan.java:37-69`。
- `ActionSchedule.Work`：绑定 mode、runForNanos 和 actors；mode 包括 `TIME_LIMITED`、`STREAM_LIMITED`、`TIME_AND_STREAM_LIMITED`、`FINITE`、`UNLIMITED`，见 `test/simulator/main/org/apache/cassandra/simulator/ActionSchedule.java:76-102`。
- `NetworkConfig.PhaseConfig`：normal/flaky 阶段分别持有 drop/delay chance 和 normal/delay latency；外层还包含 partition/flaky chance 与 reconfigure interval，见 `test/simulator/main/org/apache/cassandra/simulator/systems/NetworkConfig.java:24-54`。
- `SimulatedFutureActionScheduler.Network/Scheduler`：把 `NetworkConfig` 和 `SchedulerConfig` 编译成 per-link latency、drop/delay decision 和 long-delay decision，见 `test/simulator/main/org/apache/cassandra/simulator/systems/SimulatedFutureActionScheduler.java:41-65`。
- `HistoryChecker.Event`：记录 event id、position、witness sequence、visibleBy/visibleUntil 和成功/未知/失败结果，见 `test/simulator/main/org/apache/cassandra/simulator/paxos/HistoryChecker.java:89-109`。
- `PaxosClusterSimulation.Builder`：保存 initial/final Paxos variant、state cache 和 serial consistency，见 `test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosClusterSimulation.java:34-72`。
- CI profile map：Jenkins 的 `pipelineProfiles()` 和 `testSteps` 是 stage/split/size/timeout 的事实来源，见 `.jenkins/Jenkinsfile:139-149` 和 `.jenkins/Jenkinsfile:190-219`。

## 生命周期

```text
Ant simulator test
  -> simulator-asm-build
  -> simulator-bootstrap-build
  -> simulator-jars
  -> build-test compiles simulator main/asm/bootstrap/test
  -> test-simulator-dtest forks per test with javaagent/bootstrap jar
```

`simulator-asm-build` 和 `simulator-bootstrap-build` 编译 ASM/bootstrap 源，见 `build.xml:667-708`；`simulator-jars` 生成 javaagent jar 和 bootstrap jar，见 `build.xml:792-820`；`test-simulator-dtest` 指向 `test/simulator/test` 并设置 strict determinism、javaagent、bootclasspath 和 JVM 编译参数，见 `build.xml:1783-1805`。

```text
CLI simulation
  -> PaxosSimulationRunner.main(args)
  -> Cli parses run/record/reconcile/help
  -> SimulationRunner.beforeAll()
  -> BasicCommand.propagate(builder)
  -> builder.create(seed)
  -> ClusterSimulation creates dtest Cluster + SimulatedSystems
  -> PaxosSimulation.run() drains ActionPlan iterator
```

`PaxosSimulationRunner.main()` 创建 builder、解析命令并调用 run/record/reconcile，见 `test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosSimulationRunner.java:129-149`。`SimulationRunner.Run` 打印 seed、创建 cluster、执行 `cluster.simulation.run()`，失败时抛 `SimulationException(seed, ...)`，见 `test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java:325-379`。

```text
CI execution
  -> Jenkins/CircleCI builds jar
  -> test profile selects simulator-dtest/jvm-dtest/dtest
  -> stage fetches source or unstashes jar
  -> Ant target runs tests
  -> output/logs/JUnit XML are archived
```

Jenkins `jar` stage 并行构建并 stash，`Tests` stage 按 `tasks()` 并行运行，见 `.jenkins/Jenkinsfile:96-115`。CircleCI 的 `j11_simulator_dtests` job 调用 `ant test-simulator-dtest -Dno-build-test=true` 并存储 `build/test/output` 与 `build/test/logs`，见 `.circleci/config.yml:5043-5113`。

## 调用链

- simulator 全局设置：`SimulationRunner.beforeAll()` -> 设置 `CLOCK_*`、JMX、ring delay、Paxos repair timeout、UUID、gossip、commitlog、directory listing、SSL -> reset `InterceptorOfGlobalMethods`，见 `test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java:94-139`。
- 参数传播：`BasicCommand.run()` -> `propagate(builder)` -> parse network/scheduler/clock/topology/debug/capture options -> seed loop -> `run(seed, builder)`，见 `test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java:255-353`。
- 集群构造：`PaxosClusterSimulation.Builder.create(seed)` -> `new PaxosClusterSimulation(...)` -> `ClusterSimulation` superclass -> `Cluster.build(numOfNodes).withRoot(fs).withConfig(...).withInstanceInitializer(...).withClassTransformer(...)`，见 `test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosClusterSimulation.java:66-91` 和 `test/simulator/main/org/apache/cassandra/simulator/ClusterSimulation.java:741-848`。
- 网络调度：dtest message sink -> `SimulatedMessageDelivery.accept()` -> `InterceptibleThread.interceptMessage(...)` -> `FutureActionScheduler.shouldDeliver/messageDeadlineNanos/messageTimeoutNanos/messageFailureNanos`，见 `test/simulator/main/org/apache/cassandra/simulator/systems/SimulatedMessageDelivery.java:37-41` 和 `test/simulator/main/org/apache/cassandra/simulator/systems/SimulatedFutureActionScheduler.java:146-185`。
- action 执行：`ActionPlan.iterator()` -> `ActionSchedule` -> action schedule/setupOrdering -> scheduled/runnable queues -> consequence/daemon/sequence handling，见 `test/simulator/main/org/apache/cassandra/simulator/ActionPlan.java:64-69` 和 `test/simulator/main/org/apache/cassandra/simulator/ActionSchedule.java:181-230`。
- Paxos history：operation start increments logical clock -> query callback calls `verify(new Observation(...))` -> `HistoryChecker.witness/applied` updates event ordering and visible intervals -> violation throws `HistoryViolation(primaryKey, ...)`，见 `test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosSimulation.java:65-103` 和 `test/simulator/main/org/apache/cassandra/simulator/paxos/HistoryChecker.java:130-182`。
- Jenkins Python dtest：test step marked `python-dtest` -> `fetchDTestsSource()` checkout `cassandra-dtest` into `build/cassandra-dtest` -> command receives `cassandra_dtest_dir`，见 `.jenkins/Jenkinsfile:229-231` 和 `.jenkins/Jenkinsfile:495-501`。
- CircleCI JVM dtest：job globs `test/distributed/**/*.java` -> split by filename timings -> `ant testclasslist ... -Dtest.classlistprefix=distributed`，见 `.circleci/config.yml:7499-7565`。

## 配置项

- `simulator.asm.print` 默认 `none`，支持 class/method summary/detail/ASM 输出，见 `build.xml:1783-1784`。
- `test-simulator-dtest` 设置 `-Dcassandra.test.simulator.determinismcheck=strict` 和 `-Dcassandra.test.simulator.print_asm=${simulator.asm.print}`，见 `build.xml:1790-1795`。
- simulator CLI 支持 `--seed`、`--simulations`、`--threads`、`--nodes`、`--dcs`、`--within-key-concurrency`、`--concurrency`、`--cluster-actions`、`--run-time`、`--reads`、`--nemesis` 等，见 `test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java:146-190`。
- 网络扰动参数包括 `--network-flaky-chance`、`--network-partition-chance`、`--network-drop-chance`、`--network-delay-chance`、latency/delay ranges 和 flaky variants，见 `test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java:193-215`。
- clock/scheduler 参数包括 `--clock-drift`、`--clock-discontinuity-interval`、`--scheduler-jitter`、`--scheduler-delay-chance`、`--scheduler-delay`、`--scheduler-long-delay`，见 `test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java:217-229`。
- Paxos runner 增加 `--consistency`、`--with-paxos-state-cache`、`--without-paxos-state-cache`、`--variant`、`--to-variant`，见 `test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosSimulationRunner.java:34-59`。
- Jenkins parameters 包括 repository、branch、profile、custom regexp、architecture、JDK、dtest repository/branch，见 `.jenkins/Jenkinsfile:73-84`。
- CircleCI 环境变量包括 `DTEST_REPO`、`DTEST_BRANCH`、`REPEATED_SIMULATOR_DTESTS`、`REPEATED_SIMULATOR_DTESTS_COUNT` 等，见 `.circleci/config.yml:5115-5139`；readme 也列出 repeated simulator tests 的生成参数，见 `.circleci/readme.md:71-108`。

## Metrics

simulator 自身不走生产 metrics 采样作为主要判据，更多依赖可复现 seed、failure collector、history checker、liveness check 和日志。

- `Failures` 聚合 throwable、chunk cache leak 和 `Ref` leak，供 simulation 在 `isDone()` 或异常路径统一失败，见 `test/simulator/main/org/apache/cassandra/simulator/systems/Failures.java:32-70`。
- `PaxosSimulation` 在启用 `TEST_SIMULATOR_LIVENESS_CHECK` 时启动 `SimulationLiveness` 定时任务；如果 counter 停滞，会记录 stall 并触发失败，见 `test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosSimulation.java:131-178`。
- `ClusterSimulation` 给实例安装 `PaxosPrepare.setOnLinearizabilityViolation`、buffer pool leak debug、`Ref.setOnLeak`，这些相当于测试时的 correctness probes，见 `test/simulator/main/org/apache/cassandra/simulator/ClusterSimulation.java:823-841`。
- CI 侧的可观测输出是 JUnit XML、stdout 和 log artifacts；CircleCI simulator job 存储 `build/test/output` 和 `build/test/logs`，见 `.circleci/config.yml:5106-5113`。

## 日志

- `test/conf/logback-simulator.xml` 为每个 cluster/instance 写 `build/test/logs/${cassandra.testtag}/${suitename}/${cluster_id}/${instance_id}/system.log`，见 `test/conf/logback-simulator.xml:26-32`。
- simulator stdout 过滤到 WARN 级别，pattern 包含 thread、instance id、UTC timestamp、file/line 和 message，见 `test/conf/logback-simulator.xml:34-40`。
- `ClusterSimulation` 在构造完成时输出 seed 和 randomized config，包括 nodes、dcs、RF、memtable、clock sequence、network scheduler、runnable scheduler、topology change sequence，见 `test/simulator/main/org/apache/cassandra/simulator/ClusterSimulation.java:676-724` 和 `test/simulator/main/org/apache/cassandra/simulator/ClusterSimulation.java:866-871`。
- `HistoryChecker.print()` 在 failure path 输出每个 event 的 visibleBy/visibleUntil、witness sequence 和 log，见 `test/simulator/main/org/apache/cassandra/simulator/paxos/HistoryChecker.java:311-323`。
- Jenkins 为每个 stage 生成压缩 stage log 路径，见 `.jenkins/Jenkinsfile:355-360` 和 `.jenkins/Jenkinsfile:417-417`。

## 运维关注点

- 本地复现 simulator 失败时，第一优先级是保留 seed、JDK/JVM 参数、`--simulations`、network/clock/scheduler 参数；`SimulationException` 会携带 seed，见 `test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java:359-378`。
- 手动跑 simulator 不应只执行普通 JUnit；package-info 明确要求先 `ant simulator-jars` 并带上 `-javaagent`、`-Xbootclasspath/a` 和 simulator logback，见 `test/simulator/main/org/apache/cassandra/simulator/package-info.java:57-62`。
- `dtest-api-*.jar` 缺失时不要把完整外部 API 结论写入源码知识库；只能引用当前可见 API 子集和 `dtest-jar`/POM 的外部边界，见 `build.xml:1741-1742` 和 `.build/cassandra-build-deps-template.xml:85-88`。
- Jenkins 不是单纯运行当前 Jenkinsfile：k8s JCasC 为 trunk、cassandra-6.0、cassandra-5.0 分别配置 pipeline job，scriptPath 都指向 `.jenkins/Jenkinsfile`，见 `.jenkins/k8s/jenkins-deployment.yaml:78-129`。
- CircleCI `config.yml` 是生成物；变更长期 CI 行为应改模板并重新生成，而不是只改当前 `config.yml`，见 `.circleci/readme.md:21-47` 和 `.circleci/readme.md:157-160`。

## 性能瓶颈

- `test-simulator-dtest` 使用 `forkmode=perTest`，有 8G heap、javaagent、bootstrap classpath 和固定 compiler 参数；单个测试启动成本高于普通 unit test，见 `build.xml:1784-1804`。
- `ClusterSimulation` 为每个 seed 构建 Jimfs、class transformer、多个 isolated instance、thread allocator、snitch、failure detector、simulated systems 和 scheduler；构造成本集中在 `ClusterSimulation` constructor，见 `test/simulator/main/org/apache/cassandra/simulator/ClusterSimulation.java:636-872`。
- `ActionSchedule` 维护 ordering sequences、scheduled/runnable priority queues、daemon waves 和 work iterator；action 数量和 consequence fanout 会直接放大调度成本，见 `test/simulator/main/org/apache/cassandra/simulator/ActionSchedule.java:125-180`。
- `HistoryChecker` 对每个 primary key 维护 by-id 和 by-position event 数组，长时间高并发 Paxos simulation 会积累 witness log 和 event state，见 `test/simulator/main/org/apache/cassandra/simulator/paxos/HistoryChecker.java:89-130`。
- Jenkins split 数量说明 dtest 是主要成本中心：`dtest` 64 splits，`dtest-upgrade` 128 splits，而 `simulator-dtest` 只有 1 split 但 large size，见 `.jenkins/Jenkinsfile:203-215`。

## 常见故障

- `dtest-api` 类型缺失：检查 `test/lib/jars` 或构建依赖是否提供 `dtest-api-*.jar`；源码只证明外部依赖和打包路径存在，见 `build.xml:1741-1742` 和 `.build/parent-pom-template.xml:534-539`。
- simulator 没有预期 interleaving：检查是否通过 `test-simulator-dtest` 加载 `simulator-asm.jar` 和 `simulator-bootstrap.jar`；`MonitorMethodTransformerTest` 期望 synchronized 方法和 executor 任务出现 interleaving，见 `test/simulator/test/org/apache/cassandra/simulator/test/MonitorMethodTransformerTest.java:31-109`。
- 使用真实时间导致 failure：`SimulatedTime.Delegating.check()` 只允许 intercepting thread 或少数 permitted thread 使用时间，否则抛 `IllegalStateException("Using time is not allowed during simulation")`，见 `test/simulator/main/org/apache/cassandra/simulator/systems/SimulatedTime.java:139-154`。
- Paxos linearizability violation：`HistoryChecker.fail()` 会抛 `HistoryViolation(primaryKey, ...)`，`PaxosSimulation.logAndThrow()` 会按 primary key dump 对应历史，见 `test/simulator/main/org/apache/cassandra/simulator/paxos/HistoryChecker.java:325-349` 和 `test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosSimulation.java:247-265`。
- ignored self reconcile：`ShortPaxosSimulationTest.selfReconcileTest()` 标记为 OOM DirectMemory 待查，说明 self reconcile 不是当前稳定 smoke path，见 `test/simulator/test/org/apache/cassandra/simulator/test/ShortPaxosSimulationTest.java:38-43`。
- CI profile 误用：Jenkins `simulator-dtest` 被限制到 default JDK；axis filter 排除非默认 JDK 的 cqlsh-test、simulator-dtest 和 upgrade dtest，见 `.jenkins/Jenkinsfile:251-258`。

## 测试用例

- `ShortPaxosSimulationTest.simulationTest()` 直接调用 `PaxosSimulationRunner.main("run", "-n", "3..6", "-t", "1000", "-c", "2", "--cluster-action-limit", "2", "-s", "30", "--simulations", DEFAULT_ITERATIONS)`，见 `test/simulator/test/org/apache/cassandra/simulator/test/ShortPaxosSimulationTest.java:30-36`。
- `TrivialSimulationTest.trivialTest()` 创建 3 节点/1 DC simulator cluster，初始化 cluster、建 keyspace/table、执行 insert/select，见 `test/simulator/test/org/apache/cassandra/simulator/test/TrivialSimulationTest.java:40-60`。
- `TrivialSimulationTest.componentTest()` 和 `identityHashMapTest()` 覆盖不启动完整 Cassandra cluster 的 component-level simulator，见 `test/simulator/test/org/apache/cassandra/simulator/test/TrivialSimulationTest.java:62-92`。
- `MonitorMethodTransformerTest` 覆盖 synchronized method 和 executor submission 在 simulated scheduler 下的 interleaving 语义，见 `test/simulator/test/org/apache/cassandra/simulator/test/MonitorMethodTransformerTest.java:30-109`。
- `SimulationTestBase` 是这些测试的共享 harness：`simulate()` 调用 `SimulationRunner.beforeAll()`、创建 `ClusterSimulation`、按 seed/iteration 运行 simulation，见 `test/simulator/test/org/apache/cassandra/simulator/test/SimulationTestBase.java:147-203`。
- CircleCI repeated test 文档允许通过 `REPEATED_SIMULATOR_DTESTS=org.apache.cassandra.simulator.test.TrivialSimulationTest` 重复 simulator 测试，见 `.circleci/readme.md:94-108` 和 `.circleci/readme.md:122-150`。
