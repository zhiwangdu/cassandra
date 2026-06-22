# Nodetool Cache Runtime Drift Checker

`research/tools/check-nodetool-cache-runtime-drift.py` protects the nodetool cache runtime matrix from source/doc drift. It reads nodetool cache command classes, `NodeTool`, `NodeProbe`, `CacheServiceMBean`, `CacheService`, `AutoSavingCache`, `NopCacheProvider`, `nodetool info`, `system_views.caches`, cache tests, README and source-map.

## What It Checks

| Area | Checks |
| --- | --- |
| Command registry | `NodeTool` still registers invalidate key/row/counter cache, `setcachecapacity` and `setcachekeystosave`. |
| CLI surface | Cache mutation commands keep their command names, required three-argument contracts and `NodeProbe` calls. |
| NodeProbe route | Cache commands still route through `org.apache.cassandra.db:type=Caches` and `CacheServiceMBean`. |
| Runtime side effects | Capacity setters update bytes, keys-to-save setters update `DatabaseDescriptor` and reschedule autosaving, invalidation clears global caches. |
| Disabled row cache | `NopCacheProvider` still rejects non-zero capacity and the distributed nodetool failure test remains present. |
| Observability | `nodetool info`, `NodeProbe.getCacheMetric()` and `system_views.caches` still expose cache metrics and save-period state. |
| Tests/gaps | Existing cache primitive tests remain present; direct CLI success and `system_views.caches` focused tests remain documented gaps. |
| Docs | Matrix, README, source-map, operations and observability docs mention scenario IDs, paths and checker command. |

## Run

```bash
python3 research/tools/check-nodetool-cache-runtime-drift.py
```

Expected output:

```text
OK nodetool cache runtime checks passed (12 scenarios)
```

Use JSON output for automation:

```bash
python3 research/tools/check-nodetool-cache-runtime-drift.py --json
```

## Scenario IDs

- `nodetool_cache_command_registry_contract`
- `nodetool_cache_invalidation_command_contract`
- `nodetool_cache_capacity_command_contract`
- `nodetool_cache_keys_to_save_command_contract`
- `nodetool_cache_nodeprobe_mbean_route_contract`
- `cache_service_capacity_side_effect_contract`
- `cache_service_keys_schedule_contract`
- `cache_service_global_clear_contract`
- `cache_disabled_row_cache_failure_contract`
- `cache_info_and_virtual_table_observability_contract`
- `nodetool_cache_existing_test_baseline`
- `nodetool_cache_operator_gap`

## Maintenance

- If cache command names or argument order changes, update the matrix and checker in the same change.
- If cache mutation commands move off `CacheServiceMBean`, update the NodeProbe/MBean route contract.
- If focused CLI or `system_views.caches` tests are added, replace the gap scenario with the concrete coverage and remove the negative test scan.
