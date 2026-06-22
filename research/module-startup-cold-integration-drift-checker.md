# Module: Startup Cold Integration Drift Checker

## 范围

`research/tools/check-startup-cold-integration-drift.py` 是 `research/module-startup-cold-start-integration-matrix.md` 的 source/test/gap drift checker。它保护 Startup 第三轮研究中关于 JMX early availability、daemon registration order、`completeSetup()` marker、native transport/RPC_READY gate、bootstrap binary gate、auth setup readiness、operator binary JMX path 和 startup-vs-runtime failure policy boundary 的判断。

当前基线：

- `CassandraDaemon.setup()` 在 startup checks 后、`StorageService.initServer()` 前注册 daemon；`completeSetup()` 在 native transport service 构造、auth cache warmup 和 Paxos auto repairs 之后。
- `StorageService.initServer()` 会注册 `StorageService` MBean，distributed bootstrap regression test 验证 bootstrap 中可通过 JMX 读取 JOINING。
- Native transport start 必须通过 peer warmup、bootstrap/write-survey validation 和 `nativeTransportService` non-null check；首次 start 发布 `RPC_READY=true`。
- Disk/commitlog failure policy 以 `isDaemonSetupCompleted()` 为分界；startup 未完成时更偏向 quiet kill。
- 完整 cold-start log marker 顺序 E2E 仍是 gap still open。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `startup_cold_jmx_early_bootstrap` | JMX setup/MBean publish before bootstrap completes and distributed JMX bootstrap test. |
| `startup_cold_daemon_registration_order` | Daemon registration before `initServer()` and native transport JMX delegate checks. |
| `startup_cold_complete_setup_marker` | `completeSetup()` placement and `setupCompleted` marker semantics. |
| `startup_cold_native_rpc_ready_gate` | Peer warmup, transport validation, native start, and `RPC_READY` publish. |
| `startup_cold_bootstrap_binary_gate` | Bootstrap/write-survey gate and resume/join CQL listener coverage. |
| `startup_cold_auth_setup_ready` | `doAuthSetup(false)` before complete setup and distributed auth setup assertion. |
| `startup_cold_jmx_binary_operator_path` | nodetool enable/disable binary path and connectivity test. |
| `startup_cold_failure_policy_boundary` | disk/commitlog startup vs runtime failure behavior keyed to `isDaemonSetupCompleted()`. |
| `startup_cold_log_marker_gap` | Current absence of full ordered cold-start log marker E2E. |
| `startup_cold_existing_tests_baseline` | Current source/test anchors remain present. |

## 设计目标

- Fail when cold-start integration order changes without updating research.
- Fail when the documented full log marker E2E gap becomes covered so the matrix stops calling it missing.
- Complement `check-startup-daemon-drift.py`: that checker protects component contracts; this checker protects cross-component timing and readiness semantics.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-startup-cold-integration-drift.py` | Source/test/gap drift checker. |
| `CassandraDaemon` | setup order, JMX, daemon setup marker, native transport lifecycle. |
| `StorageService` | daemon delegate, MBean publish, initServer, RPC_READY, auth setup observed state. |
| `DefaultFSErrorHandler` / `JVMStabilityInspector` | startup-vs-runtime disk/commitlog failure boundaries. |
| `BootstrapTest` / `BootstrapBinaryDisabledTest` / `AuthTest` / `NodeToolEnableDisableBinaryTest` / failure policy tests | Current integration test anchors. |

## 运维关注点

- A green checker means current source/test/gap statements still match this checkout; it does not prove the full ordered cold-start log marker E2E exists.
- If startup order changes around `completeSetup()`, re-evaluate failure policy semantics before only updating line anchors.
- If new cold-start E2E logging coverage lands, replace `startup_cold_log_marker_gap` with concrete covered scenario IDs.

## 常见故障

- `source token contract ... CassandraDaemon.java` fails: setup/start ordering, JMX, completeSetup or native transport gate changed.
- `source token contract ... StorageService.java` fails: daemon delegate, MBean publish, initServer, RPC_READY or auth setup surface changed.
- `test token contract ...` fails: distributed/unit coverage anchor moved or was removed.
- `gap still open ...` fails: a likely full ordered cold-start marker test landed and the gap is stale.
- `doc token ...` fails: scenario IDs, source paths, test anchors or explicit gap language disappeared.

## 运行方式

- `python3 research/tools/check-startup-cold-integration-drift.py`
- `python3 research/tools/check-startup-cold-integration-drift.py --json`
- Related validation: `python3 -m py_compile research/tools/check-startup-cold-integration-drift.py`
