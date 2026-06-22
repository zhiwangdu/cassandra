# Nodetool Status/Ring Drift Checker

`research/tools/check-nodetool-status-ring-drift.py` protects the `nodetool status` / `nodetool ring` observability matrix from source/doc drift. It is source-only: it reads nodetool command source, `NodeProbe`, `StorageServiceMBean`, `StorageService`, snitch MBean, distributed tests, README and source-map.

## What It Checks

| Area | Checks |
| --- | --- |
| Command surface | `Status` and `Ring` remain registered nodetool commands with keyspace and `-r/--resolve-ip` surfaces. |
| JMX snapshot | Both commands still read with-port live/down/join/leave/move, token, load, ownership and snitch data through `NodeProbe`. |
| State rendering | `status` still renders `U/D/?` plus `J/L/M/N`; `ring` still renders `Up/Down/?` plus `Normal/Joining/Leaving/Moving`. |
| StorageService MBean | The with-port MBean methods used by these commands remain available and backed by token metadata, `Gossiper`, `LoadBroadcaster` and ownership code. |
| Ownership fallback | Both commands still prefer `effectiveOwnershipWithPort(keyspace)` and fall back to `getOwnershipWithPort()` on `IllegalStateException`. |
| Snitch grouping | DC grouping and rack rendering still use `EndpointSnitchInfoMBean`. |
| Tests | The checker verifies the current ring/status distributed-test baseline in `NodeToolTest`, `JMXFeatureTest` and `ClusterUtils`. |
| Docs | Matrix, README, source-map and operations docs mention scenario IDs, paths and checker command. |

## Run

```bash
python3 research/tools/check-nodetool-status-ring-drift.py
```

Expected output:

```text
OK nodetool status/ring checks passed (10 scenarios)
```

Use JSON output for automation:

```bash
python3 research/tools/check-nodetool-status-ring-drift.py --json
```

## Scenario IDs

- `nodetool_status_command_surface_contract`
- `nodetool_status_jmx_snapshot_contract`
- `nodetool_status_state_rendering_contract`
- `nodetool_ring_command_surface_contract`
- `nodetool_ring_state_rendering_contract`
- `nodetool_status_ring_with_port_mbean_contract`
- `nodetool_status_ring_tokenmetadata_source_contract`
- `nodetool_status_ring_ownership_fallback_contract`
- `nodetool_status_ring_snitch_grouping_contract`
- `nodetool_status_ring_distributed_test_baseline`

## Maintenance

- If status/ring output columns or state markers change, update the matrix, parser/test references and any runbooks that parse `UN`/`DN` or `Up`/`Down`.
- If StorageService removes deprecated no-port MBean methods, keep this checker focused on the with-port path these commands use.
- If focused tests for `-r`, `-pp`, vnode warning or ownership fallback land, cite them in the matrix and extend the test baseline checks.
