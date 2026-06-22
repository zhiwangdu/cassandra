# Configuration Loading Drift Checker

`research/tools/check-configuration-loading-drift.py` protects the configuration loading/runtime matrix from source drift. It is intentionally source-only and fast: it does not start Cassandra, parse YAML with Java, or run unit tests.

## What It Checks

| Area | Checks |
| --- | --- |
| Source tokens | `Config`, `DatabaseDescriptor`, `YamlConfigurationLoader`, `DefaultLoader`, `Properties`, `Replacement`, `Replacements`, `Converters`, `CassandraRelevantProperties`, `ParameterizedClass`, `InheritingClass`, `Redacted`, `SettingsTable`, `StorageService` and `StorageServiceMBean` still contain the documented methods, constants and side effects. |
| Counts | Protects current structural baselines: 414 non-static public field-style config declarations, 96 `Config` `@Replaces`, 22 converter enum entries, 328 relevant system properties, 27 `system_views.settings` compatibility names and 439 runtime setter declarations across `DatabaseDescriptor`/`StorageService`/`StorageServiceMBean`. |
| Templates | Protects the compatible/latest distribution templates, `test/conf/latest_diff.yaml`, dtest latest-mode overrides and old/default test YAML fixtures. |
| Tests | Ensures the matrix still points to loader selection, YAML/update map, system property overlay, converter, old YAML, compatibility diff, duplicate key, property flatten and typed system property tests. |
| Docs | Ensures every `config_*` scenario appears in the matrix and checker docs, and that `README.md` plus `notes/source-map.md` link the new matrix and script. |
| Gap | Confirms this research checker is not yet wired into `build.xml` or `.circleci/config.yml`; if it becomes a CI gate, the documented gap must be updated. |

## Run

```bash
python3 research/tools/check-configuration-loading-drift.py
```

Expected output:

```text
OK configuration loading drift checks passed (414 config fields, 96 replacements, 22 converters, 328 system properties, 27 settings aliases, 439 runtime setters, 17 scenarios)
```

## Scenario IDs

- `config_model_field_contract`
- `config_database_descriptor_modes_contract`
- `config_loader_selection_contract`
- `config_yaml_url_and_empty_file_contract`
- `config_yaml_property_checker_contract`
- `config_duplicate_and_replacement_guard_contract`
- `config_compat_replacement_converter_contract`
- `config_system_property_overlay_contract`
- `config_template_defaults_contract`
- `config_parameterized_nested_contract`
- `config_unit_spec_contract`
- `config_apply_simple_validation_contract`
- `config_settings_virtual_table_contract`
- `config_runtime_jmx_setter_contract`
- `config_guardrails_startup_checks_contract`
- `config_existing_unit_tests_baseline`
- `config_ci_drift_checker_gap`

## Maintenance

- If a new YAML field is added, update `Config`, default YAML templates, tests, this matrix and the expected field count.
- If an old config name changes, update `@Replaces`, converter coverage, compatibility tests and the replacement count.
- If a `StorageServiceMBean` setter is added/removed, update the runtime setter count and document whether it has side effects beyond mutating `DatabaseDescriptor`.
- If the checker is added to CI, remove or rewrite `config_ci_drift_checker_gap` in both matrix and checker.
