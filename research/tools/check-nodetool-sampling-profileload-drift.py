#!/usr/bin/env python3
#
# Source-only drift check for nodetool profileload/toppartitions sampling research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

PROFILE_LOAD = "src/java/org/apache/cassandra/tools/nodetool/ProfileLoad.java"
TOP_PARTITIONS = "src/java/org/apache/cassandra/tools/nodetool/TopPartitions.java"
NODE_TOOL = "src/java/org/apache/cassandra/tools/NodeTool.java"
NODEPROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
STORAGE_SERVICE_MBEAN = "src/java/org/apache/cassandra/service/StorageServiceMBean.java"
STORAGE_SERVICE = "src/java/org/apache/cassandra/service/StorageService.java"
SAMPLING_MANAGER = "src/java/org/apache/cassandra/metrics/SamplingManager.java"
SAMPLER = "src/java/org/apache/cassandra/metrics/Sampler.java"
FREQUENCY_SAMPLER = "src/java/org/apache/cassandra/metrics/FrequencySampler.java"
MAX_SAMPLER = "src/java/org/apache/cassandra/metrics/MaxSampler.java"
TABLE_METRICS = "src/java/org/apache/cassandra/metrics/TableMetrics.java"
CFS_MBEAN = "src/java/org/apache/cassandra/db/ColumnFamilyStoreMBean.java"
CFS = "src/java/org/apache/cassandra/db/ColumnFamilyStore.java"
SINGLE_PARTITION_READ = "src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java"
READ_COMMAND = "src/java/org/apache/cassandra/db/ReadCommand.java"
READ_EXECUTION_CONTROLLER = "src/java/org/apache/cassandra/db/ReadExecutionController.java"
STORAGE_PROXY = "src/java/org/apache/cassandra/service/StorageProxy.java"
PAXOS = "src/java/org/apache/cassandra/service/paxos/Paxos.java"

TOP_PARTITIONS_TEST = "test/unit/org/apache/cassandra/tools/TopPartitionsTest.java"
PROFILE_LOAD_TEST = "test/distributed/org/apache/cassandra/distributed/test/ProfileLoadTest.java"
FREQUENCY_SAMPLER_TEST = "test/unit/org/apache/cassandra/metrics/TopFrequencySamplerTest.java"
MAX_SAMPLER_TEST = "test/unit/org/apache/cassandra/metrics/MaxSamplerTest.java"
SAMPLER_TEST = "test/unit/org/apache/cassandra/metrics/SamplerTest.java"

MATRIX_DOC = "research/module-nodetool-sampling-profileload-matrix.md"
CHECKER_DOC = "research/module-nodetool-sampling-profileload-drift-checker.md"
OPERATIONS_DOC = "research/module-operations-observability.md"
OBS_MAPPING_DOC = "research/module-observability-mapping.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

SAMPLER_TYPES = (
    "READS",
    "WRITES",
    "LOCAL_READ_TIME",
    "READ_ROW_COUNT",
    "READ_TOMBSTONE_COUNT",
    "READ_SSTABLE_COUNT",
    "WRITE_SIZE",
    "CAS_CONTENTIONS",
)

SCENARIO_IDS = (
    "profileload_command_surface_contract",
    "profileload_argument_guard_contract",
    "profileload_sampler_selection_contract",
    "profileload_blocking_sample_contract",
    "profileload_scheduled_job_contract",
    "samplingmanager_overlap_contract",
    "samplingmanager_background_cycle_contract",
    "sampler_type_output_contract",
    "sampler_execution_model_contract",
    "tablemetrics_sampler_registration_contract",
    "sampling_update_sites_contract",
    "profileload_existing_test_baseline",
)

SOURCE_TOKEN_CHECKS = {
    PROFILE_LOAD: (
        '@Command(name = "profileload", description = "Low footprint profiling of activity for a period of time")',
        '@Arguments(usage = "<keyspace> <cfname> <duration>"',
        '@Option(name = "-s", description = "Capacity of the sampler',
        '@Option(name = "-k", description = "Number of the top samples to list',
        '@Option(name = "-a", description = "Comma separated list of samplers to use',
        '@Option(name = {"-i", "--interval"}',
        '@Option(name = {"-t", "--stop"}',
        '@Option(name = {"-l", "--list"}',
        "checkArgument(args.size() == 3 || args.size() == 2 || args.size() == 1 || args.size() == 0",
        "checkArgument(topCount > 0",
        "checkArgument(topCount < capacity",
        "checkArgument(capacity <= 1024",
        "durationMillis = Integer.parseInt(args.get(2));",
        "durationMillis = Integer.parseInt(args.get(0));",
        "keyspace = nullifyWildcard(keyspace);",
        "table = nullifyWildcard(table);",
        "checkArgument(durationMillis > 0",
        "checkArgument(!hasInterval() || intervalMillis >= durationMillis",
        "Set<String> available = Arrays.stream(SamplerType.values()).map(Enum::toString).collect(Collectors.toSet());",
        "checkArgument(available.contains(sampler)",
        "probe.handleScheduledSampling(keyspace, table, capacity, topCount, durationMillis, intervalMillis, targets, shouldStop);",
        "probe.getSampleTasks()",
        "probe.getPartitionSample(keyspace, capacity, durationMillis, topCount, targets);",
        "probe.getPartitionSample(keyspace, table, capacity, durationMillis, topCount, targets);",
        "SamplingManager.formatResult(rb)",
    ),
    TOP_PARTITIONS: (
        '@Command(name = "toppartitions", description = "Sample and print the most active partitions")',
        "@Deprecated(since = \"4.0\")",
        "public class TopPartitions extends ProfileLoad",
    ),
    NODE_TOOL: (
        "ProfileLoad.class",
        "TopPartitions.class",
    ),
    NODEPROBE: (
        "public boolean handleScheduledSampling(String ks,",
        "ssProxy.stopSamplingPartitions(ks, table)",
        "ssProxy.startSamplingPartitions(ks, table, durationMillis, intervalMillis, capacity, count, samplers)",
        "public List<String> getSampleTasks()",
        "return ssProxy.getSampleTasks();",
        "public Map<String, List<CompositeData>> getPartitionSample(String ks, int capacity, int durationMillis, int count, List<String> samplers)",
        "return ssProxy.samplePartitions(ks, durationMillis, capacity, count, samplers);",
        "public Map<String, List<CompositeData>> getPartitionSample(String ks, String cf, int capacity, int durationMillis, int count, List<String> samplers)",
        "cfsProxy.beginLocalSampling(sampler, capacity, durationMillis);",
        "Uninterruptibles.sleepUninterruptibly(durationMillis, TimeUnit.MILLISECONDS);",
        "result.put(sampler, cfsProxy.finishLocalSampling(sampler, count));",
    ),
    STORAGE_SERVICE_MBEAN: (
        "public Map<String, List<CompositeData>> samplePartitions(int duration, int capacity, int count, List<String> samplers) throws OpenDataException;",
        "public Map<String, List<CompositeData>> samplePartitions(String keyspace, int duration, int capacity, int count, List<String> samplers) throws OpenDataException;",
        "public boolean startSamplingPartitions(String ks, String table, int duration, int interval, int capacity, int count, List<String> samplers) throws OpenDataException;",
        "public boolean stopSamplingPartitions(String ks, String table) throws OpenDataException;",
        "public List<String> getSampleTasks();",
    ),
    STORAGE_SERVICE: (
        "private final SamplingManager samplingManager = new SamplingManager();",
        "public Map<String, List<CompositeData>> samplePartitions(int duration, int capacity, int count, List<String> samplers) throws OpenDataException",
        "public Map<String, List<CompositeData>> samplePartitions(String keyspace, int durationMillis, int capacity, int count,",
        "Iterable<ColumnFamilyStore> tables = SamplingManager.getTables(keyspace, null);",
        "table.beginLocalSampling(sampler, capacity, durationMillis);",
        "Uninterruptibles.sleepUninterruptibly(durationMillis, MILLISECONDS);",
        "topk.addAll(table.finishLocalSampling(sampler, count));",
        'return Long.compare((long) right.get("count"), (long) left.get("count"));',
        "public boolean startSamplingPartitions(String ks, String table, int duration, int interval, int capacity, int count, List<String> samplers)",
        "Preconditions.checkArgument(duration > 0",
        "Preconditions.checkArgument(interval <= 0 || interval >= duration",
        "Preconditions.checkArgument(capacity > 0 && capacity <= 1024",
        "Preconditions.checkArgument(count > 0 && count < capacity",
        "return samplingManager.register(ks, table, duration, interval, capacity, count, samplers);",
        "return samplingManager.unregister(ks, table);",
        "return samplingManager.allJobs();",
    ),
    SAMPLING_MANAGER: (
        "private final ConcurrentHashMap<JobId, Future<?>> activeSamplingTasks = new ConcurrentHashMap<>();",
        "private final Set<JobId> cancelingTasks = ConcurrentHashMap.newKeySet();",
        "public static String formatResult(ResultBuilder resultBuilder)",
        "for (Sampler.SamplerType samplerType : Sampler.SamplerType.values())",
        "public static Iterable<ColumnFamilyStore> getTables(String ks, String table)",
        "return ColumnFamilyStore.all();",
        "return keyspace.getColumnFamilyStores();",
        "return Collections.singletonList(keyspace.getColumnFamilyStore(table));",
        "public boolean register(String ks, String table, int duration, int interval, int capacity, int count, List<String> samplers)",
        "if (!canSchedule(jobId))",
        "activeSamplingTasks.put(jobId, ScheduledExecutors.optionalTasks.submit(",
        "public boolean unregister(String ks, String table)",
        "public List<String> allJobs()",
        "private boolean canSchedule(JobId jobId)",
        "allJobIds.contains(JobId.ALL_KS_AND_TABLES)",
        "allJobIds.contains(jobId)",
        "allJobIds.contains(JobId.createForAllTables(jobId.keyspace))",
        "private Runnable createSamplingBeginRunnable",
        "cfs.beginLocalSampling(sampler, capacity, duration);",
        "ScheduledExecutors.optionalTasks.schedule(",
        "private Runnable createSamplingEndRunnable",
        "topk.addAll(cfs.finishLocalSampling(sampler, count));",
        "logger.info(formatResult(rb));",
        "if (!cancelingTasks.contains(jobId))",
        "createSamplingBeginRunnable(jobId, tables, duration, interval, capacity, count, samplers)",
        "activeSamplingTasks.remove(jobId);",
        "public static final JobId ALL_KS_AND_TABLES = new JobId(null, null);",
        'return input == null ? "*" : input;',
        "ps.println(description + ':');",
        'ps.println("   Nothing recorded during sampling period...");',
    ),
    SAMPLER: (
        "READS(\"Frequency of reads by partition\"",
        "WRITES(\"Frequency of writes by partition\"",
        "LOCAL_READ_TIME(\"Longest read query times\"",
        "READ_ROW_COUNT(\"Partitions read with the most rows\"",
        "READ_TOMBSTONE_COUNT(\"Partitions read with the most tombstones\"",
        "READ_SSTABLE_COUNT(\"Partitions read with the most sstables\"",
        "WRITE_SIZE(\"Max mutation size by partition\"",
        "CAS_CONTENTIONS(\"Frequency of CAS contention by partition\"",
        "public static final ExecutorPlus samplerExecutor",
        "configureSequential(\"Sampler\")",
        "withQueueLimit(1000)",
        "recordSelfDroppedMessage(Verb._SAMPLE)",
        "public void addSample(final T item, final int value)",
        "samplerExecutor.submit(() -> insert(item, value));",
    ),
    FREQUENCY_SAMPLER: (
        "public abstract class FrequencySampler<T> extends Sampler<T>",
        "private StreamSummary<T> summary;",
        "public synchronized void beginSampling(int capacity, long durationMillis)",
        "if (isActive())",
        "summary = new StreamSummary<>(capacity);",
        "public synchronized List<Sample<T>> finishSampling(int count)",
        "summary.topK(count)",
        "new Sample<>(c.getItem(), c.getCount(), c.getError())",
        "summary.offer(item, (int) Math.min(value, Integer.MAX_VALUE));",
    ),
    MAX_SAMPLER: (
        "public abstract class MaxSampler<T> extends Sampler<T>",
        "private MinMaxPriorityQueue<Sample<T>> queue;",
        "public synchronized void beginSampling(int capacity, long durationMillis)",
        "maximumSize(Math.max(1, capacity))",
        "public synchronized List<Sample<T>> finishSampling(int count)",
        "while ((next = queue.poll()) != null && result.size() <= count)",
        "queue.add(new Sample<T>(item, value, 0));",
        "return value > 0 && (queue.isEmpty() || queue.size() < capacity || queue.peekLast().count < value);",
    ),
    TABLE_METRICS: (
        "public final Sampler<ByteBuffer> topReadPartitionFrequency;",
        "public final Sampler<ByteBuffer> topWritePartitionFrequency;",
        "public final Sampler<ByteBuffer> topWritePartitionSize;",
        "public final Sampler<ByteBuffer> topCasPartitionContention;",
        "public final Sampler<String> topLocalReadQueryTime;",
        "public final Sampler<ByteBuffer> topReadPartitionRowCount;",
        "public final Sampler<ByteBuffer> topReadPartitionTombstoneCount;",
        "public final Sampler<ByteBuffer> topReadPartitionSSTableCount;",
        "samplers = new EnumMap<>(SamplerType.class);",
        "topReadPartitionFrequency = new FrequencySampler<ByteBuffer>()",
        "topLocalReadQueryTime = new MaxSampler<String>()",
        "topReadPartitionSSTableCount = new MaxSampler<ByteBuffer>()",
        "samplers.put(SamplerType.READS, topReadPartitionFrequency);",
        "samplers.put(SamplerType.WRITES, topWritePartitionFrequency);",
        "samplers.put(SamplerType.WRITE_SIZE, topWritePartitionSize);",
        "samplers.put(SamplerType.CAS_CONTENTIONS, topCasPartitionContention);",
        "samplers.put(SamplerType.LOCAL_READ_TIME, topLocalReadQueryTime);",
        "samplers.put(SamplerType.READ_ROW_COUNT, topReadPartitionRowCount);",
        "samplers.put(SamplerType.READ_TOMBSTONE_COUNT, topReadPartitionTombstoneCount);",
        "samplers.put(SamplerType.READ_SSTABLE_COUNT, topReadPartitionSSTableCount);",
    ),
    CFS_MBEAN: (
        "public void beginLocalSampling(String sampler, int capacity, int durationMillis);",
        "public List<CompositeData> finishLocalSampling(String sampler, int count) throws OpenDataException;",
    ),
    CFS: (
        "metric.topWritePartitionFrequency.addSample(key.getKey(), 1);",
        "metric.topWritePartitionSize.addSample(key.getKey(), update.dataSize());",
        "public void beginLocalSampling(String sampler, int capacity, int durationMillis)",
        "metric.samplers.get(SamplerType.valueOf(sampler)).beginSampling(capacity, durationMillis);",
        "public List<CompositeData> finishLocalSampling(String sampler, int count) throws OpenDataException",
        "Sampler samplerImpl = metric.samplers.get(SamplerType.valueOf(sampler));",
        "List<Sample> samplerResults = samplerImpl.finishSampling(count);",
        "new Object[] {",
        "getKeyspaceName() + \".\" + name",
        "samplerImpl.toString(counter.value)",
    ),
    SINGLE_PARTITION_READ: (
        "metrics.topReadPartitionFrequency.addSample(key.getKey(), 1);",
        "metrics.topReadPartitionSSTableCount.addSample(key.getKey(), metricsCollector.getMergedSSTables());",
    ),
    READ_COMMAND: (
        "metric.topReadPartitionRowCount.addSample(currentKey.getKey(), lr);",
        "metric.topReadPartitionTombstoneCount.addSample(currentKey.getKey(), ts);",
    ),
    READ_EXECUTION_CONTROLLER: (
        "baseCfs.metric.topLocalReadQueryTime.isEnabled()",
        "cfs.metric.topLocalReadQueryTime.addSample(cql, timeMicros);",
    ),
    STORAGE_PROXY: (
        "topCasPartitionContention",
        ".addSample(key.getKey(), contentions);",
    ),
    PAXOS: (
        "openAndGetStore(metadata).metric.topCasPartitionContention.addSample(partitionKey.getKey(), failedAttemptsDueToContention);",
    ),
    TOP_PARTITIONS_TEST: (
        "Includes test cases for both the 'toppartitions' command and its successor 'profileload'",
        "public void testServiceTopPartitionsNoArg()",
        "StorageService.instance.samplePartitions(null, 1000, 100, 10, Lists.newArrayList(\"READS\", \"WRITES\"))",
        "public void testServiceTopPartitionsSingleTable()",
        "columnFamilyStore.beginLocalSampling(samplerName, 5, 240_000);",
        "columnFamilyStore.finishLocalSampling(samplerName, 5);",
        "public void testTopPartitionsRowTombstoneAndSSTableCount()",
        "cfs.beginLocalSampling(\"READ_ROW_COUNT\", count, 240000);",
        "cfs.beginLocalSampling(\"READ_TOMBSTONE_COUNT\", count, 240000);",
        "cfs.beginLocalSampling(\"READ_SSTABLE_COUNT\", count, 240000);",
        "public void testStartAndStopScheduledSampling()",
        "ss.startSamplingPartitions(null, null, 10, 10, 100, 10, allSamplers)",
        "assertEquals(Collections.singletonList(\"*.*\"), ss.getSampleTasks());",
        "ss.stopSamplingPartitions(null, null)",
    ),
    PROFILE_LOAD_TEST: (
        "public void testScheduledSamplingTaskLogs()",
        'nodetoolResult("profileload", "1000", "-i", "1000")',
        'nodetoolResult("profileload", "--list")',
        'grep("Frequency of (reads|writes|cas contentions) by partition")',
        'grep("Starting to sample tables")',
        'nodetoolResult("profileload", "--stop")',
        "public void testPreventDuplicatedSchedule()",
        'stdoutContains("Unable to schedule sampling for keyspace")',
        'stdoutContains("Unable to stop the non-existent scheduled sampling")',
    ),
    FREQUENCY_SAMPLER_TEST: (
        "public class TopFrequencySamplerTest extends SamplerTest",
        "this.sampler = new FrequencySampler<String>()",
    ),
    MAX_SAMPLER_TEST: (
        "public class MaxSamplerTest",
        "this.sampler = new MaxSampler<String>()",
    ),
    SAMPLER_TEST: (
        "public class SamplerTest",
        "waitSampler.addSample(\"TEST\", 1);",
        "public void testSamplerOutOfOrder()",
    ),
}

DOC_REQUIRED_TOKENS = (
    MATRIX_DOC,
    CHECKER_DOC,
    "check-nodetool-sampling-profileload-drift.py",
    PROFILE_LOAD,
    TOP_PARTITIONS,
    NODE_TOOL,
    NODEPROBE,
    STORAGE_SERVICE_MBEAN,
    STORAGE_SERVICE,
    SAMPLING_MANAGER,
    SAMPLER,
    FREQUENCY_SAMPLER,
    MAX_SAMPLER,
    TABLE_METRICS,
    CFS_MBEAN,
    CFS,
    SINGLE_PARTITION_READ,
    READ_COMMAND,
    READ_EXECUTION_CONTROLLER,
    STORAGE_PROXY,
    PAXOS,
    TOP_PARTITIONS_TEST,
    PROFILE_LOAD_TEST,
    FREQUENCY_SAMPLER_TEST,
    MAX_SAMPLER_TEST,
    SAMPLER_TEST,
    "profileload",
    "toppartitions",
    "SamplingManager",
    "SamplerType",
    "beginLocalSampling",
    "finishLocalSampling",
    "startSamplingPartitions",
    "getSampleTasks",
) + SCENARIO_IDS + SAMPLER_TYPES


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

    profile = read(PROFILE_LOAD)
    checks.append(
        CheckResult(
            "scheduled branch precedes list and blocking branches",
            PROFILE_LOAD,
            profile.index("if (hasInterval() || shouldStop)")
            < profile.index("else if (shouldList)")
            < profile.index("probe.getPartitionSample(keyspace, capacity, durationMillis, topCount, targets);"),
        )
    )

    storage_service = read(STORAGE_SERVICE)
    checks.append(
        CheckResult(
            "blocking StorageService sample starts before sleep and finish",
            STORAGE_SERVICE,
            storage_service.index("table.beginLocalSampling(sampler, capacity, durationMillis);")
            < storage_service.index("Uninterruptibles.sleepUninterruptibly(durationMillis, MILLISECONDS);")
            < storage_service.index("topk.addAll(table.finishLocalSampling(sampler, count));"),
        )
    )

    sampling_manager = read(SAMPLING_MANAGER)
    checks.append(
        CheckResult(
            "scheduled begin/end cycle order",
            SAMPLING_MANAGER,
            sampling_manager.index("private Runnable createSamplingBeginRunnable")
            < sampling_manager.index("cfs.beginLocalSampling(sampler, capacity, duration);")
            < sampling_manager.index("ScheduledExecutors.optionalTasks.schedule(")
            < sampling_manager.index("private Runnable createSamplingEndRunnable")
            < sampling_manager.index("topk.addAll(cfs.finishLocalSampling(sampler, count));"),
        )
    )

    table_metrics = read(TABLE_METRICS)
    checks.append(
        CheckResult(
            "all sampler types registered",
            TABLE_METRICS,
            all(f"samplers.put(SamplerType.{sampler}" in table_metrics for sampler in SAMPLER_TYPES),
        )
    )
    return checks


def doc_checks() -> list[CheckResult]:
    matrix = read(MATRIX_DOC)
    checker = read(CHECKER_DOC)
    operations = read(OPERATIONS_DOC)
    obs_mapping = read(OBS_MAPPING_DOC)
    readme = read(README_DOC)
    source_map = read(SOURCE_MAP_DOC)
    all_docs = "\n".join((matrix, checker, operations, obs_mapping, readme, source_map))
    matrix_and_checker = matrix + "\n" + checker

    checks = [
        CheckResult(f"scenario documented {scenario}", f"{MATRIX_DOC} / {CHECKER_DOC}", documented(scenario, matrix_and_checker))
        for scenario in SCENARIO_IDS
    ]
    checks.extend(CheckResult(f"doc token {token}", "research docs", token in all_docs) for token in DOC_REQUIRED_TOKENS)
    checks.extend(
        [
            CheckResult("README references matrix", README_DOC, MATRIX_DOC.split("/", 1)[1] in readme),
            CheckResult("README references checker", README_DOC, CHECKER_DOC.split("/", 1)[1] in readme and "check-nodetool-sampling-profileload-drift.py" in readme),
            CheckResult("source-map references matrix", SOURCE_MAP_DOC, MATRIX_DOC in source_map),
            CheckResult("source-map references checker", SOURCE_MAP_DOC, "research/tools/check-nodetool-sampling-profileload-drift.py" in source_map),
            CheckResult("operations doc mentions profileload", OPERATIONS_DOC, "profileload" in operations and "toppartitions" in operations),
            CheckResult("observability mapping mentions sampling", OBS_MAPPING_DOC, "profileload" in obs_mapping and "SamplingManager" in obs_mapping),
        ]
    )
    return checks


def check() -> tuple[dict[str, object], bool]:
    sources = source_checks()
    docs = doc_checks()
    result = {
        "scenario_ids": list(SCENARIO_IDS),
        "sampler_types": list(SAMPLER_TYPES),
        "source_files": sorted(SOURCE_TOKEN_CHECKS),
        "matrix_doc": MATRIX_DOC,
        "checker_doc": CHECKER_DOC,
        "source_checks": [entry.__dict__ for entry in sources],
        "doc_checks": [entry.__dict__ for entry in docs],
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check nodetool profileload/toppartitions source/doc coverage.")
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
            print(f"OK nodetool sampling/profileload checks passed ({len(result['scenario_ids'])} scenarios)")
        else:
            print("Nodetool sampling/profileload checks failed.", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
