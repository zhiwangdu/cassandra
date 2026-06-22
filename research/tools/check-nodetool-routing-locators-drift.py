#!/usr/bin/env python3
#
# Source-only drift check for nodetool key routing and local SSTable locator research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

NODE_TOOL = "src/java/org/apache/cassandra/tools/NodeTool.java"
GET_ENDPOINTS = "src/java/org/apache/cassandra/tools/nodetool/GetEndpoints.java"
GET_SSTABLES = "src/java/org/apache/cassandra/tools/nodetool/GetSSTables.java"
DESCRIBE_RING = "src/java/org/apache/cassandra/tools/nodetool/DescribeRing.java"
NODEPROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
STORAGE_SERVICE_MBEAN = "src/java/org/apache/cassandra/service/StorageServiceMBean.java"
STORAGE_SERVICE = "src/java/org/apache/cassandra/service/StorageService.java"
TOKEN_RANGE = "src/java/org/apache/cassandra/service/TokenRange.java"
CFS_MBEAN = "src/java/org/apache/cassandra/db/ColumnFamilyStoreMBean.java"
CFS = "src/java/org/apache/cassandra/db/ColumnFamilyStore.java"

BOOLEAN_TEST = "test/distributed/org/apache/cassandra/distributed/test/BooleanTest.java"
GOSSIP_SETTLES_TEST = "test/distributed/org/apache/cassandra/distributed/test/GossipSettlesTest.java"
SCHEMA_CQL_HELPER_TEST = "test/unit/org/apache/cassandra/db/SchemaCQLHelperTest.java"

MATRIX_DOC = "research/module-nodetool-routing-locators-matrix.md"
CHECKER_DOC = "research/module-nodetool-routing-locators-drift-checker.md"
OPERATIONS_DOC = "research/module-operations-observability.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

SCENARIO_IDS = (
    "nodetool_routing_command_registry_contract",
    "nodetool_getendpoints_surface_contract",
    "nodetool_getendpoints_mbean_route_contract",
    "nodetool_getendpoints_partition_key_contract",
    "nodetool_describering_surface_contract",
    "nodetool_describering_storage_contract",
    "nodetool_describering_tokenrange_format_contract",
    "nodetool_getsstables_surface_contract",
    "nodetool_getsstables_cfs_contract",
    "nodetool_routing_existing_test_baseline",
)

SOURCE_TOKEN_CHECKS = {
    NODE_TOOL: (
        "DescribeRing.class",
        "GetEndpoints.class",
        "GetSSTables.class",
    ),
    GET_ENDPOINTS: (
        '@Command(name = "getendpoints", description = "Print the end points that owns the key")',
        '@Arguments(usage = "<keyspace> <table> <key>"',
        'checkArgument(args.size() == 3, "getendpoints requires keyspace, table and partition key arguments");',
        "if (printPort)",
        "probe.getEndpointsWithPort(ks, table, key)",
        "List<InetAddress> endpoints = probe.getEndpoints(ks, table, key);",
        "endpoint.getHostAddress()",
    ),
    GET_SSTABLES: (
        '@Command(name = "getsstables", description = "Print the sstable filenames that own the key")',
        'name = {"-hf", "--hex-format"}',
        '@Option(name={"-l", "--show-levels"}',
        '@Arguments(usage = "<keyspace> <cfname> <key>"',
        'checkArgument(args.size() == 3, "getsstables requires ks, cf and key args");',
        "showLevels && probe.isLeveledCompaction(ks, cf)",
        "probe.getSSTablesWithLevel(ks, cf, key, hexFormat)",
        "probe.getSSTables(ks, cf, key, hexFormat)",
        'level + ": " + sstable',
    ),
    DESCRIBE_RING: (
        '@Command(name = "describering", description = "Shows the token ranges info of a given keyspace")',
        '@Arguments(description = "The keyspace name", required = true)',
        'out.println("Schema Version:" + probe.getSchemaVersion());',
        'out.println("TokenRange: ");',
        "probe.describeRing(keyspace, printPort)",
        'out.println("\\t" + tokenRangeString);',
    ),
    NODEPROBE: (
        "public List<String> getEndpointsWithPort(String keyspace, String cf, String key)",
        "return ssProxy.getNaturalEndpointsWithPort(keyspace, cf, key);",
        "public List<InetAddress> getEndpoints(String keyspace, String cf, String key)",
        "return ssProxy.getNaturalEndpoints(keyspace, cf, key);",
        "public List<String> getSSTables(String keyspace, String cf, String key, boolean hexFormat)",
        "return cfsProxy.getSSTablesForKey(key, hexFormat);",
        "public Map<Integer, Set<String>> getSSTablesWithLevel(String keyspace, String cf, String key, boolean hexFormat)",
        "return cfsProxy.getSSTablesForKeyWithLevel(key, hexFormat);",
        "public boolean isLeveledCompaction(String keyspace, String cf)",
        "return cfsProxy.isLeveledCompaction();",
        "public List<String> describeRing(String keyspaceName, boolean withPort) throws IOException",
        "return withPort ? ssProxy.describeRingWithPortJMX(keyspaceName) : ssProxy.describeRingJMX(keyspaceName);",
    ),
    STORAGE_SERVICE_MBEAN: (
        "@Deprecated(since = \"4.0\") public List <String> describeRingJMX(String keyspace) throws IOException;",
        "public List<String> describeRingWithPortJMX(String keyspace) throws IOException;",
        "@Deprecated(since = \"4.0\") public List<InetAddress> getNaturalEndpoints(String keyspaceName, String cf, String key);",
        "public List<String> getNaturalEndpointsWithPort(String keyspaceName, String cf, String key);",
    ),
    STORAGE_SERVICE: (
        "public List<String> describeRingJMX(String keyspace) throws IOException",
        "public List<String> describeRingWithPortJMX(String keyspace) throws IOException",
        "private List<String> describeRingJMX(String keyspace, boolean withPort) throws IOException",
        "tokenRanges = describeRing(keyspace, false, withPort);",
        "result.add(tokenRange.toString(withPort));",
        "private List<TokenRange> describeRing(String keyspace, boolean includeOnlyLocalDC, boolean withPort) throws InvalidRequestException",
        'throw new InvalidRequestException("No such keyspace: " + keyspace);',
        "Keyspace.open(keyspace).getReplicationStrategy() instanceof LocalStrategy",
        "getRangeToAddressMap(keyspace)",
        "TokenRange.create(tf, entry.getKey(), ImmutableList.copyOf(entry.getValue().endpoints()), withPort)",
        "public List<String> getNaturalEndpointsWithPort(String keyspaceName, String cf, String key)",
        "return Replicas.stringify(getNaturalReplicasForToken(keyspaceName, cf, key), true);",
        "public EndpointsForToken getNaturalReplicasForToken(String keyspaceName, String cf, String key)",
        "return getNaturalReplicasForToken(keyspaceName, partitionKeyToBytes(keyspaceName, cf, key));",
        "Token token = tokenMetadata.partitioner.getToken(key);",
        "return Keyspace.open(keyspaceName).getReplicationStrategy().getNaturalReplicasForToken(token);",
        "private static ByteBuffer partitionKeyToBytes(String keyspaceName, String cf, String key)",
        "Schema.instance.getKeyspaceMetadata(keyspaceName)",
        "ksMetaData.getTableOrViewNullable(cf)",
        "return metadata.partitionKeyType.fromString(key);",
    ),
    TOKEN_RANGE: (
        "Holds token range informations for the sake of {@link StorageService#describeRing}.",
        "public static TokenRange create(Token.TokenFactory tokenFactory, Range<Token> range, List<InetAddressAndPort> endpoints, boolean withPorts)",
        "StorageService.instance.getNativeaddress(ep, withPorts)",
        "snitch.getDatacenter(ep)",
        "snitch.getRack(ep)",
        "public String toString(boolean withPorts)",
        'StringBuilder sb = new StringBuilder("TokenRange(");',
        'sb.append("start_token:").append(toStr(range.left));',
        'sb.append(", end_token:").append(toStr(range.right));',
        'sb.append(", endpoints:").append(hosts);',
        'sb.append(", rpc_endpoints:").append(rpcs);',
        'sb.append(", endpoint_details:").append(endpointDetails);',
        "Format matters for backward compatibility with describeRing()",
        'String.format("EndpointDetails(host:%s%s%s)", host.getHostAddress(withPorts), dcStr, rackStr)',
    ),
    CFS_MBEAN: (
        "public List<String> getSSTablesForKey(String key);",
        "public List<String> getSSTablesForKey(String key, boolean hexFormat);",
        "public Map<Integer, Set<String>> getSSTablesForKeyWithLevel(String key, boolean hexFormat);",
        "public boolean isLeveledCompaction();",
    ),
    CFS: (
        "WARNING: this returns the set of LIVE sstables only",
        "public List<String> getSSTablesForKey(String key, boolean hexFormat)",
        "return withSSTablesForKey(key, hexFormat, SSTableReader::getFilename);",
        "public Map<Integer, Set<String>> getSSTablesForKeyWithLevel(String key, boolean hexFormat)",
        "sstr -> Pair.create(sstr.getSSTableLevel(), sstr.getFilename())",
        "public <T> List<T> withSSTablesForKey(String key, boolean hexFormat, Function<SSTableReader, T> mapper)",
        "ByteBuffer keyBuffer = hexFormat ? ByteBufferUtil.hexToBytes(key) : metadata().partitionKeyType.fromString(key);",
        "DecoratedKey dk = decorateKey(keyBuffer);",
        "select(View.select(SSTableSet.LIVE, dk)).sstables",
        "sstr.getPosition(dk, SSTableReader.Operator.EQ, false) >= 0",
        "return compactionStrategyManager.isLeveledCompaction();",
    ),
    BOOLEAN_TEST: (
        "public void booleanTest() throws Throwable",
        'cluster.get(1).nodetoolResult("getsstables", KEYSPACE, "tbl", "1:true");',
    ),
    GOSSIP_SETTLES_TEST: (
        "ss.getNaturalEndpoints(SchemaConstants.DISTRIBUTED_KEYSPACE_NAME,",
        "ss.getNaturalEndpointsWithPort(SchemaConstants.DISTRIBUTED_KEYSPACE_NAME,",
        "ss.getNaturalEndpoints(SchemaConstants.DISTRIBUTED_KEYSPACE_NAME, ByteBufferUtil.EMPTY_BYTE_BUFFER)",
        "ss.getNaturalEndpointsWithPort(SchemaConstants.DISTRIBUTED_KEYSPACE_NAME, ByteBufferUtil.EMPTY_BYTE_BUFFER)",
    ),
    SCHEMA_CQL_HELPER_TEST: (
        "public void testBooleanCompositeKey() throws Throwable",
        'cfs.getSSTablesForKey("false:true");',
    ),
}

DOC_REQUIRED_TOKENS = (
    MATRIX_DOC,
    CHECKER_DOC,
    "check-nodetool-routing-locators-drift.py",
    GET_ENDPOINTS,
    GET_SSTABLES,
    DESCRIBE_RING,
    NODEPROBE,
    STORAGE_SERVICE_MBEAN,
    STORAGE_SERVICE,
    TOKEN_RANGE,
    CFS_MBEAN,
    CFS,
    BOOLEAN_TEST,
    GOSSIP_SETTLES_TEST,
    SCHEMA_CQL_HELPER_TEST,
    "nodetool getendpoints",
    "nodetool getsstables",
    "nodetool describering",
    "getNaturalEndpointsWithPort",
    "describeRingWithPortJMX",
    "getSSTablesForKeyWithLevel",
    "withSSTablesForKey",
    "TokenRange",
) + SCENARIO_IDS


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
        checks.extend(
            CheckResult(f"source token {token}", path, token in text)
            for token in tokens
        )

    node_tool = read(NODE_TOOL)
    checks.append(
        CheckResult(
            "registry order includes routing commands",
            NODE_TOOL,
            node_tool.index("DescribeRing.class") < node_tool.index("GetEndpoints.class") < node_tool.index("GetSSTables.class"),
        )
    )

    get_sstables = read(GET_SSTABLES)
    checks.append(
        CheckResult(
            "show levels gated by LCS",
            GET_SSTABLES,
            get_sstables.index("showLevels && probe.isLeveledCompaction") < get_sstables.index("probe.getSSTablesWithLevel"),
        )
    )
    checks.append(
        CheckResult(
            "plain sstable branch remains fallback",
            GET_SSTABLES,
            get_sstables.index("probe.getSSTablesWithLevel") < get_sstables.index("probe.getSSTables(ks, cf, key, hexFormat)"),
        )
    )

    storage_service = read(STORAGE_SERVICE)
    checks.append(
        CheckResult(
            "endpoint key decode precedes tokenization",
            STORAGE_SERVICE,
            storage_service.index("return getNaturalReplicasForToken(keyspaceName, partitionKeyToBytes(keyspaceName, cf, key));")
            < storage_service.index("Token token = tokenMetadata.partitioner.getToken(key);"),
        )
    )

    cfs = read(CFS)
    checks.append(
        CheckResult(
            "sstable lookup decodes before live selection",
            CFS,
            cfs.index("ByteBuffer keyBuffer = hexFormat ? ByteBufferUtil.hexToBytes(key) : metadata().partitionKeyType.fromString(key);")
            < cfs.index("select(View.select(SSTableSet.LIVE, dk)).sstables")
            < cfs.index("sstr.getPosition(dk, SSTableReader.Operator.EQ, false) >= 0"),
        )
    )
    return checks


def doc_checks() -> list[CheckResult]:
    matrix = read(MATRIX_DOC)
    checker = read(CHECKER_DOC)
    readme = read(README_DOC)
    source_map = read(SOURCE_MAP_DOC)
    operations = read(OPERATIONS_DOC)
    matrix_and_checker = matrix + "\n" + checker
    all_docs = "\n".join((matrix, checker, readme, source_map, operations))

    checks = [
        CheckResult(f"scenario documented {scenario}", f"{MATRIX_DOC} / {CHECKER_DOC}", documented(scenario, matrix_and_checker))
        for scenario in SCENARIO_IDS
    ]
    checks.extend(CheckResult(f"doc token {token}", "research docs", token in all_docs) for token in DOC_REQUIRED_TOKENS)
    checks.extend(
        [
            CheckResult("README references matrix", README_DOC, MATRIX_DOC.split("/", 1)[1] in readme),
            CheckResult("README references checker", README_DOC, CHECKER_DOC.split("/", 1)[1] in readme and "check-nodetool-routing-locators-drift.py" in readme),
            CheckResult("source-map references matrix", SOURCE_MAP_DOC, MATRIX_DOC in source_map),
            CheckResult("source-map references checker", SOURCE_MAP_DOC, "research/tools/check-nodetool-routing-locators-drift.py" in source_map),
            CheckResult("operations doc references commands", OPERATIONS_DOC, all(token in operations for token in ("getendpoints", "getsstables", "describering"))),
        ]
    )
    return checks


def check() -> tuple[dict[str, object], bool]:
    sources = source_checks()
    docs = doc_checks()
    result = {
        "scenario_ids": list(SCENARIO_IDS),
        "source_files": sorted(SOURCE_TOKEN_CHECKS),
        "matrix_doc": MATRIX_DOC,
        "checker_doc": CHECKER_DOC,
        "source_checks": [entry.__dict__ for entry in sources],
        "doc_checks": [entry.__dict__ for entry in docs],
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check nodetool routing/locator source/doc coverage.")
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
            print(f"OK nodetool routing/locator checks passed ({len(result['scenario_ids'])} scenarios)")
        else:
            print("Nodetool routing/locator checks failed.", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
