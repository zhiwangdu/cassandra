# ProxyHistograms ClientRequest Drift Checker

`research/tools/check-proxyhistograms-clientrequest-drift.py` protects the `proxyhistograms` client request latency matrix from source/doc drift. It is source-only: it reads nodetool source, `NodeProbe`, client request metrics, update sites, tests, README and source-map.

## What It Checks

| Area | Checks |
| --- | --- |
| Command surface | `ProxyHistograms` remains a no-option nodetool command and stays registered in `NodeTool`. |
| Percentile/order | The command still prints `50%`、`75%`、`95%`、`98%`、`99%`、`Min`、`Max` in `metricPercentilesAsArray()` order. |
| JMX scopes | The six scopes remain `Read`、`Write`、`RangeSlice`、`CASRead`、`CASWrite`、`ViewWrite`. |
| NodeProbe | `getProxyMetric()` still reads `org.apache.cassandra.metrics:type=ClientRequest,scope=<scope>,name=Latency` through `JmxTimerMBean`. |
| Update sites | StorageProxy, RangeCommandIterator, Paxos and ViewWriteMetrics update the documented latency metrics. |
| Test gap | The checker fails if a direct `proxyhistograms`/`ProxyHistograms` Java test appears, forcing the matrix to replace `proxyhistograms_test_gap` with concrete coverage. |
| Docs | Matrix, README, source-map and observability docs mention scenario IDs, paths and checker command. |

## Run

```bash
python3 research/tools/check-proxyhistograms-clientrequest-drift.py
```

Expected output:

```text
OK proxyhistograms client request checks passed (10 scenarios)
```

Use JSON output for automation:

```bash
python3 research/tools/check-proxyhistograms-clientrequest-drift.py --json
```

## Scenario IDs

- `proxyhistograms_command_surface_contract`
- `proxyhistograms_percentile_order_contract`
- `proxyhistograms_metric_scope_contract`
- `proxyhistograms_output_column_contract`
- `proxyhistograms_nodeprobe_jmx_contract`
- `proxyhistograms_read_write_update_contract`
- `proxyhistograms_range_update_contract`
- `proxyhistograms_cas_update_contract`
- `proxyhistograms_viewwrite_update_contract`
- `proxyhistograms_test_gap`

## Maintenance

- If a scope is renamed or added, update `EXPECTED_SCOPES`, the output table and any exporter/JMX mapping notes.
- If a direct command test lands, remove the negative test-gap predicate and cite the new test.
- Keep this checker focused on coordinator client request histograms; table-local histograms and virtual metric tables remain separate research surfaces.
