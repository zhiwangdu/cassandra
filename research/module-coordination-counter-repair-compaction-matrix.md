# Coordination Counter Repair And Compaction Matrix

## 范围

本文是 Paxos/Counter/Hints/Batchlog 第六轮补充中的 counter tombstone + repair/compaction 专项矩阵，聚焦：

- Counter delete 如何通过普通 tombstone/read filtering 遮蔽后续 counter increment，而不是重置 shard。
- Counter context 的 global/local/remote shard merge、legacy shard 清理和 compaction self-heal warning。
- Repaired-data digest 如何处理 empty context、legacy shard 和 counter context header。
- Repair validation compaction 如何 purge gc-able tombstones 以避免 hash 依赖各节点本地 compaction schedule。
- Compaction/tombstone garbage collection、read repair deletion propagation、counter cache invalidation 与当前 distributed 测试缺口。

前置主线见 `research/module-coordination-lwt-counter-hints.md`、`research/module-coordination-lwt-counter-hints-internals.md`、`research/module-coordination-lwt-counter-hints-deep-dive.md`、`research/flow-counter-write.md` 和 `research/module-coordination-fault-coverage-runbook.md`。本矩阵由 `research/tools/check-coordination-counter-repair-compaction-drift.py` 保护，checker 说明见 `research/module-coordination-counter-repair-compaction-drift-checker.md`。

## Drift Checker Scenarios

| 场景 ID | 覆盖语义 |
|---|---|
| `coordination_counter_delete_tombstone_shadow` | `CounterMutationTest.testDeletes()` 确认 counter cell/row delete 后同 timestamp window 内 increment 仍被 tombstone shadow。 |
| `coordination_counter_read_before_write_tombstone_filter` | `CounterMutation` read-before-write 通过 `UnfilteredRowIterators.filter(...)` 只读取可见 current counter cells。 |
| `coordination_counter_context_merge_self_heal` | `CounterContext.compare()` 在 compaction 线程发现 same id/clock but different count 时 warning 并选择较大 count。 |
| `coordination_counter_local_shard_cleanup` | `markLocalToBeCleared()` / `clearAllLocal()` 的 local shard 清理和 header rewrite。 |
| `coordination_counter_digest_empty_legacy_context` | repaired-data digest 跳过 empty context、legacy shards 和 counter header。 |
| `coordination_counter_repair_validation_tombstone_purge` | validation compaction 的 purge evaluator always-purge gc-able tombstones，避免 repair hash 依赖本地 compaction timing。 |
| `coordination_counter_read_repair_deletion_boundary` | read repair 的 generic partition/range tombstone propagation applies to counter rows, but no counter-specific distributed deletion repair test is present. |
| `coordination_counter_cache_invalidation_boundary` | counter cache write/read/invalidate paths and range cleanup boundaries。 |
| `coordination_counter_repair_compaction_dtest_gap` | 当前缺少 distributed counter delete + repair + compaction 专项测试。 |
| `coordination_existing_counter_tests_baseline` | `CounterMutationTest`、`CounterContextTest`、`CountersTest`、`ReadCommandTest` 的现有覆盖基线。 |

## 设计目标

- 把 counter delete 的语义从 “reset counter” 明确改写为 “normal tombstone shadows current-value read”。
- 把 repair 的两个层次分开：repair/read repaired-data digest normalization 与实际 streaming/read-repair 数据修复不是同一个覆盖面。
- 把 compaction 的两个层次分开：普通 compaction tombstone GC 与 `CounterContext.compare()` 在 compactor thread 的 invalid shard self-heal warning。
- 保留测试缺口的机器校验：一旦 distributed counter delete + repair + compaction test 出现，checker 会失败并要求重写本矩阵。

## 关键结论

| 问题 | 结论 | 证据 |
|---|---|---|
| Counter delete 是否把 counter shard reset 为 0 | 否。delete 生成普通 tombstone；后续 counter increment 在 read-before-write 阶段只读取可见 cell，被 tombstone 遮蔽的 cell 不会复活。 | `src/java/org/apache/cassandra/db/CounterMutation.java:207-239`、`src/java/org/apache/cassandra/db/CounterMutation.java:273-319`、`test/unit/org/apache/cassandra/db/CounterMutationTest.java:160-217` |
| Counter 是否走 hinted handoff | 否。`CounterMutation.hintOnFailure()` 返回 `null`；普通 hint fallback 不适合 counter。 | `src/java/org/apache/cassandra/db/CounterMutation.java:85-88` |
| Repair digest 是否比较 counter header | 普通 digest 跳过 counter context header；repaired-data tracking 还跳过 empty context 和 legacy shards。 | `src/java/org/apache/cassandra/db/Digest.java:62-80`、`src/java/org/apache/cassandra/db/Digest.java:147-162` |
| Validation repair 如何处理 gc-able tombstone | validation compaction 的 controller 对每个 timestamp 返回 true，目的是避免 repair digest 受各节点本地 compaction schedule 影响。 | `src/java/org/apache/cassandra/db/repair/CassandraValidationIterator.java:69-97` |
| Compaction 对 counter context 有什么特殊风险 | global/remote shard same id+clock but count different 时，compactor thread warning 并选择最高 count 自愈；这通常提示历史 SSTable 丢失或 best-effort disk failure。 | `src/java/org/apache/cassandra/db/context/CounterContext.java:461-523` |
| 当前 distributed 覆盖是否证明 counter delete + repair + compaction | 没有。`CountersTest.testEmptyContext()` 覆盖 repaired-data digest/empty context，普通 read-repair tests 覆盖 deletion propagation，但没有 counter table + delete/tombstone + repair + compaction 的组合测试。 | `test/distributed/org/apache/cassandra/distributed/test/CountersTest.java:85-125`、`test/unit/org/apache/cassandra/db/ReadCommandTest.java:723-871` |

## 核心类

| 类 | 责任 | 关键边界 |
|---|---|---|
| `CounterMutation` | Counter write leader 上的 read-before-write、striped lock、counter cache 和 result mutation 生成。 | `hintOnFailure()` 为 null；`processModifications()` 通过 cache/CFS 读取 current value。 |
| `CounterContext` | Counter context shard layout、diff/merge/total、local shard cleanup、invalid shard warning。 | Header 是 local/global index；digest 跳过 header；compaction warning 只在 compactor thread 触发。 |
| `Digest` | Read/repaired-data digest byte accumulation。 | `forRepairedDataTracking()` 对 empty/legacy counter context 做 skip，普通 counter digest 跳过 header。 |
| `CassandraValidationIterator` | Repair validation compaction scanner。 | Validation controller always purges gc-able tombstones for stable repair hashes。 |
| `CompactionIterator` | 普通 compaction tombstone purge 和 shadowed cell removal。 | `TombstoneOption.CELL` 时移除被 tombstone source 遮蔽的 cells。 |
| `ColumnFamilyStore` | Counter cache read/write/invalidation、garbage collect/major compaction入口。 | counter table truncate/drop/range cleanup 必须清 counter cache。 |
| `RowIteratorMergeListener` | Read repair diff listener，生成缺失 row/partition/range tombstone repair mutation。 | 删除传播是 generic row/tombstone 语义，不是 counter 专用路径；实现位于 `src/java/org/apache/cassandra/service/reads/repair/RowIteratorMergeListener.java`。 |

## 核心接口与数据结构

- `CounterMutation.applyCounterMutation()`：获取 counter locks，处理每个 `PartitionUpdate`，本地 apply 后返回用于 replica 写入的 result mutation，见 `src/java/org/apache/cassandra/db/CounterMutation.java:129-151`。
- `PartitionUpdate.CounterMark`：counter write 中待填 current value 的 marker；cache/CFS 命中后会被 `markIter.remove()` 移出待处理列表，见 `src/java/org/apache/cassandra/db/CounterMutation.java:211-228`、`src/java/org/apache/cassandra/db/CounterMutation.java:302-319`。
- `CounterContext.ContextState`：封装 global/local/remote shard cursor；`CounterContext.compare()` 对同 id shard 根据 clock/count/global-local-remote 优先级合并，见 `src/java/org/apache/cassandra/db/context/CounterContext.java:447-531`。
- `CounterCacheKey` / `ClockAndCount`：counter cache 以 table、partition、clustering、column/path 定位 current local clock/count，读写入口见 `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:2499-2510`。
- `ValidationCompactionController`：repair validation 专用 compaction controller，`getPurgeEvaluator()` 固定允许 purge，见 `src/java/org/apache/cassandra/db/repair/CassandraValidationIterator.java:75-97`。
- `GarbageSkippingUnfilteredRowIterator`：普通 compaction 中借助 tombstone source 移除 shadowed data；cell-level GC 时调用 `Rows.removeShadowedCells(...)`，见 `src/java/org/apache/cassandra/db/compaction/CompactionIterator.java:408-641`。

## 生命周期

```text
Counter delete shadows later increment
  -> CQL DELETE / RowUpdateBuilder.delete(...)
  -> tombstone stored like normal deletion
  -> later CounterMutation.applyCounterMutation()
     -> collect CounterMark
     -> read current values from counter cache
     -> cache misses read CFS through SinglePartitionReadCommand
     -> UnfilteredRowIterators.filter(...) applies tombstones
     -> missing cell keeps mark as new counter
     -> result mutation is still shadowed by newer/equal deletion
```

```text
Repaired-data digest for counter context
  -> read execution controller enables repaired data digest
  -> Digest.forRepairedDataTracking()
     -> skip empty counter context
     -> skip legacy local/remote shards
     -> otherwise Digest.updateWithCounterContext()
        -> skip header
        -> digest body bytes only
```

```text
Repair validation compaction
  -> validation selects SSTables for ranges
  -> ValidationCompactionIterator(OperationType.VALIDATION)
  -> ValidationCompactionController.getPurgeEvaluator(key)
     -> return time -> true
  -> gc-able tombstones are excluded from validation hash
```

```text
Compaction/cache boundary
  -> compaction merges counter cells with CounterContext.merge()
  -> invalid same id/clock/different count logs warning in compactor thread
  -> tombstone GC may remove shadowed cells depending on TombstoneOption
  -> truncate/drop/range movement invalidates counter cache entries
```

## 配置项

| 配置 | 影响 | 证据 |
|---|---|---|
| `counter_write_request_timeout` | Counter lock/read-before-write/write 的 RPC timeout。 | `src/java/org/apache/cassandra/db/CounterMutation.java:328-331`、`conf/cassandra.yaml:1331-1334` |
| `concurrent_counter_writes` | Counter mutation stage concurrency and striped lock sizing input。 | `src/java/org/apache/cassandra/db/CounterMutation.java:59`、`conf/cassandra.yaml:716-724` |
| `counter_cache_size` / save options | Counter current-value cache capacity and persistence schedule。 | `src/java/org/apache/cassandra/service/CacheService.java:170-187`、`conf/cassandra.yaml:581-607` |
| `gc_grace_seconds` | Repair validation/normal compaction tombstone eligibility boundary。 | `src/java/org/apache/cassandra/db/repair/CassandraValidationIterator.java:100-105`、`src/java/org/apache/cassandra/db/compaction/CompactionIterator.java:392-405` |
| compaction `tombstone_threshold` / `tombstone_compaction_interval` | Tombstone compaction candidate selection; counter tables inherit normal compaction strategy behavior。 | `src/java/org/apache/cassandra/db/compaction/AbstractCompactionStrategy.java:70-120` |
| `repaired_data_tracking_for_partition_reads_enabled` / range reads | Enables repaired-data digest tracking exercised by distributed counter empty-context test。 | `test/distributed/org/apache/cassandra/distributed/test/CountersTest.java:88-124` |

## Metrics And Logs

- Counter delete/repair/compaction has no dedicated metric; use counter write timeout, counter cache behavior, read-repair/repair metrics, compaction logs and repaired-data tracking symptoms together.
- `CounterMutation.applyCounterMutation()` tracing names lock acquisition and cache/CFS current-value reads，见 `src/java/org/apache/cassandra/db/CounterMutation.java:134-140`、`src/java/org/apache/cassandra/db/CounterMutation.java:213-222`。
- `CounterContext.compare()` logs `invalid global counter shard detected` or `invalid remote counter shard detected` only when `CompactionManager.isCompactor(Thread.currentThread())`，见 `src/java/org/apache/cassandra/db/context/CounterContext.java:461-523`。
- `ReadCommandTest.dontIncludeLegacyCounterContextInDigest()` and `CountersTest.testEmptyContext()` are the closest regression anchors for repaired-data tracking behavior，见 `test/unit/org/apache/cassandra/db/ReadCommandTest.java:723-779`、`test/distributed/org/apache/cassandra/distributed/test/CountersTest.java:85-125`。

## 运维关注点

| 场景 | 判断 | 操作线索 |
|---|---|---|
| Counter delete 后 increment 不可见 | 可能是 tombstone shadow，而不是 write lost。 | 对比 deletion timestamp/gc grace；不要把 counter 当成 resettable scalar。 |
| Counter read repair/repair 后 digest 异常 | Empty/legacy counter context 被 repaired-data digest 特判。 | 检查 repaired data tracking、legacy shard、SSTable repaired metadata。 |
| Compaction warning invalid counter shard | 同 id/clock 不同 count，只能 deterministic pick highest。 | 排查历史 SSTable 丢失、best-effort disk failure、手工文件操作。 |
| Topology cleanup 后 counter 读异常 | counter cache 可能仍有不属于本节点 ranges 的 entry。 | `ColumnFamilyStore.cleanupCache()` 会按 ranges 清 counter cache；必要时 invalidate counter cache。 |
| Repair validation 与普通 compaction结果不同 | Validation compaction 为稳定 hash 会 purge gc-able tombstones；普通 compaction 还受 overlap/tombstone option/策略影响。 | 不要把 validation hash 行为等同于持久化 compaction 输出。 |

## 性能瓶颈

- Counter write 热点同时受 striped locks、current-value read 和 counter cache hit rate 影响；cache miss 必须构造 `SinglePartitionReadCommand` 并读 memtable/disk，见 `src/java/org/apache/cassandra/db/CounterMutation.java:158-176`、`src/java/org/apache/cassandra/db/CounterMutation.java:258-319`。
- Counter context with many legacy remote/local shards increases merge and digest cost; `hasLegacyShards()` forces repaired-data digest skip to avoid false mismatch，见 `src/java/org/apache/cassandra/db/context/CounterContext.java:592-607`。
- Validation repair includes all relevant SSTables and runs a compaction iterator; large tombstone-heavy counter tables can pay repair CPU even if the validation output is read-only，见 `src/java/org/apache/cassandra/db/repair/CassandraValidationIterator.java:115-150`。
- Cell-level tombstone GC can remove shadowed counter cells only when the compaction controller uses `TombstoneOption.CELL`; operator `garbagecollect` has explicit tombstone option surface，见 `src/java/org/apache/cassandra/db/compaction/CompactionIterator.java:617-641`、`src/java/org/apache/cassandra/service/StorageService.java:4308-4315`。

## 常见故障

| 故障 | 触发点 | 处理线索 |
|---|---|---|
| Deleted counter appears permanently gone after new increment | Tombstone timestamp shadows the new counter result. | Verify deletion timestamp and gc grace; wait for safe tombstone purge only after repair safety is understood. |
| Counter write timeout with low replica latency | Lock wait can exhaust `counter_write_request_timeout` before read/write. | Inspect hotspot partition/cell and counter cache hit rate; tune `concurrent_counter_writes` cautiously. |
| Repaired-data mismatch involving legacy counters | Repaired-data digest deliberately skips legacy shards, so mismatch may come from metadata/tombstone not body count. | Use `ReadCommandTest.dontIncludeLegacyCounterContextInDigest()` as semantic anchor. |
| Compaction logs invalid counter shard | Same id/clock with different count detected during compaction. | Treat as data-integrity warning; compaction picks highest count but cannot explain root cause. |
| Repair test seems to pass but production counter delete remains risky | Existing distributed test covers empty context/repaired metadata, not delete + repair + compaction. | `coordination_counter_repair_compaction_dtest_gap` remains open. |

## 测试用例

| 区域 | 已有测试 | 仍需补的专项测试 |
|---|---|---|
| Counter write/delete | `test/unit/org/apache/cassandra/db/CounterMutationTest.java` covers single/multi-cell, batch and `testDeletes()` tombstone shadow; `test/unit/org/apache/cassandra/db/CounterCellTest.java` covers counter cell reconcile and digest local-shard clearing. | Distributed counter delete followed by repair/read repair and compaction. |
| Counter context cleanup | `test/unit/org/apache/cassandra/db/context/CounterContextTest.java` covers `testClearLocal()` and merge/total. | Mixed legacy shard cleanup through streaming/repair with post-compaction verification. |
| Repaired-data digest | `test/unit/org/apache/cassandra/db/ReadCommandTest.java` covers legacy context digest skip and gc-able tombstone purge before repaired digest. | Counter-specific repaired-data digest with delete/tombstone and read repair mutation assertion. |
| Distributed counter baseline | `test/distributed/org/apache/cassandra/distributed/test/CountersTest.java` covers update/decrement and `testEmptyContext()` with repaired metadata. | Counter tombstone + `nodetool repair` + `nodetool compact` distributed data correctness matrix. |
| Generic repair deletion propagation | Read-repair query tests cover ordinary row/column/partition deletion propagation. | Counter table variant with counter cells and tombstone shadow. |

第六轮结论：counter repair/compaction 的源码语义、unit/distributed baseline 和缺口已拆开；仍未实现 counter tombstone + repair/compaction 的 distributed 专项测试。
