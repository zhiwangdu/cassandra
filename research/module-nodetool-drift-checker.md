# Module: Nodetool Runbook Drift Checker

## 范围

本模块记录 `research/tools/check-nodetool-runbook-drift.py` 的用途、输入、输出和维护方式。它覆盖 `NodeTool.execute()` 注册的 147 个顶层命令，以及 `bootstrap`、`repair_admin` Airline command group 的子命令到 `research/module-observability-runbook-virtual-schema.md` 的覆盖检查。命令行为、MBean 调用和运维风险仍以 `research/module-observability-runbook-virtual-schema.md`、`research/module-observability-mapping.md` 和 `research/flow-ops-tools.md` 为主；逐命令 `@Option` / `@Arguments` 风险覆盖见 `research/module-nodetool-option-risk-matrix.md` 和 `research/tools/check-nodetool-option-risk-drift.py`。

## 设计目标

- 用 `NodeTool.execute()` 的 command registry 作为 nodetool 命令清单事实来源，避免新增命令后 runbook 漏写。
- 用 `@Command(name = "...")` 解析真实 CLI 命令名，避免从 Java 类名错误推断 `reloadssl`、`upgradesstables`、`rebuild_index`、`recompress_sstables` 等特殊名称。
- 同时检查顶层命令和 command group，确保 `bootstrap resume` 与 `repair_admin list/cancel/cleanup/summarize-*` 也进入 runbook。
- 不启动 Cassandra、不连接 JMX、不依赖 Ant/JUnit/Airline classpath，只读取源码和 research markdown。

## 解决的问题

- `NodeTool.execute()` 集中注册 147 个顶层命令，并追加 `bootstrap`、`repair_admin` group；旧 runbook 手工维护命令分组，新增命令容易漏掉，registry 入口见 `src/java/org/apache/cassandra/tools/NodeTool.java:98-267`。
- CLI 名称来自 `@Command` annotation，而不是类名；例如 `ReloadSslCertificates` 的命令名是 `reloadssl`，`UpgradeSSTable` 是 `upgradesstables`，见 `src/java/org/apache/cassandra/tools/ReloadSslCertificates.java:24-25` 和 `src/java/org/apache/cassandra/tools/nodetool/UpgradeSSTable.java:33`。
- `repair_admin` 子命令是 `RepairAdmin` 的 nested class，命令名分别是 `list`、`cancel`、`cleanup`、`summarize-pending`、`summarize-repaired`，见 `src/java/org/apache/cassandra/tools/nodetool/RepairAdmin.java:48-273`。
- `CassHelp` 是 nodetool default/help command，不使用普通 `@Command` annotation；checker 显式把 `CassHelp.class` 映射为 `help`，源码位置见 `src/java/org/apache/cassandra/tools/NodeTool.java:335-342`。

## 设计取舍

- checker 只检查命令名是否在 runbook 文档出现，不证明每个命令的 MBean 方法、选项和风险描述完整；option/argument 由 `check-nodetool-option-risk-drift.py` 单独保护。
- 对 command group 使用完整字符串检查，例如 `repair_admin summarize-pending`，避免顶层命令名或普通词语误判 group 子命令已覆盖。
- parser 使用源码文本正则而不是 Java parser；优点是轻量，代价是如果 `NodeTool.execute()` registry 结构大改，需要同步更新脚本。
- `@Command` annotation 扫描范围限定在 `src/java/org/apache/cassandra/tools`，因为 nodetool 顶层命令和 group 子命令都在该目录或其 `nodetool` 子包。

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-nodetool-runbook-drift.py` | 解析 nodetool registry、解析 `@Command` 名称、检查 runbook 覆盖并输出 drift。 |
| `NodeTool` | nodetool CLI parser、顶层 command registry 和 command group 构建入口，见 `src/java/org/apache/cassandra/tools/NodeTool.java:73-267`。 |
| `NodeTool.CassHelp` | nodetool help/default command，见 `src/java/org/apache/cassandra/tools/NodeTool.java:335-342`。 |
| `BootstrapResume` | `bootstrap resume` group 子命令，见 `src/java/org/apache/cassandra/tools/nodetool/BootstrapResume.java:31`。 |
| `RepairAdmin` | `repair_admin` group 子命令集合，见 `src/java/org/apache/cassandra/tools/nodetool/RepairAdmin.java:48-273`。 |
| `GuardrailsConfigCommand` | nested `GetGuardrailsConfig` / `SetGuardrailsConfig` 命令示例，证明 checker 需要支持 nested class annotation，见 `src/java/org/apache/cassandra/tools/nodetool/GuardrailsConfigCommand.java:55-172`。 |

## 核心接口

- `top_level_command_classes()`：从 `NodeTool.execute()` 的 `newArrayList(...)` registry 中提取顶层 command class refs。
- `grouped_command_classes()`：从 `builder.withGroup("...").withCommand(...)` block 中提取 group 子命令。
- `command_annotations()`：扫描 `src/java/org/apache/cassandra/tools/**/*.java` 的 `@Command(name = "...")` annotation，建立 simple class name 到 CLI command name 的映射。
- `resolve_class()`：把 registry class ref 解析成 CLI 命令名；`CassHelp` 显式映射到 `help`。
- `documented()`：对 runbook 文本做命令名精确匹配。

## 核心数据结构

| 数据结构 | 字段 | 语义 |
|---|---|---|
| `CommandEntry` | `kind` | `top-level` 或 `group`。 |
| `CommandEntry` | `class_ref` | `NodeTool.execute()` registry 中的 class ref，例如 `RepairAdmin.ListCmd`。 |
| `CommandEntry` | `command` | 真实 runbook 应覆盖的 CLI 名称；group 子命令使用 `group command` 形式。 |
| `CommandEntry` | `source` | 提供 `@Command` annotation 的 Java source path。 |
| JSON result | `top_level_count` / `grouped_count` | 当前解析到的顶层命令数与 group 子命令数。 |
| JSON result | `missing_top_level` / `missing_grouped` | runbook 未覆盖的命令条目。 |

## 生命周期

本地运行：

```text
developer changes nodetool command registry or @Command annotation
  -> run python3 research/tools/check-nodetool-runbook-drift.py
  -> script parses NodeTool top-level registry and groups
  -> script resolves @Command names
  -> script scans module-observability-runbook-virtual-schema.md
  -> missing commands fail the run
```

研究维护：

```text
new nodetool command added
  -> add Java command class and NodeTool registry entry
  -> update runbook command group and risk notes
  -> run nodetool drift checker
  -> run research markdown/citation validation
```

## 调用链

```text
main()
  -> check()
     -> registered_commands()
        -> top_level_command_classes()
        -> grouped_command_classes()
        -> command_annotations()
        -> resolve_class()
     -> documented(command, runbook_text)
  -> print counts and missing commands
  -> exit 0/1/2
```

## 配置项

- 当前没有外部配置；脚本顶部固定 `NODETOOL_SOURCE`、`COMMAND_SOURCE_ROOT` 和 `RUNBOOK_DOC`。
- `--json` 输出机器可读结果，适合后续接入 CI 或生成 runbook drift artifact。
- 如果 runbook 拆分到多个文档，应把 `RUNBOOK_DOC` 扩展为文档列表并拼接扫描。

## Metrics

- checker 不接入 Cassandra runtime metrics。
- 可观测输出是顶层命令数、group 子命令数、缺失顶层命令和缺失 group 命令。
- 当前基线应解析到 147 个顶层命令和 6 个 group 子命令；6 个 group entries 包含 `bootstrap resume` 和 5 个 `repair_admin` 子命令。

## 日志

- 成功时输出 `OK nodetool top-level registry`、`OK nodetool groups` 和 `Nodetool runbook is in sync with parsed command registries.`。
- drift 时输出缺失命令、registry class ref 和 annotation source。
- 解析失败、annotation 缺失或文件读取失败时向 stderr 输出 `ERROR: ...` 并返回 2。

## 运维关注点

- checker 是 runbook 维护工具，不替代 `NodeToolCommandTest`、distributed `NodeToolTest` 或真实 JMX 兼容性测试。
- 新增命令进入 runbook 时不能只列命令名，还应补目标 MBean/子系统、读写风险、性能影响和常见失败模式。
- 如果 command group 增加默认命令或 alias，checker 可能需要扩展解析逻辑。
- 在 secure deployment 中，runbook 还需结合 JMX auth/permission 文档；checker 只解决命令覆盖 drift。

## 性能瓶颈

- 脚本只读取 `NodeTool.java`、tools Java sources 和一个 markdown 文档，运行成本主要是文本 IO 和正则匹配。
- 逐命令 option/argument drift check 已拆到 `check-nodetool-option-risk-drift.py`，本 checker 保持 command registry 级别，避免输出混杂。

## 常见故障

- `Could not find NodeTool top-level newArrayList command registry`：`NodeTool.execute()` registry 结构变化，需要更新 `top_level_command_classes()`。
- `Could not resolve @Command annotation`：新增命令没有 annotation、annotation 不在扫描目录，或 command class 不按当前源码结构声明。
- `Missing top-level commands from runbook`：顶层命令已注册但 runbook 未列出真实 CLI 名称。
- `Missing grouped commands from runbook`：command group 子命令没有以 `group command` 形式进入 runbook。

## 测试用例

- `python3 research/tools/check-nodetool-runbook-drift.py`：本地 source-only drift check，当前应返回 0。
- `python3 research/tools/check-nodetool-runbook-drift.py --json`：输出命令 registry、annotation source 和缺失命令列表。
- `NodeToolCommandTest` 覆盖 nodetool command execution helper 和代表性命令输出，见 `test/unit/org/apache/cassandra/tools/NodeToolCommandTest.java:38-77`。
- `NodeToolTest` 覆盖 in-JVM distributed nodetool 场景，见 `test/distributed/org/apache/cassandra/distributed/test/NodeToolTest.java:55-145`。
- `JMXCompatibilityTest` 与 `JMXGetterCheckTest` 覆盖 JMX 兼容性与 getter 可读性，见 `test/unit/org/apache/cassandra/tools/JMXCompatibilityTest.java:99-140` 和 `test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java:63-94`。

## 待补项

- 将 command registry checker 和 option/argument risk checker 一起接入 CI 或 pre-commit，并保留 JSON artifact。
