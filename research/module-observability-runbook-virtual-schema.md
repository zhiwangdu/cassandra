# Module: Observability Runbook And Virtual Schema

## 范围

本模块覆盖运维观测第四轮的两个本地源码目标：`nodetool` 逐命令 runbook 分组，以及 `system_virtual_schema.columns` 的字段生成规则。当前 checkout 没有 Prometheus exporter、Grafana dashboard 或 alert rule 文件，因此本轮不写外部 dashboard 对照，只把 Cassandra 进程内已经暴露的命令面和 virtual schema 元数据固化下来。

`NodeTool.execute()` registry / `@Command` annotation 到本 runbook 的覆盖 drift checker 见 `research/module-nodetool-drift-checker.md` 和 `research/tools/check-nodetool-runbook-drift.py`。逐命令 `@Option` / `@Arguments` 风险矩阵与 drift checker 见 `research/module-nodetool-option-risk-matrix.md`、`research/module-nodetool-option-drift-checker.md` 和 `research/tools/check-nodetool-option-risk-drift.py`。

边界：

- `NodeTool.execute()` 注册 147 个顶层命令类，并把 `bootstrap`、`repair_admin` 作为 Airline command group 追加到同一个 CLI parser，见 `src/java/org/apache/cassandra/tools/NodeTool.java:98-267`。
- 普通 `NodeToolCmd` 在执行前统一解析 `--host`、`--port`、`--username`、`--password`、`--password-file`、`--print-port`，然后创建 `NodeProbe` 并调用命令自己的 `execute(NodeProbe)`，见 `src/java/org/apache/cassandra/tools/NodeTool.java:348-455`。
- `NodeProbe.connect()` 是 nodetool 生产连接模型的 MBean 代理清单，包含 StorageService、MessagingService、StreamManager、CompactionManager、FailureDetector、CacheService、StorageProxy、HintsService、Batchlog、Repair、Audit、Auth/CIDR/Guardrails/AutoRepair 等入口，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:262-321`。
- `system_virtual_schema` 固定注册 `keyspaces`、`tables`、`columns` 三张 virtual table，见 `src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java:37-40`。
- `system_virtual_schema.columns` 的行不是手写清单，而是遍历 `VirtualKeyspaceRegistry.instance.virtualKeyspacesMetadata()`、每个 virtual table 和每个 `ColumnMetadata` 生成，见 `src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java:128-149`。

## 设计目标

- 把 nodetool 命令按生产风险和目标子系统分组，作为排障、巡检、变更和限速的入口索引。
- 明确哪些命令只是读取状态，哪些会改 runtime config，哪些会触发 streaming、compaction、schema/cache/logging 或进程生命周期动作。
- 给 `system_virtual_schema.columns` 建立源码级解释：它反映当前注册的 virtual keyspace metadata，而不是独立维护的文档表。
- 将 `system_views` 的静态注册表、动态 metric 表、CIDR metrics 和 SAI virtual tables 对接到 `system_virtual_schema.columns`，便于后续自动化生成列清单。

## 解决的问题

- 仅说“nodetool 走 JMX”不够：同一个 `NodeProbe` facade 背后可能是 service MBean、metrics ObjectName、virtual table MBean 或本地 JVM MXBean，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:262-321`。
- 命令名和 Java 类名并非总是一一映射：例如 `ReloadSslCertificates` 的 CLI 名称是 `reloadssl`，`UpgradeSSTable` 的 CLI 名称是 `upgradesstables`，CIDR list 命令类在 `src/java/org/apache/cassandra/tools/ListCIDRGroups.java:32-33`，SSL reload 命令在 `src/java/org/apache/cassandra/tools/ReloadSslCertificates.java:24-25`。
- `system_virtual_schema.columns` 是 virtual table metadata 的实时投影；新增或删除 `system_views` provider 会改变它的输出，不需要改 `VirtualSchemaKeyspace` 的生成循环，见 `src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java:132-143`。
- `system_views` 同时包含低成本固定指标表和高成本枚举表；runbook 必须把高频 scrape、人工排障和破坏性变更分开。

## 设计取舍

- nodetool 把命令注册集中在 `NodeTool.execute()`，利于帮助信息和 parser 构建，但命令行为仍分散在各 `tools/nodetool` 类；runbook 因此以 registry 为完整性边界，以命令实现和 `NodeProbe` 为风险边界，见 `src/java/org/apache/cassandra/tools/NodeTool.java:98-252`。
- `NodeToolCmd.runInternal()` 每次命令创建并关闭 `NodeProbe`，避免命令之间复用 JMX state；代价是批量脚本多次执行 nodetool 会反复连接 JMX，见 `src/java/org/apache/cassandra/tools/NodeTool.java:380-399`。
- `system_virtual_schema.columns` 输出 `column_name_bytes`、`kind`、`position`、`type` 等 `ColumnMetadata` 视角字段，适合自动化检查；它不负责解释 provider 的运行时读成本，见 `src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java:100-149`。
- `system_views` 把 table metrics、CIDR metrics、SAI metadata 等放入 CQL virtual table，便于 SQL 巡检；完整 exporter 仍应以 JMX metrics wrapper attribute 和 MBean ObjectName 为准，见 `src/java/org/apache/cassandra/db/virtual/SystemViewsKeyspace.java:32-58`、`src/java/org/apache/cassandra/db/virtual/TableMetricTables.java:233-265`。

## 核心类

| 类 | 作用 |
|---|---|
| `NodeTool` | nodetool CLI parser、顶层命令 registry、command group 和全局 JMX 参数入口。见 `src/java/org/apache/cassandra/tools/NodeTool.java:98-267`、`src/java/org/apache/cassandra/tools/NodeTool.java:348-455` |
| `NodeTool.NodeToolCmd` | 普通命令基类，负责读取密码、连接 `NodeProbe`、执行命令并检查失败状态。见 `src/java/org/apache/cassandra/tools/NodeTool.java:348-455` |
| `NodeProbe` | nodetool 的 JMX facade，缓存 service MBean proxy 并提供命令调用方法。见 `src/java/org/apache/cassandra/tools/NodeProbe.java:262-321` |
| `BootstrapResume` | `bootstrap resume` command group 下的 resume 子命令。见 `src/java/org/apache/cassandra/tools/nodetool/BootstrapResume.java:31`、`src/java/org/apache/cassandra/tools/NodeTool.java:254-258` |
| `RepairAdmin` | `repair_admin` command group 下的 list/cancel/cleanup/summarize 子命令。见 `src/java/org/apache/cassandra/tools/nodetool/RepairAdmin.java:48-273`、`src/java/org/apache/cassandra/tools/NodeTool.java:260-267` |
| `VirtualSchemaKeyspace` | `system_virtual_schema.keyspaces/tables/columns` 的 provider。见 `src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java:33-149` |
| `SystemViewsKeyspace` | `system_views` provider registry。见 `src/java/org/apache/cassandra/db/virtual/SystemViewsKeyspace.java:32-58` |
| `TableMetricTables` | 按 table metric 类型动态生成 table metric virtual tables 和列。见 `src/java/org/apache/cassandra/db/virtual/TableMetricTables.java:233-265` |
| `GossipInfoTable` | 按 `ApplicationState` 动态生成 gossip value/version 列。见 `src/java/org/apache/cassandra/db/virtual/GossipInfoTable.java:168-186` |
| `StorageAttachedIndexTables` | 注册 SAI column index、SSTable index、segment 三类 virtual table。见 `src/java/org/apache/cassandra/index/sai/virtual/StorageAttachedIndexTables.java:31-35` |

## 核心接口

- `NodeToolCmdRunnable.run(INodeProbeFactory, Output)`：Airline parser 执行后的统一入口；`CassHelp` 也实现这个接口，因此 help/default command 不需要 JMX，见 `src/java/org/apache/cassandra/tools/NodeTool.java:335-342`。
- `NodeToolCmd.execute(NodeProbe)`：普通命令只实现业务逻辑，连接和关闭由基类处理，见 `src/java/org/apache/cassandra/tools/NodeTool.java:390-442`。
- `INodeProbeFactory.create(host, port[, username, password])`：把 CLI 全局参数转换成生产 JMX 连接或测试里的 probe mock，见 `src/java/org/apache/cassandra/tools/NodeTool.java:444-455`。
- `VirtualTable.data()`：`system_virtual_schema.keyspaces/tables/columns` 都通过 `SimpleDataSet` 返回当前 registry metadata，见 `src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java:56-61`、`src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java:83-97`、`src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java:128-149`。
- `TableMetadata.Builder.addPartitionKeyColumn/addClusteringColumn/addRegularColumn`：virtual schema 和 system views 的列定义最终都进入 `TableMetadata`，再由 `ColumnMetadata` 投影到 `system_virtual_schema.columns`，见 `src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java:113-125`。

## 核心数据结构

### nodetool 命令 runbook 分组

`NodeTool` 顶层 registry 覆盖 `AutoRepairStatus` 到 `ForceCompact` 的 147 个命令类，见 `src/java/org/apache/cassandra/tools/NodeTool.java:98-245`。下表按运维动作分组；命令名使用 CLI 名称，括号内是高风险或特殊入口。

| 分组 | 命令 | 主要目标与风险 |
|---|---|---|
| 帮助、版本、JVM 工具 | `help`、`version`、`sjk` | `help` 走 `CassHelp` 不需要 JMX；`version` 读取节点版本；`sjk` 运行 Swiss Java Knife，适合现场 JVM 诊断但要控制执行权限。`CassHelp` 位于 `src/java/org/apache/cassandra/tools/NodeTool.java:335-342`，`Sjk` 注册于 `src/java/org/apache/cassandra/tools/NodeTool.java:224`。 |
| Ring 与拓扑状态 | `status`、`ring`、`info`、`describecluster`、`describering`、`gossipinfo`、`failuredetector`、`checktokenmetadata`、`getendpoints`、`getseeds`、`reloadseeds` | 主要读取 StorageService/Gossiper/FailureDetector 状态；`reloadseeds` 会更新 seed provider 结果。命令注册见 `src/java/org/apache/cassandra/tools/NodeTool.java:103-164`、`src/java/org/apache/cassandra/tools/NodeTool.java:201-231`。 |
| Ring 与节点生命周期变更 | `join`、`move`、`decommission`、`removenode`、`assassinate`、`rebuild`、`drain`、`stopdaemon`、`bootstrap resume` | 变更 token ownership、触发 streaming、停止写入或停止 daemon；`assassinate` 是最后手段，`bootstrap resume` 在 `bootstrap` group 下。注册见 `src/java/org/apache/cassandra/tools/NodeTool.java:111-123`、`src/java/org/apache/cassandra/tools/NodeTool.java:175-200`、`src/java/org/apache/cassandra/tools/NodeTool.java:254-258`。 |
| SSTable 与本地数据维护 | `flush`、`cleanup`、`compact`、`forcecompact`、`garbagecollect`、`scrub`、`verify`、`upgradesstables`、`refresh`、`import`、`relocatesstables`、`recompress_sstables`、`rebuild_index`、`sstablerepairedset`、`getsstables`、`datapaths`、`refreshsizeestimates`、`rangekeysample` | 多数会触发磁盘 IO、compaction 或 SSTable metadata 变更；`scrub`/`verify`/`sstablerepairedset` 需要窗口期和备份策略。注册见 `src/java/org/apache/cassandra/tools/NodeTool.java:104-110`、`src/java/org/apache/cassandra/tools/NodeTool.java:135-136`、`src/java/org/apache/cassandra/tools/NodeTool.java:156-188`、`src/java/org/apache/cassandra/tools/NodeTool.java:202-245`。 |
| Repair 与 incremental repair admin | `repair`、`repair_admin list`、`repair_admin cancel`、`repair_admin cleanup`、`repair_admin summarize-pending`、`repair_admin summarize-repaired` | `repair` 触发反熵 repair；`repair_admin` 管理 incremental repair sessions 和 pending/repaired 数据摘要。group 注册见 `src/java/org/apache/cassandra/tools/NodeTool.java:260-267`，子命令见 `src/java/org/apache/cassandra/tools/nodetool/RepairAdmin.java:48-273`。 |
| Compaction 与执行并发 | `compactionstats`、`compactionhistory`、`stop`、`disableautocompaction`、`enableautocompaction`、`statusautocompaction`、`getcompactionthreshold`、`setcompactionthreshold`、`getcompactionthroughput`、`setcompactionthroughput`、`getconcurrentcompactors`、`setconcurrentcompactors`、`getconcurrentviewbuilders`、`setconcurrentviewbuilders`、`getconcurrency`、`setconcurrency`、`getcolumnindexsize`、`setcolumnindexsize`、`viewbuildstatus` | 读状态类命令可巡检；set/disable/stop 类命令会改变吞吐、并发或 compaction 生命周期。注册见 `src/java/org/apache/cassandra/tools/NodeTool.java:108-109`、`src/java/org/apache/cassandra/tools/NodeTool.java:115-126`、`src/java/org/apache/cassandra/tools/NodeTool.java:143-148`、`src/java/org/apache/cassandra/tools/NodeTool.java:208-244`。 |
| Client、网络、streaming 与 protocol | `clientstats`、`netstats`、`disablebinary`、`enablebinary`、`statusbinary`、`disableoldprotocolversions`、`enableoldprotocolversions`、`gettimeout`、`settimeout`、`getstreamthroughput`、`setstreamthroughput`、`getinterdcstreamthroughput`、`setinterdcstreamthroughput` | client/network 读取适合排障；binary/protocol/timeout/throughput set 类命令会影响客户端连接和 streaming 限速。注册见 `src/java/org/apache/cassandra/tools/NodeTool.java:106-122`、`src/java/org/apache/cassandra/tools/NodeTool.java:153-160`、`src/java/org/apache/cassandra/tools/NodeTool.java:180-223`。 |
| Gossip 与可用性控制 | `disablegossip`、`enablegossip`、`statusgossip` | `disablegossip` 会让节点对集群表现为 down，应只在明确的维护场景使用。注册见 `src/java/org/apache/cassandra/tools/NodeTool.java:119-130`、`src/java/org/apache/cassandra/tools/NodeTool.java:231`。 |
| Hints 与 batchlog | `enablehandoff`、`disablehandoff`、`statushandoff`、`pausehandoff`、`resumehandoff`、`listpendinghints`、`truncatehints`、`enablehintsfordc`、`disablehintsfordc`、`getmaxhintwindow`、`setmaxhintwindow`、`sethintedhandoffthrottlekb`、`replaybatchlog`、`getbatchlogreplaythrottle`、`setbatchlogreplaythrottle` | 读取 pending hints 可巡检；truncate、pause/disable、replay 和 throttle 变更会影响最终一致性恢复和写入重放。注册见 `src/java/org/apache/cassandra/tools/NodeTool.java:120-132`、`src/java/org/apache/cassandra/tools/NodeTool.java:141-155`、`src/java/org/apache/cassandra/tools/NodeTool.java:177-205`、`src/java/org/apache/cassandra/tools/NodeTool.java:216-239`。 |
| Cache、auth cache 与 CIDR | `invalidatekeycache`、`invalidaterowcache`、`invalidatecountercache`、`setcachecapacity`、`setcachekeystosave`、`invalidatecredentialscache`、`invalidatejmxpermissionscache`、`invalidatenetworkpermissionscache`、`invalidatepermissionscache`、`invalidaterolescache`、`getauthcacheconfig`、`setauthcacheconfig`、`listcidrgroups`、`updatecidrgroup`、`dropcidrgroup`、`getcidrgroupsofip`、`reloadcidrgroupscache`、`invalidatecidrpermissionscache`、`cidrfilteringstats` | cache invalidation 会降低后续命中率但可修复 stale auth/cache 状态；CIDR group update/drop 是安全策略变更。`listcidrgroups` 在 tools 包下定义，见 `src/java/org/apache/cassandra/tools/ListCIDRGroups.java:32-33`；其余注册见 `src/java/org/apache/cassandra/tools/NodeTool.java:102-176`、`src/java/org/apache/cassandra/tools/NodeTool.java:203-240`。 |
| Audit、FQL、logging 与 tracing | `enableauditlog`、`disableauditlog`、`getauditlog`、`enablefullquerylog`、`disablefullquerylog`、`getfullquerylog`、`resetfullquerylog`、`getlogginglevels`、`setlogginglevel`、`gettraceprobability`、`settraceprobability` | audit/FQL 影响磁盘和敏感数据留存；动态 log level 和 trace probability 适合短时排障，必须回收。注册见 `src/java/org/apache/cassandra/tools/NodeTool.java:114-129`、`src/java/org/apache/cassandra/tools/NodeTool.java:138-161`、`src/java/org/apache/cassandra/tools/NodeTool.java:198-223`。 |
| Snapshot 与 incremental backup | `snapshot`、`clearsnapshot`、`listsnapshots`、`enablebackup`、`disablebackup`、`statusbackup`、`getsnapshotthrottle`、`setsnapshotthrottle` | snapshot/clear 会触达文件系统并影响磁盘占用；backup 开关影响新增 SSTable hardlink 行为。注册见 `src/java/org/apache/cassandra/tools/NodeTool.java:105-127`、`src/java/org/apache/cassandra/tools/NodeTool.java:158-178`、`src/java/org/apache/cassandra/tools/NodeTool.java:220-229`。 |
| Schema、guardrails、SSL 与默认 RF | `reloadlocalschema`、`resetlocalschema`、`reloadtriggers`、`reloadssl`、`getguardrailsconfig`、`setguardrailsconfig`、`getdefaultrf`、`setdefaultrf` | schema reset/reload 和 trigger reload 是控制面动作；`reloadssl` 重新加载证书；guardrails/default RF set 类命令影响运行时策略。`reloadssl` 定义见 `src/java/org/apache/cassandra/tools/ReloadSslCertificates.java:24-25`，guardrails 命令见 `src/java/org/apache/cassandra/tools/nodetool/GuardrailsConfigCommand.java:56-173`。 |
| 指标、直方图与现场 profiling | `tablestats`、`tablehistograms`、`proxyhistograms`、`tpstats`、`gcstats`、`toppartitions`、`profileload`、`autorepairstatus`、`getautorepairconfig`、`setautorepairconfig` | 读取类命令适合巡检；`toppartitions` 会采样活动 partition，`profileload` 会进行短时低开销 profiling，`setautorepairconfig` 会改自动 repair runtime config。注册见 `src/java/org/apache/cassandra/tools/NodeTool.java:99-140`、`src/java/org/apache/cassandra/tools/NodeTool.java:182-238`。 |

### system_virtual_schema 列生成

| 表 | 固定列 | 生成规则 |
|---|---|---|
| `system_virtual_schema.keyspaces` | partition key: `keyspace_name` | 遍历 `VirtualKeyspaceRegistry.instance.virtualKeyspacesMetadata()` 并输出 keyspace name，见 `src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java:42-62`。 |
| `system_virtual_schema.tables` | partition key: `keyspace_name`; clustering: `table_name`; regular: `comment` | 遍历每个 virtual keyspace 的 `keyspace.tables`，输出 table keyspace/name 和 table comment，见 `src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java:65-97`。 |
| `system_virtual_schema.columns` | partition key: `keyspace_name`; clustering: `table_name`, `column_name`; regular: `clustering_order`, `column_name_bytes`, `kind`, `position`, `type` | 遍历每个 virtual table 的 `table.columns()`，从 `ColumnMetadata` 输出 clustering order、bytes、kind、position 和 CQL type，见 `src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java:100-149`。 |

### system_views provider 到列清单的锚点

| provider | 列清单来源 |
|---|---|
| 固定 `system_views` 表 | `SystemViewsKeyspace` 直接注册 caches、clients、settings、system_properties、sstable_tasks、thread_pools、internode、pending_hints、auth cache keys、CQL/batch metrics、streaming、gossip、queries、logs、snapshots、repair、CIDR、SAI provider，见 `src/java/org/apache/cassandra/db/virtual/SystemViewsKeyspace.java:32-58`。 |
| 表级 metric tables | `TableMetricTables.buildMetadata()` 先固定 `keyspace_name`、`table_name`，再按 Dropwizard metric 类型添加 count/value、p50/p99/max、rate 等列，见 `src/java/org/apache/cassandra/db/virtual/TableMetricTables.java:233-265`。 |
| Gossip info | 固定 `address`、`port`、`hostname`、`generation`、`heartbeat`，再按 `ApplicationState` 添加 value/version 列，见 `src/java/org/apache/cassandra/db/virtual/GossipInfoTable.java:168-186`。 |
| CIDR metrics | count 表为 `name` + `value`；latency 表为 `name` + p50/p95/p99/p999/max，见 `src/java/org/apache/cassandra/db/virtual/CIDRFilteringMetricsTable.java:90-98`、`src/java/org/apache/cassandra/db/virtual/CIDRFilteringMetricsTable.java:153-163`。 |
| SAI virtual tables | `StorageAttachedIndexTables.getAll()` 注册 column indexes、segments、sstable indexes；三张表的列分别由对应 provider 的 builder 定义，见 `src/java/org/apache/cassandra/index/sai/virtual/StorageAttachedIndexTables.java:31-35`、`src/java/org/apache/cassandra/index/sai/virtual/ColumnIndexesSystemView.java:54-66`、`src/java/org/apache/cassandra/index/sai/virtual/SSTableIndexesSystemView.java:61-78`、`src/java/org/apache/cassandra/index/sai/virtual/SegmentsSystemView.java:61-80`。 |

## 生命周期

nodetool：

```text
NodeTool.main()
  -> NodeTool.execute(args)
  -> register top-level commands
  -> register bootstrap and repair_admin groups
  -> Airline parses command
  -> NodeToolCmd.runInternal()
  -> NodeProbeFactory.create(...)
  -> NodeProbe.connect()
  -> command.execute(probe)
```

Virtual schema：

```text
CassandraDaemon registers virtual keyspaces
  -> VirtualKeyspaceRegistry contains system_views and system_virtual_schema
  -> CQL SELECT system_virtual_schema.columns
  -> VirtualSchemaKeyspace.VirtualColumns.data()
  -> for each virtual keyspace/table/ColumnMetadata
  -> SimpleDataSet row(keyspace, table, column)
```

## 调用链

- parser 构建：`NodeTool.execute()` 先把 147 个顶层命令类传入 `builder.withCommands(commands)`，再用 `withGroup("bootstrap")` 和 `withGroup("repair_admin")` 添加 group，见 `src/java/org/apache/cassandra/tools/NodeTool.java:248-267`。
- 命令执行：Airline parse 后调用 `parse.run(nodeProbeFactory, output)`；普通命令进入 `NodeToolCmd.runInternal()`，help 命令直接运行 Airline Help，见 `src/java/org/apache/cassandra/tools/NodeTool.java:269-276`、`src/java/org/apache/cassandra/tools/NodeTool.java:335-342`。
- JMX 连接：`NodeProbe` 构造 JMX URL、设置 credentials 和 RMI socket factory，然后创建 service MBean proxy，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:250-321`。
- virtual schema keyspaces：`VirtualKeyspaces.data()` 输出每个 virtual keyspace；`VirtualTables.data()` 输出每个 virtual table；`VirtualColumns.data()` 输出每个 virtual column，见 `src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java:56-149`。
- dynamic columns：table metric tables、gossip info、CIDR metrics、SAI system views 都先构造 `TableMetadata`，再被 `system_virtual_schema.columns` 统一投影，见 `src/java/org/apache/cassandra/db/virtual/TableMetricTables.java:233-265`、`src/java/org/apache/cassandra/db/virtual/GossipInfoTable.java:168-186`、`src/java/org/apache/cassandra/db/virtual/CIDRFilteringMetricsTable.java:90-163`、`src/java/org/apache/cassandra/index/sai/virtual/StorageAttachedIndexTables.java:31-35`。

## 配置项

| 配置 / 参数 | 影响 |
|---|---|
| nodetool `--host` / `--port` | JMX 目标地址和端口，默认 `127.0.0.1:7199`，见 `src/java/org/apache/cassandra/tools/NodeTool.java:351-355`。 |
| nodetool `--username` / `--password` / `--password-file` | 远程 JMX 认证；指定 username 且无 password 时会从 password file 或 console 读取，见 `src/java/org/apache/cassandra/tools/NodeTool.java:357-388`。 |
| nodetool `--print-port` | 4.0 模式下按 host+port 区分节点，影响输出展示和部分命令的 endpoint 格式，见 `src/java/org/apache/cassandra/tools/NodeTool.java:366-367`。 |
| JMX SSL/RMI properties | `NodeProbe` 构造 JMX URL 和 RMI socket factory，JMX SSL 配置会影响 nodetool/JMXTool 能否连接，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:250-264`。 |
| `system_views` provider registration | 任何新增 provider 只要注册到 `VirtualKeyspaceRegistry`，都会被 `system_virtual_schema` 枚举；`SystemViewsKeyspace` 当前注册清单见 `src/java/org/apache/cassandra/db/virtual/SystemViewsKeyspace.java:32-58`。 |

## Metrics

- nodetool 指标命令分为三类：直接读 service MBean 状态、动态 query metrics ObjectName、读取 virtual table backed MBean。`NodeProbe.connect()` 固定 proxy 清单见 `src/java/org/apache/cassandra/tools/NodeProbe.java:262-321`。
- `tablestats`、`tablehistograms`、`proxyhistograms`、`tpstats`、`gcstats` 是人读巡检入口；完整 exporter 字段仍需要依据 Dropwizard/JMX wrapper attribute。表级 virtual metric tables 只输出经过筛选的 value/percentile/rate 列，见 `src/java/org/apache/cassandra/db/virtual/TableMetricTables.java:233-265`。
- `cidrfilteringstats` 是特殊桥接：CIDR metrics 既有 virtual table，也注册 MBean 供 nodetool 读取；列定义见 `src/java/org/apache/cassandra/db/virtual/CIDRFilteringMetricsTable.java:90-163`。
- `system_virtual_schema.columns` 可作为 metrics virtual table 的 schema smoke test：如果 provider 新增/删除 metric 列，`columns` 输出会随 `TableMetadata` 变化，见 `src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java:132-143`。

## 日志

- nodetool 会把实际命令行写入工具输出目录下的 history file，并隐藏 password 参数；这对审计本机操作有用，但不是服务端 audit log，见 `src/java/org/apache/cassandra/tools/NodeTool.java:300-316`。
- `setlogginglevel` 和 `getlogginglevels` 改的是运行时 logging level；`enableauditlog`/`disableauditlog`/`getauditlog` 控制 audit log；`enablefullquerylog`/`resetfullquerylog` 影响 FQL 文件生命周期，注册入口见 `src/java/org/apache/cassandra/tools/NodeTool.java:114-151`、`src/java/org/apache/cassandra/tools/NodeTool.java:198-218`。
- `system_views.system_logs` 的列和 buffer 行为由 `LogMessagesTable` 定义，本模块只把它作为 `system_virtual_schema.columns` 的 registry 输出对象；provider 注册见 `src/java/org/apache/cassandra/db/virtual/SystemViewsKeyspace.java:52-54`。

## 运维关注点

- 先区分读命令、runtime set 命令和数据迁移动作：`status`/`tablestats`/`tpstats` 可用于巡检，`set*`/`enable*`/`disable*` 需要变更记录，`move`/`decommission`/`removenode`/`rebuild`/`repair` 需要窗口和回滚预案。
- 多个 nodetool 命令连续运行会重复建立 JMX 连接；大规模巡检更适合合并脚本、JMX client 或 CQL virtual table 查询，连接路径见 `src/java/org/apache/cassandra/tools/NodeTool.java:390-455`。
- `assassinate`、`truncatehints`、`resetlocalschema`、`stopdaemon`、`disablegossip`、`disablebinary` 是高风险命令，应该需要人工确认和变更单。
- `system_virtual_schema.columns` 只说明列存在，不说明读取成本；高成本 provider 仍需参考对应 `data()` 实现，例如 table metric tables、SAI views、snapshots、queries 和 gossip info。
- `system_views` 和 nodetool/JMX 都是节点本地观测面；需要全集群结论时必须逐节点采集并处理 token/ring/DC 维度。

## 性能瓶颈

- `NodeToolCmd.runInternal()` 每次连接 JMX 并关闭；在含认证、SSL 或远程网络延迟的环境里，短周期反复执行 nodetool 会把连接成本放大，见 `src/java/org/apache/cassandra/tools/NodeTool.java:380-399`。
- `tablehistograms`、`tablestats`、表级 metric virtual tables 都会随 keyspace/table 数增长；表级 metric metadata 还会根据 metric 类型追加 percentile/rate 列，见 `src/java/org/apache/cassandra/db/virtual/TableMetricTables.java:233-265`。
- `system_virtual_schema.columns` 遍历所有 virtual keyspace、table 和 column；它适合低频 introspection 和 schema drift 检查，不适合秒级 scrape，见 `src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java:128-149`。
- SAI `system_views` 会枚举 index metadata、SSTable index 和 segment；列定义入口见 `src/java/org/apache/cassandra/index/sai/virtual/ColumnIndexesSystemView.java:54-66`、`src/java/org/apache/cassandra/index/sai/virtual/SSTableIndexesSystemView.java:61-78`、`src/java/org/apache/cassandra/index/sai/virtual/SegmentsSystemView.java:61-80`。

## 常见故障

- `nodetool` 报 server not initialized：`NodeTool.err()` 对 `InstanceNotFoundException` 给出该错误，通常是 JMX 可连但 Cassandra MBean 尚未注册，见 `src/java/org/apache/cassandra/tools/NodeTool.java:322-330`。
- 认证失败或密码为空：如果传了 username 但没有 password，nodetool 会尝试 password file 或 console；非交互脚本要显式配置 `--password-file`，见 `src/java/org/apache/cassandra/tools/NodeTool.java:357-388`。
- 命令名找不到：以 `NodeTool.execute()` registry 和 `@Command(name=...)` 为准，不要从类名猜测；`reloadssl`、`upgradesstables`、`rebuild_index`、`recompress_sstables` 都是典型例子，见 `src/java/org/apache/cassandra/tools/NodeTool.java:186-245`。
- `system_virtual_schema.columns` 查不到新表或新列：先确认 provider 是否注册到 `VirtualKeyspaceRegistry` 或 `SystemViewsKeyspace`，再看 `TableMetadata.Builder` 是否添加列；registry 见 `src/java/org/apache/cassandra/db/virtual/SystemViewsKeyspace.java:32-58`。
- virtual schema 列清单和外部 dashboard 不一致：当前仓库没有外部 dashboard 配置作为准绳，应以 `TableMetadata`、JMX wrapper 和 exporter 实际配置三方对齐。

## 测试用例

- `NodeToolCommandTest` 覆盖 nodetool command execution helper 和代表性命令输出，见 `test/unit/org/apache/cassandra/tools/NodeToolCommandTest.java:38-77`。
- `NodeToolTest` 覆盖 in-JVM distributed nodetool 场景，见 `test/distributed/org/apache/cassandra/distributed/test/NodeToolTest.java:55-145`。
- `JMXToolTest`、`JMXCompatibilityTest`、`JMXGetterCheckTest` 覆盖 JMX dump/diff、兼容性和 getter 可读性，见 `test/unit/org/apache/cassandra/tools/JMXToolTest.java:40-51`、`test/unit/org/apache/cassandra/tools/JMXCompatibilityTest.java:99-140`、`test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java:63-94`。
- `VirtualTableTest` 覆盖 virtual table 的 CQL 行为边界，见 `test/unit/org/apache/cassandra/cql3/validation/entities/VirtualTableTest.java:72-220`。
- `CQLMetricsTableTest`、`BatchMetricsTableTest`、`CIDRFilteringMetricsTableTest`、`SSTableTasksTableTest` 覆盖 metrics virtual table 行输出，见 `test/unit/org/apache/cassandra/db/virtual/CQLMetricsTableTest.java:50-85`、`test/unit/org/apache/cassandra/db/virtual/BatchMetricsTableTest.java:51-55`、`test/unit/org/apache/cassandra/db/virtual/CIDRFilteringMetricsTableTest.java:97-180`、`test/unit/org/apache/cassandra/db/virtual/SSTableTasksTableTest.java:59-64`。
- `IndexesSystemViewTest` 覆盖 SAI virtual table 输出，见 `test/unit/org/apache/cassandra/index/sai/virtual/IndexesSystemViewTest.java:53-132`。

## 待继续

- 若仓库后续加入 exporter、Grafana dashboard 或 alert rule 文件，再补外部采集字段、dashboard panel 和 alert expression 的文件级映射。
- 将 `research/tools/check-nodetool-runbook-drift.py` 与 `research/tools/check-nodetool-option-risk-drift.py` 接入 CI 或 pre-commit，并保留 JSON artifact。
- 可以在能启动本地节点时用 CQL 直接导出 `SELECT * FROM system_virtual_schema.columns`，把运行时列清单与本源码推导表比对。
