# Module: Startup Cold-Start Integration Matrix

本页是 `module-startup-daemon-deep-dive.md` 的第三轮补充，聚焦完整 cold-start 集成时序：JMX 何时可用、daemon 何时注册到 `StorageService`、`setupCompleted` 何时翻转、native transport/RPC_READY 何时发布，以及启动期和启动后的 failure policy 如何分叉。

## 范围

- `CassandraDaemon.setup()` 从 filesystem handler/JMX 到 `completeSetup()` 的跨模块时序。
- `StorageService.registerDaemon()`、`registerMBeans()` 和 bootstrap 过程中 JMX 可见性。
- `NativeTransportService` 初始化 vs 启动分离，以及 `RPC_READY` gossip state 的开启/关闭。
- `validateTransportsCanStart()` 对未完成 bootstrap、write survey 和 auth 的 client transport gate。
- `completeSetup()` 对 disk/commitlog failure policy 的边界影响。
- 现有 unit/distributed tests 对上述集成边界的覆盖，以及仍缺少的完整 cold-start log marker E2E。

## 覆盖场景

| 场景 ID | 当前结论 |
|---|---|
| `startup_cold_jmx_early_bootstrap` | `maybeInitJmx()` 在 startup checks 和 ring join 前执行；`StorageService` MBean 在 `initServer()` 中注册，distributed test 验证 bootstrap 中可通过 JMX 读 JOINING。 |
| `startup_cold_daemon_registration_order` | daemon 在 `StorageService.initServer()` 前注册，使 JMX/nodetool binary 操作能委托回 daemon；若 daemon 缺失，`StorageService.startNativeTransport()`/`stopNativeTransport()` 抛 `No configured daemon`。 |
| `startup_cold_complete_setup_marker` | `completeSetup()` 是 setup 末端标记，位于 client transport 构造、auth cache warmup 和 Paxos auto repairs 之后；它不是 native transport 已启动的标志。 |
| `startup_cold_native_rpc_ready_gate` | `start()` 先执行 peer warmup 和 transport validation，再启动 native transport；首次启动后发布 `RPC_READY=true`，stop/deactivate 发布 `RPC_READY=false` 或停止服务。 |
| `startup_cold_bootstrap_binary_gate` | bootstrap 失败或 write survey + auth/bootstrap 时不开放 CQL；resume/bootstrap/join 完成后才出现 `Starting listening for CQL clients`。 |
| `startup_cold_auth_setup_ready` | `StorageService.doAuthSetup(false)` 在 daemon setup 中、native transport start 前执行；distributed test 轮询 `authSetupCalled()`。 |
| `startup_cold_jmx_binary_operator_path` | `nodetool enablebinary/disablebinary` 走 `NodeProbe` -> `StorageServiceMBean` -> daemon，并真实改变 client connectivity。 |
| `startup_cold_failure_policy_boundary` | `isDaemonSetupCompleted()` 决定 disk/commitlog failure 是 quiet kill startup，还是按配置 stop/ignore/die 处理。 |
| `startup_cold_log_marker_gap` | 当前有分散日志断言，但缺少一条完整 daemon cold-start E2E 断言关键 marker 顺序；gap still open。 |
| `startup_cold_existing_tests_baseline` | `BootstrapTest`、`BootstrapBinaryDisabledTest`、`AuthTest`、`NodeToolEnableDisableBinaryTest`、`DefaultFSErrorHandlerTest`、`DiskFailurePolicyTest`、`CommitLogFailurePolicyTest` 共同覆盖集成边界。 |

## 设计目标

- 让 operator 在节点还没完成 bootstrap 时也能通过 JMX 观察 bootstrap state 和执行安全的后续操作。
- 明确“setup 完成”和“对外接收 CQL”不是同一个状态：`completeSetup()` 只表示 daemon 初始化完成，client transport 仍要通过 `start()` 的 peer warmup 与 bootstrap/write-survey gate。
- 将 startup failure 视为比运行期 failure 更严重：在 setup 未完成时，disk/commitlog 错误应 quiet kill JVM，避免半初始化节点继续运行。
- 在 native transport 开放前完成 auth setup、cache warmup、Paxos auto-repair scheduler 初始化，降低第一个 client request 命中未初始化组件的概率。

## 解决的问题

- JMX late publish 会让 bootstrap 失败/卡住时无法查询状态。当前源码在 `StorageService.initServer()` 早段注册 MBeans，且 `BootstrapTest.testStorageServiceMBeanIsPublishedOnJMXDuringBootstrap()` 在 bootstrap latch 阻塞时通过 JMX 读取 `JOINING`，见 `src/java/org/apache/cassandra/service/StorageService.java:1017`、`test/distributed/org/apache/cassandra/distributed/test/ring/BootstrapTest.java:387-416`。
- Native transport 不能在 bootstrap incomplete 时开放，否则节点可能在未拥有数据前接收 CQL。`validateTransportsCanStart()` 拒绝未完成 bootstrap 和 write survey + auth/bootstrap，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:783-807`。
- daemon 尚未注册时，JMX/nodetool binary 操作没有可委托目标；`StorageService.startNativeTransport()` 和 `stopNativeTransport()` 都检查 daemon，见 `src/java/org/apache/cassandra/service/StorageService.java:631-657`。
- 启动期 commitlog/disk 错误不能按运行期 `ignore` 继续。`JVMStabilityInspector.inspectCommitLogError()` 和 `DefaultFSErrorHandler` 都检查 `isDaemonSetupCompleted()`，见 `src/java/org/apache/cassandra/utils/JVMStabilityInspector.java:208-217`、`src/java/org/apache/cassandra/service/DefaultFSErrorHandler.java:43-64`。

## 设计取舍

- `maybeInitJmx()` 早于 `runStartupChecks()`。这提高故障可观测性，但意味着 JMX server 可能在后续 startup check 失败前已经创建，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:246-258`。
- `StorageService.registerDaemon(this)` 早于 `initServer()`。这样 `StorageService` MBean 操作能找到 daemon，但也要求 `startNativeTransport()` 内再次校验 bootstrap/write-survey，而不能只信任 daemon 存在。
- `initializeClientTransports()` 只构造 `NativeTransportService`，不 bind 端口；真正 bind 发生在 `CassandraDaemon.startNativeTransport()`，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:562-567`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:809-825`。
- `completeSetup()` 放在 auth cache warmup和 `PaxosState.startAutoRepairs()` 后，这让 failure policy 在这些 late hooks 之前仍按 startup failure 处理；代价是某些运行期组件已经启动但 failure policy 仍处于 startup 严格模式。
- `start()` 捕获 `validateTransportsCanStart()` 的 `IllegalStateException` 并只记录 warning/return，不让 daemon startup 整体失败；bootstrap resume/join 可以稍后重新开放 CQL。

## 核心类

| 类 | 责任 |
|---|---|
| `CassandraDaemon` | cold-start 主时序、JMX 初始化、startup checks、daemon setup completion、native transport validation/start/stop，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:139-186`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:229-454`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:643-825`。 |
| `StorageService` | daemon 注册、MBean 注册、ring/bootstrap 初始化、native transport JMX facade、RPC_READY gossip state，见 `src/java/org/apache/cassandra/service/StorageService.java:559-568`、`src/java/org/apache/cassandra/service/StorageService.java:631-657`、`src/java/org/apache/cassandra/service/StorageService.java:966-1068`、`src/java/org/apache/cassandra/service/StorageService.java:3074-3096`。 |
| `NativeTransportService` | lazy 初始化 Netty worker group 和 native protocol server list，`start()`/`stop()`/`destroy()` 管理 CQL listener 生命周期，见 `src/java/org/apache/cassandra/service/NativeTransportService.java:61-163`。 |
| `DefaultFSErrorHandler` | disk/corrupt SSTable failure policy，启动期未完成 setup 时调用 startup error path，见 `src/java/org/apache/cassandra/service/DefaultFSErrorHandler.java:43-137`。 |
| `JVMStabilityInspector` | commitlog startup failure quiet kill 和运行期 die policy 处理，见 `src/java/org/apache/cassandra/utils/JVMStabilityInspector.java:208-217`。 |
| `StartupClusterConnectivityChecker` | CQL 开放前 peer gossip/small/large connection warmup，见 `src/java/org/apache/cassandra/net/StartupClusterConnectivityChecker.java:62-214`。 |

## 核心接口

- `StorageServiceMBean.startNativeTransport()` / `stopNativeTransport(boolean)`：JMX/nodetool binary path 入口，`StorageService` 委托 daemon 并处理 daemon 缺失，见 `src/java/org/apache/cassandra/service/StorageService.java:631-657`。
- `CassandraDaemon.validateTransportsCanStart()`：native transport gate，抛 `IllegalStateException` 表示暂时不能开放 CQL，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:783-807`。
- `CassandraDaemon.setupCompleted()` / `StorageService.isDaemonSetupCompleted()`：failure policy 分界接口，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:585-593`、`src/java/org/apache/cassandra/service/StorageService.java:730-733`。

## 核心数据结构

- `CassandraDaemon.setupCompleted`：boolean setup marker，构造时 false，`completeSetup()` 后 true，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:205-221`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:585-593`。
- `CassandraDaemon.nativeTransportService`：volatile service reference；`initializeClientTransports()` 构造，`startNativeTransport()` 要求非 null，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:205`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:562-567`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:809-825`。
- `StorageService.daemon`：JMX facade 的 daemon delegate；`registerDaemon()` 写入，native transport JMX 操作读取，见 `src/java/org/apache/cassandra/service/StorageService.java:565-568`、`src/java/org/apache/cassandra/service/StorageService.java:631-657`。
- `ApplicationState.RPC_READY`：native transport readiness 通过 gossip 发布；`setRpcReady(true)` 要求 local endpoint state 已存在，false 容忍空 state，见 `src/java/org/apache/cassandra/service/StorageService.java:3080-3096`。
- `authSetupCalled`：`AtomicBoolean`，测试可观察 auth setup 是否完成，见 `src/java/org/apache/cassandra/service/StorageService.java:484`、`src/java/org/apache/cassandra/service/StorageService.java:1442-1488`。

## 生命周期

### Cold Start Integration

```text
CassandraDaemon.activate()
  -> applyConfig()
  -> registerNativeAccess()
  -> setup()
     -> FileUtils.setFSErrorHandler(DefaultFSErrorHandler)
     -> maybeInitJmx()
     -> CommitLog.instance.start()
     -> runStartupChecks()
     -> SystemKeyspace.persistLocalMetadata()
     -> Schema.instance.loadFromDisk()
     -> Keyspace.open(...) and disableAutoCompaction()
     -> load row/key cache
     -> CommitLog.instance.recoverSegmentsOnDisk()
     -> StorageService.instance.registerDaemon(this)
     -> StorageService.instance.initServer()
        -> registerMBeans()
        -> prepareToJoin()
        -> joinTokenRing(...) or not-join path
        -> completeInitialization()
     -> schedule MV rebuild
     -> Gossiper.waitToSettle()
     -> StorageService.instance.doAuthSetup(false)
     -> reload / maybe enable autocompaction
     -> initializeClientTransports()
     -> AuthCacheService.instance.warmCaches()
     -> PaxosState.startAutoRepairs()
     -> completeSetup()
  -> start()
     -> StartupClusterConnectivityChecker.execute(...)
     -> validateTransportsCanStart()
     -> startClientTransports()
     -> log "Startup complete"
```

### JMX During Bootstrap

```text
CassandraDaemon.setup()
  -> StorageService.registerDaemon(this)
  -> StorageService.initServer()
     -> registerMBeans()
     -> prepareToJoin()
     -> bootstrap/joinTokenRing(...)
Distributed test pauses bootstrap
  -> JMX.newMBeanProxy(StorageServiceMBean)
  -> getOperationMode() == JOINING
```

### Native Transport Readiness

```text
CassandraDaemon.start()
  -> StartupClusterConnectivityChecker.execute(...)
  -> validateTransportsCanStart()
     -> reject incomplete bootstrap or unsafe write survey
  -> startClientTransports()
     -> startNativeTransport()
        -> require nativeTransportService != null
        -> NativeTransportService.start()
        -> if not already running: StorageService.setRpcReady(true)

nodetool disablebinary
  -> NodeProbe.stopNativeTransport(force)
  -> StorageService.stopNativeTransport(force)
  -> CassandraDaemon.stopNativeTransport(force)
```

### Failure Policy Boundary

```text
Disk or commitlog error during setup
  -> StorageService.isDaemonSetupCompleted() == false
  -> startup FSError / commitlog error path
  -> quiet JVM kill for stop/die/stop_paranoid style policies

Disk or commitlog error after completeSetup()
  -> StorageService.isDaemonSetupCompleted() == true
  -> apply configured disk_failure_policy or commit_failure_policy
  -> stop transports, kill JVM, or ignore according to policy
```

## 配置项

| 配置项 / property | 定义位置 | 集成影响 |
|---|---|---|
| `start_native_transport` | `src/java/org/apache/cassandra/config/Config.java:278`、`conf/cassandra.yaml:1018-1020` | 决定 `startClientTransports()` 是否自动 bind CQL listener。 |
| `cassandra.start_native_transport` | `src/java/org/apache/cassandra/service/CassandraDaemon.java:665-671` | system property override；true 时覆盖 yaml false。 |
| `block_for_peers_timeout_in_secs` / `block_for_peers_in_remote_dcs` | `src/java/org/apache/cassandra/config/Config.java:675-695` | 控制 CQL listener 前 peer warmup 的等待范围和时长。 |
| `auto_bootstrap` / write survey property | `StorageService.prepareToJoin()` / `CassandraRelevantProperties.TEST_WRITE_SURVEY` | 影响 bootstrap/write-survey 状态，从而影响 `validateTransportsCanStart()`。 |
| `commit_failure_policy` / `disk_failure_policy` | `src/java/org/apache/cassandra/config/Config.java`、`DatabaseDescriptor` getters/setters | 与 `setupCompleted` 一起决定 startup failure vs runtime failure 处理。 |
| `autocompaction_on_startup_enabled` | `src/java/org/apache/cassandra/config/Config.java:833` | gossip settle 后是否重新 enable compaction，发生在 `completeSetup()` 前。 |

## Metrics

- Cold-start integration 自身没有单独 metric；验证依赖日志、JMX、gossip app state 和 client connectivity。
- `StorageService.setRpcReady()` 发布 `ApplicationState.RPC_READY`，其他节点通过 gossip 和 lifecycle subscriber 观察 up/down，见 `src/java/org/apache/cassandra/service/StorageService.java:3024-3039`、`src/java/org/apache/cassandra/service/StorageService.java:3088-3096`。
- Native transport metrics 在 `NativeTransportService.initialize()` 后按实际 server list 初始化，见 `src/java/org/apache/cassandra/service/NativeTransportService.java:122-124`。

## 日志

- `CassandraDaemon.activate()` 成功后记录 `Startup complete`，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:742-744`。
- 未自动启动 native transport 时记录 `Not starting native transport as requested...`，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:665-671`。
- bootstrap/write survey gate 失败时 `start()` 记录 warning 并 return，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:651-660`；distributed test 断言相关 log，见 `test/distributed/org/apache/cassandra/distributed/test/BootstrapBinaryDisabledTest.java:121-147`。
- native transport start/stop 的用户可见文本由 nodetool test 验证包含 `Starting listening for CQL clients` / `Stop listening for CQL clients`，见 `test/distributed/org/apache/cassandra/distributed/test/NodeToolEnableDisableBinaryTest.java:134-152`。
- startup disk error quiet-kill 路径记录 `Exiting forcefully due to file system exception on startup`，见 `src/java/org/apache/cassandra/service/DefaultFSErrorHandler.java:121-133`。

## 运维关注点

- `Startup complete` 不是“所有启动风险已消失”的唯一信号；如果 native transport 被配置关闭或被 bootstrap gate 拦截，节点可能完成 daemon startup 但不接收 CQL。
- JMX 可在 bootstrap 中途观察 `StorageService`，这对 `nodetool bootstrap resume`、状态诊断和故障恢复是必要能力。
- `setupCompleted=false` 时 commitlog/disk 错误可能 quiet kill JVM，即使运行期策略是 `ignore`；不要把 startup failure policy 和 runtime failure policy 混为一谈。
- `nodetool enablebinary` 仍会调用 `validateTransportsCanStart()`；未完成 bootstrap 的节点不会因为 operator 手动启 binary 就绕过 gate。
- `completeSetup()` 后 failure policy 改为运行期语义；`DefaultFSErrorHandlerTest` 和 `CommitLogFailurePolicyTest` 都显式构造 daemon 并调用 `completeSetup()` 来测试这一点。

## 性能瓶颈

- `setup()` 中 commitlog replay、schema load、keyspace open、cache load、auth setup 和 compaction reload 都在 `completeSetup()` 前，慢盘或大缓存会延迟 failure policy 从 startup 模式切到 runtime 模式。
- `StartupClusterConnectivityChecker` 位于 CQL 开放前；remote DC wait 或 large-message ping timeout 会延迟 `RPC_READY=true`。
- JMX 提前开放改善可观测性，但 JMX server 创建失败会 `exitOrFail()`，属于启动阻塞点，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:176-185`。

## 常见故障

- JMX 无法在 bootstrap 中查询：检查 `Feature.JMX`、JMX port property 和 `StorageService.registerMBeans()` 是否执行；regression test 是 `testStorageServiceMBeanIsPublishedOnJMXDuringBootstrap()`。
- CQL 不监听但 daemon 已启动：看 `validateTransportsCanStart()` log，常见原因是 bootstrap incomplete 或 write survey + auth/bootstrap。
- `No configured daemon`：说明 `StorageService` 尚未 `registerDaemon()`，JMX/nodetool binary 操作不能委托 daemon。
- Disk/commitlog error 在 startup 阶段杀 JVM：这是 `isDaemonSetupCompleted=false` 的设计，先修复启动期错误，不要只调整 runtime failure policy。
- `setup() must be called first for CassandraDaemon`：直接调用 daemon `startNativeTransport()` 前没有 `initializeClientTransports()`。

## 测试用例

| 测试 | 覆盖 |
|---|---|
| `test/distributed/org/apache/cassandra/distributed/test/ring/BootstrapTest.java:387-416` | bootstrap 中 `StorageServiceMBean` 已发布且可读 JOINING。 |
| `test/distributed/org/apache/cassandra/distributed/test/BootstrapBinaryDisabledTest.java:121-147` | bootstrap failure/write survey gate 阻止 native transport，resume/join 后才监听 CQL。 |
| `test/distributed/org/apache/cassandra/distributed/test/AuthTest.java:54-69` | daemon startup 后 `doAuthSetup()` 已执行。 |
| `test/distributed/org/apache/cassandra/distributed/test/NodeToolEnableDisableBinaryTest.java:134-152` | nodetool enable/disable binary 真实改变 client connectivity。 |
| `test/distributed/org/apache/cassandra/distributed/test/DisableBinaryTest.java:144-172` | disablebinary 后新请求失败，已开始请求处理完。 |
| `test/unit/org/apache/cassandra/service/DefaultFSErrorHandlerTest.java:54-120` | `completeSetup()` 后 disk/corrupt SSTable failure policy 对 gossip/transport 的影响。 |
| `test/unit/org/apache/cassandra/service/DiskFailurePolicyTest.java:87-124` | startup-in-progress vs completed 的 disk failure quiet-kill/stop/ignore matrix。 |
| `test/unit/org/apache/cassandra/db/commitlog/CommitLogFailurePolicyTest.java:46-134` | startup 未完成时 commitlog error quiet kill，完成后按 commit failure policy。 |
| `test/unit/org/apache/cassandra/service/NativeTransportServiceTest.java:58-180` | native transport start/stop/destroy/concurrent start 和 TLS server list。 |

## 缺口

- `startup_cold_log_marker_gap`：当前测试覆盖多个集成边界，但缺少一个完整 daemon cold-start E2E 测试按顺序断言关键日志 marker：JMX setup、startup checks passed、StorageService MBean published、auth setup, native transport listen, `Startup complete`。建议用 in-JVM dtest 监听日志并在 bootstrap/no-bootstrap 两个配置下验证。

## Drift Checker

- `research/tools/check-startup-cold-integration-drift.py` 保护本页 source/test/gap baseline。
- 运行：

```bash
python3 research/tools/check-startup-cold-integration-drift.py
python3 research/tools/check-startup-cold-integration-drift.py --json
```
