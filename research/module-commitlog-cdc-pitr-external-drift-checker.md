# Module: CommitLog CDC/PITR External Drift Checker

## 目的

`research/tools/check-commitlog-cdc-pitr-external-drift.py` 是 CommitLog CDC/PITR external integration matrix 的 source/test/doc/gap checker。它不启动 Cassandra，不解析真实 commitlog 文件，只保护当前源码暴露给外部 CDC/PITR 系统的合同和当前没有真实外部 connector/rehearsal 的文件级事实。

## 覆盖范围

- CDC table option 到 `Mutation.trackedByCDC()` 的标记链。
- `CommitLogSegmentManagerCDC` 的 segment state、hard link、blocking/nonblocking backpressure、consumer 删除后 size recalculation。
- `_cdc.idx` offset 和 `COMPLETED` watermark。
- replay 后 CDC raw/index rebuild。
- `cdc_on_repair_enabled` 的 streaming/repair write path。
- `commitlog_archiving.properties`、`CommitLogArchiver` archive/restore command 和 PITR precision/cutoff。
- `CommitLog.recoverSegmentsOnDisk()`、`CommitLogReplayer.construct()`、`ReplayFilter` 和 `pointInTimeExceeded()`。
- `CommitLogMBean` / `CommitLogMetrics` 的外部观测入口。
- 缺口 negative scan：外部 CDC connector/consumer checkpoint、PITR rehearsal/backup script/dry-run 配置仍不存在。

## 场景 ID

- `commitlog_external_cdc_table_marking_contract`
- `commitlog_external_cdc_segment_state_contract`
- `commitlog_external_cdc_index_watermark_contract`
- `commitlog_external_cdc_space_backpressure_contract`
- `commitlog_external_cdc_consumer_delete_contract`
- `commitlog_external_cdc_replay_rebuild_contract`
- `commitlog_external_cdc_repair_streaming_contract`
- `commitlog_external_archiver_command_contract`
- `commitlog_external_restore_command_contract`
- `commitlog_external_pitr_cutoff_contract`
- `commitlog_external_replay_filter_snapshot_contract`
- `commitlog_external_observability_contract`
- `commitlog_external_cdc_consumer_gap`
- `commitlog_external_pitr_rehearsal_gap`
- `commitlog_external_existing_tests_baseline`

## 运行方式

```bash
python3 research/tools/check-commitlog-cdc-pitr-external-drift.py
```

JSON 输出：

```bash
python3 research/tools/check-commitlog-cdc-pitr-external-drift.py --json
```

## 失败处理

- source token 失败：重新审查 CDC raw、PITR replay、archive/restore 或 MBean/metrics contract，并同步矩阵。
- test token 失败：确认测试迁移还是覆盖删除；如果覆盖删除，在矩阵中保留 explicit gap。
- doc/scenario 失败：补齐矩阵、checker 说明、README 和 source-map 的场景 ID。
- gap scan 失败：仓库新增了外部 connector/rehearsal 配置或测试，需要补文件级字段、checkpoint、restore dry-run、timestamp audit 和运维 runbook 对照。
