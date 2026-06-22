# Tpstats ThreadPool Observability Drift Checker

`research/tools/check-tpstats-threadpool-observability-drift.py` protects the `tpstats` thread-pool/dropped-message observability matrix from source/doc drift. It is source-only and reads nodetool, NodeProbe, metrics, virtual table, tests, README and source-map.

## What It Checks

| Area | Checks |
| --- | --- |
| Command | `TpStats` still exposes only `-F` / `--format`, accepts `json`/`yaml`, and rejects other format values. |
| Holder | `TpStatsHolder.convert2Map()` still emits `ThreadPools`, `DroppedMessage` and `WaitLatencies`, with the documented five thread-pool metrics. |
| Printer | Default output still prints the pool header and dropped-message latency table with `50%`、`95%`、`99%`、`Max`. |
| NodeProbe | Thread-pool names still come from the `ThreadPools` JMX ObjectName query; gauge vs counter wrappers and `N/A` behavior remain intact. |
| Metrics | `ThreadPoolMetrics` still defines/registers the 8 metric names, and `ThreadPoolsTable` remains a same-source virtual table boundary. |
| Dropped messages | `MessagingMetrics.getDroppedMessages()` still returns lifetime dropped counts and recent dropped-message logging still calls `StatusLogger.log()`. |
| Tests | `TpStatsTest`、`ThreadPoolMetricsTest` and `MessagingServiceTest` keep the relevant output/metric anchors. |
| Docs | Matrix, README, source-map and operations observability docs mention scenario IDs, checker path and key source files. |

## Run

```bash
python3 research/tools/check-tpstats-threadpool-observability-drift.py
```

Expected output:

```text
OK tpstats threadpool observability checks passed (10 scenarios)
```

Use JSON output for automation:

```bash
python3 research/tools/check-tpstats-threadpool-observability-drift.py --json
```

## Scenario IDs

- `tpstats_command_format_contract`
- `tpstats_holder_threadpool_map_contract`
- `tpstats_holder_dropped_latency_contract`
- `tpstats_default_printer_contract`
- `tpstats_nodeprobe_threadpool_jmx_contract`
- `tpstats_nodeprobe_metric_wrapper_contract`
- `tpstats_threadpool_metrics_registry_contract`
- `tpstats_threadpool_virtual_table_boundary`
- `tpstats_dropped_message_metrics_contract`
- `tpstats_existing_tests_baseline`

## Maintenance

- If `tpstats` gains a new format or option, update command contract, help-test references and checker tokens together.
- If `ThreadPoolMetrics` adds/removes metrics, decide whether `tpstats` should expose them or leave them to JMX/system_views, then update matrix wording.
- If JSON/YAML schema gets a focused golden test, replace the remaining gap with that test anchor.
- Keep this checker focused on `tpstats`; broader metrics registry and external dashboard drift remain in `check-metrics-registry-drift.py` and `check-external-observability-drift.py`.
