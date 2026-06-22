# Schema Sync Migration Matrix

本矩阵把 schema 同步链路从 DDL apply 之后的本地 schema mutation、gossip announce、schema push、schema pull、reset/clear 和 startup wait gate 单独固化。它补充 `flow-schema-change.md` 的调用图，重点关注 `SchemaUpdateHandler` 与 `MigrationCoordinator` 的运行时合同。

## Source Contract

| Scenario | Contract | Source anchors | Test anchors |
| --- | --- | --- | --- |
| `schema_sync_handler_interface_contract` | `SchemaUpdateHandler` 是 schema 同步抽象，要求实现 start、readiness wait、apply、reset 和 clear；默认实现可以被替换为非 gossip backend。 | `src/java/org/apache/cassandra/schema/SchemaUpdateHandler.java:23`, `src/java/org/apache/cassandra/schema/SchemaUpdateHandlerFactoryProvider.java:28` | `test/unit/org/apache/cassandra/schema/MigrationCoordinatorTest.java:176` |
| `schema_sync_default_handler_registration` | `DefaultSchemaUpdateHandler` 同时是 `IEndpointStateChangeSubscriber`；构造时注册 gossip subscriber、schema push handler 和 schema pull handler。 | `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:46`, `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:84` | `test/distributed/org/apache/cassandra/distributed/test/SchemaTest.java:129` |
| `schema_sync_apply_diff_mutation_contract` | 本地 DDL transformation 先基于 current `DistributedSchema` 计算 `Keyspaces.diff`，再转成 `system_schema` mutations、写入 `SchemaKeyspace`、计算 digest、更新内存 schema。 | `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:227`, `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:899` | `test/unit/org/apache/cassandra/schema/SchemaKeyspaceTest.java` |
| `schema_sync_remote_mutation_merge_contract` | 收到远端 schema mutations 时只重读受影响 keyspaces，合成 before/after diff 后走同一 `updateSchema(update, false)` 合并路径。 | `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:200`, `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:212` | `test/distributed/org/apache/cassandra/distributed/test/SchemaTest.java:129` |
| `schema_sync_announce_and_startup_wait_contract` | 默认 handler start 保存 system keyspaces schema、启动 migration coordinator；readiness wait 依赖 `awaitSchemaRequests()`，失败时给出 skip/ignore system properties。 | `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:111`, `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:122` | `test/distributed/org/apache/cassandra/distributed/test/MigrationCoordinatorTest.java:66` |
| `schema_sync_endpoint_version_tracking_contract` | `MigrationCoordinator` 维护 schema version -> endpoints、outstanding requests、request queue 和 wait queue；gossip `ApplicationState.SCHEMA` report 会更新 endpoint/version 关系。 | `src/java/org/apache/cassandra/schema/MigrationCoordinator.java:161`, `src/java/org/apache/cassandra/schema/MigrationCoordinator.java:428`, `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:154` | `test/unit/org/apache/cassandra/schema/MigrationCoordinatorTest.java:220`, `test/unit/org/apache/cassandra/schema/MigrationCoordinatorTest.java:240` |
| `schema_sync_pull_selection_compatibility_contract` | schema pull 只从可用远端拉取：不能是本地 endpoint，必须有 gossip state、同 major release、已知 messaging version、等于当前 messaging version，并且不是 gossip-only member。 | `src/java/org/apache/cassandra/schema/MigrationCoordinator.java:353`, `src/java/org/apache/cassandra/schema/MigrationCoordinator.java:377`, `src/java/org/apache/cassandra/schema/MigrationCoordinator.java:390` | `test/unit/org/apache/cassandra/schema/MigrationCoordinatorTest.java:281`, `test/unit/org/apache/cassandra/schema/MigrationCoordinatorTest.java:303` |
| `schema_sync_pull_retry_await_contract` | pull 请求使用 `SCHEMA_PULL_REQ`，失败 endpoint 记录 backoff，成功标记 version received；startup wait 注册每个未收到 version 的 wait signal。 | `src/java/org/apache/cassandra/schema/MigrationCoordinator.java:548`, `src/java/org/apache/cassandra/schema/MigrationCoordinator.java:686`, `src/java/org/apache/cassandra/schema/MigrationCoordinator.java:707` | `test/unit/org/apache/cassandra/schema/MigrationCoordinatorTest.java:177`, `test/unit/org/apache/cassandra/schema/MigrationCoordinatorTest.java:312` |
| `schema_sync_push_viable_nodes_contract` | 本地非 local DDL 会异步 push schema mutations；push 只发给 live peers 中 messaging version 已知且等于当前版本的节点。 | `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:243`, `src/java/org/apache/cassandra/schema/MigrationCoordinator.java:737`, `src/java/org/apache/cassandra/schema/MigrationCoordinator.java:757` | `test/unit/org/apache/cassandra/schema/MigrationCoordinatorTest.java:376` |
| `schema_sync_reset_clear_contract` | local reset reload 本地 schema tables；remote reset 触发 coordinator reset/await；clear 把本地 schema version 暂时视为 empty，收到非空 mutations 时 truncate 本地 schema 后替换。 | `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:281`, `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:307`, `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:337` | `test/distributed/org/apache/cassandra/distributed/test/SchemaTest.java:129` |
| `schema_sync_verb_serializer_diagnostics_contract` | schema sync verbs 运行在 `MIGRATION` stage；push/pull 使用 `SchemaMutationsSerializer`，version request 使用 UUID serializer；push/receive path 发布 `SchemaAnnouncementEvent`。 | `src/java/org/apache/cassandra/net/Verb.java:155`, `src/java/org/apache/cassandra/schema/SchemaMutationsSerializer.java:30`, `src/java/org/apache/cassandra/schema/SchemaAnnouncementDiagnostics.java:37`, `src/java/org/apache/cassandra/schema/SchemaAnnouncementEvent.java:46` | `test/unit/org/apache/cassandra/schema/MigrationCoordinatorTest.java:376` |
| `schema_sync_disagreement_tests_baseline` | 现有 distributed tests 覆盖 replace/explicit ignore、manual schema reset、schema disagreement write safety 和 upgrade schema agreement 基线。 | `test/distributed/org/apache/cassandra/distributed/test/MigrationCoordinatorTest.java`, `test/distributed/org/apache/cassandra/distributed/test/SchemaTest.java`, `test/distributed/org/apache/cassandra/distributed/test/SchemaDisagreementTest.java` | same |

## Design Goals

- 让 schema update backend 可替换，同时默认实现能用 gossip/messaging 在集群内自动收敛。
- 避免每个节点都全量扫描 schema：remote mutation merge 只重读受影响 keyspaces。
- 在 startup/bootstrap 时阻止节点带着已知 schema disagreement 继续启动，除非显式跳过或忽略特定 endpoint/version。
- 兼容 rolling upgrade：不同 major release、unknown messaging version 或 schema format 不兼容时不拉取 schema。

## Lifecycle

```text
DDL on coordinator
  -> DefaultSchemaUpdateHandler.apply(transformation, local=false)
     -> transformation.apply(before.keyspaces)
     -> Keyspaces.diff(before, after)
     -> SchemaKeyspace.convertSchemaDiffToMutations(...)
     -> SchemaKeyspace.applyChanges(mutations)
     -> DistributedSchema(afterKeyspaces, calculateSchemaDigest())
     -> updateSchema(update, false)
        -> Schema.mergeAndUpdateVersion(...)
        -> MigrationCoordinator.announce(schemaVersion)
     -> async MigrationCoordinator.pushSchemaMutations(mutations)
        -> Message.out(SCHEMA_PUSH_REQ, mutations)
        -> remote SchemaPushVerbHandler.doVerb(...)
        -> remote DefaultSchemaUpdateHandler.applyMutations(...)
```

```text
gossip observes remote schema version
  -> DefaultSchemaUpdateHandler.onChange(ApplicationState.SCHEMA)
     -> MigrationCoordinator.reportEndpointVersion(endpoint, version)
        -> versionInfo[version].requestQueue.addFirst(endpoint)
        -> maybePullSchema(version)
           -> shouldPullSchema(version)
           -> shouldPullFromEndpoint(endpoint)
           -> scheduleSchemaPull(endpoint, info)
           -> Message.out(SCHEMA_PULL_REQ, NoPayload)
           -> remote SchemaPullVerbHandler responseWith(getSchemaMutations())
           -> Callback.response(mutations)
              -> schemaUpdateCallback.accept(endpoint, mutations)
              -> mark version received and unblock awaiters
```

```text
manual reset / startup wait
  -> SchemaUpdateHandler.waitUntilReady(timeout)
     -> MigrationCoordinator.awaitSchemaRequests(timeout)
     -> if timeout: report outstandingVersions and skip/ignore properties

  -> SchemaUpdateHandler.clear()
     -> requestedReset = AsyncPromise
     -> MigrationCoordinator.reset()
     -> first non-empty remote mutations:
        -> schema = DistributedSchema.EMPTY
        -> SchemaKeyspace.truncate()
        -> applyMutations(mutations)
```

## Configuration And Operations

| Surface | Contract |
| --- | --- |
| `cassandra.schema_pull_interval_ms` | Controls periodic pull loop interval through `SCHEMA_PULL_INTERVAL_MS`. |
| `cassandra.migration_delay_ms` | Delays schema pulls after startup unless local schema is empty or node uptime is below the migration delay. |
| `cassandra.skip_schema_check` | Lets startup proceed even if required schemas were not received. |
| `cassandra.skip_schema_check_for_endpoints` | Ignores specific endpoints when waiting for schema agreement. |
| `cassandra.skip_schema_check_for_versions` | Ignores specific schema versions when waiting for schema agreement. |
| `resetLocalSchema()` / `reloadLocalSchema()` | JMX-facing operational path for replacing local schema from peers or reloading local schema tables. |

## Operational Notes

- `getOutstandingSchemaVersions*()` reflects `MigrationCoordinator.outstandingVersions()` and is the first stop for startup schema wait failures.
- If a replaced node advertises an old schema version, replacement startup must remove/ignore that endpoint version before waiting.
- `clear()` intentionally waits for a real remote schema before truncating local schema tables; an empty pull response does not wipe the local schema.
- Push is best effort and version-gated; pull remains the recovery mechanism when push is missed or dropped.

## Performance And Failure Boundaries

- Large schema changes produce `system_schema` mutations and push messages to all viable live peers.
- Pulling full schema mutations is bounded by version tracking and compatibility checks, but repeated failures cycle through the request queue.
- During rolling upgrades, schema disagreement can persist until compatible messaging/schema format is available.
- Startup may block on schema versions that are only advertised by unavailable endpoints unless the endpoint/version is ignored or removed.

## Test Cases

- `test/unit/org/apache/cassandra/schema/MigrationCoordinatorTest.java:177`：request/failure/retry/success cycle and startup await behavior.
- `test/unit/org/apache/cassandra/schema/MigrationCoordinatorTest.java:220`：version waiters are signalled when an endpoint changes versions.
- `test/unit/org/apache/cassandra/schema/MigrationCoordinatorTest.java:240`：removed endpoint unblocks version waiters.
- `test/unit/org/apache/cassandra/schema/MigrationCoordinatorTest.java:281`：incompatible endpoint filtering.
- `test/unit/org/apache/cassandra/schema/MigrationCoordinatorTest.java:312`：repeated pull request scheduling and eventual unblock.
- `test/unit/org/apache/cassandra/schema/MigrationCoordinatorTest.java:376`：push only to viable nodes.
- `test/distributed/org/apache/cassandra/distributed/test/MigrationCoordinatorTest.java:66`：replace node does not wait on old replaced endpoint schema.
- `test/distributed/org/apache/cassandra/distributed/test/MigrationCoordinatorTest.java:87`：explicit endpoint ignore startup path.
- `test/distributed/org/apache/cassandra/distributed/test/MigrationCoordinatorTest.java:108`：explicit version ignore startup path.
- `test/distributed/org/apache/cassandra/distributed/test/SchemaTest.java:129`：manual schema reset/clear replaces local schema from peer.
- `test/distributed/org/apache/cassandra/distributed/test/SchemaDisagreementTest.java:34`：inconsequential schema disagreement write safety.
