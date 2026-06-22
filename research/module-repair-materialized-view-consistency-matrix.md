# Repair Materialized View Consistency Matrix

## 研究目标

Repair + Materialized View 的核心风险不是 streaming 能否完成，而是 streamed base table SSTable 在接收端是否重新经过普通 mutation write path，从而触发 view row 的创建、更新、旧 entry 删除、paired view replica 写入和本地 batchlog 兜底。这个矩阵把 `CassandraStreamReceiver`、`Keyspace.apply()`、`TableViews`、`ViewUpdateGenerator` 与 `StorageProxy.mutateMV()` 串成一条可验证的 correctness contract，并把当前缺少的 distributed 数据正确性测试显式固化为 gap。

## 场景矩阵

| 场景 ID | 保护内容 | 源码/测试锚点 | 风险 |
|---|---|---|---|
| `repair_mv_receiver_write_path_gate` | receiver 只有在 repair operation、base table 有 MV 且 `materialized_views_on_repair_enabled=true` 时为 MV 进入 write path；CDC 和 `streamToMemtable()` 是独立触发条件 | `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:169-200`、`test/unit/org/apache/cassandra/db/streaming/CassandraStreamReceiverTest.java:69-152` | 条件漂移会让 repair 直接 attach SSTable，MV 不会 replay |
| `repair_mv_stream_operation_gate` | `StreamOperation.REPAIR` 和 `BULK_LOAD` 标记 `requiresViewBuild=true`，bootstrap/rebuild/decommission 不走同一 MV replay 语义 | `src/java/org/apache/cassandra/streaming/StreamOperation.java:20-68` | 错误扩散到 topology streaming 会改变 ingest 成本和 MV 行为 |
| `repair_mv_config_toggle_contract` | `materialized_views_on_repair_enabled` 默认 true，并由 `DatabaseDescriptor.is/setMaterializedViewsOnRepairEnabled()` 暴露给测试和运行时 | `src/java/org/apache/cassandra/config/Config.java:595-600`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4227-4234` | 配置默认值或 setter 漂移会改变 repair 后 MV 一致性预期 |
| `repair_mv_replay_mutation_contract` | write-path repair 扫描接收 SSTable、按 `MAX_ROWS_PER_BATCH` 拆 partition、构造 `PartitionUpdate` 并调用 `Keyspace.apply()` | `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:202-224` | 大 partition 或大 repair range 会变成 mutation replay 压力；若跳过 apply，MV/2i/CDC 都可能不更新 |
| `repair_mv_cleanup_flush_abort_contract` | replay 后 `cleanup()` 强制 flush `STREAMS_RECEIVED` 并 abort/delete streamed SSTable transaction，因为数据已通过 write path 写入 | `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:291-301` | 若未 flush 或未 abort，可能出现重复数据、泄漏 SSTable 或 commitlog/CDC 边界不清 |
| `repair_mv_keyspace_apply_view_contract` | `Keyspace.apply()` 先获取 MV lock，调用 `pushViewReplicaUpdates()`，再写 base table，并在 base 完成后更新 `baseComplete` | `src/java/org/apache/cassandra/db/Keyspace.java:560-657` | view mutation 依赖 base completion latency；lock timeout 会以 `WriteType.VIEW` 暴露 |
| `repair_mv_existing_row_read_contract` | `TableViews.pushViewReplicaUpdates()` 读取 existing base rows，再用 streamed update 计算最小 view mutation | `src/java/org/apache/cassandra/db/view/TableViews.java:143-170`、`src/java/org/apache/cassandra/db/view/TableViews.java:390-467` | 不读旧状态就无法删除旧 view PK entry 或判断 filter/liveness 变化 |
| `repair_mv_update_action_contract` | `ViewUpdateGenerator` 区分 `NEW_ENTRY`、`DELETE_OLD`、`UPDATE_EXISTING`、`SWITCH_ENTRY`，覆盖 view PK 非 base-PK 列、filter 和 liveness | `src/java/org/apache/cassandra/db/view/ViewUpdateGenerator.java:118-217`、`src/java/org/apache/cassandra/db/view/ViewUpdateGenerator.java:266-419` | 修复只断言 insert 会漏掉 update/delete/switch entry 后的旧 view row 残留 |
| `repair_mv_view_replica_write_contract` | `StorageProxy.mutateMV()` 通过 base token 和 view token 找 paired endpoint，本地可直接 apply，远端通过 `Stage.VIEW_MUTATION` 写入 | `src/java/org/apache/cassandra/service/StorageProxy.java:1010-1112` | 只测单节点或 RF=1 不能证明远端 view replica 正确 |
| `repair_mv_batchlog_pending_boundary` | 启动/加入/移动、无 paired endpoint 或 pending endpoints 时使用本地 batchlog/ordinary write 兜底 | `src/java/org/apache/cassandra/service/StorageProxy.java:1021-1106` | pending range 或拓扑变化时 repair+MV 可能依赖 batchlog replay 才最终一致 |
| `repair_mv_metrics_observability_contract` | 成本暴露在 `ViewReadTime`、`ViewWrite`、`ViewWriteLatency`、MV lock acquire 和 flush/write metrics 上 | `src/java/org/apache/cassandra/db/view/TableViews.java:167`、`src/java/org/apache/cassandra/service/StorageProxy.java:1111`、`src/java/org/apache/cassandra/service/StorageProxy.java:1425-1442`、`src/java/org/apache/cassandra/db/Keyspace.java:616-623` | repair 成功但 MV 延迟或 backlog 异常需要从这些指标定位 |
| `repair_mv_auto_repair_gate_contract` | auto-repair 已有 MV scheduling/config 计数测试，但不等价于 streaming repair 数据正确性测试 | `test/unit/org/apache/cassandra/repair/autorepair/AutoRepairParameterizedTest.java:173-204`、`test/distributed/org/apache/cassandra/distributed/test/repair/AutoRepairFlagToggleTest.java:45-128` | auto-repair flag/describe 覆盖容易被误认为 MV repair correctness coverage |
| `repair_mv_existing_tests_baseline` | 当前测试覆盖 receiver gate、MV update generator 普通 CQL 行为、repair dtest baseline 和 distributed MV schema/describe baseline，但没有交叉 correctness dtest | `test/unit/org/apache/cassandra/db/streaming/CassandraStreamReceiverTest.java:69-152`、`test/unit/org/apache/cassandra/cql3/ViewFiltering1Test.java:81-230`、`test/distributed/org/apache/cassandra/distributed/test/RepairTest.java:136-196`、`test/distributed/org/apache/cassandra/distributed/test/repair/AutoRepairFlagToggleTest.java:45-128` | 分层测试都绿仍不能证明 repair streaming 后 MV 数据一致 |
| `repair_mv_distributed_correctness_gap` | 当前 `test/distributed` 没有同时创建 MV、执行 repair、并断言 base/view 数据一致的 Java test | `research/tools/check-repair-materialized-view-consistency-drift.py` gap scan | 需要新增真实 2+ node distributed test 才能关闭 |

## 调用图

```text
repair streaming receive
  -> StreamOperation.REPAIR.requiresViewBuild() == true
  -> CassandraStreamReceiver.requiresWritePath(cfs)
     -> cdcRequiresWriteCommitLog(cfs)
     -> cfs.streamToMemtable()
     -> hasViews(cfs)
        -> View.findAll(cfs.metadata.keyspace, cfs.getTableName())
     -> DatabaseDescriptor.isMaterializedViewsOnRepairEnabled()
  -> CassandraStreamReceiver.finished()
     -> sendThroughWritePath(cfs, readers)
        -> reader.getScanner()
        -> ThrottledUnfilteredIterator.throttle(scanner, MAX_ROWS_PER_BATCH)
        -> PartitionUpdate.fromIterator(..., ColumnFilter.all(cfs.metadata()))
        -> Keyspace.apply(new Mutation(update), writeCDCCommitLog, true, false)
           -> acquire MV lock through ViewManager.acquireLockFor()
           -> viewManager.forTable(baseTableId).pushViewReplicaUpdates(update, makeDurable, baseComplete)
              -> updatedViews(update)
              -> readExistingRowsCommand(update, views, nowInSec)
              -> command.executeLocally()
              -> generateViewUpdates(views, updates, existings, nowInSec, false)
                 -> ViewUpdateGenerator.addBaseTableUpdate()
                 -> NEW_ENTRY / DELETE_OLD / UPDATE_EXISTING / SWITCH_ENTRY
              -> StorageProxy.mutateMV(baseKey, viewMutations, writeCommitLog, baseComplete, requestTime)
                 -> ViewUtils.getViewNaturalEndpoint(replicationStrategy, baseToken, viewToken)
                 -> local mutation.apply() or asyncWriteBatchedMutations(..., Stage.VIEW_MUTATION)
                 -> local batchlog when topology/pending endpoint requires it
           -> cfs.getWriteHandler().write(base update, ctx, updateIndexes=false)
           -> baseComplete.set(currentTimeMillis())
  -> CassandraStreamReceiver.cleanup()
     -> cfs.forceBlockingFlush(STREAMS_RECEIVED)
     -> abort streamed SSTable transaction
```

## 配置项

| 配置项 | 默认 | 作用 |
|---|---:|---|
| `materialized_views_enabled` | `false` | 是否允许 MV schema/use；测试通过 `DatabaseDescriptor.setMaterializedViewsEnabled(true)` 打开。见 `src/java/org/apache/cassandra/config/Config.java:595-596` |
| `materialized_views_on_repair_enabled` | `true` | repair/internode streaming 是否为 MV 走 write path replay。见 `src/java/org/apache/cassandra/config/Config.java:598-600` |
| `cassandra.streaming.requires_cdc_replay` / CDC on repair | 运行时属性/配置 | CDC table 可独立触发 write path，并决定 repair replay 是否写 commitlog。见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:174-183` |

## Metrics 与日志

- `ViewReadTime` 记录为生成 view mutation 读取 existing base rows 的耗时，见 `src/java/org/apache/cassandra/db/view/TableViews.java:167` 与 `src/java/org/apache/cassandra/metrics/TableMetrics.java:796`。
- `ViewWrite` 与 `ViewWriteLatency` 记录 view mutation dispatch 和 base-complete 延迟，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1111`、`src/java/org/apache/cassandra/service/StorageProxy.java:1437-1441`、`src/java/org/apache/cassandra/metrics/ViewWriteMetrics.java:27-39`。
- MV lock acquire time 只为 droppable writes 记录，repair replay 需要结合 write stage、flush、view read/write metrics 观察，见 `src/java/org/apache/cassandra/db/Keyspace.java:616-623`。
- repair receiver attach path有 stream debug 日志；write-path replay 不走 `cfs.addSSTables()` 的 attach 日志，失败通常从 streaming session failure、view update error 和 flush/commitlog 异常定位，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:258-285`、`src/java/org/apache/cassandra/db/Keyspace.java:641-649`。

## 运维关注点

- `materialized_views_on_repair_enabled=true` 把 repair 接收端变成 mutation replay：吞吐受 SSTable scan、partition throttling、MV existing-row read、view mutation write、flush 和 batchlog 共同影响。
- `materialized_views_on_repair_enabled=false` 会恢复普通 SSTable attach 语义，但 repair 不负责把 base SSTable 中的数据 replay 到 MV；这是一致性语义改变，不只是性能开关。
- 单节点或 RF=1 只能证明本地 MV mutation 生成，不足以证明 paired endpoint、pending endpoint 和 local batchlog 兜底。
- 数据正确性测试应覆盖 insert、update 影响 view PK、delete/tombstone、filter/liveness 变化、repair 前后 base/view 对齐，以及至少一个远端 view replica 写入场景。

## 性能瓶颈

- `sendThroughWritePath()` 会扫描 repair 收到的每个 SSTable，并按 `MAX_ROWS_PER_BATCH` 拆 partition，宽 partition 会放大 heap 和 mutation apply 成本。
- `readExistingRowsCommand()` 在 deletion 或 filter/liveness 判断场景下可能读取更多 base columns/rows；多个 views 会退化为 `ColumnFilter.all(metadata)`。
- `StorageProxy.mutateMV()` 对非本地 paired endpoint 先写本地 batchlog，再异步发送 view mutation；view backlog 会增加 repair 完成后收敛时间。
- `cleanup()` 的 `forceBlockingFlush(STREAMS_RECEIVED)` 会把 replay 产生的 memtable 压力转化为同步 flush 延迟。

## 常见故障

| 现象 | 可能根因 | 证据 |
|---|---|---|
| repair 成功但 MV 缺行 | `materialized_views_on_repair_enabled=false`、receiver 未走 write path、或 distributed test 只验证 base table | `CassandraStreamReceiver.requiresWritePath()` 与 config token |
| MV 有旧 view PK 残留 | update 改变 view PK 或 filter/liveness 时没有读 existing row 或没有触发 `DELETE_OLD`/`SWITCH_ENTRY` | `TableViews.readExistingRowsCommand()`、`ViewUpdateGenerator.updateAction()` |
| repair 期间 view write 延迟增大 | paired endpoint 远端写、batchlog 兜底、pending range 或 view mutation stage backlog | `StorageProxy.mutateMV()`、`ViewWriteLatency` |
| streaming 接收后磁盘出现临时 SSTable | write-path replay 后 cleanup 前的 offline transaction；最终应 flush replay 数据并 abort streamed SSTable | `CassandraStreamReceiver.cleanup()` |

## 测试覆盖与缺口

- `CassandraStreamReceiverTest` 覆盖 repair/bulk-load、CDC、MV 和配置开关对 `requiresWritePath()` 的影响，见 `test/unit/org/apache/cassandra/db/streaming/CassandraStreamReceiverTest.java:69-152`。
- `ViewFiltering*Test` 和 `ViewFiltering1Test` 覆盖普通 CQL 下 view row create/update/delete/filter 行为，见 `test/unit/org/apache/cassandra/cql3/ViewFiltering1Test.java:81-230`。
- `AutoRepairParameterizedTest` 覆盖 MV repair scheduling/config metrics，但不是 streaming repair 数据正确性，见 `test/unit/org/apache/cassandra/repair/autorepair/AutoRepairParameterizedTest.java:173-204`、`test/unit/org/apache/cassandra/repair/autorepair/AutoRepairParameterizedTest.java:398-429`。
- `AutoRepairFlagToggleTest` 是 distributed MV schema/describe/accessibility baseline；它没有执行 repair，见 `test/distributed/org/apache/cassandra/distributed/test/repair/AutoRepairFlagToggleTest.java:45-128`。
- 当前缺口：需要新增 2+ node distributed test，创建 base table + MV，制造副本不一致，执行 `nodetool repair` 或 `StorageService.instance.repair()`，并断言 repair 后 base rows 与 MV rows 在本地/远端 view replica 上一致。
