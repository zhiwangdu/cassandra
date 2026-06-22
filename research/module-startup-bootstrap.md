# Module: Startup And Bootstrap

## 范围

本模块覆盖 CassandraDaemon 启动、StorageService 初始化、join ring、token selection、bootstrap streaming 和 resume bootstrap 主线。

## 设计目标

Startup 负责把一个 Cassandra 进程从“配置未加载”推进到“可以加入 ring 并对外提供服务”。Bootstrap 负责在新节点或替换节点第一次加入集群时获取 token 对应的数据范围，并在 streaming 成功后进入 normal ring 状态。

核心目标：

- 先完成本地配置、目录、schema、system keyspace、commitlog replay，再启动 gossip/ring 逻辑。
- 在尚未 bootstrap 完成时阻止不安全的 client transport 启动。
- 通过 gossip 广播本节点的 host id、token、native address、release version、SSTable version 等状态。
- 对 seed、已 bootstrapped 节点、新节点、replacement、write survey mode 分支做不同处理。
- 在 decommission 时先校验 RF/活节点约束，再迁出数据、停止服务并标记本地 bootstrap state。

## 解决的问题

- 避免配置未校验或目录未创建时启动服务：`DatabaseDescriptor.daemonInitialization()` 会加载配置、执行 `applyAll()` 并应用 auth 配置，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:245-265`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:447-476`。
- 避免 commitlog 未 replay 时打开写服务：`CassandraDaemon.setup()` 先 `CommitLog.instance.start()`，随后加载 schema/keyspace 并执行 `CommitLog.instance.recoverSegmentsOnDisk()`，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:256`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:282-345`。
- 避免未完成 bootstrap 的节点接收客户端流量：`validateTransportsCanStart()` 在 joined 状态下检查 survey mode/auth/bootstrap state，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:783-806`。
- 避免 bootstrapping/leaving/moving 节点互相破坏一致性：`joinTokenRing()` 和 bootstrap 前置检查会围绕 `shouldBootstrap`、saved tokens、pending ranges 执行，见 `src/java/org/apache/cassandra/service/StorageService.java:1260-1358`。

## 设计取舍

- 启动流程偏顺序化：`CassandraDaemon.activate()` 串行执行 `applyConfig -> setup -> start`，降低状态交错风险，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:718-743`。
- Gossip 在 ring 正式加入前启动：`prepareToJoin()` 先 `MessagingService.instance().listen()`，再 `Gossiper.instance.start(...)`，因为 bootstrap 需要通过 gossip 获取其他节点信息，见 `src/java/org/apache/cassandra/service/StorageService.java:1163-1219`。
- Seed 默认不 auto bootstrap：`joinTokenRing()` 明确记录 seed 不 auto bootstrap 的分支，见 `src/java/org/apache/cassandra/service/StorageService.java:1274-1295`。
- Bootstrap streaming 同步等待完成：`StorageService.bootstrap()` 对 `startBootstrap(tokens)` 返回的 future 执行 `get()`，失败则设置 `JOINING_FAILED`，见 `src/java/org/apache/cassandra/service/StorageService.java:2247-2263`。
- Decommission 默认保护 RF：非 force 模式会检查每个 distributed keyspace 的 RF 与可用节点数量，见 `src/java/org/apache/cassandra/service/StorageService.java:5339-5368`。

## 核心类

| 类 | 作用 |
|---|---|
| `org.apache.cassandra.service.CassandraDaemon` | 进程级生命周期入口，负责 `activate()`、`setup()`、`start()`、transport 启停。类定义：`src/java/org/apache/cassandra/service/CassandraDaemon.java:102` |
| `org.apache.cassandra.config.DatabaseDescriptor` | daemon/tool/client 配置初始化、配置校验、目录创建、snitch/partitioner/seed provider 应用。配置初始化：`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:245-265` |
| `org.apache.cassandra.service.StorageService` | ring、gossip、bootstrap、decommission、MBean、auth setup、load broadcasting。类定义：`src/java/org/apache/cassandra/service/StorageService.java:292` |
| `org.apache.cassandra.dht.BootStrapper` | bootstrap token 计算和 range streaming 发起。类定义：`src/java/org/apache/cassandra/dht/BootStrapper.java:43` |
| `org.apache.cassandra.streaming.StreamPlan` | request/transfer ranges 并执行 streaming plan。`requestRanges()` 和 `transferRanges()` 见 `src/java/org/apache/cassandra/streaming/StreamPlan.java:91-130` |
| `org.apache.cassandra.gms.Gossiper` | endpoint state 传播，startup 中由 `StorageService.prepareToJoin()` 启动。类定义：`src/java/org/apache/cassandra/gms/Gossiper.java:120` |

## 核心接口

- `StorageServiceMBean`：StorageService 对 JMX/nodetool 暴露的管理接口，`StorageService` 实现位置见 `src/java/org/apache/cassandra/service/StorageService.java:292`。
- `StreamEventHandler`：bootstrap streaming 进度回调，`BootStrapper.bootstrap()` 内匿名实现处理 `STREAM_PREPARED`、`FILE_PROGRESS`、`STREAM_COMPLETE`，见 `src/java/org/apache/cassandra/dht/BootStrapper.java:85-130`。
- `SeedProvider`：由 `DatabaseDescriptor.applySeedProvider()` 反射创建，缺失或空 seeds 会直接配置失败，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1327-1342`。

## 核心数据结构

- `ApplicationState -> VersionedValue`：`prepareToJoin()` 构造本地 gossip 状态，包括 `NET_VERSION`、`HOST_ID`、`NATIVE_ADDRESS_AND_PORT`、`RELEASE_VERSION`、`SSTABLE_VERSIONS`，见 `src/java/org/apache/cassandra/service/StorageService.java:1208-1218`。
- `TokenMetadata`：ring token/host id 状态，startup 从 system tables 加载 peers，并在 bootstrap/decommission 中更新，见 `src/java/org/apache/cassandra/service/StorageService.java:1071-1103`。
- `SystemKeyspace.BootstrapState`：用于判断 `bootstrapComplete()`、`bootstrapInProgress()`、`DECOMMISSIONED`，startup 和 decommission 多处依赖，见 `src/java/org/apache/cassandra/service/StorageService.java:1130-1133`、`src/java/org/apache/cassandra/service/StorageService.java:5395-5397`。
- `StreamState`：bootstrap/decommission streaming 的 future 结果，`StorageService.bootstrap()` 等待该对象，见 `src/java/org/apache/cassandra/service/StorageService.java:2247-2256`。

## 生命周期

```text
CassandraDaemon.main
  -> CassandraDaemon.activate()
     -> applyConfig()
        -> DatabaseDescriptor.daemonInitialization()
           -> loadConfig()
           -> applyAll()
     -> setup()
        -> CommitLog.instance.start()
        -> Schema.instance.loadFromDisk()
        -> Keyspace.open(...)
        -> CommitLog.instance.recoverSegmentsOnDisk()
        -> ActiveRepairService.instance().start()
        -> StreamManager.instance.start()
        -> QueryProcessor.instance.preloadPreparedStatements()
        -> StorageService.instance.initServer()
     -> start()
        -> start native transport when bootstrap state allows
```

关键源码：

- `activate()` 调用 `applyConfig()`、`setup()`、`start()`：`src/java/org/apache/cassandra/service/CassandraDaemon.java:718-743`
- `setup()` 启动 commitlog、加载 schema/keyspaces、replay commitlog、启动 repair/streaming、进入 `StorageService.initServer()`：`src/java/org/apache/cassandra/service/CassandraDaemon.java:229-383`
- `initServer()` 注册 MBean、加载 ring state、调用 `prepareToJoin()`、执行 `joinTokenRing()`：`src/java/org/apache/cassandra/service/StorageService.java:956-1063`

## 调用链

```text
StorageService.initServer()
  -> prepareToJoin()
     -> DatabaseDescriptor.getInternodeAuthenticator().setupInternode()
     -> MessagingService.instance().listen()
     -> SystemKeyspace.getOrInitializeLocalHostId()
     -> Gossiper.instance.register(this)
     -> Gossiper.instance.start(generation, appStates)
     -> Schema.instance.startSync()
     -> HintsService.instance.startDispatch()
     -> BatchlogManager.instance.start()
  -> joinTokenRing(schemaTimeoutMillis, ringTimeoutMillis)
     -> shouldBootstrap()
     -> prepareForBootstrap(...)
     -> bootstrap(bootstrapTokens, bootstrapTimeoutMillis)
        -> Gossiper.instance.addLocalApplicationStates(BOOTSTRAPPING)
        -> repairPaxosForTopologyChange("bootstrap")
        -> startBootstrap(tokens)
           -> new BootStrapper(...).bootstrap(streamStateStore, strict)
              -> RangeStreamer.addRanges(...)
              -> RangeStreamer.fetchAsync()
        -> bootstrapFinished()
     -> finishJoiningRing(...)
```

证据：

- `prepareToJoin()`：`src/java/org/apache/cassandra/service/StorageService.java:1140-1240`
- `joinTokenRing()`：`src/java/org/apache/cassandra/service/StorageService.java:1260-1358`
- `bootstrap()`：`src/java/org/apache/cassandra/service/StorageService.java:2207-2264`
- `BootStrapper.bootstrap()`：`src/java/org/apache/cassandra/dht/BootStrapper.java:63-85`

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| `auto_bootstrap` | `src/java/org/apache/cassandra/config/Config.java:111`，读取位置 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3540-3542` | 控制首次启动且非 seed 时是否 bootstrap |
| `seed_provider` | `src/java/org/apache/cassandra/config/Config.java:121`，校验位置 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1327-1342` | 提供 seeds；缺失或空列表启动失败 |
| `initial_token` | `src/java/org/apache/cassandra/config/Config.java:130-132`，校验位置 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1404-1427` | 手工指定 bootstrap tokens |
| `num_tokens` | `src/java/org/apache/cassandra/config/Config.java:130-132`，默认/校验位置 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1404-1431` | vnode token 数量 |
| `listen_address` | `src/java/org/apache/cassandra/config/Config.java:216`，校验位置 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1177-1193` | internode 监听地址 |
| `transfer_hints_on_decommission` | `src/java/org/apache/cassandra/config/Config.java:452`，读取位置 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3744-3749` | decommission 时是否迁移 hints |

## Metrics

- Startup/Bootstrap 本身主要通过 StorageService MBean、progress events 和日志观测。
- Bootstrap streaming 通过 `StreamEventHandler` 发出 `ProgressEvent`，见 `src/java/org/apache/cassandra/dht/BootStrapper.java:85-130`。
- Load 广播使用 `StorageMetrics.load`，调用见 `src/java/org/apache/cassandra/service/LoadBroadcaster.java:89`。

## 日志

关键日志锚点：

- 启动完成：`CassandraDaemon.activate()` 的 `logger.info("Startup complete")`，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:742-744`。
- 版本、Git SHA、CQL/native protocol：`StorageService.initServer()`，见 `src/java/org/apache/cassandra/service/StorageService.java:968-972`。
- 启动 gossip：`prepareToJoin()` 的 `logger.info("Starting up server gossip")`，见 `src/java/org/apache/cassandra/service/StorageService.java:1216-1219`。
- bootstrap 成功/失败：`src/java/org/apache/cassandra/service/StorageService.java:2254-2261`。
- decommission 失败状态：`src/java/org/apache/cassandra/service/StorageService.java:5400-5416`。

## 运维关注点

- 新节点如果被配置成 seed，默认不会 auto bootstrap；应避免把新空节点直接当 seed 扩容，见 `src/java/org/apache/cassandra/service/StorageService.java:1292-1295`。
- `nodetool bootstrap resume` 对应 `StorageService.resumeBootstrap()`，只有 `isBootstrapMode && SystemKeyspace.bootstrapInProgress()` 才会真正继续，见 `src/java/org/apache/cassandra/service/StorageService.java:2320-2388`。
- 未完成 bootstrap 时，client transport 可能被拒绝启动，错误信息会指向 `nodetool help bootstrap`，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:799-804`。
- decommission 前检查 RF 与 pending ranges，force 会绕过部分 RF 保护但不会改变数据迁移风险，见 `src/java/org/apache/cassandra/service/StorageService.java:5339-5372`。

## 性能瓶颈

- `RING_DELAY_MILLIS` 的等待影响 bootstrap/decommission 速度，但用于 pending range/gossip 收敛，见 `src/java/org/apache/cassandra/service/StorageService.java:2224-2227`、`src/java/org/apache/cassandra/service/StorageService.java:5375-5378`。
- Bootstrap streaming 受 streaming connections、磁盘、网络和 range 数影响，`BootStrapper` 创建 `RangeStreamer` 时传入 `DatabaseDescriptor.getStreamingConnectionsPerHost()`，见 `src/java/org/apache/cassandra/dht/BootStrapper.java:67-75`。
- Startup commitlog replay 与 schema/keyspace 打开在 transport 前串行完成，commitlog 较大时会拉长启动时间，入口见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:339-345`。

## 常见故障

- `Unable to contact any seeds`：bootstrap 时 `Gossiper.instance.seenAnySeed()` 为 false，见 `src/java/org/apache/cassandra/service/StorageService.java:2234-2235`。
- 未完成 bootstrap 无法启动 transport：`validateTransportsCanStart()` 抛出 `IllegalStateException`，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:799-804`。
- decommission 因 RF 不足失败：非 force 模式下 `Not enough live nodes to maintain replication factor`，见 `src/java/org/apache/cassandra/service/StorageService.java:5364-5367`。
- decommission 过程中出现 streaming/执行异常会进入 `DECOMMISSION_FAILED`，见 `src/java/org/apache/cassandra/service/StorageService.java:5400-5416`。

## 测试用例

- `test/unit/org/apache/cassandra/service/StorageServiceTest.java`
- `test/unit/org/apache/cassandra/service/JoinTokenRingTest.java`
- `test/unit/org/apache/cassandra/service/BootstrapTransientTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/ring/BootstrapTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/ring/AutoBootstrapTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/DecommissionTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidWriteTimeoutsTest.java`

## 待继续

- 单独展开 replace address、move、remove node、rebuild。
- 单独展开 gossip state transitions：BOOTSTRAPPING、NORMAL、LEAVING、LEFT、HIBERNATE。
- 对 nodetool 命令到 MBean 方法做反向索引。
