#!/usr/bin/env python3
#
# Source-only drift check for nodetool status/ring observability research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

STATUS = "src/java/org/apache/cassandra/tools/nodetool/Status.java"
RING = "src/java/org/apache/cassandra/tools/nodetool/Ring.java"
NODE_TOOL = "src/java/org/apache/cassandra/tools/NodeTool.java"
NODEPROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
STORAGE_SERVICE_MBEAN = "src/java/org/apache/cassandra/service/StorageServiceMBean.java"
STORAGE_SERVICE = "src/java/org/apache/cassandra/service/StorageService.java"
ENDPOINT_SNITCH_MBEAN = "src/java/org/apache/cassandra/locator/EndpointSnitchInfoMBean.java"

NODETOOL_TEST = "test/distributed/org/apache/cassandra/distributed/test/NodeToolTest.java"
JMX_FEATURE_TEST = "test/distributed/org/apache/cassandra/distributed/test/jmx/JMXFeatureTest.java"
CLUSTER_UTILS = "test/distributed/org/apache/cassandra/distributed/shared/ClusterUtils.java"

MATRIX_DOC = "research/module-nodetool-status-ring-observability-matrix.md"
CHECKER_DOC = "research/module-nodetool-status-ring-drift-checker.md"
OPERATIONS_DOC = "research/module-operations-observability.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

SCENARIO_IDS = (
    "nodetool_status_command_surface_contract",
    "nodetool_status_jmx_snapshot_contract",
    "nodetool_status_state_rendering_contract",
    "nodetool_ring_command_surface_contract",
    "nodetool_ring_state_rendering_contract",
    "nodetool_status_ring_with_port_mbean_contract",
    "nodetool_status_ring_tokenmetadata_source_contract",
    "nodetool_status_ring_ownership_fallback_contract",
    "nodetool_status_ring_snitch_grouping_contract",
    "nodetool_status_ring_distributed_test_baseline",
)

WITH_PORT_METHODS = (
    "getLiveNodesWithPort",
    "getUnreachableNodesWithPort",
    "getJoiningNodesWithPort",
    "getLeavingNodesWithPort",
    "getMovingNodesWithPort",
    "getTokenToEndpointWithPortMap",
    "getLoadMapWithPort",
    "getEndpointWithPortToHostId",
    "getOwnershipWithPort",
    "effectiveOwnershipWithPort",
)

SOURCE_TOKEN_CHECKS = {
    STATUS: (
        '@Command(name = "status", description = "Print cluster information (state, load, IDs, ...)")',
        '@Arguments(usage = "[<keyspace>]", description = "The keyspace name")',
        '@Option(title = "resolve_ip", name = {"-r", "--resolve-ip"}',
        "joiningNodes = probe.getJoiningNodes(true);",
        "leavingNodes = probe.getLeavingNodes(true);",
        "movingNodes = probe.getMovingNodes(true);",
        "loadMap = probe.getLoadMap(true);",
        "Map<String, String> tokensToEndpoints = probe.getTokenToEndpointMap(true);",
        "liveNodes = probe.getLiveNodes(true);",
        "unreachableNodes = probe.getUnreachableNodes(true);",
        "hostIDMap = probe.getHostIdMap(true);",
        "epSnitchInfo = probe.getEndpointSnitchInfoProxy();",
        "ownerships = probe.effectiveOwnershipWithPort(keyspace);",
        "ownerships = probe.getOwnershipWithPort();",
        "NodeTool.getOwnershipByDcWithPort(probe, resolveIp, tokensToEndpoints, ownerships);",
        'out.println("Status=Up/Down");',
        'out.println("|/ State=Normal/Leaving/Joining/Moving");',
        'String owns = hasEffectiveOwns ? "Owns (effective)" : "Owns";',
        'tableBuilder.add("--", "Address", "Load", owns, "Host ID", "Token", "Rack");',
        'tableBuilder.add("--", "Address", "Load", "Tokens", owns, "Host ID", "Rack");',
        'if (liveNodes.contains(endpoint)) status = "U";',
        'else if (unreachableNodes.contains(endpoint)) status = "D";',
        'if (joiningNodes.contains(endpoint)) state = "J";',
        'else if (leavingNodes.contains(endpoint)) state = "L";',
        'else if (movingNodes.contains(endpoint)) state = "M";',
        'else state = "N";',
        "epSnitchInfo.getRack(endpoint)",
    ),
    RING: (
        '@Command(name = "ring", description = "Print information about the token ring")',
        '@Arguments(description = "Specify a keyspace for accurate ownership information (topology awareness)")',
        '@Option(title = "resolve_ip", name = {"-r", "--resolve-ip"}',
        "liveNodes = probe.getLiveNodes(true);",
        "deadNodes = probe.getUnreachableNodes(true);",
        "joiningNodes = probe.getJoiningNodes(true);",
        "leavingNodes = probe.getLeavingNodes(true);",
        "movingNodes = probe.getMovingNodes(true);",
        "loadMap = probe.getLoadMap(true);",
        "Map<String, String> tokensToEndpoints = probe.getTokenToEndpointMap(true);",
        "ownerships = probe.effectiveOwnershipWithPort(keyspace);",
        "ownerships = probe.getOwnershipWithPort();",
        "NodeTool.getOwnershipByDcWithPort(probe, resolveIp, tokensToEndpoints, ownerships)",
        'out.println("  Warning: \\"nodetool ring\\" is used to output all the tokens of a node.");',
        'out.printf(format, "Address", "Rack", "Status", "State", "Load", "Owns", "Token");',
        'String state = "Normal";',
        'state = "Joining";',
        'state = "Leaving";',
        'state = "Moving";',
        'String load = loadMap.getOrDefault(endpoint, "?");',
        'stat.ipOrDns(printPort)',
        "epSnitchInfo.getRack(endpoint)",
    ),
    NODE_TOOL: (
        "Ring.class",
        "Status.class",
        "public static SortedMap<String, SetHostStatWithPort> getOwnershipByDcWithPort",
        "EndpointSnitchInfoMBean epSnitchInfo = probe.getEndpointSnitchInfoProxy();",
        "epSnitchInfo.getDatacenter(tokenAndEndPoint.getValue())",
        "ownershipByDc.get(dc).add(tokenAndEndPoint.getKey(), tokenAndEndPoint.getValue(), ownerships);",
    ),
    NODEPROBE: (
        "public Map<String, String> getTokenToEndpointMap(boolean withPort)",
        "return withPort ? ssProxy.getTokenToEndpointWithPortMap() : ssProxy.getTokenToEndpointMap();",
        "public List<String> getLiveNodes(boolean withPort)",
        "return withPort ? ssProxy.getLiveNodesWithPort() : ssProxy.getLiveNodes();",
        "public List<String> getJoiningNodes(boolean withPort)",
        "public List<String> getLeavingNodes(boolean withPort)",
        "public List<String> getMovingNodes(boolean withPort)",
        "public List<String> getUnreachableNodes(boolean withPort)",
        "public Map<String, String> getLoadMap(boolean withPort)",
        "return withPort ? ssProxy.getLoadMapWithPort() : ssProxy.getLoadMap();",
        "public Map<String, Float> getOwnershipWithPort()",
        "return ssProxy.getOwnershipWithPort();",
        "public Map<String, Float> effectiveOwnershipWithPort(String keyspace) throws IllegalStateException",
        "return ssProxy.effectiveOwnershipWithPort(keyspace);",
        "public Map<String, String> getHostIdMap(boolean withPort)",
        "return withPort ? ssProxy.getEndpointWithPortToHostId() : ssProxy.getEndpointToHostId();",
        "public EndpointSnitchInfoMBean getEndpointSnitchInfoProxy()",
        '"org.apache.cassandra.db:type=EndpointSnitchInfo"',
    ),
    STORAGE_SERVICE_MBEAN: (
        "public List<String> getLiveNodesWithPort();",
        "public List<String> getUnreachableNodesWithPort();",
        "public List<String> getJoiningNodesWithPort();",
        "public List<String> getLeavingNodesWithPort();",
        "public List<String> getMovingNodesWithPort();",
        "public Map<String, String> getTokenToEndpointWithPortMap();",
        "public Map<String, String> getEndpointWithPortToHostId();",
        "public Map<String, String> getLoadMapWithPort();",
        "public Map<String, Float> getOwnershipWithPort();",
        "public Map<String, Float> effectiveOwnershipWithPort(String keyspace) throws IllegalStateException;",
    ),
    STORAGE_SERVICE: (
        "public Map<String, String> getTokenToEndpointWithPortMap()",
        "tokenMetadata.getNormalAndBootstrappingTokenToEndpointMap();",
        "Collections.sort(tokens);",
        "mapString.put(token.toString(), mapInetAddress.get(token).getHostAddress(withPort));",
        "public Map<String, String> getEndpointWithPortToHostId()",
        "LoadBroadcaster.instance.getLoadInfo().entrySet()",
        "map.put(FBUtilities.getBroadcastAddressAndPort().getHostAddress(withPort), getLoadString());",
        "tokenMetadata.getLeavingEndpoints()",
        "tokenMetadata.getMovingEndpoints()",
        "tokenMetadata.getBootstrapTokens().valueSet()",
        "Gossiper.instance.getLiveMembers()",
        "Gossiper.instance.getUnreachableMembers()",
        "public Map<String, Float> getOwnershipWithPort()",
        "private LinkedHashMap<InetAddressAndPort, Float> getEffectiveOwnership(String keyspace)",
        "public LinkedHashMap<String, Float> effectiveOwnershipWithPort(String keyspace) throws IllegalStateException",
        "Schema.instance.getUserKeyspaces()",
        "LocalStrategy",
    ),
    ENDPOINT_SNITCH_MBEAN: (
        "public String getRack(String host) throws UnknownHostException;",
        "public String getDatacenter(String host) throws UnknownHostException;",
        "public String getSnitchName();",
    ),
    NODETOOL_TEST: (
        'NODE.nodetoolResult("ring")',
        'stdoutContains("Datacenter: datacenter0")',
        'stdoutContains("127.0.0.1       rack0       Up     Normal")',
    ),
    JMX_FEATURE_TEST: (
        'nodetoolResult("status")',
        'containsString("DN  127.0.0.1")',
        'containsString("UN  127.0.0.1")',
        "ClusterUtils.awaitRingStatus",
        "ClusterUtils.awaitRingState",
    ),
    CLUSTER_UTILS: (
        "public static List<RingInstanceDetails> ring(IInstance inst)",
        'inst.nodetoolResult("ring")',
        "return parseRing(results.getStdout());",
        "public static List<RingInstanceDetails> awaitRingStatus",
        "public static List<RingInstanceDetails> awaitRingState",
        'details.status.equals("Up") && details.state.equals("Normal")',
        "private static List<RingInstanceDetails> parseRing(String str)",
        "public static final class RingInstanceDetails",
    ),
}

DOC_REQUIRED_TOKENS = (
    MATRIX_DOC,
    CHECKER_DOC,
    "check-nodetool-status-ring-drift.py",
    STATUS,
    RING,
    NODE_TOOL,
    NODEPROBE,
    STORAGE_SERVICE_MBEAN,
    STORAGE_SERVICE,
    ENDPOINT_SNITCH_MBEAN,
    NODETOOL_TEST,
    JMX_FEATURE_TEST,
    CLUSTER_UTILS,
    "nodetool status",
    "nodetool ring",
    "effectiveOwnershipWithPort",
    "getOwnershipWithPort",
    "getTokenToEndpointWithPortMap",
    "getEndpointWithPortToHostId",
    "EndpointSnitchInfoMBean",
    "LoadBroadcaster",
    "Gossiper",
    "UN",
    "DN",
    "Up",
    "Down",
) + SCENARIO_IDS + WITH_PORT_METHODS


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

    mbean = read(STORAGE_SERVICE_MBEAN)
    nodeprobe = read(NODEPROBE)
    checks.extend(
        [
            CheckResult("all with-port methods in StorageServiceMBean", STORAGE_SERVICE_MBEAN, all(method in mbean for method in WITH_PORT_METHODS)),
            CheckResult("all with-port methods routed by NodeProbe", NODEPROBE, all(method in nodeprobe for method in WITH_PORT_METHODS)),
        ]
    )

    status = read(STATUS)
    ring = read(RING)
    checks.extend(
        [
            CheckResult("status has short state markers", STATUS, all(token in status for token in ('"U"', '"D"', '"J"', '"L"', '"M"', '"N"'))),
            CheckResult("ring has long state markers", RING, all(token in ring for token in ('"Up"', '"Down"', '"Normal"', '"Joining"', '"Leaving"', '"Moving"'))),
            CheckResult("status ownership fallback is guarded", STATUS, "catch (IllegalStateException e)" in status and "catch (IllegalArgumentException ex)" in status),
            CheckResult("ring ownership fallback is guarded", RING, "catch (IllegalStateException ex)" in ring and "catch (IllegalArgumentException ex)" in ring),
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
            CheckResult("README references checker", README_DOC, CHECKER_DOC.split("/", 1)[1] in readme and "check-nodetool-status-ring-drift.py" in readme),
            CheckResult("source-map references matrix", SOURCE_MAP_DOC, MATRIX_DOC in source_map),
            CheckResult("source-map references checker", SOURCE_MAP_DOC, "research/tools/check-nodetool-status-ring-drift.py" in source_map),
            CheckResult("operations docs mention status/ring source", OPERATIONS_DOC, "Status.java" in operations and "Ring.java" in operations),
        ]
    )
    return checks


def check() -> tuple[dict[str, object], bool]:
    sources = source_checks()
    docs = doc_checks()
    result = {
        "scenario_ids": list(SCENARIO_IDS),
        "with_port_methods": list(WITH_PORT_METHODS),
        "source_checks": [entry.__dict__ for entry in sources],
        "doc_checks": [entry.__dict__ for entry in docs],
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check nodetool status/ring source/doc coverage.")
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
            print(f"OK nodetool status/ring checks passed ({len(result['scenario_ids'])} scenarios)")
        else:
            print("Nodetool status/ring checks failed.", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
