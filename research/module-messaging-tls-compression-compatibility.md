# Module: Messaging TLS And Compression Compatibility

本页是 Gossip/Messaging 第五轮补充，聚焦 internode TLS optional/strict、handshake framing、`internode_compression` 策略和 mixed-version 测试缺口。第二轮通用 Netty handshake 内容已在 `module-gossip-messaging-deep-dive.md` 覆盖；本页把配置、源码分支、测试覆盖和缺口固定成可 drift-check 的矩阵。

## 范围

- Internode TLS policy：`server_encryption_options.internode_encryption`、`optional`、`legacy_ssl_storage_port_enabled`、`require_client_auth`、`require_endpoint_verification`。
- Inbound TLS pipeline：`RejectSslHandler`、`OptionalSslHandler`、strict `SslHandler` 和 required-encryption handshake gate。
- Outbound TLS pipeline：`OutboundConnectionSettings.defaultEncryptionOptions()`、`OutboundConnectionInitiator.SslFallbackConnectionType`、client-side SSL context 和 server authentication。
- Messaging handshake and frames：`HandshakeProtocol.Initiate` / `Accept` 的 version bounds、connection type、framing id、CRC，以及 LZ4/CRC/unprotected encoder/decoder。
- Compression policy：`internode_compression` 的 `all`、`dc`、`none` 到 `OutboundConnectionSettings.Framing.LZ4` / `CRC` 的映射。
- Test boundary：当前仓库已有 TLS distributed tests、compression unit tests 和 config propagation tests；仍缺少 rolling-upgrade/mixed-version 场景同时覆盖 TLS optional/strict 与 `internode_compression`。

## 设计目标

- 允许从明文 internode traffic 滚动迁移到 TLS：`conf/cassandra.yaml:1637-1640` 明确两步迁移，先 `internode_encryption=<dc|rack|all>` 且 `optional=true`，再切 `optional=false` / mTLS。
- 把 TLS 策略和 messaging handshake 解耦：TLS handler 先进入 Netty pipeline，`HandshakeProtocol` 继续负责 messaging version、connection type 和 framing 协商，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:117-141`、`src/java/org/apache/cassandra/net/HandshakeProtocol.java:55-181`。
- 让 `internode_compression=dc` 使用 snitch DC 判断，只压缩跨 DC messaging traffic，见 `src/java/org/apache/cassandra/net/OutboundConnectionSettings.java:454-464`、`src/java/org/apache/cassandra/net/OutboundConnectionSettings.java:497-500`。
- 让 rolling upgrade 仍走 version bounds，而不是把 frame/TLS policy 硬编码到版本号中；`Initiate` 发送 min/max，`Accept` 返回 negotiated version 和 peer max，见 `src/java/org/apache/cassandra/net/HandshakeProtocol.java:92-181`、`src/java/org/apache/cassandra/net/HandshakeProtocol.java:224-274`。

## 解决的问题

- 明文配置下误连 TLS：`UNENCRYPTED` policy 在 inbound 端安装 `RejectSslHandler`，检测到 TLS bytes 后记录拒绝并关闭连接，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:119-124`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:574-599`。
- 过渡期同端口混用：`OPTIONAL` policy 的 `OptionalSslHandler` 读取前 5 bytes，用 `SslHandler.isEncrypted(in)` 决定替换成 `SslHandler` 或移除自身继续明文，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:541-571`。
- strict TLS 下防止 peer 伪装明文：inbound handshake 在 `isEncryptionRequired(initiate.from)` 且 pipeline 没有 `SslHandler` 时 warn 并 fail handshake，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:320-326`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:365-373`。
- outbound 是否加 TLS 不靠调用方猜测：`OutboundConnectionSettings.encryption()` 使用 `DatabaseDescriptor.getInternodeMessagingEncyptionOptions()` 和 `ServerEncryptionOptions.shouldEncrypt(endpoint)` 得出目标 peer 的 encryption options，见 `src/java/org/apache/cassandra/net/OutboundConnectionSettings.java:359-362`、`src/java/org/apache/cassandra/net/OutboundConnectionSettings.java:489-494`。
- compression 与 frame integrity 分层：`internode_compression` 只决定 messaging framing 是 `LZ4` 还是 `CRC`；streaming connection 仍默认 `UNPROTECTED`，见 `src/java/org/apache/cassandra/net/OutboundConnectionSettings.java:454-464`。

## 设计取舍

- `EncryptionOptions.applyConfig()` 在有 keystore 且未启用 TLS 时默认 `optional=true`，方便滚动迁移；没有 keystore 时不能 optional TLS，因为无法协商 TLS，见 `src/java/org/apache/cassandra/config/EncryptionOptions.java:218-242`。
- `ServerEncryptionOptions.applyConfigInternal()` 用 `internode_encryption != none` 覆盖通用 `enabled`，并强制 `rack` / `dc` 为 optional，以便同 rack/DC 的明文连接仍能建立，见 `src/java/org/apache/cassandra/config/EncryptionOptions.java:675-699`。
- `require_client_auth` 配 `rack` / `dc` 会 warning，因为握手中的 broadcast address 可被伪造以绕过 mTLS；需要强 mTLS 时应使用 `internode_encryption=all`，见 `src/java/org/apache/cassandra/config/EncryptionOptions.java:686-692`。
- `HandshakeProtocol.Initiate` 把 framing id 分散到兼容位上，保留 pre-4.0 flag layout 的兼容读法；5.0+ 仍拒绝 `maxMessagingVersion < VERSION_40`，见 `src/java/org/apache/cassandra/net/HandshakeProtocol.java:107-120`、`src/java/org/apache/cassandra/net/HandshakeProtocol.java:153-165`。
- Java `Config` 默认 `internode_compression=none`，模板 `cassandra.yaml` 默认 `dc`；真实 daemon 配置来自 yaml，测试可直接设置 `Config.InternodeCompression`，见 `src/java/org/apache/cassandra/config/Config.java:436`、`conf/cassandra.yaml:1730-1742`。

## 核心类

| 类 | 责任 |
|---|---|
| `EncryptionOptions` | 通用 TLS options、`TlsEncryptionPolicy`、optional/enabled 归一化、accepted protocols/ciphers，见 `src/java/org/apache/cassandra/config/EncryptionOptions.java:51-68`、`src/java/org/apache/cassandra/config/EncryptionOptions.java:218-242`、`src/java/org/apache/cassandra/config/EncryptionOptions.java:420-433` |
| `ServerEncryptionOptions` | Internode-specific TLS policy、`InternodeEncryption`、`shouldEncrypt(endpoint)`、legacy ssl storage port flag，见 `src/java/org/apache/cassandra/config/EncryptionOptions.java:613-650`、`src/java/org/apache/cassandra/config/EncryptionOptions.java:675-723` |
| `DatabaseDescriptor` | 应用 server encryption config、校验 legacy SSL port 与 `UNENCRYPTED` 冲突、暴露 internode compression/encryption getters，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:963-970`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3650-3657`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4039-4046` |
| `InboundConnectionInitiator` | inbound Netty pipeline、TLS optional/reject/strict、required encryption gate、Accept response、frame decoder setup，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:100-141`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:312-362`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:467-516` |
| `OutboundConnectionSettings` | peer-specific encryption options、connect target/preferred IP、messaging/streaming framing、`shouldCompressConnection()`，见 `src/java/org/apache/cassandra/net/OutboundConnectionSettings.java:50-68`、`src/java/org/apache/cassandra/net/OutboundConnectionSettings.java:359-364`、`src/java/org/apache/cassandra/net/OutboundConnectionSettings.java:454-500` |
| `OutboundConnectionInitiator` | outbound preconnect auth、optional SSL handler insertion、server authentication、Initiate send、Accept decode、frame encoder insertion，见 `src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:139-181`、`src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:216-253`、`src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:297-316`、`src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:336-399` |
| `HandshakeProtocol` | Internode handshake wire contract、version min/max、framing id、connection type、CRC validation，见 `src/java/org/apache/cassandra/net/HandshakeProtocol.java:41-181`、`src/java/org/apache/cassandra/net/HandshakeProtocol.java:213-274` |
| `FrameEncoderLZ4` / `FrameDecoderLZ4` | compressed messaging frames；unit coverage exercises random frames in `FramingTest.testRandomLZ4()`, see `test/unit/org/apache/cassandra/net/FramingTest.java:107-111` |
| `FrameEncoderCrc` / `FrameDecoderCrc` | uncompressed CRC-protected messaging frames；unit coverage exercises random frames in `FramingTest.testRandomCrc()`, see `test/unit/org/apache/cassandra/net/FramingTest.java:113-117` |

## 核心接口

- `EncryptionOptions.tlsEncryptionPolicy()`：把 normalized `optional` / `enabled` 转成 `OPTIONAL`、`ENCRYPTED` 或 `UNENCRYPTED`，见 `src/java/org/apache/cassandra/config/EncryptionOptions.java:420-433`。
- `ServerEncryptionOptions.shouldEncrypt(InetAddressAndPort endpoint)`：按 `none`、`all`、`dc`、`rack` 和 snitch 本地 DC/rack 判断 peer 是否必须 TLS，见 `src/java/org/apache/cassandra/config/EncryptionOptions.java:702-723`。
- `ServerEncryptionOptions.isExplicitlyOptional()`：只返回用户显式设置的 optional；handshake required-encryption gate 用它区分 transitional mode 和 `dc/rack` 隐式 optional，见 `src/java/org/apache/cassandra/config/EncryptionOptions.java:726-733`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:365-368`。
- `OutboundConnectionSettings.framing(ConnectionCategory category)`：streaming 返回 `UNPROTECTED`，messaging 根据 `shouldCompressConnection()` 返回 `LZ4` 或 `CRC`，见 `src/java/org/apache/cassandra/net/OutboundConnectionSettings.java:454-464`。
- `OutboundConnectionSettings.shouldCompressConnection(IEndpointSnitch, local, remote)`：`all` 始终 true，`dc` 仅 remote 不在 local DC 时 true，`none` false，见 `src/java/org/apache/cassandra/net/OutboundConnectionSettings.java:496-500`。
- `HandshakeProtocol.Initiate.maybeDecode(ByteBuf)` / `Accept.maybeDecode(ByteBuf)`：分别校验 protocol magic/framing/version/CRC 和 accept CRC，见 `src/java/org/apache/cassandra/net/HandshakeProtocol.java:141-181`、`src/java/org/apache/cassandra/net/HandshakeProtocol.java:248-274`。

## 核心数据结构

| 数据结构 | 字段/值 | 语义 |
|---|---|---|
| `TlsEncryptionPolicy` | `UNENCRYPTED` / `OPTIONAL` / `ENCRYPTED` | inbound pipeline 的 TLS handler branch，见 `src/java/org/apache/cassandra/config/EncryptionOptions.java:51-68` |
| `ServerEncryptionOptions.InternodeEncryption` | `all, none, dc, rack` | peer selection policy；`dc` / `rack` 需要 snitch 判断，见 `src/java/org/apache/cassandra/config/EncryptionOptions.java:615-618` |
| `Config.InternodeCompression` | `all, none, dc` | outbound messaging compression policy，见 `src/java/org/apache/cassandra/config/Config.java:1187-1190` |
| `OutboundConnectionSettings.Framing` | `UNPROTECTED(0)`, `LZ4(1)`, `CRC(2)` | handshake flags 中编码的 frame family，见 `src/java/org/apache/cassandra/net/OutboundConnectionSettings.java:50-68` |
| `HandshakeProtocol.Initiate` | `AcceptVersions`, `ConnectionType`, `Framing`, `from` | outbound first handshake message，包含 magic/flags/from/CRC，见 `src/java/org/apache/cassandra/net/HandshakeProtocol.java:86-181` |
| `HandshakeProtocol.Accept` | `useMessagingVersion`, `maxMessagingVersion` | inbound second handshake message，包含 negotiated version、peer max 和 CRC，见 `src/java/org/apache/cassandra/net/HandshakeProtocol.java:224-274` |

## 生命周期

### Config to TLS policy

1. `DatabaseDescriptor` 读取并 apply `server_encryption_options`，再禁止 `legacy_ssl_storage_port_enabled=true` 且 policy 为 `UNENCRYPTED` 的配置，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:963-970`。
2. `EncryptionOptions.applyConfig()` 初始化 SSL context factory，计算通用 `isEnabled` 和 `isOptional`，见 `src/java/org/apache/cassandra/config/EncryptionOptions.java:218-242`。
3. `ServerEncryptionOptions.applyConfigInternal()` 用 `internode_encryption` 重新计算 `isEnabled`，并让 `rack` / `dc` 隐式 optional，见 `src/java/org/apache/cassandra/config/EncryptionOptions.java:675-699`。
4. `tlsEncryptionPolicy()` 把结果映射给 inbound pipeline，见 `src/java/org/apache/cassandra/config/EncryptionOptions.java:420-433`。

### Inbound TLS and handshake

1. Inbound channel 初始化先放入 `InternodeErrorExclusionsHandler`，再按 `settings.encryption.tlsEncryptionPolicy()` 选择 reject/optional/strict TLS handler，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:100-141`。
2. Optional TLS 检测前 5 bytes；TLS bytes 替换成 `SslHandler`，非 TLS bytes 移除检测器继续明文，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:541-571`。
3. Strict TLS 直接插入 `SslHandler`；明文连接无法通过 pipeline，required-encryption gate 也会在握手阶段阻止，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:128-131`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:320-326`。
4. 解码 `Initiate` 后按 messaging/streaming accept bounds 计算 `useMessagingVersion`，返回 `Accept`，版本不相交则关闭，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:331-362`。
5. messaging pipeline 按 peer requested framing 加入 `FrameDecoderLZ4`、`FrameDecoderCrc` 或 `FrameDecoderUnprotected`，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:483-516`。

### Outbound TLS, compression, frames

1. Outbound connect 先执行 `OUTBOUND_PRECONNECT` authenticator；失败会 interrupt outbound connections，见 `src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:139-150`。
2. `OutboundConnectionSettings.withDefaults()` 为 peer 计算 connect target、encryption、framing、timeouts 和 acceptVersions，见 `src/java/org/apache/cassandra/net/OutboundConnectionSettings.java:466-480`。
3. initializer 在 `SERVER_CONFIG` 且 `settings.withEncryption()` 或 fallback SSL/mTLS 下创建 client `SslHandler`，见 `src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:216-253`。
4. channel active 后发送 `HandshakeProtocol.Initiate(settings.acceptVersions, type, settings.framing, settings.from)`，见 `src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:297-316`。
5. 收到 `Accept` 后校验 negotiated version，messaging connection 按 `settings.framing` 插入 `FrameEncoderLZ4`、`FrameEncoderCrc` 或 `FrameEncoderUnprotected`，见 `src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java:336-399`。

## 调用链

Internode TLS policy:

```text
DatabaseDescriptor.applyConfig()
  -> conf.server_encryption_options.applyConfig()
  -> ServerEncryptionOptions.applyConfigInternal()
  -> EncryptionOptions.tlsEncryptionPolicy()
InboundConnectionInitiator.Initializer.initChannel(...)
  -> switch tlsEncryptionPolicy
     -> RejectSslHandler | OptionalSslHandler | SslHandler
  -> Handler.initiate(...)
  -> isEncryptionRequired(peer) && !isChannelEncrypted(ctx) => failHandshake
```

Outbound compression and frame selection:

```text
OutboundConnections selects peer/type
  -> new OutboundConnectionSettings(peer).withDefaults(MESSAGING)
  -> OutboundConnectionSettings.framing(MESSAGING)
     -> shouldCompressConnection(snitch, local, peer)
     -> Framing.LZ4 or Framing.CRC
  -> OutboundConnectionInitiator.channelActive()
     -> send Initiate(acceptVersions, type, framing, from)
InboundConnectionInitiator.setupMessagingPipeline(...)
  -> switch initiate.framing
     -> FrameDecoderLZ4 | FrameDecoderCrc | FrameDecoderUnprotected
OutboundConnectionInitiator.decode(Accept)
  -> switch settings.framing
     -> FrameEncoderLZ4 | FrameEncoderCrc | FrameEncoderUnprotected
```

## 配置项

- `server_encryption_options.internode_encryption`：`none`、`dc`、`rack`、`all`，决定 outbound peer 是否使用 TLS 和 inbound 是否要求 encrypted channel，见 `conf/cassandra.yaml:1641-1648`、`src/java/org/apache/cassandra/config/EncryptionOptions.java:702-723`。
- `server_encryption_options.optional`：明文/TLS 同端口 transitional switch；有 keystore 且 `internode_encryption=none` 时未显式配置也会 optional，见 `conf/cassandra.yaml:1649-1652`、`src/java/org/apache/cassandra/config/EncryptionOptions.java:226-241`。
- `server_encryption_options.legacy_ssl_storage_port_enabled`：4.0 upgrade 兼容端口；与 `UNENCRYPTED` policy 同时启用会启动失败，见 `conf/cassandra.yaml:1653-1655`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:963-970`。
- `server_encryption_options.require_client_auth`：internode mTLS；与 `dc` / `rack` 搭配会产生安全 warning，见 `conf/cassandra.yaml:1670-1674`、`src/java/org/apache/cassandra/config/EncryptionOptions.java:686-692`。
- `server_encryption_options.accepted_protocols` / `cipher_suites`：TLS protocol/cipher allow-list，distributed tests 覆盖协议/cipher不能协商的 failure，见 `test/distributed/org/apache/cassandra/distributed/test/InternodeEncryptionOptionsTest.java:232-290`。
- `internode_compression`：`all`、`dc`、`none`，模板默认 `dc`，源码策略在 `OutboundConnectionSettings.shouldCompressConnection()`，见 `conf/cassandra.yaml:1730-1742`、`src/java/org/apache/cassandra/net/OutboundConnectionSettings.java:496-500`。

## Metrics

- `system_views.internode_outbound` 可观察 successful connection attempts；`InternodeEncryptionOptionsTest.allInternodeEncryptionEstablishedTest()` 用它确认 strict TLS 集群已建立 internode outbound connection，见 `test/distributed/org/apache/cassandra/distributed/test/InternodeEncryptionOptionsTest.java:197-218`。
- `MessagingService` 注释列出 `system_views.internode_inbound` / `system_views.internode_outbound` 作为 internode connection views，见 `src/java/org/apache/cassandra/net/MessagingService.java:195-205`。
- Frame decode corruption 仍落在 `InternodeInboundMetrics`，不是 TLS/compression 专属 metrics；相关指标在 `module-gossip-messaging-deep-dive.md` 已归档。

## 日志

- `RejectSslHandler` 对明文配置下的 TLS attempt 记录 “Rejected incoming TLS connection before negotiating...”，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:585-590`。
- required encryption 收到 unencrypted handshake 时记录 “attempted to establish an unencrypted connection”，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:320-326`。
- 版本不相交时 inbound 记录 peer only supports higher/lower messaging versions，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:346-355`。
- 成功建立 messaging connection 时记录 `version`、`framing`、`encryption`，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:510-516`。
- handshake failure 会按 `internode_error_reporting_exclusions` 和 invalid legacy protocol magic no-spam 配置降噪，见 `src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:144-155`、`src/java/org/apache/cassandra/net/InboundConnectionInitiator.java:381-391`。

## 运维关注点

- `optional=true` 是迁移窗口，不是最终安全姿态；窗口期间同一个 storage port 可接受明文和 TLS，故障排查要同时检查 TLS keystore/truststore、protocol magic 和 internode authenticator。
- `internode_encryption=dc` / `rack` 与 `require_client_auth=true` 不提供强 mTLS 边界；源码 warning 明确指出 broadcast address spoofing 风险，强认证应使用 `all`。
- `internode_compression=dc` 依赖 snitch DC 判断；DC/rack gossip 不收敛时，跨 DC traffic 是否 LZ4 可能与 operator 预期不一致。
- `legacy_ssl_storage_port_enabled` 只应在旧 upgrade 过渡使用；新部署应避免额外端口面。
- Rolling upgrade 中同时切 TLS policy 和 compression policy 风险更高，因为失败可能表现为 TLS negotiation failure、handshake version incompatibility 或 frame decode corruption；当前仓库缺少组合型 mixed-version dtest。

## 性能瓶颈

- Optional TLS 在每条 inbound connection 的前几个 bytes 做 TLS detection；成本小，但连接 churn 下会放大 handshake/SSL context 观测噪声。
- LZ4 frame 可降低跨 DC bandwidth，但会增加 CPU 和 allocator 压力；`FrameEncoderLZ4` 在压缩无收益时会发送原 payload，见 `module-gossip-messaging-deep-dive.md` 的性能条目。
- `internode_compression=all` 会压缩 intra-DC traffic，可能在低延迟高带宽环境中得不偿失。
- Strict TLS + mTLS 把 certificate validation 放到连接建立路径；证书过期、truststore 错误或 protocol/cipher mismatch 会直接影响 internode availability。

## 常见故障

- TLS client 连接默认配置节点失败：默认 yaml 是 insecure `internode_encryption: none`，但如果无 keystore，optional TLS 也无法建立，见 `test/distributed/org/apache/cassandra/distributed/test/InternodeEncryptionOptionsTest.java:67-82`。
- 有 keystore 但 TLS 被拒绝：显式 `internode_encryption=none` 且 `optional=false` 会安装 reject handler，见 `test/distributed/org/apache/cassandra/distributed/test/InternodeEncryptionOptionsTest.java:171-194`。
- 两个 DC 互连失败：一端 required encrypted，另一端 unencrypted，会导致 schema agreement/open connection failure；`InternodeEncryptionEnforcementTest.testConnectionsAreRejectedWithInvalidConfig()` 覆盖该场景，见 `test/distributed/org/apache/cassandra/distributed/test/InternodeEncryptionEnforcementTest.java:167-229`。
- 协议/cipher 不匹配：accepted protocols 或 cipher suites 没有交集会失败并收到 handshake exception，见 `test/distributed/org/apache/cassandra/distributed/test/InternodeEncryptionOptionsTest.java:232-290`。
- 预期 compression 但看到 CRC framing：检查 `DatabaseDescriptor.internodeCompression()`、snitch local/remote DC 和 `OutboundConnectionSettings.shouldCompressConnection()`；unit tests 覆盖 none/dc/all/same-DC，见 `test/unit/org/apache/cassandra/net/OutboundConnectionSettingsTest.java:109-143`。

## 测试用例

| 场景 ID | 现有覆盖 | 状态 |
|---|---|---|
| `messaging_tls_policy_config_baseline` | `EncryptionOptions.applyConfig()` / `tlsEncryptionPolicy()` / `ServerEncryptionOptions.shouldEncrypt()` and `DatabaseDescriptor` legacy SSL port guard | 源码 baseline |
| `messaging_tls_optional_inbound_baseline` | `InternodeEncryptionOptionsTest.optionalTlsConnectionDisabledWithoutKeystoreTest()`、`optionalTlsConnectionAllowedWithKeystoreTest()`、`optionalTlsConnectionAllowedToStoragePortTest()` | 已有 distributed coverage |
| `messaging_tls_reject_unencrypted_baseline` | `InternodeEncryptionOptionsTest.tlsConnectionRejectedWhenUnencrypted()` | 已有 distributed coverage |
| `messaging_tls_strict_inbound_baseline` | `InternodeEncryptionOptionsTest.allInternodeEncryptionEstablishedTest()` | 已有 distributed coverage |
| `messaging_tls_protocol_cipher_baseline` | `negotiatedProtocolMustBeAcceptedProtocolTest()`、`connectionCannotAgreeOnClientAndServer()`、`nodeMustNotStartWithNonExistantProtocol()`、`nodeMustNotStartWithNonExistantCipher()` | 已有 distributed coverage |
| `messaging_tls_cross_dc_enforcement_baseline` | `InternodeEncryptionEnforcementTest.testConnectionsAreRejectedWithInvalidConfig()`、`testConnectionsAreAcceptedWithValidConfig()` | 已有 distributed coverage |
| `messaging_tls_mtls_auth_baseline` | `InternodeEncryptionEnforcementTest.testInboundConnectionsAreRejectedWhenAuthFails()`、`testOutboundConnectionsAreRejectedWhenAuthFails()`、`testAuthenticationWithCertificateAuthenticator()` | 已有 distributed coverage |
| `messaging_internode_compression_policy_baseline` | `OutboundConnectionSettingsTest.shouldCompressConnection_None/DifferentDc/All/SameDc()` | 已有 unit coverage |
| `messaging_internode_compression_config_baseline` | `JVMDTestTest.nonSharedConfigClassTest()` 设置并读取 `internode_compression=dc` | 已有 distributed config coverage |
| `messaging_frame_codec_baseline` | `FramingTest.testRandomLZ4()`、`FramingTest.testRandomCrc()` | 已有 unit coverage |
| `messaging_error_reporting_exclusion_baseline` | `InternodeErrorExclusionTest.ignoreExcludedInternodeErrors()`、`testNoSpammingInvalidLegacyProtocolMagicException()` | 已有 distributed coverage |
| `messaging_tls_compression_mixed_version_gap` | `rg -n "internode_compression|server_encryption_options" test/distributed/org/apache/cassandra/distributed/upgrade` 当前无结果 | gap still open |

## 待补项

- 实现或取得 mixed-version dtest：rolling upgrade 中启用 `internode_encryption=all` 或 `dc`，并验证 upgraded/not-upgraded coordinators 都能建立 encrypted internode messaging。
- 实现或取得 mixed-version dtest：`internode_compression=dc` 与多 DC topology 下，升级前/中/后 messaging framing 仍按跨 DC LZ4、同 DC CRC 的预期工作。
- 实现或取得组合 dtest：TLS optional transitional mode + `internode_compression=dc` + `MixedModeMessageForwardTest` 风格的 cross-DC write/read，验证 handshake、forwarding 和 frame selection 同时成立。
- 若新增上述 dtest，更新 `research/tools/check-messaging-tls-compression-drift.py` 的 gap predicate 和本页 `messaging_tls_compression_mixed_version_gap` 状态。
