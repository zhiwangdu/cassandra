# Module: System Tables And Virtual System Keyspaces

## 范围

本模块覆盖 system、system_schema、system_auth、system_traces、system_distributed 和 system_views 表族，关注表定义、读写者和运维含义。

## 设计目标

本模块覆盖 Cassandra 5.0 的系统表族：本地持久系统表、schema 表、认证/权限表、tracing 表、distributed 系统表，以及 `system_views` / `system_virtual_schema` 虚拟 keyspace。它们共同承担节点身份、token/ring 状态、schema 持久化、auth 元数据、repair/MV 状态、observability 和 CQL introspection。

`system_traces.sessions/events` 与 `system` 核心表的逐列、写入方、读取方和生命周期矩阵见 `research/module-system-tables-core-matrix.md`；`system_distributed` repair/MV/denylist/autorepair 表的 owner 与清理矩阵见 `research/module-system-distributed-state-matrix.md`；`SystemKeyspace`、`SchemaKeyspace`、`TraceKeyspace`、`AuthKeyspace`、`SystemDistributedKeyspace` 的源码 CQL 列契约见 `research/module-system-table-column-contract.md`；Java registry 到 research 文档的 drift checker 见 `research/module-system-table-drift-checker.md` 和 `research/module-system-table-column-drift-checker.md`。

设计目标：

- 系统 keyspace 必须能在普通用户 keyspace 之前创建和读取，用于启动、schema load、gossip 和 ring 状态恢复。
- `system_schema` 是本地 schema 镜像，不走普通 RF 复制；schema agreement 通过 migration 协议传播。
- `system_auth`、`system_traces`、`system_distributed` 是 replicated keyspace，用于 auth、trace 和跨节点状态。
- virtual keyspace 不落盘，用 runtime provider 生成行，并通过 CQL 只读或受限可写接口暴露。
- 系统表写入必须避免普通业务路径的循环依赖，尤其是启动、prepare/cache、view build 和 repair 状态。

## 解决的问题

- 节点启动必须在用户表打开前恢复本地身份、tokens、peers 和 schema；`SystemKeyspace` 与 `SchemaKeyspace` 分别提供本地节点状态和 schema metadata，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:264-318` 和 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:90-145`。
- Auth、tracing、repair/MV 等跨节点系统状态不能只存本地，需要 replicated system keyspaces，metadata 入口见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:155-163`、`src/java/org/apache/cassandra/tracing/TraceKeyspace.java:110-113`、`src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:213-229`。
- 运维观测需要低成本暴露 runtime 状态，但不应落盘或参与 compaction/repair；`VirtualKeyspaceRegistry` 注册 `system_views`，见 `src/java/org/apache/cassandra/db/virtual/VirtualKeyspaceRegistry.java:30-80`。
- 普通用户需要读取部分 system schema 信息，但系统/auth/virtual keyspace 需要额外 DDL/DML 保护；虚拟表限制测试见 `test/unit/org/apache/cassandra/cql3/validation/entities/VirtualTableTest.java:905-1011`。

## 设计取舍

- `system` 和 `system_schema` 使用 local keyspace 语义，优先保证启动与本地恢复；schema 的集群收敛交给 migration 协议而不是表复制，`SchemaKeyspace.metadata()` 见 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:291-294`。
- `system_auth`、`system_traces`、`system_distributed` 走 replicated keyspace，牺牲一部分启动/查询复杂度换取跨节点可用性，metadata 见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:155-163`、`src/java/org/apache/cassandra/tracing/TraceKeyspace.java:110-113`、`src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:213-229`。
- Virtual tables 通过 provider 生成 runtime rows，避免 compaction/repair/storage 开销，但限制 DDL、TTL、timestamp、LWT、logged batch 等普通表能力，见 `test/unit/org/apache/cassandra/cql3/validation/entities/VirtualTableTest.java:905-1011`。
- `system_distributed` 按 compatibility mode 选择表集合，保留混合版本升级空间，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:213-229`。

## 核心类

| 类 | 作用 |
|---|---|
| `SchemaConstants` | 定义 local、replicated、virtual system keyspace 名称集合，见 `src/java/org/apache/cassandra/schema/SchemaConstants.java:40-68` 和 `src/java/org/apache/cassandra/schema/SchemaConstants.java:115-158` |
| `SystemKeyspace` | `system` keyspace 表定义、本地节点/ring/bootstrap/prepared/range 状态读写，metadata 入口见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:536-543` |
| `SchemaKeyspace` | `system_schema` 表定义及 schema metadata row 转换，metadata 入口见 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:291-294` |
| `AuthKeyspace` | `system_auth` roles/permissions/network/cidr 表定义，metadata 入口见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:155-163` |
| `TraceKeyspace` | `system_traces.sessions/events` 表定义，metadata 入口见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:110-113` |
| `SystemDistributedKeyspace` | `system_distributed` repair/MV/denylist/autorepair 表定义，metadata 入口见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:213-229` |
| `VirtualKeyspace` | virtual keyspace 容器，定义见 `src/java/org/apache/cassandra/db/virtual/VirtualKeyspace.java:29-58` |
| `VirtualKeyspaceRegistry` | virtual keyspace/table metadata 注册与查找，定义见 `src/java/org/apache/cassandra/db/virtual/VirtualKeyspaceRegistry.java:30-80` |
| `SystemViewsKeyspace` | `system_views` runtime virtual tables 组装入口，见 `src/java/org/apache/cassandra/db/virtual/SystemViewsKeyspace.java:26-60` |

## 核心接口

- `KeyspaceMetadata.metadata()` 风格的 system keyspace metadata 工厂：`SystemKeyspace.metadata()`、`SchemaKeyspace.metadata()`、`AuthKeyspace.metadata()`、`TraceKeyspace.metadata()`、`SystemDistributedKeyspace.metadata()` 分别创建系统 keyspace schema。
- `CreateTableStatement.parse(...).build()`：多数组件通过 CQL 字符串定义 system table，再构造 `TableMetadata`，示例见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:527-536` 和 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:281-294`。
- `VirtualTable` / `AbstractVirtualTable`：virtual table 的 runtime data provider 接口，典型实现类见 `src/java/org/apache/cassandra/db/virtual/CQLMetricsTable.java:31-51` 和 `src/java/org/apache/cassandra/db/virtual/GossipInfoTable.java:42-77`。
- `VirtualKeyspaceRegistry.register()` / `getTableNullable()`：daemon 注册和查询 virtual metadata/table 的入口，见 `src/java/org/apache/cassandra/db/virtual/VirtualKeyspaceRegistry.java:41-80`。

## 核心数据结构

- `KeyspaceMetadata` / `Tables`：每个 system keyspace 的 schema 容器，`SystemKeyspace.metadata()` 组装 `Tables.of(...)`，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:536-543`。
- `TableMetadata`：system table 的列、主键、comment、local/replicated 参数定义，`SystemKeyspace.parse()` 和 `SchemaKeyspace.parse()` 使用 `CreateTableStatement.parse()` 生成；四个 system table source 的 CQL column contract 由 `research/tools/check-system-table-column-drift.py` 校验，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:527-536` 和 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:281-294`。
- `VirtualKeyspace` 的 table id 到 `VirtualTable` map：注册后用于 CQL read path 按 metadata id 定位 provider，见 `src/java/org/apache/cassandra/db/virtual/VirtualKeyspace.java:29-58`。
- `SystemKeyspace.BootstrapState`：系统表中的 bootstrap/decommission 状态语义被 StorageService 启停和拓扑变更依赖，使用见 `src/java/org/apache/cassandra/service/StorageService.java:2315-2318` 和 `src/java/org/apache/cassandra/service/StorageService.java:5395-5397`。

## 系统 keyspace 分类

- `SchemaConstants` 定义本地系统 keyspace、replicated system keyspace 和 virtual system keyspace 名称集合，见 `src/java/org/apache/cassandra/schema/SchemaConstants.java:40-68` 和 `src/java/org/apache/cassandra/schema/SchemaConstants.java:115-158`。
- `system` keyspace 由 `SystemKeyspace.metadata()` 创建，包含 local、peers、compaction history、prepared statements、paxos、batches、range/view/rewrite 状态等本地表，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:536-543`。
- `system_schema` 由 `SchemaKeyspace.metadata()` 创建，使用 local keyspace params，见 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:291-294`。
- `system_auth` 由 `AuthKeyspace.metadata()` 创建，默认 simple RF 参数承载 roles/permissions 等表，见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:155-163`。
- `system_traces` 由 `TraceKeyspace.metadata()` 创建，承载 sessions/events，见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:110-113`。
- `system_distributed` 由 `SystemDistributedKeyspace.metadata()` 创建，承载 repair/MV/denylist/autorepair 等跨节点状态，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:213-229`。
- `system_views` 是 `VirtualKeyspace`，由 `SystemViewsKeyspace` 组装 runtime virtual tables，见 `src/java/org/apache/cassandra/db/virtual/SystemViewsKeyspace.java:26-60`。

## `system`

`SystemKeyspace` 的表按用途可分为：

- 节点身份和 ring：`local`、`peers_v2`、`peer_events_v2`，定义见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:264-318`。
- 存储/compaction 观测：`compaction_history`、`sstable_activity`、`table_estimates`，定义见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:321-397`。
- range/stream/view 状态：`available_ranges_v2`、`transferred_ranges_v2`、`view_builds_in_progress`、`built_views`，定义见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:390-455`。
- 查询/协调内部状态：`prepared_statements`、`batches`、`paxos`、`repairs`，定义见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:212-242` 和 `src/java/org/apache/cassandra/db/SystemKeyspace.java:448-477`。
- 兼容旧版本迁移：legacy peers/events/ranges 表仍在 metadata 里保留或迁移，定义见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:477-527`。

这些表的详细 owner 矩阵见 `research/module-system-tables-core-matrix.md`，其中覆盖 batchlog、Paxos、prepared statements、MV build、range checkpoint、consistent repair、table estimates 和 tracing tables。

关键调用：

- 启动时 `CassandraDaemon.setup()` 先初始化系统 keyspace/schema，再继续 ring/join 流程，相关阶段见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:230-291`。
- 本地节点 metadata 持久化由 `SystemKeyspace.persistLocalMetadata()` 覆盖，测试见 `test/unit/org/apache/cassandra/db/SystemKeyspaceTest.java:142`。
- prepared statement 持久化表为 native protocol prepared cache 提供跨重启恢复基础，表定义见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:448-455`。

## `system_schema`

`SchemaKeyspace` 将 schema 拆成 normalized tables：

- keyspaces/tables/columns：基础 schema 对象，见 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:90-145`。
- column masks、`dropped_columns`、triggers、views、indexes：表附属对象，见 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:147-230`。
- types/functions/aggregates：UDT/UDF/UDA 元数据，见 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:231-294`。
- `system_schema.tables` / `views` 的 `auto_repair` 是 `AUTOREPAIR_ENABLE` 条件列，源码最大 ABI 已纳入 `research/module-system-table-column-contract.md`。

关键行为：

- `SchemaKeyspace.metadata()` 使用 `KeyspaceParams.local()`，因此 schema 表本地持久化，schema 分发由 migration 层负责，见 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:291-294`。
- Schema 变更写入和读取会把 `TableMetadata`、`KeyspaceMetadata` 等对象转换成 rows 再转换回来；测试覆盖 conversions inverse，见 `test/unit/org/apache/cassandra/schema/SchemaKeyspaceTest.java:142-158`。
- 局部 schema 更新可见性由 tests 保证不会暴露 partial schema updates，见 `test/unit/org/apache/cassandra/schema/SchemaKeyspaceTest.java:92-102`。

## `system_auth`

`AuthKeyspace` 持久化内置 auth backend 的元数据：

- `roles`、`identity_to_role`、`role_members` 保存角色、登录、成员关系，见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:56-100`。
- `role_permissions`、`resource_role_permissons_index` 保存授权数据和按 resource 查找的反向索引，见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:100-116`。
- `network_permissions`、`cidr_permissions`、`cidr_groups` 支持网络/CIDR auth，见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:117-146`。
- `AuthKeyspace.metadata()` 组装这些表并使用 auth keyspace params，见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:155-163`。

运维上，`system_auth` RF 不当会直接影响登录/授权可用性；auth 模块的 permission cache/login flow 详见 `module-schema-cql-auth.md`。

## `system_traces`

`TraceKeyspace` 只有两张核心表：

- `sessions`：trace session 级 metadata、coordinator、parameters、duration 等，见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:73-88`。
- `events`：session 内事件时间线，见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:89-113`。

`system_traces` 使用 simple RF，至少为默认 RF 与历史默认值取较大值，见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:110-113`。Tracing 写入本身会带来额外系统表写入，因此生产排查时应短期开启。

`sessions` / `events` 的列语义、TTL、写入方和默认可读授权见 `research/module-system-tables-core-matrix.md`。

## `system_distributed`

`SystemDistributedKeyspace` 承载需要 replicated 的系统状态：

- repair history 和 parent repair history，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:120-166`。
- materialized view build status，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:166-176`。
- partition denylist 和 auto repair history/priority，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:176-206`。
- metadata 根据 compatibility mode 选择表集合，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:213-229`。

这类表不应简单当作业务数据调优；repair/MV/denylist 组件会按自己的语义读写。
各表写入方、读取方、TTL/删除/feature flag 语义见 `research/module-system-distributed-state-matrix.md`。

## Virtual System Keyspaces

- `VirtualKeyspace` 是 name + `ImmutableMap<TableId, VirtualTable>` 的容器，并生成 virtual keyspace metadata，见 `src/java/org/apache/cassandra/db/virtual/VirtualKeyspace.java:29-58`。
- `VirtualKeyspaceRegistry` 负责注册、按 keyspace/table id 查找 metadata/table，见 `src/java/org/apache/cassandra/db/virtual/VirtualKeyspaceRegistry.java:30-80`。
- `CassandraDaemon.setupVirtualKeyspaces()` 注册 `system_virtual_schema` 和 `system_views`，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:534-544`。
- `SystemViewsKeyspace` 默认注册 caches、clients、settings、sstable tasks、thread pools、metrics、gossip info、queries、logs 等表，见 `src/java/org/apache/cassandra/db/virtual/SystemViewsKeyspace.java:33-53`。
- 典型 virtual tables 包括 `CachesTable`、`ClientsTable`、`SettingsTable`、`SSTableTasksTable`、`ThreadPoolsTable`、`CQLMetricsTable`、`GossipInfoTable`、`QueriesTable`、`LogMessagesTable`，定义分别见 `src/java/org/apache/cassandra/db/virtual/CachesTable.java:27-39`、`src/java/org/apache/cassandra/db/virtual/ClientsTable.java:28-45`、`src/java/org/apache/cassandra/db/virtual/SettingsTable.java:46-62`、`src/java/org/apache/cassandra/db/virtual/SSTableTasksTable.java:30-44`、`src/java/org/apache/cassandra/db/virtual/ThreadPoolsTable.java:30-40`、`src/java/org/apache/cassandra/db/virtual/CQLMetricsTable.java:31-51`、`src/java/org/apache/cassandra/db/virtual/GossipInfoTable.java:42-77`、`src/java/org/apache/cassandra/db/virtual/QueriesTable.java:46-54`、`src/java/org/apache/cassandra/db/virtual/LogMessagesTable.java:53-78`。

## 生命周期

启动：

```text
CassandraDaemon.setup()
  -> initialize config, directories, schema
  -> create/open system keyspaces
  -> load schema from system_schema
  -> setupVirtualKeyspaces()
     -> register VirtualSchemaKeyspace
     -> register SystemViewsKeyspace
```

Schema DDL：

```text
ALTER/CREATE/DROP statement
  -> schema transform
  -> SchemaKeyspace converts metadata to mutations
  -> local system_schema updated
  -> migration notification/push to peers
```

Virtual table read：

```text
CQL SELECT system_views.<table>
  -> QueryProcessor / ReadCommand
  -> VirtualKeyspaceRegistry resolves table metadata
  -> VirtualTable.data(partitionKey / range)
  -> result rows generated from runtime state
```

## 调用链

- Daemon startup：`CassandraDaemon.setup()` 初始化 system data、加载 schema、打开 keyspaces、注册 virtual keyspaces，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:230-291` 和 `src/java/org/apache/cassandra/service/CassandraDaemon.java:534-544`。
- System keyspace metadata：`SystemKeyspace.metadata()` 组装 local system tables，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:536-543`。
- Schema metadata：`SchemaKeyspace.metadata()` 组装 `system_schema`，并由 schema update handler 将 schema diff 转换为 mutations，见 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:291-294` 和 `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:227-252`。
- Auth/traces/distributed metadata：`AuthKeyspace.metadata()`、`TraceKeyspace.metadata()`、`SystemDistributedKeyspace.metadata()` 创建 replicated system keyspaces，见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:155-163`、`src/java/org/apache/cassandra/tracing/TraceKeyspace.java:110-113`、`src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:213-229`。
- Virtual table read：`VirtualKeyspaceRegistry` 按 keyspace/table metadata 定位 virtual table provider，见 `src/java/org/apache/cassandra/db/virtual/VirtualKeyspaceRegistry.java:51-80`。

## 配置项

- `system` 和 `system_schema` 是 local keyspace，不能按业务 keyspace 方式设置 RF。
- `system_auth`、`system_traces`、`system_distributed` 是 replicated system keyspaces；RF 与默认 keyspace RF/compatibility mode 有关，metadata 分别见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:155-163`、`src/java/org/apache/cassandra/tracing/TraceKeyspace.java:110-113`、`src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:213-229`。
- `system_views` 与 `system_virtual_schema` 是 virtual keyspace，不落盘，不通过 compaction/repair 管理。

## Metrics

- `system_views.caches` 来源于 cache runtime state，table 定义见 `src/java/org/apache/cassandra/db/virtual/CachesTable.java:27-39`。
- `system_views.clients` 展示当前 native clients，table 定义见 `src/java/org/apache/cassandra/db/virtual/ClientsTable.java:28-45`。
- `system_views.settings` 展示配置项，table 定义见 `src/java/org/apache/cassandra/db/virtual/SettingsTable.java:46-62`。
- `system_views.cql_metrics` 展示 CQL prepared/executed metrics，table 定义见 `src/java/org/apache/cassandra/db/virtual/CQLMetricsTable.java:31-51`。
- `system_views.gossip_info` 展示 gossip endpoint state，table 定义见 `src/java/org/apache/cassandra/db/virtual/GossipInfoTable.java:42-77`。
- `system_views.system_logs` 由 virtual table appender 写入 ring buffer，table 定义见 `src/java/org/apache/cassandra/db/virtual/LogMessagesTable.java:53-78`。

## 日志

- `system_views.system_logs` 是日志到 virtual table 的桥接入口，`LogMessagesTable` 使用 ring buffer 保存日志行，见 `src/java/org/apache/cassandra/db/virtual/LogMessagesTable.java:53-90`。
- `CassandraDaemon.setupVirtualKeyspaces()` 注册 `SystemViewsKeyspace` 后会 flush 之前已经记录的 log messages 到 virtual table，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:534-544`。
- `SchemaKeyspace` 和 `SystemKeyspace` 本身更多是 metadata/table 定义，运行时异常通常通过 schema load、StorageService、auth/tracing/repair 调用方日志暴露。

## 运维关注点

- 不要手工修改 `system` / `system_schema` 表，除非执行明确的修复流程；这些表与启动和 schema agreement 强耦合。
- `system.local` 与 `peers_v2` 异常会影响 node identity、host id、preferred IP、token/ring 状态。
- `system_schema` 不一致通常应从 schema agreement/migration 排查，而不是直接改表。
- `system_auth` RF 太低或节点不可用会导致登录/授权失败；多 DC 集群要按 auth 查询路径规划 RF。
- `system_traces` 写入量随 tracing 开启而增加，长期开启可能污染系统表和 compaction。
- virtual tables 是 runtime 视图，不保证像普通表一样支持所有 DDL/DML；测试明确拒绝虚拟 keyspace DDL、read-only table mutation、TTL/timestamp/LWT 等，见 `test/unit/org/apache/cassandra/cql3/validation/entities/VirtualTableTest.java:905-1011`。

## 性能瓶颈

- 大量 prepared statements 会写入/读取 `system.prepared_statements`，并与 QueryProcessor prepared cache 交互。
- 高频 tracing 会向 `system_traces.events` 写入大量细粒度事件，增加系统 keyspace compaction 压力。
- virtual table 的查询成本取决于 provider；例如 logs/queries/gossip/metrics 表会扫描 runtime state，不应当被高频全表查询。
- `system_distributed` 写入与 repair/MV/denylist 工作流耦合，复制不可用会放大这些后台任务的失败。

## 常见故障

- `system_schema` 缺行或转换失败：schema load 可能无法构造完整 metadata；`SchemaKeyspaceTest` 覆盖无 partition/column 的异常场景，见 `test/unit/org/apache/cassandra/schema/SchemaKeyspaceTest.java:264-287`。
- local tokens/host id 异常：`SystemKeyspaceTest` 覆盖 local token 和 local host id 读取，见 `test/unit/org/apache/cassandra/db/SystemKeyspaceTest.java:59-91`。
- virtual table DDL 被拒绝：`VirtualTableTest.testInvalidDDLOperationsOnVirtualKeyspaceAndReadOnlyTable()` 覆盖 drop/alter/create 等拒绝路径，见 `test/unit/org/apache/cassandra/cql3/validation/entities/VirtualTableTest.java:984-1011`。
- virtual table DML 被拒绝：read-only 表 mutation、TTL/timestamp/LWT 等限制见 `test/unit/org/apache/cassandra/cql3/validation/entities/VirtualTableTest.java:905-980`。

## 测试用例

- `SystemKeyspaceTest` 覆盖 local tokens、host id、local metadata 持久化，见 `test/unit/org/apache/cassandra/db/SystemKeyspaceTest.java:49-142`。
- `SystemKeyspaceTablesNamesTest` 覆盖 `system`、`system_traces`、`system_auth` 和 `system_distributed` metadata table name 集合，见 `test/unit/org/apache/cassandra/cql3/SystemKeyspaceTablesNamesTest.java:51-88`。
- `SchemaKeyspaceTest` 覆盖 partial schema update 可见性、metadata 转换、extensions 和异常 schema rows，见 `test/unit/org/apache/cassandra/schema/SchemaKeyspaceTest.java:69-287`。
- `VirtualTableTest` 覆盖 read-only/mutable virtual table 的读写、过滤、DDL/DML 限制和 MBean 方法，见 `test/unit/org/apache/cassandra/cql3/validation/entities/VirtualTableTest.java:66-1110`。
- `CQLMetricsTableTest`、`GossipInfoTableTest`、`LogMessagesTableTest` 覆盖典型 `system_views` 表，见 `test/unit/org/apache/cassandra/db/virtual/CQLMetricsTableTest.java:38-108`、`test/unit/org/apache/cassandra/db/virtual/GossipInfoTableTest.java:40-58`、`test/unit/org/apache/cassandra/db/virtual/LogMessagesTableTest.java:45-126`。

## 待补项

- 将 `research/tools/check-system-table-drift.py` 和 `research/tools/check-system-table-column-drift.py` 接入 CI 或 pre-commit；若继续扩展 drift，应补类型、TTL、compaction/table params。
