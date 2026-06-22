# Module: Range Read Storage Drift Checker

## 范围

`research/tools/check-range-read-storage-drift.py` 是 source-only drift check，用来保护 `research/module-range-read-storage-engine-matrix.md`、`research/flow-range-read.md`、`research/module-read-path.md`、`research/module-storage-engine.md` 和 `research/module-local-read-merge-cache-deep-dive.md` 中关于 range read 与 storage engine 逐分片交互的源码锚点。

当前基线：

- `PartitionRangeReadCommand` 保存 `requestedSlices`，`forSubRange()` 对 continuation 使用 `limits().withoutState()`，本地 `queryStorage()` 选择 live view、打开 memtable/SSTable partition iterator、lazy merge 并做 row cache filter。
- `DataRange` 区分 key range 与 clustering filter，`Paging.forSubRange()` 只在左边界等于原 start key 时保留 paging filter。
- `PartitionRangeQueryPager` 通过 `lastReturnedKey`、`lastReturnedRow` 和 remaining-in-partition 决定下一页是 `forPaging()` 还是 `forSubRange()`。
- `RangeCommands` 使用 `cassandra.max_concurrent_range_requests`、10% margin 和 rows/range 估算构造 `RangeCommandIterator`。
- `RangeCommandIterator` 负责 dynamic concurrency、local `Stage.READ`、remote `RANGE_REQ`、transient query copy、round trips 和 coordinator scan latency。
- BigTable、BTI、SkipList、ShardedSkipList 和 Trie memtable 都提供 range `partitionIterator(...)` contract。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `range_storage_data_range_contract` | `DataRange` key range/clustering filter 与 `requestedSlices` contract。 |
| `range_storage_paging_boundary` | range pager 的 same-partition paging 与 cross-partition subrange 分支。 |
| `range_storage_subrange_state_reset` | `PartitionRangeReadCommand.forSubRange()` 对 continuation limits state 的隔离。 |
| `range_storage_replica_plan_split_merge` | ring token split、`ReplicaPlans.forRangeRead()` 与 adjacent plan merge。 |
| `range_storage_dynamic_concurrency` | `MAX_CONCURRENT_RANGE_REQUESTS`、10% margin 和 concurrency factor 逻辑。 |
| `range_storage_local_memtable_sstable_merge` | replica 本地 memtable/SSTable partition iterator 收集和 lazy merge。 |
| `range_storage_row_cache_filter` | range lazy merge 输出后的 cached partition replacement。 |
| `range_storage_repaired_tracking_overread` | range read repaired-data tracking 与 `InputCollector` repaired merge。 |
| `range_storage_sstable_reader_format_boundary` | Big/BTI/memtable range iterator contract。 |
| `range_storage_metrics_observability` | rangeLatency、coordinatorScanLatency、SSTablesPerRangeReadHistogram 和 roundTrips。 |
| `range_storage_tests_coverage` | range iterator、bounds/limits、client metrics 和 SSTablesIterated 测试锚点。 |

## 设计目标

- Fail when range read storage behavior moves without updating research docs.
- Keep coordinator plan/concurrency, pager bounds and replica local storage scan in one drift boundary.
- Make the remaining gaps explicit: distributed fault coverage, row-cache substitution focus test and performance matrix.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-range-read-storage-drift.py` | Source/doc drift checker。 |
| `PartitionRangeReadCommand` | Range command、subrange copy、本地 queryStorage 与 cache filter。 |
| `DataRange` | key range、clustering filter、paging/subrange transformation。 |
| `PartitionRangeQueryPager` | range paging state 和 next page command 构造。 |
| `RangeCommands` | coordinator range command iterator construction。 |
| `ReplicaPlanIterator` / `ReplicaPlanMerger` | subrange split 与 adjacent plan merge。 |
| `RangeCommandIterator` | dynamic concurrency、local/remote requests、metrics。 |
| `ReadCommand.InputCollector` | range 本地 repaired-data tracking 和 final iterator merge。 |
| `BigTableReader` / `BtiTableReader` | SSTable range scanner format boundary。 |

## 运维关注点

- A green checker proves research docs still match the current source anchors; it does not prove the missing distributed/performance tests exist.
- If range read adds speculation, rapid read protection or read repair semantics, the checker should add source tokens and move the docs out of the current gap wording.
- If row cache substitution receives a focused test, update `range_storage_row_cache_filter` and remove that gap from the matrix.
- If new SSTable format readers or memtable implementations land, add their `partitionIterator(...)` anchors.

## 常见故障

- `source token contract ... PartitionRangeReadCommand.java` fails: local range scan, cache filter or subrange state behavior changed.
- `source token contract ... RangeCommandIterator.java` fails: dynamic concurrency, request dispatch or coordinator metrics changed.
- `doc token ...` fails: a scenario/path/metric/test is not named in the protected research docs.
- `scenario coverage ...` fails: the matrix forgot one of the range storage scenario IDs.

## 运行方式

- `python3 research/tools/check-range-read-storage-drift.py`
- `python3 research/tools/check-range-read-storage-drift.py --json`
- Related validation: `python3 -m py_compile research/tools/check-range-read-storage-drift.py`
