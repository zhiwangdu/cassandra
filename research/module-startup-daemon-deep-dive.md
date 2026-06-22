# Module: Startup Daemon Deep Dive

## 范围

本模块补齐 Startup 第二轮源码细节，聚焦 `CassandraDaemon` 进程生命周期、`DatabaseDescriptor` 初始化模式、pre-flight startup checks、JMX/native transport、block-for-peers coordinator gate、cache/auth/Paxos/auto-compaction late startup hooks，以及测试覆盖边界。Bootstrap token/ring/streaming 主线仍以 `research/module-startup-bootstrap.md` 和 `research/flow-bootstrap.md` 为入口。

本矩阵由 `research/tools/check-startup-daemon-drift.py` 做 source/test/doc drift check，说明见 `research/module-startup-daemon-drift-checker.md`。Cold-start 集成时序、JMX/bootstrap 可见性、`completeSetup()` failure-policy boundary 和 native transport readiness 另见 `module-startup-cold-start-integration-matrix.md`，由 `research/tools/check-startup-cold-integration-drift.py` 保护。

## 覆盖场景 ID

| 场景 ID | 保护内容 |
|---|---|
| `startup_daemon_lifecycle_order` | `activate()` -> `applyConfig()` -> `setup()` -> `start()`，以及 `setup()` 内从 startup checks 到 `completeSetup()` 的顺序。 |
| `startup_config_initialization_modes` | `daemonInitialization`、`toolInitialization`、`clientInitialization` 的互斥和 apply 范围。 |
| `startup_checks_default_preflight` | `StartupChecks.DEFAULT_TESTS` 的默认 pre-flight 检查列表和 fail-fast contract。 |
| `startup_check_options_gate` | `StartupChecksOptions` 的 enabled/default/non-configurable 语义。 |
| `startup_filesystem_ownership_gate` | `FileSystemOwnershipCheck` 的 marker 文件、token、volume count 和 property/yaml 覆盖。 |
| `startup_data_resurrection_gate` | `DataResurrectionCheck` 的 heartbeat、gc_grace_seconds、exclude keyspace/table 和 postAction heartbeat。 |
| `startup_native_transport_gate` | `validateTransportsCanStart()`、`start_native_transport`、nodetool enable/disable binary 和 bootstrap failure gating。 |
| `startup_native_transport_tls_dual_port` | `NativeTransportService` 的 TLS policy、dual-port deprecation 和 invalid ssl-port config failure。 |
| `startup_block_for_peers_gate` | `StartupClusterConnectivityChecker` 在 client transport 前 warm up gossip/small/large internode connections。 |
| `startup_existing_tests_baseline` | Startup checks、native transport、binary gating、connectivity checker、data resurrection 和 config loader tests。 |

## 设计目标

- 把 Cassandra 进程从“配置未加载”推进到“本地状态安全、ring 初始化完成、可启动 client transport”的顺序固定下来。
- 在写任何新的 system keyspace metadata 前执行 startup checks，避免错误磁盘、错误 DC/rack、旧 SSTable、系统 keyspace 损坏或数据复活风险进入正常启动。
- 让 daemon/tool/client 三类初始化互斥，避免 standalone tools 或 client-mode 进程误执行 daemon-only 的目录、snitch、auth、SSL 和 startup-check side effects。
- 仅在 bootstrap/survey/auth 条件允许时启动 native transport，并在开放 CQL 前可选等待 internode peers 的 gossip + small/large message connection 预热。
- 把 late startup hooks 分层：commitlog/schema/keyspace/replay 完成后进入 `StorageService.initServer()`；ring/gossip/auth/auto-compaction/cache warming/Paxos auto repair 完成后才 `completeSetup()`。

## 解决的问题

- `CassandraDaemon.activate()` 串行调用 `applyConfig()`、`registerNativeAccess()`、`setup()`、`start()`，异常会通过 `exitOrFail` 退出或 fail 测试，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:718-769`。
- `setup()` 在 `CommitLog.instance.start()` 后立即 `runStartupChecks()`，随后才 snapshot/persist system metadata、加载 schema、打开 keyspace、replay commitlog 和进入 `StorageService.initServer()`，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:229-271`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:280-383`。
- `StartupChecks.verify()` 先执行所有 checks，再执行每个 check 的 `postAction()`；postAction 失败只 warning，不应阻断已通过的 startup，见 `src/java/org/apache/cassandra/service/StartupChecks.java:176-192`。
- `DatabaseDescriptor.daemonInitialization()` 会加载配置、`applyAll()` 和 `AuthConfig.applyAuth()`；`toolInitialization()` 只应用 non-daemon 必需项；`clientInitialization()` 设置 client mode 和默认 FD，不读写本地数据，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:245-314`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:340-363`。
- Native transport 不是创建即启动：`initializeClientTransports()` 只创建 `NativeTransportService`，`start()` 先跑 `StartupClusterConnectivityChecker` 与 `validateTransportsCanStart()`，再按 `start_native_transport` 或 `cassandra.start_native_transport` 启动，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:562-567`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:643-671`。
- 未完成 bootstrap 或 write survey + auth 会阻止 client transports，避免未 ready 节点接收 CQL 流量，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:783-806` 和 `test/distributed/org/apache/cassandra/distributed/test/BootstrapBinaryDisabledTest.java:121-147`。

## 设计取舍

- Startup checks 在 commitlog start 之后、system metadata 写入前执行。这样 native library/direct I/O/JMX/JVM/data dir/SSTable/system keyspace/DC/rack/auth-table checks 能 fail fast，但 `SystemKeyspace.snapshotOnVersionChange()` 和 `persistLocalMetadata()` 仍不会在 checks 失败时提前落盘，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:256-271`。
- `check_filesystem_ownership` 和 `check_data_resurrection` 默认 disabled，因为它们要求运维提前部署 marker 或 heartbeat；`non_configurable_check` 永远 enabled，见 `src/java/org/apache/cassandra/service/StartupChecks.java:106-126`、`src/java/org/apache/cassandra/config/StartupChecksOptions.java:81-96`。
- `StartupClusterConnectivityChecker` 不要求全部 peers healthy，而是每个参与 DC 允许一个 peer down；这减少 restart 后立即协调请求的连接延迟，同时避免一个少量故障 peer 无限阻塞 startup，见 `src/java/org/apache/cassandra/net/StartupClusterConnectivityChecker.java:124-132`。
- `block_for_peers_in_remote_dcs=false` 默认只等待 local DC，适配 LOCAL_QUORUM/LOCAL_SERIAL 类 workload；开启 remote DC wait 更适合 EACH_QUORUM/global quorum，但拉长启动时间，见 `src/java/org/apache/cassandra/config/Config.java:675-695`。
- Native dual port 保留兼容但 deprecated；当 `native_transport_port_ssl` 与 regular port 不同而 client encryption 仍 unencrypted 时配置阶段失败，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:920-936`。
- 自动 compaction 在 keyspace open 后先 disable，gossip settle 后 reload 并根据 `autocompaction_on_startup_enabled` 重新 enable，避免启动早期 disk boundaries/ring view 未稳定时调度 compaction，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:304-317`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:403-429`。

## 核心类

| 类 | 作用 |
|---|---|
| `CassandraDaemon` | 进程生命周期入口，负责 `activate()`、`setup()`、`start()`、JMX、startup checks、native transport 和 `completeSetup()`。见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:102`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:718-744` |
| `DatabaseDescriptor` | daemon/tool/client 配置初始化、`applyAll()`、startup-check options、native transport/TLS 配置和 block-for-peers 配置读取。见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:245-314`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:447-476` |
| `StartupChecks` | 默认 pre-flight checks 管理器，执行 checks 和 postAction。见 `src/java/org/apache/cassandra/service/StartupChecks.java:104-152`、`src/java/org/apache/cassandra/service/StartupChecks.java:176-192` |
| `StartupChecksOptions` | 将 `startup_checks` yaml map 展开为每个 `StartupCheckType` 的 enabled/config map，并保证 non-configurable check 不能被禁用。见 `src/java/org/apache/cassandra/config/StartupChecksOptions.java:32-96` |
| `FileSystemOwnershipCheck` | 向上遍历每个 data/commitlog/cache/hints target，校验 `.cassandra_fs_ownership`、volume count 和 ownership token。见 `src/java/org/apache/cassandra/service/FileSystemOwnershipCheck.java:74-117`、`src/java/org/apache/cassandra/service/FileSystemOwnershipCheck.java:120-225` |
| `DataResurrectionCheck` | 读取 heartbeat，按非系统表 `gc_grace_seconds` 判断停机窗口是否可能让 tombstone 过期，并在 postAction 中周期写 heartbeat。见 `src/java/org/apache/cassandra/service/DataResurrectionCheck.java:167-239`、`src/java/org/apache/cassandra/service/DataResurrectionCheck.java:241-265` |
| `StartupClusterConnectivityChecker` | native transport 前的 peer connectivity warmup，要求 gossip alive + small message ping + large message ping。见 `src/java/org/apache/cassandra/net/StartupClusterConnectivityChecker.java:84-188`、`src/java/org/apache/cassandra/net/StartupClusterConnectivityChecker.java:195-214` |
| `NativeTransportService` | lazy 初始化 Netty worker group 和 one/two native protocol `Server` 实例，处理 TLS policy、start/stop/destroy。见 `src/java/org/apache/cassandra/service/NativeTransportService.java:61-125`、`src/java/org/apache/cassandra/service/NativeTransportService.java:130-163` |
| `StorageService` | daemon 注册、JMX start/stop native transport、ring init 和 `completeInitialization()`。见 `src/java/org/apache/cassandra/service/StorageService.java:565-570`、`src/java/org/apache/cassandra/service/StorageService.java:631-666`、`src/java/org/apache/cassandra/service/StorageService.java:956-1069` |

## 核心接口

- `StartupCheck.execute()` / `postAction()`：startup check 的同步 fail-fast 与成功后 side-effect contract；`StartupChecks.verify()` 统一调用，见 `src/java/org/apache/cassandra/service/StartupChecks.java:176-192`。
- `StorageServiceMBean.startNativeTransport()` / `stopNativeTransport(boolean)`：JMX/nodetool 控制 binary transport 的入口，`StorageService` 委托到 registered daemon，见 `src/java/org/apache/cassandra/service/StorageService.java:631-656`。
- `NodeProbe.startNativeTransport()` / `stopNativeTransport()`：`nodetool enablebinary` / `disablebinary` 的 probe 侧入口，命令类见 `src/java/org/apache/cassandra/tools/nodetool/EnableBinary.java:25-32`、`src/java/org/apache/cassandra/tools/nodetool/DisableBinary.java:25-35`。
- `ConfigurationLoader.loadConfig()`：`DatabaseDescriptor.loadConfig()` 默认用 `YamlConfigurationLoader`，也可通过 `cassandra.config.loader` 自定义，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:390-409`、`test/unit/org/apache/cassandra/config/DatabaseDescriptorTest.java:70-84`。

## 核心数据结构

| 数据结构 | 语义 |
|---|---|
| `StartupCheckType` | `non_configurable_check`、`check_filesystem_ownership`、`check_dc`、`check_rack`、`check_data_resurrection`。其中 ownership/data resurrection disabled by default，见 `src/java/org/apache/cassandra/service/StartupChecks.java:106-126`。 |
| `StartupChecks.DEFAULT_TESTS` | 默认 pre-flight check list，包含 kernel direct I/O bug、jemalloc、lz4、launch date、JMX、JVM/native library、sigar、map count、read ahead、data dirs、SSTable format、system keyspace、DC/rack、legacy auth tables、data resurrection，见 `src/java/org/apache/cassandra/service/StartupChecks.java:135-152`。 |
| `StartupChecksOptions.options` | `EnumMap<StartupCheckType, Map<String,Object>>`，为缺失 check 自动创建 config，并写入 enabled default，见 `src/java/org/apache/cassandra/config/StartupChecksOptions.java:36-46`、`src/java/org/apache/cassandra/config/StartupChecksOptions.java:81-96`。 |
| `DataResurrectionCheck.Heartbeat` | JSON 文件中的 `last_heartbeat`；读取失败会退回文件 last modified time，见 `src/java/org/apache/cassandra/service/DataResurrectionCheck.java:71-108`、`src/java/org/apache/cassandra/service/DataResurrectionCheck.java:181-193`。 |
| `NativeTransportService.servers` | 一个 regular port server，或 regular + TLS dual-port servers；`ClientMetrics.instance.init(servers)` 绑定到创建的 servers，见 `src/java/org/apache/cassandra/service/NativeTransportService.java:86-124`。 |
| `StartupClusterConnectivityChecker.AckMap` | 每个 peer 需要 3 个 ack：gossip alive、small ping、large ping；达到 threshold 后按 DC latch decrement，见 `src/java/org/apache/cassandra/net/StartupClusterConnectivityChecker.java:124-143`、`src/java/org/apache/cassandra/net/StartupClusterConnectivityChecker.java:248-279`。 |

默认 pre-flight token list:

| token | 类型 |
|---|---|
| `checkKernelBug1057843` | fail-fast kernel/direct-I/O corruption guard |
| `checkJemalloc` | performance warning |
| `checkLz4Native` | compression native library warning |
| `checkValidLaunchDate` | clock sanity guard |
| `checkJMXPorts` | JMX visibility warning |
| `checkJMXProperties` | deprecated JMX system property warning |
| `inspectJvmOptions` | JVM/OOM safety warnings |
| `checkNativeLibraryInitialization` | native library fail-fast guard |
| `initSigarLibrary` | degraded system info warning |
| `checkMaxMapCount` | mmap capacity warning |
| `checkReadAheadKbSetting` | Linux block-device readahead warning |
| `checkDataDirs` | directory create/permission fail-fast guard |
| `checkSSTablesFormat` | SSTable compatibility and id fail-fast guard |
| `checkSystemKeyspaceState` | system keyspace health fail-fast guard |
| `checkDatacenter` | stored/current DC mismatch guard |
| `checkRack` | stored/current rack mismatch guard |
| `checkLegacyAuthTables` | removed auth table fail-fast guard |
| `new DataResurrectionCheck()` | optional heartbeat/gc_grace guard |

## 生命周期

Daemon cold start:

```text
CassandraDaemon.main()
  -> instance.activate()
     -> applyConfig()
        -> DatabaseDescriptor.daemonInitialization()
           -> loadConfig()
           -> applyAll()
           -> AuthConfig.applyAuth()
     -> registerNativeAccess()
     -> setup()
        -> migrateSystemDataIfNeeded()
        -> maybeInitJmx()
        -> ThreadAwareSecurityManager.install()
        -> NativeLibrary.tryMlockall()
        -> CommitLog.instance.start()
        -> runStartupChecks()
        -> SystemKeyspace.snapshotOnVersionChange()
        -> SystemKeyspace.persistLocalMetadata()
        -> Schema.instance.loadFromDisk()
        -> setupVirtualKeyspaces()
        -> scrubDataDirectories()
        -> Keyspace.open(...) and disableAutoCompaction()
        -> loadRowAndKeyCacheAsync().get()
        -> CommitLog.instance.recoverSegmentsOnDisk()
        -> StorageService.instance.initServer()
        -> schedule view rebuild
        -> Gossiper.waitToSettle()
        -> StorageService.instance.doAuthSetup(false)
        -> reload and maybe enable auto-compaction
        -> AuditLogManager.instance.initialize()
        -> initializeClientTransports()
        -> AuthCacheService.instance.warmCaches()
        -> PaxosState.startAutoRepairs()
        -> completeSetup()
     -> start()
        -> StartupClusterConnectivityChecker.execute()
        -> validateTransportsCanStart()
        -> startClientTransports()
```

Native transport start:

```text
CassandraDaemon.start()
  -> StartupClusterConnectivityChecker.create(block_for_peers_timeout_in_secs,
                                             block_for_peers_in_remote_dcs)
  -> execute(Gossiper.instance.getEndpoints(), snitch::getDatacenter)
     -> register AliveListener
     -> send PING_REQ on SMALL_MESSAGES and LARGE_MESSAGES
     -> wait until only one peer per selected DC is missing
  -> validateTransportsCanStart()
     -> if joined and write survey with bootstrap/auth: reject
     -> if joined and bootstrap incomplete: reject
  -> startClientTransports()
     -> if cassandra.start_native_transport true or config start_native_transport true:
          NativeTransportService.start()
          StorageService.instance.setRpcReady(true)
```

Startup checks:

```text
CassandraDaemon.runStartupChecks()
  -> startupChecks.verify(DatabaseDescriptor.getStartupChecksOptions())
     -> for each StartupCheck in DEFAULT_TESTS + FileSystemOwnershipCheck:
          execute(options)
     -> for each check:
          postAction(options)
```

## 调用链

- `DatabaseDescriptor.applyAll()` 应用 compatibility mode、SSTable formats、crypto provider、simple config、partitioner、address、snitch、tokens、seed provider、encryption、SSL context、directories、guardrails 和 startup checks，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:447-476`。
- `StartupChecks.checkDataDirs` 会创建缺失目录并校验 full permissions；失败抛 `ERR_WRONG_DISK_STATE`，见 `src/java/org/apache/cassandra/service/StartupChecks.java:561-593`。
- `StartupChecks.checkSSTablesFormat` 遍历 data directories，跳过 snapshots/backups/commitlog/saved caches/hints，拒绝不可读/不兼容 SSTable 和禁用 UUID identifier 时的 UUID SSTable id，见 `src/java/org/apache/cassandra/service/StartupChecks.java:596-708`。
- `StartupChecks.checkSystemKeyspaceState` 先 scrub system keyspace data directories，再调用 `SystemKeyspace.checkHealth()`，见 `src/java/org/apache/cassandra/service/StartupChecks.java:711-733`。
- `checkDatacenter` / `checkRack` 对比 system keyspace 存储值与当前 snitch local DC/rack，仍接受 deprecated `cassandra.ignore_dc` / `cassandra.ignore_rack` override，见 `src/java/org/apache/cassandra/service/StartupChecks.java:736-807`。
- `FileSystemOwnershipCheck.execute()` 从每个 target dir 向上找 marker，要求每个 target 正好找到一个 marker、所有 marker 内容一致、version=1、`volume_count` 等于 marker 数、token 匹配，见 `src/java/org/apache/cassandra/service/FileSystemOwnershipCheck.java:120-225`。
- `DataResurrectionCheck.execute()` 对非系统 keyspaces/tables 计算 `last_heartbeat + gc_grace_seconds < now`，若有 violation 则拒绝启动并输出 `Invalid tables`，见 `src/java/org/apache/cassandra/service/DataResurrectionCheck.java:200-238`。
- `NativeTransportService.initialize()` 选择 epoll/NIO，按 `native_transport_port`、`native_transport_port_ssl` 和 `client_encryption_options.tlsEncryptionPolicy()` 构造 server list，见 `src/java/org/apache/cassandra/service/NativeTransportService.java:61-125`。
- `StorageService.startNativeTransport()` 先 `checkServiceAllowedToStart("native transport")`，要求 daemon 已注册，再调用 daemon，见 `src/java/org/apache/cassandra/service/StorageService.java:631-647`。

## 配置项

| 配置项 / system property | 定义位置 | 作用 |
|---|---|---|
| `start_native_transport` | `src/java/org/apache/cassandra/config/Config.java:278`、`conf/cassandra.yaml:1018-1020` | 控制 daemon `startClientTransports()` 是否自动启动 native transport。 |
| `cassandra.start_native_transport` | `src/java/org/apache/cassandra/service/CassandraDaemon.java:665-671` | system property override；为 true 时即使 yaml 关闭也启动。 |
| `native_transport_port` | `src/java/org/apache/cassandra/config/Config.java:279`、`conf/cassandra.yaml:1021-1023` | CQL native transport regular port。 |
| `native_transport_port_ssl` | `src/java/org/apache/cassandra/config/Config.java:280-282`、`conf/cassandra.yaml:1024-1032` | Deprecated dual TLS port；如果 distinct port 且 client encryption unencrypted，配置失败。 |
| `client_encryption_options` | `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:920-936`、`conf/cassandra.yaml:1699` | 决定 native transport TLS policy 和 ssl-port 合法性。 |
| `block_for_peers_timeout_in_secs` | `src/java/org/apache/cassandra/config/Config.java:675-695`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4446-4448` | native transport 前等待 peer 连接预热的最长秒数；`-1` 禁用，`0` 只触发连接不等待。 |
| `block_for_peers_in_remote_dcs` | `src/java/org/apache/cassandra/config/Config.java:691-695`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4441-4443` | 是否把 remote DC 也纳入 block-for-peers latch。 |
| `startup_checks` | `src/java/org/apache/cassandra/config/Config.java:954-955`、`conf/cassandra.yaml:2266-2290` | 配置可配置 startup checks，例如 ownership、DC/rack、data resurrection。 |
| `check_filesystem_ownership.enabled` / `ownership_token` / `ownership_filename` | `conf/cassandra.yaml:2271-2275`、`src/java/org/apache/cassandra/service/FileSystemOwnershipCheck.java:276-315` | 控制磁盘 marker 所有权校验；system property 仍可 override 但会 warn。 |
| `check_data_resurrection.enabled` / `heartbeat_file` / `excluded_keyspaces` / `excluded_tables` | `conf/cassandra.yaml:2282-2290`、`src/java/org/apache/cassandra/service/DataResurrectionCheck.java:65-67` | 控制 heartbeat/gc_grace 数据复活风险检查和排除项。 |
| `autocompaction_on_startup_enabled` | `src/java/org/apache/cassandra/config/Config.java:833`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4658-4660` | gossip settle 后是否重新 enable compaction。 |

## Metrics

- `CassandraDaemon` 静态初始化把 logback metrics registry 的 meter 注册成 Cassandra metrics MBean，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:120-136`。
- Native transport 创建 servers 后调用 `ClientMetrics.instance.init(servers)`，CQL client metrics 与实际 bound server set 对齐，见 `src/java/org/apache/cassandra/service/NativeTransportService.java:122-124`。
- Startup connectivity checker 只有日志和返回值，没有专门 metrics；它通过 `PING_REQ` 触发 small/large internode connection 建立，见 `src/java/org/apache/cassandra/net/StartupClusterConnectivityChecker.java:195-214`。
- Token 相关非法请求在 startup 期间会计入 `StorageMetrics.startupOpsForInvalidToken`，非 startup 进入 `totalOpsForInvalidToken`，见 `src/java/org/apache/cassandra/service/StorageService.java:386`。

## 日志

- `CassandraDaemon.logSystemInfo()` 输出 host、JVM、heap、classpath、JVM arguments，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:596-620`。
- `activate()` 成功后记录 `Startup complete`；异常路径会输出 exception class/message 并按 `ConfigurationException.logStackTrace` 决定 stacktrace，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:742-769`。
- `StorageService.initServer()` 输出 Cassandra version、Git SHA、CQL version、native protocol supported versions，见 `src/java/org/apache/cassandra/service/StorageService.java:968-972`。
- `StartupClusterConnectivityChecker` 成功记录 healthy connections，失败记录 missing peer host addresses grouped by DC，见 `src/java/org/apache/cassandra/net/StartupClusterConnectivityChecker.java:166-185`。
- `DataResurrectionCheck` heartbeat deserialize 失败会记录文件长度和前 1024 bytes hex，然后 fallback last modified，见 `src/java/org/apache/cassandra/service/DataResurrectionCheck.java:93-107`、`src/java/org/apache/cassandra/service/DataResurrectionCheck.java:181-193`。
- Native transport start 记录 Netty version，initialize 记录 epoll 或 NIO event loop，见 `src/java/org/apache/cassandra/service/NativeTransportService.java:67-75`、`src/java/org/apache/cassandra/service/NativeTransportService.java:130-135`。

## 运维关注点

- `startup_checks.check_data_resurrection.enabled=true` 需要保留 heartbeat 文件；如果节点停机超过某些表的 `gc_grace_seconds`，它会拒绝启动，运维需要确认 tombstone 风险后处理 heartbeat 或排除项，见 `conf/cassandra.yaml:2282-2290`。
- `check_filesystem_ownership` 适合共享存储或自动化挂载场景；marker 缺失、重复、不一致、volume_count 不符或 token 不符都会阻止启动，见 `src/java/org/apache/cassandra/service/FileSystemOwnershipCheck.java:169-225`。
- `block_for_peers_timeout_in_secs=-1` 禁用 peer warmup；`0` 触发 ping 但立即继续；大于 100 秒会 warning，见 `src/java/org/apache/cassandra/net/StartupClusterConnectivityChecker.java:62-68`。
- Bootstrap failure 后 native transport 不应被手动启起，除非 `nodetool bootstrap resume` 成功或 write survey 明确 join；分布式测试覆盖该行为，见 `test/distributed/org/apache/cassandra/distributed/test/BootstrapBinaryDisabledTest.java:121-147`。
- `native_transport_port_ssl` 是 deprecated dual-port，不应作为新部署策略；优先使用 regular port 的 optional/encrypted TLS policy，见 `conf/cassandra.yaml:1024-1032`。
- `autocompaction_on_startup_enabled=false` 会让启动后 compaction 保持关闭，需要运维明确后续 enable，否则 SSTable 数量和读放大可能持续增长，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:418-425`。

## 性能瓶颈

- Commitlog replay、schema load、keyspace open、row/key cache load 和 counter cache load 都在 client transport 前串行或阻塞等待，重启时间会受 commitlog backlog、SSTable count、cache file 体积和 disk latency 影响，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:280-345`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:319-327`。
- `checkSSTablesFormat` 会 walk data directories 并解析 SSTable descriptors；大量旧数据目录、无效文件或慢盘会拉长 startup checks，见 `src/java/org/apache/cassandra/service/StartupChecks.java:596-708`。
- `StartupClusterConnectivityChecker` 在 CQL 开放前等待 gossip/small/large connections；跨 DC 等待开启时，remote DC 网络抖动会直接拉长 startup，见 `src/java/org/apache/cassandra/net/StartupClusterConnectivityChecker.java:109-123`。
- Native transport dual-port 会构造两个 server，对测试和本地部署问题排查有价值，但在生产上增加配置复杂度且已 deprecated，见 `src/java/org/apache/cassandra/service/NativeTransportService.java:90-120`。

## 常见故障

- 配置初始化模式冲突：daemon 初始化后再 tool/client init 会 assertion，反之亦然，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:250-260`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:283-299`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:340-356`。
- Native SSL port 配置失败：`native_transport_port_ssl` 与 `native_transport_port` 不同但 client encryption 未启用，抛 `Encryption must be enabled in client_encryption_options for native_transport_port_ssl`，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:933-936`。
- Startup check invalid SSTables：`checkSSTablesFormat` 抛 `Detected unreadable sstables`，测试见 `test/unit/org/apache/cassandra/service/StartupChecksTest.java:117-146`。
- Direct I/O + affected ext4 kernel：`checkKernelBug1057843` 在 Linux ext4、commitlog direct I/O、kernel 6.1.64 <= version < 6.1.66 时 fail，测试见 `test/unit/org/apache/cassandra/service/StartupChecksTest.java:277-373`。
- DC/rack mismatch：stored system keyspace DC/rack 与当前 snitch 不同会阻止启动，见 `src/java/org/apache/cassandra/service/StartupChecks.java:736-807`。
- Bootstrap incomplete：`validateTransportsCanStart()` 抛出 `Node is not yet bootstrapped completely`，测试见 `test/distributed/org/apache/cassandra/distributed/test/BootstrapBinaryDisabledTest.java:121-147`。
- Filesystem ownership marker 缺失或重复：`FileSystemOwnershipCheck` 抛 `FS ownership check failed`，测试见 `test/unit/org/apache/cassandra/service/AbstractFilesystemOwnershipCheckTest.java:232-260`。
- Data resurrection risk：heartbeat 太旧且存在短 `gc_grace_seconds` 表时抛 `Invalid tables`，测试见 `test/distributed/org/apache/cassandra/distributed/test/DataResurrectionCheckTest.java:60-129`。

## 测试用例

| 测试 | 覆盖 |
|---|---|
| `test/unit/org/apache/cassandra/service/StartupChecksTest.java` | invalid SSTable、read_ahead path、max_map_count、data resurrection unit fallback、kernel bug 1057843。 |
| `test/unit/org/apache/cassandra/config/StartupCheckOptionsTest.java` | startup check option enable/disable/default/non-configurable 和 data resurrection exclude parsing。 |
| `test/unit/org/apache/cassandra/service/AbstractFilesystemOwnershipCheckTest.java` | ownership marker 缺失、重复、不一致、invalid count/token/version/property。 |
| `test/unit/org/apache/cassandra/service/SystemPropertiesBasedFileSystemOwnershipCheckTest.java` | ownership check system property enable/token override。 |
| `test/unit/org/apache/cassandra/service/YamlBasedFileSystemOwnershipCheckTest.java` | ownership check yaml enabled/token config。 |
| `test/distributed/org/apache/cassandra/distributed/test/DataResurrectionCheckTest.java` | 启用 data resurrection check 的真实节点 heartbeat、gc_grace violation 和 exclude keyspace/table。 |
| `test/unit/org/apache/cassandra/net/StartupClusterConnectivityCheckerTest.java` | local/global DC quorum、no-op、zero-wait、gossip alive 与 small/large ping ack。 |
| `test/unit/org/apache/cassandra/service/NativeTransportServiceTest.java` | native transport start/stop/destroy/concurrent lifecycle、plain/TLS/optional/dual-port server selection。 |
| `test/distributed/org/apache/cassandra/distributed/test/BootstrapBinaryDisabledTest.java` | bootstrap streaming failure 后 binary transport 不启动，resume 后启动，write survey + auth 仍阻止。 |
| `test/distributed/org/apache/cassandra/distributed/test/NodeToolEnableDisableBinaryTest.java` | nodetool help、disablebinary/enablebinary 与真实 driver connection。 |
| `test/unit/org/apache/cassandra/config/DatabaseDescriptorTest.java` | custom config loader、address/interface config、partitioner/config validation。 |
| `test/distributed/org/apache/cassandra/distributed/test/NativeTransportEncryptionOptionsTest.java` | native TLS and ssl port distributed coverage，细节见 native TLS reload matrix。 |

## 待继续

- 补一个真正从 process/daemon 层验证 `setup()` ordering、`completeSetup()`、log markers 和 JMX/native transport ready state 的 cold-start integration matrix；当前覆盖主要由 source contract、component unit tests 和 in-JVM distributed startup 间接保护。
- 将 Startup drift checker 接入 CI 后，Startup 第二轮文档能随 daemon/config/startup-check 变更自动提示更新。
