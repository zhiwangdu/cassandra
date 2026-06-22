# Module: Startup Ordered Log Marker Matrix

## 范围

本模块补齐 `startup_cold_log_marker_gap` 的源码侧知识库：哪些 cold-start checkpoint 有稳定源码顺序，哪些 checkpoint 只有间接日志/JMX 证据，哪些当前没有完整 ordered E2E 测试。它扩展 `research/module-startup-cold-start-integration-matrix.md`，不替代 daemon lifecycle、failure policy 或 native transport 的既有分析。

核心结论：当前源码可以明确推导 `CassandraDaemon.setup()` 与 `activate()->start()` 的顺序，但测试覆盖仍是分散的。仓库没有一个 test 从同一个 cold-start run 中按顺序断言 JMX setup/startup checks、`StorageServiceMBean` publish、auth setup、native transport listen 和 `Startup complete`。

## 场景矩阵

| 场景 ID | 源码/测试锚点 | 设计语义 |
|---|---|---|
| `startup_marker_jmx_before_checks` | `src/java/org/apache/cassandra/service/CassandraDaemon.java:246-258`、`src/java/org/apache/cassandra/service/StartupChecks.java:310-330` | daemon `setup()` 先 `maybeInitJmx()`，后 `runStartupChecks()`；startup checks 本身也会报告 JMX port 配置。 |
| `startup_marker_preflight_before_system_writes` | `src/java/org/apache/cassandra/service/CassandraDaemon.java:262-281`、`src/java/org/apache/cassandra/service/StartupChecks.java:176-189` | `CommitLog.instance.start()` 后立即执行 startup checks，随后才 snapshot/version-change 和 `SystemKeyspace.persistLocalMetadata()`。 |
| `startup_marker_schema_storage_before_mbean` | `src/java/org/apache/cassandra/service/CassandraDaemon.java:286-383`、`src/java/org/apache/cassandra/service/StorageService.java:1017` | schema、virtual keyspaces、data directory scrub、commitlog replay、repair/stream internals 和 prepared preload 完成后，daemon 注册并进入 `StorageService.initServer()` 注册 MBeans。 |
| `startup_marker_mbean_during_bootstrap` | `src/java/org/apache/cassandra/service/StorageService.java:966-1036`、`test/distributed/org/apache/cassandra/distributed/test/ring/BootstrapTest.java:387-416` | `registerMBeans()` 在 `prepareToJoin()`/bootstrap 前执行；distributed test 在 bootstrap latch 中通过 JMX 读取 `JOINING`。 |
| `startup_marker_auth_before_transport` | `src/java/org/apache/cassandra/service/CassandraDaemon.java:403-448`、`src/java/org/apache/cassandra/service/StorageService.java:1442-1488`、`test/distributed/org/apache/cassandra/distributed/test/AuthTest.java:54-69` | gossip settle 后调用 `doAuthSetup(false)`，并在 `initializeClientTransports()` 和 `start()` 前完成；测试轮询 `authSetupCalled()`。 |
| `startup_marker_complete_setup_before_start` | `src/java/org/apache/cassandra/service/CassandraDaemon.java:443-454`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:585-593` | daemon setup 尾部先 initialize transports、warm auth caches、start Paxos auto repairs，再 `completeSetup()` 翻转 failure policy marker。 |
| `startup_marker_transport_gate_before_listen` | `src/java/org/apache/cassandra/service/CassandraDaemon.java:643-671`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:783-825`、`test/distributed/org/apache/cassandra/distributed/test/BootstrapBinaryDisabledTest.java:121-147` | `start()` 先 block-for-peers 和 `validateTransportsCanStart()`，只有 bootstrap/write-survey gate 通过后才 start client transports。 |
| `startup_marker_listen_before_rpc_ready` | `src/java/org/apache/cassandra/service/NativeTransportService.java:130-135`、`src/java/org/apache/cassandra/transport/PipelineConfigurator.java:146-149`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:809-825`、`src/java/org/apache/cassandra/service/StorageService.java:3080-3096` | native server bind/listen 发生在 `NativeTransportService.start()` 内；daemon 在 service start 后发布 `RPC_READY=true`。 |
| `startup_marker_startup_complete_after_start` | `src/java/org/apache/cassandra/service/CassandraDaemon.java:725-744` | `activate()` 在 `setup()` 和 `start()` 都返回后记录 `Startup complete`；如果 `start()` 因 transport gate warning return，仍会记录 daemon startup complete。 |
| `startup_marker_stop_deactivate_inverse` | `src/java/org/apache/cassandra/service/CassandraDaemon.java:675-699`、`src/java/org/apache/cassandra/transport/Server.java:184-203`、`test/distributed/org/apache/cassandra/distributed/test/NodeToolEnableDisableBinaryTest.java:134-152` | stop/disablebinary 先停止 native transport，再发布 `RPC_READY=false`；nodetool test 验证 stop/start 用户可见文本和 connectivity。 |
| `startup_marker_injvm_dtest_order_divergence` | `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:581-763` | in-JVM dtest startup 手动镜像 daemon order，但在 optional native protocol start 前后都调用 `completeSetup()`；ordered marker E2E 需要区分 production daemon 与 dtest harness。 |
| `startup_marker_ordered_e2e_gap` | `research/tools/check-startup-ordered-marker-drift.py` negative scan | 当前没有 test 在同一个 cold-start run 中同时断言 `Startup complete`、`Starting listening for CQL clients`、`StorageServiceMBean`/auth setup 和 log watch/grep 顺序。 |

## 设计目标

- 把启动时“可观察日志 marker”和“真实状态 checkpoint”分开，避免把 `Startup complete` 误读成 CQL listener 已开放。
- 为未来 ordered cold-start E2E test 给出明确断言顺序和 source anchors。
- 保护现有测试分散覆盖边界：JMX during bootstrap、auth setup、bootstrap binary gate、enable/disable binary。
- 记录 in-JVM dtest startup 与 production daemon startup 的顺序差异，避免把 dtest harness 行为直接当作 daemon log order。

## 解决的问题

- 早期 JMX 可观测性和 startup checks 顺序容易混淆。`CassandraDaemon.setup()` 中 `maybeInitJmx()` 位于 `runStartupChecks()` 之前，而 `StartupChecks.checkJMXPorts` 只是检查 JMX 配置，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:246-262` 和 `src/java/org/apache/cassandra/service/StartupChecks.java:310-330`。
- `StorageServiceMBean` publish 不是 `StorageService.initServer()` 的尾部动作。`registerMBeans()` 在 shutdown hook 之后、`prepareToJoin()` 之前执行，见 `src/java/org/apache/cassandra/service/StorageService.java:966-1028`。
- `Startup complete` 不是 CQL listener 成功 bind 的唯一证据。`CassandraDaemon.start()` 捕获 transport validation failure 后只 warning 并 return，`activate()` 之后仍记录 `Startup complete`，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:643-660`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:725-744`。
- native transport 的用户可见 listen 日志来自 `PipelineConfigurator.initializeChannel()`，不是 daemon；源码文本是 `Starting listening for CQL clients on ...`，见 `src/java/org/apache/cassandra/transport/PipelineConfigurator.java:146-149`。
- dtest startup harness 不完全等同于 production daemon。`Instance.startup()` 在 native protocol start 前后都调用 `CassandraDaemon.getInstanceForTesting().completeSetup()`，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:743-763`。

## 设计取舍

- 使用日志 marker 做 E2E 断言直观，但 marker 分布在 `CassandraDaemon`、`StorageService`、`NativeTransportService`、`PipelineConfigurator` 和 tests helper 之间；必须配合 state/JMX assertions 才能说明真实 readiness。
- `Startup complete` 放在 `activate()` 末尾，便于 operator 识别 daemon 启动流程结束；但当 native transport 被配置关闭或 bootstrap gate 拦截时，它不代表 CQL 可用。
- JMX early publish 改善 bootstrap 诊断，但也意味着一个 ordered test 不能简单假设 MBean publish 发生在所有 storage setup 完成后。
- in-JVM dtest 为了控制 classloader、network/gossip/native protocol feature flags，会拆解 daemon setup；ordered marker E2E 如果跑在 dtest 中，应断言它验证的是 dtest startup order 还是 production daemon order。

## 核心类

| 类 | 作用 |
|---|---|
| `CassandraDaemon` | production daemon setup/start/activate 主顺序、`completeSetup()` marker、native transport gate 和 `Startup complete` 日志。 |
| `StartupChecks` | default preflight check 执行和 post-action 顺序，包含 JMX port、data dirs、SSTable format 等 check。 |
| `StorageService` | daemon delegate、MBean publish、join/bootstrap、auth setup 和 `RPC_READY` app state。 |
| `NativeTransportService` | native protocol server list 初始化和 start/stop lifecycle。 |
| `PipelineConfigurator` | Netty bind 前记录 `Starting listening for CQL clients on ...`。 |
| `Server` | transport close 时记录 `Stop listening for CQL clients`。 |
| `Instance` | in-JVM distributed startup harness，手动镜像 daemon order 并提供 logs API。 |

## 核心接口

- `CassandraDaemon.setup()`：production daemon cold-start source order。
- `CassandraDaemon.start()`：peer connectivity、transport validation 和 client transport start。
- `CassandraDaemon.completeSetup()` / `setupCompleted()`：failure policy boundary marker。
- `StorageService.registerMBeans()`：`StorageServiceMBean` JMX publish point。
- `StorageService.doAuthSetup(boolean)`：auth backend setup and cache registration readiness。
- `StorageService.setRpcReady(boolean)`：native transport readiness gossip app state。
- `LogAction.mark()` / `watchFor()` / `grep()`：distributed tests 的 log observation API。

## 核心数据结构

- `CassandraDaemon.setupCompleted`：startup-vs-runtime failure policy marker。
- `CassandraDaemon.nativeTransportService`：`initializeClientTransports()` 构造、`startNativeTransport()` 读取的 volatile service。
- `StorageService.daemon`：JMX/nodetool binary transport delegate。
- `StorageService.authSetupCalled` / `authSetupComplete`：auth setup readiness 的 test-visible state。
- `ApplicationState.RPC_READY`：CQL transport readiness 的 gossip signal。
- `LogAction` mark offset：future ordered marker E2E 应从 startup 前或 restart 前 mark，避免命中过往日志。

## 生命周期

```text
Production CassandraDaemon.activate()
  -> applyConfig()
  -> registerNativeAccess()
  -> setup()
     -> maybeInitJmx()
     -> logSystemInfo()
     -> CommitLog.instance.start()
     -> runStartupChecks()
        -> StartupChecks.verify()
        -> each StartupCheck.execute()
        -> each StartupCheck.postAction()
     -> SystemKeyspace.snapshotOnVersionChange()
     -> SystemKeyspace.persistLocalMetadata()
     -> Schema.instance.loadFromDisk()
     -> setupVirtualKeyspaces()
     -> scrubDataDirectories()
     -> Keyspace.open(...) and disableAutoCompaction()
     -> load row/key cache
     -> CommitLog.recoverSegmentsOnDisk()
     -> ActiveRepairService.start()
     -> StreamManager.start()
     -> QueryProcessor.preloadPreparedStatements()
     -> StorageService.registerDaemon(this)
     -> StorageService.initServer()
        -> log Cassandra/Git/CQL/native protocol versions
        -> registerMBeans()
        -> prepareToJoin()
        -> joinTokenRing() or not-join path
        -> completeInitialization()
     -> Gossiper.waitToSettle()
     -> StorageService.doAuthSetup(false)
     -> reload stores and maybe enable autocompaction
     -> initializeClientTransports()
     -> AuthCacheService.warmCaches()
     -> PaxosState.startAutoRepairs()
     -> completeSetup()
  -> start()
     -> StartupClusterConnectivityChecker.execute()
     -> validateTransportsCanStart()
     -> startClientTransports()
        -> startNativeTransport()
           -> NativeTransportService.start()
           -> PipelineConfigurator logs "Starting listening..."
           -> StorageService.setRpcReady(true)
  -> logger.info("Startup complete")
```

In-JVM dtest startup:

```text
Instance.startup()
  -> optional startJmx()
  -> DatabaseDescriptor.daemonInitialization()
  -> CassandraDaemon.runStartupChecks()
  -> SystemKeyspace.persistLocalMetadata(config::hostId)
  -> Schema.loadFromDisk()
  -> setupVirtualKeyspaces()
  -> CommitLog.recoverSegmentsOnDisk()
  -> MessagingService.listen() or mock messaging
  -> StorageService.registerDaemon(CassandraDaemon.getInstanceForTesting())
  -> StorageService.initServer() if GOSSIP
  -> Gossiper.waitToSettle()
  -> populateTokenMetadata()
  -> CassandraDaemon.completeSetup()
  -> if NATIVE_PROTOCOL:
     -> initializeClientTransports()
     -> start()
  -> ActiveRepairService.start()
  -> StreamManager.start()
  -> PaxosState.startAutoRepairs()
  -> CassandraDaemon.completeSetup()
```

## 配置项

| 配置项 / feature | 定义位置 | 影响 |
|---|---|---|
| `start_native_transport` | `src/java/org/apache/cassandra/config/Config.java:278`、`conf/cassandra.yaml:1018-1020` | 关闭时 `startClientTransports()` 不 bind CQL，但 `Startup complete` 仍可能出现。 |
| `cassandra.start_native_transport` | `src/java/org/apache/cassandra/service/CassandraDaemon.java:665-671` | system property override native transport auto-start。 |
| `block_for_peers_timeout_in_secs` / `block_for_peers_in_remote_dcs` | `src/java/org/apache/cassandra/config/Config.java:675-695` | `start()` 中 peer connectivity wait 的时间和 DC 范围。 |
| `Feature.JMX` | `test/distributed` cluster config | dtest 是否启动 isolated JMX，决定是否能测试 `StorageServiceMBean` publish。 |
| `Feature.NATIVE_PROTOCOL` | `test/distributed` cluster config | dtest 是否执行 `initializeClientTransports()` 和 `start()`。 |
| `TEST_WRITE_SURVEY` / `auto_bootstrap` | `CassandraRelevantProperties` / cluster config | 影响 bootstrap/write-survey native transport gate。 |

## Metrics

- 本矩阵聚焦 startup marker，不新增 runtime metric。
- `ApplicationState.RPC_READY` 是最接近 native transport readiness 的 distributed signal，`StorageService.setRpcReady(true)` 写入，见 `src/java/org/apache/cassandra/service/StorageService.java:3080-3096`。
- future E2E test 应同时读取 logs、JMX state 和 connectivity；只看 metric 或单个 log line 不能证明完整顺序。

## 日志

| Marker | 源码位置 | 注意事项 |
|---|---|---|
| `JMX is enabled to receive remote connections...` / JMX warning | `src/java/org/apache/cassandra/service/StartupChecks.java:310-330` | 这是 startup check 对 JMX 配置的日志，不是 `maybeInitJmx()` 成功日志。 |
| `Cassandra version` / `Git SHA` / `Native protocol supported versions` | `src/java/org/apache/cassandra/service/StorageService.java:966-978` | 出现在 `initServer()` 早段，MBean publish 前。 |
| `Starting listening for CQL clients on ...` | `src/java/org/apache/cassandra/transport/PipelineConfigurator.java:146-149` | 只有 native transport gate 通过并实际 bind 时出现。 |
| `Startup complete` | `src/java/org/apache/cassandra/service/CassandraDaemon.java:742-744` | daemon activate 末尾 marker，不单独证明 CQL listener 已开放。 |
| `Stop listening for CQL clients` | `src/java/org/apache/cassandra/transport/Server.java:184-203` | disablebinary/stop path marker。 |
| bootstrap/write-survey warnings | `src/java/org/apache/cassandra/service/CassandraDaemon.java:651-660`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:783-807` | 说明 `start()` 没有继续 start transports。 |

## 运维关注点

- 排查“Startup complete 但无法 CQL 连接”时，先找是否有 `Starting listening for CQL clients`；若没有，看 `Not starting native transport...`、bootstrap incomplete 或 write survey gate warning。
- JMX 能查 `StorageServiceMBean` 不代表节点已完成 bootstrap；bootstrap 中 JMX 可见是设计目标。
- `completeSetup()` 是 failure policy boundary，不是日志 marker；要从源码/JMX/test state 推断，不能从普通日志直接观察。
- dtest log order 和 production daemon log order不完全一致，尤其是 `completeSetup()` 和 optional native protocol start。

## 性能瓶颈

- Ordered marker E2E 可能被 cache load、commitlog replay、schema load、bootstrap streaming、peer warmup 和 auth cache warmup 拉长；测试应使用 bounded wait 和 precise log marks。
- `StartupClusterConnectivityChecker` 在 CQL listener 前运行，远端 DC wait 会推迟 listen marker。
- JMX startup 和 startup checks 是 early blockers；JMX server creation failure 会 `exitOrFail()`，startup checks failure 也会终止 setup。

## 常见故障

- 缺少 `Starting listening for CQL clients`：检查 `start_native_transport`、bootstrap complete、write survey、auth enabled 和 bind failure。
- `Startup complete` 出现但 `RPC_READY` 未发布：通常是 native transport未启动或 `start()` gate return；`Startup complete` 不是 `RPC_READY=true` 的替代。
- `StorageServiceMBean` bootstrap 中不可见：检查 dtest 是否启用 `Feature.JMX`、`registerMBeans()` 是否在 `prepareToJoin()` 前执行。
- Ordered marker test 偶发：可能是 test 从旧 log offset grep，或同时混用 dtest harness marker 与 production daemon marker。

## 测试用例

- `test/distributed/org/apache/cassandra/distributed/test/ring/BootstrapTest.java:387-416`：验证 bootstrap 中可通过 JMX 读取 `StorageServiceMBean` 的 JOINING operation mode。
- `test/distributed/org/apache/cassandra/distributed/test/BootstrapBinaryDisabledTest.java:121-147`：验证 bootstrap/write-survey gate 拦截 native transport，resume/join 后出现 `Starting listening for CQL clients`。
- `test/distributed/org/apache/cassandra/distributed/test/AuthTest.java:54-69`：验证 dtest startup 后 `StorageService.instance.authSetupCalled()`。
- `test/distributed/org/apache/cassandra/distributed/test/NodeToolEnableDisableBinaryTest.java:134-152`：验证 disable/enable binary 的 stdout marker 和 client connectivity。
- `test/unit/org/apache/cassandra/service/NativeTransportServiceTest.java:58-180`：验证 native transport service start/stop/concurrency/TLS server list。
- `test/distributed/org/apache/cassandra/distributed/test/JVMDTestTest.java:102-103`：展示 dtest logs API 能 grep startup log such as `JVM Arguments`，但不是 ordered cold-start marker E2E。

## 缺口

- `startup_marker_ordered_e2e_gap`：缺少一个 single test 使用 fresh log mark 从同一个 cold-start/restart run 中按顺序验证：
  - JMX server/setup or `StorageServiceMBean` publish before bootstrap completion。
  - Startup checks completed before local system metadata write side effects。
  - `authSetupCalled()` true before native protocol listen。
  - `Starting listening for CQL clients` appears only after transport gate passes。
  - `Startup complete` appears after `start()` returns, and test separately asserts CQL connectivity or `RPC_READY=true` when native transport should be open。
- 该 test 应至少有两种配置：normal no-bootstrap/native enabled path，以及 bootstrap incomplete 或 write-survey path。后者应 assert `Startup complete` can coexist with no CQL listen marker until resume/join.

## Drift Checker

- `research/tools/check-startup-ordered-marker-drift.py` 保护本页 source/test/gap baseline。
- 运行：

```bash
python3 research/tools/check-startup-ordered-marker-drift.py
python3 research/tools/check-startup-ordered-marker-drift.py --json
```
