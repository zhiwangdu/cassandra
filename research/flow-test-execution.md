# Flow: Test Execution

## 1. 单 JVM CQL 单测执行

目标：说明 `ant test -Dtest.name=...` 到 `CQLTester.execute()` 的路径。

```
ant test
  -> build.xml:test
  -> testhelper
  -> testmacrohelper
  -> junit-timeout fork
  -> JUnit @BeforeClass CQLTester.setUpClass()
  -> CQLTester.prePrepareServer()
  -> ServerTestUtils.daemonInitialization()
  -> ServerTestUtils.prepareServer()
  -> JUnit @Before CQLTester.beforeTest()
  -> test method
  -> createTable/schemaChange/execute/assertRows
  -> JUnit @After CQLTester.afterTest()
  -> JUnit @AfterClass CQLTester.tearDownClass()
```

源码锚点：

- `build.xml:test` 从 `test.unit.src` 中匹配 `**/${test.name}.java`，见 `build.xml:1665-1671`。
- `testmacrohelper` 创建 JUnit runner、formatter、JVM 参数、classpath 和 batchtest，见 `build.xml:1123-1218`。
- `CQLTester.setUpClass()` 调 `prePrepareServer()` 与 `prepareServer()`，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:402-419`。
- `ServerTestUtils.prepareServer()` 清理并初始化单 JVM server 状态，见 `test/unit/org/apache/cassandra/ServerTestUtils.java:96-138`。
- `beforeTest()` 创建默认 keyspace，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:453-458`。
- `createTable()` 生成表名并执行 schema change，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1030-1046`。
- `execute()` 进入 `executeFormattedQuery()`，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1620-1669`。
- `assertRows` 逐列比较查询结果并报告额外/缺失行，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1840-1895`。

关键判断：

- 默认执行路径是 internal CQL，不经过 native protocol。
- `schemaChange()` 和 `executeFormattedQuery()` 都使用 internal client state，因此权限、认证和部分 guardrail 测试不能只靠这条路径。

## 2. CQLTester Native Protocol 执行

目标：说明 `executeNet()` 如何从同一个单 JVM server 走真实 native transport。

```
test method
  -> CQLTester.executeNet(...)
  -> sessionNet(protocolVersion)
  -> requireNetwork()
  -> startServices()
       -> VirtualKeyspaceRegistry.register(VirtualSchemaKeyspace)
       -> StorageService.instance.initServer()
       -> SchemaLoader.startGossiper()
  -> startServer()
       -> allocate native port
       -> Server.Builder.withHost/withPort
       -> ClientMetrics.init
       -> server.start()
  -> getCluster/getSession
       -> Java driver Cluster.builder()
       -> connect()
  -> driver Session.execute()
```

源码锚点：

- `executeNet()` 调 `sessionNet()`，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1517-1557`。
- `sessionNet()` 调 `requireNetwork()` 并取得 session，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1564-1585`。
- `requireNetwork()` 启动 services 和 server，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:613-631`。
- `startServices()` 注册 virtual schema keyspace、初始化 `StorageService`、启动 gossip，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:633-638`。
- `startServer()` 自动分配端口、构造 native transport server、初始化 client metrics 并 start，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:667-675`。
- `initClientCluster()` 配置 Java driver contact point、port、socket timeout、protocol version、credentials 和 netty options，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:677-707`。

适用场景：

- native protocol、driver paging、protocol version、auth、warning/error 映射。
- 需要真实 client session 的 CQL 行为。

不适用场景：

- 多节点一致性、bootstrap、repair、streaming，应使用 `test-jvm-dtest`。

## 3. In-JVM Distributed Test 启动

目标：说明 `ant test-jvm-dtest -Dtest.name=...` 到多节点启动完成的路径。

```
ant test-jvm-dtest
  -> build.xml:test-jvm-dtest
  -> testmacro(inputdir=test/distributed, forkmode=once)
  -> JUnit @BeforeClass TestBaseImpl.beforeClass()
  -> ICluster.setup()
  -> test method
  -> Cluster.build(nodeCount).withConfig(...).start()
  -> AbstractCluster.AbstractBuilder.<init>()
       -> mark DTEST_IS_IN_JVM_DTEST
       -> reset unit-test-only properties
       -> configure shared classes
  -> AbstractCluster.<init>()
       -> createInstanceConfig for each node
       -> newInstanceWrapperInternal
       -> instanceMap
  -> AbstractCluster.startup()
       -> install uncaught handler
       -> start auto_bootstrap nodes sequentially
       -> start remaining nodes in parallel
       -> wait live member monitor
  -> Instance.startup(ICluster)
       -> DatabaseDescriptor.daemonInitialization()
       -> CommitLog.start()
       -> startup checks
       -> persist local metadata
       -> populate token metadata
       -> load schema
       -> setup virtual keyspaces
```

源码锚点：

- `test-jvm-dtest` 使用 `test.distributed.src`、forkmode once、dtest logback、ring delay、skip sync 和 8G heap，见 `build.xml:1762-1770`。
- `TestBaseImpl.beforeClass()` 调 `ICluster.setup()`，见 `test/distributed/org/apache/cassandra/distributed/test/TestBaseImpl.java:60-70`。
- `Cluster.build/create` 是当前版本 dtest cluster 入口，见 `test/distributed/org/apache/cassandra/distributed/Cluster.java:45-72`。
- `AbstractBuilder` 标记 dtest 环境并设置 shared classes，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:183-203`。
- `AbstractCluster` 构造 nodes、configs、instances 和 instance map，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:541-573`。
- `createInstanceConfig()` 生成配置并做 vnode/token 约束，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:581-621`。
- `AbstractCluster.startup()` 控制串行/并行启动和 live member monitor，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:1018-1050`。
- `Instance.startup()` 执行节点内部启动流程，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:581-650`。

关键判断：

- dtest 不是多进程真实集群，但每个节点有隔离 classloader 和独立 config/root/log path。
- `auto_bootstrap=true` 节点串行启动，用于减少并发 bootstrap range movement 的不确定性。

## 4. DTest Schema Change 与查询

目标：说明 cluster schema change、coordinator query、paging 和 tracing 的路径。

```
test method
  -> cluster.schemaChange("CREATE TABLE ...")
  -> AbstractCluster.schemaChange(query, ignoreStoppedInstances=false)
  -> choose instance
  -> SchemaChangeMonitor.startPolling()
  -> instance.coordinator().execute(query, ALL)
  -> SchemaChangeMonitor.waitForCompletion()

test method
  -> cluster.coordinator(1).execute(...)
  -> Coordinator.executeWithResult(...)
  -> instance.sync(...)
  -> CoordinatorHelper.unsafeExecuteInternal(...)
  -> QueryProcessor / statement execution inside node1
```

源码锚点：

- `schemaChange()` 选择运行节点、启动 monitor、以 `ALL` 执行 DDL 并等待完成，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:823-863`。
- `SchemaChangeMonitor` 提供 `ignoreStoppedInstances()`、`waitForCompletion()` 和 timeout 错误，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:889-940`。
- `cluster.coordinator(node)` 是 1-based 索引，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:662-668`。
- `ICoordinator` 暴露 execute、paging、tracing、SERIAL/commit CL 重载，见 `test/distributed/org/apache/cassandra/distributed/api/ICoordinator.java:27-72`。
- `Coordinator.executeWithResult()` 在目标实例内同步执行 internal query，见 `test/distributed/org/apache/cassandra/distributed/impl/Coordinator.java:58-95`。
- paging 分支构造 `QueryOptions` 并迭代 paging state，见 `test/distributed/org/apache/cassandra/distributed/impl/Coordinator.java:115-180`。

关键判断：

- dtest CQL 执行是在指定节点内触发 coordinator 行为，而不是 Java driver 网络客户端。
- 多节点一致性由 Cassandra 的 coordinator/read/write/messaging 路径决定；测试可以用 CL 控制成功/失败条件。

## 5. DTest 消息过滤与消息投递

目标：说明如何模拟网络 drop/delay/failure。

```
test method
  -> cluster.filters() or cluster.verbs(Verb.X)
  -> install message rule
  -> coordinator sends internode message
  -> AbstractCluster.deliverMessage(to, message)
  -> optional messageSink.accept(to, message)
  -> target Instance.receiveMessage(message)
  -> deserialize
  -> Tracing.initializeFromMessage
  -> verb.stage.executor().execute(...)
  -> MessagingService.instance().inboundSink.accept(messageIn)
```

源码锚点：

- `filters()` 返回全局 message filters，`verbs(Verb...)` 根据 verb id 构造 filter builder，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:788-813`。
- `setMessageSink()`/`deliverMessage()` 可拦截或转发到目标 instance，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:793-805`。
- `Instance.receiveMessage()` 反序列化消息、恢复 tracing、按 verb stage executor 入队，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:500-529`。

适用场景：

- read timeout、write timeout、repair validation timeout、streaming failure、gossip partition、Paxos contention、hint replay 边界。

## 6. DTest Nodetool

目标：说明 `cluster.get(1).nodetoolResult(...)` 的内部调用路径。

```
test method
  -> cluster.get(1).nodetoolResult("repair", ...)
  -> Instance.nodetoolResult(withNotifications, args)
  -> instance.sync(...)
  -> CapturingOutput
  -> DTestNodeTool(new InternalNodeProbeFactory, output)
  -> InternalNodeProbe.connect()
       -> no remote JMX
       -> bind StorageService/MessagingService/StreamManager/...
  -> NodeTool.execute(args)
  -> capture System.exit as rc
  -> return NodeToolResult(rc, notifications, latestError, stdout, stderr)
```

源码锚点：

- `Instance.nodetoolResult()` 在节点隔离上下文运行并捕获 rc/stdout/stderr/notification，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:984-1025`。
- `DTestNodeTool` 继承 `NodeTool`，绑定 `InternalNodeProbe` 并监听 `StorageServiceMBean` notification，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:1071-1134`。
- `InternalNodeProbe.connect()` 明确不走 JMX，直接绑定 Cassandra 服务实例，见 `test/distributed/org/apache/cassandra/distributed/mock/nodetool/InternalNodeProbe.java:61-85`。
- `ToolRunner.invokeNodetoolJvmDtest()` 可在工具测试中包装同一条路径，见 `test/unit/org/apache/cassandra/tools/ToolRunner.java:287-305`。

关键判断：

- 这条路径验证 nodetool 命令逻辑和 MBean 调用语义，但不是远程 JMX 连接测试。
- 需要远程 JMX 行为时，应看 `test/distributed/.../jmx` 测试和 `CQLTester.startJMXServer()` 相关路径，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:370-399`。

## 7. 升级测试执行

目标：说明 `UpgradeTestBase.TestCase.run()` 的版本切换主线。

```
test method
  -> new UpgradeTestBase.TestCase()
       -> nodes(n)
       -> upgradesToCurrentFrom(...)
       -> setup(...)
       -> runBeforeClusterUpgrade(...)
       -> runBeforeNodeRestart(...)
       -> runAfterNodeUpgrade(...)
       -> runAfterClusterUpgrade(...)
  -> run()
  -> for each upgrade path
       -> UpgradeableCluster.create(nodeCount, initialVersion, config, builder)
       -> setup.run(cluster)
       -> for each target version
            -> runBeforeClusterUpgrade
            -> for each node to upgrade
                 -> shutdown
                 -> triggerGC
                 -> setVersion(nextVersion)
                 -> runBeforeNodeRestart
                 -> startup
                 -> runAfterNodeUpgrade
            -> runAfterClusterUpgrade
            -> checkAndResetUncaughtExceptions
```

源码锚点：

- `UpgradeableCluster` 支持指定版本创建 cluster，见 `test/distributed/org/apache/cassandra/distributed/UpgradeableCluster.java:49-89`。
- `UpgradeTestBase` 定义 supported upgrade graph，见 `test/distributed/org/apache/cassandra/distributed/upgrade/UpgradeTestBase.java:90-98`。
- `TestCase` 的 hook 字段和 builder/config hook，见 `test/distributed/org/apache/cassandra/distributed/upgrade/UpgradeTestBase.java:142-155`、`test/distributed/org/apache/cassandra/distributed/upgrade/UpgradeTestBase.java:270-310`。
- `run()` 的停节点、换版本、重启和 hook 顺序，见 `test/distributed/org/apache/cassandra/distributed/upgrade/UpgradeTestBase.java:312-368`。
- build 注释说明 upgrade dtest 需要各版本 `dtest-*.jar`，见 `build.xml:1807-1819`。

## 8. 日志与输出定位

```
unit test:
  build/test/logs/${cassandra.testtag}/TEST-${suitename}.log

in-JVM dtest:
  build/test/logs/${cassandra.testtag}/${suitename}/${cluster_id}/${instance_id}/system.log

JUnit XML:
  build/test/output/.../TEST-*.xml
```

源码锚点：

- `testmacrohelper` 设置 XML/brief formatter 和 `cassandra.testtag`，见 `build.xml:1153-1179`。
- 普通单测 logback file appender 路径，见 `test/conf/logback-test.xml:27-38`。
- dtest logback 使用 `ClusterIDDefiner` 和 `InstanceIDDefiner` 组织每节点 system.log，见 `test/conf/logback-dtest.xml:20-32`。

## 9. 失败定位顺序

1. 先看 JUnit XML/brief failure，确认是 assertion、timeout、assumption 还是 uncaught background exception。
2. 单 JVM CQL 测试看 `CQLTester.execute()`/`schemaChange()` 报错是否来自 internal CQL；权限/native 相关失败优先复现 `executeNet()`。
3. dtest 启动失败看每节点 `system.log`，再看 `AbstractCluster.startup()` 的 live member monitor 和 `Instance.startup()` 启动阶段。
4. dtest 网络失败看 `cluster.filters()`/`verbs()` 是否拦截了目标 verb，再看 `Instance.receiveMessage()` 是否投递到正确 stage。
5. nodetool 失败同时看 `NodeToolResult` 的 rc、stdout、stderr、notification 和 `latestError`。
6. upgrade 失败看异常中标注的 upgrade path/target version，并检查是否准备了所有版本的 dtest jar。
