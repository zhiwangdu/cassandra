# Module: Native TLS Reload Coverage Matrix

## 范围

本模块把 native CQL TLS certificate reload 从配置、SSL context factory、Netty pipeline、JMX force reload、mTLS 依赖和测试覆盖拆开。它补充 `research/module-native-protocol.md`、`research/module-schema-cql-auth-native-deep-dive.md` 和 `research/module-schema-cql-auth-native-third-round.md` 中的 TLS/cert reload 内容，重点说明：当前源码支持的是“证书文件变化后清理 cached `SslContext`，新连接使用新 context”，不是把已经握手完成的 channel 在线换证书。

当前基线：

- `SSLFactory` 缓存 Netty `SslContext`，`checkCertFilesForHotReloading()` 检查已缓存 context 的 encryption options 是否应该 reload，验证新 context 成功后清理相同 encryption options 的 cache；默认调度常量是 `DEFAULT_HOT_RELOAD_INITIAL_DELAY_SEC=600` 和 `DEFAULT_HOT_RELOAD_PERIOD_SEC=600`，见 `src/java/org/apache/cassandra/security/SSLFactory.java:82`、`src/java/org/apache/cassandra/security/SSLFactory.java:90`、`src/java/org/apache/cassandra/security/SSLFactory.java:95`、`src/java/org/apache/cassandra/security/SSLFactory.java:180`、`src/java/org/apache/cassandra/security/SSLFactory.java:195`、`src/java/org/apache/cassandra/security/SSLFactory.java:238`。
- `DatabaseDescriptor.applySslContext()` 在启动配置阶段验证 internode/native TLS context，并调用 `SSLFactory.initHotReloading()`，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1271`。
- native server pipeline 在 channel 初始化时通过 `PipelineConfigurator.encryptionConfig()` 获取 server `SslContext`，见 `src/java/org/apache/cassandra/transport/PipelineConfigurator.java:173`、`src/java/org/apache/cassandra/transport/PipelineConfigurator.java:187`、`src/java/org/apache/cassandra/transport/PipelineConfigurator.java:223`。
- current tests cover SSLFactory JKS/PEM reload cache behavior and distributed native TLS negotiation, but do not combine them into a real native TLS cert reload end-to-end test.

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `native_tls_reload_context_cache_contract` | `SSLFactory` cache key, cache reuse and valid reload cache invalidation. |
| `native_tls_reload_file_watch_contract` | JKS file-based keystore/outbound/truststore timestamp watch and reload decision. |
| `native_tls_reload_pem_file_contract` | PEM file-based key/trust material reload only when material comes from files, not inline YAML strings. |
| `native_tls_reload_startup_validation_contract` | startup validates server/native SSL contexts and schedules periodic reload checks. |
| `native_tls_reload_native_pipeline_contract` | native server and `SimpleClient` obtain `SslContext` at channel initialization, so reload affects new channels. |
| `native_tls_reload_dual_port_policy` | native dual-port TLS policy and deprecation/error gates. |
| `native_tls_reload_mtls_gate` | mTLS authenticator requires native TLS enabled and client auth required. |
| `native_tls_reload_jmx_force_gate` | `MessagingServiceMBean.reloadSslCertificates()` calls `SSLFactory.forceCheckCertFiles()`. |
| `native_tls_reload_test_coverage_matrix` | existing JKS/PEM reload tests and native TLS negotiation tests. |
| `native_tls_reload_e2e_gap` | missing true native connection before/after certificate rotation coverage. |

## Source Contract

### Reload Control Plane

| Step | Method/source | Contract |
|---|---|---|
| Startup config apply | `EncryptionOptions.applyConfig()` | Builds `sslContextFactoryInstance`, computes `enabled`/`optional`, and treats a keystore without explicit `enabled=true` as optional TLS transition support. See `src/java/org/apache/cassandra/config/EncryptionOptions.java:218-242`. |
| Startup validation | `DatabaseDescriptor.applySslContext()` | Validates internode and native SSL contexts, then initializes hot reload scheduling. See `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1271-1280`. |
| Periodic check | `SSLFactory.initHotReloading()` | Calls `initHotReloading()` on non-unencrypted server/client options and schedules `checkCertFilesForHotReloading()` with 600s initial/period delay. See `src/java/org/apache/cassandra/security/SSLFactory.java:255-280`. |
| Manual force | `MessagingServiceMBeanImpl.reloadSslCertificates()` | Calls `SSLFactory.forceCheckCertFiles()` so JMX users can force validation/cache invalidation without waiting for the scheduler. See `src/java/org/apache/cassandra/net/MessagingServiceMBeanImpl.java:276-278`. |
| Validation before clearing | `SSLFactory.checkCachedContextsForReload()` | Validates server/client Netty contexts before clearing cache; bad cert/password/file leaves old context cached. See `src/java/org/apache/cassandra/security/SSLFactory.java:195-218`. |
| Cache clear | `SSLFactory.clearSslContextCache(options, keysToCheck)` | Removes all cached contexts whose `CacheKey.encryptionOptions` equals the changed options. See `src/java/org/apache/cassandra/security/SSLFactory.java:238-246`. |

### File Material Matrix

| Material | Factory | Reload detector | Notes |
|---|---|---|---|
| JKS keystore | `FileBasedSslContextFactory` | `HotReloadableFile(keystoreContext.filePath)` | Used by server socket type. |
| JKS outbound keystore | `FileBasedSslContextFactory` | `HotReloadableFile(outboundKeystoreContext.filePath)` | Used by client socket type for internode/SimpleClient-style outbound contexts. |
| JKS truststore | `FileBasedSslContextFactory` | `HotReloadableFile(trustStoreContext.filePath)` | Required when peer verification/client auth needs trust material. |
| PEM file private key/cert | `PEMBasedSslContextFactory` | only when `maybeFilebasedKey` and `hasKeystore()` | File is reread by `readPEMFile()` on rebuild. |
| PEM outbound file key/cert | `PEMBasedSslContextFactory` | only when outbound material is file based | Inline outbound private key does not create a reloadable file. |
| PEM file trusted certs | `PEMBasedSslContextFactory` | only when `maybeFilebasedKey` and `hasTruststore()` | Inline trusted certs do not hot reload from file timestamps. |

Core source:

- `FileBasedSslContextFactory.initHotReloading()` builds a volatile list of `HotReloadableFile` entries; `shouldReload()` compares and updates last-modified timestamp, see `src/java/org/apache/cassandra/security/FileBasedSslContextFactory.java:59`、`src/java/org/apache/cassandra/security/FileBasedSslContextFactory.java:101`、`src/java/org/apache/cassandra/security/FileBasedSslContextFactory.java:258`。
- `PEMBasedSslContextFactory.initHotReloading()` only adds file-backed key/trust material, then `buildKeyManagerFactory()` and `buildTrustManagerFactory()` reread PEM files, see `src/java/org/apache/cassandra/security/PEMBasedSslContextFactory.java:188`、`src/java/org/apache/cassandra/security/PEMBasedSslContextFactory.java:236`、`src/java/org/apache/cassandra/security/PEMBasedSslContextFactory.java:278`。

### Native Transport Boundary

| Path | Source | Reload implication |
|---|---|---|
| Server encrypted port | `PipelineConfigurator.encryptionConfig()` `ENCRYPTED` branch | Fetches cached server `SslContext` during `initChannel()`, then adds `SslHandler`; existing channel keeps its handler. |
| Server optional TLS | `PipelineConfigurator.encryptionConfig()` `OPTIONAL` branch | Fetches cached server `SslContext` before TLS/plain detection handler replaces itself with `SslHandler`. |
| Native dual ports | `NativeTransportService` and `DatabaseDescriptor` | `native_transport_port_ssl` creates a separate TLS server only if client encryption is enabled/optional; dual-port mode is deprecated. |
| Test client | `SimpleClient.SecureInitializer` | Fetches cached client `SslContext` during channel init, matching the new-connection-only reload boundary. |
| mTLS auth | `MutualTlsAuthenticator.checkMtlsConfigurationIsValid()` | Requires `client_encryption_options.enabled=true` and `require_client_auth=true`; certificate identity validation occurs after TLS client cert is available. |

`native_tls_reload_native_pipeline_contract` means a real end-to-end reload test must prove both sides of the boundary:

```text
start native TLS server with cert A
  -> connect client and verify cert/protocol behavior for new channel
  -> rotate keystore/truststore to cert B
  -> force or wait for SSLFactory reload
  -> connect new client channel and prove cert B is used
  -> prove bad rotation preserves old cached context
```

The current source does not claim existing channels renegotiate certificates. Existing channels keep their installed `SslHandler` and `SSLEngine`.

## 设计目标

- Validate TLS material at startup so bad certs fail early for native/internode paths.
- Avoid rebuilding expensive Netty `SslContext` objects on every connection; cache by `EncryptionOptions` + socket type + context description.
- Allow operators to rotate certificate files without process restart, affecting subsequent connections once validation succeeds.
- Preserve serving ability on bad rotation by leaving old contexts in cache.
- Support JKS and file-based PEM material while making inline PEM config immutable until process/config reload.

## 解决的问题

- Native TLS users need a low-risk certificate rotation path that avoids restart.
- Optional/native dual-port modes need clear connection behavior when both encrypted and plaintext clients exist.
- mTLS authentication depends on native TLS client certificate handoff, so its config gate must fail before serving traffic.
- Tests must not confuse SSLFactory cache reload with a full native transport end-to-end reload.

## 设计取舍

- Last-modified timestamps are a lightweight file-change detector; they do not prove certificate identity changed.
- Reload clears cache only after full server and client context validation, trading reload immediacy for safety.
- Cache invalidation is by `EncryptionOptions.equals()`, whose fields include keystore/truststore/protocol/cipher/auth flags and `ssl_context_factory`; it does not inspect certificate file bytes.
- The JMX force hook is exposed on `MessagingServiceMBean`, but the same `SSLFactory` cache is shared by native and internode contexts.
- Native pipeline reload is new-connection based; live channel renegotiation is intentionally absent.

## 核心类

| 类 | 作用 |
|---|---|
| `SSLFactory` | Creates, caches, validates and invalidates Netty/JSSE SSL contexts. |
| `SSLFactory.CacheKey` | Cache key: `EncryptionOptions`, `SocketType`, context description. |
| `FileBasedSslContextFactory` | JKS-style file material loader and reload timestamp tracker. |
| `PEMBasedSslContextFactory` | PEM file/inline material loader; file-backed PEM participates in hot reload. |
| `EncryptionOptions` | Native/internode TLS config, factory instantiation, equality/hash for cache keys. |
| `DatabaseDescriptor` | Applies native encryption options, validates contexts and starts reload scheduler. |
| `PipelineConfigurator` | Adds native TLS/optional TLS `SslHandler` to new server channels. |
| `NativeTransportService` | Builds regular/TLS native servers for single-port and dual-port policy. |
| `SimpleClient` | Test/client-side secure native connection setup using `SSLFactory`; source `src/java/org/apache/cassandra/transport/SimpleClient.java`. |
| `MutualTlsAuthenticator` | Requires native TLS client auth and maps certificate identity to roles. |

## 核心接口

- `SSLFactory.getOrCreateSslContext(EncryptionOptions, boolean, SocketType, String)`：cache lookup/build entrypoint.
- `SSLFactory.checkCertFilesForHotReloading()`：scheduled reload check.
- `SSLFactory.forceCheckCertFiles()`：manual force reload entrypoint.
- `ISslContextFactory.initHotReloading()` / `shouldReload()`：factory-specific reload hooks.
- `EncryptionOptions.applyConfig()`：factory initialization and enabled/optional computation.
- `PipelineConfigurator.EncryptionConfig.applyTo(Channel)`：native channel TLS attach point.
- `MessagingServiceMBean.reloadSslCertificates()`：JMX operation invoking force reload.

## 核心数据结构

- `ConcurrentHashMap<CacheKey, SslContext> cachedSslContexts`：global Netty `SslContext` cache.
- `List<HotReloadableFile> hotReloadableFiles`：factory-local reloadable files.
- `HotReloadableFile.lastModTime`：last observed timestamp.
- `FileBasedStoreContext`：file path/password/expiry-check state for keystore/truststore.
- `PEMBasedKeyStoreContext`：PEM key/trust material plus whether it might be file based.
- `EncryptionOptions.TlsEncryptionPolicy`：`UNENCRYPTED`、`OPTIONAL`、`ENCRYPTED` native pipeline policy.

## 生命周期

```text
startup
  -> Config.client_encryption_options
  -> EncryptionOptions.applyConfig()
     -> instantiate ISslContextFactory
     -> compute enabled / optional
  -> DatabaseDescriptor.applySslContext()
     -> SSLFactory.validateSslContext("Native transport", client_encryption_options, require_client_auth, true)
     -> SSLFactory.initHotReloading(server_encryption_options, client_encryption_options, false)
        -> sslContextFactoryInstance.initHotReloading()
        -> schedule periodic checkCertFilesForHotReloading()

new native channel
  -> PipelineConfigurator.initChannel()
     -> configure protocol handlers
     -> encryptionConfig.applyTo(channel)
        -> SSLFactory.getOrCreateSslContext(client_encryption_options, require_client_auth, SERVER, "client_encryption_options")
        -> add SslHandler if encrypted or encrypted bytes detected

certificate file changes
  -> scheduled check or MessagingServiceMBean.reloadSslCertificates()
  -> SSLFactory.checkCachedContextsForReload(force?)
     -> factory.shouldReload() or force
     -> validateSslContext(...)
     -> clear cached SslContexts for matching EncryptionOptions
  -> next native channel builds fresh SslContext
```

## 调用链

```text
operator rotates native TLS files
  -> file last-modified changes
  -> SSLFactory.checkCertFilesForHotReloading()
     -> FileBasedSslContextFactory.shouldReload()
        -> HotReloadableFile.shouldReload()
     -> SSLFactory.validateSslContext("client_encryption_options", ...)
        -> sslContextFactoryInstance.createNettySslContext(SERVER)
        -> serverSslContext.newEngine(...)
        -> sslContextFactoryInstance.createNettySslContext(CLIENT)
     -> SSLFactory.clearSslContextCache(options, keysToCheck)
  -> next PipelineConfigurator channel
     -> SSLFactory.getOrCreateSslContext(...)
     -> new SslHandler with new SslContext
```

## 配置项

| 配置项 | 定义/使用 | 作用 |
|---|---|---|
| `client_encryption_options.enabled` | `src/java/org/apache/cassandra/config/Config.java:434` / `EncryptionOptions.applyConfig()` | Enables encrypted native transport. |
| `client_encryption_options.optional` | `EncryptionOptions.applyConfig()` | Optional TLS/plaintext on same port when enabled by config/keystore. |
| `client_encryption_options.keystore` / `keystore_password` | `EncryptionOptions.fillSslContextParams()` | Server key material for native TLS. |
| `client_encryption_options.truststore` / `truststore_password` | `EncryptionOptions.fillSslContextParams()` | Trust material for client cert validation. |
| `client_encryption_options.require_client_auth` | `EncryptionOptions.fillSslContextParams()` / `MutualTlsAuthenticator` | Requires client certificate and gates mTLS authenticator. |
| `client_encryption_options.require_endpoint_verification` | `PipelineConfigurator` | Adds peer endpoint verification to `SslHandler`. |
| `client_encryption_options.accepted_protocols` / `cipher_suites` | `SSLFactory.validateSslContext()` and tests | Limits TLS protocol/cipher negotiation. |
| `native_transport_port_ssl` | `src/java/org/apache/cassandra/config/Config.java:282` | Deprecated dual-port TLS listener, must have encryption enabled when distinct from regular port. |

## Metrics

- There are no dedicated certificate reload counters in this source path.
- Native connection metrics and auth metrics show downstream effects, but do not identify reload success/failure.
- TLS handshake success/failure is mostly observable through logs/tests, not a first-class `ClientMetrics` counter.

## 日志

- Startup validation logs enabled protocols/ciphers when `logProtocolAndCiphers=true`.
- Unsupported ciphers are warned and can cause startup validation failure when no ciphers remain.
- Successful reload logs `SSL certificates have been updated... Resetting the ssl contexts for new connections.`
- Failed reload logs `Failed to hot reload the SSL Certificates! Please check the certificate files...` and preserves cached contexts.
- Dual native ports log a deprecation warning when `native_transport_port_ssl` is configured.

## 运维关注点

- Reload affects new connections only. Existing native client connections keep their current `SslHandler`.
- Use `reloadSslCertificates` JMX/`MessagingServiceMBean` or wait for the scheduled check; the default scheduled delay is 600 seconds.
- Bad rotations should not break existing cached contexts, but new certificate files should still be verified with a canary new connection.
- Inline PEM material is not file-watched; use file-backed PEM if hot reload is required.
- mTLS deployments must rotate truststore/client certs carefully because authentication can fail after TLS handshake if identity mapping is missing or stale.
- Dual native ports are deprecated and have corner-case limitations documented in `DatabaseDescriptor`.

## 性能瓶颈

- Building Netty `SslContext` is expensive and consumes direct memory; cache reuse avoids per-connection rebuilds.
- Forced reload validates both server and client contexts for each cached key before clearing, so a large cache can make reload checks more expensive.
- TLS handshake cost still applies to every new encrypted native channel.
- Excessive certificate churn can cause repeated validation/cache churn.

## 常见故障

- `Hot reloading functionality has not been initialized.`：`SSLFactory.checkCertFilesForHotReloading()` was called before `initHotReloading()`.
- `Failed to create SSL context using Native transport`：startup or reload validation cannot build the SSL context.
- `Failed to hot reload the SSL Certificates!`：changed files were detected, but validation failed; old cached contexts remain.
- TLS connection cannot negotiate: accepted protocols/ciphers do not overlap or keystore/truststore is invalid.
- `MutualTlsAuthenticator requires client_encryption_options.enabled...`：mTLS auth configured without native TLS client auth.
- New connection still sees old certificate: scheduler has not run, JMX force was not called, timestamp did not change, or cache key did not match expected options.

## 测试用例

- `test/unit/org/apache/cassandra/security/SSLFactoryTest.java:110` covers JKS reload happy path: timestamp change clears cache and new context differs.
- `test/unit/org/apache/cassandra/security/SSLFactoryTest.java:180` covers PEM reload happy path.
- `test/unit/org/apache/cassandra/security/SSLFactoryTest.java:217` covers bad password validation failure.
- `test/unit/org/apache/cassandra/security/SSLFactoryTest.java:227` and `test/unit/org/apache/cassandra/security/SSLFactoryTest.java:260` prove bad password/corrupt-or-missing file does not clear old cached context.
- `test/distributed/org/apache/cassandra/distributed/test/NativeTransportEncryptionOptionsTest.java:49` covers bad native keystore startup failure.
- `test/distributed/org/apache/cassandra/distributed/test/NativeTransportEncryptionOptionsTest.java:83` and `test/distributed/org/apache/cassandra/distributed/test/NativeTransportEncryptionOptionsTest.java:104` cover native TLS negotiation and dual-port behavior.
- `test/distributed/org/apache/cassandra/distributed/test/NativeTransportEncryptionOptionsTest.java:165` and `test/distributed/org/apache/cassandra/distributed/test/NativeTransportEncryptionOptionsTest.java:202` cover accepted protocol/cipher negotiation.
- `test/distributed/org/apache/cassandra/distributed/test/NativeTransportEncryptionOptionsTest.java:254` covers endpoint verification and client certificate handling through driver SSL options.
- `test/distributed/org/apache/cassandra/distributed/test/AbstractEncryptionOptionsImpl.java:112` provides the `TlsConnection` helper and `test/distributed/org/apache/cassandra/distributed/test/AbstractEncryptionOptionsImpl.java:194` performs handshake assertions.
- `test/unit/org/apache/cassandra/security/PEMBasedSslContextFactoryTest.java` covers PEM factory parse/config boundaries; `test/unit/org/apache/cassandra/security/FileBasedSslContextFactoryTest.java` covers file-based factory password/config boundaries.
- Remaining gap: no Java test currently combines native TLS server startup, real connection, certificate file rotation, `SSLFactory.checkCertFilesForHotReloading()` or JMX force, and a second real native TLS connection that proves fresh certificate material is used.
