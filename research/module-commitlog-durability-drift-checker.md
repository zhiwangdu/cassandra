# Module: CommitLog Durability Drift Checker

## 范围

`research/tools/check-commitlog-durability-drift.py` 保护 CommitLog durability/replay/CDC/PITR 研究的 source/test/doc 基线。它不运行 Cassandra，也不尝试 replay commitlog 文件；它验证关键源码入口、测试覆盖锚点、文档场景 ID 和索引是否仍然一致。

## 保护对象

- `CommitLog` append/recover/sync/discard/failure policy 主入口。
- `AbstractCommitLogService`、`BatchCommitLogService`、`GroupCommitLogService`、`PeriodicCommitLogService` 的 sync/lag/wait 语义。
- `AbstractCommitLogSegmentManager`、standard manager、CDC manager、`CommitLogSegment` 的 segment allocation/reclaim/CDC state/index。
- `CommitLogReader`、`CommitLogSegmentReader`、`CommitLogReadHandler`、`CommitLogReplayer` 的 replay/error/PITR/filter/CDC rebuild。
- `CommitLogDescriptor`、compressed/encrypted/direct/mmap segment implementations。
- `CommitLogArchiver` 和 `commitlog_archiving.properties`。
- `Config`、`DatabaseDescriptor`、`Mutation`、`TableAttributes`、`CassandraStreamReceiver`、`CommitLogMBean`、`CommitLogMetrics` 的配置/操作/metrics 面。
- CommitLog unit/distributed/long tests: sync service、failure policy、backpressure、CDC raw、PITR、segment reader、direct I/O、legacy encrypted fixtures、repair CDC、CDC CQL option 和 stress matrix。

## 场景 ID

- `commitlog_append_record_crc`
- `commitlog_sync_strategy_modes`
- `commitlog_sync_lag_marker`
- `commitlog_segment_allocation_reclaim`
- `commitlog_segment_clean_discard`
- `commitlog_cdc_raw_backpressure`
- `commitlog_cdc_index_contract`
- `commitlog_cdc_replay_rebuild`
- `commitlog_cdc_repair_streaming`
- `commitlog_archiver_pitr_restore`
- `commitlog_replay_filter_pitr`
- `commitlog_reader_error_policy`
- `commitlog_format_compression_encryption_io`
- `commitlog_config_validation_metrics`

## 运行方式

```bash
python3 research/tools/check-commitlog-durability-drift.py
```

JSON 输出：

```bash
python3 research/tools/check-commitlog-durability-drift.py --json
```

## 失败处理

- source token 失败：先确认源码入口是否迁移；迁移后同步更新 `module-commitlog-durability-replay-matrix.md` 和 checker token。
- test token 失败：确认测试是否重命名或覆盖被删除；如果覆盖被删除，在矩阵中保留 explicit gap。
- doc/scenario 失败：恢复被删场景，或用新的场景 ID 替代并同步所有索引。
