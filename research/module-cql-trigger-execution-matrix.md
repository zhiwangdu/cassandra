# Module: CQL Trigger Execution Matrix

## Scope

This matrix covers Cassandra CQL triggers as a write-path extension point: grammar and schema DDL, trigger metadata persistence, trigger class loading and reload, ordinary mutation/batch execution, CAS single-partition restrictions, audit logging and the current unit-test baseline. Triggers are related to write coordination, schema and nodetool, but they are not covered by the existing CQL parser or StorageProxy matrices as an independent runtime contract.

Current source baseline:

- `Parser.g` has dedicated `CREATE TRIGGER ... ON ... USING ...` and `DROP TRIGGER ... ON ...` rules that produce `CreateTriggerStatement.Raw` and `DropTriggerStatement.Raw`, see `src/antlr/Parser.g:918` and `src/antlr/Parser.g:930`.
- `CreateTriggerStatement.apply()` rejects missing keyspace/table, rejects materialized views, handles `IF NOT EXISTS`, preloads the trigger class through `TriggerExecutor.instance.loadTriggerInstance(triggerClass)` and adds `TriggerMetadata` to `TableMetadata.triggers`, see `src/java/org/apache/cassandra/cql3/statements/schema/CreateTriggerStatement.java:48`.
- `DropTriggerStatement.apply()` handles missing table/trigger plus `IF EXISTS` and removes the trigger from `TableMetadata.triggers`, see `src/java/org/apache/cassandra/cql3/statements/schema/DropTriggerStatement.java:45`.
- `TriggerMetadata` currently stores only the trigger name and `class` option; `Triggers` is an immutable name-to-metadata collection with `with()` / `without()` duplicate and missing-name checks, see `src/java/org/apache/cassandra/schema/TriggerMetadata.java:24` and `src/java/org/apache/cassandra/schema/Triggers.java:27`.
- `SchemaKeyspace` persists triggers in `system_schema.triggers(keyspace_name, table_name, trigger_name, options)` and serializes only `{"class": classOption}`, see `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:173` and `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:815`.
- `TriggerExecutor.reloadClasses()` resolves the trigger jar directory through `FBUtilities.cassandraTriggerDir()`, creates a new `CustomClassLoader` and clears cached trigger instances, see `src/java/org/apache/cassandra/triggers/TriggerExecutor.java:59` and `src/java/org/apache/cassandra/utils/FBUtilities.java:412`.
- `CustomClassLoader.addClassPath()` scans only `.jar` files, copies them to a temp `lib` directory and loads parent-first before falling back to trigger jars, see `src/java/org/apache/cassandra/triggers/CustomClassLoader.java:67` and `src/java/org/apache/cassandra/triggers/CustomClassLoader.java:104`.
- Ordinary writes and non-conditional batches call `StorageProxy.mutateWithTriggers()`, which executes trigger augmentations and forces augmented writes through `mutateAtomically()`, see `src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:505`, `src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:434` and `src/java/org/apache/cassandra/service/StorageProxy.java:1116`.
- Legacy Paxos CAS and local internal CAS execute triggers with `TriggerExecutor.execute(PartitionUpdate)`, which validates generated updates remain on the same table and partition, see `src/java/org/apache/cassandra/service/StorageProxy.java:376` and `src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:721`.
- `nodetool reloadtriggers` routes `ReloadTriggers -> NodeProbe.reloadTriggers() -> StorageService.reloadTriggerClasses() -> TriggerExecutor.reloadClasses()`, see `src/java/org/apache/cassandra/tools/nodetool/ReloadTriggers.java:25`, `src/java/org/apache/cassandra/tools/NodeProbe.java:2243` and `src/java/org/apache/cassandra/service/StorageProxy.java:2857`.

## Scenario Matrix

| Scenario ID | Contract |
|---|---|
| `cql_trigger_grammar_contract` | CQL grammar has explicit create/drop trigger rules returning raw schema statements. |
| `cql_trigger_create_authorization_load_contract` | CREATE TRIGGER is superuser-only, rejects materialized views, validates duplicates and preloads the trigger class before schema mutation. |
| `cql_trigger_drop_authorization_contract` | DROP TRIGGER is superuser-only, honors `IF EXISTS`, and mutates table metadata by removing the trigger. |
| `cql_trigger_metadata_contract` | `TriggerMetadata` only stores name and class option; `Triggers` is immutable and keyed by trigger name. |
| `cql_trigger_system_schema_contract` | `system_schema.triggers` persists trigger rows and reconstructs `TriggerMetadata` from `options['class']`. |
| `cql_trigger_classloader_reload_contract` | Trigger reload swaps the custom classloader and clears cached trigger instances; the loader scans `.jar` files and is parent-first. |
| `cql_trigger_directory_config_contract` | `cassandra.triggers_dir` / `conf/triggers` is the runtime jar directory boundary. |
| `cql_trigger_ordinary_write_contract` | Non-conditional single mutations execute trigger augmentations before StorageProxy writes. |
| `cql_trigger_batch_atomic_contract` | Augmented batch writes are merged and forced through logged batch semantics; counter+trigger atomicity is rejected. |
| `cql_trigger_cas_single_partition_contract` | CAS trigger augmentations must target the same table and partition as the Paxos update. |
| `cql_trigger_validation_contract` | Trigger-generated mutations are key-validated and partition-update validated before execution. |
| `cql_trigger_nodetool_reload_contract` | `reloadtriggers` is an operator-only classloader/cache reload, not a schema mutation. |
| `cql_trigger_audit_contract` | CREATE/DROP TRIGGER map to DDL audit entry types. |
| `cql_trigger_tests_baseline` | Existing unit tests cover schema mutation, executor merge/reject behavior, CQL execution and audit baseline. |
| `cql_trigger_distributed_gap` | No dedicated distributed trigger test exists in this checkout; current coverage is unit/in-JVM only. |

## Call Graphs

```text
CREATE TRIGGER trigger_1 ON ks.tbl USING 'com.example.Trigger'
  -> Parser.g createTriggerStatement
  -> CreateTriggerStatement.Raw.prepare()
  -> CreateTriggerStatement.authorize()
     -> ClientState.ensureIsSuperuser(...)
  -> CreateTriggerStatement.apply()
     -> lookup keyspace/table
     -> reject materialized view
     -> table.triggers.get(triggerName)
     -> TriggerExecutor.instance.loadTriggerInstance(triggerClass)
     -> table.withSwapped(table.triggers.with(TriggerMetadata.create(...)))
     -> SchemaChange UPDATED TABLE
  -> SchemaKeyspace.addTriggerToSchemaMutation()
     -> system_schema.triggers.options = {"class": triggerClass}
```

```text
INSERT / UPDATE / DELETE without IF
  -> ModificationStatement.executeWithoutCondition()
     -> getMutations(...)
     -> StorageProxy.mutateWithTriggers(mutations, cl, false, requestTime)
        -> TriggerExecutor.instance.execute(mutations)
           -> for each PartitionUpdate
              -> executeInternal(update)
                 -> set context classloader to customClassLoader
                 -> load cached trigger or customClassLoader.loadClass(...)
                 -> ITrigger.augment(update)
              -> validate generated mutations
           -> mergeMutations(original + augmentations)
        -> if augmented != null: mutateAtomically(augmented, ...)
        -> else: mutate(...) or mutateAtomically(original, ...)
```

```text
conditional update / legacy CAS
  -> StorageProxy.legacyCas()
     -> request.makeUpdates(...)
     -> TriggerExecutor.instance.execute(PartitionUpdate)
        -> executeInternal(update)
        -> validateForSinglePartition(original table id, original partition key, generated mutations)
        -> PartitionUpdate.merge(generated + original)
     -> doPaxos(...)
```

```text
nodetool reloadtriggers
  -> ReloadTriggers.execute(NodeProbe)
  -> NodeProbe.reloadTriggers()
  -> StorageProxy.reloadTriggerClasses()
  -> TriggerExecutor.reloadClasses()
     -> FBUtilities.cassandraTriggerDir()
     -> new CustomClassLoader(parent, triggerDirectory)
     -> cachedTriggers.clear()
```

## Design Goals

- Allow table-local custom mutation augmentation without changing core write statement code for every use case.
- Keep schema state small: only trigger name and class name are persisted.
- Validate trigger classes at CREATE time to fail DDL before schema agreement publishes an unusable trigger.
- Keep ordinary augmented writes atomic by forcing generated mutations through batchlog-backed `mutateAtomically()`.
- Keep CAS scoped to a single Paxos partition by rejecting cross-table and cross-partition trigger output.

## Problems Solved

- Operators can attach custom code to write operations at table scope.
- Schema agreement can replicate trigger metadata through `system_schema.triggers`.
- Reloading jars does not require a full node restart when the trigger directory changes.
- Trigger errors prevent partially applying original writes in covered CQL paths.

## Tradeoffs

- Trigger code is loaded from jars and executes in the coordinator write path; bad trigger code can increase write latency or fail writes.
- Only a single `class` option is persisted, so there is no first-class parameter model.
- Ordinary multi-partition trigger output is allowed and becomes atomic/logged batch work, while CAS output is intentionally constrained to the original table/partition.
- `reloadtriggers` only swaps classloader/cache; it does not validate every schema trigger after reload.
- Existing coverage is strong at unit level but does not prove multi-node schema agreement or rolling reload behavior.

## Core Classes

| Class/File | Role |
|---|---|
| `ITrigger` | Beta trigger SPI. Implementations must have a no-arg constructor and should be stateless. |
| `TriggerExecutor` | Executes trigger augmentations, validates generated mutations, merges mutation groups and reloads custom trigger classes. |
| `CustomClassLoader` | Parent-first URL classloader that copies trigger jars to temp files before loading. |
| `CreateTriggerStatement` / `DropTriggerStatement` | CQL DDL schema statements and authorization/audit boundary. |
| `TriggerMetadata` / `Triggers` | Table metadata representation for trigger name/class mappings. |
| `SchemaKeyspace` | `system_schema.triggers` persistence and fetch path. |
| `ModificationStatement` / `BatchStatement` / `StorageProxy` | Ordinary write and batch execution entrypoints that invoke triggers. |
| `ReloadTriggers` / `NodeProbe` / `StorageProxyMBean` surface | Operator reload route. |

## Core Interfaces

- `ITrigger.augment(Partition update)`.
- `TriggerExecutor.execute(PartitionUpdate)` for single-partition CAS semantics.
- `TriggerExecutor.execute(Collection<? extends IMutation>)` for ordinary mutation/batch semantics.
- `TriggerExecutor.reloadClasses()` and `loadTriggerInstance(String)`.
- `CreateTriggerStatement.apply()` / `authorize()` / `getAuditLogContext()`.
- `DropTriggerStatement.apply()` / `authorize()` / `getAuditLogContext()`.

## Core Data Structures

| Data Structure | Meaning |
|---|---|
| `TriggerMetadata` | Trigger name plus `classOption`. |
| `Triggers` | Immutable trigger map on `TableMetadata`. |
| `cachedTriggers` | Runtime cache keyed by trigger class name. |
| `CustomClassLoader.cache` | Loaded class cache inside the current trigger classloader. |
| `system_schema.triggers.options` | Frozen map currently containing only `class`. |
| `ListMultimap<Pair<String, ByteBuffer>, Mutation>` | Grouping used to merge original and generated ordinary mutations by keyspace and partition key. |

## Configuration

| Config | Source | Meaning |
|---|---|---|
| `cassandra.triggers_dir` | `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:605`, `conf/jvm-server.options:84` | Overrides trigger jar directory. |
| `conf/triggers` | `src/java/org/apache/cassandra/utils/FBUtilities.java:421` | Default trigger directory when available on the classpath. |

## Metrics

No trigger-specific metrics are registered in this path. Trigger latency and failures surface indirectly through normal write/CAS metrics, batchlog behavior, audit logs and client exceptions.

## Logs

- `CustomClassLoader.addClassPath()` logs each jar it loads with `Loading new jar ...`, see `src/java/org/apache/cassandra/triggers/CustomClassLoader.java:82`.
- Missing trigger directory logs a warning from `FBUtilities.cassandraTriggerDir()`, see `src/java/org/apache/cassandra/utils/FBUtilities.java:425`.
- Trigger execution exceptions are wrapped in a runtime exception unless they are already a Cassandra exception, see `src/java/org/apache/cassandra/triggers/TriggerExecutor.java:241`.

## Operational Notes

- Trigger jars must be present on every coordinator that may execute writes for the table before CREATE TRIGGER or before the node observes schema containing that trigger.
- Reloading classes does not change schema and does not guarantee stateful trigger instances keep state; the SPI explicitly recommends stateless implementations.
- Counter mutations cannot be atomically combined with generated trigger mutations.
- CAS triggers that emit a different partition or table are rejected to preserve Paxos scope.
- There is no dedicated distributed trigger test in this checkout; rolling jar deployment and schema propagation need separate validation.

## Performance Bottlenecks

- Every write touching a table with triggers calls user code in the write path.
- Ordinary trigger augmentations that emit extra partitions force logged batch behavior and can increase coordinator work, batchlog writes and replica fanout.
- Classloader reload clears the trigger instance cache; the next write pays class loading and construction costs.

## Common Failures

- `Trigger class ... couldn't be loaded`: jar is missing from `cassandra.triggers_dir` / `conf/triggers` or the class has no public no-arg constructor.
- `Counter mutations and trigger mutations cannot be applied together atomically`: trigger returned mutations while original mutation set contains counters.
- `Partition key of additional mutation does not match primary update key` or `table of additional mutation does not match primary update table`: CAS trigger output violated single-partition scope.
- Original write not applied after trigger throws: existing tests assert failed trigger execution prevents applying the original mutation in the covered CQL path.

## Tests

- `TriggersTest` covers CQL insert, batch insert, conditional insert, conditional batch, cross-partition/cross-table CAS rejection and error atomicity, see `test/unit/org/apache/cassandra/triggers/TriggersTest.java:82`.
- `TriggerExecutorTest` covers single-partition merge, ordinary multi-mutation merge, no-op trigger behavior, cross-table/keyspace/partition output and validation, see `test/unit/org/apache/cassandra/triggers/TriggerExecutorTest.java:51`.
- `TriggersSchemaTest` covers creating keyspaces/tables with triggers, adding triggers to an existing table and removing triggers, see `test/unit/org/apache/cassandra/triggers/TriggersSchemaTest.java:51`.
- `AuditLoggerTest.testCqlTriggerAuditing()` covers trigger DDL audit entry mapping for `DROP_TRIGGER`, see `test/unit/org/apache/cassandra/audit/AuditLoggerTest.java:520`.

