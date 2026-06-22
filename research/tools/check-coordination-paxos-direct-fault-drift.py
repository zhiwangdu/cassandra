#!/usr/bin/env python3
#
# Source-only drift check for Paxos v2 direct-fault research.

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
PAXOS_REQUEST_CALLBACK = "src/java/org/apache/cassandra/service/paxos/PaxosRequestCallback.java"
VERB = "src/java/org/apache/cassandra/net/Verb.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
CASSANDRA_YAML = "conf/cassandra.yaml"

CAS_WRITE_TEST = "test/distributed/org/apache/cassandra/distributed/test/CasWriteTest.java"
CAS_TEST = "test/distributed/org/apache/cassandra/distributed/test/CASTest.java"
PAXOS_REPAIR_TEST = "test/distributed/org/apache/cassandra/distributed/test/PaxosRepairTest.java"
PAXOS_STATE_TEST = "test/unit/org/apache/cassandra/service/paxos/PaxosStateTest.java"
PAXOS_PROPOSE_TEST = "test/unit/org/apache/cassandra/service/paxos/PaxosProposeTest.java"
PAXOS_REPAIR_UNIT_TEST = "test/unit/org/apache/cassandra/service/paxos/PaxosRepairTest.java"

TARGET_DOCS = (
    "research/module-coordination-paxos-direct-fault-matrix.md",
    "research/module-coordination-paxos-direct-fault-drift-checker.md",
    "research/module-coordination-fault-coverage-runbook.md",
    "research/module-coordination-fault-coverage-drift-checker.md",
    "research/module-coordination-lwt-counter-hints-deep-dive.md",
    "research/module-coordination-lwt-counter-hints-internals.md",
    "research/flow-lwt-paxos.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "coordination_paxos_commit_prepare_entry",
    "coordination_paxos_commit_prepare_message_contract",
    "coordination_paxos_commit_prepare_handler_order",
    "coordination_paxos_commit_prepare_range_gate_gap",
    "coordination_paxos_prepare_refresh_trigger",
    "coordination_paxos_prepare_refresh_self_failure",
    "coordination_paxos_prepare_refresh_superseded",
    "coordination_paxos_prepare_refresh_range_gate_gap",
    "coordination_paxos_existing_drop_tests_baseline",
    "coordination_paxos_direct_handler_test_gap",
)

SOURCE_TOKEN_CHECKS = {
    PAXOS: (
        "case FOUND_INCOMPLETE_COMMITTED:",
        "retry = commitAndPrepare(incomplete.committed, incomplete.participants, query, isWrite, acceptEarlyReadPermission);",
        "case FOUND_INCOMPLETE_ACCEPTED:",
        "PaxosPropose.Status proposeResult = propose(repropose, inProgress.participants, false).awaitUntil(deadline);",
        "case SUCCESS:",
        "retry = commitAndPrepare(repropose.agreed(), inProgress.participants, query, isWrite, acceptEarlyReadPermission);",
        "casWriteMetrics.unfinishedCommit.inc();",
        "casReadMetrics.unfinishedCommit.inc();",
    ),
    PAXOS_COMMIT_AND_PREPARE: (
        "public static final RequestSerializer requestSerializer = new RequestSerializer();",
        "public static final RequestHandler requestHandler = new RequestHandler();",
        "static PaxosPrepare commitAndPrepare(Agreed commit, Paxos.Participants participants, SinglePartitionReadCommand readCommand, boolean isWrite, boolean acceptEarlyReadSuccess)",
        "Ballot ballot = newBallot(commit.ballot, participants.consistencyForConsensus);",
        "Message<Request> message = Message.out(PAXOS2_COMMIT_AND_PREPARE_REQ, request);",
        "start(prepare, participants, message, RequestHandler::execute);",
        "Agreed.serializer.serialize(request.commit, out, version);",
        "return Agreed.serializer.serializedSize(request.commit, version)",
        "MessagingService.instance().respondWithFailure(UNKNOWN, message);",
        "private static PaxosPrepare.Response execute(Request request, InetAddressAndPort from)",
        "!Paxos.isInRangeAndShouldProcess(from, commit.update.partitionKey(), commit.update.metadata(), request.read != null)",
        "state.commit(commit);",
        "return PaxosPrepare.RequestHandler.execute(request, state);",
    ),
    PAXOS_PREPARE_REFRESH: (
        "public class PaxosPrepareRefresh implements RequestCallbackWithFailure<PaxosPrepareRefresh.Response>",
        "void onRefreshFailure(InetAddressAndPort from, RequestFailureReason reason);",
        "void onRefreshSuccess(Ballot isSupersededBy, InetAddressAndPort from);",
        "this.send = Message.out(PAXOS2_PREPARE_REFRESH_REQ, new Request(prepared, latestCommitted));",
        "MessagingService.instance().sendWithCallback(send, destination, this);",
        "PAXOS2_PREPARE_REFRESH_REQ.stage.execute(this::executeOnSelf);",
        "if (response == null)",
        "if (ex instanceof WriteTimeoutException) reason = TIMEOUT;",
        "else logger.error(\"Failed to apply paxos refresh-prepare locally\", ex);",
        "callbacks.onRefreshFailure(from, reason);",
        "callbacks.onRefreshSuccess(response.isSupersededBy, from);",
        "MessagingService.instance().respondWithFailure(UNKNOWN, message);",
        "public static Response execute(Request request, InetAddressAndPort from)",
        "!Paxos.isInRangeAndShouldProcess(from, commit.update.partitionKey(), commit.update.metadata(), false)",
        "state.commit(commit);",
        "Ballot latest = state.current(request.promised).latestWitnessedOrLowBound();",
        "if (isAfter(latest, request.promised))",
        "return new Response(latest);",
        "return new Response(null);",
        "serializeNullable(Ballot.Serializer.instance, response.isSupersededBy, out, version);",
        "deserializeNullable(Ballot.Serializer.instance, in, version);",
    ),
    PAXOS_PREPARE: (
        "if (needLatest == null)",
        "needLatest.add(from);",
        "else if (haveReadResponseWithLatest)",
        "refreshStaleParticipants();",
        "refreshStaleParticipants = new PaxosPrepareRefresh(request.ballot, participants, latestCommitted, this);",
        "refreshStaleParticipants.refresh(needLatest);",
        "needLatest.clear();",
        "public void onRefreshFailure(InetAddressAndPort from, RequestFailureReason reason)",
        "onFailure(from, reason);",
        "public synchronized void onRefreshSuccess(Ballot isSupersededBy, InetAddressAndPort from)",
        "if (isSupersededBy != null)",
        "supersededBy = isSupersededBy;",
        "if (hasProposalStability) signalDone(Outcome.READ_PERMITTED);",
        "else signalDone(SUPERSEDED);",
        "withLatest.add(from);",
        "if (withLatest.size() >= participants.sizeOfConsensusQuorum)",
        "signalDone(hasOnlyPromises ? Outcome.PROMISED : Outcome.READ_PERMITTED);",
        "MessagingService.instance().respondWithFailure(UNKNOWN, message);",
        "static Response execute(AbstractRequest<?> request, PaxosState state)",
    ),
    PAXOS_REQUEST_CALLBACK: (
        "protected <I> void executeOnSelf(I parameter, BiFunction<I, InetAddressAndPort, T> execute)",
        "if (response == null)",
        "if (ex instanceof WriteTimeoutException) reason = TIMEOUT;",
        "else logger.error(\"Failed to apply {} locally\", parameter, ex);",
        "onFailure(getBroadcastAddressAndPort(), reason);",
        "onResponse(response, getBroadcastAddressAndPort());",
        "static boolean shouldExecuteOnSelf(InetAddressAndPort replica)",
    ),
    VERB: (
        "PAXOS2_PREPARE_REFRESH_RSP",
        "() -> PaxosPrepareRefresh.responseSerializer",
        "PAXOS2_PREPARE_REFRESH_REQ",
        "() -> PaxosPrepareRefresh.requestSerializer",
        "() -> PaxosPrepareRefresh.requestHandler",
        "PAXOS2_COMMIT_AND_PREPARE_RSP",
        "() -> PaxosPrepare.responseSerializer",
        "PAXOS2_COMMIT_AND_PREPARE_REQ",
        "() -> PaxosCommitAndPrepare.requestSerializer",
        "() -> PaxosCommitAndPrepare.requestHandler",
    ),
    CONFIG: (
        "public volatile DurationSpec.LongMillisecondsBound write_request_timeout",
        "public volatile PaxosVariant paxos_variant",
        "public volatile DurationSpec.LongMillisecondsBound cas_contention_timeout",
        "public volatile PaxosStatePurging paxos_state_purging",
        "public volatile boolean paxos_repair_enabled",
    ),
    CASSANDRA_YAML: (
        "write_request_timeout:",
        "cas_contention_timeout:",
        "paxos_variant:",
    ),
    CAS_WRITE_TEST: (
        "public void testCasWriteTimeoutAtCommitPhase_ReqLost()",
        "expectCasWriteTimeout();",
        "Verb.PAXOS2_COMMIT_AND_PREPARE_REQ.id",
        ".from(1).to(2, 3).drop().on();",
    ),
    CAS_TEST: (
        "private static int[] paxosAndReadVerbs()",
        "PAXOS2_PREPARE_REFRESH_REQ.id",
        "PAXOS2_COMMIT_AND_PREPARE_REQ.id",
        "PAXOS_PROPOSE_REQ.id",
        "PAXOS_COMMIT_REQ.id",
        "fastReadsAndFailedWrites",
    ),
    PAXOS_REPAIR_TEST: (
        "IMessageFilters.Filter filter2 = cluster.verbs(PAXOS_COMMIT_REQ, PAXOS2_COMMIT_AND_PREPARE_REQ).drop();",
        "PaxosCleanup.cleanup",
        "Assert.assertFalse(hasUncommitted(cluster, KEYSPACE, TABLE));",
        "Assert.assertFalse(hasUncommittedQuorum(cluster, KEYSPACE, TABLE));",
    ),
    PAXOS_STATE_TEST: (
        "public class PaxosStateTest",
    ),
    PAXOS_PROPOSE_TEST: (
        "public class PaxosProposeTest",
    ),
    PAXOS_REPAIR_UNIT_TEST: (
        "public class PaxosRepairTest",
    ),
}

DOC_REQUIRED_TOKENS = (
    "research/tools/check-coordination-paxos-direct-fault-drift.py",
    "research/module-coordination-paxos-direct-fault-matrix.md",
    "research/module-coordination-paxos-direct-fault-drift-checker.md",
    "PaxosCommitAndPrepare",
    "PaxosPrepareRefresh",
    "PaxosPrepare",
    "PaxosRequestCallback",
    "PAXOS2_COMMIT_AND_PREPARE_REQ",
    "PAXOS2_PREPARE_REFRESH_REQ",
    "commitAndPrepare",
    "respondWithFailure(UNKNOWN",
    "WriteTimeoutException",
    "TIMEOUT",
    "superseding ballot",
    "CasWriteTest",
    "CASTest",
    "PaxosRepairTest",
    "direct handler",
    "range-gate null",
    "gap",
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

    direct_handler_hits = files_matching(
        ("test/unit", "test/distributed", "test/simulator"),
        lambda text, _path: (
            "PaxosCommitAndPrepare.RequestHandler" in text
            or "PaxosCommitAndPrepare.requestHandler" in text
            or "PaxosPrepareRefresh.RequestHandler" in text
            or "PaxosPrepareRefresh.requestHandler" in text
        ),
    )
    checks.append(Check(
        "gap still open: no Paxos v2 direct handler test",
        "test/unit test/distributed test/simulator",
        not direct_handler_hits,
    ))

    refresh_superseded_hits = files_matching(
        ("test/unit", "test/distributed", "test/simulator"),
        lambda text, _path: (
            "PaxosPrepareRefresh" in text
            and ("isSupersededBy" in text or "onRefreshSuccess" in text or "superseding" in text)
        ),
    )
    checks.append(Check(
        "gap still open: no prepare-refresh superseded direct test",
        "test/unit test/distributed test/simulator",
        not refresh_superseded_hits,
    ))

    local_timeout_hits = files_matching(
        ("test/unit", "test/distributed", "test/simulator"),
        lambda text, _path: (
            "PaxosPrepareRefresh" in text
            and "WriteTimeoutException" in text
            and ("TIMEOUT" in text or "onRefreshFailure" in text)
        ),
    )
    checks.append(Check(
        "gap still open: no prepare-refresh local timeout direct test",
        "test/unit test/distributed test/simulator",
        not local_timeout_hits,
    ))

    return checks


def doc_checks() -> list[Check]:
    docs = {path: read(path) for path in TARGET_DOCS}
    combined = "\n".join(docs.values())
    checks = [Check(f"target doc exists {path}", path, bool(text.strip())) for path, text in docs.items()]
    checks.extend(Check(f"doc token {token}", "research", token in combined) for token in DOC_REQUIRED_TOKENS)

    matrix = docs["research/module-coordination-paxos-direct-fault-matrix.md"]
    drift_doc = docs["research/module-coordination-paxos-direct-fault-drift-checker.md"]
    for scenario in SCENARIO_IDS:
        checks.append(Check(f"scenario coverage {scenario}", "research", scenario in matrix and scenario in drift_doc))

    return checks


def run_checks() -> list[Check]:
    return source_checks() + doc_checks()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Paxos direct-fault research drift.")
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
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ))
    elif failures:
        print("Paxos direct-fault drift check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure.name} [{failure.source}]", file=sys.stderr)
    else:
        print(f"OK Paxos direct-fault drift check: {len(checks)} checks")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
