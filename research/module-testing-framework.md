# Testing Framework

## 范围

本文件覆盖 Cassandra 5.0 分支内置测试框架的源码结构和执行模型，重点是单 JVM 单元测试、`CQLTester`、in-JVM distributed test、升级测试、fuzz/生成式测试、工具测试和 Ant 测试入口。它不是测试用例清单；测试用例按主题索引在 `notes/source-map.md`。

## 设计目标

Cassandra 的测试框架要同时支撑三类反馈：

1. 单 JVM 快速验证：直接初始化 `DatabaseDescriptor`、schema、system keyspace、commitlog/data/hints/cache 目录，使用内部 CQL 执行路径验证语义。
2. 协议级验证：按需启动 native transport 和 Java driver session，让测试走真实网络协议、认证、paging、protocol version 和 warning/error 映射。
3. 多节点行为验证：在一个 JVM 内创建多个隔离 Cassandra 节点，用独立 classloader 和实例配置模拟网络、gossip、bootstrap、repair、streaming、nodetool、升级和故障注入。

源码证据：

- `CQLTester` 是 CQL 测试基类，持有 test name、默认 keyspace、native/JMX server、driver cluster/session 缓存和 protocol version 列表，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:200-243`。
- `SchemaLoader` 的 `loadSchema()` 会准备 server 并启动 gossiper，见 `test/unit/org/apache/cassandra/SchemaLoader.java:59-69`。
- `ServerTestUtils.prepareServer()` 清理目录、安装 security manager、初始化 `Keyspace`、持久化 local metadata、初始化 audit log，见 `test/unit/org/apache/cassandra/ServerTestUtils.java:96-138`。
- `Cluster` 是当前版本 in-JVM dtest 的多节点入口，`Cluster.create/build` 最终委托 `AbstractCluster`，见 `test/distributed/org/apache/cassandra/distributed/Cluster.java:29-72`。
- `AbstractCluster.AbstractBuilder` 在构造时设置 in-JVM dtest 标记并重置部分单测优化属性，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:183-203`。
- `Instance` 是单个隔离节点 wrapper，继承 `IsolatedExecutor` 并写入 cluster id、instance id、broadcast address、override config，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:175-217`。
- `build.xml` 的 `testmacrohelper` 定义 JUnit fork、classpath、jvmarg、batchtest 和输出目录，见 `build.xml:1123-1218`。

## 解决的问题

- 单元测试需要在不启动完整 daemon 的情况下初始化足够的 Cassandra runtime；`ServerTestUtils.prepareServer()` 清理目录并初始化 `Keyspace`、system metadata、audit log，见 `test/unit/org/apache/cassandra/ServerTestUtils.java:96-138`。
- CQL 语义测试需要快速创建/销毁 keyspace/table/view/type/function，并复用 internal CQL execution；`CQLTester.beforeTest()` 和 `afterTest()` 管理 per-test schema，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:453-470`。
- 协议/auth/paging 测试必须走真实 native transport；`CQLTester.requireNetwork()` 启动 StorageService、gossip 和 native transport，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:613-631`。
- 多节点一致性、repair、streaming、bootstrap、upgrade 需要多个隔离节点；`AbstractCluster.startup()` 管理 in-JVM 节点启动顺序和 live member 收敛，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:1018-1050`。
- nodetool/JMX 类操作需要在测试中捕获 stdout、exit code 和 notifications；`Instance.nodetoolResult()` 与 `InternalNodeProbe` 提供 in-process probe，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:984-1025` 和 `test/distributed/org/apache/cassandra/distributed/mock/nodetool/InternalNodeProbe.java:61-85`。

## 设计取舍

- `CQLTester.execute()` 选择 internal execution，速度快且定位服务端逻辑明确，但不覆盖 native protocol、auth 和部分 guardrails，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1630-1669`。
- `executeNet()` 选择 driver/native protocol，覆盖真实客户端行为，但需要启动 transport 和复用 driver session，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1517-1585`。
- in-JVM dtest 用 classloader 隔离替代多进程，执行快且可注入 message filters，但要显式处理静态状态、JMX、executor、crypto provider 和 shutdown，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:175-217` 和 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:930-961`。
- upgrade dtest 复用 dtest API jar 和版本切换机制，降低真实集群升级成本，但要求提前构建各版本 `dtest-*.jar`，见 `build.xml:1733-1758` 和 `build.xml:1807-1819`。

## 核心类

| 类 | 作用 |
|---|---|
| `CQLTester` | CQL 单测基类、schema helper、internal/native query helper、assert helper，定义见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:200-243` |
| `SchemaLoader` | 测试 schema/server/gossiper bootstrap helper，见 `test/unit/org/apache/cassandra/SchemaLoader.java:59-92` |
| `ServerTestUtils` | daemon initialization、目录清理、system metadata、audit log、security manager helper，见 `test/unit/org/apache/cassandra/ServerTestUtils.java:63-138` |
| `Cluster` | in-JVM dtest cluster builder 入口，见 `test/distributed/org/apache/cassandra/distributed/Cluster.java:29-72` |
| `AbstractCluster` | 多节点生命周期、schema agreement、message filters、startup/shutdown 管理，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:541-573` |
| `Instance` | 单个隔离 Cassandra 节点 wrapper，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:175-217` |
| `Coordinator` | dtest CQL coordinator API 实现，见 `test/distributed/org/apache/cassandra/distributed/impl/Coordinator.java:50-95` |
| `InternalNodeProbe` | dtest nodetool/JMX 的 in-process probe，见 `test/distributed/org/apache/cassandra/distributed/mock/nodetool/InternalNodeProbe.java:50-85` |
| `UpgradeableCluster` / `UpgradeTestBase` | mixed-version/upgrade dtest cluster 与 DSL，见 `test/distributed/org/apache/cassandra/distributed/UpgradeableCluster.java:29-89` 和 `test/distributed/org/apache/cassandra/distributed/upgrade/UpgradeTestBase.java:58-98` |

## 核心接口

- `ICoordinator.execute()` / `executeWithResult()` / `executeWithPaging()`：dtest 在指定节点上执行 CQL 的接口，见 `test/distributed/org/apache/cassandra/distributed/api/ICoordinator.java:27-72`。
- `ICluster` / `Cluster.Builder`：cluster 创建、配置、启动和 bootstrap 新节点入口，当前可见 builder 见 `test/distributed/org/apache/cassandra/distributed/Cluster.java:45-72`。
- `IInstance` / `Instance.runOnInstance()` / `Instance.callOnInstance()`：在隔离节点 classloader 中执行代码，wrapper 定义见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:175-217`。
- `MessageFilters`：按 verb/source/destination drop/delay/transform internode messages，cluster 暴露入口见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:788-813`。
- `NodeToolResult` 路径：`Instance.nodetoolResult()` 捕获 nodetool rc/stdout/stderr/notifications，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:984-1025`。

## 核心数据结构

- `UntypedResultSet` / `Object[][]`：`CQLTester` internal 查询和断言的主要结果结构，`assertRows` 比对入口见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1840-1895`。
- `InstanceConfig`：dtest 节点配置、token/topology/ports/datadir 等，创建入口见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:581-621`。
- `ConsistencyLevel`：dtest API 自带 CL enum，包含 `SERIAL`、`LOCAL_SERIAL`、`NODE_LOCAL`，见 `test/distributed/org/apache/cassandra/distributed/api/ConsistencyLevel.java:21-40`。
- `MessageFilters.Filter` / `MessageImpl`：dtest internode message 过滤和转发结构，cluster delivery 入口见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:788-813`。
- `TestCase`：upgrade dtest 的版本路径、hook、config/builder updater 容器，见 `test/distributed/org/apache/cassandra/distributed/upgrade/UpgradeTestBase.java:142-155` 和 `test/distributed/org/apache/cassandra/distributed/upgrade/UpgradeTestBase.java:270-310`。

## 生命周期

```text
Unit CQL test
  -> CQLTester.setUpClass()
     -> ServerTestUtils.daemonInitialization()
     -> ServerTestUtils.prepareServer()
  -> beforeTest()
     -> create test keyspaces
  -> test method
     -> createTable/createIndex/execute/assertRows
  -> afterTest()
     -> drop test schema and reset prepared settings
```

```text
In-JVM dtest
  -> Cluster.build(...).create/startup()
     -> AbstractCluster creates InstanceConfig and Instance wrappers
     -> Instance.startup() performs Cassandra startup inside isolated classloader
  -> cluster.schemaChange(...)
     -> coordinator(node).execute(..., ALL)
     -> wait schema agreement
  -> test logic with coordinator/message filters/nodetool
  -> cluster.close()
```

```text
Upgrade test
  -> UpgradeTestBase.TestCase.run()
     -> create initial-version cluster
     -> setup hooks
     -> for each target version and node:
          shutdown node
          setVersion(...)
          startup node
          before/after node hooks
     -> after cluster hook and exception audit
```

## 调用链

- 单 JVM server 准备：`CQLTester.setUpClass()` -> `prePrepareServer()` -> `ServerTestUtils.daemonInitialization()` -> `prepareServer()`，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:402-419` 和 `test/unit/org/apache/cassandra/ServerTestUtils.java:63-138`。
- Internal CQL：`CQLTester.execute()` -> `executeFormattedQuery()` -> `QueryProcessor.executeInternal/executeOnceInternal`，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1620-1669`。
- Native CQL：`executeNet()` -> `sessionNet()` -> `requireNetwork()` -> driver session execute，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1517-1585` 和 `test/unit/org/apache/cassandra/cql3/CQLTester.java:613-631`。
- dtest schema change：`AbstractCluster.schemaChange()` -> coordinator execute at CL ALL -> `SchemaChangeMonitor` wait，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:823-863`。
- dtest nodetool：`Instance.nodetoolResult()` -> `DTestNodeTool` -> `InternalNodeProbe` direct MBean bindings，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:984-1134` 和 `test/distributed/org/apache/cassandra/distributed/mock/nodetool/InternalNodeProbe.java:61-85`。

## 核心分层

| 层 | 入口 | 作用 | 证据 |
|---|---|---|---|
| Ant/JUnit runner | `testmacrohelper`、`test`、`test-jvm-dtest` | 选择测试目录、fork 策略、JVM 参数、JUnit formatter、batchtest | `build.xml:1123-1218`、`build.xml:1665-1671`、`build.xml:1762-1770` |
| 单 JVM server 准备 | `ServerTestUtils`、`SchemaLoader` | 初始化 daemon 配置、固定 snitch、清理目录、启动 gossip、加载预置 schema | `test/unit/org/apache/cassandra/ServerTestUtils.java:63-94`、`test/unit/org/apache/cassandra/SchemaLoader.java:80-92` |
| CQL 单测 DSL | `CQLTester` | 创建 keyspace/table/index/view/type/function，执行 internal CQL 或 native CQL，断言结果/错误 | `test/unit/org/apache/cassandra/cql3/CQLTester.java:402-419`、`test/unit/org/apache/cassandra/cql3/CQLTester.java:1030-1046`、`test/unit/org/apache/cassandra/cql3/CQLTester.java:1620-1669` |
| in-JVM dtest cluster | `Cluster`、`AbstractCluster`、`Instance` | 在一个 JVM 中启动多个隔离 Cassandra 节点，配置 token/topology/ports，控制启动、schema agreement、消息过滤和 shutdown | `test/distributed/org/apache/cassandra/distributed/Cluster.java:45-72`、`test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:541-573`、`test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:1018-1050` |
| dtest coordinator API | `ICoordinator`、`Coordinator` | 在指定节点上执行 CQL、paging、SERIAL/commit CL、tracing | `test/distributed/org/apache/cassandra/distributed/api/ICoordinator.java:27-72`、`test/distributed/org/apache/cassandra/distributed/impl/Coordinator.java:50-95`、`test/distributed/org/apache/cassandra/distributed/impl/Coordinator.java:108-180` |
| dtest nodetool | `Instance.nodetoolResult`、`InternalNodeProbe` | 在节点 classloader 内运行 nodetool，不走远程 JMX，直接绑定 MBean 实例并捕获 stdout/stderr/notification | `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:984-1025`、`test/distributed/org/apache/cassandra/distributed/impl/Instance.java:1071-1134`、`test/distributed/org/apache/cassandra/distributed/mock/nodetool/InternalNodeProbe.java:50-85` |
| 升级测试 | `UpgradeableCluster`、`UpgradeTestBase` | 使用多版本 dtest jar 顺序停节点、换版本、重启、执行 hook，验证混合版本兼容性 | `test/distributed/org/apache/cassandra/distributed/UpgradeableCluster.java:29-89`、`test/distributed/org/apache/cassandra/distributed/upgrade/UpgradeTestBase.java:58-98`、`test/distributed/org/apache/cassandra/distributed/upgrade/UpgradeTestBase.java:312-368` |
| Fuzz/生成式测试 | `distributed.fuzz.FuzzTestBase`、`repair.FuzzTestBase` | 生成 schema/data/SSTable 或模拟 repair 状态组合，覆盖普通示例测试难以枚举的状态空间 | `test/distributed/org/apache/cassandra/distributed/fuzz/FuzzTestBase.java:37-63`、`test/distributed/org/apache/cassandra/distributed/fuzz/FuzzTestBase.java:78-105`、`test/unit/org/apache/cassandra/repair/FuzzTestBase.java:163-180` |

## 单 JVM 测试模型

### Server 准备

`CQLTester.setUpClass()` 的主线是：

1. `prePrepareServer()` 设置 superuser setup delay、执行 `ServerTestUtils.daemonInitialization()`、按需设置 row cache，并把 partitioner 固定为 `Murmur3Partitioner`，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:411-419`。
2. `prepareServer()` 委托 `ServerTestUtils.prepareServer()`，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:360-363`。
3. `ServerTestUtils.daemonInitialization()` 执行 `DatabaseDescriptor.daemonInitialization()` 后安装固定 datacenter/rack 的 snitch，见 `test/unit/org/apache/cassandra/ServerTestUtils.java:63-94`。
4. `ServerTestUtils.prepareServer()` 只执行一次，开启 transient replication、清理 commitlog/cdc/hints/cache/data、设置默认 uncaught handler、安装 security manager、初始化 keyspace/system metadata/audit log，见 `test/unit/org/apache/cassandra/ServerTestUtils.java:96-138`。

`SchemaLoader` 是更通用的测试 schema bootstrap：`loadSchema()` 准备 server 后启动 gossiper；`startGossiper()` 会设置 `ALLOW_UNSAFE_JOIN` 并在未启用时启动 `Gossiper`，见 `test/unit/org/apache/cassandra/SchemaLoader.java:59-69`、`test/unit/org/apache/cassandra/SchemaLoader.java:86-92`。

### 每个测试的 schema 生命周期

`CQLTester.beforeTest()` 为 `cql_test_keyspace` 和 `cql_test_keyspace_alt` 创建 SimpleStrategy keyspace，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:453-458`。`afterTest()` 先 drop per-test keyspace，再恢复 prepared 配置，随后清理由 helper 记录的 keyspace/table/view/type/function/aggregate，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:460-470`。

`createTable()` 生成当前表名、把 `%s` 格式化为当前表全名，然后通过 `schemaChange()` 执行 DDL，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1030-1046`。`schemaChange()` 使用 `ClientState.forInternalCalls`、`QueryProcessor.parseStatement`、`statement.validate` 和 `statement.executeLocally`，这说明单元测试 DDL 不走 native protocol，也绕过普通客户端权限模型，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1489-1502`。

### CQL 执行与断言

`execute()` 格式化当前表查询后调用 `executeFormattedQuery()`，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1620-1623`。`executeFormattedQuery()` 的默认路径是 `QueryProcessor.executeInternal` 或 `QueryProcessor.executeOnceInternal`；注释明确指出它使用 `ClientState.forInternalCalls()`，因此不会应用权限检查和 guardrails，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1630-1669`。

因此：

- 需要验证真实客户端 auth/permission/guardrail/native protocol 时，应使用 `executeNet*` 或专门的 transport 测试。
- 需要验证 coordinator/read/write/storage 语义时，`execute()` 更快，失败点也更贴近服务端内部执行。

`executeNet()` 系列通过 `sessionNet()` 走 Java driver；`sessionNet()` 会调用 `requireNetwork()`，再复用或创建 driver session，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1517-1585`。`requireNetwork()` 启动 storage service、gossip、native transport server；driver builder 绑定 loopback 地址、自动分配端口、protocol version 和 socket timeout，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:613-631`、`test/unit/org/apache/cassandra/cql3/CQLTester.java:667-707`。

结果断言集中在 `assertRows`、`row`、`rows`、`assertEmpty`、`assertInvalid*` 等 helper。`assertRows` 逐列按 column type 序列化/反序列化比对，并在额外行或缺行时给出详细错误，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1840-1895`。`assertInvalidThrowMessage()` 可以选择 internal 执行或 network 执行，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:2154-2194`。

### InMemory 子类

`CQLTester.InMemory` 为需要内存文件系统的测试创建全局 in-memory filesystem、设置 `IGNORE_MISSING_NATIVE_FILE_HINTS` 并创建 tmp 目录，然后仍然调用 `CQLTester.setUpClass()`；每个测试前默认清理 filesystem listener，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:2909-2935`。

## In-JVM Distributed Test 模型

### Cluster 构建

`Cluster.build()`/`Cluster.create()` 是当前版本 dtest 的入口，`Builder` 默认设置 `CURRENT_VERSION`，见 `test/distributed/org/apache/cassandra/distributed/Cluster.java:45-72`。

`AbstractCluster.AbstractBuilder` 构造时设置三件事：

- 标记 `DTEST_IS_IN_JVM_DTEST=true`。
- 重置 `TEST_FLUSH_LOCAL_SCHEMA_CHANGES`、`NON_GRACEFUL_SHUTDOWN` 这类单测优化属性。
- 默认共享类谓词使用 `SHARED_PREDICATE`，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:145-203`。

`AbstractCluster` 构造时保存 root、classloader、transformer、subnet、token supplier、topology、config updater、broadcast port、datadir count、message filters 等状态，然后按 node count 调 `createInstanceConfig()` 和 `newInstanceWrapperInternal()` 创建实例列表与 broadcast address 索引，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:541-573`。

`createInstanceConfig()` 根据 provision strategy、token supplier、network topology 生成 `InstanceConfig`，写入 cluster id，并校验 vnode/token 数量、测试配置和 initial token/gossip 条件，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:581-621`。`AbstractClusterTest` 专门覆盖这些 vnode/token 假设失败条件，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractClusterTest.java:41-164`。

### 节点启动

`AbstractCluster.startup()` 先安装 uncaught exception handler，再用 `AllMembersAliveMonitor` 等待 live member 收敛；启动顺序把第一个节点和 `auto_bootstrap=true` 的节点串行启动，其余节点并行启动，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:1018-1050`。

`Instance.startup(ICluster)` 在节点隔离上下文中执行 Cassandra 启动的一部分真实流程：

- 设置 executor factory、版本断言和 gossip 相关 property。
- 分配 distributed test snitch。
- 按需启动 JMX。
- 执行 `DatabaseDescriptor.daemonInitialization()`、logging startup、filesystem error handler、system data migration、commitlog start、startup checks。
- 持久化 local metadata、迁移 system keyspace、填充 token metadata、从磁盘加载 schema、设置 virtual keyspaces。

证据见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:581-650`。

### Schema 与查询

`AbstractCluster.schemaChange()` 选择节点，创建 `SchemaChangeMonitor`，在目标节点执行 `instance.coordinator().execute(query, ConsistencyLevel.ALL)`，再等待 schema agreement，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:823-863`。

`cluster.coordinator(node)` 是 1-based 索引，返回该节点的 coordinator，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:662-668`。`Coordinator.executeWithResult()` 把执行包进目标 `Instance.sync()`，核心执行委托 `CoordinatorHelper.unsafeExecuteInternal`；paging 分支手动构造 `QueryOptions` 并重复调用 `SelectStatement.execute` 直到 paging state 为空，见 `test/distributed/org/apache/cassandra/distributed/impl/Coordinator.java:58-95`、`test/distributed/org/apache/cassandra/distributed/impl/Coordinator.java:115-180`。

`ICoordinator` 暴露 `execute`、`executeWithResult`、paging、tracing 和 `instance()`，并支持 SERIAL/commit CL 的重载，见 `test/distributed/org/apache/cassandra/distributed/api/ICoordinator.java:27-72`。dtest 自己的 `ConsistencyLevel` enum 包括 `SERIAL`、`LOCAL_SERIAL`、`NODE_LOCAL`，并通过 numeric code 映射到 Cassandra CL，见 `test/distributed/org/apache/cassandra/distributed/api/ConsistencyLevel.java:21-40`、`test/distributed/org/apache/cassandra/distributed/impl/Coordinator.java:79-89`。

### 消息过滤与故障注入

`AbstractCluster` 持有 `MessageFilters`，`filters()` 返回全局过滤器，`verbs(Verb...)` 用 verb id 构造 filter builder；`setMessageSink()` 允许安装自定义 message sink，`deliverMessage()` 会把消息送给目标 instance 或 sink，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:788-813`。

`Instance.receiveMessage()` 反序列化消息、恢复 tracing state，并按 verb 的 stage executor 投递到 `MessagingService.instance().inboundSink`；如果 executor 已关闭则记录 dropped message，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:500-529`。

这层能力是很多 repair、streaming、read repair、timeout、gossip、paxos、hint 测试的基础：测试可以 drop/delay 某些 verb、停某些节点、再观察 coordinator 的错误路径和 recovery。

### Nodetool/JMX 测试路径

in-JVM dtest 的 nodetool 不需要启动外部 `jmxremote`。`Instance.nodetoolResult()` 在节点隔离上下文创建 `DTestNodeTool`，临时安装 security manager 捕获 `System.exit`，运行命令后返回 `NodeToolResult`，其中包含 rc、notifications、latestError、stdout、stderr，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:984-1025`。

`DTestNodeTool` 使用 `InternalNodeProbeFactory` 与 `InternalNodeProbe`，并监听 `StorageServiceMBean` notification，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:1071-1134`。`InternalNodeProbe.connect()` 明确不走 JMX，而是把 `StorageService`、`MessagingService`、`StreamManager`、`CompactionManager`、`FailureDetector`、`CacheService`、`StorageProxy`、`HintsService`、`Gossiper`、`BatchlogManager`、`ActiveRepairService` 等实例直接绑定到 `NodeProbe` proxy 字段，见 `test/distributed/org/apache/cassandra/distributed/mock/nodetool/InternalNodeProbe.java:61-85`。

单 JVM工具测试中，`ToolRunner.invokeNodetoolJvmDtest()` 也可包装 `node.nodetoolResult(args)` 并合并 stdout/stderr，见 `test/unit/org/apache/cassandra/tools/ToolRunner.java:287-305`。

## 升级测试模型

`UpgradeableCluster` 是多版本 cluster 入口，`newInstanceWrapper()` 关闭 dtest api config check 后返回 wrapper，`create()` 支持指定版本、config updater 和 builder updater，见 `test/distributed/org/apache/cassandra/distributed/UpgradeableCluster.java:29-89`。

`UpgradeTestBase`：

- `beforeClass()` 调 `ICluster.setup()`，见 `test/distributed/org/apache/cassandra/distributed/upgrade/UpgradeTestBase.java:68-72`。
- 定义 4.0、4.1、5.0 的 supported upgrade graph，见 `test/distributed/org/apache/cassandra/distributed/upgrade/UpgradeTestBase.java:90-98`。
- `TestCase` 收集节点数、upgrade paths、setup hook、before/after node hook、before/after cluster hook、config/builder hook，见 `test/distributed/org/apache/cassandra/distributed/upgrade/UpgradeTestBase.java:142-155`、`test/distributed/org/apache/cassandra/distributed/upgrade/UpgradeTestBase.java:270-310`。
- `run()` 对每条升级路径创建初始版本 cluster，执行 setup，然后对每个目标版本顺序停节点、GC、`setVersion`、启动节点、执行 hook、最后检查 uncaught exceptions，见 `test/distributed/org/apache/cassandra/distributed/upgrade/UpgradeTestBase.java:312-368`。

`build.xml` 注释说明运行 upgrade dtest 前需要对涉及的每个版本执行 `ant dtest-jar` 并复制 `build/dtest-*.jar`，`dtest-jar` target 会把 main/test classes、test conf 和 `dtest-api-*.jar` 等依赖打进 jar，见 `build.xml:1733-1758`、`build.xml:1807-1819`。

## Fuzz 与生成式测试模型

分布式 fuzz 基类 `test/distributed/.../FuzzTestBase` 继承 `TestBaseImpl`，静态初始化 Harry 配置，`beforeClassOverride()` 启动 2 节点 cluster 并初始化 RF=2 schema，见 `test/distributed/org/apache/cassandra/distributed/fuzz/FuzzTestBase.java:37-63`。`generateTables()` 用 Harry run 和 fixed schema provider 构造 SSTable 数据，关闭 compaction，并混合生成普通分区与大分区 SSTable，见 `test/distributed/org/apache/cassandra/distributed/fuzz/FuzzTestBase.java:78-105`。

repair fuzz 基类继承 `CQLTester.InMemory`，安装模拟 executor、clock、gossip/failure detector/repair/streaming 相关依赖，用生成器覆盖 repair coordinator/session/job/validation/paxos cleanup 等状态空间，入口见 `test/unit/org/apache/cassandra/repair/FuzzTestBase.java:163-180`。

## 构建与运行入口

| 目标 | 用途 | 关键行为 | 证据 |
|---|---|---|---|
| `ant test -Dtest.name=...` | 单元测试默认入口 | 在 `test/unit` 下按 `${test.name}` 匹配 `*.java`，排除 upgrade dtest | `build.xml:1665-1671` |
| `ant testclasslist -Dtest.classlistfile=...` | 文件列表批量运行 | 从 classlist 文件读取相对 `test/unit` 的类路径 | `build.xml:1673-1682` |
| `ant test-jvm-dtest -Dtest.name=...` | in-JVM distributed test | 从 `test/distributed` 下 `**/test/${test.name}.java` 匹配，forkmode once，使用 dtest logback、ring delay、skip sync、8G heap | `build.xml:1762-1770` |
| `ant test-jvm-dtest-some -Dtest.name=FQCN [-Dtest.methods=...]` | 指定 dtest 类/方法 | 直接传入 JUnit test name/methods，适合局部调试 | `build.xml:1822-1835` |
| `ant test-jvm-upgrade-dtest` | 升级测试 | 运行 `**/upgrade/*Test.java`，要求准备各版本 dtest jar | `build.xml:1807-1819` |
| `ant test-simulator-dtest` | simulator dtest | 使用 simulator javaagent/bootclasspath 和严格 determinism check | `build.xml:1783-1804` |
| `ant dtest-jar` | 生成升级/远程 dtest jar | 合并 main/test classes、test conf、dtest-api、asm、javassist、reflections、semver4j 和依赖 jar | `build.xml:1733-1758` |

`testmacrohelper` 默认输出 XML/brief formatter、设置 `storage-config=test/conf`、`cassandra.testtag`、driver timeout、debug refcount、strict runtime checks、read defensive checks、prepared 配置、classpath 和 test lib jar，见 `build.xml:1123-1218`。每轮后清理 `build/test/cassandra` 下 commitlog/cdc/data/system_data/saved_caches 等目录，见 `build.xml:1220-1225`。

日志位置：

- 普通单测日志：`./build/test/logs/${cassandra.testtag}/TEST-${suitename}.log`，见 `test/conf/logback-test.xml:27-38`。
- dtest 每节点日志：`./build/test/logs/${cassandra.testtag}/${suitename}/${cluster_id}/${instance_id}/system.log`，见 `test/conf/logback-dtest.xml:20-32`。

## 配置项

- `build.xml` test targets 通过 Ant properties 控制测试类/方法、fork、classpath、JVM args 和输出目录，主入口见 `build.xml:1123-1218`。
- `test.name`、`test.methods`、`test.classlistfile` 分别控制按类名、按方法和按列表运行，target 见 `build.xml:1665-1682` 和 `build.xml:1822-1835`。
- `cassandra.testtag` 决定测试日志目录，logback 配置见 `test/conf/logback-test.xml:27-38` 和 `test/conf/logback-dtest.xml:20-32`。
- `storage-config=test/conf`、driver timeout、debug refcount、strict runtime checks、prepared 配置等测试 JVM 参数由 `testmacrohelper` 注入，见 `build.xml:1123-1218`。
- dtest ring delay、skip sync、heap、logback dtest 配置由 `test-jvm-dtest` target 注入，见 `build.xml:1762-1770`。

## Metrics

- 测试框架本身不注册生产 Dropwizard metrics；它主要产出 JUnit XML/brief formatter、stdout/stderr、nodetool notifications 和 logback 文件，formatter/输出配置见 `build.xml:1123-1218`。
- 被测 Cassandra runtime 的 metrics 仍可在测试中读取；dtest nodetool/JMX 路径通过 `InternalNodeProbe` 直接绑定 `StorageService`、`MessagingService`、`StreamManager`、`CompactionManager`、`CacheService` 等 MBeans，见 `test/distributed/org/apache/cassandra/distributed/mock/nodetool/InternalNodeProbe.java:61-85`。
- `NodeToolResult` 记录 rc、stdout、stderr、notifications 和 latestError，是拓扑/repair/streaming 类测试的主要结果指标，创建入口见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:984-1025`。

## 日志

- 普通单测 logback 输出到 `build/test/logs/${cassandra.testtag}/TEST-${suitename}.log`，见 `test/conf/logback-test.xml:27-38`。
- dtest 每个节点输出独立 `system.log`，路径包含 suite、cluster id 和 instance id，见 `test/conf/logback-dtest.xml:20-32`。
- `ToolRunner` 和 dtest nodetool 路径会捕获 stdout/stderr，便于断言 CLI 输出，见 `test/unit/org/apache/cassandra/tools/ToolRunner.java:287-305` 和 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:984-1025`。
- dtest close/upgrade 阶段会检查并重置 uncaught exceptions，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:1078-1112`。

## 运维关注点

- 选择 `execute()` 还是 `executeNet()` 会改变 auth、guardrail、protocol、paging 覆盖范围；权限/driver 行为必须走 native path，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1517-1585` 和 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1630-1669`。
- dtest 节点共享宿主 JVM，新增测试要注意 static state、executor、JMX、delete-on-exit hook 和 classloader 清理，启动/关闭相关代码见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:581-650` 和 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:930-961`。
- 拓扑类测试应显式等待 schema agreement、live member 收敛或 nodetool notification，避免只断言最终 stdout。
- upgrade dtest 运行前需要准备涉及版本的 dtest jar，见 `build.xml:1733-1758` 和 `build.xml:1807-1819`。

## 性能瓶颈

- `executeNet()` 会启动 native transport 和 driver session，比 internal CQL 慢，且可能受 protocol timeout 影响，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:613-707`。
- in-JVM dtest 多节点启动需要 schema/gossip/live member 收敛，`AbstractCluster.startup()` 对第一个节点和 auto-bootstrap 节点串行启动，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:1018-1050`。
- upgrade tests 会逐节点 stop/setVersion/start，并在每个 hook 后检查异常，运行成本显著高于普通 dtest，见 `test/distributed/org/apache/cassandra/distributed/upgrade/UpgradeTestBase.java:312-368`。
- Fuzz/生成式测试会生成大量 schema/data/SSTable 状态组合，适合作为长耗时覆盖而不是快速单测入口，见 `test/distributed/org/apache/cassandra/distributed/fuzz/FuzzTestBase.java:78-105`。

## 常见取舍

### Internal CQL vs native CQL

`CQLTester.execute()` 快、稳定、便于直接验证服务端逻辑，但它使用 internal client state，权限和部分 guardrail 不生效，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1630-1669`。`executeNet()` 更接近真实客户端，但需要启动 native transport 和 driver session，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1517-1585`。

### 单 JVM dtest vs 多进程真实集群

in-JVM dtest 能快速模拟多节点、故障、message drop、bootstrap、repair、streaming 和 nodetool，但节点共享一个宿主 JVM，需要 classloader/静态状态清理。`Instance` 构造时设置 cluster/instance id、broadcast address 和 override config，启动/shutdown 又显式清理 executor、JMX、crypto provider、delete-on-exit hook 等资源，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:175-217`、`test/distributed/org/apache/cassandra/distributed/impl/Instance.java:930-961`。

### Schema agreement 等待

dtest 的 `schemaChange()` 不只是执行 DDL，还通过 `SchemaChangeMonitor` 等待 schema agreement；对于停节点场景可使用 `schemaChangeIgnoringStoppedInstances()`，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:823-863`、`test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:889-940`。

### NodeTool 结果解释

`NodeToolResult` 同时包含 exit code、stdout/stderr 和 notification。对于 repair/streaming/topology 操作，notification 可能比 stdout 更能说明 progress/error；`DTestNodeTool` 会捕获 `StorageServiceMBean` notification，见 `test/distributed/org/apache/cassandra/distributed/impl/Instance.java:984-1025`、`test/distributed/org/apache/cassandra/distributed/impl/Instance.java:1071-1134`。

## 常见故障

| 现象 | 优先查看 | 原因线索 |
|---|---|---|
| 单测目录脏数据导致失败 | `ServerTestUtils.cleanup()` 与 `build/test/cassandra/*` | 单测准备阶段清理 commitlog/cdc/hints/cache/data，见 `test/unit/org/apache/cassandra/ServerTestUtils.java:143-170` |
| dtest 启动超时 | `AbstractCluster.startup()`、每节点 `system.log` | live member monitor 等待收敛，auto_bootstrap 节点串行启动，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:1018-1050` |
| dtest 隐性线程异常 | `AbstractCluster.checkAndResetUncaughtExceptions()` | cluster close 或升级阶段会汇总隔离节点线程异常并抛出 `ShutdownException`，见 `test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java:1078-1112` |
| dtest nodetool 与真实 JMX 不一致 | `InternalNodeProbe` | 该路径不走远程 JMX，直接绑定本进程 MBean/服务实例，见 `test/distributed/org/apache/cassandra/distributed/mock/nodetool/InternalNodeProbe.java:61-85` |
| CQL 权限测试误判 | `execute()` vs `executeNet()` | internal calls 绕过普通权限检查，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1630-1669` |
| 升级测试找不到旧版本 | `ant dtest-jar` 和 `build/dtest-*.jar` | upgrade target 注释要求准备每个涉及版本的 dtest jar，见 `build.xml:1807-1819` |

## 测试用例

- `test/unit/org/apache/cassandra/cql3/CQLTesterTest.java`：CQLTester 自身 helper 行为。
- `test/distributed/org/apache/cassandra/distributed/impl/AbstractClusterTest.java`：cluster builder vnode/token config 约束。
- `test/distributed/org/apache/cassandra/distributed/test/TestBaseImpl.java`：分布式测试公共 helper、bootstrap 新节点、system keyspace RF 修复。
- `test/unit/org/apache/cassandra/tools/ToolRunner.java`：工具/standalone/nodetool 测试包装。
- `test/distributed/org/apache/cassandra/distributed/upgrade/UpgradeTestBase.java`：升级测试 DSL。
- `test/distributed/org/apache/cassandra/distributed/fuzz/FuzzTestBase.java`：Harry 分布式 fuzz 基类。
- `test/unit/org/apache/cassandra/repair/FuzzTestBase.java`：repair 生成式测试基类。

## 可继续深化

- 反编译/查看 `test.lib` 中 `dtest-api-*.jar` 的 `ICluster`、`IInstance`、`DistributedTestBase`、`NodeToolResult` 源，补齐跨版本 API 的完整契约。
- 单独展开 simulator dtest：`test/simulator` 目录、simulator asm、determinism check、clock/scheduler/network 模型。
- 单独展开 Byteman/class transformer：与 in-JVM dtest classloader、shared classes、fault injection 的关系。
- 梳理每类 CI profile 与 Jenkins/Ant target 的关系。
