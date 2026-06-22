# Flow: Schema Change

## 目标

Schema change 链路解释一次 `CREATE/ALTER/DROP` 如何从 CQL DDL statement 变成 schema mutations，如何更新本地 `Schema`、通知 listeners、失效 prepared statements，并通过 gossip/push/pull 与其他节点收敛。

## 文字版调用图

DDL 执行：

```text
CREATE/ALTER/DROP statement
  -> QueryProcessor.processStatement(...)
     -> statement.authorize(clientState)
     -> statement.validate(clientState)
     -> AlterSchemaStatement.execute(queryState, locally=false)
        -> reject local system keyspace / virtual keyspace
        -> validate keyspace name
        -> Schema.instance.transform(statement, locally)
           -> DefaultSchemaUpdateHandler.apply(transformation, local=false)
              -> before = current DistributedSchema
              -> afterKeyspaces = transformation.apply(before.keyspaces)
              -> diff = Keyspaces.diff(before, after)
              -> SchemaKeyspace.convertSchemaDiffToMutations(diff, timestamp)
              -> SchemaKeyspace.applyChanges(mutations)
              -> after = DistributedSchema(afterKeyspaces, calculateSchemaDigest())
              -> updateSchema(update, local=false)
                 -> schema = update.after
                 -> Schema.mergeAndUpdateVersion(update, dropData=true)
                    -> notifyPreChanges(update)
                    -> merge(diff, dropData)
                    -> updateVersion(update.after.version)
                    -> SystemKeyspace.updateSchemaVersion(...)
                 -> migrationCoordinator.announce(version)
              -> async migrationCoordinator.pushSchemaMutations(mutations)
        -> grant permissions on created resources
        -> return ResultMessage.SchemaChange
```

`CreateTableStatement` 示例：

```text
CreateTableStatement.apply(schema)
  -> keyspace = schema.getNullable(keyspaceName)
  -> reject missing/existing table unless IF NOT EXISTS
  -> table = builder(keyspace.types).build()
  -> table.validate()
  -> reject read_repair != NONE for transient replication
  -> guardrail uncompressed tables
  -> return schema.withAddedOrUpdated(keyspace.withSwapped(keyspace.tables.with(table)))
```

本地 merge：

```text
Schema.merge(diff, dropData)
  -> dropped keyspaces: dropKeyspace(...)
  -> created keyspaces: createKeyspace(...)
  -> altered keyspaces: alterKeyspace(...)
     -> drop removed tables/views
     -> load updated KeyspaceMetadata
     -> create new tables/views
     -> alter changed tables/views
     -> reload view manager
     -> schemaChangeNotifier.notifyKeyspaceAltered(...)
```

Cluster convergence：

```text
local updateSchema(...)
  -> migrationCoordinator.announce(schemaVersion)
     -> Gossiper ApplicationState.SCHEMA
  -> pushSchemaMutations(mutations) to live peers
     -> remote SchemaPushVerbHandler.doVerb(schema mutations)
        -> DefaultSchemaUpdateHandler.applyMutations(...)
           -> SchemaKeyspace.applyChanges(remote mutations)
           -> fetch affected keyspaces
           -> diff before/after
           -> updateSchema(update, local=false)

node observes schema version via gossip
  -> MigrationCoordinator tracks outstanding version
  -> pull schema if needed
     -> send SCHEMA_PULL_REQ
     -> remote SchemaPullVerbHandler returns convertSchemaToMutations()
     -> callback applies mutations through schemaUpdateCallback
```

Prepared statement invalidation:

```text
Schema.mergeAndUpdateVersion(...)
  -> schemaChangeNotifier.notifyPreChanges(update)
  -> merge diff
  -> schemaChangeNotifier.notifyKeyspaceAltered(...)
     -> notifyAlterTable(before, after)
        -> before.changeAffectsPreparedStatements(after)
        -> QueryProcessor.StatementInvalidatingListener.onAlterTable(...)
           -> removeInvalidPreparedStatements(keyspace, table)
     -> notifyDropTable/DropKeyspace(...)
        -> removeInvalidPreparedStatements(...)
```

## 关键源码锚点

| 阶段 | 文件/方法 |
|---|---|
| DDL base | `AlterSchemaStatement`：`src/java/org/apache/cassandra/cql3/statements/schema/AlterSchemaStatement.java:43-65` |
| DDL execute | `AlterSchemaStatement.execute()`：`src/java/org/apache/cassandra/cql3/statements/schema/AlterSchemaStatement.java:107-136` |
| Created resource grants | `AlterSchemaStatement.grantPermissionsOnResource()`：`src/java/org/apache/cassandra/cql3/statements/schema/AlterSchemaStatement.java:147-160` |
| Create keyspace apply | `CreateKeyspaceStatement.apply()`：`src/java/org/apache/cassandra/cql3/statements/schema/CreateKeyspaceStatement.java:63-88` |
| Create table apply | `CreateTableStatement.apply()`：`src/java/org/apache/cassandra/cql3/statements/schema/CreateTableStatement.java:97-124` |
| Create table validate/auth | `CreateTableStatement.validate()` / `authorize()`：`src/java/org/apache/cassandra/cql3/statements/schema/CreateTableStatement.java:127-165` |
| Schema singleton | `Schema` fields/init：`src/java/org/apache/cassandra/schema/Schema.java:84-127` |
| Schema transform | `Schema.transform()`：`src/java/org/apache/cassandra/schema/Schema.java:606-614` |
| Update handler apply | `DefaultSchemaUpdateHandler.apply()`：`src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:227-252` |
| Update handler updateSchema | `DefaultSchemaUpdateHandler.updateSchema()`：`src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:255-271` |
| Apply remote mutations | `DefaultSchemaUpdateHandler.applyMutations()`：`src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:200-224` |
| Schema merge/update | `Schema.mergeAndUpdateVersion()`：`src/java/org/apache/cassandra/schema/Schema.java:594-604` |
| Schema merge diff | `Schema.merge()`：`src/java/org/apache/cassandra/schema/Schema.java:644-649` |
| Alter keyspace merge | `Schema.alterKeyspace()`：`src/java/org/apache/cassandra/schema/Schema.java:651-685` |
| Create keyspace local | `Schema.createKeyspace()`：`src/java/org/apache/cassandra/schema/Schema.java:688-705` |
| Drop keyspace local | `Schema.dropKeyspace()`：`src/java/org/apache/cassandra/schema/Schema.java:708-735` |
| Schema listener registration | `Schema.registerListener()`：`src/java/org/apache/cassandra/schema/Schema.java:200-208` |
| Change notifier | `SchemaChangeNotifier.notifyKeyspaceAltered()`：`src/java/org/apache/cassandra/schema/SchemaChangeNotifier.java:59-83` |
| Prepared invalidation listener | `QueryProcessor.StatementInvalidatingListener`：`src/java/org/apache/cassandra/cql3/QueryProcessor.java:975-1060` |
| Alter table prepared decision | `SchemaChangeNotifier.notifyAlterTable()`：`src/java/org/apache/cassandra/schema/SchemaChangeNotifier.java:151-155` |
| Table metadata affects prepared | `TableMetadata.changeAffectsPreparedStatements()`：`src/java/org/apache/cassandra/schema/TableMetadata.java:661-670` |
| Migration announce | `MigrationCoordinator.announce()`：`src/java/org/apache/cassandra/schema/MigrationCoordinator.java:574-579` |
| Pull response callback | `MigrationCoordinator.Callback.response()`：`src/java/org/apache/cassandra/schema/MigrationCoordinator.java:628-650` |
| Schema push receiver | `SchemaPushVerbHandler.doVerb()`：`src/java/org/apache/cassandra/schema/SchemaPushVerbHandler.java:51-61` |
| Schema pull receiver | `SchemaPullVerbHandler.doVerb()`：`src/java/org/apache/cassandra/schema/SchemaPullVerbHandler.java:48-56` |
| Schema version request | `SchemaVersionVerbHandler.doVerb()`：`src/java/org/apache/cassandra/schema/SchemaVersionVerbHandler.java:36-40` |
| Auth system keyspace update | `StorageService.doAuthSetup()`：`src/java/org/apache/cassandra/service/StorageService.java:1441-1458` |
| Schema reset/reload JMX | `StorageService.resetLocalSchema()` / `reloadLocalSchema()`：`src/java/org/apache/cassandra/service/StorageService.java:6616-6624` |
| Outstanding schema versions | `StorageService.getOutstandingSchemaVersions*()`：`src/java/org/apache/cassandra/service/StorageService.java:7172-7185` |

## Schema 存储与传播语义

- `SchemaTransformation.apply()` 只产生新的 `Keyspaces`，不能直接改系统状态，见 `src/java/org/apache/cassandra/schema/SchemaTransformation.java:22-43`。
- `DefaultSchemaUpdateHandler.apply()` 将 diff 转成 mutations 并写入 `SchemaKeyspace`，schema digest 来自 `SchemaKeyspace.calculateSchemaDigest()`，见 `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:227-252`。
- 非 local schema change 会异步 `pushSchemaMutations()` 到 peers，并通过 gossip announce 新 schema version，见 `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:243-250`、`src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:255-265`。
- 收到 schema push 时只分发给已注册 handlers；默认 handler 在 `DefaultSchemaUpdateHandler` 构造函数中注册，见 `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:92-109`。
- schema pull 用于发现 disagreement 后拉全量 schema mutations，`SchemaPullVerbHandler` 的类注释说明该请求来自 gossip 发现 schema disagreement，见 `src/java/org/apache/cassandra/schema/SchemaPullVerbHandler.java:31-35`。

## Listener 副作用

- `AuthSchemaChangeListener` 在 keyspace/table drop 后让 authorizer revoke 对应 permissions，注册入口见 `src/java/org/apache/cassandra/service/StorageService.java:1456-1458`。
- `QueryProcessor.StatementInvalidatingListener` 会在 drop keyspace/table、alter table/function/aggregate 时移除相关 prepared statements，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:1078-1122`。
- `SchemaChangeNotifier.notifyPreChanges()` 在 alter 前触发 pre-alter table/view listeners，见 `src/java/org/apache/cassandra/schema/SchemaChangeNotifier.java:95-114`。

## 排查路径

1. DDL 返回 success 但其他节点不见：查看 gossip `ApplicationState.SCHEMA` 和 `getOutstandingSchemaVersionsWithPort()`。
2. DDL 卡在启动等待 schema：`DefaultSchemaUpdateHandler.waitUntilReady()` 会列出 outstanding versions，并提示可用的 skip properties，见 `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:122-145`。
3. 本地 schema 表疑似损坏：用 `reloadLocalSchema()` 从本地 schema tables reload 并 announce，或 `resetLocalSchema()` 清空本地 schema 后从其他节点拉取。
4. ALTER TABLE 后 prepared query 异常：看 `TableMetadata.changeAffectsPreparedStatements()` 是否触发 listener invalidation，以及 driver 是否 reprepare。
5. DDL 权限失败：检查 statement-specific `authorize()`，比如 `CreateTableStatement` 需要 `CREATE` on all tables in keyspace，见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateTableStatement.java:162-165`。
6. system keyspace DDL 失败：`AlterSchemaStatement.execute()` 拒绝 local system/virtual keyspace，`ClientState` 额外保护 replicated system keyspaces，见 `src/java/org/apache/cassandra/cql3/statements/schema/AlterSchemaStatement.java:107-118`、`src/java/org/apache/cassandra/service/ClientState.java:544-563`。

## 测试用例

- `test/unit/org/apache/cassandra/cql3/validation/operations/CreateTest.java`
- `test/unit/org/apache/cassandra/cql3/validation/operations/AlterTest.java`
- `test/unit/org/apache/cassandra/cql3/validation/operations/DropTest.java`
- `test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java`
- `test/unit/org/apache/cassandra/schema/SchemaKeyspaceTest.java`
- `test/unit/org/apache/cassandra/schema/SchemaTest.java`
- `test/unit/org/apache/cassandra/schema/MigrationCoordinatorTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/SchemaTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/SchemaDisagreementTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java`
