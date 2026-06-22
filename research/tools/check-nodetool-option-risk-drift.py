#!/usr/bin/env python3
#
# Source-only drift check for nodetool @Option/@Arguments risk coverage.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

ANNOTATION_SOURCE_FILES = (
    "src/java/org/apache/cassandra/tools/ListCIDRGroups.java",
    "src/java/org/apache/cassandra/tools/NodeTool.java",
    "src/java/org/apache/cassandra/tools/nodetool/Assassinate.java",
    "src/java/org/apache/cassandra/tools/nodetool/AutoRepairStatus.java",
    "src/java/org/apache/cassandra/tools/nodetool/BootstrapResume.java",
    "src/java/org/apache/cassandra/tools/nodetool/Cleanup.java",
    "src/java/org/apache/cassandra/tools/nodetool/ClearSnapshot.java",
    "src/java/org/apache/cassandra/tools/nodetool/ClientStats.java",
    "src/java/org/apache/cassandra/tools/nodetool/Compact.java",
    "src/java/org/apache/cassandra/tools/nodetool/CompactionHistory.java",
    "src/java/org/apache/cassandra/tools/nodetool/CompactionStats.java",
    "src/java/org/apache/cassandra/tools/nodetool/DataPaths.java",
    "src/java/org/apache/cassandra/tools/nodetool/Decommission.java",
    "src/java/org/apache/cassandra/tools/nodetool/DescribeRing.java",
    "src/java/org/apache/cassandra/tools/nodetool/DisableAutoCompaction.java",
    "src/java/org/apache/cassandra/tools/nodetool/DisableBinary.java",
    "src/java/org/apache/cassandra/tools/nodetool/DisableHintsForDC.java",
    "src/java/org/apache/cassandra/tools/nodetool/DropCIDRGroup.java",
    "src/java/org/apache/cassandra/tools/nodetool/EnableAuditLog.java",
    "src/java/org/apache/cassandra/tools/nodetool/EnableAutoCompaction.java",
    "src/java/org/apache/cassandra/tools/nodetool/EnableFullQueryLog.java",
    "src/java/org/apache/cassandra/tools/nodetool/EnableHintsForDC.java",
    "src/java/org/apache/cassandra/tools/nodetool/Flush.java",
    "src/java/org/apache/cassandra/tools/nodetool/ForceCompact.java",
    "src/java/org/apache/cassandra/tools/nodetool/GarbageCollect.java",
    "src/java/org/apache/cassandra/tools/nodetool/GetAuthCacheConfig.java",
    "src/java/org/apache/cassandra/tools/nodetool/GetCIDRGroupsOfIP.java",
    "src/java/org/apache/cassandra/tools/nodetool/GetCompactionThreshold.java",
    "src/java/org/apache/cassandra/tools/nodetool/GetCompactionThroughput.java",
    "src/java/org/apache/cassandra/tools/nodetool/GetConcurrency.java",
    "src/java/org/apache/cassandra/tools/nodetool/GetEndpoints.java",
    "src/java/org/apache/cassandra/tools/nodetool/GetInterDCStreamThroughput.java",
    "src/java/org/apache/cassandra/tools/nodetool/GetSSTables.java",
    "src/java/org/apache/cassandra/tools/nodetool/GetStreamThroughput.java",
    "src/java/org/apache/cassandra/tools/nodetool/GetTimeout.java",
    "src/java/org/apache/cassandra/tools/nodetool/GossipInfo.java",
    "src/java/org/apache/cassandra/tools/nodetool/GuardrailsConfigCommand.java",
    "src/java/org/apache/cassandra/tools/nodetool/Import.java",
    "src/java/org/apache/cassandra/tools/nodetool/Info.java",
    "src/java/org/apache/cassandra/tools/nodetool/InvalidateCIDRPermissionsCache.java",
    "src/java/org/apache/cassandra/tools/nodetool/InvalidateCredentialsCache.java",
    "src/java/org/apache/cassandra/tools/nodetool/InvalidateJmxPermissionsCache.java",
    "src/java/org/apache/cassandra/tools/nodetool/InvalidateNetworkPermissionsCache.java",
    "src/java/org/apache/cassandra/tools/nodetool/InvalidatePermissionsCache.java",
    "src/java/org/apache/cassandra/tools/nodetool/InvalidateRolesCache.java",
    "src/java/org/apache/cassandra/tools/nodetool/ListSnapshots.java",
    "src/java/org/apache/cassandra/tools/nodetool/Move.java",
    "src/java/org/apache/cassandra/tools/nodetool/NetStats.java",
    "src/java/org/apache/cassandra/tools/nodetool/ProfileLoad.java",
    "src/java/org/apache/cassandra/tools/nodetool/Rebuild.java",
    "src/java/org/apache/cassandra/tools/nodetool/RebuildIndex.java",
    "src/java/org/apache/cassandra/tools/nodetool/RecompressSSTables.java",
    "src/java/org/apache/cassandra/tools/nodetool/Refresh.java",
    "src/java/org/apache/cassandra/tools/nodetool/RelocateSSTables.java",
    "src/java/org/apache/cassandra/tools/nodetool/RemoveNode.java",
    "src/java/org/apache/cassandra/tools/nodetool/Repair.java",
    "src/java/org/apache/cassandra/tools/nodetool/RepairAdmin.java",
    "src/java/org/apache/cassandra/tools/nodetool/Ring.java",
    "src/java/org/apache/cassandra/tools/nodetool/SSTableRepairedSet.java",
    "src/java/org/apache/cassandra/tools/nodetool/Scrub.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetAuthCacheConfig.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetAutoRepairConfig.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetBatchlogReplayThrottle.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetCacheCapacity.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetCacheKeysToSave.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetColumnIndexSize.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetCompactionThreshold.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetCompactionThroughput.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetConcurrency.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetConcurrentCompactors.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetConcurrentViewBuilders.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetDefaultKeyspaceRF.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetHintedHandoffThrottleInKB.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetInterDCStreamThroughput.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetLoggingLevel.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetMaxHintWindow.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetSnapshotThrottle.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetStreamThroughput.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetTimeout.java",
    "src/java/org/apache/cassandra/tools/nodetool/SetTraceProbability.java",
    "src/java/org/apache/cassandra/tools/nodetool/Sjk.java",
    "src/java/org/apache/cassandra/tools/nodetool/Snapshot.java",
    "src/java/org/apache/cassandra/tools/nodetool/Status.java",
    "src/java/org/apache/cassandra/tools/nodetool/StatusAutoCompaction.java",
    "src/java/org/apache/cassandra/tools/nodetool/Stop.java",
    "src/java/org/apache/cassandra/tools/nodetool/TableHistograms.java",
    "src/java/org/apache/cassandra/tools/nodetool/TableStats.java",
    "src/java/org/apache/cassandra/tools/nodetool/TpStats.java",
    "src/java/org/apache/cassandra/tools/nodetool/TruncateHints.java",
    "src/java/org/apache/cassandra/tools/nodetool/UpdateCIDRGroup.java",
    "src/java/org/apache/cassandra/tools/nodetool/UpgradeSSTable.java",
    "src/java/org/apache/cassandra/tools/nodetool/Verify.java",
    "src/java/org/apache/cassandra/tools/nodetool/Version.java",
    "src/java/org/apache/cassandra/tools/nodetool/ViewBuildStatus.java",
)

EXPECTED_OPTION_COUNT = 180
EXPECTED_ARGUMENTS_COUNT = 76

TARGET_DOCS = (
    "research/module-nodetool-option-risk-matrix.md",
    "research/module-nodetool-option-drift-checker.md",
)

SCENARIO_IDS = (
    "nodetool_global_jmx_connection_options",
    "nodetool_repair_scope_and_safety_options",
    "nodetool_topology_change_arguments",
    "nodetool_data_rewrite_options",
    "nodetool_streaming_throughput_units",
    "nodetool_audit_fql_runtime_options",
    "nodetool_auth_cache_runtime_options",
    "nodetool_snapshot_cleanup_filters",
    "nodetool_table_selection_arguments",
    "nodetool_output_format_options",
    "nodetool_guardrail_runtime_options",
    "nodetool_sampler_runtime_options",
)

SOURCE_EXPECTATIONS = {
    "src/java/org/apache/cassandra/tools/NodeTool.java": (
        "OptionType.GLOBAL", "--host", "--port", "--username", "--password", "--password-file", "--print-port",
    ),
    "src/java/org/apache/cassandra/tools/ListCIDRGroups.java": (
        "listcidrgroups", "[<cidrGroup>]", "listAvailableCidrGroups", "listCidrsOfCidrGroup",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/Repair.java": (
        "--sequential", "--dc-parallel", "--in-local-dc", "--in-dc", "--in-hosts",
        "--start-token", "--end-token", "--partitioner-range", "--full", "--force",
        "--preview", "--validate", "--job-threads", "--trace", "--pull",
        "--optimise-streams", "--skip-paxos", "--paxos-only", "--ignore-unreplicated-keyspaces",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/Rebuild.java": (
        "<src-dc-name>", "--keyspace", "--tokens", "--sources", "--exclude-local-dc", "probe.rebuild",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/Decommission.java": (
        "--force", "probe.decommission",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/BootstrapResume.java": (
        "--force", "RESET_BOOTSTRAP_PROGRESS", "resumeBootstrap",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/Move.java": (
        "<new token>", "probe.move",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/RemoveNode.java": (
        "<status>|<force>|<ID>", "forceRemoveCompletion", "removeNode",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/Assassinate.java": (
        "<ip_address>", "assassinateEndpoint",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/Compact.java": (
        "--split-output", "--user-defined", "--start-token", "--end-token", "--partition",
        "forceUserDefinedCompaction", "forceKeyspaceCompactionForTokenRange",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/Scrub.java": (
        "--no-snapshot", "--skip-corrupted", "--no-validate", "--reinsert-overflowed-ttl", "--jobs", "probe.scrub",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/Verify.java": (
        "--extended-verify", "--check-version", "--force", "--dfp", "--rsc", "--check-tokens", "--quick", "probe.verify",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/Import.java": (
        "--keep-level", "--keep-repaired", "--no-verify", "--no-tokens", "--no-invalidate-caches",
        "--quick", "--extended-verify", "--copy-data", "--require-index-components", "--no-index-validation",
        "importNewSSTables",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/SSTableRepairedSet.java": (
        "--really-set", "--is-repaired", "--is-unrepaired", "mutateSSTableRepairedState",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/EnableAuditLog.java": (
        "--logger", "--included-keyspaces", "--excluded-keyspaces", "--included-categories", "--excluded-categories",
        "--included-users", "--excluded-users", "--roll-cycle", "--blocking", "--max-queue-weight",
        "--max-log-size", "--archive-command", "--max-archive-retries", "enableAuditLog",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/EnableFullQueryLog.java": (
        "--roll-cycle", "--blocking", "--max-queue-weight", "--max-log-size", "--path",
        "--archive-command", "--max-archive-retries", "enableFullQueryLogger",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/SetAuthCacheConfig.java": (
        "--cache-name", "--validity-period", "--update-interval", "--max-entries",
        "--enable-active-update", "--disable-active-update", "getAuthCacheMBean",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/SetAutoRepairConfig.java": (
        "--repair-type", "start_scheduler", "number_of_repair_threads", "priority_hosts", "forcerepair_hosts",
        "ignore_dcs", "token_range_splitter.", "mixed_major_version_repair_enabled",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/ClearSnapshot.java": (
        "snapshot_name", "--all", "--older-than", "--older-than-timestamp", "clearSnapshot",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/Snapshot.java": (
        "--column-family", "--table", "--tag", "--kt-list", "--skip-flush", "--ttl", "takeSnapshot",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/ProfileLoad.java": (
        "--interval", "--stop", "--list", "SamplerType", "handleScheduledSampling",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/SetStreamThroughput.java": (
        "<value_in_mb>", "--entire-sstable-throughput", "--mib", "setStreamThroughput",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/SetInterDCStreamThroughput.java": (
        "<value_in_mb>", "--entire-sstable-throughput", "--mib", "setInterDCStreamThroughput",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/GetStreamThroughput.java": (
        "--entire-sstable-throughput", "--mib", "--precise-mbit", "getStreamThroughput",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/GetInterDCStreamThroughput.java": (
        "--entire-sstable-throughput", "--mib", "--precise-mbit", "getInterDCStreamThroughput",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/SetConcurrency.java": (
        "<stage-name>", "<maximum-concurrency>", "setConcurrency",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/Stop.java": (
        "<compaction type>", "--compaction-id", "stopById",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/GarbageCollect.java": (
        "--granularity", "--jobs", "garbageCollect",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/Cleanup.java": (
        "--jobs", "forceKeyspaceCleanup",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/TableStats.java": (
        "--human-readable", "--format", "--sort", "--top", "--sstable-location-check", "StatsPrinter",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/GuardrailsConfigCommand.java": (
        "--category", "--expand", "getguardrailsconfig", "setguardrailsconfig", "GuardrailsMBean",
    ),
}

DOC_REQUIRED_TOKENS = (
    "180 @Option",
    "76 @Arguments",
    "94 annotated",
    "JMXTool.java",
    "NodeTool.java",
    "ListCIDRGroups.java",
    "Repair.java",
    "Rebuild.java",
    "Compact.java",
    "Scrub.java",
    "Verify.java",
    "Import.java",
    "EnableAuditLog.java",
    "EnableFullQueryLog.java",
    "SetAuthCacheConfig.java",
    "SetAutoRepairConfig.java",
    "ClearSnapshot.java",
    "Snapshot.java",
    "SetStreamThroughput.java",
    "SetInterDCStreamThroughput.java",
    "GetStreamThroughput.java",
    "GetInterDCStreamThroughput.java",
    "GuardrailsConfigCommand.java",
    "ProfileLoad.java",
    "SSTableRepairedSet.java",
    "SetConcurrency.java",
    "Stop.java",
    "NodeToolCommandTest.java",
    "NodeToolTest.java",
    "SetAuthCacheConfigTest.java",
    "SetAutoRepairConfigTest.java",
    "SetGetStreamThroughputTest.java",
    "SetGetInterDCStreamThroughputTest.java",
    "ClearSnapshotTest.java",
    "VerifyTest.java",
    "ScrubToolTest.java",
    "ImportTest.java",
)


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def actual_annotated_files() -> list[str]:
    files: list[str] = []
    candidates = [
        REPO_ROOT / "src/java/org/apache/cassandra/tools/NodeTool.java",
        REPO_ROOT / "src/java/org/apache/cassandra/tools/ListCIDRGroups.java",
    ]
    candidates.extend((REPO_ROOT / "src/java/org/apache/cassandra/tools/nodetool").glob("*.java"))
    for path in sorted(candidates):
        text = path.read_text(encoding="utf-8")
        if re.search(r"@\s*(?:Option|Arguments)\b", text):
            files.append(str(path.relative_to(REPO_ROOT)))
    return files


def annotation_count(kind: str) -> int:
    return sum(len(re.findall(rf"@\s*{kind}\b", read(path))) for path in ANNOTATION_SOURCE_FILES)


def source_checks() -> tuple[list[Check], dict[str, object]]:
    actual_files = actual_annotated_files()
    expected_files = sorted(ANNOTATION_SOURCE_FILES)
    option_count = annotation_count("Option")
    arguments_count = annotation_count("Arguments")

    checks = [
        Check("annotated file set matches baseline", "src/java/org/apache/cassandra/tools", actual_files == expected_files),
        Check("option annotation count matches baseline", "src/java/org/apache/cassandra/tools", option_count == EXPECTED_OPTION_COUNT),
        Check("arguments annotation count matches baseline", "src/java/org/apache/cassandra/tools", arguments_count == EXPECTED_ARGUMENTS_COUNT),
    ]

    for path, tokens in SOURCE_EXPECTATIONS.items():
        text = read(path)
        missing = [token for token in tokens if token not in text]
        checks.append(Check(f"source contract {path}", path, not missing))

    metadata = {
        "expected_option_count": EXPECTED_OPTION_COUNT,
        "actual_option_count": option_count,
        "expected_arguments_count": EXPECTED_ARGUMENTS_COUNT,
        "actual_arguments_count": arguments_count,
        "expected_annotated_file_count": len(expected_files),
        "actual_annotated_file_count": len(actual_files),
        "added_annotated_files": sorted(set(actual_files) - set(expected_files)),
        "removed_annotated_files": sorted(set(expected_files) - set(actual_files)),
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
        "scenario_ids": list(SCENARIO_IDS),
        "source_expectations": {
            path: list(tokens)
            for path, tokens in SOURCE_EXPECTATIONS.items()
        },
        "source_checks": [entry.__dict__ for entry in sources],
        "doc_checks": [entry.__dict__ for entry in docs],
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check nodetool option and argument risk coverage in research docs.")
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
        print(f"OK nodetool option annotations: {result['actual_option_count']} @Option annotations")
        print(f"OK nodetool argument annotations: {result['actual_arguments_count']} @Arguments annotations")
        print(f"OK nodetool annotated files: {result['actual_annotated_file_count']} files tracked")
        failed_sources = [entry for entry in result["source_checks"] if not entry["ok"]]
        failed_docs = [entry for entry in result["doc_checks"] if not entry["ok"]]
        if result["added_annotated_files"]:
            print("New annotated files not in baseline:")
            for path in result["added_annotated_files"]:
                print(f"  {path}")
        if result["removed_annotated_files"]:
            print("Baseline annotated files no longer present:")
            for path in result["removed_annotated_files"]:
                print(f"  {path}")
        if failed_sources:
            print("Failed source checks:")
            for entry in failed_sources:
                print(f"  {entry['name']} ({entry['source']})")
        if failed_docs:
            print("Failed doc checks:")
            for entry in failed_docs:
                print(f"  {entry['name']} ({entry['source']})")
        if ok:
            print("Nodetool option risk matrix is in sync with parsed annotations and source contracts.")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
