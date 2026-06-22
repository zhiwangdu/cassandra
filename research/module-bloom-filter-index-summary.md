# Module: Bloom Filter And Index Summary

## 范围

本模块限定在 SSTable 读路径中的 Bloom filter、Filter.db、index summary、summary resize 和相关读加速结构，不展开完整 compaction 策略或 SSTable 格式差异。

## 设计目标

本模块覆盖 Cassandra 5.0 SSTable 读路径中的两个轻量索引结构：Bloom filter 和 index summary。Bloom filter 用于在进入 partition index/data seek 前快速排除不存在的 partition key；index summary 则采样 primary index，减少 BigTable 格式下定位 partition index 位置时的二分和磁盘读取成本。

设计目标：

- Bloom filter 必须低成本、off-heap、可序列化，并允许按表配置 false positive chance。
- `bloom_filter_fp_chance = 1.0` 时可以退化为 always-present filter，避免为不需要过滤的表分配 bitset。
- SSTable 写出时生成 filter/summary；打开旧 SSTable 时如果组件缺失且需要使用，应能从 index component 重建。
- Index summary 受 `min_index_interval`、`max_index_interval` 和全局内存池控制，可后台重采样。
- 查询语义必须保守：Bloom false positive 只导致额外 seek，false negative 不允许出现。

## 解决的问题

- Bloom filter 把“大量不存在 key 的 point read”从 SSTable index/data seek 降级为内存 bitset 检查；核心 `IFilter` 接口只暴露 add/isPresent/serialization/off-heap size，见 `src/java/org/apache/cassandra/utils/IFilter.java:25-64`。
- Bloom filter 由 table params 驱动，`TableParams` 默认从 compaction strategy 取 `bloom_filter_fp_chance`，并验证 false positive chance 范围，见 `src/java/org/apache/cassandra/schema/TableParams.java:80-119` 和 `src/java/org/apache/cassandra/schema/TableParams.java:160-165`。
- `FilterComponent.maybeLoadBloomFilter()` 在 SSTable 打开时决定 load、skip、rebuild 或返回 always-present filter，见 `src/java/org/apache/cassandra/io/sstable/format/FilterComponent.java:99-141`。
- BigTable reader 先查 Bloom filter，再在 index summary/partition index 中定位 key；Bloom 不命中直接返回不存在，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:258-279`。
- Index summary 将 sampled keys、offsets、position 等信息放在 off-heap memory，并提供 binary search 和 skip-entry 辅助，见 `src/java/org/apache/cassandra/io/sstable/indexsummary/IndexSummary.java:55-170`。
- `IndexSummaryManager` 以全局 memory pool 和 resize interval 管理所有支持 summary 的 SSTable，见 `src/java/org/apache/cassandra/io/sstable/indexsummary/IndexSummaryManager.java:57-148`。

## 设计取舍

- Bloom filter 使用 Murmur hash 的 base/increment 组合生成多个 bucket；`add()` 只置位，`isPresent()` 只要发现一个 unset bit 即可排除，见 `src/java/org/apache/cassandra/utils/BloomFilter.java:88-136`。
- `FilterFactory` 按元素数和目标 buckets-per-element 创建 off-heap bitset；当 false positive chance 为 1.0 时使用 `AlwaysPresent`，见 `src/java/org/apache/cassandra/utils/FilterFactory.java:30-75` 和 `src/java/org/apache/cassandra/utils/FilterFactory.java:77-125`。
- Bloom filter 是 SSTable component，不参与共识或复制语义；损坏或缺失时可重建，代价是打开 SSTable 时扫描 index。
- BigTable 有 index summary，BTI 格式使用 partition index 结构但仍保留 Bloom filter；BTI loading builder 也会在缺失时重建 filter，见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReaderLoadingBuilder.java:91-156`。
- Index summary 以采样换内存；下采样减少 memory pressure，但增加 primary index seek 范围，见 `src/java/org/apache/cassandra/io/sstable/indexsummary/IndexSummaryBuilder.java:294-350`。

## 核心类

| 类 | 作用 |
|---|---|
| `IFilter` | Bloom filter 抽象接口，包含 `add()`、`isPresent()`、`isInformative()`、`serializedSize()` 和 off-heap size。定义见 `src/java/org/apache/cassandra/utils/IFilter.java:25` |
| `BloomFilter` | off-heap bitset + hash count 的 Bloom filter 实现。定义见 `src/java/org/apache/cassandra/utils/BloomFilter.java:31` |
| `FilterFactory` | 根据元素数或目标 false positive chance 创建 Bloom filter/always-present filter。定义见 `src/java/org/apache/cassandra/utils/FilterFactory.java:30` |
| `BloomFilterSerializer` | Bloom filter 的新旧格式序列化器，见 `src/java/org/apache/cassandra/utils/BloomFilterSerializer.java:29-80` |
| `FilterComponent` | SSTable `Filter.db` 的 load/save/maybeLoad 入口，见 `src/java/org/apache/cassandra/io/sstable/format/FilterComponent.java:39` |
| `SSTableReaderWithFilter` | 带 Bloom filter 的 reader 基类，封装 filter tracker 和 may-contain 判断。定义见 `src/java/org/apache/cassandra/io/sstable/format/SSTableReaderWithFilter.java:36` |
| `BloomFilterTracker` | 记录 true/false positive 和 recent false positive ratio，见 `src/java/org/apache/cassandra/io/sstable/filter/BloomFilterTracker.java:23-82` |
| `BloomFilterMetrics` | 每表 Bloom false positive/ratio metrics，见 `src/java/org/apache/cassandra/io/sstable/filter/BloomFilterMetrics.java:29-120` |
| `IndexSummary` | sampled primary-index keys/offsets 的 off-heap 结构。定义见 `src/java/org/apache/cassandra/io/sstable/indexsummary/IndexSummary.java:55` |
| `IndexSummaryBuilder` | flush/open/rebuild 时构建或下采样 summary，定义见 `src/java/org/apache/cassandra/io/sstable/indexsummary/IndexSummaryBuilder.java:38` |
| `IndexSummaryManager` | 后台 resize、JMX 管理和全局内存池控制。定义见 `src/java/org/apache/cassandra/io/sstable/indexsummary/IndexSummaryManager.java:61` |

## 核心接口

- `IFilter.add()` / `isPresent()` / `isInformative()`：Bloom filter 的写入、查询和退化能力判断接口，见 `src/java/org/apache/cassandra/utils/IFilter.java:25-64`。
- `SSTableReaderWithFilter.mayContainAssumingKeyIsInRange()`：SSTable reader 对外的 may-contain 判断，封装 informative filter 与 primary-index fallback，见 `src/java/org/apache/cassandra/io/sstable/format/SSTableReaderWithFilter.java:69-75`。
- `IndexSummarySupport`：BigTable reader 暴露 summary 给 `IndexSummaryManager` 的支持接口，使用入口见 `src/java/org/apache/cassandra/io/sstable/indexsummary/IndexSummaryManager.java:76-94`。
- `IndexSummaryManagerMBean`：JMX 调整 summary memory pool 和 resize interval 的管理接口，实现入口见 `src/java/org/apache/cassandra/io/sstable/indexsummary/IndexSummaryManager.java:112-148`。

## 核心数据结构

- `BloomFilter.bitset`：off-heap bitset，容量由 `BloomCalculations` 结果决定；hash count 和 bitset 在构造函数固定，见 `src/java/org/apache/cassandra/utils/BloomFilter.java:31-49`。
- `FilterFactory.AlwaysPresent`：`isPresent()` 永远 true、`isInformative()` false，用于配置上不需要 Bloom 的 SSTable，见 `src/java/org/apache/cassandra/utils/FilterFactory.java:77-125`。
- `IndexSummary.entries` / `offsets`：summary entry 数量、key bytes 和 offsets 分离存储，便于 binary search 和 off-heap size 统计，见 `src/java/org/apache/cassandra/io/sstable/indexsummary/IndexSummary.java:55-110`。
- `IndexSummaryBuilder.ReadableBoundary`：写入过程中标记当前 summary 可安全打开的上下界，BigTable writer 用它 open early reader，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableWriter.java:130-179` 和 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableWriter.java:262-289`。
- `TableParams.bloomFilterFpChance`、`minIndexInterval`、`maxIndexInterval`：schema 层保存的表级控制参数，toCQL 输出见 `src/java/org/apache/cassandra/schema/TableParams.java:250-310`。

## 生命周期

Flush / compaction 写出：

```text
SortedTableWriter
  -> beforeAppend()
     -> if shouldUseBloomFilter(params.bloomFilterFpChance)
        -> bf.add(partitionKey)
  -> finish()
     -> FilterComponent.save(bf, descriptor, true)
BigTableWriter.IndexWriter
  -> summary = new IndexSummaryBuilder(keyCount, minIndexInterval, BASE_SAMPLING_LEVEL)
  -> maybeAddEntry(key, indexPosition)
  -> new IndexSummaryComponent(summary.build(...)).save(Summary.db)
```

SSTable 打开：

```text
BigSSTableReaderLoadingBuilder
  -> FilterComponent.maybeLoadBloomFilter(...)
  -> loadSummary()
  -> if filter/summary missing and needed:
       buildSummaryAndBloomFilter(indexFile, rebuildFilter, rebuildSummary)
       save rebuilt Filter.db / Summary.db
  -> BigTableReader.Builder.setFilter(...).setIndexSummary(...)
```

读取：

```text
ReadCommand local execution
  -> SSTable reader selected by key/range
  -> BigTableReader.getPosition()
     -> isPresentInFilter(key)
        -> false: filterTracker.addFalsePositive? no data seek
        -> true: use index summary to bound primary index search
```

## 调用链

- Bloom filter 写入：`SortedTableWriter` 在追加 key 时调用 `bf.add()`，finish 时保存 filter component，见 `src/java/org/apache/cassandra/io/sstable/format/SortedTableWriter.java:445-458` 和 `src/java/org/apache/cassandra/io/sstable/format/SortedTableWriter.java:501-503`。
- BigTable summary 写出：`BigTableWriter.IndexWriter` 构造 `IndexSummaryBuilder`，finish 时保存 `Summary.db`，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableWriter.java:244-255` 和 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableWriter.java:321-323`。
- 打开时重建：`BigSSTableReaderLoadingBuilder.buildSummaryAndBloomFilter()` 扫描 index file 生成 Bloom/summary，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigSSTableReaderLoadingBuilder.java:188-240`。
- BTI filter 重建：`BtiTableReaderLoadingBuilder.buildBloomFilter()` 从 partition index 生成 Bloom filter，见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReaderLoadingBuilder.java:150-179`。
- Reader may-contain：`SSTableReaderWithFilter.mayContainAssumingKeyIsInRange()` 在 informative filter 和 primary index fallback 之间选择，见 `src/java/org/apache/cassandra/io/sstable/format/SSTableReaderWithFilter.java:69-75`。
- BigTable lookup：`BigTableReader` Bloom 不命中直接返回，命中后从 index summary 找 sampled index，再读 primary index，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:258-279`。
- Summary resize：`BigTableReader.cloneWithNewSummarySamplingLevel()` 可 downsample 或 rebuild summary 并保存 component，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:580-640`。

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| `bloom_filter_fp_chance` | `src/java/org/apache/cassandra/schema/TableParams.java:80-119` | 表级 Bloom false positive target；默认可由 compaction strategy 决定 |
| `min_index_interval` | `src/java/org/apache/cassandra/schema/TableParams.java:121-145` | index summary 最小采样间隔；越小 summary 越大、seek 越短 |
| `max_index_interval` | `src/java/org/apache/cassandra/schema/TableParams.java:121-145` | summary resize 后允许的最大 effective interval |
| `index_summary_capacity` | `src/java/org/apache/cassandra/io/sstable/indexsummary/IndexSummaryManager.java:101-110` | 全局 summary memory pool 容量 |
| `index_summary_resize_interval` | `src/java/org/apache/cassandra/io/sstable/indexsummary/IndexSummaryManager.java:101-120` | 后台 summary 重采样周期；负值可暂停 resize |

## Metrics

- `BloomFilterMetrics` 暴露 false positives、true positives、recent false positive ratio 等每表指标，见 `src/java/org/apache/cassandra/io/sstable/filter/BloomFilterMetrics.java:29-120`。
- `BloomFilterTracker` 是 reader 内部计数器，`SSTableReaderWithFilter.addTo(StatsMetadata)` 将结果写回 stats，见 `src/java/org/apache/cassandra/io/sstable/format/SSTableReaderWithFilter.java:116-147`。
- `IndexSummaryMetrics` 暴露 index summary memory pool 容量、已用容量和 resize interval，见 `src/java/org/apache/cassandra/io/sstable/indexsummary/IndexSummaryMetrics.java:28-51`。

## 日志

- Bloom filter load/save 失败会在 `FilterComponent` 中记录 warn/error，并在需要时尝试 rebuild 或返回 always-present filter，见 `src/java/org/apache/cassandra/io/sstable/format/FilterComponent.java:90-150`。
- `IndexSummaryBuilder` 在 `min_index_interval` 过低且会溢出 expected keys 时记录 warn 并提高 interval，见 `src/java/org/apache/cassandra/io/sstable/indexsummary/IndexSummaryBuilder.java:100-132`。
- `IndexSummaryManager` 初始化、容量调整和定时 resize 在 manager 构造及 setter 中处理，见 `src/java/org/apache/cassandra/io/sstable/indexsummary/IndexSummaryManager.java:97-148`。

## 运维关注点

- Bloom false positive ratio 升高通常意味着 `bloom_filter_fp_chance` 太宽松、SSTable 很旧或 workload 里大量查询不存在 key；它会增加 index/data seek，但不影响正确性。
- `bloom_filter_fp_chance = 1.0` 等价于放弃 Bloom 过滤，适合极少 point negative lookup 的表，但可能放大 miss-heavy read。
- Index summary 内存不足时 manager 会下采样冷 SSTable；点读 latency 可能出现更多 primary index seek。
- 修改 `min_index_interval` / `max_index_interval` 不会立即改写所有 SSTable；新 SSTable 使用新参数，旧 SSTable 可通过 summary redistribution/rebuild 调整。
- Bloom/summary component 缺失时启动或打开 SSTable 可能额外扫描 index component；大量缺失会拖慢节点恢复。

## 性能瓶颈

- Bloom filter 过大消耗 off-heap，过小带来 false positive seek；最佳点取决于 negative lookup 比例和内存预算。
- Index summary 下采样会减少内存，但提高 primary index 的扫描跨度；宽分区多、key 很大的表更敏感。
- SSTable 数量过多时，即使 Bloom filter 能排除大部分 SSTable，仍有 per-SSTable metadata/filter 检查成本；compaction 策略和 cache 命中率同样重要。
- 打开旧 SSTable 时重建 Bloom/summary 会与 bootstrap/repair/compaction 后的 reader loading 叠加。

## 常见故障

- `Filter.db` 损坏：`FilterComponent.load()` 失败后根据路径可能删除/重建，若不能重建则退化为 less-informative read path，见 `src/java/org/apache/cassandra/io/sstable/format/FilterComponent.java:53-71` 和 `src/java/org/apache/cassandra/io/sstable/format/FilterComponent.java:99-150`。
- `bloom_filter_fp_chance` 非法：`TableParams.validate()` 拒绝小于等于最小支持值或大于 1 的值，见 `src/java/org/apache/cassandra/schema/TableParams.java:160-165`。
- Summary rebuild 被取消：`IndexSummaryManagerTest` 覆盖 `CompactionManager.stopCompaction("INDEX_SUMMARY")` 与 interrupt 路径，见 `test/unit/org/apache/cassandra/io/sstable/indexsummary/IndexSummaryManagerTest.java:618-629`。

## 测试用例

- `BloomFilterTest` 覆盖 false positive、serialization、off-heap allocation 和 Murmur hash 行为，见 `test/unit/org/apache/cassandra/utils/BloomFilterTest.java:49-234`。
- `BloomFilterTrackerTest` 覆盖 true/false positive 计数隔离，见 `test/unit/org/apache/cassandra/io/sstable/filter/BloomFilterTrackerTest.java:26-57`。
- `IndexSummaryTest` 覆盖 key size、binary search、serialization、downsample 和 position 计算，见 `test/unit/org/apache/cassandra/io/sstable/indexsummary/IndexSummaryTest.java:57-428`。
- `IndexSummaryManagerTest` 覆盖 min/max interval 变更、redistribution、JMX、cancel/pause 路径，见 `test/unit/org/apache/cassandra/io/sstable/indexsummary/IndexSummaryManagerTest.java:82-724`。

## 待继续

- Big/BTI partition index、generated-on-load component、old Bloom filter serialization 和 compaction strategy default FP chance 已在 `research/module-bloom-sstable-index-deep-dive.md` 补充。
- 后续只保留测试侧缺口：mixed-version upgrade/streaming distributed test 与 legacy old Bloom filter loader fixture 的组合覆盖。
