# Module: Cache Runtime Persistence Drift Checker

## 范围

`research/tools/check-cache-runtime-persistence-drift.py` 保护 `research/module-cache-runtime-persistence-matrix.md` 与当前源码、测试和索引的一致性。它聚焦 `CacheService` MBean 初始化、key/row/counter cache runtime controls、`AutoSavingCache` 保存/加载、cache serializers、row/counter read path、chunk cache、metrics/virtual table、nodetool/JMX surface 和 operator-facing test gaps。

## 设计目标

- 固定 `CacheService`、`CacheServiceMBean` 和 nodetool/NodeProbe 的 cache control plane。
- 固定 `AutoSavingCache` 的 saved cache 文件格式、schema/version guard、periodic scheduling、cache-write operation type 和 serializer lifecycle。
- 固定 key/row/counter/chunk cache 的 entry identity、read/write/invalidation 主路径和 metrics surface。
- 固定现有测试基线，并把 `cache_runtime_operator_gap` 明确留在文档中。
- 在不启动 Cassandra 的情况下发现 Cache runtime 源码或文档漂移。

## 解决的问题

- Cache 涉及启动配置、JMX/nodetool、SSTable read path、counter write path、virtual table 和 metrics；只看 `src/java/org/apache/cassandra/cache` 容易漏掉实际调用链。
- Row cache disabled 的 runtime capacity 行为来自 `NopCacheProvider`，不是 nodetool 参数校验；checker 把这个 contract 和 distributed test 绑定。
- AutoSavingCache 的落盘格式和 schema guard 对重启 warmup 很关键，源码重构后需要同步更新矩阵和索引。

## 设计取舍

- checker 使用文件存在性和精确字符串 token，不解析 Java AST；如果源码语义不变但 token 重构，需要同步更新 checker。
- checker 不运行 unit/dtest，只保护现有测试文件中的关键测试名和断言仍存在。
- 文档检查验证 scenario IDs、关键类/命令/测试名和 gap，不约束 Markdown 版式。
- negative scan 只看 `test/unit` 和 `test/distributed`：如果未来新增 cache CLI 或 `system_views.caches` 专项测试，会要求同步更新本矩阵。

## 场景 ID

- `cache_service_mbean_init_contract`
- `cache_config_autosize_directory_contract`
- `cache_autosaving_persistence_contract`
- `cache_save_load_serializer_contract`
- `cache_runtime_capacity_keys_contract`
- `cache_global_table_invalidation_contract`
- `key_cache_entry_identity_contract`
- `row_cache_read_write_invalidation_contract`
- `counter_cache_read_before_write_contract`
- `chunk_cache_file_cache_contract`
- `cache_metrics_virtual_table_contract`
- `cache_nodetool_jmx_surface_contract`
- `cache_existing_tests_baseline`
- `cache_runtime_operator_gap`

## 核心接口

- `check_source_tokens()`：验证 CacheService、AutoSavingCache、CacheKey、read/write path、metrics、virtual table、Config/DatabaseDescriptor 和 nodetool source tokens。
- `check_test_tokens()`：验证 AutoSavingCache、KeyCache、CounterCache、RowCache、CacheMetrics 和 NodeToolTest 的测试基线。
- `check_absent_test_tokens()`：验证当前仍缺 `setcachekeystosave`、三种 invalidate cache CLI 和 `system_views.caches` focused tests。
- `check_doc_tokens()`：验证矩阵、checker 说明、README 和 source-map 覆盖 scenario IDs、命令、测试名和 gap。
- `--json`：输出 source/test/doc/absent-gaps check 计数和失败项。

## 生命周期

```text
developer changes CacheService, AutoSavingCache, cache keys, row/counter read path, ChunkCache, CacheMetrics, CachesTable, nodetool cache commands, or cache tests
  -> run python3 research/tools/check-cache-runtime-persistence-drift.py
  -> checker validates source/test/doc tokens and explicit gaps
  -> source drift requires updating matrix + checker
  -> new focused test requires replacing matching gap text with covered scenario
```

## 运维关注点

- checker 只证明 research 与当前源码/测试同步，不证明 cache runtime 命令已经端到端覆盖。
- 如果新增 `system_views.caches`、`setcachekeystosave` 或 invalidate cache CLI 测试，应删除对应 negative scan token 并把测试加入 baseline。
- 适合与 Cache/Index/MV coverage、metrics registry、nodetool runbook、JMX compatibility 和 SSTable format drift checkers 一起运行。

## 命令

```bash
python3 research/tools/check-cache-runtime-persistence-drift.py
python3 research/tools/check-cache-runtime-persistence-drift.py --json
```
