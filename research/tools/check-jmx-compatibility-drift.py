#!/usr/bin/env python3
#
# Source-only drift check for JMX compatibility dump research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

JMX_TOOL = "src/java/org/apache/cassandra/tools/JMXTool.java"
JMX_SERVER_UTILS = "src/java/org/apache/cassandra/utils/JMXServerUtils.java"
CQL_TESTER = "test/unit/org/apache/cassandra/cql3/CQLTester.java"
JMX_COMPATIBILITY_TEST = "test/unit/org/apache/cassandra/tools/JMXCompatibilityTest.java"
JMX_TOOL_TEST = "test/unit/org/apache/cassandra/tools/JMXToolTest.java"
JMX_STANDARDS_TEST = "test/unit/org/apache/cassandra/tools/JMXStandardsTest.java"
BREAKS_JMX = "src/java/org/apache/cassandra/utils/BreaksJMX.java"
JMX_GETTER_CHECK_TEST = "test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java"
JMX_FEATURE_TEST = "test/distributed/org/apache/cassandra/distributed/test/jmx/JMXFeatureTest.java"
ISOLATED_JMX = "test/distributed/org/apache/cassandra/distributed/impl/IsolatedJmx.java"

TARGET_DOCS = (
    "research/module-jmx-compatibility-dump-matrix.md",
    "research/module-jmx-compatibility-drift-checker.md",
    "research/README.md",
    "research/notes/source-map.md",
)

DUMP_BASELINE = {
    "test/data/jmxdump/cassandra-3.0-jmx.yaml": {"objects": 3855, "attributes": 18062, "operations": 5624},
    "test/data/jmxdump/cassandra-3.11-jmx.yaml": {"objects": 4493, "attributes": 21006, "operations": 6642},
    "test/data/jmxdump/cassandra-4.0-jmx.yaml": {"objects": 7426, "attributes": 42633, "operations": 11106},
    "test/data/jmxdump/cassandra-4.1-jmx.yaml": {"objects": 7426, "attributes": 42633, "operations": 11106},
}

SCENARIO_IDS = (
    "jmx_compat_dump_gold_files",
    "jmx_compat_diff_direction",
    "jmx_compat_exclusion_contract",
    "jmx_compat_dump_generation_workload",
    "jmx_tool_dump_model",
    "jmx_tool_diff_semantics",
    "jmx_standards_mbean_type_gate",
    "jmx_getter_runtime_surface",
    "jmx_distributed_isolated_server",
    "jmx_compatibility_ci_gap",
)

SOURCE_TOKEN_CHECKS = {
    JMX_COMPATIBILITY_TEST: (
        "public void diff30()",
        "public void diff311()",
        "public void diff40()",
        "public void diff41()",
        "tools/bin/jmxtool dump -f yaml --url service:jmx:rmi:///jndi/rmi://",
        '"tools/bin/jmxtool"',
        '"diff"',
        '"-f"',
        '"yaml"',
        '"--ignore-missing-on-left"',
        "test/data/jmxdump/cassandra-3.0-jmx.yaml",
        "test/data/jmxdump/cassandra-3.11-jmx.yaml",
        "test/data/jmxdump/cassandra-4.0-jmx.yaml",
        "test/data/jmxdump/cassandra-4.1-jmx.yaml",
        "BtiFormat.isSelected()",
        "CASSANDRA-11115",
        "CASSANDRA-13910",
        "CASSANDRA-15939",
        "CASSANDRA-17056",
        "CASSANDRA-18313",
        "CASSANDRA-18959",
        "org.apache.cassandra.metrics:type=BufferPool,name=(Misses|Size)",
        "org.apache.cassandra.metrics:type=DroppedMessage",
        "org.apache.cassandra.request:type=ReadRepairStage",
        "org.apache.cassandra.db:type=HintedHandoffManager",
        "RPCServerRunning",
        "MaxNativeProtocolVersion",
        "HostIdMap",
        "startRPCServer",
        "stopRPCServer",
        "forceRepairAsync",
        "forceRepairRangeAsync",
        "beginLocalSampling",
        "finishLocalSampling",
        "scrub\\\\(p1:boolean,p2:boolean,p3:java.lang.String,p4:java.lang.String\\\\[\\\\]\\\\):int",
        "Assertions.assertThat(result.getStdout()).isEmpty();",
    ),
    JMX_TOOL: (
        "private static final List<String> METRIC_PACKAGES = Arrays.asList",
        '@Command(name = "dump", description = "Dump the Apache Cassandra JMX objects and metadata.")',
        '@Command(name = "diff", description = "Diff two jmx dump files and report their differences")',
        'name = { "-u", "--url" }',
        'name = { "-f", "--format" }',
        'name = { "--ignore-missing-on-left" }',
        'name = { "--ignore-missing-on-right" }',
        'name = "--exclude-object"',
        'name = "--exclude-attribute"',
        'name = "--exclude-operation"',
        "DiffResult<Attribute> attributes = diff(leftInfo.attributeSet(), rightInfo.attributeSet(), attribute ->",
        "DiffResult<Operation> operations = diff(leftInfo.operationSet(), rightInfo.operationSet(), operation ->",
        "operation.toString().replaceAll(\" +\", \"\")",
        "rightInfo.getOperation(o.name).ifPresent(match ->",
        "leftInfo.getOperation(o.name).ifPresent(match ->",
        "for (String pkg : new TreeSet<>(METRIC_PACKAGES))",
        "mbsc.queryNames(new ObjectName(pkg + \":*\"), null)",
        "MBeanInfo info = mbsc.getMBeanInfo(name);",
        "map.put(name.toString(), Info.from(info));",
        "private static String normalizeType(String type)",
        "private static Info from(MBeanInfo info)",
        "private static Attribute from(MBeanAttributeInfo info)",
        "private static Operation from(MBeanOperationInfo info)",
        "private static Parameter from(MBeanParameterInfo info)",
    ),
    JMX_TOOL_TEST: (
        "public void jsonSerde()",
        "public void yamlSerde()",
        "public void cliHelpDiff()",
        "public void cliHelpDump()",
        "jmxtool diff - Diff two jmx dump files and report their differences",
        "jmxtool dump - Dump the Apache Cassandra JMX objects and metadata.",
        "deserialize(serialize(value)) == value failed",
    ),
    JMX_STANDARDS_TEST: (
        "private static final Set<Class<?>> ALLOWED_TYPES",
        "private static final Set<Class<?>> DANGEROUS_TYPES",
        "Pattern.compile(\".*MBean$\")",
        "Assertions.assertThat(klass).isInterface();",
        "method.isAnnotationPresent(BreaksJMX.class)",
        "Error at signature %s; type %s is not in the supported set of types",
    ),
    BREAKS_JMX: (
        "public @interface BreaksJMX",
    ),
    JMX_GETTER_CHECK_TEST: (
        "private static final Set<String> IGNORE_ATTRIBUTES",
        "private static final Set<String> IGNORE_OPERATIONS",
        "mbsc.queryNames(null, null)",
        "mbsc.getMBeanInfo(name)",
        "if (!a.isReadable() || IGNORE_ATTRIBUTES.contains(fqn))",
        "mbsc.getAttribute(name, a.getName());",
        "if (o.getSignature().length != 0 || IGNORE_OPERATIONS.contains(fqn))",
        "mbsc.invoke(name, o.getName(), new Object[0], new String[0]);",
        "testAllValidGetters(Cluster cluster)",
        "org.apache.cassandra.net:type=MessagingService:BackPressurePerHost",
        "org.apache.cassandra.db:type=StorageService:stopDaemon",
    ),
    JMX_FEATURE_TEST: (
        "testMultipleNetworkInterfacesProvisioning",
        "testOneNetworkInterfaceProvisioning",
        "testShutDownAndRestartInstances",
        "testAllValidGetters(cluster)",
        "mbsc.getDefaultDomain()",
        "startsWith(JMXUtil.getJmxHost(config) + ':' + config.jmxPort())",
        "nodetoolResult(\"status\")",
    ),
    ISOLATED_JMX: (
        "public void startJmx()",
        "public void stopJmx()",
        "ORG_APACHE_CASSANDRA_DISABLE_MBEAN_REGISTRATION.setBoolean(false);",
        "new MBeanWrapper.InstanceMBeanWrapper(hostname + \":\" + jmxPort)",
        "env.put(\"jmx.remote.x.daemon\", \"true\");",
        "registry.setRemoteServerStub(jmxRmiServer.toStub());",
        "waitForJmxAvailability(env);",
        "clearMapField(TCPEndpoint.class, null, \"localEndpoints\", this::endpointCreateByThisInstance);",
    ),
    CQL_TESTER: (
        "public static void startJMXServer() throws Exception",
        "jmxHost = loopback.getHostAddress();",
        "jmxPort = getAutomaticallyAllocatedPort(loopback);",
        "jmxServer = JMXServerUtils.createJMXServer(jmxPort, true);",
        "service:jmx:rmi:///jndi/rmi://%s:%d/jmxrmi",
    ),
    JMX_SERVER_UTILS: (
        "public static JMXConnectorServer createJMXServer(int port, String hostname, boolean local)",
        "configureJmxSocketFactories(serverAddress, local)",
        "configureJmxAuthentication()",
        "configureSecureCredentials()",
        "configureJmxAuthorization(env)",
        "env.put(\"jmx.remote.x.daemon\", \"true\");",
        "new RMIJRMPServerImpl",
        "new RMIConnectorServer(serviceURL, env, server, ManagementFactory.getPlatformMBeanServer())",
        "logJmxServiceUrl(serverAddress, port);",
    ),
}

DOC_REQUIRED_TOKENS = (
    "4 个历史 JMX gold dump",
    "3855",
    "4493",
    "7426",
    "18062",
    "21006",
    "42633",
    "5624",
    "6642",
    "11106",
    "JMXCompatibilityTest",
    "JMXToolTest",
    "JMXStandardsTest",
    "JMXGetterCheckTest",
    "JMXFeatureTest",
    "IsolatedJmx",
    "JMXServerUtils",
    "tools/bin/jmxtool dump",
    "tools/bin/jmxtool diff",
    "--ignore-missing-on-left",
    "BtiFormat.isSelected()",
    "METRIC_PACKAGES",
    "Attribute(name,type)",
    "Operation(name,parameters,returnType)",
    "source-only",
    "runtime evidence",
    "module-jmx-compatibility-dump-matrix.md",
    "module-jmx-compatibility-drift-checker.md",
    "check-jmx-compatibility-drift.py",
) + tuple(DUMP_BASELINE.keys()) + SCENARIO_IDS

KEY_DUMP_OBJECTS = (
    "org.apache.cassandra.db:type=BatchlogManager:",
    "org.apache.cassandra.db:type=Caches:",
    "org.apache.cassandra.db:type=StorageService:",
    "org.apache.cassandra.metrics:type=ClientRequest,scope=Read,name=Latency:",
    "org.apache.cassandra.metrics:type=ClientRequest,scope=Write,name=Latency:",
)


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def dump_counts(path: str) -> dict[str, int]:
    text = read(path)
    return {
        "objects": len(re.findall(r"^org\.apache\.cassandra\.", text, re.M)),
        "attributes": len(re.findall(r"^  - \{access:", text, re.M)),
        "operations": len(re.findall(r"^  - name:", text, re.M)),
    }


def source_checks() -> tuple[list[Check], dict[str, object]]:
    checks: list[Check] = []
    dump_metadata: dict[str, dict[str, int]] = {}

    actual_dump_files = tuple(sorted(str(path.relative_to(REPO_ROOT)) for path in (REPO_ROOT / "test/data/jmxdump").glob("*.yaml")))
    expected_dump_files = tuple(sorted(DUMP_BASELINE))
    checks.append(Check("JMX gold dump file set matches baseline", "test/data/jmxdump", actual_dump_files == expected_dump_files))

    for path, expected in DUMP_BASELINE.items():
        actual = dump_counts(path)
        dump_metadata[path] = actual
        checks.append(Check(f"dump object count {path}", path, actual["objects"] == expected["objects"]))
        checks.append(Check(f"dump attribute count {path}", path, actual["attributes"] == expected["attributes"]))
        checks.append(Check(f"dump operation count {path}", path, actual["operations"] == expected["operations"]))
        text = read(path)
        for token in KEY_DUMP_OBJECTS:
            checks.append(Check(f"dump key object {path} contains {token}", path, token in text))

    compat_text = read(JMX_COMPATIBILITY_TEST)
    referenced_dumps = tuple(re.findall(r'"(test/data/jmxdump/cassandra-[^"]+-jmx\.yaml)"', compat_text))
    checks.append(Check("JMXCompatibilityTest references expected dumps in order", JMX_COMPATIBILITY_TEST, referenced_dumps == tuple(DUMP_BASELINE.keys())))

    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(Check(f"source token contract {path}", path, all(token in text for token in tokens)))

    metadata: dict[str, object] = {
        "dump_files": list(actual_dump_files),
        "dump_counts": dump_metadata,
        "referenced_dumps": list(referenced_dumps),
        "scenario_ids": list(SCENARIO_IDS),
    }
    return checks, metadata


def doc_checks() -> list[Check]:
    docs_text = "\n".join(read(path) for path in TARGET_DOCS)
    checks = [Check(f"doc token {token}", ",".join(TARGET_DOCS), token in docs_text) for token in DOC_REQUIRED_TOKENS]
    return checks


def run_checks() -> tuple[list[Check], dict[str, object]]:
    checks, metadata = source_checks()
    checks.extend(doc_checks())
    return checks, metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="Check JMX compatibility dump research for source/doc drift.")
    parser.add_argument("--json", action="store_true", help="emit JSON metadata and check results")
    args = parser.parse_args()

    try:
        checks, metadata = run_checks()
    except Exception as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2

    failed = [check for check in checks if not check.ok]
    if args.json:
        print(json.dumps({
            "ok": not failed,
            "metadata": metadata,
            "checks": [check.__dict__ for check in checks],
            "failed": [check.__dict__ for check in failed],
        }, indent=2, sort_keys=True))
    elif failed:
        for check in failed:
            print(f"FAIL {check.name} ({check.source})")
    else:
        counts = metadata["dump_counts"]
        total_objects = sum(item["objects"] for item in counts.values())
        total_attributes = sum(item["attributes"] for item in counts.values())
        total_operations = sum(item["operations"] for item in counts.values())
        print(
            "OK JMX compatibility drift checks passed "
            f"({len(checks)} checks, {len(counts)} dumps, "
            f"{total_objects} objects, {total_attributes} attributes, {total_operations} operations)"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
