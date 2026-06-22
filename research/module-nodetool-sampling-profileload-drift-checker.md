# Nodetool Sampling And ProfileLoad Drift Checker

`research/tools/check-nodetool-sampling-profileload-drift.py` protects the `profileload` / `toppartitions` sampling matrix from source/doc drift. It is source-only: it reads nodetool command classes, `NodeProbe`, `StorageServiceMBean`, `StorageService`, `SamplingManager`, sampler implementations, table metrics, update sites, direct unit/distributed tests, README and source-map.

## What It Checks

| Area | Checks |
| --- | --- |
| Command surface | `profileload` and deprecated `toppartitions` remain registered and route to `ProfileLoad`. |
| Argument guards | Capacity, top-K, duration, interval and sampler name validation stay in place. |
| Blocking sampling | All-table/all-keyspace and single-table paths still use `samplePartitions()` or CFS `beginLocalSampling()` / `finishLocalSampling()`. |
| Scheduled sampling | `--interval`, `--list` and `--stop` still route through `StorageService` and `SamplingManager`. |
| Sampling manager | Job overlap rejection, begin/end background cycle, cancellation and log formatting remain documented. |
| Sampler types | `SamplerType` output families, `FrequencySampler`, `MaxSampler` and executor model stay aligned with the matrix. |
| Update sites | Read/write/local read/CAS sampler update sites still call the documented table samplers. |
| Tests | Unit and distributed `TopPartitionsTest` / `ProfileLoadTest` baselines remain present. |
| Docs | Matrix, README, source-map, operations and observability mapping docs mention scenario IDs, paths and checker command. |

## Run

```bash
python3 research/tools/check-nodetool-sampling-profileload-drift.py
```

Expected output:

```text
OK nodetool sampling/profileload checks passed (12 scenarios)
```

Use JSON output for automation:

```bash
python3 research/tools/check-nodetool-sampling-profileload-drift.py --json
```

## Scenario IDs

- `profileload_command_surface_contract`
- `profileload_argument_guard_contract`
- `profileload_sampler_selection_contract`
- `profileload_blocking_sample_contract`
- `profileload_scheduled_job_contract`
- `samplingmanager_overlap_contract`
- `samplingmanager_background_cycle_contract`
- `sampler_type_output_contract`
- `sampler_execution_model_contract`
- `tablemetrics_sampler_registration_contract`
- `sampling_update_sites_contract`
- `profileload_existing_test_baseline`

## Maintenance

- If a new `SamplerType` is added, update sampler output mapping, TableMetrics registration and checker token lists.
- If scheduled sampling moves off `ScheduledExecutors.optionalTasks`, update the background cycle contract and tests.
- Keep this checker scoped to sampling/profiling commands; tablehistograms, proxyhistograms, tpstats, netstats and status/ring have separate matrices.
