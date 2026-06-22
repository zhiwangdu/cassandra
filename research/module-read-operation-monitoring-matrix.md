# Module: Read Operation Monitoring Matrix

## Scope

This matrix covers Cassandra's local read operation monitoring contract: how replica-side and local coordinator reads inherit request deadlines, how `ReadCommand` cancellation is checked while iterating rows, how timed-out and slow reads are aggregated into logs, and how the current tests protect that behavior. It is adjacent to coordinator read timeouts and `ReadCallback` behavior in `research/module-storageproxy-coordinator-timeout-matrix.md`, but the focus here is the in-progress local read state machine and `MonitoringTask` reporting path.

Current source baseline:

- `AbstractReadQuery` extends `MonitorableImpl`, so every `ReadCommand` is monitorable before the local read iterator is consumed, see `src/java/org/apache/cassandra/db/AbstractReadQuery.java:32`.
- `Monitorable` defines the read-monitoring surface: name, creation time, timeout, slow timeout, state predicates, cross-node flag, `abort()` and `complete()`, see `src/java/org/apache/cassandra/db/monitoring/Monitorable.java:21`.
- `MonitorableImpl.setMonitoringTime()` records approximate creation time, cross-node flag, request timeout and slow-query timeout after the read command has been deserialized or scheduled, see `src/java/org/apache/cassandra/db/monitoring/MonitorableImpl.java:43`.
- `MonitorableImpl.check()` uses `approxTime.now() - approxCreationTimeNanos - approxTime.error()`; it marks reads slow after `slowTimeoutNanos` and aborts after `timeoutNanos`, see `src/java/org/apache/cassandra/db/monitoring/MonitorableImpl.java:124`.
- `abort()` enqueues a failed operation exactly once and moves `IN_PROGRESS -> ABORTED`; `complete()` enqueues a slow operation only if the read was slow and `slowTimeoutNanos > 0`, then moves `IN_PROGRESS -> COMPLETED`, see `src/java/org/apache/cassandra/db/monitoring/MonitorableImpl.java:96` and `src/java/org/apache/cassandra/db/monitoring/MonitorableImpl.java:110`.
- `MonitoringTask` is a scheduled singleton with failed and slow `OperationsQueue` instances, controlled by `cassandra.monitoring_report_interval_ms` and `cassandra.monitoring_max_operations`, see `src/java/org/apache/cassandra/db/monitoring/MonitoringTask.java:56` and `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:360`.
- Remote replica reads set monitoring time from internode message timestamps and preserve `message.isCrossNode()` in the log suffix, see `src/java/org/apache/cassandra/db/ReadCommandVerbHandler.java:85`.
- Local coordinator reads set monitoring time from `Dispatcher.RequestTime`, use a local `false` cross-node flag, and record a self-dropped message when completion loses the race with timeout, see `src/java/org/apache/cassandra/service/StorageProxy.java:2204`.
- `ReadCommand.executeLocally()` applies query size tracking, test delay injection and `withQueryCancellation()`, while `QueryCancellationChecker.maybeCancel()` throws `QueryCancelledException` when `isAborted()` turns true, see `src/java/org/apache/cassandra/db/ReadCommand.java:777`.
- `ReadCommand.name()` returns `toCQLString()`, so `MonitoringTask` aggregates failed/slow reads by rendered CQL, see `src/java/org/apache/cassandra/db/ReadCommand.java:894`.
- `slow_query_log_timeout` defaults to `500ms` and can be set to zero to disable slow-query logging; read and range request timeouts default to `5000ms` and `10000ms`, see `src/java/org/apache/cassandra/config/Config.java:172` and `conf/cassandra.yaml:1319`.
- `StorageService` and `NodeProbe` expose read/range timeout runtime setters and getters; there is no matching runtime setter for `slow_query_log_timeout`, see `src/java/org/apache/cassandra/service/StorageService.java:1675` and `src/java/org/apache/cassandra/tools/NodeProbe.java:1466`.
- SAI `QueryContext` uses the same `QueryCancelledException` for index execution quota, but it is a separate index-local timeout boundary and does not enqueue `MonitoringTask` slow/failed operations by itself, see `src/java/org/apache/cassandra/index/sai/QueryContext.java:85`.

## Scenario Matrix

| Scenario ID | Contract |
|---|---|
| `read_monitoring_interface_contract` | `Monitorable` exposes name, creation time, timeout, slow timeout, state predicates, cross-node flag, abort and complete. |
| `read_monitoring_state_machine_contract` | `MonitorableImpl` starts `IN_PROGRESS`, transitions to `ABORTED` or `COMPLETED`, and treats repeated abort/complete calls as idempotent for the same terminal state. |
| `read_monitoring_set_time_contract` | Monitoring time is injected after construction so serializers do not need request deadline fields. |
| `read_monitoring_timeout_abort_contract` | Approximate elapsed time beyond request timeout aborts the read and enqueues a failed operation. |
| `read_monitoring_slow_complete_contract` | Slow reads are marked while in progress and only reported when they complete successfully with `slowTimeoutNanos > 0`. |
| `read_monitoring_queue_capacity_contract` | `MonitoringTask.OperationsQueue` supports disabled, bounded and unbounded logging, with dropped-operation accounting. |
| `read_monitoring_log_aggregation_contract` | Failed and slow operations are aggregated by operation name, include avg/min/max timings, and use a cross-node suffix when applicable. |
| `read_monitoring_remote_verb_contract` | Remote read requests copy message creation/deadline/cross-node metadata into the command before executing locally. |
| `read_monitoring_local_read_contract` | Local reads compute a deadline from `RequestTime`, set local monitoring metadata, and report self-dropped messages on timeout race. |
| `read_monitoring_query_cancellation_contract` | Row/partition iteration periodically checks abort state and raises `QueryCancelledException` to stop local work. |
| `read_monitoring_config_contract` | YAML/default config defines read/range request timeouts and slow-query timeout, with lowest accepted request timeout clamping. |
| `read_monitoring_jmx_nodetool_timeout_contract` | JMX/nodetool runtime timeout control covers read/range request timeouts but not slow-query logging timeout. |
| `read_monitoring_sai_query_context_boundary` | SAI query quota throws `QueryCancelledException` through index code but is separate from `MonitoringTask` slow/failed queues. |
| `read_monitoring_tests_baseline` | Unit tests cover monitoring state transitions, slow reporting, queue capacity, aggregation, cross-node logs and read command abort propagation. |
| `read_monitoring_coordinator_timeout_boundary` | Coordinator `ReadCallback` timeout/failure/speculation remains covered by the StorageProxy coordinator matrix and is not this module's local monitoring contract. |

## Call Graphs

```text
remote replica read request
  -> ReadCommandVerbHandler.doVerb(Message<ReadCommand>)
     -> validateTransientStatus(message)
     -> timeout = message.expiresAtNanos() - message.createdAtNanos()
     -> command.setMonitoringTime(message.createdAtNanos(), message.isCrossNode(), timeout, slow_query_log_timeout)
     -> command.executeLocally(controller)
        -> withQueryCancellation(iterator)
           -> QueryCancellationChecker.maybeCancel()
              -> command.isAborted()
                 -> MonitorableImpl.check()
                    -> mark slow or abort on approximate elapsed time
              -> throw QueryCancelledException on abort
     -> command.complete()
        -> send response when true
        -> recordDroppedMessage(...) when timeout already aborted the command
```

```text
local coordinator read on this node
  -> StorageProxy.LocalReadRunnable.runMayThrow()
     -> deadline = requestTime.computeDeadline(verb.expiresAfterNanos())
     -> command.setMonitoringTime(requestTime.startedAtNanos(), false, deadline - startedAt, slow_query_log_timeout)
     -> command.executeLocally(controller)
     -> catch QueryCancelledException
     -> command.complete()
        -> handler.response(response) when completed
        -> MessagingService.metrics.recordSelfDroppedMessage(...) and handler.onFailure(...) when aborted
```

```text
read monitoring report loop
  -> MonitoringTask.instance = make(reportIntervalMs, maxOperations)
     -> ScheduledExecutors.scheduledTasks.scheduleWithFixedDelay(logOperations)
  -> MonitorableImpl.abort()
     -> MonitoringTask.addFailedOperation(...)
  -> MonitorableImpl.complete()
     -> if isSlow && slowTimeoutNanos > 0: MonitoringTask.addSlowOperation(...)
  -> MonitoringTask.logOperations()
     -> logSlowOperations()
        -> slowOperationsQueue.popOperations()
        -> aggregate by operation.name()
        -> no-spam info + debug details
     -> logFailedOperations()
        -> failedOperationsQueue.popOperations()
        -> aggregate by operation.name()
        -> no-spam warn + debug details
```

```text
SAI index query quota boundary
  -> StorageAttachedIndexSearcher(... executionQuotaMs)
     -> new QueryContext(readCommand, executionQuotaMs)
  -> IndexSearchResultIterator / SAI search loop
     -> queryContext.checkpoint()
        -> if totalQueryTimeNs >= executionQuotaNano: throw QueryCancelledException(readCommand)
  -> exception propagates through read execution
  -> not a MonitoringTask.addFailedOperation(...) call unless the ReadCommand monitor itself aborts
```

## Design Goals

- Stop long-running local read work after the request deadline instead of continuing to burn CPU/disk after the coordinator has timed out.
- Log slow reads as an aggregate signal without requiring one log line per operation.
- Keep request timing metadata out of read command serializers by setting monitoring time at the message/local runnable boundary.
- Preserve operator visibility into cross-node timeout attribution with a distinct log suffix.
- Keep monitoring source-only and lightweight: reads check approximate time only as they iterate partitions/rows.

## Problems Solved

- Replica work is cancelled cooperatively during iterator consumption when the request has timed out.
- Slow but successful reads can be reported separately from reads that timed out.
- Operators get bounded, aggregated CQL text in debug logs rather than unbounded per-query spam.
- Local reads and remote replica reads share one state machine while preserving different metrics behavior for dropped messages.

## Tradeoffs

- Monitoring is cooperative. A read must pass through `QueryCancellationChecker` or another cancellation checkpoint before the exception is thrown.
- `approxTime` reduces overhead but means timeout detection is approximate and guarded by `approxTime.error()`.
- Slow operations are only queued on successful `complete()`. A read that becomes slow and then aborts is reported as failed, not as slow.
- `slow_query_log_timeout: 0` still lets `isSlow()` become true, but `complete()` suppresses slow operation logging.
- The operation name is rendered CQL; this is useful for diagnosis but can be expensive and may include query shape detail in debug logs.

## Core Classes

| Class/File | Role |
|---|---|
| `Monitorable` | Interface for operation state, timing, cross-node flag and terminal transitions. |
| `MonitorableImpl` | Shared state machine and approximate-time timeout/slow detection. |
| `MonitoringState` | `IN_PROGRESS`, `ABORTED`, `COMPLETED` terminal model. |
| `MonitoringTask` | Scheduled singleton that aggregates and logs failed/slow operation queues. |
| `ReadCommand` | Monitorable read command; wraps local iterators with cancellation checks and names operations as CQL. |
| `ReadCommandVerbHandler` | Remote replica read entry that injects message deadline/cross-node metadata. |
| `StorageProxy.LocalReadRunnable` | Local read entry that injects local deadline and maps timeout races to self-dropped metrics. |
| `QueryCancelledException` | Runtime exception used by read monitoring and SAI query quota to stop local work. |
| `QueryContext` | SAI index-local quota/cancellation boundary adjacent to read monitoring. |

## Core Interfaces

- `Monitorable.abort()` and `Monitorable.complete()`.
- `Monitorable.isInProgress()` / `isAborted()` / `isCompleted()` / `isSlow()`.
- `MonitorableImpl.setMonitoringTime(long approxCreationTimeNanos, boolean isCrossNode, long timeoutNanos, long slowTimeoutNanos)`.
- `MonitoringTask.addFailedOperation(Monitorable, long)` / `addSlowOperation(Monitorable, long)`.
- `ReadCommand.executeLocally(ReadExecutionController)` and `withQueryCancellation(UnfilteredPartitionIterator)`.
- `ReadCommandVerbHandler.doVerb(Message<ReadCommand>)`.
- `StorageProxy.LocalReadRunnable.runMayThrow()`.

## Core Data Structures

| Data Structure | Meaning |
|---|---|
| `MonitoringState` | In-progress vs aborted vs completed state. |
| `OperationsQueue` | Bounded/unbounded/disabled queue for failed or slow operation records. |
| `AggregatedOperations` | Pop result that merges queued operations by CQL name and appends dropped-operation count. |
| `Operation` | Timing accumulator with total/min/max and lazy operation name. |
| `FailedOperation` | Log formatter for timed-out reads. |
| `SlowOperation` | Log formatter for slow completed reads. |
| `Dispatcher.RequestTime` | Local coordinator start time/deadline input. |
| `Message<ReadCommand>` timestamps | Remote read creation/expiration/cross-node input. |

## Configuration

| Config | Source | Meaning |
|---|---|---|
| `read_request_timeout` | `src/java/org/apache/cassandra/config/Config.java:147`, `conf/cassandra.yaml:1322` | Default coordinator wait for ordinary read operations; also feeds local/remote command monitoring deadlines through message/request time. |
| `range_request_timeout` | `src/java/org/apache/cassandra/config/Config.java:149`, `conf/cassandra.yaml:1326` | Default coordinator wait for range/index scans. |
| `slow_query_log_timeout` | `src/java/org/apache/cassandra/config/Config.java:172`, `conf/cassandra.yaml:1398` | Threshold for slow-query aggregate logging; zero disables slow operation queueing on complete. |
| `cassandra.monitoring_report_interval_ms` | `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:363` | `MonitoringTask` scheduled reporting interval; negative values are clamped to zero by `Math.max(0, ...)`. |
| `cassandra.monitoring_max_operations` | `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:361` | Queue capacity for unique operation records; zero disables logging and negative makes queues unbounded. |

## Metrics

- Remote read timeout races record dropped internode messages through `MessagingService.instance().metrics.recordDroppedMessage(...)`, see `src/java/org/apache/cassandra/db/ReadCommandVerbHandler.java:133`.
- Local read timeout races record self-dropped messages through `MessagingService.instance().metrics.recordSelfDroppedMessage(...)` and fail the read callback, see `src/java/org/apache/cassandra/service/StorageProxy.java:2234`.
- Completed local reads still update latency subscribers when the read was not rejected, see `src/java/org/apache/cassandra/service/StorageProxy.java:2239`.
- There is no dedicated `MonitoringTask` metric for queue depth or dropped monitoring operations; dropped monitoring entries are reported only in aggregate debug log text.

## Logs

- `MonitoringTask` logs scheduling at info level with report interval and max operations.
- Timed-out operation batches produce a no-spam warning and debug detail: `Some operations timed out, details available at debug level (debug.log)`.
- Slow operation batches produce a no-spam info message and debug detail: `Some operations were slow, details available at debug level (debug.log)`.
- `ReadCommandVerbHandler` and `StorageProxy.LocalReadRunnable` log `Query cancelled (timeout)` at debug level when `QueryCancelledException` is caught.
- Failed/slow log lines add `msec/cross-node` when `Monitorable.isCrossNode()` is true.

## Operational Notes

- Raising `read_request_timeout` or `range_request_timeout` can reduce cancellation frequency, but if the underlying problem is disk/CPU saturation it may increase in-flight work.
- `slow_query_log_timeout` is configured in YAML/default config and read through `DatabaseDescriptor.getSlowQueryTimeout()`. Runtime `nodetool settimeout read|range` does not update slow-query logging threshold.
- `cassandra.monitoring_max_operations=0` disables failed/slow operation logging; negative removes the queue bound.
- Debug log detail is required to see the actual aggregated CQL text; normal logs only contain no-spam summary lines.
- SAI query quota cancellations look like `QueryCancelledException` to callers but should be diagnosed together with SAI query metrics and `executionQuotaMs`, not only `MonitoringTask` logs.

## Performance Bottlenecks

- The cancellation transform runs during row/partition iteration, so very large partitions and slow storage can still consume work between checkpoints.
- Rendering CQL with `ReadCommand.toCQLString()` is lazy but happens during log aggregation and can be non-trivial under many unique slow/failed queries.
- An unbounded monitoring queue can retain many operation records until the next report cycle.
- Too-low slow-query thresholds can generate frequent aggregation work and debug log volume.

## Common Failures

- `Query cancelled for taking too long: ...`: local read iterator observed the monitor as aborted or SAI quota expired.
- Slow query summaries without failed operations: reads crossed `slow_query_log_timeout` but completed before request timeout.
- Timed-out summaries with dropped monitoring entries: `cassandra.monitoring_max_operations` bounded queue was exceeded.
- No slow-query logs despite slow reads: `slow_query_log_timeout` may be zero, `cassandra.monitoring_max_operations` may be zero, or debug logs may not be enabled for details.
- Cross-node suffix in failed/slow logs: remote replica read request carried cross-node timing metadata.

## Tests

- `MonitoringTaskTest` covers abort, idempotent abort, cross-node abort, complete, idempotent complete, slow reporting, zero slow timeout, scheduled reporting, bounded queue drops and same-name aggregation, see `test/unit/org/apache/cassandra/db/monitoring/MonitoringTaskTest.java:129`.
- `ReadCommandTest` covers abort propagation for partition range, single partition slice and single partition names reads, see `test/unit/org/apache/cassandra/db/ReadCommandTest.java:232`.
- `ParseAndConvertUnitsTest` and `LoadOldYAMLBackwardCompatibilityTest` cover default and old-name config parsing for read/range/slow-query timeouts, see `test/unit/org/apache/cassandra/config/ParseAndConvertUnitsTest.java:45` and `test/unit/org/apache/cassandra/config/LoadOldYAMLBackwardCompatibilityTest.java:51`.
- `DatabaseDescriptorTest.testLowestAcceptableTimeouts()` covers lowest accepted read/range timeout clamping, see `test/unit/org/apache/cassandra/config/DatabaseDescriptorTest.java:354`.
