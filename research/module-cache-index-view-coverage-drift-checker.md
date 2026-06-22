# Module: Cache Index View Coverage Drift Checker

## 范围

`research/tools/check-cache-index-view-coverage-drift.py` 是 `research/module-cache-index-view-vector-import-repair.md` 的 source/test/gap drift checker。它保护 Cache / Secondary Index / SAI / Materialized View 第四轮研究中关于 SAI vector ANN、SSTable import SAI validation/build、streaming SAI failure、MV repair write path、Big/BTI key-cache 边界和剩余专项测试缺口的判断。

当前基线：

- SAI vector ANN 已有 source 和 distributed coverage：memtable/on-disk、multi-SSTable、partition restricted、token restricted、paging/no-LIMIT rejection；vector corrupt graph/compressed-vector fault injection 仍是 gap still open。
- Import/streaming SAI 已有 default import missing-components build、build interruption、checksum failure、entire/non-entire streaming failure coverage；nodetool `import -ri` missing-component distributed test 仍是 gap still open。
- MV repair 的 source contract 和 `CassandraStreamReceiverTest` condition matrix 已有覆盖；repair+MV data correctness distributed test 仍是 gap still open。
- BigTable and BTI key-cache/lookup boundary is source-backed and unit-backed; Big/BTI mixed-version or legacy-format upgrade coverage remains gap still open.

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `cache_index_sai_vector_ann_baseline` | SAI top-K search source path and `VectorDistributedTest` ANN baseline. |
| `cache_index_sai_vector_corruption_gap` | Current absence of direct vector graph/compressed-vector corruption fault injection. |
| `cache_index_sai_import_validation_build_baseline` | `SSTableImporter` default validate/build path and `ImportIndexedSSTablesTest` build/interruption/checksum coverage. |
| `cache_index_sai_import_require_components_gap` | Current absence of nodetool `import -ri` / `--require-index-components` missing-component coverage. |
| `cache_index_sai_streaming_failure_baseline` | Entire and non-entire SAI streaming failure coverage in `IndexStreamingFailureTest`. |
| `cache_index_mv_repair_write_path_baseline` | `CassandraStreamReceiver.requiresWritePath()` repair/MV/CDC source and unit coverage. |
| `cache_index_mv_repair_correctness_gap` | Current absence of distributed repair+MV data correctness coverage. |
| `cache_index_big_bti_key_cache_boundary` | BigTable key cache vs BTI partition-trie/no-key-cache source and unit coverage. |
| `cache_index_big_bti_mixed_version_gap` | Current absence of Big/BTI key-cache or lookup mixed-version upgrade coverage. |
| `cache_index_existing_tests_baseline` | Existing Vector, Import, Streaming, MV condition, Big/BTI key-cache and storage compatibility test anchors. |

## 设计目标

- Fail when SAI ANN, import/build/validation, streaming receiver, MV repair write path, or Big/BTI lookup contracts move without a research update.
- Fail when a new test lands for a documented gap so the matrix stops calling it missing.
- Keep import default behavior separate from `import -ri`: the default path may build missing SAI components, while `-ri` should fail before copy/move when components are missing.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-cache-index-view-coverage-drift.py` | Source/test/gap drift checker. |
| `StorageAttachedIndexSearcher` / `VectorTopKProcessor` | Replica ANN search, score-order retrieval and primary-key ordered response. |
| `DiskAnn` / `VectorIndexSegmentSearcher` / `VectorMemoryIndex` | On-disk and memtable vector graph/brute-force/compressed-vector paths. |
| `SSTableImporter` / `Import` | Default SAI validate/build behavior and nodetool `-ri` precheck surface. |
| `SecondaryIndexManager` / `StorageAttachedIndexGroup` | SSTable-attached index validation, checksum verification and incremental build futures. |
| `CassandraStreamReceiver` / `StreamOperation` | Streaming receive, SAI validation, and MV/CDC write-path replay. |
| `BigTableReader` / `BtiTableReader` / `BtiFormat` | Big key cache vs BTI no-key-cache lookup boundary. |

## 运维关注点

- A green checker preserves the current source/test/gap claims; it does not imply the missing tests have been implemented.
- If vector graph/compressed-vector corruption tests land, rewrite `cache_index_sai_vector_corruption_gap` with the new anchors.
- If `import -ri` tests land, split default import build coverage from require-components failure coverage.
- If repair+MV data correctness or Big/BTI mixed-version tests land, replace the gap IDs with covered scenario IDs and update the absence predicates.

## 常见故障

- `source token contract ... SSTableImporter.java` fails: import precheck/default SAI validation/build behavior changed.
- `source token contract ... CassandraStreamReceiver.java` fails: repair/MV write-path or SAI streaming validation behavior changed.
- `gap still open ...` fails: a documented missing test appears and the research must be updated.
- `doc token ...` fails: protected scenario IDs, source paths, test anchors or explicit gap language disappeared.

## 运行方式

- `python3 research/tools/check-cache-index-view-coverage-drift.py`
- `python3 research/tools/check-cache-index-view-coverage-drift.py --json`
- Related validation: `python3 -m py_compile research/tools/check-cache-index-view-coverage-drift.py`
