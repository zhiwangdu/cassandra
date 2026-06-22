# Compaction Control And Observability Matrix

## 范围

本文补齐 `research/module-compaction-operations-failure-matrix.md` 的运行控制面细节，聚焦 active compaction registry、`CompactionInfo` 任务标识、`nodetool stop`/JMX stop、`compactionstats -V`、`vts.sstable_tasks`、取消轮询、global pause 和空间估算。策略选择、writer pipeline 和空间缩小主流程仍以 `research/module-compaction-strategies-deep-dive.md`、`research/module-sstable-compaction.md`、`research/flow-compaction.md` 为主。

## 场景矩阵

| 场景 ID | 源码合同 | 测试/缺口 |
|---|---|---|
| `compaction_active_tracker_contract` | `ActiveCompactions` 用 synchronized identity set 保存 `CompactionInfo.Holder`，`beginCompaction()`/`finishCompaction()` 维护 active 集合；`finishCompaction()` 更新 `BytesCompacted`、`CompressedBytesCompacted` 和 `TotalCompactionsCompleted`。见 `src/java/org/apache/cassandra/db/compaction/ActiveCompactions.java:35-54`。 | `ActiveCompactionsTest.testActiveCompactionTrackingRaceWithIndexBuilder()` 覆盖 active set 与 index builder 并发访问。 |
| `compaction_info_task_identity_contract` | `CompactionInfo` 暴露 `COMPACTION_ID`、`SSTABLES`、`TARGET_DIRECTORY`、keyspace/table、completed/total/totalCompressed、task type 和 unit；`asMap()` 是 JMX/NodeProbe/compactionstats 的 map 事实来源。见 `src/java/org/apache/cassandra/db/compaction/CompactionInfo.java:35-55`、`:223-237`。 | `CompactionStatsTest` 和 `SSTableTasksTableTest` 都用同一 `CompactionInfo` fake holder 验证输出。 |
| `compaction_stop_by_type_contract` | `CompactionManager.stopCompaction(String type)` 把字符串转成 `OperationType.valueOf(type)`，遍历 `active.getCompactions()`，只对 task type 匹配的 holder 调 `stop()`。见 `src/java/org/apache/cassandra/db/compaction/CompactionManager.java:2217-2225`。 | nodetool command path 有 source coverage；缺真实长任务 stop-by-type live assertion。 |
| `compaction_stop_by_id_contract` | `CompactionManager.stopCompactionById(String compactionId)` 遍历 active holders，比对 `holder.getCompactionInfo().getTaskId()` 与 `TimeUUID.fromString(compactionId)`，匹配后 `holder.stop()`。见 `CompactionManager.java:2228-2235`。 | `compactionstats -V` 暴露 task id，但缺 `nodetool stop --compaction-id <id>` 取消 live task 的端到端测试。 |
| `compaction_holder_stop_poll_contract` | `CompactionInfo.Holder.stop()` 只设置 volatile `stopRequested`；真正中断发生在 `CompactionTask` 或 `CompactionIterator` 后续轮询 `isStopRequested()` 并抛 `CompactionInterruptedException`。见 `CompactionInfo.java:249-268`、`CompactionTask.java:212-220`、`CompactionIterator.java:728-746`。 | `CompactionIteratorTest.transformTest()` 和 `transformPartitionTest()` 覆盖 iterator 层 stop 后抛 `CompactionInterruptedException`。 |
| `compaction_interrupt_for_sstable_contract` | `CompactionManager.interruptCompactionFor()` 可按 table metadata、sstable predicate 和 validation flag 过滤 active tasks；`CompactionInfo.shouldStop()` 对没有 sstable 的 holder 总是 true，对普通 compaction 按 sstable predicate 匹配。见 `CompactionManager.java:2419-2460`、`CompactionInfo.java:240-247`。 | `ActiveCompactionsTest.testIndexSummaryRedistributionTracking()` 验证 index summary 这类 no-sstable task 可被 stop predicate 命中。 |
| `compaction_global_pause_contract` | `CompactionInfo.Holder.isStopRequested()` 对 global holder 同时检查 `CompactionManager.isGlobalCompactionPaused()`；`pauseGlobalCompaction()` 通过 `globalCompactionPauseCount` 提供 `runWithCompactionsDisabled()` 的全局停止边界。见 `CompactionInfo.java:260-268`、`CompactionManager.java:2498-2511`、`ColumnFamilyStore.java:2871-2888`。 | 缺 focused global pause + active global task 单元测试；目前主要由 truncate/compactions-disabled 路径间接使用。 |
| `compactionstats_verbose_task_contract` | `nodetool compactionstats -V` 输出 keyspace/table/task id/completion ratio/kind/progress/sstable count/total/total compressed/unit/target directory；数据来自 `CompactionManager.getCompactions()` -> `CompactionInfo.asMap()`。见 `src/java/org/apache/cassandra/tools/nodetool/CompactionStats.java:45-143`。 | `CompactionStatsTest.testCompactionStatsVtable()` 和 human-readable variant 覆盖 verbose 表头、task id 和 target directory。 |
| `sstable_tasks_virtual_table_contract` | `SSTableTasksTable.data()` 读取 `CompactionManager.instance.getSSTableTasks()`，把当前 SSTable tasks 映射到 `vts.sstable_tasks`，并过滤 key/row/counter cache save。见 `src/java/org/apache/cassandra/db/virtual/SSTableTasksTable.java:29-82`、`CompactionManager.java:2488-2496`。 | `SSTableTasksTableTest.testSelectAll()` 覆盖 virtual table row、completion ratio、kind、sstables、target directory 和空结果。 |
| `compaction_remaining_write_estimate_contract` | `ActiveCompactions.estimatedRemainingWriteToDiskBytes()` 遍历 active tasks，按 `CompactionInfo.getTargetDirectories()` 平分 remaining write bytes 并按目录聚合；`CompactionInfo.estimatedRemainingWriteToDiskBytes()` 只对 `OperationType.writesData` 任务估算。见 `ActiveCompactions.java:57-76`、`CompactionInfo.java:196-207`、`OperationType.java:51-60`。 | `SecondaryIndexCompactionTest` 覆盖 index CFS compaction 参与 remaining-write estimate，不因 index metadata 触发异常。 |
| `compaction_operation_type_stop_contract` | `OperationType` 的枚举声明要求修改时同步 nodetool Stop 支持列表；priority 用于 operator-driven interruption，`writesData` 用于空间估算。见 `src/java/org/apache/cassandra/db/compaction/OperationType.java:20-60`。 | 没有 exhaustiveness test 对比 `OperationType` 与 `nodetool Stop` help 文案；保留 gap。 |
| `compaction_control_existing_tests_baseline` | 当前 coverage 包括 active registry 并发、secondary index tracking、index summary no-sstable stop、compactionstats/VTable/human-readable 输出、SSTable tasks virtual table、iterator stop transform 和 upgrade/compaction latch byteman。 | checker 保护这些测试文件与关键 tokens 仍存在。 |
| `compaction_live_cancel_metrics_gap` | 仍缺长任务 live cancellation 测试：通过 `compactionstats -V` 获取 task id，执行 `nodetool stop --compaction-id`，验证 task 消失、`CompactionInterruptedException`/state 传播、metrics 不误记完成/空间缩小，并覆盖 stop-by-type 与 global pause。 | 保留 explicit gap，避免把 source-only stop contract 误读成 live cancellation 已经端到端验证。 |

## 设计目标

- 用 `CompactionInfo.Holder` 作为所有 compaction-like task 的最小控制接口：可观测、可停止、可判断是否 global。
- 让 JMX、nodetool、virtual table 和 disk-space estimator 共享同一个 active task registry，避免不同运维界面看到不一致任务。
- 以 `TimeUUID` task id 支撑 operator 精确停止单个任务，同时保留按 `OperationType` 批量停止。
- 用 cooperative cancellation 避免强杀线程：operator stop 只设置 stop flag，task 在安全轮询点抛 `CompactionInterruptedException`。
- 把 active tasks 的 remaining write estimate 纳入磁盘空间判定，防止多个并发任务在同一目录/filestore 上超额写入。

## 设计取舍

- `ActiveCompactions` 返回 copy，避免外部持有内部 synchronized identity set；代价是 stop/observe 都是快照视角。
- stop-by-id 如果 id 不匹配不会报错；这让重复 stop/id 已消失时无害，但也要求运维先用 `compactionstats -V` 或 `vts.sstable_tasks` 确认当前 task id。
- no-sstable task 的 `shouldStop()` 总是 true，适配 view build、cache save、index summary 等无法提前知道 SSTable set 的任务；这让 table-level interruption 更保守。
- global pause 只影响 `holder.isGlobal() == true` 的任务，普通 per-table compaction 仍靠 table/sstable predicate stop。
- completion metrics 在 `finishCompaction()` 更新，live cancellation 是否计入完成取决于 holder 是否进入 finish path；这需要测试明确约束。

## 核心类

| 类 | 作用 |
|---|---|
| `ActiveCompactions` | active holder registry、begin/finish tracking、completion metrics、remaining write estimate、sstable->compaction lookup。 |
| `CompactionInfo` | task id、进度、任务类型、单位、SSTable set、target directory 和 stop predicate。 |
| `CompactionInfo.Holder` | cooperative stop flag、global pause gate 和 `getCompactionInfo()` 抽象接口。 |
| `CompactionManager` | JMX `getCompactions()`/`getCompactionSummary()`、stop-by-type/id、table/sstable interruption、SSTable tasks virtual table source。 |
| `CompactionTask` | task execution 中 active begin/finish、strategy inactive interruption 和 metrics update。 |
| `CompactionIterator` | task progress holder，partition/row transform 中轮询 stop flag 并抛 `CompactionInterruptedException`。 |
| `OperationType` | compaction-like task 类型、`writesData` 空间估算标记和 operator interruption priority。 |
| nodetool `Stop` | operator CLI 入口，按 type 或 `--compaction-id` 调用 NodeProbe。 |
| nodetool `CompactionStats` | operator 观测入口，包含 verbose task id 和 target directory。 |
| `SSTableTasksTable` | virtual table 观测入口，对外暴露当前 SSTable tasks。 |

## 核心接口与数据结构

- `ActiveCompactions.beginCompaction(CompactionInfo.Holder)` / `finishCompaction(...)`：注册和注销 active holder。
- `CompactionInfo.asMap()`：JMX/NodeProbe/compactionstats 的字段映射。
- `CompactionInfo.Holder.stop()` / `isStopRequested()`：cooperative cancellation flag。
- `CompactionManager.stopCompaction(String)`：按 `OperationType` 停止所有匹配 active tasks。
- `CompactionManager.stopCompactionById(String)`：按 `TimeUUID` task id 停止单个 active task。
- `CompactionManager.interruptCompactionFor(...)`：按 table metadata、sstable predicate 和 validation flag 停止任务。
- `CompactionManager.getSSTableTasks()`：virtual table 的 task source，过滤 cache save tasks。
- `ActiveCompactions.estimatedRemainingWriteToDiskBytes()`：返回目标目录到剩余写入估算 bytes 的 map。

## 生命周期与调用链

普通 compaction active lifecycle：

```text
CompactionTask.runMayThrow()
  -> new CompactionIterator(..., taskId)
  -> activeCompactions.beginCompaction(ci)
  -> if strategy inactive: throw CompactionInterruptedException(ci.getCompactionInfo())
  -> while ci.hasNext()
       -> writer.append(ci.next())
       -> ci.setTargetDirectory(writer.getSStableDirectory().path())
       -> CompactionManager.compactionRateLimiterAcquire(...)
  -> writer.finish()
  -> finally activeCompactions.finishCompaction(ci)
       -> bytesCompacted/compressedBytesCompacted/totalCompactionsCompleted
```

Operator observation:

```text
nodetool compactionstats -V
  -> NodeProbe.getCompactionManagerProxy().getCompactions()
  -> CompactionManager.getCompactions()
  -> active.getCompactions()
  -> CompactionInfo.asMap()
  -> CompactionStats.reportCompactionTable(..., vtableOutput=true)
```

Virtual table observation:

```text
SELECT * FROM system_views.sstable_tasks
  -> SSTableTasksTable.data()
  -> CompactionManager.getSSTableTasks()
  -> active.getCompactions()
  -> CompactionInfo rows
```

Stop-by-id:

```text
nodetool stop --compaction-id <uuid>
  -> Stop.execute()
  -> NodeProbe.stopById(compactionId)
  -> CompactionManager.stopCompactionById(compactionId)
  -> active holders snapshot
  -> holder.getCompactionInfo().getTaskId() == TimeUUID.fromString(compactionId)
  -> holder.stop()
  -> CompactionIterator/CompactionTask later observes isStopRequested()
  -> throw CompactionInterruptedException
```

Space estimate:

```text
CompactionTask.buildCompactionCandidatesForAvailableDiskSpace()
  -> ActiveCompactions.estimatedRemainingWriteToDiskBytes()
  -> for each active CompactionInfo
       -> getTargetDirectories()
       -> estimatedRemainingWriteToDiskBytes() if OperationType.writesData
       -> split remaining bytes across target directories
  -> Directories.hasDiskSpaceForCompactionsAndStreams(...)
```

## 配置项

- `concurrent_compactors`：影响同时 active 的 compaction tasks 数量；定义见 `src/java/org/apache/cassandra/config/Config.java:335`。
- `compaction_throughput`：影响 active task 的 rate limiter 和 `compactionstats` 剩余时间估算；定义见 `Config.java:337`。
- `min_free_space_per_drive` 与 `max_space_usable_for_compactions_in_percentage`：与 active remaining write estimate 一起参与空间判定。
- JMX `CompactionManagerMBean.stopCompaction(String)` / `stopCompactionById(String)`：运行时控制入口。
- nodetool `stop`：支持 operation type 参数或 `-id/--compaction-id`。

## Metrics、日志与诊断

- `CompactionMetrics.BytesCompacted` / `CompressedBytesCompacted` / `TotalCompactionsCompleted`：`ActiveCompactions.finishCompaction()` 更新。
- `PendingTasksByTableName`：用于 `compactionstats` pending tasks 分表输出，辅助判断 stop 后 backlog 是否下降。
- `CompactionsReduced` / `SSTablesDroppedFromCompaction` / `CompactionsAborted`：空间缩小和失败指标，结合 active task id 定位具体任务。
- `compactionstats -V`：输出 task id 和 target directory，是 stop-by-id 的主要入口。
- `system_views.sstable_tasks`：CQL 方式查看 active task id、kind、progress、target directory。
- `CompactionInterruptedException`：cooperative stop 的显式异常文本包含 `CompactionInfo`。

## 运维关注点

- stop-by-id 前先用 `nodetool compactionstats -V` 或 `SELECT * FROM system_views.sstable_tasks` 取 task id；普通 `compactionstats` 也有 id，但 `-V` 更贴近 virtual table 字段。
- stop 不会阻塞等待任务结束；需要循环观察 active task 是否从 JMX/virtual table 消失。
- 如果 task 已接近 point-of-no-return，可能在下一次 stop polling 前继续完成；这就是 cooperative cancellation 的代价。
- VIEW_BUILD、INDEX_SUMMARY、cache save 等 no-sstable/global task 的 stop 语义与普通 compaction 不同，不能只按 SSTable set 推断。
- 空间不足排查要同时看 active tasks 的 target directory，因为 running task remaining write 会影响新 compaction 是否能启动。

## 性能瓶颈

- active registry 很小但所有 stop/observe 都要遍历；如果未来大量小任务并发，应重新评估 copy/synchronized set 成本。
- `CompactionInfo.asMap()` 会 join SSTable set；verbose 输出在大 compaction 上可能生成较长字符串。
- remaining write estimate 将任务剩余 bytes 平分到 target directories，是 conservative/worst-case 近似，不是精确 writer 输出。
- stop polling 发生在 partition/row transform 等安全点；单个超大 partition 或 writer I/O 卡顿会延迟响应。
- global pause 使用计数器，嵌套 pause 正常，但泄漏 pauser 会让 global holder 持续被视为 stop requested。

## 常见故障

- `nodetool stop --compaction-id` 后任务仍存在：确认 id 是否来自当前 active task，等待下一个 polling point，并检查是否卡在 writer/disk I/O。
- `compactionstats -V` 看到 target directory 为空：某些 task 没有 metadata 或没有 target directory，例如部分 global/cache/index summary task。
- `system_views.sstable_tasks` 没有 cache save：`getSSTableTasks()` 显式过滤 key/row/counter cache save tasks。
- stop 造成 `CompactionInterruptedException`：这是预期 cooperative cancellation，不应误判为 JVM 或 disk failure。
- 空间估算过高：active compaction uses uncompressed progress and compression ratio，estimate 偏保守；结合 actual disk usage 判断。

## 测试基线与缺口

- `test/unit/org/apache/cassandra/db/compaction/ActiveCompactionsTest.java`：active tracking race、secondary index tracking、index summary no-sstable stop、view build/cache tracking。
- `test/unit/org/apache/cassandra/tools/nodetool/CompactionStatsTest.java`：ordinary/human-readable/vtable compactionstats 输出、task id、target directory 和 metrics 字段。
- `test/unit/org/apache/cassandra/db/virtual/SSTableTasksTableTest.java`：`vts.sstable_tasks` row 与 empty result。
- `test/unit/org/apache/cassandra/db/compaction/CompactionIteratorTest.java`：iterator stop 在 row/partition transform 中抛 `CompactionInterruptedException`。
- `test/distributed/org/apache/cassandra/distributed/test/SecondaryIndexCompactionTest.java`：index CFS active compaction remaining write estimate。
- `test/distributed/org/apache/cassandra/distributed/test/UpgradeSSTablesTest.java`：ByteBuddy latch 观察 `ActiveCompactions.beginCompaction()` 中 UPGRADE_SSTABLES/COMPACTION task type。
- gap：缺真实 long-running compaction 的 stop-by-id/stop-by-type live cancellation 测试，缺 stop 后 metrics/virtual table/JMX 的一致性断言。
