#!/usr/bin/env python3
#
# Source-only drift check for dynamic snitch topology regression coverage.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

SOURCE_PATHS = {
    "dynamic_snitch": "src/java/org/apache/cassandra/locator/DynamicEndpointSnitch.java",
    "dynamic_snitch_mbean": "src/java/org/apache/cassandra/locator/DynamicEndpointSnitchMBean.java",
    "config": "src/java/org/apache/cassandra/config/Config.java",
    "properties": "src/java/org/apache/cassandra/config/CassandraRelevantProperties.java",
    "database_descriptor": "src/java/org/apache/cassandra/config/DatabaseDescriptor.java",
    "storage_service": "src/java/org/apache/cassandra/service/StorageService.java",
    "storage_service_mbean": "src/java/org/apache/cassandra/service/StorageServiceMBean.java",
    "storage_proxy": "src/java/org/apache/cassandra/service/StorageProxy.java",
    "replica_plans": "src/java/org/apache/cassandra/locator/ReplicaPlans.java",
    "node_probe": "src/java/org/apache/cassandra/tools/NodeProbe.java",
    "yaml": "conf/cassandra.yaml",
    "yaml_latest": "conf/cassandra_latest.yaml",
    "snitch_test": "test/unit/org/apache/cassandra/locator/DynamicEndpointSnitchTest.java",
    "decommission_test": "test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidTimeouts.java",
    "decommission_read_test": "test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidReadTimeoutsTest.java",
    "decommission_write_test": "test/distributed/org/apache/cassandra/distributed/test/topology/DecommissionAvoidWriteTimeoutsTest.java",
    "batchlog_test": "test/unit/org/apache/cassandra/batchlog/BatchlogEndpointFilterTest.java",
    "jmx_test": "test/distributed/org/apache/cassandra/distributed/test/jmx/JMXGetterCheckTest.java",
}

TARGET_DOCS = (
    "research/module-dynamic-snitch-topology-regression.md",
    "research/module-dynamic-snitch-drift-checker.md",
)

SCENARIO_IDS = (
    "score_order_zero_threshold",
    "badness_threshold_preserves_subsnitch",
    "decommission_severity_gossip",
    "decommission_read_write_trace_regression",
    "remote_write_forwarding_severity_filter",
    "batchlog_dynamic_snitch_selection",
    "jmx_dynamic_endpoint_snitch_observability",
    "runtime_update_snitch_config",
)

DOC_REQUIRED_TOKENS = (
    "DynamicEndpointSnitch",
    "sortedByProximity",
    "sortedByProximityWithScore",
    "sortedByProximityWithBadness",
    "updateScores",
    "ApplicationState.SEVERITY",
    "severity_during_decommission",
    "dynamic_snitch_update_interval",
    "dynamic_snitch_reset_interval",
    "dynamic_snitch_badness_threshold",
    "StorageService.updateSnitch",
    "StorageProxy.pickReplica",
    "ReplicaPlans.filterBatchlogEndpoints",
    "DynamicEndpointSnitchMBean",
    "DecommissionAvoidTimeouts",
    "DecommissionAvoidReadTimeoutsTest",
    "DecommissionAvoidWriteTimeoutsTest",
    "BatchlogEndpointFilterTest",
)


@dataclass(frozen=True)
class SourceCheck:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def contains_regex(text: str, pattern: str) -> bool:
    return re.search(pattern, text, re.S) is not None


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def source_checks() -> list[SourceCheck]:
    dynamic = read(SOURCE_PATHS["dynamic_snitch"])
    mbean = read(SOURCE_PATHS["dynamic_snitch_mbean"])
    config = read(SOURCE_PATHS["config"])
    properties = read(SOURCE_PATHS["properties"])
    descriptor = read(SOURCE_PATHS["database_descriptor"])
    service = read(SOURCE_PATHS["storage_service"])
    service_mbean = read(SOURCE_PATHS["storage_service_mbean"])
    proxy = read(SOURCE_PATHS["storage_proxy"])
    replica_plans = read(SOURCE_PATHS["replica_plans"])
    node_probe = read(SOURCE_PATHS["node_probe"])
    yaml = read(SOURCE_PATHS["yaml"])
    yaml_latest = read(SOURCE_PATHS["yaml_latest"])
    snitch_test = read(SOURCE_PATHS["snitch_test"])
    decom_test = read(SOURCE_PATHS["decommission_test"])
    decom_read = read(SOURCE_PATHS["decommission_read_test"])
    decom_write = read(SOURCE_PATHS["decommission_write_test"])
    batchlog_test = read(SOURCE_PATHS["batchlog_test"])
    jmx_test = read(SOURCE_PATHS["jmx_test"])

    checks: list[SourceCheck] = [
        SourceCheck("DynamicEndpointSnitch implements latency subscriber and MBean", SOURCE_PATHS["dynamic_snitch"], "implements LatencySubscribers.Subscriber, DynamicEndpointSnitchMBean" in dynamic),
        SourceCheck("DynamicEndpointSnitch uses severity property", SOURCE_PATHS["dynamic_snitch"], "IGNORE_DYNAMIC_SNITCH_SEVERITY" in dynamic and "USE_SEVERITY" in dynamic),
        SourceCheck("DynamicEndpointSnitch config snapshots", SOURCE_PATHS["dynamic_snitch"], all(token in dynamic for token in ("dynamicUpdateInterval", "dynamicResetInterval", "dynamicBadnessThreshold"))),
        SourceCheck("DynamicEndpointSnitch registers expected MBean", SOURCE_PATHS["dynamic_snitch"], '"org.apache.cassandra.db:type=DynamicEndpointSnitch"' in dynamic),
        SourceCheck("DynamicEndpointSnitch applyConfigChanges", SOURCE_PATHS["dynamic_snitch"], "public void applyConfigChanges()" in dynamic and "scheduleWithFixedDelay(update" in dynamic and "scheduleWithFixedDelay(reset" in dynamic),
        SourceCheck("DynamicEndpointSnitch threshold branch", SOURCE_PATHS["dynamic_snitch"], contains_regex(dynamic, r"dynamicBadnessThreshold\s*==\s*0\s*\?\s*sortedByProximityWithScore\s*\(\s*address\s*,\s*unsortedAddresses\s*\)\s*:\s*sortedByProximityWithBadness")),
        SourceCheck("DynamicEndpointSnitch score branch copies score snapshot", SOURCE_PATHS["dynamic_snitch"], "private <C extends ReplicaCollection<? extends C>> C sortedByProximityWithScore" in dynamic and "final HashMap<InetAddressAndPort, Double> scores = this.scores" in dynamic),
        SourceCheck("DynamicEndpointSnitch badness branch preserves subsnitch", SOURCE_PATHS["dynamic_snitch"], "subsnitch.sortedByProximity(address, replicas)" in dynamic and "double badnessThreshold = 1.0 + dynamicBadnessThreshold" in dynamic),
        SourceCheck("DynamicEndpointSnitch fallback to score order", SOURCE_PATHS["dynamic_snitch"], "return sortedByProximityWithScore(address, replicas)" in dynamic),
        SourceCheck("DynamicEndpointSnitch receiveTiming and updateScores", SOURCE_PATHS["dynamic_snitch"], "public void receiveTiming" in dynamic and "public void updateScores()" in dynamic and "MessagingService.instance().latencySubscribers.subscribe(this)" in dynamic),
        SourceCheck("DynamicEndpointSnitch score includes severity", SOURCE_PATHS["dynamic_snitch"], "score += getSeverity(entry.getKey())" in dynamic),
        SourceCheck("DynamicEndpointSnitch scores MBean getters", SOURCE_PATHS["dynamic_snitch"], "public Map<String, Double> getScoresWithPort()" in dynamic and "public Map<InetAddress, Double> getScores()" in dynamic),
        SourceCheck("DynamicEndpointSnitch severity gossip write/read", SOURCE_PATHS["dynamic_snitch"], "addLocalApplicationState(ApplicationState.SEVERITY" in dynamic and "state.getApplicationState(ApplicationState.SEVERITY)" in dynamic),
        SourceCheck("DynamicEndpointSnitch range merge score gate", SOURCE_PATHS["dynamic_snitch"], "public boolean isWorthMergingForRangeQuery" in dynamic and "RANGE_MERGING_PREFERENCE" in dynamic),
    ]

    for method in ("getScoresWithPort", "getScores", "getUpdateInterval", "getResetInterval", "getBadnessThreshold", "getSubsnitchClassName", "dumpTimings", "setSeverity", "getSeverity"):
        checks.append(SourceCheck(f"DynamicEndpointSnitchMBean method {method}", SOURCE_PATHS["dynamic_snitch_mbean"], method in mbean))

    for token in ("dynamic_snitch = true", "dynamic_snitch_update_interval", "dynamic_snitch_reset_interval", "dynamic_snitch_badness_threshold = 1.0", "severity_during_decommission"):
        checks.append(SourceCheck(f"Config contains {token}", SOURCE_PATHS["config"], token in config))

    checks.extend(
        [
            SourceCheck("Config batchlog dynamic strategies", SOURCE_PATHS["config"], "dynamic_remote(true, false)" in config and "dynamic(true, true)" in config and "useDynamicSnitchScores" in config),
            SourceCheck("Relevant property ignore dynamic snitch severity", SOURCE_PATHS["properties"], 'IGNORE_DYNAMIC_SNITCH_SEVERITY("cassandra.ignore_dynamic_snitch_severity")' in properties),
        ]
    )

    for yaml_source, yaml_text in ((SOURCE_PATHS["yaml"], yaml), (SOURCE_PATHS["yaml_latest"], yaml_latest)):
        for token in ("dynamic_snitch_update_interval", "dynamic_snitch_reset_interval", "dynamic_snitch_badness_threshold"):
            checks.append(SourceCheck(f"YAML contains {token}", yaml_source, token in yaml_text))
        checks.append(SourceCheck("YAML documents dynamic batchlog strategy", yaml_source, "dynamic_remote" in yaml_text and "DynamicEndpointSnitch" in yaml_text))

    checks.extend(
        [
            SourceCheck("DatabaseDescriptor wraps dynamic snitch", SOURCE_PATHS["database_descriptor"], "snitch = createEndpointSnitch(conf.dynamic_snitch, conf.endpoint_snitch)" in descriptor and "return dynamic ? new DynamicEndpointSnitch(snitch) : snitch" in descriptor),
            SourceCheck("DatabaseDescriptor dynamic interval setters", SOURCE_PATHS["database_descriptor"], all(token in descriptor for token in ("getDynamicUpdateInterval", "setDynamicUpdateInterval", "getDynamicResetInterval", "setDynamicResetInterval", "getDynamicBadnessThreshold", "setDynamicBadnessThreshold"))),
            SourceCheck("DatabaseDescriptor runtime dynamic snitch check", SOURCE_PATHS["database_descriptor"], "return snitch instanceof DynamicEndpointSnitch" in descriptor),
            SourceCheck("DatabaseDescriptor severity during decommission getter", SOURCE_PATHS["database_descriptor"], "getSeverityDuringDecommission()" in descriptor and "OptionalDouble.of(conf.severity_during_decommission)" in descriptor),
            SourceCheck("StorageService injects decommission severity before leaving", SOURCE_PATHS["storage_service"], "getSeverityDuringDecommission().ifPresent(DynamicEndpointSnitch::addSeverity)" in service and "valueFactory.leaving(getLocalTokens())" in service),
            SourceCheck("StorageService setDynamicUpdateInterval routes updateSnitch", SOURCE_PATHS["storage_service"], "setDynamicUpdateInterval" in service and "updateSnitch(null, true, dynamicUpdateInterval, null, null)" in service),
            SourceCheck("StorageService updateSnitch applies dynamic config", SOURCE_PATHS["storage_service"], all(token in service for token in ("DatabaseDescriptor.setDynamicUpdateInterval", "DatabaseDescriptor.setDynamicResetInterval", "DatabaseDescriptor.setDynamicBadnessThreshold"))),
            SourceCheck("StorageService updateSnitch closes old MBean and refreshes strategies", SOURCE_PATHS["storage_service"], "((DynamicEndpointSnitch)oldSnitch).close()" in service and "DatabaseDescriptor.setEndpointSnitch(newSnitch)" in service and "getReplicationStrategy().snitch = newSnitch" in service),
            SourceCheck("StorageService updateSnitch applies config changes", SOURCE_PATHS["storage_service"], "snitch.applyConfigChanges()" in service and "updateTopology()" in service),
            SourceCheck("StorageServiceMBean exposes updateSnitch", SOURCE_PATHS["storage_service_mbean"], "updateSnitch(String epSnitchClassName" in service_mbean and "setDynamicUpdateInterval" in service_mbean),
            SourceCheck("StorageProxy severity filter for forwarding", SOURCE_PATHS["storage_proxy"], "DynamicEndpointSnitch.getSeverity(r.endpoint()) == 0" in proxy),
            SourceCheck("ReplicaPlans dynamic batchlog branch", SOURCE_PATHS["replica_plans"], "getBatchlogEndpointStrategy().useDynamicSnitchScores" in replica_plans and "DatabaseDescriptor.isDynamicEndpointSnitch()" in replica_plans and "filterBatchlogEndpointsDynamic" in replica_plans),
            SourceCheck("ReplicaPlans dynamic batchlog sorts by proximity", SOURCE_PATHS["replica_plans"], "List<InetAddressAndPort> sorted = sortByProximity(validated.values())" in replica_plans and "DatabaseDescriptor.getEndpointSnitch().getRack(endpoint)" in replica_plans),
            SourceCheck("NodeProbe dynamic endpoint snitch proxy", SOURCE_PATHS["node_probe"], 'new ObjectName("org.apache.cassandra.db:type=DynamicEndpointSnitch")' in node_probe and "DynamicEndpointSnitchMBean.class" in node_probe),
        ]
    )

    checks.extend(
        [
            SourceCheck("DynamicEndpointSnitchTest sets badness and asserts ordering", SOURCE_PATHS["snitch_test"], "DatabaseDescriptor.setDynamicBadnessThreshold(0.1)" in snitch_test and "Util.assertRCEquals" in snitch_test and "CASSANDRA-6683" in snitch_test),
            SourceCheck("DecommissionAvoidTimeouts configures severity and threshold", SOURCE_PATHS["decommission_test"], 'set("severity_during_decommission", 10000D)' in decom_test and 'set("dynamic_snitch_badness_threshold", 0)' in decom_test),
            SourceCheck("DecommissionAvoidTimeouts waits severity gossip and updates scores", SOURCE_PATHS["decommission_test"], "awaitGossipStateMatch(cluster, cluster.get(DECOM_NODE), ApplicationState.SEVERITY)" in decom_test and "updateScores()" in decom_test),
            SourceCheck("DecommissionAvoidTimeouts checks read/write trace failures", SOURCE_PATHS["decommission_test"], "Sending mutation to remote replica" in decom_test and "reading data from" in decom_test and "reading digest from" in decom_test),
            SourceCheck("DecommissionAvoidTimeouts ByteBuddy sortedByProximity hook", SOURCE_PATHS["decommission_test"], "new ByteBuddy().rebase(DynamicEndpointSnitch.class)" in decom_test and 'method(named("sortedByProximity"))' in decom_test),
            SourceCheck("DecommissionAvoidTimeouts asserts decommission endpoint last", SOURCE_PATHS["decommission_test"], "DynamicEndpointSnitch.getSeverity(decom) != 0" in decom_test and "Expected endpoint " in decom_test and "to be the last replica" in decom_test),
            SourceCheck("DecommissionAvoidReadTimeoutsTest extends base", SOURCE_PATHS["decommission_read_test"], "extends DecommissionAvoidTimeouts" in decom_read and "SELECT * FROM " in decom_read),
            SourceCheck("DecommissionAvoidWriteTimeoutsTest extends base", SOURCE_PATHS["decommission_write_test"], "extends DecommissionAvoidTimeouts" in decom_write and "INSERT INTO " in decom_write),
            SourceCheck("BatchlogEndpointFilterTest dynamic strategy tests", SOURCE_PATHS["batchlog_test"], "shouldSelectTwoFastestHostsFromSingleLocalRackWithDynamicSnitch" in batchlog_test and "shouldSelectOneFastestHostsFromNonLocalRackWithDynamicSnitch" in batchlog_test),
            SourceCheck("BatchlogEndpointFilterTest dynamic_remote strategy tests", SOURCE_PATHS["batchlog_test"], "shouldSelectTwoFastestHostsFromSingleLocalRackWithDynamicSnitchRemote" in batchlog_test and "shouldSelectOneFastestHostsFromNonLocalRackWithDynamicSnitchRemote" in batchlog_test),
            SourceCheck("BatchlogEndpointFilterTest dynamic score helper", SOURCE_PATHS["batchlog_test"], "dsnitch.receiveTiming" in batchlog_test and "dsnitch.updateScores()" in batchlog_test),
            SourceCheck("JMXGetterCheckTest knows DynamicEndpointSnitch scores", SOURCE_PATHS["jmx_test"], "org.apache.cassandra.db:type=DynamicEndpointSnitch:Scores" in jmx_test),
        ]
    )

    return checks


def read_doc_text() -> str:
    parts: list[str] = []
    for path in TARGET_DOCS:
        parts.append(read(path))
    return "\n".join(parts)


def doc_checks() -> list[SourceCheck]:
    text = read_doc_text()
    checks = [SourceCheck(f"doc scenario {scenario}", " / ".join(TARGET_DOCS), documented(scenario, text)) for scenario in SCENARIO_IDS]
    checks.extend(SourceCheck(f"doc token {token}", " / ".join(TARGET_DOCS), token in text) for token in DOC_REQUIRED_TOKENS)
    return checks


def check() -> tuple[dict[str, object], bool]:
    sources = source_checks()
    docs = doc_checks()
    result = {
        "source_paths": SOURCE_PATHS,
        "docs": list(TARGET_DOCS),
        "scenario_ids": list(SCENARIO_IDS),
        "source_checks": [entry.__dict__ for entry in sources],
        "doc_checks": [entry.__dict__ for entry in docs],
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check dynamic snitch topology regression source/doc coverage.")
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

        print(f"OK dynamic snitch topology scenario IDs expected: {len(result['scenario_ids'])}")
        print(f"{'OK' if not failed_sources else 'FAILED'} dynamic snitch topology source checks: {len(result['source_checks']) - len(failed_sources)}/{len(result['source_checks'])}")
        print(f"{'OK' if not failed_docs else 'FAILED'} dynamic snitch topology doc checks: {len(result['doc_checks']) - len(failed_docs)}/{len(result['doc_checks'])}")

        if failed_sources or failed_docs:
            print("Dynamic snitch source/doc checks failed:")
            for entry in failed_sources + failed_docs:
                print(f"  - {entry['name']} ({entry['source']})")
        else:
            print("Dynamic snitch topology regression docs are in sync with checked source contracts.")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
