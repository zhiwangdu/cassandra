# Module: Flush Execution Disk Drift Checker

## 范围

`research/tools/check-flush-execution-disk-drift.py` 保护 `research/module-flush-execution-disk-pressure-matrix.md` 与当前源码、测试和索引的一致性。它聚焦 Flush 执行层、per-disk writer、disk boundaries、低空间/不可写目录、PostFlush/CommitLog 清理、StorageService/nodetool 触发和 metrics 观测。

## 设计目标

- 用 `ColumnFamilyStore.Flush`、`PostFlush` 和 `PerDiskFlushExecutors` 作为 flush switch/barrier/per-disk submit 的源码事实来源。
- 用 `Flushing.flushRunnables()`、`FlushRunnable`、`DiskBoundaries` 和 `Directories` 保护 disk boundary 拆分、writer 目录选择和低磁盘错误合同。
- 用 `StorageService`、`NodeProbe` 和 nodetool `Flush` 保护 user forced flush 与 drain flush 入口。
- 用 `TableMetrics` 保护 `PendingFlushes`、`MemtableSwitchCount`、`BytesFlushed` 和 `flushSizeOnDisk` 观测合同。
- 要求研究文档保留本轮 15 个 scenario IDs、测试基线和 `flush_disk_pressure_gap`。

## 解决的问题

- Flush 逻辑跨 `ColumnFamilyStore`、`Flushing`、`Directories`、`DiskBoundaries`、`StorageService` 和 tests，容易只维护 memtable 文档而漏掉磁盘压力边界。
- 低磁盘/慢盘风险往往不会被普通 `Util.flush(cfs)` 单元测试显式覆盖，需要把 source contract 与 explicit gap 固定下来。
- checker 可在不启动 Cassandra、不运行 dtest 的情况下发现源码重构导致 research 引用漂移。

## 设计取舍

- checker 使用精确字符串和文件存在性检查，不解析 Java AST；源码语义不变但 token 重构时，应同步更新 matrix 和 checker token。
- checker 不执行 unit/dtest；测试项只验证现有测试基线仍包含关键用例、helper 或断言。
- 文档检查验证 scenario IDs、关键类/配置/测试名、checker 命令和 gap，不约束 Markdown 表格布局。

## 场景 ID

- `flush_executor_topology_contract`
- `flush_force_switch_dirty_contract`
- `flush_barrier_commitlog_upper_bound_contract`
- `flush_postflush_commitlog_discard_contract`
- `flush_empty_memtable_reclaim_contract`
- `flush_disk_boundaries_split_contract`
- `flush_writer_location_space_contract`
- `flush_per_disk_submit_wait_contract`
- `flush_runnable_write_metrics_contract`
- `flush_failure_abort_transaction_contract`
- `flush_secondary_index_blocking_contract`
- `flush_storage_service_user_drain_contract`
- `flush_metrics_observability_contract`
- `flush_existing_test_baseline`
- `flush_disk_pressure_gap`

## 核心接口

- `check_source_tokens()`：按 path/token 列表验证源码合同。
- `check_test_tokens()`：验证测试基线仍包含 flush、commitlog recovery、observer、disk failure 和 nodetool flush 锚点。
- `check_doc_tokens()`：验证矩阵、checker 说明、README 和 source-map 覆盖场景 ID、命令、测试名和 gap。
- `--json`：输出 source/test/doc check 计数和失败项，适合 CI artifact。

## 生命周期

```text
developer changes ColumnFamilyStore.Flush, Flushing, Directories, DiskBoundaries, StorageService drain/flush, or TableMetrics flush metrics
  -> run python3 research/tools/check-flush-execution-disk-drift.py
  -> checker validates source/test/doc tokens
  -> source drift requires updating matrix + checker
  -> doc drift requires updating research references/index rows
```

## 运维关注点

- checker 只证明 research 与当前源码同步，不证明多目录低空间/慢盘组合压测已存在。
- 如果新增真实 distributed tests，应把 `flush_disk_pressure_gap` 拆成已覆盖项，并同步扩展 checker 的 test tokens。
- 适合与 memtable implementation/flush、commitlog durability、compaction operations 和 SSTable runtime drift checkers 一起运行。

## 命令

```bash
python3 research/tools/check-flush-execution-disk-drift.py
python3 research/tools/check-flush-execution-disk-drift.py --json
```
