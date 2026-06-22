#!/usr/bin/env python3
#
# Source-only drift check for nodetool cache runtime research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

NODE_TOOL = "src/java/org/apache/cassandra/tools/NodeTool.java"
NODEPROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
INVALIDATE_KEY_CACHE = "src/java/org/apache/cassandra/tools/nodetool/InvalidateKeyCache.java"
INVALIDATE_ROW_CACHE = "src/java/org/apache/cassandra/tools/nodetool/InvalidateRowCache.java"
INVALIDATE_COUNTER_CACHE = "src/java/org/apache/cassandra/tools/nodetool/InvalidateCounterCache.java"
SET_CACHE_CAPACITY = "src/java/org/apache/cassandra/tools/nodetool/SetCacheCapacity.java"
SET_CACHE_KEYS_TO_SAVE = "src/java/org/apache/cassandra/tools/nodetool/SetCacheKeysToSave.java"
NODETOOL_INFO = "src/java/org/apache/cassandra/tools/nodetool/Info.java"
CACHE_SERVICE_MBEAN = "src/java/org/apache/cassandra/service/CacheServiceMBean.java"
CACHE_SERVICE = "src/java/org/apache/cassandra/service/CacheService.java"
AUTO_SAVING_CACHE = "src/java/org/apache/cassandra/cache/AutoSavingCache.java"
NOP_CACHE_PROVIDER = "src/java/org/apache/cassandra/cache/NopCacheProvider.java"
CACHES_TABLE = "src/java/org/apache/cassandra/db/virtual/CachesTable.java"
CACHE_METRICS = "src/java/org/apache/cassandra/metrics/CacheMetrics.java"

NODETOOL_TEST = "test/distributed/org/apache/cassandra/distributed/test/NodeToolTest.java"
AUTO_SAVING_CACHE_TEST = "test/unit/org/apache/cassandra/cache/AutoSavingCacheTest.java"
KEY_CACHE_TEST = "test/unit/org/apache/cassandra/io/sstable/keycache/KeyCacheTest.java"
COUNTER_CACHE_TEST = "test/unit/org/apache/cassandra/db/CounterCacheTest.java"
ROW_CACHE_TEST = "test/unit/org/apache/cassandra/db/RowCacheTest.java"
CACHE_METRICS_TEST = "test/unit/org/apache/cassandra/metrics/CacheMetricsTest.java"

MATRIX_DOC = "research/module-nodetool-cache-runtime-matrix.md"
CHECKER_DOC = "research/module-nodetool-cache-runtime-drift-checker.md"
CACHE_RUNTIME_DOC = "research/module-cache-runtime-persistence-matrix.md"
OPERATIONS_DOC = "research/module-operations-observability.md"
OBS_MAPPING_DOC = "research/module-observability-mapping.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

SCENARIO_IDS = (
    "nodetool_cache_command_registry_contract",
    "nodetool_cache_invalidation_command_contract",
    "nodetool_cache_capacity_command_contract",
    "nodetool_cache_keys_to_save_command_contract",
    "nodetool_cache_nodeprobe_mbean_route_contract",
    "cache_service_capacity_side_effect_contract",
    "cache_service_keys_schedule_contract",
    "cache_service_global_clear_contract",
    "cache_disabled_row_cache_failure_contract",
    "cache_info_and_virtual_table_observability_contract",
    "nodetool_cache_existing_test_baseline",
    "nodetool_cache_operator_gap",
)

SOURCE_TOKEN_CHECKS = {
    NODE_TOOL: (
        "InvalidateCounterCache.class",
        "InvalidateKeyCache.class",
        "InvalidateRowCache.class",
        "SetCacheCapacity.class",
        "SetCacheKeysToSave.class",
    ),
    INVALIDATE_KEY_CACHE: (
        '@Command(name = "invalidatekeycache", description = "Invalidate the key cache")',
        "public class InvalidateKeyCache extends NodeToolCmd",
        "public void execute(NodeProbe probe)",
        "probe.invalidateKeyCache();",
    ),
    INVALIDATE_ROW_CACHE: (
        '@Command(name = "invalidaterowcache", description = "Invalidate the row cache")',
        "public class InvalidateRowCache extends NodeToolCmd",
        "public void execute(NodeProbe probe)",
        "probe.invalidateRowCache();",
    ),
    INVALIDATE_COUNTER_CACHE: (
        '@Command(name = "invalidatecountercache", description = "Invalidate the counter cache")',
        "public class InvalidateCounterCache extends NodeToolCmd",
        "public void execute(NodeProbe probe)",
        "probe.invalidateCounterCache();",
    ),
    SET_CACHE_CAPACITY: (
        '@Command(name = "setcachecapacity", description = "Set global key, row, and counter cache capacities (in MB units)")',
        '@Arguments(title = "<key-cache-capacity> <row-cache-capacity> <counter-cache-capacity>"',
        "private List<Integer> args = new ArrayList<>();",
        'checkArgument(args.size() == 3, "setcachecapacity requires key-cache-capacity, row-cache-capacity, and counter-cache-capacity args.");',
        "probe.setCacheCapacities(args.get(0), args.get(1), args.get(2));",
    ),
    SET_CACHE_KEYS_TO_SAVE: (
        '@Command(name = "setcachekeystosave", description = "Set number of keys saved by each cache for faster post-restart warmup. 0 to disable")',
        '@Arguments(title = "<key-cache-keys-to-save> <row-cache-keys-to-save> <counter-cache-keys-to-save>"',
        "private List<Integer> args = new ArrayList<>();",
        'checkArgument(args.size() == 3, "setcachekeystosave requires key-cache-keys-to-save, row-cache-keys-to-save, and counter-cache-keys-to-save args.");',
        "probe.setCacheKeysToSave(args.get(0), args.get(1), args.get(2));",
    ),
    NODEPROBE: (
        "public void invalidateCounterCache()",
        "cacheService.invalidateCounterCache();",
        "public void invalidateKeyCache()",
        "cacheService.invalidateKeyCache();",
        "public void invalidateRowCache()",
        "cacheService.invalidateRowCache();",
        "public CacheServiceMBean getCacheServiceMBean()",
        'String cachePath = "org.apache.cassandra.db:type=Caches";',
        "JMX.newMBeanProxy(mbeanServerConn, new ObjectName(cachePath), CacheServiceMBean.class)",
        "public void setCacheCapacities(int keyCacheCapacity, int rowCacheCapacity, int counterCacheCapacity)",
        "cacheMBean.setKeyCacheCapacityInMB(keyCacheCapacity);",
        "cacheMBean.setRowCacheCapacityInMB(rowCacheCapacity);",
        "cacheMBean.setCounterCacheCapacityInMB(counterCacheCapacity);",
        "public void setCacheKeysToSave(int keyCacheKeysToSave, int rowCacheKeysToSave, int counterCacheKeysToSave)",
        "cacheMBean.setKeyCacheKeysToSave(keyCacheKeysToSave);",
        "cacheMBean.setRowCacheKeysToSave(rowCacheKeysToSave);",
        "cacheMBean.setCounterCacheKeysToSave(counterCacheKeysToSave);",
        "public Object getCacheMetric(String cacheType, String metricName)",
    ),
    CACHE_SERVICE_MBEAN: (
        "public int getRowCacheSavePeriodInSeconds();",
        "public int getKeyCacheKeysToSave();",
        "public void setCounterCacheKeysToSave(int cckts);",
        "public void invalidateKeyCache();",
        "public void invalidateRowCache();",
        "public void invalidateCounterCache();",
        "public void setRowCacheCapacityInMB(long capacity);",
        "public void setKeyCacheCapacityInMB(long capacity);",
        "public void setCounterCacheCapacityInMB(long capacity);",
    ),
    CACHE_SERVICE: (
        "public class CacheService implements CacheServiceMBean",
        'public static final String MBEAN_NAME = "org.apache.cassandra.db:type=Caches";',
        "KEY_CACHE(\"KeyCache\")",
        "ROW_CACHE(\"RowCache\")",
        "COUNTER_CACHE(\"CounterCache\");",
        "MBeanWrapper.instance.registerMBean(this, MBEAN_NAME);",
        "keyCache = initKeyCache();",
        "rowCache = initRowCache();",
        "counterCache = initCounterCache();",
        "public void setRowCacheKeysToSave(int count)",
        "DatabaseDescriptor.setRowCacheKeysToSave(count);",
        "rowCache.scheduleSaving(getRowCacheSavePeriodInSeconds(), count);",
        "public void setKeyCacheKeysToSave(int count)",
        "DatabaseDescriptor.setKeyCacheKeysToSave(count);",
        "keyCache.scheduleSaving(getKeyCacheSavePeriodInSeconds(), count);",
        "public void setCounterCacheKeysToSave(int count)",
        "DatabaseDescriptor.setCounterCacheKeysToSave(count);",
        "counterCache.scheduleSaving(getCounterCacheSavePeriodInSeconds(), count);",
        "public void invalidateKeyCache()",
        "keyCache.clear();",
        "public void invalidateRowCache()",
        "rowCache.clear();",
        "public void invalidateCounterCache()",
        "counterCache.clear();",
        "public void setRowCacheCapacityInMB(long capacity)",
        "rowCache.setCapacity(capacity * 1024 * 1024);",
        "public void setKeyCacheCapacityInMB(long capacity)",
        "keyCache.setCapacity(capacity * 1024 * 1024);",
        "public void setCounterCacheCapacityInMB(long capacity)",
        "counterCache.setCapacity(capacity * 1024 * 1024);",
    ),
    AUTO_SAVING_CACHE: (
        "public void scheduleSaving(int savePeriodInSeconds, final int keysToSave)",
        "saveTask.cancel(false); // Do not interrupt an in-progress save",
        "if (savePeriodInSeconds > 0)",
        "submitWrite(keysToSave);",
        "ScheduledExecutors.optionalTasks.scheduleWithFixedDelay(runnable,",
        "public Future<?> submitWrite(int keysToSave)",
        "return CompactionManager.instance.submitCacheWrite(getWriter(keysToSave));",
        "if (keysToSave >= size || keysToSave == 0)",
        "keyIterator = hotKeyIterator(keysToSave);",
    ),
    NOP_CACHE_PROVIDER: (
        "public class NopCacheProvider implements CacheProvider<RowCacheKey, IRowCacheEntry>",
        "public void setCapacity(long capacity)",
        "if (capacity != 0)",
        "is not permitted as this cache is disabled. Check your yaml settings if you want to enable it.",
    ),
    NODETOOL_INFO: (
        "CacheServiceMBean cacheService = probe.getCacheServiceMBean();",
        '"Key Cache"',
        'probe.getCacheMetric("KeyCache", "Entries")',
        "cacheService.getKeyCacheSavePeriodInSeconds()",
        '"Row Cache"',
        'probe.getCacheMetric("RowCache", "Entries")',
        "cacheService.getRowCacheSavePeriodInSeconds()",
        '"Counter Cache"',
        'probe.getCacheMetric("CounterCache", "Entries")',
        "cacheService.getCounterCacheSavePeriodInSeconds()",
        '"Chunk Cache"',
        'probe.getCacheMetric("ChunkCache", "MissLatency")',
    ),
    CACHES_TABLE: (
        'super(TableMetadata.builder(keyspace, "caches")',
        ".addPartitionKeyColumn(NAME, UTF8Type.instance)",
        ".addRegularColumn(CAPACITY_BYTES, LongType.instance)",
        ".addRegularColumn(REQUEST_COUNT, LongType.instance)",
        ".addRegularColumn(HIT_RATIO, DoubleType.instance)",
        "if (null != ChunkCache.instance)",
        'addRow(result, "chunks", ChunkCache.instance.metrics);',
        'addRow(result, "counters", CacheService.instance.counterCache.getMetrics());',
        'addRow(result, "keys", CacheService.instance.keyCache.getMetrics());',
        'addRow(result, "rows", CacheService.instance.rowCache.getMetrics());',
    ),
    CACHE_METRICS: (
        'factory = new DefaultNameFactory("Cache", type);',
        'factory.createMetricName("Capacity")',
        'factory.createMetricName("Size")',
        'factory.createMetricName("Entries")',
        'factory.createMetricName("Hits")',
        'factory.createMetricName("Misses")',
        'factory.createMetricName("Requests")',
        'factory.createMetricName("HitRate")',
    ),
    NODETOOL_TEST: (
        "public void testSetCacheCapacityWhenDisabled()",
        'withConfig(c->c.set("row_cache_size", "0MiB")).start()',
        'cluster.get(1).nodetoolResult("setcachecapacity", "1", "1", "1")',
        'stderrContains("is not permitted as this cache is disabled")',
    ),
    AUTO_SAVING_CACHE_TEST: (
        "public class AutoSavingCacheTest",
        "testSerializeAndLoadKeyCache",
    ),
    KEY_CACHE_TEST: (
        "public class KeyCacheTest",
        "testKeyCacheLoad",
    ),
    COUNTER_CACHE_TEST: (
        "public class CounterCacheTest",
        "testCounterCacheInvalidate",
        "testSaveLoad",
    ),
    ROW_CACHE_TEST: (
        "public class RowCacheTest",
        "testRowCacheDisabled",
    ),
    CACHE_METRICS_TEST: (
        "public class CacheMetricsTest",
        "testCacheMetrics",
    ),
}

DOC_REQUIRED_TOKENS = (
    MATRIX_DOC,
    CHECKER_DOC,
    CACHE_RUNTIME_DOC,
    "research/tools/check-nodetool-cache-runtime-drift.py",
    NODE_TOOL,
    NODEPROBE,
    INVALIDATE_KEY_CACHE,
    INVALIDATE_ROW_CACHE,
    INVALIDATE_COUNTER_CACHE,
    SET_CACHE_CAPACITY,
    SET_CACHE_KEYS_TO_SAVE,
    CACHE_SERVICE_MBEAN,
    CACHE_SERVICE,
    AUTO_SAVING_CACHE,
    NOP_CACHE_PROVIDER,
    CACHES_TABLE,
    CACHE_METRICS,
    NODETOOL_TEST,
    AUTO_SAVING_CACHE_TEST,
    KEY_CACHE_TEST,
    COUNTER_CACHE_TEST,
    ROW_CACHE_TEST,
    CACHE_METRICS_TEST,
    "nodetool setcachecapacity",
    "nodetool setcachekeystosave",
    "invalidatekeycache",
    "invalidaterowcache",
    "invalidatecountercache",
    "system_views.caches",
    "CacheServiceMBean",
    "AutoSavingCache.scheduleSaving",
    "NopCacheProvider",
    "nodetool_cache_operator_gap",
) + SCENARIO_IDS

GAP_TEST_TOKENS = (
    'nodetoolResult("setcachekeystosave"',
    'nodetoolResult("invalidatekeycache"',
    'nodetoolResult("invalidaterowcache"',
    'nodetoolResult("invalidatecountercache"',
    '"SELECT * FROM system_views.caches"',
    '"SELECT * FROM vts.caches"',
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    source: str
    ok: bool
    detail: str = ""


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def source_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.extend(CheckResult(f"source token {token}", path, token in text) for token in tokens)

    nodeprobe = read(NODEPROBE)
    cache_service = read(CACHE_SERVICE)
    auto_saving_cache = read(AUTO_SAVING_CACHE)
    node_tool = read(NODE_TOOL)

    checks.extend(
        [
            CheckResult(
                "NodeProbe cache capacity order",
                NODEPROBE,
                nodeprobe.index("cacheMBean.setKeyCacheCapacityInMB(keyCacheCapacity);")
                < nodeprobe.index("cacheMBean.setRowCacheCapacityInMB(rowCacheCapacity);")
                < nodeprobe.index("cacheMBean.setCounterCacheCapacityInMB(counterCacheCapacity);"),
            ),
            CheckResult(
                "NodeProbe cache keys-to-save order",
                NODEPROBE,
                nodeprobe.index("cacheMBean.setKeyCacheKeysToSave(keyCacheKeysToSave);")
                < nodeprobe.index("cacheMBean.setRowCacheKeysToSave(rowCacheKeysToSave);")
                < nodeprobe.index("cacheMBean.setCounterCacheKeysToSave(counterCacheKeysToSave);"),
            ),
            CheckResult(
                "NodeTool registry keeps cache commands in top-level list",
                NODE_TOOL,
                all(token in node_tool for token in ("InvalidateKeyCache.class", "InvalidateRowCache.class", "InvalidateCounterCache.class", "SetCacheCapacity.class", "SetCacheKeysToSave.class")),
            ),
            CheckResult(
                "keys-to-save updates schedule after DatabaseDescriptor",
                CACHE_SERVICE,
                cache_service.index("DatabaseDescriptor.setKeyCacheKeysToSave(count);") < cache_service.index("keyCache.scheduleSaving(getKeyCacheSavePeriodInSeconds(), count);")
                and cache_service.index("DatabaseDescriptor.setRowCacheKeysToSave(count);") < cache_service.index("rowCache.scheduleSaving(getRowCacheSavePeriodInSeconds(), count);")
                and cache_service.index("DatabaseDescriptor.setCounterCacheKeysToSave(count);") < cache_service.index("counterCache.scheduleSaving(getCounterCacheSavePeriodInSeconds(), count);"),
            ),
            CheckResult(
                "scheduleSaving cancels before reschedule",
                AUTO_SAVING_CACHE,
                auto_saving_cache.index("saveTask.cancel(false);") < auto_saving_cache.index("if (savePeriodInSeconds > 0)") < auto_saving_cache.index("ScheduledExecutors.optionalTasks.scheduleWithFixedDelay"),
            ),
        ]
    )

    test_corpus = "\n".join(read(path) for path in (NODETOOL_TEST, AUTO_SAVING_CACHE_TEST, KEY_CACHE_TEST, COUNTER_CACHE_TEST, ROW_CACHE_TEST, CACHE_METRICS_TEST))
    checks.extend(CheckResult(f"operator gap still open: {token}", "test sources", token not in test_corpus) for token in GAP_TEST_TOKENS)
    return checks


def doc_checks() -> list[CheckResult]:
    docs = {
        MATRIX_DOC: read(MATRIX_DOC),
        CHECKER_DOC: read(CHECKER_DOC),
        CACHE_RUNTIME_DOC: read(CACHE_RUNTIME_DOC),
        OPERATIONS_DOC: read(OPERATIONS_DOC),
        OBS_MAPPING_DOC: read(OBS_MAPPING_DOC),
        README_DOC: read(README_DOC),
        SOURCE_MAP_DOC: read(SOURCE_MAP_DOC),
    }
    matrix_and_checker = docs[MATRIX_DOC] + "\n" + docs[CHECKER_DOC]
    all_docs = "\n".join(docs.values())

    checks = [CheckResult(f"scenario documented {scenario}", f"{MATRIX_DOC} / {CHECKER_DOC}", documented(scenario, matrix_and_checker)) for scenario in SCENARIO_IDS]
    checks.extend(CheckResult(f"doc token {token}", "research docs", token in all_docs) for token in DOC_REQUIRED_TOKENS)
    checks.extend(
        [
            CheckResult("README references matrix", README_DOC, "module-nodetool-cache-runtime-matrix.md" in docs[README_DOC]),
            CheckResult("README references checker", README_DOC, "module-nodetool-cache-runtime-drift-checker.md" in docs[README_DOC] and "check-nodetool-cache-runtime-drift.py" in docs[README_DOC]),
            CheckResult("source-map references matrix", SOURCE_MAP_DOC, MATRIX_DOC in docs[SOURCE_MAP_DOC]),
            CheckResult("source-map references checker", SOURCE_MAP_DOC, "research/tools/check-nodetool-cache-runtime-drift.py" in docs[SOURCE_MAP_DOC]),
            CheckResult("operations doc references cache commands", OPERATIONS_DOC, all(token in docs[OPERATIONS_DOC] for token in ("setcachecapacity", "setcachekeystosave", "invalidatekeycache"))),
            CheckResult("observability mapping references cache runtime", OBS_MAPPING_DOC, all(token in docs[OBS_MAPPING_DOC] for token in ("system_views.caches", "CacheServiceMBean", "setcachekeystosave"))),
        ]
    )
    return checks


def check() -> tuple[dict[str, object], bool]:
    sources = source_checks()
    docs = doc_checks()
    result = {
        "scenario_ids": list(SCENARIO_IDS),
        "source_checks": [entry.__dict__ for entry in sources],
        "doc_checks": [entry.__dict__ for entry in docs],
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check nodetool cache runtime source/doc drift.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    try:
        result, ok = check()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        failed_sources = [entry for entry in result["source_checks"] if not entry["ok"]]
        failed_docs = [entry for entry in result["doc_checks"] if not entry["ok"]]
        if failed_sources:
            for entry in failed_sources:
                detail = f" ({entry['detail']})" if entry.get("detail") else ""
                print(f"source: {entry['source']}: failed {entry['name']}{detail}")
        if failed_docs:
            for entry in failed_docs:
                print(f"doc: {entry['source']}: missing {entry['name']}")
        if ok:
            print(f"OK nodetool cache runtime checks passed ({len(result['scenario_ids'])} scenarios)")
        else:
            print("Nodetool cache runtime checks failed.", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
