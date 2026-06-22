#!/usr/bin/env python3
#
# Source-only drift check for nodetool info observability research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

INFO = "src/java/org/apache/cassandra/tools/nodetool/Info.java"
NODE_TOOL = "src/java/org/apache/cassandra/tools/NodeTool.java"
NODEPROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
STORAGE_SERVICE_MBEAN = "src/java/org/apache/cassandra/service/StorageServiceMBean.java"
STORAGE_SERVICE = "src/java/org/apache/cassandra/service/StorageService.java"
CACHE_SERVICE_MBEAN = "src/java/org/apache/cassandra/service/CacheServiceMBean.java"
CACHE_SERVICE = "src/java/org/apache/cassandra/service/CacheService.java"
CACHE_METRICS = "src/java/org/apache/cassandra/metrics/CacheMetrics.java"
CHUNK_CACHE_METRICS = "src/java/org/apache/cassandra/metrics/ChunkCacheMetrics.java"
BUFFER_POOL_METRICS = "src/java/org/apache/cassandra/metrics/BufferPoolMetrics.java"

NODETOOL_TEST = "test/distributed/org/apache/cassandra/distributed/test/NodeToolTest.java"
JMX_GETTER_CHECK_TEST = "test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java"
BUFFER_POOL_METRICS_TEST = "test/unit/org/apache/cassandra/metrics/BufferPoolMetricsTest.java"

MATRIX_DOC = "research/module-nodetool-info-observability-matrix.md"
CHECKER_DOC = "research/module-nodetool-info-drift-checker.md"
OPERATIONS_DOC = "research/module-operations-observability.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

SCENARIO_IDS = (
    "nodetool_info_command_surface_contract",
    "nodetool_info_identity_liveness_contract",
    "nodetool_info_jvm_memory_contract",
    "nodetool_info_topology_exception_contract",
    "nodetool_info_cache_contract",
    "nodetool_info_chunk_network_cache_contract",
    "nodetool_info_table_metric_contract",
    "nodetool_info_token_join_contract",
    "nodetool_info_bootstrap_decommission_contract",
    "nodetool_info_out_of_range_ops_contract",
    "nodetool_info_existing_test_baseline",
)

INFO_OUTPUT_LABELS = (
    "ID",
    "Gossip active",
    "Native Transport active",
    "Load",
    "Uncompressed load",
    "Generation No",
    "Uptime (seconds)",
    "Heap Memory (MB)",
    "Off Heap Memory (MB)",
    "Data Center",
    "Rack",
    "Exceptions",
    "Key Cache",
    "Row Cache",
    "Counter Cache",
    "Chunk Cache",
    "Network Cache",
    "Percent Repaired",
    "Token",
    "Bootstrap state",
    "Bootstrap failed",
    "Decommissioning",
    "Decommission failed",
    "Invalid Token Ops",
)

SOURCE_TOKEN_CHECKS = {
    INFO: (
        '@Command(name = "info", description = "Print node information (uptime, load, ...)")',
        '@Option(name = {"-T", "--tokens"}, description = "Display all tokens")',
        '@Option(name = {"-O", "--out-of-range-ops"}, description = "Display per-keyspace counts of operations for invalid tokens")',
        "boolean gossipInitialized = probe.isGossipRunning();",
        'out.printf("%-23s: %s%n", "ID", probe.getLocalHostId());',
        'out.printf("%-23s: %s%n", "Gossip active", gossipInitialized);',
        'out.printf("%-23s: %s%n", "Native Transport active", probe.isNativeTransportRunning());',
        'out.printf("%-23s: %s%n", "Load", probe.getLoadString());',
        'out.printf("%-23s: %s%n", "Uncompressed load", probe.getUncompressedLoadString());',
        'out.printf("%-23s: %s%n", "Generation No", probe.getCurrentGenerationNumber());',
        'out.printf("%-23s: %s%n", "Generation No", 0);',
        "long secondsUp = probe.getUptime() / 1000;",
        "MemoryUsage heapUsage = probe.getHeapMemoryUsage();",
        "getOffHeapMemoryUsed(probe)",
        'out.printf("%-23s: %s%n", "Data Center", probe.getDataCenter());',
        'out.printf("%-23s: %s%n", "Rack", probe.getRack());',
        'out.printf("%-23s: %s%n", "Exceptions", probe.getStorageMetric("Exceptions"));',
        "CacheServiceMBean cacheService = probe.getCacheServiceMBean();",
        'probe.getCacheMetric("KeyCache", "Entries")',
        'probe.getCacheMetric("RowCache", "Entries")',
        'probe.getCacheMetric("CounterCache", "Entries")',
        'probe.getCacheMetric("ChunkCache", "MissLatencyUnit")',
        'probe.getBufferPoolMetric("networking", "OverflowSize")',
        'probe.getColumnFamilyMetric(null, null, "PercentRepaired")',
        "if (probe.isJoined())",
        "List<String> tokens = probe.getTokens();",
        'out.printf("%-23s: (node is not joined to the cluster)%n", "Token");',
        'probe.getStorageService().getBootstrapState()',
        'probe.getStorageService().isBootstrapFailed()',
        'probe.getStorageService().isDecommissioning()',
        'probe.getStorageService().isDecommissionFailed()',
        "Map<String, long[]> outOfRangeOpCounts = probe.getOutOfRangeOpCounts();",
        "counts[0]",
        "counts[1]",
        "counts[2]",
        'probe.getColumnFamilyMetric(keyspaceName, cfName, "MemtableOffHeapSize")',
        'probe.getColumnFamilyMetric(keyspaceName, cfName, "BloomFilterOffHeapMemoryUsed")',
        'probe.getColumnFamilyMetric(keyspaceName, cfName, "IndexSummaryOffHeapMemoryUsed")',
        'probe.getColumnFamilyMetric(keyspaceName, cfName, "CompressionMetadataOffHeapMemoryUsed")',
    ),
    NODE_TOOL: (
        "Info.class",
    ),
    NODEPROBE: (
        "public String getLocalHostId()",
        "return ssProxy.getLocalHostId();",
        "public String getLoadString()",
        "return ssProxy.getLoadString();",
        "public String getUncompressedLoadString()",
        "return ssProxy.getUncompressedLoadString();",
        "public int getCurrentGenerationNumber()",
        "return ssProxy.getCurrentGenerationNumber();",
        "public long getUptime()",
        "return runtimeProxy.getUptime();",
        "public MemoryUsage getHeapMemoryUsage()",
        "return memProxy.getHeapMemoryUsage();",
        "public boolean isJoined()",
        "return ssProxy.isJoined();",
        "public boolean isNativeTransportRunning()",
        "return ssProxy.isNativeTransportRunning();",
        "public boolean isGossipRunning()",
        "return ssProxy.isGossipRunning();",
        "public CacheServiceMBean getCacheServiceMBean()",
        "public Object getCacheMetric(String cacheType, String metricName)",
        '"org.apache.cassandra.metrics:type=Cache,scope=" + cacheType + ",name=" + metricName',
        "public Object getBufferPoolMetric(String poolType, String metricName)",
        '"org.apache.cassandra.metrics:type=BufferPool,scope=" + poolType + ",name=" + metricName',
        "public Object getColumnFamilyMetric(String ks, String cf, String metricName)",
        '"org.apache.cassandra.metrics:type=Table,name=%s"',
        "public long getStorageMetric(String metricName)",
        '"org.apache.cassandra.metrics:type=Storage,name=" + metricName',
        "public StorageServiceMBean getStorageService()",
        "return ssProxy;",
        "public Map<String,long[]> getOutOfRangeOpCounts()",
        "return ssProxy.getOutOfRangeOperationCounts();",
    ),
    STORAGE_SERVICE_MBEAN: (
        "public String getLocalHostId();",
        "public String getLoadString();",
        "public String getUncompressedLoadString();",
        "public int getCurrentGenerationNumber();",
        "public boolean isGossipRunning();",
        "public boolean isNativeTransportRunning();",
        "public boolean isJoined();",
        "public boolean isDecommissionFailed();",
        "public boolean isDecommissioning();",
        "public boolean isBootstrapFailed();",
        "public String getBootstrapState();",
        "Map<String, long[]> getOutOfRangeOperationCounts();",
    ),
    STORAGE_SERVICE: (
        "public boolean isJoined()",
        "tokenMetadata.isMember(FBUtilities.getBroadcastAddressAndPort()) && !isSurveyMode",
        "public String getLoadString()",
        "StorageMetrics.load.getCount()",
        "public String getUncompressedLoadString()",
        "StorageMetrics.uncompressedLoad.getCount()",
        "public int getCurrentGenerationNumber()",
        "Gossiper.instance.getCurrentGenerationNumber(FBUtilities.getBroadcastAddressAndPort())",
        "public String getBootstrapState()",
        "SystemKeyspace.getBootstrapState().name()",
        "public boolean isDecommissionFailed()",
        "operationMode == DECOMMISSION_FAILED",
        "public boolean isDecommissioning()",
        "isDecommissioning.get()",
        "public boolean isBootstrapFailed()",
        "operationMode == JOINING_FAILED",
        "public Map<String, long[]> getOutOfRangeOperationCounts()",
        "getOutOfRangeOperationCounts(Keyspace keyspace)",
        "incOutOfRangeOperationCount",
    ),
    CACHE_SERVICE_MBEAN: (
        "public int getRowCacheSavePeriodInSeconds();",
        "public int getKeyCacheSavePeriodInSeconds();",
        "public int getCounterCacheSavePeriodInSeconds();",
    ),
    CACHE_SERVICE: (
        "public int getRowCacheSavePeriodInSeconds()",
        "return DatabaseDescriptor.getRowCacheSavePeriod();",
        "public int getKeyCacheSavePeriodInSeconds()",
        "return DatabaseDescriptor.getKeyCacheSavePeriod();",
        "public int getCounterCacheSavePeriodInSeconds()",
        "return DatabaseDescriptor.getCounterCacheSavePeriod();",
    ),
    CACHE_METRICS: (
        'new DefaultNameFactory("Cache", type)',
        'factory.createMetricName("Capacity")',
        'factory.createMetricName("Size")',
        'factory.createMetricName("Entries")',
        'factory.createMetricName("Hits")',
        'factory.createMetricName("Misses")',
        'factory.createMetricName("Requests")',
        'factory.createMetricName("HitRate")',
    ),
    CHUNK_CACHE_METRICS: (
        "public class ChunkCacheMetrics extends CacheMetrics implements StatsCounter",
        'super("ChunkCache", cache);',
        'missLatency = Metrics.timer(factory.createMetricName("MissLatency"));',
    ),
    BUFFER_POOL_METRICS: (
        'MetricNameFactory factory = new DefaultNameFactory("BufferPool", scope);',
        'Metrics.register(factory.createMetricName("Size")',
        'Metrics.register(factory.createMetricName("OverflowSize")',
        'Metrics.register(factory.createMetricName("Capacity")',
    ),
    NODETOOL_TEST: (
        "public void testInfoOutput()",
        'cluster.get(1).nodetoolResult("info")',
        'stdoutContains("ID")',
        'stdoutContains("Gossip active")',
        'stdoutContains("Native Transport active")',
        'stdoutContains("Load")',
        'stdoutContains("Uncompressed load")',
        'stdoutContains("Generation")',
        'stdoutContains("Uptime")',
        'stdoutContains("Heap Memory")',
    ),
    JMX_GETTER_CHECK_TEST: (
        "testAllValidGetters(Cluster cluster)",
        "mbsc.getMBeanInfo(name)",
        "mbsc.getAttribute(name, a.getName())",
    ),
    BUFFER_POOL_METRICS_TEST: (
        "public class BufferPoolMetricsTest",
        "testMetricsOverflowSize",
        "testMetricsHits",
        "testMetricsMisses",
    ),
}

DOC_REQUIRED_TOKENS = (
    MATRIX_DOC,
    CHECKER_DOC,
    "check-nodetool-info-drift.py",
    INFO,
    NODE_TOOL,
    NODEPROBE,
    STORAGE_SERVICE_MBEAN,
    STORAGE_SERVICE,
    CACHE_SERVICE_MBEAN,
    CACHE_METRICS,
    CHUNK_CACHE_METRICS,
    BUFFER_POOL_METRICS,
    NODETOOL_TEST,
    JMX_GETTER_CHECK_TEST,
    BUFFER_POOL_METRICS_TEST,
    "nodetool info",
    "getOffHeapMemoryUsed",
    "PercentRepaired",
    "getOutOfRangeOperationCounts",
    "CacheServiceMBean",
    "BufferPool",
) + SCENARIO_IDS + INFO_OUTPUT_LABELS


@dataclass(frozen=True)
class CheckResult:
    name: str
    source: str
    ok: bool
    detail: str = ""


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def source_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []

    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        missing = [token for token in tokens if token not in text]
        checks.append(CheckResult(f"source token contract {path}", path, not missing, ", ".join(missing[:3])))

    info = read(INFO)
    checks.extend(
        [
            CheckResult("info output labels remain documented", INFO, all(f'"{label}"' in info for label in INFO_OUTPUT_LABELS)),
            CheckResult("info optional mbeans are guarded", INFO, info.count("InstanceNotFoundException") >= 3 and info.count("throw e;") >= 3),
            CheckResult("info token branch preserves vnode short output", INFO, "tokens.size() == 1 || this.tokens" in info and "-T/--tokens" in info),
            CheckResult("info out-of-range output is opt-in", INFO, "if (this.outOfRangeOps)" in info and "Invalid Token Ops" in info),
        ]
    )
    return checks


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def doc_checks() -> list[CheckResult]:
    matrix = read(MATRIX_DOC)
    checker = read(CHECKER_DOC)
    operations = read(OPERATIONS_DOC)
    readme = read(README_DOC)
    source_map = read(SOURCE_MAP_DOC)
    matrix_and_checker = matrix + "\n" + checker
    all_docs = "\n".join((matrix, checker, operations, readme, source_map))

    checks = [CheckResult(f"scenario documented {scenario}", f"{MATRIX_DOC} / {CHECKER_DOC}", documented(scenario, matrix_and_checker)) for scenario in SCENARIO_IDS]
    checks.extend(CheckResult(f"doc token {token}", "research docs", token in all_docs) for token in DOC_REQUIRED_TOKENS)
    checks.extend(
        [
            CheckResult("README references matrix", README_DOC, MATRIX_DOC.split("/", 1)[1] in readme),
            CheckResult("README references checker", README_DOC, CHECKER_DOC.split("/", 1)[1] in readme and "check-nodetool-info-drift.py" in readme),
            CheckResult("source-map references matrix", SOURCE_MAP_DOC, MATRIX_DOC in source_map),
            CheckResult("source-map references checker", SOURCE_MAP_DOC, "research/tools/check-nodetool-info-drift.py" in source_map),
            CheckResult("operations docs mention Info source", OPERATIONS_DOC, "Info.java" in operations and "getOffHeapMemoryUsed" in operations),
        ]
    )
    return checks


def check() -> tuple[dict[str, object], bool]:
    sources = source_checks()
    docs = doc_checks()
    result = {
        "scenario_ids": list(SCENARIO_IDS),
        "output_labels": list(INFO_OUTPUT_LABELS),
        "source_checks": [entry.__dict__ for entry in sources],
        "doc_checks": [entry.__dict__ for entry in docs],
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check nodetool info source/doc coverage.")
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
            print(f"OK nodetool info checks passed ({len(result['scenario_ids'])} scenarios)")
        else:
            print("Nodetool info checks failed.", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
