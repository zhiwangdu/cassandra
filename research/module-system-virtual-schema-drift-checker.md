# System Virtual Schema Drift Checker

`research/tools/check-system-virtual-schema-drift.py` 保护 `system_virtual_schema.columns` 研究矩阵和源码/测试事实一致。它关注 virtual schema provider、CQL read command dispatch、filtering/permission/DML guard、DESCRIBE baseline 与直接 SELECT 行内容测试缺口。

## 覆盖范围

- Source：`VirtualSchemaKeyspace`、`VirtualKeyspaceRegistry`、`VirtualKeyspace`、`VirtualTable`、`AbstractVirtualTable`、`SinglePartitionReadCommand`、`PartitionRangeReadCommand`、`StatementRestrictions`、`CassandraDaemon`、`ClientState`、`ReadCommandVerbHandler`、`VirtualMutation`。
- Tests：`VirtualTableTest`、`DescribeStatementTest`、`VirtualTableFromInternodeTest`、`CQLTester`、`GrantAndRevokeTest`。
- Docs：`module-system-virtual-schema-columns-matrix.md`、本说明、`README.md`、`notes/source-map.md`。

## 场景 ID

- `system_virtual_schema_registration_contract`
- `system_virtual_schema_keyspaces_contract`
- `system_virtual_schema_tables_contract`
- `system_virtual_schema_columns_schema_contract`
- `system_virtual_schema_columns_projection_contract`
- `system_virtual_schema_columns_self_row_content_contract`
- `system_virtual_schema_read_single_partition_contract`
- `system_virtual_schema_read_range_contract`
- `system_virtual_schema_filtering_contract`
- `system_virtual_schema_default_read_permission_contract`
- `system_virtual_schema_dml_ddl_guard_contract`
- `system_virtual_schema_internode_read_contract`
- `system_virtual_schema_select_data_test_gap`
- `system_virtual_schema_existing_tests_baseline`

## 检查逻辑

1. Source token checks：确认 virtual schema 三表、`columns` 列定义、`ColumnMetadata` kind/position/clustering-order 语义、`ColumnMetadata` 投影、registry registration/replacement、single/range read command dispatch、filtering gate、默认可读权限和 virtual mutation guard 仍存在。
2. Test token checks：确认当前测试仍覆盖 virtual table read/paging/DML/DDL/implicit filtering、`system_virtual_schema.columns` DESCRIBE、internode virtual read 和 virtual keyspace grant/revoke。
3. Gap check：扫描 `test/unit` 与 `test/distributed`，如果出现 `SELECT ... system_virtual_schema.columns` 行内容测试，会让 checker 失败，提醒更新矩阵并关闭 `system_virtual_schema_select_data_test_gap`。
4. Doc checks：确认矩阵和 drift checker 文档包含全部场景 ID、核心文件名与 checker 名。

## 运行方式

```bash
python3 research/tools/check-system-virtual-schema-drift.py
python3 research/tools/check-system-virtual-schema-drift.py --json
```

通过时输出：

```text
OK system virtual schema drift checks passed (... source files, ... test files, ... docs, ... scenarios)
```

## 维护规则

- 修改 `VirtualSchemaKeyspace.VirtualColumns` 的列名、primary key、regular columns 或 `ColumnMetadata` 投影时，同步更新矩阵和 checker token。
- 修改 `ColumnMetadata.Kind`、`ClusteringOrder` 或 `NO_POSITION` 语义时，同步更新 `system_virtual_schema_columns_self_row_content_contract`。
- 新增直接 SELECT `system_virtual_schema.columns` 的测试后，把负向 gap 改为已覆盖场景，并更新文档中的测试证据。
- 新增高成本 virtual table provider 时，优先评估是否覆盖 `data(DecoratedKey)` 或 `allowFilteringImplicitly()`；本 checker 保护入口合同，不替代每张 provider 的性能分析。
