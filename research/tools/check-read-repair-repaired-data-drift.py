#!/usr/bin/env python3
#
# Source-only drift check for read repair and repaired-data research coverage.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

MATRIX_DOC = "research/module-read-repair-repaired-data-matrix.md"
CHECKER_DOC = "research/module-read-repair-repaired-data-drift-checker.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

SCENARIOS = (
    "read_repair_strategy_table_option_contract",
    "read_repair_digest_mismatch_entry_contract",
    "read_repair_full_data_read_contract",
    "read_repair_data_resolver_merge_contract",
    "read_repair_blocking_write_contract",
    "read_repair_none_noop_write_contract",
    "read_repair_partition_ack_contract",
    "read_repair_speculative_read_contract",
    "read_repair_speculative_write_contract",
    "read_repair_repaired_data_tracking_contract",
    "read_repair_repaired_data_verifier_contract",
    "read_repair_diagnostic_metrics_contract",
    "read_repair_mbean_operational_contract",
    "read_repair_existing_tests_baseline",
)

SOURCE_EXPECTATIONS = {
    "src/java/org/apache/cassandra/schema/TableParams.java": (
        "public final ReadRepairStrategy readRepair;",
        "private ReadRepairStrategy readRepair = ReadRepairStrategy.BLOCKING;",
        "public Builder readRepair(ReadRepairStrategy val)",
        ".append(\"AND read_repair = \").appendWithSingleQuotes(readRepair.toString())",
    ),
    "src/java/org/apache/cassandra/service/reads/repair/ReadRepairStrategy.java": (
        "public enum ReadRepairStrategy implements ReadRepair.Factory",
        "NONE",
        "return new ReadOnlyReadRepair<>(command, replicaPlan, requestTime);",
        "BLOCKING",
        "return new BlockingReadRepair<>(command, replicaPlan, requestTime);",
        "return valueOf(s.toUpperCase());",
    ),
    "src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java": (
        "handler.awaitResults();",
        "assert digestResolver.isDataPresent()",
        "if (digestResolver.responsesMatch())",
        "setResult(digestResolver.getData());",
        "readRepair.startRepair(digestResolver, this::setResult);",
        "logger.info(\"Blocking Read Repair triggered for query",
        "readRepair.awaitReads();",
        "throw new ReadTimeoutException(replicaPlan().consistencyLevel(), handler.blockFor - 1, handler.blockFor, true);",
        "readRepair.maybeSendAdditionalReads();",
    ),
    "src/java/org/apache/cassandra/service/reads/DigestResolver.java": (
        "public class DigestResolver",
        "Preconditions.checkArgument(command instanceof SinglePartitionReadCommand",
        "if (dataResponse == null && !message.payload.isDigestResponse() && replica.isFull())",
        "public boolean responsesMatch()",
        "if (replicaPlan().lookup(message.from()).isTransient())",
        "else if (!digest.equals(newDigest))",
        "public DigestResolverDebugResult[] getDigestsByEndpoint()",
    ),
    "src/java/org/apache/cassandra/service/reads/DataResolver.java": (
        "private final ReadRepair<E, P> readRepair;",
        "private final boolean trackRepairedStatus;",
        "RepairedDataTracker repairedDataTracker = trackRepairedStatus",
        "msg.payload.mayIncludeRepairedDigest()",
        "repairedDataTracker.recordDigest",
        "private boolean needsReadRepair()",
        "if (command.isTopK())",
        "private boolean needShortReadProtection()",
        "ShortReadProtection.extend",
        "if (context.needsReadRepair() && readRepair != NoopReadRepair.instance)",
        "listener = wrapMergeListener(readRepair.getMergeListener(sources), sources, repairedDataTracker);",
        "ReplicaFilteringProtection",
        "protected RepairedDataVerifier getRepairedDataVerifier(ReadCommand command)",
        "repairedDataTracker.verify();",
    ),
    "src/java/org/apache/cassandra/service/reads/repair/ReadRepair.java": (
        "public interface ReadRepair",
        "ReadRepair<E, P> create(ReadCommand command, ReplicaPlan.Shared<E, P> replicaPlan, Dispatcher.RequestTime requestTime)",
        "UnfilteredPartitionIterators.MergeListener getMergeListener(P replicaPlan);",
        "public void startRepair(DigestResolver<E, P> digestResolver, Consumer<PartitionIterator> resultConsumer);",
        "public void awaitReads() throws ReadTimeoutException;",
        "public void maybeSendAdditionalReads();",
        "public void maybeSendAdditionalWrites();",
        "public void awaitWrites();",
        "void repairPartition(DecoratedKey partitionKey, Map<Replica, Mutation> mutations, ReplicaPlan.ForWrite writePlan);",
    ),
    "src/java/org/apache/cassandra/service/reads/repair/AbstractReadRepair.java": (
        "public abstract class AbstractReadRepair",
        "void sendReadCommand(Replica to, ReadCallback<E, P> readCallback, boolean speculative, boolean trackRepairedStatus)",
        "new StorageProxy.LocalReadRunnable(command, readCallback, requestTime, trackRepairedStatus)",
        "command.copyAsTransientQuery(to)",
        "Message<ReadCommand> message = command.createMessage(trackRepairedStatus && to.isFull(), requestTime);",
        "MessagingService.instance().sendWithCallback(message, to.endpoint(), readCallback);",
        "public void startRepair(DigestResolver<E, P> digestResolver, Consumer<PartitionIterator> resultConsumer)",
        "boolean trackRepairedStatus = DatabaseDescriptor.getRepairedDataTrackingForPartitionReadsEnabled();",
        "DataResolver<E, P> resolver = new DataResolver<>(command, replicaPlan, this, requestTime, trackRepairedStatus);",
        "ReadCallback<E, P> readCallback = new ReadCallback<>(resolver, command, replicaPlan, requestTime);",
        "sendReadCommand(replica, readCallback, false, trackRepairedStatus);",
        "ReadRepairDiagnostics.startRepair(this, replicaPlan(), digestResolver);",
        "repair.readCallback.awaitResults();",
        "ReadRepairMetrics.timedOut.mark();",
        "repair.resultConsumer.accept(digestRepair.dataResolver.resolve());",
        "private boolean shouldSpeculate()",
        "consistency != ConsistencyLevel.EACH_QUORUM",
        "cfs.sampleReadLatencyMicros <= command.getTimeout(MICROSECONDS)",
        "public void maybeSendAdditionalReads()",
        "replicaPlan.addToContacts(uncontacted);",
        "ReadRepairMetrics.speculatedRead.mark();",
        "ReadRepairDiagnostics.speculatedRead(this, uncontacted.endpoint(), replicaPlan());",
    ),
    "src/java/org/apache/cassandra/service/reads/repair/BlockingReadRepair.java": (
        "public class BlockingReadRepair",
        "protected final Queue<BlockingPartitionRepair> repairs = new ConcurrentLinkedQueue<>();",
        "return new PartitionIteratorMergeListener<>(replicaPlan, command, this);",
        "return ReadRepairMetrics.repairedBlocking;",
        "public void maybeSendAdditionalWrites()",
        "repair.maybeSendAdditionalWrites(cfs.additionalWriteLatencyMicros, MICROSECONDS);",
        "public void awaitWrites()",
        "repair.awaitRepairsUntil(deadline, NANOSECONDS)",
        "throw new ReadTimeoutException(replicaPlan().consistencyLevel(), received, blockFor, true);",
        "public void repairPartition(DecoratedKey partitionKey, Map<Replica, Mutation> mutations, ReplicaPlan.ForWrite writePlan)",
        "blockingRepair.sendInitialRepairs();",
    ),
    "src/java/org/apache/cassandra/service/reads/repair/ReadOnlyReadRepair.java": (
        "public class ReadOnlyReadRepair",
        "return UnfilteredPartitionIterators.MergeListener.NOOP;",
        "return ReadRepairMetrics.reconcileRead;",
        "public void maybeSendAdditionalWrites()",
        "throw new UnsupportedOperationException(\"ReadOnlyReadRepair shouldn't be trying to repair partitions\");",
        "public void awaitWrites()",
    ),
    "src/java/org/apache/cassandra/service/reads/repair/NoopReadRepair.java": (
        "public class NoopReadRepair",
        "public static final NoopReadRepair instance = new NoopReadRepair();",
        "return UnfilteredPartitionIterators.MergeListener.NOOP;",
        "resultConsumer.accept(digestResolver.getData());",
    ),
    "src/java/org/apache/cassandra/service/reads/repair/BlockingPartitionRepair.java": (
        "public class BlockingPartitionRepair",
        "extends AsyncFuture<Object> implements RequestCallback<Object>",
        "private final Map<Replica, Mutation> pendingRepairs;",
        "int blockFor = writePlan.writeQuorum();",
        "blockFor--;",
        "Preconditions.checkState(!writePlan.consistencyLevel().isDatacenterLocal() || InOurDc.replicas().test(participant)",
        "latch = newCountDownLatch(Math.max(blockFor, 0));",
        "void ack(InetAddressAndPort from)",
        "private PartitionUpdate mergeUnackedUpdates()",
        "public void sendInitialRepairs()",
        "Replicas.assertFull(pendingRepairs.keySet());",
        "Message.out(READ_REPAIR_REQ, mutation)",
        "ColumnFamilyStore.metricsFor(tableId).readRepairRequests.mark();",
        "ReadRepairDiagnostics.sendInitialRepair(this, destination.endpoint(), mutation);",
        "public boolean awaitRepairsUntil(long timeoutAt, TimeUnit timeUnit)",
        "public void maybeSendAdditionalWrites(long timeout, TimeUnit timeoutUnit)",
        "writePlan.liveUncontacted()",
        "ReadRepairMetrics.speculatedWrite.mark();",
        "BlockingReadRepairs.createRepairMutation(update, writePlan.consistencyLevel(), replica.endpoint(), true)",
        "ReadRepairDiagnostics.speculatedWriteOversized(this, replica.endpoint());",
        "ReadRepairDiagnostics.speculatedWrite(this, replica.endpoint(), mutation);",
    ),
    "src/java/org/apache/cassandra/service/reads/repair/RepairedDataTracker.java": (
        "public class RepairedDataTracker",
        "public final Multimap<ByteBuffer, InetAddressAndPort> digests = HashMultimap.create();",
        "public final Set<InetAddressAndPort> inconclusiveDigests = new HashSet<>();",
        "public void recordDigest(InetAddressAndPort source, ByteBuffer digest, boolean isConclusive)",
        "if (!isConclusive)",
        "public void verify()",
        "verifier.verify(this);",
    ),
    "src/java/org/apache/cassandra/service/reads/repair/RepairedDataVerifier.java": (
        "public interface RepairedDataVerifier",
        "static RepairedDataVerifier verifier(ReadCommand command)",
        "DatabaseDescriptor.snapshotOnRepairedDataMismatch() ? snapshotting(command) : simple(command)",
        "static class SimpleVerifier implements RepairedDataVerifier",
        "if (tracker.digests.keySet().size() > 1)",
        "if (tracker.inconclusiveDigests.isEmpty())",
        "metrics.confirmedRepairedInconsistencies.mark();",
        "else if (DatabaseDescriptor.reportUnconfirmedRepairedDataMismatches())",
        "metrics.unconfirmedRepairedInconsistencies.mark();",
        "static class SnapshottingVerifier extends SimpleVerifier",
        "DiagnosticSnapshotService.repairedDataMismatch(command.metadata(), tracker.digests.values());",
    ),
    "src/java/org/apache/cassandra/service/reads/repair/ReadRepairDiagnostics.java": (
        "static void startRepair(AbstractReadRepair readRepair, ReplicaPlan.ForRead<?, ?> fullPlan, DigestResolver digestResolver)",
        "ReadRepairEventType.START_REPAIR",
        "static void speculatedRead(AbstractReadRepair readRepair, InetAddressAndPort endpoint,",
        "ReadRepairEventType.SPECULATED_READ",
        "static void sendInitialRepair(BlockingPartitionRepair partitionRepair, InetAddressAndPort destination, Mutation mutation)",
        "PartitionRepairEventType.SEND_INITIAL_REPAIRS",
        "static void speculatedWrite(BlockingPartitionRepair partitionRepair, InetAddressAndPort destination, Mutation mutation)",
        "PartitionRepairEventType.SPECULATED_WRITE",
        "static void speculatedWriteOversized(BlockingPartitionRepair partitionRepair, InetAddressAndPort destination)",
        "PartitionRepairEventType.UPDATE_OVERSIZED",
    ),
    "src/java/org/apache/cassandra/service/reads/repair/ReadRepairEvent.java": (
        "final class ReadRepairEvent extends DiagnosticEvent",
        "START_REPAIR",
        "SPECULATED_READ",
        "ret.put(\"keyspace\", keyspace.getName());",
        "ret.put(\"speculativeRetry\", speculativeRetry.name());",
        "ret.put(\"endpointDestinations\", new HashSet<>(eps));",
        "ret.put(\"digestsByEndpoint\", digestsMap);",
    ),
    "src/java/org/apache/cassandra/metrics/ReadRepairMetrics.java": (
        "public class ReadRepairMetrics",
        "public static final Meter repairedBlocking",
        "public static final Meter reconcileRead",
        "public static final Meter timedOut",
        "public static final Meter speculatedRead",
        "public static final Meter speculatedWrite",
    ),
    "src/java/org/apache/cassandra/service/StorageProxyMBean.java": (
        "public void logBlockingReadRepairAttemptsForNSeconds(int seconds);",
        "public boolean isLoggingReadRepairs();",
        "void enableRepairedDataTrackingForRangeReads();",
        "void enableRepairedDataTrackingForPartitionReads();",
        "void enableReportingUnconfirmedRepairedDataMismatches();",
        "void enableSnapshotOnRepairedDataMismatch();",
    ),
    "src/java/org/apache/cassandra/service/StorageProxy.java": (
        "public static PartitionIterator concatAndBlockOnRepair(List<PartitionIterator> iterators, List<ReadRepair<?, ?>> repairs)",
        "repairs.forEach(ReadRepair::maybeSendAdditionalWrites);",
        "repairs.forEach(ReadRepair::awaitWrites);",
        "private volatile long logBlockingReadRepairAttemptsUntilNanos",
        "boolean logBlockingRepairAttempts = instance.isLoggingReadRepairs();",
        "DatabaseDescriptor.setRepairedDataTrackingForRangeReadsEnabled(true);",
        "DatabaseDescriptor.setRepairedDataTrackingForPartitionReadsEnabled(true);",
        "DatabaseDescriptor.reportUnconfirmedRepairedDataMismatches(true);",
        "DatabaseDescriptor.setSnapshotOnRepairedDataMismatch(true);",
        "public void logBlockingReadRepairAttemptsForNSeconds(int seconds)",
        "logBlockingReadRepairAttemptsUntilNanos = nanoTime() + TimeUnit.SECONDS.toNanos(seconds);",
        "public boolean isLoggingReadRepairs()",
    ),
}

TEST_EXPECTATIONS = {
    "test/unit/org/apache/cassandra/service/reads/DigestResolverTest.java": (
        "public void noRepairNeeded()",
        "public void digestMismatch()",
        "public void transientResponse()",
    ),
    "test/unit/org/apache/cassandra/service/reads/DataResolverTest.java": (
        "public void testResolveNewerSingleRow()",
        "assertEquals(1, readRepair.sent.size());",
        "public void testRepairRangeTombstoneBoundary()",
        "public void trackMatchingEmptyDigestsWithAllConclusive()",
        "public void trackMismatchingRepairedDigestsWithAllConclusive()",
        "public void trackMismatchingRepairedDigestsWithDifferentData()",
    ),
    "test/unit/org/apache/cassandra/service/reads/repair/AbstractReadRepairTest.java": (
        "static void configureClass(ReadRepairStrategy repairStrategy) throws Throwable",
        "assert cfm.params.readRepair == repairStrategy;",
        "repair.startRepair(null, consumer);",
        "repair.maybeSendAdditionalReads();",
    ),
    "test/unit/org/apache/cassandra/service/reads/repair/BlockingReadRepairTest.java": (
        "configureClass(ReadRepairStrategy.BLOCKING);",
        "public void additionalMutationRequired() throws Exception",
        "handler.maybeSendAdditionalWrites(0, TimeUnit.NANOSECONDS);",
        "public void noAdditionalMutationRequired() throws Exception",
        "public void noAdditionalMutationPossible() throws Exception",
        "public void onlyBlockOnQuorum()",
        "public void remoteDCSpeculativeRetryTest() throws Exception",
    ),
    "test/unit/org/apache/cassandra/service/reads/repair/ReadOnlyReadRepairTest.java": (
        "configureClass(ReadRepairStrategy.NONE);",
        "public void getMergeListener()",
        "public void repairPartitionFailure()",
    ),
    "test/unit/org/apache/cassandra/service/reads/repair/RepairedDataVerifierTest.java": (
        "public void repairedDataMismatchWithSomeConclusive()",
        "public void repairedDataMismatchWithNoneConclusive()",
        "public void repairedDataMismatchWithAllConclusive()",
        "public void repairedDataMatchesWithAllConclusive()",
        "public void noTrackingDataRecorded()",
        "metrics.confirmedRepairedInconsistencies.table.getCount()",
        "metrics.unconfirmedRepairedInconsistencies.table.getCount()",
    ),
    "test/unit/org/apache/cassandra/service/reads/repair/DiagEventsBlockingReadRepairTest.java": (
        "public class DiagEventsBlockingReadRepairTest extends AbstractReadRepairTest",
        "configureClass(ReadRepairStrategy.BLOCKING);",
        "public void additionalMutationRequired()",
        "ReadRepairEventType.START_REPAIR",
        "ReadRepairEventType.SPECULATED_READ",
    ),
    "test/unit/org/apache/cassandra/service/StorageProxyTest.java": (
        "public void testTransientLoggingTimer()",
        "StorageProxy.instance.logBlockingReadRepairAttemptsForNSeconds(2);",
        "StorageProxy.instance.isLoggingReadRepairs()",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/ReadRepairTest.java": (
        "public void testBlockingReadRepair() throws Throwable",
        "testReadRepair(ReadRepairStrategy.BLOCKING);",
        "public void testNoneReadRepair() throws Throwable",
        "testReadRepair(ReadRepairStrategy.NONE);",
        "public void readRepairTimeoutTest() throws Throwable",
        "public void failingReadRepairTest() throws Throwable",
        "public void movingTokenReadRepairTest() throws Throwable",
        "public void alterRFAndRunReadRepair() throws Throwable",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/RepairDigestTrackingTest.java": (
        "public void testInconsistenciesFound() throws Throwable",
        "StorageProxy.instance.enableRepairedDataTrackingForRangeReads()",
        "public void testSnapshottingOnInconsistency() throws Throwable",
        "StorageProxy.instance.enableRepairedDataTrackingForPartitionReads()",
        "StorageProxy.instance.enableSnapshotOnRepairedDataMismatch()",
        "public void testRepairedReadCountNormalizationWithInitialUnderread() throws Throwable",
        "public void testLocalDataAndRemoteRequestConcurrency() throws Exception",
    ),
}

DOC_EXPECTATIONS = {
    MATRIX_DOC: SCENARIOS + (
        "Read Repair And Repaired Data Matrix",
        "BlockingReadRepair",
        "ReadOnlyReadRepair",
        "BlockingPartitionRepair",
        "RepairedDataTracker",
        "RepairedDataVerifier",
        "ReadRepairMetrics",
    ),
    CHECKER_DOC: SCENARIOS + (
        "Read Repair And Repaired Data Drift Checker",
        "14 scenarios",
        "check-read-repair-repaired-data-drift.py",
    ),
    README_DOC: (
        "module-read-repair-repaired-data-matrix.md",
        "module-read-repair-repaired-data-drift-checker.md",
        "research/tools/check-read-repair-repaired-data-drift.py",
    ),
    SOURCE_MAP_DOC: (
        "Read repair repaired data",
        "module-read-repair-repaired-data-matrix.md",
        "module-read-repair-repaired-data-drift-checker.md",
        "research/tools/check-read-repair-repaired-data-drift.py",
        "src/java/org/apache/cassandra/service/reads/repair/ReadRepairStrategy.java:26",
        "src/java/org/apache/cassandra/service/reads/repair/AbstractReadRepair.java:126",
        "src/java/org/apache/cassandra/service/reads/repair/BlockingPartitionRepair.java:47",
        "src/java/org/apache/cassandra/service/reads/repair/RepairedDataVerifier.java:38",
    ),
}


@dataclass
class Failure:
    category: str
    path: str
    detail: str


def check_tokens(expectations, category):
    failures = []
    for path, tokens in expectations.items():
        full = REPO_ROOT / path
        if not full.exists():
            failures.append(Failure(category, path, "missing file"))
            continue
        text = full.read_text(encoding="utf-8")
        for token in tokens:
            if token not in text:
                failures.append(Failure(category, path, f"missing token: {token}"))
    return failures


def main(argv):
    parser = argparse.ArgumentParser(description="Check read repair repaired-data research coverage for drift.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable result")
    args = parser.parse_args(argv)

    failures = []
    failures.extend(check_tokens(SOURCE_EXPECTATIONS, "source"))
    failures.extend(check_tokens(TEST_EXPECTATIONS, "test"))
    failures.extend(check_tokens(DOC_EXPECTATIONS, "doc"))

    if args.json:
        print(json.dumps({
            "ok": not failures,
            "scenario_count": len(SCENARIOS),
            "failures": [failure.__dict__ for failure in failures],
        }, indent=2, sort_keys=True))
    elif failures:
        for failure in failures:
            print(f"{failure.category}: {failure.path}: {failure.detail}", file=sys.stderr)
    else:
        print(f"OK read repair repaired-data drift checks passed ({len(SCENARIOS)} scenarios)")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
