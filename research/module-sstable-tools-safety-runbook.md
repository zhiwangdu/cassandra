# Module: SSTable Tools Safety Runbook

## 范围

本模块覆盖 `src/java/org/apache/cassandra/tools` 下直接读取、校验、导出或重写 SSTable 文件的 standalone 工具安全边界。重点是每个工具的运行前提、是否会修改磁盘、是否需要 Cassandra 停止、是否自动 snapshot、以及哪些选项会把只读检查升级为元数据 mutation 或文件重写。不覆盖 nodetool/JMX 命令的完整清单，也不展开 bulk loader、FQL tool、cassandra-stress。wrapper 到 runbook 的覆盖 drift 由 `research/tools/check-sstable-tools-runbook-drift.py` 检查，设计见 `research/module-sstable-tools-drift-checker.md`。

## 设计目标

- standalone SSTable tools 必须能在 daemon 生命周期之外初始化配置、加载 schema、解析 descriptor，并尽量避免把损坏 SSTable 加入正常 table lifecycle。
- 读工具应优先用 SSTable 自带 metadata 恢复 schema 或 `openNoValidation()`，降低对系统 keyspace 和运行中服务的依赖。
- 重写工具必须使用 offline transaction 或 metadata serializer mutation，并在 help/option 中暴露足够强的安全提示。
- 高风险工具需要显式确认开关，例如 `sstableverify --force`、`sstablelevelreset --really-reset`、`sstablerepairedset --really-set`。
- 对会替换或删除源文件的工具，默认尽量保留 snapshot 或提供 keep-source/dry-run/no-snapshot 这类可审计选项。

## 解决的问题

- 工具初始化不能启动完整服务端。公共 `Util.initDatabaseDescriptor()` 只触发 `DatabaseDescriptor.toolInitialization()` 并在配置错误时退出，见 `src/java/org/apache/cassandra/tools/Util.java:271-297`。
- 对 keyspace/table 型工具，源码通常先 `Schema.instance.loadFromDisk()`，再 `Keyspace.openWithoutSSTables()`，避免正常打开 table 时加载 live SSTables，见 `src/java/org/apache/cassandra/tools/StandaloneVerifier.java:87-99`、`src/java/org/apache/cassandra/tools/StandaloneScrubber.java:91-100` 和 `src/java/org/apache/cassandra/tools/StandaloneUpgrader.java:65-76`。
- 对单文件/目录型读工具，源码可从 `Stats.db`/header 恢复 table metadata，再 `SSTableReader.openNoValidation()`，见 `src/java/org/apache/cassandra/tools/Util.java:305-335`、`src/java/org/apache/cassandra/tools/SSTableExport.java:147-151` 和 `src/java/org/apache/cassandra/tools/SSTablePartitions.java:356-358`。
- 高风险 verify 默认拒绝执行，必须传 `-f/--force`，见 `src/java/org/apache/cassandra/tools/StandaloneVerifier.java:70-79`；help 文案和测试也强调 known risks，见 `test/unit/org/apache/cassandra/tools/StandaloneVerifierTest.java:41-71`。
- metadata mutation 工具在源码和测试中都要求停止 Cassandra 并传 “really” 开关，见 `src/java/org/apache/cassandra/tools/SSTableRepairedAtSetter.java:38-58`、`src/java/org/apache/cassandra/tools/SSTableLevelResetter.java:44-62`、`test/unit/org/apache/cassandra/tools/SSTableRepairedAtSetterTest.java:52-60` 和 `test/unit/org/apache/cassandra/tools/SSTableLevelResetterTest.java:47-85`。

## 设计取舍

- standalone 工具不通过 StorageService 协调 compaction/flush/repair，因此不能与 daemon 对同一 live SSTable 的 mutation 并发；源码侧只能通过 `openWithoutSSTables()`、`skipTemporary(true)`、offline transaction、snapshot/keep-source 等手段降低破坏面。
- `openNoValidation()` 允许工具查看可能损坏的 SSTable，但也意味着某些正常 reader load 校验被绕过；verify/scrub 之后才应据此做修复判断，见 `src/java/org/apache/cassandra/tools/StandaloneVerifier.java:101-138` 和 `src/java/org/apache/cassandra/tools/StandaloneScrubber.java:138-173`。
- `sstablemetadata` 默认只读 metadata component；`-s/--scan` 会打开 scanner 遍历 SSTable，统计 widest/largest/tombstone leaders，成本接近全表扫描，见 `src/java/org/apache/cassandra/tools/SSTableMetadataViewer.java:172-180` 和 `src/java/org/apache/cassandra/tools/SSTableMetadataViewer.java:250-313`。
- `sstableverify` 的 `--mutate_repair_status` 选项名与 standalone help 文案不一致：代码把该开关传给 verifier，verifier 在 corrupt repaired SSTable 上可把 repaired status 改为 unrepaired，见 `src/java/org/apache/cassandra/tools/StandaloneVerifier.java:126-132`、`src/java/org/apache/cassandra/io/sstable/IVerifier.java:95-127` 和 `src/java/org/apache/cassandra/io/sstable/format/SortedTableVerifier.java:124-138`。
- `sstableupgrade` 可升级 snapshot，但 usage 明确这种操作会替换 snapshot 文件并破坏与 live SSTable 的硬链接；`-k/--keep-source` 可保留源 SSTable，见 `src/java/org/apache/cassandra/tools/StandaloneUpgrader.java:214-235`。

## 核心类

| 类 | 作用 |
|---|---|
| `Util` | standalone 工具共享的初始化、histogram 输出和 `metadataFromSSTable()` schema 恢复工具，见 `src/java/org/apache/cassandra/tools/Util.java:271-335` |
| `StandaloneSSTableUtil` | 列出 final/tmp/transaction log 文件，或 `--cleanup` 清理 unfinished transaction leftovers，见 `src/java/org/apache/cassandra/tools/StandaloneSSTableUtil.java:44-90` |
| `StandaloneVerifier` | 离线打开 table SSTables 并运行 verifier，默认需要 `--force`，可 quick/extended/check version/token range，见 `src/java/org/apache/cassandra/tools/StandaloneVerifier.java:70-138` |
| `StandaloneScrubber` | 自动创建 pre-scrub snapshot，然后用 offline transaction scrub/重写 SSTable，见 `src/java/org/apache/cassandra/tools/StandaloneScrubber.java:117-173` |
| `StandaloneUpgrader` | 用 offline transaction 将旧 SSTable 重写为当前版本，可 `--keep-source`，见 `src/java/org/apache/cassandra/tools/StandaloneUpgrader.java:57-121` |
| `StandaloneSplitter` | 对指定 SSTable 文件按 size 拆分，默认创建 pre-split snapshot，可 `--no-snapshot`，见 `src/java/org/apache/cassandra/tools/StandaloneSplitter.java:66-158` |
| `SSTableMetadataViewer` | 读取 `Statistics.db`/compression metadata，或 `--scan` 全量扫描分区统计，见 `src/java/org/apache/cassandra/tools/SSTableMetadataViewer.java:316-390` |
| `SSTableExport` | 将单个 SSTable 导出 JSON/json-lines/key list/debug rows，见 `src/java/org/apache/cassandra/tools/SSTableExport.java:110-220` |
| `SSTablePartitions` | 扫描 SSTable 或目录，按阈值输出 partition 级统计，支持 recursive/snapshots/backups，见 `src/java/org/apache/cassandra/tools/SSTablePartitions.java:152-175` 和 `src/java/org/apache/cassandra/tools/SSTablePartitions.java:276-370` |
| `SSTableRepairedAtSetter` | 直接修改 repairedAt metadata，必须 `--really-set`，见 `src/java/org/apache/cassandra/tools/SSTableRepairedAtSetter.java:38-88` |
| `SSTableLevelResetter` / `SSTableOfflineRelevel` | 直接修改 SSTable level metadata；前者强制 level=0，后者可 `--dry-run` 计算新分层，见 `src/java/org/apache/cassandra/tools/SSTableLevelResetter.java:44-103` 和 `src/java/org/apache/cassandra/tools/SSTableOfflineRelevel.java:80-145` |

## 核心接口

- `DatabaseDescriptor.toolInitialization()`：standalone tools 初始化配置和静态单例，但不走 CassandraDaemon 启动流程；公共包装见 `src/java/org/apache/cassandra/tools/Util.java:271-297`。
- `Schema.instance.loadFromDisk()`：keyspace/table 型工具加载 schema，避免从正在运行的节点 API 获取表定义；调用示例见 `src/java/org/apache/cassandra/tools/StandaloneVerifier.java:87-95`。
- `Keyspace.openWithoutSSTables()`：打开 keyspace/table 对象但不加载磁盘 SSTables；verify/scrub/upgrader/splitter/relevel 都依赖它，见 `src/java/org/apache/cassandra/tools/StandaloneScrubber.java:99-104` 和 `src/java/org/apache/cassandra/tools/SSTableOfflineRelevel.java:102-112`。
- `SSTableReader.openNoValidation()`：对目标 SSTable 构造 reader，允许后续 verify/scrub/export/scan 决定如何处理损坏文件，见 `src/java/org/apache/cassandra/tools/StandaloneVerifier.java:101-114` 和 `src/java/org/apache/cassandra/tools/SSTableExport.java:147-151`。
- `LifecycleTransaction.offline()`：重写类工具的磁盘事务边界；scrub/split/upgrade 都在 offline transaction 中替换或 obsolete 原 SSTable，见 `src/java/org/apache/cassandra/tools/StandaloneScrubber.java:162-173`、`src/java/org/apache/cassandra/tools/StandaloneSplitter.java:154-158` 和 `src/java/org/apache/cassandra/tools/StandaloneUpgrader.java:116-121`。
- `descriptor.getMetadataSerializer().mutate*()`：metadata mutation 工具直接改 Statistics component，见 `src/java/org/apache/cassandra/tools/SSTableRepairedAtSetter.java:79-87`、`src/java/org/apache/cassandra/tools/SSTableLevelResetter.java:98-103` 和 `src/java/org/apache/cassandra/tools/SSTableOfflineRelevel.java:222-236`。

## 核心数据结构

- `Descriptor` / `Component`：所有工具先从文件名或 table directories 得到 descriptor/component set；splitter 拒绝非 SSTable 文件并要求同一 keyspace/table，见 `src/java/org/apache/cassandra/tools/StandaloneSplitter.java:82-107`。
- `TableMetadata`：keyspace/table 型工具从 schema disk state 取真实 metadata；单文件工具可用 `Util.metadataFromSSTable()` 从 header 恢复临时 metadata，见 `src/java/org/apache/cassandra/tools/Util.java:312-335`。
- `Directories.SSTableLister`：按 table data directories 列出 SSTables，支持 skip temporary、include backups、snapshot filtering，见 `src/java/org/apache/cassandra/tools/StandaloneVerifier.java:101-109` 和 `src/java/org/apache/cassandra/tools/StandaloneUpgrader.java:78-88`。
- `StatsComponent` / `StatsMetadata`：metadata viewer、level reset、repaired setter、offline relevel 都读取或修改 Statistics component，见 `src/java/org/apache/cassandra/tools/SSTableMetadataViewer.java:316-339` 和 `src/java/org/apache/cassandra/tools/SSTableLevelResetter.java:90-103`。
- `LifecycleTransaction` leftovers：`sstableutil --cleanup` 和 level/relevel 工具可清理 unfinished transaction leftovers；这会修改磁盘文件集合，见 `src/java/org/apache/cassandra/tools/StandaloneSSTableUtil.java:61-65` 和 `src/java/org/apache/cassandra/tools/SSTableLevelResetter.java:80-88`。

## 生命周期

只读单文件工具：

```text
sstabledump / sstablemetadata / sstablepartitions
  -> DatabaseDescriptor.toolInitialization()
  -> Descriptor.fromFile(...)
  -> Util.metadataFromSSTable(desc)
  -> SSTableReader.openNoValidation(...)
  -> key iteration / scanner / metadata print
  -> release reader
```

keyspace/table 重写工具：

```text
sstablescrub / sstableupgrade / sstablesplit
  -> Util.initDatabaseDescriptor()
  -> Schema.instance.loadFromDisk()
  -> Keyspace.openWithoutSSTables(...)
  -> list or parse target SSTables
  -> optional snapshot / keep-source guard
  -> LifecycleTransaction.offline(...)
  -> scrub / upgrade / split
  -> finish compactions and wait for deletions
```

metadata mutation tools:

```text
sstablerepairedset / sstablelevelreset / sstableofflinerelevel
  -> explicit safety flag or dry-run where available
  -> tool initialization
  -> load schema or parse descriptor list
  -> descriptor.getMetadataSerializer().mutateRepairMetadata / mutateLevel
```

## 调用链

- `sstableutil`：初始化配置、加载 schema，默认列文件；`--cleanup` 调用 `LifecycleTransaction.removeUnfinishedLeftovers(metadata)`，见 `src/java/org/apache/cassandra/tools/StandaloneSSTableUtil.java:44-70`。
- `sstableverify`：解析 options，拒绝无 `--force`，加载 schema，`openWithoutSSTables()` 后打开完整 primary components，再构造 `IVerifier.Options` 执行 `verifier.verify()`，见 `src/java/org/apache/cassandra/tools/StandaloneVerifier.java:70-138`。
- `sstablescrub`：加载 table，先为所有 Data component 创建 snapshot hard links，再用 `LifecycleTransaction.offline(OperationType.SCRUB, sstable)` 和 format-specific scrubber 重写/修复，见 `src/java/org/apache/cassandra/tools/StandaloneScrubber.java:117-173`。
- `sstableupgrade`：按 id 顺序打开需要升级的 SSTable，跳过已是 latest version 的 reader，之后 offline transaction 调用 `Upgrader.upgrade(keepSource)`，见 `src/java/org/apache/cassandra/tools/StandaloneUpgrader.java:85-121`。
- `sstablesplit`：解析指定文件，要求同一 keyspace/table，默认 snapshot，然后 offline transaction 调用 `SSTableSplitter.split()`，见 `src/java/org/apache/cassandra/tools/StandaloneSplitter.java:82-158`。
- `sstablemetadata`：读取 Stats/Validation/Compaction/SerializationHeader/Compression metadata；如果 `--scan` 且版本支持，则打开 scanner 统计行、cell、tombstone 和 partition leaders，见 `src/java/org/apache/cassandra/tools/SSTableMetadataViewer.java:316-390`。
- `sstabledump`：从 SSTable 自身恢复 metadata 并打开 reader，可枚举 keys、按 keys 建 bounds、或 full scanner 输出 JSON/debug 行，见 `src/java/org/apache/cassandra/tools/SSTableExport.java:147-220`。
- `sstablepartitions`：验证文件/目录可读，递归时默认跳过 snapshots/backups，除非显式 `--snapshots`/`--backups`，然后扫描分区统计，见 `src/java/org/apache/cassandra/tools/SSTablePartitions.java:276-370` 和 `src/java/org/apache/cassandra/tools/SSTablePartitions.java:791-848`。
- `sstableexpiredblockers`：打开 table 所有 SSTables，计算 expired SSTable blockers 并打印阻塞关系，不修改 metadata，见 `src/java/org/apache/cassandra/tools/SSTableExpiredBlockers.java:51-103`。
- `sstablerepairedset`：验证 `--really-set` 和 repaired/unrepaired 模式后，按文件或文件列表直接 mutate repair metadata，见 `src/java/org/apache/cassandra/tools/SSTableRepairedAtSetter.java:38-88`。
- `sstablelevelreset` / `sstableofflinerelevel`：前者需要 `--really-reset` 并把 level>0 改成 0；后者可 `--dry-run`，非 dry-run 时按 token overlap 重新 mutate levels，见 `src/java/org/apache/cassandra/tools/SSTableLevelResetter.java:44-103` 和 `src/java/org/apache/cassandra/tools/SSTableOfflineRelevel.java:173-236`。

## 配置项

| 配置/参数 | 安全影响 |
|---|---|
| `--force` on `sstableverify` | 必须显式传入才会运行；代码和测试都把它作为高风险确认，见 `src/java/org/apache/cassandra/tools/StandaloneVerifier.java:70-79` 和 `test/unit/org/apache/cassandra/tools/StandaloneVerifierTest.java:41-71` |
| `--quick` on `sstableverify` | 不读取所有 data，降低 IO，但也减少校验深度，见 `src/java/org/apache/cassandra/io/sstable/IVerifier.java:58-61` 和 `src/java/org/apache/cassandra/tools/StandaloneVerifier.java:277-287` |
| `--extended` on `sstableverify` | 强制 extended verification，增加 IO/CPU，见 `src/java/org/apache/cassandra/io/sstable/IVerifier.java:48-52` |
| `--mutate_repair_status` on `sstableverify` | 代码层可在 corrupt repaired SSTable 上 mutate repair status；使用前按 metadata mutation 风险处理，见 `src/java/org/apache/cassandra/io/sstable/format/SortedTableVerifier.java:124-138` |
| `--manifest-check` on `sstablescrub` | 只检查/修复 leveled manifest，不进入 row scrub，见 `src/java/org/apache/cassandra/tools/StandaloneScrubber.java:162-193` 和 `src/java/org/apache/cassandra/tools/StandaloneScrubber.java:312-319` |
| `--header-fix` on `sstablescrub` | 仅保留兼容选项，help 标注 validate/fix 模式；测试显示 deprecated warning，见 `src/java/org/apache/cassandra/tools/StandaloneScrubber.java:321-337` 和 `test/unit/org/apache/cassandra/tools/StandaloneScrubberTest.java:135-141` |
| `--keep-source` on `sstableupgrade` | 升级时保留源 SSTable，见 `src/java/org/apache/cassandra/tools/StandaloneUpgrader.java:116-121` 和 `src/java/org/apache/cassandra/tools/StandaloneUpgrader.java:214-220` |
| `--no-snapshot` on `sstablesplit` | 禁止默认 pre-split snapshot；只应在已有备份时使用，见 `src/java/org/apache/cassandra/tools/StandaloneSplitter.java:133-158` 和 `src/java/org/apache/cassandra/tools/StandaloneSplitter.java:247-253` |
| `--cleanup` on `sstableutil` | 删除 unfinished transaction leftovers，不是纯 list 操作，见 `src/java/org/apache/cassandra/tools/StandaloneSSTableUtil.java:61-65` |
| `--really-set` / `--really-reset` | repaired status 和 level reset 的显式危险确认，见 `src/java/org/apache/cassandra/tools/SSTableRepairedAtSetter.java:48-58` 和 `src/java/org/apache/cassandra/tools/SSTableLevelResetter.java:54-62` |
| `--dry-run` on `sstableofflinerelevel` | 只打印 potential leveling，不 mutate level metadata，见 `src/java/org/apache/cassandra/tools/SSTableOfflineRelevel.java:92-95` 和 `src/java/org/apache/cassandra/tools/SSTableOfflineRelevel.java:212-236` |
| `--scan` on `sstablemetadata` | 从 metadata-only 变成 full SSTable scan，见 `src/java/org/apache/cassandra/tools/SSTableMetadataViewer.java:172-180` 和 `test/unit/org/apache/cassandra/tools/SSTableMetadataViewerTest.java:206-217` |
| `--recursive --snapshots --backups` on `sstablepartitions` | 决定目录扫描是否包含 snapshot/backup SSTables，默认递归时跳过它们，见 `src/java/org/apache/cassandra/tools/SSTablePartitions.java:126-143` 和 `src/java/org/apache/cassandra/tools/SSTablePartitions.java:276-305` |

## Metrics

- standalone tools 通常不向 Cassandra metrics registry 报告业务指标；它们的“指标”是 stdout/stderr、exit code 和离线统计输出。
- `sstablemetadata --scan` 输出 partition count、row count、cell count、tombstone count、widest/largest/tombstone leaders，见 `src/java/org/apache/cassandra/tools/SSTableMetadataViewer.java:268-309`。
- `sstablepartitions` 输出 SSTable/partition 级统计，可 CSV；scanner 统计入口见 `src/java/org/apache/cassandra/tools/SSTablePartitions.java:345-370` 和 `src/java/org/apache/cassandra/tools/SSTablePartitions.java:722-736`。
- `ToolsSchemaLoadingTest` 和各工具测试用 exit code/stdout/stderr 作为 CLI 行为 contract，见 `test/unit/org/apache/cassandra/tools/ToolsSchemaLoadingTest.java:30-103`。

## 日志

- 工具侧日志配置来自 `conf/logback-tools.xml`，已有 operations 文档引用为 tools stderr 日志阈值，见 `conf/logback-tools.xml:20-33`。
- 多数 standalone tools 用 `System.out`/`System.err` 和 `OutputHandler.SystemOutput` 报告进度、错误和 debug stack trace；verify/scrub/upgrader 示例见 `src/java/org/apache/cassandra/tools/StandaloneVerifier.java:101-143`、`src/java/org/apache/cassandra/tools/StandaloneScrubber.java:155-188` 和 `src/java/org/apache/cassandra/tools/StandaloneUpgrader.java:123-128`。
- 配置初始化失败由 `Util.initDatabaseDescriptor()` 打印异常类型/message，必要时打印 stack trace 并以 exit code 3 退出，见 `src/java/org/apache/cassandra/tools/Util.java:275-297`。

## 运维关注点

- 只读不等于无风险：`sstablemetadata --scan`、`sstabledump` 和 `sstablepartitions` 会全量扫描 SSTable，对大文件可能造成明显磁盘 IO；优先对 snapshot 或复制文件运行。
- 会重写或 mutate metadata 的工具必须在 Cassandra 停止、无 compaction/repair/streaming/import 并发时运行；`sstablerepairedset` 和 `sstablelevelreset` 的 help 明确要求停止 Cassandra。
- 运行 `sstablescrub`、`sstablesplit`、`sstableupgrade` 前先用 `sstableutil` 列出目标文件，并确认没有 tmp/txn log leftovers；如需清理 leftovers，单独执行并记录 `sstableutil --cleanup`。
- 对 `sstablesplit --no-snapshot`、`sstableupgrade` 不带 `--keep-source`、`sstableofflinerelevel` 非 dry-run 这类操作，先做外部备份或 Cassandra snapshot。
- 对 snapshot 目录运行 `sstableupgrade` 会替换 snapshot 文件并破坏与 live SSTable 的 hard links；恢复旧版本 snapshot 前必须先理解该副作用。
- `sstableverify --mutate_repair_status` 应按数据修复操作处理：它可能把 corrupt repaired SSTable 标为 unrepaired，从而改变后续 incremental/full repair 策略。

## 性能瓶颈

- `sstableverify --extended`、`sstablemetadata --scan`、`sstabledump` full export、`sstablepartitions` full scan 和 `sstablescrub` 都可能读取完整 SSTable 数据。
- `sstablescrub` 和 `sstablesplit` 需要额外磁盘空间保存 snapshot/hard links 或新 SSTable 输出；如果底层不支持廉价 hard link，空间和 inode 压力更明显。
- `sstableupgrade` 会重写旧 SSTable 到当前格式；不带 `--keep-source` 时源文件生命周期由 offline transaction 管理，带 `--keep-source` 时需要更多磁盘空间。
- metadata mutation 工具本身很快，但风险集中在后续 compaction/repair 解释这些 metadata 的方式，尤其是 repairedAt、pending repair 和 level。

## 常见故障

- 工具直接打印 usage 且未加载 schema/server：通常是参数错误，`ToolsSchemaLoadingTest` 覆盖 no-args 路径不会加载 schema、CLSM、system keyspace、keyspace 或 server，见 `test/unit/org/apache/cassandra/tools/ToolsSchemaLoadingTest.java:30-103`。
- `sstableverify` 未传 `--force`：直接退出并提示 CASSANDRA-17017 风险，见 `src/java/org/apache/cassandra/tools/StandaloneVerifier.java:70-79`。
- `sstablesplit` 目标文件不存在或不是 SSTable：会跳过文件，若没有有效 SSTable 则退出，见 `src/java/org/apache/cassandra/tools/StandaloneSplitter.java:82-113` 和 `test/unit/org/apache/cassandra/tools/StandaloneSplitterTest.java:77-96`。
- `sstablerepairedset` / `sstablelevelreset` 缺少 really flag：只打印 Cassandra stopped warning 和正确 usage，不修改文件，见 `src/java/org/apache/cassandra/tools/SSTableRepairedAtSetter.java:48-58` 和 `src/java/org/apache/cassandra/tools/SSTableLevelResetter.java:54-62`。
- SSTable version 不兼容：`Util.metadataFromSSTable()` 会拒绝 unsupported version；`SSTableRepairedAtSetter` 也会跳过 incompatible descriptor，见 `src/java/org/apache/cassandra/tools/Util.java:312-317` 和 `src/java/org/apache/cassandra/tools/SSTableRepairedAtSetter.java:70-77`。
- `sstablemetadata mockFile` 这类不存在文件：测试期望 stdout 包含 "No such file" 并保持工具环境清理，见 `test/unit/org/apache/cassandra/tools/SSTableMetadataViewerTest.java:94-114`。

## 测试用例

- `ToolsSchemaLoadingTest` 覆盖 verifier/scrubber/splitter/sstableutil/upgrader no-args 失败时不加载 schema/server 状态，见 `test/unit/org/apache/cassandra/tools/ToolsSchemaLoadingTest.java:30-103`。
- `StandaloneVerifierTest` 覆盖 `--force` help/risk 文案、quick/extended/mutateRepairStatus options 和 clean exit，见 `test/unit/org/apache/cassandra/tools/StandaloneVerifierTest.java:41-150`。
- `StandaloneVerifierOnSSTablesTest` 用真实/损坏 SSTable 覆盖 check-version、corrupt stats 和 corrupt data 失败路径，见 `test/unit/org/apache/cassandra/tools/StandaloneVerifierOnSSTablesTest.java:93-173`。
- `StandaloneScrubberTest` 覆盖 help 文案、pre-scrub snapshot 输出、header-fix deprecated warning，见 `test/unit/org/apache/cassandra/tools/StandaloneScrubberTest.java:42-90` 和 `test/unit/org/apache/cassandra/tools/StandaloneScrubberTest.java:135-141`。
- `StandaloneSplitterTest` 覆盖 `--no-snapshot` help、错误文件和参数失败路径，见 `test/unit/org/apache/cassandra/tools/StandaloneSplitterTest.java:50-96`。
- `StandaloneSSTableUtilTest` 覆盖 list、`--cleanup`、type/oplog/debug/verbose options，见 `test/unit/org/apache/cassandra/tools/StandaloneSSTableUtilTest.java:45-102`。
- `SSTableMetadataViewerTest` 覆盖 no-args/help、不存在文件、普通 metadata 输出和 `--scan` widest partitions 输出，见 `test/unit/org/apache/cassandra/tools/SSTableMetadataViewerTest.java:50-115` 和 `test/unit/org/apache/cassandra/tools/SSTableMetadataViewerTest.java:206-228`。
- `SSTableRepairedAtSetterTest` 与 `SSTableLevelResetterTest` 覆盖 really flags、stopped warning 和 clean environment，见 `test/unit/org/apache/cassandra/tools/SSTableRepairedAtSetterTest.java:52-123` 和 `test/unit/org/apache/cassandra/tools/SSTableLevelResetterTest.java:47-85`。
- `python3 research/tools/check-sstable-tools-runbook-drift.py` 检查 `bin/sstable*` / `tools/bin/sstable*` wrapper 的 tool name 和 Java main class 是否进入本 runbook，见 `research/module-sstable-tools-drift-checker.md`。

## 待继续

- 补真实大文件/低磁盘空间场景的 `sstablescrub`、`sstablesplit`、`sstableupgrade --keep-source` 空间预算测试。
