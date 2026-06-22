# Flow: LWT / Paxos

## 目标

解释一条带 `IF` 条件的 CQL mutation 如何从普通 statement 分流到 CAS，并通过 Paxos 在线性化条件判断后提交或返回当前值。

## 文字版调用图

```text
Client / Driver
  -> Native protocol QUERY / EXECUTE
  -> QueryProcessor executes ModificationStatement
     -> ModificationStatement.execute()
        -> hasConditions()
        -> executeWithCondition()
           -> makeCasRequest()
           -> StorageProxy.cas(keyspace, table, key, request, serialCL, commitCL, ...)
              -> partition denylist check
              -> Paxos.useV2()
                 -> true: Paxos.cas(...)
                 -> false: legacyCas(...)

Paxos v2:
  Paxos.cas()
    -> request.readCommand()
    -> validate serial CL and commit CL
    -> PaxosState.lock(partitionKey, metadata, deadline, ...)
    -> begin(...)
       -> prepare/read current values from participants
    -> request.appliesTo(current)
       -> false and read linearized: return current rows
       -> false and not linearized: propose empty update
       -> true: request.makeUpdates(); TriggerExecutor; proposal
    -> propose(proposal, participants, conditionMet)
    -> on success: commit non-empty proposal / return applied

Legacy Paxos:
  legacyCas()
    -> updateProposer(ballot)
       -> read existing values at QUORUM or LOCAL_QUORUM
       -> request.appliesTo(current)
       -> if false: empty update + current rows
       -> if true: request.makeUpdates(); TriggerExecutor
    -> doPaxos()
       -> ReplicaPlans.forPaxos()
       -> beginAndRepairPaxos()
          -> preparePaxos()
          -> finish incomplete in-progress proposal if needed
          -> repair replicas missing most recent commit
       -> proposePaxos()
       -> commitPaxos()
       -> return applied/null or current rows
```

## 关键源码锚点

| 阶段 | 文件/方法 |
|---|---|
| 条件语句分流 | `ModificationStatement.execute()`：`src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:491-502` |
| CAS 请求入口 | `ModificationStatement.executeWithCondition()`：`src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:538-552` |
| CAS coordinator 分流 | `StorageProxy.cas()`：`src/java/org/apache/cassandra/service/StorageProxy.java:308-328` |
| Paxos v2 设计注释 | `Paxos` class comment：`src/java/org/apache/cassandra/service/paxos/Paxos.java:137-216` |
| Paxos v2 CAS 入口 | `Paxos.cas()`：`src/java/org/apache/cassandra/service/paxos/Paxos.java:626-636` |
| Paxos v2 begin/proposal | `Paxos.cas(...)` internal：`src/java/org/apache/cassandra/service/paxos/Paxos.java:650-760` |
| legacy Paxos 算法注释 | `StorageProxy.cas()` comment：`src/java/org/apache/cassandra/service/StorageProxy.java:269-307` |
| legacy CAS precondition read | `StorageProxy.legacyCas()`：`src/java/org/apache/cassandra/service/StorageProxy.java:335-395` |
| legacy Paxos 主循环 | `StorageProxy.doPaxos()`：`src/java/org/apache/cassandra/service/StorageProxy.java:483-568` |
| prepare/repair | `beginAndRepairPaxos()`：`src/java/org/apache/cassandra/service/StorageProxy.java:577-682` |
| prepare message | `preparePaxos()`：`src/java/org/apache/cassandra/service/StorageProxy.java:695-731` |
| propose message | `proposePaxos()`：`src/java/org/apache/cassandra/service/StorageProxy.java:739-774` |
| commit message | `commitPaxos()`：`src/java/org/apache/cassandra/service/StorageProxy.java:776-803` |
| 本地 commit | `commitPaxosLocal()`：`src/java/org/apache/cassandra/service/StorageProxy.java:830-857` |
| SERIAL read | `readWithPaxos()`：`src/java/org/apache/cassandra/service/StorageProxy.java:1898-1956` |

## 一致性语义

- `consistencyForPaxos` 只能是 `SERIAL` 或 `LOCAL_SERIAL`；`doPaxos()` 调用 `validateForCas()`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:493-500`。
- legacy CAS 在读取当前值时，`LOCAL_SERIAL` 使用 `LOCAL_QUORUM`，其它 serial CL 使用 `QUORUM`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:346-354`。
- Paxos commit phase 使用客户端传入的 normal write CL，不能是 `SERIAL/LOCAL_SERIAL`，语义写在 `StorageProxy.cas()` 参数注释中，见 `src/java/org/apache/cassandra/service/StorageProxy.java:298-304`。
- SERIAL read 会先执行 Paxos read/repair，再用 quorum/local quorum fetch rows，见 `src/java/org/apache/cassandra/service/StorageProxy.java:1922-1956`。

## 失败与重试

- `doPaxos()` 在 `cas_contention_timeout` deadline 前循环，遇到更高 ballot 会随机 sleep 后重试，见 `src/java/org/apache/cassandra/service/StorageProxy.java:502-548`。
- prepare 阶段如果发现未完成 proposal，会尝试先 finish incomplete paxos round，见 `src/java/org/apache/cassandra/service/StorageProxy.java:617-654`。
- prepare 阶段如果有 replicas 缺少 most recent commit，会主动发送 commit 修复再重试，见 `src/java/org/apache/cassandra/service/StorageProxy.java:657-670`。
- propose 部分成功但未达明确结论时可能抛 `CasWriteUnknownResultException`，见 `src/java/org/apache/cassandra/service/StorageProxy.java:767-773`。
- CAS write metrics 在 unknown result、timeout、failure、unavailable 上分别更新，见 `src/java/org/apache/cassandra/service/StorageProxy.java:398-440`。

## 配置与观测

- `cas_contention_timeout` 定义在 `src/java/org/apache/cassandra/config/Config.java:156-157`，模板值见 `conf/cassandra.yaml:1335-1339`。
- `paxos_variant` 定义与 v1/v2 语义见 `src/java/org/apache/cassandra/config/Config.java:969-1005`、`src/java/org/apache/cassandra/config/Config.java:1048-1051`。
- v2 升级模板提示先全量 repair，再设置 `paxos_variant: v2` 滚动重启，见 `conf/cassandra.yaml:1594-1602`。
- CAS metrics 定义见 `src/java/org/apache/cassandra/metrics/CASClientRequestMetrics.java:27-39`、`src/java/org/apache/cassandra/metrics/CASClientWriteRequestMetrics.java:30-45`。

## 排查路径

1. 判断是 condition failed 还是 CAS timeout：condition failed 会返回当前 rows，timeout/failure 会走 CAS metrics。
2. 看 `ClientRequest.CASWrite.ContentionHistogram` 和 `UnknownResult`，区分热点竞争与网络/replica 不稳定。
3. 混用 `SERIAL` 与 `LOCAL_SERIAL` 时关注跨 DC 线性化语义，`paxos_on_linearizability_violations` 默认是 ignore，见 `src/java/org/apache/cassandra/config/Config.java:1066-1089`。
4. v2 Paxos 问题要同时看 paxos repair/state purging 配置，`repaired` 模式依赖常规 paxos repair，见 `src/java/org/apache/cassandra/config/Config.java:1017-1040`。

## 测试用例

- `test/distributed/org/apache/cassandra/distributed/test/CASTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/CASContentionTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/CASMultiDCTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/LegacyCASTest.java`
- `test/unit/org/apache/cassandra/service/paxos/PaxosProposeTest.java`
- `test/unit/org/apache/cassandra/service/paxos/PaxosStateTest.java`
- `test/unit/org/apache/cassandra/service/paxos/uncommitted/PaxosUncommittedTrackerTest.java`
