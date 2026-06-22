# Module: System Distributed State Matrix

## 范围

本模块覆盖 `system_distributed` replicated system keyspace 的表定义、写入方、读取方、清理策略、配置、metrics、日志和测试覆盖。重点是 `repair_history`、`parent_repair_history`、`view_build_status`、`partition_denylist`、`auto_repair_history`、`auto_repair_priority` 的 runtime owner，而不是普通 system keyspace 或 virtual table；源码 CQL 列契约见 `research/module-system-table-column-contract.md`，本地 `system` 表矩阵见 `research/module-system-tables-core-matrix.md`。

## 设计目标

- 把需要跨节点可见的 repair、MV build、denylist 和 auto-repair 调度状态放到 replicated `system_distributed`，避免只保存在本地 `system` 表。
- 用 `SystemDistributedKeyspace.metadata()` 统一创建 keyspace，RF 为 `max(cassandra.system_distributed.default_rf, default_keyspace_rf)`，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:213-228` 和 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:540`。
- 用表级 owner 控制写入与清理：repair history 依赖 TTL/TWCS，MV status 显式删除，partition denylist 由 operator/JMX 和 cache refresh 控制，auto-repair history/priority 由 scheduler turn election 控制。
- 让 `AUTOREPAIR_ENABLE` 同时决定 schema generation、auto-repair tables 是否出现在 metadata、MBean/scheduler 是否暴露，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:84-117`、`src/java/org/apache/cassandra/service/AutoRepairService.java:62-78`。

## 解决的问题

- Repair coordinator 需要记录 parent repair 与每个 table/range repair job 的开始、成功和失败状态；写入入口是 `RepairCoordinator`、`RepairSession`、`RepairJob` 调用 `SystemDistributedKeyspace`，见 `src/java/org/apache/cassandra/repair/RepairCoordinator.java:421-442`、`src/java/org/apache/cassandra/repair/RepairSession.java:297-331` 和 `src/java/org/apache/cassandra/repair/RepairJob.java:204-229`。
- MV build 需要跨节点展示每个 host 的 build 状态；`ViewBuilder` 写 `STARTED` / `SUCCESS`，`StorageService.getViewBuildStatuses()` 把 host id 转 endpoint 并把缺失 host 填成 `UNKNOWN`，见 `src/java/org/apache/cassandra/db/view/ViewBuilder.java:84-100`、`src/java/org/apache/cassandra/db/view/ViewBuilder.java:206-224` 和 `src/java/org/apache/cassandra/service/StorageService.java:6246-6270`。
- Partition denylist 需要 operator 能在不改业务表的情况下阻断问题 partition；`PartitionDenylist` 用 `system_distributed.partition_denylist` 做持久源，并在 `StorageProxy` 的 CAS、regular write、single-partition read、range read 路径拒绝请求，见 `src/java/org/apache/cassandra/schema/PartitionDenylist.java:56-83`、`src/java/org/apache/cassandra/service/StorageProxy.java:319-324`、`src/java/org/apache/cassandra/service/StorageProxy.java:1122-1138`、`src/java/org/apache/cassandra/service/StorageProxy.java:1870-1881` 和 `src/java/org/apache/cassandra/service/StorageProxy.java:2281-2293`。
- Auto-repair 需要跨节点选择 turn、记录 start/finish、force repair、delete vote 和 priority hosts；`AutoRepairUtils` 预编译表查询/修改语句，主循环和 cleanup 更新表，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:115-180`、`src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:204-220` 和 `src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:480-519`。

## 设计取舍

- `repair_history` / `parent_repair_history` 设置 30 天 TTL 和 TWCS，减少长期运维元数据堆积；代价是过期后无法从系统表追溯旧 repair，定义见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:120-163`。
- Repair history 写入走 `processSilent(..., ConsistencyLevel.ANY)` 并捕获 `Throwable` 只记录 error，避免 repair 主流程被历史表写失败反向打断，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:231-281`、`src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:284-376` 和 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:433-447`。
- `view_build_status` 不用 TTL；删除 view 时由 `SystemDistributedKeyspace.setViewRemoved()` 删除整组 status 并 force flush，避免废弃 view 状态长期影响 `viewbuildstatus`，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:426-455`。
- `partition_denylist` 允许直接 CQL 维护，也提供 JMX helper；内存 cache 先整体构建再替换，避免部分加载窗口放过 denylisted key，见 `src/java/org/apache/cassandra/schema/PartitionDenylist.java:217-238` 和 `src/java/org/apache/cassandra/service/StorageProxy.java:3062-3176`。
- Auto-repair tables 不带 TTL；清理依赖 turn-election 的 ring membership、delete vote、delete_hosts 超时清理和 priority host removal，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:821-989`、`src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:992-1074` 和 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:1076-1129`。

## 核心类

| 类 | 作用 |
|---|---|
| `SystemDistributedKeyspace` | 表定义、metadata、repair history writer、MV status writer/reader/delete helper。见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:63-228`、`src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:231-455` |
| `RepairCoordinator` / `RepairSession` / `RepairJob` | parent repair、repair session、per-table repair job 的 system_distributed 写入 owner。见 `src/java/org/apache/cassandra/repair/RepairCoordinator.java:421-442`、`src/java/org/apache/cassandra/repair/RepairSession.java:297-331`、`src/java/org/apache/cassandra/repair/RepairJob.java:204-229` |
| `ViewBuilder` / `ViewManager` | MV build status 的 start/success/delete owner。见 `src/java/org/apache/cassandra/db/view/ViewBuilder.java:84-100`、`src/java/org/apache/cassandra/db/view/ViewBuilder.java:206-224`、`src/java/org/apache/cassandra/db/view/ViewManager.java:170-171` |
| `PartitionDenylist` | `partition_denylist` 的 cache、load、insert/delete、range/token check owner。见 `src/java/org/apache/cassandra/schema/PartitionDenylist.java:56-83`、`src/java/org/apache/cassandra/schema/PartitionDenylist.java:128-238`、`src/java/org/apache/cassandra/schema/PartitionDenylist.java:245-535` |
| `StorageProxy` | denylist enforcement、JMX load/mutate/config entrypoints。见 `src/java/org/apache/cassandra/service/StorageProxy.java:319-324`、`src/java/org/apache/cassandra/service/StorageProxy.java:1122-1138`、`src/java/org/apache/cassandra/service/StorageProxy.java:1869-1885`、`src/java/org/apache/cassandra/service/StorageProxy.java:3062-3176` |
| `AutoRepair` / `AutoRepairUtils` | auto-repair scheduler, turn election, history/priority read-write-cleanup owner。见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:113-150`、`src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:199-228`、`src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:821-1129` |

## 核心接口

- `SystemDistributedKeyspace.getTableNames()`：按 `AUTOREPAIR_ENABLE` 返回基础表或附加 auto-repair 表，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:102-117`。
- `SystemDistributedKeyspace.startParentRepair()` / `successfulParentRepair()` / `failParentRepair()`：写 parent repair lifecycle，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:231-281`。
- `SystemDistributedKeyspace.startRepairs()` / `successfulRepairJob()` / `failedRepairJob()`：写 per-table/range repair history，包含 mixed-version v3 column 兼容分支，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:284-376`。
- `SystemDistributedKeyspace.startViewBuild()` / `successfulViewBuild()` / `viewStatus()` / `setViewRemoved()`：写读删 MV distributed build status，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:379-430`。
- `StorageProxy.loadPartitionDenylist()` / `denylistKey()` / `removeDenylistKey()` / `isKeyDenylisted()`：operator-facing JMX/API 入口，见 `src/java/org/apache/cassandra/service/StorageProxy.java:3062-3176`。
- `AutoRepairUtils.getAutoRepairHistory()` / `myTurnToRunRepair()` / `insertNewRepairHistory()` / `updateStartAutoRepairHistory()` / `updateFinishAutoRepairHistory()` / `addPriorityHosts()`：auto-repair 表的主读写接口，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:335-430`、`src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:821-1129`。

## 核心数据结构

| 表 | 主键 | 关键列 | 写入方 | 清理/保留 |
|---|---|---|---|---|
| `repair_history` | `(keyspace_name, columnfamily_name), id` | `parent_id`、`range_begin/end`、`coordinator(_port)`、`participants(_v2)`、`status`、`started_at`、`finished_at`、exception | `RepairSession.start()` 写 STARTED；`RepairJob` 写 SUCCESS/FAILED，见 `src/java/org/apache/cassandra/repair/RepairSession.java:297-331`、`src/java/org/apache/cassandra/repair/RepairJob.java:204-229` | 表 TTL 30 天 + TWCS；preview repair 不写，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:120-143` |
| `parent_repair_history` | `parent_id` | `keyspace_name`、`columnfamily_names`、`requested_ranges`、`successful_ranges`、`options`、exception | `RepairCoordinator` 在非 preview parent repair start/success/failure 写，见 `src/java/org/apache/cassandra/repair/RepairCoordinator.java:421-442` | 表 TTL 30 天 + TWCS，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:145-163` |
| `view_build_status` | `(keyspace_name, view_name), host_id` | `status` | `ViewBuilder.start()` 写 STARTED，finish 后写 SUCCESS；`StorageService` / nodetool 读 status，见 `src/java/org/apache/cassandra/db/view/ViewBuilder.java:84-100`、`src/java/org/apache/cassandra/db/view/ViewBuilder.java:206-224`、`src/java/org/apache/cassandra/service/StorageService.java:6246-6270` | 删除 view 时 `setViewRemoved()` 删除并 force flush，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:426-455` |
| `partition_denylist` | `(ks_name, table_name), key` | `key blob` | operator CQL 或 `StorageProxy.denylistKey/removeDenylistKey()` 写删，见 `src/java/org/apache/cassandra/schema/PartitionDenylist.java:245-285`、`src/java/org/apache/cassandra/service/StorageProxy.java:3128-3160` | 无 TTL；operator 删除/截断；cache load 按 per-table/global limit 截断，见 `src/java/org/apache/cassandra/schema/PartitionDenylist.java:385-513` |
| `auto_repair_history` | `repair_type, host_id` | `repair_turn`、`repair_start_ts`、`repair_finish_ts`、`delete_hosts`、`delete_hosts_update_time`、`force_repair` | `AutoRepairUtils` CAS insert、start/finish update、delete vote、force repair，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:138-171`、`src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:821-1074` | 无 TTL；delete_hosts 超时清空，过半 vote 删除 orphan host record，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:840-864` |
| `auto_repair_priority` | `repair_type` | `repair_priority set<uuid>` | `addPriorityHosts()` 添加，priority turn 完成后 `removePriorityStatus()` 删除 host，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:1076-1129`、`src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:480-488` | 无 TTL；非 ring host 在 turn election 中移除，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:923-939` |

## 生命周期

Startup：

```text
StorageService join/startup
  -> setUpDistributedSystemKeyspaces()
     -> update TraceKeyspace/SystemDistributedKeyspace/AuthKeyspace
  -> finishJoiningRing(...)
  -> StorageProxy.initialLoadPartitionDenylist()
  -> setupAutoRepair()
     -> AutoRepairService.setup()
     -> AutoRepair.setup()
        -> AutoRepairUtils.setup()
```

源码锚点见 `src/java/org/apache/cassandra/service/StorageService.java:1318-1350`、`src/java/org/apache/cassandra/service/StorageService.java:1464-1498`、`src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:113-150`。

Repair history：

```text
RepairCoordinator
  -> startParentRepair()
RepairSession
  -> startRepairs()
RepairJob callback
  -> successfulRepairJob() or failedRepairJob()
RepairCoordinator finish
  -> successfulParentRepair() or failParentRepair()
```

MV status：

```text
ViewBuilder.start()
  -> system_distributed.view_build_status = STARTED
ViewBuilder.finish()
  -> system.view_builds_in_progress removed
  -> system_distributed.view_build_status = SUCCESS
  -> system.built_views status_replicated = true
ViewManager remove
  -> delete system + system_distributed build status
```

Partition denylist:

```text
operator CQL/JMX mutation
  -> system_distributed.partition_denylist row insert/delete
  -> refresh per-table cache
read/write/range read hot path
  -> StorageProxy checks PartitionDenylist cache
  -> reject and mark DenylistMetrics when denied
```

Auto-repair:

```text
scheduled repair(repairType)
  -> myTurnToRunRepair()
     -> insert missing ring host history
     -> clear stale delete_hosts / delete orphan host / trim priority
  -> updateStartAutoRepairHistory()
  -> repair keyspaces/tables
  -> updateFinishAutoRepairHistory()
  -> remove priority host if used
```

## 调用链

- Distributed system keyspace setup：`StorageService.setUpDistributedSystemKeyspaces()` calls `SchemaTransformations.updateSystemKeyspace(SystemDistributedKeyspace.metadata(), GENERATION)`，见 `src/java/org/apache/cassandra/service/StorageService.java:1492-1498`。
- Repair history write：`RepairCoordinator.maybeStoreParentRepair*()`、`RepairSession.start()`、`RepairJob` callback 分别调用 parent/session/job writer，见 `src/java/org/apache/cassandra/repair/RepairCoordinator.java:421-442`、`src/java/org/apache/cassandra/repair/RepairSession.java:297-331`、`src/java/org/apache/cassandra/repair/RepairJob.java:204-229`。
- MV operator read：`ViewBuildStatus` nodetool -> `NodeProbe.getViewBuildStatuses()` -> `StorageService.getViewBuildStatuses()` -> `SystemDistributedKeyspace.viewStatus()`，读路径核心见 `src/java/org/apache/cassandra/service/StorageService.java:6246-6270`、`src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:401-424`。
- Denylist enforcement：CAS、regular mutations、single partition read 和 range read 都在 `StorageProxy` 前置检查，见 `src/java/org/apache/cassandra/service/StorageProxy.java:319-324`、`src/java/org/apache/cassandra/service/StorageProxy.java:1122-1138`、`src/java/org/apache/cassandra/service/StorageProxy.java:1870-1881`、`src/java/org/apache/cassandra/service/StorageProxy.java:2281-2293`。
- Auto-repair turn：`AutoRepair.repair()` 调 `AutoRepairUtils.myTurnToRunRepair()`，若获得 turn 则写 start，cleanup 写 finish，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:204-220`、`src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:480-519`。

## 配置项

| 配置项 | 作用 | 源码 |
|---|---|---|
| `cassandra.system_distributed.default_rf` | `system_distributed` RF 下限，默认 3 | `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:540`、`src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:213-228` |
| `cassandra.autorepair.enable` | JVM property，决定 auto-repair schema/MBean/setup 是否可用 | `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:62`、`src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:84-117`、`src/java/org/apache/cassandra/service/AutoRepairService.java:62-78` |
| `partition_denylist_enabled` | 全局开启 partition denylist，默认 false | `src/java/org/apache/cassandra/config/Config.java:756-760`、`conf/cassandra.yaml:1436-1438` |
| `denylist_writes_enabled` / `denylist_reads_enabled` / `denylist_range_reads_enabled` | 分别控制写、单 partition read、range read 拒绝 | `src/java/org/apache/cassandra/config/Config.java:761-765`、`conf/cassandra.yaml:1440-1442` |
| `denylist_refresh` / `denylist_initial_load_retry` | cache refresh 与初始加载失败重试 | `src/java/org/apache/cassandra/config/Config.java:767-769`、`conf/cassandra.yaml:1444-1452` |
| `denylist_max_keys_per_table` / `denylist_max_keys_total` | denylist cache 加载上限，溢出会允许超出部分通过 | `src/java/org/apache/cassandra/config/Config.java:771-780`、`conf/cassandra.yaml:1454-1462` |
| `denylist_consistency_level` | denylist 表读写和 cache load 使用的 CL，默认 QUORUM | `src/java/org/apache/cassandra/config/Config.java:782-786`、`conf/cassandra.yaml:1464-1467` |

## Metrics

- `DenylistMetrics` 暴露 `StorageProxy.PartitionDenylist.WriteRejected`、`ReadRejected`、`RangeReadRejected`、`TotalRejected` meters，见 `src/java/org/apache/cassandra/metrics/DenylistMetrics.java:25-58`。
- Auto-repair turn、delay、success/failure 和 scheduler stats 主要走 `AutoRepairMetrics` / state metrics；turn 记录入口见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepair.java:204-220` 和 `src/java/org/apache/cassandra/metrics/AutoRepairMetrics.java:191-226`。
- `system_distributed` 普通表仍有 table metrics；`tablestats system_distributed` 和 table histograms 测试覆盖 table count，见 `test/unit/org/apache/cassandra/tools/nodetool/TableStatsTest.java:148-150`、`test/unit/org/apache/cassandra/tools/nodetool/TableHistogramsTest.java:24-46`。
- Repair history 表本身没有专属 metric，repair 成功/失败指标主要归 repair job/table metrics；history row 用于审计和排障。

## 日志

- `SystemDistributedKeyspace.processSilent()` 写失败会记录 `"Error executing query"`，但不向 repair 调用方抛出，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:433-447`。
- `PartitionDenylist.initialLoad()` 在节点不足或异常时记录原因并调度重试，见 `src/java/org/apache/cassandra/schema/PartitionDenylist.java:128-165`。
- `PartitionDenylist` 在 per-table/global 上限溢出时 error，并说明超出 key 被忽略或需要清理 `system_distributed.partition_denylist`，见 `src/java/org/apache/cassandra/schema/PartitionDenylist.java:419-431`、`src/java/org/apache/cassandra/schema/PartitionDenylist.java:484-491`。
- `AutoRepairUtils.myTurnToRunRepair()` 会记录 ring host 数、delete vote、priority host、next host、异常等 turn-election 状态，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:821-989`。
- `ViewBuilder.updateDistributed()` 写 distributed MV status 失败时 5 分钟后重试，并记录 warn，见 `src/java/org/apache/cassandra/db/view/ViewBuilder.java:213-224`。

## 运维关注点

- `system_distributed` RF 低于生产拓扑需求时，repair history、MV build status、denylist 和 auto-repair 状态都可能不可用；多 DC 集群应按 replicated system keyspace 单独规划 RF。
- Repair history 表有 30 天 TTL；超过保留期后只能依赖外部日志、metrics 或 repair service 状态追溯。
- `partition_denylist` 不是自动清理表；超出 per-table/global limit 的 key 会写入表但不会全部进入 cache，导致 operator 以为已 denylist 但请求仍可通过。
- denylist 禁止对 `system`、`system_distributed`、`system_traces`、`system_virtual_schema`、`system_views`、`system_auth` 这些关键 keyspace 生效，见 `src/java/org/apache/cassandra/schema/PartitionDenylist.java:288-300`。
- Auto-repair feature flag 启用/禁用是 schema 级边界；测试说明启用后再以 disabled 启动并不支持，见 `test/distributed/org/apache/cassandra/distributed/test/repair/AutoRepairFlagToggleTest.java:192-210`。
- MV build status 读出的 `UNKNOWN` 不一定代表失败，也可能是该 host 没有 row；需要结合 `system.view_builds_in_progress` 和 view build 日志判断。

## 性能瓶颈

- Repair history 每个 common range/table 都会写行；大范围、多表 repair 会放大 `system_distributed.repair_history` 写入量，虽然 TTL/TWCS 会最终清理。
- Partition denylist range read 检查使用 cached token set 的 range subset；denylisted key 数量越大，cache 内存和 range count 成本越高，加载逻辑见 `src/java/org/apache/cassandra/schema/PartitionDenylist.java:343-383`、`src/java/org/apache/cassandra/schema/PartitionDenylist.java:385-513`。
- Denylist cache full reload 会查询 distinct table list，再按表查询 key；表数和 key 数越多，reload 越重，见 `src/java/org/apache/cassandra/schema/PartitionDenylist.java:463-513`。
- Auto-repair turn election 读取所有 history 和 priority，且会在 ring membership 变化时执行 insert/delete/vote；大集群或频繁拓扑变化会增加 scheduler 元数据负载，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:821-989`。
- `view_build_status` 每个 view/host 一行，MV 数量多时 nodetool viewbuildstatus 要合并更多 host id rows。

## 常见故障

- repair history 缺行：preview repair 不写，写入走 `processSilent()`，失败只记日志；先查 repair logs 再查 TTL 是否已过期。
- `viewbuildstatus` 长期 `UNKNOWN`：可能该 host 未写 `view_build_status`，或 distributed status 写失败后仍在 5 分钟重试，见 `src/java/org/apache/cassandra/db/view/ViewBuilder.java:213-224`。
- denylist 写入后仍可访问：检查 `partition_denylist_enabled`、读写/range 开关、cache 是否 reload、key 是否超过 per-table/global limit、目标 keyspace 是否在禁止 denylist 集合中。
- denylist 初始加载失败：`PartitionDenylist.initialLoad()` 会按 `denylist_initial_load_retry` 重试；CL 节点不足会 warn，见 `src/java/org/apache/cassandra/schema/PartitionDenylist.java:142-176`。
- Auto-repair 一直不是本节点 turn：检查 `auto_repair_priority`、`force_repair`、ongoing repair rows、stale `delete_hosts` 和 host 是否仍在 ring，核心逻辑见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:821-989`。
- auto-repair priority host 不执行：priority 中 host 不在当前 ring 会被移除；非 priority host 会等待第一个 priority host，见 `src/java/org/apache/cassandra/repair/autorepair/AutoRepairUtils.java:923-952`。

## 测试用例

- `SystemKeyspaceTablesNamesTest` 校验 `SystemDistributedKeyspace.getTableNames()` 和 schema metadata 一致，见 `test/unit/org/apache/cassandra/cql3/SystemKeyspaceTablesNamesTest.java:84-88`。
- `python3 research/tools/check-system-table-column-drift.py` 校验 `system_distributed` 六张表的源码 CQL 列契约、primary key 和文档 section 一致。
- `IncRepairCoordinatorErrorTest` 通过 distributed repair 查询 `system_distributed.repair_history` parent id，并注入 finalize commit 消息失败，见 `test/distributed/org/apache/cassandra/distributed/test/IncRepairCoordinatorErrorTest.java:45-54`。
- `PartitionDenylistTest` 覆盖 JMX add/remove/load、read/write/range deny、cache mutation、per-table/global limit 和 truncate/reset，见 `test/unit/org/apache/cassandra/service/PartitionDenylistTest.java:112-180`、`test/unit/org/apache/cassandra/service/PartitionDenylistTest.java:360-475`。
- `AutoRepairUtilsTest` 覆盖 auto-repair history delete/start/finish、delete_hosts、priority add/remove/get，见 `test/unit/org/apache/cassandra/repair/autorepair/AutoRepairUtilsTest.java:397-520`。
- `AutoRepairKeyspaceTest` 覆盖 `AUTOREPAIR_ENABLE=true` 时 auto-repair tables 出现在 metadata，见 `test/unit/org/apache/cassandra/repair/autorepair/AutoRepairKeyspaceTest.java:48-70`。
- `AutoRepairFlagToggleTest` 覆盖 flag disabled 时 system_distributed auto-repair 表不存在，以及启用/禁用边界，见 `test/distributed/org/apache/cassandra/distributed/test/repair/AutoRepairFlagToggleTest.java:150-176`、`test/distributed/org/apache/cassandra/distributed/test/repair/AutoRepairFlagToggleTest.java:192-210`。
