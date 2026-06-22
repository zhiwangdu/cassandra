# Module: Row Index Read Size Thresholds Matrix

## 范围

本矩阵补齐 BigTable `RowIndexEntry` read-size 阈值的独立研究面：BigTable primary index lookup、`RowIndexEntry.Serializer.deserialize()`、`IndexedEntry` / `ShallowIndexedEntry` 选择、materialized row-index memory 估算、`ROW_INDEX_READ_SIZE_*` message params、`WarningsSnapshot` abort mapping、`RowIndexSize*` metrics、runtime config/JMX 和现有 distributed threshold tests。通用 tombstone/local/coordinator warning 框架见 `research/module-read-warning-abort-thresholds-matrix.md`；Big/BTI format 和 key cache 差异见 `research/module-sstable-format-runtime-matrix.md` 与 `research/module-cache-index-view-deep-dive.md`。

当前源码基线：

- `ReadCommand.executeLocally()` 把当前 command 放入 thread-local `COMMAND`，BigTable primary-index 反序列化可通过 `ReadCommand.getCommand()` 判断当前读请求和表元数据，见 `src/java/org/apache/cassandra/db/ReadCommand.java:100`、`src/java/org/apache/cassandra/db/ReadCommand.java:170`、`src/java/org/apache/cassandra/db/ReadCommand.java:430`。
- BigTable point read 先 `getRowIndexEntry()`，命中 primary index 后调用 `rowIndexEntrySerializer.deserialize(in)`；精确命中并允许 stats 时会把反序列化的 `RowIndexEntry` 写入 key cache，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:126`、`src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:255`、`src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:325`、`src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:343`。
- `RowIndexEntry.create()` 根据 index samples 和 `column_index_cache_size` 选择 plain `RowIndexEntry`、on-heap `IndexedEntry` 或 disk-backed `ShallowIndexedEntry`，见 `src/java/org/apache/cassandra/io/sstable/format/big/RowIndexEntry.java:216`。
- `RowIndexEntry.Serializer.checkSize()` 只在当前 read command 存在、非 system keyspace、`read_thresholds_enabled=true` 且 row-index warn/fail 至少一个非空时启用，见 `src/java/org/apache/cassandra/io/sstable/format/big/RowIndexEntry.java:377`。
- Row-index fail 写 `ROW_INDEX_READ_SIZE_FAIL`、移除 warn 并抛 `RowIndexEntryReadSizeTooLargeException`；warn 只保留当前请求中最大 `ROW_INDEX_READ_SIZE_WARN`，见 `src/java/org/apache/cassandra/io/sstable/format/big/RowIndexEntry.java:392`。
- `WarningContext` 把 `ROW_INDEX_READ_SIZE_FAIL` 映射为 `RequestFailureReason.READ_SIZE`，`WarningsSnapshot.maybeAbort()` 把 row-index abort 映射为 `ReadSizeAbortException`，`CoordinatorWarnings.done()` 写 `RowIndexSizeWarnings` / `RowIndexSizeAborts`，见 `src/java/org/apache/cassandra/service/reads/thresholds/WarningContext.java:54`、`src/java/org/apache/cassandra/service/reads/thresholds/WarningsSnapshot.java:117`、`src/java/org/apache/cassandra/service/reads/thresholds/CoordinatorWarnings.java:97`。
- BTI `TrieIndexEntry` 不允许 key cache/in-memory persisted entry，`BtiTableReader` 通过 partition trie 获取 `TrieIndexEntry`；本矩阵的 BigTable `RowIndexEntry` threshold 不覆盖 BTI lookup path，见 `src/java/org/apache/cassandra/io/sstable/format/bti/TrieIndexEntry.java:33`、`src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java:128`。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `row_index_read_size_threadlocal_contract` | `ReadCommand.COMMAND` thread-local 让 SSTable index deserialization 能定位当前 CQL query 和 keyspace。 |
| `row_index_read_size_big_lookup_contract` | BigTable reader 的 Bloom/key-cache/index-summary/primary-index lookup 到 `RowIndexEntry.Serializer.deserialize()` 的触发路径。 |
| `row_index_read_size_entry_shape_contract` | Plain `RowIndexEntry`、on-heap `IndexedEntry` 和 disk-backed `ShallowIndexedEntry` 的选择规则与 `column_index_cache_size` 边界。 |
| `row_index_read_size_threshold_gate` | Threshold gate：非 system keyspace、`read_thresholds_enabled`、warn/fail 非空和 `ReadCommand` 存在。 |
| `row_index_read_size_memory_estimate_contract` | Materialized memory estimate = per-entry object overhead * entries + serialized bytes；strictly greater-than threshold 才 warn/fail。 |
| `row_index_read_size_warn_contract` | Warn path 写入最大 `ROW_INDEX_READ_SIZE_WARN`，不覆盖更大的已记录 warning。 |
| `row_index_read_size_abort_contract` | Fail path 移除 warn、写 `ROW_INDEX_READ_SIZE_FAIL`、抛 `RowIndexEntryReadSizeTooLargeException` 并在 coordinator 映射为 read-size abort。 |
| `row_index_read_size_warning_aggregation_contract` | `WarningContext` / `WarningsSnapshot` / `CoordinatorWarnings` 聚合 row-index warnings/aborts、输出 client warning 和 table metrics。 |
| `row_index_read_size_metrics_contract` | `Index.RowIndexEntry.*` histograms 与 table/keyspace `RowIndexSize*` metrics 的职责边界。 |
| `row_index_read_size_config_jmx_contract` | Config/YAML/DatabaseDescriptor/StorageService runtime setter 和 warn/fail validation。 |
| `row_index_read_size_bti_boundary` | BTI `TrieIndexEntry` 不走 BigTable key-cache/`RowIndexEntry` threshold path，测试也只在 `BigFormat.isSelected()` 下运行。 |
| `row_index_read_size_tests_baseline` | `RowIndexSizeWarningTest` + `AbstractClientSizeWarning` 覆盖 single-partition warn/fail/disabled/metrics；config/YAML tests 覆盖加载和 validation。 |
| `row_index_read_size_scan_test_boundary` | 当前 RowIndexSize dtest 显式忽略 scan 变体，保留 source-proven contract 与 runtime test boundary 的差异。 |

## 调用图

```text
single-partition read on BigTable SSTable
  -> ReadCommand.executeLocally()
     -> COMMAND.set(this)
     -> BigTableReader.rowIterator(key, ...)
        -> getRowIndexEntry(key, EQ, updateStats=true, listener)
           -> min/max and Bloom filter
           -> key cache lookup
           -> index summary scan position
           -> primary index scan
           -> rowIndexEntrySerializer.deserialize(in)
              -> RowIndexEntry.Serializer.deserialize(...)
                 -> read position / size / header / deletion / columnsIndexCount
                 -> checkSize(columnsIndexCount, size)
                    -> ReadCommand.getCommand()
                    -> row_index_read_size warn/fail thresholds
                    -> tableMetrics.rowIndexSize.update(estimatedMemory)
                    -> ROW_INDEX_READ_SIZE_WARN or ROW_INDEX_READ_SIZE_FAIL
                 -> if size <= column_index_cache_size: IndexedEntry
                 -> else: ShallowIndexedEntry
           -> exact match: cacheKey(decoratedKey, indexEntry)
     -> ReadCallback warning snapshot
        -> WarningContext.updateCounters()
        -> WarningsSnapshot.maybeAbort()
        -> CoordinatorWarnings.done()
```

## 设计目标

- Prevent very wide partitions from forcing too much row-index metadata onto heap while reading BigTable SSTables.
- Keep row-index thresholding near the deserialization point where entry count and serialized size are known.
- Reuse the read warning/abort framework so row-index warnings reach clients and metrics like local read-size warnings.
- Preserve BigTable key-cache compatibility while keeping BTI out of the BigTable `RowIndexEntry` path.

## 解决的问题

- Wide partitions create many `IndexInfo` entries; materializing them on heap can create GC pressure before row data is returned.
- Row-index memory pressure is not the same as result size or local row heap size; it is tied to SSTable index metadata shape.
- Without message params, replica-side row-index rejects would degrade into generic read failures without typed metrics.
- BigTable and BTI use different partition/row index structures; operators need to know which metrics and thresholds apply.

## 设计取舍

- Threshold checks are source-local to BigTable `RowIndexEntry.Serializer`, not a generic `SSTableReader` hook; this keeps the estimate close to the serialized shape but makes BTI an explicit boundary.
- Fail/warn use `estimatedMemory > threshold`, while local read-size uses `>=`; runbooks should not assume every read-size threshold has identical comparison semantics.
- Warning stores only the largest row-index estimated memory for a command through `MessageParams.get()` / add-if-larger semantics.
- `RowIndexEntryReadSizeTooLargeException` is a local `RejectException`; coordinator-visible behavior is `ReadSizeAbortException` once warning params are merged.
- Current dtest disables key cache and forces flush/multiple index entries so the RowIndexEntry path is exercised deterministically.

## 核心类

| 类/文件 | 作用 |
|---|---|
| `ReadCommand` | Holds the current read command in a FastThreadLocal while local SSTable read code executes. |
| `BigTableReader` | BigTable Bloom/key-cache/index-summary/primary-index lookup and `RowIndexEntry` deserialization trigger. |
| `RowIndexEntry` | BigTable row-index entry hierarchy, serializer, materialized-memory estimate and warning/abort params. |
| `IndexedEntry` | On-heap `IndexInfo[]` entry used when serialized index data is within `column_index_cache_size`. |
| `ShallowIndexedEntry` | Disk-backed entry for large row-index metadata, with `IndexInfoRetriever` fetching entries from the primary index file. |
| `TrieIndexEntry` / `BtiTableReader` | BTI boundary; uses partition trie/row-index file and rejects key-cache/in-memory persisted entry assumptions. |
| `WarningContext` / `WarningsSnapshot` / `CoordinatorWarnings` | Row-index warning/abort aggregation and client/table metric publication. |
| `TableMetrics` / `KeyspaceMetrics` | `RowIndexSize`, `RowIndexSizeWarnings`, `RowIndexSizeAborts` metrics. |

## 核心接口

- `ReadCommand.getCommand()`、`executeLocally()`。
- `BigTableReader.rowIterator()`、`getRowIndexEntry()`。
- `RowIndexEntry.create()`、`Serializer.deserialize()`、`Serializer.checkSize()`、`estimateMaterializedIndexSize()`。
- `RowIndexEntry.openWithIndex()`、`IndexInfoRetriever.columnsIndex()`。
- `WarningContext.updateCounters()`、`WarningsSnapshot.rowIndexReadSizeAbortMessage()`、`rowIndexSizeWarnMessage()`。
- `StorageService.getRowIndexReadSizeWarnThreshold()` / `setRowIndexReadSizeWarnThreshold()` / `getRowIndexReadSizeAbortThreshold()` / `setRowIndexReadSizeAbortThreshold()`。

## 核心数据结构

| 数据结构 | 语义 |
|---|---|
| `RowIndexEntry` | Plain entry with only data-file position when no row-index samples are needed. |
| `IndexedEntry` | Keeps `IndexInfo[]` on heap and records index-entry size/count/get histograms when opened. |
| `ShallowIndexedEntry` | Stores counts/offsets and creates `ShallowInfoRetriever` to read `IndexInfo` from the primary index file on demand. |
| `MessageParams` `ROW_INDEX_READ_SIZE_WARN/FAIL` | Internode warning params carrying estimated row-index materialized bytes. |
| `WarningsSnapshot.rowIndexReadSize` | Coordinator-side warn/abort counter with instances and max value. |

## 配置项

| 配置项 | Source | 语义 |
|---|---|---|
| `read_thresholds_enabled` | `src/java/org/apache/cassandra/config/Config.java:526`、`conf/cassandra.yaml:2015` | Enables row-index read-size warning/fail reporting across replicas. |
| `row_index_read_size_warn_threshold` / `row_index_read_size_fail_threshold` | `src/java/org/apache/cassandra/config/Config.java:531`、`conf/cassandra.yaml:2029`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4913` | BigTable RowIndexEntry materialized memory warning/failure thresholds. |
| `column_index_cache_size` | `src/java/org/apache/cassandra/io/sstable/format/big/RowIndexEntry.java:106`、`src/java/org/apache/cassandra/io/sstable/format/big/RowIndexEntry.java:360` | Determines whether index samples are held on heap as `IndexedEntry` or accessed as `ShallowIndexedEntry`. |
| `column_index_size_in_kb` | `test/distributed/org/apache/cassandra/distributed/test/thresholds/RowIndexSizeWarningTest.java:48` | Test-side knob to force multiple row-index entries. |

## Metrics

- `Index.RowIndexEntry.IndexedEntrySize`、`IndexInfoCount`、`IndexInfoGets`、`IndexInfoReads` are registered in `RowIndexEntry` static initialization and updated when row-index entries are opened/read，见 `src/java/org/apache/cassandra/io/sstable/format/big/RowIndexEntry.java:148`、`src/java/org/apache/cassandra/io/sstable/format/big/RowIndexEntry.java:589`、`src/java/org/apache/cassandra/io/sstable/format/big/RowIndexEntry.java:754`、`src/java/org/apache/cassandra/io/sstable/format/big/RowIndexEntry.java:886`。
- Table/keyspace `RowIndexSize`, `RowIndexSizeWarnings`, `RowIndexSizeAborts` are created in `TableMetrics` / `KeyspaceMetrics` and updated by `RowIndexEntry.Serializer.checkSize()` plus `CoordinatorWarnings.done()`，见 `src/java/org/apache/cassandra/metrics/TableMetrics.java:282`、`src/java/org/apache/cassandra/metrics/KeyspaceMetrics.java:178`、`src/java/org/apache/cassandra/io/sstable/format/big/RowIndexEntry.java:389`、`src/java/org/apache/cassandra/service/reads/thresholds/CoordinatorWarnings.java:97`。
- Global client request `ReadSizeAborts` is shared with local/coordinator read-size aborts through `ClientRequestMetrics.markAbort()`，见 `src/java/org/apache/cassandra/metrics/ClientRequestMetrics.java:57`。

## 日志

- Row-index local fail message includes CQL, estimated in-memory bytes, total entries, total serialized bytes and `row_index_read_size_fail_threshold`，见 `src/java/org/apache/cassandra/io/sstable/format/big/RowIndexEntry.java:394`。
- Coordinator warning/abort messages use `row_index_size_warn_threshold` / `row_index_size_fail_threshold` in the client-facing text, even though config field names include `read_size`，见 `src/java/org/apache/cassandra/service/reads/thresholds/WarningsSnapshot.java:154`。
- `CoordinatorWarnings.recordAborts()` / `recordWarnings()` emits both `ClientWarn` and logger warning for row-index counters，见 `src/java/org/apache/cassandra/service/reads/thresholds/CoordinatorWarnings.java:156`。

## 运维关注点

- Row-index warnings point to very wide partitions with large row-index metadata, not necessarily large returned result sets.
- If BTI is selected, this BigTable RowIndexEntry threshold path is not the primary lookup path; inspect BTI-specific row index behavior and format selection before applying BigTable assumptions.
- A warning mentioning `row_index_size_warn_threshold` maps back to config `row_index_read_size_warn_threshold`.
- Key cache can bypass primary-index deserialization for cached exact matches; tests disable key cache to force the threshold path.
- Pair `RowIndexSize*` metrics with `Index.RowIndexEntry.*` histograms and partition width diagnostics.

## 性能瓶颈

- Very wide partitions with many clustering blocks increase `IndexInfo` count and either on-heap entry size or disk index reads.
- `ShallowIndexedEntry` avoids materializing all samples but pays random/sequential reads through `IndexInfoRetriever`.
- Repeated cache misses can deserialize RowIndexEntry metadata repeatedly and update row-index size histograms.
- Aborting at row-index metadata lookup avoids deeper row scanning but still pays primary-index lookup/deserialization cost up to the check.

## 常见故障

- `RowIndexEntryReadSizeTooLargeException`: replica rejected a BigTable row-index entry before row data was read.
- Client sees `ReadSizeAbortException` / read failure with `READ_SIZE`: row-index, local read-size or coordinator result-size may be the cause; check warning text and `RowIndexSize*` vs `LocalReadSize*` / `CoordinatorReadSize*` metrics.
- Warning text uses `row_index_size_*` but YAML uses `row_index_read_size_*`.
- Expected warning missing: `read_thresholds_enabled=false`, thresholds null, system keyspace, key-cache hit, BTI format, or no multi-block RowIndexEntry.

## 测试用例

- `RowIndexSizeWarningTest` sets row-index thresholds to 1KiB/2KiB, assumes `BigFormat.isSelected()`, disables scan variants, forces flush/multiple index entries and verifies warning/abort messages plus `RowIndexSize*` metrics，见 `test/distributed/org/apache/cassandra/distributed/test/thresholds/RowIndexSizeWarningTest.java:34`。
- `AbstractClientSizeWarning` provides no-warning, warning, abort, tracking-disabled, driver and histogram/global abort assertions shared by coordinator/local/row-index size tests，见 `test/distributed/org/apache/cassandra/distributed/test/thresholds/AbstractClientSizeWarning.java:97`、`test/distributed/org/apache/cassandra/distributed/test/thresholds/AbstractClientSizeWarning.java:242`。
- `DatabaseDescriptorTest` validates row-index warn <= fail semantics and warn-only/fail-only cases，见 `test/unit/org/apache/cassandra/config/DatabaseDescriptorTest.java:763`。
- `YamlConfigurationLoaderTest` validates `row_index_read_size_warn_threshold` / `row_index_read_size_fail_threshold` loading from YAML and map，见 `test/unit/org/apache/cassandra/config/YamlConfigurationLoaderTest.java:203`。
