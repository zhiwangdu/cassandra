# Module: System Table Column Drift Checker

## 范围

本模块记录 `research/tools/check-system-table-column-drift.py` 的用途、输入、输出和维护方式。它从 Cassandra 源码里的 system table CQL 字符串抽取列契约，并校验 `research/module-system-table-column-contract.md` 的逐表 section 是否同步。

覆盖范围包括：

- `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- `src/java/org/apache/cassandra/schema/SchemaKeyspace.java`
- `src/java/org/apache/cassandra/schema/SchemaKeyspaceTables.java`
- `src/java/org/apache/cassandra/tracing/TraceKeyspace.java`
- `src/java/org/apache/cassandra/auth/AuthKeyspace.java`
- `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java`

## 设计目标

- 从 `parse(..., "CREATE TABLE %s ...")` 的源码 CQL 字符串导出列名和 primary key，不依赖 Cassandra 编译、Ant、JUnit 或运行中 schema dump。
- 为 `SchemaKeyspace` 额外加载 `SchemaKeyspaceTables` 常量，覆盖 `system_schema` 的 11 张 normalized schema 表。
- 解析 `static final String` 常量，覆盖 `AuthKeyspace` 中用常量拼接的 CIDR 表列名。
- 解析当前源码中的 optional Java string fragment，采用 `AUTOREPAIR_ENABLE ? "auto_repair ..." : ""` 的 true 分支来记录最大源码 ABI。
- 捕获 `recordDeprecatedSystemColumn(...)`，目前用于 `system.local.thrift_version` 的 deprecated column marker。
- 用 scenario id 绑定 contract section，让新增表、新增列、删除列、主键变化和 deprecated marker 变化都能返回非零退出码。

## 解决的问题

- 原有 `check-system-table-drift.py` 只检查 table registry 覆盖，不能发现 `system.peers_v2.native_port`、`system_distributed.repair_history.participants_v2` 或 `system_auth.cidr_groups.cidrs` 这类列级 ABI 变化。
- `system_schema.tables` 和 `system_schema.views` 保留 driver 兼容列并新增 feature-flag optional `auto_repair`，这类列变化需要和普通 system tables 使用同一个 source-only gate。
- system table 列经常被 driver、cqlsh、nodetool、repair/autorepair tooling 和运维 runbook 直接依赖；只靠人工矩阵容易漏掉 mixed-version 兼容列。
- `system_distributed` auto-repair 表受 `AUTOREPAIR_ENABLE` 影响，但源码 CQL 定义仍应纳入研究契约，避免 feature flag 关闭环境漏掉文档。

## 设计取舍

- checker 不执行 Cassandra，也不解析完整 Java AST；它只实现足够覆盖当前源码形态的 Java string 拼接和 top-level argument splitter。
- 只校验列名、primary key 和 deprecated column marker，不校验类型、TTL、compaction 或 table params；类型/owner/lifecycle 仍由模块文档解释。
- `system_schema` 的 optional `auto_repair` 列按源码最大 ABI 记录；禁用 auto-repair 的运行环境可能没有该列，但研究文档必须覆盖启用分支。
- contract doc 采用固定 heading 形态 `### \`keyspace.table\` (\`scenario_id\`)`，这是脚本解析 markdown 的稳定边界。

## 核心接口

| 函数 | 作用 |
|---|---|
| `extract_contracts()` | 读取一个 Java source spec，解析所有裸 `parse(...)` 调用并抽取 CQL contract。 |
| `eval_java_string_expr()` | 解析 Java string literal 与 `static final String` 常量拼接。 |
| `parse_create_table()` | 从 CQL body 中提取 column names 和 normalized primary key。 |
| `deprecated_columns_after_call()` | 扫描 parse call 后续 builder chain 中的 `recordDeprecatedSystemColumn`。 |
| `parse_contract_doc()` | 读取 `module-system-table-column-contract.md` 的 scenario section。 |
| `compare_contracts()` | 对比源码 contract 与 markdown contract，生成 drift 结果。 |

## 核心数据结构

| 数据结构 | 字段 |
|---|---|
| `SourceSpec` | `keyspace`、`source`、`constant_sources` |
| `TableContract` | `keyspace`、`table`、`source`、`columns`、`primary_key`、`deprecated_columns` |

scenario id 由 `TableContract.scenario_id` 生成，格式为 `system_table_column_<keyspace>_<table>`，非字母数字字符规范化为 `_`。例如 `system_auth.resource_role_permissons_index` 对应 `system_table_column_system_auth_resource_role_permissons_index`。

## 调用链

```text
main()
  -> extract_all_contracts()
     -> extract_contracts()
        -> strip_comments()
        -> string_constants()
        -> load constant_sources
        -> find_matching()
        -> split_top_level()
        -> eval_java_string_expr()
        -> eval_java_conditional_string()
        -> parse_create_table()
        -> deprecated_columns_after_call()
  -> parse_contract_doc()
  -> compare_contracts()
  -> print OK/MISMATCH per keyspace
```

## 命令

```bash
python3 research/tools/check-system-table-column-drift.py
python3 research/tools/check-system-table-column-drift.py --json
python3 research/tools/check-system-table-column-drift.py --dump-markdown
```

`--dump-markdown` 输出从源码重新解析出的 section，可用于 review 列变化，但不直接写文件。

## 运维关注点

- 新增 system table 或 system_schema column 时，应先更新源码和 Java 测试，再补 `module-system-table-column-contract.md` section，最后运行本 checker 和 `check-system-table-drift.py`。
- 如果源码从 CQL string 改成 builder API，脚本会返回解析错误或缺失 section；应改进 parser，而不是在 contract 文档里手动绕过。
- 若文档 section 的列顺序与源码不一致，checker 会失败；列顺序也是 driver/tooling 语义审查的一部分。

## 测试用例

- `python3 research/tools/check-system-table-column-drift.py`：本地 source-only column contract check，当前应返回 0。
- `python3 research/tools/check-system-table-column-drift.py --json`：输出每张表的源码列契约和 mismatch 列表。
- `python3 research/tools/check-system-table-drift.py`：配套 table registry drift check，防止新增表名缺失。
