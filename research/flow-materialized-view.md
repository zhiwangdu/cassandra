# Flow: Materialized View Write And Build

## 目标

Materialized View 链路说明一个 base table mutation 如何在 base replica 上判断是否影响 view，读取旧行，生成 view mutation，并按 base/view token 的 paired replica 规则写入 view。该文档聚焦写入更新链路，build/rebuild 和 repair-MV 后续单独展开。

## 文字版调用图

```text
Client write to base table
  -> QueryMessage / ExecuteMessage
     -> ModificationStatement.execute(...)
        -> StorageProxy.mutateWithTriggers(mutations, CL, requestTime)
           -> TriggerExecutor.execute(mutations)
           -> Keyspace.open(...).viewManager.updatesAffectView(mutations, coordinatorBatchlog=true)
           -> mutateAtomically(..., updatesView)
              -> send MUTATION_REQ to base replicas

Base replica receives mutation
  -> MutationVerbHandler / Mutation.apply(...)
     -> Keyspace.applyInternal(mutation, makeDurable, updateIndexes, ...)
        -> requiresViewUpdate = updateIndexes && viewManager.updatesAffectView(..., false)
        -> if requiresViewUpdate:
           -> acquire ViewManager lock per base key/table id
        -> begin write context
        -> for each PartitionUpdate:
           -> if requiresViewUpdate:
              -> TableViews.pushViewReplicaUpdates(update, makeDurable, baseComplete)
                 -> updatedViews(update)
                 -> readExistingRowsCommand(update, views, nowInSec)
                 -> command.executeLocally(orderGroup)
                 -> update.unfilteredIterator()
                 -> generateViewUpdates(views, updates, existings, nowInSec, false)
                    -> ViewUpdateGenerator.addBaseTableUpdate(existingRow, updateRow)
                    -> ViewUpdateGenerator.generateViewUpdates()
                    -> buildMutations(...)
                 -> StorageProxy.mutateMV(baseKey, viewMutations, writeCommitLog, baseComplete, requestTime)
           -> cfs.getWriteHandler().write(base update)
           -> baseComplete.set(now)
        -> release locks
```

View mutation 分发：

```text
StorageProxy.mutateMV(baseKey, viewMutations, writeCommitLog, baseComplete, requestTime)
  -> if node not fully joined:
     -> write local batchlog
  -> else for each view mutation:
     -> compute base token and view token
     -> ViewUtils.getViewNaturalEndpoint(replicationStrategy, baseToken, viewToken)
     -> if no paired endpoint:
        -> keep in local batchlog for replay/range movement
     -> if paired endpoint is self and no pending replica:
        -> mutation.apply(writeCommitLog)
     -> else:
        -> ordinary write to paired/pending replicas
  -> cleanup local batchlog after view writes finish
```

## 关键源码锚点

| 阶段 | 文件/方法 |
|---|---|
| CREATE VIEW parse/build statement | `CreateViewStatement.Raw.prepare()`：`src/java/org/apache/cassandra/cql3/statements/schema/CreateViewStatement.java:420-443` |
| CREATE VIEW schema transform | `CreateViewStatement.apply()`：`src/java/org/apache/cassandra/cql3/statements/schema/CreateViewStatement.java:113-347` |
| MV enable check | `DatabaseDescriptor.getMaterializedViewsEnabled()` in `CreateViewStatement.apply()`：`src/java/org/apache/cassandra/cql3/statements/schema/CreateViewStatement.java:113-116` |
| ViewManager update affect 判断 | `ViewManager.updatesAffectView()`：`src/java/org/apache/cassandra/db/view/ViewManager.java:73-93` |
| ViewManager lock | `ViewManager.acquireLockFor()`：`src/java/org/apache/cassandra/db/view/ViewManager.java:198-206` |
| Base replica apply | `Keyspace.applyInternal()` MV lock/read/write 分支：`src/java/org/apache/cassandra/db/Keyspace.java:523-657` |
| TableViews 旧行读取和 mutateMV | `TableViews.pushViewReplicaUpdates()`：`src/java/org/apache/cassandra/db/view/TableViews.java:143-170` |
| View 更新合成 | `TableViews.generateViewUpdates()`：`src/java/org/apache/cassandra/db/view/TableViews.java:189-357` |
| 受影响 views | `TableViews.updatedViews()`：`src/java/org/apache/cassandra/db/view/TableViews.java:360-379` |
| 旧行 read command | `TableViews.readExistingRowsCommand()`：`src/java/org/apache/cassandra/db/view/TableViews.java:381-430` |
| View row action | `ViewUpdateGenerator.updateAction()`：`src/java/org/apache/cassandra/db/view/ViewUpdateGenerator.java:163-217` |
| View row create/update | `ViewUpdateGenerator.createEntry()` / `updateEntry()`：`src/java/org/apache/cassandra/db/view/ViewUpdateGenerator.java:229-290` |
| Build mutations | `TableViews.buildMutations()`：`src/java/org/apache/cassandra/db/view/TableViews.java:518-549` |
| View mutation 分发 | `StorageProxy.mutateMV()`：`src/java/org/apache/cassandra/service/StorageProxy.java:1010-1075` |
| Coordinator batchlog 判断 | `StorageProxy.mutateWithTriggers()` updatesView：`src/java/org/apache/cassandra/service/StorageProxy.java:1141-1152` |

## CREATE MATERIALIZED VIEW

- `CreateViewStatement.apply()` 首先检查 `materialized_views_enabled`；默认模板中该项为 `false`，见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateViewStatement.java:113-116` 和 `conf/cassandra.yaml:1979-1981`。
- MV 不支持 transient replication keyspace，创建时直接拒绝，见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateViewStatement.java:122-127`。
- WHERE clause 不能包含 token relation 或 custom index expression，见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateViewStatement.java:270-274`。
- View primary key columns 必须被 `IS NOT NULL` 或其他 restriction 限制；非法非 PK column restriction 默认拒绝，见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateViewStatement.java:276-303`。
- MV 不允许设置 `default_time_to_live`，因为 view 数据和 base 数据生命周期一致，见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateViewStatement.java:309-317`。
- 构造 view metadata 时将 view 标记为 `TableMetadata.Kind.VIEW`，并写入 keyspace views，见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateViewStatement.java:323-347`。

## Base Replica 更新

- `Keyspace.applyInternal()` 先判断 `requiresViewUpdate = updateIndexes && viewManager.updatesAffectView(...)`，见 `src/java/org/apache/cassandra/db/Keyspace.java:523-536`。
- 若需要更新 MV，会按 mutation key 和 table id 计算 lock key 并尝试获取 `ViewManager` lock，见 `src/java/org/apache/cassandra/db/Keyspace.java:537-614`。
- 获取锁耗时只对 droppable writes 记录 `viewLockAcquireTime`，见 `src/java/org/apache/cassandra/db/Keyspace.java:616-623`。
- base partition update 写入前先调用 `TableViews.pushViewReplicaUpdates()` 生成并提交 view mutation，然后再写 base CFS，见 `src/java/org/apache/cassandra/db/Keyspace.java:635-656`。
- `baseComplete` 在 base CFS 写完后设置，用于 `mutateMV()` 的视图写入顺序/清理协调，见 `src/java/org/apache/cassandra/db/Keyspace.java:635-657`。

## View Mutation 生成

- `TableViews.updatedViews()` 先用 view read query 判断 base partition key 是否可能被该 view 选中，见 `src/java/org/apache/cassandra/db/view/TableViews.java:360-379`。
- `readExistingRowsCommand()` 根据 partition deletion、range tombstone、updated rows 和 view filter 构造需要读取的旧 base rows，见 `src/java/org/apache/cassandra/db/view/TableViews.java:381-430`。
- `generateViewUpdates()` 并行迭代旧行和更新行，按 clustering 比较决定是新增、更新还是删除影响，见 `src/java/org/apache/cassandra/db/view/TableViews.java:210-268`。
- 对 partition deletion 剩余旧行，会生成删除旧 view entry 的更新，见 `src/java/org/apache/cassandra/db/view/TableViews.java:270-283`。
- `ViewUpdateGenerator` 根据 before/after row 产生 `NONE`、`NEW_ENTRY`、`DELETE_OLD`、`UPDATE_EXISTING`、`SWITCH_ENTRY`，见 `src/java/org/apache/cassandra/db/view/ViewUpdateGenerator.java:68-76` 和 `src/java/org/apache/cassandra/db/view/ViewUpdateGenerator.java:118-137`。
- `View.matchesViewFilter()` 同时检查 clustering 是否被 SELECT 选中，以及 row filter 是否满足，见 `src/java/org/apache/cassandra/db/view/View.java:150-154`。

## View Mutation 分发

- `StorageProxy.mutateMV()` 在节点 starting/joining/moving 时把 view mutations 写入本地 batchlog，避免 paired replicas 过期，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1021-1028`。
- 正常状态下，MV 使用 `ConsistencyLevel.ONE` 和 local batchlog cleanup；base token 由 base key 计算，view token 由 view mutation key 计算，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1031-1041`。
- `ViewUtils.getViewNaturalEndpoint(...)` 根据 base token/view token 找 paired endpoint，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1044-1050`。
- 若 paired endpoint 是本机且没有 pending replicas，可直接 `mutation.apply(writeCommitLog)` 并减少 batchlog cleanup 计数，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1064-1075`。

## 观测与排查

| 现象 | 重点指标/日志 | 代码依据 |
|---|---|---|
| CREATE VIEW 被拒绝 | `materialized_views_enabled`、transient replication、WHERE/TTL 限制 | `src/java/org/apache/cassandra/cql3/statements/schema/CreateViewStatement.java:113-347` |
| Base 写延迟升高 | `ViewLockAcquireTime`、`ViewReadTime`、write latency | `src/java/org/apache/cassandra/db/Keyspace.java:616-623`、`src/java/org/apache/cassandra/db/view/TableViews.java:167` |
| 写超时类型为 VIEW | MV lock 竞争或 view write 慢 | `src/java/org/apache/cassandra/db/Keyspace.java:561-576` |
| View 结果缺失/延迟 | local batchlog、range movement paired endpoint warn | `src/java/org/apache/cassandra/service/StorageProxy.java:1052-1060` |
| View build 未启动 | StorageService 未初始化时 reload 不提交 build task | `src/java/org/apache/cassandra/db/view/ViewManager.java:115-130` |

## 测试用例

- `test/unit/org/apache/cassandra/cql3/ViewTest.java`
- `test/unit/org/apache/cassandra/cql3/ViewSchemaTest.java`
- `test/unit/org/apache/cassandra/cql3/ViewFiltering1Test.java`
- `test/unit/org/apache/cassandra/cql3/ViewFiltering2Test.java`
- `test/unit/org/apache/cassandra/cql3/ViewComplexUpdatesTest.java`
- `test/unit/org/apache/cassandra/cql3/ViewComplexDeletionsTest.java`
- `test/unit/org/apache/cassandra/cql3/ViewPKTest.java`
- `test/unit/org/apache/cassandra/cql3/ViewRangesTest.java`
- `test/unit/org/apache/cassandra/db/view/ViewBuilderTaskTest.java`
- `test/unit/org/apache/cassandra/db/view/ViewUtilsTest.java`
- `test/unit/org/apache/cassandra/db/guardrails/GuardrailViewsPerTableTest.java`
- `test/long/org/apache/cassandra/cql3/ViewLongTest.java`

## 待继续

- 展开 `ViewBuilder`、`ViewBuilderTask`、system_distributed build status 和 view build resume。
- 展开 repair/streaming 与 MV：`materialized_views_on_repair_enabled`、view SSTable streaming、auto repair config。
- 展开 `ViewUtils.getViewNaturalEndpoint()` 的 paired replica 算法和 range movement corner cases。
