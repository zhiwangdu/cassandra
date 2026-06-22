# Module: Bloom Filter And SSTable Index Deep Dive

## 范围

本模块补充 `module-bloom-filter-index-summary.md` 中未展开的 SSTable format 差异：BigTable 与 BTI 的 Bloom/index lookup、component sets、generated-on-load 行为、旧 Bloom filter 序列化格式、`bloom_filter_fp_chance` 默认值和相关测试覆盖。不重复展开完整 compaction 策略、row index block 格式或 SAI 二级索引。

## 设计目标

- BigTable 格式继续用 `Index.db` + `Summary.db` 作为 partition key 定位结构，Bloom filter 只负责 point read 的快速 negative check。
- BTI 格式用 trie partition index 替代 BigTable primary-index scan，用 `Rows.db` 保存宽分区 row index，用负数编码直接指向 data file 的小分区位置。
- `Filter.db` 对 BigTable 和 BTI 都是可重建的 generated-on-load component；BigTable 还可重建 `Summary.db`，BTI 不再使用 index summary。
- 新版本 Bloom filter 使用内存字节布局序列化；BigTable 旧版本仍可按旧格式反序列化，以支持 legacy SSTable 读入和 loader。
- `bloom_filter_fp_chance` 缺省值必须由 compaction strategy 明确落地，用户显式 table option 优先。

## 解决的问题

- BigTable lookup 在 Bloom 命中后还需要 key cache、index summary 和 primary index scan；miss-heavy point read 能被 Bloom 过滤，但 false positive 会进入 primary-index 查找，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:258-346`。
- BTI lookup 在 Bloom 命中后通过 `PartitionIndex.Reader.exactCandidate()` 或 `ceiling()` 定位 `Rows.db`/`Data.db`，不使用 key cache 和 index summary，见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java:128-167` 和 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java:223-282`。
- BigTable component set 中 `Filter.db` 与 `Summary.db` 都属于 generated-on-load；BTI generated-on-load 只有 `Filter.db`，主索引组件是 `Partitions.db`，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigFormat.java:81-121` 和 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiFormat.java:70-111`。
- 旧 Bloom filter 格式由 version feature flag 驱动，`FilterComponent` 按 `descriptor.version.hasOldBfFormat()` 选择 serializer，见 `src/java/org/apache/cassandra/io/sstable/format/Version.java:68-74`、`src/java/org/apache/cassandra/io/sstable/format/FilterComponent.java:53-80` 和 `src/java/org/apache/cassandra/utils/BloomFilterSerializer.java:29-80`。
- 表级 Bloom 默认值不是 YAML 常量，而是 `TableParams` 在 builder 没显式设置时调用 `CompactionParams.defaultBloomFilterFbChance()`：LCS 为 `0.1`，其他策略为 `0.01`，见 `src/java/org/apache/cassandra/schema/TableParams.java:95-101` 和 `src/java/org/apache/cassandra/schema/CompactionParams.java:261-264`。

## 设计取舍

- BigTable 读路径保留 key cache：`EQ` 和部分 `GE` 查询可先查 key cache，命中时避免 index summary/primary index scan；BTI 明确不支持 key cache，`BtiFormat` 的 key-cache serializer 直接抛 assertion，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:265-275`、`src/java/org/apache/cassandra/io/sstable/format/big/BigFormat.java:270-290` 和 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiFormat.java:189-193`。
- BigTable 的 `Summary.db` 是内存/seek 之间的采样取舍；summary 下采样减少 off-heap 占用，但扩大 primary index 扫描区间，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:579-647`。
- BTI 把 partition index 做成 trie，payload 中携带低位 filter hash，用 prefix match 加 hash byte 降低不存在 key 的误候选概率；仍需读取 data/row-index key 做最终确认，见 `src/java/org/apache/cassandra/io/sstable/format/bti/PartitionIndex.java:96-140` 和 `src/java/org/apache/cassandra/io/sstable/format/bti/PartitionIndex.java:283-301`。
- BTI writer 对小分区直接在 trie payload 中存 `~dataPosition`，对 indexed partition 存 `Rows.db` position；这减少了不必要 row-index 文件访问，但 reader 必须按正负号分流，见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableWriter.java:185-213` 和 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java:248-267`。
- `bloom_filter_fp_chance = 1.0` 会退化为 non-informative filter；BTI 为避免每次 miss 都随机读 partition index，可在没有 informative Bloom 时 preload partition index，见 `src/java/org/apache/cassandra/io/sstable/format/FilterComponent.java:141-144`、`src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReaderLoadingBuilder.java:139-148` 和 `test/unit/org/apache/cassandra/io/sstable/format/bti/LoadingBuilderTest.java:58-95`。

## 核心类

| 类 | 作用 |
|---|---|
| `BigTableReader` | BigTable partition key lookup：Bloom gate、key cache、summary 二分、primary index scan 和 cache update，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:240-346` |
| `BigSSTableReaderLoadingBuilder` | BigTable 打开时加载或重建 filter/summary/index file，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigSSTableReaderLoadingBuilder.java:80-153` 和 `src/java/org/apache/cassandra/io/sstable/format/big/BigSSTableReaderLoadingBuilder.java:181-240` |
| `BigFormat.BigVersion` | BigTable version feature flags，包括 `ma` 到 `oa`、old Bloom filter format 和 streaming compatibility，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigFormat.java:341-405` 和 `src/java/org/apache/cassandra/io/sstable/format/big/BigFormat.java:516-525` |
| `BtiTableReader` | BTI partition trie lookup 和 `Rows.db`/`Data.db` entry 读取，见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java:122-167` 和 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java:223-282` |
| `BtiTableReaderLoadingBuilder` | BTI 打开时加载 filter、重建 filter、打开 row/partition index 和可选 preload，见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReaderLoadingBuilder.java:87-148` |
| `PartitionIndex` | BTI on-disk trie partition index，payload 存 position 和 filter hash lower bits，见 `src/java/org/apache/cassandra/io/sstable/format/bti/PartitionIndex.java:49-65` 和 `src/java/org/apache/cassandra/io/sstable/format/bti/PartitionIndex.java:96-140` |
| `PartitionIndexBuilder` | BTI partition trie 写入和 footer 完成逻辑，见 `src/java/org/apache/cassandra/io/sstable/format/bti/PartitionIndexBuilder.java:124-183` |
| `TrieIndexEntry` | BTI row-index entry，禁止进入 key cache/in-memory index entry 持久化路径，见 `src/java/org/apache/cassandra/io/sstable/format/bti/TrieIndexEntry.java:29-32` 和 `src/java/org/apache/cassandra/io/sstable/format/bti/TrieIndexEntry.java:61-97` |

## 核心接口

- `SSTableReaderWithFilter.isPresentInFilter()` / `mayContainAssumingKeyIsInRange()`：reader 统一的 Bloom filter check 和 non-informative fallback，见 `src/java/org/apache/cassandra/io/sstable/format/SSTableReaderWithFilter.java:64-75`。
- `PartitionIndex.Reader.exactCandidate()`：BTI exact lookup 的 trie candidate 选择，先检查 key prefix，再检查 payload hash bits，见 `src/java/org/apache/cassandra/io/sstable/format/bti/PartitionIndex.java:283-301`。
- `PartitionIndex.Reader.ceiling()`：BTI `GE`/`GT` lookup 的 closest greater lookup，见 `src/java/org/apache/cassandra/io/sstable/format/bti/PartitionIndex.java:303-329`。
- `KeyCacheSupport`：BigTable reader 支持 key cache 的接口；BTI reader class 不实现该支持，见 `src/java/org/apache/cassandra/io/sstable/keycache/KeyCacheSupport.java:34-96`。
- `StorageCompatibilityMode.validateSstableFormat()`：配置层限制 `CASSANDRA_4` compatibility 下不能选择 BTI，见 `src/java/org/apache/cassandra/utils/StorageCompatibilityMode.java:74-80`。

## 核心数据结构

- BigTable `Index.db`：partition key 到 data position/row-index entry 的 primary index；BigTable component type 定义见 `src/java/org/apache/cassandra/io/sstable/format/big/BigFormat.java:81-92`。
- BigTable `Summary.db`：primary index 的 sampled key/position summary；BigTable generated-on-load set 同时包含 `FILTER` 和 `SUMMARY`，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigFormat.java:100-106`。
- BTI `Partitions.db`：prefix-compressed trie，payload 可指向 `Rows.db` 或直接指向 data file，见 `src/java/org/apache/cassandra/io/sstable/format/bti/PartitionIndex.java:49-65`。
- BTI `Rows.db`：宽分区 row-index entry 文件；BTI writer 对 indexed partition 写入 key 和 `TrieIndexEntry`，见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableWriter.java:189-205`。
- Bloom `Filter.db`：两种 SSTable format 共用的 generated-on-load filter；是否使用 old serialization format 由 version flag 决定，见 `src/java/org/apache/cassandra/io/sstable/format/FilterComponent.java:53-80`。
- `CompactionParams.klass`：决定默认 Bloom false positive chance 的 compaction strategy class；LCS 特判为 `0.1`，其他策略为 `0.01`，见 `src/java/org/apache/cassandra/schema/CompactionParams.java:108-118` 和 `src/java/org/apache/cassandra/schema/CompactionParams.java:261-264`。

## 生命周期

写出路径：

```text
SortedTableWriter.Builder.addDefaultComponents()
  -> if shouldUseBloomFilter(table.bloom_filter_fp_chance)
     add Filter.db
BigTableWriter
  -> write Data.db + Index.db
  -> build/save Summary.db
BTI writer
  -> write Data.db + Partitions.db
  -> write Rows.db only for indexed partitions
  -> write Filter.db from shared AbstractIndexWriter
```

打开路径：

```text
FilterComponent.maybeLoadBloomFilter()
  -> fpChance ~= 1.0: AlwaysPresent
  -> missing/invalid/metadata missing: null, caller may rebuild
BigSSTableReaderLoadingBuilder
  -> load or rebuild Filter.db
  -> load or rebuild Summary.db
BtiTableReaderLoadingBuilder
  -> load or rebuild Filter.db
  -> open Rows.db and Partitions.db
  -> preload partition index when filter is not informative
```

版本迁移路径：

```text
Descriptor.version.hasOldBfFormat()
  -> Big ma/mb/mc/md/me: old Bloom filter serialization
  -> Big na/nb/oa and BTI da: new Bloom filter serialization
FilterComponent.load/save()
  -> BloomFilterSerializer.forVersion(oldFlag)
```

## 调用链

- BigTable point read：`BigTableReader.getPosition()` 先做 min/max 和 Bloom check，再查 key cache，然后用 index summary 定界 primary index scan，最后反序列化 `RowIndexEntry` 并按需写 key cache，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:240-346`。
- BigTable secondary-index key lookup：`keyAtPositionFromSecondaryIndex()` 从 primary index position 读取 key，并在能拿到 row-index entry 时写 key cache，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigTableReader.java:379-397`。
- BTI exact read：`BtiTableReader.getExactPosition()` 先检查 min/max 和 Bloom，再打开 `PartitionIndex.Reader`，通过 `exactCandidate()` 得到正/负 position，最后读取 `Rows.db` 或 `Data.db` 验证 key，见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java:223-282`。
- BTI range-like partition lookup：`getRowIndexEntry()` 对 `GT`/`GE` 使用 `PartitionIndex.Reader.ceiling()`，再通过 `retrieveEntryIfAcceptable()` 校验候选 entry，见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java:139-164` 和 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReader.java:176-209`。
- BigTable load rebuild：缺少 filter/summary 且需要 online rebuild 时，loading builder 扫描 `KeyReader`，同时构造 Bloom 和 summary 并保存 component，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigSSTableReaderLoadingBuilder.java:181-240`。
- BTI load rebuild：缺少 filter 且 partition/row index 存在时，loading builder 扫描 key reader 重建 Bloom；缺少 informative Bloom 时打开 partition index 使用 preload，见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReaderLoadingBuilder.java:139-173`。

## 配置项

| 配置项 | 默认/来源 | 影响 |
|---|---|---|
| `bloom_filter_fp_chance` | 未显式设置时来自 `CompactionParams.defaultBloomFilterFbChance()` | 决定 `Filter.db` 大小和 false positive 率；`1.0` 等价于不使用 informative Bloom，见 `src/java/org/apache/cassandra/schema/TableParams.java:95-101` |
| LCS 默认 Bloom FP chance | `0.1` | 降低 LCS 场景 Bloom 内存，见 `src/java/org/apache/cassandra/schema/CompactionParams.java:261-264` |
| STCS/TWCS/UCS 默认 Bloom FP chance | `0.01` | 非 LCS strategy 的默认值，见 `src/java/org/apache/cassandra/schema/CompactionParams.java:36-39` 和 `src/java/org/apache/cassandra/schema/CompactionParams.java:261-264` |
| `sstable.selected_format` | `big` | 选择新写 SSTable 的 format；YAML 注释说明 Cassandra 5.0 支持 `bti`，见 `conf/cassandra.yaml:1164-1172` 和 `src/java/org/apache/cassandra/config/Config.java:371-377` |
| `storage_compatibility_mode` | `CASSANDRA_4` | `CASSANDRA_4` 禁止选择 BTI；`UPGRADING`/`NONE` 允许，见 `conf/cassandra.yaml:2308-2320` 和 `src/java/org/apache/cassandra/utils/StorageCompatibilityMode.java:29-80` |
| `automatic_sstable_upgrade` | `false` | 升级后可自动重写 oldest non-upgraded SSTable，但不改变 `Filter.db` 旧格式读取逻辑本身，见 `conf/cassandra.yaml:1885-1889` 和 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4451-4481` |

## Metrics

- 两种 format 的 reader 都继承 `SSTableReaderWithFilter`，true positive、true negative、false positive 统计由 `notifySelected()`/`notifySkipped()` 更新，见 `src/java/org/apache/cassandra/io/sstable/format/SSTableReaderWithFilter.java:77-109`。
- BigTable format-specific metrics provider 包含 BloomFilter、IndexSummary 和 KeyCache metrics；BTI format-specific metrics provider 只暴露 BloomFilter metrics，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigFormat.java:528-540` 和 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiFormat.java:422-430`。
- `SSTableReaderTest.testGetPositionsBloomFilterStats()` 覆盖 Bloom true/false positive 和 `GT`/`GE` 不更新 Bloom 计数的行为，见 `test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java:637-694`。

## 日志

- `FilterComponent.maybeLoadBloomFilter()` 对 missing/invalid filter 记录 trace/info，调用方可选择 rebuild 或退化为 `AlwaysPresent`，见 `src/java/org/apache/cassandra/io/sstable/format/FilterComponent.java:99-138`。
- `BtiTableReaderLoadingBuilder.openPartitionIndex()` 捕获 partition index 打开失败后记录 debug，并将异常包装为 corruption path，见 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReaderLoadingBuilder.java:175-185`。
- BigTable 删除 SSTable 时会记录 SSTable/component 删除日志，并可在删除前清理对应 key-cache entries；实现入口见 `src/java/org/apache/cassandra/io/sstable/format/big/BigFormat.java:231-263`。
- `DatabaseDescriptor.setAutomaticSSTableUpgradeEnabled()` 和 `setMaxConcurrentAutoUpgradeTasks()` 在运行时变更 auto upgrade 配置时记录 debug/warn，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:4456-4481`。

## 运维关注点

- BigTable 缺 `Summary.db` 可以在线重建，但会扫描 primary index；BTI 不存在 summary 组件，缺的是 `Partitions.db`/`Rows.db` 这类主索引组件时不应按 generated-on-load 处理。
- `Filter.db` 缺失在 online open 中可重建；offline/no-validation open 更倾向于不重建并退化为 non-informative filter，测试覆盖见 `test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java:876-980` 和 `test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java:982-1068`。
- 如果把 `bloom_filter_fp_chance` 调成 `1.0`，BigTable 会更多依赖 summary/index scan，BTI 会更多依赖 partition index lookup，并可能 preload partition index；这适合 miss 很少或内存压力优先的表。
- 在 `storage_compatibility_mode: CASSANDRA_4` 下选择 `bti` 会配置失败；升级窗口若需要写 BTI，必须进入 `UPGRADING` 或 `NONE`，并确认回滚语义。
- legacy BigTable SSTable 的 old Bloom filter format 可读取，但 zero-copy streaming/loader 场景可能因为 legacy old BF format 禁用整表零拷贝路径，测试注释见 `test/unit/org/apache/cassandra/io/sstable/SSTableLoaderLegacyTest.java:99-104`。

## 性能瓶颈

- BigTable false positive 之后需要 index summary 二分、primary index scan 和 row-index entry 反序列化；summary 下采样或 index interval 过大都会扩大 scan 范围。
- BigTable key cache 对热点 point read 有明显收益，但 BTI 没有 key cache；BTI 依赖 trie index 结构降低随机 primary-index scan 成本。
- BTI `exactCandidate()` 的 prefix/hash candidate 不是最终匹配，仍需读取 `Rows.db` 或 `Data.db` key 验证；不存在 key 但 Bloom false positive 时仍有随机读成本。
- BTI 在 no-informative Bloom 场景 preload partition index 可减少后续随机页面读取，但会提高 open-time 内存和启动成本。
- Bloom FP chance 从 `0.01` 放宽到 `0.1` 可减少 Bloom 内存，但 miss-heavy workload 会放大 false positive read amplification；LCS 默认就是这种取舍。

## 常见故障

- `Filter.db` 损坏或缺失：BigTable/BTI online open 可尝试重建；如果主索引组件也缺失，则无法安全重建，相关分支见 `src/java/org/apache/cassandra/io/sstable/format/big/BigSSTableReaderLoadingBuilder.java:80-153` 和 `src/java/org/apache/cassandra/io/sstable/format/bti/BtiTableReaderLoadingBuilder.java:87-148`。
- BigTable `Summary.db` 缺失：online open 可以只重建 summary；BTI 没有 summary，因此同类告警应先确认 format，再检查 `Partitions.db`/`Rows.db`。
- 选择 `bti` 但处于 `CASSANDRA_4` compatibility：`StorageCompatibilityMode.validateSstableFormat()` 抛 `ConfigurationException`，测试覆盖见 `test/unit/org/apache/cassandra/utils/StorageCompatibilityModeTest.java:31-56`。
- `bloom_filter_fp_chance` 非法或误设为 `1.0`：前者由 `TableParams.validate()` 拒绝，后者会创建 non-informative filter 并改变 miss path 成本，见 `src/java/org/apache/cassandra/schema/TableParams.java:160-166` 和 `src/java/org/apache/cassandra/io/sstable/format/SortedTableWriter.java:497-504`。
- legacy old BF format 加载异常：先确认 descriptor version 是否 Big `ma` 到 `me`，再看 `BloomFilterSerializer.forVersion(oldFlag)` 反序列化路径，见 `src/java/org/apache/cassandra/io/sstable/format/big/BigFormat.java:346-405` 和 `src/java/org/apache/cassandra/utils/BloomFilterSerializer.java:41-80`。

## 测试用例

- Bloom 序列化：`BloomFilterTest.testSerialize()` 同时覆盖 old/new Bloom filter serialization round trip，见 `test/unit/org/apache/cassandra/utils/BloomFilterTest.java:55-73`。
- Big/BTI lookup listener 和 Bloom metrics：`SSTableReaderTest` 覆盖 key cache 命中、Bloom true/false positive、Big/BTI skipped reason 差异，见 `test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java:600-634`、`test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java:637-694` 和 `test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java:697-785`。
- generated-on-load component：`SSTableWriterTransactionTest` 验证 in-progress 阶段只有 primary components，prepared 阶段出现 generated-on-load components，见 `test/unit/org/apache/cassandra/io/sstable/SSTableWriterTransactionTest.java:97-108`。
- reader open/rebuild：`SSTableReaderTest.checkOpenedBigTable()` 与 `checkOpenedBtiTable()` 覆盖 filter/summary 缺失、BFFP 改变和 index missing 分支，见 `test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java:876-980` 和 `test/unit/org/apache/cassandra/io/sstable/SSTableReaderTest.java:982-1068`。
- BTI preload：`LoadingBuilderTest` 验证 `bloom_filter_fp_chance = 1` 时 reopen 会 preload partition index，见 `test/unit/org/apache/cassandra/io/sstable/format/bti/LoadingBuilderTest.java:58-95`。
- format/config：`SSTableFormatTest` 覆盖 `sstable` YAML 解析、selected format 和未知/重复 format validation，见 `test/unit/org/apache/cassandra/io/sstable/SSTableFormatTest.java:188-275`；`StorageCompatibilityModeTest` 覆盖 BTI 与 compatibility mode 的矩阵，见 `test/unit/org/apache/cassandra/utils/StorageCompatibilityModeTest.java:31-56`。
- offline writer：`CQLSSTableWriterTest` 覆盖 Big 和 BTI 格式写出后可加载读取，见 `test/unit/org/apache/cassandra/io/sstable/CQLSSTableWriterTest.java:117-155`。
- verify/scrub：`VerifyTest` 和 `ScrubTest` 分别按 Big/BTI 选择不同 index component，见 `test/unit/org/apache/cassandra/io/sstable/VerifyTest.java:552-575` 和 `test/unit/org/apache/cassandra/io/sstable/ScrubTest.java:276-285`。

## 待继续

- 增加 mixed-version upgrade/downgrade distributed test，覆盖 `storage_compatibility_mode` 从 `CASSANDRA_4` 到 `UPGRADING`/`NONE` 后 Big/BTI 写入、streaming 和 rollback 风险。
- 增加 legacy old Bloom filter fixture 的 loader/streaming 专项测试，明确 old BF format、zero-copy streaming fallback 和 automatic SSTable upgrade 的组合行为。
