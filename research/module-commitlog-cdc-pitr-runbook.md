# Module: CommitLog CDC And PITR Runbook

## 范围

本模块补齐 CommitLog 的外部 CDC consumer contract 与 point-in-time restore 操作边界。它建立在 `research/module-commitlog.md` 和 `research/module-commitlog-deep-dive.md` 的内部实现研究之上，重点回答外部系统如何安全读取 `cdc_raw`、何时删除文件、CDC 空间满时 Cassandra 如何处理写入，以及 `commitlog_archiving.properties` 如何驱动 archive/restore/PITR replay。

## 设计目标

- CDC 只通过 commitlog segment 和 `_cdc.idx` 暴露 durable 数据，不引入独立的事件队列；consumer 必须理解 commitlog 文件格式或复用同等 reader。
- `cdc_raw` 空间既包含已 flush 的 CDC hard link，也临时估算未 flush segment 的空间；写入路径需要在 raw 消费滞后时给出可预测 backpressure。
- PITR 通过外部 archive/restore 命令接入备份系统，Cassandra 只负责在 segment 删除前调用 archive、启动时 restore archived segment 并按 timestamp/filter replay。
- Runbook 必须明确边界：CDC consumer 删除文件是释放空间的信号，PITR 截止点依赖 mutation timestamp 而不是 wall-clock replay time。

## 解决的问题

- CDC 表属性来自 CQL table option，`TableAttributes` 将 `WITH cdc = true/false` 写入 table params，见 `src/java/org/apache/cassandra/cql3/statements/schema/TableAttributes.java:154-155`；`CDCStatementTest` 覆盖 create/alter/disable，见 `test/unit/org/apache/cassandra/cql3/CDCStatementTest.java:38-61`。
- mutation 级 CDC 标记在 `Mutation` 构造时由 partition update 的 table params 汇总，`trackedByCDC()` 返回该布尔值，见 `src/java/org/apache/cassandra/db/Mutation.java:83-108` 和 `src/java/org/apache/cassandra/db/Mutation.java:290-293`。
- 开启节点级 CDC 后，配置层选择 `CommitLogSegmentManagerCDC` 代替 standard manager，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:241-243`；启动配置会补默认 `cdc_raw_directory` 与 `cdc_total_space`，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:677-697`。
- CDC consumer 不能直接读到文件尾：commitlog sync 时才写 `_cdc.idx` offset，segment close 时追加 `COMPLETED`，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegment.java:363-385`。
- PITR 需要把外部备份目录恢复为 live commitlog 目录；`CommitLog.recoverSegmentsOnDisk()` 在 replay 前归档 unmanaged live files、等待 archive、执行 `maybeRestoreArchive()`，再排序 replay，见 `src/java/org/apache/cassandra/db/commitlog/CommitLog.java:182-215`。

## 设计取舍

- CDC 使用 hard link 而不是复制 segment：`createSegment()` 在 permitted segment 上把 live segment hard link 到 `cdc_raw`，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:236-248`。这减少复制成本，但 consumer 删除 raw hard link 才会释放 CDC 空间。
- `_cdc.idx` 是外部消费 watermark，不是事务日志。第一行 offset 表示已同步到磁盘且可读的 segment 边界，第二行 `COMPLETED` 表示不再追加；测试覆盖 offset 不小于 last sync 和 completed flag，见 `test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDCTest.java:149-187`、`test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDCTest.java:189-209`。
- CDC raw segment 是完整 commitlog segment；一个 segment 只要包含任意 CDC mutation 就会保留，因此下游 consumer 需要按 table/schema 过滤事件，不能把 segment 文件等同于只含 CDC 表记录。
- `cdc_block_writes=true` 时容量满会拒绝 CDC table mutation；`false` 时会删除最旧 raw segment 腾空间，优先可用性但允许 CDC 缺口，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:212-227` 和 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:344-354`。
- `archive_command`/`restore_command` 使用 `ProcessBuilder(command.split(" "))` 执行单命令，properties 明确不支持 STDIN/STDOUT 或多命令；复杂逻辑必须封装成脚本，见 `conf/commitlog_archiving.properties:20-28` 和 `src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java:334-339`。
- PITR cutoff 使用 mutation 的 client timestamp，经 `precision` 转 microseconds 比较；时间戳大于 `restore_point_in_time` 的 mutation 被跳过，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:502-510`。

## 核心类

| 类 | 作用 |
|---|---|
| `CommitLogSegmentManagerCDC` | CDC-aware segment manager，负责 hard link、raw 空间估算、blocking/nonblocking 写入策略、replay 后 CDC index 重建，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:48-84`。 |
| `CommitLogSegment` | 持有 `CDCState`、sync/index 写入和 dirty/clean interval；CDC index 写入见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegment.java:70-77`、`src/java/org/apache/cassandra/db/commitlog/CommitLogSegment.java:379-393`。 |
| `Mutation` | 根据 table params 汇总 mutation 是否被 CDC 追踪，见 `src/java/org/apache/cassandra/db/Mutation.java:83-108`。 |
| `CommitLogArchiver` | 读取 archive/restore/PITR properties，执行 archive/restore 命令，校验 descriptor/header/compression，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java:101-193`、`src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java:270-331`。 |
| `CommitLogReplayer` | 构造 replay persisted interval/filter，执行 PITR cutoff、CDC replay completion 和 mutation apply，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:116-187`、`src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:512-523`。 |
| `CassandraStreamReceiver` | repair/streaming 接收 CDC 表时可强制通过 write path 写 commitlog，从而进入 CDC raw，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:174-224`。 |

## 核心接口

- `CommitLogMBean.getCDCBlockWrites()` / `setCDCBlockWrites()`：运行时切换 CDC blocking/nonblocking 行为，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogMBean.java:92-94`。
- `CommitLogMBean.isCDCOnRepairEnabled()` / `setCDCOnRepairEnabled()`：控制 repair/streaming 的 CDC 数据是否走 write path，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogMBean.java:96-100`。
- `CommitLogArchiver.maybeArchive(CommitLogSegment)`：segment 删除前等待 final sync，然后替换 `%name`、`%path` 执行 archive 命令，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java:195-210`。
- `CommitLogArchiver.maybeRestoreArchive()`：扫描 `restore_directories`，校验 descriptor/version/compression，跳过 live 目录已有文件，再替换 `%from`、`%to` 执行 restore 命令，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java:270-331`。
- `CommitLogReplayer.ReplayFilter`：`COMMIT_LOG_REPLAY_LIST` 可限制 keyspace/table replay；格式与校验见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:384-445`。

## 核心数据结构

| 数据结构 | 字段/文件 | 语义 |
|---|---|---|
| `CDCState` | `PERMITTED` | 当前 segment 允许 CDC mutation 分配。 |
| `CDCState` | `FORBIDDEN` | blocking 模式且 CDC 空间预算不足，CDC mutation 会被拒绝。 |
| `CDCState` | `CONTAINS` | segment 已包含 CDC mutation，discard 时保留 raw hard link/index。 |
| `cdc_raw` segment hard link | `<CommitLog-...log>` | 与 live commitlog segment 指向同一文件内容；consumer 删除 raw hard link 表示已处理。 |
| CDC index | `<CommitLog-..._cdc.idx>` | 第一行是可消费 offset；第二行可为 `COMPLETED`。 |
| `archive_command` | `%path` / `%name` | segment 归档命令替换 token，定义见 `conf/commitlog_archiving.properties:20-28`。 |
| `restore_command` | `%from` / `%to` | archived segment 恢复命令替换 token，定义见 `conf/commitlog_archiving.properties:30-37`。 |
| PITR cutoff | `restore_point_in_time` / `precision` | GMT timestamp 和写入 timestamp precision，定义见 `conf/commitlog_archiving.properties:39-61`。 |

## 生命周期

CDC 正常消费：

```text
CREATE/ALTER TABLE ... WITH cdc=true
  -> Mutation.trackedByCDC() == true for writes touching CDC table
  -> CommitLogSegmentManagerCDC.allocate()
     -> permitSegmentMaybe()
     -> throwIfForbidden() if CDC space is exhausted in blocking mode
     -> set segment CDCState.CONTAINS after CDC allocation
  -> CommitLogSegment.sync(true)
     -> write durable data and _cdc.idx offset
  -> table flush / segment recycle
     -> discard keeps raw hard link + index for CONTAINS segment
  -> external consumer parses segment up to _cdc.idx offset
  -> external consumer deletes segment and _cdc.idx after durable downstream commit
```

PITR restore：

```text
normal operation
  -> segment becomes unused
  -> CommitLogArchiver.maybeArchive(segment)
     -> waitForFinalSync()
     -> archive_command with %path/%name

restore rehearsal / startup
  -> configure restore_directories, restore_command, restore_point_in_time, precision
  -> CommitLog.recoverSegmentsOnDisk()
     -> maybeArchive unmanaged live files
     -> maybeRestoreArchive()
     -> CommitLogReplayer.replayFiles()
     -> pointInTimeExceeded() skips writes after cutoff
```

## 调用链

- CDC write path：`CommitLog.add()` 调用 segment manager `allocate()`；CDC manager 先检查当前 segment state，再对 CDC mutation 抛 `CDCWriteException` 或分配空间，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:168-190`。
- 空间释放路径：consumer 删除 raw 文件后，`permitSegmentMaybe()` 或 `updateCDCTotalSize()` 触发 size recalculation，FORBIDDEN segment 在空间低于预算时恢复 PERMITTED 并重新 hard link，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:192-210`、`src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:385-450`。
- nonblocking 清理路径：`processNewSegment()` 发现 `sizeInProgress > cdc_total_space` 时调用 `deleteOldLinkedCDCCommitLogSegment()`，从最旧 raw segment 起删除 segment 与 index，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:91-131`、`src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:344-354`。
- 非 CDC segment discard：CDC manager 删除没有 CDC mutation 的 hard link/index，避免 consumer 误读无 index 文件，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:66-83`。
- replay 后 CDC index 重建：`CommitLogReplayer` 如果在 replay 中看到 CDC mutation 会调用 completion 逻辑；测试清空 `cdc_raw` 后 replay，确认旧 index 被重建且 offset 不小于原值，见 `test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDCTest.java:264-335`。
- repair streaming CDC 路径：`CassandraStreamReceiver.requiresWritePath()` 在 CDC 表且 `cdc_on_repair_enabled` 时返回 true，并用 durable write path apply streamed mutation，见 `src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java:179-224`。
- PITR replay apply：`MutationInitiator` 先检查 keyspace、PITR cutoff、replay filter、drop/flushed table，再用 `Keyspace.apply(..., durableWrites=false)` 应用 replayed mutation，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:294-327`。

## 配置项

| 配置项 | 定义位置 | 运维含义 |
|---|---|---|
| `cdc_enabled` | `src/java/org/apache/cassandra/config/Config.java:409-410`、`conf/cassandra.yaml:410-413` | 节点级 CDC 开关；启用后使用 CDC segment manager。 |
| `cdc_block_writes` | `src/java/org/apache/cassandra/config/Config.java:411-413`、`conf/cassandra.yaml:415-418` | true 时 raw 空间满拒绝 CDC table 写；false 时删除旧 raw 保持写可用。 |
| `cdc_on_repair_enabled` | `src/java/org/apache/cassandra/config/Config.java:414-416`、`conf/cassandra.yaml:420-425` | repair/streaming 接收 CDC 表数据时是否写入 commitlog/raw。 |
| `cdc_raw_directory` | `src/java/org/apache/cassandra/config/Config.java:417`、`conf/cassandra.yaml:427-431` | raw hard link 和 `_cdc.idx` 目录；建议独立磁盘。 |
| `cdc_total_space` | `src/java/org/apache/cassandra/config/Config.java:418-419`、`conf/cassandra.yaml:915-923` | CDC raw 空间上限；默认按 raw 目录总空间计算。 |
| `cdc_free_space_check_interval` | `src/java/org/apache/cassandra/config/Config.java:420-421`、`conf/cassandra.yaml:925-929` | raw 空间满后重新检查 consumer 是否释放空间的间隔。 |
| `archive_command` | `conf/commitlog_archiving.properties:20-28` | segment 归档命令，空值表示禁用。 |
| `restore_command` / `restore_directories` | `conf/commitlog_archiving.properties:30-37` | archived segment 恢复命令和扫描目录。 |
| `restore_point_in_time` | `conf/commitlog_archiving.properties:39-49` | GMT cutoff；只应用 timestamp 小于等于该值的 mutation。 |
| `snapshot_commitlog_position` | `conf/commitlog_archiving.properties:51-58` | 覆盖 snapshot 前已持久化位置，主要用于非 SSTable snapshot 载体。 |
| `precision` | `conf/commitlog_archiving.properties:60-61` | 写入 timestamp 精度；错误设置会改变 PITR cutoff。 |

## Metrics

- `CommitLogMetrics.TotalCommitLogSize` 只反映 active commitlog manager on-disk size，不等同于 `cdc_raw` backlog；CDC raw 空间由 `CDCSizeTracker` 遍历目录计算，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:279-285`、`src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:407-414`。
- `WaitingOnSegmentAllocation` 上升可能是 commitlog 总空间、flush reclaim 或 CDC blocking 间接导致；commitlog metrics 定义见 `src/java/org/apache/cassandra/metrics/CommitLogMetrics.java:31-82`。
- `CommitLogMBean.getArchivingSegmentNames()` 暴露 pending archive 文件名，但不包含已经失败的 archive attempt，接口注释见 `src/java/org/apache/cassandra/db/commitlog/CommitLogMBean.java:72-75`。
- CDC consumer 应额外监控 `cdc_raw` 目录 bytes、segment count、最老 segment age、缺失 `_cdc.idx`、未完成 index offset 停滞，以及 CDC write failure 计数/日志；这些是外部指标，不由 Cassandra metrics registry 直接导出。

## 日志

- raw 空间满且 blocking 时会 NoSpam warn，消息包含 keyspace、`cdc_raw_directory` 和当前 CDC bytes，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:212-227`。
- nonblocking 删除旧 raw 后 debug 记录释放 bytes、剩余 size 和 allowance，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:344-354`。
- archive 失败时 `maybeWaitForArchiving()` 记录错误并返回 false，segment 不会被删除，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java:240-268`。
- restore 时遇到 name/header descriptor 不一致、unsupported version 或 unknown compression 会抛异常停止启动，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java:284-310`。
- PITR 清除晚于 restore point 的 truncation record 时会 info 记录 table，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:128-142`。

## 运维关注点

- CDC consumer 的安全删除顺序应是：读取 `_cdc.idx`，只解析 segment 中小于等于 offset 的完整 records，把下游 sink commit 到可重放位置，然后删除 raw segment 和 `_cdc.idx`。如果 index 没有 `COMPLETED`，保留文件并在下一轮从已提交 offset 继续。
- Consumer 不能假设一个 raw segment 只包含 CDC 表，也不能仅按 file mtime 或 file size 判断可读边界；源码把 durable boundary 放在 `_cdc.idx`，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegment.java:374-385`。
- `cdc_block_writes=false` 是丢数据策略：Cassandra 会删除最旧 raw segment 保持写入可用，适合有上游可补偿或允许 CDC 缺口的场景；严格 CDC 应保持 true 并对空间告警。
- repair/streaming CDC 需要按 `cdc_on_repair_enabled` 决策。关闭可提高 streaming 速度，但配置注释明确存在 SSTable 数据未进入 CDC log 的风险，见 `conf/cassandra.yaml:420-425`。
- PITR archive script 必须幂等，处理同名文件、重试和跨节点并行归档；Cassandra 启动时会尝试归档 unmanaged live files，重复归档失败只 warning，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java:212-237`。
- PITR 恢复前应恢复匹配 snapshot 的 SSTables，再配置 `restore_directories` 和 cutoff。只恢复 commitlog 而没有对应 SSTable 基线会造成 replay 范围过大或缺历史数据。
- `snapshot_commitlog_position` 会覆盖从 SSTable 推导的 persisted intervals；properties 明确它不会排除现有 SSTable 已覆盖 interval，见 `conf/commitlog_archiving.properties:51-58`。
- `precision` 必须匹配业务写入 timestamp 单位。`USING TIMESTAMP` 是微秒语义；如果业务传毫秒而 precision 配微秒或相反，PITR cutoff 会偏移。

## 性能瓶颈

- CDC consumer 滞后会增加 `cdc_raw` 目录扫描成本，`CDCSizeTracker.calculateSize()` 使用 `Files.walkFileTree()` 重新计算大小，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDC.java:407-414`。
- Hard link 保留会让 live commitlog segment 删除不释放真实 blocks，直到 raw link 也删除；这会放大磁盘空间压力。
- `_cdc.idx` 更新发生在 commitlog sync flush 中，CDC segment 可见性受 commitlog sync 周期、batch/group fsync latency 和 segment recycle 影响。
- PITR restore 会把 archived segment 拷回 live commitlog 目录并执行正常 replay；大量 archived segment 会拉长 startup replay 和 mutation stage apply，replay outstanding bytes/count 节流见 `src/java/org/apache/cassandra/db/commitlog/CommitLogReplayer.java:512-531`。
- Archive command 在 segment 回收路径上异步执行，但删除前会等待 pending archive 结果；归档存储慢或脚本失败会导致 live commitlog 目录增长。

## 常见故障

- `CDCWriteException` / CDC write timeout：`cdc_block_writes=true` 且 raw 空间满；释放 raw 文件后需要等待 `cdc_free_space_check_interval` 或下一次 size recalc，测试见 `test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDCTest.java:72-100`。
- CDC 数据缺口：`cdc_block_writes=false` 时旧 raw segment 被删除；测试验证 nonblocking 保持空间约束，见 `test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDCTest.java:114-132`。
- Consumer 误删未完成 segment：如果只看 raw segment 文件而不看 `_cdc.idx` offset，可能解析未同步 tail；测试明确 index offset 与 sync offset 的关系，见 `test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDCTest.java:149-187`。
- Consumer 看到没有 index 的 raw hard link：没有 CDC data 的 segment discard 会删除 hard link；若 consumer 在 race 中看到文件但无 index，应跳过等待或重新扫描，见 `test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDCTest.java:211-235`。
- Repair 数据缺 CDC：`cdc_on_repair_enabled=false` 时 repaired data 写入 SSTable 而不进 CDC commitlog；distributed test 验证开关两种状态，见 `test/distributed/org/apache/cassandra/distributed/test/cdc/ToggleCDCOnRepairEnabledTest.java:37-95`。
- PITR 多恢复或少恢复：`restore_point_in_time`、`precision`、业务 timestamp 单位不一致；`CommitLogArchiverTest` 分别验证微秒和毫秒 cutoff，见 `test/unit/org/apache/cassandra/db/commitlog/CommitLogArchiverTest.java:121-173`。
- Archive 命令无法执行 shell 管道：properties 和 `ProcessBuilder(command.split(" "))` 不支持多命令/重定向，见 `conf/commitlog_archiving.properties:25-28`、`src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java:334-339`。
- Restore descriptor 校验失败：文件名/header/version/compression 不一致或未知，`maybeRestoreArchive()` 会抛异常，见 `src/java/org/apache/cassandra/db/commitlog/CommitLogArchiver.java:284-310`。

## 测试用例

- `test/unit/org/apache/cassandra/cql3/CDCStatementTest.java:38-61`：CQL create/alter/disable CDC table option。
- `test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDCTest.java:72-100`：blocking CDC raw 空间满、非 CDC 表仍可写、consumer 删除 raw 后恢复 PERMITTED。
- `test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDCTest.java:114-146`：nonblocking steady disk usage 与 blocking/nonblocking 动态切换。
- `test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDCTest.java:149-209`：CDC index offset 与 `COMPLETED` flag。
- `test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDCTest.java:211-262`：非 CDC segment discard 删除 hard link，CDC segment discard 保留 hard link/index。
- `test/unit/org/apache/cassandra/db/commitlog/CommitLogSegmentManagerCDCTest.java:264-335`：replay 后重建 CDC raw/index。
- `test/unit/org/apache/cassandra/db/commitlog/CommitLogArchiverTest.java:97-119`：archive command 生效。
- `test/unit/org/apache/cassandra/db/commitlog/CommitLogArchiverTest.java:121-173`：PITR 微秒/毫秒 precision cutoff。
- `test/distributed/org/apache/cassandra/distributed/test/cdc/ToggleCDCOnRepairEnabledTest.java:37-95`：repair/streaming CDC 数据是否进入 commitlog 由 `cdc_on_repair_enabled` 控制。

## 待补项

- 仍缺真实外部 CDC consumer integration test：包括 downstream checkpoint、consumer crash/restart、partial segment、schema evolution 和 duplicate delivery 处理。
- 仍缺真实备份系统 PITR rehearsal：包括跨节点 snapshot 一致性、archive script 幂等性、对象存储延迟、restore dry-run 和 clock/timestamp audit。
