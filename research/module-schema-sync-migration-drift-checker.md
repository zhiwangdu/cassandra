# Schema Sync Migration Drift Checker

`research/tools/check-schema-sync-migration-drift.py` protects the schema sync migration matrix from source/test/doc drift. It is source-only and does not start Cassandra.

## What It Checks

| Area | Checks |
| --- | --- |
| Handler contract | `SchemaUpdateHandler` still exposes start/readiness/apply/reset/clear, and `DefaultSchemaUpdateHandler` still registers gossip push/pull handlers. |
| Local and remote apply | DDL transformation diff -> `SchemaKeyspace` mutations -> digest -> `DistributedSchema`, and remote mutations still merge through affected-keyspace refresh. |
| Version tracking | `MigrationCoordinator` still tracks endpoint versions, outstanding requests, request queues, ignored endpoints/versions and wait signals. |
| Pull/push gates | Pull still enforces endpoint compatibility and liveness; push still targets only viable peers with current messaging version. |
| Reset/clear | local reload, remote reset/await and clear/truncate-on-first-non-empty-schema behavior remain documented. |
| Wire and diagnostics | schema verbs, mutation serializer and `SchemaAnnouncementEvent` diagnostics remain aligned with the matrix. |
| Tests/docs | Existing unit/distributed tests and README/source-map entries still cite the scenario IDs and checker. |

## Run

```bash
python3 research/tools/check-schema-sync-migration-drift.py
```

Expected output:

```text
OK schema sync migration drift checks passed (12 scenarios)
```

## Scenario IDs

- `schema_sync_handler_interface_contract`
- `schema_sync_default_handler_registration`
- `schema_sync_apply_diff_mutation_contract`
- `schema_sync_remote_mutation_merge_contract`
- `schema_sync_announce_and_startup_wait_contract`
- `schema_sync_endpoint_version_tracking_contract`
- `schema_sync_pull_selection_compatibility_contract`
- `schema_sync_pull_retry_await_contract`
- `schema_sync_push_viable_nodes_contract`
- `schema_sync_reset_clear_contract`
- `schema_sync_verb_serializer_diagnostics_contract`
- `schema_sync_disagreement_tests_baseline`

## Maintenance

- If `SchemaUpdateHandler` gains a new backend capability, add a scenario instead of folding it into the default handler row.
- If schema wire verbs or serializers change, update the verb/serializer scenario and the corresponding source-map anchors together.
- If startup schema wait behavior changes, update `schema_sync_announce_and_startup_wait_contract` and the distributed ignore/replace tests baseline.
