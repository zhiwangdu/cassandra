# Read Repair And Repaired Data Matrix

本矩阵把普通读链路中的 read repair 从 `StorageProxy` coordinator 矩阵中拆出来，覆盖 digest mismatch 后的 full-data repair、`read_repair` 表参数、`BLOCKING` vs `NONE` 策略、partition repair mutation/ack、speculative repair read/write、repaired-data tracking、diagnostic events 和 JMX 运维入口。

## Source Contract

| Scenario | Contract | Source anchors | Test anchors |
| --- | --- | --- | --- |
| `read_repair_strategy_table_option_contract` | 表级 `read_repair` 由 `TableParams` 持有，默认 `BLOCKING`；`ReadRepairStrategy.NONE` 创建 `ReadOnlyReadRepair`，`BLOCKING` 创建 `BlockingReadRepair`。 | `src/java/org/apache/cassandra/schema/TableParams.java:92`, `src/java/org/apache/cassandra/schema/TableParams.java:374`, `src/java/org/apache/cassandra/service/reads/repair/ReadRepairStrategy.java:26` | `test/unit/org/apache/cassandra/service/reads/repair/AbstractReadRepairTest.java:290`, `test/distributed/org/apache/cassandra/distributed/test/ReadRepairTest.java:80` |
| `read_repair_digest_mismatch_entry_contract` | coordinator 初始 data/digest read 满足 CL 后，`DigestResolver.responsesMatch()` 不一致才调用 `readRepair.startRepair(...)`；repair timeout 会重写为原始 read CL。 | `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:400`, `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:446`, `src/java/org/apache/cassandra/service/reads/DigestResolver.java:105` | `test/unit/org/apache/cassandra/service/reads/DigestResolverTest.java:135`, `test/distributed/org/apache/cassandra/distributed/test/ReadRepairTest.java:125` |
| `read_repair_full_data_read_contract` | `AbstractReadRepair.startRepair()` 对原 contacted replicas 重新发 full data read，用 `DataResolver` reconcile，并可按配置请求 full replicas 返回 repaired-data digest。 | `src/java/org/apache/cassandra/service/reads/repair/AbstractReadRepair.java:126`, `src/java/org/apache/cassandra/service/reads/repair/AbstractReadRepair.java:139`, `src/java/org/apache/cassandra/service/reads/repair/AbstractReadRepair.java:146` | `test/unit/org/apache/cassandra/service/reads/repair/AbstractReadRepairTest.java:389`, `test/unit/org/apache/cassandra/service/reads/repair/DiagEventsBlockingReadRepairTest.java:78` |
| `read_repair_data_resolver_merge_contract` | `DataResolver` 只在多 replica 且非 top-K 时创建 read repair merge listener；short-read protection 和 replica filtering protection 会在 reconciliation 前后增加额外读取边界。 | `src/java/org/apache/cassandra/service/reads/DataResolver.java:173`, `src/java/org/apache/cassandra/service/reads/DataResolver.java:218`, `src/java/org/apache/cassandra/service/reads/DataResolver.java:237` | `test/unit/org/apache/cassandra/service/reads/DataResolverTest.java:132`, `test/unit/org/apache/cassandra/service/reads/DataResolverTest.java:548` |
| `read_repair_blocking_write_contract` | `BlockingReadRepair` 的 merge listener 生成 repair mutations；`repairPartition()` 创建 `BlockingPartitionRepair`，立即发送 initial repair mutations，并在 iterator close 后等待 write quorum。 | `src/java/org/apache/cassandra/service/reads/repair/BlockingReadRepair.java:57`, `src/java/org/apache/cassandra/service/reads/repair/BlockingReadRepair.java:83`, `src/java/org/apache/cassandra/service/reads/repair/BlockingReadRepair.java:114` | `test/unit/org/apache/cassandra/service/reads/repair/BlockingReadRepairTest.java:123`, `test/unit/org/apache/cassandra/service/reads/repair/ReadRepairTest.java:296` |
| `read_repair_none_noop_write_contract` | `ReadOnlyReadRepair` 只 reconcile data，返回 no-op merge listener，不发 additional writes，若尝试 repair partition 直接抛错。 | `src/java/org/apache/cassandra/service/reads/repair/ReadOnlyReadRepair.java:29`, `src/java/org/apache/cassandra/service/reads/repair/ReadOnlyReadRepair.java:47`, `src/java/org/apache/cassandra/service/reads/repair/ReadOnlyReadRepair.java:66` | `test/unit/org/apache/cassandra/service/reads/repair/ReadOnlyReadRepairTest.java:85`, `test/unit/org/apache/cassandra/service/reads/repair/ReadOnlyReadRepairTest.java:93`, `test/distributed/org/apache/cassandra/distributed/test/ReadRepairTest.java:90` |
| `read_repair_partition_ack_contract` | `BlockingPartitionRepair` 只向 full replicas 发 `READ_REPAIR_REQ`，用 write quorum latch 等 ack，local CL repair 禁止 remote DC contact，empty mutations 会从 blockFor 中扣除。 | `src/java/org/apache/cassandra/service/reads/repair/BlockingPartitionRepair.java:47`, `src/java/org/apache/cassandra/service/reads/repair/BlockingPartitionRepair.java:72`, `src/java/org/apache/cassandra/service/reads/repair/BlockingPartitionRepair.java:147` | `test/unit/org/apache/cassandra/service/reads/repair/ReadRepairTest.java:172`, `test/unit/org/apache/cassandra/service/reads/repair/BlockingReadRepairTest.java:261` |
| `read_repair_speculative_read_contract` | repair read 阶段可在 non-EACH_QUORUM、满足 speculative CL、sample read latency 未超过 read timeout 时向 uncontacted candidate 发 speculative data read，并标记 metrics/diagnostics。 | `src/java/org/apache/cassandra/service/reads/repair/AbstractReadRepair.java:175`, `src/java/org/apache/cassandra/service/reads/repair/AbstractReadRepair.java:185`, `src/java/org/apache/cassandra/service/reads/repair/AbstractReadRepair.java:201` | `test/unit/org/apache/cassandra/service/reads/repair/AbstractReadRepairTest.java:385`, `test/unit/org/apache/cassandra/service/reads/repair/AbstractReadRepairTest.java:404` |
| `read_repair_speculative_write_contract` | repair write 阶段若 initial repair ack 慢，会合并未 ack mutations，向 live uncontacted candidates 发 speculative `READ_REPAIR_REQ`，并按 messaging version 复用 mutation。 | `src/java/org/apache/cassandra/service/reads/repair/BlockingPartitionRepair.java:198`, `src/java/org/apache/cassandra/service/reads/repair/BlockingPartitionRepair.java:213`, `src/java/org/apache/cassandra/service/reads/repair/BlockingPartitionRepair.java:224` | `test/unit/org/apache/cassandra/service/reads/repair/BlockingReadRepairTest.java:135`, `test/unit/org/apache/cassandra/service/reads/repair/ReadRepairTest.java:193` |
| `read_repair_repaired_data_tracking_contract` | repaired-data tracking 为 full replica data responses 记录 repaired digest 和 inconclusive endpoints，`DataResolver` 在 merge listener close 时调用 verifier。 | `src/java/org/apache/cassandra/service/reads/DataResolver.java:90`, `src/java/org/apache/cassandra/service/reads/DataResolver.java:103`, `src/java/org/apache/cassandra/service/reads/DataResolver.java:407`, `src/java/org/apache/cassandra/service/reads/repair/RepairedDataTracker.java:36` | `test/unit/org/apache/cassandra/service/reads/DataResolverTest.java:933`, `test/distributed/org/apache/cassandra/distributed/test/RepairDigestTrackingTest.java:83` |
| `read_repair_repaired_data_verifier_contract` | repaired digest mismatch 在全部 conclusive 时记 confirmed metric；存在 inconclusive digest 时可按配置记 unconfirmed；snapshotting verifier 可触发 diagnostic snapshot。 | `src/java/org/apache/cassandra/service/reads/repair/RepairedDataVerifier.java:38`, `src/java/org/apache/cassandra/service/reads/repair/RepairedDataVerifier.java:66`, `src/java/org/apache/cassandra/service/reads/repair/RepairedDataVerifier.java:107` | `test/unit/org/apache/cassandra/service/reads/repair/RepairedDataVerifierTest.java:76`, `test/unit/org/apache/cassandra/service/reads/repair/RepairedDataVerifierTest.java:110`, `test/distributed/org/apache/cassandra/distributed/test/RepairDigestTrackingTest.java:172` |
| `read_repair_diagnostic_metrics_contract` | read repair metrics 包括 blocking/reconcile/timedOut/speculatedRead/speculatedWrite；diagnostic events 覆盖 START_REPAIR、SPECULATED_READ、initial/speculated repair writes 和 oversized updates。 | `src/java/org/apache/cassandra/metrics/ReadRepairMetrics.java:25`, `src/java/org/apache/cassandra/service/reads/repair/ReadRepairDiagnostics.java:41`, `src/java/org/apache/cassandra/service/reads/repair/ReadRepairEvent.java:45` | `test/unit/org/apache/cassandra/service/reads/repair/DiagEventsBlockingReadRepairTest.java:78` |
| `read_repair_mbean_operational_contract` | `StorageProxyMBean` 暴露 blocking read repair 临时日志、range/partition repaired-data tracking、unconfirmed mismatch reporting 和 snapshot-on-mismatch toggles。 | `src/java/org/apache/cassandra/service/StorageProxyMBean.java:102`, `src/java/org/apache/cassandra/service/StorageProxy.java:2908`, `src/java/org/apache/cassandra/service/StorageProxy.java:3180` | `test/unit/org/apache/cassandra/service/StorageProxyTest.java:127`, `test/distributed/org/apache/cassandra/distributed/test/RepairDigestTrackingTest.java:172` |
| `read_repair_existing_tests_baseline` | Existing tests cover digest mismatch, blocking vs none, timeout/failing repair, speculative repair reads/writes, repaired data verifier, repaired digest tracking and diagnostic event recipients. | `test/unit/org/apache/cassandra/service/reads/repair`, `test/unit/org/apache/cassandra/service/reads/DataResolverTest.java`, `test/distributed/org/apache/cassandra/distributed/test/ReadRepairTest.java`, `test/distributed/org/apache/cassandra/distributed/test/RepairDigestTrackingTest.java` | same |

## Design Goals

- Return reconciled data only after detecting and repairing digest mismatch according to table-level `read_repair` semantics.
- Preserve monotonic quorum reads for `BLOCKING` by waiting on repair writes; allow `NONE` to preserve write atomicity and avoid repair mutation latency.
- Avoid making one slow repair participant fail the whole read when additional full replicas can ack equivalent repair mutations.
- Detect divergence in repaired SSTable data sets separately from ordinary digest mismatch so anti-entropy problems can be surfaced.

## Lifecycle

```text
Initial read
  -> AbstractReadExecutor.awaitResponses()
     -> ReadCallback.awaitResults()
     -> DigestResolver.responsesMatch()
     -> if mismatch:
        -> readRepair.startRepair(digestResolver, setResult)
           -> DataResolver(command, replicaPlan, readRepair, trackRepairedStatus)
           -> ReadCallback(dataResolver, command, replicaPlan)
           -> send full data read to each contacted replica
           -> ReadRepairDiagnostics.startRepair(...)
        -> readRepair.maybeSendAdditionalReads()
        -> readRepair.awaitReads()
           -> dataResolver.resolve()
              -> readRepair.getMergeListener(...)
              -> generate partition repair mutations while iterator is consumed
```

```text
Blocking repair write
  -> BlockingReadRepair.repairPartition(...)
     -> BlockingPartitionRepair.sendInitialRepairs()
        -> Message.out(READ_REPAIR_REQ, mutation)
        -> readRepairRequests metric
     -> StorageProxy.concatAndBlockOnRepair closes iterator
        -> readRepair.maybeSendAdditionalWrites()
           -> merge unacked updates
           -> send speculative READ_REPAIR_REQ to live uncontacted candidates
        -> readRepair.awaitWrites()
           -> wait write quorum latch or throw ReadTimeoutException(data_present=true)
```

```text
Repaired data tracking
  -> AbstractReadRepair.startRepair()
     -> trackRepairedStatus = DatabaseDescriptor.getRepairedDataTrackingForPartitionReadsEnabled()
  -> DataResolver.resolve()
     -> RepairedDataTracker.recordDigest(full replica repaired digest, conclusive?)
     -> merge listener close
        -> RepairedDataVerifier.verify(...)
           -> confirmed/unconfirmed repaired inconsistency metrics
           -> optional DiagnosticSnapshotService.repairedDataMismatch(...)
```

## Configuration And Operations

| Surface | Contract |
| --- | --- |
| table `read_repair` | `BLOCKING` waits for repair writes; `NONE` reconciles only. Default is `BLOCKING`. |
| `repaired_data_tracking_for_partition_reads_enabled` | Enables repaired-data digest comparison on partition read repair reads. |
| `repaired_data_tracking_for_range_reads_enabled` | Enables repaired-data digest comparison for range read tracking paths. |
| `report_unconfirmed_repaired_data_mismatches` | Records mismatches involving inconclusive repaired digests. |
| `snapshot_on_repaired_data_mismatch` | Triggers diagnostic snapshots when repaired-data mismatch is reported. |
| `logBlockingReadRepairAttemptsForNSeconds` | Time-boxed JMX switch to log blocking read repair attempts. |

## Operational Notes

- `ReadTimeoutException` with `data_present=true` during read repair means the initial read had enough responses but repair reads or writes exceeded the original read timeout budget.
- `read_repair='NONE'` can leave replicas divergent after a digest mismatch; anti-entropy repair remains responsible for convergence.
- Speculative repair writes use `READ_REPAIR_REQ` and intentionally avoid hints; they are for preserving read semantics, not durable write retry.
- Repaired-data mismatch metrics indicate inconsistency among repaired SSTables, which can be more serious than ordinary unrepaired divergence.
- Snapshot-on-mismatch is useful for forensics but can create snapshots on all affected nodes, so enable it deliberately.

## Performance And Failure Boundaries

- Digest mismatch doubles the read cost for contacted replicas because the repair phase reissues full data reads.
- `BLOCKING` adds repair mutation fan-out and ack wait to the client read latency.
- Additional repair reads/writes reduce tail-latency failures but increase fan-out under slow or unavailable replicas.
- Repaired-data tracking adds digest collection and verifier work to read repair/range read tracking paths.
- Large repair mutations may be skipped as oversized during speculative write generation, with a diagnostic event.

## Test Cases

- `test/unit/org/apache/cassandra/service/reads/DigestResolverTest.java:135`：digest mismatch detection.
- `test/unit/org/apache/cassandra/service/reads/DataResolverTest.java:132`：reconciliation produces repair mutations.
- `test/unit/org/apache/cassandra/service/reads/DataResolverTest.java:933`：repaired digest tracking baseline.
- `test/unit/org/apache/cassandra/service/reads/repair/AbstractReadRepairTest.java:385`：additional repair reads.
- `test/unit/org/apache/cassandra/service/reads/repair/BlockingReadRepairTest.java:135`：additional repair mutation required.
- `test/unit/org/apache/cassandra/service/reads/repair/BlockingReadRepairTest.java:238`：only block on quorum.
- `test/unit/org/apache/cassandra/service/reads/repair/ReadOnlyReadRepairTest.java:85`：`NONE` strategy merge listener is no-op.
- `test/unit/org/apache/cassandra/service/reads/repair/RepairedDataVerifierTest.java:76`：unconfirmed mismatch metric.
- `test/unit/org/apache/cassandra/service/reads/repair/RepairedDataVerifierTest.java:110`：confirmed mismatch metric.
- `test/unit/org/apache/cassandra/service/reads/repair/DiagEventsBlockingReadRepairTest.java:78`：diagnostic read repair event recipients.
- `test/distributed/org/apache/cassandra/distributed/test/ReadRepairTest.java:80`：blocking read repair distributed behavior.
- `test/distributed/org/apache/cassandra/distributed/test/ReadRepairTest.java:90`：none read repair distributed behavior.
- `test/distributed/org/apache/cassandra/distributed/test/ReadRepairTest.java:125`：read repair timeout.
- `test/distributed/org/apache/cassandra/distributed/test/RepairDigestTrackingTest.java:172`：snapshotting on repaired-data inconsistency.
