# Module: Compaction Control Observability Drift Checker

## 范围

`research/tools/check-compaction-control-observability-drift.py` 保护 `research/module-compaction-control-observability-matrix.md` 与当前源码、测试和索引的一致性。它聚焦 active compaction registry、`CompactionInfo` task id/map、stop-by-type/id、stop polling、global pause、`compactionstats -V`、`system_views.sstable_tasks` 和 active remaining write estimate。

## 设计目标

- 用 `ActiveCompactions` 与 `CompactionInfo.Holder` 保护 active task lifecycle、completion metrics 和 cooperative cancellation。
- 用 `CompactionManager`、`CompactionManagerMBean`、`NodeProbe` 和 nodetool `Stop` 保护 JMX/CLI stop control plane。
- 用 nodetool `CompactionStats` 与 `SSTableTasksTable` 保护 task id、target directory、progress 和 virtual table observability。
- 用 `OperationType` 和 `CompactionInfo.estimatedRemainingWriteToDiskBytes()` 保护 active task 空间估算合同。
- 要求研究文档保留本轮 13 个 scenario IDs、测试基线和 `compaction_live_cancel_metrics_gap`。

## 解决的问题

- Compaction 控制面跨 JMX、nodetool、virtual table、metrics 和内部 active registry；只看 compaction task pipeline 容易漏掉 operator stop 与 task id 的边界。
- `stopCompactionById()` 只是设置 stop flag，真正停止依赖 task 后续轮询；这个 cooperative 语义需要在文档中显式固定。
- checker 可在不启动 Cassandra、不运行 dtest 的情况下发现源码重构导致 research 引用漂移。

## 设计取舍

- checker 使用精确字符串和文件存在性检查，不解析 Java AST；源码语义不变但 token 重构时，应同步更新 matrix 和 checker token。
- checker 不执行 unit/dtest；测试项只验证已有测试基线仍包含关键用例、helper 或断言。
- 文档检查验证 scenario IDs、关键类/命令/测试名、checker 命令和 gap，不约束 Markdown 表格布局。

## 场景 ID

- `compaction_active_tracker_contract`
- `compaction_info_task_identity_contract`
- `compaction_stop_by_type_contract`
- `compaction_stop_by_id_contract`
- `compaction_holder_stop_poll_contract`
- `compaction_interrupt_for_sstable_contract`
- `compaction_global_pause_contract`
- `compactionstats_verbose_task_contract`
- `sstable_tasks_virtual_table_contract`
- `compaction_remaining_write_estimate_contract`
- `compaction_operation_type_stop_contract`
- `compaction_control_existing_tests_baseline`
- `compaction_live_cancel_metrics_gap`

## 核心接口

- `check_source_tokens()`：按 path/token 列表验证源码合同。
- `check_test_tokens()`：验证测试基线仍包含 active tracking、compactionstats、sstable_tasks、iterator stop 和 distributed active estimate 锚点。
- `check_doc_tokens()`：验证矩阵、checker 说明、README 和 source-map 覆盖场景 ID、命令、测试名和 gap。
- `--json`：输出 source/test/doc check 计数和失败项，适合 CI artifact。

## 生命周期

```text
developer changes ActiveCompactions, CompactionInfo, CompactionManager stop paths, nodetool stop/compactionstats, or SSTableTasksTable
  -> run python3 research/tools/check-compaction-control-observability-drift.py
  -> checker validates source/test/doc tokens
  -> source drift requires updating matrix + checker
  -> doc drift requires updating research references/index rows
```

## 运维关注点

- checker 只证明 research 与当前源码同步，不证明 live stop-by-id cancellation 已端到端覆盖。
- 如果新增真实 long-running compaction cancellation test，应把 `compaction_live_cancel_metrics_gap` 拆成已覆盖项，并同步扩展 checker 的 test tokens。
- 适合与 compaction operations、metrics registry、nodetool runbook 和 JMX compatibility drift checkers 一起运行。

## 命令

```bash
python3 research/tools/check-compaction-control-observability-drift.py
python3 research/tools/check-compaction-control-observability-drift.py --json
```
