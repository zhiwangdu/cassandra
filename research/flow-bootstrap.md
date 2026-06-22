# Flow: Bootstrap

## 入口

Bootstrap 是新节点或替换节点第一次进入 ring 前的数据获取流程。它从 daemon startup 进入 `StorageService.initServer()`，在 gossip 已启动但节点尚未成为 normal replica 时，计算 tokens、广播 bootstrapping 状态、从现有 replicas 拉取 pending ranges，最后完成 ring join。

## 主调用图

```text
CassandraDaemon.setup()
  -> StorageService.instance.initServer()
     -> registerMBeans()
     -> prepareToJoin()
        -> validate decommission/replacement state
        -> InternodeAuthenticator.setupInternode()
        -> MessagingService.listen()
        -> SystemKeyspace.getOrInitializeLocalHostId()
        -> Gossiper.register(this)
        -> Gossiper.start(generation, appStates)
        -> Schema.startSync()
        -> LoadBroadcaster / DiskUsageBroadcaster / HintsService / BatchlogManager start
     -> joinTokenRing(schemaTimeoutMillis, ringTimeoutMillis)
        -> shouldBootstrap()
        -> if shouldBootstrap:
             prepareForBootstrap(...)
             bootstrap(bootstrapTokens, bootstrapTimeoutMillis)
        -> else:
             load saved tokens or BootStrapper.getBootstrapTokens(...)
        -> setUpDistributedSystemKeyspaces()
        -> finishJoiningRing(shouldBootstrap, bootstrapTokens)
        -> StorageProxy.initialLoadPartitionDenylist()
```

关键源码：

- `CassandraDaemon.setup()` 在完成 commitlog/schema/keyspace/replay 后进入 `StorageService.initServer()`，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:229-383`。
- `StorageService.initServer()` 记录版本、加载 ring state、注册 MBeans、调用 `prepareToJoin()` 和 `joinTokenRing()`，见 `src/java/org/apache/cassandra/service/StorageService.java:966-1063`。
- `shouldBootstrap()` 要求 `auto_bootstrap=true`、本地未完成 bootstrap、且本节点不是 seed，见 `src/java/org/apache/cassandra/service/StorageService.java:1130-1138`。
- `prepareToJoin()` 启动 internode messaging/gossip/schema sync/hints/batchlog，见 `src/java/org/apache/cassandra/service/StorageService.java:1140-1240`。
- `joinTokenRing()` 决定 bootstrap 或直接使用 saved/generated tokens，并在成功后 finish joining ring，见 `src/java/org/apache/cassandra/service/StorageService.java:1260-1358`。

## Token 选择

```text
joinTokenRing()
  -> if shouldBootstrap:
       prepareForBootstrap(...)
       bootstrapTokens already prepared from replacement/new-node path
  -> else:
       SystemKeyspace.getSavedTokens()
       if empty:
          BootStrapper.getBootstrapTokens(...)
             -> initial_token specified: parse and reject existing token conflicts
             -> allocate_tokens_for_keyspace/local_rf: wait schema, wait gossip settle, TokenAllocation
             -> otherwise: random tokens by num_tokens
```

关键源码：

- `joinTokenRing()` 使用 saved tokens 或调用 `BootStrapper.getBootstrapTokens()`，见 `src/java/org/apache/cassandra/service/StorageService.java:1297-1321`。
- `BootStrapper.getBootstrapTokens()` 处理 `initial_token`、token allocation 和 random tokens，见 `src/java/org/apache/cassandra/dht/BootStrapper.java:156-186`。
- 手工 token 冲突会抛出 `Bootstrapping to existing token`，见 `src/java/org/apache/cassandra/dht/BootStrapper.java:190-203`。
- token allocation 会等待 schema ready 和 gossip settle，再按 keyspace/RF 调用 `TokenAllocation.allocateTokens()`，见 `src/java/org/apache/cassandra/dht/BootStrapper.java:205-239`。

## Bootstrap Streaming

```text
StorageService.bootstrap(tokens, timeout)
  -> isBootstrapMode = true
  -> SystemKeyspace.updateTokens(tokens)
  -> if normal bootstrap/replacement with different address:
       gossip TOKENS + STATUS BOOTSTRAPPING / BOOT_REPLACING
       setMode(JOINING)
       sleep RING_DELAY_MILLIS for pending range setup
  -> validate seenAnySeed()
  -> optionally reset bootstrap progress
  -> invalidateLocalRanges()
  -> repairPaxosForTopologyChange("bootstrap")
  -> startBootstrap(tokens)
     -> new BootStrapper(local, tokens, tokenMetadata)
     -> BootStrapper.bootstrap(streamStateStore, strict)
        -> new RangeStreamer(..., StreamOperation.BOOTSTRAP, ...)
        -> for each distributed keyspace:
             strategy.getPendingAddressRanges(tokenMetadata, tokens, local)
             RangeStreamer.addRanges(keyspace, pendingRanges)
        -> RangeStreamer.fetchAsync()
           -> StreamPlan.requestRanges(source, keyspace, full, transient)
           -> StreamPlan.execute()
  -> wait stream future
  -> bootstrapFinished()
```

关键源码：

- `StorageService.bootstrap()` 广播 bootstrapping/replacing 状态、等待 pending ranges、检查 seeds、重置进度、触发 Paxos repair 并等待 streaming，见 `src/java/org/apache/cassandra/service/StorageService.java:2207-2263`。
- `startBootstrap()` 构造 `BootStrapper` 并挂接 progress listener，见 `src/java/org/apache/cassandra/service/StorageService.java:2266-2275`。
- `BootStrapper.bootstrap()` 为每个 distributed keyspace 添加 pending ranges 并执行 fetch，见 `src/java/org/apache/cassandra/dht/BootStrapper.java:63-85`。
- `RangeStreamer` 构造时创建 `StreamPlan`，并默认过滤 down endpoints 与 local node，见 `src/java/org/apache/cassandra/dht/RangeStreamer.java:276-314`。
- `RangeStreamer.addRanges()` 计算 preferred endpoints、strict source、optimized work map，见 `src/java/org/apache/cassandra/dht/RangeStreamer.java:334-390`。
- `RangeStreamer.fetchAsync()` 过滤已完成的 streamed ranges，并调用 `streamPlan.requestRanges()`，见 `src/java/org/apache/cassandra/dht/RangeStreamer.java:705-784`。

## Resume Bootstrap

```text
nodetool bootstrap resume
  -> NodeProbe.resumeBootstrap(out)
     -> add BootstrapMonitor notification listener
     -> StorageServiceMBean.resumeBootstrap()
        -> if isBootstrapMode && SystemKeyspace.bootstrapInProgress():
             load saved tokens
             BootStrapper.bootstrap(...)
             on success:
                bootstrapFinished()
                if not survey mode:
                   finishJoiningRing(true, bootstrapTokens)
                   doAuthSetup(false)
                initialize/start client transports if needed
```

关键源码：

- `NodeProbe.resumeBootstrap()` 注册 `BootstrapMonitor` 并调用 MBean，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:2270-2287`。
- `StorageService.resumeBootstrap()` 只在 bootstrap mode 且 system keyspace 标记 in progress 时继续，见 `src/java/org/apache/cassandra/service/StorageService.java:2320-2388`。
- RangeStreamer 会根据 `SystemKeyspace.AvailableRanges` 跳过已完成 ranges；若发现部分进度但未设置 `cassandra.reset_bootstrap_progress`，会拒绝继续，见 `src/java/org/apache/cassandra/dht/RangeStreamer.java:705-763`。

## 状态与观测

- `SystemKeyspace.BootstrapState` 由 `getBootstrapState()` 暴露，`StorageService.getBootstrapState()` 见 `src/java/org/apache/cassandra/service/StorageService.java:2315-2318`。
- 运行期 `isBootstrapMode()` 由 StorageService/NodeProbe 暴露，见 `src/java/org/apache/cassandra/service/StorageService.java:2405-2407` 和 `src/java/org/apache/cassandra/tools/NodeProbe.java:1001-1003`。
- `BootStrapper` 将 stream prepared/file progress/session complete 转换为 progress events，见 `src/java/org/apache/cassandra/dht/BootStrapper.java:85-148`。
- 未完成 bootstrap 时 client transports 可能不启动，`CassandraDaemon.validateTransportsCanStart()` 检查见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:783-806`。

## 异常分支

- Seed 节点不会 auto bootstrap：`joinTokenRing()` 在 seed + auto_bootstrap 时记录跳过，见 `src/java/org/apache/cassandra/service/StorageService.java:1274-1295`。
- 无法联系 seeds：`StorageService.bootstrap()` 检查 `Gossiper.instance.seenAnySeed()`，失败时抛出，见 `src/java/org/apache/cassandra/service/StorageService.java:2234-2235`。
- streaming 失败：`bootstrap()` 捕获异常、设置 `JOINING_FAILED` 并返回 false，见 `src/java/org/apache/cassandra/service/StorageService.java:2254-2263`。
- 已存在部分 bootstrap 数据：`RangeStreamer.fetchAsync()` 在缺少 reset property 时拒绝继续，见 `src/java/org/apache/cassandra/dht/RangeStreamer.java:705-763`。
- 被 decommission 的节点重启：`prepareToJoin()` 需要 override property，否则拒绝重新加入，见 `src/java/org/apache/cassandra/service/StorageService.java:1145-1158`。

## 配置入口

- `auto_bootstrap` 控制是否参与首次 bootstrap，定义见 `src/java/org/apache/cassandra/config/Config.java:111`，读取见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3540-3542`。
- `initial_token` / `num_tokens` 影响 token 选择，定义见 `src/java/org/apache/cassandra/config/Config.java:130-132`。
- `allocate_tokens_for_keyspace` / `allocate_tokens_for_local_replication_factor` 走 token allocation，读取入口见 `src/java/org/apache/cassandra/dht/BootStrapper.java:156-186`。
- `streaming_connections_per_host` 传入 `RangeStreamer`，见 `src/java/org/apache/cassandra/dht/BootStrapper.java:67-75`。
- `cassandra.reset_bootstrap_progress` 控制 resume 时是否忽略/重置已完成 ranges，使用见 `src/java/org/apache/cassandra/dht/RangeStreamer.java:705-763`。

## 测试锚点

- `JoinTokenRingTest` 覆盖 join ring/bootstrap 分支，见 `test/unit/org/apache/cassandra/service/JoinTokenRingTest.java`。
- `BootstrapTransientTest` 覆盖 transient replication 下的 bootstrap source retrieval，见 `test/unit/org/apache/cassandra/service/BootstrapTransientTest.java:56-60`。
- `BootstrapTest` 覆盖 bootstrap、resume、部分进度失败、读写期间 bootstrap、JMX 状态，见 `test/distributed/org/apache/cassandra/distributed/test/ring/BootstrapTest.java:117-319` 和 `test/distributed/org/apache/cassandra/distributed/test/ring/BootstrapTest.java:389-460`。
- `AutoBootstrapTest` 覆盖 auto bootstrap 扩容路径，见 `test/distributed/org/apache/cassandra/distributed/test/ring/AutoBootstrapTest.java:41-53`。
- `BootstrapBinaryDisabledTest` 覆盖 bootstrap 期间 binary transport 行为，见 `test/distributed/org/apache/cassandra/distributed/test/BootstrapBinaryDisabledTest.java`。
