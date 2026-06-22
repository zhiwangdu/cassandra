# Nodetool Cache Runtime Matrix

This matrix isolates the operator-facing cache commands from the broader cache runtime/persistence research. It covers `invalidatekeycache`, `invalidaterowcache`, `invalidatecountercache`, `setcachecapacity`, `setcachekeystosave`, the `CacheServiceMBean` route, `nodetool info` cache observability and the remaining CLI/virtual-table test gap.

## Source Contract

| Scenario | Contract | Source anchors | Operational meaning |
| --- | --- | --- | --- |
| `nodetool_cache_command_registry_contract` | `NodeTool` registers the three invalidate commands and the two cache mutation commands beside other top-level commands. | `src/java/org/apache/cassandra/tools/NodeTool.java:166`、`src/java/org/apache/cassandra/tools/NodeTool.java:170`、`src/java/org/apache/cassandra/tools/NodeTool.java:174`、`src/java/org/apache/cassandra/tools/NodeTool.java:206`、`src/java/org/apache/cassandra/tools/NodeTool.java:207` | Removing one class from the registry silently removes an operator control even if the implementation class still compiles. |
| `nodetool_cache_invalidation_command_contract` | `invalidatekeycache`, `invalidaterowcache` and `invalidatecountercache` are argument-free commands that call `NodeProbe.invalidateKeyCache()`, `invalidateRowCache()` and `invalidateCounterCache()`. | `src/java/org/apache/cassandra/tools/nodetool/InvalidateKeyCache.java:25`、`src/java/org/apache/cassandra/tools/nodetool/InvalidateKeyCache.java:29`、`src/java/org/apache/cassandra/tools/nodetool/InvalidateRowCache.java:58`、`src/java/org/apache/cassandra/tools/nodetool/InvalidateCounterCache.java:91` | These are global per-node clears, not table-scoped evictions. Table/range eviction stays in `ColumnFamilyStore` hooks. |
| `nodetool_cache_capacity_command_contract` | `setcachecapacity` requires exactly three integer args: key, row and counter cache capacity in MiB. It forwards them in that order to `NodeProbe.setCacheCapacities()`. | `src/java/org/apache/cassandra/tools/nodetool/SetCacheCapacity.java:129`、`src/java/org/apache/cassandra/tools/nodetool/SetCacheCapacity.java:132`、`src/java/org/apache/cassandra/tools/nodetool/SetCacheCapacity.java:141`、`src/java/org/apache/cassandra/tools/nodetool/SetCacheCapacity.java:142` | Argument ordering matters because each value targets a different underlying cache. |
| `nodetool_cache_keys_to_save_command_contract` | `setcachekeystosave` requires exactly three integer args and forwards key/row/counter keys-to-save values to `NodeProbe.setCacheKeysToSave()`. | `src/java/org/apache/cassandra/tools/nodetool/SetCacheKeysToSave.java:174`、`src/java/org/apache/cassandra/tools/nodetool/SetCacheKeysToSave.java:177`、`src/java/org/apache/cassandra/tools/nodetool/SetCacheKeysToSave.java:186`、`src/java/org/apache/cassandra/tools/nodetool/SetCacheKeysToSave.java:187` | `0` means save all keys, not disable saving; disabling periodic saves is controlled by the save period. |
| `nodetool_cache_nodeprobe_mbean_route_contract` | `NodeProbe` creates the `org.apache.cassandra.db:type=Caches` proxy, routes invalidations to `CacheServiceMBean.invalidate*Cache()`, capacity changes to `set*CacheCapacityInMB()` and keys-to-save changes to `set*CacheKeysToSave()`. | `src/java/org/apache/cassandra/tools/NodeProbe.java:593`、`src/java/org/apache/cassandra/tools/NodeProbe.java:618`、`src/java/org/apache/cassandra/tools/NodeProbe.java:688`、`src/java/org/apache/cassandra/tools/NodeProbe.java:777`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1088`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1096` | The commands fail with JMX/MBean access failures before reaching cache code if this ObjectName or proxy contract changes. |
| `cache_service_capacity_side_effect_contract` | `CacheService.set*CacheCapacityInMB()` rejects negative capacity and sets the underlying `AutoSavingCache` capacity in bytes. | `src/java/org/apache/cassandra/service/CacheServiceMBean.java:54`、`src/java/org/apache/cassandra/service/CacheService.java:325`、`src/java/org/apache/cassandra/service/CacheService.java:334`、`src/java/org/apache/cassandra/service/CacheService.java:342` | Capacity changes are runtime memory controls; they do not rewrite `cassandra.yaml`. |
| `cache_service_keys_schedule_contract` | `CacheService.set*CacheKeysToSave()` rejects negative counts, updates `DatabaseDescriptor`, then calls `AutoSavingCache.scheduleSaving(existingPeriod, count)`. `scheduleSaving()` cancels the previous periodic task and only reschedules when the period is positive. | `src/java/org/apache/cassandra/service/CacheService.java:240`、`src/java/org/apache/cassandra/service/CacheService.java:253`、`src/java/org/apache/cassandra/service/CacheService.java:266`、`src/java/org/apache/cassandra/cache/AutoSavingCache.java:158`、`src/java/org/apache/cassandra/cache/AutoSavingCache.java:160`、`src/java/org/apache/cassandra/cache/AutoSavingCache.java:165` | A keys-to-save change has immediate scheduler side effects, but a zero save period still leaves no periodic save task. |
| `cache_service_global_clear_contract` | `CacheService.invalidateKeyCache()`, `invalidateRowCache()` and `invalidateCounterCache()` directly call `clear()` on the three global caches. | `src/java/org/apache/cassandra/service/CacheService.java:274`、`src/java/org/apache/cassandra/service/CacheService.java:290`、`src/java/org/apache/cassandra/service/CacheService.java:317` | Use these as emergency or maintenance controls; they drop node-local warm state across all tables. |
| `cache_disabled_row_cache_failure_contract` | When row cache is disabled through `row_cache_size=0MiB`, the provider is `NopCacheProvider`; setting non-zero capacity throws the disabled-cache error covered by distributed `NodeToolTest`. | `src/java/org/apache/cassandra/service/CacheService.java:145`、`src/java/org/apache/cassandra/cache/NopCacheProvider.java:37`、`src/java/org/apache/cassandra/cache/NopCacheProvider.java:41`、`test/distributed/org/apache/cassandra/distributed/test/NodeToolTest.java:111` | `setcachecapacity` cannot enable row cache from a disabled provider; enable row cache in configuration before using runtime capacity changes. |
| `cache_info_and_virtual_table_observability_contract` | `nodetool info` prints Key/Row/Counter/Chunk cache metrics via `NodeProbe.getCacheMetric()` and `CacheServiceMBean.get*SavePeriodInSeconds()`; `system_views.caches` maps chunks/counters/keys/rows to `CacheMetrics` rows. | `src/java/org/apache/cassandra/tools/nodetool/Info.java:91`、`src/java/org/apache/cassandra/tools/nodetool/Info.java:94`、`src/java/org/apache/cassandra/tools/nodetool/Info.java:105`、`src/java/org/apache/cassandra/tools/nodetool/Info.java:116`、`src/java/org/apache/cassandra/tools/nodetool/Info.java:129`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1752`、`src/java/org/apache/cassandra/db/virtual/CachesTable.java:41`、`src/java/org/apache/cassandra/db/virtual/CachesTable.java:74` | Mutations and observability share the same CacheService/JMX surface, so operator runbooks should verify both command success and post-change metrics. |
| `nodetool_cache_existing_test_baseline` | Current tests cover disabled row-cache capacity failure, cache persistence/runtime primitives and basic cache metrics, but not direct CLI success for every cache command. | `test/distributed/org/apache/cassandra/distributed/test/NodeToolTest.java:111`、`test/unit/org/apache/cassandra/cache/AutoSavingCacheTest.java`、`test/unit/org/apache/cassandra/io/sstable/keycache/KeyCacheTest.java`、`test/unit/org/apache/cassandra/db/CounterCacheTest.java`、`test/unit/org/apache/cassandra/db/RowCacheTest.java`、`test/unit/org/apache/cassandra/metrics/CacheMetricsTest.java` | Existing tests prove core cache behavior and one nodetool failure mode; success-path operator controls are still source-only contracts. |
| `nodetool_cache_operator_gap` | Missing focused coverage remains for `setcachekeystosave` runtime reschedule, `invalidatekeycache` / `invalidaterowcache` / `invalidatecountercache` CLI success, `system_views.caches` row assertions and chunk cache invalidation. | `research/module-cache-runtime-persistence-matrix.md`、`research/tools/check-nodetool-cache-runtime-drift.py` | When these tests land, update this matrix and remove the negative gap scan from the checker. |

## Call Graph

```text
nodetool invalidatekeycache
  -> InvalidateKeyCache.execute(NodeProbe)
  -> NodeProbe.invalidateKeyCache()
  -> CacheServiceMBean.invalidateKeyCache()
  -> CacheService.invalidateKeyCache()
  -> keyCache.clear()

nodetool setcachecapacity <keyMiB> <rowMiB> <counterMiB>
  -> SetCacheCapacity.execute(NodeProbe)
  -> validate exactly 3 args
  -> NodeProbe.setCacheCapacities(key, row, counter)
  -> CacheServiceMBean.setKeyCacheCapacityInMB(key)
  -> CacheServiceMBean.setRowCacheCapacityInMB(row)
  -> CacheServiceMBean.setCounterCacheCapacityInMB(counter)
  -> AutoSavingCache.setCapacity(bytes)

nodetool setcachekeystosave <key> <row> <counter>
  -> SetCacheKeysToSave.execute(NodeProbe)
  -> validate exactly 3 args
  -> NodeProbe.setCacheKeysToSave(key, row, counter)
  -> CacheService.set*CacheKeysToSave(count)
  -> DatabaseDescriptor.set*CacheKeysToSave(count)
  -> AutoSavingCache.scheduleSaving(existingPeriod, count)
```

## Operational Notes

- These commands mutate only the contacted node; run them per node when changing a cluster-wide operating posture.
- `setcachecapacity` uses MiB arguments; `CacheService` converts them to bytes before updating the cache.
- `setcachekeystosave` adjusts future periodic saves and explicit `saveCaches()` behavior; it does not immediately write cache files.
- Disabled row cache is a provider choice, not just a zero capacity. A non-zero runtime capacity cannot swap `NopCacheProvider` into a real row cache implementation.
- `nodetool info` and `system_views.caches` are the quick post-change checks for capacity, entry count, requests and hit ratio.

## Tests And Gaps

- `NodeToolTest.testSetCacheCapacityWhenDisabled()` covers the row-cache disabled failure path.
- `AutoSavingCacheTest`, `KeyCacheTest`, `CounterCacheTest`, `RowCacheTest` and `CacheMetricsTest` cover persistence, clear/invalidate primitives and metric counters.
- Remaining gap: direct nodetool success tests for `setcachekeystosave`, `invalidatekeycache`, `invalidaterowcache`, `invalidatecountercache`, plus focused `system_views.caches` and chunk cache invalidation assertions.
