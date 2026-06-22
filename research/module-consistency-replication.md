# Module: Consistency, Replica Plans, Replication

## 范围

本模块覆盖 ConsistencyLevel、ReplicaPlan、replication strategy 和 range read planning，说明协调器如何从复制拓扑中选择读写参与者。

## 设计目标

Consistency 和 replica planning 把 CQL 请求的一致性级别转换成 coordinator 需要联系哪些 replicas、需要等待多少响应、哪些失败可以立即判定不可用。

设计目标：

- 用 `ConsistencyLevel.blockFor()` 为读写计算满足 CL 所需响应数。
- 根据 replication strategy、token/range、failure detector 和 snitch 顺序生成 read/write `ReplicaPlan`。
- 区分 read candidates、contacts、write live/liveAndDown/pending，支持 speculation、read repair、hint、pending range 和 transient replica。
- 对 `LOCAL_*`、`EACH_QUORUM`、`ANY`、`SERIAL/LOCAL_SERIAL` 提供不同的合法性与等待语义。
- Range read 按 token ranges 拆分 plan，并在满足 CL 的前提下合并相邻 ranges，降低跨节点请求数。

## 解决的问题

- CL 不是简单的副本数量：`ConsistencyLevel.blockFor()` 对 ONE/TWO/THREE/QUORUM/ALL/LOCAL_QUORUM/EACH_QUORUM 分别计算，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:133-170`。
- 写入需要考虑 pending replicas：`blockForWrite()` 会把 pending endpoints 加入等待目标，LOCAL CL 只加本 DC pending，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:172-191`。
- 读不能只看 endpoint live 个数，还至少要有 full replica：`ReplicaPlans.isSufficientLiveReplicasForRead()` 默认要求 live 数达到 blockFor 且 full replica > 0，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:98-127`。
- 写入 contacts 和等待数不同：`ReplicaPlan.ForWrite` 保存 pending、liveAndDown、live、contacts，并用 `writeQuorum()` 计算等待数，见 `src/java/org/apache/cassandra/locator/ReplicaPlan.java:187-217`。
- Range read 的一个 CQL 查询可能覆盖多个 vnode range，必须拆成不重叠 subranges，否则 replica 会返回重复结果，见 `src/java/org/apache/cassandra/service/reads/range/ReplicaPlanIterator.java:87-130`。

## 设计取舍

- `ReplicaPlan` 保存 replication strategy snapshot，避免查询执行过程中 keyspace replication strategy 改变导致 blockFor 不一致，见 `src/java/org/apache/cassandra/locator/ReplicaPlan.java:52-59`。
- Read plan 分离 candidates 与 contacts：contacts 是初始请求目标，candidates 用于 speculation/read repair 后续追加，见 `src/java/org/apache/cassandra/locator/ReplicaPlan.java:87-116`。
- Range read 当前没有普通 read speculation；`forRangeRead()` 总是 `alwaysSpeculate=false`，失败响应会失败整个 range query，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:730-748`。
- `EACH_QUORUM` 在读路径要按 DC 选 quorum，并且注释明确不做 speculation，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:659-685`。
- Normal writes 默认写所有 full natural replicas 和 pending replicas；只有为 transient replication 补足承诺时才选择 transient replicas，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:504-545`。
- `ANY` 对读非法，对普通写可由本地 hint 满足；`validateForRead()` 明确拒绝 `ANY`，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:208-215`。

## 核心类

| 类 | 作用 |
|---|---|
| `ConsistencyLevel` | CQL/binary protocol CL 枚举、blockFor、local quorum、读写合法性。定义见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:35-88` |
| `ReplicaPlan` | coordinator 本次请求的 keyspace、RS snapshot、CL、contacts 抽象。定义见 `src/java/org/apache/cassandra/locator/ReplicaPlan.java:30-85` |
| `ReplicaPlan.ForTokenRead` | 单 token 读 plan，持有 read candidates 和 contacts。定义见 `src/java/org/apache/cassandra/locator/ReplicaPlan.java:119-134` |
| `ReplicaPlan.ForRangeRead` | range read plan，额外持有 range 和 vnodeCount。定义见 `src/java/org/apache/cassandra/locator/ReplicaPlan.java:136-165` |
| `ReplicaPlan.ForWrite` | 写 plan，持有 pending、liveAndDown、live、contacts。定义见 `src/java/org/apache/cassandra/locator/ReplicaPlan.java:187-217` |
| `ReplicaPlans` | plan factory 和 replica selection policy。定义见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:82-98` |
| `AbstractReplicationStrategy` | 自然副本计算抽象和 write response handler 选择。定义见 `src/java/org/apache/cassandra/locator/AbstractReplicationStrategy.java:126-174` |
| `SimpleStrategy` | 顺 ring 选择 RF 个不同 endpoints。实现见 `src/java/org/apache/cassandra/locator/SimpleStrategy.java:59-82` |
| `NetworkTopologyStrategy` | 按 DC/RF/rack 分散选择 replicas。构造和 rack 逻辑见 `src/java/org/apache/cassandra/locator/NetworkTopologyStrategy.java:70-155` |
| `ReplicaPlanIterator` | range read 按 token metadata 拆分 subranges 并生成 `ForRangeRead`。定义见 `src/java/org/apache/cassandra/service/reads/range/ReplicaPlanIterator.java:45-85` |
| `ReplicaPlanMerger` | 合并相邻 range plans，降低 range query 请求数。定义见 `src/java/org/apache/cassandra/service/reads/range/ReplicaPlanMerger.java:45-75` |
| `RangeCommandIterator` | range read 批量发送、等待、合并、动态调整并发。定义见 `src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:60-99` |

## 核心接口

- `ReplicaPlan.contacts()`：本次请求会发消息或本地执行的 replicas，定义见 `src/java/org/apache/cassandra/locator/ReplicaPlan.java:30-39`。
- `ReplicaPlan.ForRead.readCandidates()`：读可追加联系的候选 replicas，用于 speculation/read repair，见 `src/java/org/apache/cassandra/locator/ReplicaPlan.java:41-49`。
- `ReplicaPlans.Selector`：写 replica selection 策略接口，`writeNormal`、`writeAll`、`writeReadRepair` 都基于它实现，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:479-482`。
- `ReadCallback`：读等待 blockFor responses，range read 构造时断言 contacts 数必须不小于 blockFor，见 `src/java/org/apache/cassandra/service/reads/ReadCallback.java:78-90`。
- `AbstractWriteResponseHandler`：写等待、timeout/failure、hint-on-failure 抽象，见 `src/java/org/apache/cassandra/service/AbstractWriteResponseHandler.java:112-150`。

## 核心数据结构

- `ReplicationFactor`：`ConsistencyLevel.quorumFor()` 读取 `replicationStrategy.getReplicationFactor().allReplicas`，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:91-100`。
- `EndpointsForToken` / `EndpointsForRange`：读写 plan 中的 natural/pending/live/contacts 集合类型。
- `Replica`：封装 endpoint、range、full/transient 标记；NTS 通过 `new Replica(ep, replicatedRange, rfLeft > transients)` 创建，见 `src/java/org/apache/cassandra/locator/NetworkTopologyStrategy.java:139-155`。
- `ReplicaPlan.SharedForTokenRead` / `SharedForRangeRead`：read executor、resolver、read repair 共享可追加 contacts 的 plan reference，见 `src/java/org/apache/cassandra/locator/ReplicaPlan.java:251-292`。
- `DataRange` / `AbstractBounds<PartitionPosition>`：range read 的查询范围，`PartitionRangeReadCommand.forSubRange()` 创建 subrange command，见 `src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java:188-210`。

## 生命周期

单 token read plan：

```text
StorageProxy.fetchRows()
  -> AbstractReadExecutor.getReadExecutor()
     -> ReplicaPlans.forRead(keyspace, token, indexPlan, CL, retryPolicy)
        -> ReplicaLayout.forTokenReadLiveSorted(...)
        -> candidatesForRead(...)
        -> contactForRead(...)
        -> assureSufficientLiveReplicasForRead(...)
        -> new ReplicaPlan.ForTokenRead(candidates, contacts)
```

write plan：

```text
StorageProxy.performWrite()
  -> ReplicaPlans.forWrite(keyspace, CL, token, ReplicaPlans.writeNormal)
     -> ReplicaLayout.forTokenWriteLiveAndDown(...)
     -> filter live by FailureDetector.isReplicaAlive
     -> writeNormal.select(...)
     -> assureSufficientLiveReplicasForWrite(...)
     -> new ReplicaPlan.ForWrite(pending, liveAndDown, live, contacts)
  -> replicationStrategy.getWriteResponseHandler(replicaPlan, ...)
     -> DatacenterWriteResponseHandler for LOCAL_*
     -> DatacenterSyncWriteResponseHandler for EACH_QUORUM + NTS
     -> WriteResponseHandler otherwise
```

range read：

```text
PartitionRangeReadCommand.execute(CL)
  -> StorageProxy.getRangeSlice(command, CL, requestTime)
     -> denylist range check
     -> RangeCommands.partitions(command, CL, requestTime)
        -> ReplicaPlanIterator(keyRange, keyspace, CL)
           -> split keyRange by token metadata
           -> ReplicaPlans.forRangeRead(...) per subrange
        -> estimate initial concurrency
        -> ReplicaPlanMerger(...)
        -> RangeCommandIterator(...)
           -> sendNextRequests()
           -> query(replicaPlan)
              -> command.forSubRange(...)
              -> ReadRepair.create(...)
              -> DataResolver + ReadCallback
              -> local Stage.READ or MessagingService.sendWithCallback(...)
           -> concatAndBlockOnRepair(...)
           -> update concurrency from returned rows
```

## 调用链

- CL enum 与 protocol code 定义见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:35-88`。
- `quorumFor()`、`localQuorumFor()`、`eachQuorumForRead()` 计算全局/本地/每 DC quorum，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:91-124`。
- `blockFor()` 和 `blockForWrite()` 是读写等待数核心，见 `src/java/org/apache/cassandra/db/ConsistencyLevel.java:133-191`。
- read live replica 检查在 `assureSufficientLiveReplicasForRead()`，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:130-138`。
- write live replica 检查在 `assureSufficientLiveReplicasForWrite()`，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:134-195`。
- write plan 构造在 `ReplicaPlans.forWrite()`，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:447-476`。
- read plan 构造在 `ReplicaPlans.forRead()`，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:708-728`。
- range read plan 构造在 `ReplicaPlans.forRangeRead()`，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:730-748`。
- adjacent range merge 在 `ReplicaPlans.maybeMerge()` 与 `ReplicaPlanMerger.computeNext()`，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:772-793`、`src/java/org/apache/cassandra/service/reads/range/ReplicaPlanMerger.java:45-75`。
- write response handler 选择由 replication strategy 决定，见 `src/java/org/apache/cassandra/locator/AbstractReplicationStrategy.java:154-174`。
- generic write ack handler 在 `WriteResponseHandler.onResponse()` 中递减 `responses`，见 `src/java/org/apache/cassandra/service/WriteResponseHandler.java:43-72`。
- EACH_QUORUM 写 handler 为每个 DC 建立 quorum counter，见 `src/java/org/apache/cassandra/service/DatacenterSyncWriteResponseHandler.java:46-76`。

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| keyspace replication strategy/RF | CQL schema，运行时由 `Keyspace.getReplicationStrategy()` 读取 | 决定 natural replicas 和 quorum 基数 |
| `read_request_timeout` | `src/java/org/apache/cassandra/config/Config.java:144-145`，模板 `conf/cassandra.yaml:1322` | 单 token read timeout |
| `range_request_timeout` | `src/java/org/apache/cassandra/config/Config.java:147-148`，模板 `conf/cassandra.yaml:1323-1326` | range read timeout，`PartitionRangeReadCommand.getTimeout()` 使用 |
| `write_request_timeout` | `src/java/org/apache/cassandra/config/Config.java:150-151`，模板 `conf/cassandra.yaml:1327-1330` | write timeout |
| `cassandra.max_concurrent_range_requests` | `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:350` | range read 最大并发 subrange 请求数，默认 CPU cores * 10 |
| `repaired_data_tracking_for_range_reads_enabled` | `src/java/org/apache/cassandra/config/Config.java:716-722`，模板 `conf/cassandra.yaml:1948-1953` | range read repaired data tracking |
| `partition_denylist_enabled` / `denylist_range_reads_enabled` | `src/java/org/apache/cassandra/config/Config.java:758-765`，模板 `conf/cassandra.yaml:1438-1442` | range read denylist 拒绝 |
| `ideal_consistency_level` | `AbstractWriteResponseHandler` 通过 `DatabaseDescriptor.getIdealConsistencyLevel()` 传入 | 请求 CL 达成后继续观测 ideal CL 写入质量 |

## Metrics

- `ClientRangeRequestMetrics("RangeSlice")` 定义 range read request metrics，并新增 `RoundTripsPerReadHistogram`，见 `src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:60-65`、`src/java/org/apache/cassandra/metrics/ClientRangeRequestMetrics.java:29-47`。
- `RangeCommandIterator` 在 timeout/failure/abort 时更新 `rangeMetrics`，见 `src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:135-147`。
- `TableMetrics.rangeLatency` 是本地 range slice latency，定义/注册见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:108-120`、`src/java/org/apache/cassandra/metrics/TableMetrics.java:628-630`。
- `TableMetrics.sstablesPerRangeReadHistogram` 记录 range read 扫过的 SSTable 数，定义/更新见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:108-113`、`src/java/org/apache/cassandra/metrics/TableMetrics.java:890-893`。
- Partition denylist range reject meter 为 `StorageProxy.PartitionDenylist.RangeReadRejected`，见 `src/java/org/apache/cassandra/metrics/DenylistMetrics.java:30-57`。
- 写 CL 的 timeout/failure 由 `ClientRequestMetrics.writeMetrics` 和 write response handler 异常体现，前置详见 `flow-write.md`。

## 日志

- `ReplicaPlans.assureSufficientLiveReplicas()` 对 LOCAL_QUORUM 和普通 CL 不足有 trace 日志，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:152-194`。
- Range read 计算并发时记录 trace 和 tracing，包括 ranges 数、预估 rows/range、concurrency factor，见 `src/java/org/apache/cassandra/service/reads/range/RangeCommands.java:84-107`。
- Range read 发送每个 subrange 时 trace `Enqueuing request to ...`，见 `src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:211-217`。
- Range read 如果首轮 rows 不足，会 trace 新 concurrency factor，见 `src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:151-177`。
- Read callback timeout/failure 会 trace/debug received/blockFor/data-present，见 `src/java/org/apache/cassandra/service/reads/ReadCallback.java:128-178`。
- Write response handler timeout/failure 抛异常时会携带 CL、received、blockFor、writeType，见 `src/java/org/apache/cassandra/service/AbstractWriteResponseHandler.java:112-150`。

## 运维关注点

- `QUORUM` 在多 DC 下是全局 RF quorum；`LOCAL_QUORUM` 只看本 DC，跨 DC 网络故障时两者行为完全不同。
- `EACH_QUORUM` 对 NTS 写入要求每个 DC 都达到 local quorum；一个远端 DC 不足会导致整个写不可用。
- `ANY` 只适用于写，读路径会直接拒绝。
- Pending endpoints 会提高写 `blockForWrite()`；bootstrap/move 时写超时可能来自 pending replica 不可达。
- Range read 的初始并发根据本地估算和 limit 计算，估算偏差会导致多轮 range requests 和更高尾延迟。
- Range read 不做普通 speculation，某个 contacted replica 慢或失败时更容易拖垮整个查询。
- `cassandra.max_concurrent_range_requests` 不是 yaml 配置，而是 system property；调大可提升大范围 scan 并发，但会增加 replica 压力。
- `repaired_data_tracking_for_range_reads_enabled` 会给所有 range reads 增加 repaired data tracking 开销，配置模板也提示这点，见 `conf/cassandra.yaml:1948-1953`。

## 性能瓶颈

- Range read 的主要成本是 subrange 数量、每个 subrange 的 contacted replicas、SSTable overlap 和 coordinator merge。
- `ReplicaPlanMerger` 只有在相邻 ranges 共享足够 live endpoints 且 snitch 判断值得合并时才合并；token 分布和 endpoint 排序会直接影响请求数。
- `SSTablesPerRangeReadHistogram` 高表示本地范围扫描读放大大，通常与 compaction backlog、wide rows、overlap 或二级索引相关。
- `EACH_QUORUM` 和 `ALL` 放大 tail latency；任何一个 required replica 或 DC 慢都会影响成功。
- 写路径发送 targets 通常多于 blockFor，尤其 full replicas + pending replicas + transient 补足逻辑会增加网络写放大。

## 常见故障

- `UnavailableException`：`assureSufficientLiveReplicas*` 在 live/full replica 数不足时抛出，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:138-195`。
- `ReadTimeoutException`：`ReadCallback.awaitResults()` 未在 `range_request_timeout/read_request_timeout` 前收到 blockFor 且包含 data 的响应，见 `src/java/org/apache/cassandra/service/reads/ReadCallback.java:128-178`。
- `WriteTimeoutException`：`AbstractWriteResponseHandler.get()` 未等到 blockFor acks，见 `src/java/org/apache/cassandra/service/AbstractWriteResponseHandler.java:112-150`。
- LOCAL CL 收到非本 DC 响应：`ReadCallback.assertWaitingFor()` 有断言保护，见 `src/java/org/apache/cassandra/service/reads/ReadCallback.java:258-266`。
- Range read denylist reject：`StorageProxy.getRangeSlice()` 在 denylisted keys 数 > 0 时抛 InvalidRequest，见 `src/java/org/apache/cassandra/service/StorageProxy.java:2277-2294`。
- Top-K range query 使用 `ScanAllRangesCommandIterator`，仅适用于 `ONE/LOCAL_ONE`，并跳过 read repair，见 `src/java/org/apache/cassandra/service/reads/range/ScanAllRangesCommandIterator.java:47-58`、`src/java/org/apache/cassandra/service/reads/range/ScanAllRangesCommandIterator.java:112-113`。

## 测试用例

- `test/unit/org/apache/cassandra/locator/ReplicaPlansTest.java`
- `test/unit/org/apache/cassandra/locator/ReplicaLayoutTest.java`
- `test/unit/org/apache/cassandra/service/reads/ReadExecutorTest.java`
- `test/unit/org/apache/cassandra/service/reads/range/RangeCommandIteratorTest.java`
- `test/unit/org/apache/cassandra/service/reads/range/RangeCommandsTest.java`
- `test/unit/org/apache/cassandra/service/reads/range/ReplicaPlanIteratorTest.java`
- `test/unit/org/apache/cassandra/service/reads/range/ReplicaPlanMergerTest.java`
- `test/unit/org/apache/cassandra/db/PartitionRangeReadTest.java`
- `test/unit/org/apache/cassandra/cql3/NodeLocalConsistencyTest.java`
- `test/unit/org/apache/cassandra/db/guardrails/GuardrailReadConsistencyLevelsTest.java`
- `test/unit/org/apache/cassandra/db/guardrails/GuardrailWriteConsistencyLevelsTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/ReadRepairRangeQueriesTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/OutOfTokenRangeTest.java`
- `test/distributed/org/apache/cassandra/distributed/upgrade/MixedModeConsistencyTest.java`

## 待继续

- `research/module-consistency-replication-deep-dive.md` 已补 transient full/transient read/write、snitch/dynamic snitch read ordering 和 guardrail 主线。
- `research/module-consistency-replication-third-round.md` 已补 multi-DC CL policy/guardrail 操作矩阵、transient repair/streaming/pending range failure-injection matrix、dynamic snitch topology-change runbook 和 system keyspace RF 操作差异。
- `research/module-consistency-guardrail-profiles.md` 和 `research/tools/check-consistency-guardrail-profile-drift.py` 已补 workload-specific CL guardrail profile 模板、custom provider 边界和 source-to-profile drift 检查。
- `research/module-system-keyspace-rf-drift-checker.md` 和 `research/tools/check-system-keyspace-rf-drift.py` 已补 system keyspace 分类、local/replicated metadata、RF default property 到研究矩阵的 drift 检查。
- `research/module-dynamic-snitch-topology-regression.md`、`research/module-dynamic-snitch-drift-checker.md` 和 `research/tools/check-dynamic-snitch-topology-drift.py` 已补 dynamic snitch topology-change regression matrix、decommission severity、batchlog dynamic strategy、JMX/updateSnitch 操作面和 source-to-doc drift 检查。
- Paxos/SERIAL/LOCAL_SERIAL 的主链路已在 `research/flow-lwt-paxos.md`、`research/module-coordination-lwt-counter-hints-internals.md` 和 `research/module-coordination-fault-coverage-runbook.md` 展开；仍需实现或取得 transient repair/streaming 专项 distributed fault tests。
