# Module: Materialized View Build Status Matrix

This matrix isolates materialized view build/rebuild from the ordinary base-write view update path and the repair+MV write-path replay matrix. It protects the local checkpoint table, distributed host status table, `ViewBuildExecutor`, nodetool/JMX status surface, resume behavior and current focused test gaps.

## Scenario IDs

| Scenario | Protected behavior |
| --- | --- |
| `mv_build_schema_reload_gate` | `ViewManager.reload(buildAllViews)` only submits view builds after `StorageService` is initialized. |
| `mv_build_local_built_status_contract` | Local `system.built_views` and `system.view_builds_in_progress` define skip/resume/finish semantics. |
| `mv_build_distributed_status_contract` | `system_distributed.view_build_status` stores host-level `STARTED` / `SUCCESS` state for operator reads. |
| `mv_build_range_checkpoint_resume_contract` | `ViewBuilder` loads prior range checkpoints, subtracts built/pending ranges and splits new local ranges into tasks. |
| `mv_build_task_mutation_replay_contract` | `ViewBuilderTask` iterates canonical SSTable keys, reads base rows and emits view mutations through `StorageProxy.mutateMV()`. |
| `mv_build_executor_compaction_info_contract` | View build tasks run on `ViewBuildExecutor` and expose `OperationType.VIEW_BUILD` compaction info. |
| `mv_build_stop_retry_contract` | Schema/truncate stop and non-compaction failures produce stop or five-minute retry behavior. |
| `mv_build_nodetool_status_contract` | `viewbuildstatus`, `getconcurrentviewbuilders` and `setconcurrentviewbuilders` route through `NodeProbe` and `StorageServiceMBean`. |
| `mv_build_concurrency_config_contract` | `concurrent_materialized_view_builders` config and runtime setter resize the view build executor. |
| `mv_build_bootstrap_mark_built_contract` | Bootstrap-created views are marked built without rebuilding local data after bootstrap finishes. |
| `mv_build_existing_tests_baseline` | Existing unit tests cover range task replay, builder resume/truncate and active compaction tracking. |
| `mv_build_operator_cli_gap` | There is no focused nodetool CLI test for `viewbuildstatus` or concurrent view builder commands in this checkout. |

## Design Goals

- Separate initial view build from steady-state MV write maintenance. Steady-state writes are covered by `flow-materialized-view.md`; this matrix covers how historical base rows are scanned after a view is created or rebuilt.
- Make local and replicated status tables explicit: `system.view_builds_in_progress` is a checkpoint/resume table, `system.built_views` is the local skip marker, and `system_distributed.view_build_status` is the operator-visible host status table.
- Tie build progress to compaction infrastructure so operators can use active compactions, `ViewBuildExecutor` thread-pool metrics and nodetool status output to diagnose a stuck build.
- Preserve known gaps: current tests exercise task/range behavior but do not directly assert the nodetool CLI output and exit code behavior for MV build status commands.

## Source Matrix

| Scenario | Source anchors | Test / evidence | Operational meaning |
| --- | --- | --- | --- |
| `mv_build_schema_reload_gate` | `ViewManager.reload()` refreshes definitions, returns early when `buildAllViews` is false, and refuses to submit builders until `StorageService.instance.isInitialized()` is true; see `src/java/org/apache/cassandra/db/view/ViewManager.java:102-130`. | Covered indirectly by CQL view creation/reload tests; no direct test toggles gossip-disabled reload. | During daemon setup or JMX-disabled gossip, views can be known in schema without immediately launching build tasks. |
| `mv_build_local_built_status_contract` | `SystemKeyspace.isViewBuilt()` reads `system.built_views`, `setViewBuilt()` writes and flushes it, `finishViewBuildStatus()` writes built first and then deletes `view_builds_in_progress`; see `src/java/org/apache/cassandra/db/SystemKeyspace.java:657-704`. | `CQLTester.waitForViewBuild()` waits on `SystemKeyspace.isViewBuilt()`, see `test/unit/org/apache/cassandra/cql3/CQLTester.java:1173-1179`. | If built status survives but checkpoint deletion fails, next boot can skip full rebuild rather than restart from zero. |
| `mv_build_distributed_status_contract` | `SystemDistributedKeyspace.ViewBuildStatus` schema is `(keyspace_name, view_name), host_id -> status`; `startViewBuild()` writes `STARTED`, `successfulViewBuild()` writes `SUCCESS`, and `viewStatus()` reads by keyspace/view; see `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:165-173` and `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:379-423`. | `module-system-distributed-state-matrix.md` already maps the table owner; this checker keeps the build-specific call path local to MV research. | `viewbuildstatus` is cluster-host status, not a direct count of local range checkpoints. Missing host rows surface as `UNKNOWN`. |
| `mv_build_range_checkpoint_resume_contract` | `ViewBuilder.start()` skips if `SystemKeyspace.isViewBuilt()` is true, otherwise writes distributed `STARTED`, flushes the base table with `VIEW_BUILD_STARTED`, loads checkpoints, subtracts built/pending ranges from `StorageService.instance.getLocalReplicas()`, splits new ranges and submits `ViewBuilderTask`; see `src/java/org/apache/cassandra/db/view/ViewBuilder.java:84-173`. | `ViewTest.testViewBuilderResume()` creates multiple SSTables, restarts the first builder with a second view and waits for the original view to complete; see `test/unit/org/apache/cassandra/cql3/ViewTest.java:427-486`. | Resume is range-token based. Incorrect checkpoint handling can skip data or replay too much work after restart, schema change or compaction interruption. |
| `mv_build_task_mutation_replay_contract` | `ViewBuilderTask.buildKey()` uses the view select statement to read the base row, generates view updates with an empty existing row iterator, and calls `StorageProxy.mutateMV(..., true, noBase, ...)`; see `src/java/org/apache/cassandra/db/view/ViewBuilderTask.java:92-118`. `call()` waits up to 10 seconds for schema agreement and iterates canonical SSTable keys for the task range; see `src/java/org/apache/cassandra/db/view/ViewBuilderTask.java:121-168`. | `ViewBuilderTaskTest.testBuildRange()` validates range boundaries, last-token resume, row counts in the MV and persisted `last_token` / `keys_built`; see `test/unit/org/apache/cassandra/db/view/ViewBuilderTaskTest.java:40-126`. | Build uses normal MV mutation dispatch for historical rows, so paired endpoint/batchlog behavior remains consistent with steady-state MV writes. |
| `mv_build_executor_compaction_info_contract` | `CompactionManager.submitViewBuilder()` wraps the task in `activeCompactions.beginCompaction()` / `finishCompaction()` and uses `ViewBuildExecutor`; see `src/java/org/apache/cassandra/db/compaction/CompactionManager.java:1986-2005` and `src/java/org/apache/cassandra/db/compaction/CompactionManager.java:2123-2128`. `ViewBuilderTask.getCompactionInfo()` returns `OperationType.VIEW_BUILD`; see `src/java/org/apache/cassandra/db/view/ViewBuilderTask.java:197-213`. | `ActiveCompactionsTest.testViewBuildTracking()` submits a `ViewBuilderTask` with a mock active-compaction tracker and verifies the holder can be stopped; see `test/unit/org/apache/cassandra/db/compaction/ActiveCompactionsTest.java:168-187`. | Operators can see MV build as compaction-style work and can reason about active/pending view builder tasks separately from ordinary compaction. |
| `mv_build_stop_retry_contract` | `ViewBuilder` treats `CompactionInterruptedException` as stop/interruption, while other failures schedule `loadStatusAndBuild()` after five minutes; distributed status update failure also retries after five minutes; see `src/java/org/apache/cassandra/db/view/ViewBuilder.java:188-224`. `View.stopBuild()` stops current builders during schema change/truncate; see `src/java/org/apache/cassandra/db/view/View.java:213-225`. | `ViewTest.testTruncateWhileBuilding()` uses Byteman to block `ViewBuilderTask.buildKey`, truncates the view, waits for builders to drain and verifies built status; see `test/unit/org/apache/cassandra/cql3/ViewTest.java:652-686`. | A stuck build may be intentionally stopped by truncate/schema change or retrying after failure; local checkpoints decide the restart position. |
| `mv_build_nodetool_status_contract` | `NodeTool` registers `ViewBuildStatus`, `GetConcurrentViewBuilders` and `SetConcurrentViewBuilders`; see `src/java/org/apache/cassandra/tools/NodeTool.java:148`, `src/java/org/apache/cassandra/tools/NodeTool.java:213` and `src/java/org/apache/cassandra/tools/NodeTool.java:244`. `NodeProbe.getViewBuildStatuses()` delegates to `StorageServiceMBean`; see `src/java/org/apache/cassandra/tools/NodeProbe.java:1312-1314`. | `ViewBuildStatus` prints success and exits 0 only when every host reports `SUCCESS`; otherwise it prints the host table and exits 1, see `src/java/org/apache/cassandra/tools/nodetool/ViewBuildStatus.java:34-85`. | `UNKNOWN` or `STARTED` status should fail automation that expects the view to be fully built. |
| `mv_build_concurrency_config_contract` | `Config.concurrent_materialized_view_builders` defaults to 1 and is validated as positive in `DatabaseDescriptor`; runtime `StorageService.setConcurrentViewBuilders()` updates the config and `CompactionManager` executor; see `src/java/org/apache/cassandra/config/Config.java:346`, `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:787-789`, `src/java/org/apache/cassandra/service/StorageService.java:2031-2041` and `src/java/org/apache/cassandra/db/compaction/CompactionManager.java:2248-2251`. | `ViewTest.testViewBuilderResume()` exercises concurrency values 1, 2, 4 and 8 by calling `CompactionManager.instance.setConcurrentViewBuilders()`; see `test/unit/org/apache/cassandra/cql3/ViewTest.java:480-486`. | Increasing concurrency can speed initial build but increases base reads and view writes. Invalid zero/negative values are rejected at config and JMX surfaces. |
| `mv_build_bootstrap_mark_built_contract` | `StorageService.markViewsAsBuilt()` marks all user-keyspace views built after bootstrap because data was created during bootstrap; see `src/java/org/apache/cassandra/service/StorageService.java:2291-2301`. | Existing bootstrap tests exercise bootstrap data movement, but no focused test asserts the MV built marker transition. | A bootstrapped node should not immediately rebuild all MVs from streamed data after bootstrap completion. |
| `mv_build_existing_tests_baseline` | Current focused tests are `ViewBuilderTaskTest`, `ViewTest.testViewBuilderResume()`, `ViewTest.testTruncateWhileBuilding()` and `ActiveCompactionsTest.testViewBuildTracking()`. | The checker protects these test tokens. | These tests are enough for task/resume/truncate/active-compaction evidence, not enough for nodetool CLI behavior. |
| `mv_build_operator_cli_gap` | Source commands exist, but test scan currently finds no focused Java test for `viewbuildstatus`, `getconcurrentviewbuilders` or `setconcurrentviewbuilders` CLI output/exit-code behavior. | `research/tools/check-materialized-view-build-status-drift.py` fails if such tests appear so this gap can be rewritten as covered evidence. | Automation relying on nodetool exit codes should be validated before treating CLI behavior as regression-protected. |

## Lifecycle

```text
Schema reload / create view
  -> ViewManager.reload(buildAllViews)
     -> add missing View objects
     -> if buildAllViews and StorageService initialized
        -> View.build()
           -> stop current builder
           -> new ViewBuilder(baseCfs, view).start()

ViewBuilder.start()
  -> if system.built_views has view:
        if status_replicated=false: update system_distributed status
        return
  -> system_distributed.view_build_status = STARTED
  -> baseCfs.forceBlockingFlush(VIEW_BUILD_STARTED)
  -> load system.view_builds_in_progress checkpoints
  -> subtract built/pending ranges from local replicas
  -> split ranges into ViewBuilderTask instances
  -> CompactionManager.submitViewBuilder(task)

ViewBuilderTask.call()
  -> waitForSchemaAgreement(10 seconds)
  -> select canonical SSTables intersecting task range
  -> ReducingKeyIterator over decorated keys
  -> for each key after prevToken:
       -> view select read from base table
       -> generateViewUpdates(view, data, empty, nowInSec, true)
       -> StorageProxy.mutateMV(...)
       -> checkpoint every 1000 keys
  -> checkpoint end token for range

All tasks complete
  -> ViewBuilder.finish()
     -> system.built_views = built, status_replicated=false
     -> delete system.view_builds_in_progress rows
     -> system_distributed.view_build_status = SUCCESS
     -> system.built_views.status_replicated=true
```

## Configuration, Metrics And Logs

| Area | Evidence | Operational note |
| --- | --- | --- |
| Config | `concurrent_materialized_view_builders` in `Config` and `DatabaseDescriptor.getConcurrentViewBuilders()` / `setConcurrentViewBuilders()`; see `src/java/org/apache/cassandra/config/Config.java:346` and `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:2533-2541`. | Runtime resize is possible through JMX/nodetool, but it changes only executor concurrency, not already-built checkpoints. |
| Thread-pool metrics | `ViewBuildExecutor` is a named `CompactionExecutor`; `ViewTest.runningViewBuilds()` reads `Metrics.getThreadPoolMetrics("ViewBuildExecutor")`; see `test/unit/org/apache/cassandra/cql3/ViewTest.java:691-695`. | Active/pending tasks are the quickest local signal for an in-progress build. |
| Compaction info | `ViewBuilderTask.getCompactionInfo()` reports `OperationType.VIEW_BUILD`; see `src/java/org/apache/cassandra/db/view/ViewBuilderTask.java:197-213`. | `compactionstats` and active compaction APIs can expose view build work even though it is not SSTable compaction. |
| Logs | Start/resume/complete/stop messages live in `ViewBuilder` and `ViewBuilderTask`; failure paths log five-minute retry messages; see `src/java/org/apache/cassandra/db/view/ViewBuilder.java:96-99`, `src/java/org/apache/cassandra/db/view/ViewBuilder.java:198-223` and `src/java/org/apache/cassandra/db/view/ViewBuilderTask.java:125-137`. | Repeated five-minute warnings usually mean data or distributed status writes keep failing. |
| Nodetool | `viewbuildstatus` accepts `<keyspace> <view>` or `<keyspace.view>` and exits non-zero until all hosts report `SUCCESS`; see `src/java/org/apache/cassandra/tools/nodetool/ViewBuildStatus.java:39-85`. | The command is suitable for scripts, but this checkout lacks focused CLI regression tests for its exit behavior. |

## Current Gaps

- `mv_build_operator_cli_gap`: add direct nodetool tests for `viewbuildstatus` argument parsing, `SUCCESS` vs `STARTED`/`UNKNOWN` exit code behavior, and `getconcurrentviewbuilders` / `setconcurrentviewbuilders` routing.
- Bootstrap MV marker coverage is source-backed but not isolated in a focused test; a future bootstrap+MV test should assert `SystemKeyspace.isViewBuilt()` after bootstrap completion.
- There is no distributed test that simulates `system_distributed.view_build_status` write failure followed by the five-minute retry.

## Verification

- `python3 research/tools/check-materialized-view-build-status-drift.py`
- `python3 research/tools/run-research-drift-checks.py --pattern materialized-view-build`
- Adjacent checks:
  - `python3 research/tools/check-cache-index-view-coverage-drift.py`
  - `python3 research/tools/check-repair-materialized-view-consistency-drift.py`
  - `python3 research/tools/check-system-table-column-drift.py`
