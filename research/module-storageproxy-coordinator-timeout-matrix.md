# Module: StorageProxy Coordinator Timeout Matrix

## 范围

本模块补齐 `StorageProxy` 普通读写 coordinator 的 source-level 矩阵：非 LWT/counter 的写入响应处理、hint/failure callback、cheap quorum backup、普通单分区读的 executor 选择、speculative retry、`ReadCallback` timeout/failure/warning 映射、digest mismatch 后的 blocking/read-only repair，以及 coordinator 侧 metrics/JMX 操作面。LWT、counter、hints/batchlog 的深水区仍以 `research/module-coordination-lwt-counter-hints*.md` 和 `research/module-coordination-hints-batchlog-backlog-matrix.md` 为主；range read 的 storage/performance 细节见 `research/module-range-read-storage-engine-matrix.md` 和 `research/module-range-read-performance-fault-matrix.md`。

当前基线：

- 写入入口 `StorageProxy.mutate()` 为每个 mutation 建立 `AbstractWriteResponseHandler`，非 counter 写入通过 `performWrite()` 取得 `ReplicaPlans.forWrite(...)` 和 replication strategy 的 response handler，再等待 `responseHandler.get()`；超时/失败在这里统一映射到 `writeMetrics.timeouts` / `writeMetrics.failures` / per-CL metrics，`CL.ANY` 失败时转为 `hintMutations()`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:878`。
- `AbstractWriteResponseHandler.get()` 用 `write_request_timeout` 或 `counter_write_request_timeout` 计算剩余 timeout，未 signal 时抛 `WriteTimeoutException`，失败数超过候选 replica 时用 `RequestCallback.isTimeout(...)` 区分 timeout-like failure 和 `WriteFailureException`，见 `src/java/org/apache/cassandra/service/AbstractWriteResponseHandler.java:111`。
- `WriteResponseHandler`、`DatacenterWriteResponseHandler`、`DatacenterSyncWriteResponseHandler` 分别覆盖普通 CL/local-DC CL/EACH_QUORUM 的 ack 计数和 ideal CL latency/failure tracking，测试见 `test/unit/org/apache/cassandra/service/WriteResponseHandlerTest.java:148`。
- 普通读入口 `StorageProxy.read()` 先做 bootstrap safety 与 partition denylist gate，非 serial CL 进入 `readRegular()`；`fetchRows()` 串起 `AbstractReadExecutor.getReadExecutor()`、initial data/digest requests、speculative retry、`awaitResponses()`、digest mismatch repair reads、repair writes 和结果拼接，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1858` 与 `src/java/org/apache/cassandra/service/StorageProxy.java:2106`。
- `ReadCallback.awaitResults()` 是读 timeout/failure/warning/abort 的中心：它等待 `read_request_timeout`，检查 data response 是否存在，合并 warning params，调用 `WarningsSnapshot.maybeAbort(...)`，最后抛 `ReadFailureException` 或 `ReadTimeoutException`，见 `src/java/org/apache/cassandra/service/reads/ReadCallback.java:111`。
- digest mismatch 时 `AbstractReadExecutor.awaitResponses()` 调 `ReadRepair.startRepair(...)`；`AbstractReadRepair.startRepair()` 向 contacted replicas 发 full data read，`awaitReads()` 合并数据并记录 repair timeout，`BlockingReadRepair.awaitWrites()` 再阻塞 repair mutations，见 `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:408`、`src/java/org/apache/cassandra/service/reads/repair/AbstractReadRepair.java:126` 和 `src/java/org/apache/cassandra/service/reads/repair/BlockingReadRepair.java:83`。

## 设计目标

- Coordinator 负责把客户端 CL 语义映射为 replica plan、message fan-out、response handler、timeout/failure 异常和 metrics，而 replica 本地读写只负责执行 mutation/read command。
- 写路径在同一个地方统一统计 client request metrics 和 table coordinator write latency，避免各个 performer 或 handler 分散记账。
- 读路径保留 data/digest 分离，以低带宽验证副本一致性；只有 digest mismatch 才升级为 full-data read repair。
- Speculative read/write backup 都以表级历史 latency 为阈值，只有在原始 request 仍可能满足 client deadline 时才扩展 contacted replicas。
- Read repair 的策略由 table option `read_repair` 决定：`BLOCKING` 保护 monotonic quorum reads，但可能拉长读延迟；`NONE` 只做 reconciliation，不发 repair mutation。

## 解决的问题

- Replica 局部失败、网络 drop、timeout-like failure reason 和 coordinator deadline 需要被转换成对客户端稳定的 `ReadTimeoutException`、`ReadFailureException`、`WriteTimeoutException` 或 `WriteFailureException`。
- Multi-DC CL 不能让远端 DC 响应误计入 local CL；`DatacenterWriteResponseHandler.waitingFor(...)` 只等待本 DC，`DatacenterSyncWriteResponseHandler` 按 DC quorum 计数。
- Digest mismatch 不能直接返回任意副本数据；需要拉取 full data、reconcile，再根据 `read_repair` 策略选择是否写回不一致副本。
- Coordinator 需要在不破坏 CL 的前提下做 speculation：读 speculation 扩展 contacts，write cheap quorum backup 则在 `additionalWriteLatencyMicros` 到达后补发到 uncontacted live replicas。

## 核心类与接口

| 类/接口 | 角色 |
|---|---|
| `StorageProxy` | 普通读写 coordinator 入口；`mutate()`、`performWrite()`、`sendToHintedReplicas()`、`read()`、`readRegular()`、`fetchRows()`、`concatAndBlockOnRepair()` 串起请求生命周期。 |
| `AbstractWriteResponseHandler<T>` | 写入 response callback 基类；维护 failures、failure reasons、ideal CL delegate、timeout 计算和 cheap quorum backup。 |
| `WriteResponseHandler<T>` | ONE/ANY/TWO/THREE/QUORUM/ALL 的 ack countdown handler。 |
| `DatacenterWriteResponseHandler<T>` | LOCAL_* CL 只等待本 DC endpoint。 |
| `DatacenterSyncWriteResponseHandler<T>` | EACH_QUORUM 按每个 DC 维护 quorum countdown。 |
| `ReadCallback<E, P>` | read response callback；收集 `ResponseResolver` responses、failure reasons、warning context，并负责 timeout/failure/abort 映射。 |
| `AbstractReadExecutor` | 选择 never/speculating/always speculation 策略，发送 data/digest requests，处理 digest mismatch 和 repair wait。 |
| `DigestResolver` | 记录 full data response，比较 full replicas 的 digest，必要时把 transient response 交给 `DataResolver` reconcile。 |
| `DataResolver` | full data reconciliation、short read protection、replica filtering protection、repaired data tracking 和 merge listener read repair。 |
| `ReadRepair<E, P>` | digest mismatch repair/read repair mutation contract，定义 `startRepair()`、`awaitReads()`、`maybeSendAdditionalReads()`、`maybeSendAdditionalWrites()`、`awaitWrites()`。 |
| `BlockingReadRepair` | 发 repair mutations 并在 iterator close 后阻塞 ack，保护 monotonic quorum reads。 |
| `ReadOnlyReadRepair` | 只 reconcile，不写 repair mutation，保留 write atomicity。 |
| `StorageProxyMBean` | 读写 timeout、read repair metrics、denylist、read repair logging、repaired data tracking 的 JMX 操作面。 |

## 核心数据结构

- `ReplicaPlan.ForWrite` / `ReplicaPlan.ForTokenRead`：把 CL、replication strategy、live/down/pending replicas 和 contacts 封装为 coordinator 的执行计划。
- `Condition`：write/read callback 用 one-time condition 协调 network/local response 与 coordinator wait。
- `failureReasonByEndpoint`：read/write handler 保存 per-endpoint failure reason，用于区分 timeout-like failures 和真实 failure。
- `ReadCallback.warningContext` / `WarningsSnapshot`：收集 replica warning params，并在返回或 abort 前更新 coordinator warnings。
- `DigestRepair`：`AbstractReadRepair` 内部保存 mismatch 后的 `DataResolver`、`ReadCallback` 和 result consumer。
- `BlockingPartitionRepair` 队列：`BlockingReadRepair` 记录每个 partition 的 repair mutations 和 ack wait 状态。

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| `read_request_timeout` | `src/java/org/apache/cassandra/config/Config.java:145`，getter/setter 在 `DatabaseDescriptor.java:2195` / `DatabaseDescriptor.java:2200` | `ReadCommand.getTimeout()` 和 `ReadCallback.awaitResults()` 的普通读 timeout 基线。 |
| `write_request_timeout` | `src/java/org/apache/cassandra/config/Config.java:151`，getter/setter 在 `DatabaseDescriptor.java:2215` / `DatabaseDescriptor.java:2220` | 非 counter `AbstractWriteResponseHandler.currentTimeoutNanos()` 的 timeout 基线。 |
| `counter_write_request_timeout` | `src/java/org/apache/cassandra/config/Config.java:154`，getter/setter 在 `DatabaseDescriptor.java:2225` / `DatabaseDescriptor.java:2230` | counter write handler 使用的 timeout 基线。 |
| `native_transport_timeout` | `src/java/org/apache/cassandra/config/Config.java:1399`，getter/setter 在 `DatabaseDescriptor.java:2352` / `DatabaseDescriptor.java:2362` | `RequestTime.clientDeadline()` 上限；read speculation 不会越过 client deadline。 |
| `cql_start_time` | `src/java/org/apache/cassandra/config/Config.java:1391`，getter/setter 在 `DatabaseDescriptor.java:2293` / `DatabaseDescriptor.java:2298` | request timeout 从 queue 或 request start 计时，影响 `RequestTime.computeDeadline()` 和 speculation。 |
| `partition_denylist_enabled` / `denylist_reads_enabled` | `src/java/org/apache/cassandra/config/Config.java:759` / `Config.java:763`，getter 在 `DatabaseDescriptor.java:4733` / `DatabaseDescriptor.java:4753` | `StorageProxy.read()` 的单分区 denylist gate。 |
| `speculative_retry` | schema CQL 输出在 `src/java/org/apache/cassandra/schema/TableParams.java:344` | `AbstractReadExecutor.getReadExecutor()` 选择 never/speculating/always read executor。 |
| `read_repair` | schema CQL 输出在 `src/java/org/apache/cassandra/schema/TableParams.java:342` | `ReadRepair.create()` 选择 `BlockingReadRepair` 或 `ReadOnlyReadRepair`。 |

## Metrics 与日志

- 写入 client metrics：`StorageProxy.mutate()` 在 `WriteFailureException`、`WriteTimeoutException`、`UnavailableException`、`OverloadedException` 上分别标记 `writeMetrics.failures`、`writeMetrics.timeouts`、`writeMetrics.unavailables` 和 per-CL metrics，见 `src/java/org/apache/cassandra/service/StorageProxy.java:909`。
- 写入 latency：`StorageProxy.mutate()` finally 调 `writeMetrics.addNano(...)`、per-CL latency 和 `updateCoordinatorWriteLatencyTableMetric(...)`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:947`。
- 写入 ideal CL：`AbstractWriteResponseHandler.signal()` 对达到 ideal CL 的请求更新 `idealCLWriteLatency`，`decrementResponseOrExpired()` 对请求 CL 已成功但 ideal CL 未达成的请求递增 `writeFailedIdealCL`，见 `src/java/org/apache/cassandra/service/AbstractWriteResponseHandler.java:277`。
- 读 client metrics：`readRegular()` 在 unavailable、timeout、abort、failure 上分别标记 read metrics/per-CL metrics，并在 finally 更新 `readMetrics.addNano(...)` 和 table `coordinatorReadLatency`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:2005`。
- Read speculation metrics：`AbstractReadExecutor` 更新 `speculativeRetries`、`speculativeFailedRetries` 和 `speculativeInsufficientReplicas`，见 `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:281`、`:305`、`:375`。
- Read repair metrics：`AbstractReadRepair.startRepair()` 标记 blocking/reconcile repair meter，`awaitReads()` 标记 `ReadRepairMetrics.timedOut`，`maybeSendAdditionalReads()` 标记 `ReadRepairMetrics.speculatedRead`，见 `src/java/org/apache/cassandra/service/reads/repair/AbstractReadRepair.java:126`。
- 日志/trace：写失败/超时由 `StorageProxy.mutate()` trace；read callback 在 tracing 或 debug 下记录 received/blockFor/data-present；digest mismatch 由 `AbstractReadExecutor.awaitResponses()` trace，JMX 可用 `StorageProxyMBean.logBlockingReadRepairAttemptsForNSeconds()` 临时打开 blocking read repair info log。

## 场景矩阵

| 场景 ID | Coordinator 路径 | 保护内容 | 测试锚点 |
|---|---|---|---|
| `storageproxy_write_response_handler_lifecycle` | `StorageProxy.mutate()` -> `performWrite()` -> `AbstractWriteResponseHandler.get()` | write replica plan、response handler、ack countdown、ideal CL delegate、callback signal。 | `test/unit/org/apache/cassandra/service/WriteResponseHandlerTest.java:148` |
| `storageproxy_write_timeout_failure_metrics` | `AbstractWriteResponseHandler.get()` -> `StorageProxy.mutate()` catch/finally | timeout-like failure reason、`WriteTimeoutException` vs `WriteFailureException`、write metrics/per-CL metrics/table latency。 | `test/distributed/org/apache/cassandra/distributed/test/metrics/RequestTimeoutTest.java:100` |
| `storageproxy_write_local_remote_hint_dispatch` | `sendToHintedReplicas()` | local apply delayed until remote sends are staged、`CALL_BACK_ON_FAILURE`、down replica `expired()`、hints with/without CL.ANY。 | `test/unit/org/apache/cassandra/service/StorageProxyTest.java:71` |
| `storageproxy_write_cheap_quorum_additional_replicas` | `AbstractWriteResponseHandler.maybeTryAdditionalReplicas()` | uncontacted live replicas、`additionalWriteLatencyMicros` threshold、`additionalWrites` metrics。 | source-only baseline; no focused unit test for ordinary write cheap-quorum backup. |
| `storageproxy_read_safety_denylist_dispatch` | `StorageProxy.read()` | bootstrap safety、system keyspace bypass、partition denylist rejection、serial CL to Paxos vs ordinary `readRegular()`。 | `test/unit/org/apache/cassandra/service/PartitionDenylistTest.java:41` |
| `storageproxy_read_executor_selection_speculation` | `AbstractReadExecutor.getReadExecutor()` / `shouldSpeculateAndMaybeWait()` | `speculative_retry` strategy、EACH_QUORUM no speculation、lack-of-extra-replica metric、native deadline guard。 | `test/unit/org/apache/cassandra/service/reads/ReadExecutorTest.java:94`、`test/distributed/org/apache/cassandra/distributed/test/ReadSpeculationTest.java:45` |
| `storageproxy_read_callback_timeout_failure_warning` | `ReadCallback.awaitResults()` | data-present requirement, failures vs timeouts, warning params, abort mapping, failure reasons. | `test/unit/org/apache/cassandra/service/reads/ReadExecutorTest.java:202`、`test/distributed/org/apache/cassandra/distributed/test/ReadFailureTest.java:50` |
| `storageproxy_read_digest_mismatch_repair` | `AbstractReadExecutor.awaitResponses()` -> `ReadRepair.startRepair()` | digest mismatch detection, full data reads to contacted replicas, repaired-data tracking, diagnostic event start. | `test/unit/org/apache/cassandra/service/reads/DigestResolverTest.java:42`、`test/unit/org/apache/cassandra/service/reads/DataResolverTest.java:86` |
| `storageproxy_read_repair_write_blocking` | `concatAndBlockOnRepair()` -> `ReadRepair.maybeSendAdditionalWrites()` / `awaitWrites()` | iterator close boundary, blocking repair write ack, timeout rewritten with original CL, read-only repair no-op writes. | `test/distributed/org/apache/cassandra/distributed/test/ReadRepairTest.java:81`、`:125`、`:159`、`:181` |
| `storageproxy_coordinator_latency_metrics` | `mutate()` / `readRegular()` finally | write/read latency measured from processing start, table `coordinatorWriteLatency` / `coordinatorReadLatency`, per-CL metrics. | `test/unit/org/apache/cassandra/service/reads/ReadExecutorTest.java:133`、`test/unit/org/apache/cassandra/service/OptionalTasksTest.java:59` |
| `storageproxy_mbean_operational_surface` | `StorageProxyMBean` / `StorageProxy` JMX methods | read/write timeout setters, read repair counters, logging timer, repaired-data tracking toggles. | `test/unit/org/apache/cassandra/service/StorageProxyTest.java:127` |
| `storageproxy_existing_tests_baseline` | unit + distributed tests | Existing coverage includes write ideal CL, read speculation, request timeout, read failure race, read repair behavior; it does not provide focused ordinary write cheap-quorum backup or full read-warning abort matrix tests. | `WriteResponseHandlerTest`、`ReadExecutorTest`、`RequestTimeoutTest`、`ReadSpeculationTest`、`ReadFailureTest`、`ReadRepairTest` |

## 文字调用图

### 普通写

```text
native QUERY/EXECUTE/BATCH
  -> QueryProcessor / ModificationStatement
  -> StorageProxy.mutate(mutations, consistencyLevel, requestTime)
     -> for each mutation:
        -> performWrite(mutation, CL, localDC, standardWritePerformer, ...)
           -> ReplicaPlans.forWrite(keyspace, CL, token, writeNormal)
           -> replicationStrategy.getWriteResponseHandler(...)
           -> standardWritePerformer.apply(...)
              -> StorageProxy.sendToHintedReplicas(...)
                 -> down replica: responseHandler.expired(); maybe submitHint(...)
                 -> remote live replica: MUTATION_REQ with CALL_BACK_ON_FAILURE
                 -> local live replica: Stage.MUTATION performLocally(... mutation.apply ...)
     -> maybeTryAdditionalReplicas(...) for non-counter cheap quorum backup
     -> responseHandler.get()
        -> success: return
        -> timeout/failure: mark write metrics or hint CL.ANY
     -> finally update write request and table coordinator latency
```

### 普通单分区读

```text
native SELECT
  -> QueryProcessor / SelectStatement
  -> StorageProxy.read(group, CL, requestTime)
     -> bootstrap safety / partition denylist gate
     -> serial CL ? readWithPaxos(...) : readRegular(...)
        -> fetchRows(commands, CL, requestTime)
           -> AbstractReadExecutor.getReadExecutor(command, CL, requestTime)
              -> ReplicaPlans.forRead(...)
              -> choose NeverSpeculatingReadExecutor / SpeculatingReadExecutor / AlwaysSpeculatingReadExecutor
           -> executeAsync()
              -> full data request(s) + transient data requests + digest requests
           -> maybeTryAdditionalReplicas()
           -> awaitResponses(logBlockingRepairAttempts)
              -> ReadCallback.awaitResults()
              -> DigestResolver.responsesMatch()
              -> if mismatch: ReadRepair.startRepair(...)
           -> maybeSendAdditionalDataRequests()
           -> awaitReadRepair()
           -> getResult() and getReadRepair()
        -> concatAndBlockOnRepair(results, repairs)
           -> iterator close:
              -> repairs.maybeSendAdditionalWrites()
              -> repairs.awaitWrites()
        -> finally update read request and table coordinator latency
```

## 运维关注点

- `ReadTimeoutException` with `data_present=false` usually means no full data response reached the coordinator; `data_present=true` during read repair means initial CL was met but repair/full-data phase timed out.
- `WriteTimeoutException` on CL.ANY can still result in hints; for CL > ANY the exception is surfaced and write metrics mark timeout/failure.
- `speculative_retry='ALWAYS'` can increase read fan-out and coordinator pressure; percentile/custom policies rely on table `sampleReadLatencyMicros` and will not speculate past native transport deadline.
- Temporarily enabling `logBlockingReadRepairAttemptsForNSeconds()` can explain unexpected blocking read repair latency, but it is a time-boxed diagnostic switch.
- `read_repair='BLOCKING'` preserves monotonic quorum reads by waiting on repair writes; `NONE` avoids repair write latency but can leave replicas divergent until repair/compaction/anti-entropy catches up.
- Partition denylist read rejection increments denylist metrics and throws `InvalidRequestException`, not a read timeout.

## 性能瓶颈

- Coordinator fan-out grows with CL, transient/full replica layout, read repair mismatch, speculative retry and cheap quorum backup.
- `DataResolver` short read protection and replica filtering protection can trigger extra reads beyond the initial data/digest set.
- Blocking read repair writes happen when the result iterator closes; slow clients that hold iterators open can delay repair write accounting.
- Table latency samples influence speculation and cheap quorum backup. Bad samples can either under-speculate slow replicas or over-speculate healthy traffic.
- Hints and `CALL_BACK_ON_FAILURE` on writes add failure-path work even when the client sees timeout/failure.

## 常见故障

- `WriteFailureException` with failure reasons: handler saw enough failure callbacks that CL can no longer be achieved; if all failure reasons are timeout-like it is converted to timeout.
- `ReadFailureException` with `READ_TOO_MANY_TOMBSTONES`: replica rejected the read, `ReadCallback` maps warning/failure reason to failure; see `ReadFailureTest`.
- Read repair timeout: data was reconciled or repair mutation may have been applied, but coordinator timed out waiting for repair ack; `ReadRepairTest.readRepairTimeoutTest()` captures this boundary.
- Speculation did not fire: table has no latency sample, sample exceeds RPC timeout, no extra candidate exists, CL is EACH_QUORUM, or native client deadline would be missed.
- Ideal CL failures rising while requested CL succeeds: write availability is meeting client CL but missing preferred/ideal replica coverage.

## 测试覆盖与缺口

- 覆盖：`WriteResponseHandlerTest` validates ideal CL latency/failure counters for `WriteResponseHandler` / `DatacenterWriteResponseHandler` / `DatacenterSyncWriteResponseHandler`.
- 覆盖：`RequestTimeoutTest` drops `MUTATION_REQ` / `READ_REQ` and asserts `WriteTimeoutException` / `ReadTimeoutException` plus timeout-like failure classification.
- 覆盖：`ReadExecutorTest` validates speculation metrics, failed speculation metrics and speculative failure race mapping to `ReadFailureException`.
- 覆盖：`ReadSpeculationTest` validates native deadline and `cql_start_time` effects on speculation.
- 覆盖：`ReadRepairTest` validates `BLOCKING` vs `NONE`, read repair timeout, failed repair request and moving-token speculative repair write.
- 缺口：ordinary write cheap quorum backup has source protection but no focused unit/distributed test that validates `maybeTryAdditionalReplicas()` plus `additionalWrites`.
- 缺口：`ReadCallback` warning/abort matrix is covered indirectly by threshold tests, but there is no single focused table that enumerates warning-only, abort, timeout-like failure and non-timeout failure combinations for ordinary single-partition reads.
