#!/usr/bin/env python3
#
# Source-only drift check for materialized view build/status research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

MATRIX_DOC = "research/module-materialized-view-build-status-matrix.md"
CHECKER_DOC = "research/module-materialized-view-build-status-drift-checker.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"
FLOW_DOC = "research/flow-materialized-view.md"

SCENARIO_IDS = (
    "mv_build_schema_reload_gate",
    "mv_build_local_built_status_contract",
    "mv_build_distributed_status_contract",
    "mv_build_range_checkpoint_resume_contract",
    "mv_build_task_mutation_replay_contract",
    "mv_build_executor_compaction_info_contract",
    "mv_build_stop_retry_contract",
    "mv_build_nodetool_status_contract",
    "mv_build_concurrency_config_contract",
    "mv_build_bootstrap_mark_built_contract",
    "mv_build_existing_tests_baseline",
    "mv_build_operator_cli_gap",
)

SOURCE_TOKEN_CHECKS = {
    "src/java/org/apache/cassandra/db/view/ViewManager.java": (
        "public void reload(boolean buildAllViews)",
        "if (!buildAllViews)",
        "if (!StorageService.instance.isInitialized())",
        "view.build();",
        "public void dropView(String name)",
        "view.stopBuild();",
        "SystemKeyspace.setViewRemoved(keyspace.getName(), view.name);",
        "SystemDistributedKeyspace.setViewRemoved(keyspace.getName(), view.name);",
    ),
    "src/java/org/apache/cassandra/db/view/View.java": (
        "public synchronized void build()",
        "builder = new ViewBuilder(baseCfs, this);",
        "builder.start();",
        "synchronized void stopBuild()",
        "builder.stop();",
    ),
    "src/java/org/apache/cassandra/db/view/ViewBuilder.java": (
        "class ViewBuilder",
        "private static final int NUM_TASKS = Runtime.getRuntime().availableProcessors() * 4;",
        "if (SystemKeyspace.isViewBuilt(ksName, view.name))",
        "SystemKeyspace.isViewStatusReplicated(ksName, view.name)",
        "SystemDistributedKeyspace.startViewBuild(ksName, view.name, localHostId);",
        "baseCfs.forceBlockingFlush(ColumnFamilyStore.FlushReason.VIEW_BUILD_STARTED);",
        "SystemKeyspace.getViewBuildStatus(ksName, view.name)",
        "StorageService.instance.getLocalReplicas(ksName)",
        "Replicas.temporaryAssertFull(replicatedRanges);",
        "r.subtractAll(builtRanges)",
        "r.subtractAll(pendingRanges.keySet())",
        "DatabaseDescriptor.getPartitioner()",
        "new ViewBuilderTask(baseCfs,",
        "CompactionManager.instance::submitViewBuilder",
        "FutureCombiner.allOf(futures)",
        "builtRanges.addAll(pendingRanges.keySet());",
        "ScheduledExecutors.nonPeriodicTasks.schedule(() -> loadStatusAndBuild(), 5, TimeUnit.MINUTES);",
        "SystemKeyspace.finishViewBuildStatus(ksName, view.name);",
        "SystemDistributedKeyspace.successfulViewBuild(ksName, view.name, localHostId);",
        "SystemKeyspace.setViewBuiltReplicated(ksName, view.name);",
        "ScheduledExecutors.nonPeriodicTasks.schedule(this::updateDistributed, 5, TimeUnit.MINUTES);",
        "tasks.forEach(task -> task.stop(isCompactionInterrupted));",
    ),
    "src/java/org/apache/cassandra/db/view/ViewBuilderTask.java": (
        "public class ViewBuilderTask extends CompactionInfo.Holder implements Callable<Long>",
        "private static final int ROWS_BETWEEN_CHECKPOINTS = 1000;",
        "view.getSelectStatement().internalReadForView(key, nowInSec)",
        "UnfilteredRowIterators.noRowsIterator(baseCfs.metadata(), key, Rows.EMPTY_STATIC_ROW, DeletionTime.LIVE, false)",
        "generateViewUpdates(Collections.singleton(view), data, empty, nowInSec, true)",
        "StorageProxy.mutateMV(key.getKey(), m, true, noBase, Dispatcher.RequestTime.forImmediateExecution())",
        "Gossiper.instance.waitForSchemaAgreement(10, TimeUnit.SECONDS, () -> this.isStopped)",
        "SSTableSet.CANONICAL",
        "new ReducingKeyIterator(sstables)",
        "range.contains(token) && (prevToken == null || token.compareTo(prevToken) > 0)",
        "SystemKeyspace.updateViewBuildStatus(ksName, view.name, range, token, keysBuilt);",
        "SystemKeyspace.updateViewBuildStatus(ksName, view.name, range, range.right, keysBuilt);",
        "OperationType.VIEW_BUILD",
        "return CompactionInfo.withoutSSTables(baseCfs.metadata(), OperationType.VIEW_BUILD",
        "throw new StoppedException(ksName, view.name, getCompactionInfo());",
    ),
    "src/java/org/apache/cassandra/db/SystemKeyspace.java": (
        "public static final String VIEW_BUILDS_IN_PROGRESS = \"view_builds_in_progress\";",
        "public static final String BUILT_VIEWS = \"built_views\";",
        "public static boolean isViewBuilt(String keyspaceName, String viewName)",
        "public static boolean isViewStatusReplicated(String keyspaceName, String viewName)",
        "public static void setViewBuilt(String keyspaceName, String viewName, boolean replicated)",
        "forceBlockingFlush(BUILT_VIEWS);",
        "public static void finishViewBuildStatus(String ksname, String viewName)",
        "setViewBuilt(ksname, viewName, false);",
        "DELETE FROM system.%s WHERE keyspace_name = ? AND view_name = ?",
        "public static void setViewBuiltReplicated(String ksname, String viewName)",
        "public static void updateViewBuildStatus(String ksname, String viewName, Range<Token> range, Token lastToken, long keysBuilt)",
        "public static Map<Range<Token>, Pair<Token, Long>> getViewBuildStatus(String ksname, String viewName)",
    ),
    "src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java": (
        "public static final String VIEW_BUILD_STATUS = \"view_build_status\";",
        "private static final TableMetadata ViewBuildStatus",
        "keyspace_name text,",
        "view_name text,",
        "host_id uuid,",
        "status text,",
        "PRIMARY KEY ((keyspace_name, view_name), host_id)",
        "tables = Tables.of(RepairHistory, ParentRepairHistory, ViewBuildStatus,",
        "public static void startViewBuild(String keyspace, String view, UUID hostId)",
        "BuildStatus.STARTED.toString()",
        "public static void successfulViewBuild(String keyspace, String view, UUID hostId)",
        "BuildStatus.SUCCESS.toString()",
        "public static Map<UUID, String> viewStatus(String keyspace, String view)",
        "public static void setViewRemoved(String keyspaceName, String viewName)",
        "private enum BuildStatus",
        "UNKNOWN, STARTED, SUCCESS",
    ),
    "src/java/org/apache/cassandra/db/compaction/CompactionManager.java": (
        "private final CompactionExecutor viewBuildExecutor = new ViewBuildExecutor();",
        "public Future<Long> submitViewBuilder(final ViewBuilderTask task)",
        "Future<Long> submitViewBuilder(final ViewBuilderTask task, ActiveCompactionsTracker activeCompactions)",
        "activeCompactions.beginCompaction(task);",
        "activeCompactions.finishCompaction(task);",
        "super(DatabaseDescriptor.getConcurrentViewBuilders(), \"ViewBuildExecutor\", Integer.MAX_VALUE);",
        "public void setConcurrentViewBuilders(int value)",
        "adjustCoreSize(viewBuildExecutor, value);",
    ),
    "src/java/org/apache/cassandra/config/Config.java": (
        "public volatile int concurrent_materialized_view_builders = 1;",
        "materialized_views_enabled",
    ),
    "src/java/org/apache/cassandra/config/DatabaseDescriptor.java": (
        "if (conf.concurrent_materialized_view_builders <= 0)",
        "concurrent_materialized_view_builders should be strictly greater than 0",
        "public static int getConcurrentViewBuilders()",
        "return conf.concurrent_materialized_view_builders;",
        "public static void setConcurrentViewBuilders(int value)",
        "conf.concurrent_materialized_view_builders = value;",
    ),
    "src/java/org/apache/cassandra/service/StorageService.java": (
        "public int getConcurrentViewBuilders()",
        "return DatabaseDescriptor.getConcurrentViewBuilders();",
        "public void setConcurrentViewBuilders(int value)",
        "Number of concurrent view builders should be greater than 0.",
        "CompactionManager.instance.setConcurrentViewBuilders(DatabaseDescriptor.getConcurrentViewBuilders());",
        "private void markViewsAsBuilt()",
        "SystemKeyspace.finishViewBuildStatus(view.keyspace(), view.name());",
        "public Map<String, String> getViewBuildStatuses(String keyspace, String view, boolean withPort)",
        "SystemDistributedKeyspace.viewStatus(keyspace, view)",
        "tokenMetadata.getEndpointToHostIdMapForReading()",
        "coreViewStatus.getOrDefault(hostId, \"UNKNOWN\")",
        "return Collections.unmodifiableMap(result);",
    ),
    "src/java/org/apache/cassandra/service/StorageServiceMBean.java": (
        "public Map<String, String> getViewBuildStatusesWithPort(String keyspace, String view);",
        "public int getConcurrentViewBuilders();",
        "public void setConcurrentViewBuilders(int value);",
    ),
    "src/java/org/apache/cassandra/tools/NodeTool.java": (
        "GetConcurrentViewBuilders.class",
        "SetConcurrentViewBuilders.class",
        "ViewBuildStatus.class",
    ),
    "src/java/org/apache/cassandra/tools/NodeProbe.java": (
        "public Map<String, String> getViewBuildStatuses(String keyspace, String view)",
        "return ssProxy.getViewBuildStatuses(keyspace, view);",
        "public void setConcurrentViewBuilders(int value)",
        "ssProxy.setConcurrentViewBuilders(value);",
        "public int getConcurrentViewBuilders()",
        "return ssProxy.getConcurrentViewBuilders();",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/ViewBuildStatus.java": (
        "@Command(name = \"viewbuildstatus\", description = \"Show progress of a materialized view build\")",
        "private final static String SUCCESS = \"SUCCESS\";",
        "viewbuildstatus requires keyspace and view name arguments",
        "Map<String, String> buildStatus = probe.getViewBuildStatuses(keyspace, view);",
        "builder.add(\"Host\", \"Info\");",
        "if (!status.getValue().equals(SUCCESS))",
        "System.exit(1);",
        "System.exit(0);",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/GetConcurrentViewBuilders.java": (
        "@Command(name = \"getconcurrentviewbuilders\", description = \"Get the number of concurrent view builders in the system\")",
        "probe.getConcurrentViewBuilders()",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/SetConcurrentViewBuilders.java": (
        "@Command(name = \"setconcurrentviewbuilders\", description = \"Set the number of concurrent view builders in the system\")",
        "concurrent_view_builders",
        "checkArgument(concurrentViewBuilders > 0",
        "probe.setConcurrentViewBuilders(concurrentViewBuilders);",
    ),
}

TEST_TOKEN_CHECKS = {
    "test/unit/org/apache/cassandra/cql3/CQLTester.java": (
        "protected void waitForViewBuild(String view)",
        "SystemKeyspace.isViewBuilt(keyspace(), view)",
    ),
    "test/unit/org/apache/cassandra/cql3/ViewTest.java": (
        "private void testViewBuilderResume(int concurrentViewBuilders) throws Throwable",
        "CompactionManager.instance.setConcurrentViewBuilders(concurrentViewBuilders);",
        "createViewAsync(\"CREATE MATERIALIZED VIEW %s AS SELECT * FROM %s",
        "waitForViewBuild(mv1);",
        "public void testViewBuilderResume() throws Throwable",
        "public void testTruncateWhileBuilding() throws Throwable",
        "targetClass = \"ViewBuilderTask\"",
        "targetMethod = \"buildKey\"",
        "assertFalse(SystemKeyspace.isViewBuilt(KEYSPACE, currentView()));",
        "assertTrue(SystemKeyspace.isViewBuilt(KEYSPACE, currentView()));",
        "Metrics.getThreadPoolMetrics(\"ViewBuildExecutor\")",
    ),
    "test/unit/org/apache/cassandra/db/view/ViewBuilderTaskTest.java": (
        "public class ViewBuilderTaskTest extends CQLTester",
        "public void testBuildRange() throws Throwable",
        "new ViewBuilderTask(cfs, view, range, lastToken, keysBuilt).call();",
        "assertEquals(expectedKeysBuilt, actualKeysBuilt);",
        "SELECT last_token, keys_built",
        "SystemKeyspace.VIEW_BUILDS_IN_PROGRESS",
    ),
    "test/unit/org/apache/cassandra/db/compaction/ActiveCompactionsTest.java": (
        "public void testViewBuildTracking() throws Throwable",
        "ViewBuilderTask vbt = new ViewBuilderTask",
        "CompactionManager.instance.submitViewBuilder(vbt, mockActiveCompactions).get();",
        "mockActiveCompactions.holder.getCompactionInfo().shouldStop",
    ),
}

DOC_TOKEN_CHECKS = {
    MATRIX_DOC: (
        "mv_build_schema_reload_gate",
        "mv_build_local_built_status_contract",
        "mv_build_distributed_status_contract",
        "mv_build_range_checkpoint_resume_contract",
        "mv_build_task_mutation_replay_contract",
        "mv_build_executor_compaction_info_contract",
        "mv_build_stop_retry_contract",
        "mv_build_nodetool_status_contract",
        "mv_build_concurrency_config_contract",
        "mv_build_bootstrap_mark_built_contract",
        "mv_build_existing_tests_baseline",
        "mv_build_operator_cli_gap",
        "ViewBuilderTaskTest",
        "ViewBuildStatus",
        "system.view_builds_in_progress",
        "system_distributed.view_build_status",
    ),
    CHECKER_DOC: (
        "check-materialized-view-build-status-drift.py",
        "mv_build_operator_cli_gap",
        "viewbuildstatus",
    ),
    README_DOC: (
        "module-materialized-view-build-status-matrix.md",
        "module-materialized-view-build-status-drift-checker.md",
        "check-materialized-view-build-status-drift.py",
        "80 个 research checker",
    ),
    SOURCE_MAP_DOC: (
        "Materialized view build/status drift",
        "module-materialized-view-build-status-matrix.md",
        "check-materialized-view-build-status-drift.py",
    ),
    FLOW_DOC: (
        "module-materialized-view-build-status-matrix.md",
        "ViewBuilder",
        "system_distributed.view_build_status",
    ),
}

CLI_TEST_PATTERNS = (
    re.compile(r"viewbuildstatus"),
    re.compile(r"getconcurrentviewbuilders"),
    re.compile(r"setconcurrentviewbuilders"),
    re.compile(r"ViewBuildStatus"),
    re.compile(r"GetConcurrentViewBuilders"),
    re.compile(r"SetConcurrentViewBuilders"),
)


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
        for token in tokens:
            checks.append(CheckResult(f"source token {token}", path, token in text))
    return checks


def test_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []
    for path, tokens in TEST_TOKEN_CHECKS.items():
        text = read(path)
        for token in tokens:
            checks.append(CheckResult(f"test token {token}", path, token in text))
    return checks


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def doc_checks() -> list[CheckResult]:
    matrix = read(MATRIX_DOC)
    checker = read(CHECKER_DOC)
    checks = [
        CheckResult(f"scenario documented {scenario}", f"{MATRIX_DOC} / {CHECKER_DOC}", documented(scenario, matrix + "\n" + checker))
        for scenario in SCENARIO_IDS
    ]
    for path, tokens in DOC_TOKEN_CHECKS.items():
        text = read(path)
        checks.extend(CheckResult(f"doc token {token}", path, token in text) for token in tokens)
    return checks


def cli_gap_checks() -> list[CheckResult]:
    candidates: list[str] = []
    for root in ("test/unit", "test/distributed", "test/long"):
        for path in (REPO_ROOT / root).rglob("*.java"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(pattern.search(text) for pattern in CLI_TEST_PATTERNS):
                candidates.append(str(path.relative_to(REPO_ROOT)))

    return [
        CheckResult("mv_build_operator_cli_gap still open", "test/**/*.java", not candidates, ", ".join(candidates)),
    ]


def check() -> tuple[dict[str, object], bool]:
    sources = source_checks()
    tests = test_checks()
    docs = doc_checks()
    gaps = cli_gap_checks()
    result = {
        "scenario_ids": list(SCENARIO_IDS),
        "source_checks": [entry.__dict__ for entry in sources],
        "test_checks": [entry.__dict__ for entry in tests],
        "doc_checks": [entry.__dict__ for entry in docs],
        "gap_checks": [entry.__dict__ for entry in gaps],
    }
    ok = all(entry.ok for group in (sources, tests, docs, gaps) for entry in group)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check materialized view build/status source/test/doc coverage.")
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
        for group_name in ("source_checks", "test_checks", "doc_checks", "gap_checks"):
            for entry in result[group_name]:
                if not entry["ok"]:
                    detail = f" ({entry['detail']})" if entry.get("detail") else ""
                    print(f"{group_name}: {entry['source']}: failed {entry['name']}{detail}")
        if ok:
            print(f"OK materialized view build status checks passed ({len(result['scenario_ids'])} scenarios)")
        else:
            print("Materialized view build status checks failed.", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
