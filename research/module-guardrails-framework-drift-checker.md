# Guardrails Framework Drift Checker

`research/tools/check-guardrails-framework-drift.py` 是 Guardrails 框架矩阵的 source/test/doc 漂移检查器。它不运行 Cassandra 测试，而是把当前源码中的 Guardrails 架构合同、调用入口、运行时配置面和测试基线与 `research/module-guardrails-framework-matrix.md` 对齐。

## Protected Contracts

| Scenario | Checks |
| --- | --- |
| `guardrails_framework_entrypoint_contract` | `Guardrails` entrypoint、MBean name、`CONFIG_PROVIDER`、`DEFAULT_CONFIG`、MBean registration 和 43 个 guardrail field 清单。 |
| `guardrails_config_provider_contract` | custom provider system property、`FBUtilities.construct`、默认 provider 到 `DatabaseDescriptor.getGuardrailsConfig()`。 |
| `guardrails_options_validation_contract` | `Config` defaults、`DatabaseDescriptor` 构造、`GuardrailsOptions` 构造校验、runtime setter 更新、YAML 模板字段。 |
| `guardrails_threshold_contract` | `Threshold` fail-before-warn、redaction、`MaxThreshold`/`MinThreshold` disabled sentinel、`PercentageThreshold` percent formatting。 |
| `guardrails_enable_flag_contract` | `EnableFlag.isEnabled()` 和 `ensureEnabled()` 行为。 |
| `guardrails_values_predicates_contract` | `Values` disallow/ignore/warn 顺序、`Predicates` failure-before-warning。 |
| `guardrails_diagnostics_event_contract` | client warnings、tracing、`DiagnosticEventService` diagnostic WARNED/FAILED event 和 `name`/`message` payload。 |
| `guardrails_mbean_runtime_config_contract` | `GuardrailsMBean` getter/setter、`Guardrails` runtime forwarding、`NodeProbe` JMX proxy、StorageService compatibility wrappers。 |
| `guardrails_nodetool_runtime_config_contract` | `getguardrailsconfig`/`setguardrailsconfig` command names、category enum、snake_case 特例、threshold 参数反转、`null`/`[]` reset 和 nodetool test baseline。 |
| `guardrails_client_bypass_contract` | ordinary-user-only guardrail enablement、super/internal bypass、background/null-state fail 不抛异常。 |
| `guardrails_cql_schema_entrypoints_contract` | schema DDL entrypoints for keyspace/table/view/index/type/RF/drop/truncate/table properties. |
| `guardrails_read_write_entrypoints_contract` | SELECT, modification, batch, collection/list, timestamp, replica disk usage entrypoints. |
| `guardrails_storage_index_background_entrypoints_contract` | SSTable writer、disk monitor、SAI query/term-size background entrypoints. |
| `guardrails_existing_unit_tests_baseline` | framework/unit/nodetool representative tests. |
| `guardrails_existing_distributed_tests_baseline` | distributed guardrail tests for SSTable write, disk usage, index query, intersect filtering. |
| `guardrails_framework_ci_drift_checker_gap` | negative scan: checker is not yet wired into CI/build; if it appears in `.circleci` or `build.xml`, update the gap row. |

## Command

```bash
python3 research/tools/check-guardrails-framework-drift.py
```

Useful options:

```bash
python3 research/tools/check-guardrails-framework-drift.py --json
```

## Update Rules

- If `Guardrails.java` adds/removes a `public static final` guardrail, update the inventory, source map, tests and checker expected list together.
- If a new guardrail type appears, add a source contract row before trusting existing `Threshold`/`EnableFlag`/`Values`/`Predicates` checks.
- If nodetool naming rules change, update both `GuardrailsConfigCommand` expectations and `GuardrailsConfigCommandsTest` anchors.
- If CI starts invoking this checker, remove `guardrails_framework_ci_drift_checker_gap` or change it from a gap into a CI contract.
