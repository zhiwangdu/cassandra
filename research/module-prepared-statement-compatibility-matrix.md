# Module: Prepared Statement Compatibility Matrix

## 范围

本模块覆盖 CQL prepared statement 在 native protocol、`QueryProcessor`、schema invalidation、persistence 和 metrics 之间的兼容性边界。它补齐 Schema/CQL/Auth/Native 研究中留下的 "跨 driver/protocol prepared compatibility matrix" 的源码侧基线；真实跨 driver 运行矩阵仍需后续接入外部 driver。当前 Java driver runtime 覆盖、protocol boundary 和 non-Java gap 已单独展开在 `research/module-prepared-driver-integration-gap-matrix.md`，并由 `research/tools/check-prepared-driver-integration-drift.py` 保护。

当前基线：

- `PREPARE` request V5+ 带 32-bit flags，bit 0 表示 request body 包含 keyspace；V4 及以下只包含 query string。
- `EXECUTE` request V5+ 在 statement id 后携带 `resultMetadataId`；V4 及以下不带该字段。
- `RESULT PREPARED` response V5+ 在 statement id 后携带 `resultMetadataId`；所有当前 supported versions 都携带 prepared metadata 和 result metadata。
- `QueryProcessor.prepare()` 维护 4 种 statement id 组合：fully qualified/unqualified query x with/without keyspace。
- prepared statement id 使用 `MD5Digest.compute(keyspace + queryString)` 或 `MD5Digest.compute(queryString)`。
- rolling upgrade gate 是 `NEW_PREPARED_STATEMENT_BEHAVIOUR_SINCE_40 = 4.0.2` 和 `force_new_prepared_statement_behaviour`。
- `system.prepared_statements` 当前列为 `prepared_id`、`logged_keyspace`、`query_string`。
- `ResultSet.Flag` bit order 是 `GLOBAL_TABLES_SPEC`、`HAS_MORE_PAGES`、`NO_METADATA`、`METADATA_CHANGED`。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `prepared_prepare_v5_keyspace_flag` | `PrepareMessage` V5+ prepare flags/keyspace decode/encode 和 `cloneWithKeyspaceIfSet()`。 |
| `prepared_execute_v5_result_metadata_id` | `ExecuteMessage` V5+ request result metadata id，以及 metadata changed/skip metadata 判断。 |
| `prepared_result_prepared_v5_result_metadata_id` | `ResultMessage.Prepared` V5+ response result metadata id。 |
| `prepared_id_four_hash_matrix` | fully-qualified/unqualified x with/without keyspace 的 4-hash compatibility matrix。 |
| `prepared_new_behaviour_upgrade_gate` | `4.0.2` min-version gate 和 `force_new_prepared_statement_behaviour` override。 |
| `prepared_cache_persistence_contract` | Caffeine cache、`system.prepared_statements` persistence、preload page size 和 eviction delete。 |
| `prepared_schema_invalidation_contract` | table/keyspace/function/aggregate schema changes remove affected prepared statements。 |
| `prepared_metadata_flag_contract` | `ResultSet.Flag` bit order、V4 partition-key bind indexes、V5 `METADATA_CHANGED` id field。 |
| `prepared_metrics_and_logs_contract` | CQL prepared metrics, cache eviction warning and keyspace misuse warning。 |
| `prepared_test_coverage_surface` | unit/distributed tests that cover prepared invalidation, metadata flags, persistence and batch keyspace cases。 |
| `prepared_external_driver_gap` | Source/test baseline exists, but complete cross-driver protocol matrix is still missing。 |

## Protocol Compatibility Matrix

| Surface | V3/V4 behavior | V5/V6 behavior | Source |
|---|---|---|---|
| `PREPARE` body | `long string query` only. | `long string query` + `uint flags`; if bit 0 is set, read `keyspace` string. | `src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:49-66` |
| `PREPARE` keyspace application | Uses current connection keyspace. | `ClientState.cloneWithKeyspaceIfSet(keyspace)` can override state for preparation. | `src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:118-129` |
| `RESULT PREPARED` | statement id + prepared metadata + result metadata. | statement id + result metadata id + prepared metadata + result metadata. | `src/java/org/apache/cassandra/transport/messages/ResultMessage.java:211-258` |
| `EXECUTE` body | statement id + query options. | statement id + result metadata id + query options. | `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:56-102` |
| result metadata cache | If `skipMetadata` and prepared cached `resultMetadataId` equals current metadata id, set `NO_METADATA`. | For non-LWT statements, compare client-provided `resultMetadataId` to current id; set `METADATA_CHANGED` or `NO_METADATA`. | `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:173-200` |
| LWT result metadata | LWT can change result shape per execution; metadata is sent rather than cached. | Same, and V5 avoids setting metadata changed for LWTs. | `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:179-192` |
| prepared metadata partition key indexes | V3 encoding omits partition-key bind indexes. | V4+ encodes partition-key bind indexes when global table spec applies. | `src/java/org/apache/cassandra/cql3/ResultSet.java:583-676` |

## Statement ID Matrix

`QueryProcessor.prepare()` explicitly handles 4 digest shapes, because older clusters and clients used different keyspace concatenation behavior:

| Query shape | Client keyspace | Digest stored | Digest returned with new behavior | Legacy/rolling behavior |
|---|---|---|---|---|
| Fully qualified CQL, e.g. `SELECT * FROM ks.t` | null | `computeId(query, null)` | without keyspace | without keyspace |
| Fully qualified CQL | set | both `computeId(query, null)` and `computeId(query, keyspace)` | without keyspace | with keyspace if available |
| Unqualified CQL, e.g. `SELECT * FROM t` | set | both `computeId(query, keyspace)` and `computeId(query, null)` | with keyspace | without keyspace |
| Unqualified CQL | null | effectively ambiguous; source stores with raw keyspace input and warns on misuse | with keyspace only if available | without keyspace |

The digest function is `keyspace == null ? queryString : keyspace + queryString`, then `MD5Digest.compute(...)`; see `src/java/org/apache/cassandra/cql3/QueryProcessor.java:786-790`. The new behavior is enabled when all gossiped versions are at least `4.0.2`, or when `force_new_prepared_statement_behaviour` is true; see `src/java/org/apache/cassandra/cql3/QueryProcessor.java:689-706` and `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4974-4984`.

## 设计目标

- Preserve statement id compatibility during rolling upgrades from pre-4.0.2 behavior.
- Let V5+ drivers cache result metadata by sending `resultMetadataId` on execute and receiving `METADATA_CHANGED` only when needed.
- Keep V3/V4 drivers functional even without the V5 result metadata id field.
- Persist prepared statements across restart while bounding preload cost and cache size.
- Invalidate prepared statements when schema/function changes make the prepared plan stale.

## 解决的问题

- Drivers may keep statement ids across reconnect. Cassandra stores both with-keyspace and without-keyspace entries in specific cases to let old and new digest behavior coexist.
- `SELECT *` prepared metadata can change after `ALTER TABLE`; V5+ gives drivers an explicit metadata id comparison path.
- LWT result shape is data-dependent; server intentionally sends metadata rather than letting drivers reuse stale metadata.
- Prepared statement cache leaks or high-cardinality prepare usage can make startup expensive, so preload stops after roughly 110% of cache bytes.

## 设计取舍

- The rolling-upgrade compatibility path deliberately stores duplicate rows for some statements. That costs cache/table space but avoids breaking old clients during upgrades.
- V5 keyspace-in-prepare is supported but logged as dangerous, because setting keyspace through query options can surprise operators and application owners.
- V5 metadata id comparison is not used for LWT statements, because LWT result metadata may vary between applied and not-applied paths.
- `system.prepared_statements` persists only id, logged keyspace and query string; it rebuilds `Prepared` objects by parsing on preload.

## 核心类

| 类 | 作用 |
|---|---|
| `PrepareMessage` | Decode/encode PREPARE body, V5+ keyspace flag, call `QueryHandler.prepare()` and notify `QueryEvents`，见 `src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:47-129`。 |
| `ExecuteMessage` | Decode statement id/result metadata id/query options, fetch prepared plan, execute and set result metadata flags，见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:54-205`。 |
| `QueryProcessor` | Prepared cache, statement id selection, preload, persistence, invalidation listener and metrics integration，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:86-205`、`src/java/org/apache/cassandra/cql3/QueryProcessor.java:682-838`、`src/java/org/apache/cassandra/cql3/QueryProcessor.java:975-1134`。 |
| `QueryHandler.Prepared` | Runtime prepared plan container: statement, result metadata id, timestamp, raw CQL, keyspace and fully-qualified flag，见 `src/java/org/apache/cassandra/cql3/QueryHandler.java:60-92`。 |
| `ResultMessage.Prepared` | Wire response body for prepared statement id, result metadata id and metadata，见 `src/java/org/apache/cassandra/transport/messages/ResultMessage.java:211-290`。 |
| `ResultSet.PreparedMetadata` / `ResultSet.ResultMetadata` | Bind variable metadata, result metadata, metadata id and metadata flags，见 `src/java/org/apache/cassandra/cql3/ResultSet.java:300-330`、`src/java/org/apache/cassandra/cql3/ResultSet.java:369-480`、`src/java/org/apache/cassandra/cql3/ResultSet.java:503-732`。 |
| `SystemKeyspace` | `system.prepared_statements` table and persistence/preload helpers，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:447-455` 和 `src/java/org/apache/cassandra/db/SystemKeyspace.java:1874-1938`。 |

## 核心接口

- `QueryHandler.prepare(String, ClientState, Map<String, ByteBuffer>)`：transport-independent prepare contract。
- `QueryHandler.getPrepared(MD5Digest)`：execute path lookup; missing id becomes `PreparedQueryNotFoundException` / `UNPREPARED` error.
- `QueryProcessor.prepare(String, ClientState)`：source of the 4-hash compatibility matrix.
- `QueryProcessor.storePreparedStatement(String, String, Prepared)`：persist/cache a digest shape.
- `SystemKeyspace.writePreparedStatement()` / `loadPreparedStatements()` / `removePreparedStatement()`：on-disk lifecycle.
- `ResultSet.ResultMetadata.getResultMetadataId()` / `setMetadataChanged()` / `setSkipMetadata()`：driver metadata cache protocol.

## 核心数据结构

- `preparedStatements`: Caffeine `Cache<MD5Digest, Prepared>` with maximum weight from `prepared_statements_cache_size`.
- `internalStatements`: internal CQL prepared cache keyed by query string.
- `system.prepared_statements`: `prepared_id blob` primary key, `logged_keyspace text`, `query_string text`.
- `ResultSet.Flag`: `GLOBAL_TABLES_SPEC`、`HAS_MORE_PAGES`、`NO_METADATA`、`METADATA_CHANGED`; order is the wire bit order.
- `ResultSet.PreparedMetadata.partitionKeyBindIndexes`: V4+ partition-key bind indexes for prepared metadata.

## 生命周期

```text
PREPARE frame
  -> PrepareMessage.decode(query, optional V5 keyspace)
  -> ClientState.cloneWithKeyspaceIfSet(keyspace)
  -> QueryProcessor.prepare(query, clientState)
     -> compute hashWithoutKeyspace / hashWithKeyspace
     -> choose legacy or new behavior
     -> parseAndPrepare()
     -> storePreparedStatement() one or two times
     -> SystemKeyspace.writePreparedStatement()
  -> ResultMessage.Prepared(statementId, resultMetadataId, preparedMetadata, resultMetadata)

EXECUTE frame
  -> ExecuteMessage.decode(statementId, optional V5 resultMetadataId, QueryOptions)
  -> QueryHandler.getPrepared(statementId)
  -> QueryOptions.prepare(bindVariables)
  -> QueryHandler.processPrepared(...)
  -> ResultMessage.Rows metadata flags updated for V5 or pre-V5 skip metadata
```

Restart/preload:

```text
Cassandra startup
  -> QueryProcessor.preloadPreparedStatements()
  -> SystemKeyspace.loadPreparedStatements(pageSize=5000)
  -> parseAndPrepare(query, loaded keyspace)
  -> preparedStatements.put(id, prepared)
  -> if not fully qualified, also load computeId(query, null)
  -> stop early if loaded bytes exceed 110% cache size
```

Schema invalidation:

```text
Schema change listener
  -> onAlterTable/onDropTable/onDropKeyspace/onAlterFunction/onDropFunction/onAlterAggregate
  -> shouldInvalidate(ks, table, statement)
  -> SystemKeyspace.removePreparedStatement(id)
  -> remove from preparedStatements/internalStatements
  -> next EXECUTE gets UNPREPARED and driver should reprepare
```

## 调用链

- PREPARE path: `Message.Decoder` -> `PrepareMessage.decode()` -> `PrepareMessage.execute()` -> `QueryProcessor.prepare()` -> `ResultMessage.Prepared`。
- EXECUTE path: `Message.Decoder` -> `ExecuteMessage.decode()` -> `ExecuteMessage.execute()` -> `QueryHandler.getPrepared()` -> `QueryProcessor.processPrepared()` -> `ResultMessage.Rows` metadata flag update。
- Persistence path: `QueryProcessor.storePreparedStatement()` -> `SystemKeyspace.writePreparedStatement()` -> `system.prepared_statements`。
- Eviction path: Caffeine removal listener -> `QueryProcessor.evictPreparedStatement()` -> `CQLMetrics.PreparedStatementsEvicted` -> `SystemKeyspace.removePreparedStatement()`。

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| `prepared_statements_cache_size` | `src/java/org/apache/cassandra/config/Config.java:581-585`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:795-804` | Prepared cache size in MiB; null/auto becomes max(heap/256, 10MiB). |
| `force_new_prepared_statement_behaviour` | `src/java/org/apache/cassandra/config/Config.java:119`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4974-4984` | Force post-4.0.2 statement id behavior even if gossip min-version gate has not flipped. |

## Metrics

`CQLMetrics` exposes:

- `PreparedStatementsExecuted`
- `PreparedStatementsEvicted`
- `PreparedStatementsCount`
- `PreparedStatementsRatio`
- `RegularStatementsExecuted`

Definitions are in `src/java/org/apache/cassandra/metrics/CQLMetrics.java:31-64`. `QueryProcessor.processPrepared()` increments prepared execution count; eviction increments prepared eviction count and removes the system table row.

## 日志

- Cache init: `Initialized prepared statement caches with {} MiB` from `QueryProcessor` static initializer.
- Cache eviction pressure: `{} prepared statements discarded in the last minute because cache limit reached` from `QueryProcessor` scheduled warning.
- Preload: `Preloaded {} prepared statements in {} ms` and leak guard warning from `SystemKeyspace.loadPreparedStatements()`.
- Dangerous V5 prepare keyspace option: `Keyspace is set via query options. This is considered dangerous...` from `PrepareMessage`.
- Keyspace mismatch on execute: `Tried to execute a prepared unqalified statement on a keyspace it was not prepared on...` from `ExecuteMessage`.

## 运维关注点

- High-cardinality prepared statements show up as eviction warnings and `PreparedStatementsEvicted`; this usually means clients are preparing dynamically generated CQL instead of reusing stable statements.
- During rolling upgrades, do not force new behavior unless the cluster and clients are ready for statement id changes.
- Dropping or altering tables/functions invalidates prepared statements; clients must handle `UNPREPARED` by repreparing.
- `system.prepared_statements` can retain leaked rows from old versions; startup preload warns and returns early when loaded bytes exceed roughly 110% of cache capacity.
- Avoid `USE <keyspace>` with prepared statements in clients; source has warnings because unqualified prepared statements depend on keyspace.

## 性能瓶颈

- Preparing is parse/prepare/cache work and can write `system.prepared_statements`; it should not be done per request.
- Preload reparses persisted CQL at startup; very large `system.prepared_statements` can lengthen startup until the 110% guard trips.
- Result metadata id comparisons are cheap, but wrong client metadata id use can force metadata to be resent.
- Duplicate digest storage during rolling compatibility consumes cache weight and system table rows.

## 常见故障

- `UNPREPARED`: prepared id missing after cache eviction, schema invalidation, restart without persisted row, or client using id from a different keyspace/protocol behavior.
- `The page size cannot be 0`: execute request had invalid query options.
- Unexpected result columns after `ALTER TABLE`: V4 clients lack the V5 metadata id path and may rely on driver reprepare behavior.
- Prepared cache eviction warning every minute: cache is undersized or clients prepare too many unique statements.
- Keyspace mismatch warning: unqualified statement executed under a different keyspace than it was prepared under.

## 测试用例

- `python3 research/tools/check-prepared-statement-compat-drift.py`：source-only drift check。
- `PreparedStatementsTest` covers drop/alter invalidation, V4 vs V5 metadata behavior, reconnect reprepare, custom expressions, LWT metadata flags and prepared LWT shape changes; see `test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java:59-459`。
- `PstmtPersistenceTest` covers prepared persistence, preload paging, eviction, deletion timestamp order and preload early return; see `test/unit/org/apache/cassandra/cql3/PstmtPersistenceTest.java:58-390`。
- `PreparedStatementTest` covers concurrent prepare cache presence; see `test/unit/org/apache/cassandra/cql3/validation/miscellaneous/PreparedStatementTest.java:31-84`。
- `PrepareMessageTest` covers V5 prepare encode/decode with keyspace; see `test/unit/org/apache/cassandra/transport/messages/PrepareMessageTest.java:27-40`。
- `SerDeserTest.preparedMetadataSerializationTest()` covers V3 prepared metadata without partition-key indexes and V4+ with indexes; see `test/unit/org/apache/cassandra/transport/SerDeserTest.java:312-354`。
- `PrepareBatchStatementsTest` covers fully qualified and unqualified prepared batch persistence across keyspaces; see `test/distributed/org/apache/cassandra/distributed/test/PrepareBatchStatementsTest.java:34-96`。

## 当前缺口

- The repository has Java driver based tests for selected protocol versions, but not a complete cross-driver matrix across Java/Python/Go/Node/Rust drivers.
- Java driver prepared runtime/gap mapping is tracked in `research/module-prepared-driver-integration-gap-matrix.md`; scenario ids include `prepared_driver_java_reprepare_runtime`、`prepared_driver_keyspace_hash_runtime`、`prepared_driver_mixed_version_runtime`、`prepared_driver_fuzz_runtime`、`prepared_driver_protocol_negotiation_boundary`、`prepared_driver_v4_v5_metadata_boundary`、`prepared_driver_wire_codec_boundary`、`prepared_driver_persistence_runtime`、`prepared_driver_batch_keyspace_runtime`、`prepared_driver_non_java_gap` and `prepared_driver_protocol_matrix_gap`.
- No generated test currently enumerates every statement id matrix row across every supported native protocol version.
- `force_new_prepared_statement_behaviour` should be tested in mixed-version upgrade coverage before relying on it operationally.
