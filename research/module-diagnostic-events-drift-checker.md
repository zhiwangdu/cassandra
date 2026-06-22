# Module: Diagnostic Events Drift Checker

## 范围

本模块记录 `research/tools/check-diagnostic-events-catalog-drift.py` 的用途、输入、输出和维护方式。它覆盖当前 `src/java` 中所有生产 `DiagnosticEvent` 子类、事件 type enum 常量、`AuditEvent` 使用的 `AuditLogEntryType` 常量，以及 `research/module-diagnostic-events-catalog.md` 的 class/type 覆盖检查。事件 payload 语义仍以 `research/module-diagnostic-events-catalog.md` 为主。

## 设计目标

- 用 Java source 中真实继承 `DiagnosticEvent` 的 class declaration 作为事件 class 事实来源，避免 catalog 漏掉新增事件。
- 用每个 `*EventType` enum 和 `AuditLogEntryType` 作为事件 type 事实来源，避免只列 class 不列 type。
- 识别当前源码里 enum 存在但没有直接 `new EventClass(... TYPE ...)` publish site 的值，要求显式记录这些例外，避免误以为所有 enum 值都会发布。
- 不编译 Cassandra、不启动节点、不连接 JMX，只读取 Java 和 markdown 文件，保持和 system table / nodetool drift checker 一样的 source-only 运行方式。

## 解决的问题

- Diagnostic Events 的生产事件 class 分散在 audit、guardrails、dht、gms、hints、locator、schema、service/read repair 等包；手工 catalog 容易漏掉新增 class，源码入口见 `research/module-diagnostic-events-catalog.md`。
- `AuditEvent` 的 type 不在 `AuditEvent` 内部 enum，而是代理 `AuditLogEntryType`，checker 单独解析 `src/java/org/apache/cassandra/audit/AuditLogEntryType.java:21-73`。
- 当前源码包含 source-spelled API 名称，如 `VERSION_ANOUNCED` 和 `*INSTANCIATED`；checker 按源码常量匹配 catalog，防止文档改成拼写修正后的不可订阅名称。
- `TokenAllocatorEvent.TOKENS_ALLOCATED`、`HintEvent.DISPATCHING_*` 和 `TokenMetadataEvent.PENDING_RANGE_CALCULATION_COMPLETED` 当前没有对应 direct publish site；checker 把它们列入 expected no-direct-publish 集合，源码变化时会提示更新 catalog，相关 enum 见 `src/java/org/apache/cassandra/dht/tokenallocator/TokenAllocatorEvent.java:78-87`、`src/java/org/apache/cassandra/hints/HintEvent.java:34-48`、`src/java/org/apache/cassandra/locator/TokenMetadataEvent.java:32-36`。

## 设计取舍

- checker 只证明 class/type 名称覆盖和 no-direct-publish 例外覆盖，不证明 payload 字段描述完整。
- publish site 识别使用 `new EventClass(...)` 之后的短窗口文本匹配 type 常量；这足以覆盖当前 helper 形态，但如果未来 publisher 结构大改，需要更新解析规则。
- `AuditEvent` 按 `AuditLogEntryType` 全量 type 处理，并视为动态可发布；checker 不试图反推每个 audit type 的具体 CQL/auth 触发路径。
- 文档匹配使用精确 symbol regex，避免常量名作为长词子串时误判。

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-diagnostic-events-catalog-drift.py` | 解析生产 `DiagnosticEvent` class/type 并检查 catalog 覆盖。 |
| `DiagnosticEvent` | 生产事件基类；checker 查找直接继承该类的 class declaration，见 `src/java/org/apache/cassandra/diag/DiagnosticEvent.java:25-52`。 |
| `DiagnosticEventService` | publish/isEnabled/subscribe 入口；checker 不运行服务，只用 catalog 记录其行为，见 `src/java/org/apache/cassandra/diag/DiagnosticEventService.java:43-305`。 |
| `AuditLogEntryType` | `AuditEvent` 的动态 type 来源，见 `src/java/org/apache/cassandra/audit/AuditLogEntryType.java:21-73`。 |
| `module-diagnostic-events-catalog.md` | checker 的目标文档，记录 class/type/publisher/payload catalog。 |

## 核心接口

- `production_event_classes()`：扫描 `src/java/**/*.java`，查找 `class X extends DiagnosticEvent`，解析 FQCN、source path 和 type 常量。
- `enum_constants()`：从指定 enum body 中提取大写常量名，支持 constructor 参数形式，例如 `SELECT(AuditLogEntryCategory.QUERY)`。
- `published_types()`：扫描 source 中 `new EventClass(...)` 的上下文窗口，判断 type 常量是否有 direct publish site。
- `check()`：读取 catalog，生成 missing class、missing type、unexpected no-direct-publish 和 stale expected no-direct-publish 列表。
- 命令行入口：`python3 research/tools/check-diagnostic-events-catalog-drift.py` 返回 0 表示同步；返回 1 表示文档 drift；返回 2 表示解析或文件读取错误。

## 核心数据结构

| 数据结构 | 字段 | 语义 |
|---|---|---|
| `EventClass` | `fqn` / `class_name` / `source` | 生产事件 class 的 FQCN、简单类名和源码路径。 |
| `EventClass` | `type_source` | type enum 的源码路径；`AuditEvent` 指向 `AuditLogEntryType.java`。 |
| `EventClass` | `event_types` | checker 解析出的可订阅 type 常量名。 |
| `EventClass` | `published_types` | 当前源码中有 direct publish site 的 type 常量名。 |
| `EXPECTED_NO_DIRECT_PUBLISH` | `(event_class, type)` | 当前源码中 enum 存在但没有 direct publish site 的显式例外集合。 |

## 生命周期

本地运行：

```text
developer updates DiagnosticEvent class/type/publisher/catalog
  -> run python3 research/tools/check-diagnostic-events-catalog-drift.py
  -> script parses DiagnosticEvent subclasses and AuditLogEntryType
  -> script scans module-diagnostic-events-catalog.md
  -> missing class/type or no-direct-publish drift fails the run
```

研究维护：

```text
new DiagnosticEvent class added
  -> add event class and publisher helper in Java
  -> update module-diagnostic-events-catalog.md class/type/payload row
  -> update expected no-direct-publish set only if enum intentionally has no direct publisher
  -> rerun drift checker and markdown validation
```

## 调用链

```text
main()
  -> check()
     -> production_event_classes()
        -> class_declaration()
        -> event_type_enums() or AuditLogEntryType
        -> enum_constants()
        -> published_types()
     -> documented(class/type, catalog_text)
     -> compare actual no-direct-publish set to EXPECTED_NO_DIRECT_PUBLISH
  -> print counts and drift details
  -> exit 0/1/2
```

## 配置项

- 当前没有外部配置文件；`SOURCE_ROOT`、`CATALOG_DOC`、`AUDIT_TYPE_SOURCE` 和 `EXPECTED_NO_DIRECT_PUBLISH` 写在脚本顶部。
- `--json` 输出 machine-readable event class/type/publisher coverage，适合后续接入 CI 或生成 drift artifact。
- 如果 catalog 拆分到多个文档，应把 `CATALOG_DOC` 扩展为文档列表并拼接扫描。

## Metrics

- checker 不接入 Cassandra runtime metrics。
- 可观测输出是生产事件 class 数、事件 type 常量数、expected no-direct-publish 数，以及缺失/新增 drift 明细。
- 当前基线应解析到 13 个生产 `DiagnosticEvent` 子类，并检查 113 个事件 type 常量。

## 日志

- 成功时输出 `OK diagnostic event classes`、`OK diagnostic event types`、`OK expected no-direct-publish notes` 和同步确认。
- 文档缺失时输出 missing class 或 missing type。
- enum 新增但没有 direct publish site 且未列入 expected set 时，输出 `New enum values without direct publish sites`。
- expected set 中的值后续被发布或消失时，输出 `Expected no-direct-publish values now have publish sites or disappeared`。

## 运维关注点

- checker 是 research 维护工具，不替代 `DiagnosticEventServiceTest`、read repair diagnostic tests、audit diagnostic tests 或真实 JMX client 验证。
- 新增事件进入 catalog 时不能只列 class/type，还应补 payload 字段、publisher helper、敏感数据风险、性能影响和测试覆盖。
- 如果 future code 通过 factory、reflection 或不同 helper 构造事件，`published_types()` 可能需要升级为更结构化的 parser。
- `EXPECTED_NO_DIRECT_PUBLISH` 是源码事实和文档说明之间的显式契约；新增例外时要先确认它确实是 intentional API surface，而不是遗漏 publisher。

## 性能瓶颈

- 脚本扫描 `src/java` 下 Java 文件并读取一个 markdown catalog，成本主要是文本 IO 和正则匹配。
- publish site 检测对每个 event class 都扫描 source；当前事件 class 数很小，运行成本可以忽略。
- 若未来扩展到 payload 字段自动检查，应该从 `toMap()` 解析结构化 field put，而不是继续增加宽泛文本匹配。

## 常见故障

- `must contain exactly one *EventType enum`：新增 event class 没有 event type enum，或一个 class 中出现多个 `*EventType` enum；需要更新 checker 或源码形态。
- `Missing DiagnosticEvent classes from catalog`：新增 event class 未写入 `module-diagnostic-events-catalog.md`。
- `Missing DiagnosticEvent type constants from catalog`：新增 enum 常量未写入 catalog，或文档拼写与源码不一致。
- `New enum values without direct publish sites`：新增 enum 值没有 direct publish site，需要补 publisher 或把 intentional 例外加入 expected set 并在 catalog 说明。
- `Expected no-direct-publish values now have publish sites or disappeared`：源码行为变了，需要从 expected set 和 catalog 例外说明中移除旧项。

## 测试用例

- `python3 research/tools/check-diagnostic-events-catalog-drift.py`：本地 source-only drift check，当前应返回 0。
- `python3 research/tools/check-diagnostic-events-catalog-drift.py --json`：输出每个 event class、type source、event types、published types 和 no-direct-publish 例外。
- `DiagnosticEventServiceTest` 覆盖 class/type/all 订阅、publish 和 global enabled flag，见 `test/unit/org/apache/cassandra/diag/DiagnosticEventServiceTest.java:54-240`。
- `DiagEventsBlockingReadRepairTest`、`CQLUserAuditTest`、`GuardrailTester` 和 distributed `Listen` 覆盖代表性生产事件 consumer，见 `research/module-diagnostic-events-catalog.md`。

## 待补项

- 将 checker 接入 CI 或 pre-commit，并保留 JSON artifact。
- 若需要进一步降低人工维护成本，可扩展到 `toMap()` payload field drift 检查。
