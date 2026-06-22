# Module: System Keyspace RF Drift Checker

## 范围

本模块记录 `research/tools/check-system-keyspace-rf-drift.py` 的用途、输入、输出和维护方式。它覆盖 `SchemaConstants` 中 local/virtual/replicated system keyspace 分类、`system`/`system_schema` 的 `KeyspaceParams.local()` metadata contract，以及 `system_auth`、`system_traces`、`system_distributed` 的默认 RF property 与 `default_keyspace_rf` max 规则到 `research/module-consistency-replication-third-round.md` 的覆盖检查。它不检查系统表逐列语义；表名 drift 仍由 `research/tools/check-system-table-drift.py` 覆盖。

## 设计目标

- 用 `SchemaConstants` 作为 local、virtual、replicated system keyspace 分类事实来源，避免 RF 矩阵漏掉新增 system keyspace。
- 用 replicated system keyspace metadata source 验证默认 RF wiring：`DEFAULT_RF` 必须来自对应 `CassandraRelevantProperties`，metadata 必须使用 `KeyspaceParams.simple(Math.max(DEFAULT_RF, DatabaseDescriptor.getDefaultKeyspaceRF()))`。
- 用 local metadata source 验证 `system` 和 `system_schema` 仍使用 `KeyspaceParams.local()`，防止文档把 local-only keyspace 当作可 ALTER RF keyspace。
- 不启动 Cassandra、不编译源码、不连接 JMX，只读取 Java source 和 research markdown。

## 解决的问题

- `SchemaConstants.LOCAL_SYSTEM_KEYSPACE_NAMES`、`VIRTUAL_SYSTEM_KEYSPACE_NAMES` 和 `REPLICATED_SYSTEM_KEYSPACE_NAMES` 是区分 LocalStrategy、virtual table keyspace 和真正复制 system keyspace 的入口，见 `src/java/org/apache/cassandra/schema/SchemaConstants.java:58-68`。
- `system` 和 `system_schema` 的 metadata 明确使用 `KeyspaceParams.local()`，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:536-539`、`src/java/org/apache/cassandra/schema/SchemaKeyspace.java:291-294`。
- `system_auth`、`system_traces`、`system_distributed` 都使用 JVM property default RF 与 `DatabaseDescriptor.getDefaultKeyspaceRF()` 取 max 后创建 SimpleStrategy metadata，见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:155-163`、`src/java/org/apache/cassandra/tracing/TraceKeyspace.java:110-113`、`src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:213-228`。
- 默认 RF property 名称和默认值集中在 `CassandraRelevantProperties`，见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:539-541`。
- 旧 RF 矩阵只把 virtual system keyspace 写成类别，没有显式列出 `system_views` 和 `system_virtual_schema`；checker 首次运行发现该缺口，矩阵已补 exact names，见 `research/module-consistency-replication-third-round.md:55-59`。

## 设计取舍

- checker 只证明 keyspace 分类、local metadata contract、replicated RF property wiring 和文档 exact name 覆盖；不证明 ALTER KEYSPACE runbook、repair 步骤或 multi-DC dtest 完整性。
- replicated RF source check 用正则识别 `DEFAULT_RF = CassandraRelevantProperties.<PROPERTY>.getInt()` 和 `KeyspaceParams.simple(Math.max(DEFAULT_RF, DatabaseDescriptor.getDefaultKeyspaceRF()))`；如果 metadata construction 被重构，需要更新解析规则。
- target 文档暂时固定为 `research/module-consistency-replication-third-round.md`，因为 system keyspace RF 操作差异集中在该模块；如果后续拆分 runbook，扩展 `RF_MATRIX_DOCS` 即可。
- 对默认 RF 数字只从 property source 输出，不单独要求文档出现裸数字；真正 gate 是 property key 和 keyspace exact name，减少无意义的数字误匹配。
- checker 不复用 system table drift checker 的 registry，因为本检查关注 keyspace-level replication/RF contract，而不是 table-level coverage。

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-system-keyspace-rf-drift.py` | 解析 system keyspace 分类、local metadata、replicated RF property wiring，并检查 RF matrix 覆盖。 |
| `SchemaConstants` | system keyspace 名称和 local/virtual/replicated 分类，见 `src/java/org/apache/cassandra/schema/SchemaConstants.java:45-68`。 |
| `SystemKeyspace` | `system` local metadata source，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:536-539`。 |
| `SchemaKeyspace` | `system_schema` local metadata source，见 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:291-294`。 |
| `AuthKeyspace` | `system_auth` replicated metadata 和 default RF wiring，见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:155-163`。 |
| `TraceKeyspace` | `system_traces` replicated metadata 和 default RF wiring，见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:110-113`。 |
| `SystemDistributedKeyspace` | `system_distributed` replicated metadata、auto-repair conditional tables 和 default RF wiring，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:213-228`。 |

## 核心接口

- `classifications()`：读取 `SchemaConstants.java`，解析 `LOCAL_SYSTEM_KEYSPACE_NAMES`、`VIRTUAL_SYSTEM_KEYSPACE_NAMES`、`REPLICATED_SYSTEM_KEYSPACE_NAMES`，见 `research/tools/check-system-keyspace-rf-drift.py:111-118`。
- `property_default(symbol)`：从 `CassandraRelevantProperties.java` 读取 RF property name 和 default value，见 `research/tools/check-system-keyspace-rf-drift.py:121-126`。
- `has_default_rf_binding()`：确认 replicated keyspace source 的 `DEFAULT_RF` 绑定到预期 property symbol，见 `research/tools/check-system-keyspace-rf-drift.py:129-134`。
- `has_simple_max_default_rf()`：确认 metadata 使用 `DEFAULT_RF` 与 `DatabaseDescriptor.getDefaultKeyspaceRF()` 取 max 的 SimpleStrategy contract，见 `research/tools/check-system-keyspace-rf-drift.py:137-144`。
- `has_local_metadata()`：确认 local system keyspace metadata 使用 `KeyspaceParams.local()`，见 `research/tools/check-system-keyspace-rf-drift.py:147-154`。
- 命令行入口：`python3 research/tools/check-system-keyspace-rf-drift.py` 返回 0 表示同步；返回 1 表示 source/doc drift；返回 2 表示解析或文件读取错误，见 `research/tools/check-system-keyspace-rf-drift.py:232-290`。

## 核心数据结构

| 数据结构 | 字段 | 语义 |
|---|---|---|
| `Classification` | `kind` / `symbol` | system keyspace 分类名和 `SchemaConstants` set symbol，见 `research/tools/check-system-keyspace-rf-drift.py:20-24`。 |
| `LocalMetadata` | `keyspace` / `source` / `keyspace_constant` | local metadata source 和应传入 `KeyspaceMetadata.create()` 的 `SchemaConstants` 常量，见 `research/tools/check-system-keyspace-rf-drift.py:26-30`。 |
| `ReplicatedRF` | `keyspace` / `source` / `property_symbol` | replicated system keyspace 的 metadata source 和默认 RF property symbol，见 `research/tools/check-system-keyspace-rf-drift.py:33-37`。 |
| `CLASSIFICATIONS` | local / virtual / replicated | 当前解析 `system`、`system_schema`、`system_views`、`system_virtual_schema`、`system_auth`、`system_traces`、`system_distributed`，见 `research/tools/check-system-keyspace-rf-drift.py:40-44`。 |
| `REPLICATED_RF` | 3 entries | `system_auth`、`system_traces`、`system_distributed` 的 RF property wiring contract，见 `research/tools/check-system-keyspace-rf-drift.py:51-55`。 |

## 生命周期

本地运行：

```text
developer changes system keyspace classification or default RF source
  -> run python3 research/tools/check-system-keyspace-rf-drift.py
  -> script parses SchemaConstants categories
  -> script checks local KeyspaceParams.local() metadata
  -> script checks replicated DEFAULT_RF property and max(default_keyspace_rf) metadata
  -> script scans module-consistency-replication-third-round.md
  -> missing source/doc coverage fails the run
```

研究维护：

```text
new system keyspace or RF property added
  -> update SchemaConstants and metadata source
  -> update system keyspace RF matrix with exact keyspace/property names
  -> run system keyspace RF drift checker
  -> run system table drift checker if tables changed
  -> run markdown/source-reference validation
```

## 调用链

```text
main()
  -> check()
     -> classifications()
        -> find_immutable_args()
        -> resolve_args()
     -> has_local_metadata() for system and system_schema
     -> property_default() + has_default_rf_binding() + has_simple_max_default_rf()
     -> documented(keyspace/property, RF matrix text)
  -> print classification, local metadata and replicated RF status
  -> exit 0/1/2
```

## 配置项

- 当前没有外部配置文件；`SCHEMA_CONSTANTS_SOURCE`、`PROPERTIES_SOURCE`、`RF_MATRIX_DOCS`、`LOCAL_METADATA` 和 `REPLICATED_RF` 写在脚本顶部，见 `research/tools/check-system-keyspace-rf-drift.py:14-55`。
- `--json` 输出 classification、local metadata、replicated RF property/default 和 missing coverage，适合后续接入 CI 或生成 artifact。
- 如果 RF matrix 拆分到多个文档，应扩展 `RF_MATRIX_DOCS`。
- 如果新增 replicated system keyspace，应在 `REPLICATED_RF` 增加 source/property mapping，并在 matrix 中补 keyspace、property 和操作语义。

## Metrics

- checker 不接入 Cassandra runtime metrics。
- 可观测输出是 local/virtual/replicated 分类列表、local metadata contract 状态、replicated RF property name/default、source wiring 状态和文档覆盖状态。
- 当前基线应输出 2 个 local、2 个 virtual、3 个 replicated system keyspace，并验证 3 个 replicated RF property。

## 日志

- 成功时输出 `OK local system keyspaces`、`OK virtual system keyspaces`、`OK replicated system keyspaces`、local metadata 状态、replicated RF 状态和同步确认。
- 文档缺失时输出 `missing from docs`，指明缺失 keyspace 或 RF property。
- source wiring drift 时输出 `source does not match KeyspaceParams.local() metadata contract`、`source does not bind DEFAULT_RF` 或 `source does not use KeyspaceParams.simple(...)`。
- 解析失败时向 stderr 输出 `ERROR: ...` 并返回 2。

## 运维关注点

- checker 是 research 维护工具，不替代真实 ALTER KEYSPACE、repair、bootstrap、decommission 或 system_auth expansion distributed tests。
- `system_auth` 扩 DC 后仍必须 ALTER RF 并 repair；checker 只保证 runbook 继续提到该 keyspace/property，不证明操作已演练。
- `system_traces` 和 `system_distributed` 默认 SimpleStrategy RF 仍需按部署和保留要求调整；checker 不判断生产 RF 是否合理。
- `system_views` 和 `system_virtual_schema` 是 virtual system keyspace，不应按用户 keyspace ALTER RF；checker 只要求矩阵明确这一点。
- 若 source 重构为 helper 方法构造 metadata，需要同步更新 checker 正则，否则会误报 source wiring drift。

## 性能瓶颈

- 脚本只读取少量 Java 和 markdown 文件，运行成本主要是文本 IO 与正则匹配。
- 分类和 RF entries 当前数量固定且很小；即使扩展到更多 system keyspace，成本仍可忽略。
- 若后续要检查 NTS ALTER/repair runbook 与 distributed tests，应另建更高层的 test/runbook coverage checker，而不是把本 checker 扩成复杂 CQL parser。

## 常见故障

- `Could not find ImmutableSet declaration`：`SchemaConstants` 分类 set 形态变化，需要更新 `find_immutable_args()`。
- `unresolved entries`：分类 set 中出现无法解析的表达式，需要扩展 `string_constants()` 或改成显式 mapping。
- `Could not find property`：RF property enum 常量重命名或迁移，需要更新 `REPLICATED_RF` mapping。
- `source does not bind DEFAULT_RF`：metadata source 不再从预期 `CassandraRelevantProperties` 读取默认 RF。
- `RF property missing from docs`：matrix 没有写出 `cassandra.system_*.default_rf` exact property name。

## 测试用例

- `python3 research/tools/check-system-keyspace-rf-drift.py`：本地 source-only drift check，当前应返回 0。
- `python3 research/tools/check-system-keyspace-rf-drift.py --json`：输出 system keyspace 分类、local metadata contract、replicated RF property/default 和 missing coverage。
- `python3 -m py_compile research/tools/check-system-keyspace-rf-drift.py`：脚本语法检查。
- `UpdateSystemAuthAfterDCExpansionTest` 验证 `system_auth` 加 DC 后 ALTER RF、repair、active DC remove guardrail 和 role visibility，见 `research/module-consistency-replication-third-round.md:173`。
- `TestBaseImpl` 多节点 helper 会提升 replicated system keyspace RF，避免 bootstrap source 不足；测试索引见 `research/module-consistency-replication-third-round.md:68`。

## 待补项

- 将 checker 接入 CI 或 pre-commit，并保留 JSON artifact。
- 后续可增加 system keyspace ALTER/repair runbook coverage checker，验证 `system_auth`、`system_traces`、`system_distributed` 的 NTS 操作步骤和测试覆盖是否同步。
