# System Virtual Schema Columns Matrix

本矩阵把 `system_virtual_schema.columns` 从“运维观测章节中的一个规则”提升为独立源码合同。它服务三个场景：运维人员通过 CQL 自省 virtual table schema，驱动/工具通过 DESCRIBE 或查询发现 virtual 表列，开发者新增 `system_views` provider 时能确认列元数据是否自动暴露。

## 设计目标

- `system_virtual_schema` 是 virtual system keyspace，不落盘、不参与 repair/compaction/flush；keyspace 名定义在 `src/java/org/apache/cassandra/schema/SchemaConstants.java:52`。
- `VirtualSchemaKeyspace` 注册三张 virtual metadata 表：`keyspaces`、`tables`、`columns`，构造入口是 `src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java:33-40`。
- `columns` 表的目标是从已注册 `VirtualKeyspace` 的 `TableMetadata` / `ColumnMetadata` 动态投影列名、列类型、kind、position 和 clustering order，而不是维护第二份静态 schema 清单，见 `VirtualSchemaKeyspace.VirtualColumns.data()`。

## 核心类与接口

| 类/接口 | 职责 |
|---|---|
| `VirtualSchemaKeyspace` | `system_virtual_schema` 的 provider，包含 `VirtualKeyspaces`、`VirtualTables`、`VirtualColumns` 三张表。 |
| `VirtualColumns` | 定义 `system_virtual_schema.columns` schema，并遍历 `VirtualKeyspaceRegistry.instance.virtualKeyspacesMetadata()` 生成行。 |
| `VirtualKeyspaceRegistry` | daemon/test 注册 virtual keyspace，维护 keyspace name -> `VirtualKeyspace` 与 `TableId` -> `VirtualTable` 两个 map。 |
| `VirtualKeyspace` | 把 `Collection<VirtualTable>` 转为 `KeyspaceMetadata.virtual(name, Tables.of(...))`。 |
| `VirtualTable` / `AbstractVirtualTable` | provider API：`metadata()`、`select(partitionKey, ...)`、`select(dataRange, ...)`、`apply()`、`truncate()` 和 `allowFilteringImplicitly()`。 |
| `SinglePartitionReadCommand.VirtualTableSinglePartitionReadCommand` | 单分区 CQL/read command 访问 virtual table 时绕过普通 storage engine。 |
| `PartitionRangeReadCommand.VirtualTablePartitionRangeReadCommand` | 范围 CQL/read command 访问 virtual table 时调用 provider 的 `select(DataRange, ...)`。 |

## 数据结构

- `system_virtual_schema.keyspaces`：partition key `keyspace_name`。
- `system_virtual_schema.tables`：partition key `keyspace_name`，clustering `table_name`，regular `comment`。
- `system_virtual_schema.columns`：partition key `keyspace_name`，clustering `table_name` / `column_name`，regular `clustering_order`、`column_name_bytes`、`kind`、`position`、`type`。
- `SimpleDataSet` 是常见 provider 输出容器；`AbstractVirtualTable` 只要求返回 `DataSet`，具体实现可以全量构造，也可以覆盖 `data(partitionKey)` 优化单分区。

## 生命周期与调用链

```text
CassandraDaemon.setupVirtualKeyspaces()
  -> VirtualKeyspaceRegistry.register(VirtualSchemaKeyspace.instance)
  -> VirtualKeyspaceRegistry.register(SystemViewsKeyspace.instance)
  -> ClientState.READABLE_SYSTEM_RESOURCES includes VirtualSchemaKeyspace tables

SELECT ... FROM system_virtual_schema.columns
  -> Schema.instance.getKeyspaceMetadataNullable("system_virtual_schema")
  -> VirtualKeyspaceRegistry.getKeyspaceMetadataNullable()
  -> SinglePartitionReadCommand.create() or PartitionRangeReadCommand.create()
  -> metadata.isVirtual() selects VirtualTable*ReadCommand
  -> VirtualKeyspaceRegistry.getTableNullable(metadata.id)
  -> VirtualColumns.select(...)
  -> VirtualColumns.data()
  -> VirtualKeyspaceRegistry.virtualKeyspacesMetadata()
  -> for each TableMetadata / ColumnMetadata emit rows
```

## 场景矩阵

| 场景 ID | 源码合同 | 测试/证据 | 运维含义 |
|---|---|---|---|
| `system_virtual_schema_registration_contract` | `CassandraDaemon.setupVirtualKeyspaces()` 先注册 `VirtualSchemaKeyspace.instance`，再注册 `SystemViewsKeyspace.instance`，见 `src/java/org/apache/cassandra/service/CassandraDaemon.java:534-543`。 | `CQLTester.startServices()` 注册 `VirtualSchemaKeyspace.instance`，见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:633-636`。 | daemon 启动后 virtual schema 可描述自身和 `system_views`；单测环境至少注册 virtual schema。 |
| `system_virtual_schema_keyspaces_contract` | `VirtualKeyspaces.data()` 遍历 `VirtualKeyspaceRegistry.instance.virtualKeyspacesMetadata()` 并输出 keyspace row，见 `VirtualSchemaKeyspace.java:42-62`。 | `DescribeStatementTest.testDescribeVirtualTables()` 覆盖 `DESCRIBE ONLY KEYSPACE system_virtual_schema`，见 `test/unit/org/apache/cassandra/cql3/statements/DescribeStatementTest.java:233-244`。 | `DESCRIBE KEYSPACE` 输出是参考结构，不可作为可重放 DDL。 |
| `system_virtual_schema_tables_contract` | `VirtualTables.data()` 输出 `table.keyspace`、`table.name`、`table.params.comment`，见 `VirtualSchemaKeyspace.java:65-97`。 | `DescribeStatementTest` 覆盖 `DESCRIBE TABLE system_virtual_schema.columns`。 | 新增 virtual table 的 comment 会进入自省结果，运维文档应同步描述读成本。 |
| `system_virtual_schema_columns_schema_contract` | `VirtualColumns` schema 固定为 `keyspace_name`、`table_name`、`column_name`、`clustering_order`、`column_name_bytes`、`kind`、`position`、`type`，见 `VirtualSchemaKeyspace.java:100-125`。 | `DescribeStatementTest` 逐行断言 `VIRTUAL TABLE system_virtual_schema.columns` 的列和 primary key，见 `DescribeStatementTest.java:246-265`。 | 列名/类型变更会影响工具自省兼容性，应有显式 release note。 |
| `system_virtual_schema_columns_projection_contract` | `VirtualColumns.data()` 从 `ColumnMetadata` 投影 `column.name`、`clusteringOrder()`、`column.name.bytes`、`column.kind`、`column.position()` 和 `column.type.asCQL3Type()`，见 `VirtualSchemaKeyspace.java:128-149`。 | 当前测试覆盖 DESCRIBE schema，但没有直接 `SELECT ... FROM system_virtual_schema.columns` 行内容断言。 | 新增 provider 列会自动出现；如果 `ColumnMetadata` 表示方式改变，CQL 自省输出也会变。 |
| `system_virtual_schema_read_single_partition_contract` | `SinglePartitionReadCommand.create()` 在 `metadata.isVirtual()` 时创建 `VirtualTableSinglePartitionReadCommand`，执行时通过 registry 调 `view.select(partitionKey, ...)`，见 `SinglePartitionReadCommand.java:133-147`、`1412-1418`。 | `VirtualTableTest.testReadOperationsOnReadOnlyTable()` 覆盖单分区、multi-partition、paging 和 count；`VirtualTableFromInternodeTest` 覆盖 remote single partition。 | virtual table 单分区读不触发 memtable/SSTable，也没有 repaired tracking。 |
| `system_virtual_schema_read_range_contract` | `PartitionRangeReadCommand.create()` 在 virtual metadata 上创建 `VirtualTablePartitionRangeReadCommand`，执行时调用 `view.select(dataRange, ...)`，见 `PartitionRangeReadCommand.java:98-110`、`552-558`。 | `VirtualTableTest` 覆盖 token range + paging + `ALLOW FILTERING`。 | 对没有覆盖 `data(partitionKey)` 的 provider，range query 会触发 `data()` 全量构造。 |
| `system_virtual_schema_filtering_contract` | `StatementRestrictions.requiresAllowFilteringIfNotSpecified()` 对 virtual table 查询 `VirtualTable.allowFilteringImplicitly()`，见 `StatementRestrictions.java:359-367`。 | `VirtualTableTest.testDisallowedFilteringOnRegularColumn()` / `testAllowedFilteringOnRegularColumn()` 覆盖开启/关闭 implicit filtering。 | provider 可选择强制 `ALLOW FILTERING`，但默认 true；高成本表应考虑覆盖该方法。 |
| `system_virtual_schema_default_read_permission_contract` | `ClientState.READABLE_SYSTEM_RESOURCES` 默认加入 `VirtualSchemaKeyspace.instance.tables()`，见 `ClientState.java:91-93`。 | `GrantAndRevokeTest.testGrantOnVirtualKeyspaces()` 覆盖 virtual keyspace grant/revoke 语法，见 `GrantAndRevokeTest.java:479-487`。 | 普通用户可读 virtual schema 的默认资源，但系统 keyspace 权限仍按 resource chain 校验。 |
| `system_virtual_schema_dml_ddl_guard_contract` | `AbstractVirtualTable.apply()` / `truncate()` 默认抛错；`VirtualMutation.apply()` 只委托 mutable provider；DDL 在 virtual keyspace 上被拒绝。 | `VirtualTableTest.testInvalidDMLOperationsOnReadOnlyTable()` 和 `testInvalidDDLOperationsOnVirtualKeyspaceAndReadOnlyTable()` 覆盖 INSERT/UPDATE/DELETE/TRUNCATE/DDL。 | `system_virtual_schema.columns` 是只读自省面，不应作为控制面。 |
| `system_virtual_schema_internode_read_contract` | `ReadCommandVerbHandler.validateTransientStatus()` 对 virtual metadata 直接 return，见 `ReadCommandVerbHandler.java:139-141`。 | `VirtualTableFromInternodeTest.readCommandAccessVirtualTable*()` 覆盖 internode read command 访问 `system_views.settings`。 | virtual table remote read 不应被 token ownership/transient status 校验误拦。 |
| `system_virtual_schema_select_data_test_gap` | 当前源码合同覆盖行生成，但测试只覆盖 DESCRIBE schema。 | `research/tools/check-system-virtual-schema-drift.py` 对 `SELECT ... system_virtual_schema.columns` 做负向扫描；新增测试后需更新矩阵。 | 建议补 `SELECT keyspace_name, table_name, column_name, kind, type FROM system_virtual_schema.columns WHERE keyspace_name='system_views'` 的 focused test。 |
| `system_virtual_schema_existing_tests_baseline` | `VirtualTableTest`、`DescribeStatementTest`、`VirtualTableFromInternodeTest`、`GrantAndRevokeTest` 共同覆盖 query planner、DESCRIBE、remote read 与权限语法。 | checker 固化这些测试文件 token。 | 这些测试不是完整列内容合同，仍需 drift checker 保持文档与源码同步。 |

## 配置、Metrics、日志

- 配置项：无用户可调配置；keyspace/table 由 daemon/test 注册，入口是 `CassandraDaemon.setupVirtualKeyspaces()` 和 `CQLTester.startServices()`。
- Metrics：无独立 metrics；读成本体现为 provider `data()` 构造开销，不经过 SSTable read metrics。
- 日志：无专属日志；`system_views.system_logs` 的 virtual appender 属于 logging slice，本矩阵只引用 daemon 注册顺序。

## 性能与故障关注

- `VirtualColumns.data()` 当前全量遍历所有 registered virtual keyspaces/tables/columns；如果未来 provider 数量或列数大幅增长，`SELECT * FROM system_virtual_schema.columns` 是 O(virtual columns) 的内存构造。
- 单分区优化依赖 provider 是否覆盖 `data(DecoratedKey)`；`VirtualColumns` 未覆盖，因此即使限制 `keyspace_name` 也先构造全量数据后取分区。
- virtual table 查询绕过普通 storage engine，不能用 flush/compaction/repair 思维排障；应从 provider、registry、CQL restrictions 和权限链排查。
- 行内容测试缺口仍存在：DESCRIBE 能保护 schema shape，但不能保护 `ColumnMetadata` 到 `kind/type/position` 的动态投影语义。
