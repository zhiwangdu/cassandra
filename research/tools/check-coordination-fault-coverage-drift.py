#!/usr/bin/env python3
#
# Source-only drift check for Paxos/counter/hints/batchlog fault coverage research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

PAXOS = "src/java/org/apache/cassandra/service/paxos/Paxos.java"
PAXOS_COMMIT_AND_PREPARE = "src/java/org/apache/cassandra/service/paxos/PaxosCommitAndPrepare.java"
PAXOS_PREPARE = "src/java/org/apache/cassandra/service/paxos/PaxosPrepare.java"
PAXOS_PREPARE_REFRESH = "src/java/org/apache/cassandra/service/paxos/PaxosPrepareRefresh.java"
COUNTER_MUTATION = "src/java/org/apache/cassandra/db/CounterMutation.java"
COUNTER_CONTEXT = "src/java/org/apache/cassandra/db/context/CounterContext.java"
HINTS_DISPATCHER = "src/java/org/apache/cassandra/hints/HintsDispatcher.java"
HINT_MESSAGE = "src/java/org/apache/cassandra/hints/HintMessage.java"
HINTS_READER = "src/java/org/apache/cassandra/hints/HintsReader.java"
BATCHLOG_MANAGER = "src/java/org/apache/cassandra/batchlog/BatchlogManager.java"
BATCHLOG_MANAGER_MBEAN = "src/java/org/apache/cassandra/batchlog/BatchlogManagerMBean.java"
BATCH_STATEMENT = "src/java/org/apache/cassandra/cql3/statements/BatchStatement.java"
SINGLE_TABLE_UPDATES_COLLECTOR = "src/java/org/apache/cassandra/cql3/statements/SingleTableUpdatesCollector.java"
STORAGE_PROXY = "src/java/org/apache/cassandra/service/StorageProxy.java"
NODE_PROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
REPLAY_BATCHLOG = "src/java/org/apache/cassandra/tools/nodetool/ReplayBatchlog.java"
LIST_PENDING_HINTS = "src/java/org/apache/cassandra/tools/nodetool/ListPendingHints.java"
PAUSE_HANDOFF = "src/java/org/apache/cassandra/tools/nodetool/PauseHandoff.java"
RESUME_HANDOFF = "src/java/org/apache/cassandra/tools/nodetool/ResumeHandoff.java"
TRUNCATE_HINTS = "src/java/org/apache/cassandra/tools/nodetool/TruncateHints.java"
DISABLE_HANDOFF = "src/java/org/apache/cassandra/tools/nodetool/DisableHandoff.java"
ENABLE_HANDOFF = "src/java/org/apache/cassandra/tools/nodetool/EnableHandoff.java"
GET_BATCHLOG_REPLAY_THROTTLE = "src/java/org/apache/cassandra/tools/nodetool/GetBatchlogReplayTrottle.java"
SET_BATCHLOG_REPLAY_THROTTLE = "src/java/org/apache/cassandra/tools/nodetool/SetBatchlogReplayThrottle.java"

CAS_WRITE_TEST = "test/distributed/org/apache/cassandra/distributed/test/CasWriteTest.java"
CAS_TEST = "test/distributed/org/apache/cassandra/distributed/test/CASTest.java"
PAXOS_REPAIR_TEST = "test/distributed/org/apache/cassandra/distributed/test/PaxosRepairTest.java"
COUNTER_MUTATION_TEST = "test/unit/org/apache/cassandra/db/CounterMutationTest.java"
COUNTER_CONTEXT_TEST = "test/unit/org/apache/cassandra/db/context/CounterContextTest.java"
COUNTERS_TEST = "test/distributed/org/apache/cassandra/distributed/test/CountersTest.java"
HINT_MESSAGE_TEST = "test/unit/org/apache/cassandra/hints/HintMessageTest.java"
HINTS_READER_TEST = "test/unit/org/apache/cassandra/hints/HintsReaderTest.java"
HINTS_UPGRADE_TEST = "test/unit/org/apache/cassandra/hints/HintsUpgradeTest.java"
OVERSIZED_MUTATION_TEST = "test/distributed/org/apache/cassandra/distributed/test/OversizedMutationTest.java"
MIXED_MODE_BATCH_TEST_BASE = "test/distributed/org/apache/cassandra/distributed/upgrade/MixedModeBatchTestBase.java"
MIXED_MODE_LOGGED_BATCH_TEST = "test/distributed/org/apache/cassandra/distributed/upgrade/MixedModeLoggedBatchTest.java"
BATCHLOG_MANAGER_TEST = "test/unit/org/apache/cassandra/batchlog/BatchlogManagerTest.java"

TARGET_DOCS = (
    "research/module-coordination-fault-coverage-runbook.md",
    "research/module-coordination-fault-coverage-drift-checker.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "coordination_paxos_commit_prepare_fault_boundary",
    "coordination_paxos_prepare_refresh_fault_gap",
    "coordination_counter_tombstone_repair_compaction_gap",
    "coordination_hints_encoded_decoded_dispatch_boundary",
    "coordination_hints_mixed_version_dispatch_gap",
    "coordination_batchlog_large_mutation_boundary",
    "coordination_batchlog_replay_hints_backlog_runbook",
    "coordination_operator_hints_batchlog_surface",
    "coordination_existing_tests_baseline",
)

SOURCE_TOKEN_CHECKS = {
    PAXOS: (
        "retry = commitAndPrepare(incomplete.committed",
        "retry = commitAndPrepare(repropose.agreed()",
    ),
    PAXOS_COMMIT_AND_PREPARE: (
        "Message<Request> message = Message.out(PAXOS2_COMMIT_AND_PREPARE_REQ, request);",
        "start(prepare, participants, message, RequestHandler::execute);",
        "public static class RequestHandler implements IVerbHandler<Request>",
        "PaxosPrepare.Response response = execute(message.payload, message.from());",
        "MessagingService.instance().respondWithFailure(UNKNOWN, message);",
        "if (!Paxos.isInRangeAndShouldProcess(from, commit.update.partitionKey(), commit.update.metadata(), request.read != null))",
        "state.commit(commit);",
        "return PaxosPrepare.RequestHandler.execute(request, state);",
    ),
    PAXOS_PREPARE: (
        "private @Nullable List<InetAddressAndPort> needLatest",
        "private PaxosPrepareRefresh refreshStaleParticipants;",
        "haveQuorumOfPermissions |= withLatest() + needLatest() >= participants.sizeOfConsensusQuorum;",
        "refreshStaleParticipants();",
        "public void onRefreshFailure(InetAddressAndPort from, RequestFailureReason reason)",
        "public synchronized void onRefreshSuccess(Ballot isSupersededBy, InetAddressAndPort from)",
    ),
    PAXOS_PREPARE_REFRESH: (
        "public class PaxosPrepareRefresh implements RequestCallbackWithFailure<PaxosPrepareRefresh.Response>",
        "this.send = Message.out(PAXOS2_PREPARE_REFRESH_REQ, new Request(prepared, latestCommitted));",
        "MessagingService.instance().sendWithCallback(send, destination, this);",
        "PAXOS2_PREPARE_REFRESH_REQ.stage.execute(this::executeOnSelf);",
        "if (ex instanceof WriteTimeoutException) reason = TIMEOUT;",
        "callbacks.onRefreshSuccess(response.isSupersededBy, from);",
        "public static class RequestHandler implements IVerbHandler<Request>",
        "MessagingService.instance().respondWithFailure(UNKNOWN, message);",
        "state.commit(commit);",
        "Ballot latest = state.current(request.promised).latestWitnessedOrLowBound();",
        "return new Response(latest);",
        "return new Response(null);",
    ),
    COUNTER_MUTATION: (
        "public Supplier<Mutation> hintOnFailure()",
        "return null;",
        "public Mutation applyCounterMutation() throws WriteTimeoutException",
        "grabCounterLocks(keyspace, locks);",
        "resultBuilder.add(processModifications(upd));",
        "result.apply();",
        "processModifications(PartitionUpdate changes)",
        "updateWithCurrentValuesFromCFS",
        "updateWithCurrentValuesFromCache",
    ),
    COUNTER_CONTEXT: (
        "EQUAL, GREATER_THAN, LESS_THAN, DISJOINT",
        "return Relationship.DISJOINT;",
        "private ByteBuffer merge(ContextState mergedState, ContextState leftState, ContextState rightState)",
        "public ByteBuffer markLocalToBeCleared(ByteBuffer context)",
        "public <V> V clearAllLocal(V context, ValueAccessor<V> accessor)",
        "public static class ContextState",
    ),
    HINTS_DISPATCHER: (
        "int messagingVersion = MessagingService.instance().versions.get(address);",
        "reader.descriptor().messagingVersion() == messagingVersion",
        "? sendHints(page.buffersIterator(), callbacks, this::sendEncodedHint)",
        ": sendHints(page.hintsIterator(), callbacks, this::sendHint);",
        "HintsServiceMetrics.hintsSucceeded.mark(success);",
        "HintsServiceMetrics.hintsFailed.mark(failures);",
        "HintsServiceMetrics.hintsTimedOut.mark(timeouts);",
        "private Callback sendHint(Hint hint)",
        "private Callback sendEncodedHint(ByteBuffer hint)",
        "HintMessage.Encoded message = new HintMessage.Encoded(hostId, hint, messagingVersion);",
    ),
    HINT_MESSAGE: (
        "static final class Encoded implements SerializableHintMessage",
        "private final ByteBuffer hint;",
        "private final int version;",
        "return Hint.serializer.getHintCreationTime(hint, version);",
        "Never deserialized as an HintMessage.Encoded",
    ),
    HINTS_READER: (
        "hintsIterator",
        "buffersIterator",
        "descriptor.messagingVersion()",
    ),
    BATCHLOG_MANAGER: (
        "public void forceBatchlogReplay() throws Exception",
        "return batchlogTasks.submit(this::replayFailedBatches);",
        "private void replayFailedBatches()",
        "setRate(DatabaseDescriptor.getBatchlogReplayThrottleInKiB());",
        "processBatchlogEntries(batches, pageSize, rateLimiter);",
        "private void processBatchlogEntries(UntypedResultSet batches, int pageSize, RateLimiter rateLimiter)",
        "HintsService.instance.flushAndFsyncBlockingly(hintedNodes);",
        "replayedBatches.forEach(BatchlogManager::remove);",
        "private static class ReplayingBatch",
        "handler.get();",
        "writeHintsForUndeliveredEndpoints(i, hintedNodes);",
        "HintsService.instance.write(nodesToHint, Hint.create(undeliveredMutation, writtenAt));",
    ),
    BATCHLOG_MANAGER_MBEAN: (
        "public int countAllBatches();",
        "public long getTotalBatchesReplayed();",
        "public void forceBatchlogReplay() throws Exception;",
    ),
    BATCH_STATEMENT: (
        "DatabaseDescriptor.getBatchSizeWarnThreshold();",
        "DatabaseDescriptor.getBatchSizeFailThreshold();",
        "throw new InvalidRequestException(\"Batch too large\");",
        "ClientWarn.instance.warn",
    ),
    SINGLE_TABLE_UPDATES_COLLECTOR: (
        "else if (metadata.isCounter())",
        "mutation.validateSize(MessagingService.current_version, CommitLogSegment.ENTRY_OVERHEAD_SIZE);",
    ),
    STORAGE_PROXY: (
        "throw new AssertionError(\"Logged batches are unsupported with transient replication\");",
        "performLocally(Stage.MUTATION, target, () -> BatchlogManager.remove(uuid), \"Batchlog remove\", requestTime);",
    ),
    NODE_PROBE: (
        "public void replayBatchlog() throws IOException",
        "bmProxy.forceBatchlogReplay();",
        "public List<Map<String, String>> listPendingHints()",
        "public void pauseHintsDelivery()",
        "public void resumeHintsDelivery()",
        "public void truncateHints(final String host)",
        "public void setBatchlogReplayThrottle(int value)",
        "public int getBatchlogReplayThrottle()",
    ),
    REPLAY_BATCHLOG: (
        "@Command(name = \"replaybatchlog\"",
        "probe.replayBatchlog();",
    ),
    LIST_PENDING_HINTS: (
        "@Command(name = \"listpendinghints\"",
        "probe.listPendingHints();",
        "Host ID",
        "Total files",
    ),
    PAUSE_HANDOFF: ("@Command(name = \"pausehandoff\"", "probe.pauseHintsDelivery();"),
    RESUME_HANDOFF: ("@Command(name = \"resumehandoff\"", "probe.resumeHintsDelivery();"),
    TRUNCATE_HINTS: ("@Command(name = \"truncatehints\"", "probe.truncateHints"),
    DISABLE_HANDOFF: ("@Command(name = \"disablehandoff\"", "probe.disableHintedHandoff();"),
    ENABLE_HANDOFF: ("@Command(name = \"enablehandoff\"", "probe.enableHintedHandoff();"),
    GET_BATCHLOG_REPLAY_THROTTLE: ("@Command(name = \"getbatchlogreplaythrottle\"", "probe.getBatchlogReplayThrottle()"),
    SET_BATCHLOG_REPLAY_THROTTLE: ("@Command(name = \"setbatchlogreplaythrottle\"", "probe.setBatchlogReplayThrottle(batchlogReplayThrottle);"),
    CAS_WRITE_TEST: (
        "testCasWriteTimeoutAtCommitPhase_ReqLost",
        "Verb.PAXOS2_COMMIT_AND_PREPARE_REQ.id",
    ),
    CAS_TEST: (
        "PAXOS2_PREPARE_REFRESH_REQ.id",
        "PAXOS2_COMMIT_AND_PREPARE_REQ.id",
        "paxosAndReadVerbs",
    ),
    PAXOS_REPAIR_TEST: (
        "cluster.verbs(PAXOS_COMMIT_REQ, PAXOS2_COMMIT_AND_PREPARE_REQ).drop();",
        "PaxosCleanup.cleanup",
    ),
    COUNTER_MUTATION_TEST: (
        "public void testDeletes()",
        ".delete(cOne)",
        "RowUpdateBuilder.deleteRow",
        "Util.assertEmpty",
    ),
    COUNTER_CONTEXT_TEST: (
        "public void testClearLocal()",
        "clearAllLocal",
    ),
    COUNTERS_TEST: (
        "public void testEmptyContext()",
        "repaired_data_tracking_for_partition_reads_enabled",
        "mutateRepairMetadata",
        "select a,d from",
    ),
    HINT_MESSAGE_TEST: (
        "public void testEncodedSerializer()",
        "HintMessage.Encoded message",
        "Hint.serializer.serialize(hint, dob, MessagingService.current_version);",
    ),
    HINTS_READER_TEST: (
        "readAndVerify(num, numTable, HintsReader.Page::hintsIterator);",
        "readAndVerify(num, numTable, this::deserializePageBuffers);",
        "page.buffersIterator();",
    ),
    HINTS_UPGRADE_TEST: (
        "public void test30() throws Exception",
        "public void test41() throws Exception",
        "HintsCatalog.load",
        "page.hintsIterator().forEachRemaining",
    ),
    OVERSIZED_MUTATION_TEST: (
        "public void testOversizedBatch() throws Throwable",
        ".set(\"max_mutation_size\", \"48KiB\")",
        "BEGIN BATCH",
        "Rejected an oversized mutation",
    ),
    MIXED_MODE_BATCH_TEST_BASE: (
        "IMessageFilters.Filter dropBatchlogWrite = cluster.filters().inbound().verbs(BATCH_STORE_REQ.id, REQUEST_RSP.id).drop();",
        "testBatches(true, true, insert, select, cluster, upgraded);",
        "WriteTimeoutException",
    ),
    MIXED_MODE_LOGGED_BATCH_TEST: (
        "public class MixedModeLoggedBatchTest extends MixedModeBatchTestBase",
    ),
    BATCHLOG_MANAGER_TEST: (
        "public void testReplay() throws Exception",
        "BatchlogManager.instance.countAllBatches()",
        "BatchlogManager.instance.getTotalBatchesReplayed()",
        "BatchlogManager.instance.startBatchlogReplay().get();",
    ),
}

DOC_REQUIRED_TOKENS = (
    "research/tools/check-coordination-fault-coverage-drift.py",
    "research/module-coordination-fault-coverage-drift-checker.md",
    "PaxosCommitAndPrepare",
    "PaxosPrepareRefresh",
    "CounterMutation",
    "CounterContext",
    "HintsDispatcher",
    "HintMessage.Encoded",
    "BatchlogManager",
    "BatchlogManagerMBean",
    "ReplayBatchlog",
    "ListPendingHints",
    "PAXOS2_COMMIT_AND_PREPARE_REQ",
    "PAXOS2_PREPARE_REFRESH_REQ",
    "CounterMutationTest.testDeletes",
    "CounterContextTest.testClearLocal",
    "CountersTest.testEmptyContext",
    "HintMessageTest.testEncodedSerializer",
    "HintsReaderTest",
    "HintsUpgradeTest",
    "OversizedMutationTest.testOversizedBatch",
    "MixedModeLoggedBatchTest",
    "BatchlogManagerTest.testReplay",
    "direct handler fault tests",
    "counter tombstone + repair/compaction",
    "mixed-version dispatch dtest",
    "large logged batch replay/hints",
    "gap still open",
) + tuple(SOURCE_TOKEN_CHECKS.keys()) + SCENARIO_IDS


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def java_files(root: str) -> tuple[Path, ...]:
    return tuple((REPO_ROOT / root).rglob("*.java"))


def relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def files_matching(roots: tuple[str, ...], predicate) -> list[str]:
    hits: list[str] = []
    for root in roots:
        for path in java_files(root):
            text = path.read_text(encoding="utf-8")
            if predicate(text, relative(path)):
                hits.append(relative(path))
    return hits


def source_checks() -> list[Check]:
    checks: list[Check] = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(Check(f"source token contract {path}", path, all(token in text for token in tokens)))

    paxos_direct_handler_hits = files_matching(
        ("test/unit", "test/distributed", "test/simulator"),
        lambda text, _path: (
            "PaxosCommitAndPrepare.RequestHandler" in text
            or "PaxosPrepareRefresh.RequestHandler" in text
            or "Failed to apply paxos refresh-prepare locally" in text
            or "Promise confirmed for ballot" in text
            or "Promise {} rescinded; latest is now {}" in text
        ),
    )
    checks.append(Check(
        "gap still open: no direct Paxos commit-and-prepare/prepare-refresh handler fault test",
        "test/unit test/distributed test/simulator",
        not paxos_direct_handler_hits,
    ))

    counter_repair_compaction_hits = files_matching(
        ("test/distributed",),
        lambda text, _path: (
            (" counter" in text or "counter," in text or "counter)" in text)
            and ("DELETE" in text or "delete(" in text)
            and ("nodetoolResult(\"repair\"" in text or ".nodetool(\"repair\"" in text or "StorageService.instance.repair" in text)
            and ("forceCompact" in text or "compact(" in text)
        ),
    )
    checks.append(Check(
        "gap still open: no counter tombstone repair compaction distributed test",
        "test/distributed",
        not counter_repair_compaction_hits,
    ))

    mixed_version_hints_dispatch_hits = files_matching(
        (
            "test/distributed/org/apache/cassandra/distributed/test",
            "test/distributed/org/apache/cassandra/distributed/upgrade",
        ),
        lambda text, _path: (
            ("HINT_REQ" in text or "hint" in text.lower())
            and ("MessagingService.instance().versions.set" in text or "setMessagingVersion" in text)
            and ("dispatch" in text.lower() or "listpendinghints" in text or "pausehandoff" in text)
        ),
    )
    checks.append(Check(
        "gap still open: no mixed-version hints dispatch distributed test",
        "test/distributed",
        not mixed_version_hints_dispatch_hits,
    ))

    large_logged_batch_replay_hits = files_matching(
        ("test/distributed",),
        lambda text, _path: (
            ("batch_size_warn_threshold" in text or "batch_size_fail_threshold" in text or "max_mutation_size" in text)
            and ("BEGIN BATCH" in text or "BATCH_STORE_REQ" in text or "isLogged" in text)
            and ("replaybatchlog" in text or "listpendinghints" in text or "startBatchlogReplay" in text or "HintsServiceMetrics" in text)
        ),
    )
    checks.append(Check(
        "gap still open: no large logged batch replay hints backlog distributed test",
        "test/distributed",
        not large_logged_batch_replay_hits,
    ))

    return checks


def doc_checks() -> list[Check]:
    docs = {path: read(path) for path in TARGET_DOCS}
    combined = "\n".join(docs.values())
    checks = [Check(f"target doc exists {path}", path, bool(text.strip())) for path, text in docs.items()]
    checks.extend(Check(f"doc token {token}", "research", token in combined) for token in DOC_REQUIRED_TOKENS)

    runbook = docs["research/module-coordination-fault-coverage-runbook.md"]
    drift_doc = docs["research/module-coordination-fault-coverage-drift-checker.md"]
    for scenario in SCENARIO_IDS:
        checks.append(Check(f"scenario coverage {scenario}", "research", scenario in runbook and scenario in drift_doc))

    return checks


def run_checks() -> list[Check]:
    return source_checks() + doc_checks()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check coordination fault coverage research drift.")
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
            print("FAIL coordination fault coverage drift check")
            for failure in failures:
                print(f"- {failure.name} ({failure.source})")
        else:
            print(f"OK coordination fault coverage drift check: {len(checks)} checks")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
