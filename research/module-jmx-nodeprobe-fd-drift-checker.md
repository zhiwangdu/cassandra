# Module: JMX NodeProbe And Failure Detector Drift Checker

## 范围

`research/tools/check-jmx-nodeprobe-fd-drift.py` 是 source-only drift check，用来保护 NodeProbe 常用 JMX proxy、JMXTool metric package allowlist、FailureDetectorMBean/GossiperMBean 方法和 nodetool FD/gossip 命令路径在 research 文档中的覆盖。

当前基线：

- 23 NodeProbe service MBean proxies，来自 `src/java/org/apache/cassandra/tools/NodeProbe.java` 的 `connect()`。
- 2 platform MXBean proxies：`MemoryMXBean`、`RuntimeMXBean`。
- 7 JMXTool metric packages，来自 `src/java/org/apache/cassandra/tools/JMXTool.java` 的 `METRIC_PACKAGES`。
- 14 FailureDetectorMBean methods，来自 `src/java/org/apache/cassandra/gms/FailureDetectorMBean.java`。
- 10 GossiperMBean methods，来自 `src/java/org/apache/cassandra/gms/GossiperMBean.java`。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `jmx_nodeprobe_proxy_baseline` | `NodeProbe.connect()` 创建的 service MBean proxy set 和顺序。 |
| `jmx_platform_mxbean_baseline` | `MemoryMXBean` / `RuntimeMXBean` platform proxy。 |
| `jmx_tool_metric_package_baseline` | `JMXTool` dump/diff 默认 query 的 Cassandra MBean package allowlist。 |
| `jmx_failure_detector_mbean_methods` | `FailureDetectorMBean` 的 phi、endpoint state、up/down count 和 threshold 方法。 |
| `jmx_gossiper_mbean_methods` | `GossiperMBean` 的 endpoint downtime/generation、assassinate、seeds、release versions 和 token metadata compare 方法。 |
| `jmx_fd_gossip_nodetool_routes` | `failuredetector`、`gossipinfo`、`enablegossip`、`disablegossip`、`statusgossip` 到 `NodeProbe`/JMX 的调用。 |
| `jmx_compatibility_test_surface` | `NodeProbeTest.java`、`JMXToolTest.java`、`JMXCompatibilityTest.java`、`JMXGetterCheckTest.java`、`GossipInfoTest.java` 等测试锚点。 |

## Source Contract

`NodeProbe.connect()` 当前必须建立这些 service MBean proxy：

| Proxy type | 目标 |
|---|---|
| `StorageServiceMBean` | StorageService ring、schema、snapshot、gossip/native transport 等操作面。 |
| `MessagingServiceMBean` | internode messaging、SSL reload、message pool 等操作面。 |
| `StreamManagerMBean` | streaming session/status。 |
| `CompactionManagerMBean` | compaction/validation/scrub/verify/cleanup task 操作面。 |
| `FailureDetectorMBean` | FD phi、endpoint state、up/down count。 |
| `CacheServiceMBean` | key/row/counter/chunk cache capacity/save/invalidate。 |
| `StorageProxyMBean` | coordinator request metrics、timeouts、sampling。 |
| `HintsServiceMBean` | hints pause/resume/truncate/list throttle。 |
| `GCInspectorMXBean` | GC state。 |
| `GossiperMBean` | seeds、assassinate、gossip/token metadata compare。 |
| `BatchlogManagerMBean` | batchlog replay throttle/replay。 |
| `ActiveRepairServiceMBean` | repair sessions/admin state。 |
| `AuditLogManagerMBean` | audit log runtime config。 |
| `PasswordAuthenticator.CredentialsCacheMBean` | credentials auth cache. |
| `AuthorizationProxy.JmxPermissionsCacheMBean` | JMX permission cache. |
| `NetworkPermissionsCacheMBean` | network permission cache. |
| `PermissionsCacheMBean` | data/function/role permission cache. |
| `RolesCacheMBean` | roles cache. |
| `CIDRPermissionsManagerMBean` | CIDR permissions cache. |
| `CIDRGroupsMappingManagerMBean` | CIDR group mapping cache. |
| `CIDRFilteringMetricsTableMBean` | CIDR virtual-table-backed metrics bridge. |
| `GuardrailsMBean` | guardrail runtime config. |
| `AutoRepairServiceMBean` | auto repair config/status. |

`JMXTool` package baseline:

```text
org.apache.cassandra.metrics
org.apache.cassandra.db
org.apache.cassandra.hints
org.apache.cassandra.internal
org.apache.cassandra.net
org.apache.cassandra.request
org.apache.cassandra.service
```

`FailureDetectorMBean` method baseline:

```text
dumpInterArrivalTimes
setPhiConvictThreshold
getPhiConvictThreshold
getAllEndpointStates
getAllEndpointStatesWithResolveIp
getAllEndpointStatesWithPort
getAllEndpointStatesWithPortAndResolveIp
getEndpointState
getSimpleStates
getSimpleStatesWithPort
getDownEndpointCount
getUpEndpointCount
getPhiValues
getPhiValuesWithPort
```

`GossiperMBean` method baseline:

```text
getEndpointDowntime
getCurrentGenerationNumber
unsafeAssassinateEndpoint
assassinateEndpoint
reloadSeeds
getSeeds
getReleaseVersionsWithPort
getLooseEmptyEnabled
setLooseEmptyEnabled
compareGossipAndTokenMetadata
```

## 设计目标

- 当 NodeProbe proxy set、JMXTool package allowlist 或 FD/Gossiper MBean 方法变化时，让 research 文档同步更新。
- 把 Failure Detector 观测面和 nodetool 命令路由纳入可运行 drift gate，补上 gossip/failure-detector 文档之前留下的 JMX drift 缺口。
- 保持 source-only，不启动 Cassandra、不连接 JMX、不读取历史 dump artifact。

## 解决的问题

- `NodeProbe.connect()` 是 nodetool 生产连接模型的核心。如果新增 MBean proxy 后文档未更新，operator 会误判 nodetool 能操作的管理面。
- `JMXTool` 的 package allowlist 是外部 exporter/JMX dump 的默认源码边界；package 变化会影响兼容 dump、diff 和采集范围。
- `FailureDetectorMBean` 同时保留 deprecated host-only 方法和 with-port 方法；`nodetool failuredetector` 使用 `getPhiValuesWithPort()` 或 deprecated `getPhiValues()` 取决于 `--print-port`。
- `gossipinfo --resolve-ip` 实际走 `FailureDetectorMBean` endpoint state dump，不走 `GossiperMBean`；该细节是排障 runbook 的关键边界。

## 设计取舍

- checker 固定 `NodeProbe.connect()` 内的 service proxy set，不检查后续动态 CFS/metrics/ObjectName proxy。动态 proxy 已在 `module-observability-mapping.md` 中描述为按命令查询。
- 对 `FailureDetectorMBean` 和 `GossiperMBean` 使用完整 method set；对大型 MBean 例如 `StorageServiceMBean`、`MessagingServiceMBean` 只检查 NodeProbe proxy baseline，不展开全量方法。
- JMX compatibility dump 本身仍由 `JMXCompatibilityTest` 维护；本 checker 只验证源码和 research 文档的映射同步。

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-jmx-nodeprobe-fd-drift.py` | 解析 NodeProbe proxy、JMXTool packages、FD/Gossiper MBean methods 和 docs coverage。 |
| `NodeProbe` | nodetool JMX facade，连接后缓存常用 service MBean proxy，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:136-333`。 |
| `JMXTool` | JMX dump/diff 工具，使用 `METRIC_PACKAGES` query Cassandra MBeans，见 `src/java/org/apache/cassandra/tools/JMXTool.java:84-92`。 |
| `FailureDetectorMBean` | FD JMX 接口，暴露 phi、endpoint state、up/down count 和 threshold，见 `src/java/org/apache/cassandra/gms/FailureDetectorMBean.java:26-54`。 |
| `GossiperMBean` | gossip JMX 接口，暴露 endpoint downtime/generation、assassinate、seeds、release versions 和 token metadata compare，见 `src/java/org/apache/cassandra/gms/GossiperMBean.java:24-50`。 |
| `FailureDetectorInfo` / `GossipInfo` / `EnableGossip` / `DisableGossip` / `StatusGossip` | nodetool FD/gossip command routes，见 `src/java/org/apache/cassandra/tools/nodetool/FailureDetectorInfo.java:30-45`、`GossipInfo.java:26-36`、`EnableGossip.java:25-32`、`DisableGossip.java:25-32`、`StatusGossip.java:25-35`。 |

## 核心接口

- `nodeprobe_proxy_classes()`：解析 `NodeProbe.connect()` 内 `JMX.newMBeanProxy(..., X.class)`。
- `platform_proxy_classes()`：解析 `ManagementFactory.newPlatformMXBeanProxy(..., X.class)`。
- `jmxtool_packages()`：解析 `JMXTool.METRIC_PACKAGES`。
- `interface_methods()`：解析 `FailureDetectorMBean.java` 和 `GossiperMBean.java` 的 method names。
- `doc_checks()`：确认 scenario ids、proxy/method/package names 和测试锚点进入 research 文档。

## 生命周期

```text
developer changes JMX/FD/Gossip surface
  -> run python3 research/tools/check-jmx-nodeprobe-fd-drift.py
  -> checker parses NodeProbe/JMXTool/MBean interfaces/nodetool routes
  -> checker compares source baselines and research docs
  -> update docs and baseline before merging
```

## 调用链

```text
nodetool failuredetector
  -> FailureDetectorInfo.execute()
  -> NodeProbe.getFailureDetectorPhilValues(printPort)
  -> FailureDetectorMBean.getPhiValuesWithPort() or getPhiValues()

nodetool gossipinfo [--resolve-ip]
  -> GossipInfo.execute()
  -> NodeProbe.getGossipInfo(printPort, resolveIp)
  -> FailureDetectorMBean endpoint-state dump method

nodetool enablegossip / disablegossip / statusgossip
  -> NodeProbe.startGossiping() / stopGossiping() / isGossipRunning()
  -> StorageServiceMBean

jmxtool dump
  -> JMXTool.load()
  -> queryNames(package prefix)
  -> MBeanServerConnection.getMBeanInfo()
```

## 配置项

- JMX connection properties remain in nodetool global options and JMX server setup: `--host`、`--port`、`--username`、`--password`、`--password-file` and JMX SSL/RMI properties.
- Failure Detector tuning remains `phi_convict_threshold` and `cassandra.max_local_pause_in_ms`; this checker only protects the management surface.
- `cassandra.disable_mbean_registration` and `mbean_registration_class` can remove or replace MBean visibility at runtime; source baseline still documents the default surface.

## Metrics

- `FailureDetectorMBean.getPhiValuesWithPort()` returns endpoint/Phi rows for `nodetool failuredetector`.
- JMXTool package allowlist includes `org.apache.cassandra.metrics` plus Cassandra service/db/net/request/internal/hints domains.
- This checker reports counts for service proxies, platform proxies, JMXTool packages, FD methods and Gossiper methods.

## 日志

- Drift checker logs failed source/doc checks to stdout and returns 1; parsing errors return 2.
- Runtime FD/gossip logs remain in `FailureDetector` and `StorageService`, including local pause suppression and operator start/stop gossip warnings.

## 运维关注点

- A green checker does not prove every JMX getter is callable; `JMXGetterCheckTest` remains the runtime evidence for readable getters.
- `JMXCompatibilityTest` remains the release/upgrade evidence for historical dump compatibility.
- `NodeProbe.connect()` proxy set is a nodetool convenience surface, not the full MBean universe. Dynamic CFS/metric ObjectName queries still require JMXTool or direct JMX inspection.
- `GossiperMBean.unsafeAssassinateEndpoint()` is intentionally tracked because external JMX clients may see it even if nodetool uses the safer `assassinateEndpoint()`.

## 性能瓶颈

- Checker cost is text IO and regex parsing.
- Runtime `jmxtool dump` can be expensive because it queries every MBeanInfo under the package allowlist.
- Runtime `gossipinfo` endpoint state dump can be large on big clusters; `--resolve-ip` adds name resolution behavior.

## 常见故障

- `NodeProbe.connect service proxy classes match baseline` fails: a service proxy was added, removed or reordered; update the source contract and docs.
- `JMXTool metric package allowlist matches baseline` fails: dump/diff scope changed; update exporter/JMX notes.
- `FailureDetectorMBean methods match baseline` fails: FD JMX compatibility changed; update gossip/FD runbook.
- `source token contract ... GossipInfo.java` fails: nodetool route changed; verify whether `gossipinfo` still reads FD endpoint state dump.
- `doc token ...` fails: add the missing proxy, package, method or test anchor to research docs.

## 测试用例

- `python3 research/tools/check-jmx-nodeprobe-fd-drift.py`：source-only drift check。
- `python3 research/tools/check-jmx-nodeprobe-fd-drift.py --json`：输出 proxy/package/method baseline 和失败项。
- `NodeProbeTest.java` 覆盖真实 JMX NodeProbe 连接后读取/设置 compaction concurrency 的远端值，见 `test/unit/org/apache/cassandra/tools/NodeProbeTest.java:33-73`。
- `JMXToolTest.java` 覆盖 dump/diff JSON/YAML serde 和 CLI help，见 `test/unit/org/apache/cassandra/tools/JMXToolTest.java:40-151`。
- `JMXCompatibilityTest.java` 生成当前 dump 并和历史 dump 做 diff，见 `test/unit/org/apache/cassandra/tools/JMXCompatibilityTest.java:99-140`。
- `JMXGetterCheckTest.java` 遍历 Cassandra MBeans 并读取可读 attributes，见 `test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java:63-94`。
- `GossipInfoTest.java` 覆盖 `gossipinfo` help、`--print-port` 和 `--resolve-ip` 输出，见 `test/unit/org/apache/cassandra/tools/nodetool/GossipInfoTest.java:54-147`。
