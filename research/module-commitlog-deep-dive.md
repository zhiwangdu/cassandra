# Module: CommitLog Deep Dive

## 范围

本文补齐 `module-commitlog.md` 留下的深水区：`AbstractCommitLogService` 的 periodic/batch/group sync 线程模型，segment allocation/backpressure，CDC segment manager，commitlog archiver/PITR，压缩/加密/direct I/O/mmap segment 格式，以及 replay 读路径和错误策略。

## 设计目标

- 写入路径在进入 memtable 前拿到 durable append 位置，同时按 `commitlog_sync` 策略决定是否等待磁盘 sync。
- segment manager 预创建 segment、限制总 commitlog 空间、在 flush 落后时驱动 dirty table flush，从而避免无限占用磁盘。
- CDC 使用同一批 segment 文件，但通过 hard link、CDC index 和 `cdc_raw` 空间追踪把可消费变更流暴露给外部 consumer。
- archiver 在 segment 删除前执行外部归档命令，启动恢复时可把归档文件 restore 回 live commitlog 目录并执行 point-in-time replay。
- descriptor header 携带 compression/encryption 参数，使 reader 可以在 replay 时选择 no-op、compressed 或 encrypted segmenter。
- direct I/O/mmap/standard 写入模式在同一个 `CommitLogSegment` 抽象下切换，配置层负责拦截不兼容组合。

## 解决的问题

- durability 与延迟冲突：batch 每次写等待 sync，group 用窗口合并等待，periodic 大多不等但在 sync lag 过大时阻塞，三种策略分别由 `BatchCommitLogService`、`GroupCommitLogService`、`PeriodicCommitLogService` 实现，见 `src/java/org/apache/cassandra/db/commitlog/BatchCommitLogService.java:24-43`、`src/java/org/apache/cassandra/db/commitlog/GroupCommitLogService.java:23-41`、`src/java/org/apache/cassandra/db/commitlog/PeriodicCommitLogService.java:28-45`。
- segment 分配不能阻塞在前台创建文件：`AbstractCommitLogSegmentManager` 用后台 allocator loop 预创建 segment、唤醒等待队列并在空间不足时触发 flush reclaim，见 `src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogSegmentManager.java:65-94`、`src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogSegmentManager.java:163-239`、`src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogSegmentManager.java:246-263`。
- CDC 写入必须在 raw 目录满时给出确定行为：blocking 模式把当前 segment 标记为 `FORBIDDEN` 并对 CDC mutation 抛 `CDCWriteException`，nonblocking 模式删除最旧 raw segment 以维持空间，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:159-190`、`src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:212-227`、`src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:316-358`。
- replay 需要辨认合法边界而不是盲读文件尾：sync marker 带 CRC，mutation record 又有 size CRC 和 data CRC，reader 在损坏/EOF 时通过 handler 决定继续、截断或失败，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentReader.java:166-211`、`src/java/org/apache/cassandra/db/commitlog/CommitLogReader.java:290-404`。
- archiver/PITR 需要把外部命令和内部 replay filter 连接起来：`CommitLogArchiver` 解析 `commitlog_archiving.properties`，replay 阶段用 `restorePointInTime` 与 `snapshot_commitlog_position` 限制可应用 mutation，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java:101-193`、`src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:116-187`。

## 设计取舍

- sync 线程即使不 flush，也会周期性写 marker/header，使 periodic 模式可以降低每次写阻塞，同时保留较新的 replay 边界；`SyncRunnable` 在 flush 周期外调用 `commitLog.sync(false)`，见 `src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogService.java:172-225`。
- `BatchCommitLogService` 主动 `requestExtraSync()` 并等待 allocation sync，`GroupCommitLogService` 让 sync thread 按 group window 批量唤醒，`PeriodicCommitLogService` 只在 lag 超阈值时等待，见 `src/java/org/apache/cassandra/db/commitlog/BatchCommitLogService.java:36-43`、`src/java/org/apache/cassandra/db/commitlog/GroupCommitLogService.java:34-41`、`src/java/org/apache/cassandra/db/commitlog/PeriodicCommitLogService.java:36-45`。
- segment rollover 先切换 `allocatingFrom`，再对旧 segment `discardUnusedTail()` 并请求额外 sync；归档在旧 segment 关闭后异步等待，失败时不删除原文件，见 `src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogSegmentManager.java:296-335`、`src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogSegmentManager.java:405-413`。
- CDC raw 文件用 hard link 复用 commitlog segment，避免复制大文件；代价是 consumer 删除 raw 文件才会释放 CDC 空间，且 nonblocking 模式会主动删除旧 raw 文件，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:192-210`、`src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:86-131`。
- compression/encryption 都要求 standard file access，direct/mmap 只适用于未压缩未加密 commitlog；配置解析会把 `auto`/`legacy` 映射成实际模式并拒绝非法组合，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1485-1529`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1532-1547`。
- encrypted commitlog 先压缩再按 chunk 加密，reader 需要独立解密每个 encrypted file segment；这让不同 chunk 可 seek/rebuffer，但要求 header 中保存 encryption IV，见 `src/java/org/apache/cassandra/db/commitlog/EncryptedSegment.java:88-150`、`src/java/org/apache/cassandra/db/commitlog/EncryptedFileSegmentInputStream.java:30-107`。

## 核心类

| 类 | 作用 |
|---|---|
| `AbstractCommitLogService` | sync executor 基类，维护 written/completed/pending counters、`lastSyncedAt`、marker interval、extra sync 请求和 flush lag 日志。定义见 `src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogService.java:59-91` |
| `BatchCommitLogService` | batch sync，写入完成前请求额外 sync 并等待 allocation 落盘。定义见 `src/java/org/apache/cassandra/db/commitlog/BatchCommitLogService.java:24-43` |
| `GroupCommitLogService` | group sync，按 group window 合并多个写入等待。定义见 `src/java/org/apache/cassandra/db/commitlog/GroupCommitLogService.java:23-41` |
| `PeriodicCommitLogService` | periodic sync，默认异步确认，sync lag 超过 `periodic_commitlog_sync_lag_block` 时阻塞。定义见 `src/java/org/apache/cassandra/db/commitlog/PeriodicCommitLogService.java:28-45` |
| `AbstractCommitLogSegmentManager` | segment builder、buffer pool、allocator thread、active segment queue、空间 reclaim、归档/删除和 forced recycle。定义见 `src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogSegmentManager.java:65-143` |
| `CommitLogSegmentManagerStandard` | 普通 segment manager，空间不足时切换 allocating segment，丢弃时按 archiver 结果删除文件。定义见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerStandard.java:31-68` |
| `CommitLogSegmentManagerCDC` | CDC-aware manager，处理 hard link、CDC index、raw 空间追踪、blocking/nonblocking 写入策略。定义见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:48-84` |
| `CommitLogSegment` | 单 segment buffer、sync marker、dirty/clean interval、CDC state 和文件关闭/删除逻辑。字段见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegment.java:98-127` |
| `CommitLogDescriptor` | filename/header/version/compression/encryption 参数，reader 从 header 恢复 segment 格式。定义见 `src/java/org/apache/cassandra/db/commitlog/CommitLogDescriptor.java:50-77` |
| `CompressedSegment` | 压缩 commitlog segment writer。格式说明与写入逻辑见 `src/java/org/apache/cassandra/db/commitlog/CompressedSegment.java:32-89` |
| `EncryptedSegment` | 加密 commitlog segment writer。格式说明与加密写入逻辑见 `src/java/org/apache/cassandra/db/commitlog/EncryptedSegment.java:43-150` |
| `DirectIOSegment` | direct I/O writer，使用 aligned direct buffer 和 page-size writes。定义见 `src/java/org/apache/cassandra/db/commitlog/DirectIOSegment.java:39-138` |
| `MemoryMappedSegment` | mmap writer，映射整个 segment 并在 sync 时 force。定义见 `src/java/org/apache/cassandra/db/commitlog/MemoryMappedSegment.java:35-113` |
| `CommitLogArchiver` | 外部 archive/restore 命令、PITR timestamp precision、restore directories。定义见 `src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java:55-75` |
| `CommitLogReader` / `CommitLogSegmentReader` | segment header/marker/record 读取和压缩/加密/no-op segmenter。主循环见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReader.java:169-259`、`src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentReader.java:48-85` |
| `CommitLogReplayer` | restart replay、per-table persisted interval 过滤、PITR/filter、CDC replay completion 和 mutation apply。定义见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:72-99` |

## 核心接口

- `CommitLogReadHandler`：reader 错误和 mutation 回调接口，包含 sync marker CRC、mutation CRC、EOF、unknown table、mutation 处理等 hook，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReadHandler.java:25-75`。
- `CommitLogMBean`：暴露 archive/restore 命令、PITR、active size、compression ratio、CDC block writes/repair toggle 和 recover 单文件入口，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogMBean.java:25-100`。
- `CommitLogSegment.AbstractCommitLogSegmentBuilder`：由 segment manager 根据 encryption/compression/access mode 选择具体 writer，选择逻辑见 `src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogSegmentManager.java:121-143`。

## 核心数据结构

- `CommitLogSegment.CDCState`：`PERMITTED`、`FORBIDDEN`、`CONTAINS` 三态，定义见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegment.java:70-76`。
- sync marker：每个 sync section 写 marker 和 CRC，未压缩/未加密场景可在特定属性下忽略零 file CRC 并依赖 mutation CRC，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegment.java:405-415`、`src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentReader.java:166-211`。
- `tableDirty` / `tableClean`：按 `TableId` 记录 dirty interval 与 clean interval，clean 只能在 segment 不再分配后从 dirty 中移除，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegment.java:555-586`。
- CDC index file：写入最后 synced offset，segment 完成时追加 `COMPLETED`，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegment.java:379-393`。
- `CommitLogDescriptor` header JSON：记录 compression class/parameters 和 encryption header parameters，写读逻辑见 `src/java/org/apache/cassandra/db/commitlog/CommitLogDescriptor.java:100-132`、`src/java/org/apache/cassandra/db/commitlog/CommitLogDescriptor.java:151-177`。
- `CommitLogReplayer.ReplayFilter`：从 `COMMIT_LOG_REPLAY_LIST` 构造 keyspace/table 过滤，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:384-489`。
- `CommitLogPosition` / persisted intervals：replay 计算每表 first-not-covered interval，跳过已经 flush 到 SSTable 的 mutation，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:339-382`。

## 生命周期

```text
Append + sync:
  CommitLog.add(mutation)
    -> serialize mutation into scratch buffer
    -> segmentManager.allocate(mutation, size)
    -> CommitLogSegment.allocate(mutation, size)
    -> write length CRC + mutation + mutation CRC
    -> alloc.markWritten()
    -> AbstractCommitLogService.finishWriteFor(alloc)
       -> Batch: requestExtraSync + await disk sync
       -> Group: await disk sync within group window
       -> Periodic: wait only when sync lag exceeds threshold

Allocator + reclaim:
  AbstractCommitLogSegmentManager.run()
    -> builder.createSegment()
    -> publish availableSegment
    -> maybeFlushToReclaim()
    -> advanceAllocatingFrom(old)
    -> archiver.maybeArchive(old)
    -> old.discardUnusedTail()

CDC:
  CommitLogSegmentManagerCDC.allocate()
    -> permitSegmentMaybe()
    -> throwIfForbidden() for CDC mutation on forbidden segment
    -> mark segment CONTAINS for CDC table mutation
    -> sync writes cdc idx
    -> discard retains CDC hardlink/index or deletes non-CDC link

Startup replay:
  CommitLog.recoverSegmentsOnDisk()
    -> archiver.maybeArchive unmanaged live files
    -> archiver.maybeRestoreArchive()
    -> CommitLogReplayer.replayFiles()
    -> CommitLogReader reads descriptor/sync sections/mutations
    -> CommitLogReplayer.handleMutation()
    -> Keyspace.apply(..., durableWrites=false)
```

## 调用链

- `CommitLog.add()` 先校验 mutation size，再序列化、分配、写 checksum、标记写入完成并交给 sync executor，见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:300-337`。
- `AbstractCommitLogService.SyncRunnable.run()` 根据 sync interval、shutdown 和 `syncRequested` 判断是否 flush，flush 后 signal 等待者，否则只更新 marker，见 `src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogService.java:172-225`。
- `requestExtraSync()` / `syncBlocking()` / `awaitSyncAt()` 是 batch/group/外部管理入口等待 sync 的基础，见 `src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogService.java:292-327`。
- `CommitLogSegment.sync(flush)` 等待 append order barrier、写入数据、flush channel/buffer、写 CDC index、signal sync complete 并在 full 时 close，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegment.java:298-372`。
- segment manager 在 `advanceAllocatingFrom()` 中把预创建 segment 切为 active，旧 segment 归档后丢弃尾部并请求额外 sync，见 `src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogSegmentManager.java:296-335`。
- `forceRecycleAll()` 用于 truncate/drop/table cleanup 等需要强制切 segment 的场景，会等待写入、flush dirty CFS、标记 dropped table clean 并归档 unused segment，见 `src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogSegmentManager.java:350-398`。
- 启动恢复先归档 unmanaged live files、等待 pending archive、restore archive、排序 replay、删除已 replay unmanaged 文件，见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:182-238`。
- reader 根据 descriptor 选择 encrypted/compressed/no-op segmenter，然后按 sync section 读取 mutation record，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentReader.java:274-405`。
- replay mutation 时会跳过不存在 keyspace、超过 PITR、已 drop/flushed table 的更新，实际 apply 不再写 commitlog，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:281-332`。

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| `commitlog_sync` | `src/java/org/apache/cassandra/config/Config.java:391`、`conf/cassandra.yaml:619-636` | `periodic`、`batch`、`group` 三种 sync 策略 |
| `commitlog_sync_group_window` | `src/java/org/apache/cassandra/config/Config.java:392-393`、getter `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3197-3205` | group commit 的合并等待窗口 |
| `commitlog_sync_period` | `src/java/org/apache/cassandra/config/Config.java:394-395`、getter `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3417-3442` | periodic flush 周期 |
| `periodic_commitlog_sync_lag_block` | `src/java/org/apache/cassandra/config/Config.java:402-403`、`conf/cassandra.yaml:641` | periodic sync 落后超过该阈值后阻塞前台写 |
| `commitlog_segment_size` | `src/java/org/apache/cassandra/config/Config.java:396-397`、`conf/cassandra.yaml:643-660` | segment 大小；影响 CDC hardlink 粒度、allocator 和 max mutation 校验 |
| `commitlog_compression` / `commitlog_max_compression_buffers_in_pool` | `src/java/org/apache/cassandra/config/Config.java:398-400`、getter `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:2790-2824` | compression segment writer 与压缩 buffer pool |
| `commitlog_disk_access_mode` | `src/java/org/apache/cassandra/config/Config.java:401`、`conf/cassandra.yaml:662-678` | `auto`、`mmap`、`direct`、`standard` 等访问模式；配置层做兼容性映射 |
| `transparent_data_encryption_options` | `src/java/org/apache/cassandra/config/Config.java:404` | commitlog encryption context 来源之一 |
| `cdc_enabled` / `cdc_block_writes` / `cdc_on_repair_enabled` / `cdc_raw_directory` | `src/java/org/apache/cassandra/config/Config.java:409-421`、`conf/cassandra.yaml:410-431` | 是否启用 CDC、raw 目录满时阻塞还是丢弃旧 raw、repair 是否写 CDC |
| `cdc_total_space` / `cdc_free_space_check_interval` | `conf/cassandra.yaml:917-929` | CDC raw 空间预算与重新计算间隔 |
| `commitlog_archiving.properties` | `conf/commitlog_archiving.properties:20-61` | `archive_command`、`restore_command`、`restore_directories`、`restore_point_in_time`、`snapshot_commitlog_position`、`precision` |
| `COMMITLOG_IGNORE_REPLAY_ERRORS` | `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:533-556` | replay 错误是否忽略 |
| `COMMITLOG_ALLOW_IGNORE_SYNC_CRC` | `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentReader.java:166-211` | 允许部分 sync marker CRC 异常时继续依赖 mutation CRC |
| `COMMIT_LOG_REPLAY_LIST` | `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:384-489` | replay keyspace/table allow-list |

## Metrics

- `CommitLogMetrics` 注册 `WaitingOnSegmentAllocation`、`WaitingOnCommit`、`WaitingOnFlush`、`OverSizedMutations`、`CompletedTasks`、`PendingTasks`、`TotalCommitLogSize`，定义见 `src/java/org/apache/cassandra/metrics/CommitLogMetrics.java:31-82`。
- allocator 等待可用 segment 时记录 `waitingOnSegmentAllocation`，见 `src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogSegmentManager.java:337-348`。
- `BatchCommitLogService` 等待 sync 时记录 `waitingOnCommit`，见 `src/java/org/apache/cassandra/db/commitlog/BatchCommitLogService.java:36-43`；periodic lag blocking 也使用同类计时，见 `src/java/org/apache/cassandra/db/commitlog/PeriodicCommitLogService.java:36-45`。
- `CommitLogMBean` 暴露 active content size、on-disk size 与 compression ratio，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogMBean.java:78-90`。
- `TotalCommitLogSize` 来自 segment manager 的 `onDiskSize()`，后者用 tracked size 和 live directory size 取大值，见 `src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogSegmentManager.java:444-450`。

## 日志

- sync 超过配置间隔时，`maybeLogFlushLag()` 使用 NoSpam warning，见 `src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogService.java:227-268`；对应测试覆盖见 `test/unit/org/apache/cassandra/db/commitlog/AbstractCommitLogServiceTest.java:168-212`。
- archiver 命令失败会记录错误并让 segment 留在原处供脚本处理，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java:240-268`。
- CDC blocking 模式 raw 空间不足会 NoSpam warn 并抛 `CDCWriteException`，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:212-227`。
- replay 遇到反序列化异常会 dump mutation 到临时文件后调用 handler，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReader.java:416-479`。
- direct I/O 不支持时配置初始化抛 `ConfigurationException`，测试消息见 `test/unit/org/apache/cassandra/db/commitlog/DirectIOSegmentBytemanTest.java:54-64`。

## 运维关注点

- `commitlog_sync=batch` 会把每次写入延迟绑定到磁盘 sync；`commitlog_sync=group` 的尾延迟至少包含 group window；`periodic` 的风险窗口取决于 sync period，且 sync lag 超阈值会阻塞写入。
- `TotalCommitLogSize` 接近 `commitlog_total_space` 时，segment manager 会强制 flush dirty table 来 reclaim；如果 flush 慢，前台写入会在等待新 segment 时累计 `WaitingOnSegmentAllocation`。
- CDC consumer 必须及时删除 `cdc_raw` 中已消费 segment 和 `_cdc.idx` 文件；blocking 模式会拒绝 CDC table 写入，nonblocking 模式会删除旧 raw 文件以腾空间。
- CDC index 第一行是可消费 offset，第二行 `COMPLETED` 表示 segment 已不再追加；consumer 不应把没有 index 或未完成 offset 后面的内容当成稳定数据。
- archive command 在 segment 归档失败时不会删除源文件；这保护 durability，但会让 commitlog 目录持续增长，需要检查 archiver 日志和外部脚本。
- PITR 依赖 mutation 的 client timestamp；`precision` 需要匹配写入时间戳单位，否则会出现多 replay 或少 replay。
- restore archived commitlog 会跳过 live 目录已有同名文件，并校验 descriptor id/version/compression，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java:270-331`。
- 压缩/加密 commitlog 必须使用 standard access；direct I/O 需要文件系统支持 block size 查询和 aligned direct buffer，配置错误会在启动初始化阶段失败。
- replay 错误开关能让节点跳过损坏 commitlog，但这本质上是在选择可用性优先于完整恢复，必须结合 commit failure policy 和备份策略判断。

## 性能瓶颈

- batch/group sync 直接受 fsync latency 影响，periodic 主要受后台 sync 是否跟上影响；sync thread 的 marker interval 会在 100ms 附近量化，测试见 `test/unit/org/apache/cassandra/db/commitlog/AbstractCommitLogServiceTest.java:47-94`。
- segment 分配如果追不上写入，会触发 `maybeFlushToReclaim()` 并阻塞等待 available segment，核心路径见 `src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogSegmentManager.java:163-239`、`src/java/org/apache/cassandra/db/commitlog/AbstractCommitLogSegmentManager.java:246-263`。
- compression 降低 on-disk bytes 但增加 CPU 和 buffer pool 压力；encrypted commitlog 强制 on-heap compression buffer 以适配 encryption API，见 `src/java/org/apache/cassandra/db/commitlog/EncryptedSegment.java:95-97`。
- direct I/O 避免 page cache 污染，但必须按 filesystem block 对齐写入；`DirectIOSegmentTest` 用 property-based range 验证 flush buffer 对齐，见 `test/unit/org/apache/cassandra/db/commitlog/DirectIOSegmentTest.java:65-113`。
- replay 会在 mutation stage 异步 apply，但 `CommitLogReplayer` 会按 outstanding bytes/count 节流，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:512-531`。
- CDC raw 空间重新计算会遍历 `cdc_raw`，触发路径见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:385-419`；大量 raw 文件会增加管理任务成本。

## 常见故障

- CDC 写入失败：`cdc_block_writes=true` 且 raw 空间满时，CDC table mutation 会收到 `CDCWriteException`；测试 `testCDCWriteFailure` 覆盖释放 raw 后状态恢复，见 `test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDCTest.java:72-100`。
- nonblocking CDC 数据缺口：`cdc_block_writes=false` 时系统会删除最旧 raw segment 来维持空间，测试见 `test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDCTest.java:114-132`。
- CDC consumer 误读非 CDC segment：没有 CDC mutation 的 hard link 不会写 index，并在 discard 时删除，见 `test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDCTest.java:211-235`。
- PITR 结果不符合预期：restore point timestamp 和 `precision` 不匹配会改变 cutoff，测试在微秒和毫秒精度下分别验证，见 `test/unit/org/apache/cassandra/db/commitlog/CommitLogArchiverTest.java:121-173`。
- archive command 配置复杂 shell 管道失效：properties 明确只支持单命令加参数，不执行 STDIN/STDOUT 或多命令，见 `conf/commitlog_archiving.properties:25-28`。
- sync marker CRC 损坏：默认会触发 replay exception；`COMMITLOG_IGNORE_REPLAY_ERRORS=true` 或 `commit_failure_policy=ignore` 可让测试继续，见 `test/unit/org/apache/cassandra/db/commitlog/CommitLogReaderTest.java:182-232`。
- direct I/O 文件系统不支持：`commitlog_disk_access_mode=direct` 初始化失败，Byteman 测试见 `test/unit/org/apache/cassandra/db/commitlog/DirectIOSegmentBytemanTest.java:54-64`。
- 加密旧版本 commitlog 不能恢复：`CommitLogUpgradeTest` 用 3.0/3.4/4.0 encrypted fixtures 验证 reader 兼容，见 `test/unit/org/apache/cassandra/db/commitlog/CommitLogUpgradeTest.java:106-166`。

## 测试用例

- `test/unit/org/apache/cassandra/db/commitlog/AbstractCommitLogServiceTest.java`：sync interval/marker interval 量化、marker-only sync、shutdown flush、flush lag 日志。
- `test/unit/org/apache/cassandra/db/commitlog/BatchCommitLogTest.java`、`test/unit/org/apache/cassandra/db/commitlog/GroupCommitLogTest.java`：具体 sync 策略行为。
- `test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentBackpressureTest.java`：segment allocation/backpressure。
- `test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDCTest.java`：CDC blocking/nonblocking、index offset、`COMPLETED`、hard link 删除/保留、replay 后 CDC index 重建。
- `test/unit/org/apache/cassandra/db/commitlog/CommitLogArchiverTest.java`：archive 命令生效、PITR 微秒/毫秒精度。
- `test/unit/org/apache/cassandra/db/commitlog/SegmentReaderTest.java`：LZ4/Snappy/Deflate/Zstd compressed segmenter 和 encrypted segmenter read/seek。
- `test/unit/org/apache/cassandra/db/commitlog/DirectIOSegmentTest.java`、`test/unit/org/apache/cassandra/db/commitlog/DirectIOSegmentBytemanTest.java`：direct I/O buffer 对齐、size accounting、builder、unsupported filesystem。
- `test/unit/org/apache/cassandra/db/commitlog/CommitLogReaderTest.java`：reader count/midpoint、sync marker CRC failure、replay error policy。
- `test/unit/org/apache/cassandra/db/commitlog/CommitLogUpgradeTest.java`：历史 encrypted commitlog fixtures replay。
- `test/long/org/apache/cassandra/db/commitlog/CommitLogStressTest.java`：legacy/direct、encryption、LZ4/Snappy/Deflate 等组合压力测试，参数矩阵见 `test/long/org/apache/cassandra/db/commitlog/CommitLogStressTest.java:144-153`。

## 待继续

- `research/module-commitlog-cdc-pitr-runbook.md` 已补外部 CDC consumer contract/runbook，包括消费 offset、删除顺序、监控告警和下游 at-least-once 边界。
- CommitLog durability/replay 的 `commitlog_append_record_crc` 与 `commitlog_cdc_raw_backpressure` 场景已由 `research/module-commitlog-durability-replay-matrix.md` 和 `research/tools/check-commitlog-durability-drift.py` 保护。
- 仍需补真实外部 CDC consumer integration test 与备份系统 PITR rehearsal，例如 archive script 幂等性、跨节点快照一致性、restore dry-run 和 clock/timestamp audit。
