# Module: CommitLog CDC/PITR External Integration Matrix

## 范围

本矩阵补充 `module-commitlog-cdc-pitr-runbook.md` 与 `module-commitlog-durability-replay-matrix.md`，聚焦 CommitLog 与外部系统交界：CDC consumer 读取 `cdc_raw` / `_cdc.idx` 的契约、CDC raw 空间和写入反压、repair/streaming CDC 语义、commitlog archive/restore 命令、PITR cutoff、replay filter、运维观测以及当前 checkout 缺少真实外部 CDC connector 与备份系统 PITR rehearsal 的文件级证据。

## 调用图

CDC 外部消费主线：

```text
table WITH cdc = true
  -> Mutation.trackedByCDC()
  -> CommitLog.add(mutation)
  -> CommitLogSegmentManagerCDC.allocate(...)
     -> permitSegmentMaybe(...)
     -> throwIfForbidden(...)
     -> CommitLogSegment.CDCState.CONTAINS
  -> CommitLogSegment.sync(...)
     -> CommitLogSegment.writeCDCIndexFile(desc, offset, complete)
  -> flush / segment recycle
     -> CDC raw hard link and _cdc.idx remain
  -> external consumer reads up to _cdc.idx offset
  -> external consumer deletes raw segment and index after downstream checkpoint
```

PITR 外部恢复主线：

```text
segment becomes unused
  -> CommitLog.discardCompletedSegments(...)
  -> segmentManager.archiveAndDiscard(segment)
  -> CommitLogArchiver.maybeArchive(segment)
     -> archive_command %path/%name

startup / recovery
  -> CommitLog.recoverSegmentsOnDisk()
     -> archive unmanaged live files
     -> CommitLogArchiver.maybeRestoreArchive()
        -> restore_command %from/%to
     -> CommitLogReplayer.construct(...)
     -> CommitLogReplayer.pointInTimeExceeded(...)
     -> ReplayFilter.filter(...)
     -> Keyspace.apply(... durableWrites=false ...)
```

## 场景矩阵

| 场景 ID | 源码锚点 | 现有测试 | 外部集成含义 |
|---|---|---|---|
| `commitlog_external_cdc_table_marking_contract` | `src/java/org/apache/cassandra/cql3/statements/schema/TableAttributes.java:154-155` 解析 `WITH cdc`；`src/java/org/apache/cassandra/db/Mutation.java:83-108` 聚合 table params，`trackedByCDC()` 暴露 mutation 级标记。 | `test/unit/org/apache/cassandra/cql3/CDCStatementTest.java:38-61` 覆盖 create/alter/disable CDC table option。 | 外部 consumer 只能依赖 commitlog mutation/table schema 过滤事件；raw segment 不是“只含 CDC 表”的队列。 |
| `commitlog_external_cdc_segment_state_contract` | `src/java/org/apache/cassandra/db/commitlog/CommitLogSegment.java:70-77` 定义 `PERMITTED/FORBIDDEN/CONTAINS`；`CommitLogSegmentManagerCDC.allocate()` 在 CDC mutation 分配后切成 `CONTAINS`，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:168-190`。 | `CommitLogSegmentManagerCDCTest.testSegmentFlaggingOnCreation()`、`testSwitchingCDCWriteModes()` 覆盖 state transition baseline。 | 一个 segment 只要含一条 CDC mutation 就会保留给 consumer；consumer 必须按 record/table 过滤。 |
| `commitlog_external_cdc_index_watermark_contract` | `src/java/org/apache/cassandra/db/commitlog/CommitLogSegment.java:374-385` 说明 `_cdc.idx` 第一行是 durable offset，`COMPLETED` 表示 segment 不再追加。 | `CommitLogSegmentManagerCDCTest.testCDCIndexFileWriteOnSync()`、`testCompletedFlag()` 覆盖 offset 和 completed flag。 | consumer 不能读到文件尾；只能解析 offset 之前的完整 durable records，未完成 segment 应保存 checkpoint 后重试。 |
| `commitlog_external_cdc_space_backpressure_contract` | `CommitLogSegmentManagerCDC.throwIfForbidden()` 在 blocking 模式抛 `CDCWriteException`，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:212-227`；nonblocking 模式删除最旧 raw segment，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:344-354`。 | `testCDCWriteFailure()`、`testNonblockingShouldMaintainSteadyDiskUsage()` 覆盖 blocking/nonblocking raw 空间行为。 | 严格 CDC 应保持 blocking 并监控 raw backlog；nonblocking 是允许 CDC 缺口的可用性取舍。 |
| `commitlog_external_cdc_consumer_delete_contract` | `deleteOldLinkedCDCCommitLogSegment()` 从最旧 raw segment 删除 segment 和 index，且不删除当前 allocating segment，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:86-131`；consumer 删除文件后 size tracker 重新计算，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:385-450`。 | `testCDCWriteFailure()` 通过删除 `cdc_raw` 模拟 consumer 释放空间；`testDeleteLinkOnDiscardNoCDC()` / `testRetainLinkOnDiscardCDC()` 覆盖 discard 文件边界。 | downstream checkpoint 必须先持久化，再删除 raw segment 和 `_cdc.idx`；删除就是 Cassandra 释放 CDC 空间的信号。 |
| `commitlog_external_cdc_replay_rebuild_contract` | `CommitLogReplayer.handleMutation()` 看到 CDC mutation 后记录 `sawCDCMutation`；replay completion 重建 raw hard link/index，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:512-515` 和 `module-commitlog-cdc-pitr-runbook.md`。 | `CommitLogSegmentManagerCDCTest.testReplayLogic()` 清空 `cdc_raw` 后 replay，确认 index 重建且 offset 不小于旧值。 | crash/restart 后 consumer 可能再次看到 replayed segment；下游必须幂等处理 duplicate delivery。 |
| `commitlog_external_cdc_repair_streaming_contract` | `CassandraStreamReceiver.cdcRequiresWriteCommitLog()` 和 `requiresWritePath()` 在 CDC 表且 `cdc_on_repair_enabled` 时让 streaming mutation 走 write path。 | `test/distributed/org/apache/cassandra/distributed/test/cdc/ToggleCDCOnRepairEnabledTest.java:37-95` 覆盖开关两种状态。 | repair/streaming 补数据是否进入 CDC 由 `cdc_on_repair_enabled` 决定；关闭会产生外部 CDC sink 看不到的历史补写。 |
| `commitlog_external_archiver_command_contract` | `conf/commitlog_archiving.properties:20-28` 定义 `archive_command` 与 `%path/%name`；`CommitLogArchiver.maybeArchive()` 等待 final sync 后替换 token 执行命令，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java:195-210`。 | `CommitLogArchiverTest.testArchiver()` 验证 archive command 生效。 | 归档脚本必须幂等并处理重复归档；Cassandra 不管理对象存储 retention。 |
| `commitlog_external_restore_command_contract` | `CommitLog.recoverSegmentsOnDisk()` 在 replay 前执行 `maybeRestoreArchive()`，见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:182-215`；`CommitLogArchiver.maybeRestoreArchive()` 校验 descriptor/version/compression 后执行 `%from/%to`，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java:270-331`。 | `CommitLogArchiverTest.testRestoreInDifferentPrecision()` 触发 restore + replay；descriptor/reader tests 覆盖格式错误。 | 恢复脚本应可 dry-run，且必须先恢复匹配 SSTable snapshot，再恢复 commitlog；只拷 commitlog 不证明 PITR 正确。 |
| `commitlog_external_pitr_cutoff_contract` | `CommitLogArchiver` 解析 `restore_point_in_time` 与 `precision`，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java:145-192`；`CommitLogReplayer.pointInTimeExceeded()` 用 mutation timestamp 做 cutoff，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:502-510`。 | `CommitLogArchiverTest.testRestoreInDifferentPrecision()` 覆盖 microsecond/millisecond cutoff。 | PITR 截止点受业务 `USING TIMESTAMP` 影响，不是 replay wall clock；备份 runbook 必须审计 timestamp 单位。 |
| `commitlog_external_replay_filter_snapshot_contract` | `CommitLogReplayer.construct()` 计算 per-table persisted intervals、truncation/PITR 交互和 `snapshot_commitlog_position` override，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:116-187`；`ReplayFilter.create()` 解析 `cassandra.replayList`，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:384-445`。 | `CommitLogTest.testReplayListProperty()` 和 archiver tests 覆盖 replay allow-list/PITR baseline。 | PITR rehearsal 需要验证 snapshot 基线、replay list 和 cutoff 组合，不应只证明单节点 replay 方法可调用。 |
| `commitlog_external_observability_contract` | `CommitLogMBean` 暴露 archive/restore config、active segments、pending archive、CDC block/write repair 开关，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogMBean.java:25-100`；`CommitLogMetrics` 暴露 waiting/size/pending/completed metrics。 | JMX/metrics checker 保护 metric wrapper；CommitLog durability checker 保护 MBean token。 | 外部 runbook 应同时监控 live commitlog、pending archive、`cdc_raw` backlog、oldest segment age、CDC write failures 和 replay logs。 |
| `commitlog_external_cdc_consumer_gap` | 当前 checkout 没有 source-owned Debezium/Kafka Connect/commitlog CDC connector、consumer checkpoint 或 sink integration test；只有 core CDC manager/unit tests 和文档。 | 本矩阵 checker 扫描 connector/consumer/checkpoint markers；`testCDCWriteFailure()` 只是删除文件模拟 consumer。 | 缺少真实 consumer crash/restart、schema evolution、partial segment 和 duplicate delivery 的端到端证明。 |
| `commitlog_external_pitr_rehearsal_gap` | 当前 checkout 没有 source-owned 对象存储/备份系统 PITR rehearsal、restore dry-run 或跨节点 snapshot+commitlog 演练配置；只有 `commitlog_archiving.properties` 示例与 unit test。 | 本矩阵 checker 扫描 PITR rehearsal/backup-script markers，并允许 core 示例配置存在。 | 生产恢复能力仍需外部演练证明：archive script 幂等、对象存储延迟、clock/timestamp audit、跨节点一致性。 |
| `commitlog_external_existing_tests_baseline` | 现有测试覆盖 CDC table option、raw 空间、index、replay rebuild、archive/restore precision、repair CDC 开关和 legacy commitlog reader。 | `CDCStatementTest`、`CommitLogSegmentManagerCDCTest`、`CommitLogArchiverTest`、`ToggleCDCOnRepairEnabledTest`、`CommitLogTest`、`CommitLogReaderTest` 是 baseline。 | 这些测试证明 Cassandra 内置 contract，不证明外部 connector 或备份系统完整。 |

## 运维判读

- CDC consumer 的安全读取边界是 `_cdc.idx` offset，不是 commitlog 文件大小。
- `cdc_block_writes=false` 会让 Cassandra 删除旧 raw segment，外部 sink 必须把它视为可能丢事件的运行模式。
- PITR 依赖 SSTable snapshot 基线 + archived commitlog + timestamp cutoff 三者一致。只验证 archive command 执行不等于恢复可用。
- `archive_command` / `restore_command` 是单命令执行，复杂逻辑必须封装脚本并自己处理锁、幂等、重试和远端存储一致性。
- 当前 research 只能重建 Cassandra 暴露的 CDC/PITR contract；外部 connector/backup rehearsal 仍是明确缺口。

## 当前缺口

- `commitlog_external_cdc_consumer_gap`：缺真实外部 CDC consumer/connector integration test，尤其是 checkpoint、crash/restart、schema evolution、partial segment、duplicate delivery。
- `commitlog_external_pitr_rehearsal_gap`：缺真实备份系统 PITR rehearsal，尤其是 snapshot 基线、archive script 幂等、restore dry-run、对象存储延迟、timestamp audit。
