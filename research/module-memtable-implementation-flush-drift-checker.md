# Module: Memtable Implementation/Flush Drift Checker

## 目的

`research/tools/check-memtable-implementation-flush-drift.py` 用于保护 `research/module-memtable-implementation-flush-matrix.md` 与当前源码、测试和索引的一致性。它不运行 Cassandra，只读取源码和研究文档中的稳定 token。

## 运行方式

```bash
python3 research/tools/check-memtable-implementation-flush-drift.py
python3 research/tools/check-memtable-implementation-flush-drift.py --json
```

## 覆盖范围

- Memtable 公共接口和 factory durability/streaming/metrics contract：`Memtable.java`。
- 抽象基类、commitlog bound、allocator pool、period flush 和 largest memtable trigger：`AbstractMemtable.java`、`AbstractMemtableWithCommitlog.java`、`AbstractAllocatorMemtable.java`。
- SkipList/ShardedSkipList/Trie 实现、shard boundary、JMX shard count 和 trie metrics：`SkipListMemtable.java`、`ShardedSkipListMemtable.java`、`TrieMemtable.java`、`ShardBoundaries.java`、`TrieMemtableMetricsView.java`。
- 配置解析和 schema validation：`MemtableParams.java`、`TableParams.java`、`Config.java`、`DatabaseDescriptor.java`、`conf/cassandra.yaml`。
- Flush switch、PostFlush、writer runnable 和 memory cleaner：`ColumnFamilyStore.java`、`Flushing.java`、`MemtablePool.java`、`MemtableCleanerThread.java`。
- 测试锚点：`MemtableParamsTest`、`CreateTest`、`AlterTest`、`MemtableQuickTest`、`MemtableSizeTestBase`、`ShardedMemtableConfigTest`、`TrieMemtableMetricsTest`、`MemtableCleanerThreadTest`、`TrackerTest`、`CommitLogTest`。

## 场景 ID

checker 要求以下场景 ID 同时出现在矩阵、索引和 checker 说明中：

- `memtable_factory_durability_contract`
- `memtable_config_resolution_contract`
- `memtable_skiplist_write_flush_contract`
- `memtable_sharded_skiplist_boundary_contract`
- `memtable_trie_single_writer_metrics_contract`
- `memtable_allocator_pool_cleaner_contract`
- `memtable_flush_switch_barrier_contract`
- `memtable_postflush_reclaim_contract`
- `memtable_flush_writer_disk_boundary_contract`
- `memtable_table_schema_validation_contract`
- `memtable_jmx_shard_count_contract`
- `memtable_existing_test_baseline`
- `memtable_persistent_custom_gap`

## 失败处理

- source token 失败：确认类、方法或字段是否迁移；迁移后同步更新 `module-memtable-implementation-flush-matrix.md` 和 checker token。
- test token 失败：确认测试是否重命名或覆盖被删除；如果覆盖被删除，在矩阵中保留 explicit gap。
- doc/scenario 失败：恢复被删场景，或用新的场景 ID 替代并同步 `research/README.md`、`research/notes/source-map.md` 和 checker。
