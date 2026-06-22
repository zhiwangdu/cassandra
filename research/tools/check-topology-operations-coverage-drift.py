#!/usr/bin/env python3
#
# Source-only drift check for topology operations test coverage research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

STORAGE_SERVICE = "src/java/org/apache/cassandra/service/StorageService.java"
RANGE_STREAMER = "src/java/org/apache/cassandra/dht/RangeStreamer.java"
NODE_PROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
MOVE_CMD = "src/java/org/apache/cassandra/tools/nodetool/Move.java"
REMOVE_NODE_CMD = "src/java/org/apache/cassandra/tools/nodetool/RemoveNode.java"
REBUILD_CMD = "src/java/org/apache/cassandra/tools/nodetool/Rebuild.java"
ASSASSINATE_CMD = "src/java/org/apache/cassandra/tools/nodetool/Assassinate.java"
CASSANDRA_RELEVANT_PROPERTIES = "src/java/org/apache/cassandra/config/CassandraRelevantProperties.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
STORAGE_SERVICE_SERVER_TEST = "test/unit/org/apache/cassandra/service/StorageServiceServerTest.java"
STORAGE_SERVICE_TEST = "test/unit/org/apache/cassandra/service/StorageServiceTest.java"
REMOVE_TEST = "test/unit/org/apache/cassandra/service/RemoveTest.java"
MOVE_TRANSIENT_TEST = "test/unit/org/apache/cassandra/service/MoveTransientTest.java"
CLUSTER_UTILS = "test/distributed/org/apache/cassandra/distributed/shared/ClusterUtils.java"
HOST_REPLACEMENT_TEST = "test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementTest.java"
HOST_REPLACEMENT_ABRUPT_TEST = "test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementAbruptDownedInstanceTest.java"
HOST_REPLACEMENT_OUTAGE_TEST = "test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementOfDownedClusterTest.java"
BASE_ASSASSINATED_CASE = "test/distributed/org/apache/cassandra/distributed/test/hostreplacement/BaseAssassinatedCase.java"
NODE_CANNOT_JOIN_HIBERNATING_TEST = "test/distributed/org/apache/cassandra/distributed/test/hostreplacement/NodeCannotJoinAsHibernatingNodeWithoutReplaceAddressTest.java"
MOVE_DTEST = "test/distributed/org/apache/cassandra/distributed/test/MoveTest.java"
UPDATE_SYSTEM_AUTH_DTEST = "test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java"
REBUILD_STREAMING_TEST = "test/distributed/org/apache/cassandra/distributed/test/streaming/RebuildStreamingTest.java"
STREAM_PREPARE_FAIL_TEST = "test/distributed/org/apache/cassandra/distributed/test/StreamPrepareFailTest.java"
SIMULATION_RUNNER = "test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java"
CLUSTER_ACTIONS = "test/simulator/main/org/apache/cassandra/simulator/cluster/ClusterActions.java"
KEYSPACE_ACTIONS = "test/simulator/main/org/apache/cassandra/simulator/cluster/KeyspaceActions.java"
ON_CLUSTER_JOIN = "test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterJoin.java"
ON_CLUSTER_LEAVE = "test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterLeave.java"
ON_CLUSTER_REPLACE = "test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterReplace.java"
ON_CLUSTER_CHANGE_RF = "test/simulator/main/org/apache/cassandra/simulator/cluster/OnClusterChangeRf.java"
ON_INSTANCE_TOPOLOGY_PAXOS_REPAIR = "test/simulator/main/org/apache/cassandra/simulator/cluster/OnInstanceTopologyChangePaxosRepair.java"
PAXOS_TOPOLOGY_CHANGE_VERIFIER = "test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosTopologyChangeVerifier.java"

TARGET_DOCS = (
    "research/module-topology-operations-test-matrix.md",
    "research/module-topology-operations-coverage-drift-checker.md",
    "research/module-topology-operations.md",
    "research/module-topology-operations-internals.md",
    "research/flow-topology-operations.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "topology_replacement_real_path",
    "topology_replacement_cross_dc_gap",
    "topology_simulator_topology_actions",
    "topology_removenode_transient_restore_contract",
    "topology_removenode_transient_dtest_gap",
    "topology_rebuild_source_filter_contract",
    "topology_rebuild_distributed_error_gap",
    "topology_nodetool_jmx_surface",
    "topology_assassinate_replacement_boundary",
    "topology_tests_coverage_baseline",
)

SOURCE_TOKEN_CHECKS = {
    STORAGE_SERVICE: (
        "private synchronized UUID prepareForReplacement()",
        "validateReplacementBootstrapTokens",
        "throw new UnsupportedOperationException(\"Cannot replace a live node... \");",
        "public void rebuild(String sourceDc, String keyspace, String tokens, String specificSources, boolean excludeLocalDatacenterNodes)",
        "Cannot set source data center to be local data center, when excludeLocalDataCenter flag is set",
        "Cannot specify tokens without keyspace.",
        "Node is still rebuilding. Check nodetool netstats.",
        "new RangeStreamer.SingleDatacenterFilter",
        "new RangeStreamer.ExcludeLocalDatacenterFilter",
        "new RangeStreamer.AllowedSourcesFilter",
        "The specified range %s is not a range that is owned by this node.",
        "This host was specified as a source for rebuilding.",
        "Unknown host specified",
        "Error while rebuilding node",
        "isRebuilding.set(false);",
        "public void forceRemoveCompletion()",
        "public void removeNode(String hostIdString)",
        "private void restoreReplicaCount",
        "private static class LeavingReplica",
        "RangesAtEndpoint transientReplicas = fetchReplicas.stream()",
        "stream.requestRanges(sourceAddress, keyspaceName, full, transientReplicas);",
        "static EndpointsByReplica getChangedReplicasForLeaving",
        "Full -> transient is handled by nodetool cleanup",
    ),
    RANGE_STREAMER: (
        "public static class SingleDatacenterFilter implements SourceFilter",
        "public static class ExcludeLocalDatacenterFilter implements SourceFilter",
        "public static class AllowedSourcesFilter implements SourceFilter",
        "calculateRangesToFetchWithPreferredEndpoints",
        "Necessary replicas for strict consistency were removed by source filters",
        "streamPlan.requestRanges(source, keyspace, full, transientReplicas);",
    ),
    NODE_PROBE: (
        "public void forceRemoveCompletion()",
        "ssProxy.forceRemoveCompletion();",
        "public void assassinateEndpoint(String address)",
        "gossProxy.assassinateEndpoint(address);",
        "public void rebuild(String sourceDc, String keyspace, String tokens, String specificSources, boolean excludeLocalDatacenterNodes)",
        "ssProxy.rebuild(sourceDc, keyspace, tokens, specificSources, excludeLocalDatacenterNodes);",
    ),
    MOVE_CMD: (
        "@Command(name = \"move\"",
        "probe.move(newToken);",
    ),
    REMOVE_NODE_CMD: (
        "@Command(name = \"removenode\"",
        "case \"status\":",
        "case \"force\":",
        "probe.forceRemoveCompletion();",
        "probe.removeNode(removeOperation);",
    ),
    REBUILD_CMD: (
        "@Command(name = \"rebuild\"",
        "@Option(title = \"specific_sources\"",
        "name = {\"-s\", \"--sources\"}",
        "@Option(title = \"exclude_local_dc\"",
        "throw new IllegalArgumentException(\"Cannot specify tokens without keyspace.\");",
        "probe.rebuild(sourceDataCenterName, keyspace, tokens, specificSources, excludeLocalDatacenterNodes);",
    ),
    ASSASSINATE_CMD: (
        "@Command(name = \"assassinate\"",
        "Forcefully remove a dead node without re-replicating any data.",
        "probe.assassinateEndpoint(endpoint);",
    ),
    CASSANDRA_RELEVANT_PROPERTIES: (
        "REPLACEMENT_ALLOW_EMPTY(\"cassandra.allow_empty_replace_address\", \"true\")",
        "REPLACE_ADDRESS(\"cassandra.replace_address\")",
        "REPLACE_ADDRESS_FIRST_BOOT(\"cassandra.replace_address_first_boot\")",
    ),
    DATABASE_DESCRIPTOR: (
        "getReplaceAddress",
        "REPLACE_ADDRESS_FIRST_BOOT",
    ),
    STORAGE_SERVICE_SERVER_TEST: (
        "isReplacingSameHostAddressAndHostIdTest",
        "StorageService.instance.isReplacingSameHostAddressAndHostId",
    ),
    STORAGE_SERVICE_TEST: (
        "Cannot set source data center to be local data center, when excludeLocalDataCenter flag is set",
        "Provided datacenter",
        "Cannot specify tokens without keyspace.",
    ),
    REMOVE_TEST: (
        "REPLICATION_DONE_REQ",
        "ss.removeNode",
    ),
    MOVE_TRANSIENT_TEST: (
        "public class MoveTransientTest",
        "transientReplica",
        "sourceFilterDownNodes",
        "Necessary replicas for strict consistency were removed by source filters:",
    ),
    CLUSTER_UTILS: (
        "public static <I extends IInstance> I replaceHostAndStart",
        "properties.set(REPLACE_ADDRESS_FIRST_BOOT",
        "properties.set(BOOTSTRAP_SCHEMA_DELAY_MS",
        "public static List<RingInstanceDetails> ring",
        "cluster.filters().allVerbs().to",
        "cluster.filters().allVerbs().from",
    ),
    HOST_REPLACEMENT_TEST: (
        "replaceHostAndStart(cluster, nodeToRemove",
        "Cannot replace a live node",
        "BOOTSTRAP_SKIP_SCHEMA_CHECK",
    ),
    HOST_REPLACEMENT_ABRUPT_TEST: (
        "replaceHostAndStart(cluster, nodeToRemove",
        "BOOTSTRAP_SKIP_SCHEMA_CHECK",
    ),
    HOST_REPLACEMENT_OUTAGE_TEST: (
        "replaceHostAndStart(cluster, nodeToRemove",
        "beforeCrashTokens",
        "getTokenMetadataTokens(seed)",
    ),
    BASE_ASSASSINATED_CASE: (
        "nodetoolResult(\"assassinate\"",
        "replaceHostAndStart(cluster, nodeToRemove",
        "BOOTSTRAP_SCHEMA_DELAY_MS",
    ),
    NODE_CANNOT_JOIN_HIBERNATING_TEST: (
        "ClusterUtils.replaceHostAndStart",
        "already exists, cancelling join",
    ),
    MOVE_DTEST: (
        "nodetoolResult(\"move\"",
    ),
    UPDATE_SYSTEM_AUTH_DTEST: (
        "dc2",
        "forceConviction",
        "StorageService.instance.removeNode",
        "alterKeyspaceStatement",
    ),
    REBUILD_STREAMING_TEST: (
        "nodetoolResult(\"rebuild\", \"--keyspace\", KEYSPACE)",
        "system_views.streaming",
    ),
    STREAM_PREPARE_FAIL_TEST: (
        "StorageService.instance.rebuild(null)",
        "rebuild should throw exception",
    ),
    SIMULATION_RUNNER: (
        "--cluster-actions",
        "JOIN,LEAVE,REPLACE,CHANGE_RF",
        "TopologyChange.valueOf",
    ),
    CLUSTER_ACTIONS: (
        "public enum TopologyChange",
        "JOIN, LEAVE, REPLACE, CHANGE_RF",
        "choicesNoJoin = allChoices.without(JOIN).without(REPLACE);",
    ),
    KEYSPACE_ACTIONS: (
        "case REPLACE:",
        "new OnClusterReplace",
        "case JOIN:",
        "new OnClusterJoin",
        "case LEAVE:",
        "new OnClusterLeave",
        "case CHANGE_RF:",
        "new OnClusterChangeRf",
    ),
    ON_CLUSTER_JOIN: (
        "new OnInstanceTopologyChangePaxosRepair(actions, joining, \"Join\")",
    ),
    ON_CLUSTER_LEAVE: (
        "new OnInstanceTopologyChangePaxosRepair(actions, leaving, \"Leave\")",
    ),
    ON_CLUSTER_REPLACE: (
        "new OnInstanceTopologyChangePaxosRepair(actions, joining, \"Replace\")",
        "new OnInstanceBootstrap(actions, joinInstance, movingToken, true)",
    ),
    ON_CLUSTER_CHANGE_RF: (
        "class OnClusterChangeRf extends OnClusterChangeTopology",
    ),
    ON_INSTANCE_TOPOLOGY_PAXOS_REPAIR: (
        "StorageService.instance.startRepairPaxosForTopologyChange(reason)",
    ),
    PAXOS_TOPOLOGY_CHANGE_VERIFIER: (
        "public class PaxosTopologyChangeVerifier implements TopologyChangeValidator",
    ),
}

DOC_REQUIRED_TOKENS = (
    "research/tools/check-topology-operations-coverage-drift.py",
    "research/module-topology-operations-coverage-drift-checker.md",
    "research/module-topology-operations-test-matrix.md",
    "StorageService",
    "RangeStreamer",
    "ClusterUtils",
    "KeyspaceActions",
    "PaxosTopologyChangeVerifier",
    "MoveTransientTest",
    "UpdateSystemAuthAfterDCExpansionTest",
    "RebuildStreamingTest",
    "StorageServiceTest",
    "HostReplacementTest",
    "HostReplacementAbruptDownedInstanceTest",
    "HostReplacementOfDownedClusterTest",
    "BaseAssassinatedCase",
    "NodeCannotJoinAsHibernatingNodeWithoutReplaceAddressTest",
    "SingleDatacenterFilter",
    "ExcludeLocalDatacenterFilter",
    "AllowedSourcesFilter",
    "REPLACE_ADDRESS_FIRST_BOOT",
    "cassandra.replace_address_first_boot",
    "cassandra.allow_empty_replace_address",
    "Cannot specify tokens without keyspace.",
    "Node is still rebuilding. Check nodetool netstats.",
    "Necessary replicas for strict consistency were removed by source filters",
    "Cross-DC replacement remains a targeted test gap",
    "Transient removenode remains a targeted distributed test gap",
    "Rebuild allow-list failures are source-code complete but not distributed-test complete",
    "distributed allow-list/error matrix",
) + tuple(SOURCE_TOKEN_CHECKS.keys()) + SCENARIO_IDS


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def distributed_java_files() -> tuple[Path, ...]:
    root = REPO_ROOT / "test/distributed"
    return tuple(root.rglob("*.java"))


def relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def files_matching(required: tuple[str, ...], any_of: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for path in distributed_java_files():
        text = path.read_text(encoding="utf-8")
        if all(token in text for token in required) and any(token in text for token in any_of):
            hits.append(relative(path))
    return hits


def source_checks() -> list[Check]:
    checks: list[Check] = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(Check(f"source token contract {path}", path, all(token in text for token in tokens)))

    cross_dc_replacement_hits = files_matching(
        ("replaceHostAndStart",),
        ("withDC(", "withDCs(", "NetworkTopologyStrategy", "dc2", "datacenter2", "datacenter1"),
    )
    checks.append(Check("gap still open: no cross-DC replacement distributed test", "test/distributed", not cross_dc_replacement_hits))

    transient_removenode_hits = []
    for path in distributed_java_files():
        text = path.read_text(encoding="utf-8")
        has_remove = "removeNode(" in text or "removenode" in text
        has_transient = "transient" in text or "transient_ranges" in text or "3/1" in text
        if has_remove and has_transient:
            transient_removenode_hits.append(relative(path))
    checks.append(Check("gap still open: no removenode transient distributed test", "test/distributed", not transient_removenode_hits))

    rebuild_allowlist_error_hits = []
    for path in distributed_java_files():
        text = path.read_text(encoding="utf-8")
        has_rebuild = "rebuild" in text
        has_error_surface = any(token in text for token in (
            "--sources",
            "specificSources",
            "AllowedSourcesFilter",
            "not a range that is owned",
            "Node is still rebuilding",
            "exclude-local-dc",
        ))
        if has_rebuild and has_error_surface:
            rebuild_allowlist_error_hits.append(relative(path))
    checks.append(Check("gap still open: no rebuild allow-list/error distributed test", "test/distributed", not rebuild_allowlist_error_hits))

    return checks


def doc_checks() -> list[Check]:
    docs = {path: read(path) for path in TARGET_DOCS}
    combined = "\n".join(docs.values())
    checks = [Check(f"target doc exists {path}", path, bool(text.strip())) for path, text in docs.items()]
    for token in DOC_REQUIRED_TOKENS:
        checks.append(Check(f"doc token {token}", "research", token in combined))

    matrix = docs["research/module-topology-operations-test-matrix.md"]
    drift_doc = docs["research/module-topology-operations-coverage-drift-checker.md"]
    for scenario in SCENARIO_IDS:
        checks.append(Check(f"scenario coverage {scenario}", TARGET_DOCS[0], scenario in matrix and scenario in drift_doc))

    return checks


def run_checks() -> list[Check]:
    return source_checks() + doc_checks()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check topology operations coverage research drift.")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args()

    checks = run_checks()
    failures = [check for check in checks if not check.ok]

    if args.json:
        print(json.dumps(
            {
                "ok": not failures,
                "checks": [check.__dict__ for check in checks],
                "failures": [check.__dict__ for check in failures],
            },
            indent=2,
            sort_keys=True,
        ))
    else:
        if failures:
            print("FAIL topology operations coverage drift check")
            for failure in failures:
                print(f"- {failure.name} ({failure.source})")
        else:
            print(f"OK topology operations coverage drift check: {len(checks)} checks")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
