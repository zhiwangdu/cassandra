# Module: Dynamic Snitch Topology Drift Checker

## 范围

本模块记录 `research/tools/check-dynamic-snitch-topology-drift.py` 的用途、输入、输出和维护方式。它覆盖 dynamic snitch topology-change regression matrix 到当前源码的 source-only 同步检查：`DynamicEndpointSnitch` 排序和 severity contract、MBean/JMX、dynamic snitch 配置、decommission severity 注入、remote write forwarding severity filter、batchlog dynamic strategy、相关 unit/distributed tests，以及 `research/module-dynamic-snitch-topology-regression.md` 中的场景 ID 覆盖。

## 设计目标

- 用源码中的 `DynamicEndpointSnitch.sortedByProximity()`、`updateScores()`、`addSeverity()` 和 `getSeverity()` 作为排序与 severity 事实来源。
- 用 `Config.java`、`conf/cassandra*.yaml`、`DatabaseDescriptor.java` 和 `StorageService.java` 作为 dynamic snitch/runtime update/decommission severity 配置事实来源。
- 用 `DecommissionAvoidTimeouts`、read/write subclasses、`DynamicEndpointSnitchTest`、`BatchlogEndpointFilterTest` 和 JMX getter test 作为 regression coverage 事实来源。
- 要求研究文档保留 `score_order_zero_threshold`、`badness_threshold_preserves_subsnitch`、`decommission_severity_gossip`、`decommission_read_write_trace_regression`、`remote_write_forwarding_severity_filter`、`batchlog_dynamic_snitch_selection`、`jmx_dynamic_endpoint_snitch_observability`、`runtime_update_snitch_config` 八个场景 ID。

## 解决的问题

- dynamic snitch topology-change 覆盖横跨 locator、service、config、tools、batchlog 和 dtest；人工维护时容易只更新其中一处。
- `severity_during_decommission` 与 `ApplicationState.SEVERITY` 的 contract 如果漂移，read/write timeout 避让 runbook 会继续引用旧路径。
- `batchlog_endpoint_strategy=dynamic_remote` 与 `dynamic` 的 fallback 和 test 覆盖容易被误认为只是 batchlog 模块问题；checker 把它纳入 dynamic snitch source contract。
- source-only checker 可以在不启动 Cassandra、不运行 dtest 的情况下提醒 research 文档和源码已经不同步。

## 设计取舍

- checker 不解析 Java AST；使用精确字符串和小范围正则检查当前源码 contract。如果源码重构但语义保持，应同步更新 checker 和本模块。
- checker 不执行 unit/dtest，只验证关键测试文件仍包含配置、hook、trace、assertion 和 helper 调用。
- checker 不判断 `severity_during_decommission` 应该设置成什么生产值；只验证源码支持该配置并且 dtest 覆盖大 severity + threshold 0 的 topology regression。
- 文档检查只要求场景 ID、关键方法名、配置项和测试名存在，不强制研究文档表格格式。

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-dynamic-snitch-topology-drift.py` | 读取 source/docs，验证 dynamic snitch topology regression contract。 |
| `SourceCheck` | checker 内部 dataclass，记录 source contract 名称、路径和 pass/fail。 |
| `DynamicEndpointSnitch` | 排序、score、severity 和 MBean implementation 的主要事实来源，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:51-60`、`src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:175-228`。 |
| `DynamicEndpointSnitchMBean` | JMX contract 事实来源，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitchMBean.java:25-61`。 |
| `DecommissionAvoidTimeouts` | decommission read/write timeout regression dtest 基类，见 `test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidTimeouts.java:77-223`。 |

## 核心接口

- `source_checks()`：读取 Java/YAML/test source，返回 source contract checks。
- `doc_checks()`：读取 target docs，检查场景 ID、方法名、配置项和测试名覆盖。
- `check()`：聚合 source 和 doc checks，输出 structured result 与 ok 状态。
- 命令行入口：`python3 research/tools/check-dynamic-snitch-topology-drift.py` 返回 0 表示同步，1 表示 source/docs drift，2 表示读取或解析错误。
- `--json`：输出 `scenario_ids`、`source_checks`、`doc_checks`、`docs` 等字段，便于 CI artifact。

## 核心数据结构

| 数据结构 | 字段 | 语义 |
|---|---|---|
| `SCENARIO_IDS` | 8 个 scenario strings | research 文档必须保留的 topology regression 场景。 |
| `TARGET_DOCS` | markdown paths | checker 要扫描的研究文档。 |
| `SOURCE_PATHS` | logical source key -> path | dynamic snitch/config/test/JMX source files。 |
| `SourceCheck` | `name` / `source` / `ok` | 单个 source 或 doc contract check 结果。 |

## 生命周期

本地运行：

```text
developer changes dynamic snitch, decommission, StorageProxy forwarding, batchlog endpoint selection, or tests
  -> run python3 research/tools/check-dynamic-snitch-topology-drift.py
  -> script validates source contract snippets and doc scenario coverage
  -> failed check prints the contract name and source/doc path
```

研究维护：

```text
source behavior changes intentionally
  -> update module-dynamic-snitch-topology-regression.md scenario matrix
  -> update check-dynamic-snitch-topology-drift.py source snippet or doc requirements
  -> rerun all research drift checkers and markdown/source-reference validation
```

## 调用链

```text
main()
  -> check()
     -> source_checks()
        -> read DynamicEndpointSnitch, Config, DatabaseDescriptor, StorageService, StorageProxy, ReplicaPlans, tests
        -> verify exact source contracts
     -> doc_checks()
        -> read target markdown docs
        -> verify scenario IDs, configs, methods, tests
  -> print human-readable counts and failures
  -> exit 0/1/2
```

## 配置项

- checker 没有外部配置文件；source paths、target docs、scenario IDs 和 doc-required tokens 写在脚本顶部。
- 如果 dynamic snitch research 拆分到多个文档，应扩展 `TARGET_DOCS`。
- 如果新增 topology regression 场景，应同步扩展 `SCENARIO_IDS` 和文档矩阵。
- `--json` 输出适合 CI 或 review artifact；默认 human-readable 输出适合本地维护。

## Metrics

- checker 不接入 Cassandra runtime metrics。
- 可观测输出是 source check 数量、doc check 数量、failed source/doc checks 和 scenario IDs。
- 当前基线应验证 8 个 scenario IDs，并覆盖 locator/service/config/tools/test 多个 source contract。

## 日志

- 成功时输出 `OK dynamic snitch topology source checks`、`OK dynamic snitch topology doc checks` 和同步确认。
- drift 时输出 `Dynamic snitch source/doc checks failed` 并列出 check name 和 path。
- 读取失败或 parser 异常时向 stderr 输出 `ERROR: ...` 并返回 2。

## 运维关注点

- checker 只证明 source/docs 同步，不替代 `DecommissionAvoidReadTimeoutsTest`、`DecommissionAvoidWriteTimeoutsTest`、`DynamicEndpointSnitchTest` 或 batchlog unit tests。
- 将 checker 接入 CI 时应和 consistency guardrail、system keyspace RF、messaging verb、system table、diagnostic event、nodetool、SSTable tools drift checkers 一起运行。
- 如果某次重构删除 ByteBuddy dtest hook，需要确认是否有等价的 runtime assertion 覆盖 severity 非零 endpoint 排最后，再更新 checker。

## 性能瓶颈

- 脚本只读取少量 source、YAML 和 markdown 文件，运行成本是线性文本 IO。
- 正则检查很小，不依赖 Java 编译或 Cassandra daemon。
- 如果未来改为解析 Java AST，复杂度和运行成本会上升，需权衡 false positive 与维护成本。

## 常见故障

- `source checks failed: DynamicEndpointSnitch threshold branch`：排序分支改写，需重新审查 score vs badness semantics。
- `source checks failed: decommission severity injection`：`StorageService.startLeaving()` 或 severity config contract 变化，需同步 topology runbook。
- `doc checks failed: scenario ...`：研究文档缺少 required scenario ID，需补回矩阵或更新 scenario 列表。
- `BatchlogEndpointFilterTest dynamic score helper` 失败：batchlog dynamic strategy 测试结构重构，需确认 `dsnitch.updateScores()` 仍有覆盖或改用新的测试依据。

## 测试用例

- `python3 research/tools/check-dynamic-snitch-topology-drift.py`：本地 source/doc drift check，当前应返回 0。
- `python3 research/tools/check-dynamic-snitch-topology-drift.py --json`：输出 source/doc checks 和 scenario IDs。
- `python3 -m py_compile research/tools/check-dynamic-snitch-topology-drift.py`：脚本语法检查。
- Java runtime 行为依据仍是 `test/unit/org/apache/cassandra/locator/DynamicEndpointSnitchTest.java`、`test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidReadTimeoutsTest.java`、`test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidWriteTimeoutsTest.java` 和 `test/unit/org/apache/cassandra/batchlog/BatchlogEndpointFilterTest.java`。
