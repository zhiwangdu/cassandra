#!/usr/bin/env python3
#
# Source-only drift check for hints/batchlog durable backlog research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

STORAGE_PROXY = "src/java/org/apache/cassandra/service/StorageProxy.java"
HINTS_SERVICE = "src/java/org/apache/cassandra/hints/HintsService.java"
HINTS_SERVICE_MBEAN = "src/java/org/apache/cassandra/hints/HintsServiceMBean.java"
HINTS_STORE = "src/java/org/apache/cassandra/hints/HintsStore.java"
HINTS_DISPATCH_EXECUTOR = "src/java/org/apache/cassandra/hints/HintsDispatchExecutor.java"
HINTS_DISPATCHER = "src/java/org/apache/cassandra/hints/HintsDispatcher.java"
HINT_MESSAGE = "src/java/org/apache/cassandra/hints/HintMessage.java"
BATCHLOG_MANAGER = "src/java/org/apache/cassandra/batchlog/BatchlogManager.java"
BATCHLOG_MANAGER_MBEAN = "src/java/org/apache/cassandra/batchlog/BatchlogManagerMBean.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
CASSANDRA_YAML = "conf/cassandra.yaml"
STORAGE_METRICS = "src/java/org/apache/cassandra/metrics/StorageMetrics.java"
HINTS_SERVICE_METRICS = "src/java/org/apache/cassandra/metrics/HintsServiceMetrics.java"
HINTED_HANDOFF_METRICS = "src/java/org/apache/cassandra/metrics/HintedHandoffMetrics.java"
NODE_PROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
LIST_PENDING_HINTS = "src/java/org/apache/cassandra/tools/nodetool/ListPendingHints.java"
TRUNCATE_HINTS = "src/java/org/apache/cassandra/tools/nodetool/TruncateHints.java"
REPLAY_BATCHLOG = "src/java/org/apache/cassandra/tools/nodetool/ReplayBatchlog.java"
PAUSE_HANDOFF = "src/java/org/apache/cassandra/tools/nodetool/PauseHandoff.java"
RESUME_HANDOFF = "src/java/org/apache/cassandra/tools/nodetool/ResumeHandoff.java"
DISABLE_HANDOFF = "src/java/org/apache/cassandra/tools/nodetool/DisableHandoff.java"
ENABLE_HANDOFF = "src/java/org/apache/cassandra/tools/nodetool/EnableHandoff.java"
DISABLE_HINTS_FOR_DC = "src/java/org/apache/cassandra/tools/nodetool/DisableHintsForDC.java"
ENABLE_HINTS_FOR_DC = "src/java/org/apache/cassandra/tools/nodetool/EnableHintsForDC.java"
STATUS_HANDOFF = "src/java/org/apache/cassandra/tools/nodetool/StatusHandoff.java"
SET_HINTED_HANDOFF_THROTTLE = "src/java/org/apache/cassandra/tools/nodetool/SetHintedHandoffThrottleInKB.java"
GET_BATCHLOG_REPLAY_THROTTLE = "src/java/org/apache/cassandra/tools/nodetool/GetBatchlogReplayTrottle.java"
SET_BATCHLOG_REPLAY_THROTTLE = "src/java/org/apache/cassandra/tools/nodetool/SetBatchlogReplayThrottle.java"

HINTS_SERVICE_TEST = "test/unit/org/apache/cassandra/hints/HintsServiceTest.java"
HINTS_STORE_TEST = "test/unit/org/apache/cassandra/hints/HintsStoreTest.java"
HINT_MESSAGE_TEST = "test/unit/org/apache/cassandra/hints/HintMessageTest.java"
HINTS_READER_TEST = "test/unit/org/apache/cassandra/hints/HintsReaderTest.java"
HINTS_UPGRADE_TEST = "test/unit/org/apache/cassandra/hints/HintsUpgradeTest.java"
HINTED_HANDOFF_NODETOOL_TEST = "test/distributed/org/apache/cassandra/distributed/test/HintedHandoffNodetoolTest.java"
HINTED_HANDOFF_ADD_REMOVE_TEST = "test/distributed/org/apache/cassandra/distributed/test/HintedHandoffAddRemoveNodesTest.java"
HINTS_MAX_SIZE_TEST = "test/distributed/org/apache/cassandra/distributed/test/HintsMaxSizeTest.java"
ABSTRACT_HINT_WINDOW_TEST = "test/distributed/org/apache/cassandra/distributed/test/AbstractHintWindowTest.java"
HINTS_SERVICE_METRICS_TEST = "test/distributed/org/apache/cassandra/distributed/test/metrics/HintsServiceMetricsTest.java"
BATCHLOG_MANAGER_TEST = "test/unit/org/apache/cassandra/batchlog/BatchlogManagerTest.java"
OVERSIZED_MUTATION_TEST = "test/distributed/org/apache/cassandra/distributed/test/OversizedMutationTest.java"
MIXED_MODE_LOGGED_BATCH_TEST = "test/distributed/org/apache/cassandra/distributed/upgrade/MixedModeLoggedBatchTest.java"

TARGET_DOCS = (
    "research/module-coordination-hints-batchlog-backlog-matrix.md",
    "research/module-coordination-hints-batchlog-backlog-drift-checker.md",
    "research/module-coordination-fault-coverage-runbook.md",
    "research/module-coordination-fault-coverage-drift-checker.md",
    "research/module-coordination-lwt-counter-hints-deep-dive.md",
    "research/flow-hints-batchlog.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "coordination_hints_write_admission_backpressure",
    "coordination_hints_window_size_limits",
    "coordination_hints_dispatch_pause_retry_resume",
    "coordination_hints_dispatch_encoded_decoded_boundary",
    "coordination_hints_orphan_convert_excise_transfer",
    "coordination_hints_operator_surface_gap",
    "coordination_batchlog_replay_paging_throttle",
    "coordination_batchlog_replay_hints_fsync_delete",
    "coordination_hints_batchlog_metrics_observability",
    "coordination_mixed_version_hints_dispatch_gap",
    "coordination_large_logged_batch_backlog_gap",
    "coordination_existing_hints_batchlog_tests_baseline",
)

SOURCE_TOKEN_CHECKS = {
    STORAGE_PROXY: (
        "public static void sendToHintedReplicas(final Mutation mutation,",
        "checkHintOverload(destination);",
        "private static void checkHintOverload(Replica destination)",
        "Too many in flight hints:",
        "public static boolean shouldHint(Replica replica, boolean tryEnablePersistentWindow)",
        "!DatabaseDescriptor.hintedHandoffEnabled()",
        "replica.isTransient()",
        "DatabaseDescriptor.hintedHandoffDisabledDCs()",
        "Gossiper.instance.getEndpointDowntime(endpoint)",
        "DatabaseDescriptor.hintWindowPersistentEnabled()",
        "HintsService.instance.findOldestHintTimestamp(hostIdForEndpoint)",
        "DatabaseDescriptor.getMaxHintsSizePerHost()",
        "HintsService.instance.getTotalHintsSize(hostIdForEndpoint)",
        "Replicas.assertFull(targets);",
        "StorageMetrics.totalHintsInProgress.inc(runnable.targets.size());",
        "StorageMetrics.totalHintsInProgress.dec(targets.size());",
        "HintsService.instance.write(hostIds, Hint.create(mutation,  creationTime));",
        "responseHandler.replicaPlan.consistencyLevel() == ConsistencyLevel.ANY",
    ),
    HINTS_SERVICE: (
        "public void write(Collection<UUID> hostIds, Hint hint)",
        "HintsService is shut down and can't accept new hints",
        "catalog.maybeLoadStores(hostIds);",
        "bufferPool.write(hostIds, hint);",
        "StorageMetrics.totalHints.inc(hostIds.size());",
        "public void flushAndFsyncBlockingly(Iterable<UUID> hostIds)",
        "writeExecutor.flushBufferPool(bufferPool, stores);",
        "writeExecutor.fsyncWritersBlockingly(stores);",
        "public synchronized void startDispatch()",
        "scheduleWithFixedDelay(trigger, 10, 10, TimeUnit.SECONDS);",
        "public void pauseDispatch()",
        "public void resumeDispatch()",
        "public List<PendingHintsInfo> getPendingHintsInfo()",
        "public List<Map<String, String>> getPendingHints()",
        "public void deleteAllHints()",
        "public void deleteAllHintsForEndpoint(String address)",
        "Can't delete hints for unknown address",
        "public void excise(UUID hostId)",
        "dispatchExecutor.interruptDispatch(store.hostId);",
        "catalog.exciseStore(hostId);",
        "public Future transferHints(Supplier<UUID> hostIdSupplier)",
        "resumeDispatch();",
        "dispatchExecutor.transfer(catalog, hostIdSupplier);",
        "public boolean isDispatchPaused()",
    ),
    HINTS_SERVICE_MBEAN: (
        "void pauseDispatch();",
        "void resumeDispatch();",
        "void deleteAllHints();",
        "void deleteAllHintsForEndpoint(String address);",
        "List<Map<String, String>> getPendingHints();",
    ),
    HINTS_STORE: (
        "private final Map<HintsDescriptor, InputPosition> dispatchPositions;",
        "private final Deque<HintsDescriptor> dispatchDequeue;",
        "private final Queue<HintsDescriptor> corruptedFiles;",
        "private final Map<HintsDescriptor, Long> hintsExpirations;",
        "PendingHintsInfo getPendingHintsInfo()",
        "void deleteAllHints()",
        "void deleteExpiredHints(long now)",
        "private boolean hasExpired(HintsDescriptor descriptor, long now)",
        "void markDispatchOffset(HintsDescriptor descriptor, InputPosition inputPosition)",
        "long getTotalFileSize()",
        "void cleanUp(HintsDescriptor descriptor)",
        "void markCorrupted(HintsDescriptor descriptor)",
        "void closeWriter()",
        "SyncUtil.trySyncDir(hintsDirectory);",
    ),
    HINTS_DISPATCH_EXECUTOR: (
        "if (isPaused.get())",
        "HintsDescriptor descriptor = store.poll();",
        "if (dispatcher.dispatch())",
        "store.delete(descriptor);",
        "store.cleanUp(descriptor);",
        "handleDispatchFailure(dispatcher, descriptor, address);",
        "store.markDispatchOffset(descriptor, dispatcher.dispatchPosition());",
        "store.offerFirst(descriptor);",
        "convert(descriptor);",
        "reader.forEach(page -> page.hintsIterator().forEachRemaining(HintsService.instance::writeForAllReplicas));",
        "logger.info(\"Finished converting hints file {}\", descriptor.fileName());",
    ),
    HINTS_DISPATCHER: (
        "int messagingVersion = MessagingService.instance().versions.get(address);",
        "reader.descriptor().messagingVersion() == messagingVersion",
        "? sendHints(page.buffersIterator(), callbacks, this::sendEncodedHint)",
        ": sendHints(page.hintsIterator(), callbacks, this::sendHint);",
        "Callback.Outcome outcome = cb.await();",
        "HintsServiceMetrics.hintsSucceeded.mark(success);",
        "HintsServiceMetrics.hintsFailed.mark(failures);",
        "HintsServiceMetrics.hintsTimedOut.mark(timeouts);",
        "if (abortRequested.getAsBoolean())",
        "Message<?> message = Message.out(HINT_REQ, new HintMessage(hostId, hint));",
        "HintMessage.Encoded message = new HintMessage.Encoded(hostId, hint, messagingVersion);",
    ),
    HINT_MESSAGE: (
        "static final class Encoded implements SerializableHintMessage",
        "private final ByteBuffer hint;",
        "private final int version;",
        "Never deserialized as an HintMessage.Encoded",
    ),
    BATCHLOG_MANAGER: (
        "public void forceBatchlogReplay() throws Exception",
        "public Future<?> startBatchlogReplay()",
        "return batchlogTasks.submit(this::replayFailedBatches);",
        "private void replayFailedBatches()",
        "TimeUUID limitUuid = TimeUUID.maxAtUnixMillis(currentTimeMillis() - getBatchlogTimeout());",
        "static int calculatePageSize(ColumnFamilyStore store)",
        "return (int) Math.max(1, Math.min(DEFAULT_PAGE_SIZE, 4 * 1024 * 1024 / averageRowSize));",
        "setRate(DatabaseDescriptor.getBatchlogReplayThrottleInKiB());",
        "int endpointThrottleInKiB = throttleInKB / endpointsCount;",
        "private void processBatchlogEntries(UntypedResultSet batches, int pageSize, RateLimiter rateLimiter)",
        "finishAndClearBatches(unfinishedBatches, hintedNodes, replayedBatches);",
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
    DATABASE_DESCRIPTOR: (
        "public static boolean hintedHandoffEnabled()",
        "public static Set<String> hintedHandoffDisabledDCs()",
        "public static void enableHintsForDC(String dc)",
        "public static void disableHintsForDC(String dc)",
        "public static int getMaxHintWindow()",
        "public static long getMaxHintsSizePerHost()",
        "public static File getHintsDirectory()",
        "public static int getHintedHandoffThrottleInKiB()",
        "public static int getBatchlogReplayThrottleInKiB()",
        "public static int getMaxHintsDeliveryThreads()",
        "public static long getMaxHintsFileSize()",
        "public static boolean isAutoHintsCleanupEnabled()",
        "public static boolean getTransferHintsOnDecommission()",
    ),
    CONFIG: (
        "public volatile boolean hinted_handoff_enabled = true;",
        "public Set<String> hinted_handoff_disabled_datacenters",
        "public volatile DurationSpec.IntMillisecondsBound max_hint_window",
        "public String hints_directory;",
        "public int max_hints_delivery_threads = 2;",
        "public DataStorageSpec.IntMebibytesBound max_hints_file_size",
        "public volatile DataStorageSpec.LongBytesBound max_hints_size_per_host",
        "public volatile boolean auto_hints_cleanup_enabled = false;",
        "public volatile boolean transfer_hints_on_decommission = true;",
    ),
    CASSANDRA_YAML: (
        "hinted_handoff_enabled: true",
        "max_hint_window: 3h",
        "hinted_handoff_throttle: 1024KiB",
        "max_hints_delivery_threads: 2",
        "max_hints_file_size: 128MiB",
        "max_hints_size_per_host: 0MiB",
        "auto_hints_cleanup_enabled: false",
        "transfer_hints_on_decommission: true",
        "batchlog_replay_throttle:",
    ),
    STORAGE_METRICS: (
        "public static final Counter totalHintsInProgress",
        "public static final Counter totalHints",
    ),
    HINTS_SERVICE_METRICS: (
        "public static final Meter hintsSucceeded",
        "public static final Meter hintsFailed",
        "public static final Meter hintsTimedOut",
        "private static final Histogram globalDelayHistogram",
    ),
    HINTED_HANDOFF_METRICS: (
        "Hints_created-",
        "Hints_for_unowned_ranges",
        "Hints_not_stored-",
        "SystemKeyspace.updateHintsDropped",
    ),
    NODE_PROBE: (
        "public void replayBatchlog() throws IOException",
        "public List<Map<String, String>> listPendingHints()",
        "public void pauseHintsDelivery()",
        "public void resumeHintsDelivery()",
        "public void truncateHints(final String host)",
        "public void setBatchlogReplayThrottle(int value)",
        "public int getBatchlogReplayThrottle()",
    ),
    LIST_PENDING_HINTS: (
        "@Command(name = \"listpendinghints\"",
        "probe.listPendingHints();",
        "Host ID",
        "Total files",
    ),
    TRUNCATE_HINTS: (
        "@Command(name = \"truncatehints\"",
        "probe.truncateHints",
    ),
    REPLAY_BATCHLOG: (
        "@Command(name = \"replaybatchlog\"",
        "probe.replayBatchlog();",
    ),
    PAUSE_HANDOFF: ("@Command(name = \"pausehandoff\"", "probe.pauseHintsDelivery();"),
    RESUME_HANDOFF: ("@Command(name = \"resumehandoff\"", "probe.resumeHintsDelivery();"),
    DISABLE_HANDOFF: ("@Command(name = \"disablehandoff\"", "probe.disableHintedHandoff();"),
    ENABLE_HANDOFF: ("@Command(name = \"enablehandoff\"", "probe.enableHintedHandoff();"),
    DISABLE_HINTS_FOR_DC: ("@Command(name = \"disablehintsfordc\"", "probe.disableHintsForDC(args.get(0));"),
    ENABLE_HINTS_FOR_DC: ("@Command(name = \"enablehintsfordc\"", "probe.enableHintsForDC(args.get(0));"),
    STATUS_HANDOFF: ("@Command(name = \"statushandoff\"", "probe.isHandoffEnabled()", "probe.getHintedHandoffDisabledDCs()"),
    SET_HINTED_HANDOFF_THROTTLE: ("SetHintedHandoffThrottleInKB", "probe.setHintedHandoffThrottleInKB(throttleInKB);"),
    GET_BATCHLOG_REPLAY_THROTTLE: ("@Command(name = \"getbatchlogreplaythrottle\"", "probe.getBatchlogReplayThrottle()"),
    SET_BATCHLOG_REPLAY_THROTTLE: ("@Command(name = \"setbatchlogreplaythrottle\"", "probe.setBatchlogReplayThrottle(batchlogReplayThrottle);"),
    HINTS_SERVICE_TEST: (
        "public void testPauseAndResume()",
        "public void testPageRetry()",
        "public void testPageSeek()",
        "HintsService.instance.pauseDispatch();",
        "store.getDispatchOffset(descriptor);",
    ),
    HINTS_STORE_TEST: (
        "public void testDeleteAllExpiredHints",
        "public void testConcurrentDeleteExpiredHints",
        "public void testPendingHintsInfo()",
    ),
    HINT_MESSAGE_TEST: (
        "public void testEncodedSerializer()",
        "HintMessage.Encoded message",
    ),
    HINTS_READER_TEST: (
        "HintsReader.Page::hintsIterator",
        "page.buffersIterator();",
        "descriptor.messagingVersion()",
    ),
    HINTS_UPGRADE_TEST: (
        "public void test30() throws Exception",
        "public void test41() throws Exception",
        "page.hintsIterator().forEachRemaining",
    ),
    HINTED_HANDOFF_NODETOOL_TEST: (
        "nodetoolResult(\"disablehandoff\")",
        "nodetoolResult(\"enablehandoff\")",
        "nodetoolResult(\"disablehintsfordc\", \"datacenter1\")",
        "nodetoolResult(\"enablehintsfordc\", \"datacenter1\")",
        "nodetoolResult(\"pausehandoff\")",
        "nodetoolResult(\"resumehandoff\")",
        "nodetoolResult(\"sethintedhandoffthrottlekb\"",
    ),
    HINTED_HANDOFF_ADD_REMOVE_TEST: (
        "shouldBootstrapWithHintsOutstanding",
        "StorageMetrics.totalHints.getCount()",
        "HintsServiceMetrics.hintsSucceeded.getCount()",
    ),
    HINTS_MAX_SIZE_TEST: (
        "\"max_hints_size_per_host\", \"2MiB\"",
        "\"max_hints_file_size\", \"1MiB\"",
        "StorageMetrics.totalHints.getCount()",
        "HintsService.instance.getTotalHintsSize(secondNode)",
    ),
    ABSTRACT_HINT_WINDOW_TEST: (
        "HintsService.instance.getTotalHintsSize(secondNode)",
        "HintsService.instance.pauseDispatch();",
        "HintsService.instance.transferHints(() -> transferToNode);",
    ),
    HINTS_SERVICE_METRICS_TEST: (
        "Verb.HINT_REQ.id",
        "HintsServiceMetrics.hintsSucceeded.getCount()",
        "HintsServiceMetrics.hintsFailed.getCount()",
        "HintsServiceMetrics.hintsTimedOut.getCount()",
        "org.apache.cassandra.metrics.HintsService.Hint_delays",
    ),
    BATCHLOG_MANAGER_TEST: (
        "public void testReplay() throws Exception",
        "BatchlogManager.instance.countAllBatches()",
        "BatchlogManager.instance.getTotalBatchesReplayed()",
        "BatchlogManager.instance.startBatchlogReplay().get();",
    ),
    OVERSIZED_MUTATION_TEST: (
        "public void testOversizedBatch() throws Throwable",
        "\"max_mutation_size\", \"48KiB\"",
        "BEGIN BATCH",
    ),
    MIXED_MODE_LOGGED_BATCH_TEST: (
        "public class MixedModeLoggedBatchTest extends MixedModeBatchTestBase",
    ),
}

DOC_REQUIRED_TOKENS = (
    "research/tools/check-coordination-hints-batchlog-backlog-drift.py",
    "research/module-coordination-hints-batchlog-backlog-drift-checker.md",
    "research/module-coordination-hints-batchlog-backlog-matrix.md",
    "StorageProxy.shouldHint()",
    "HintsService.write()",
    "HintsService.flushAndFsyncBlockingly",
    "HintsStore.dispatchDequeue",
    "HintsDispatchExecutor",
    "HintsDispatcher",
    "HintMessage.Encoded",
    "BatchlogManager",
    "BatchlogManager.ReplayingBatch",
    "StorageMetrics.totalHintsInProgress",
    "HintsServiceMetrics.HintsSucceeded",
    "BatchlogManager.countAllBatches()",
    "max_hints_size_per_host",
    "batchlog_replay_throttle",
    "listpendinghints",
    "truncatehints",
    "replaybatchlog",
    "HintedHandoffNodetoolTest",
    "HintsServiceMetricsTest",
    "HintsMaxSizeTest",
    "BatchlogManagerTest.testReplay",
    "mixed-version hints dispatch",
    "large logged batch replay/hints backlog",
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

    list_truncate_dtest_hits = files_matching(
        ("test/distributed",),
        lambda text, _path: 'nodetoolResult("listpendinghints"' in text or 'nodetoolResult("truncatehints"' in text,
    )
    checks.append(Check(
        "gap still open: no distributed listpendinghints/truncatehints nodetool assertion",
        "test/distributed",
        not list_truncate_dtest_hits,
    ))

    mixed_version_hints_dispatch_hits = files_matching(
        (
            "test/distributed/org/apache/cassandra/distributed/test",
            "test/distributed/org/apache/cassandra/distributed/upgrade",
        ),
        lambda text, _path: (
            ("HINT_REQ" in text or "HintsDispatcher" in text or "HintMessage.Encoded" in text)
            and ("MessagingService.instance().versions.set" in text or "setMessagingVersion" in text or "messagingVersion()" in text)
            and ("dispatch" in text.lower() or "nodetoolResult(\"resumehandoff\"" in text)
        ),
    )
    checks.append(Check(
        "gap still open: no mixed-version hints dispatch distributed test",
        "test/distributed",
        not mixed_version_hints_dispatch_hits,
    ))

    batchlog_pending_hints_hits = files_matching(
        ("test/distributed",),
        lambda text, _path: (
            ("nodetoolResult(\"replaybatchlog\"" in text or "startBatchlogReplay" in text)
            and ("nodetoolResult(\"listpendinghints\"" in text or "getPendingHints" in text or "HintsServiceMetrics" in text)
        ),
    )
    checks.append(Check(
        "gap still open: no distributed replaybatchlog plus pending-hints observability test",
        "test/distributed",
        not batchlog_pending_hints_hits,
    ))

    large_logged_batch_backlog_hits = files_matching(
        ("test/distributed",),
        lambda text, _path: (
            ("batch_size_warn_threshold" in text or "batch_size_fail_threshold" in text or "max_mutation_size" in text)
            and ("BEGIN BATCH" in text or "BATCH_STORE_REQ" in text)
            and ("replaybatchlog" in text or "listpendinghints" in text or "HintsServiceMetrics" in text or "getPendingHints" in text)
        ),
    )
    checks.append(Check(
        "gap still open: no large logged batch replay hints backlog distributed test",
        "test/distributed",
        not large_logged_batch_backlog_hits,
    ))

    return checks


def doc_checks() -> list[Check]:
    docs = {path: read(path) for path in TARGET_DOCS}
    combined = "\n".join(docs.values())
    checks = [Check(f"target doc exists {path}", path, bool(text.strip())) for path, text in docs.items()]
    checks.extend(Check(f"doc token {token}", "research", token in combined) for token in DOC_REQUIRED_TOKENS)

    matrix = docs["research/module-coordination-hints-batchlog-backlog-matrix.md"]
    drift_doc = docs["research/module-coordination-hints-batchlog-backlog-drift-checker.md"]
    for scenario in SCENARIO_IDS:
        checks.append(Check(f"scenario coverage {scenario}", "research", scenario in matrix and scenario in drift_doc))

    return checks


def run_checks() -> list[Check]:
    return source_checks() + doc_checks()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check hints/batchlog backlog research drift.")
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
            print("FAIL hints/batchlog backlog drift check")
            for failure in failures:
                print(f"- {failure.name} ({failure.source})")
        else:
            print(f"OK hints/batchlog backlog drift check: {len(checks)} checks")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
