# Module: JMX Compatibility Drift Checker

## 范围

`research/tools/check-jmx-compatibility-drift.py` 是 source-only drift check，用来保护 JMX compatibility dump matrix 的源码、测试、gold dump 和文档同步。它不启动 Cassandra、不连接 JMX，也不执行 Java tests；运行时证据仍来自 `JMXCompatibilityTest`、`JMXGetterCheckTest`、`JMXFeatureTest` 和 `JMXStandardsTest`。

当前基线：

- 4 个 gold dump 文件：3.0、3.11、4.0、4.1。
- dump ObjectName rows：3855、4493、7426、7426。
- dump attribute rows：18062、21006、42633、42633。
- dump operation rows：5624、6642、11106、11106。
- `JMXCompatibilityTest` 必须引用 4 个 dump，并使用 `--ignore-missing-on-left`。
- `JMXTool` 必须保留 dump/diff/options、package scan、Info/Attribute/Operation metadata model 和 diff set semantics。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `jmx_compat_dump_gold_files` | `test/data/jmxdump` 下历史 dump 文件集、ObjectName/attribute/operation row count 和关键 ObjectName token。 |
| `jmx_compat_diff_direction` | `JMXCompatibilityTest` 的 old-vs-current diff 方向和 `--ignore-missing-on-left` 语义。 |
| `jmx_compat_exclusion_contract` | 历史兼容破坏/BTI 差异的 exclude object/attribute/operation token。 |
| `jmx_compat_dump_generation_workload` | JMX server、GC/native access、CQL table、native insert/select 和 jmxtool dump 触发路径。 |
| `jmx_tool_dump_model` | `JMXTool.METRIC_PACKAGES`、`queryNames`、`getMBeanInfo`、YAML/JSON dump model。 |
| `jmx_tool_diff_semantics` | object/attribute/operation set diff、ignore missing、exclude pattern、similar operation 输出。 |
| `jmx_standards_mbean_type_gate` | `JMXStandardsTest` 的 MBean interface/type allowlist gate 和 `@BreaksJMX` 降级边界。 |
| `jmx_getter_runtime_surface` | `JMXGetterCheckTest` 的 runtime getter/zero-arg operation 遍历和 ignore sets。 |
| `jmx_distributed_isolated_server` | `IsolatedJmx` / `JMXFeatureTest` 的多 instance JMX server、default domain 和 cleanup 语义。 |
| `jmx_compatibility_ci_gap` | source-only checker 与真实 Java JMX tests 的证据边界。 |

## Source Contract

Gold dump 文件必须保持：

| 文件 | ObjectName rows | Attribute rows | Operation rows |
|---|---:|---:|---:|
| `test/data/jmxdump/cassandra-3.0-jmx.yaml` | 3855 | 18062 | 5624 |
| `test/data/jmxdump/cassandra-3.11-jmx.yaml` | 4493 | 21006 | 6642 |
| `test/data/jmxdump/cassandra-4.0-jmx.yaml` | 7426 | 42633 | 11106 |
| `test/data/jmxdump/cassandra-4.1-jmx.yaml` | 7426 | 42633 | 11106 |

关键源码/测试必须包含：

- `JMXCompatibilityTest`: `tools/bin/jmxtool dump -f yaml`、`tools/bin/jmxtool diff`、`--ignore-missing-on-left`、4 个历史 dump path、CASSANDRA-11115/13910/15939/17056/18313/18959 排除项。
- `JMXTool`: `METRIC_PACKAGES`、dump/diff commands、`--exclude-object`、`--exclude-attribute`、`--exclude-operation`、`DiffResult<Attribute>`、`DiffResult<Operation>`、`Info.from(info)`、`normalizeType`。
- `JMXStandardsTest`: `ALLOWED_TYPES`、`DANGEROUS_TYPES`、`Pattern.compile(".*MBean$")`、`BreaksJMX`。
- `JMXGetterCheckTest`: `IGNORE_ATTRIBUTES`、`IGNORE_OPERATIONS`、`queryNames(null, null)`、`getAttribute`、zero-arg `invoke`。
- `JMXFeatureTest` / `IsolatedJmx`: multi instance provisioning、default domain、`InstanceMBeanWrapper`、RMI endpoint cleanup。

## 设计目标

- 在不运行 Cassandra 的情况下，让历史 dump 文件、compatibility test、JMXTool semantics 和 research docs 的漂移显性化。
- 把 dump 文件数量/规模当作版本化源码资产保护，避免 gold dump 被误删、误改或重生成后未更新研究资料。
- 明确 source-only checker 不能替代 runtime JMX tests。

## 解决的问题

- 仅靠 `module-jmx-nodeprobe-fd-drift-checker.md` 无法证明历史 JMX ObjectName/attribute/operation 兼容面仍被维护。
- JMX exclude list 是升级兼容债务；checker 让修改排除项必须同步文档。
- `JMXTool` diff equality 的细节不直观，尤其是 attribute access 不参与 equality、operation similar signature 输出；checker 保护这些源码 token。

## 设计取舍

- 不完整解析 YAML value，只用文本级 row count 和关键 ObjectName token 保护 dump 文件。完整 diff 要靠 Java `JMXCompatibilityTest`。
- 不连接 JMX，也不尝试运行 `tools/bin/jmxtool`；这样 checker 可在普通源码 checkout 快速运行。
- 对测试源码采用 token contract，而不是 Java AST；测试结构大改时 checker 会失败并要求人工复核。

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-jmx-compatibility-drift.py` | source-only drift checker。 |
| `JMXCompatibilityTest` | 当前 dump 生成和历史 gold dump diff。 |
| `JMXTool` | dump/diff CLI、metadata model 和 diff implementation。 |
| `JMXStandardsTest` | MBean interface/type compatibility gate。 |
| `JMXGetterCheckTest` | runtime getter/zero-arg operation smoke。 |
| `JMXFeatureTest` / `IsolatedJmx` | distributed JMX server isolation and cleanup evidence。 |

## 核心接口

- `dump_counts(path)`：统计 ObjectName、attribute row、operation row。
- `source_checks()`：验证源码/测试 token 和 dump file baselines。
- `doc_checks()`：验证 matrix、checker doc、README、source-map 包含 scenario ids、file paths、counts 和 test anchors。
- `--json`：输出 metadata 和 failed checks，便于 CI 或人工审计。

## 生命周期

```text
developer changes JMX metadata/tests/dumps
  -> run python3 research/tools/check-jmx-compatibility-drift.py
  -> source-only checker validates dump counts, source tokens and docs
  -> run Java JMX tests for real compatibility/runtime evidence
  -> update gold dumps/excludes/docs together if the change is intentional
```

## 调用链

```text
check-jmx-compatibility-drift.py
  -> dump_counts(test/data/jmxdump/*.yaml)
  -> source token checks for JMXCompatibilityTest/JMXTool/JMXStandardsTest/JMXGetterCheckTest/JMXFeatureTest/IsolatedJmx
  -> doc token checks for matrix/checker/README/source-map
  -> print OK or failed checks
```

## 配置项

- 无运行时配置；checker 只读 repository files。
- JMX runtime 配置仍由 `JMXServerUtils`、`CassandraDaemon` 和 test harness 控制。

## Metrics

- checker 输出 dump object/attribute/operation counts。
- 不读取 runtime metric values，也不验证 metric cardinality；那属于 `JMXCompatibilityTest` 和 metrics matrix 的范围。

## 日志

- 成功输出 `OK JMX compatibility drift checks passed (...)`。
- 失败输出每个 failed source/doc/dump check，并返回 1。
- 源码结构无法解析时返回 2。

## 运维关注点

- checker 绿色只说明文档和源码基线同步；不能说明 JMX server 能启动、远端能连接、getter 可读。
- gold dump row count drift 可能是合法重生成，也可能是误改；必须结合 `JMXCompatibilityTest` 和 release 语义判断。
- 新增 Cassandra JMX package 时，需要同时更新 `JMXTool.METRIC_PACKAGES`、matrix 和 checker。

## 性能瓶颈

- 只做文本 IO 和正则统计，成本低。
- 最大输入是 4 个 YAML dump，当前合计约 20k ObjectName rows、124k attribute rows、34k operation rows。

## 常见故障

- `dump object count ...` 失败：历史 dump 文件被修改或重生成。
- `source token contract JMXCompatibilityTest` 失败：diff 方向、dump path 或 exclude contract 改变。
- `source token contract JMXTool` 失败：dump/diff CLI 或 metadata model 改变。
- `doc token ...` 失败：matrix、checker doc、README 或 source-map 未同步。

## 测试用例

- `python3 research/tools/check-jmx-compatibility-drift.py`。
- `python3 research/tools/check-jmx-compatibility-drift.py --json`。
- Runtime evidence: `JMXCompatibilityTest`、`JMXToolTest`、`JMXStandardsTest`、`JMXGetterCheckTest`、`JMXFeatureTest`。
