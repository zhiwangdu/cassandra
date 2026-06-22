# Nodetool Snapshot Lifecycle Drift Checker

`research/tools/check-nodetool-snapshot-lifecycle-drift.py` protects the nodetool snapshot lifecycle matrix from source/doc drift. It reads nodetool snapshot command classes, `NodeTool`, `NodeProbe`, `StorageServiceMBean`, `StorageService`, snapshot service classes, CFS/Keyspace snapshot creation, snapshot virtual table/tests, README and source-map.

## What It Checks

| Area | Checks |
| --- | --- |
| Command registry | `NodeTool` still registers `snapshot`, `clearsnapshot`, `listsnapshots`, `getsnapshotthrottle` and `setsnapshotthrottle`. |
| CLI surface | Snapshot take/clear/list/throttle commands keep their command names, option names, validation guards and `NodeProbe` calls. |
| NodeProbe route | Snapshot create, clear, list, true-size and throttle paths still route through `StorageServiceMBean`. |
| Storage dispatch | `StorageService` still parses TTL/skipFlush, enforces minimum TTL, validates table-list snapshots and uses shared creation timestamps. |
| Snapshot creation | `Keyspace` and `ColumnFamilyStore` still create hard links, write manifest/schema metadata, apply skip-flush semantics and register expiring snapshots. |
| Cleanup | `clearsnapshot` age filters, `TableSnapshot.shouldClearSnapshot()`, ephemeral refusal and `SnapshotManager` TTL cleanup remain intact. |
| Observability | `listsnapshots`, `SnapshotDetailsTabularData` and `system_views.snapshots` still expose size, timestamps and ephemeral state. |
| Config | `snapshot_before_compaction`, `auto_snapshot`, `auto_snapshot_ttl`, `snapshot_links_per_second` and snapshot TTL properties remain documented. |
| Tests/gaps | Existing snapshot lifecycle and option-guard tests remain present; snapshot throttle and skip-flush content assertions remain documented gaps. |
| Docs | Matrix, README, source-map, operations and observability docs mention scenario IDs, paths and checker command. |

## Run

```bash
python3 research/tools/check-nodetool-snapshot-lifecycle-drift.py
```

Expected output:

```text
OK nodetool snapshot lifecycle checks passed (16 scenarios)
```

Use JSON output for automation:

```bash
python3 research/tools/check-nodetool-snapshot-lifecycle-drift.py --json
```

## Scenario IDs

- `nodetool_snapshot_command_registry_contract`
- `nodetool_snapshot_take_command_surface_contract`
- `nodetool_snapshot_take_validation_route_contract`
- `nodetool_snapshot_clear_command_guard_contract`
- `nodetool_snapshot_list_command_observability_contract`
- `nodetool_snapshot_throttle_command_contract`
- `snapshot_nodeprobe_mbean_route_contract`
- `snapshot_storage_ttl_dispatch_contract`
- `snapshot_storage_keyspace_table_atomicity_contract`
- `snapshot_cfs_manifest_hardlink_contract`
- `snapshot_clear_filter_ephemeral_contract`
- `snapshot_manager_ttl_cleanup_contract`
- `snapshot_listing_virtual_table_contract`
- `snapshot_config_autosnapshot_contract`
- `snapshot_existing_test_baseline`
- `snapshot_operator_gap`

## Maintenance

- If snapshot command names, option names or validation rules change, update the matrix and checker in the same change.
- If snapshot lifecycle moves off `StorageServiceMBean`, update the NodeProbe route contract.
- If focused throttle tests are added, replace the gap scenario with concrete test anchors and remove the negative gap scans.
