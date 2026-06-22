# Module: CQL Trigger Execution Drift Checker

## Scope

`research/tools/check-cql-trigger-execution-drift.py` is a source-only drift checker for `research/module-cql-trigger-execution-matrix.md`. It validates CQL trigger grammar, schema DDL, trigger metadata persistence, classloader/reload behavior, write-path execution, CAS restrictions, audit entries, current unit-test coverage and README/source-map inventory coverage.

## Scenario IDs

| Scenario ID | Protected Contract |
|---|---|
| `cql_trigger_grammar_contract` | Create/drop trigger grammar and raw statement dispatch. |
| `cql_trigger_create_authorization_load_contract` | CREATE TRIGGER authorization, MV rejection, duplicate handling and class preload. |
| `cql_trigger_drop_authorization_contract` | DROP TRIGGER authorization, `IF EXISTS` handling and metadata removal. |
| `cql_trigger_metadata_contract` | `TriggerMetadata` / `Triggers` data model. |
| `cql_trigger_system_schema_contract` | `system_schema.triggers` row contract and fetch path. |
| `cql_trigger_classloader_reload_contract` | Trigger classloader reload, jar scanning and cache clearing. |
| `cql_trigger_directory_config_contract` | `cassandra.triggers_dir` and default `conf/triggers` directory boundary. |
| `cql_trigger_ordinary_write_contract` | Ordinary write path trigger execution through `mutateWithTriggers()`. |
| `cql_trigger_batch_atomic_contract` | Batch/logged atomicity and counter rejection behavior. |
| `cql_trigger_cas_single_partition_contract` | CAS trigger output must remain in the original table and partition. |
| `cql_trigger_validation_contract` | Generated mutation key/update validation. |
| `cql_trigger_nodetool_reload_contract` | `nodetool reloadtriggers` operator route. |
| `cql_trigger_audit_contract` | Trigger DDL audit entry mapping. |
| `cql_trigger_tests_baseline` | Current trigger unit-test baseline. |
| `cql_trigger_distributed_gap` | Current lack of dedicated distributed trigger tests. |

## Design

- `source_checks()` validates Java/ANTLR/config source tokens.
- `test_checks()` validates trigger schema/executor/CQL/audit unit-test anchors and the current distributed-test gap.
- `doc_checks()` validates matrix, checker doc, README and source-map references.
- `check()` returns JSON-friendly source/test/doc results and a pass/fail status.

## Lifecycle

```text
change trigger grammar, schema metadata, TriggerExecutor, StorageProxy write path, or reloadtriggers
  -> run python3 research/tools/check-cql-trigger-execution-drift.py
  -> update matrix, checker doc, README/source-map and source tokens together
  -> if distributed trigger tests are added, replace cql_trigger_distributed_gap with positive coverage
```

## Operational Notes

- This checker does not compile trigger jars or run Cassandra.
- It intentionally records the current absence of dedicated distributed trigger tests so the research KB does not overstate coverage.
- If `reloadtriggers` becomes a schema-aware validation command, update both the matrix and checker scenario semantics.

## Common Failures

- `source token ...` fails: trigger grammar, schema, classloader, write-path or nodetool route changed.
- `test token ...` fails: unit tests were renamed or coverage shifted.
- `doc token ...` fails: README/source-map/matrix/checker inventory missed a scenario or file reference.
- `distributed trigger gap` fails: a dedicated distributed trigger test was added; update this module to document it as positive evidence.

## Verification

- `python3 research/tools/check-cql-trigger-execution-drift.py`
- `python3 research/tools/check-cql-trigger-execution-drift.py --json`
- Related tests: `TriggersTest`, `TriggerExecutorTest`, `TriggersSchemaTest`, `AuditLoggerTest.testCqlTriggerAuditing()`.

