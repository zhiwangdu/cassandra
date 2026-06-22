# Module: Compaction Operations Drift Checker

## 范围

`research/tools/check-compaction-operations-drift.py` 保护 `research/module-compaction-operations-failure-matrix.md` 的 source/test/doc 基线，重点覆盖 compaction 运行时语义而不是策略算法细节。

## 保护对象

- `CompactionManager`：rate limiter、background submission backpressure、automatic SSTable upgrade、all-SSTable operations、stop-by-type/stop-by-id、failure metric increments。
- `CompactionStrategyManager`：repair-finished cleanup 优先级、holder task sorting、upgrade task discovery、pause/resume/startup boundary。
- `CompactionTask`：snapshot、fully expired SSTable、available disk space check、scope reduction、abort/reduced/dropped metrics、history/bytes metrics。
- `CompactionIterator`：garbage skip、purger/Paxos purger、duplicate row checker、index compaction hook、row cache invalidation、中断边界。
- `CompactionParams`：class/enabled/min/max/provide_overlapping_tombstones、threshold=0 removal、strategy validation。
- `CompactionMetrics`、`CompactionManagerMBean`、`ColumnFamilyStoreMBean`、`NodeProbe`、nodetool command files：运营可见性和操作面。
- tests：`CompactionDiskSpaceTest`、`CompactionTaskTest`、`CompactionStrategyManagerTest`、`CompactionIteratorTest`、`CompactionStatsTest`、`CompactTest`、strategy option tests。

## 场景 ID

checker 要求以下 ID 同时出现在矩阵文档、checker 说明和脚本中：

- `compaction_background_scheduler_backpressure`
- `compaction_strategy_manager_repair_promotion`
- `compaction_strategy_params_validation`
- `compaction_task_snapshot_space_reduction`
- `compaction_iterator_purge_index_cache`
- `compaction_rate_limit_bootstrap_boundary`
- `compaction_auto_upgrade_boundary`
- `compaction_metrics_observability`
- `compaction_jmx_nodetool_surface`
- `compaction_strategy_tuning_matrix`
- `compaction_disk_space_failure_coverage`
- `compaction_existing_tests_baseline`

## 运行方式

```bash
python3 research/tools/check-compaction-operations-drift.py
```

可选输出 JSON：

```bash
python3 research/tools/check-compaction-operations-drift.py --json
```

## 失败处理

- 如果源码 token 丢失，先确认 Cassandra 源码是否迁移了入口；迁移后更新矩阵引用和 checker token。
- 如果测试 token 丢失，确认是测试重命名还是覆盖被删除；覆盖被删除时要在矩阵里保留 gap，并调整 checker 的 gap token。
- 如果 scenario ID 丢失，说明矩阵维度被删，需要恢复或显式替换为新的场景 ID。

