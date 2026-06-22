# Module: SSTable Format Runtime Drift Checker

## 目的

`research/tools/check-sstable-format-runtime-drift.py` 用于保护 SSTable format/runtime 研究矩阵与当前源码、测试和索引的一致性。它只做静态 token 检查，不运行 Cassandra。

## 运行方式

```bash
python3 research/tools/check-sstable-format-runtime-drift.py
python3 research/tools/check-sstable-format-runtime-drift.py --json
```

## 覆盖范围

- format/config：`SSTableFormat`、`AbstractSSTableFormat`、`DatabaseDescriptor.applySSTableFormats()`、`Config.SSTableConfig`、`StorageCompatibilityMode`、`conf/cassandra.yaml`。
- descriptor/component：`Descriptor`、`Component`、`SSTableFormat.Components`、`TOCComponent`。
- reader/writer：`SSTableReader`、`SSTableReaderLoadingBuilder`、`SSTableWriter`、`SortedTableWriter`、`DataComponent`、`StatsComponent`、`CompressionInfoComponent`。
- metadata：`MetadataType`、`MetadataCollector`、`MetadataSerializer`、`StatsMetadata`、`ValidationMetadata`、`CompactionMetadata`。
- Big/BTI：`BigFormat`、`BigTableReader`、`BigTableWriter`、`BigSSTableReaderLoadingBuilder`、`BtiFormat`、`BtiTableReader`、`BtiTableWriter`、`BtiTableReaderLoadingBuilder`、`PartitionIndex`、`TrieIndexEntry`。
- tests：`SSTableFormatTest`、`StorageCompatibilityModeTest`、`SSTableReaderTest`、`SSTableWriterTest`、`SSTableWriterTransactionTest`、`MetadataSerializerTest`、`CQLSSTableWriterTest`、`LoadingBuilderTest`、`VerifyTest`、`ScrubTest`、`LegacySSTableTest`、`SSTableLoaderLegacyTest`。

## 场景 ID

- `sstable_format_registry_config_contract`
- `sstable_descriptor_component_contract`
- `sstable_reader_open_components_contract`
- `sstable_writer_finish_toc_contract`
- `sstable_metadata_stats_mutation_contract`
- `sstable_big_format_components_contract`
- `sstable_bti_format_components_contract`
- `sstable_filter_keycache_metrics_contract`
- `sstable_verify_scrub_contract`
- `sstable_cql_writer_format_contract`
- `sstable_legacy_compatibility_contract`
- `sstable_runtime_gap_contract`

## 失败处理

- source token 失败：确认类/方法是否迁移；迁移后同步更新 `module-sstable-format-runtime-matrix.md` 和 checker token。
- test token 失败：确认测试是否重命名或覆盖被删除；如果覆盖被删除，在矩阵中保留 explicit gap。
- doc/scenario 失败：同步 `research/README.md`、`research/notes/source-map.md` 和本 checker 说明，避免矩阵成为孤立文档。
