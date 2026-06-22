# Module: Coordination Deep Dive

## 范围

本文是 LWT/Paxos、Counter、Hints、Batchlog 的第三轮补充，专门补 `PaxosCommitAndPrepare`/`PaxosPrepareRefresh`、counter delete/compaction 语义、`HintsBuffer` rollover/backpressure/legacy fixture、mixed-version logged batch。第一轮主线见 `module-coordination-lwt-counter-hints.md`，第二轮内部结构见 `module-coordination-lwt-counter-hints-internals.md`。

## 设计目标

- Paxos v2 要减少轮次并修复 stale participant：`PaxosCommitAndPrepare.commitAndPrepare()` 把前一轮 commit 和下一轮 prepare 合成一个 `PAXOS2_COMMIT_AND_PREPARE_REQ`，见 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:45-55`。
- Paxos prepare quorum 必须确认 latest commit 对未来 quorum 可见；`PaxosPrepareRefresh` 的类注释说明 promised 节点可能缺 latest commit，因此 coordinator 要先提交 missing commit 再确认 promise，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:51-57`。
- Counter delete 不重置 counter shard，而是用 tombstone 遮蔽后续 counter increment；单测明确删除 counter 后再 increment 仍被 tombstone shadow，见 `test/unit/org/apache/cassandra/db/CounterMutationTest.java:181-217`。
- Hints 写入要同时控制内存 slab、writer 文件大小和跨版本读取；内存写在 `HintsBuffer`，文件 rollover 在 `HintsWriteExecutor`，legacy fixture 在 `HintsUpgradeTest`，见 `src/java/org/apache/cassandra/hints/HintsBuffer.java:43-58`、`src/java/org/apache/cassandra/hints/HintsWriteExecutor.java:217-258`、`test/unit/org/apache/cassandra/hints/HintsUpgradeTest.java:108-160`。
- Logged batch 在 mixed-version upgrade 中必须保留 batchlog store 失败语义和 RF placement；`MixedModeBatchTestBase` 覆盖升级过程中每个 coordinator 的 logged/unlogged batch，并对 logged batch 注入 batchlog write timeout，见 `test/distributed/org/apache/cassandra/distributed/upgrade/MixedModeBatchTestBase.java:37-41` 和 `test/distributed/org/apache/cassandra/distributed/upgrade/MixedModeBatchTestBase.java:64-78`。

## 解决的问题

- `PaxosCommitAndPrepare` 解决的是“刚完成 commit 后马上进入下一轮 prepare”的额外往返；request 同时携带 `Agreed commit` 与新 ballot，服务端先 `state.commit(commit)` 再执行 prepare handler，见 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:58-82` 和 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:131-142`。
- `PaxosPrepareRefresh` 解决的是 prepare 已经拿到足够 promise，但其中部分 promised 节点没有 latest commit；`PaxosPrepare` 将这类节点放入 `needLatest`，有 latest read response 时触发 refresh，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:520-635`。
- Counter delete 解决的是 counter table 中删除后不能被 blind increment 复活；`CounterMutation` 读当前可见 cell 后生成 global shard，若读路径被 tombstone 遮蔽，则不会恢复被删除的 cell，见 `src/java/org/apache/cassandra/db/CounterMutation.java:207-239` 和 `test/unit/org/apache/cassandra/db/CounterMutationTest.java:190-217`。
- HintsBuffer rollover 解决内存 slab 填满与 writer 文件过大两个问题：slab 超容量后关闭当前 buffer 并切换，writer 达到 `max_hints_file_size` 后关闭当前 writer，见 `src/java/org/apache/cassandra/hints/HintsBuffer.java:182-197`、`src/java/org/apache/cassandra/hints/HintsBufferPool.java:68-83`、`src/java/org/apache/cassandra/hints/HintsWriteExecutor.java:222-249`。
- Mixed-mode logged batch 解决升级时 batchlog verb/serializer 兼容和 placement 正确性；`Batch` 在同版本下保留 encoded mutations，不同版本下 decode 成 local mutations，见 `src/java/org/apache/cassandra/batchlog/Batch.java:137-149`。

## 设计取舍

- Commit-and-prepare 降低网络往返，但把两步状态变更放进同一 verb；服务端必须先 range-gate commit，再在同一个 `PaxosState` 上执行 commit 和 prepare，见 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:131-142`。
- Prepare refresh 比直接重启 prepare 更便宜，但只在已经有 latest read response 时有用；没有 latest read response 时 `PaxosPrepare` 选择 `FOUND_INCOMPLETE_COMMITTED` 重新开始，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:620-635`。
- Counter delete 依赖普通 tombstone/read filtering 语义，而不是特殊 counter reset；这保留了 counter 的 CRDT merge 特性，但 tombstone 存在期间会让后续 increment 不可见，见 `test/unit/org/apache/cassandra/db/CounterMutationTest.java:194-217`。
- HintsBuffer 限制单条 hint 不能超过 slab 一半，避免一个巨大 hint 独占整个 direct buffer；代价是过大的 mutation hint 会直接被拒绝，见 `src/java/org/apache/cassandra/hints/HintsBuffer.java:148-157` 和 `test/unit/org/apache/cassandra/hints/HintsBufferTest.java:69-92`。
- Batchlog serializer 对当前版本走 encoded fast path，对非当前版本解码；这保留同版本性能，同时让 mixed-version store/replay 可以通过 mutation serializer 兼容，见 `src/java/org/apache/cassandra/batchlog/Batch.java:90-149`。

## 核心类

| 类 | 角色 | 证据 |
|---|---|---|
| `PaxosCommitAndPrepare` | 合并 commit 和 prepare 的 Paxos v2 verb | `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:45-55`、`src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:119-142` |
| `PaxosPrepareRefresh` | 对 stale promised participants 提交 missing commit 并确认 promise | `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:75-102`、`src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:175-197` |
| `PaxosPrepare` | 维护 `withLatest`/`needLatest`、refresh 和 prepare outcome | `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:279-300`、`src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:847-879` |
| `CounterMutation` | counter leader read-before-write、lock、cache、global shard 写入 | `src/java/org/apache/cassandra/db/CounterMutation.java:116-151`、`src/java/org/apache/cassandra/db/CounterMutation.java:207-239` |
| `CounterContext` | counter shard compare/merge/total/legacy local shard cleanup | `src/java/org/apache/cassandra/db/context/CounterContext.java:447-531`、`src/java/org/apache/cassandra/db/context/CounterContext.java:586-679` |
| `HintsBuffer` / `HintsBufferPool` | direct slab、offset queues、allocation、current/reserve buffer 切换与 backpressure | `src/java/org/apache/cassandra/hints/HintsBuffer.java:60-113`、`src/java/org/apache/cassandra/hints/HintsBufferPool.java:30-46` |
| `HintsWriteExecutor` | flush buffer、demultiplex hostId、按 max file size 关闭 writer | `src/java/org/apache/cassandra/hints/HintsWriteExecutor.java:80-153`、`src/java/org/apache/cassandra/hints/HintsWriteExecutor.java:217-258` |
| `Batch` / `BatchlogManager` | logged batch wire/system.batches 形态与 replay | `src/java/org/apache/cassandra/batchlog/Batch.java:57-74`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:134-165` |
| `MixedModeBatchTestBase` | mixed-version logged/unlogged batch upgrade matrix | `test/distributed/org/apache/cassandra/distributed/upgrade/MixedModeBatchTestBase.java:56-78`、`test/distributed/org/apache/cassandra/distributed/upgrade/MixedModeBatchTestBase.java:81-155` |

## 核心接口

- Paxos v2 新 verb 在 `Verb` 中注册为 `PAXOS2_PREPARE_REFRESH_REQ/RSP` 和 `PAXOS2_COMMIT_AND_PREPARE_REQ/RSP`，它们都使用 write timeout，见 `src/java/org/apache/cassandra/net/Verb.java:186-195`。
- `PaxosPrepareRefresh.Callbacks` 把 refresh failure/success 回接到 `PaxosPrepare`，failure 走普通 `onFailure`，success 可能带 superseded ballot，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:66-70` 和 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:861-879`。
- `HintsBufferPool.FlushCallback` 是 buffer 满后的异步 flush 接口；`HintsWriteExecutor.flushBuffer()` 负责等待 append barrier、flush、recycle 并放回 reserve queue，见 `src/java/org/apache/cassandra/hints/HintsBufferPool.java:36-45` 和 `src/java/org/apache/cassandra/hints/HintsWriteExecutor.java:80-153`。
- `HintsReader.Page` 同时提供 decoded `hintsIterator()` 和 encoded `buffersIterator()`；读测验证两条路径都能还原 hint，见 `test/unit/org/apache/cassandra/hints/HintsReaderTest.java:106-180`。
- Batchlog 的远端 store/remove 仍通过 `BATCH_STORE_REQ`/`BATCH_REMOVE_REQ`，mixed-mode test 用 message filter drop `BATCH_STORE_REQ` 和 response 来制造 batchlog write timeout，见 `src/java/org/apache/cassandra/net/Verb.java:121-124` 和 `test/distributed/org/apache/cassandra/distributed/upgrade/MixedModeBatchTestBase.java:64-70`。

## 核心数据结构

- `CommitAndPrepare.Request`：`Agreed commit` + new prepare ballot + electorate/read/isWrite；serializer 先写 agreed commit，再写 prepare request 主体，见 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:58-115`。
- `PrepareRefresh.Request/Response`：request 保存 promised ballot 和 missing committed value；response 只返回 nullable superseding ballot，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:142-161` 和 `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:200-241`。
- `PaxosPrepare.withLatest/needLatest`：promise 节点按是否见过 latest commit 分组；`needLatest` 在 refresh 后清空，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:287-292` 和 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:852-859`。
- `CounterContext` header：负数 element count 表示需要清 local refs；`clearAllLocal()` 只保留 global shard index 并复制 body，见 `src/java/org/apache/cassandra/db/context/CounterContext.java:586-679`。
- `HintsBuffer` slab entry：每条 hint 是 length、length checksum、hint bytes、body checksum；同一个 offset 可以放入多个 hostId queue，见 `src/java/org/apache/cassandra/hints/HintsBuffer.java:43-58` 和 `src/java/org/apache/cassandra/hints/HintsBuffer.java:225-256`。
- `Batch`：local batch 保存 decoded mutations；remote/current-version batch 保存 encoded mutation buffers；系统表持久化时统一存 `version` 和 `mutations` list，见 `src/java/org/apache/cassandra/batchlog/Batch.java:44-100` 和 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:141-165`。

## 生命周期

```text
Paxos commit-and-prepare
  -> coordinator has Agreed commit
  -> build newer ballot
  -> send PAXOS2_COMMIT_AND_PREPARE_REQ
  -> replica range-gates commit
  -> PaxosState.commit(commit)
  -> PaxosPrepare.RequestHandler.execute()
```

入口和服务端执行见 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:45-55` 和 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:131-142`。

```text
Paxos prepare refresh
  -> prepare responses split withLatest/needLatest
  -> quorum possible but not quorum withLatest
  -> send missing latest commit to needLatest
  -> replica commit() then checks current promised state
  -> response null means promise confirmed, ballot means superseded
```

分组和触发条件见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:520-635`；refresh 执行见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:81-102` 和 `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:175-197`。

```text
Counter delete and increment
  -> delete creates tombstone through normal update path
  -> later counter mutation collects counter marks
  -> cache/CFS read only returns visible counter cells
  -> tombstoned cells remain absent
  -> increment does not resurrect deleted counter
```

Counter read-before-write 见 `src/java/org/apache/cassandra/db/CounterMutation.java:207-239`；delete test 见 `test/unit/org/apache/cassandra/db/CounterMutationTest.java:160-217`。

```text
Hints rollover
  -> HintsBufferPool.write()
  -> current HintsBuffer allocation fails
  -> switch current buffer
  -> flush old buffer through HintsWriteExecutor
  -> demultiplex by hostId
  -> writer reaches max_hints_file_size
  -> close writer, next hint opens next file
```

Buffer switch 见 `src/java/org/apache/cassandra/hints/HintsBufferPool.java:68-83` 和 `src/java/org/apache/cassandra/hints/HintsBufferPool.java:107-133`；writer rollover 见 `src/java/org/apache/cassandra/hints/HintsWriteExecutor.java:222-249`。

## 调用链

- Paxos commit-and-prepare：`Paxos.commitAndPrepare()` import 到 `Paxos` 主流程，构造 `Message.out(PAXOS2_COMMIT_AND_PREPARE_REQ, request)` 后复用 `PaxosPrepare.start()`，见 `src/java/org/apache/cassandra/service/paxos/Paxos.java:128` 和 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:45-55`。
- Paxos refresh：`PaxosPrepare.permitted()` 更新 latest/needLatest，达到 consensus quorum 但缺 latest quorum 时调用 `refreshStaleParticipants()`，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:597-635` 和 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:847-859`。
- Counter write：`CounterMutation.applyCounterMutation()` -> `grabCounterLocks()` -> `processModifications()` -> cache/CFS read -> `updateWithCurrentValue()` -> result mutation apply，见 `src/java/org/apache/cassandra/db/CounterMutation.java:129-151`、`src/java/org/apache/cassandra/db/CounterMutation.java:158-176`、`src/java/org/apache/cassandra/db/CounterMutation.java:207-239`。
- Hints write：`HintsBufferPool.write()` -> `allocate()` -> `HintsBuffer.Allocation.write()` -> flush callback -> `HintsWriteExecutor.flush()` -> `HintsWriter.Session.append()`，见 `src/java/org/apache/cassandra/hints/HintsBufferPool.java:59-83`、`src/java/org/apache/cassandra/hints/HintsBuffer.java:225-256`、`src/java/org/apache/cassandra/hints/HintsWriter.java:232-275`。
- Batchlog replay：`replayFailedBatches()` pages `system.batches` -> `processBatchlogEntries()` -> `ReplayingBatch.replay()` -> `finish()` writes hints for failed endpoints -> fsync hints -> remove batchlog rows，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:200-227`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:260-317`、`src/java/org/apache/cassandra/batchlog/BatchlogManager.java:337-448`。

## 配置项

- `max_hints_file_size` 默认 `128MiB`，控制单个 hints file rollover；配置定义见 `src/java/org/apache/cassandra/config/Config.java:446-447`，默认 YAML 见 `conf/cassandra.yaml:104-106`。
- `cassandra.MAX_HINT_BUFFERS` 控制 `HintsBufferPool.MAX_ALLOCATED_BUFFERS`，达到上限后 `switchCurrentBuffer()` 会阻塞等待 reserve buffer，见 `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:351` 和 `src/java/org/apache/cassandra/hints/HintsBufferPool.java:107-124`。
- Hints writer 还受 trickle fsync interval 影响，session close 时可能 fsync 和 skip page cache，见 `src/java/org/apache/cassandra/hints/HintsWriter.java:265-302`。
- Batchlog replay 受 `batchlog_replay_throttle` 和 `BATCHLOG_REPLAY_TIMEOUT` 影响；replay 先按 endpoint 数调整 rate，再只扫描超过 timeout 的 batch，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:200-224` 和 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:229-247`。
- Paxos refresh/commit-and-prepare 没有单独配置项；它们跟随 Paxos v2 variant 和 verb write timeout，verb 注册见 `src/java/org/apache/cassandra/net/Verb.java:186-195`。

## Metrics

- Paxos refresh 主要通过 prepare outcome、failure reasons 和 tracing 暴露，不单独定义 metric；`PaxosPrepare` refresh failure 走普通 failure 计数路径，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:861-879`。
- Counter delete/compaction 没有专用 metric；可通过 counter cache 命中、counter write timeout 和 compaction warning 侧面观察。`CounterMutation` 写 counter cache，`CounterContext.compare()` 在 compaction 线程发现同 clock 不同 count 会 warning，见 `src/java/org/apache/cassandra/db/CounterMutation.java:231-239` 和 `src/java/org/apache/cassandra/db/context/CounterContext.java:461-523`。
- Hints dispatch 成功/失败/超时 metrics 在 `HintsDispatcher` 发送 page 后更新；跨版本是否 decoded/encoded 不改变这组指标，见 `src/java/org/apache/cassandra/hints/HintsDispatcher.java:126-171`。
- Batchlog replay 暴露 `totalBatchesReplayed`，并通过 `countAllBatches()` 查询 `system.batches`；store/replay 测试检查 replay 前后数量，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:167-181` 和 `test/unit/org/apache/cassandra/batchlog/BatchlogManagerTest.java:130-202`。

## 日志

- `PaxosPrepareRefresh` trace 会记录 refresh/confirm 目标和 superseded/promise confirmed 结果，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:81-102` 和 `src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java:182-195`。
- `CounterContext.compare()` 在 compaction 线程发现异常 global/remote shard 会记录 warning 并选择较大 count 自愈，见 `src/java/org/apache/cassandra/db/context/CounterContext.java:461-523`。
- Hints flush failure 会记录 error 并传播 FS error；writer rollover 本身不是错误路径，见 `src/java/org/apache/cassandra/hints/HintsWriteExecutor.java:166-179` 和 `src/java/org/apache/cassandra/hints/HintsWriteExecutor.java:222-249`。
- Batchlog replay 对 IOException 会 warn 并删除该 batch，对 replay timeout/failure 会 trace 后写 hints，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:288-316` 和 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:372-387`。

## 运维关注点

- Paxos refresh failure 不代表 commit 一定失败；它表示本次 prepare 不能证明 latest commit 已进入足够参与者，coordinator 会走 prepare failure/superseded/retry 路径。
- Counter delete 后短期内不要期待同一 counter cell 的新 increment 立即可见；tombstone shadow 是测试确认的语义，见 `test/unit/org/apache/cassandra/db/CounterMutationTest.java:181-217`。
- Hints 内存 backpressure 是有意设计。`HintsBufferPoolTest` 用 Byteman 确认达到最大 allocated buffers 后会阻塞在 reserve queue `take()`，见 `test/unit/org/apache/cassandra/hints/HintsBufferPoolTest.java:45-73`。
- Hints legacy fixture 已存在：3.0.29 和 4.1.3 目录各有 `.hints`、`.crc32`、`hash.txt`，测试通过 `HintsReader` 读并校验 hash/cell count，见 `test/unit/org/apache/cassandra/hints/HintsUpgradeTest.java:101-160` 和 `test/data/legacy-hints/3.0.29/hash.txt`。
- Mixed-mode logged batch 已有升级测试，但 operator runbook 仍缺：如何结合 `nodetool replaybatchlog`、batchlog throttle、hints backlog 判断是否安全手动 replay，还需要单独整理。

## 性能瓶颈

- Commit-and-prepare 节省一次 prepare RTT，但 request 同时序列化 commit 和 prepare request；大 mutation 的 agreed commit 会放大该 verb payload，serializer 成本见 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:97-115`。
- Prepare refresh 的收益取决于是否已有 latest read response；没有时会重启 prepare，可能增加竞争时延，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:620-635`。
- Counter write 热点仍受 striped cell lock 和 read-before-write 限制；lock timeout 抛 `WriteTimeoutException(WriteType.COUNTER)`，见 `src/java/org/apache/cassandra/db/CounterMutation.java:158-176`。
- HintsBuffer 使用 direct buffer 和 offset queue，单条 hint 上限是 slab 一半；并发写满后会切 buffer 并由单线程 executor 顺序写盘，见 `src/java/org/apache/cassandra/hints/HintsBuffer.java:75-113`、`src/java/org/apache/cassandra/hints/HintsBuffer.java:148-197`、`src/java/org/apache/cassandra/hints/HintsWriteExecutor.java:40-61`。
- Batchlog replay 按 page 处理并在每页后等待 unfinished batches，page size 受 `system.batches` 平均 partition size 影响，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:250-317`。

## 常见故障

- Refresh 返回 superseded ballot：表示 promise 已被更新 ballot 取代，`PaxosPrepare.onRefreshSuccess()` 会设置 `supersededBy` 并 signal `SUPERSEDED` 或 `READ_PERMITTED`，见 `src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java:867-879`。
- Commit-and-prepare range gate 失败：`PaxosCommitAndPrepare.RequestHandler.execute()` 返回 null，verb handler respond failure `UNKNOWN`，见 `src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java:119-142`。
- Counter invalid shard：compaction 中同 id/clock 不同 count 会 self-heal by highest count 并 warning；这通常意味着历史 SSTable 丢失或 best-effort disk failure 风险，见 `src/java/org/apache/cassandra/db/context/CounterContext.java:461-523`。
- Hints allocation too large：超过 slab 一半会抛 `IllegalArgumentException`，测试验证错误信息和边界，见 `src/java/org/apache/cassandra/hints/HintsBuffer.java:148-157` 和 `test/unit/org/apache/cassandra/hints/HintsBufferTest.java:69-92`。
- Batchlog replay delivery timeout：`ReplayingBatch.finish()` 从失败位置开始为 undelivered endpoints 写 hints，并在 hints fsync 后删除 batchlog，见 `src/java/org/apache/cassandra/batchlog/BatchlogManager.java:372-448`。

## 测试用例

| 主题 | 已有覆盖 | 剩余缺口 |
|---|---|---|
| Paxos commit-and-prepare / refresh | Paxos v2 source path、mixed-mode Paxos upgrade docs/test family、simulator Paxos topology verifier 间接覆盖 | 针对 `PaxosCommitAndPrepare` 和 `PaxosPrepareRefresh` 的 fault-injection 单测/模拟矩阵仍可补 |
| Counter delete / compaction | `CounterMutationTest.testDeletes()`、`CounterContextTest.testClearLocal()`、CQL counter validation、distributed empty context | counter tombstone + repair/compaction 端到端 distributed 场景仍可补 |
| HintsBuffer rollover | `HintsBufferTest.testOverlyLargeAllocation()`、并发写满 slab、`HintsBufferPoolTest.testBackpressure()` | max hints file size rollover 的直接断言和压缩/加密 rollover 组合仍可补 |
| Hints upgrade fixtures | `HintsUpgradeTest` 读取 3.0.29/4.1.3 legacy hints fixture；`HintsReaderTest` 覆盖 decoded/encoded page iterator | mixed-version dispatch 到不同 messaging version 节点的 dtest 仍可补 |
| Mixed-version logged batch | `MixedModeLoggedBatchTest` 从 `OLDEST` 升级并复用 `MixedModeBatchTestBase`，覆盖 batchlog store timeout 和 RF placement | large mutation、operator replay runbook、system.batches compaction 运行手册仍可补 |

Concrete tests:

- `CounterMutationTest.testDeletes()`：删除 counter cell 后再次 increment 仍被 tombstone shadow，row delete 后两个 counter 都保持不可见，见 `test/unit/org/apache/cassandra/db/CounterMutationTest.java:160-217`。
- `CounterContextTest.testClearLocal()`：标记 local shard 清理、只保留 global shard header/body，见 `test/unit/org/apache/cassandra/db/context/CounterContextTest.java:420-485`。
- `CountersTest.testCounterUpdatesWithUnset()` 和 filtering tests 验证 CQL 层 unset/null/filtering 语义，见 `test/unit/org/apache/cassandra/cql3/validation/entities/CountersTest.java:72-167`。
- `test/distributed/.../CountersTest.testEmptyContext()` 覆盖多节点 counter empty context 与 repaired metadata 组合，见 `test/distributed/org/apache/cassandra/distributed/test/CountersTest.java:85-125`。
- `HintsBufferTest.testWrite()` 验证并发写满 slab、failed allocation closes oporder、hostId offset queue 和 CRC，见 `test/unit/org/apache/cassandra/hints/HintsBufferTest.java:94-160`。
- `HintsBufferPoolTest.testBackpressure()` 验证 reserve buffer 不及时归还时 write 线程会阻塞，见 `test/unit/org/apache/cassandra/hints/HintsBufferPoolTest.java:45-73`。
- `HintsUpgradeTest.test30()` / `test41()` 读取 3.0.29 和 4.1.3 legacy hints fixture，见 `test/unit/org/apache/cassandra/hints/HintsUpgradeTest.java:108-160`。
- `BatchlogTest.testSerialization()` 验证 local batch 序列化后以 encoded mutations 形态反序列化，见 `test/unit/org/apache/cassandra/batchlog/BatchlogTest.java:62-106`。
- `BatchlogManagerTest.testReplay()` 验证到期 batch 才 replay，未到期保留在 `system.batches`，见 `test/unit/org/apache/cassandra/batchlog/BatchlogManagerTest.java:130-202`。
- `MixedModeLoggedBatchTest.testSimpleStrategy()` 从 `OLDEST` 到当前版本跑 logged batch upgrade，核心矩阵在 `MixedModeBatchTestBase`，见 `test/distributed/org/apache/cassandra/distributed/upgrade/MixedModeLoggedBatchTest.java:23-29` 和 `test/distributed/org/apache/cassandra/distributed/upgrade/MixedModeBatchTestBase.java:56-155`。
