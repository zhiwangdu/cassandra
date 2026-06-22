# Module: Startup Daemon Drift Checker

## 范围

`research/tools/check-startup-daemon-drift.py` 是 `research/module-startup-daemon-deep-dive.md` 的 source/test/doc drift checker。它保护 Startup 第二轮研究中关于 `CassandraDaemon` lifecycle order、`DatabaseDescriptor` 初始化模式、default startup checks、startup check options、filesystem ownership、data resurrection、native transport gating、TLS dual-port policy、block-for-peers 和测试锚点的判断。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `startup_daemon_lifecycle_order` | `activate()` / `setup()` / `start()` source ordering and late `completeSetup()`. |
| `startup_config_initialization_modes` | daemon/tool/client initialization conflict and apply scope. |
| `startup_checks_default_preflight` | Default startup check list and `verify()` execute/postAction sequence. |
| `startup_check_options_gate` | `StartupChecksOptions` defaults, disabled-by-default checks and non-configurable check behavior. |
| `startup_filesystem_ownership_gate` | Ownership marker file source and yaml/system-property test anchors. |
| `startup_data_resurrection_gate` | Heartbeat/gc_grace source and distributed coverage. |
| `startup_native_transport_gate` | Transport startup validation, config flag and nodetool enable/disable coverage. |
| `startup_native_transport_tls_dual_port` | TLS policy and dual-port validation in source and tests. |
| `startup_block_for_peers_gate` | Peer warmup checker source and local/global/no-op/zero-wait tests. |
| `startup_existing_tests_baseline` | Existing startup component test anchors remain present. |

## 设计目标

- Fail when startup daemon ordering, startup-check defaults, config initialization semantics, native transport gates or peer warmup contracts move without updating research.
- Fail when source docs lose required paths/classes/config/test anchors.
- Keep daemon startup research separate from bootstrap/ring streaming research while linking the two at `StorageService.initServer()` and binary transport bootstrap gating.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-startup-daemon-drift.py` | Source/test/doc drift checker. |
| `CassandraDaemon` | Daemon order, checks, setup completion and transport validation. |
| `DatabaseDescriptor` / `Config` / `StartupChecksOptions` | Config initialization modes, startup check config and native/block-for-peers settings. |
| `StartupChecks` / `FileSystemOwnershipCheck` / `DataResurrectionCheck` | Pre-flight startup checks and configurable gates. |
| `NativeTransportService` / `StartupClusterConnectivityChecker` | CQL server lifecycle and peer connectivity warmup before opening transport. |

## 运维关注点

- A green checker only means the documented source/test baseline is in sync; it does not prove the optional cold-start integration gap is implemented.
- If `StartupChecks.DEFAULT_TESTS` changes, update the default-check table and checker token list together.
- If new full daemon startup integration coverage lands, replace the current `待继续` note with concrete test anchors.

## 常见故障

- `source token contract ... CassandraDaemon.java` fails: daemon setup/start order or transport gate changed.
- `source token contract ... StartupChecks.java` fails: default pre-flight list or check semantics changed.
- `test token contract ...` fails: test anchor was renamed, moved, or no longer covers the documented behavior.
- `doc token ...` fails: scenario IDs, source paths, config names or test anchors disappeared from the research docs.

## 运行方式

- `python3 research/tools/check-startup-daemon-drift.py`
- `python3 research/tools/check-startup-daemon-drift.py --json`
- Related validation: `python3 -m py_compile research/tools/check-startup-daemon-drift.py`
