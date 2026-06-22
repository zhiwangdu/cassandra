# Nodetool Routing And Locator Drift Checker

`research/tools/check-nodetool-routing-locators-drift.py` protects the `nodetool getendpoints` / `getsstables` / `describering` routing and locator matrix from source/doc drift. It is source-only: it reads nodetool command classes, `NodeTool`, `NodeProbe`, `StorageServiceMBean`, `StorageService`, `TokenRange`, `ColumnFamilyStoreMBean`, `ColumnFamilyStore`, direct tests, README and source-map.

## What It Checks

| Area | Checks |
| --- | --- |
| Command registry | `DescribeRing`, `GetEndpoints` and `GetSSTables` remain registered by `NodeTool.execute()`. |
| `getendpoints` | Argument count, with-port branch, legacy branch and `NodeProbe` to `StorageServiceMBean` routes remain intact. |
| Natural endpoint source | `StorageService` still decodes keys through table metadata, tokenizes with the partitioner and asks the replication strategy for natural replicas. |
| `describering` | Schema/version header, with-port JMX route, missing-keyspace/LocalStrategy errors and `TokenRange.toString()` compatibility fields remain documented. |
| `getsstables` | `-hf/--hex-format`, `-l/--show-levels`, LCS gating, CFS MBean methods and live-SSTable key lookup remain intact. |
| Tests | Existing direct and adjacent coverage for `getsstables`, boolean composite key parsing and with-port natural endpoints still exists. |
| Docs | Matrix, README, source-map and operations docs mention scenario IDs, paths and checker command. |

## Run

```bash
python3 research/tools/check-nodetool-routing-locators-drift.py
```

Expected output:

```text
OK nodetool routing/locator checks passed (10 scenarios)
```

Use JSON output for automation:

```bash
python3 research/tools/check-nodetool-routing-locators-drift.py --json
```

## Scenario IDs

- `nodetool_routing_command_registry_contract`
- `nodetool_getendpoints_surface_contract`
- `nodetool_getendpoints_mbean_route_contract`
- `nodetool_getendpoints_partition_key_contract`
- `nodetool_describering_surface_contract`
- `nodetool_describering_storage_contract`
- `nodetool_describering_tokenrange_format_contract`
- `nodetool_getsstables_surface_contract`
- `nodetool_getsstables_cfs_contract`
- `nodetool_routing_existing_test_baseline`

## Maintenance

- If `getendpoints`, `describering` or `getsstables` gains output flags, update the command surface scenario and field/failure table.
- If focused distributed nodetool tests land for with-port endpoints, `describering --print-port`, hex keys or LCS levels, expand the test-baseline scenario instead of leaving them as gaps.
- Keep this checker scoped to key location and range/SSTable lookup commands; status/ring, info, tpstats, netstats and proxyhistograms have separate matrices.
