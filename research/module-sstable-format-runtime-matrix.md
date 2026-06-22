# Module: SSTable Format Runtime Matrix

## 范围

本矩阵补齐 `research/module-sstable-compaction.md` 和 `research/module-bloom-sstable-index-deep-dive.md` 之间的 SSTable runtime 合同：format registry/config、descriptor/component 命名、reader open/load、writer finish/TOC、metadata serialization/mutation、Big/BTI 组件集、verify/scrub、CQL offline writer、legacy SSTable 兼容和 compaction/streaming 边界。对应 checker 是 `research/tools/check-sstable-format-runtime-drift.py`。

## 场景矩阵

| 场景 ID | 保护内容 | 源码锚点 | 测试/缺口 |
|---|---|---|---|
| `sstable_format_registry_config_contract` | `sstable.selected_format`、ServiceLoader format factories、selected write format 和 storage compatibility validation | `Config.SSTableConfig`、`DatabaseDescriptor.applySSTableFormats()`、`StorageCompatibilityMode.validateSstableFormat()` | `SSTableFormatTest`、`StorageCompatibilityModeTest` |
| `sstable_descriptor_component_contract` | `Descriptor` 从文件名解析 version/format/component，组件 type 全局注册，`TOC.txt` 维护 component set | `Descriptor.java`、`Component.java`、`SSTableFormat.Components`、`TOCComponent.java` | `SSTableReaderTest` open/rebuild 分支间接覆盖 |
| `sstable_reader_open_components_contract` | reader open 要求 `DATA`，validate 模式要求 primary components，打开 compression/stats/filter/index 资源失败要释放 | `SSTableReader.open()`、`SSTableReaderLoadingBuilder.build()`、`CompressionInfoComponent.verifyCompressionInfoExistenceIfApplicable()` | `SSTableReaderTest.checkOpenedBigTable()`、`checkOpenedBtiTable()` |
| `sstable_writer_finish_toc_contract` | writer append/finish、flush observer、transaction prepare、`Stats.db` 和 `TOC.txt` 写入、final reader open | `SSTableWriter.java`、`SortedTableWriter.java`、`StatsComponent.java`、`TOCComponent.java` | `SSTableWriterTest`、`SSTableWriterTransactionTest` |
| `sstable_metadata_stats_mutation_contract` | `MetadataType`、Stats/Validation/Compaction/Header component，commitlog intervals、level、repair metadata 和 metadata rewrite | `MetadataCollector.java`、`MetadataSerializer.java`、`StatsMetadata.java` | `MetadataSerializerTest`、`SSTableWriterTest` repaired metadata cases |
| `sstable_big_format_components_contract` | Big format `Data.db`/`Index.db`/`Summary.db`/`Filter.db` component set、generated-on-load filter+summary、key cache/summary metrics | `BigFormat.java`、`BigTableReader.java`、`BigTableWriter.java`、`BigSSTableReaderLoadingBuilder.java` | `SSTableReaderTest`、`SSTableWriterTransactionTest` |
| `sstable_bti_format_components_contract` | BTI `Data.db`/`Partitions.db`/`Rows.db` component set、generated-on-load filter、no key cache、partition trie lookup | `BtiFormat.java`、`BtiTableReader.java`、`BtiTableWriter.java`、`PartitionIndex.java`、`TrieIndexEntry.java` | `LoadingBuilderTest`、`VerifyTest`、`ScrubTest` |
| `sstable_filter_keycache_metrics_contract` | `SSTableReaderWithFilter` 的 true positive/true negative/false positive 统计和 non-informative filter fallback | `SSTableReaderWithFilter.java`、`FilterComponent.java`、Big/BTI reader lookup | `SSTableReaderTest.testGetPositionsBloomFilterStats()` |
| `sstable_verify_scrub_contract` | verifier/scrubber 按 format 选择 primary index component，Big 与 BTI corruption 行为不同 | `SSTableFormat.getScrubber()`、`SortedTableVerifier`、`BigTableVerifier`、`BtiTableVerifier`、`SortedTableScrubber` | `VerifyTest`、`ScrubTest` |
| `sstable_cql_writer_format_contract` | offline `CQLSSTableWriter` 可显式选择 Big/BTI format，并验证输出 descriptor format | `CQLSSTableWriter.java`、format writer factories | `CQLSSTableWriterTest` |
| `sstable_legacy_compatibility_contract` | legacy SSTable version 读取、cache/stream/compaction、old Bloom filter zero-copy fallback | `Version.hasOldBfFormat()`、`Descriptor.isCompatible()`、legacy test fixtures | `LegacySSTableTest`、`SSTableLoaderLegacyTest` |
| `sstable_runtime_gap_contract` | 仍缺 mixed-version Big/BTI rolling upgrade、streaming/automatic upgrade/old BF 组合 distributed coverage | 当前 unit/legacy tests 为主 | explicit gap，后续需要 distributed compatibility suite |

## 调用图

```text
Startup/config:
  cassandra.yaml sstable.selected_format
    -> Config.SSTableConfig
    -> DatabaseDescriptor.applySSTableFormats()
    -> ServiceLoader<SSTableFormat.Factory>
    -> validate factories/options
    -> selectedSSTableFormat = getAndValidateWriteFormat(...)
    -> StorageCompatibilityMode.validateSstableFormat(...)

Flush/compaction/offline write:
  SSTableWriter.Builder.addDefaultComponents(...)
    -> DATA + STATS + DIGEST + TOC
    -> optional COMPRESSION_INFO / CRC / index components
    -> SortedTableWriter.Builder.addDefaultComponents(...)
       -> optional FILTER
    -> BigTableWriter.Builder.addDefaultComponents(...)
       -> PRIMARY_INDEX + SUMMARY
    -> BtiTableWriter.Builder.addDefaultComponents(...)
       -> PARTITION_INDEX + ROW_INDEX
  SSTableWriter.append(...)
    -> SortedTableWriter.append(...)
    -> format partition writer + index writer
  SSTableWriter.finish(openResult)
    -> observers.complete()
    -> txnProxy.finish()
    -> StatsComponent.save(...)
    -> TOCComponent.updateTOC(...)
    -> openFinal(...)

Open/read:
  SSTableReader.open(...)
    -> descriptor.getFormat().getReaderFactory().loadingBuilder(...)
    -> SSTableReaderLoadingBuilder.build(owner, validate, online)
       -> TOCComponent.loadOrCreate(...)
       -> require DATA and primary components when validate=true
       -> CompressionInfoComponent.verifyCompressionInfoExistenceIfApplicable(...)
       -> openComponents(...)
       -> reader builder.build(...)

Big lookup:
  BigTableReader.rowIterator(...)
    -> getRowIndexEntry(EQ)
    -> Bloom / min-max / key cache / index summary / primary index scan
    -> RowIndexEntry

BTI lookup:
  BtiTableReader.rowIterator(...)
    -> getExactPosition(...)
    -> Bloom / min-max
    -> PartitionIndex.Reader.exactCandidate(...)
    -> Rows.db TrieIndexEntry or direct Data.db position
```

## 配置、Metrics 与日志

- `sstable.selected_format` 默认 `big`，5.0 还支持 `bti`；`storage_compatibility_mode: CASSANDRA_4` 禁止新写 BTI。
- Big format 的 generated-on-load components 是 `FILTER` 和 `SUMMARY`；BTI 只有 `FILTER`，主索引组件 `Partitions.db` 不能按 generated-on-load 处理。
- `SSTableReaderWithFilter` 更新 Bloom filter true positive、true negative 和 false positive 计数；Big 额外提供 IndexSummary/KeyCache metrics provider，BTI 不支持 key cache。
- `StatsMetadata` 保存 commitlog intervals、timestamp/local deletion/TTL、SSTable level、repairedAt、pendingRepair、isTransient、first/last key 和 clustering min/max。
- open path 会记录 `Opening {descriptor}`、filter/summary/index missing/corruption 和 loaded latency；writer prepare 会写 `Statistics.db` 和 `TOC.txt`，失败进入 transaction abort。

## 运维关注点

- 不要把所有缺失组件等价看待：Big 的 `Summary.db` 和两种 format 的 `Filter.db` 可重建，`Data.db`、Big `Index.db`、BTI `Partitions.db` 是 primary components。
- BTI 缺 `Rows.db` 只影响 indexed wide partition row-index path，但 `Partitions.db` 缺失会破坏主分区定位。
- metadata mutation（level/repairedAt/pendingRepair/isTransient）只应改写 `Statistics.db`；需要和 lifecycle transaction、snapshot/backup 策略一起看。
- legacy SSTable 能读不代表所有 runtime path 一样；old Bloom filter format 会影响 zero-copy streaming/loader 行为。
- `CQLSSTableWriter.withFormat(...)` 是离线写入入口，输出文件必须由 descriptor version format 证明，不应只看文件后缀。

## 后续缺口

- `sstable_runtime_gap_contract`：缺少 mixed-version rolling upgrade 下 `storage_compatibility_mode`、Big/BTI selected format、streaming、automatic SSTable upgrade 和 rollback 的 distributed matrix。
- old Bloom filter fixture 当前有 legacy loader/read/stream coverage，但还需要与 zero-copy streaming fallback、automatic upgrade 和 BTI selected-format 混合验证。
