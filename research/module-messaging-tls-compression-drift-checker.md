# Module: Messaging TLS Compression Drift Checker

## 范围

本模块记录 `research/tools/check-messaging-tls-compression-drift.py` 的用途、输入、输出和维护方式。它覆盖 internode TLS optional/strict、handshake framing、`internode_compression` 策略、现有测试锚点以及 mixed-version upgrade gap 的 source-only drift check。

## 设计目标

- 用源码 token 保护 `module-messaging-tls-compression-compatibility.md` 的关键结论：TLS policy branch、required encryption gate、outbound SSL insertion、handshake version/framing、LZ4/CRC/unprotected frame selection 和 compression policy。
- 用测试 token 保护现有覆盖边界：TLS optional/strict/protocol/cipher/cross-DC/mTLS distributed tests、compression policy unit tests、config propagation test 和 handshake error-reporting tests。
- 用 upgrade 目录的 absence predicate 保护 `messaging_tls_compression_mixed_version_gap`：只要 `test/distributed/org/apache/cassandra/distributed/upgrade` 出现 `internode_compression` 或 `server_encryption_options`，checker 就失败，要求更新研究结论；当前状态是 gap still open。
- 保持 source-only：不编译 Cassandra、不启动 in-JVM cluster、不打开 sockets。

## 解决的问题

- `module-gossip-messaging-deep-dive.md` 已覆盖 Netty handshake，但 mixed-version/TLS/compression gap 没有独立 checker；新增 checker 将第五轮 Messaging gap 固定为可验证状态。
- TLS tests 和 compression tests 分散在 `test/distributed` 与 `test/unit`；checker 把这些锚点聚合到一个可维护清单。
- 缺口是“当前没有组合 upgrade test”，不能只靠人工记忆；checker 的 absence predicate 会在新增测试后提醒把 gap 改成 coverage baseline。

## 设计取舍

- checker 不解析 Java AST，只检查关键 token；这与其他 research drift checker 保持一致，低成本且足以发现源码/测试/文档迁移。
- mixed-version gap 只扫描 `test/distributed/org/apache/cassandra/distributed/upgrade`，避免被非升级类如 `InternodeEncryptionOptionsTest` 或 `JVMDTestTest` 误判为 rolling-upgrade coverage。
- gap predicate 使用 `internode_compression` 或 `server_encryption_options` 任一 token 触发失败；如果未来 upgrade test 只覆盖其中之一，也应人工更新本模块而不是静默通过。
- checker 不验证真实 TLS negotiation、certificate chain、frame bytes 或 network behavior；这些仍应由 Java tests/dtests 覆盖。

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-messaging-tls-compression-drift.py` | Source/test/doc/gap drift checker。 |
| `EncryptionOptions` | TLS policy 和 internode encryption semantics 的源码事实来源。 |
| `InboundConnectionInitiator` | inbound optional/reject/strict TLS、required encryption 和 frame decoder 事实来源。 |
| `OutboundConnectionInitiator` | outbound SSL handler、server authentication、handshake Accept 和 frame encoder 事实来源。 |
| `OutboundConnectionSettings` | `internode_compression` 到 `Framing.LZ4` / `Framing.CRC` 的事实来源。 |
| `HandshakeProtocol` | Initiate/Accept version/framing/CRC wire contract 的事实来源。 |

## 核心接口

- `check_required_tokens()`：按文件检查 source/test/doc token 是否存在。
- `scan_upgrade_gap()`：扫描 upgrade test tree，确认当前没有 `internode_compression` / `server_encryption_options` mixed-version anchors。
- `check()`：合并 token 和 gap 结果，输出 `ok`、`check_count`、`missing`、`unexpected_upgrade_tokens`。
- `--json`：输出机器可读结果，供后续 CI artifact 或本地分析。

## 核心数据结构

| 数据结构 | 字段 | 语义 |
|---|---|---|
| `TokenCheck` | `path`, `token`, `kind` | 单个 source/test/doc token 检查结果。 |
| `SOURCE_TOKEN_CHECKS` | path -> tokens | 源码锚点，例如 `RejectSslHandler`、`OptionalSslHandler`、`FrameDecoderLZ4.fast`、`shouldCompressConnection`。 |
| `TEST_TOKEN_CHECKS` | path -> tokens | 现有 Java test anchors。 |
| `DOC_TOKEN_CHECKS` | path -> tokens | 研究文档和索引的场景 ID / 脚本名覆盖。 |
| `GAP_UPGRADE_TOKENS` | token list | 当前不应出现在 upgrade tests 的 gap trigger tokens。 |

## 生命周期

本地运行：

```text
developer changes internode TLS/compression source or tests
  -> python3 research/tools/check-messaging-tls-compression-drift.py
  -> checker validates source/test/doc tokens
  -> checker scans upgrade tests for gap trigger tokens
  -> missing source/test/doc tokens or new upgrade anchors fail the run
```

研究维护：

```text
new mixed-version TLS/compression dtest appears
  -> checker fails with unexpected upgrade token path
  -> update module-messaging-tls-compression-compatibility.md
  -> change messaging_tls_compression_mixed_version_gap from open gap to coverage baseline
  -> adjust checker gap predicate to require the new dtest tokens
```

## 调用链

```text
main()
  -> check()
     -> check_required_tokens(SOURCE_TOKEN_CHECKS)
     -> check_required_tokens(TEST_TOKEN_CHECKS)
     -> check_required_tokens(DOC_TOKEN_CHECKS)
     -> scan_upgrade_gap()
  -> print OK or drift details
  -> exit 0/1/2
```

## 配置项

- Checker path constants are embedded at script top and are intentionally repository-relative.
- `GAP_UPGRADE_DIR` is fixed to `test/distributed/org/apache/cassandra/distributed/upgrade`.
- `GAP_UPGRADE_TOKENS` currently contains `internode_compression` and `server_encryption_options`.
- If the upgrade package is reorganized, update the path before trusting the gap result.

## Metrics

- Runtime output includes the total check count.
- `--json` includes missing token entries and unexpected upgrade token entries.
- Current success should print `OK messaging TLS/compression drift checks passed`.

## 日志

- 成功：prints the number of source/test/doc/gap checks.
- Missing token：prints `Missing required tokens:` followed by kind, path and token.
- Gap closed/new coverage found：prints `Unexpected upgrade mixed-version anchors found:` with path and token.
- Read/scan errors return exit code 2.

## 运维关注点

- Checker 是 research 维护工具，不替代 `InternodeEncryptionOptionsTest`、`InternodeEncryptionEnforcementTest`、`OutboundConnectionSettingsTest`、`FramingTest` 或真实 upgrade dtests。
- 如果新增的 upgrade test 只包含 `server_encryption_options` 但不含 `internode_compression`，仍应更新本页，因为 TLS mixed-version gap 至少部分关闭。
- 如果新增 compression-only upgrade test 只含 `internode_compression`，同样需要把缺口拆分为 TLS 和 compression 两个状态。
- 如果 source rename 只是重构而行为不变，更新 token anchors 和 `module-messaging-tls-compression-compatibility.md` 的 path/line references together。

## 性能瓶颈

- 脚本只读取固定 source/test/doc 文件并扫描一个 test directory，成本是文本 IO。
- Upgrade gap scan 会遍历 `*.java`，当前目录规模较小，运行成本可忽略。

## 常见故障

- `Missing required tokens` in source：TLS/compression implementation moved or semantics changed; re-read source before editing docs.
- `Missing required tokens` in docs：new module or README/source-map index lost a scenario id or script reference.
- `Unexpected upgrade mixed-version anchors found`：mixed-version coverage may have appeared; update the research gap and checker predicate.
- checker passes but Java tests fail：说明 source/doc anchors仍存在，但 runtime behavior changed; use Java test output as higher-priority signal.

## 测试用例

- `python3 research/tools/check-messaging-tls-compression-drift.py`
- `python3 research/tools/check-messaging-tls-compression-drift.py --json`
- `python3 -m py_compile research/tools/check-messaging-tls-compression-drift.py`
- Full research suite:

```bash
for f in $(find research/tools -maxdepth 1 -type f -name 'check-*.py' | sort); do python3 "$f"; done
```
