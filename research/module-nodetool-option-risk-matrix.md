# Module: Nodetool Option And Argument Risk Matrix

## 范围

本模块补齐 nodetool runbook 的 option/argument 层覆盖。`research/tools/check-nodetool-runbook-drift.py` 已用 `NodeTool.execute()` registry 和 `@Command` annotation 保护 147 个顶层命令与 6 个 command-group 子命令；本模块进一步把 `@Option` / `@Arguments` 风险分组固化为源码契约。

当前基线限定为 `src/java/org/apache/cassandra/tools/NodeTool.java`、`src/java/org/apache/cassandra/tools/ListCIDRGroups.java` 和 `src/java/org/apache/cassandra/tools/nodetool/*.java`。该范围包含 180 @Option、76 @Arguments、94 annotated source files。`src/java/org/apache/cassandra/tools/JMXTool.java` 也使用 Airline annotation，但它是 standalone JMX browser，不属于 nodetool command registry，本 checker 有意排除。

## 设计目标

- 用 annotation 计数和 annotated file set 保护 nodetool 参数面，避免新增高风险 flag 后只更新命令名而漏写风险说明。
- 把参数分成连接、repair scope、topology、data rewrite、streaming throttle、audit/FQL、auth cache、snapshot cleanup、table selection、format output、guardrail 和 sampler 十二类。
- 对高风险命令同时记录 source file、option token、核心 NodeProbe/MBean 调用和测试锚点。
- 保持 source-only，不启动 Cassandra、不连 JMX、不依赖 Airline classpath。

## 解决的问题

- command-level runbook 只能证明 `repair`、`rebuild`、`verify` 等命令被列出，不能证明 `--force`、`--paxos-only`、`--require-index-components`、`--older-than-timestamp` 这类改变安全边界的参数被分析。
- nodetool 全局 JMX 连接参数定义在 `NodeTool.NodeToolCmd`，而不是每个 command class；遗漏 `--password-file`、`--print-port` 会影响所有命令的安全和输出语义，见 `src/java/org/apache/cassandra/tools/NodeTool.java:348-388`。
- command 参数并不都表现为 `@Option`。拓扑操作中的 `move <new token>`、`removenode <status>|<force>|<ID>`、`assassinate <ip_address>`、`rebuild <src-dc-name>` 都是 `@Arguments`，但风险高于很多普通 flag。
- 部分输出类参数看似无害，但会改变遍历成本或输出体积，例如 `tablestats --sort/--top/--sstable-location-check`，见 `src/java/org/apache/cassandra/tools/nodetool/TableStats.java:35-107`。

## 设计取舍

- checker 固定 annotation 计数和 annotated file set，而不是生成一份 256 行 option dump。这样新增/删除 annotation 会触发 drift，同时文档仍围绕风险类别维护。
- 对高风险 command 使用 token contract，例如 `Repair.java` 必须保留 `--skip-paxos`、`--paxos-only` 和 `--ignore-unreplicated-keyspaces`；这比只看总数更能发现危险参数变化。
- 不解析 Java AST。源码结构若大改，checker 会以 count/file/token drift 失败，维护者再判断是否升级 parser。
- 不把 standalone `JMXTool.java` 纳入 nodetool baseline；JMX browser 选项应在 JMX tool 文档中单独覆盖。

## 核心类

| 类/文件 | 作用 |
|---|---|
| `NodeTool.NodeToolCmd` | 全局 `--host`、`--port`、`--username`、`--password`、`--password-file`、`--print-port` 参数与 `runInternal()` 连接生命周期，见 `src/java/org/apache/cassandra/tools/NodeTool.java:348-399`。 |
| `NodeProbe` | nodetool 参数最终进入的 JMX facade；repair、streaming、snapshot、auth cache、audit/FQL、compaction 等命令都通过它调用 MBean，见 `src/java/org/apache/cassandra/tools/NodeProbe.java:262-321`。 |
| `Repair` | repair scope/safety 参数最密集的命令，`@Arguments` 选择 keyspace/table，`@Option` 控制 parallelism、DC/host/token range、preview/validate、Paxos 和 unrepl keyspace 行为，见 `src/java/org/apache/cassandra/tools/nodetool/Repair.java:43-108`。 |
| `Rebuild` / `Move` / `RemoveNode` / `Assassinate` / `Decommission` / `BootstrapResume` | topology/streaming 操作参数入口，见 `src/java/org/apache/cassandra/tools/nodetool/Rebuild.java:32-64`、`Move.java:29-42`、`RemoveNode.java:29-45`、`Assassinate.java:31-42`、`Decommission.java:30-44`、`BootstrapResume.java:31-47`。 |
| `Compact` / `Scrub` / `Verify` / `Import` / `SSTableRepairedSet` | data rewrite、validation bypass、token ownership、index component 和 repaired-state mutation 参数入口，见 `src/java/org/apache/cassandra/tools/nodetool/Compact.java:33-96`、`Scrub.java:34-75`、`Verify.java:35-89`、`Import.java:39-117`、`SSTableRepairedSet.java:35-91`。 |
| `EnableAuditLog` / `EnableFullQueryLog` | runtime audit/FQL 配置参数，包含 queue、roll、path、archive command 和 blocking 行为，见 `src/java/org/apache/cassandra/tools/nodetool/EnableAuditLog.java:31-88`、`EnableFullQueryLog.java:28-69`。 |
| `SetAuthCacheConfig` / `SetAutoRepairConfig` / `SetConcurrency` / `GuardrailsConfigCommand` | runtime control-plane 参数，覆盖 auth cache、auto repair、stage concurrency 和 guardrail 配置面，见 `SetAuthCacheConfig.java:31-91`、`SetAutoRepairConfig.java:40-150`、`SetConcurrency.java:31-58`、`GuardrailsConfigCommand.java:55-110`。 |
| `SetStreamThroughput` / `SetInterDCStreamThroughput` / `GetStreamThroughput` / `GetInterDCStreamThroughput` | streaming throttle 单位和 entire-SSTable 维度参数，见 `SetStreamThroughput.java:27-54`、`SetInterDCStreamThroughput.java:27-54`、`GetStreamThroughput.java:30-91`、`GetInterDCStreamThroughput.java:30-93`。 |
| `ClearSnapshot` / `Snapshot` | snapshot create/delete filter 参数，见 `src/java/org/apache/cassandra/tools/nodetool/ClearSnapshot.java:36-107`、`Snapshot.java:39-109`。 |
| `ProfileLoad` | low-footprint sampler 的 capacity/top/sampler/list/stop/interval 参数，见 `src/java/org/apache/cassandra/tools/nodetool/ProfileLoad.java:45-151`。 |

## 核心接口

- `@Option`：Airline option annotation，nodetool 使用它声明 short/long flag、required、allowedValues、global option 和 help text。
- `@Arguments`：Airline positional argument annotation，通常承载 keyspace/table、token、host ID、snapshot target、streaming throughput value 等。
- `NodeToolCmd.execute(NodeProbe)`：各 command 参数解析完成后的统一执行入口，连接生命周期由 `NodeToolCmd.runInternal()` 包办，见 `src/java/org/apache/cassandra/tools/NodeTool.java:380-455`。
- `NodeProbe` command methods：参数转换后的 JMX 调用边界，例如 `repairAsync()`、`rebuild()`、`importNewSSTables()`、`clearSnapshot()`、`setStreamThroughputMiB()`、`enableAuditLog()`、`getAuthCacheMBean()`。

## 核心数据结构

| 数据结构 | 字段 | 语义 |
|---|---|---|
| `ANNOTATION_SOURCE_FILES` | source path tuple | option/argument annotation baseline，当前为 94 annotated files。 |
| `EXPECTED_OPTION_COUNT` | 180 | nodetool baseline 的 `@Option` annotation 数量。 |
| `EXPECTED_ARGUMENTS_COUNT` | 76 | nodetool baseline 的 `@Arguments` annotation 数量。 |
| `SOURCE_EXPECTATIONS` | path -> tokens | 高风险命令必须保留的 option/argument/NodeProbe token。 |
| `SCENARIO_IDS` | risk category id | 文档必须覆盖的十二类参数风险。 |

## 风险矩阵

| 场景 ID | Source | 参数面 | 风险与运维关注 |
|---|---|---|---|
| `nodetool_global_jmx_connection_options` | `NodeTool.java` | `--host`、`--port`、`--username`、`--password`、`--password-file`、`--print-port` | 控制所有命令的 JMX target、认证和输出 endpoint 格式；非交互脚本应避免裸 `--password`，secure deployment 必须结合 JMX auth/SSL。 |
| `nodetool_repair_scope_and_safety_options` | `Repair.java` | keyspace/table args、`--sequential`、`--dc-parallel`、`--in-local-dc`、`--in-dc`、`--in-hosts`、`--start-token`、`--end-token`、`--partitioner-range`、`--full`、`--force`、`--preview`、`--validate`、`--pull`、`--optimise-streams`、`--skip-paxos`、`--paxos-only`、`--ignore-unreplicated-keyspaces` | 改变反熵范围、并发、Paxos cleanup 和 failure semantics；`--force` 会过滤 down endpoints，`--skip-paxos`/`--paxos-only` 改变 LWT 修复路径。 |
| `nodetool_topology_change_arguments` | `Rebuild.java`、`Move.java`、`RemoveNode.java`、`Assassinate.java`、`Decommission.java`、`BootstrapResume.java` | `rebuild <src-dc-name>`、`--keyspace`、`--tokens`、`--sources`、`--exclude-local-dc`、`move <new token>`、`removenode <status>|<force>|<ID>`、`assassinate <ip_address>`、`decommission --force`、`bootstrap resume --force` | 直接改变 token ownership、streaming source 或 node membership；这些参数必须结合 topology runbook 和 pending range 状态使用。 |
| `nodetool_data_rewrite_options` | `Compact.java`、`Scrub.java`、`Verify.java`、`Import.java`、`SSTableRepairedSet.java`、`Cleanup.java`、`GarbageCollect.java`、`Stop.java` | `--user-defined`、token/partition compaction、`--no-snapshot`、`--skip-corrupted`、`--no-validate`、`--extended-verify`、`--dfp`、`--rsc`、`--no-verify`、`--no-tokens`、`--quick`、`--require-index-components`、`--no-index-validation`、`--really-set`、`--compaction-id` | 触发 SSTable rewrite、验证跳过、磁盘故障策略、token ownership 检查、index component 要求和 repaired metadata mutation。 |
| `nodetool_streaming_throughput_units` | `SetStreamThroughput.java`、`SetInterDCStreamThroughput.java`、`GetStreamThroughput.java`、`GetInterDCStreamThroughput.java` | `<value_in_mb>`、`--mib`、`--entire-sstable-throughput`、`--precise-mbit` | Mbps/MiB/s 和 entire-SSTable throttle 容易混淆；设置命令禁止 `--mib` 与 `--entire-sstable-throughput` 同用，get 命令也限制多个 unit flags。 |
| `nodetool_audit_fql_runtime_options` | `EnableAuditLog.java`、`EnableFullQueryLog.java` | include/exclude keyspace/category/user、`--path`、`--blocking`、`--max-queue-weight`、`--max-log-size`、`--archive-command`、`--max-archive-retries`、`--roll-cycle` | 运行时变更审计/FQL 开销、落盘路径、queue backpressure 和 archive command；archive command 还受 yaml allow flag 限制。 |
| `nodetool_auth_cache_runtime_options` | `SetAuthCacheConfig.java`、`GetAuthCacheConfig.java`、invalidate cache commands | `--cache-name`、`--validity-period`、`--update-interval`、`--max-entries`、`--enable-active-update`、`--disable-active-update` | 改变 auth/cache 一致性、缓存容量和主动刷新；enable/disable active update 互斥，cache name 必须映射到 AuthCache MBean。 |
| `nodetool_snapshot_cleanup_filters` | `Snapshot.java`、`ClearSnapshot.java`、`ListSnapshots.java` | snapshot keyspaces/table/tag/kt-list/skip-flush/ttl、clearsnapshot `-t`、`--all`、`--older-than`、`--older-than-timestamp` | snapshot create/delete 以 keyspace/table/tag/time 过滤；clear snapshot 对 `--all` 与 tag 互斥，对相对时间和 timestamp 互斥。 |
| `nodetool_table_selection_arguments` | `ListCIDRGroups.java`、`Flush.java`、`Cleanup.java`、`Repair.java`、`Compact.java`、`Scrub.java`、`Verify.java`、`UpgradeSSTable.java`、`RecompressSSTables.java`、`Refresh.java`、`RelocateSSTables.java` | `[<keyspace> <tables>...]`、`[<keyspace.table>...]`、CIDR group args、directory args | 许多命令默认 all keyspaces/tables；研究和 runbook 必须标明默认范围、system keyspace 排除和 table parser 行为。 |
| `nodetool_output_format_options` | `TableStats.java`、`CompactionStats.java`、`ClientStats.java`、`Status.java`、`Ring.java`、`TpStats.java`、`Sjk.java` | `--format`、json/yaml、sort/top、human-readable、vtable、port-resolution flags | 改变输出格式、排序成本、vtable 数据源和自动化 parser contract；不应与 destructive action 混为一类。 |
| `nodetool_guardrail_runtime_options` | `GuardrailsConfigCommand.java` | `getguardrailsconfig --category/--expand`、`setguardrailsconfig <name> <value>` | 直接读取或改变 guardrail runtime config；名称映射由 GuardrailsMBean getter/setter 反射派生。 |
| `nodetool_sampler_runtime_options` | `ProfileLoad.java` | capacity/top/samplers/interval/stop/list 和 keyspace/table/duration args | profileload 可以启动后台 sampling job；capacity/top 有约束，interval 必须不小于 duration。 |

## 生命周期

```text
developer adds or changes nodetool @Option/@Arguments
  -> run python3 research/tools/check-nodetool-option-risk-drift.py
  -> checker compares annotation counts and annotated file set
  -> checker validates high-risk source tokens
  -> checker validates matrix/drift-checker docs contain scenario ids and test/source anchors
  -> update matrix or baseline before merging
```

## 调用链

```text
NodeTool.main(args)
  -> new NodeTool().execute(args)
     -> Airline Cli parses @Option/@Arguments
     -> NodeToolCmd.runInternal()
        -> connect() builds NodeProbe / JMX proxies
        -> command.execute(NodeProbe)
           -> NodeProbe method
              -> StorageServiceMBean / StreamManagerMBean / Cache MBean / Audit/FQL/Auth MBean
```

## 配置项

- CLI annotation 自身就是 nodetool option schema；没有额外配置文件。
- `NodeTool.NodeToolCmd` 的 global options 是跨命令配置面。
- runtime side effects 进入 Cassandra MBeans，例如 storage service、stream manager、audit log、FQL、auth cache、guardrails 和 auto repair。

## Metrics

- checker 不接入 runtime metrics。
- 可观测输出是 option count、arguments count、annotated file count、source contract failures 和 doc coverage failures。
- 命令运行时 metrics 仍按目标子系统归属，例如 repair/streaming/compaction/cache/audit/FQL/auth，而不是归属于 nodetool 本身。

## 日志

- checker 成功时输出 180 @Option、76 @Arguments、94 files tracked 和同步确认。
- drift 时输出新增/删除 annotated file、失败 source contract 或失败 doc token。
- 真实 nodetool 命令的服务端日志由目标子系统产生；本地 nodetool history 会隐藏 password 参数，见 `src/java/org/apache/cassandra/tools/NodeTool.java:300-316`。

## 运维关注点

- 新增 nodetool flag 时先判断它属于哪个 scenario id；如果它改变数据范围、membership、rewrite、validation 或 runtime config，必须同步本矩阵。
- 对 topology 和 repair 参数，runbook 应同时要求检查 ring/pending range/streaming state，不应只给出命令语法。
- 对 `--quick`、`--no-verify`、`--no-tokens`、`--no-index-validation` 这类跳过检查的参数，文档必须说明牺牲的验证层。
- 对 output-only 参数，仍需注意自动化 parser 兼容性和高成本读取。

## 性能瓶颈

- checker 只做文本 IO 和 regex count，成本低。
- 真实 nodetool 参数的性能影响取决于目标命令：repair/streaming/compaction/scrub/import 可能产生网络、磁盘和 CPU 压力；tablestats sort/top 主要影响本地 MBean/metrics 枚举和输出处理。

## 常见故障

- annotation count drift：新增或删除 `@Option` / `@Arguments`，需要更新 baseline 和风险矩阵。
- annotated file set drift：新增 command file 使用 annotation，必须判断是否属于 nodetool registry 和风险类别。
- source contract drift：高风险 token 改名、删除或行为迁移，需要重读对应 command 和 NodeProbe 方法。
- doc drift：新增风险类别、source path 或测试 anchor 未进入 matrix/checker 文档。

## 测试用例

- `python3 research/tools/check-nodetool-option-risk-drift.py`：source-only option/argument risk drift check。
- `python3 research/tools/check-nodetool-option-risk-drift.py --json`：输出 counts、scenario ids、source expectations 和失败项。
- `NodeToolCommandTest` 捕获 `repair` option map 并断言 `--paxos-only` 进入 `RepairOption`，见 `test/unit/org/apache/cassandra/tools/NodeToolCommandTest.java:70-82`。
- `FuzzTestBase` 通过 `Repair.parseOptionMap()` 生成随机 repair options，见 `test/unit/org/apache/cassandra/repair/FuzzTestBase.java:607`。
- `NodeToolTest` 覆盖 distributed nodetool `verify --check-tokens --force` 缺少 `--extended-verify` 的 system-exit 行为，见 `test/distributed/org/apache/cassandra/distributed/test/NodeToolTest.java:76-79`。
- `SetAuthCacheConfigTest` 覆盖 help/options、互斥 active update 和 cache MBean mutation，见 `test/unit/org/apache/cassandra/tools/nodetool/SetAuthCacheConfigTest.java:54-203`。
- `SetAutoRepairConfigTest` 覆盖 auto repair 参数、repair type 和 disabled scheduler guard，见 `test/unit/org/apache/cassandra/tools/nodetool/SetAutoRepairConfigTest.java:65-317`。
- `SetGetStreamThroughputTest` 与 `SetGetInterDCStreamThroughputTest` 覆盖 `--mib`、`--entire-sstable-throughput`、`--precise-mbit` 组合，见 `test/unit/org/apache/cassandra/tools/nodetool/SetGetStreamThroughputTest.java:114-216`。
- `ClearSnapshotTest` 覆盖 `-t`、`--all`、`--older-than`、`--older-than-timestamp` 和互斥组合，见 `test/unit/org/apache/cassandra/tools/nodetool/ClearSnapshotTest.java:84-250`。
- `ScrubToolTest` 覆盖 scrub skip/validate 行为，见 `test/unit/org/apache/cassandra/tools/nodetool/ScrubToolTest.java:84-180`。
- `ImportTest` 覆盖 `SSTableImporter.Options` 的 verify/copy/token/cache/index 相关行为，见 `test/unit/org/apache/cassandra/db/ImportTest.java:83-979`。
