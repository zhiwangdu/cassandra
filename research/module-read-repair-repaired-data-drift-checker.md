# Read Repair And Repaired Data Drift Checker

`research/tools/check-read-repair-repaired-data-drift.py` protects the read repair matrix from source/test/doc drift. It is source-only and fast: it does not start a cluster or execute read repair.

## What It Checks

| Area | Checks |
| --- | --- |
| Strategy | `read_repair` table option and `ReadRepairStrategy` still map `NONE` to read-only reconciliation and `BLOCKING` to blocking repair writes. |
| Digest mismatch | `AbstractReadExecutor` still starts repair only after digest mismatch and rewrites repair timeout to original read CL. |
| Repair reads/writes | `AbstractReadRepair`, `BlockingReadRepair`, `BlockingPartitionRepair`, `ReadOnlyReadRepair` and `NoopReadRepair` still expose the documented read/write behavior. |
| Data resolver | `DataResolver` still wraps repair merge listeners, short-read protection, replica filtering protection and repaired-data verifier close behavior. |
| Tracking/verifier | `RepairedDataTracker` and `RepairedDataVerifier` still classify confirmed/unconfirmed mismatches and snapshotting. |
| Operations | `ReadRepairMetrics`, diagnostic events and `StorageProxyMBean` repaired-data/logging toggles remain aligned. |
| Tests/docs | Unit/distributed tests and README/source-map entries still cover the scenario IDs. |

## Run

```bash
python3 research/tools/check-read-repair-repaired-data-drift.py
```

Expected output:

```text
OK read repair repaired-data drift checks passed (14 scenarios)
```

## Scenario IDs

- `read_repair_strategy_table_option_contract`
- `read_repair_digest_mismatch_entry_contract`
- `read_repair_full_data_read_contract`
- `read_repair_data_resolver_merge_contract`
- `read_repair_blocking_write_contract`
- `read_repair_none_noop_write_contract`
- `read_repair_partition_ack_contract`
- `read_repair_speculative_read_contract`
- `read_repair_speculative_write_contract`
- `read_repair_repaired_data_tracking_contract`
- `read_repair_repaired_data_verifier_contract`
- `read_repair_diagnostic_metrics_contract`
- `read_repair_mbean_operational_contract`
- `read_repair_existing_tests_baseline`

## Maintenance

- If table `read_repair` semantics change, update both the strategy scenario and distributed `ReadRepairTest` anchors.
- If repaired-data tracking moves out of `DataResolver`, add a new scenario instead of weakening the verifier token checks.
- If JMX toggles or mismatch snapshotting are renamed, update the matrix, source-map and checker in one change.
