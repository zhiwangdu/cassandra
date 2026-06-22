# Module: Read Operation Monitoring Drift Checker

## Scope

`research/tools/check-read-operation-monitoring-drift.py` is a source-only drift checker for `research/module-read-operation-monitoring-matrix.md`. It validates the read monitoring interface/state machine, `MonitoringTask` queue and log aggregation, local and remote read deadline injection, query cancellation, configuration/JMX/nodetool surfaces, SAI cancellation boundary, test baseline and README/source-map inventory coverage.

## Scenario IDs

| Scenario ID | Protected Contract |
|---|---|
| `read_monitoring_interface_contract` | `Monitorable` method surface for timing, state, cross-node, abort and complete. |
| `read_monitoring_state_machine_contract` | `MonitorableImpl` starts in progress and transitions idempotently to aborted/completed terminal states. |
| `read_monitoring_set_time_contract` | Monitoring time is injected after construction through `setMonitoringTime()`. |
| `read_monitoring_timeout_abort_contract` | Request timeout causes abort and failed-operation queueing. |
| `read_monitoring_slow_complete_contract` | Slow reads are marked while in progress and reported only on successful complete when slow logging is enabled. |
| `read_monitoring_queue_capacity_contract` | `OperationsQueue` supports disabled, bounded, unbounded and dropped-entry behavior. |
| `read_monitoring_log_aggregation_contract` | Failed/slow operations are aggregated by CQL name and formatted with timing/cross-node details. |
| `read_monitoring_remote_verb_contract` | `ReadCommandVerbHandler` injects remote message timestamps, deadline and cross-node flag. |
| `read_monitoring_local_read_contract` | `StorageProxy.LocalReadRunnable` injects local request deadline and records self-dropped messages on timeout. |
| `read_monitoring_query_cancellation_contract` | `ReadCommand` iterator transformation periodically throws `QueryCancelledException` after abort. |
| `read_monitoring_config_contract` | YAML/default config and `DatabaseDescriptor` preserve read/range/slow-query timeout semantics. |
| `read_monitoring_jmx_nodetool_timeout_contract` | `StorageService`/`NodeProbe` expose read/range timeout runtime controls. |
| `read_monitoring_sai_query_context_boundary` | SAI `QueryContext` cancellation remains a related but separate quota boundary. |
| `read_monitoring_tests_baseline` | Unit tests cover monitoring state/aggregation and read command abort behavior. |
| `read_monitoring_coordinator_timeout_boundary` | Coordinator timeout behavior stays documented in the StorageProxy coordinator matrix. |

## Design

- `source_checks()` validates Java/config/YAML tokens for read monitoring, logging, local/remote read entrypoints, config and SAI boundary.
- `test_checks()` validates `MonitoringTaskTest`, `ReadCommandTest` and config parsing/clamping test anchors.
- `doc_checks()` validates matrix, checker doc, README and source-map references.
- `check()` returns JSON-friendly source/test/doc results and a pass/fail status.

## Lifecycle

```text
change MonitorableImpl, MonitoringTask, ReadCommand cancellation, read verb handling, StorageProxy local read, timeout config, or SAI quota behavior
  -> run python3 research/tools/check-read-operation-monitoring-drift.py
  -> update matrix, checker doc, README/source-map and source tokens together
  -> if MonitoringTask gets metrics or CI coverage, add positive scenarios instead of extending generic docs
```

## Operational Notes

- This checker does not run Cassandra or read debug logs.
- It intentionally separates replica/local read monitoring from coordinator `ReadCallback` timeout contracts.
- It treats SAI `QueryContext` as a boundary scenario because it reuses `QueryCancelledException` but does not by itself enqueue `MonitoringTask` operations.

## Common Failures

- `source token ...` fails: monitoring state, queue/logging behavior, read entrypoints, config or SAI boundary changed.
- `test token ...` fails: existing unit/config test coverage moved or was renamed.
- `doc token ...` fails: README/source-map/matrix/checker inventory missed a scenario or file reference.
- `coordinator boundary` fails: the StorageProxy coordinator matrix/checker reference changed and this module must be retargeted.

## Verification

- `python3 research/tools/check-read-operation-monitoring-drift.py`
- `python3 research/tools/check-read-operation-monitoring-drift.py --json`
- Related tests: `MonitoringTaskTest`, `ReadCommandTest`, `ParseAndConvertUnitsTest`, `LoadOldYAMLBackwardCompatibilityTest`, `DatabaseDescriptorTest.testLowestAcceptableTimeouts()`.
