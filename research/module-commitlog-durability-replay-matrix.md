# Module: CommitLog Durability Replay Matrix

## 范围

本模块把 CommitLog 的 durability、sync、segment lifecycle、CDC raw、PITR restore、reader/replay error policy 和测试覆盖整理成可漂移检查的运行矩阵。`research/module-commitlog.md` 保留基础写入/回放说明，`research/module-commitlog-deep-dive.md` 覆盖实现细节，`research/module-commitlog-cdc-pitr-runbook.md` 覆盖外部 CDC/PITR 操作，本模块重点保护这些结论和源码/测试锚点的一致性。

## 设计目标

- 写入先进入 CommitLog，再进入 memtable；`CommitLog.add()` 校验 mutation size、分配 segment、写 CRC 包裹的 record，并按 sync service 完成 durability 边界，见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:300-337`。
- `commitlog_sync` 的 periodic/batch/group 三种策略分别由 `PeriodicCommitLogService`、`BatchCommitLogService`、`GroupCommitLogService` 执行，构造分派见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:116-129`。
- segment manager 负责预创建 segment、等待可用 segment、空间不足触发 flush reclaim、切换 allocating segment、归档和丢弃 unused segment，入口见 `src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogSegmentManager.java:160-239`、`:246-263`、`:296-335`。
- replay 通过 `CommitLogReader`/`CommitLogSegmentReader` 校验 descriptor、sync marker CRC、mutation length/data CRC，再交给 `CommitLogReplayer` 做 persisted interval、PITR 和 replay filter 过滤，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReader.java:169-259`、`src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:116-187`。
- CDC 复用 commitlog segment，通过 hard link 和 `_cdc.idx` 暴露可消费 offset；raw 目录满时根据 `cdc_block_writes` 拒绝 CDC write 或删除旧 raw，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:169-190`、`:212-227`、`:344-354`。
- PITR 通过 `commitlog_archiving.properties` 的 archive/restore 命令接入外部备份系统，并用 `restore_point_in_time` 与 `precision` 决定 replay cutoff，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java:101-193`、`src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:502-510`。

## 场景矩阵

| 场景 ID | 运行语义 | 源码锚点 | 测试/缺口 |
|---|---|---|---|
| `commitlog_append_record_crc` | append record 包含 length CRC、serialized mutation、mutation CRC；写失败包装为 `FSWriteError` | `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:300-342` | `CommitLogTest.replaySimple()`、`CommitLogReaderTest` 覆盖 replay reader |
| `commitlog_sync_strategy_modes` | periodic 主要异步、batch 每写 request extra sync、group 按 window 等待 sync | `CommitLog.java:116-129`、`BatchCommitLogService.java:36-43`、`GroupCommitLogService.java:34-41`、`PeriodicCommitLogService.java:36-45` | `AbstractCommitLogServiceTest`、`BatchCommitLogTest`、`GroupCommitLogTest` |
| `commitlog_sync_lag_marker` | sync runnable 按 marker interval/commitlog sync interval 决定 flush 或 marker-only sync，并记录 flush lag | `AbstractCommitLogService.java:150-225`、`:231-268` | `AbstractCommitLogServiceTest.java:47-212` |
| `commitlog_segment_allocation_reclaim` | allocator 预创建可用 segment，空间不足时触发 dirty CFS flush reclaim；等待 segment allocation 进入 metrics | `AbstractCommitLogSegmentManager.java:163-239`、`:246-263`、`:337-348` | `CommitLogSegmentBackpressureTest.java:66-132` |
| `commitlog_segment_clean_discard` | flush 后 `discardCompletedSegments()` 标记 table clean，unused segment 归档并删除/保留 | `CommitLog.java:353-370`、`CommitLogSegment.java:555-586`、`AbstractCommitLogSegmentManager.java:405-413` | `CommitLogTest.testTruncateWithoutSnapshot()`、out-of-order flush/discard tests |
| `commitlog_cdc_raw_backpressure` | CDC raw 空间满时 blocking 模式拒绝 CDC mutation，nonblocking 模式删除旧 raw segment | `CommitLogSegmentManagerCDC.java:169-190`、`:212-227`、`:344-354` | `CommitLogSegmentManagerCDCTest.java:72-146` |
| `commitlog_cdc_index_contract` | `_cdc.idx` 第一行是 durable offset，segment 完成时第二行 `COMPLETED`；非 CDC segment discard 删除 hard link/index | `CommitLogSegment.java:363-385`、`CommitLogSegmentManagerCDC.java:66-83` | `CommitLogSegmentManagerCDCTest.java:149-262` |
| `commitlog_cdc_replay_rebuild` | replay 期间看到 CDC mutation 后重建 raw hard link 和 index，保证 CDC consumer 可继续读取 replayed segment | `CommitLogReplayer.java:191-235`、`:512-515` | `CommitLogSegmentManagerCDCTest.java:264-335` |
| `commitlog_cdc_repair_streaming` | repair/streaming 接收 CDC 表时，如果 `cdc_on_repair_enabled` 为 true，则走 write path 写 CommitLog/CDC raw | `CassandraStreamReceiver.java:176-224` | `ToggleCDCOnRepairEnabledTest.java:37-95` |
| `commitlog_archiver_pitr_restore` | archive command 在 segment 回收前执行，restore command 在 startup replay 前把 archived segment 放回 live commitlog 目录 | `CommitLogArchiver.java:195-237`、`:270-331`、`CommitLog.java:182-215` | `CommitLogArchiverTest.java:97-173`；仍缺真实备份系统 rehearsal |
| `commitlog_replay_filter_pitr` | replay filter 支持 keyspace/table allow-list；PITR cutoff 用 mutation timestamp 和 `precision` 转换 | `CommitLogReplayer.java:384-489`、`:502-510` | `CommitLogTest.testReplayListProperty()`、`CommitLogArchiverTest.testRestoreInDifferentPrecision()` |
| `commitlog_reader_error_policy` | reader 按 descriptor/header/sync marker/mutation CRC 判定错误；`COMMITLOG_IGNORE_REPLAY_ERRORS` 与 commit failure policy 决定跳过或失败 | `CommitLogSegmentReader.java:166-211`、`CommitLogReader.java:290-404`、`CommitLogReplayer.java:533-556` | `CommitLogReaderTest`、`CommitLogTest.replayWithBadSyncMarkerCRC()`、`CommitLogFailurePolicyTest` |
| `commitlog_format_compression_encryption_io` | descriptor header 保存 compression/encryption；reader 选择 compressed/encrypted/no-op segmenter；direct/mmap/standard writer 由 access mode 决定 | `CommitLogDescriptor.java:100-177`、`CommitLogSegmentReader.java:68-85`、`:295-369`、`DirectIOSegment.java:44-180`、`MemoryMappedSegment.java:40-125` | `SegmentReaderTest`、`DirectIOSegmentTest`、`DirectIOSegmentBytemanTest`、`CommitLogUpgradeTest` |
| `commitlog_config_validation_metrics` | config 校验 sync 参数、目录冲突、segment size、direct I/O 与 compression/encryption 兼容；metrics 暴露 waiting/size/pending/completed | `DatabaseDescriptor.java:498-529`、`:717-749`、`:891-901`、`:1497-1546`、`CommitLogMetrics.java:31-82` | 配置相关测试分散；metrics 已由 metrics registry checker 间接保护 |

## 调用图

```text
Local write
  -> CassandraKeyspaceWriteHandler.addToCommitLog(mutation)
  -> CommitLog.instance.add(mutation)
     -> mutation.validateSize(...)
     -> Mutation.serializer.serializedSize(...)
     -> segmentManager.allocate(mutation, totalSize)
        -> CommitLogSegment.allocate(mutation, size)
        -> CDC manager may reject or mark segment CONTAINS
     -> write length CRC
     -> write serialized mutation
     -> write mutation CRC
     -> alloc.markWritten()
     -> executor.finishWriteFor(alloc)
        -> Batch: requestExtraSync() + alloc.awaitDiskSync(...)
        -> Group: alloc.awaitDiskSync(...)
        -> Periodic: awaitSyncAt(...) only when lag exceeds block threshold
```

```text
Flush clean / segment recycle
  -> CommitLog.discardCompletedSegments(tableId, lowerBound, upperBound)
     -> segment.markClean(tableId, lowerBound, upperBound)
     -> if segment.isUnused()
        -> segmentManager.archiveAndDiscard(segment)
           -> archiver.maybeArchive(segment)
           -> maybeWaitForArchiving(segment)
           -> discardSegment(segment, deleteFile)
```

```text
Startup replay / PITR
  -> CommitLog.recoverSegmentsOnDisk()
     -> archiver.maybeArchive(unmanaged live files)
     -> archiver.maybeRestoreArchive()
     -> CommitLogReplayer.construct(...)
     -> CommitLogReader.readAllFiles(...)
        -> CommitLogDescriptor.readHeader(...)
        -> CommitLogSegmentReader sync section iterator
        -> CommitLogReader.readSection(...)
        -> CommitLogReplayer.handleMutation(...)
           -> replayFilter.filter(mutation)
           -> pointInTimeExceeded(mutation)
           -> Keyspace.apply(... durableWrites=false ...)
     -> CommitLogReplayer.blockForWrites()
```

## 配置与操作面

| 配置项 | 源码定义 | 运行影响 |
|---|---|---|
| `commitlog_directory` | `src/java/org/apache/cassandra/config/Config.java:388` | live segment 目录，不能与 data/local system/saved caches/hints 冲突 |
| `commitlog_total_space` | `Config.java:389-390` | segment manager reclaim/flush 压力边界 |
| `commitlog_sync` | `Config.java:391` | periodic/batch/group sync service 选择 |
| `commitlog_sync_group_window` | `Config.java:392-393` | group commit 等待窗口 |
| `commitlog_sync_period` | `Config.java:394-395` | periodic flush 周期 |
| `commitlog_segment_size` | `Config.java:396-397`、`DatabaseDescriptor.java:891-901` | segment 文件大小和 max mutation size 下界 |
| `commitlog_compression` | `Config.java:398` | compressed segment writer/reader |
| `commitlog_disk_access_mode` | `Config.java:401`、`DatabaseDescriptor.java:1497-1546` | legacy/direct/mmap/standard access mode，和 compression/encryption 有兼容限制 |
| `periodic_commitlog_sync_lag_block` | `Config.java:402-403` | periodic sync 落后时阻塞写入 |
| `transparent_data_encryption_options` | `Config.java:404` | encrypted commitlog descriptor/header 和 reader context |
| `cdc_enabled` | `Config.java:410`、`DatabaseDescriptor.java:242` | 选择 `CommitLogSegmentManagerCDC` |
| `cdc_block_writes` | `Config.java:413` | raw 空间满时 reject CDC write 或 delete old raw |
| `cdc_on_repair_enabled` | `Config.java:416` | repair/streaming CDC 表是否走 write path |
| `cdc_raw_directory` | `Config.java:417` | raw hard link 和 `_cdc.idx` 目录 |
| `cdc_total_space` | `Config.java:418-419` | CDC raw 空间预算 |
| `cdc_free_space_check_interval` | `Config.java:420-421` | raw 空间满后的重新检查间隔 |
| `commitlog_archiving.properties` | `conf/commitlog_archiving.properties:20-61` | archive/restore/PITR 外部命令和 cutoff |

## Metrics 与告警

- `CommitLog.WaitingOnSegmentAllocation`：等待 segment 分配，通常表示 commitlog 总空间、flush reclaim 或 CDC raw backpressure 影响写入。
- `CommitLog.WaitingOnCommit`：等待 sync，batch/group 直接影响写延迟，periodic lag blocking 时也会体现。
- `CommitLog.WaitingOnFlush`：sync runnable flush buffer 到磁盘耗时。
- `CommitLog.OverSizedMutations`：mutation size validation 失败计数。
- `CommitLog.PendingTasks` / `CompletedTasks`：commitlog executor pending/completed。
- `CommitLog.TotalCommitLogSize`：active commitlog manager on-disk size；不等同于外部 `cdc_raw` backlog。
- CDC 仍需外部监控 `cdc_raw` bytes、segment count、oldest age、missing `_cdc.idx`、index offset stagnation 和 `CDCWriteException` 日志。

## 故障与测试缺口

- `commitlog_reader_error_policy` 有 corruption/replay policy 覆盖，但真实生产恢复仍需要 snapshot + PITR rehearsal 级测试。
- `commitlog_archiver_pitr_restore` 只有本地 archive/PITR precision 单测，缺少对象存储/外部脚本幂等/跨节点 snapshot 一致性测试。
- `commitlog_cdc_raw_backpressure` 有 raw 空间和 mode 单测，但缺少真实 CDC consumer crash/restart、schema evolution、partial segment 和 duplicate delivery integration。
- `commitlog_config_validation_metrics` 的 metrics 值没有 dedicated CommitLog metrics regression，只由 registry/export checker 间接保护 metric name。
- `commitlog_format_compression_encryption_io` 有 segmenter/direct/legacy encrypted fixture 覆盖，但 mixed-version streaming/upgrade 场景仍依赖更高层测试。
