# Nodetool TableHistograms Drift Checker

`research/tools/check-nodetool-tablehistograms-drift.py` protects the `nodetool tablehistograms` observability matrix from source/doc drift. It is source-only: it reads `TableHistograms`, `NodeTool`, `NodeProbe`, `TableMetrics`, `CassandraMetricsRegistry`, direct nodetool tests, metric primitive tests, README and source-map.

## What It Checks

| Area | Checks |
| --- | --- |
| Command surface | `tablehistograms` remains registered and keeps the documented optional positional argument forms. |
| Table selection | No-arg all-table mode still enumerates CFS MBeans, `ks.table` parsing remains, and bad argument forms still throw the documented error. |
| Metric sources | The command still reads `EstimatedPartitionSizeHistogram`, `EstimatedColumnCountHistogram`, `ReadLatency`, `WriteLatency` and `SSTablesPerReadHistogram`. |
| Percentiles | The row order remains `50%`, `75%`, `95%`, `98%`, `99%`, `Min`, `Max`, and `NodeProbe.metricPercentilesAsArray()` keeps the same array order. |
| JMX mapping | `getColumnFamilyMetric()` still builds table/index-table ObjectNames and returns gauge/timer/histogram proxies for the documented metrics. |
| TableMetrics | The underlying metrics still come from canonical SSTable estimated histograms, table read/write latency and SSTables-per-read histograms. |
| Tests | Direct `TableHistogramsTest` coverage and adjacent histogram metric tests are still present. |
| Docs | Matrix, README, source-map and operations docs mention scenario IDs, paths and checker command. |

## Run

```bash
python3 research/tools/check-nodetool-tablehistograms-drift.py
```

Expected output:

```text
OK nodetool tablehistograms checks passed (10 scenarios)
```

Use JSON output for automation:

```bash
python3 research/tools/check-nodetool-tablehistograms-drift.py --json
```

## Scenario IDs

- `tablehistograms_command_surface_contract`
- `tablehistograms_table_selection_contract`
- `tablehistograms_metric_source_contract`
- `tablehistograms_estimated_histogram_contract`
- `tablehistograms_percentile_order_contract`
- `tablehistograms_output_column_contract`
- `tablehistograms_nodeprobe_jmx_contract`
- `tablehistograms_tablemetrics_definition_contract`
- `tablehistograms_jmx_percentile_mbean_contract`
- `tablehistograms_existing_test_baseline`

## Maintenance

- If `tablehistograms` adds JSON/YAML output or new metric columns, update the field mapping and checker token list.
- If tests begin asserting non-empty percentile values, update the test-baseline scenario and remove the remaining-gap note.
- Keep this checker scoped to table-local histograms; `proxyhistograms`, `tpstats`, `netstats`, `info` and status/ring each have separate matrices.
