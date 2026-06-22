# Module: JMX Compatibility Dump Matrix

## 范围

本模块补齐 JMX 行之前留下的外部兼容 dump 缺口，聚焦 `tools/bin/jmxtool`、历史 gold dump、`JMXCompatibilityTest`、`JMXStandardsTest`、distributed JMX getter/feature tests 和 JMX server wiring。它不重复 `module-jmx-nodeprobe-fd-drift-checker.md` 已覆盖的 NodeProbe proxy set、FD/Gossiper MBean 方法清单。

当前源码基线：

- 4 个历史 JMX gold dump：`test/data/jmxdump/cassandra-3.0-jmx.yaml`、`cassandra-3.11-jmx.yaml`、`cassandra-4.0-jmx.yaml`、`cassandra-4.1-jmx.yaml`。
- dump 对象数分别为 3855、4493、7426、7426；attribute rows 分别为 18062、21006、42633、42633；operation rows 分别为 5624、6642、11106、11106。
- `JMXCompatibilityTest` 生成当前 dump 后，使用 `jmxtool diff -f yaml --ignore-missing-on-left` 对比历史 dump，允许新对象/属性/操作出现在右侧，但不允许历史兼容面无说明地消失或改变。
- `JMXGetterCheckTest` 在真实 in-JVM dtest JMX connector 上遍历 `org.apache.cassandra` MBeans，读取 readable attributes，并调用零参数 operations，排除明确危险或已知不稳定项。

## 场景矩阵

| 场景 ID | 源码锚点 | 现有测试 | 运维/兼容含义 |
|---|---|---|---|
| `jmx_compat_dump_gold_files` | `test/data/jmxdump/*.yaml` 保存 3.0、3.11、4.0、4.1 的 gold dump；每个 YAML key 是 ObjectName，value 包含 `attributes` / `operations`。 | `JMXCompatibilityTest.diff30()`、`diff311()`、`diff40()`、`diff41()` 分别引用这些文件，见 `test/unit/org/apache/cassandra/tools/JMXCompatibilityTest.java:105`、`:144`、`:185`、`:202`。 | 外部 JMX scraper、dashboard 和脚本的兼容面由历史 dump 证明；新增 dump 版本时必须同步文档和 checker 基线。 |
| `jmx_compat_diff_direction` | `JMXCompatibilityTest.diff(...)` 构造 `tools/bin/jmxtool diff -f yaml --ignore-missing-on-left <old> <current>`，见 `JMXCompatibilityTest.java:218-240`。 | 测试断言 `result.getStdout()` 为空，见 `JMXCompatibilityTest.java:241`。 | `--ignore-missing-on-left` 表示允许当前版本新增 MBean surface；缺失旧 surface、类型/签名变化或未排除的 operation/attribute drift 会失败。 |
| `jmx_compat_exclusion_contract` | `diff30`/`diff311`/`diff40`/`diff41` 维护 `excludeObjects`、`excludeAttributes`、`excludeOperations`，并按 `BtiFormat.isSelected()` 加 BTI 专属排除，见 `JMXCompatibilityTest.java:107-215`。 | 测试只允许明确列出的历史破坏：Thrift RPC、old repair API、old scrub signature、removed BufferPool metrics、read repair stage、hinted handoff manager、schema legacy tables、BTI index-summary 差异等。 | 排除项是兼容性 debt 清单；新增排除必须有 release/issue 语义，不能把真实回归简单加白。 |
| `jmx_compat_dump_generation_workload` | `setupStandardTables()` 启动 JMX、注册 `GCInspector`/native access、创建测试表、通过 native protocol insert/select 触发 storage proxy 和 table metrics，再运行 `tools/bin/jmxtool dump -f yaml --url ...`，见 `JMXCompatibilityTest.java:84-101`。 | `CQLTester.startJMXServer()` 复用 loopback JMX server，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:373-381`。 | gold dump 不是空节点快照；它有意触发表级 MBean、client request metrics、StorageProxy 等面向生产的常用对象。 |
| `jmx_tool_dump_model` | `JMXTool.load()` 只遍历 `METRIC_PACKAGES` 中的 7 个 Cassandra package，并对每个 ObjectName 读取 `MBeanInfo`，见 `src/java/org/apache/cassandra/tools/JMXTool.java:86-92`、`:427-442`。 | `JMXToolTest.jsonSerde()` / `yamlSerde()` 覆盖 `Info` serde；`cliHelpDump()` 固定 dump CLI 文案，见 `test/unit/org/apache/cassandra/tools/JMXToolTest.java:35-151`。 | dump 是 metadata 合同，不采集 metric value；scope 是 package allowlist，不是 JVM 全 MBean universe。 |
| `jmx_tool_diff_semantics` | `JMXTool.Diff` 对 object names、`Attribute(name,type)`、`Operation(name,parameters,returnType)` 做 set diff，支持 `--exclude-object`、`--exclude-attribute`、`--exclude-operation` 和左右缺失 ignore，见 `JMXTool.java:184-326`。 | `JMXToolTest.cliHelpDiff()` 固定 CLI options；serde fuzz 保证 YAML/JSON load 后等价，见 `JMXToolTest.java:55-119`、`:153-210`。 | Attribute access 不参与 equality，name/type 才是兼容核心；operation diff 会打印 similar signature，方便定位签名改动。 |
| `jmx_standards_mbean_type_gate` | `JMXStandardsTest.interfaces()` 扫描 `.*MBean$` 接口，要求 MBean 是 interface，并校验 return/parameter/throws 类型属于 allowlist；`@BreaksJMX` 只能降级为 warning，见 `test/unit/org/apache/cassandra/tools/JMXStandardsTest.java:74-176`。 | `BreaksJMX` annotation 定义在 `src/java/org/apache/cassandra/utils/BreaksJMX.java:31`。 | 这保护外部 JMX client classpath 兼容性，避免 MBean 暴露 Cassandra 内部类型导致远端反序列化或 ClassNotFound。 |
| `jmx_getter_runtime_surface` | `JMXGetterCheckTest.testAllValidGetters()` 连接每个 instance 的 JMX，遍历 `org.apache.cassandra` ObjectNames，读取 readable attributes，调用零参 operations，并排除危险操作，见 `test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java:36-94`。 | `JMXFeatureTest` 复用 `testAllValidGetters(cluster)`，见 `test/distributed/org/apache/cassandra/distributed/test/jmx/JMXFeatureTest.java:66`、`:114`。 | compatibility dump 只证明 metadata；getter check 证明运行时 getter/零参 operation 不抛异常，是排查 nodetool/JMX exporter 失败的关键证据。 |
| `jmx_distributed_isolated_server` | `IsolatedJmx.startJmx()` 给每个 in-JVM instance 安装 `InstanceMBeanWrapper`、独立 RMI socket factory、registry 和 `jmx.remote.x.daemon`；`stopJmx()` 只清理由本 instance 创建的 RMI endpoints，见 `test/distributed/org/apache/cassandra/distributed/impl/IsolatedJmx.java:78-177`。 | `JMXFeatureTest.testMultipleNetworkInterfacesProvisioning()`、`testOneNetworkInterfaceProvisioning()` 和 `testShutDownAndRestartInstances()` 验证多 JMX server、默认 domain、stop/start cleanup，见 `JMXFeatureTest.java:37-116`。 | distributed tests 能覆盖多节点 JMX 连接和 cleanup；这比单 JVM platform MBeanServer 更接近 nodetool/status 真实行为。 |
| `jmx_compatibility_ci_gap` | 当前 research checker 是 source-only，只验证源码、dump 文件和文档同步；真正兼容性仍由 Java tests 运行 `jmxtool dump/diff` 证明。 | 需要执行 `JMXCompatibilityTest`、`JMXStandardsTest`、`JMXToolTest`、`JMXGetterCheckTest`、`JMXFeatureTest` 才能关闭运行时证据。 | 如果 CI 没跑这些测试，source-only drift 只能防文档过期，不能证明当前 JMX server 可连接或 getter 全部可读。 |

## 设计目标

- 把 JMX 外部兼容证据从“有测试”细化成 gold dump 文件、diff 方向、排除项、dump 生成 workload、工具 diff semantics 和 runtime getter 证据。
- 让新增 JMX gold dump、删除历史 dump、修改 `jmxtool diff` 方向、扩大排除项或改变 MBean standards gate 时触发 research drift。
- 把 JMX 与 Metrics/Nodetool 的边界说清：JMX compatibility 保护 ObjectName/attribute/operation metadata，metrics value 语义和 NodeProbe proxy 清单分别由其他矩阵覆盖。

## 解决的问题

- 外部运维脚本通常绑定 ObjectName、attribute type 和 operation signature。源码重构如果只通过单元测试但破坏历史 MBean surface，会影响升级。
- `JMXCompatibilityTest` 的 `--ignore-missing-on-left` 容易被误读；该方向允许新增当前 surface，却会阻止旧 surface 消失。
- `JMXGetterCheckTest` 与 compatibility dump 保护不同层次：一个证明运行时 getter 可读，一个证明历史 metadata 兼容。
- `JMXStandardsTest` 的 allowlist 是远端 client classpath 的安全边界；MBean 暴露内部类型会造成非 Cassandra client 无法解析。

## 设计取舍

- drift checker 不完整解析 YAML schema，只保护 dump 文件集、对象/attribute/operation row 数和关键 ObjectName token；真正 diff 仍由 `JMXCompatibilityTest` 执行。
- 文档把 exclude list 当兼容 debt，而不是自动生成全量表。checker 保护关键 tokens，避免排除项被静默删除或扩大。
- 不把 JVM/platform MBeans 纳入 gold dump 分析；`JMXTool.METRIC_PACKAGES` 本身限定 Cassandra package。
- Attribute equality 不考虑 access，是 `JMXTool.Attribute.equals()` 的现状；文档记录这个取舍，避免误把 read/write access 当 compatibility gate。

## 核心类

| 类/文件 | 作用 |
|---|---|
| `JMXCompatibilityTest` | 启动 JMX、生成当前 dump、用历史 gold dump 做兼容 diff，见 `test/unit/org/apache/cassandra/tools/JMXCompatibilityTest.java:68-241`。 |
| `JMXTool` | `dump`/`diff` CLI、MBean metadata model、YAML/JSON load/dump 和 diff 算法，见 `src/java/org/apache/cassandra/tools/JMXTool.java:73-816`。 |
| `JMXTool.Info` / `Attribute` / `Operation` / `Parameter` | dump 的结构化 metadata；attribute 按 name/type 比较，operation 按 name/parameters/returnType 比较，见 `JMXTool.java:506-816`。 |
| `JMXStandardsTest` | MBean interface/type compatibility gate，见 `test/unit/org/apache/cassandra/tools/JMXStandardsTest.java:74-176`。 |
| `JMXGetterCheckTest` | distributed runtime getter/zero-arg operation smoke，见 `test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java:36-124`。 |
| `JMXFeatureTest` | 多 instance JMX server、default domain、stop/start cleanup，见 `test/distributed/org/apache/cassandra/distributed/test/jmx/JMXFeatureTest.java:37-146`。 |
| `IsolatedJmx` | in-JVM dtest JMX server isolation/cleanup，见 `test/distributed/org/apache/cassandra/distributed/impl/IsolatedJmx.java:78-177`。 |
| `JMXServerUtils` | daemon/test JMX server 创建、socket/auth/authz/env 设置，见 `src/java/org/apache/cassandra/utils/JMXServerUtils.java:82-160`。 |

## 核心接口

- `tools/bin/jmxtool dump -f yaml --url <service:jmx:rmi:///...>`：生成当前 metadata dump。
- `tools/bin/jmxtool diff -f yaml --ignore-missing-on-left --exclude-* <old> <current>`：验证旧 surface 没有无说明消失或改变。
- `MBeanServerConnection.queryNames(...)` / `getMBeanInfo(...)`：`JMXTool` dump 的元数据入口。
- `MBeanServerConnection.getAttribute(...)` / `invoke(..., new Object[0], new String[0])`：`JMXGetterCheckTest` 的运行时可调用性入口。

## 核心数据结构

| 数据结构 | 字段 | 语义 |
|---|---|---|
| Gold dump YAML | ObjectName -> `attributes` / `operations` | 历史版本 JMX metadata baseline。 |
| `JMXTool.Info` | `Attribute[] attributes`、`Operation[] operations` | 单个 MBean 的 metadata。 |
| `JMXTool.Attribute` | `name`、`type`、`access` | equality 只比较 `name` 和 `type`，`access` 用于输出。 |
| `JMXTool.Operation` | `name`、`Parameter[] parameters`、`returnType` | operation compatibility key。 |
| `JMXCompatibilityTest` exclude lists | object regex、attribute regex、operation regex | 已知历史破坏/格式切换/BTI 差异的白名单。 |
| `JMXGetterCheckTest` ignore sets | attribute FQN、operation FQN | 运行时 getter check 中危险或已知不稳定项。 |

## 生命周期

```text
developer changes MBean interface / metric ObjectName / JMXTool / dump coverage
  -> run python3 research/tools/check-jmx-compatibility-drift.py
  -> checker validates source tokens, dump files, dump row counts and docs
  -> if source-only drift passes, run Java JMX tests for runtime evidence
  -> update matrix, gold dumps or exclude contract with explicit compatibility reason
```

## 调用链

```text
JMXCompatibilityTest.setupStandardTables()
  -> CQLTester.startJMXServer()
  -> GCInspector.register()
  -> CassandraDaemon.registerNativeAccess()
  -> createTable / executeNet INSERT / SELECT
  -> tools/bin/jmxtool dump -f yaml --url service:jmx:rmi:///...
  -> tools/bin/jmxtool diff -f yaml --ignore-missing-on-left old.yaml current.yaml
     -> JMXTool.Diff.load()
     -> compare ObjectName set
     -> compare Attribute(name,type) set
     -> compare Operation(name,parameters,returnType) set
```

```text
JMXFeatureTest
  -> Cluster.build(...).with(Feature.JMX)
  -> IsolatedJmx.startJmx()
  -> JMXUtil.getJmxConnector(config)
  -> MBeanServerConnection.getDefaultDomain()
  -> JMXGetterCheckTest.testAllValidGetters(cluster)
```

## 配置项

- `CASSANDRA_JMX_LOCAL_PORT` / `CASSANDRA_JMX_REMOTE_PORT` 决定 daemon JMX 启动口，`CassandraDaemon.maybeInitJmx()` 读取，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:165-178`。
- JMX auth/SSL/RMI properties 由 `JMXServerUtils.configureJmxAuthentication()`、`configureJmxSocketFactories()`、`configureJmxAuthorization()` 处理，见 `JMXServerUtils.java:82-160`。
- `ORG_APACHE_CASSANDRA_DISABLE_MBEAN_REGISTRATION` 在 `IsolatedJmx.startJmx()` 中显式设为 false，确保 distributed tests 能注册 MBeans，见 `IsolatedJmx.java:78-90`。
- `BtiFormat.isSelected()` 会影响 index summary/RowIndexEntry 相关排除项，见 `JMXCompatibilityTest.java:135-212`。

## Metrics

- `JMXTool` 的 package allowlist 包含 `org.apache.cassandra.metrics`，因此 metrics MBean ObjectName/type 变化会进入 compatibility diff。
- 该矩阵关注 metadata，具体 metric 注册、单位、ObjectName 工厂和 virtual table 投影仍由 `module-metrics-registry-export-matrix.md` 维护。
- dump row count 是 drift checker 的观测值，不代表生产 metric cardinality；生产 cardinality 受表数、索引数、DC/host 数和 workload 影响。

## 日志

- `JMXCompatibilityTest` 失败时 `jmxtool diff` stdout 会列出 missing object、attribute 或 operation。
- `JMXGetterCheckTest` 收集 `JMRuntimeException` 并把失败 endpoint/attribute/operation 放入 suppressed errors，减少反射/JMX 栈噪音。
- `JMXServerUtils.logJmxServiceUrl(...)` 在 JMX server 启动后记录连接 URL，daemon/test 路径都会调用。

## 运维关注点

- 删除或改名 MBean attribute/operation 必须按兼容策略处理；有历史 dump 证明的 surface 不能只靠源码重构理由移除。
- `jmxtool dump` 不读取 metric 值，因此不会发现 getter 抛异常；外部 exporter 失败时要同时看 `JMXGetterCheckTest` 类型证据。
- 新增 MBean package 若不在 `METRIC_PACKAGES` 中，JMXTool compatibility dump 不会覆盖。
- 修改 exclude list 等价于修改升级兼容承诺，必须在 release note/issue/文档中解释。

## 性能瓶颈

- `jmxtool dump` 枚举 package 下所有 ObjectName 并读取 `MBeanInfo`，在高表数集群上输出和 diff 成本会随 MBean cardinality 增长。
- `JMXGetterCheckTest` 读取每个 readable attribute，部分 getter 可能触发聚合、DNS、表/streaming/compaction 状态遍历。
- distributed isolated JMX server 依赖 RMI endpoint cleanup；stop/start 测试覆盖该风险，但真实 CI 中端口冲突和 RMI keepalive 仍是常见 flake 来源。

## 常见故障

- gold dump file set drift：新增或删除历史 dump 后没有同步 compatibility matrix/checker。
- object/attribute/operation row count drift：历史 dump 被重生成或修改，需要确认是否 intentional。
- `--ignore-missing-on-left` 消失或方向反了：测试会从“保护旧 surface”变成不同语义。
- exclude token drift：兼容债务被修改，需要复核是否掩盖回归。
- `JMXStandardsTest` 失败：MBean 暴露了非 allowlist 类型，远端 client 可能无法加载。
- `JMXGetterCheckTest` 失败：metadata 仍在，但 getter/零参 operation 运行时抛异常。

## 测试用例

- `python3 research/tools/check-jmx-compatibility-drift.py`：source-only JMX compatibility dump drift check。
- `python3 research/tools/check-jmx-compatibility-drift.py --json`：输出 dump counts、source metadata 和失败项。
- `JMXCompatibilityTest`：历史 gold dump diff，见 `test/unit/org/apache/cassandra/tools/JMXCompatibilityTest.java:105-241`。
- `JMXToolTest`：dump/diff help 和 YAML/JSON serde，见 `test/unit/org/apache/cassandra/tools/JMXToolTest.java:35-210`。
- `JMXStandardsTest`：MBean interface/type allowlist，见 `test/unit/org/apache/cassandra/tools/JMXStandardsTest.java:74-176`。
- `JMXGetterCheckTest`：distributed runtime getter/zero-arg operation check，见 `test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java:36-124`。
- `JMXFeatureTest`：multi-instance JMX provisioning、default domain 和 restart cleanup，见 `test/distributed/org/apache/cassandra/distributed/test/jmx/JMXFeatureTest.java:37-146`。
