#!/usr/bin/env python3
#
# Source-only drift check for materialized view paired-replica research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

MATRIX_DOC = "research/module-materialized-view-paired-replica-matrix.md"
CHECKER_DOC = "research/module-materialized-view-paired-replica-drift-checker.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"
FLOW_DOC = "research/flow-materialized-view.md"

SCENARIO_IDS = (
    "mv_pair_viewutils_cardinality_contract",
    "mv_pair_local_view_replica_preference",
    "mv_pair_local_dc_filter_contract",
    "mv_pair_shared_endpoint_filter_contract",
    "mv_pair_non_base_replica_empty_contract",
    "mv_pair_starting_batchlog_contract",
    "mv_pair_pending_endpoint_write_contract",
    "mv_pair_local_apply_fastpath_contract",
    "mv_pair_remote_stage_contract",
    "mv_pair_batchlog_metrics_contract",
    "mv_pair_existing_tests_baseline",
    "mv_pair_range_movement_distributed_gap",
)

SOURCE_TOKEN_CHECKS = {
    "src/java/org/apache/cassandra/db/view/ViewUtils.java": (
        "public static Optional<Replica> getViewNaturalEndpoint(AbstractReplicationStrategy replicationStrategy, Token baseToken, Token viewToken)",
        "DatabaseDescriptor.getEndpointSnitch().getLocalDatacenter()",
        "replicationStrategy.getNaturalReplicasForToken(baseToken)",
        "replicationStrategy.getNaturalReplicasForToken(viewToken)",
        "Iterables.tryFind(naturalViewReplicas, Replica::isSelf).toJavaUtil()",
        "Predicate<Replica> isLocalDC",
        "replicationStrategy instanceof NetworkTopologyStrategy",
        "DatabaseDescriptor.getEndpointSnitch().getDatacenter(r).equals(localDataCenter)",
        "!naturalViewReplicas.endpoints().contains(r.endpoint()) && isLocalDC.test(r)",
        "!naturalBaseReplicas.endpoints().contains(r.endpoint()) && isLocalDC.test(r)",
        "assert baseReplicas.size() == viewReplicas.size()",
        "if (baseReplicas.get(i).isSelf())",
        "if (baseIdx < 0)",
        "return Optional.empty();",
        "return Optional.of(viewReplicas.get(baseIdx));",
    ),
    "src/java/org/apache/cassandra/service/StorageProxy.java": (
        "public static void mutateMV(ByteBuffer dataKey, Collection<Mutation> mutations, boolean writeCommitLog, AtomicLong baseComplete, Dispatcher.RequestTime requestTime)",
        "StorageService.instance.isStarting() || StorageService.instance.isJoining() || StorageService.instance.isMoving()",
        "BatchlogManager.store(Batch.createLocal(batchUUID, FBUtilities.timestampMicros(),",
        "Set<Mutation> nonLocalMutations = new HashSet<>(mutations);",
        "Token baseToken = StorageService.instance.getTokenMetadata().partitioner.getToken(dataKey);",
        "ReplicaPlan.ForWrite replicaPlan = ReplicaPlans.forLocalBatchlogWrite();",
        "BatchlogCleanup cleanup = new BatchlogCleanup(mutations.size(),",
        "ViewUtils.getViewNaturalEndpoint(replicationStrategy, baseToken, tk)",
        "StorageService.instance.getTokenMetadata().pendingEndpointsForToken(tk, keyspaceName)",
        "if (!pairedEndpoint.isPresent())",
        "if (pendingReplicas.isEmpty())",
        "There is probably a range movement happening",
        "if (pairedEndpoint.get().isSelf() && StorageService.instance.isJoined()",
        "&& pendingReplicas.isEmpty())",
        "mutation.apply(writeCommitLog);",
        "nonLocalMutations.remove(mutation);",
        "cleanup.decrement();",
        "ReplicaLayout.forTokenWrite(replicationStrategy,",
        "EndpointsForToken.of(tk, pairedEndpoint.get())",
        "wrapViewBatchResponseHandler(mutation,",
        "BatchlogManager.store(Batch.createLocal(batchUUID, FBUtilities.timestampMicros(), nonLocalMutations), writeCommitLog);",
        "asyncWriteBatchedMutations(wrappers, localDataCenter, Stage.VIEW_MUTATION, requestTime);",
        "viewWriteMetrics.addNano(nanoTime() - startTime);",
        "viewWriteMetrics.viewWriteLatency.update(delay, MILLISECONDS);",
        "new ViewWriteMetricsWrapped(writeHandler",
    ),
    "src/java/org/apache/cassandra/locator/TokenMetadata.java": (
        "public EndpointsForToken pendingEndpointsForToken(Token token, String keyspaceName)",
        "PendingRangeMaps pendingRangeMaps = this.pendingRanges.get(keyspaceName);",
        "return EndpointsForToken.empty(token);",
        "return pendingRangeMaps.pendingEndpointsFor(token);",
    ),
    "src/java/org/apache/cassandra/concurrent/Stage.java": (
        "VIEW_MUTATION",
        "\"ViewMutationStage\"",
        "DatabaseDescriptor::getConcurrentViewWriters",
        "DatabaseDescriptor::setConcurrentViewWriters",
    ),
    "src/java/org/apache/cassandra/config/DatabaseDescriptor.java": (
        "public static int getConcurrentViewWriters()",
        "return conf.concurrent_materialized_view_writes;",
        "public static void setConcurrentViewWriters(int concurrent_materialized_view_writes)",
        "conf.concurrent_materialized_view_writes = concurrent_materialized_view_writes;",
    ),
    "src/java/org/apache/cassandra/metrics/ViewWriteMetrics.java": (
        "public final Counter viewReplicasAttempted;",
        "public final Counter viewReplicasSuccess;",
        "public final Timer viewWriteLatency;",
        "ViewPendingMutations",
        "viewReplicasAttempted.getCount() - viewReplicasSuccess.getCount()",
    ),
}

TEST_TOKEN_CHECKS = {
    "test/unit/org/apache/cassandra/db/view/ViewUtilsTest.java": (
        "public class ViewUtilsTest",
        "DatabaseDescriptor.setEndpointSnitch(snitch);",
        "public void testGetIndexNaturalEndpoint() throws Exception",
        "NetworkTopologyStrategy.class.getName()",
        "Optional<Replica> naturalEndpoint = ViewUtils.getViewNaturalEndpoint",
        "Assert.assertEquals(InetAddressAndPort.getByName(\"127.0.0.2\"), naturalEndpoint.get().endpoint());",
        "public void testLocalHostPreference() throws Exception",
        "Assert.assertEquals(InetAddressAndPort.getByName(\"127.0.0.1\"), naturalEndpoint.get().endpoint());",
        "public void testBaseTokenDoesNotBelongToLocalReplicaShouldReturnEmpty() throws Exception",
        "Assert.assertFalse(naturalEndpoint.isPresent());",
    ),
    "test/unit/org/apache/cassandra/cql3/ViewComplexDeletionsTest.java": (
        "public void testNoBatchlogCleanupForLocalMutations() throws Throwable",
        "CREATE MATERIALIZED VIEW",
    ),
    "test/unit/org/apache/cassandra/locator/PendingRangeMapsTest.java": (
        "pendingEndpointsFor(new BigIntegerToken",
        "assertEquals(2, pendingRangeMaps.pendingEndpointsFor",
    ),
    "test/unit/org/apache/cassandra/cql3/CQLTester.java": (
        "protected static void waitForViewMutations()",
        "Stage.VIEW_MUTATION.executor().getPendingTaskCount() == 0",
        "Stage.VIEW_MUTATION.executor().getActiveTaskCount() == 0",
    ),
}

DOC_TOKEN_CHECKS = {
    MATRIX_DOC: (
        "mv_pair_viewutils_cardinality_contract",
        "mv_pair_local_view_replica_preference",
        "mv_pair_local_dc_filter_contract",
        "mv_pair_shared_endpoint_filter_contract",
        "mv_pair_non_base_replica_empty_contract",
        "mv_pair_starting_batchlog_contract",
        "mv_pair_pending_endpoint_write_contract",
        "mv_pair_local_apply_fastpath_contract",
        "mv_pair_remote_stage_contract",
        "mv_pair_batchlog_metrics_contract",
        "mv_pair_existing_tests_baseline",
        "mv_pair_range_movement_distributed_gap",
        "ViewUtils.getViewNaturalEndpoint",
        "Stage.VIEW_MUTATION",
        "ViewPendingMutations",
    ),
    CHECKER_DOC: (
        "check-materialized-view-paired-replica-drift.py",
        "mv_pair_range_movement_distributed_gap",
        "ViewUtils.getViewNaturalEndpoint",
    ),
    README_DOC: (
        "module-materialized-view-paired-replica-matrix.md",
        "module-materialized-view-paired-replica-drift-checker.md",
        "check-materialized-view-paired-replica-drift.py",
        "76 个 research checker",
    ),
    SOURCE_MAP_DOC: (
        "Materialized view paired replica drift",
        "module-materialized-view-paired-replica-matrix.md",
        "check-materialized-view-paired-replica-drift.py",
    ),
    FLOW_DOC: (
        "module-materialized-view-paired-replica-matrix.md",
        "ViewUtils.getViewNaturalEndpoint",
        "Stage.VIEW_MUTATION",
    ),
}

MV_MARKERS = (
    re.compile(r"CREATE\s+MATERIALIZED\s+VIEW", re.IGNORECASE),
    re.compile(r"Materialized view", re.IGNORECASE),
)

TOPOLOGY_MARKERS = (
    re.compile(r"\bnodetoolResult\(\"move\""),
    re.compile(r"\bnodetoolResult\(\"decommission\""),
    re.compile(r"\.bootstrap\("),
    re.compile(r"\.decommission\("),
    re.compile(r"\.move\("),
    re.compile(r"pendingEndpointsForToken"),
    re.compile(r"pending range", re.IGNORECASE),
    re.compile(r"replaceHostAndStart"),
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
        checks.extend(CheckResult(f"source token {token}", path, token in text) for token in tokens)
    return checks


def test_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []
    for path, tokens in TEST_TOKEN_CHECKS.items():
        text = read(path)
        checks.extend(CheckResult(f"test token {token}", path, token in text) for token in tokens)
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


def gap_checks() -> list[CheckResult]:
    candidates: list[str] = []
    for path in (REPO_ROOT / "test/distributed").rglob("*.java"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(pattern.search(text) for pattern in MV_MARKERS) and any(pattern.search(text) for pattern in TOPOLOGY_MARKERS):
            candidates.append(str(path.relative_to(REPO_ROOT)))
    return [
        CheckResult("mv_pair_range_movement_distributed_gap still open", "test/distributed/**/*.java", not candidates, ", ".join(candidates)),
    ]


def check() -> tuple[dict[str, object], bool]:
    sources = source_checks()
    tests = test_checks()
    docs = doc_checks()
    gaps = gap_checks()
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
    parser = argparse.ArgumentParser(description="Check materialized view paired-replica source/test/doc coverage.")
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
            print(f"OK materialized view paired replica checks passed ({len(result['scenario_ids'])} scenarios)")
        else:
            print("Materialized view paired replica checks failed.", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
