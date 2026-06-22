# Module: Prepared Driver Integration Drift Checker

## 范围

`research/tools/check-prepared-driver-integration-drift.py` 是 source-only drift check，用来保护 `research/module-prepared-driver-integration-gap-matrix.md` 和 `research/module-prepared-driver-integration-drift-checker.md`。它验证 Java driver prepared runtime 覆盖、protocol negotiation boundary、prepared metadata/codecs、persistence tests、batch keyspace tests 和非 Java driver 缺口在 research 文档中保持同步。

当前基线：

- Java driver runtime coverage uses `com.datastax.driver.core.PreparedStatement` and `Session.prepare()`.
- Reprepare dtests cover cache clearing, forced host switch, keyspace mismatch and old/new behavior simulation.
- Fuzz dtests cover qualified/unqualified prepare, execute, cache clear, reload from `system.prepared_statements`, reconnect/client bounce and mixed behavior.
- `ProtocolNegotiationTest` covers protocol selection V3/V4/V5/V6 but intentionally does not prepare statements.
- `PreparedStatementsTest` covers V4/V5 metadata behavior, reconnect and `SimpleClient` metadata flags.
- No Python/Go/Node/Rust prepared driver matrix is present in the test tree.

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `prepared_driver_java_reprepare_runtime` | Java driver reprepare runtime dtest anchors. |
| `prepared_driver_keyspace_hash_runtime` | Java driver prepared id hash helper and dtest usage. |
| `prepared_driver_mixed_version_runtime` | ByteBuddy old/new behavior and version bump coverage. |
| `prepared_driver_fuzz_runtime` | Fuzz actions for cache clear, reload, reconnect and keyspace switching. |
| `prepared_driver_protocol_negotiation_boundary` | Protocol negotiation exists but is not prepared execution. |
| `prepared_driver_v4_v5_metadata_boundary` | V4/V5 metadata and LWT prepared behavior anchors. |
| `prepared_driver_wire_codec_boundary` | V5 prepare keyspace and prepared metadata serde anchors. |
| `prepared_driver_persistence_runtime` | Persistence/preload/eviction anchors. |
| `prepared_driver_batch_keyspace_runtime` | Prepared batch keyspace storage anchors. |
| `prepared_driver_non_java_gap` | Non-Java driver matrix remains absent and documented. |
| `prepared_driver_protocol_matrix_gap` | Generated protocol x driver x scenario matrix remains absent and documented. |

## 设计目标

- Fail when Java driver prepared runtime tests move or lose the behavior the research claims.
- Fail when protocol negotiation turns into prepared coverage, or when new non-Java driver tests appear, so the matrix can be updated.
- Keep the remaining gap precise: partial Java driver runtime coverage exists, complete cross-driver protocol coverage does not.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-prepared-driver-integration-drift.py` | Source/doc drift checker. |
| `ReprepareTestBase` | Shared Java driver reprepare harness. |
| `ReprepareNewBehaviourTest` | New behavior and multiple keyspace coverage. |
| `ReprepareOldBehaviourTest` | Mixed old/new behavior coverage. |
| `ReprepareFuzzTest` | New-behavior prepared fuzz coverage. |
| `MixedModeFuzzTest` | Mixed-mode prepared fuzz coverage. |
| `PreparedStatementHelper` | Java driver prepared id hash helper. |
| `PreparedStatementsTest` | Metadata/reconnect/LWT prepared coverage. |
| `PstmtPersistenceTest` | Persistence/preload/eviction coverage. |
| `ProtocolNegotiationTest` | Protocol boundary without prepared execution. |

## 运维关注点

- A green checker does not prove cross-driver compatibility; it proves the current coverage map and remaining gaps are documented.
- When a non-Java driver harness lands, the checker should be updated to move `prepared_driver_non_java_gap` from expected gap to covered scenario.
- When a generated protocol matrix lands, the checker should stop expecting `prepared_driver_protocol_matrix_gap`.

## 常见故障

- `source token contract ... ReprepareTestBase.java` fails: Java driver reprepare harness changed.
- `protocol negotiation remains non-prepared boundary` fails: negotiation tests now include prepared execution and the matrix should classify that coverage.
- `non-Java prepared driver matrix remains absent` fails: a new external driver test appeared and docs/checker need to name it.
- `doc token ...` fails: research docs are missing a scenario, path or gap token.

## 测试用例

- `python3 research/tools/check-prepared-driver-integration-drift.py`。
- `python3 research/tools/check-prepared-driver-integration-drift.py --json`。
- Related Java anchors: `ReprepareTestBase.java`、`ReprepareNewBehaviourTest.java`、`ReprepareOldBehaviourTest.java`、`ReprepareFuzzTest.java`、`MixedModeFuzzTest.java`、`PreparedStatementHelper.java`、`PreparedStatementsTest.java`、`PstmtPersistenceTest.java`、`ProtocolNegotiationTest.java`、`PrepareMessageTest.java`、`SerDeserTest.java`、`PrepareBatchStatementsTest.java`。
