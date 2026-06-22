# Module: Range Read Performance Drift Checker

## 范围

`research/tools/check-range-read-performance-drift.py` 是 source-only drift check，用来保护 `research/module-range-read-performance-fault-matrix.md` 和本说明文档 `research/module-range-read-performance-drift-checker.md` 中关于 range read 性能与 fault coverage 的源码锚点。

当前基线：

- `RangeCommands` 通过 `cassandra.max_concurrent_range_requests`、10% margin、`estimateResultsPerRange()`、token 数和 RF 计算 initial concurrency。
- `RangeCommandIterator` 记录 `rangesQueried`、`batchesRequested`、`liveReturned`，按真实 rows/range 调整并发，并将 batch 数写入 `RangeSlice.RoundTripsPerReadHistogram`。
- `RangeCommandIterator.query()` 区分 local `Stage.READ`、remote `RANGE_REQ`、full/transient replica 和 repaired tracking flag。
- `PartitionRangeReadCommand` 与 `ReadCommand` 共同承担 SSTable overlap、row cache substitution、tombstone/read-size threshold 和 repaired-data tracking iterator 成本。
- 当前 distributed tests 没有把大量 vnode、多 remote replica、repaired range tracking 和 range performance metrics/max-concurrency 放进同一个场景。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `range_perf_initial_concurrency_estimate` | rows-per-range 估算、index estimate、token 数、RF 和 10% margin。 |
| `range_perf_max_concurrent_guardrail` | `cassandra.max_concurrent_range_requests` 上限和 unit coverage。 |
| `range_perf_dynamic_concurrency_roundtrips` | `computeConcurrencyFactor()`、`rangesQueried`、`batchesRequested`、`liveReturned` 和 round-trip metrics。 |
| `range_perf_remote_full_transient_contacts` | local/remote request dispatch、transient query copy 和 full replica tracking flag。 |
| `range_perf_repaired_tracking_overread` | range repaired-data tracking、`InputCollector` repaired merge 和 distributed normalization tests。 |
| `range_perf_row_cache_substitution` | range lazy merge 后的 cached partition replacement 与 `RowCacheTest.testRowCacheRange`。 |
| `range_perf_sstable_overlap_density` | selected SSTable count、`SSTablesPerRangeReadHistogram` 和 token range overlap tests。 |
| `range_perf_tombstone_read_size_thresholds` | tombstone warning/failure、local read size threshold 和 range tombstone correctness tests。 |
| `range_perf_denylist_rejection` | `StorageProxy.getRangeSlice()` denylist range read rejection。 |
| `range_perf_existing_tests_baseline` | 当前 unit/distributed test baseline。 |
| `range_perf_distributed_fault_gap` | negative scan：如果出现组合式 distributed perf/fault coverage，checker fail 以提示更新 gap wording。 |

## 设计目标

- 在不执行 Cassandra tests 的情况下，快速判断 range performance/fault 文档是否仍贴合源码。
- 把性能锚点和缺口锚点放在同一个 checker 中，避免只保护 happy-path structure。
- 当新增真正的 distributed coverage 时主动失败，推动文档从缺口矩阵更新为已覆盖矩阵。

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-range-read-performance-drift.py` | Source/doc/gap drift checker。 |
| `RangeCommands` | Initial concurrency、max concurrent range requests 和 rows-per-range estimate。 |
| `RangeCommandIterator` | Dynamic concurrency、remote/full/transient dispatch 和 round-trip metrics。 |
| `PartitionRangeReadCommand` | Local SSTable overlap、row cache substitution 和 `SSTablesPerRangeReadHistogram`。 |
| `ReadCommand` | Tombstone/read-size thresholds 与 repaired tracking iterator cost。 |
| `RepairDigestTrackingTest` | Range repaired tracking distributed correctness baseline。 |

## 运维关注点

- Green checker 只表示文档与当前 source/test baseline 一致，不表示缺口已经实现。
- 如果 range read 新增 speculation、read repair、rapid read protection 或 workload-specific scheduler，应该扩展 scenario IDs 和 source tokens。
- 如果新增 distributed max-concurrency/perf/fault test，`range_perf_distributed_fault_gap` 会 fail；此时应把 gap 改成测试用例说明，并更新 negative scan。

## 常见故障

- `source token contract ... RangeCommands.java` fails：initial concurrency、system property 或 rows/range estimate 变了。
- `source token contract ... RangeCommandIterator.java` fails：dynamic concurrency、remote dispatch、transient query 或 metrics 变了。
- `doc token ...` fails：新增文档、README 或 source map 未包含关键 source/test/scenario token。
- `gap still open ...` fails：仓库新增了组合式 distributed coverage，当前文档还停留在缺口描述。

## 运行方式

- `python3 research/tools/check-range-read-performance-drift.py`
- `python3 research/tools/check-range-read-performance-drift.py --json`
- Related validation: `python3 -m py_compile research/tools/check-range-read-performance-drift.py`
