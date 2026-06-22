# Materialized View Build Status Drift Checker

`research/tools/check-materialized-view-build-status-drift.py` protects `research/module-materialized-view-build-status-matrix.md` from source/test/doc drift. It is source-only and does not start Cassandra.

## What It Checks

| Area | Checks |
| --- | --- |
| Source | `ViewManager`, `View`, `ViewBuilder`, `ViewBuilderTask`, `SystemKeyspace`, `SystemDistributedKeyspace`, `CompactionManager`, `StorageService`, nodetool commands and config still expose the documented build/status behavior. |
| Tests | Existing focused tests still cover range task replay, builder resume, truncate cancellation and active compaction tracking. |
| Docs | Matrix, checker docs, README, source-map and `flow-materialized-view.md` mention the scenario IDs, commands and checker path. |
| Gap scan | No focused Java test currently covers `viewbuildstatus`, `getconcurrentviewbuilders` or `setconcurrentviewbuilders` CLI behavior. |

## Run

```bash
python3 research/tools/check-materialized-view-build-status-drift.py
```

Expected output:

```text
OK materialized view build status checks passed (12 scenarios)
```

Use JSON for automation:

```bash
python3 research/tools/check-materialized-view-build-status-drift.py --json
```

## Scenario IDs

- `mv_build_schema_reload_gate`
- `mv_build_local_built_status_contract`
- `mv_build_distributed_status_contract`
- `mv_build_range_checkpoint_resume_contract`
- `mv_build_task_mutation_replay_contract`
- `mv_build_executor_compaction_info_contract`
- `mv_build_stop_retry_contract`
- `mv_build_nodetool_status_contract`
- `mv_build_concurrency_config_contract`
- `mv_build_bootstrap_mark_built_contract`
- `mv_build_existing_tests_baseline`
- `mv_build_operator_cli_gap`

## Maintenance

- If `ViewBuilder` / `ViewBuilderTask` checkpoint or retry behavior changes, update the matrix and this checker together.
- If nodetool CLI tests land, replace `mv_build_operator_cli_gap` with concrete test anchors and remove the negative scan.
- If `system_distributed.view_build_status` columns change, update this matrix, `module-system-distributed-state-matrix.md` and `module-system-table-column-contract.md` together.
