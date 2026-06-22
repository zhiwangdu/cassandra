#!/usr/bin/env python3
#
# Source-only drift check for NodeProbe JMX proxies and FD/Gossip MBean coverage.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

NODEPROBE_SOURCE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
JMXTOOL_SOURCE = "src/java/org/apache/cassandra/tools/JMXTool.java"
FAILURE_DETECTOR_MBEAN = "src/java/org/apache/cassandra/gms/FailureDetectorMBean.java"
GOSSIPER_MBEAN = "src/java/org/apache/cassandra/gms/GossiperMBean.java"

FD_COMMAND_SOURCES = (
    "src/java/org/apache/cassandra/tools/nodetool/FailureDetectorInfo.java",
    "src/java/org/apache/cassandra/tools/nodetool/GossipInfo.java",
    "src/java/org/apache/cassandra/tools/nodetool/EnableGossip.java",
    "src/java/org/apache/cassandra/tools/nodetool/DisableGossip.java",
    "src/java/org/apache/cassandra/tools/nodetool/StatusGossip.java",
)

TARGET_DOCS = (
    "research/module-jmx-nodeprobe-fd-drift-checker.md",
    "research/module-observability-mapping.md",
    "research/module-gossip-messaging-deep-dive.md",
)

EXPECTED_NODEPROBE_PROXIES = (
    "StorageServiceMBean",
    "MessagingServiceMBean",
    "StreamManagerMBean",
    "CompactionManagerMBean",
    "FailureDetectorMBean",
    "CacheServiceMBean",
    "StorageProxyMBean",
    "HintsServiceMBean",
    "GCInspectorMXBean",
    "GossiperMBean",
    "BatchlogManagerMBean",
    "ActiveRepairServiceMBean",
    "AuditLogManagerMBean",
    "PasswordAuthenticator.CredentialsCacheMBean",
    "AuthorizationProxy.JmxPermissionsCacheMBean",
    "NetworkPermissionsCacheMBean",
    "PermissionsCacheMBean",
    "RolesCacheMBean",
    "CIDRPermissionsManagerMBean",
    "CIDRGroupsMappingManagerMBean",
    "CIDRFilteringMetricsTableMBean",
    "GuardrailsMBean",
    "AutoRepairServiceMBean",
)

EXPECTED_PLATFORM_PROXIES = (
    "MemoryMXBean",
    "RuntimeMXBean",
)

EXPECTED_JMXTOOL_PACKAGES = (
    "org.apache.cassandra.metrics",
    "org.apache.cassandra.db",
    "org.apache.cassandra.hints",
    "org.apache.cassandra.internal",
    "org.apache.cassandra.net",
    "org.apache.cassandra.request",
    "org.apache.cassandra.service",
)

EXPECTED_FAILURE_DETECTOR_METHODS = (
    "dumpInterArrivalTimes",
    "setPhiConvictThreshold",
    "getPhiConvictThreshold",
    "getAllEndpointStates",
    "getAllEndpointStatesWithResolveIp",
    "getAllEndpointStatesWithPort",
    "getAllEndpointStatesWithPortAndResolveIp",
    "getEndpointState",
    "getSimpleStates",
    "getSimpleStatesWithPort",
    "getDownEndpointCount",
    "getUpEndpointCount",
    "getPhiValues",
    "getPhiValuesWithPort",
)

EXPECTED_GOSSIPER_METHODS = (
    "getEndpointDowntime",
    "getCurrentGenerationNumber",
    "unsafeAssassinateEndpoint",
    "assassinateEndpoint",
    "reloadSeeds",
    "getSeeds",
    "getReleaseVersionsWithPort",
    "getLooseEmptyEnabled",
    "setLooseEmptyEnabled",
    "compareGossipAndTokenMetadata",
)

SOURCE_TOKEN_CHECKS = {
    NODEPROBE_SOURCE: (
        "fdProxy.getPhiValuesWithPort()",
        "fdProxy.getAllEndpointStatesWithPortAndResolveIp()",
        "fdProxy.getAllEndpointStatesWithResolveIp()",
        "fdProxy.getAllEndpointStatesWithPort()",
        "fdProxy.getAllEndpointStates()",
        "gossProxy.assassinateEndpoint(address)",
        "gossProxy.reloadSeeds()",
        "gossProxy.getSeeds()",
        "gossProxy.compareGossipAndTokenMetadata()",
        "ssProxy.stopGossiping()",
        "ssProxy.startGossiping()",
        "ssProxy.isGossipRunning()",
    ),
    "src/java/org/apache/cassandra/gms/FailureDetector.java": (
        'MBEAN_NAME = "org.apache.cassandra.net:type=FailureDetector"',
        "MBeanWrapper.instance.registerMBean(this, MBEAN_NAME)",
    ),
    "src/java/org/apache/cassandra/gms/Gossiper.java": (
        'MBEAN_NAME = "org.apache.cassandra.net:type=Gossiper"',
        "MBeanWrapper.instance.registerMBean(this, MBEAN_NAME)",
        "FailureDetector.instance.forceConviction(endpoint)",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/FailureDetectorInfo.java": (
        "probe.getFailureDetectorPhilValues(printPort)",
        '"Endpoint"',
        '"Phi"',
    ),
    "src/java/org/apache/cassandra/tools/nodetool/GossipInfo.java": (
        "--resolve-ip",
        "probe.getGossipInfo(printPort, resolveIp)",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/EnableGossip.java": (
        "probe.startGossiping()",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/DisableGossip.java": (
        "probe.stopGossiping()",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/StatusGossip.java": (
        "probe.isGossipRunning()",
        '"running"',
        '"not running"',
    ),
}

SCENARIO_IDS = (
    "jmx_nodeprobe_proxy_baseline",
    "jmx_platform_mxbean_baseline",
    "jmx_tool_metric_package_baseline",
    "jmx_failure_detector_mbean_methods",
    "jmx_gossiper_mbean_methods",
    "jmx_fd_gossip_nodetool_routes",
    "jmx_compatibility_test_surface",
)

DOC_REQUIRED_TOKENS = (
    "23 NodeProbe service MBean proxies",
    "2 platform MXBean proxies",
    "7 JMXTool metric packages",
    "14 FailureDetectorMBean methods",
    "10 GossiperMBean methods",
    NODEPROBE_SOURCE,
    JMXTOOL_SOURCE,
    FAILURE_DETECTOR_MBEAN,
    GOSSIPER_MBEAN,
    "FailureDetectorInfo.java",
    "GossipInfo.java",
    "EnableGossip.java",
    "DisableGossip.java",
    "StatusGossip.java",
    "NodeProbeTest.java",
    "JMXToolTest.java",
    "JMXCompatibilityTest.java",
    "JMXGetterCheckTest.java",
    "GossipInfoTest.java",
) + EXPECTED_NODEPROBE_PROXIES + EXPECTED_JMXTOOL_PACKAGES + EXPECTED_FAILURE_DETECTOR_METHODS + EXPECTED_GOSSIPER_METHODS


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def connect_body() -> str:
    text = read(NODEPROBE_SOURCE)
    match = re.search(r"protected void connect\(\) throws IOException\s*\{(.*?)\n    private RMIClientSocketFactory", text, re.S)
    if not match:
        raise ValueError("Could not locate NodeProbe.connect() body")
    return match.group(1)


def nodeprobe_proxy_classes() -> tuple[str, ...]:
    body = connect_body()
    return tuple(re.findall(r"JMX\.newMBeanProxy\([^;]+?,\s*([A-Za-z0-9_.$]+)\.class\)", body, re.S))


def platform_proxy_classes() -> tuple[str, ...]:
    body = connect_body()
    return tuple(re.findall(r"newPlatformMXBeanProxy\([^;]+?,\s*([A-Za-z0-9_.$]+)\.class\)", body, re.S))


def jmxtool_packages() -> tuple[str, ...]:
    text = read(JMXTOOL_SOURCE)
    match = re.search(r"METRIC_PACKAGES\s*=\s*Arrays\.asList\((.*?)\);", text, re.S)
    if not match:
        raise ValueError("Could not locate JMXTool.METRIC_PACKAGES")
    return tuple(re.findall(r'"([^"]+)"', match.group(1)))


def interface_methods(path: str) -> tuple[str, ...]:
    text = read(path)
    methods = re.findall(
        r"\bpublic\s+[A-Za-z0-9_<>, ?\[\]\.]+\s+([a-z][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*(?:throws\s+[A-Za-z0-9_., ]+)?;",
        text,
    )
    return tuple(methods)


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def source_checks() -> tuple[list[Check], dict[str, object]]:
    proxies = nodeprobe_proxy_classes()
    platform_proxies = platform_proxy_classes()
    packages = jmxtool_packages()
    fd_methods = interface_methods(FAILURE_DETECTOR_MBEAN)
    gossiper_methods = interface_methods(GOSSIPER_MBEAN)

    checks = [
        Check("NodeProbe.connect service proxy classes match baseline", NODEPROBE_SOURCE, proxies == EXPECTED_NODEPROBE_PROXIES),
        Check("NodeProbe.connect platform MXBean classes match baseline", NODEPROBE_SOURCE, platform_proxies == EXPECTED_PLATFORM_PROXIES),
        Check("JMXTool metric package allowlist matches baseline", JMXTOOL_SOURCE, packages == EXPECTED_JMXTOOL_PACKAGES),
        Check("FailureDetectorMBean methods match baseline", FAILURE_DETECTOR_MBEAN, fd_methods == EXPECTED_FAILURE_DETECTOR_METHODS),
        Check("GossiperMBean methods match baseline", GOSSIPER_MBEAN, gossiper_methods == EXPECTED_GOSSIPER_METHODS),
    ]

    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(Check(f"source token contract {path}", path, all(token in text for token in tokens)))

    metadata = {
        "nodeprobe_proxy_count": len(proxies),
        "platform_proxy_count": len(platform_proxies),
        "jmxtool_package_count": len(packages),
        "failure_detector_method_count": len(fd_methods),
        "gossiper_method_count": len(gossiper_methods),
        "nodeprobe_proxies": list(proxies),
        "platform_proxies": list(platform_proxies),
        "jmxtool_packages": list(packages),
        "failure_detector_methods": list(fd_methods),
        "gossiper_methods": list(gossiper_methods),
    }
    return checks, metadata


def doc_text() -> str:
    return "\n".join(read(path) for path in TARGET_DOCS)


def doc_checks() -> list[Check]:
    text = doc_text()
    checks = [Check(f"doc scenario {scenario}", " / ".join(TARGET_DOCS), documented(scenario, text)) for scenario in SCENARIO_IDS]
    checks.extend(Check(f"doc token {token}", " / ".join(TARGET_DOCS), token in text) for token in DOC_REQUIRED_TOKENS)
    return checks


def check() -> tuple[dict[str, object], bool]:
    sources, metadata = source_checks()
    docs = doc_checks()
    result = {
        **metadata,
        "docs": list(TARGET_DOCS),
        "fd_command_sources": list(FD_COMMAND_SOURCES),
        "scenario_ids": list(SCENARIO_IDS),
        "source_checks": [entry.__dict__ for entry in sources],
        "doc_checks": [entry.__dict__ for entry in docs],
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check NodeProbe JMX and FD/Gossip surface drift in research docs.")
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
        print(f"OK NodeProbe service MBean proxies: {result['nodeprobe_proxy_count']} proxies")
        print(f"OK NodeProbe platform MXBean proxies: {result['platform_proxy_count']} proxies")
        print(f"OK JMXTool metric packages: {result['jmxtool_package_count']} packages")
        print(f"OK FailureDetectorMBean methods: {result['failure_detector_method_count']} methods")
        print(f"OK GossiperMBean methods: {result['gossiper_method_count']} methods")
        failed_sources = [entry for entry in result["source_checks"] if not entry["ok"]]
        failed_docs = [entry for entry in result["doc_checks"] if not entry["ok"]]
        if failed_sources:
            print("Failed source checks:")
            for entry in failed_sources:
                print(f"  {entry['name']} ({entry['source']})")
        if failed_docs:
            print("Failed doc checks:")
            for entry in failed_docs:
                print(f"  {entry['name']} ({entry['source']})")
        if ok:
            print("NodeProbe JMX and FD/Gossip research docs are in sync with checked source contracts.")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
