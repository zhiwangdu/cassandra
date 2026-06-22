# Module: Prepared Driver Integration Gap Matrix

## 范围

本模块补齐 prepared statement compatibility matrix 之后的测试覆盖视角：当前源码树里有哪些真实 driver/native protocol prepared runtime 覆盖，哪些只是 server-side codec/source 覆盖，哪些仍是完整 external driver/protocol integration matrix 的缺口。

结论：

- 当前仓库已有 DataStax Java driver 3.x 风格的 `com.datastax.driver.core` prepared runtime 覆盖。
- Java driver 覆盖重点是 reprepare、cache clear、旧/新 prepared id 行为、keyspace-sensitive hash、reconnect、batch keyspace 存储和部分 V4/V5 metadata 行为。
- Native protocol V3/V4/V5/V6 negotiation 有 Java driver/`SimpleClient` 覆盖，但不是完整 prepared statement scenario matrix。
- V5 PREPARE keyspace flag、V5 EXECUTE `resultMetadataId`、RESULT PREPARED `resultMetadataId` 和 metadata flag 主要由 source/codec/`SimpleClient` 单元测试覆盖。
- 当前源码树没有 Python/Go/Node/Rust driver prepared statement compatibility matrix，也没有每个 supported protocol version x 每个 driver x 每个 prepared scenario 的生成式集成测试。

## 覆盖场景

| 场景 ID | 当前状态 |
|---|---|
| `prepared_driver_java_reprepare_runtime` | Java driver dtests cover cache clear, host switch and driver-side reprepare. |
| `prepared_driver_keyspace_hash_runtime` | Java driver helper asserts with-keyspace and without-keyspace prepared ids. |
| `prepared_driver_mixed_version_runtime` | ByteBuddy-based dtests simulate old/new prepared behavior during mixed mode. |
| `prepared_driver_fuzz_runtime` | Fuzz dtests mix prepare/execute/cache clear/reload/reconnect/keyspace switch. |
| `prepared_driver_protocol_negotiation_boundary` | Protocol negotiation tests cover V3/V4/V5/V6 connection selection, but not prepared execution. |
| `prepared_driver_v4_v5_metadata_boundary` | Unit tests cover V4 vs V5 prepared metadata behavior after schema change and LWT metadata shape. |
| `prepared_driver_wire_codec_boundary` | Codec tests cover V5 PREPARE keyspace and prepared metadata serialization across supported protocol versions. |
| `prepared_driver_persistence_runtime` | Persistence tests cover `system.prepared_statements`, preload, eviction and timestamp ordering. |
| `prepared_driver_batch_keyspace_runtime` | Distributed batch prepared test covers fully qualified/unqualified batch storage under USE. |
| `prepared_driver_non_java_gap` | No Python/Go/Node/Rust prepared driver matrix is present in this source tree. |
| `prepared_driver_protocol_matrix_gap` | No generated V3/V4/V5/V6 x driver x scenario integration matrix is present. |

## Java Driver Runtime Coverage

| Surface | Covered behavior | Source |
|---|---|---|
| Reprepare after cache clear | `ReprepareTestBase.testReprepare()` prepares on one host, clears server caches, switches forced host and executes the same `PreparedStatement` to rely on driver reprepare. | `test/distributed/org/apache/cassandra/distributed/test/ReprepareTestBase.java:67-116` |
| Keyspace mismatch after USE | `testReprepareTwoKeyspaces()` prepares in one keyspace, switches to another keyspace and expects driver/server mismatch failure. | `test/distributed/org/apache/cassandra/distributed/test/ReprepareTestBase.java:119-164` |
| New behavior with multiple keyspaces | `ReprepareNewBehaviourTest.testUseWithMultipleKeyspaces()` checks `getQueryKeyspace()` and confirms two `SELECT * FROM tbl` prepared statements keep distinct keyspace semantics. | `test/distributed/org/apache/cassandra/distributed/test/ReprepareNewBehaviourTest.java:36-78` |
| Mixed old/new behavior | `ReprepareOldBehaviourTest` simulates pre-4.0.2 behavior on one node and new behavior on another, then executes prepared statements through forced hosts. | `test/distributed/org/apache/cassandra/distributed/test/ReprepareOldBehaviourTest.java:35-129` |
| New-behavior fuzz | `ReprepareFuzzTest` runs prepare/execute for qualified and unqualified statements, cache eviction, preload and reconnect while checking Java driver statement ids through `PreparedStatementHelper`. | `test/distributed/org/apache/cassandra/distributed/test/ReprepareFuzzTest.java:66-353` |
| Mixed-mode fuzz | `MixedModeFuzzTest` adds version bump, node selection, client bounce and old/new prepare override while tolerating expected id mismatch during upgrade. | `test/distributed/org/apache/cassandra/distributed/test/MixedModeFuzzTest.java:77-487` |
| Driver hash helper | `PreparedStatementHelper` reaches into Java driver prepared id metadata and asserts `MD5(keyspace + query)` vs `MD5(query)`. | `src/java/com/datastax/driver/core/PreparedStatementHelper.java:25-105` |
| Prepared batch storage | `PrepareBatchStatementsTest.testPreparedBatch()` verifies fully qualified and USE-dependent batch prepared statements are stored once or twice as expected. | `test/distributed/org/apache/cassandra/distributed/test/PrepareBatchStatementsTest.java:41-100` |

## Protocol And Codec Coverage

| Surface | Covered behavior | Source |
|---|---|---|
| Java driver protocol negotiation | `ProtocolNegotiationTest` checks V3/V4/V5, V6 beta, old unsupported versions, stream ids and message version mismatch. It executes simple queries, not prepared statements. | `test/unit/org/apache/cassandra/transport/ProtocolNegotiationTest.java:70-239` |
| Driver utility protocol pinning | `JavaDriverUtils.create(..., ProtocolVersion)` can set `withProtocolVersion(version)`, but it is a helper rather than a prepared matrix. | `test/distributed/org/apache/cassandra/distributed/test/JavaDriverUtils.java:32-58` |
| V4/V5 prepared metadata after ALTER | `PreparedStatementsTest.testInvalidatePreparedStatementOnAlterV4/V5()` verifies V5 metadata change support and V4 stale metadata behavior. | `test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java:91-149` |
| V5 reconnect and beta driver path | `PreparedStatementsTest.testStatementRePreparationOnReconnect()` reconnects a Java driver cluster with beta protocol allowed and prepares/executess statements again. | `test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java:200-239` |
| V5 result metadata/LWT flag behavior | `testMetadataFlagsWithLWTs()` uses `SimpleClient` to execute prepared statements and checks `METADATA_CHANGED` vs regular metadata for LWT/select paths. | `test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java:276-465` |
| LWT result shape via Java driver | `testPrepareWithLWT()` and `testPrepareWithBatchLWT()` cover V4/V5 Java driver prepared LWT result column changes. | `test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java:467-583` |
| V5 PREPARE keyspace codec | `PrepareMessageTest.testEncodeThenDecode()` encodes and decodes a V5 `PrepareMessage` with keyspace. | `test/unit/org/apache/cassandra/transport/messages/PrepareMessageTest.java:27-40` |
| Prepared metadata serde | `SerDeserTest.preparedMetadataSerializationTest()` iterates `ProtocolVersion.SUPPORTED`, treating V3 partition-key bind indexes differently from V4+. | `test/unit/org/apache/cassandra/transport/SerDeserTest.java:312-354` |

## Persistence And Operational Coverage

| Surface | Covered behavior | Source |
|---|---|---|
| Persistence and reload | `PstmtPersistenceTest.testCachedPreparedStatements()` validates memory/disk counts, preload and drop-keyspace cleanup for `system.prepared_statements`. | `test/unit/org/apache/cassandra/cql3/PstmtPersistenceTest.java:83-150` |
| Eviction and async deletion | `testPstmtInvalidation()` and `testAsyncPstmtInvalidation()` cover cache eviction, table row count parity and delete timestamp ordering. | `test/unit/org/apache/cassandra/cql3/PstmtPersistenceTest.java:170-280` |
| Preload paging and leak guard | `testPreloadPreparedStatements()` and `testPreloadPreparedStatementsUntilCacheFull()` cover page size and early return once the persisted table is much larger than cache capacity. | `test/unit/org/apache/cassandra/cql3/PstmtPersistenceTest.java:282-390` |

## Gap Matrix

| Desired external matrix row | Current source-tree status | Gap |
|---|---|---|
| Java driver x V3/V4/V5/V6 x prepare/execute/reprepare | Partial. Protocol negotiation covers versions; prepared runtime covers Java driver but not as an enumerated protocol matrix. | Need generated runtime scenarios per protocol version. |
| Java driver x V5 keyspace flag | Partial. V5 keyspace flag codec is covered; Java driver 3.x does not expose a full scenario matrix for the server-side flag. | Need explicit runtime test if driver API supports the flag path. |
| Java driver x result metadata id after ALTER/LWT | Partial. V4/V5 and `SimpleClient` tests cover the server behavior. | Need explicit driver protocol matrix for metadata cache behavior. |
| Java driver x old/new behavior rolling upgrade | Covered for source-level old/new behavior simulation and Java driver reprepare. | Keep existing dtests and update if driver changes. |
| Python driver x supported protocols | Missing. | Need external driver harness. |
| Go driver x supported protocols | Missing. | Need external driver harness. |
| Node driver x supported protocols | Missing. | Need external driver harness. |
| Rust driver x supported protocols | Missing. | Need external driver harness. |
| Cross-driver UNPREPARED handling | Partial for Java driver reprepare/cache clear; missing for non-Java drivers. | Need cross-driver reprepare assertions. |
| Cross-driver schema invalidation metadata refresh | Partial for Java driver/SimpleClient; missing for non-Java drivers. | Need driver-specific metadata cache assertions. |

## 设计目标

- Preserve the existing source-level prepared compatibility baseline while making runtime driver coverage explicit.
- Avoid treating Java driver dtests as proof of every external driver and every protocol version.
- Give future test authors a concrete checklist for a complete external-driver matrix.

## 解决的问题

- The earlier prepared matrix documented protocol/source behavior but left the external driver item as a single broad gap.
- Operators care about whether drivers reprepare after `UNPREPARED`, schema invalidation and reconnect; those behaviors are partly tested for Java driver and should be visible.
- Protocol version coverage is easy to overstate because negotiation tests and prepared tests live in different files.

## 设计取舍

- The current tests use ByteBuddy to simulate old/new server behavior rather than launching real mixed-version binaries. This keeps the test local to the source tree but is not a full upgrade rehearsal.
- `PreparedStatementHelper` lives in the Java driver package to access package-private prepared id internals. This is test-oriented coupling and should not be treated as production API.
- `SimpleClient` gives precise protocol-frame control for metadata flags, but it is not an external driver.
- Non-Java drivers are intentionally represented as gaps until their harnesses exist in the repository.

## 核心类

| 类 | 作用 |
|---|---|
| `ReprepareTestBase` | Shared Java driver reprepare/cache-clear/keyspace-mismatch harness. |
| `ReprepareNewBehaviourTest` | New prepared id behavior and multiple-keyspace runtime tests. |
| `ReprepareOldBehaviourTest` | Old/new mixed behavior simulation for reprepare. |
| `ReprepareFuzzTest` | New-behavior fuzzing across prepare/execute/cache/reload/reconnect. |
| `MixedModeFuzzTest` | Mixed-mode fuzzing with version bump and client bounce. |
| `PreparedStatementHelper` | Java driver prepared id hash assertions. |
| `PreparedStatementsTest` | Unit-level Java driver and `SimpleClient` prepared metadata/invalidation coverage. |
| `PstmtPersistenceTest` | Prepared cache persistence, eviction and preload tests. |
| `ProtocolNegotiationTest` | Native protocol negotiation boundary, not a prepared matrix. |

## 核心接口

- Java driver `Session.prepare()` and `Session.execute(prepared.bind(...))` exercise driver-side prepare/execute/reprepare.
- `ForceHostLoadBalancingPolicy.newQueryPlan()` forces a prepared statement to specific nodes during cache clear and mixed behavior tests.
- `PreparedStatementHelper.assertHashWithoutKeyspace()` and `assertHashWithKeyspace()` assert the returned prepared id shape.
- `QueryProcessor.clearPreparedStatementsCache()` and `QueryProcessor.preloadPreparedStatements()` drive server-side invalidation/reload conditions.
- `SimpleClient.prepare()` and `SimpleClient.executePrepared()` exercise protocol-level metadata flags without an external driver.

## 生命周期

```text
Java driver runtime reprepare test
  -> Session.prepare(query)
  -> Session.execute(boundStatement)
  -> QueryProcessor.clearPreparedStatementsCache() on one or more nodes
  -> forced host switch or reconnect
  -> Session.execute(boundStatement)
  -> Java driver receives UNPREPARED and re-prepares transparently
```

```text
Mixed old/new behavior fuzz
  -> start two-node in-JVM cluster with ByteBuddy prepare behavior override
  -> prepare qualified/unqualified statements in Java driver sessions
  -> optionally bump version to 4.0.2 behavior
  -> execute through selected host or bounce client
  -> accept expected id mismatch only during mixed behavior window
```

```text
Metadata flag unit path
  -> SimpleClient.prepare(select/lwt)
  -> SimpleClient.executePrepared(resultMetadataId)
  -> schema change or LWT result-shape change
  -> assert GLOBAL_TABLES_SPEC, METADATA_CHANGED or full metadata as expected
```

## 调用链

- Java driver prepare/reprepare: `Cluster.builder()` -> `Session.prepare()` -> native `PREPARE` -> `QueryProcessor.prepare()` -> `PreparedStatement` id stored in driver -> `Session.execute(bound)` -> native `EXECUTE` -> possible `UNPREPARED` -> driver reprepare。
- Hash assertion path: Java driver `PreparedStatement.getPreparedId().boundValuesMetadata.id` -> `PreparedStatementHelper.computeId(query, keyspace)` -> compare with returned id。
- Protocol negotiation boundary: `Cluster.Builder.withProtocolVersion()` or beta allowance -> `Session.connect()` -> simple query execution; no prepared statement in that test.

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| `force_new_prepared_statement_behaviour` | `src/java/org/apache/cassandra/config/Config.java:119`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4974-4984` | Operational override for new prepared id behavior; dtests mostly simulate behavior with ByteBuddy. |
| `prepared_statements_cache_size` | `src/java/org/apache/cassandra/config/Config.java:581-585`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:795-804` | Controls cache capacity that persistence/eviction tests exercise. |

## Metrics

This matrix does not add new metrics beyond prepared statement metrics documented in `research/module-prepared-statement-compatibility-matrix.md`:

- `PreparedStatementsExecuted`
- `PreparedStatementsEvicted`
- `PreparedStatementsCount`
- `PreparedStatementsRatio`

The runtime driver tests mainly verify correctness; `PstmtPersistenceTest` reads eviction metrics through `QueryProcessor.metrics.preparedStatementsEvicted`.

## 日志

- Mixed-mode fuzz logs expected id mismatch and version bump progress in `MixedModeFuzzTest`.
- Server logs for prepared cache eviction, dangerous keyspace option and keyspace mismatch remain documented in `research/module-prepared-statement-compatibility-matrix.md`.

## 运维关注点

- Java driver prepared success in these tests does not prove Python/Go/Node/Rust behavior.
- Protocol negotiation success does not prove prepared metadata cache behavior for that protocol.
- Reprepare correctness depends on drivers handling `UNPREPARED` and on applications not generating unbounded unique prepared CQL.
- During rolling upgrades, statement id behavior still needs driver-aware validation if clients pin old protocol versions or use keyspace-sensitive unqualified CQL.

## 性能瓶颈

- Fuzz tests intentionally exercise cache clear/preload/reconnect behavior, but they are not load tests for high-cardinality prepared CQL.
- A complete external driver matrix should track prepare rate, reprepare rate, metadata resend rate and cache eviction metrics under each driver/protocol pair.

## 常见故障

- Driver reports id mismatch during rolling behavior window: compare old/new prepared id behavior and whether keyspace was part of the statement id.
- Java driver transparently reprepares but another driver fails on `UNPREPARED`: add that driver to the missing matrix before declaring compatibility.
- Metadata stale after `ALTER TABLE`: check whether the client used V5 result metadata id or a pre-V5 protocol path.
- Statement prepared in one keyspace executed in another: unqualified CQL retains keyspace-sensitive semantics and may fail with keyspace mismatch.

## 测试用例

- `python3 research/tools/check-prepared-driver-integration-drift.py`：source-only drift check for this matrix.
- `test/distributed/org/apache/cassandra/distributed/test/ReprepareTestBase.java:67-164`
- `test/distributed/org/apache/cassandra/distributed/test/ReprepareNewBehaviourTest.java:36-92`
- `test/distributed/org/apache/cassandra/distributed/test/ReprepareOldBehaviourTest.java:35-129`
- `test/distributed/org/apache/cassandra/distributed/test/ReprepareFuzzTest.java:66-353`
- `test/distributed/org/apache/cassandra/distributed/test/MixedModeFuzzTest.java:77-487`
- `src/java/com/datastax/driver/core/PreparedStatementHelper.java:25-105`
- `test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java:58-583`
- `test/unit/org/apache/cassandra/cql3/PstmtPersistenceTest.java:83-390`
- `test/unit/org/apache/cassandra/transport/ProtocolNegotiationTest.java:70-239`
- `test/unit/org/apache/cassandra/transport/messages/PrepareMessageTest.java:27-40`
- `test/unit/org/apache/cassandra/transport/SerDeserTest.java:312-354`
- `test/distributed/org/apache/cassandra/distributed/test/PrepareBatchStatementsTest.java:41-100`

## 当前缺口

- Build a generated matrix for Java driver x V3/V4/V5/V6 x prepare/execute/reprepare/UNPREPARED/schema invalidation/result metadata id.
- Add Python/Go/Node/Rust driver harnesses if those drivers are part of the supported external compatibility target.
- Add runtime assertions for V5 PREPARE keyspace flag if the driver surface exposes it.
- Promote the matrix into CI once external driver dependencies and cluster startup cost are acceptable.
