#!/usr/bin/env python3
#
# Source-only drift check for transient repair/streaming fault coverage.

import argparse
import glob
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

SOURCE_PATHS = {
    "repair_job": "src/java/org/apache/cassandra/repair/RepairJob.java",
    "local_sync_task": "src/java/org/apache/cassandra/repair/LocalSyncTask.java",
    "owned_ranges": "src/java/org/apache/cassandra/dht/OwnedRanges.java",
    "stream_session": "src/java/org/apache/cassandra/streaming/StreamSession.java",
    "mutation_handler": "src/java/org/apache/cassandra/db/AbstractMutationVerbHandler.java",
    "storage_service": "src/java/org/apache/cassandra/service/StorageService.java",
    "replica_plans": "src/java/org/apache/cassandra/locator/ReplicaPlans.java",
    "read_executor": "src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java",
    "response_resolver": "src/java/org/apache/cassandra/service/reads/ResponseResolver.java",
    "digest_resolver": "src/java/org/apache/cassandra/service/reads/DigestResolver.java",
    "abstract_read_repair": "src/java/org/apache/cassandra/service/reads/repair/AbstractReadRepair.java",
    "config": "src/java/org/apache/cassandra/config/Config.java",
    "database_descriptor": "src/java/org/apache/cassandra/config/DatabaseDescriptor.java",
    "yaml": "conf/cassandra.yaml",
    "repair_job_test": "test/unit/org/apache/cassandra/repair/RepairJobTest.java",
    "local_sync_task_test": "test/unit/org/apache/cassandra/repair/LocalSyncTaskTest.java",
    "repair_out_of_range_test": "test/unit/org/apache/cassandra/repair/RepairMessageVerbHandlerOutOfRangeTest.java",
    "stream_owned_ranges_test": "test/unit/org/apache/cassandra/streaming/StreamSessionOwnedRangesTest.java",
    "mutation_out_of_range_test": "test/unit/org/apache/cassandra/db/MutationVerbHandlerOutOfRangeTest.java",
    "repair_errors_test": "test/distributed/org/apache/cassandra/distributed/test/RepairErrorsTest.java",
    "stream_failure_logs": "test/distributed/org/apache/cassandra/distributed/test/streaming/AbstractStreamFailureLogs.java",
    "stream_failed_receiving": "test/distributed/org/apache/cassandra/distributed/test/streaming/StreamFailedWhileReceivingTest.java",
    "stream_prepare_fail": "test/distributed/org/apache/cassandra/distributed/test/StreamPrepareFailTest.java",
    "pending_writes_test": "test/distributed/org/apache/cassandra/distributed/test/ring/PendingWritesTest.java",
    "bootstrap_test": "test/distributed/org/apache/cassandra/distributed/test/ring/BootstrapTest.java",
}

TARGET_DOCS = (
    "research/module-repair-streaming-transient-fault-coverage.md",
    "research/module-repair-streaming-transient-coverage-drift-checker.md",
)

SCENARIO_IDS = (
    "transient_standard_sync_direction",
    "transient_optimized_sync_no_target",
    "local_sync_request_transfer_flags",
    "repair_validation_owned_range_rejection",
    "stream_request_owned_range_rejection",
    "mutation_pending_range_acceptance",
    "transient_read_full_replica_requirement",
    "pending_bootstrap_write_distribution",
    "generic_repair_stream_failure_injection",
    "generic_stream_failure_visibility",
    "distributed_transient_repair_streaming_gap",
)

DOC_REQUIRED_TOKENS = (
    "RepairJob",
    "LocalSyncTask",
    "OwnedRanges",
    "StreamSession",
    "AbstractMutationVerbHandler",
    "ReplicaPlans",
    "AbstractReadExecutor",
    "ResponseResolver",
    "DigestResolver",
    "transient_replication_enabled",
    "reject_out_of_token_range_requests",
    "RepairJobTest",
    "LocalSyncTaskTest",
    "RepairMessageVerbHandlerOutOfRangeTest",
    "StreamSessionOwnedRangesTest",
    "MutationVerbHandlerOutOfRangeTest",
    "RepairErrorsTest",
    "AbstractStreamFailureLogs",
    "StreamFailedWhileReceivingTest",
    "StreamPrepareFailTest",
    "PendingWritesTest",
    "BootstrapTest",
)

ALLOWED_DISTRIBUTED_TRANSIENT_MARKER_PATHS = {
    "test/distributed/org/apache/cassandra/distributed/test/ring/BootstrapTest.java",
}

TRANSIENT_DISTRIBUTED_MARKER = re.compile(
    r"transient_replication_enabled|enable_transient_replication|\"3/1\"|ReplicationFactor\.fromString|"
    r"withTransient|transientReplicas|transient_ranges"
)


@dataclass(frozen=True)
class SourceCheck:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def source_checks() -> list[SourceCheck]:
    repair_job = read(SOURCE_PATHS["repair_job"])
    local_sync = read(SOURCE_PATHS["local_sync_task"])
    owned_ranges = read(SOURCE_PATHS["owned_ranges"])
    stream_session = read(SOURCE_PATHS["stream_session"])
    mutation_handler = read(SOURCE_PATHS["mutation_handler"])
    storage_service = read(SOURCE_PATHS["storage_service"])
    replica_plans = read(SOURCE_PATHS["replica_plans"])
    read_executor = read(SOURCE_PATHS["read_executor"])
    response_resolver = read(SOURCE_PATHS["response_resolver"])
    digest_resolver = read(SOURCE_PATHS["digest_resolver"])
    abstract_read_repair = read(SOURCE_PATHS["abstract_read_repair"])
    config = read(SOURCE_PATHS["config"])
    descriptor = read(SOURCE_PATHS["database_descriptor"])
    yaml = read(SOURCE_PATHS["yaml"])
    repair_job_test = read(SOURCE_PATHS["repair_job_test"])
    local_sync_test = read(SOURCE_PATHS["local_sync_task_test"])
    repair_oor_test = read(SOURCE_PATHS["repair_out_of_range_test"])
    stream_owned_test = read(SOURCE_PATHS["stream_owned_ranges_test"])
    mutation_oor_test = read(SOURCE_PATHS["mutation_out_of_range_test"])
    repair_errors_test = read(SOURCE_PATHS["repair_errors_test"])
    stream_failure_logs = read(SOURCE_PATHS["stream_failure_logs"])
    stream_failed_receiving = read(SOURCE_PATHS["stream_failed_receiving"])
    stream_prepare_fail = read(SOURCE_PATHS["stream_prepare_fail"])
    pending_writes = read(SOURCE_PATHS["pending_writes_test"])
    bootstrap_test = read(SOURCE_PATHS["bootstrap_test"])

    checks: list[SourceCheck] = [
        SourceCheck("RepairJob skips transient-transient standard sync", SOURCE_PATHS["repair_job"], "Avoid streming between two tansient replicas" in repair_job and "isTransient.test(r1.endpoint) && isTransient.test(r2.endpoint)" in repair_job),
        SourceCheck("RepairJob local transient request/transfer flags", SOURCE_PATHS["repair_job"], "boolean requestRanges = !isTransient.test(self.endpoint)" in repair_job and "boolean transferRanges = !isTransient.test(remote.endpoint) && !pullRepair" in repair_job),
        SourceCheck("RepairJob skips empty local transient task", SOURCE_PATHS["repair_job"], "if (!requestRanges && !transferRanges)" in repair_job),
        SourceCheck("RepairJob remote transient asymmetric stream", SOURCE_PATHS["repair_job"], "Stream only from transient replica" in repair_job and "new AsymmetricRemoteSyncTask(ctx, desc, streamTo.endpoint, streamFrom.endpoint" in repair_job),
        SourceCheck("RepairJob remote full symmetric stream", SOURCE_PATHS["repair_job"], "new SymmetricRemoteSyncTask(ctx, desc, r1.endpoint, r2.endpoint" in repair_job),
        SourceCheck("RepairJob optimized skip transient targets", SOURCE_PATHS["repair_job"], "we don't stream to transient replicas" in repair_job and "if (isTransient.test(address))" in repair_job),
        SourceCheck("RepairJob optimized local fetch only", SOURCE_PATHS["repair_job"], "new LocalSyncTask(ctx, desc, address, fetchFrom, toFetch" in repair_job and "true, false, previewKind" in repair_job),
        SourceCheck("LocalSyncTask records request and transfer flags", SOURCE_PATHS["local_sync_task"], "public final boolean requestRanges" in local_sync and "public final boolean transferRanges" in local_sync),
        SourceCheck("LocalSyncTask prevents empty sync", SOURCE_PATHS["local_sync_task"], "Preconditions.checkArgument(requestRanges || transferRanges" in local_sync),
        SourceCheck("LocalSyncTask creates repair stream plan", SOURCE_PATHS["local_sync_task"], "new StreamPlan(StreamOperation.REPAIR" in local_sync and "flushBeforeTransfer(pendingRepair == null)" in local_sync),
        SourceCheck("LocalSyncTask maps request ranges", SOURCE_PATHS["local_sync_task"], "if (requestRanges)" in local_sync and "plan.requestRanges" in local_sync),
        SourceCheck("LocalSyncTask maps transfer ranges", SOURCE_PATHS["local_sync_task"], "if (transferRanges)" in local_sync and "plan.transferRanges" in local_sync),
        SourceCheck("OwnedRanges validates with log/reject toggles", SOURCE_PATHS["owned_ranges"], "getLogOutOfTokenRangeRequests" in owned_ranges and "getRejectOutOfTokenRangeRequests" in owned_ranges and "return !outOfRangeTokenRejection || unownedRanges.isEmpty()" in owned_ranges),
        SourceCheck("OwnedRanges increments invalid token metric", SOURCE_PATHS["owned_ranges"], "StorageMetrics.totalOpsForInvalidToken.inc()" in owned_ranges),
        SourceCheck("OwnedRanges documents repair and stream callers", SOURCE_PATHS["owned_ranges"], "StreamRequests in StreamSession" in owned_ranges and "ValidationRequest in RepairMessageVerbHandler" in owned_ranges),
        SourceCheck("StreamSession validates full plus transient ranges", SOURCE_PATHS["stream_session"], "RangesAtEndpoint.concat(req.full, req.transientReplicas)" in stream_session and "ownedRanges.validateRangeRequest" in stream_session),
        SourceCheck("StreamSession throws out-of-range exception", SOURCE_PATHS["stream_session"], "StreamRequestOutOfTokenRangeException" in stream_session and "rejectedRequests" in stream_session),
        SourceCheck("StreamSession repair outgoing metrics", SOURCE_PATHS["stream_session"], "StreamOperation.REPAIR == getStreamOperation()" in stream_session and "totalOutgoingRepairBytes" in stream_session),
        SourceCheck("Mutation handler checks log/reject and pending validity", SOURCE_PATHS["mutation_handler"], "getLogOutOfTokenRangeRequests" in mutation_handler and "getRejectOutOfTokenRangeRequests" in mutation_handler and "isEndpointValidForWrite" in mutation_handler),
        SourceCheck("Mutation handler increments invalid/out-of-range metrics", SOURCE_PATHS["mutation_handler"], "incOutOfRangeOperationCount" in mutation_handler and "outOfRangeTokenWrites.inc" in mutation_handler),
        SourceCheck("StorageService normalized local ranges", SOURCE_PATHS["storage_service"], "getNormalizedLocalRanges" in storage_service and "return getNormalizedRanges(keyspaceName, FBUtilities.getBroadcastAddressAndPort())" in storage_service),
        SourceCheck("StorageService write validity includes pending", SOURCE_PATHS["storage_service"], "isEndpointValidForWrite" in storage_service and "isTokenInLocalNaturalOrPendingRange" in storage_service),
        SourceCheck("ReplicaPlans read requires full replica", SOURCE_PATHS["replica_plans"], "Replicas.countFull(liveReplicas) > 0" in replica_plans and "assureSufficientLiveReplicas(replicationStrategy, consistencyLevel, liveReplicas, consistencyLevel.blockFor(replicationStrategy), 1)" in replica_plans),
        SourceCheck("ReplicaPlans normal write includes full natural and pending", SOURCE_PATHS["replica_plans"], "contacts.addAll(filter(liveAndDown.natural(), Replica::isFull))" in replica_plans and "contacts.addAll(liveAndDown.pending())" in replica_plans),
        SourceCheck("ReplicaPlans write adds needed transient per DC", SOURCE_PATHS["replica_plans"], "filter(live.natural(), Replica::isTransient)" in replica_plans and "requiredPerDc.addTo(dc, -1)" in replica_plans),
        SourceCheck("ReplicaPlans read repair write excludes transient", SOURCE_PATHS["replica_plans"], "assert !any(liveAndDown.all(), Replica::isTransient)" in replica_plans),
        SourceCheck("ReplicaPlans Paxos pending movement guard", SOURCE_PATHS["replica_plans"], "pending().size() > 1" in replica_plans and "pending range movement" in replica_plans),
        SourceCheck("Read executor sends digests only to full replicas", SOURCE_PATHS["read_executor"], "assert all(replicas, Replica::isFull)" in read_executor and "only send digest requests to full replicas" in read_executor),
        SourceCheck("Read executor sends transient data requests", SOURCE_PATHS["read_executor"], "makeTransientDataRequests(selected.filterLazily(Replica::isTransient))" in read_executor and "copyAsTransientQuery" in read_executor),
        SourceCheck("ResponseResolver rejects transient digest", SOURCE_PATHS["response_resolver"], "isTransient()" in response_resolver and "isDigestResponse()" in response_resolver and "Digest response received from transient replica" in response_resolver),
        SourceCheck("DigestResolver reconciles transient data responses", SOURCE_PATHS["digest_resolver"], "hasTransientResponse" in digest_resolver and "Reconcile with transient replicas" in digest_resolver and "DataResolver" in digest_resolver),
        SourceCheck("AbstractReadRepair uses transient query but not repair mutation", SOURCE_PATHS["abstract_read_repair"], "to.isTransient()" in abstract_read_repair and "copyAsTransientQuery" in abstract_read_repair and "ReadOnlyReadRepair" in abstract_read_repair),
        SourceCheck("Config has transient/out-of-range/streaming options", SOURCE_PATHS["config"], "transient_replication_enabled = false" in config and "log_out_of_token_range_requests = true" in config and "reject_out_of_token_range_requests = false" in config and "stream_entire_sstables = true" in config),
        SourceCheck("DatabaseDescriptor exposes transient/out-of-range/streaming options", SOURCE_PATHS["database_descriptor"], "isTransientReplicationEnabled" in descriptor and "getRejectOutOfTokenRangeRequests" in descriptor and "streamEntireSSTables" in descriptor and "internodeCompression" in descriptor),
        SourceCheck("YAML documents transient replication experimental", SOURCE_PATHS["yaml"], "transient_replication_enabled: false" in yaml and "experimental and is not recommended for production use" in yaml),
        SourceCheck("RepairJobTest local full remote transient", SOURCE_PATHS["repair_job_test"], "testStandardSyncTransient" in repair_job_test and "isRequestRanges()" in repair_job_test and "hasTransferRanges(false)" in repair_job_test),
        SourceCheck("RepairJobTest local transient pull repair empty", SOURCE_PATHS["repair_job_test"], "testStandardSyncLocalTransient" in repair_job_test and "assertThat(tasks).isEmpty()" in repair_job_test),
        SourceCheck("RepairJobTest five-node transient asymmetric", SOURCE_PATHS["repair_job_test"], "testCreate5NodeStandardSyncTasksWithTransient" in repair_job_test and "AsymmetricRemoteSyncTask" in repair_job_test),
        SourceCheck("RepairJobTest local and remote transient skips pair", SOURCE_PATHS["repair_job_test"], "testLocalAndRemoteTransient" in repair_job_test and "assertThat(tasks.get(pair(addr4, addr5))).isNull()" in repair_job_test),
        SourceCheck("RepairJobTest optimized transient", SOURCE_PATHS["repair_job_test"], "testOptimisedCreateStandardSyncTasksWithTransient" in repair_job_test and "hasTransferRanges(false)" in repair_job_test),
        SourceCheck("LocalSyncTaskTest transient stream plans", SOURCE_PATHS["local_sync_task_test"], "transientRemoteStreamPlan" in local_sync_test and "transientLocalStreamPlan" in local_sync_test and "assertNumInOut(plan, 1, 0)" in local_sync_test and "assertNumInOut(plan, 0, 1)" in local_sync_test),
        SourceCheck("Repair out-of-range validation tests", SOURCE_PATHS["repair_out_of_range_test"], "testValidationRequestWithRequestedRangeOutsideOwned" in repair_oor_test and "tryValidationExpectingFailure" in repair_oor_test and "StorageMetrics.totalOpsForInvalidToken.getCount()" in repair_oor_test),
        SourceCheck("Stream owned range tests full/transient request builder", SOURCE_PATHS["stream_owned_ranges_test"], "StreamRequestOutOfTokenRangeException" in stream_owned_test and "streamRequests(RangesAtEndpoint fullRanges" in stream_owned_test and "transientRanges" in stream_owned_test),
        SourceCheck("Mutation out-of-range pending tests", SOURCE_PATHS["mutation_out_of_range_test"], "acceptMutationForPendingEndpoint" in mutation_oor_test and "setPendingRangesUnsafe" in mutation_oor_test and "rejectMutationForTokenOutOfRange" in mutation_oor_test),
        SourceCheck("RepairErrorsTest remote sync/stream failures", SOURCE_PATHS["repair_errors_test"], "testRemoteSyncFailure" in repair_errors_test and "testRemoteStreamFailure" in repair_errors_test and "installStreamPlanExecutionFailure" in repair_errors_test and "installStreamHandlingFailure" in repair_errors_test),
        SourceCheck("Stream failure logs assert virtual table failure cause", SOURCE_PATHS["stream_failure_logs"], "Stream failed:" in stream_failure_logs and "system_views.streaming" in stream_failure_logs and "failure_cause" in stream_failure_logs),
        SourceCheck("StreamFailedWhileReceivingTest aborts receiving stream", SOURCE_PATHS["stream_failed_receiving"], "StreamFailedWhileReceivingTest" in stream_failed_receiving and "CassandraStreamReceiver" in stream_failed_receiving and "firstSession.abort()" in stream_failed_receiving),
        SourceCheck("StreamPrepareFailTest rebuild stream prepare failure", SOURCE_PATHS["stream_prepare_fail"], "StreamPrepareFailTest" in stream_prepare_fail and "StorageService.instance.rebuild(null)" in stream_prepare_fail and "Stream failed" in stream_prepare_fail),
        SourceCheck("PendingWritesTest pending write distribution", SOURCE_PATHS["pending_writes_test"], "testPendingWrites" in pending_writes and "getPendingRanges(KEYSPACE)" in pending_writes and "row state" in pending_writes),
        SourceCheck("BootstrapTest available ranges transient_ranges marker", SOURCE_PATHS["bootstrap_test"], "AVAILABLE_RANGES_V2" in bootstrap_test and "transient_ranges" in bootstrap_test and "Discovered existing bootstrap data" in bootstrap_test),
    ]

    return checks


def distributed_transient_markers() -> dict[str, list[str]]:
    markers: dict[str, list[str]] = {}
    for match in glob.glob(str(REPO_ROOT / "test/distributed/**/*.java"), recursive=True):
        rel = str(Path(match).relative_to(REPO_ROOT))
        text = Path(match).read_text(encoding="utf-8")
        hits = sorted(set(TRANSIENT_DISTRIBUTED_MARKER.findall(text)))
        if hits:
            markers[rel] = hits
    return markers


def distributed_gap_checks() -> list[SourceCheck]:
    markers = distributed_transient_markers()
    marker_paths = set(markers)
    unexpected = marker_paths - ALLOWED_DISTRIBUTED_TRANSIENT_MARKER_PATHS
    missing_allowed = ALLOWED_DISTRIBUTED_TRANSIENT_MARKER_PATHS - marker_paths
    return [
        SourceCheck("Distributed transient marker allow-list unchanged", "test/distributed/**/*.java", not unexpected and not missing_allowed),
        SourceCheck("Distributed transient marker is only available-ranges BootstrapTest", SOURCE_PATHS["bootstrap_test"], marker_paths == ALLOWED_DISTRIBUTED_TRANSIENT_MARKER_PATHS and "transient_ranges" in read(SOURCE_PATHS["bootstrap_test"])),
    ]


def read_doc_text() -> str:
    return "\n".join(read(path) for path in TARGET_DOCS)


def doc_checks() -> list[SourceCheck]:
    text = read_doc_text()
    checks = [SourceCheck(f"doc scenario {scenario}", " / ".join(TARGET_DOCS), documented(scenario, text)) for scenario in SCENARIO_IDS]
    checks.extend(SourceCheck(f"doc token {token}", " / ".join(TARGET_DOCS), token in text) for token in DOC_REQUIRED_TOKENS)
    return checks


def check() -> tuple[dict[str, object], bool]:
    sources = source_checks()
    gap = distributed_gap_checks()
    docs = doc_checks()
    markers = distributed_transient_markers()
    result = {
        "source_paths": SOURCE_PATHS,
        "docs": list(TARGET_DOCS),
        "scenario_ids": list(SCENARIO_IDS),
        "allowed_distributed_transient_marker_paths": sorted(ALLOWED_DISTRIBUTED_TRANSIENT_MARKER_PATHS),
        "distributed_transient_markers": markers,
        "source_checks": [entry.__dict__ for entry in sources],
        "distributed_gap_checks": [entry.__dict__ for entry in gap],
        "doc_checks": [entry.__dict__ for entry in docs],
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in gap) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check transient repair/streaming fault coverage source/doc drift.")
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
        failed_gap = [entry for entry in result["distributed_gap_checks"] if not entry["ok"]]
        failed_docs = [entry for entry in result["doc_checks"] if not entry["ok"]]

        print(f"OK transient repair/streaming scenario IDs expected: {len(result['scenario_ids'])}")
        print(f"{'OK' if not failed_sources else 'FAILED'} transient repair/streaming source checks: {len(result['source_checks']) - len(failed_sources)}/{len(result['source_checks'])}")
        print(f"{'OK' if not failed_gap else 'FAILED'} distributed transient marker checks: {len(result['distributed_gap_checks']) - len(failed_gap)}/{len(result['distributed_gap_checks'])}")
        print(f"{'OK' if not failed_docs else 'FAILED'} transient repair/streaming doc checks: {len(result['doc_checks']) - len(failed_docs)}/{len(result['doc_checks'])}")

        if result["distributed_transient_markers"]:
            print("Distributed transient marker files:")
            for path, hits in sorted(result["distributed_transient_markers"].items()):
                print(f"  - {path}: {', '.join(hits)}")

        if failed_sources or failed_gap or failed_docs:
            print("Transient repair/streaming source/doc checks failed:")
            for entry in failed_sources + failed_gap + failed_docs:
                print(f"  - {entry['name']} ({entry['source']})")
        else:
            print("Transient repair/streaming source/doc checks passed.")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
