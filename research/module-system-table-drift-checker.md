# Module: System Table Drift Checker

## 范围

本模块记录 `research/tools/check-system-table-drift.py` 的用途、输入、输出和运维方式。它覆盖 `system`、`system_schema`、`system_traces`、`system_auth` 和 `system_distributed` 的表名 registry 到 research 文档覆盖检查；逐列 CQL 契约由 `research/module-system-table-column-contract.md` 和 `research/tools/check-system-table-column-drift.py` 覆盖。

## 设计目标

- 用源码 registry 作为事实来源，避免新增系统表后只更新 Java metadata 而遗漏 research 矩阵。
- 不编译 Cassandra，只解析 Java 常量和 `ImmutableSet.of(...)` / `ImmutableList.of(...)` 声明，降低运行门槛。
- 对每个 keyspace 绑定目标文档集合，让 `system`、`system_traces`、`system_auth`、`system_schema` 和 `system_distributed` 的 drift 能分别定位。
- 同时覆盖 `SystemKeyspace.TABLE_NAMES`、`TraceKeyspace.TABLE_NAMES`、`AuthKeyspace.TABLE_NAMES`、`SystemDistributedKeyspace.TABLE_NAMES_WITH_AUTO_REPAIR` 和 `SchemaKeyspaceTables.ALL`，对齐源码测试中的 keyspace table name 断言。

## 解决的问题

- `SystemKeyspace.TABLE_NAMES` 和 `TraceKeyspace.TABLE_NAMES` 是 metadata 是否包含表的核心集合；旧研究只人工维护矩阵，新增表时容易漏写，源码入口见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:198-209` 和 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:69-72`。
- `system_distributed` 有 `AUTOREPAIR_ENABLE` 条件表集合，checker 同时解析基础集合和 auto-repair 集合，避免只覆盖默认分支，源码见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:84-117`。
- `system_schema` 的表顺序集中在 `SchemaKeyspaceTables.ALL`，它不是 `SchemaKeyspace` 内部 `TableMetadata` 变量列表；checker 直接读取这个公开列表，见 `src/java/org/apache/cassandra/schema/SchemaKeyspaceTables.java:20-53`。
- 仓库已有 `SystemKeyspaceTablesNamesTest` 校验 Java registry 与 runtime metadata 对齐，但它不检查 research 文档；checker 补上文档侧 drift，测试入口见 `test/unit/org/apache/cassandra/cql3/SystemKeyspaceTablesNamesTest.java:51-88`。

## 设计取舍

- checker 只检查表名覆盖，不尝试解析列定义、TTL、compaction、owner 或生命周期；列名、primary key 和 deprecated column marker 由 column drift checker 维护。
- 文档覆盖采用目标 markdown 文件中的精确表名匹配，能发现完全缺失的新增表，但不能证明该表的 owner/生命周期描述充分。
- `system_distributed` 取基础集合与 auto-repair 集合的并集，因此即使本地 `AUTOREPAIR_ENABLE=false`，研究文档也必须覆盖 auto-repair 表。
- 脚本使用 Python 标准库，避免依赖 Ant、JUnit、Cassandra classpath 或 Guava。

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-system-table-drift.py` | 解析源码 registry 并检查目标 research 文档是否包含每个表名。 |
| `SystemKeyspace` | `system` keyspace 当前与 legacy metadata 表集合来源，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:151-209`。 |
| `TraceKeyspace` | `system_traces.sessions/events` 表集合来源，见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:69-72`。 |
| `AuthKeyspace` | `system_auth` roles/permissions/network/CIDR 表集合来源，见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:56-65`。 |
| `SystemDistributedKeyspace` | `system_distributed` 基础表与 auto-repair 条件表集合来源，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:90-117`。 |
| `SchemaKeyspaceTables` | `system_schema` 表名与 flush/truncate 顺序来源，见 `src/java/org/apache/cassandra/schema/SchemaKeyspaceTables.java:20-53`。 |

## 核心接口

- `extract_registry()`：读取 registry source，抽取字符串常量并解析指定 immutable set/list symbol。
- `find_immutable_args()`：定位 `ImmutableSet.of(...)` 或 `ImmutableList.of(...)` 参数块，避免用简单按行匹配漏掉多行声明。
- `documented()`：对目标文档集合做表名精确匹配。
- 命令行入口：`python3 research/tools/check-system-table-drift.py` 返回 0 表示所有 registry 表名在目标文档中出现；返回 1 表示缺失；返回 2 表示脚本解析或文件读取错误。

## 核心数据结构

| keyspace | registry source | 解析 symbol | 目标文档 |
|---|---|---|---|
| `system` | `src/java/org/apache/cassandra/db/SystemKeyspace.java` | `TABLE_NAMES` | `research/module-system-tables.md`、`research/module-system-tables-core-matrix.md`、`research/module-schema-cql-auth-native-deep-dive.md`、`research/module-startup-bootstrap.md` |
| `system_schema` | `src/java/org/apache/cassandra/schema/SchemaKeyspaceTables.java` | `ALL` | `research/module-system-tables.md`、`research/module-schema-cql-auth-native-deep-dive.md`、`research/module-schema-cql-auth-native-third-round.md` |
| `system_traces` | `src/java/org/apache/cassandra/tracing/TraceKeyspace.java` | `TABLE_NAMES` | `research/module-system-tables.md`、`research/module-system-tables-core-matrix.md`、`research/module-tracing-native-cqlsh.md` |
| `system_auth` | `src/java/org/apache/cassandra/auth/AuthKeyspace.java` | `TABLE_NAMES` | `research/module-system-tables.md`、`research/module-schema-cql-auth-native-deep-dive.md`、`research/module-permission-role-matrix.md` |
| `system_distributed` | `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java` | `TABLE_NAMES`、`TABLE_NAMES_WITH_AUTO_REPAIR` | `research/module-system-tables.md`、`research/module-system-distributed-state-matrix.md`、`research/module-repair-streaming-autorepair-netty.md` |

## 生命周期

本地运行：

```text
developer updates a system table registry
  -> run python3 research/tools/check-system-table-drift.py
  -> script parses registry constants
  -> script scans target research docs
  -> missing table names fail the run
  -> author updates module matrix or explains why the table is intentionally excluded
```

研究维护：

```text
new system table added
  -> update Java metadata and tests
  -> update module-system-tables*.md owner/lifecycle matrix
  -> run drift checker
  -> run markdown link/citation validation
```

## 调用链

```text
main()
  -> check()
     -> extract_registry(registry)
        -> strip_comments()
        -> string_constants()
        -> find_immutable_args()
        -> resolve_args()
     -> read_doc_text(registry.docs)
     -> documented(table, docs_text)
  -> print per-keyspace result
  -> exit 0/1/2
```

## 配置项

- 当前没有外部配置文件；registry 列表写在脚本的 `REGISTRIES` 常量里。
- 需要新增 keyspace 或目标文档时，添加一个 `Registry(...)` 项即可。
- `--json` 输出机器可读结果，便于后续接入 CI 或生成缺口报告。

## Metrics

- checker 不接入 Cassandra runtime metrics。
- 可观测输出是每个 keyspace 的 `OK` / `MISSING` 状态、表名数量和缺失表名列表。
- CI 接入时可把非零退出码作为唯一 gate，把 JSON 输出作为 artifact。

## 日志

- 成功时输出每个 keyspace 的表名数量，并输出 `System table research docs are in sync with parsed table registries.`。
- 缺失时输出 `MISSING <keyspace>` 和缺失表名。
- 解析失败或文件缺失时向 stderr 输出 `ERROR: ...` 并返回 2。

## 运维关注点

- checker 是 research 维护工具，不应替代 `SystemKeyspaceTablesNamesTest`；Java 测试仍负责 registry 与 runtime metadata 的一致性。
- 若新增表是 legacy/pre-flight 名称但不进入当前 `TABLE_NAMES`，需要先确认是否应该纳入文档矩阵；checker 默认只看 metadata registry。
- 对 `system_distributed` 新增条件表时，应同时覆盖 feature flag、writer/reader、清理策略和失败模式，而不是只把表名写入文档。
- 如果文档重命名或拆分，需要同步更新脚本里的目标文档列表。

## 性能瓶颈

- 脚本只读取少量 Java 和 markdown 文件，运行成本主要是文本 IO 与正则匹配。
- 表名匹配是朴素正则扫描，目标文档数量继续增长时仍是低成本；若未来扩展到逐列矩阵，应该改为结构化清单或生成文件。

## 常见故障

- `Could not find ImmutableSet/List declaration`：源码 registry 声明形态变化，需更新 `find_immutable_args()` 的解析规则。
- `unresolved entries`：registry 中出现非字符串常量或表达式，需为该表达式增加显式解析或把 registry 改回常量引用。
- `No research docs matched`：目标文档移动或删除，需更新 `REGISTRIES`。
- `MISSING system...`：新增表尚未进入目标 research 文档；应补对应模块矩阵后重跑。

## 测试用例

- `python3 research/tools/check-system-table-drift.py`：本地 source-only drift check，当前应返回 0。
- `python3 research/tools/check-system-table-drift.py --json`：输出每个 keyspace 的 registry、目标文档、表名和缺失列表。
- `python3 research/tools/check-system-table-column-drift.py`：配套列契约 drift check，覆盖源码 CQL `CREATE TABLE` 中的列和主键。
- `SystemKeyspaceTablesNamesTest`：Java 层校验 `system`、`system_schema`、`system_traces`、`system_auth` 和 `system_distributed` metadata table names，见 `test/unit/org/apache/cassandra/cql3/SystemKeyspaceTablesNamesTest.java:51-88`。

## 待补项

- 将 checker 接入 CI 或 pre-commit，并保留 JSON artifact。
- 列级 drift 已由 `research/tools/check-system-table-column-drift.py` 覆盖；后续若要扩展，应优先补类型、TTL、compaction/table params，而不是扩展表名正则。
