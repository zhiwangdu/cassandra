# Module: Consistency Guardrail Profiles

## 范围

本文补充 `research/module-consistency-replication.md`、`research/module-consistency-replication-deep-dive.md` 和 `research/module-consistency-replication-third-round.md` 的 read/write consistency guardrail 运维侧研究。它把 `read_consistency_levels_warned`、`read_consistency_levels_disallowed`、`write_consistency_levels_warned`、`write_consistency_levels_disallowed` 四个源码配置项转成 workload profile 模板，并说明何时只能靠全局 `cassandra.yaml`，何时需要 `GuardrailsConfigProvider` 自定义实现。本文不替代业务一致性设计，也不声称 profile 可直接复制到所有集群。

## 设计目标

- 用 `ConsistencyLevel` enum 作为合法 CL token 的唯一事实来源；当前源码定义 `ANY`、`ONE`、`TWO`、`THREE`、`QUORUM`、`ALL`、`LOCAL_QUORUM`、`EACH_QUORUM`、`SERIAL`、`LOCAL_SERIAL`、`LOCAL_ONE`、`NODE_LOCAL`，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:35-48`。
- 用 `Guardrails.readConsistencyLevels` 和 `Guardrails.writeConsistencyLevels` 的 `Values<ConsistencyLevel>` 定义解释 warn/fail 行为，见 `src/java/org/apache/cassandra/db/guardrails/Guardrails.java:307-327`。
- 明确 write guardrail 同时检查 normal CL 和 serial CL；`ModificationStatement` 与 `BatchStatement` 都把 `options.getConsistency()` 和 `options.getSerialConsistency()` 放入同一个 set，见 `src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:491-498`、`src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:410-417`。
- 把 per-workload profile 的边界写清楚：默认 provider 从 `cassandra.yaml` 返回同一份配置；真正按用户/租户/应用区分需要 `cassandra.custom_guardrails_config_provider_class`，见 `src/java/org/apache/cassandra/db/guardrails/GuardrailsConfigProvider.java:30-39`、`src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:179`。

## 解决的问题

- 默认配置四个 set 全为空，意味着 Cassandra 不会主动限制任何 CL；默认字段见 `src/java/org/apache/cassandra/config/Config.java:882-885`，模板注释见 `conf/cassandra.yaml:2107-2113`。
- `Values.guard()` 先检查 disallowed，再检查 ignored，再检查 warned；CL guardrail 没有 ignored set，所以命中 disallowed 会抛 `GuardrailViolatedException`，命中 warned 会通过 client warning/tracing/diagnostic event 暴露，见 `src/java/org/apache/cassandra/db/guardrails/Values.java:103-128`。
- `Guardrail.enabled()` 只对 daemon initialized 且普通用户启用；system/superuser 旁路在源码层面存在，见 `src/java/org/apache/cassandra/db/guardrails/Guardrail.java:85-96`。
- read path 在 `validateForRead()` 后执行 read guardrail；`ANY` 读会先被 `ConsistencyLevel.validateForRead()` 拒绝，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:208-215`、`src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:280-287`。
- write path 在 statement execute 入口执行 write guardrail；conditional write 的 serial CL 默认来自 query options，`QueryOptions` 默认 serial CL 为 `SERIAL`，见 `src/java/org/apache/cassandra/cql3/QueryOptions.java:558`。

CL token profile matrix：

| CL | 读写角色 | profile 处理建议 |
|---|---|---|
| `ANY` | 写专用，读非法 | read disallowed 可显式列出但读会先被源码拒绝；write 只给 hint-tolerant ingest 使用 |
| `ONE` | 任意 DC 单 replica | multi-DC 在线服务通常 warn，避免跨 DC 或弱保证误用 |
| `TWO` | 任意两个 replicas | 很少作为 policy baseline；profile 应明确允许或 warn |
| `THREE` | 任意三个 replicas | 很少作为 policy baseline；profile 应明确允许或 warn |
| `QUORUM` | 全 RF quorum | NTS 多 DC 下不是本地 quorum；local-first workload 应 warn 或 disallow |
| `ALL` | 所有 replicas | tail latency 和可用性风险最高；多数 profile warn 或 disallow |
| `LOCAL_QUORUM` | 本 DC quorum | 多 DC 在线 OLTP 的常见默认候选 |
| `EACH_QUORUM` | 每 DC quorum | 强跨 DC 写策略才保留；远端 DC 问题会直接影响请求 |
| `SERIAL` | global Paxos serial CL | LWT 使用；不使用 LWT 的 workload 可 disallow |
| `LOCAL_SERIAL` | local Paxos serial CL | local LWT 使用；不使用 LWT 的 workload 可 disallow |
| `LOCAL_ONE` | 本 DC 单 replica | 低延迟弱读/弱写可允许，关键写通常 warn |
| `NODE_LOCAL` | 节点本地 CL | 普通 driver workload 不应依赖；profile 应至少 warn |

## 设计取舍

- profile 只控制 Cassandra 已有 guardrail set，不发明新的 CL 语义；最终响应数仍由 `ConsistencyLevel.blockFor()` 和 `blockForWrite()` 计算，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:133-191`。
- profile 以 YAML 片段表示，因为静态部署主要通过 `cassandra.yaml` 配置；运行时可通过 Guardrails MBean 修改同一组 set，MBean surface 见 `src/java/org/apache/cassandra/db/guardrails/GuardrailsMBean.java:391-469`。
- per-workload 差异不是 YAML 内建功能。默认 `GuardrailsConfigProvider.Default` 永远返回 `DatabaseDescriptor.getGuardrailsConfig()`，见 `src/java/org/apache/cassandra/db/guardrails/GuardrailsConfigProvider.java:71-81`。
- disallow serial CL 会影响 LWT，而不仅是普通写；write tests 对 normal CL、`SERIAL`、`LOCAL_SERIAL` 组合都覆盖，见 `test/unit/org/apache/cassandra/db/guardrails/GuardrailWriteConsistencyLevelsTest.java:120-179`。
- profile 中列出 `ANY` 的 read disallowed 是防 drift 可读性选择；实际 read path 会先在 `validateForRead()` 拒绝 `ANY`。

## Profile 模板

### `profile_default_observe`

适合迁移或首次观测阶段；完全保持默认行为，只依赖现有指标、日志和 client-side usage 统计定位误用。

```yaml
read_consistency_levels_warned: []
read_consistency_levels_disallowed: []
write_consistency_levels_warned: []
write_consistency_levels_disallowed: []
```

### `profile_local_dc_oltp`

适合多 DC、本地优先、允许 LWT 的在线 OLTP。核心目标是把正常读写推向 `LOCAL_QUORUM` / `LOCAL_ONE`，同时对 global CL、`ALL`、`EACH_QUORUM` 和 `NODE_LOCAL` 提醒。

```yaml
read_consistency_levels_warned: [ONE, TWO, THREE, QUORUM, EACH_QUORUM, ALL, NODE_LOCAL]
read_consistency_levels_disallowed: [ANY]
write_consistency_levels_warned: [ANY, ONE, TWO, THREE, QUORUM, EACH_QUORUM, ALL, SERIAL, NODE_LOCAL]
write_consistency_levels_disallowed: []
```

### `profile_no_lwt_service`

适合明确禁止 LWT 的服务。它保留本地读写 CL，但拒绝 `SERIAL` / `LOCAL_SERIAL`，避免 conditional statement 或 driver 默认 serial CL 悄悄进入写 guardrail。

```yaml
read_consistency_levels_warned: [ONE, TWO, THREE, QUORUM, EACH_QUORUM, ALL, NODE_LOCAL]
read_consistency_levels_disallowed: [ANY]
write_consistency_levels_warned: [ANY, ONE, TWO, THREE, QUORUM, EACH_QUORUM, ALL, NODE_LOCAL]
write_consistency_levels_disallowed: [SERIAL, LOCAL_SERIAL]
```

### `profile_cross_dc_strict`

适合少数需要跨 DC 强一致写入的 workload。它允许 `EACH_QUORUM` 作为显式选择，但提醒普通 global `QUORUM` 和 `ALL` 的 tail-latency/availability 风险。

```yaml
read_consistency_levels_warned: [ONE, TWO, THREE, QUORUM, ALL, LOCAL_ONE, NODE_LOCAL]
read_consistency_levels_disallowed: [ANY]
write_consistency_levels_warned: [ANY, ONE, TWO, THREE, QUORUM, ALL, LOCAL_ONE, NODE_LOCAL]
write_consistency_levels_disallowed: []
```

### `profile_bulk_ingest`

适合可接受弱写、以吞吐为主的批量导入窗口。它不拒绝 `ANY` / `ONE`，但对 quorum/serial/`ALL` 写发 warning，避免导入任务误把强一致放到吞吐关键路径。

```yaml
read_consistency_levels_warned: [ALL, EACH_QUORUM, NODE_LOCAL]
read_consistency_levels_disallowed: [ANY]
write_consistency_levels_warned: [QUORUM, LOCAL_QUORUM, EACH_QUORUM, ALL, SERIAL, LOCAL_SERIAL, NODE_LOCAL]
write_consistency_levels_disallowed: []
```

## 核心类

| 类 | 作用 |
|---|---|
| `ConsistencyLevel` | 定义 CL token、protocol code、blockFor、read/write 合法性和 serial 判断，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:35-260`。 |
| `Guardrails` | 注册 read/write `Values<ConsistencyLevel>` guardrail，并暴露 JMX getter/setter，见 `src/java/org/apache/cassandra/db/guardrails/Guardrails.java:310-327`、`src/java/org/apache/cassandra/db/guardrails/Guardrails.java:1024-1116`。 |
| `Values` | 对 provided values 与 warned/ignored/disallowed sets 求交集并触发 warn/fail，见 `src/java/org/apache/cassandra/db/guardrails/Values.java:103-128`。 |
| `GuardrailsOptions` | 校验配置 set 非 null、转换为 immutable enum set，并记录运行时更新日志，见 `src/java/org/apache/cassandra/config/GuardrailsOptions.java:75-78`、`src/java/org/apache/cassandra/config/GuardrailsOptions.java:494-547`、`src/java/org/apache/cassandra/config/GuardrailsOptions.java:1240-1246`。 |
| `GuardrailsConfigProvider` | 默认返回全局 config；可通过 custom provider 以 `ClientState` 区分 workload，见 `src/java/org/apache/cassandra/db/guardrails/GuardrailsConfigProvider.java:48-81`。 |
| `SelectStatement` / `ModificationStatement` / `BatchStatement` | read/write guardrail 的 CQL statement 入口，见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:280-287`、`src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:491-498`、`src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:410-417`。 |

## 核心接口

- `Guardrails.readConsistencyLevels.guard(EnumSet.of(cl), state.getClientState())`：SELECT 执行时检查 read CL，见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:282-287`。
- `Guardrails.writeConsistencyLevels.guard(EnumSet.of(options.getConsistency(), options.getSerialConsistency()), clientState)`：普通写、conditional write 和 batch 共用的 write/serial CL 检查，见 `src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:497-498`、`src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:415-417`。
- `GuardrailsMBean` 的 set/get/CSV 方法：允许 JMX 读写四个 set，接口见 `src/java/org/apache/cassandra/db/guardrails/GuardrailsMBean.java:391-469`，实现见 `src/java/org/apache/cassandra/db/guardrails/Guardrails.java:1024-1116`。
- `GuardrailsConfigProvider.getOrCreate(ClientState)`：自定义 provider 可按用户、角色、远端地址或应用标识返回不同 config；接口见 `src/java/org/apache/cassandra/db/guardrails/GuardrailsConfigProvider.java:51-58`。

## 核心数据结构

- 四个 config fields 是 `Set<ConsistencyLevel>`，默认 `Collections.emptySet()`，见 `src/java/org/apache/cassandra/config/Config.java:882-885`。
- `Values` 在运行时只做 set intersection，因此 profile 的可表达能力就是“这些 CL warning”和“这些 CL fail”；源码见 `src/java/org/apache/cassandra/db/guardrails/Values.java:108-127`。
- `EnumSet.of(normal, serial)` 让 write guardrail 可以同时命中 commit CL 和 serial CL；如果两个 CL 都被列入 set，message 会按 intersection 输出。
- `GuardrailsOptions.validateConsistencyLevels()` 对空 set 返回 `Collections.emptySet()`，非空 set 转成 immutable enum set；null 会被拒绝，见 `src/java/org/apache/cassandra/config/GuardrailsOptions.java:1240-1246`。

## 生命周期

全局 YAML profile：

```text
cassandra.yaml
  -> Config read_consistency_levels_* / write_consistency_levels_* sets
  -> GuardrailsOptions validates non-null enum sets
  -> Guardrails Values suppliers read current config
  -> CQL SELECT / write / batch entrypoints invoke guard
  -> Values.guard emits warning or throws GuardrailViolatedException
```

per-workload custom provider：

```text
-Dcassandra.custom_guardrails_config_provider_class=...
  -> GuardrailsConfigProvider.instance loads custom class
  -> getOrCreate(ClientState) returns workload-specific GuardrailsConfig
  -> read/write Values guardrails use that config for ordinary user requests
  -> system and superuser requests still bypass Guardrail.enabled(state)
```

runtime adjustment：

```text
JMX GuardrailsMBean / nodetool guardrails config
  -> setReadConsistencyLevelsWarnedCSV or setWriteConsistencyLevelsDisallowed
  -> GuardrailsOptions validates CL names
  -> later requests observe new supplier values
```

## 调用链

- read profile enforcement: `SelectStatement.execute()` -> `options.getConsistency()` -> `ConsistencyLevel.validateForRead()` -> `Guardrails.readConsistencyLevels.guard()` -> `Values.guard()` -> warning/failure.
- write profile enforcement: `ModificationStatement.execute()` -> `EnumSet.of(normal, serial)` -> `Guardrails.writeConsistencyLevels.guard()` -> conditional/non-conditional write path.
- batch profile enforcement: `BatchStatement.execute()` -> null CL checks -> `Guardrails.writeConsistencyLevels.guard()` -> per-statement disk usage and execution.
- JMX update path: `Guardrails.setReadConsistencyLevelsWarnedCSV()` -> `fromCSV(..., ConsistencyLevel::fromString)` -> `GuardrailsOptions.setReadConsistencyLevelsWarned()` -> `validateConsistencyLevels()`，见 `src/java/org/apache/cassandra/db/guardrails/Guardrails.java:1042-1044`、`src/java/org/apache/cassandra/config/GuardrailsOptions.java:499-504`。

## 配置项

| 配置项 | 默认 | 作用 |
|---|---:|---|
| `read_consistency_levels_warned` | `[]` | 对指定 read CL 发 warning，不拒绝；模板见 `conf/cassandra.yaml:2107-2109`。 |
| `read_consistency_levels_disallowed` | `[]` | 拒绝指定 read CL；模板见 `conf/cassandra.yaml:2107-2109`。 |
| `write_consistency_levels_warned` | `[]` | 对指定 write/serial CL 发 warning；模板见 `conf/cassandra.yaml:2111-2113`。 |
| `write_consistency_levels_disallowed` | `[]` | 拒绝指定 write/serial CL；模板见 `conf/cassandra.yaml:2111-2113`。 |
| `cassandra.custom_guardrails_config_provider_class` | unset | 自定义 `GuardrailsConfigProvider` class；property 定义见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:179`。 |

## Metrics

- consistency guardrail 没有专属 meter；命中后会通过 client warning、tracing 和 `GuardrailsDiagnostics` 暴露，warn/fail 触发点见 `src/java/org/apache/cassandra/db/guardrails/Guardrail.java:98-140`。
- 被拒绝的请求对客户端表现为 guardrail violation；后续不会进入正常 read/write response handler，所以不要把它当 timeout/unavailable 处理。
- 可用性和延迟效果仍需要结合 `ClientRequestMetrics`、driver request metrics、tracing 和 query logs 观察；profile 只能防止已知 CL 被误用。

## 日志

- warn 命中会记录 `Guardrail <name> violated` 前缀，并写入 client warning 和 tracing，见 `src/java/org/apache/cassandra/db/guardrails/Guardrail.java:103-117`。
- fail 命中会记录 error，同样写 client warning/tracing/diagnostic event，然后对普通 CQL 请求抛异常，见 `src/java/org/apache/cassandra/db/guardrails/Guardrail.java:119-140`。
- 配置更新通过 `GuardrailsOptions.updatePropertyWithLogging()` 记录，四个 setter 分别见 `src/java/org/apache/cassandra/config/GuardrailsOptions.java:499-547`。

## 运维关注点

- 先从 `profile_default_observe` 或 warn-only profile 开始，收集 driver 和 server 侧 warnings 后再把高风险 CL 放入 disallowed。
- 禁止 `SERIAL` / `LOCAL_SERIAL` 会影响 LWT，包括 INSERT/UPDATE/DELETE IF 和 conditional batch；write test 覆盖这些分支，见 `test/unit/org/apache/cassandra/db/guardrails/GuardrailWriteConsistencyLevelsTest.java:63-94`。
- `EACH_QUORUM` 不是“更稳的 quorum”，它要求每个 DC 达成本地 quorum；远端 DC 维护会直接放大写失败。
- `QUORUM` 在 NTS 多 DC 下是 global quorum，不等于 `LOCAL_QUORUM`；本地优先服务应通过 profile warning 逼近 `LOCAL_QUORUM`。
- 如果需要 per-service policy，静态 YAML 不够；必须实现并部署 custom `GuardrailsConfigProvider`，且要有对应测试或运行时审计。
- system/superuser bypass 是源码行为；profile 不能用于约束 repair、schema migration、内部查询或管理员会话。

## 性能瓶颈

- guardrail 检查本身只是 enum set intersection，成本可忽略；性能影响来自被允许的 CL 选择。
- `ALL`、`EACH_QUORUM` 和 global `QUORUM` 会把慢 replica 或远端 DC 放入关键路径；profile 只能警告或拒绝，不能降低这些 CL 的等待成本。
- `SERIAL` / `LOCAL_SERIAL` 会进入 Paxos path；只靠 write CL profile 控制不了 Paxos 内部 read/repair 成本，但可以防止不使用 LWT 的 workload 误触发。

## 常见故障

- 应用收到 guardrail violation：检查四个 consistency set、请求用户是否 ordinary user，以及 driver 是否发送了默认 serial CL。
- LWT 被禁止但普通写没有问题：通常是 `write_consistency_levels_disallowed` 包含 `SERIAL` 或 `LOCAL_SERIAL`；conditional write 会和 commit CL 一起进入 write guardrail。
- profile 在 YAML 中配置了未知 CL：`ConsistencyLevel.fromString()` 会在 CSV/JMX path 抛 enum constant error；测试覆盖 invalid CSV，见 `test/unit/org/apache/cassandra/db/guardrails/GuardrailConsistencyLevelsTester.java:102-132`。
- superuser 测试绕过 guardrail：这是 `Guardrail.enabled(state)` 设计，不是 profile 未生效；read/write tests 明确断言 excluded users valid，见 `test/unit/org/apache/cassandra/db/guardrails/GuardrailReadConsistencyLevelsTest.java:102-116`、`test/unit/org/apache/cassandra/db/guardrails/GuardrailWriteConsistencyLevelsTest.java:192-206`。
- custom provider 不生效：检查 JVM property 是否为 `cassandra.custom_guardrails_config_provider_class`，类是否可由 `FBUtilities.construct()` 加载，测试见 `test/unit/org/apache/cassandra/db/guardrails/GuardrailsConfigProviderTest.java:35-63`。

## 测试用例

- `GuardrailConsistencyLevelsTester` 覆盖 null rejection、empty set、`EnumSet.allOf(ConsistencyLevel.class)` 和 CSV invalid token，见 `test/unit/org/apache/cassandra/db/guardrails/GuardrailConsistencyLevelsTester.java:92-132`。
- `GuardrailReadConsistencyLevelsTest` 覆盖 SELECT 的 valid/warn/fail 和 system/superuser bypass，见 `test/unit/org/apache/cassandra/db/guardrails/GuardrailReadConsistencyLevelsTest.java:53-116`。
- `GuardrailWriteConsistencyLevelsTest` 覆盖 INSERT/UPDATE/DELETE/BATCH 和 LWT serial CL warn/fail，见 `test/unit/org/apache/cassandra/db/guardrails/GuardrailWriteConsistencyLevelsTest.java:63-179`。
- `GuardrailsConfigProviderTest` 覆盖 custom provider build 和 missing class error，见 `test/unit/org/apache/cassandra/db/guardrails/GuardrailsConfigProviderTest.java:35-63`。
- `GuardrailsConfigCommandsTest` 的 nodetool 输出包含四个 consistency guardrail set，见 `test/unit/org/apache/cassandra/tools/nodetool/GuardrailsConfigCommandsTest.java:295-301`。

## Drift 检查

- `research/tools/check-consistency-guardrail-profile-drift.py` 解析 `ConsistencyLevel.java` 中所有 CL 常量，校验本文 profile YAML 片段只使用合法 CL，并要求四个 guardrail property 在每个 profile 中都出现。
- checker 同时验证 `Guardrails` 定义、`Config` 默认值、`GuardrailsOptions` 校验/update、`GuardrailsMBean` JMX surface、`cassandra.yaml` / `cassandra_latest.yaml` 模板、三个 CQL entrypoints、custom provider property 和 guardrail unit tests 的源码锚点。
- 运行方式：`python3 research/tools/check-consistency-guardrail-profile-drift.py`；`--json` 输出 source checks、profile sets 和 drift 明细。

## 待补项

- 若未来实现真实 per-workload `GuardrailsConfigProvider`，需要增加 provider-specific 单测和 deployment runbook。
- 可把 checker 接入 CI，与 system keyspace RF、messaging verb、diagnostic events、system table、nodetool、SSTable tools drift checker 一起运行。
