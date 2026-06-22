# Materialized View Paired Replica Drift Checker

`research/tools/check-materialized-view-paired-replica-drift.py` protects `research/module-materialized-view-paired-replica-matrix.md` from source/test/doc drift. It is source-only and does not start Cassandra.

## What It Checks

| Area | Checks |
| --- | --- |
| Source | `ViewUtils`, `StorageProxy.mutateMV()`, `TokenMetadata.pendingEndpointsForToken()`, `Stage.VIEW_MUTATION`, `ViewWriteMetrics` and `DatabaseDescriptor` still expose the documented pairing and fallback behavior. |
| Tests | Existing `ViewUtilsTest`, local MV cleanup test and `CQLTester.waitForViewMutations()` anchors remain present. |
| Docs | Matrix, checker docs, README, source-map and `flow-materialized-view.md` mention the scenario IDs, checker path and current gap. |
| Gap scan | No distributed Java test currently combines materialized views with move/decommission/bootstrap/pending-range behavior. |

## Run

```bash
python3 research/tools/check-materialized-view-paired-replica-drift.py
```

Expected output:

```text
OK materialized view paired replica checks passed (12 scenarios)
```

Use JSON for automation:

```bash
python3 research/tools/check-materialized-view-paired-replica-drift.py --json
```

## Scenario IDs

- `mv_pair_viewutils_cardinality_contract`
- `mv_pair_local_view_replica_preference`
- `mv_pair_local_dc_filter_contract`
- `mv_pair_shared_endpoint_filter_contract`
- `mv_pair_non_base_replica_empty_contract`
- `mv_pair_starting_batchlog_contract`
- `mv_pair_pending_endpoint_write_contract`
- `mv_pair_local_apply_fastpath_contract`
- `mv_pair_remote_stage_contract`
- `mv_pair_batchlog_metrics_contract`
- `mv_pair_existing_tests_baseline`
- `mv_pair_range_movement_distributed_gap`

## Maintenance

- If `ViewUtils.getViewNaturalEndpoint()` changes pairing semantics, update the matrix before adjusting tokens.
- If a distributed MV topology test lands, replace `mv_pair_range_movement_distributed_gap` with concrete test anchors and remove the negative scan.
- If `Stage.VIEW_MUTATION` or `ViewWriteMetrics` changes names, update observability docs and checker inventory together.
