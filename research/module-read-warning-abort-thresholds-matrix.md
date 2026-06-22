# Module: Read Warning Abort Thresholds Matrix

## 范围

本矩阵补齐读取链路中 warning / abort 阈值的独立视角：tombstone 扫描保护、replica 本地 read-size 保护、coordinator result-size 保护、message params 聚合、client warning 输出、abort 异常映射、表/keyspace/client request metrics、runtime JMX 配置和现有阈值测试。基础 read path 仍见 `research/module-read-path.md`，range read 的并发/overlap/denylist 仍见 `research/module-range-read-performance-fault-matrix.md`。

当前源码基线：

- Replica 本地读在 `ReadCommand.executeLocally()` 先套 `withQuerySizeTracking()`，再套 `withMetricsRecording()`，见 `src/java/org/apache/cassandra/db/ReadCommand.java:426`、`src/java/org/apache/cassandra/db/ReadCommand.java:457`、`src/java/org/apache/cassandra/db/ReadCommand.java:461`。
- Tombstone 超 failure 阈值时 `withMetricsRecording()` 记录 `TombstoneFailures`、写入 `ParamType.TOMBSTONE_FAIL` 并抛 `TombstoneOverwhelmingException`，见 `src/java/org/apache/cassandra/db/ReadCommand.java:588`。
- Tombstone 超 warn 阈值时同一 wrapper 更新 scanned histograms、写 `ParamType.TOMBSTONE_WARNING` 或 `ClientWarn` 并记录 logger warning，见 `src/java/org/apache/cassandra/db/ReadCommand.java:621`。
- Local read size 只在 `trackWarnings`、非 system keyspace 且 local 阈值至少一个非空时启用；超 fail 写 `LOCAL_READ_SIZE_FAIL` 并抛 `LocalReadSizeTooLargeException`，超 warn 写 `LOCAL_READ_SIZE_WARN`，见 `src/java/org/apache/cassandra/db/ReadCommand.java:656`。
- Coordinator result size 在 `SelectStatement.process()` 构建 `ResultSet` 后 `maybeWarn()`，并在每个 partition 处理前 `maybeFail()`；它通过 `QueryOptions` 创建时捕获的 `ReadThresholds` 判断是否启用，见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:1014`、`src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:1039`、`src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:1057`、`src/java/org/apache/cassandra/cql3/QueryOptions.java:267`。
- Replica warning/abort 通过 internode `ParamType` 汇总到 `WarningContext` 和 `WarningsSnapshot`；`ReadCallback.awaitResults()` 把 snapshot 交给 `WarningsSnapshot.maybeAbort()`，`CoordinatorWarnings.done()` 统一发 client warnings 和 client-facing table metrics，见 `src/java/org/apache/cassandra/net/ParamType.java:51`、`src/java/org/apache/cassandra/service/reads/thresholds/WarningContext.java:29`、`src/java/org/apache/cassandra/service/reads/ReadCallback.java:146`、`src/java/org/apache/cassandra/service/reads/thresholds/WarningsSnapshot.java:107`、`src/java/org/apache/cassandra/service/reads/thresholds/CoordinatorWarnings.java:79`。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `read_warning_config_contract` | `Config`/`DatabaseDescriptor`/`cassandra.yaml` 中 read thresholds 和 tombstone thresholds 的字段、默认值、校验和 getter/setter。 |
| `read_warning_query_options_snapshot_contract` | `QueryOptions.ReadThresholds.create()` 在请求创建时根据 daemon init 和 `read_thresholds_enabled` 捕获 coordinator 阈值。 |
| `read_warning_replica_tombstone_warn_contract` | Replica 本地 tombstone warning 统计 live/tombstone histograms、table warning counter、trace/logger/client warning/message param。 |
| `read_abort_replica_tombstone_contract` | Replica 本地 tombstone fail 写 `TOMBSTONE_FAIL`、记录 table failure counter，并把 `TombstoneOverwhelmingException` 转为 coordinator-visible tombstone abort。 |
| `read_warning_replica_local_size_contract` | Local read size tracking 统计 partition key/row/range tombstone/deletion heap size，超 warn 写 `LOCAL_READ_SIZE_WARN` 并更新 `LocalReadSize` histogram。 |
| `read_abort_replica_local_size_contract` | Local read size 超 fail 移除 warn、写 `LOCAL_READ_SIZE_FAIL`、抛 `LocalReadSizeTooLargeException` 并映射到 `READ_SIZE`。 |
| `read_warning_message_param_contract` | `ParamType`、`WarningContext`、`WarningsSnapshot` 保存 tombstone/local read size warning/abort 计数与最大值。 |
| `read_abort_snapshot_callback_contract` | `ReadCallback.awaitResults()` 在失败/timeout 分支前固定 snapshot，优先调用 `maybeAbort()` 抛 `TombstoneAbortException` 或 `ReadSizeAbortException`。 |
| `read_warning_coordinator_result_size_contract` | Coordinator result-size warning/abort 更新 `CoordinatorReadSize*` metrics、client warning、logger warning，并用 `StorageProxy.recordReadRegularAbort()` 记录全局 read abort。 |
| `read_warning_metrics_contract` | `TableMetrics`、`KeyspaceMetrics`、`ClientRequestMetrics` 分别暴露 table/keyspace tombstone/read-size warning/abort 和 client request abort meters。 |
| `read_warning_jmx_runtime_contract` | `StorageService` runtime setter 暴露 tombstone、coordinator read-size、local read-size 和 row-index read-size 阈值。 |
| `read_warning_threshold_tests_baseline` | `CoordinatorReadSizeWarningTest`、`LocalReadSizeWarningTest`、`TombstoneCountWarningTest`、`DatabaseDescriptorTest`、`YamlConfigurationLoaderTest` 覆盖 warn/fail/config/metrics baseline。 |
| `read_warning_speculative_race_regression` | `ReadFailureTest.testSpecExecRace()` 覆盖 tombstone fail 与 speculative execution race，避免 warning/abort snapshot 竞态退化。 |

## 调用图

```text
coordinator SELECT
  -> QueryMessage / QueryProcessor / SelectStatement
  -> QueryOptions.ReadThresholds.create()
     -> if daemon initialized and read_thresholds_enabled
        -> capture coordinator_read_size_warn/fail_threshold
  -> StorageProxy read or range read
     -> ReadCallback.awaitResults()
        -> WarningContext.snapshot()
        -> CoordinatorWarnings.update(command, snapshot)
        -> if failed: WarningsSnapshot.maybeAbort()
           -> TombstoneAbortException or ReadSizeAbortException
  -> SelectStatement.process()
     -> for each partition:
        -> maybeFail(result, options)
           -> ReadSizeAbortException + CoordinatorReadSizeAborts + StorageProxy.recordReadRegularAbort()
        -> processPartition(...)
     -> result.build()
     -> maybeWarn(result, options)
        -> CoordinatorReadSize + CoordinatorReadSizeWarnings + ClientWarn/logger
     -> CoordinatorWarnings.done()
        -> ClientTombstoneWarnings/Aborts
        -> LocalReadSizeWarnings/Aborts

replica local read
  -> ReadCommand.executeLocally()
     -> queryStorage(...) or secondary-index searcher
     -> withQuerySizeTracking(...)
        -> add partition key / row / marker / deletion heap size
        -> LOCAL_READ_SIZE_WARN or LOCAL_READ_SIZE_FAIL
        -> LocalReadSize histogram
     -> withoutPurgeableTombstones(...)
     -> withMetricsRecording(...)
        -> count live rows and tombstones
        -> TOMBSTONE_WARNING or TOMBSTONE_FAIL
        -> TombstoneWarnings / TombstoneFailures
        -> live/tombstone histograms
```

## 设计目标

- Protect coordinators from result sets that grow too large after CQL selection/materialization.
- Protect replicas from partitions that produce too many tombstones or too much local heap materialization.
- Preserve client-visible diagnostics even when the failing condition is discovered on a replica.
- Keep warning paths observable without failing requests, and keep abort paths typed enough for metrics and failure reasons.
- Allow operators to tune thresholds at startup and runtime without changing schema.

## 解决的问题

- Tombstone-heavy reads can burn CPU/heap and hide real data behind deleted cells.
- A single read can materialize enough rows, range markers or result cells to threaten coordinator or replica heap.
- Distributed reads need to distinguish timeout/failure from semantic read aborts such as too many tombstones or read size.
- Client warnings should aggregate per-replica events rather than expose only coordinator-local checks.
- Metrics need to separate table/keyspace warning/abort counters from global client request abort meters.

## 设计取舍

- Tombstone thresholds apply even when `read_thresholds_enabled` is false; `read_thresholds_enabled` gates the newer coordinated read-size warning framework.
- `QueryOptions.ReadThresholds` snapshots coordinator thresholds per request, so runtime changes affect new requests rather than mutating an in-flight `QueryOptions` object.
- Local read-size tracking is disabled for system keyspaces and when both local thresholds are null, avoiding overhead on internal/system reads.
- Tombstone warn can still be coordinator-local when warning tracking is disabled; scans that split into multiple `ReadCommand`s may not propagate a top-level warning in that mode, as tested in `TombstoneCountWarningTest`.
- Coordinator read-size abort is created locally as `ReadSizeAbortException` and marks the coordinator as the only relevant failed endpoint because replica block/received counts are not meaningful for result materialization failure.

## 核心类

| 类/文件 | 作用 |
|---|---|
| `ReadCommand` | Replica local read wrapper stack；tombstone metrics/warnings/failures and local read-size tracking. |
| `SelectStatement` | Coordinator result-set materialization, coordinator read-size warning/abort and result-size metrics. |
| `QueryOptions` | Request-scoped read threshold snapshot for coordinator result-size checks. |
| `WarningContext` | Converts internode warning params into tombstone/local read-size/row-index/index warning counters. |
| `WarningsSnapshot` | Immutable warning/abort snapshot; maps abort counters to `TombstoneAbortException` or `ReadSizeAbortException`. |
| `CoordinatorWarnings` | Thread-local coordinator aggregation and final ClientWarn/logger/table-metric publication. |
| `ReadCallback` | Read response wait path that captures warnings and asks the snapshot to abort before generic read failure/timeout. |
| `TableMetrics` / `KeyspaceMetrics` / `ClientRequestMetrics` | Table/keyspace histograms/meters and client request abort meters. |
| `StorageService` | Runtime JMX surface for tombstone and read-size thresholds. |

## 核心接口

- `ReadCommand.withMetricsRecording()`、`withQuerySizeTracking()`、`shouldTrackSize()`。
- `SelectStatement.maybeWarn()`、`maybeFail()`、`processPartition()`。
- `QueryOptions.isReadThresholdsEnabled()`、`getCoordinatorReadSizeWarnThresholdBytes()`、`getCoordinatorReadSizeAbortThresholdBytes()`。
- `WarningContext.updateCounters()`、`snapshot()`。
- `WarningsSnapshot.maybeAbort()`、`tombstoneWarnMessage()`、`tombstoneAbortMessage()`、`localReadSizeWarnMessage()`、`localReadSizeAbortMessage()`。
- `CoordinatorWarnings.init()`、`update()`、`done()`、`reset()`。
- `ClientRequestMetrics.markAbort()` and `StorageProxy.recordReadRegularAbort()`。

## 配置项

| 配置项 | Source | 语义 |
|---|---|---|
| `tombstone_warn_threshold` / `tombstone_failure_threshold` | `src/java/org/apache/cassandra/config/Config.java:534`、`conf/cassandra.yaml:1814`、runtime setter `src/java/org/apache/cassandra/service/StorageService.java:6716` | Replica local tombstone warning/failure thresholds; failure aborts with `READ_TOO_MANY_TOMBSTONES`. |
| `read_thresholds_enabled` | `src/java/org/apache/cassandra/config/Config.java:526`、`conf/cassandra.yaml:2015`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4851` | Enables coordinated read-size warning/fail reporting. |
| `coordinator_read_size_warn_threshold` / `coordinator_read_size_fail_threshold` | `src/java/org/apache/cassandra/config/Config.java:527`、`conf/cassandra.yaml:2021`、`src/java/org/apache/cassandra/service/StorageService.java:7285` | Coordinator materialized result size warning/abort thresholds. |
| `local_read_size_warn_threshold` / `local_read_size_fail_threshold` | `src/java/org/apache/cassandra/config/Config.java:529`、`conf/cassandra.yaml:2025`、`src/java/org/apache/cassandra/service/StorageService.java:7310` | Replica local read heap-size warning/abort thresholds. |
| `row_index_read_size_warn_threshold` / `row_index_read_size_fail_threshold` | `src/java/org/apache/cassandra/config/Config.java:531`、`conf/cassandra.yaml:2029`、`src/java/org/apache/cassandra/service/StorageService.java:7333` | RowIndexEntry read-size thresholds; full BigTable/BTI boundary tracked in `research/module-row-index-read-size-thresholds-matrix.md`. |

## Metrics

- `ReadCommand.withMetricsRecording()` updates `tombstoneScannedHistogram`、`liveScannedHistogram`、`TombstoneWarnings` and `TombstoneFailures`，见 `src/java/org/apache/cassandra/db/ReadCommand.java:595`、`src/java/org/apache/cassandra/db/ReadCommand.java:626`、`src/java/org/apache/cassandra/db/ReadCommand.java:641`。
- `ReadCommand.withQuerySizeTracking()` updates table/keyspace `LocalReadSize` histogram on close，见 `src/java/org/apache/cassandra/db/ReadCommand.java:731`。
- `SelectStatement.maybeWarn()` and `maybeFail()` update `CoordinatorReadSize` histogram plus `CoordinatorReadSizeWarnings` / `CoordinatorReadSizeAborts` meters，见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:1045`、`src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:1071`。
- `CoordinatorWarnings.done()` records `ClientTombstoneWarnings` / `ClientTombstoneAborts` and `LocalReadSizeWarnings` / `LocalReadSizeAborts`，见 `src/java/org/apache/cassandra/service/reads/thresholds/CoordinatorWarnings.java:91`。
- `ClientRequestMetrics.markAbort()` increments global `Aborts` and typed `TombstoneAborts` / `ReadSizeAborts` when the cause is a `ReadAbortException`，见 `src/java/org/apache/cassandra/metrics/ClientRequestMetrics.java:57`。

## 日志

- Tombstone warning logs `Read %d live rows and %d tombstone cells... (see tombstone_warn_threshold)`，见 `src/java/org/apache/cassandra/db/ReadCommand.java:632`。
- Local read-size failure traces the abort message before adding `LOCAL_READ_SIZE_FAIL`，见 `src/java/org/apache/cassandra/db/ReadCommand.java:717`。
- Coordinator result-size warning and abort log table name plus rendered CQL query，见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:1048`、`src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:1063`。
- `CoordinatorWarnings.recordAborts()` and `recordWarnings()` warn after aggregating replica params，见 `src/java/org/apache/cassandra/service/reads/thresholds/CoordinatorWarnings.java:156`。

## 运维关注点

- Tombstone warnings indicate data-model or TTL/delete churn risk; increasing thresholds can hide heap pressure and should be paired with compaction/tombstone analysis.
- Coordinator read-size warning means the result is already materialized; it is a client query shaping signal, not a replica protection signal.
- Local read-size abort maps to `READ_SIZE`; tombstone abort maps to `READ_TOO_MANY_TOMBSTONES` and should be triaged separately.
- Runtime setter changes should be tested with new requests; `QueryOptions` snapshots coordinator thresholds when the request options are built.
- Metrics to inspect together: table `TombstoneWarnings/Failures`, `ClientTombstoneWarnings/Aborts`, `LocalReadSize*`, `CoordinatorReadSize*`, and client request `Aborts` / `TombstoneAborts` / `ReadSizeAborts`.

## 性能瓶颈

- Tombstone-heavy partitions force scanning deleted cells/markers even if the returned result is small.
- Local read-size tracking adds heap-size accounting on rows, markers and deletion times when enabled.
- Coordinator result-size checks happen after CQL selection/materialization and can still allocate a large result before warning or failing.
- Client warning aggregation requires carrying message params through read responses and merging snapshots on the coordinator.

## 常见故障

- `TombstoneOverwhelmingException` on replica: tombstones exceeded `tombstone_failure_threshold`; coordinator may expose `TombstoneAbortException` or a read failure reason.
- `ReadSizeAbortException`: local or coordinator read-size fail threshold was exceeded.
- Warning emitted but request succeeds: warn threshold crossed without fail threshold, or fail threshold disabled.
- No warning when expected: `read_thresholds_enabled=false`, thresholds are null, system keyspace bypass, or scan path with multiple `ReadCommand`s while coordinated warning tracking is disabled.
- Global read abort meter increments but table-level counter does not match expectation: distinguish coordinator result-size abort from replica local read-size/tombstone abort and check which node acted as coordinator.

## 测试用例

- `CoordinatorReadSizeWarningTest` sets coordinator warn/fail thresholds to 1KiB/2KiB and verifies warning/abort messages plus `CoordinatorReadSize*` metrics，见 `test/distributed/org/apache/cassandra/distributed/test/thresholds/CoordinatorReadSizeWarningTest.java:36`。
- `LocalReadSizeWarningTest` disables coordinator thresholds, sets local read-size thresholds and verifies warning/abort messages plus `LocalReadSize*` metrics，见 `test/distributed/org/apache/cassandra/distributed/test/thresholds/LocalReadSizeWarningTest.java:32`。
- `AbstractClientSizeWarning` drives single-partition, scan, read-repair, enabled/disabled and driver paths for client read-size warning/abort behavior，见 `test/distributed/org/apache/cassandra/distributed/test/thresholds/AbstractClientSizeWarning.java:97`、`test/distributed/org/apache/cassandra/distributed/test/thresholds/AbstractClientSizeWarning.java:242`。
- `TombstoneCountWarningTest` covers tombstone warn/fail, `TombstoneAbortException`, failure reason `READ_TOO_MANY_TOMBSTONES`, client tombstone metrics and disabled tracking behavior，见 `test/distributed/org/apache/cassandra/distributed/test/thresholds/TombstoneCountWarningTest.java:122`、`test/distributed/org/apache/cassandra/distributed/test/thresholds/TombstoneCountWarningTest.java:221`。
- `ReadFailureTest.testSpecExecRace()` covers tombstone failure racing with speculative execution，见 `test/distributed/org/apache/cassandra/distributed/test/ReadFailureTest.java:49`。
- `DatabaseDescriptorTest` validates coordinator/local warn <= fail semantics；`YamlConfigurationLoaderTest` validates YAML and map loading of read thresholds，见 `test/unit/org/apache/cassandra/config/DatabaseDescriptorTest.java:683`、`test/unit/org/apache/cassandra/config/YamlConfigurationLoaderTest.java:203`。
