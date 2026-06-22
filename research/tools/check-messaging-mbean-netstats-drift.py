#!/usr/bin/env python3
#
# Source-only drift check for MessagingServiceMBean and nodetool netstats coverage.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

MBEAN_INTERFACE = "src/java/org/apache/cassandra/net/MessagingServiceMBean.java"
MBEAN_IMPL = "src/java/org/apache/cassandra/net/MessagingServiceMBeanImpl.java"
NODEPROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
NETSTATS = "src/java/org/apache/cassandra/tools/nodetool/NetStats.java"
NETSTATS_TEST = "test/unit/org/apache/cassandra/tools/nodetool/NetStatsTest.java"
GOSSIP_SETTLES_TEST = "test/distributed/org/apache/cassandra/distributed/test/GossipSettlesTest.java"
JMX_GETTER_CHECK_TEST = "test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java"

MATRIX_DOC = "research/module-messaging-mbean-netstats-matrix.md"
CHECKER_DOC = "research/module-messaging-mbean-netstats-drift-checker.md"
MESSAGING_DOC = "research/module-messaging-verb-semantics.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

EXPECTED_MBEAN_METHODS = (
    "getLargeMessagePendingTasks",
    "getLargeMessagePendingTasksWithPort",
    "getLargeMessageCompletedTasks",
    "getLargeMessageCompletedTasksWithPort",
    "getLargeMessageDroppedTasks",
    "getLargeMessageDroppedTasksWithPort",
    "getSmallMessagePendingTasks",
    "getSmallMessagePendingTasksWithPort",
    "getSmallMessageCompletedTasks",
    "getSmallMessageCompletedTasksWithPort",
    "getSmallMessageDroppedTasks",
    "getSmallMessageDroppedTasksWithPort",
    "getGossipMessagePendingTasks",
    "getGossipMessagePendingTasksWithPort",
    "getGossipMessageCompletedTasks",
    "getGossipMessageCompletedTasksWithPort",
    "getGossipMessageDroppedTasks",
    "getGossipMessageDroppedTasksWithPort",
    "getDroppedMessages",
    "getTotalTimeouts",
    "getTimeoutsPerHost",
    "getTimeoutsPerHostWithPort",
    "getBackPressurePerHost",
    "setBackPressureEnabled",
    "isBackPressureEnabled",
    "getVersion",
    "reloadSslCertificates",
)

NETSTATS_POOL_METHODS = (
    "getLargeMessagePendingTasksWithPort",
    "getLargeMessageCompletedTasksWithPort",
    "getLargeMessageDroppedTasksWithPort",
    "getSmallMessagePendingTasksWithPort",
    "getSmallMessageCompletedTasksWithPort",
    "getSmallMessageDroppedTasksWithPort",
    "getGossipMessagePendingTasksWithPort",
    "getGossipMessageCompletedTasksWithPort",
    "getGossipMessageDroppedTasksWithPort",
)

WITH_PORT_MIRROR_METHODS = (
    "getTimeoutsPerHost",
    "getLargeMessagePendingTasks",
    "getLargeMessageCompletedTasks",
    "getLargeMessageDroppedTasks",
    "getSmallMessagePendingTasks",
    "getSmallMessageCompletedTasks",
    "getSmallMessageDroppedTasks",
    "getGossipMessagePendingTasks",
    "getGossipMessageCompletedTasks",
    "getGossipMessageDroppedTasks",
)

SCENARIO_IDS = (
    "messaging_mbean_method_baseline",
    "messaging_mbean_registration_contract",
    "messaging_mbean_pool_counter_mapping",
    "messaging_mbean_timeout_drop_contract",
    "messaging_mbean_backpressure_removed_contract",
    "messaging_mbean_nodeprobe_routes",
    "messaging_netstats_pool_aggregation_contract",
    "messaging_mbean_with_port_compatibility_test",
    "messaging_mbean_tls_reload_route",
)

SOURCE_TOKEN_CHECKS = {
    MBEAN_IMPL: (
        'MBEAN_NAME = "org.apache.cassandra.net:type=MessagingService"',
        "MBeanWrapper.instance.registerMBean(this, MBEAN_NAME)",
        "metrics.scheduleLogging();",
        "entry.getValue().large.pendingCount()",
        "entry.getValue().large.sentCount()",
        "entry.getValue().large.dropped()",
        "entry.getValue().small.pendingCount()",
        "entry.getValue().small.sentCount()",
        "entry.getValue().small.dropped()",
        "entry.getValue().urgent.pendingCount()",
        "entry.getValue().urgent.sentCount()",
        "entry.getValue().urgent.dropped()",
        "entry.getKey().toString(false)",
        "entry.getKey().toString()",
        "return metrics.getDroppedMessages();",
        "InternodeOutboundMetrics.totalExpiredCallbacks.getCount()",
        "entry.getValue().expiredCallbacks()",
        'throw new UnsupportedOperationException("This feature has been removed")',
        "return false;",
        "SSLFactory.forceCheckCertFiles();",
        "return versions.get(address);",
    ),
    NODEPROBE: (
        "MessagingService.MBEAN_NAME",
        "msProxy = JMX.newMBeanProxy(mbeanServerConn, name, MessagingServiceMBean.class)",
        "return msProxy.getDroppedMessages();",
        "msProxy.reloadSslCertificates();",
        "public MessagingServiceMBean getMessagingServiceProxy()",
        "return msProxy;",
    ),
    NETSTATS: (
        '@Command(name = "netstats"',
        'name = {"-H", "--human-readable"}',
        "probe.getOperationMode()",
        "probe.getStreamStatus()",
        "if (!probe.isStarting())",
        "MessagingServiceMBean ms = probe.getMessagingServiceProxy();",
        '"Pool Name"',
        '"Large messages"',
        '"Small messages"',
        '"Gossip messages"',
    ),
    NETSTATS_TEST: (
        "public void testMaybeChangeDocs()",
        'ToolRunner.invokeNodetool("help", "netstats")',
        "public void testNetStats()",
        "Message.out(ECHO_REQ, NoPayload.noPayload)",
        'ToolRunner.invokeNodetool("netstats")',
        '"Gossip messages                 n/a         0              2         0"',
        "public void testHumanReadable()",
        "printReceivingSummaries(out, info, true)",
        "printSendingSummaries(out, info, true)",
    ),
    GOSSIP_SETTLES_TEST: (
        "MessagingService ms = MessagingService.instance();",
        "addPortToKeys(ms.getTimeoutsPerHost())",
        "addPortToKeys(ms.getLargeMessagePendingTasks())",
        "addPortToKeys(ms.getSmallMessagePendingTasks())",
        "addPortToKeys(ms.getGossipMessagePendingTasks())",
    ),
    JMX_GETTER_CHECK_TEST: (
        "private static final Set<String> IGNORE_ATTRIBUTES",
        "org.apache.cassandra.net:type=MessagingService:BackPressurePerHost",
        "testAllValidGetters(Cluster cluster)",
    ),
}

DOC_REQUIRED_TOKENS = (
    MATRIX_DOC,
    CHECKER_DOC,
    "check-messaging-mbean-netstats-drift.py",
    MBEAN_INTERFACE,
    MBEAN_IMPL,
    NODEPROBE,
    NETSTATS,
    NETSTATS_TEST,
    GOSSIP_SETTLES_TEST,
    JMX_GETTER_CHECK_TEST,
    "27 个方法",
    "27 methods",
    "13 deprecated",
    "10 个 with-port",
    "MessagingServiceMBean",
    "MessagingServiceMBeanImpl",
    "NetStats",
    "NodeProbe",
    "Large messages",
    "Small messages",
    "Gossip messages",
    "BackPressurePerHost",
    "SSLFactory.forceCheckCertFiles",
) + SCENARIO_IDS + EXPECTED_MBEAN_METHODS


@dataclass(frozen=True)
class CheckResult:
    name: str
    source: str
    ok: bool
    detail: str = ""


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def interface_methods() -> tuple[str, ...]:
    text = read(MBEAN_INTERFACE)
    methods = []
    pattern = re.compile(
        r"^\s*(?:public\s+)?[A-Za-z0-9_<>, ?]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^;]*\)\s*(?:throws\s+[A-Za-z0-9_, ]+)?;",
        re.M,
    )
    for match in pattern.finditer(text):
        methods.append(match.group(1))
    if not methods:
        raise ValueError(f"Could not parse interface methods from {MBEAN_INTERFACE}")
    return tuple(methods)


def deprecated_count() -> int:
    return read(MBEAN_INTERFACE).count('@Deprecated(since = "4.0")')


def source_checks() -> list[CheckResult]:
    methods = interface_methods()
    checks = [
        CheckResult("MessagingServiceMBean method order matches baseline", MBEAN_INTERFACE, methods == EXPECTED_MBEAN_METHODS, f"found {len(methods)}"),
        CheckResult("MessagingServiceMBean deprecated compatibility count", MBEAN_INTERFACE, deprecated_count() == 13, f"found {deprecated_count()}"),
        CheckResult("netstats with-port methods are interface methods", MBEAN_INTERFACE, all(method in methods for method in NETSTATS_POOL_METHODS)),
    ]

    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(CheckResult(f"source token contract {path}", path, all(token in text for token in tokens)))

    netstats_text = read(NETSTATS)
    checks.append(
        CheckResult(
            "NetStats uses all with-port pool methods",
            NETSTATS,
            all(f"ms.{method}().values()" in netstats_text for method in NETSTATS_POOL_METHODS),
        )
    )

    gossip_test = read(GOSSIP_SETTLES_TEST)
    checks.append(
        CheckResult(
            "GossipSettlesTest covers with-port mirror methods",
            GOSSIP_SETTLES_TEST,
            all(
                f"Assert.assertEquals(addPortToKeys(ms.{method}()), ms.{method}WithPort())" in gossip_test
                for method in WITH_PORT_MIRROR_METHODS
            ),
        )
    )
    return checks


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def doc_checks() -> list[CheckResult]:
    matrix = read(MATRIX_DOC)
    checker = read(CHECKER_DOC)
    messaging = read(MESSAGING_DOC)
    readme = read(README_DOC)
    source_map = read(SOURCE_MAP_DOC)
    all_docs = "\n".join((matrix, checker, messaging, readme, source_map))
    matrix_and_checker = matrix + "\n" + checker

    checks = [CheckResult(f"scenario documented {scenario}", f"{MATRIX_DOC} / {CHECKER_DOC}", documented(scenario, matrix_and_checker)) for scenario in SCENARIO_IDS]
    checks.extend(CheckResult(f"doc token {token}", "research docs", token in all_docs) for token in DOC_REQUIRED_TOKENS)
    checks.extend(
        [
            CheckResult("README references matrix", README_DOC, MATRIX_DOC.split("/", 1)[1] in readme),
            CheckResult("README references checker", README_DOC, CHECKER_DOC.split("/", 1)[1] in readme and "check-messaging-mbean-netstats-drift.py" in readme),
            CheckResult("source-map references matrix", SOURCE_MAP_DOC, MATRIX_DOC in source_map),
            CheckResult("source-map references checker", SOURCE_MAP_DOC, "research/tools/check-messaging-mbean-netstats-drift.py" in source_map),
            CheckResult("messaging verb doc closes old JMX gap", MESSAGING_DOC, "check-messaging-mbean-netstats-drift.py" in messaging),
        ]
    )
    return checks


def check() -> tuple[dict[str, object], bool]:
    methods = interface_methods()
    sources = source_checks()
    docs = doc_checks()
    result = {
        "method_count": len(methods),
        "deprecated_count": deprecated_count(),
        "methods": list(methods),
        "netstats_pool_methods": list(NETSTATS_POOL_METHODS),
        "with_port_mirror_methods": list(WITH_PORT_MIRROR_METHODS),
        "scenario_ids": list(SCENARIO_IDS),
        "source_checks": [entry.__dict__ for entry in sources],
        "doc_checks": [entry.__dict__ for entry in docs],
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check MessagingServiceMBean/netstats source/doc coverage.")
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
            print(f"OK messaging MBean/netstats checks passed ({result['method_count']} methods, {len(result['scenario_ids'])} scenarios)")
        else:
            print("Messaging MBean/netstats checks failed.", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
