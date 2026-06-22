# Module: Coordination Counter Repair/Compaction Drift Checker

## 范围

`research/tools/check-coordination-counter-repair-compaction-drift.py` 是 `research/module-coordination-counter-repair-compaction-matrix.md` 的 source/test/gap drift checker。它保护 counter delete tombstone shadow、read-before-write tombstone filtering、counter context merge/self-heal、local shard cleanup、repaired-data digest handling、validation compaction tombstone purge、read repair deletion boundary、counter cache invalidation and current distributed-test gap。

当前基线：

- `CounterMutationTest.testDeletes()` 覆盖 counter delete 后 increment 仍被 tombstone shadow。
- `CounterContextTest.testClearLocal()` 覆盖 mark/clear local shard behavior；`CounterContext.compare()` compactor warning remains source-backed。
- `Digest.forRepairedDataTracking()` and `ReadCommandTest` cover empty/legacy counter context digest behavior and gc-able tombstone purge before repaired digest。
- `CountersTest.testEmptyContext()` 覆盖 distributed repaired metadata + empty counter context baseline。
- No distributed counter delete + repair + compaction test is present in this checkout.

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `coordination_counter_delete_tombstone_shadow` | Counter delete/tombstone shadow baseline. |
| `coordination_counter_read_before_write_tombstone_filter` | Counter write current-value read filtered by normal tombstone semantics. |
| `coordination_counter_context_merge_self_heal` | Counter context invalid shard compaction warning and highest-count self-heal. |
| `coordination_counter_local_shard_cleanup` | Local shard mark/clear behavior and header rewrite. |
| `coordination_counter_digest_empty_legacy_context` | Empty context, legacy shard and header skipping in digest paths. |
| `coordination_counter_repair_validation_tombstone_purge` | Validation compaction always-purge evaluator for stable repair hashes. |
| `coordination_counter_read_repair_deletion_boundary` | Generic read repair deletion propagation boundary for counter tables. |
| `coordination_counter_cache_invalidation_boundary` | Counter cache read/write/invalidate/range cleanup contracts. |
| `coordination_counter_repair_compaction_dtest_gap` | Current absence of distributed counter tombstone + repair + compaction test. |
| `coordination_existing_counter_tests_baseline` | Existing source/test anchors that must stay cited. |

## 设计目标

- Fail when source contracts for counter read-before-write, context cleanup, digest normalization, validation compaction, compaction tombstone removal or counter cache invalidation move without updating the matrix.
- Fail when a distributed counter delete + repair + compaction test lands so the matrix stops calling that scenario missing.
- Keep this checker focused on counter repair/compaction; hints/batchlog backlog and Paxos direct handler gaps remain in their dedicated checkers.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-coordination-counter-repair-compaction-drift.py` | Source/test/gap drift checker. |
| `CounterMutation` | Counter write read-before-write, tombstone-filtered current-value read and hint boundary. |
| `CounterContext` | Merge, local shard cleanup, legacy shard detection and compaction warning. |
| `Digest` | Counter context digest semantics for normal and repaired-data tracking reads. |
| `CassandraValidationIterator` | Repair validation compaction and always-purge evaluator. |
| `CompactionIterator` | Ordinary compaction shadowed row/cell tombstone removal. |
| `ColumnFamilyStore` | Counter cache read/write/invalidate boundaries. |
| `CounterMutationTest` / `CounterContextTest` / `CountersTest` / `ReadCommandTest` | Existing coverage baseline. |

## 运维关注点

- A green checker means the current source/test/gap claims still match this checkout; it does not prove counter delete + repair + compaction is covered by a distributed test.
- If a counter-specific repair/compaction dtest lands, update `coordination_counter_repair_compaction_dtest_gap` and cite the new file.
- If `CounterContext` invalid-shard behavior changes, update the compaction warning/self-heal sections before changing the checker tokens.
- If repaired-data digest semantics change for legacy counter shards, update both the matrix and `ReadCommandTest` anchors.

## 常见故障

- `source token contract ... CounterMutation.java` fails: counter read-before-write or hint boundary moved.
- `source token contract ... CounterContext.java` fails: local shard cleanup or invalid shard warning moved.
- `source token contract ... Digest.java` fails: repaired-data counter digest normalization moved.
- `gap still open ...` fails: new distributed coverage likely landed and the matrix must be rewritten.
- `doc token ...` fails: protected scenario IDs, source paths, test anchors or explicit gap language disappeared.

## 运行方式

- `python3 research/tools/check-coordination-counter-repair-compaction-drift.py`
- `python3 research/tools/check-coordination-counter-repair-compaction-drift.py --json`
- Related validation: `python3 -m py_compile research/tools/check-coordination-counter-repair-compaction-drift.py`
