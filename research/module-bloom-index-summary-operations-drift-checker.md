# Module: Bloom Index Summary Operations Drift Checker

## 目的

`research/tools/check-bloom-index-summary-operations-drift.py` 是 Bloom filter / index summary operations matrix 的源码漂移检查器。它不运行 Cassandra，也不依赖外部服务，只读取当前 checkout 的源码、测试和 `research/` 文档。

## 覆盖范围

检查器覆盖以下场景 ID：

- `bloom_ops_table_option_contract`
- `bloom_ops_filter_factory_limits`
- `bloom_ops_generated_component_contract`
- `bloom_ops_sorted_writer_filter_component`
- `bloom_ops_filter_load_rebuild_boundary`
- `bloom_ops_big_open_rebuild_matrix`
- `bloom_ops_bti_open_preload_matrix`
- `bloom_ops_reader_metrics_accounting`
- `bloom_ops_metrics_observability`
- `bloom_ops_index_summary_resize_runtime`
- `bloom_ops_legacy_mixed_version_gap`

## 源码锚点

- Schema/default/validation：`src/java/org/apache/cassandra/schema/TableParams.java`、`src/java/org/apache/cassandra/schema/CompactionParams.java`、`src/java/org/apache/cassandra/utils/BloomCalculations.java`
- Filter implementation：`src/java/org/apache/cassandra/utils/FilterFactory.java`、`src/java/org/apache/cassandra/io/sstable/format/FilterComponent.java`
- Writer/open path：`src/java/org/apache/cassandra/io/sstable/format/SortedTableWriter.java`、`src/java/org/apache/cassandra/io/sstable/format/big/BigSSTableReaderLoadingBuilder.java`、`src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReaderLoadingBuilder.java`
- Format boundary：`src/java/org/apache/cassandra/io/sstable/format/big/BigFormat.java`、`src/java/org/apache/cassandra/io/sstable/format/bti/BtiFormat.java`、`src/java/org/apache/cassandra/io/sstable/format/Version.java`
- Metrics/observability：`src/java/org/apache/cassandra/io/sstable/format/SSTableReaderWithFilter.java`、`src/java/org/apache/cassandra/io/sstable/filter/BloomFilterMetrics.java`、`src/java/org/apache/cassandra/io/sstable/indexsummary/IndexSummaryMetrics.java`、`src/java/org/apache/cassandra/tools/NodeProbe.java`、`src/java/org/apache/cassandra/tools/nodetool/stats/TableStatsHolder.java`
- Runtime config：`src/java/org/apache/cassandra/config/Config.java`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java`、`conf/cassandra.yaml`
- Tests：`test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java`、`test/unit/org/apache/cassandra/io/sstable/format/bti/LoadingBuilderTest.java`、`test/unit/org/apache/cassandra/schema/CreateTableValidationTest.java`、`test/unit/org/apache/cassandra/io/sstable/indexsummary/IndexSummaryManagerTest.java`、`test/unit/org/apache/cassandra/utils/BloomFilterTest.java`

## 运行方式

```bash
python3 research/tools/check-bloom-index-summary-operations-drift.py
```

成功时输出类似：

```text
OK Bloom/index-summary operations drift check: N checks
```

失败时会列出缺失的源码 token、文档 token 或已经被新测试关闭的 gap。若 future distributed/upgrade tests 覆盖 old Bloom / Big-BTI mixed-version 场景，检查器会失败，提示更新 `bloom_ops_legacy_mixed_version_gap`。

## 不覆盖

- 不构造真实 SSTable，不验证 old Bloom fixture 内容。
- 不运行 mixed-version upgrade、streaming、loader 或 rollback distributed test。
- 不验证外部监控系统是否抓取 JMX/nodetool metrics。
