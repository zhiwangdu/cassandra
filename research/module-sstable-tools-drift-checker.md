# Module: SSTable Tools Drift Checker

## 范围

本模块记录 `research/tools/check-sstable-tools-runbook-drift.py` 的用途、输入、输出和维护方式。它覆盖 `bin/sstable*` 与 `tools/bin/sstable*` wrapper 到 `research/module-sstable-tools-safety-runbook.md` 的工具名、Java main class 和源码存在性检查。`sstableloader` 明确排除，因为 safety runbook 不覆盖 bulk loader；bulk loader 仍属于 streaming/bulk-load 运维工具范畴。

## 设计目标

- 用实际发布 wrapper 作为 standalone SSTable 工具清单事实来源，避免新增 wrapper 后 runbook 漏写。
- 解析 wrapper 内的 `org.apache.cassandra.tools.*` main class，确认对应 `src/java/...` 文件存在，并确认 runbook 同时提到 wrapper tool name 和 Java class。
- 显式记录 out-of-scope wrapper，避免 checker 因 `sstableloader` 漂移而把 runbook scope 扩大到 bulk loader。
- 不启动 Cassandra、不执行工具、不依赖 Ant classpath，只读取 shell wrapper、Java source 和 research markdown。

## 解决的问题

- Cassandra 的 SSTable 工具分布在 `bin` 与 `tools/bin` 两个 wrapper 目录。`bin` 提供 `sstablescrub`、`sstableupgrade`、`sstableutil`、`sstableverify` 和 out-of-scope `sstableloader`，`tools/bin` 提供 dump/metadata/partitions/split/repaired/level/relevel/expired-blockers 等附加工具，wrapper 入口见 `bin/sstableverify:44-47`、`tools/bin/sstabledump:44-47`。
- runbook 还需要覆盖 Java main class 的安全语义，而不是只列 shell 名称；core wrapper 分别指向 `StandaloneVerifier`、`StandaloneScrubber`、`StandaloneUpgrader` 和 `StandaloneSSTableUtil`，见 `src/java/org/apache/cassandra/tools/StandaloneVerifier.java:57-70`、`src/java/org/apache/cassandra/tools/StandaloneScrubber.java:61-82`、`src/java/org/apache/cassandra/tools/StandaloneUpgrader.java:50-57`、`src/java/org/apache/cassandra/tools/StandaloneSSTableUtil.java:34-44`。
- 旧 runbook 的待补项要求从 wrapper 和 main class 导出风险矩阵；本 checker 先把 wrapper-to-runbook 覆盖做成可运行 gate，风险字段仍由 `research/module-sstable-tools-safety-runbook.md` 维护。

## 设计取舍

- checker 只检查 wrapper 名称、main class 名称和 main class source 是否覆盖，不证明每个工具的所有 option 都有风险说明。
- `sstableloader` 用 `EXPECTED_EXCLUDED_WRAPPERS` 显式排除，而不是静默跳过；如果 wrapper 移动或消失，checker 会报告 stale exclusion。
- wrapper parser 只识别 `org.apache.cassandra.tools.*` main class；若未来 wrapper 改用 helper launcher 或 nested class，需要更新解析规则。
- 对 runbook 的覆盖检查使用精确 symbol regex，避免 `sstablemetadata` 这类名称作为更长词子串时误判。

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-sstable-tools-runbook-drift.py` | 解析 SSTable wrapper，检查 Java main class 存在和 runbook 覆盖。 |
| `StandaloneVerifier` | `sstableverify` main class，默认要求 `--force`，见 `src/java/org/apache/cassandra/tools/StandaloneVerifier.java:57-85`。 |
| `StandaloneScrubber` | `sstablescrub` main class，执行 scrub/manifest/header 相关逻辑，见 `src/java/org/apache/cassandra/tools/StandaloneScrubber.java:61-88`。 |
| `StandaloneUpgrader` | `sstableupgrade` main class，执行 offline upgrade，见 `src/java/org/apache/cassandra/tools/StandaloneUpgrader.java:50-65`。 |
| `StandaloneSSTableUtil` | `sstableutil` main class，列出 SSTable files 或 cleanup leftovers，见 `src/java/org/apache/cassandra/tools/StandaloneSSTableUtil.java:34-52`。 |
| `SSTableExport` / `SSTableMetadataViewer` / `SSTablePartitions` | `tools/bin` 中 dump/metadata/partitions wrapper 的 main classes，见 `tools/bin/sstabledump:44-47`、`tools/bin/sstablemetadata:44-47`、`tools/bin/sstablepartitions:44-47`。 |

## 核心接口

- `wrappers()`：扫描 `bin` 和 `tools/bin` 下的 `sstable*` 文件，解析 included/excluded wrapper 列表。
- `parse_wrapper()`：从 shell wrapper 中抽取 `org.apache.cassandra.tools.*` main class，并映射到 `src/java/...` source path。
- `documented()`：对 safety runbook 做 tool name 和 simple class name 精确匹配。
- `check()`：生成 missing source、missing tool name、missing class、stale exclusion 和 unexpected exclusion 列表。
- 命令行入口：`python3 research/tools/check-sstable-tools-runbook-drift.py` 返回 0 表示同步；返回 1 表示 runbook drift；返回 2 表示解析或文件读取错误。

## 核心数据结构

| 数据结构 | 字段 | 语义 |
|---|---|---|
| `ToolWrapper` | `tool` | wrapper 文件名，例如 `sstableverify`。 |
| `ToolWrapper` | `wrapper` | wrapper 相对路径，例如 `bin/sstableverify`。 |
| `ToolWrapper` | `class_ref` | wrapper 调用的 Java main class FQCN。 |
| `ToolWrapper` | `source` | main class 对应 `src/java` source path。 |
| `EXPECTED_EXCLUDED_WRAPPERS` | path -> reason | out-of-scope wrapper 的显式排除契约。 |

## 生命周期

本地运行：

```text
developer adds or changes bin/sstable* or tools/bin/sstable* wrapper
  -> run python3 research/tools/check-sstable-tools-runbook-drift.py
  -> script resolves wrapper main classes
  -> script checks source files and runbook coverage
  -> missing tool/class fails the run
```

研究维护：

```text
new standalone SSTable wrapper added
  -> add wrapper and Java main class
  -> update module-sstable-tools-safety-runbook.md tool row, risk notes, options and tests
  -> run SSTable tools drift checker
  -> run research markdown/citation validation
```

## 调用链

```text
main()
  -> check()
     -> wrappers()
        -> parse_wrapper()
           -> java_source_for(class_ref)
     -> documented(tool, runbook_text)
     -> documented(simple_class(class_ref), runbook_text)
  -> print counts and drift details
  -> exit 0/1/2
```

## 配置项

- 当前没有外部配置文件；`WRAPPER_DIRS`、`RUNBOOK_DOC` 和 `EXPECTED_EXCLUDED_WRAPPERS` 写在脚本顶部。
- `--json` 输出 machine-readable wrapper/main-class coverage，适合后续接入 CI 或生成 runbook drift artifact。
- 如果 safety runbook 拆分到多个文件，应把 `RUNBOOK_DOC` 扩展为文档列表并拼接扫描。

## Metrics

- checker 不接入 Cassandra runtime metrics。
- 可观测输出是 included wrapper 数、excluded wrapper 数，以及缺失 source、tool name、class name 或 stale exclusion 明细。
- 当前基线应解析 12 个 included SSTable wrapper，并追踪 1 个 out-of-scope wrapper。

## 日志

- 成功时输出 `OK SSTable tool wrappers`、`OK SSTable tool exclusions` 和同步确认。
- drift 时输出缺失 wrapper tool name、Java main class、source path 或 stale exclusion。
- 解析失败时向 stderr 输出 `ERROR: ...` 并返回 2。

## 运维关注点

- checker 是 runbook 维护工具，不替代 `StandaloneVerifierTest`、`StandaloneScrubberTest`、`SSTableMetadataViewerTest` 等真实 CLI 行为测试。
- 新增 wrapper 进入 runbook 时不能只列名称，还应补是否只读、是否需要 Cassandra 停止、是否 snapshot、是否会 rewrite/mutate metadata、关键 options 和测试覆盖。
- `sstableloader` 排除只针对本 safety runbook；bulk loader 仍应在 streaming/ops 文档中覆盖。
- 如果 packaging 目录新增 sstable wrapper 但不在 `bin` 或 `tools/bin`，需要先判断是否属于发布入口，再扩展 `WRAPPER_DIRS`。

## 性能瓶颈

- 脚本只读取少量 shell wrapper、一个 markdown 文档和 main class source path，运行成本主要是文本 IO 与正则匹配。
- 如果后续扩展到 option-level drift check，需要解析 Apache Commons CLI declarations，false positive 风险会比 wrapper/class coverage 更高。

## 常见故障

- `Could not find org.apache.cassandra.tools main class`：wrapper launcher 格式变化，需要更新 `parse_wrapper()`。
- `Wrappers whose Java main class source is missing`：wrapper 指向不存在或移动的 class，需修复 wrapper 或 checker mapping。
- `Wrapper tool names missing from runbook`：新增发布 wrapper 未进入 safety runbook。
- `Wrapper Java main classes missing from runbook`：runbook 只提到 CLI 名称，未覆盖对应 Java implementation。
- `Expected excluded wrappers no longer exist`：`sstableloader` 路径变化或被移除，需要更新 `EXPECTED_EXCLUDED_WRAPPERS`。

## 测试用例

- `python3 research/tools/check-sstable-tools-runbook-drift.py`：本地 source-only drift check，当前应返回 0。
- `python3 research/tools/check-sstable-tools-runbook-drift.py --json`：输出 wrapper、tool name、main class、source path 和排除原因。
- `StandaloneVerifierTest`、`StandaloneScrubberTest`、`StandaloneSplitterTest`、`StandaloneSSTableUtilTest` 覆盖 key standalone tools 的 help/options/error behavior，见 `research/module-sstable-tools-safety-runbook.md`。
- `SSTableExportTest`、`SSTableMetadataViewerTest`、`SSTablePartitionsTest`、`SSTableExpiredBlockersTest`、`SSTableOfflineRelevelTest` 覆盖 `tools/bin` 对应 Java main class 行为，测试索引见 `research/notes/source-map.md`。

## 待补项

- 将 checker 接入 CI 或 pre-commit，并保留 JSON artifact。
- 扩展到 Commons CLI option-level drift check，确保新增高风险选项进入 runbook。
