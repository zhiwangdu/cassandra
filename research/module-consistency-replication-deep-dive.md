# Consistency/Replication Deep Dive

## 范围

本文补充 `research/module-consistency-replication.md` 的第二轮源码细节，聚焦：

- read/write consistency level guardrails 的配置、JMX 暴露、statement 执行点和 serial CL 处理。
- transient replication 的 RF 表达、DDL 限制、full/transient replica 标记、read/write plan 选择和读响应校验。
- snitch/proximity 排序如何进入 read replica candidates、range read candidates、batchlog endpoint 选择和动态 snitch 分数。

不重复第一轮已经覆盖的 `ConsistencyLevel.blockFor()`、`ReplicaPlan` 基础结构和 range read 并发主链路；不展开 repair/streaming 对 transient SSTable 的所有行为，只引用与 consistency/replication 直接相关的边界。

## 设计目标

- Consistency guardrails 给运维提供“允许但告警”与“直接拒绝”两级控制，避免应用在生产误用 `ALL`、跨 DC `QUORUM` 或 serial CL。定义在 `src/java/org/apache/cassandra/db/guardrails/Guardrails.java:308`，配置模板在 `conf/cassandra.yaml:2107`。
- Transient replication 让 keyspace 用 fewer full replicas + transient replicas 降低长期存储成本，同时保留读写一致性承诺。RF 由 `ReplicationFactor.allReplicas` 和 `fullReplicas` 表达，`3/1` 表示 total=3、transient=1、full=2，见 `src/java/org/apache/cassandra/locator/ReplicationFactor.java:33` 和 `src/java/org/apache/cassandra/locator/ReplicationFactor.java:110`。
- Replica selection 必须把“是否 live”“是否 full/transient”“是否 local DC”“snitch 排序”“index 可查询状态”分开处理，避免 transient 节点承担 full data/digest 语义。读候选生成在 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:649`，contact 选择在 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:670`。
- Snitch 排序要影响初始 read contacts，但不能绕过 failure detector、CL blockFor 和 full replica 要求。排序入口在 `src/java/org/apache/cassandra/locator/ReplicaLayout.java:329` 和 `src/java/org/apache/cassandra/locator/ReplicaLayout.java:342`。

## 解决的问题

- 读 CL guardrail 必须在 CQL SELECT 入口执行，而不是等到 replica plan 之后。`SelectStatement.execute()` 先 `validateForRead()`，再调用 `Guardrails.readConsistencyLevels.guard()`，见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:280`。
- 写 CL guardrail 必须同时检查 normal CL 和 serial CL。`ModificationStatement` 与 `BatchStatement` 都把 `options.getConsistency()` 和 `options.getSerialConsistency()` 放入同一个 set，见 `src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:491`、`src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:408`。
- transient RF 不能只是 schema 字符串。`ReplicationFactor.validate()` 要求 transient replication 开启、transient 数小于 total RF、单 token、非 4.0 以前混合版本集群，见 `src/java/org/apache/cassandra/locator/ReplicationFactor.java:62`。
- transient keyspace 不能与若干功能随意组合。`AlterKeyspaceStatement.validateTransientReplication()` 禁止 vnodes、已有 materialized views、已有 secondary indexes，并限制 full/transient 转换顺序，见 `src/java/org/apache/cassandra/cql3/statements/schema/AlterKeyspaceStatement.java:145`。
- read plan 至少要有一个 full replica。`ReplicaPlans.isSufficientLiveReplicasForRead()` 对 local/global CL 都要求满足 blockFor 且 full replica 数大于 0，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:98`。
- transient replica 不能接收 digest request，也不能用 full read request 服务 transient-local 数据。`ReadCommand.copyAsDigestQuery()` 拒绝 transient replica，`ReadCommandVerbHandler.validateTransientStatus()` 在接收端校验 local replica 状态，见 `src/java/org/apache/cassandra/db/ReadCommand.java:337`、`src/java/org/apache/cassandra/db/ReadCommandVerbHandler.java:137`。
- dynamic snitch 不能无条件重排底层 snitch 结果。`DynamicEndpointSnitch` 在 badness threshold 不为 0 时先按 subsnitch 排序，再仅在分数偏差超过阈值时切换到 score 排序，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:193`。

## 设计取舍

- CL guardrail 配置默认为空集合，即默认允许所有 CL；这是兼容优先的设计。`conf/cassandra.yaml:2107` 明确写明默认允许所有 read/write consistency levels。
- guardrail 放在 statement 层，而不是 `ConsistencyLevel` 枚举层，使内部查询、特殊用户和 CQL statement 类型可以通过 `ClientState` 控制绕过/告警策略。读写入口见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:286`、`src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:497`。
- transient replication 默认关闭。配置在 `conf/cassandra.yaml:1996`，运行时开关在 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4267`。
- transient RF 校验重复出现在 `ReplicationFactor.validate()` 和 replication strategy validation 中，是为了分别覆盖 schema option parse 和 strategy validate 两个入口。见 `src/java/org/apache/cassandra/locator/ReplicationFactor.java:62`、`src/java/org/apache/cassandra/locator/AbstractReplicationStrategy.java:409`。
- write conflicts 中 full 优先。`ReplicaLayout` 明确在 pending 和 natural 发生 full/transient 冲突时偏向 full replica，因为 full 更严格、更符合运维预期，见 `src/java/org/apache/cassandra/locator/ReplicaLayout.java:225`。
- normal writes 默认写 full natural replicas 和 pending replicas，再按需补 live transient replicas；这比只写 blockFor 更保守，目的是降低 transient replication 给用户带来的意外。见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:504`。
- SimpleSnitch 不排序，直接返回原集合；DynamicEndpointSnitch 包装 subsnitch 并用读延迟分数调整。见 `src/java/org/apache/cassandra/locator/SimpleSnitch.java:40`、`src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:175`。

## 核心类

- `Guardrails`：定义 `readConsistencyLevels` 和 `writeConsistencyLevels` 两个 `Values<ConsistencyLevel>` guardrail，并提供 JMX getter/setter/CSV 转换。定义见 `src/java/org/apache/cassandra/db/guardrails/Guardrails.java:308`，JMX 方法见 `src/java/org/apache/cassandra/db/guardrails/Guardrails.java:1024`。
- `SelectStatement`：SELECT 执行入口，校验 read CL 并触发 read CL guardrail；Top-K 查询还会拒绝 SERIAL/LOCAL_SERIAL 并将需要 reconciliation 的 CL downgrade 到 ONE/LOCAL_ONE。见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:280`。
- `ModificationStatement`：INSERT/UPDATE/DELETE 执行入口，先检查 normal/serial CL guardrail，再进入 conditional 或 non-conditional 写路径。见 `src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:491`。
- `BatchStatement`：batch 执行入口，同样检查 normal/serial CL guardrail。见 `src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:408`。
- `ReplicationFactor`：解析 full-only 或 transient RF，保存 total/full 数，提供 `transientReplicas()`、`hasTransientReplicas()` 和 `toParseableString()`。见 `src/java/org/apache/cassandra/locator/ReplicationFactor.java:33`、`src/java/org/apache/cassandra/locator/ReplicationFactor.java:47`、`src/java/org/apache/cassandra/locator/ReplicationFactor.java:125`。
- `AlterKeyspaceStatement`：alter RF 时校验 range movement、transient replication 限制、full/transient 变化顺序，并在增加 full RF 时提示 full repair。见 `src/java/org/apache/cassandra/cql3/statements/schema/AlterKeyspaceStatement.java:91`、`src/java/org/apache/cassandra/cql3/statements/schema/AlterKeyspaceStatement.java:120`。
- `SimpleStrategy`：顺 ring 添加 `rf.allReplicas` 个不同 endpoint，前 `rf.fullReplicas` 个标记 full，其余 transient。见 `src/java/org/apache/cassandra/locator/SimpleStrategy.java:59`。
- `NetworkTopologyStrategy`：按 DC/rack 选择 replicas，节点数不足时会降低 effective RF 并相应减少 transient 数；新增 replica 时用 `rfLeft > transients` 决定 full/transient。见 `src/java/org/apache/cassandra/locator/NetworkTopologyStrategy.java:120`、`src/java/org/apache/cassandra/locator/NetworkTopologyStrategy.java:139`。
- `Replica`：把 endpoint、range、full 标记绑定在一起，避免调用方丢失 transientness。见 `src/java/org/apache/cassandra/locator/Replica.java:38`、`src/java/org/apache/cassandra/locator/Replica.java:52`。
- `ReplicaLayout`：构造 write/read layout，处理 natural/pending full/transient 冲突，并在 read layout 中调用 snitch 排序、failure detector 过滤。见 `src/java/org/apache/cassandra/locator/ReplicaLayout.java:205`、`src/java/org/apache/cassandra/locator/ReplicaLayout.java:273`、`src/java/org/apache/cassandra/locator/ReplicaLayout.java:329`。
- `ReplicaPlans`：根据 layout、CL、index plan 和 retry policy 选择 candidates/contacts，检查 live/full 数是否足够，并为 transient writes 选择额外 transient targets。见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:98`、`src/java/org/apache/cassandra/locator/ReplicaPlans.java:504`、`src/java/org/apache/cassandra/locator/ReplicaPlans.java:708`。
- `DynamicEndpointSnitch`：根据 subsnitch、badness threshold、读延迟 score 和 severity 调整 proximity 排序。见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:51`、`src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:175`、`src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:304`。

## 核心接口

- `IEndpointSnitch.getRack()`、`getDatacenter()`、`sortedByProximity()` 是 topology 与 read ordering 的核心接口。见 `src/java/org/apache/cassandra/locator/IEndpointSnitch.java:31`。
- `AbstractEndpointSnitch.compareEndpoints()` 给普通 snitch 提供排序比较器；默认 `sortedByProximity()` 只是按该 comparator 排序。见 `src/java/org/apache/cassandra/locator/AbstractEndpointSnitch.java:23`。
- `ReplicaPlans.Selector` 是 write target selection 接口，`writeNormal`、`writeAll`、read repair write 都通过它选择 contacts。基础接口在 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:479`，transient-aware normal selector 在 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:504`。
- `ReadCommand.copyAsTransientQuery()` 和 `copyAsDigestQuery()` 是 read path 上区分 transient/full 请求的接口。见 `src/java/org/apache/cassandra/db/ReadCommand.java:315`、`src/java/org/apache/cassandra/db/ReadCommand.java:337`。
- `GuardrailsMBean` 暴露 consistency guardrail JMX 操作，见 `src/java/org/apache/cassandra/db/guardrails/GuardrailsMBean.java:392`。

## 核心数据结构

- `ReplicationFactor`：
  - `allReplicas` 是 total RF。
  - `fullReplicas` 是 full RF。
  - `transientReplicas()` 返回 `allReplicas - fullReplicas`。
  - `fromString("N/T")` 解析 transient RF，见 `src/java/org/apache/cassandra/locator/ReplicationFactor.java:37`、`src/java/org/apache/cassandra/locator/ReplicationFactor.java:110`。
- `Replica`：`full=true` 表示 full replica，`full=false` 表示 transient replica；`toString()` 也会输出 Full/Transient，见 `src/java/org/apache/cassandra/locator/Replica.java:46`。
- `EndpointsForToken` / `EndpointsForRange`：保存 ordered replica collection，顺序受 snitch 排序影响，并保留 full/transient 标记。
- `ReplicaLayout.ForTokenWrite`：保存 natural 和 pending replicas，先解析 full/transient 冲突，再交给 write selector。入口见 `src/java/org/apache/cassandra/locator/ReplicaLayout.java:205`。
- `ReplicaPlan.ForTokenRead` / `ForRangeRead`：保存 read candidates 和 contacts；candidates 是 live natural replicas 经 snitch 排序和 index query filter 后的集合，contacts 是按 CL 取出的子集。见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:708`、`src/java/org/apache/cassandra/locator/ReplicaPlans.java:737`。
- `ReadCommand.acceptsTransient`：read command 序列化 flags 中的一位，用于告知 replica 该请求是否允许 transient 数据；序列化见 `src/java/org/apache/cassandra/db/ReadCommand.java:1135`。
- `DynamicEndpointSnitch.scores`：endpoint 到 score 的快照 map，score 基于 median latency/max latency 加 severity，最低分优先。见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:304`。

## 生命周期

Consistency guardrail 生命周期：

```text
cassandra.yaml / JMX
  -> Guardrails read/write consistency level sets
  -> SelectStatement.execute(): validateForRead then guard(read CL)
  -> ModificationStatement/BatchStatement.execute(): guard(normal CL + serial CL)
  -> Values.guard(): warn or reject for ordinary users
  -> normal query execution continues only if guardrail allows it
```

Transient keyspace lifecycle：

```text
CREATE/ALTER KEYSPACE replication options
  -> ReplicationFactor.fromString("replicas/transient")
  -> ReplicationFactor.validate()
  -> AbstractReplicationStrategy.validateReplicationFactor()
  -> AlterKeyspaceStatement.validateTransientReplication()
  -> SimpleStrategy/NTS calculate Replica(full/transient)
  -> ReplicaLayout and ReplicaPlans consume full/transient status
```

Read lifecycle with transient replicas：

```text
StorageProxy read
  -> ReplicaLayout.forTokenReadLiveSorted()/forRangeReadLiveSorted()
     -> natural replicas
     -> snitch.sortedByProximity()
     -> FailureDetector live filter
  -> ReplicaPlans.candidatesForRead()
     -> local DC filter and index query filter
  -> ReplicaPlans.contactForRead()
     -> EACH_QUORUM per DC or first blockFor candidates
  -> assureSufficientLiveReplicasForRead()
     -> require blockFor and at least one full replica
  -> AbstractReadExecutor/RangeCommandIterator
     -> full replicas receive data/digest requests
     -> transient replicas receive copyAsTransientQuery()
```

Write lifecycle with transient replicas：

```text
StorageProxy write
  -> ReplicaLayout.forTokenWriteLiveAndDown()
     -> natural replicas + pending replicas
     -> resolve full/transient conflicts, prefer full
  -> live = failure-detector-filtered liveAndDown
  -> ReplicaPlans.writeNormal.select()
     -> all full natural replicas
     -> all pending replicas
     -> enough live transient replicas for per-DC quorum target
  -> assureSufficientLiveReplicasForWrite()
  -> ReplicaPlan.ForWrite contacts sent by StorageProxy
```

Snitch score lifecycle：

```text
endpoint_snitch + dynamic_snitch config
  -> DatabaseDescriptor.createEndpointSnitch(dynamic, class)
  -> DynamicEndpointSnitch wraps subsnitch when enabled
  -> read latencies update score snapshots
  -> sortedByProximity()
     -> threshold 0: pure score order
     -> threshold > 0: subsnitch order unless score badness exceeds threshold
  -> ReplicaLayout read candidates consume sorted order
```

## 调用链

- Read guardrail: `SelectStatement.execute()` -> `ConsistencyLevel.validateForRead()` -> `Guardrails.readConsistencyLevels.guard()`，见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:282`。
- Write guardrail: `ModificationStatement.execute()` -> `Guardrails.writeConsistencyLevels.guard(EnumSet.of(normal, serial))` -> conditional/non-conditional path，见 `src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:491`。
- Batch guardrail: `BatchStatement.execute()` -> `Guardrails.writeConsistencyLevels.guard(EnumSet.of(normal, serial))`，见 `src/java/org/apache/cassandra/cql3/statements/BatchStatement.java:410`。
- RF parse: `ReplicationFactor.fromString()` -> `ReplicationFactor.validate()` -> `fullReplicas/allReplicas`，见 `src/java/org/apache/cassandra/locator/ReplicationFactor.java:110`。
- Strategy validation: replication strategy parse -> `AbstractReplicationStrategy.validateReplicationStrategy()` -> transient enabled check -> `validateReplicationFactor()`，见 `src/java/org/apache/cassandra/locator/AbstractReplicationStrategy.java:409`。
- NTS replica marking: `NetworkTopologyStrategy.DatacenterEndpoints.addEndpointAndCheckIfDone()` -> `new Replica(ep, range, rfLeft > transients)`，见 `src/java/org/apache/cassandra/locator/NetworkTopologyStrategy.java:139`。
- Read ordering: `ReplicaLayout.forTokenReadLiveSorted()` -> `DatabaseDescriptor.getEndpointSnitch().sortedByProximity()` -> `FailureDetector.isReplicaAlive`，见 `src/java/org/apache/cassandra/locator/ReplicaLayout.java:329`。
- Range read ordering: `ReplicaLayout.forRangeReadLiveSorted()` mirrors token read ordering,见 `src/java/org/apache/cassandra/locator/ReplicaLayout.java:342`。
- Contact selection: `ReplicaPlans.forRead()` -> `candidatesForRead()` -> `contactForRead()` -> `assureSufficientLiveReplicasForRead()`，见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:716`。
- EACH_QUORUM read: `contactForEachQuorumRead()` decrements per-DC quorum counters using snitch DC,见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:659`。
- Transient read request: `AbstractReadExecutor.executeAsync()` sends full data to initial full replicas, transient data requests to transient contacts, digest only to remaining full replicas，见 `src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java:178`。
- Range transient request: `RangeCommandIterator.query()` uses normal range command for full replica and `copyAsTransientQuery()` for transient replica，见 `src/java/org/apache/cassandra/service/reads/range/RangeCommandIterator.java:211`。
- Transient response handling: `ResponseResolver.preprocess()` rejects digest response from transient replica; `DigestResolver` skips transient digests and reconciles transient data when present，见 `src/java/org/apache/cassandra/service/reads/ResponseResolver.java:60`、`src/java/org/apache/cassandra/service/reads/DigestResolver.java:65`。

## 配置项

| 配置项 | 默认 | 作用 |
|---|---:|---|
| `read_consistency_levels_warned` | `[]` | 对指定 read CL 发 warning，不拒绝。模板见 `conf/cassandra.yaml:2107` |
| `read_consistency_levels_disallowed` | `[]` | 拒绝指定 read CL。模板见 `conf/cassandra.yaml:2107` |
| `write_consistency_levels_warned` | `[]` | 对指定 write/serial CL 发 warning。模板见 `conf/cassandra.yaml:2111` |
| `write_consistency_levels_disallowed` | `[]` | 拒绝指定 write/serial CL。模板见 `conf/cassandra.yaml:2111` |
| `transient_replication_enabled` | `false` | 是否允许 RF 使用 transient replicas。模板见 `conf/cassandra.yaml:1996`，getter 见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4267` |
| `num_tokens` | 配置相关 | transient RF 要求单 token；校验见 `src/java/org/apache/cassandra/locator/ReplicationFactor.java:70` |
| `endpoint_snitch` | `SimpleSnitch` | 基础 topology/proximity provider。模板见 `conf/cassandra.yaml:1473`、`conf/cassandra.yaml:1556` |
| `dynamic_snitch` | `true` | 是否用 `DynamicEndpointSnitch` 包装基础 snitch。构造见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1665` |
| `dynamic_snitch_update_interval` | `100ms` | dynamic snitch score 更新周期。默认见 `src/java/org/apache/cassandra/config/Config.java:423` |
| `dynamic_snitch_reset_interval` | `10m` | dynamic snitch score reset 周期。默认见 `src/java/org/apache/cassandra/config/Config.java:423` |
| `dynamic_snitch_badness_threshold` | `1.0` | subsnitch order 与 score order 的切换阈值。默认见 `src/java/org/apache/cassandra/config/Config.java:429` |
| `batchlog_endpoint_strategy` | `random_remote` | 可选 dynamic_remote/dynamic_remote_nonstrict，使用 dynamic snitch scores 选择 batchlog endpoints。说明见 `src/java/org/apache/cassandra/config/Config.java:1288` |

## Metrics

- Consistency guardrails 不直接新增专用 metrics；可见信号主要是 client warnings、query failures 和 guardrail JMX 配置。JMX getter/setter 在 `src/java/org/apache/cassandra/db/guardrails/Guardrails.java:1024`。
- Read CL 变化会影响 `ClientRequestMetrics` 和 read timeout/unavailable 计数，但触发点仍是 read callback/replica plan；基础 metrics 已在 `research/module-consistency-replication.md` 覆盖。
- Dynamic snitch 暴露 MBean `org.apache.cassandra.db:type=DynamicEndpointSnitch`，测试索引里也把 Scores 作为 JMX getter 覆盖点，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:85`、`test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java:47`。
- Dynamic snitch score 由 endpoint latency snapshots 和 severity 组合，`updateScores()` 中最低 score 胜出，见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:304`。
- Transient reads 的异常主要体现为 read unavailable、invalid request、digest mismatch/read repair 路径，而不是单独 metrics；`RepairDigestTrackingTest` 用 ByteBuddy 改写 read layout 来验证 digest tracking 边界，见 `test/distributed/org/apache/cassandra/distributed/test/RepairDigestTrackingTest.java:377`。

## 日志

- Guardrail warn/reject 消息由 `Values.guard()` 体系生成，read/write consistency guardrail 的用户可见消息在测试中断言。见 `test/unit/org/apache/cassandra/db/guardrails/GuardrailReadConsistencyLevelsTest.java:96`、`test/unit/org/apache/cassandra/db/guardrails/GuardrailWriteConsistencyLevelsTest.java:186`。
- `SelectStatement` 的 Top-K CL downgrade 会发送 `ClientWarn`，见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:308`。
- Alter RF 增加 full replicas 时会返回 client warning，提示需要 full repair 分发数据，见 `src/java/org/apache/cassandra/cql3/statements/schema/AlterKeyspaceStatement.java:120`。
- Read replica 不拥有 range 时会 warn；如果 full request 打到 transient local replica，会记录 dropped message 并抛 InvalidRequest，见 `src/java/org/apache/cassandra/db/ReadCommandVerbHandler.java:153`、`src/java/org/apache/cassandra/db/ReadCommandVerbHandler.java:164`。
- `ReplicaPlans.assureSufficientLiveReplicas()` 在 LOCAL_QUORUM/full 数不足时 trace live replica 不足细节，第一轮文档已索引 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:152`。
- Dynamic snitch score MBean 和 badness threshold 通常用于排查“为什么 coordinator 选了这个副本”，排序分支见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:175`。

## 运维关注点

- 对应用禁用某些 CL 时，必须同时考虑 normal CL 和 serial CL。例如禁用 `SERIAL` 会影响 LWT，即使 normal write CL 是 `QUORUM`。写 guardrail 使用 normal+serial set，见 `src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:497`。
- `read_consistency_levels_disallowed` 会在 SELECT statement 层拒绝请求；这比靠服务端超时/unavailable 更早失败，适合策略治理，但可能破坏旧客户端。
- transient replication 仍然是显式 opt-in，并且要求单 token；在 vnode 集群中直接被拒绝。见 `src/java/org/apache/cassandra/locator/ReplicationFactor.java:70`。
- 启用 transient replication 的 keyspace 不能直接与已有 MV/secondary index 组合；如果业务依赖这些功能，先不要把 RF 改成 `N/T`。见 `src/java/org/apache/cassandra/cql3/statements/schema/AlterKeyspaceStatement.java:165`。
- 修改 transient/full 数时不能跳过安全顺序。源码禁止在存在 transient replicas 时直接增加 full replicas，要求先移除 transient、改 full、再加回 transient。见 `src/java/org/apache/cassandra/cql3/statements/schema/AlterKeyspaceStatement.java:180`。
- read path 至少需要一个 full replica。只剩 transient replicas live 时，即使 total live replicas 达到 blockFor，也会 unavailable。见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:98`。
- transient read repair/repair/streaming 的完整运维语义跨模块，本文只覆盖 coordinator read/write 入口；修复数据前仍需结合 `research/module-repair-streaming-deep-dive.md`。
- Dynamic snitch tracks reads, not writes；将 batchlog endpoint strategy 改为 dynamic 也可能不适合 write-only workload。源码注释见 `src/java/org/apache/cassandra/config/Config.java:1291`。
- `SimpleSnitch` 不改变 replica 顺序；如果预期 read coordinator 自动靠延迟排序，必须确认 `dynamic_snitch` 实际启用并包装了 snitch。构造见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1665`。

## 性能瓶颈

- 禁用高 CL 不是性能优化本身，它只是策略约束；如果应用因为 guardrail 降低 CL，可能改变一致性语义。
- Transient replication 减少 full data 存储，但 read path 仍可能联系 transient replicas 取 transient data，并需要 full replica 参与 digest/数据确认。
- `DigestResolver` 在有 transient data response 时会额外 reconcile transient responses；这降低错误语义风险，但会增加 resolver CPU。见 `src/java/org/apache/cassandra/service/reads/DigestResolver.java:77`。
- Dynamic snitch 排序依赖 latency score snapshot。score 更新/重置滞后可能让短期延迟尖刺影响后续 read contact 顺序。
- `dynamic_snitch_badness_threshold=0` 会强制 score order，更激进；默认 1.0 会保留 subsnitch order，除非分数差距超过阈值。见 `src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:175`。
- Range reads 也先 snitch 排序再选 contacts；如果动态 snitch 把慢节点排前，range query 没有普通 speculation，会直接放大尾延迟。range read contact 选择见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:737`。
- Pending/natural full/transient 冲突处理偏保守，可能增加写入目标，但减少 transition 期间读到不完整 full 数据的风险。见 `src/java/org/apache/cassandra/locator/ReplicaLayout.java:225`。

## 常见故障

- 配置了 `read_consistency_levels_disallowed` 后 SELECT 失败：入口在 `SelectStatement.execute()`，先过 `validateForRead()` 再触发 guardrail，见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:282`。
- LWT 因 write CL guardrail 失败：serial CL 也被放入 write guardrail set，见 `src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:497`。
- RF `3/1` 被拒绝：可能是 `transient_replication_enabled=false`、`num_tokens>1`、transient >= total，或混合版本节点低于 4.0。校验见 `src/java/org/apache/cassandra/locator/ReplicationFactor.java:62`。
- Alter keyspace transient RF 被拒绝：已有 MV/secondary index、存在 range movement 或 full/transient 转换顺序不安全。见 `src/java/org/apache/cassandra/cql3/statements/schema/AlterKeyspaceStatement.java:126`、`src/java/org/apache/cassandra/cql3/statements/schema/AlterKeyspaceStatement.java:145`。
- Read unavailable 但 live endpoint 数看起来够：检查 live replicas 中是否有 full replica；read path 对 full 数有额外要求。见 `src/java/org/apache/cassandra/locator/ReplicaPlans.java:124`。
- Digest response from transient replica：这是错误请求路径，`ResponseResolver` 会抛异常。见 `src/java/org/apache/cassandra/service/reads/ResponseResolver.java:60`。
- Full read request 打到 transient replica：接收端会记录 dropped message 并抛 InvalidRequest。见 `src/java/org/apache/cassandra/db/ReadCommandVerbHandler.java:164`。
- Snitch 排序与预期不同：如果 dynamic snitch 开启，排序可能由 latency score 和 severity 改写；如果 `SimpleSnitch` 或 dynamic snitch 未启用，则顺序更接近 strategy/ring 输出。见 `src/java/org/apache/cassandra/locator/SimpleSnitch.java:40`、`src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java:193`。

## 测试用例

- Consistency guardrails：`test/unit/org/apache/cassandra/db/guardrails/GuardrailReadConsistencyLevelsTest.java`、`test/unit/org/apache/cassandra/db/guardrails/GuardrailWriteConsistencyLevelsTest.java`、`test/unit/org/apache/cassandra/db/guardrails/GuardrailConsistencyLevelsTester.java`。
- RF/transient parsing and strategy selection：`test/unit/org/apache/cassandra/locator/ReplicationFactorTest.java`、`test/unit/org/apache/cassandra/locator/SimpleStrategyTest.java`、`test/unit/org/apache/cassandra/locator/NetworkTopologyStrategyTest.java`。
- Replica layout/plan：`test/unit/org/apache/cassandra/locator/ReplicaPlansTest.java`、`test/unit/org/apache/cassandra/locator/ReplicaLayoutTest.java`、`test/unit/org/apache/cassandra/service/reads/range/ReplicaPlanIteratorTest.java`、`test/unit/org/apache/cassandra/service/reads/range/ReplicaPlanMergerTest.java`。
- Dynamic snitch/proximity：`test/unit/org/apache/cassandra/locator/DynamicEndpointSnitchTest.java`、`test/unit/org/apache/cassandra/batchlog/BatchlogEndpointFilterTest.java`、`test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidTimeouts.java`。
- Transient/repair interaction boundaries：`test/unit/org/apache/cassandra/repair/RepairJobTest.java`、`test/distributed/org/apache/cassandra/distributed/test/RepairDigestTrackingTest.java`、`test/distributed/org/apache/cassandra/distributed/test/ring/PendingWritesTest.java`。
- Existing mixed consistency coverage remains in `test/distributed/org/apache/cassandra/distributed/upgrade/MixedModeConsistencyTest.java` and first-round range read tests.

## 待继续

- `research/module-consistency-replication-third-round.md` 已补 multi-DC CL policy/guardrail 操作矩阵、transient replication + repair/streaming/pending range failure-injection matrix、dynamic snitch topology-change runbook，以及 system keyspace RF 与用户 keyspace RF 的操作差异。
- `research/module-consistency-guardrail-profiles.md` 与 `research/tools/check-consistency-guardrail-profile-drift.py` 已补 workload-specific CL guardrail profile 模板和 source-to-profile drift 检查。
- `research/module-system-keyspace-rf-drift-checker.md` 与 `research/tools/check-system-keyspace-rf-drift.py` 已补 system keyspace RF source-to-doc drift 检查。
- `research/module-dynamic-snitch-topology-regression.md`、`research/module-dynamic-snitch-drift-checker.md` 与 `research/tools/check-dynamic-snitch-topology-drift.py` 已补 dynamic snitch topology-change regression matrix、decommission severity、batchlog dynamic strategy、JMX/updateSnitch 操作面和 source-to-doc drift 检查。
- 仍需实现或取得 transient repair/streaming/pending range 专项 distributed fault tests。
