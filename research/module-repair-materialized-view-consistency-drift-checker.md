# Repair Materialized View Consistency Drift Checker

## 范围

`research/tools/check-repair-materialized-view-consistency-drift.py` 是 source-only drift check，用来保护 `research/module-repair-materialized-view-consistency-matrix.md` 中的 repair + Materialized View consistency contract。

它不启动 Cassandra、不跑 JUnit，也不证明 repair+MV 数据正确性已经被真实 distributed test 覆盖。它只做四件事：

- 校验 repair receiver write-path gate、MV repair config、mutation replay、cleanup flush/abort、`Keyspace.apply()` view update、`TableViews` existing-row read、`ViewUpdateGenerator` action matrix、`StorageProxy.mutateMV()` paired endpoint/batchlog/metrics 等源码合同仍存在。
- 校验现有测试 baseline 仍存在：receiver gate unit test、普通 MV CQL update/delete tests、auto-repair MV config/describe tests 和 repair distributed baseline。
- 校验研究文档和索引仍引用所有 repair+MV consistency 场景 ID。
- 扫描 `test/distributed` 是否新增了同时包含 MV schema marker 和显式 repair invocation 的 Java 测试；如果发现，说明 `repair_mv_distributed_correctness_gap` 已变化，必须更新矩阵和 checker。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `repair_mv_receiver_write_path_gate` | `CassandraStreamReceiver.requiresWritePath()` 的 MV gate |
| `repair_mv_stream_operation_gate` | `StreamOperation.REPAIR`/`BULK_LOAD` 的 `requiresViewBuild` 标记 |
| `repair_mv_config_toggle_contract` | `materialized_views_on_repair_enabled` 默认值与 `DatabaseDescriptor` getter/setter |
| `repair_mv_replay_mutation_contract` | repair received SSTable 通过 scanner/throttle/`PartitionUpdate`/`Keyspace.apply()` replay |
| `repair_mv_cleanup_flush_abort_contract` | replay 后 force flush 并 abort streamed SSTable transaction |
| `repair_mv_keyspace_apply_view_contract` | `Keyspace.apply()` 中 MV lock、`pushViewReplicaUpdates()` 与 base write ordering |
| `repair_mv_existing_row_read_contract` | `TableViews` 为 view correctness 读取 existing base rows |
| `repair_mv_update_action_contract` | `ViewUpdateGenerator` 的 create/delete/update/switch action matrix |
| `repair_mv_view_replica_write_contract` | `StorageProxy.mutateMV()` paired endpoint 与 `Stage.VIEW_MUTATION` |
| `repair_mv_batchlog_pending_boundary` | starting/joining/moving、pending endpoint 和 local batchlog fallback |
| `repair_mv_metrics_observability_contract` | `ViewReadTime`、`ViewWrite`、`ViewWriteLatency` 和 MV lock metrics |
| `repair_mv_auto_repair_gate_contract` | auto-repair MV config 测试与 correctness test 的边界 |
| `repair_mv_existing_tests_baseline` | 当前分层测试 baseline |
| `repair_mv_distributed_correctness_gap` | 当前缺少 repair+MV distributed correctness dtest |

## 运行方式

```bash
python3 research/tools/check-repair-materialized-view-consistency-drift.py
python3 research/tools/check-repair-materialized-view-consistency-drift.py --json
```

成功时输出源码检查、测试检查、gap scan、文档检查和场景数量。失败时列出具体缺失 token、缺失文档场景或新增的 distributed repair+MV 候选测试文件。

## 更新规则

- 如果 `CassandraStreamReceiver`、`StreamOperation`、`Keyspace`、`TableViews`、`ViewUpdateGenerator`、`StorageProxy.mutateMV()` 的源码合同改变，先更新 matrix 的调用图和场景说明，再调整 checker token。
- 如果新增真正的 repair+MV distributed correctness test，不要只放过 gap scan；应把 `repair_mv_distributed_correctness_gap` 改为具体覆盖项，写明测试文件、repair 触发方式、base/view 断言和剩余缺口。
- 如果 distributed MV tests 或 repair tests 迁移到新文件，更新 test token checks，并确认它们是否真的同时覆盖 MV schema、repair execution 和数据一致性断言。
