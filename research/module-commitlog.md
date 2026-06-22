# Module: CommitLog

## 范围

本模块覆盖 CommitLog 写入、segment 管理、sync、replay 和常见配置边界。CDC、archiver/PITR、encryption、compression、direct I/O 和 sync service 深水区已在 `research/module-commitlog-deep-dive.md` 展开。

## 设计目标

CommitLog 是 Cassandra 本地写入 durability 的核心。普通写入在进入 Memtable 前先序列化到 CommitLog segment；节点崩溃后，尚未 flush 到 SSTable 的 mutation 通过 CommitLog replay 恢复。

设计目标：

- 追加式顺序写减少随机 I/O。
- 支持 periodic、batch、group 三种 sync 策略。
- 以 segment 为单位管理磁盘空间、CDC 状态、dirty table intervals 和 replay。
- Flush 完成后按 table 的 commitlog position 标记 segment clean，回收或归档不再需要的 segment。

## 解决的问题

- Memtable 是内存结构，进程崩溃会丢失；CommitLog 记录 mutation 用于 restart replay。
- 多个 table 共享 CommitLog segment，需要记录每个 table 的 dirty/clean interval。`CommitLogSegment` 持有 `tableDirty` 与 `tableClean`，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegment.java:123-127`。
- commitlog_sync 策略需要在延迟与 durability 之间取舍；构造时根据 `DatabaseDescriptor.getCommitLogSync()` 选择 executor，见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:116-129`。
- Flush 完成后需要释放已持久化数据对应的 segment：`discardCompletedSegments()` 标记 clean 并归档/丢弃 unused segment，见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:353-370`。

## 设计取舍

- 所有 durable table 默认共享全局 CommitLog，而不是每表日志，降低文件数量但需要 per-table dirty interval 管理。
- 追加路径先序列化 mutation 到 scratch buffer，再向 segment allocation buffer 写入 length/checksum/mutation/checksum，见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:306-326`。
- Segment 写入使用 checksum 检测部分写/损坏，replay 阶段可以定位有效数据。
- 持久化 memtable 可以声明跳过 CommitLog，但会影响 point-in-time restore 和 CDC，接口说明见 `src/java/org/apache/cassandra/db/memtable/Memtable.java:88-108`。

## 核心类

| 类 | 作用 |
|---|---|
| `CommitLog` | 全局 commitlog 管理器、MBean、append/recover/sync/segment clean 入口。类定义：`src/java/org/apache/cassandra/db/commitlog/CommitLog.java:75` |
| `CommitLogSegment` | 单个 segment 的 buffer、sync marker、dirty/clean interval、CDC state。类定义：`src/java/org/apache/cassandra/db/commitlog/CommitLogSegment.java:66` |
| `AbstractCommitLogSegmentManager` | segment 分配、回收、归档、空间管理的抽象基类 |
| `CommitLogSegmentManagerStandard` | 标准 segment manager，类定义：`src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerStandard.java:24` |
| `CommitLogSegmentManagerCDC` | CDC 场景 segment manager，类定义：`src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:48` |
| `CommitLogReplayer` | restart/recover path 的 replay 控制器。类定义：`src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:72` |
| `CommitLogReader` | 读取 segment 内容并回调 replay handler。类定义：`src/java/org/apache/cassandra/db/commitlog/CommitLogReader.java:50` |
| `CommitLogArchiver` | archive/restore point-in-time 支持。类定义：`src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java:55` |

## 核心接口

- `CommitLogMBean`：JMX 暴露 recover/sync 等管理能力；`CommitLog` 注册 MBean 见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:92-96`。
- `CommitLogReadHandler`：replay 读取回调接口；`CommitLogReplayer implements CommitLogReadHandler`，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:72`。
- `Memtable.Factory.writesShouldSkipCommitLog()` 和 `writesAreDurable()`：让特殊 memtable 修改 commitlog replay/append 语义，见 `src/java/org/apache/cassandra/db/memtable/Memtable.java:88-108`。

## 核心数据结构

- `CommitLogPosition`：segment id + offset 的位置标识，类定义见 `src/java/org/apache/cassandra/db/commitlog/CommitLogPosition.java:35`。
- `Allocation`：segment manager 为一次 mutation 分配的写入空间，`CommitLog.add()` 调用 `segmentManager.allocate(mutation, totalSize)`，见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:309-312`。
- `CommitLogDescriptor`：segment 文件名、压缩、加密上下文，segment 构造时生成，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegment.java:153-157`。
- `tableDirty` / `tableClean`：segment 中每个 table 的未 flush 区间和已 clean 区间，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegment.java:123-127`。
- `cfPersisted`：replay 期间每表已持久化区间过滤器，构造见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:116-155`。

## 生命周期

```text
Startup:
  CassandraDaemon.setup()
    -> CommitLog.instance.start()
       -> segmentManager.start()
       -> executor.start()
    -> CommitLog.instance.recoverSegmentsOnDisk()

Write:
  CassandraKeyspaceWriteHandler.beginWrite()
    -> addToCommitLog(mutation)
       -> CommitLog.instance.add(mutation)
          -> Mutation.serializer.serialize(...)
          -> segmentManager.allocate(...)
          -> write length/checksum/mutation/checksum
          -> alloc.markWritten()
          -> executor.finishWriteFor(alloc)
          -> return CommitLogPosition

Flush clean:
  ColumnFamilyStore.Flush/PostFlush
    -> CommitLog.instance.discardCompletedSegments(tableId, lowerBound, upperBound)
       -> segment.markClean(...)
       -> archiveAndDiscard(segment) if unused
```

## 调用链

- 启动 CommitLog：`CassandraDaemon.setup()` 调用 `CommitLog.instance.start()`，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:256`；`CommitLog.start()` 启动 segment manager 和 executor，见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:140-155`。
- 写入 CommitLog：`CassandraKeyspaceWriteHandler.addToCommitLog()` 调用 `CommitLog.instance.add(mutation)`，见 `src/java/org/apache/cassandra/db/CassandraKeyspaceWriteHandler.java:67-99`。
- 追加实现：`CommitLog.add()` 序列化 mutation、分配 segment 空间、写 checksum、完成 sync 策略，见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:300-337`。
- Replay：`CommitLog.recoverFiles()` 创建 `CommitLogReplayer` 并 `blockForWrites()`，见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:220-230`。
- Clean：`CommitLog.discardCompletedSegments()` 标记 table clean 并回收 unused segment，见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:353-370`。

## 配置项

| 配置项 | 定义位置 | 默认/作用 |
|---|---|---|
| `commitlog_directory` | `src/java/org/apache/cassandra/config/Config.java:388`，模板 `conf/cassandra.yaml:408` | segment 存储目录 |
| `commitlog_total_space` | `src/java/org/apache/cassandra/config/Config.java:389-390`，模板 `conf/cassandra.yaml:883` | commitlog 总空间上限 |
| `commitlog_sync` | `src/java/org/apache/cassandra/config/Config.java:391`，模板 `conf/cassandra.yaml:619-636` | `periodic`、`batch`、`group` |
| `commitlog_sync_group_window` | `src/java/org/apache/cassandra/config/Config.java:392-393` | group sync 等待窗口 |
| `commitlog_sync_period` | `src/java/org/apache/cassandra/config/Config.java:394-395`，模板 `conf/cassandra.yaml:636` | periodic sync 周期 |
| `commitlog_segment_size` | `src/java/org/apache/cassandra/config/Config.java:396-397`，校验 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:891-901` | segment 大小，默认 32MiB |
| `commitlog_compression` | `src/java/org/apache/cassandra/config/Config.java:398` | commitlog 压缩 |
| `commitlog_disk_access_mode` | `src/java/org/apache/cassandra/config/Config.java:401`，模板 `conf/cassandra.yaml:678` | legacy/direct/auto 等访问模式 |
| `periodic_commitlog_sync_lag_block` | `src/java/org/apache/cassandra/config/Config.java:402-403` | periodic sync 落后时阻塞写入 |
| `cdc_enabled`、`cdc_block_writes`、`cdc_raw_directory`、`cdc_total_space` | `src/java/org/apache/cassandra/config/Config.java:409-421` | CDC 对 commitlog segment 管理和写入拒绝策略有影响 |

## Metrics

`CommitLogMetrics` 定义位置：`src/java/org/apache/cassandra/metrics/CommitLogMetrics.java:31-82`。

关键指标：

- `CompletedTasks`：executor 完成任务数，注册见 `src/java/org/apache/cassandra/metrics/CommitLogMetrics.java:58-66`。
- `PendingTasks`：executor 待处理任务数，注册见 `src/java/org/apache/cassandra/metrics/CommitLogMetrics.java:67-73`。
- `TotalCommitLogSize`：segment manager 磁盘占用，注册见 `src/java/org/apache/cassandra/metrics/CommitLogMetrics.java:74-80`。
- `WaitingOnSegmentAllocation`：等待 segment 分配耗时，定义见 `src/java/org/apache/cassandra/metrics/CommitLogMetrics.java:41-52`。
- `WaitingOnCommit`：等待 commit/sync 耗时，定义见 `src/java/org/apache/cassandra/metrics/CommitLogMetrics.java:43-54`。
- `WaitingOnFlush`：flush buffer 到磁盘耗时，定义见 `src/java/org/apache/cassandra/metrics/CommitLogMetrics.java:45-54`。
- `OverSizedMutations`：过大 mutation 计数，定义见 `src/java/org/apache/cassandra/metrics/CommitLogMetrics.java:47-55`。

## 日志

- segment unused：`logger.debug("Commit log segment {} is unused", segment)`，见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:366-369`。
- replay 中 point-in-time restore 与 truncation 处理会记录 info，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:136-142`。
- 写入失败通常包装为 `FSWriteError`，位置见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:327-342`。

## 运维关注点

- `TotalCommitLogSize` 持续接近上限通常表示 memtable flush/segment clean 跟不上。
- `WaitingOnSegmentAllocation` 非零说明 commitlog segment 分配或磁盘空间成为写入瓶颈。
- `WaitingOnCommit` 在 periodic 模式下通常只有 sync 落后时明显升高；batch/group 模式下直接影响写延迟。
- CDC 开启后，segment 生命周期还受 CDC raw 目录和消费速度约束，需联动 `cdc_total_space`、`cdc_block_writes`。
- 大 mutation 会被 `mutation.validateSize(..., ENTRY_OVERHEAD_SIZE)` 拦截，append 入口见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:300-305`。

## 性能瓶颈

- sync 策略：batch 最强 durability 但写延迟最高，periodic 延迟较低但 crash window 取决于 sync period。
- segment 分配：磁盘慢、flush 慢或空间不足会导致 `WaitingOnSegmentAllocation` 上升。
- 序列化与 checksum：`CommitLog.add()` 每次写入都序列化 mutation 并计算 checksum，见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:306-326`。
- 大 mutation：单条 mutation 接近 `max_mutation_size` 会放大分配、序列化和 sync 成本。

## 常见故障

- CommitLog 目录配置缺失或与 data/saved caches/hints 目录冲突：校验见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:717-749`。
- `commitlog_segment_size` 不合法或小于 `2 * max_mutation_size`：校验见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:891-901`。
- 磁盘写失败：`CommitLog.add()` 抛出 `FSWriteError`，见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:327-342`。
- replay 慢：大量未 clean segment 或 PITR/replay filter 范围大，会增加 startup 时间，replay 构造见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:116-170`。

## 测试用例

- `test/unit/org/apache/cassandra/db/commitlog/CommitLogTest.java`
- `test/unit/org/apache/cassandra/db/commitlog/CommitLogReaderTest.java`
- `test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentBackpressureTest.java`
- `test/unit/org/apache/cassandra/db/commitlog/CommitLogFailurePolicyTest.java`
- `test/unit/org/apache/cassandra/db/commitlog/AbstractCommitLogServiceTest.java`
- `test/unit/org/apache/cassandra/db/commitlog/CommitLogArchiverTest.java`
- `test/unit/org/apache/cassandra/db/commitlog/SegmentReaderTest.java`
- `test/unit/org/apache/cassandra/db/commitlog/DirectIOSegmentTest.java`
- `test/unit/org/apache/cassandra/db/commitlog/DirectIOSegmentBytemanTest.java`
- `test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDCTest.java`
- `test/long/org/apache/cassandra/db/commitlog/CommitLogStressTest.java`

## 待继续

- `research/module-commitlog-deep-dive.md` 已覆盖 `AbstractCommitLogService`、segment allocation/backpressure、CDC、archiver/PITR、压缩/加密/direct I/O/mmap 与 replay error policy。
- `research/module-commitlog-cdc-pitr-runbook.md` 已补外部 CDC consumer contract、`cdc_raw` 删除顺序、repair CDC write-path 和 PITR archive/restore 操作边界。
- CommitLog durability/replay 的 `commitlog_append_record_crc` 与 `commitlog_cdc_raw_backpressure` 场景已由 `research/module-commitlog-durability-replay-matrix.md` 和 `research/tools/check-commitlog-durability-drift.py` 保护。
- 可选继续补真实外部 CDC consumer integration test 与备份系统 PITR rehearsal。
