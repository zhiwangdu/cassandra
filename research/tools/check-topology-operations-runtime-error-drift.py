#!/usr/bin/env python3
#
# Source-only drift check for topology operations runtime error research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

STORAGE_SERVICE = "src/java/org/apache/cassandra/service/StorageService.java"
RANGE_STREAMER = "src/java/org/apache/cassandra/dht/RangeStreamer.java"
RANGE_RELOCATOR = "src/java/org/apache/cassandra/service/RangeRelocator.java"
REBUILD_CMD = "src/java/org/apache/cassandra/tools/nodetool/Rebuild.java"
NODE_PROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
CLUSTER_UTILS = "test/distributed/org/apache/cassandra/distributed/shared/ClusterUtils.java"
HOST_REPLACEMENT_TEST = "test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementTest.java"
HOST_REPLACEMENT_ABRUPT_TEST = "test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementAbruptDownedInstanceTest.java"
HOST_REPLACEMENT_OUTAGE_TEST = "test/distributed/org/apache/cassandra/distributed/test/hostreplacement/HostReplacementOfDownedClusterTest.java"
UPDATE_SYSTEM_AUTH_DTEST = "test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java"
MOVE_TRANSIENT_TEST = "test/unit/org/apache/cassandra/service/MoveTransientTest.java"
REMOVE_TEST = "test/unit/org/apache/cassandra/service/RemoveTest.java"
STORAGE_SERVICE_TEST = "test/unit/org/apache/cassandra/service/StorageServiceTest.java"
REBUILD_STREAMING_TEST = "test/distributed/org/apache/cassandra/distributed/test/streaming/RebuildStreamingTest.java"
STREAM_PREPARE_FAIL_TEST = "test/distributed/org/apache/cassandra/distributed/test/StreamPrepareFailTest.java"

TARGET_DOCS = (
    "research/module-topology-operations-runtime-error-matrix.md",
    "research/module-topology-operations-runtime-error-drift-checker.md",
    "research/module-topology-operations-test-matrix.md",
    "research/module-topology-operations-coverage-drift-checker.md",
    "research/module-topology-operations.md",
    "research/flow-topology-operations.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "topology_runtime_replacement_shadow_gossip",
    "topology_runtime_replacement_live_node_guard",
    "topology_runtime_replacement_cross_dc_gap",
    "topology_runtime_removenode_restore_identity",
    "topology_runtime_removenode_force_boundary",
    "topology_runtime_removenode_transient_gap",
    "topology_runtime_rebuild_source_filters",
    "topology_runtime_rebuild_argument_errors",
    "topology_runtime_rebuild_stream_failure_wrap",
    "topology_runtime_existing_test_baseline",
    "topology_runtime_distributed_error_gap",
)

SOURCE_TOKEN_CHECKS = {
    STORAGE_SERVICE: (
        "private synchronized UUID prepareForReplacement() throws ConfigurationException",
        "Gossiper.instance.doShadowRound()",
        "Cannot replace_address %s because it doesn't exist in gossip",
        "validateEndpointSnitch(epStates.values().iterator());",
        "validateReplacementBootstrapTokens",
        "throw new UnsupportedOperationException(\"Cannot replace a live node... \");",
        "public void rebuild(String sourceDc, String keyspace, String tokens, String specificSources, boolean excludeLocalDatacenterNodes)",
        "Cannot set source data center to be local data center, when excludeLocalDataCenter flag is set",
        "Provided datacenter '%s' is not a valid datacenter",
        "Cannot specify tokens without keyspace.",
        "Node is still rebuilding. Check nodetool netstats.",
        "new RangeStreamer.SingleDatacenterFilter",
        "new RangeStreamer.ExcludeLocalDatacenterFilter",
        "new RangeStreamer.AllowedSourcesFilter",
        "The specified range %s is not a range that is owned by this node.",
        "This host was specified as a source for rebuilding.",
        "Unknown host specified",
        "Error while rebuilding node: ",
        "isRebuilding.set(false);",
        "private Multimap<InetAddressAndPort, FetchReplica> getNewSourceReplicas",
        "private static class LeavingReplica",
        "private void restoreReplicaCount",
        "StreamOperation.RESTORE_REPLICA_COUNT",
        "RangesAtEndpoint transientReplicas = fetchReplicas.stream()",
        "stream.requestRanges(sourceAddress, keyspaceName, full, transientReplicas);",
        "Streaming to restore replica count failed",
        "sendReplicationNotification(notifyEndpoint);",
        "public void forceRemoveCompletion()",
        "No further attempt will be made to restore replicas.",
    ),
    RANGE_STREAMER: (
        "public static class SingleDatacenterFilter implements SourceFilter",
        "public static class ExcludeLocalDatacenterFilter implements SourceFilter",
        "public static class AllowedSourcesFilter implements SourceFilter",
        "Filtered \" + replica + \" out because it does not belong to",
        "Filtered \" + replica + \" out because it belongs to the local datacenter",
        "Filtered \" + replica + \" out because it was not in the allowed set",
        "Necessary replicas for strict consistency were removed by source filters",
        "Couldn't find any matching sufficient replica",
        "Multiple strict sources found",
        "Unable to find sufficient sources for streaming range",
        "strat.getReplicationFactor().hasTransientReplicas()",
        "streamPlan.requestRanges(source, keyspace, full, transientReplicas);",
    ),
    RANGE_RELOCATOR: (
        "calculateRangesToFetchWithPreferredEndpoints",
        "new RangeStreamer.FailureDetectorSourceFilter",
        "new RangeStreamer.ExcludeLocalNodeFilter",
        "Need to stream %s, but only have %s which is transient and not full",
    ),
    REBUILD_CMD: (
        "@Command(name = \"rebuild\"",
        "@Option(title = \"specific_tokens\"",
        "name = {\"-s\", \"--sources\"}",
        "name = {\"--exclude-local-dc\"}",
        "throw new IllegalArgumentException(\"Cannot specify tokens without keyspace.\");",
        "probe.rebuild(sourceDataCenterName, keyspace, tokens, specificSources, excludeLocalDatacenterNodes);",
    ),
    NODE_PROBE: (
        "public void rebuild(String sourceDc, String keyspace, String tokens, String specificSources, boolean excludeLocalDatacenterNodes)",
        "ssProxy.rebuild(sourceDc, keyspace, tokens, specificSources, excludeLocalDatacenterNodes);",
        "public void forceRemoveCompletion()",
        "ssProxy.forceRemoveCompletion();",
    ),
    CLUSTER_UTILS: (
        "public static <I extends IInstance> I replaceHostAndStart",
        "properties.set(REPLACE_ADDRESS_FIRST_BOOT",
        "properties.set(BOOTSTRAP_SCHEMA_DELAY_MS",
    ),
    HOST_REPLACEMENT_TEST: (
        "replaceHostAndStart(cluster, nodeToRemove",
        "Cannot replace a live node",
        "BOOTSTRAP_SKIP_SCHEMA_CHECK",
    ),
    HOST_REPLACEMENT_ABRUPT_TEST: (
        "replaceHostAndStart(cluster, nodeToRemove",
        "abrupt shutdown",
        "BOOTSTRAP_SKIP_SCHEMA_CHECK",
    ),
    HOST_REPLACEMENT_OUTAGE_TEST: (
        "replaceHostAndStart(cluster, nodeToRemove",
        "beforeCrashTokens",
        "getTokenMetadataTokens(seed)",
    ),
    UPDATE_SYSTEM_AUTH_DTEST: (
        "networkTopology(2",
        "dcAndRack(\"dc2\", \"rack2\")",
        "FailureDetector.instance.forceConviction(endpoint);",
        "StorageService.instance.removeNode(node2hostId);",
    ),
    MOVE_TRANSIENT_TEST: (
        "public class MoveTransientTest",
        "transientReplica",
        "sourceFilterDownNodes",
        "Necessary replicas for strict consistency were removed by source filters:",
        "replication_factor\", \"3/1\"",
    ),
    REMOVE_TEST: (
        "ss.removeNode",
        "REPLICATION_DONE_REQ",
    ),
    STORAGE_SERVICE_TEST: (
        "testLocalDatacenterNodesExcludedDuringRebuild",
        "testRebuildFailOnNonExistingDatacenter",
        "testRebuildingWithTokensWithoutKeyspace",
        "Cannot set source data center to be local data center, when excludeLocalDataCenter flag is set",
        "Cannot specify tokens without keyspace.",
    ),
    REBUILD_STREAMING_TEST: (
        "nodetoolResult(\"rebuild\", \"--keyspace\", KEYSPACE)",
        "system_views.streaming",
        "operation\", \"Rebuild\"",
    ),
    STREAM_PREPARE_FAIL_TEST: (
        "StorageService.instance.rebuild(null)",
        "rebuild should throw exception",
        "Stream failed",
    ),
}

DOC_REQUIRED_TOKENS = (
    "research/tools/check-topology-operations-runtime-error-drift.py",
    "research/module-topology-operations-runtime-error-drift-checker.md",
    "research/module-topology-operations-runtime-error-matrix.md",
    "StorageService.prepareForReplacement()",
    "Gossiper.instance.doShadowRound()",
    "Cannot replace_address %s because it doesn't exist in gossip",
    "Cannot replace a live node...",
    "ClusterUtils.replaceHostAndStart()",
    "REPLACE_ADDRESS_FIRST_BOOT",
    "restoreReplicaCount()",
    "getNewSourceReplicas()",
    "LeavingReplica",
    "RESTORE_REPLICA_COUNT",
    "Streaming to restore replica count failed",
    "forceRemoveCompletion()",
    "No further attempt will be made to restore replicas",
    "SingleDatacenterFilter",
    "ExcludeLocalDatacenterFilter",
    "AllowedSourcesFilter",
    "Cannot specify tokens without keyspace.",
    "Node is still rebuilding. Check nodetool netstats.",
    "The specified range %s is not a range that is owned by this node.",
    "This host was specified as a source for rebuilding.",
    "Unknown host specified",
    "Necessary replicas for strict consistency were removed by source filters",
    "Error while rebuilding node: ",
    "HostReplacementTest",
    "UpdateSystemAuthAfterDCExpansionTest",
    "MoveTransientTest",
    "StorageServiceTest",
    "RebuildStreamingTest",
    "StreamPrepareFailTest",
    "cross-DC replacement remains a targeted distributed gap",
    "removenode transient replication distributed test",
    "rebuild `--sources`、non-owned ranges、concurrent rebuild",
) + tuple(SOURCE_TOKEN_CHECKS.keys()) + SCENARIO_IDS


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def distributed_java_files() -> tuple[Path, ...]:
    return tuple((REPO_ROOT / "test/distributed/org/apache/cassandra/distributed/test").rglob("*.java"))


def relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def source_checks() -> list[Check]:
    checks: list[Check] = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(Check(f"source token contract {path}", path, all(token in text for token in tokens)))

    cross_dc_replacement_hits = []
    for path in distributed_java_files():
        text = path.read_text(encoding="utf-8")
        if "replaceHostAndStart" not in text:
            continue
        if any(token in text for token in (
            "NetworkTopologyStrategy",
            "withDC(",
            "withNodeIdTopology",
            "NetworkTopology.dcAndRack",
            "networkTopology(",
            "dc2",
            "datacenter2",
        )):
            cross_dc_replacement_hits.append(relative(path))
    checks.append(Check("gap still open: no cross-DC replacement distributed test", "test/distributed", not cross_dc_replacement_hits))

    transient_removenode_hits = []
    for path in distributed_java_files():
        text = path.read_text(encoding="utf-8")
        has_remove = "removeNode(" in text or "nodetoolResult(\"removenode\"" in text
        has_transient = "transient" in text or "transient_ranges" in text or "\"3/1\"" in text
        if has_remove and has_transient:
            transient_removenode_hits.append(relative(path))
    checks.append(Check("gap still open: no removenode transient distributed test", "test/distributed", not transient_removenode_hits))

    rebuild_error_hits = []
    for path in distributed_java_files():
        text = path.read_text(encoding="utf-8")
        has_rebuild = "nodetoolResult(\"rebuild\"" in text or "StorageService.instance.rebuild" in text
        has_error_surface = any(token in text for token in (
            "--sources",
            "\"--tokens\"",
            "--exclude-local-dc",
            "specificSources",
            "AllowedSourcesFilter",
            "not a range that is owned",
            "Node is still rebuilding",
            "Unknown host specified",
            "This host was specified as a source",
            "Cannot set source data center",
        ))
        if has_rebuild and has_error_surface:
            rebuild_error_hits.append(relative(path))
    checks.append(Check("gap still open: no rebuild allow-list/error distributed test", "test/distributed", not rebuild_error_hits))

    return checks


def doc_checks() -> list[Check]:
    docs = {path: read(path) for path in TARGET_DOCS}
    combined = "\n".join(docs.values())
    checks = [Check(f"target doc exists {path}", path, bool(text.strip())) for path, text in docs.items()]
    for token in DOC_REQUIRED_TOKENS:
        checks.append(Check(f"doc token {token}", "research", token in combined))

    matrix = docs["research/module-topology-operations-runtime-error-matrix.md"]
    drift_doc = docs["research/module-topology-operations-runtime-error-drift-checker.md"]
    for scenario in SCENARIO_IDS:
        checks.append(Check(f"scenario coverage {scenario}", TARGET_DOCS[0], scenario in matrix and scenario in drift_doc))

    return checks


def run_checks() -> list[Check]:
    return source_checks() + doc_checks()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check topology operations runtime error research drift.")
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
            print("FAIL topology operations runtime error drift check")
            for failure in failures:
                print(f"- {failure.name} ({failure.source})")
        else:
            print(f"OK topology operations runtime error drift check: {len(checks)} checks")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
