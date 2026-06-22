# Module: Consistency Guardrail Profile Drift Checker

## 范围

本模块记录 `research/tools/check-consistency-guardrail-profile-drift.py` 的用途、输入、输出和维护方式。它覆盖 `ConsistencyLevel` enum、read/write consistency guardrail source wiring、四个 guardrail property、YAML 模板、JMX surface、CQL entrypoints、custom config provider hook、unit tests 到 `research/module-consistency-guardrail-profiles.md` 的同步检查。它不证明某个 profile 对业务一定正确，也不运行 Cassandra。

## 设计目标

- 以 `src/java/org/apache/cassandra/db/ConsistencyLevel.java` 作为 CL token 事实来源，避免 profile YAML 片段引用已删除或拼错的 CL。
- 以 `Guardrails.java`、`Config.java`、`GuardrailsOptions.java`、`GuardrailsMBean.java` 和 `conf/cassandra*.yaml` 作为配置 contract 事实来源，避免 research profile 漏掉四个 set-valued property。
- 检查 read/write/batch entrypoints 仍在 CQL statement execute path 上调用 guardrail，避免 source 重构后 runbook 继续指向旧入口。
- 检查 custom provider property 和 unit tests 仍存在，确保 per-workload profile 的文档边界有源码依据。

## 解决的问题

- consistency guardrail profile 很容易变成静态建议，和源码实际可配置字段漂移。本 checker 要求每个 profile YAML snippet 明确列出 `read_consistency_levels_warned`、`read_consistency_levels_disallowed`、`write_consistency_levels_warned`、`write_consistency_levels_disallowed`。
- `ConsistencyLevel` 增删时，profile 文档必须更新 CL semantics matrix；checker 从 enum 常量区解析 exact symbols。
- 如果 Guardrails/JMX/YAML/entrypoint 重构，本 checker 会报 source contract drift，迫使研究文档同步更新。

## 设计取舍

- checker 只验证“profile 可被 Cassandra 当前源码表达”和“文档覆盖 source contract”，不判断 profile 是否适合某个业务 SLA。
- profile parser 只读取 `### profile_*` 小节里的第一个 fenced `yaml` block，保持格式稳定、便于审阅。
- source checks 使用精确字符串和小范围正则，不做 Java AST 解析；如果源码重构但语义不变，应同步调整 checker。
- checker 要求 `profile_default_observe`、`profile_local_dc_oltp`、`profile_no_lwt_service`、`profile_cross_dc_strict`、`profile_bulk_ingest` 五个 profile ID 存在，避免后续删掉有代表性的 workload 模板。

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-consistency-guardrail-profile-drift.py` | 解析 CL enum、profile YAML、source wiring，并输出 drift 明细。 |
| `SourceCheck` | checker 内部 dataclass，记录 source contract 名称、路径和是否通过。 |
| `Profile` | checker 内部 dataclass，记录 profile name 和四个 guardrail property 的 CL 列表。 |
| `ConsistencyLevel` | CL enum source，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:35-48`。 |
| `Guardrails` | read/write `Values<ConsistencyLevel>` 和 JMX 实现 source，见 `src/java/org/apache/cassandra/db/guardrails/Guardrails.java:310-327`、`src/java/org/apache/cassandra/db/guardrails/Guardrails.java:1024-1116`。 |
| `GuardrailsConfigProvider` | per-workload config hook source，见 `src/java/org/apache/cassandra/db/guardrails/GuardrailsConfigProvider.java:40-81`。 |

## 核心接口

- `consistency_levels()`：扫描 `public enum ConsistencyLevel` 常量区，返回 exact CL names。
- `source_checks()`：验证 Guardrails definitions、Config defaults、GuardrailsOptions validation/update、MBean surface、YAML templates、entrypoints、custom provider property 和 tests。
- `parse_profiles()`：读取 profile doc 中 `### profile_*` 小节和 YAML block。
- `check()`：聚合 source checks、profile property coverage、invalid CL values、duplicate values、missing docs 和 missing profiles。
- 命令行入口：`python3 research/tools/check-consistency-guardrail-profile-drift.py` 返回 0 表示同步，1 表示 drift，2 表示解析或文件读取错误。

## 核心数据结构

| 数据结构 | 字段 | 语义 |
|---|---|---|
| `PROPERTIES` | 4 property names | Cassandra consistency guardrail 可配置面。 |
| `EXPECTED_PROFILES` | 5 profile IDs | profile doc 必须保留的 workload 模板。 |
| `ENTRYPOINTS` | read/write/batch source paths | CQL execution guardrail hook 的 source anchors。 |
| `SourceCheck` | `name` / `source` / `ok` | 单个 source contract check 结果。 |
| `Profile` | `name` / `properties` | profile YAML 中四个 property 到 CL list 的映射。 |

## 生命周期

```text
developer changes ConsistencyLevel or guardrail wiring
  -> run python3 research/tools/check-consistency-guardrail-profile-drift.py
  -> script parses CL enum and profile YAML snippets
  -> script validates source contracts and profile property coverage
  -> invalid CL, missing property, missing profile or source drift fails the run
```

研究维护：

```text
new CL or guardrail property appears
  -> update module-consistency-guardrail-profiles.md CL matrix and profiles
  -> update checker PROPERTIES or parser if source contract changed
  -> rerun all research drift checkers and markdown/source-reference validation
```

## 调用链

```text
main()
  -> check()
     -> consistency_levels()
     -> read_doc_text()
     -> parse_profiles()
     -> source_checks()
     -> documented(CL/property/profile)
     -> validate profile properties and CL values
  -> print counts and drift details
  -> exit 0/1/2
```

## 配置项

- checker 没有外部配置文件；source paths、target docs、expected property names 和 expected profile IDs 写在脚本顶部。
- `--json` 输出 `consistency_levels`、`source_checks`、`profiles`、missing lists 和 invalid/duplicate values，适合 CI artifact。
- 如果 profile doc 拆分，应扩展 `PROFILE_DOCS`。

## Metrics

- checker 不接入 Cassandra runtime metrics。
- 可观测输出是 CL 常量数量、profile 数量、failed source checks、missing properties、missing profiles、invalid profile values 和 duplicate values。
- 当前基线应解析 12 个 `ConsistencyLevel` constants 和 5 个 profiles。

## 日志

- 成功时输出 `OK consistency levels parsed`、`OK profiles parsed` 和同步确认。
- source contract drift 时输出 `Source contract checks failed` 并列出 check name/source。
- profile drift 时输出缺失/额外 property、非法 CL 或重复 CL。
- 解析失败时向 stderr 输出 `ERROR: ...` 并返回 2。

## 运维关注点

- checker 是 research 维护工具，不替代真实 profile rollout、driver-side CL inventory、canary 或 application SLA review。
- 新 profile 通过 checker 只代表语法和 source coverage 正确；是否应 warn/disallow 某个 CL 仍要结合 workload。
- 如果 Cassandra 引入 official per-workload guardrail config，checker 应增加对新 provider/config source 的识别，而不是只检查当前 custom provider hook。

## 性能瓶颈

- 脚本只读取少量 Java、YAML 和 markdown 文件，运行成本主要是文本 IO。
- profile parsing 是线性扫描，当前 5 个 profile 和 12 个 CL 的规模可以忽略。
- 更复杂的 policy comparison 不应塞入本 checker；如果需要验证业务 profile rollout，应单独做 deployment/test checker。

## 常见故障

- `Could not parse consistency levels`：`ConsistencyLevel` enum 常量区格式变更，需要更新 parser。
- `Expected profile IDs missing`：profile doc 删除或重命名了 required workload template。
- `invalid CL values`：profile YAML 中的 token 不存在于当前 `ConsistencyLevel` enum。
- `Source contract checks failed`：Guardrails/JMX/YAML/entrypoint/test source 已重构，需要同步 checker 和研究文档。

## 测试用例

- `python3 research/tools/check-consistency-guardrail-profile-drift.py`：本地 source-only drift check，当前应返回 0。
- `python3 research/tools/check-consistency-guardrail-profile-drift.py --json`：输出 CL constants、profile sets 和 source contract checks。
- `python3 -m py_compile research/tools/check-consistency-guardrail-profile-drift.py`：脚本语法检查。
- Java 侧 guardrail tests 仍是 runtime 行为依据：`test/unit/org/apache/cassandra/db/guardrails/GuardrailConsistencyLevelsTester.java`、`test/unit/org/apache/cassandra/db/guardrails/GuardrailReadConsistencyLevelsTest.java`、`test/unit/org/apache/cassandra/db/guardrails/GuardrailWriteConsistencyLevelsTest.java`、`test/unit/org/apache/cassandra/db/guardrails/GuardrailsConfigProviderTest.java`。
