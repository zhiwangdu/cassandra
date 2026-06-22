# Nodetool Info Drift Checker

`research/tools/check-nodetool-info-drift.py` protects the `nodetool info` observability matrix from source/doc drift. It is source-only: it reads `Info.java`, `NodeProbe`, `StorageServiceMBean`, `StorageService`, cache/buffer metrics, direct distributed tests, README and source-map.

## What It Checks

| Area | Checks |
| --- | --- |
| Command surface | `info` remains registered in `NodeTool` and keeps `-T/--tokens` plus `-O/--out-of-range-ops`. |
| Identity/liveness | Host id, gossip/native state, load, generation, uptime and heap memory still route through the documented MBeans/MXBeans. |
| Off-heap/table metrics | `Info.getOffHeapMemoryUsed()` still sums the documented per-table metrics and `PercentRepaired` still uses global table metrics. |
| Cache metrics | Key/Row/Counter/Chunk cache and Network Cache lines still use the documented Cache/BufferPool JMX ObjectNames and CacheService save-period methods. |
| Ring lifecycle | Token output still checks `isJoined()` and bootstrap/decommission fields still come from `StorageServiceMBean`. |
| Out-of-range ops | `-O` still reads `getOutOfRangeOperationCounts()` and prints read/write/paxos counts. |
| Tests | Direct `NodeToolTest.testInfoOutput()` and adjacent JMX/buffer metrics tests are still present. |
| Docs | Matrix, README, source-map and operations docs mention scenario IDs, paths and checker command. |

## Run

```bash
python3 research/tools/check-nodetool-info-drift.py
```

Expected output:

```text
OK nodetool info checks passed (11 scenarios)
```

Use JSON output for automation:

```bash
python3 research/tools/check-nodetool-info-drift.py --json
```

## Scenario IDs

- `nodetool_info_command_surface_contract`
- `nodetool_info_identity_liveness_contract`
- `nodetool_info_jvm_memory_contract`
- `nodetool_info_topology_exception_contract`
- `nodetool_info_cache_contract`
- `nodetool_info_chunk_network_cache_contract`
- `nodetool_info_table_metric_contract`
- `nodetool_info_token_join_contract`
- `nodetool_info_bootstrap_decommission_contract`
- `nodetool_info_out_of_range_ops_contract`
- `nodetool_info_existing_test_baseline`

## Maintenance

- If `info` adds/removes output fields, update both the field mapping and checker tokens.
- If focused `info -T` / `info -O` tests land, expand the test-baseline scenario instead of treating them as gaps.
- Keep this checker scoped to `nodetool info`; status/ring, tpstats, netstats and proxyhistograms have separate matrices.
