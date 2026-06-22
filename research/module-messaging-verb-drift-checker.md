# Module: Messaging Verb Drift Checker

## 范围

本模块记录 `research/tools/check-messaging-verb-matrix-drift.py` 的用途、输入、输出和维护方式。它覆盖 `src/java/org/apache/cassandra/net/Verb.java` 中 internode `Verb` enum 常量到 `research/module-messaging-verb-semantics.md` 的精确名称覆盖检查。它不验证每个 verb 的 timeout、stage、serializer、handler 语义是否逐字段一致；这些解释仍由 `research/module-messaging-verb-semantics.md` 维护。

## 设计目标

- 用 `Verb.java` 作为 internode verb 清单事实来源，避免新增或删除 verb 后语义矩阵漏写。
- 要求矩阵文档出现每个 verb 的精确常量名，而不是只用 `REQ/RSP` 缩写概括一组 verb。
- 不编译 Cassandra、不启动节点、不连接 JMX，只读取 Java source 和 markdown 文件，保持和 system table、nodetool、SSTable tools drift checker 一样的 source-only 运行方式。
- 输出 human-readable drift 明细，同时提供 `--json` 给后续 CI artifact 或本地分析使用。

## 解决的问题

- `Verb` enum 是 messaging contract 的集中 registry，当前源码在 `src/java/org/apache/cassandra/net/Verb.java:115-228` 定义 87 个常量，覆盖 write、hints、batchlog、Paxos、read、gossip、schema、repair、snapshot、failure、dummy/deprecated/custom verbs。
- 语义矩阵如果使用 `PAXOS_PREPARE_REQ/RSP` 这类压缩写法，读者可以理解，但 source drift checker 无法证明 `PAXOS_PREPARE_RSP` 等 exact symbol 被覆盖。
- `Verb.fromId()` 和 `VerbTest.idsMatch()` 已验证 enum id round-trip，见 `src/java/org/apache/cassandra/net/Verb.java:446-457`、`test/unit/org/apache/cassandra/net/VerbTest.java:27-31`；本 checker 补的是 research 文档同步，不替代 Java 单测。
- custom verb id 映射从 VInt 两字节上界向下分配，见 `src/java/org/apache/cassandra/net/Verb.java:383-465`；checker 通过 enum 常量名覆盖 `UNUSED_CUSTOM_VERB`，不重新实现 id 合法性验证。

## 设计取舍

- parser 只读取 `public enum Verb` 后、enum 常量分号前的行首 `NAME(` 模式；这能覆盖当前单行和 `UNUSED_CUSTOM_VERB` 的多行形态，见 `research/tools/check-messaging-verb-matrix-drift.py:29-49`。
- checker 只检查 source verb -> matrix 覆盖，不检查 matrix 中是否存在已经删除的旧 verb；保持低 false positive，避免把 stage、param、flag 等 uppercase symbol 误判为 verb。
- 文档匹配使用精确 symbol regex，避免 `READ_REQ` 被更长 token 子串误匹配，见 `research/tools/check-messaging-verb-matrix-drift.py:52-53`。
- 当前不解析 `id`、`priority`、`stage`、`expiration`、serializer、handler 或 `responseVerb` 字段，因为这些语义在 matrix 中以人工解释呈现，结构化解析成本和误判风险更高。
- `--json` 输出每个 verb 的 source line，方便后续脚本比较或生成 review artifact，但不作为 Cassandra runtime API。

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-messaging-verb-matrix-drift.py` | 解析 `Verb.java` 常量并检查 messaging matrix 是否覆盖每个 exact verb name。 |
| `Verb` | internode message 类型 registry，定义 id、priority、stage、timeout、serializer、handler 和 response verb，见 `src/java/org/apache/cassandra/net/Verb.java:113-228`。 |
| `VerbEntry` | checker 内部 dataclass，记录 verb name、source line 和 source path，见 `research/tools/check-messaging-verb-matrix-drift.py:18-22`。 |
| `module-messaging-verb-semantics.md` | checker 的目标文档，记录 verb family、stage/timeout、默认连接、failure callback、params、metrics 和测试覆盖。 |
| `VerbTest` | Java 侧 id round-trip 单测，见 `test/unit/org/apache/cassandra/net/VerbTest.java:27-31`。 |

## 核心接口

- `verb_entries()`：扫描 `Verb.java`，进入 `public enum Verb` 后提取行首常量名和行号，遇到 enum 常量区结束分号停止，见 `research/tools/check-messaging-verb-matrix-drift.py:29-49`。
- `documented(symbol, text)`：用 exact symbol regex 判断矩阵是否出现某个 verb 名称，见 `research/tools/check-messaging-verb-matrix-drift.py:52-53`。
- `check()`：读取 source entries 和 matrix 文本，生成 `missing_verbs` 列表并返回 ok 状态，见 `research/tools/check-messaging-verb-matrix-drift.py:56-68`。
- 命令行入口：`python3 research/tools/check-messaging-verb-matrix-drift.py` 返回 0 表示同步；返回 1 表示 matrix drift；返回 2 表示解析或文件读取错误，见 `research/tools/check-messaging-verb-matrix-drift.py:71-97`。
- `--json`：输出 `source`、`matrix`、`verb_count`、`verbs` 和 `missing_verbs` 字段。

## 核心数据结构

| 数据结构 | 字段 | 语义 |
|---|---|---|
| `VerbEntry` | `name` | Java enum 常量名，例如 `MUTATION_REQ`、`GOSSIP_DIGEST_SYN`、`PAXOS2_CLEANUP_RSP2`。 |
| `VerbEntry` | `line` | 常量在 `Verb.java` 中的源码行号，用于 drift 输出定位。 |
| `VerbEntry` | `source` | 固定为 `src/java/org/apache/cassandra/net/Verb.java`。 |
| `result` | `verb_count` | 当前解析到的 verb 常量数量；当前基线为 87。 |
| `result` | `missing_verbs` | source 中存在但 matrix 文档没有 exact symbol 的 verb entries。 |

## 生命周期

本地运行：

```text
developer adds/removes/renames Verb constant
  -> run python3 research/tools/check-messaging-verb-matrix-drift.py
  -> script parses Verb.java constants
  -> script checks module-messaging-verb-semantics.md exact symbol coverage
  -> missing verb fails the run with source line
```

研究维护：

```text
new internode Verb added
  -> update Verb.java id/priority/stage/timeout/serializer/handler/responseVerb
  -> update module-messaging-verb-semantics.md matrix row and related semantics
  -> run messaging verb drift checker
  -> run all research drift checkers and markdown/source-reference validation
```

## 调用链

```text
main()
  -> check()
     -> verb_entries()
        -> read(Verb.java)
        -> scan enum constants until constant-section semicolon
        -> emit VerbEntry(name, line)
     -> read(module-messaging-verb-semantics.md)
     -> documented(entry.name, matrix_text)
  -> print count and missing verb details
  -> exit 0/1/2
```

## 配置项

- 当前没有外部配置文件；`VERB_SOURCE` 和 `MATRIX_DOC` 写在脚本顶部，见 `research/tools/check-messaging-verb-matrix-drift.py:13-15`。
- 如果 matrix 拆分到多个文档，应把 `MATRIX_DOC` 扩展为文档列表并拼接扫描。
- 如果 `Verb.java` 未来改成每个常量不以 `NAME(` 开头的格式，需要调整 `verb_entries()` 的正则。
- `--json` 可以用于 CI artifact 或本地审阅；human-readable 输出适合 pre-commit 或手动运行。

## Metrics

- checker 不接入 Cassandra runtime metrics。
- 可观测输出是解析到的 verb 常量数、缺失 verb 清单和每个缺失项的 source line。
- 当前成功输出应包含 `OK messaging verbs parsed: 87 constants from src/java/org/apache/cassandra/net/Verb.java`。

## 日志

- 成功时输出解析到的 verb 常量数量，以及 `Messaging verb matrix is in sync with parsed Verb.java constants.`。
- matrix 漏写时输出 `Verb constants missing from messaging matrix:`，并逐项打印 `NAME (source:line)`。
- 解析或读取失败时向 stderr 输出 `ERROR: ...` 并返回 2。
- `--json` 模式只输出 JSON，便于机器消费。

## 运维关注点

- checker 是 research 维护工具，不替代 `VerbTest`、messaging serialization tests、mixed-version dtests 或真实 internode protocol compatibility 验证。
- 新增 verb 不能只让 checker 通过；还要在 matrix 中说明 stage、timeout、默认 connection、failure callback、params、metrics、测试覆盖和与 mixed-version 的关系。
- 如果新 verb 是 response-only、repair session message 或 custom/deprecated/dummy verb，应在 matrix 中明确它是否由 `ResponseVerbHandler` 处理、是否有 request pair、是否可能走 failure callback。
- 如果 `Verb.java` 增加嵌套 enum 或 helper 常量，checker 只看 enum 常量区；源码结构大改后需要先确认 parser 仍只抽取 `Verb` constants。
- 将本 checker 接入 CI 时应和其他 research drift checkers 同步运行，避免只证明 verb name coverage 而忽略 system table、nodetool、SSTable tools 或 diagnostic events drift。

## 性能瓶颈

- 脚本只读取一个 Java 文件和一个 markdown 文件，成本主要是文本 IO 和正则匹配。
- 精确 symbol check 对 87 个 verb 做线性扫描，运行成本可以忽略。
- 若未来扩展到解析 stage/timeout/response pair 字段，应优先引入结构化 parser 或更严格的 enum-row parser，避免在复杂 supplier 参数中用宽泛正则误判。

## 常见故障

- `Could not parse verb constants from src/java/org/apache/cassandra/net/Verb.java`：`Verb.java` enum 结构变化，`public enum Verb` 或常量行格式不再匹配。
- `Verb constants missing from messaging matrix`：新增、删除后重命名后的 verb 没有进入 `module-messaging-verb-semantics.md` exact symbol 覆盖。
- matrix 使用压缩写法导致失败：把 `FOO_REQ/RSP` 改成 ``FOO_REQ` -> `FOO_RSP`` 这样的 exact constants。
- checker 通过但语义解释过旧：说明 exact name 仍存在，但 timeout、stage、handler 或 callback 语义发生变化；需要人工复核对应 `Verb.java` 行和 send site。

## 测试用例

- `python3 research/tools/check-messaging-verb-matrix-drift.py`：本地 source-only drift check，当前应返回 0。
- `python3 research/tools/check-messaging-verb-matrix-drift.py --json`：输出每个 verb constant、source line 和 missing coverage 列表。
- `python3 -m py_compile research/tools/check-messaging-verb-matrix-drift.py`：脚本语法检查。
- `VerbTest.idsMatch()`：Java 侧确认 every `Verb.values()` entry can round-trip through `Verb.fromId(v.id)`，见 `test/unit/org/apache/cassandra/net/VerbTest.java:27-31`。
- `OutboundConnectionsTest` 和 `MessageTest` 仍覆盖 connection routing、message flags/params serialization；测试索引见 `research/module-messaging-verb-semantics.md`。

## 待补项

- 将 checker 接入 CI 或 pre-commit，并保留 JSON artifact。
- 后续若需要更强保障，可扩展为解析 `Verb.java` 的 stage、timeout、priority、handler 和 response pair，并与 matrix 中的结构化字段做一致性检查。
