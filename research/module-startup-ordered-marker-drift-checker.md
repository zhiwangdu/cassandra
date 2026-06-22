# Module: Startup Ordered Marker Drift Checker

## 范围

`research/tools/check-startup-ordered-marker-drift.py` 是 source-only drift check，用来保护 `research/module-startup-ordered-log-marker-matrix.md` 中的 startup ordered marker/source/test/gap baseline。

当前基线：

- `CassandraDaemon.setup()` 先 JMX、startup checks、schema/storage/commitlog replay，再注册 daemon 和进入 `StorageService.initServer()`。
- `StorageService.initServer()` 在 `prepareToJoin()` 前注册 `StorageServiceMBean`，bootstrap regression test 验证 JMX during bootstrap。
- `StorageService.doAuthSetup(false)` 位于 daemon setup 中，早于 `initializeClientTransports()` 和 `start()`。
- `NativeTransportService.start()`/`PipelineConfigurator.initializeChannel()` 负责 CQL listener marker；`CassandraDaemon.startNativeTransport()` 在 service start 后发布 `RPC_READY=true`。
- `CassandraDaemon.activate()` 在 `setup()` 和 `start()` 返回后记录 `Startup complete`。
- 当前没有完整 ordered cold-start log marker E2E；checker 以 negative scan 保护这个 gap。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `startup_marker_jmx_before_checks` | `maybeInitJmx()` before `runStartupChecks()` and JMX startup check source. |
| `startup_marker_preflight_before_system_writes` | startup checks before local metadata writes. |
| `startup_marker_schema_storage_before_mbean` | schema/storage/replay before daemon registration and `initServer()`. |
| `startup_marker_mbean_during_bootstrap` | `registerMBeans()` before bootstrap and distributed JMX test. |
| `startup_marker_auth_before_transport` | auth setup before client transport construction/start. |
| `startup_marker_complete_setup_before_start` | auth cache warm, Paxos auto repairs and `completeSetup()` before `start()`. |
| `startup_marker_transport_gate_before_listen` | peer warmup and bootstrap/write-survey validation before transport listen. |
| `startup_marker_listen_before_rpc_ready` | CQL listener marker and `RPC_READY=true` publish relation. |
| `startup_marker_startup_complete_after_start` | `Startup complete` after `start()`. |
| `startup_marker_stop_deactivate_inverse` | native stop marker and `RPC_READY=false` path. |
| `startup_marker_injvm_dtest_order_divergence` | dtest startup order differences and duplicated `completeSetup()` calls. |
| `startup_marker_ordered_e2e_gap` | absence of single ordered marker E2E. |

## 设计目标

- Fail when marker order source anchors move without research updates.
- Fail when existing distributed/unit tests no longer cover the dispersed baseline.
- Fail when a future test likely closes the ordered E2E gap, so docs stop calling it missing.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-startup-ordered-marker-drift.py` | Source/test/doc/gap drift checker。 |
| `CassandraDaemon` | setup/start/activate order and `Startup complete` marker。 |
| `StartupChecks` | preflight execute/postAction and JMX/data/SSTable checks。 |
| `StorageService` | MBean publish, auth setup, initServer and RPC_READY。 |
| `NativeTransportService` / `PipelineConfigurator` / `Server` | native listen/stop marker source。 |
| `Instance` | in-JVM distributed startup harness order。 |

## 运维关注点

- Green checker 不代表 ordered marker E2E 已存在，只表示当前 gap 描述仍与 tests 匹配。
- If `Startup complete` semantics change, review bootstrap/write-survey path before updating only source tokens.
- If production daemon gains explicit JMX setup/startup checks/auth setup markers, add them to the marker matrix and future E2E test shape.

## 常见故障

- `source token contract ... CassandraDaemon.java` fails：setup/start/activate order changed.
- `source token contract ... PipelineConfigurator.java` fails：CQL listen marker moved.
- `test token contract ...` fails：existing distributed/unit coverage changed or was renamed.
- `gap still open ...` fails：a likely complete ordered marker test landed and docs must be updated.

## 运行方式

- `python3 research/tools/check-startup-ordered-marker-drift.py`
- `python3 research/tools/check-startup-ordered-marker-drift.py --json`
- Related validation: `python3 -m py_compile research/tools/check-startup-ordered-marker-drift.py`
