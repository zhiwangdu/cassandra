# Module: Compaction Strategies Deep Dive

## 范围

本模块专门覆盖 Cassandra 表级 compaction strategy 的选择层：`SizeTieredCompactionStrategy`、`LeveledCompactionStrategy`、`TimeWindowCompactionStrategy`、`UnifiedCompactionStrategy`，以及 `CompactionStrategyManager` 对 repaired/unrepaired/pending repair、token-range holder 和策略实例的路由。`CompactionTask` 的 scanner/iterator/writer 执行细节在 `research/module-sstable-compaction.md` 和 `research/flow-compaction.md` 展开，本模块只解释哪些 SSTable 会被选中、为什么被选中、对应配置如何影响读写放大和运维风险。

## 设计目标

- 用同一个 `AbstractCompactionStrategy` 抽象表达后台任务、maximal task、user-defined task 和 pending task 估算；抽象方法定义见 `src/java/org/apache/cassandra/db/compaction/AbstractCompactionStrategy.java:176-214`。
- 让表级 `CompactionParams` 保存 class/enabled/min/max threshold/tombstone overlap 等统一选项，并在支持 threshold 的策略上补默认值；解析逻辑见 `src/java/org/apache/cassandra/schema/CompactionParams.java:121-145`。
- STCS 以低写放大为主，通过相近大小 bucket 与热度排序选择 SSTable；bucket 选择见 `src/java/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategy.java:79-130`。
- LCS 以降低读放大为主，把 SSTable 组织为 level，并在 L0 backlog 与高层超额之间选择任务；manifest 选择见 `src/java/org/apache/cassandra/db/compaction/LeveledManifest.java:199-301`。
- TWCS 面向时间序列和 TTL 数据，把 SSTable 按时间窗口分桶，新窗口用 STCS，旧窗口避免跨窗口重写；bucket/window 逻辑见 `src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategy.java:172-190`、`src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategy.java:296-363`。
- UCS 用 scaling parameter、density level 和 shard boundary 统一 tiered/leveled 取舍，并能让 flush/compaction writer 直接输出分片 SSTable；设计说明见 `src/java/org/apache/cassandra/db/compaction/UnifiedCompactionStrategy.md:19-23`，实现入口见 `src/java/org/apache/cassandra/db/compaction/UnifiedCompactionStrategy.java:88-104`。

## 解决的问题

- 后台 compaction 不能只按表全局 FIFO 扫描；`CompactionStrategyManager.getNextBackgroundTask()` 会先处理 pending/transient repair cleanup，再按 holder 估算的剩余任务数排序调用策略 supplier，见 `src/java/org/apache/cassandra/db/compaction/CompactionStrategyManager.java:192-239`。
- 同一张表可能同时存在 repaired、unrepaired、pending repair 和 transient pending repair 的 SSTable；manager 持有四类 holder，字段见 `src/java/org/apache/cassandra/db/compaction/CompactionStrategyManager.java:121-129`。
- token range 被分到多个数据目录时，holder 需要按 disk boundary 找策略实例；路由逻辑见 `src/java/org/apache/cassandra/db/compaction/CompactionStrategyManager.java:338-389`。
- STCS 要避免把大小差异过大的 SSTable 混在一起，同时在达到 `min_threshold` 后优先 compact 热 bucket；bucket 修剪和 hotness 见 `src/java/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategy.java:133-176`。
- LCS 要在 L0 过多、上层超额、starved overlap 和 bootstrap 模式之间选择，不只是“下一层满了就 compact”；主要分支见 `src/java/org/apache/cassandra/db/compaction/LeveledManifest.java:199-301`。
- TWCS 要让旧时间窗口的数据尽快形成稳定大 SSTable，便于 TTL 数据整窗过期；过期 SSTable 检查和 overlap 行为见 `src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategy.java:115-147`。
- UCS 要用一个参数化模型覆盖 leveled/tiered/neutral 三类策略，并通过 shard 数减少单个大任务；`fanoutFromScalingParameter()`、`thresholdFromScalingParameter()` 和参数解析见 `src/java/org/apache/cassandra/db/compaction/UnifiedCompactionStrategy.java:106-130`。

## 设计取舍

- STCS 写放大低、实现简单，但大小相近的 SSTable 会长期重叠，读路径可能触碰更多 SSTable；策略用 hotness 选择更值得 compact 的 bucket，见 `src/java/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategy.java:110-159`。
- LCS 降低每层 overlap，读放大更可控，但高写入量和 L0 backlog 会推高写放大；L0 超过阈值时可以退回 STCS in L0，见 `src/java/org/apache/cassandra/db/compaction/LeveledManifest.java:304-329`。
- TWCS 牺牲跨窗口全局最优压缩，换取 TTL/time-series 场景下整窗清理和较少旧数据重写；旧窗口只需至少 2 个 SSTable 就可 compact，见 `src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategy.java:296-363`。
- TWCS 默认禁用 tombstone compaction 选项，除非用户显式传入相关选项；构造函数处理见 `src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategy.java:65-80`。
- UCS 把 leveled/tiered 视为同一模型的不同 `W` 值，配置表达力更强，但选择过程依赖 density、overlap inclusion、survival factor 和 shard manager，调参复杂度更高；设计取舍见 `src/java/org/apache/cassandra/db/compaction/UnifiedCompactionStrategy.md:25-56`。
- `unsafe_aggressive_sstable_expiration` 可以更激进地丢弃过期 SSTable，但必须由系统属性显式允许；TWCS 和 UCS 的 gate 分别见 `src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategyOptions.java:62-82`、`src/java/org/apache/cassandra/db/compaction/unified/Controller.java:203-215`。

## 核心类

| 类 | 作用 |
|---|---|
| `CompactionStrategyManager` | 表级策略总入口，持有 repaired/unrepaired/pending repair holders、表级 params、disk boundary router，构造和 startup 见 `src/java/org/apache/cassandra/db/compaction/CompactionStrategyManager.java:151-190` |
| `CompactionStrategyHolder` | 为普通 repaired/unrepaired SSTable 创建每 token partition 一个 strategy；`setStrategyInternal()` 见 `src/java/org/apache/cassandra/db/compaction/CompactionStrategyHolder.java:44-73` |
| `PendingRepairHolder` | 为 pending repair SSTable 创建 per-range `PendingRepairManager`；`setStrategyInternal()` 见 `src/java/org/apache/cassandra/db/compaction/PendingRepairHolder.java:45-74` |
| `AbstractCompactionStrategy` | strategy 基类，统一 tombstone/log/enabled 选项和 pause/resume/startup/shutdown 生命周期，构造与生命周期见 `src/java/org/apache/cassandra/db/compaction/AbstractCompactionStrategy.java:106-174` |
| `SizeTieredCompactionStrategy` | 按 size bucket/hotness 选择后台任务，核心选择见 `src/java/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategy.java:79-107` |
| `SizeTieredCompactionStrategyOptions` | `min_sstable_size`、`bucket_low`、`bucket_high` 默认值和校验，见 `src/java/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategyOptions.java:24-31`、`src/java/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategyOptions.java:67-96` |
| `LeveledCompactionStrategy` | 管理 LCS options、manifest、LCS task 创建和 L0/tombstone fallback，核心后台任务见 `src/java/org/apache/cassandra/db/compaction/LeveledCompactionStrategy.java:131-180` |
| `LeveledManifest` | 保存各 level 的 SSTable set、last compacted key、score 计算和候选选择，字段与构造见 `src/java/org/apache/cassandra/db/compaction/LeveledManifest.java:71-91` |
| `TimeWindowCompactionStrategy` | 按 SSTable 最大时间戳映射窗口，并在最新窗口/旧窗口中使用不同 threshold，构造和后台任务见 `src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategy.java:65-107` |
| `TimeWindowCompactionStrategyOptions` | TWCS window、timestamp resolution、expired check、unsafe aggressive expiration 和内嵌 STCS 选项，默认值见 `src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategyOptions.java:37-47` |
| `UnifiedCompactionStrategy` | UCS 主策略，负责 level formation、compaction pick、flush writer 与 compaction writer 创建，主字段见 `src/java/org/apache/cassandra/db/compaction/UnifiedCompactionStrategy.java:78-87` |
| `Controller` | UCS 参数控制器，解析 scaling/min size/shard/target size/growth/survival/overlap 等选项，选项常量见 `src/java/org/apache/cassandra/db/compaction/unified/Controller.java:50-150` |
| `UnifiedCompactionTask` | UCS compaction task，按 shard density 创建 `ShardedCompactionWriter`，见 `src/java/org/apache/cassandra/db/compaction/unified/UnifiedCompactionTask.java:40-60` |
| `ShardedCompactionWriter` | compaction 输出跨 shard boundary 切换 writer，构造与切换见 `src/java/org/apache/cassandra/db/compaction/unified/ShardedCompactionWriter.java:48-82` |

## 核心接口

- `AbstractCompactionStrategy.getNextBackgroundTask()`：后台 compaction 入口，所有策略都通过它返回带 `LifecycleTransaction` 的任务；接口定义见 `src/java/org/apache/cassandra/db/compaction/AbstractCompactionStrategy.java:176-183`。
- `AbstractCompactionStrategy.getMaximalTask()`：nodetool compact 或 maximal compaction 入口，定义见 `src/java/org/apache/cassandra/db/compaction/AbstractCompactionStrategy.java:185-193`。
- `AbstractCompactionStrategy.getUserDefinedTask()`：用户指定 SSTable compaction 入口，定义见 `src/java/org/apache/cassandra/db/compaction/AbstractCompactionStrategy.java:195-204`。
- `AbstractCompactionStrategy.getEstimatedRemainingTasks()`：pending task 估算入口，manager 根据 holder 估算排序，定义见 `src/java/org/apache/cassandra/db/compaction/AbstractCompactionStrategy.java:211-214`，排序使用见 `src/java/org/apache/cassandra/db/compaction/CompactionStrategyManager.java:218-230`。
- `CompactionParams.create()`：表 schema 层把 compaction options 转成 class/enabled/threshold/tombstone 参数，见 `src/java/org/apache/cassandra/schema/CompactionParams.java:121-145`。
- `Controller.getNumShards()`：UCS flush/compaction writer 根据 density、flush size、min size、target size 和 growth 计算 shard 数，见 `src/java/org/apache/cassandra/db/compaction/unified/Controller.java:264-355`。
- `UnifiedCompactionStrategy.createSSTableMultiWriter()`：UCS flush 输出可直接生成 sharded SSTable，见 `src/java/org/apache/cassandra/db/compaction/UnifiedCompactionStrategy.java:253-287`。

## 核心数据结构

- `CompactionParams`：保存 strategy class、options map、enabled 标志和 tombstone overlap 策略；option enum 见 `src/java/org/apache/cassandra/schema/CompactionParams.java:50-63`，默认 STCS/fallback 见 `src/java/org/apache/cassandra/schema/CompactionParams.java:90-106`。
- STCS bucket：由相近 size pair 组成，并按 `min_threshold`/`max_threshold` 修剪；bucket 生成和选择见 `src/java/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategy.java:79-130`。
- LCS generations：`LeveledManifest` 的 `generations` 保存每个 level 的 SSTable set，最大 level 容量由 `fanout` 和目标 SSTable size 计算；容量计算见 `src/java/org/apache/cassandra/db/compaction/LeveledManifest.java:180-193`。
- TWCS bucket：`getBuckets()` 按 SSTable 最大时间戳落入 window boundary，同时维护 `sstableCountByBuckets` 供观测，见 `src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategy.java:52-64`、`src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategy.java:242-272`。
- UCS `Level`：保存 survival factor、scaling parameter、fanout、threshold、density range 和 max overlap；字段见 `src/java/org/apache/cassandra/db/compaction/UnifiedCompactionStrategy.java:542-565`。
- UCS bucket/pick：level 内通过 overlap sets 构造 bucket，并选择 overlap 最高的 bucket 形成 compaction pick；选择见 `src/java/org/apache/cassandra/db/compaction/UnifiedCompactionStrategy.java:588-679`。
- Shard boundaries：UCS writer 根据 shard manager 的 token boundaries 切换输出；`ShardedCompactionWriter` 切换条件见 `src/java/org/apache/cassandra/db/compaction/unified/ShardedCompactionWriter.java:64-90`。

## 生命周期

```text
Table schema loaded:
  -> TableParams.compaction
  -> CompactionParams.create(...)
  -> CompactionStrategyManager(...)
     -> CompactionStrategyHolder / PendingRepairHolder
     -> setStrategy(params)
     -> startup()
        -> addSSTables(canonical live SSTables)
        -> start strategy holders
        -> propagate early open, fanout, max SSTable size, strategy name

Background compaction:
  -> CompactionManager.submitBackground(cfs)
  -> CompactionStrategyManager.getNextBackgroundTask(gcBefore)
     -> repair-finished cleanup task first
     -> collect holder task suppliers
     -> sort by estimated remaining tasks
     -> call concrete strategy.getNextBackgroundTask(...)
        -> choose SSTables
        -> cfs.getTracker().tryModify(...)
        -> return CompactionTask / LeveledCompactionTask / TimeWindowCompactionTask / UnifiedCompactionTask
```

Manager startup loads canonical SSTables into holders, starts strategies, and enables compaction logger when strategy `logAll` is set; startup details见 `src/java/org/apache/cassandra/db/compaction/CompactionStrategyManager.java:313-336`。Strategy pause/resume/shutdown state lives in the base class and is guarded by `isActive`, see `src/java/org/apache/cassandra/db/compaction/AbstractCompactionStrategy.java:142-174`。

## 调用链

- Manager 选择链：`CompactionManager.submitBackground()` 提交后台候选，之后进入 `CompactionStrategyManager.getNextBackgroundTask()`；提交见 `src/java/org/apache/cassandra/db/compaction/CompactionManager.java:230-258`，manager 选择见 `src/java/org/apache/cassandra/db/compaction/CompactionStrategyManager.java:192-239`。
- Holder 路由链：普通 SSTable 由 `CompactionStrategyHolder.getStrategyFor()` 按 router index 找策略，pending repair SSTable 由 `PendingRepairHolder.getStrategyFor()` 取 `PendingRepairManager` 内部策略；见 `src/java/org/apache/cassandra/db/compaction/CompactionStrategyHolder.java:91-112`、`src/java/org/apache/cassandra/db/compaction/PendingRepairHolder.java:84-122`。
- STCS 后台链：过滤 live/uncompacting/non-suspect SSTable，按 size bucket 选择候选，`tryModify()` 成功后创建 `CompactionTask`；见 `src/java/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategy.java:79-107`、`src/java/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategy.java:178-202`。
- LCS 后台链：`LeveledCompactionStrategy.getNextBackgroundTask()` 先问 `LeveledManifest.getCompactionCandidates()`，失败时 fallback 到 droppable tombstone SSTable，然后创建 `LeveledCompactionTask` 或 `SingleSSTableLCSTask`；见 `src/java/org/apache/cassandra/db/compaction/LeveledCompactionStrategy.java:131-180`。
- LCS manifest 链：bootstrap 模式只在 L0 做 STCS，高层按 score 从高到低扫描，必要时优先 L0 compaction；见 `src/java/org/apache/cassandra/db/compaction/LeveledManifest.java:199-301`。
- TWCS 后台链：过滤候选、周期性计算 fully expired SSTable、按窗口选择最新 bucket，最后用 `tryModify()` 创建 `TimeWindowCompactionTask`；见 `src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategy.java:82-107`、`src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategy.java:115-147`。
- UCS 后台链：刷新 shard manager，构造 selection context，剔除 suspect/early SSTable，形成 density levels，选择 overlap 最高 pick，创建 `UnifiedCompactionTask`；见 `src/java/org/apache/cassandra/db/compaction/UnifiedCompactionStrategy.java:299-344`、`src/java/org/apache/cassandra/db/compaction/UnifiedCompactionStrategy.java:369-390`。

## 配置项

| 范围 | 配置项 | 默认/校验 | 作用 |
|---|---|---|---|
| 表级通用 | `class`、`enabled`、`min_threshold`、`max_threshold`、`provide_overlapping_tombstones` | option enum 见 `src/java/org/apache/cassandra/schema/CompactionParams.java:50-63`，默认 min=4/max=32/enabled=true 见 `src/java/org/apache/cassandra/schema/CompactionParams.java:79-88` | 选择策略类、开关自动 compaction、配置阈值和 tombstone overlap 行为 |
| 全局默认 | `default_compaction` | `DatabaseDescriptor.getDefaultCompaction()` 未设置时回退 STCS，见 `src/java/org/apache/cassandra/schema/CompactionParams.java:90-106`；模板注释见 `conf/cassandra.yaml:1202-1209` | 未显式指定表级策略时的默认策略 |
| 全局并发/吞吐 | `concurrent_compactors`、`compaction_throughput` | 字段见 `src/java/org/apache/cassandra/config/Config.java:335-337`，并发默认/校验见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:777-781` | 控制后台 compaction executor 并发和限速 |
| 全局空间 | `max_space_usable_for_compactions_in_percentage` | 字段见 `src/java/org/apache/cassandra/config/Config.java:343-344` | 影响 compaction 空间可用性判断 |
| STCS | `min_sstable_size`、`bucket_low`、`bucket_high` | 默认值见 `src/java/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategyOptions.java:24-31`，校验见 `src/java/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategyOptions.java:67-96` | 定义 size bucket 边界和小 SSTable 合并行为 |
| LCS | `sstable_size_in_mb`、`fanout_size`、`single_sstable_uplevel` | 选项常量见 `src/java/org/apache/cassandra/db/compaction/LeveledCompactionStrategy.java:45-57`，构造解析见 `src/java/org/apache/cassandra/db/compaction/LeveledCompactionStrategy.java:64-103` | 控制每层目标 SSTable 大小、level fanout 和单 SSTable 升层 |
| LCS 系统属性 | `DISABLE_STCS_IN_L0`、`TOLERATE_SSTABLE_SIZE` | 定义见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:197`、`src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:604` | 禁用 L0 的 STCS fallback，或允许非常小/大的 LCS SSTable size |
| TWCS | `compaction_window_unit`、`compaction_window_size`、`timestamp_resolution`、`expired_sstable_check_frequency_seconds`、`unsafe_aggressive_sstable_expiration` | 默认值见 `src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategyOptions.java:37-47`，校验见 `src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategyOptions.java:94-165` | 定义窗口粒度、时间戳单位、过期检查频率和激进过期策略 |
| TWCS 系统属性 | `ALLOW_UNSAFE_AGGRESSIVE_SSTABLE_EXPIRATION` | 定义见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:48`，TWCS gate 见 `src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategyOptions.java:62-82` | 允许忽略 overlap 做激进过期 SSTable 清理 |
| UCS | `scaling_parameters`、`min_sstable_size`、`flush_size_override`、`base_shard_count`、`target_sstable_size`、`sstable_growth`、`survival_factor`、`max_sstables_to_compact`、`overlap_inclusion_method` | 选项常量见 `src/java/org/apache/cassandra/db/compaction/unified/Controller.java:50-150`，解析见 `src/java/org/apache/cassandra/db/compaction/unified/Controller.java:408-460` | 控制 UCS fanout/threshold、density level、shard 数、单次任务规模和 overlap 选择 |
| UCS 系统属性 | `UCS_BASE_SHARD_COUNT`、`UCS_MIN_SSTABLE_SIZE`、`UCS_OVERLAP_INCLUSION_METHOD`、`UCS_SCALING_PARAMETER`、`UCS_SSTABLE_GROWTH`、`UCS_SURVIVAL_FACTOR`、`UCS_TARGET_SSTABLE_SIZE` | 定义见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:609-615` | 为 UCS 提供节点级默认值 |

## Metrics

- `CompactionMetrics.pendingTasks`、`completedTasks`、`bytesCompacted`、`compactionsReduced`、`compactionsAborted` 是 compaction 全局观测入口，定义见 `src/java/org/apache/cassandra/metrics/CompactionMetrics.java:40-69`。
- `TableMetrics.sstablesPerReadHistogram` 和 `sstablesPerRangeReadHistogram` 是策略效果的读放大指标，定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:110-113`。
- `TableMetrics.compactionBytesWritten` 反映 compaction 写放大的一部分，定义见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:126-129`，更新见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:297-299`。
- `estimatedRemainingTasks` 是 strategy 向 manager 暴露的调度信号；manager 使用它排序 holder supplier，见 `src/java/org/apache/cassandra/db/compaction/CompactionStrategyManager.java:218-230`。
- LCS 暴露 level 信息和 estimated task；`getAllLevelSize()` 等方法见 `src/java/org/apache/cassandra/db/compaction/LeveledCompactionStrategy.java:105-118`。
- TWCS 维护 `sstableCountByBuckets` 供每窗口 SSTable 数观测，字段见 `src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategy.java:52-64`。
- UCS 在选择时更新 `estimatedRemainingTasks`，level pick 统计见 `src/java/org/apache/cassandra/db/compaction/UnifiedCompactionStrategy.java:588-637`。

## 日志

- STCS 在 `tryModify()` 竞争失败时记录 retry warning，见 `src/java/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategy.java:190-194`。
- LCS 对异常大的/小的 `sstable_size_in_mb` 记录 warning，见 `src/java/org/apache/cassandra/db/compaction/LeveledCompactionStrategy.java:78-83`。
- LCS 在 `tryModify()` 失败时记录 retry warning，见 `src/java/org/apache/cassandra/db/compaction/LeveledCompactionStrategy.java:161-164`。
- LCS 当数据到达最大 level 且仍然超额时记录 warning，见 `src/java/org/apache/cassandra/db/compaction/LeveledCompactionStrategy.java:260-266`。
- TWCS 对非默认 `timestamp_resolution` 记录 warning，见 `src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategyOptions.java:64-68`。
- TWCS fully expired SSTable 选择、overlap 检查和加入过期 SSTable 有 debug 日志，见 `src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategy.java:127-143`。
- TWCS 在 `tryModify()` 竞争失败时记录 retry warning，见 `src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategy.java:95-100`。
- UCS 在 `tryModify()` 失败时记录 reference leak/race warning，见 `src/java/org/apache/cassandra/db/compaction/UnifiedCompactionStrategy.java:246-249`。
- UCS 对最终选择的 level 和 bucket 写 debug 日志，见 `src/java/org/apache/cassandra/db/compaction/UnifiedCompactionStrategy.java:385-387`。
- UCS controller 在未开启系统属性却配置 unsafe aggressive expiration 时记录 warning 并关闭该行为，见 `src/java/org/apache/cassandra/db/compaction/unified/Controller.java:207-214`。
- `ShardedCompactionWriter` 在跨 shard boundary 切换 writer 时写 debug 日志，见 `src/java/org/apache/cassandra/db/compaction/unified/ShardedCompactionWriter.java:73-77`。

## 运维关注点

- 选择 strategy 先看 workload：STCS 更适合写入重、读放大可接受的场景；LCS 更适合读延迟敏感但能承受更高写放大的场景；TWCS 适合时间序列/TTL；UCS 用 `scaling_parameters` 在 leveled/tiered 中间调节，设计说明见 `src/java/org/apache/cassandra/db/compaction/UnifiedCompactionStrategy.md:44-53`。
- pending compaction 增长要同时看 executor 并发、吞吐限速、磁盘空间、表级 strategy 和 repaired/pending repair 分组；manager 对 repair 相关 holder 有独立路径，见 `src/java/org/apache/cassandra/db/compaction/CompactionStrategyManager.java:121-129`。
- LCS 的 L0 backlog 会显著放大读延迟；`LeveledManifest` 明确在 L0 和高 level score 之间做优先级选择，见 `src/java/org/apache/cassandra/db/compaction/LeveledManifest.java:213-301`。
- TWCS window 要和写入时间顺序、TTL 和 `default_time_to_live` 配套；窗口越小，旧窗口越容易稳定，但 SSTable 数和元数据也会增加。TTL 配置模板见 `conf/cassandra.yaml:1814-1815`。
- `unsafe_aggressive_sstable_expiration` 会绕过 overlap 安全保守性，生产启用前必须确认旧数据不会与新窗口交叠；系统属性 gate 见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:48`。
- UCS 调参不要只看 pending tasks，还要看 shard 数、flush size 估算、target SSTable size 和 overlap inclusion；controller 计算 shard 的分支见 `src/java/org/apache/cassandra/db/compaction/unified/Controller.java:264-355`。
- 自动 compaction 可以由表级 `enabled` 或 manager pause/resume 影响；表级 enabled 解析见 `src/java/org/apache/cassandra/schema/CompactionParams.java:121-145`，manager pause/resume 见 `src/java/org/apache/cassandra/db/compaction/CompactionStrategyManager.java:271-311`。

## 性能瓶颈

- STCS 主要瓶颈是读放大和 tombstone 清理延迟：相近大小的 SSTable 才容易同批 compact，热点小 SSTable 可被优先挑选，但冷重叠 SSTable 可能长期存在；hotness 逻辑见 `src/java/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategy.java:133-176`。
- LCS 主要瓶颈是 L0 积压和写放大：高层数据被反复重写，L0 太多时读路径仍会访问大量 SSTable；L0 fallback 见 `src/java/org/apache/cassandra/db/compaction/LeveledManifest.java:304-329`。
- TWCS 主要瓶颈是乱序写入和窗口选择错误：旧窗口如果仍有新写入，过期清理会被 overlap 阻止；expired check 逻辑见 `src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategy.java:115-147`。
- UCS 主要瓶颈是 overlap set 构造、density level 形成和 shard writer 切换；level formation 见 `src/java/org/apache/cassandra/db/compaction/UnifiedCompactionStrategy.java:461-507`。
- 全部策略都受磁盘吞吐、compaction throughput、可用空间和 `CompactionTask.reduceScopeForLimitedSpace()` 影响；空间缩小逻辑见 `src/java/org/apache/cassandra/db/compaction/CompactionTask.java:98-114`。

## 常见故障

- `ConfigurationException`：strategy options 不合法。STCS bucket 校验见 `src/java/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategyOptions.java:67-96`，TWCS window 校验见 `src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategyOptions.java:94-165`，UCS option 解析见 `src/java/org/apache/cassandra/db/compaction/unified/Controller.java:408-460`。
- 后台没有任务：表级 compaction 被禁用、strategy inactive、候选 SSTable 正在 compact 或 suspect。base lifecycle 见 `src/java/org/apache/cassandra/db/compaction/AbstractCompactionStrategy.java:142-174`，STCS 过滤见 `src/java/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategy.java:79-107`。
- LCS 卡在 L0：可能写入速度超过 L0 compaction，或 `DISABLE_STCS_IN_L0` 改变了 fallback；相关系统属性见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:197`。
- TWCS 过期 SSTable 未被丢弃：通常是 overlap 检查认为仍不安全，或 aggressive expiration 未被系统属性允许；TWCS 过期候选见 `src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategy.java:115-147`。
- UCS 配置了 unsafe aggressive expiration 但无效：controller 会在未开启系统属性时记录 warning 并关闭，见 `src/java/org/apache/cassandra/db/compaction/unified/Controller.java:207-214`。
- `tryModify()` 失败或 retry warning：说明候选 SSTable 已被并发任务占用或状态变化，需要看是否有 repair、user-defined compaction、cleanup、scrub 等任务同时运行；各策略 warning 见 `src/java/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategy.java:190-194`、`src/java/org/apache/cassandra/db/compaction/LeveledCompactionStrategy.java:161-164`、`src/java/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategy.java:95-100`、`src/java/org/apache/cassandra/db/compaction/UnifiedCompactionStrategy.java:246-249`。
- UCS shard writer 产出异常多 SSTable：检查 `base_shard_count`、`target_sstable_size`、`sstable_growth` 和 flush size 估算；`getNumShards()` 分支见 `src/java/org/apache/cassandra/db/compaction/unified/Controller.java:264-355`。

## 测试用例

- STCS options 和 bucket 选择：`test/unit/org/apache/cassandra/db/compaction/SizeTieredCompactionStrategyTest.java:68-148`。
- LCS schema/options、level grouping 和 level validation：`test/unit/org/apache/cassandra/db/compaction/LeveledCompactionStrategyTest.java:96-210`。
- TWCS options、window bounds、newest bucket、expired SSTable 和 overlap 行为：`test/unit/org/apache/cassandra/db/compaction/TimeWindowCompactionStrategyTest.java:80-376`。
- 表级 minor compaction trigger、local strategy 和 enable/disable：`test/unit/org/apache/cassandra/db/compaction/CompactionsCQLTest.java:96-130`、`test/unit/org/apache/cassandra/db/compaction/CompactionsCQLTest.java:208-280`。
- UCS strategy 基础选择：`test/unit/org/apache/cassandra/db/compaction/UnifiedCompactionStrategyTest.java:80-180`。
- UCS controller/sharded writer 单测入口：`test/unit/org/apache/cassandra/db/compaction/unified/ControllerTest.java`、`test/unit/org/apache/cassandra/db/compaction/unified/ShardedMultiWriterTest.java`、`test/unit/org/apache/cassandra/db/compaction/unified/ShardedCompactionWriterTest.java`。
- UCS density 和 compaction disk space distributed 覆盖：`test/distributed/org/apache/cassandra/distributed/test/UnifiedCompactionDensitiesTest.java`、`test/distributed/org/apache/cassandra/distributed/test/CompactionDiskSpaceTest.java`。
- overlap/failure 场景 distributed 覆盖：`test/distributed/org/apache/cassandra/distributed/test/CompactionOverlappingSSTableTest.java`。
- 生产运行面的 `compaction_task_snapshot_space_reduction` 与 `compaction_disk_space_failure_coverage` 场景由 `module-compaction-operations-failure-matrix.md` 和 `research/tools/check-compaction-operations-drift.py` 继续保护。
