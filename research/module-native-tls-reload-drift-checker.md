# Module: Native TLS Reload Drift Checker

## 范围

`research/tools/check-native-tls-reload-drift.py` 是 source-only drift check，用来保护 native TLS reload coverage matrix 的 research 覆盖。它检查 `SSLFactory` cache/reload contract、JKS/PEM file-watch hooks、native pipeline `SslContext` attach points、startup/dual-port/mTLS/JMX gates，以及当前测试覆盖边界。

当前基线：

- `SSLFactory` caches Netty `SslContext` in a `ConcurrentHashMap<CacheKey, SslContext>`.
- Periodic reload defaults are 600 seconds initial delay and 600 seconds period.
- File-based JKS and file-backed PEM material participate in hot reload.
- Native server and `SimpleClient` obtain `SslContext` during channel initialization.
- Existing tests cover factory reload and native TLS negotiation separately.
- `native_tls_reload_e2e_gap` remains true until a real native cert rotation connection test is added.

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `native_tls_reload_context_cache_contract` | SSL context cache, validation-before-clear and cache-key semantics. |
| `native_tls_reload_file_watch_contract` | JKS keystore/outbound/truststore hot reload file list. |
| `native_tls_reload_pem_file_contract` | PEM file-backed reload and inline material boundary. |
| `native_tls_reload_startup_validation_contract` | startup SSL validation and scheduler init. |
| `native_tls_reload_native_pipeline_contract` | native server/client channel initialization uses cached contexts. |
| `native_tls_reload_dual_port_policy` | `native_transport_port_ssl` and TLS policy gates. |
| `native_tls_reload_mtls_gate` | mTLS authenticator TLS/client-auth config dependency. |
| `native_tls_reload_jmx_force_gate` | JMX force reload calls `SSLFactory.forceCheckCertFiles()`. |
| `native_tls_reload_test_coverage_matrix` | existing unit/distributed TLS tests. |
| `native_tls_reload_e2e_gap` | missing real native connection cert rotation test. |

## 设计目标

- Keep source-level reload semantics synchronized with the research matrix.
- Fail if native TLS pipeline behavior, reload cache behavior, file-watch hooks or test coverage assumptions drift.
- Make the missing end-to-end test visible until it exists.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-native-tls-reload-drift.py` | Source/doc drift checker. |
| `SSLFactory` | Cache, validation, reload and force reload. |
| `FileBasedSslContextFactory` | JKS file watcher and manager factory builders. |
| `PEMBasedSslContextFactory` | PEM file/inline material and file-backed reload. |
| `PipelineConfigurator` | Native server TLS/optional TLS attach point. |
| `NativeTransportService` | Single/dual native server policy. |
| `SimpleClient` | Secure native client channel setup. |
| `DatabaseDescriptor` / `EncryptionOptions` | Config apply, validation and cache-key fields. |
| `MutualTlsAuthenticator` | mTLS native TLS dependency. |

## 运维关注点

- A green checker does not prove live certificate rotation works on a real native channel; it proves the source-level matrix is current.
- When a real native reload test lands, update this checker so `native_tls_reload_e2e_gap` no longer expects the gap.
- If reload counters or metrics are added, add them to the matrix and checker.

## 常见故障

- `source token contract ... SSLFactory.java` fails: reload/cache behavior changed.
- `native TLS reload E2E gap remains explicit` fails: tests likely changed and the matrix should be updated.
- `doc scenario ...` fails: source or docs changed without updating the research coverage matrix.

## 测试用例

- `python3 research/tools/check-native-tls-reload-drift.py`。
- `python3 research/tools/check-native-tls-reload-drift.py --json`。
- Related Java anchors: `SSLFactoryTest.java`、`NativeTransportEncryptionOptionsTest.java`、`AbstractEncryptionOptionsImpl.java`、`PEMBasedSslContextFactoryTest.java`、`FileBasedSslContextFactoryTest.java`。
