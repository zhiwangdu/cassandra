#!/usr/bin/env python3
#
# Source-only drift check for StorageProxy ordinary read/write coordinator research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

STORAGE_PROXY = "src/java/org/apache/cassandra/service/StorageProxy.java"
ABSTRACT_WRITE_RESPONSE_HANDLER = "src/java/org/apache/cassandra/service/AbstractWriteResponseHandler.java"
WRITE_RESPONSE_HANDLER = "src/java/org/apache/cassandra/service/WriteResponseHandler.java"
DC_WRITE_RESPONSE_HANDLER = "src/java/org/apache/cassandra/service/DatacenterWriteResponseHandler.java"
DC_SYNC_WRITE_RESPONSE_HANDLER = "src/java/org/apache/cassandra/service/DatacenterSyncWriteResponseHandler.java"
READ_CALLBACK = "src/java/org/apache/cassandra/service/reads/ReadCallback.java"
ABSTRACT_READ_EXECUTOR = "src/java/org/apache/cassandra/service/reads/AbstractReadExecutor.java"
DIGEST_RESOLVER = "src/java/org/apache/cassandra/service/reads/DigestResolver.java"
DATA_RESOLVER = "src/java/org/apache/cassandra/service/reads/DataResolver.java"
READ_REPAIR = "src/java/org/apache/cassandra/service/reads/repair/ReadRepair.java"
ABSTRACT_READ_REPAIR = "src/java/org/apache/cassandra/service/reads/repair/AbstractReadRepair.java"
BLOCKING_READ_REPAIR = "src/java/org/apache/cassandra/service/reads/repair/BlockingReadRepair.java"
READ_ONLY_READ_REPAIR = "src/java/org/apache/cassandra/service/reads/repair/ReadOnlyReadRepair.java"
STORAGE_PROXY_MBEAN = "src/java/org/apache/cassandra/service/StorageProxyMBean.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
TABLE_PARAMS = "src/java/org/apache/cassandra/schema/TableParams.java"

WRITE_RESPONSE_HANDLER_TEST = "test/unit/org/apache/cassandra/service/WriteResponseHandlerTest.java"
READ_EXECUTOR_TEST = "test/unit/org/apache/cassandra/service/reads/ReadExecutorTest.java"
STORAGE_PROXY_TEST = "test/unit/org/apache/cassandra/service/StorageProxyTest.java"
PARTITION_DENYLIST_TEST = "test/unit/org/apache/cassandra/service/PartitionDenylistTest.java"
DIGEST_RESOLVER_TEST = "test/unit/org/apache/cassandra/service/reads/DigestResolverTest.java"
DATA_RESOLVER_TEST = "test/unit/org/apache/cassandra/service/reads/DataResolverTest.java"
REQUEST_TIMEOUT_TEST = "test/distributed/org/apache/cassandra/distributed/test/metrics/RequestTimeoutTest.java"
READ_SPECULATION_TEST = "test/distributed/org/apache/cassandra/distributed/test/ReadSpeculationTest.java"
READ_FAILURE_TEST = "test/distributed/org/apache/cassandra/distributed/test/ReadFailureTest.java"
READ_REPAIR_TEST = "test/distributed/org/apache/cassandra/distributed/test/ReadRepairTest.java"
OPTIONAL_TASKS_TEST = "test/unit/org/apache/cassandra/service/OptionalTasksTest.java"

TARGET_DOCS = (
    "research/module-storageproxy-coordinator-timeout-matrix.md",
    "research/module-storageproxy-coordinator-drift-checker.md",
    "research/module-read-path.md",
    "research/flow-read.md",
    "research/flow-write.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "storageproxy_write_response_handler_lifecycle",
    "storageproxy_write_timeout_failure_metrics",
    "storageproxy_write_local_remote_hint_dispatch",
    "storageproxy_write_cheap_quorum_additional_replicas",
    "storageproxy_read_safety_denylist_dispatch",
    "storageproxy_read_executor_selection_speculation",
    "storageproxy_read_callback_timeout_failure_warning",
    "storageproxy_read_digest_mismatch_repair",
    "storageproxy_read_repair_write_blocking",
    "storageproxy_coordinator_latency_metrics",
    "storageproxy_mbean_operational_surface",
    "storageproxy_existing_tests_baseline",
)

SOURCE_TOKEN_CHECKS = {
    STORAGE_PROXY: (
        "public static void mutate(List<? extends IMutation> mutations",
        "responseHandlers.get(i).maybeTryAdditionalReplicas",
        "responseHandler.get();",
        "hintMutations(mutations);",
        "writeMetrics.failures.mark();",
        "writeMetrics.timeouts.mark();",
        "updateCoordinatorWriteLatencyTableMetric(mutations, latency);",
        "public static AbstractWriteResponseHandler<IMutation> performWrite",
        "ReplicaPlans.forWrite(keyspace, consistencyLevel, tk, ReplicaPlans.writeNormal);",
        "rs.getWriteResponseHandler(replicaPlan, callback, writeType, mutation.hintOnFailure(), requestTime);",
        "public static void sendToHintedReplicas",
        "Collections.singletonList(MessageFlag.CALL_BACK_ON_FAILURE)",
        "responseHandler.expired();",
        "submitHint(mutation, EndpointsForToken.copyOf(mutation.key().getToken(), endpointsToHint), responseHandler);",
        "performLocally(stage, localReplica, mutation::apply, responseHandler, mutation, requestTime);",
        "MessagingService.instance().sendWriteWithCallback(message, destination, responseHandler);",
        "public static PartitionIterator read(SinglePartitionReadCommand.Group group",
        "DatabaseDescriptor.getPartitionDenylistEnabled() && DatabaseDescriptor.getDenylistReadsEnabled()",
        "partitionDenylist.isKeyPermitted",
        "? readWithPaxos(group, consistencyLevel, requestTime)",
        "private static PartitionIterator readRegular",
        "recordReadRegularAbort(consistencyLevel, e);",
        "Keyspace.openAndGetStore(command.metadata()).metric.coordinatorReadLatency.update",
        "private static PartitionIterator fetchRows",
        "AbstractReadExecutor.getReadExecutor",
        "reads[i].executeAsync();",
        "reads[i].maybeTryAdditionalReplicas();",
        "reads[i].awaitResponses(logBlockingRepairAttempts);",
        "reads[i].maybeSendAdditionalDataRequests();",
        "reads[i].awaitReadRepair();",
        "return concatAndBlockOnRepair(results, repairs);",
        "repairs.forEach(ReadRepair::maybeSendAdditionalWrites);",
        "repairs.forEach(ReadRepair::awaitWrites);",
        "public void setReadRpcTimeout(Long timeoutInMillis)",
        "public void logBlockingReadRepairAttemptsForNSeconds(int seconds)",
    ),
    ABSTRACT_WRITE_RESPONSE_HANDLER: (
        "public void get() throws WriteTimeoutException, WriteFailureException",
        "condition.await(timeoutNanos, NANOSECONDS);",
        "if (!signaled)",
        "throwTimeout();",
        "if (blockFor() + failures > candidateReplicaCount())",
        "RequestCallback.isTimeout(this.failureReasonByEndpoint.keySet().stream()",
        "throw new WriteFailureException(replicaPlan.consistencyLevel(), ackCount(), blockFor(), writeType, this.failureReasonByEndpoint);",
        "writeType == COUNTER",
        "? getCounterWriteRpcTimeout(NANOSECONDS)",
        ": getWriteRpcTimeout(NANOSECONDS);",
        "failureReasonByEndpoint.put(from, failureReason);",
        "StorageProxy.submitHint(hintOnFailure.get(), replicaPlan.lookup(from), null);",
        "public void maybeTryAdditionalReplicas(IMutation mutation, WritePerformer writePerformer, String localDC)",
        "cf.metric.additionalWrites.inc();",
    ),
    WRITE_RESPONSE_HANDLER: (
        "public class WriteResponseHandler<T> extends AbstractWriteResponseHandler<T>",
        "responses = blockFor();",
        "if (responsesUpdater.decrementAndGet(this) == 0)",
        "protected int ackCount()",
    ),
    DC_WRITE_RESPONSE_HANDLER: (
        "public class DatacenterWriteResponseHandler<T> extends WriteResponseHandler<T>",
        "assert replicaPlan.consistencyLevel().isDatacenterLocal();",
        "if (message == null || waitingFor(message.from()))",
        "protected boolean waitingFor(InetAddressAndPort from)",
    ),
    DC_SYNC_WRITE_RESPONSE_HANDLER: (
        "public class DatacenterSyncWriteResponseHandler<T> extends AbstractWriteResponseHandler<T>",
        "assert replicaPlan.consistencyLevel() == ConsistencyLevel.EACH_QUORUM;",
        "responses.put(dc, new AtomicInteger((rf / 2) + 1));",
        "for (Replica pending : replicaPlan.pending())",
        "responses.get(dataCenter).getAndDecrement();",
    ),
    READ_CALLBACK: (
        "public void awaitResults() throws ReadFailureException, ReadTimeoutException",
        "boolean signaled = await(command.getTimeout(MILLISECONDS), TimeUnit.MILLISECONDS);",
        "boolean failed = failures > 0 && (blockFor > received || !resolver.isDataPresent());",
        "timedout = RequestCallback.isTimeout(new HashMap<>(failureReasonByEndpoint));",
        "CoordinatorWarnings.update(command, snapshot);",
        "snapshot.maybeAbort(command, replicaPlan().consistencyLevel(), received, blockFor, resolver.isDataPresent(), failureReasonByEndpoint);",
        "throw !timedout",
        "new ReadFailureException(replicaPlan().consistencyLevel(), received, blockFor, resolver.isDataPresent(), failureReasonByEndpoint)",
        "new ReadTimeoutException(replicaPlan().consistencyLevel(), received, blockFor, resolver.isDataPresent());",
        "resolver.preprocess(message);",
        "if (resolver.isDataPresent() && resolver.responses.size() >= blockFor)",
        "failureReasonByEndpoint.put(from, failureReason);",
    ),
    ABSTRACT_READ_EXECUTOR: (
        "SpeculativeRetryPolicy retry = cfs.metadata().params.speculativeRetry;",
        "ReplicaPlans.forRead(keyspace,",
        "retry.equals(NeverSpeculativeRetryPolicy.INSTANCE) || consistencyLevel == ConsistencyLevel.EACH_QUORUM",
        "return new AlwaysSpeculatingReadExecutor(cfs, command, replicaPlan, requestTime);",
        "return new SpeculatingReadExecutor(cfs, command, replicaPlan, requestTime);",
        "long sampleLatencyNanos = MICROSECONDS.toNanos(cfs.sampleReadLatencyMicros);",
        "sampleLatencyNanos > command.getTimeout(NANOSECONDS)",
        "now + sampleLatencyNanos > requestTime.clientDeadline()",
        "cfs.metric.speculativeInsufficientReplicas.inc();",
        "cfs.metric.speculativeRetries.inc();",
        "cfs.metric.speculativeFailedRetries.inc();",
        "readRepair.startRepair(digestResolver, this::setResult);",
        "readRepair.awaitReads();",
        "new ReadTimeoutException(replicaPlan().consistencyLevel(), handler.blockFor - 1, handler.blockFor, true)",
        "readRepair.maybeSendAdditionalReads();",
    ),
    DIGEST_RESOLVER: (
        "public class DigestResolver",
        "if (dataResponse == null && !message.payload.isDigestResponse() && replica.isFull())",
        "if (!hasTransientResponse(responses))",
        "return UnfilteredPartitionIterators.filter(dataResponse.payload.makeIterator(command), command.nowInSec());",
        "DataResolver<E, P> dataResolver",
        "if (!digest.equals(newDigest))",
        "return false;",
    ),
    DATA_RESOLVER: (
        "public class DataResolver",
        "private final ReadRepair<E, P> readRepair;",
        "private final boolean trackRepairedStatus;",
        "RepairedDataTracker repairedDataTracker = trackRepairedStatus",
        "resolveWithReadRepair",
        "listener = wrapMergeListener(readRepair.getMergeListener(sources), sources, repairedDataTracker);",
        "ShortReadProtection.extend",
        "ReplicaFilteringProtection<E> rfp",
    ),
    READ_REPAIR: (
        "ReadRepair<E, P> create(ReadCommand command, ReplicaPlan.Shared<E, P> replicaPlan, Dispatcher.RequestTime requestTime)",
        "return command.metadata().params.readRepair.create(command, replicaPlan, requestTime);",
        "public void startRepair(DigestResolver<E, P> digestResolver, Consumer<PartitionIterator> resultConsumer);",
        "public void maybeSendAdditionalWrites();",
        "public void awaitWrites();",
    ),
    ABSTRACT_READ_REPAIR: (
        "public void startRepair(DigestResolver<E, P> digestResolver, Consumer<PartitionIterator> resultConsumer)",
        "DatabaseDescriptor.getRepairedDataTrackingForPartitionReadsEnabled();",
        "new DataResolver<>(command, replicaPlan, this, requestTime, trackRepairedStatus);",
        "new ReadCallback<>(resolver, command, replicaPlan, requestTime);",
        "ReadRepairDiagnostics.startRepair(this, replicaPlan(), digestResolver);",
        "public void awaitReads() throws ReadTimeoutException",
        "ReadRepairMetrics.timedOut.mark();",
        "public void maybeSendAdditionalReads()",
        "ReadRepairMetrics.speculatedRead.mark();",
    ),
    BLOCKING_READ_REPAIR: (
        "public class BlockingReadRepair",
        "ReadRepairMetrics.repairedBlocking",
        "repair.maybeSendAdditionalWrites(cfs.additionalWriteLatencyMicros, MICROSECONDS);",
        "requestTime.computeDeadline(DatabaseDescriptor.getReadRpcTimeout(NANOSECONDS));",
        "new ReadTimeoutException(replicaPlan().consistencyLevel(), received, blockFor, true);",
        "blockingRepair.sendInitialRepairs();",
    ),
    READ_ONLY_READ_REPAIR: (
        "public class ReadOnlyReadRepair",
        "ReadRepairMetrics.reconcileRead",
        "UnfilteredPartitionIterators.MergeListener.NOOP",
        "ReadOnlyReadRepair shouldn't be trying to repair partitions",
    ),
    STORAGE_PROXY_MBEAN: (
        "public Long getReadRpcTimeout();",
        "public Long getWriteRpcTimeout();",
        "public long getReadRepairAttempted();",
        "public long getReadRepairRepairedBlocking();",
        "public long getReadRepairRepairTimedOut();",
        "public void logBlockingReadRepairAttemptsForNSeconds(int seconds);",
        "void enableRepairedDataTrackingForPartitionReads();",
    ),
    CONFIG: (
        "public volatile DurationSpec.LongMillisecondsBound read_request_timeout",
        "public volatile DurationSpec.LongMillisecondsBound write_request_timeout",
        "public volatile DurationSpec.LongMillisecondsBound counter_write_request_timeout",
        "public volatile boolean partition_denylist_enabled = false;",
        "public volatile boolean denylist_reads_enabled = true;",
        "public volatile CQLStartTime cql_start_time = CQLStartTime.REQUEST;",
        "public DurationSpec.LongMillisecondsBound native_transport_timeout",
    ),
    DATABASE_DESCRIPTOR: (
        "return conf.read_request_timeout.to(unit);",
        "conf.read_request_timeout = new DurationSpec.LongMillisecondsBound(timeOutInMillis);",
        "return conf.write_request_timeout.to(unit);",
        "conf.write_request_timeout = new DurationSpec.LongMillisecondsBound(timeOutInMillis);",
        "return conf.counter_write_request_timeout.to(unit);",
        "conf.counter_write_request_timeout = new DurationSpec.LongMillisecondsBound(timeOutInMillis);",
        "return conf.cql_start_time;",
        "conf.cql_start_time = value;",
        "return conf.partition_denylist_enabled;",
        "return conf.denylist_reads_enabled;",
    ),
    TABLE_PARAMS: (
        ".append(\"AND read_repair = \").appendWithSingleQuotes(readRepair.toString())",
        ".append(\"AND speculative_retry = \").appendWithSingleQuotes(speculativeRetry.toString())",
    ),
    WRITE_RESPONSE_HANDLER_TEST: (
        "public class WriteResponseHandlerTest",
        "idealCLLatencyTracked",
        "failedIdealCLIncrementsStat",
        "failedIdealCLIncrementsStatForExplicitOnFailure",
    ),
    READ_EXECUTOR_TEST: (
        "public class ReadExecutorTest",
        "testUnableToSpeculate",
        "testSpeculateSucceeded",
        "testSpeculateFailed",
        "testRaceWithNonSpeculativeFailure",
    ),
    STORAGE_PROXY_TEST: (
        "testShouldHint",
        "testShouldHintOnWindowExpiry",
        "testShouldHintOnExceedingSize",
        "testTransientLoggingTimer",
    ),
    PARTITION_DENYLIST_TEST: (
        "public class PartitionDenylistTest",
        "DatabaseDescriptor.setPartitionDenylistEnabled(true)",
        "StorageProxy.instance.loadPartitionDenylist();",
    ),
    DIGEST_RESOLVER_TEST: ("public class DigestResolverTest",),
    DATA_RESOLVER_TEST: ("public class DataResolverTest", "new TestableReadRepair(command)"),
    REQUEST_TIMEOUT_TEST: (
        "public class RequestTimeoutTest",
        "public void insert()",
        "public void select()",
        "WriteTimeoutException.class",
        "ReadTimeoutException.class",
    ),
    READ_SPECULATION_TEST: (
        "public class ReadSpeculationTest",
        "public void speculateTest()",
        "assertWillSpeculate",
        "assertWillNotSpeculate",
    ),
    READ_FAILURE_TEST: (
        "public class ReadFailureTest",
        "public void testSpecExecRace()",
        "READ_TOO_MANY_TOMBSTONES",
    ),
    READ_REPAIR_TEST: (
        "public class ReadRepairTest",
        "testBlockingReadRepair",
        "testNoneReadRepair",
        "readRepairTimeoutTest",
        "failingReadRepairTest",
        "movingTokenReadRepairTest",
    ),
    OPTIONAL_TASKS_TEST: ("coordinatorReadLatency.update",),
}

DOC_TOKEN_CHECKS = (
    "module-storageproxy-coordinator-timeout-matrix.md",
    "module-storageproxy-coordinator-drift-checker.md",
    "research/tools/check-storageproxy-coordinator-drift.py",
    "StorageProxy.mutate()",
    "AbstractWriteResponseHandler.get()",
    "sendToHintedReplicas()",
    "ReadCallback.awaitResults()",
    "AbstractReadExecutor.getReadExecutor()",
    "ReadRepair.startRepair()",
    "BlockingReadRepair.awaitWrites()",
    "read_request_timeout",
    "write_request_timeout",
    "counter_write_request_timeout",
    "native_transport_timeout",
    "speculative_retry",
    "read_repair",
    "StorageProxyMBean",
    "WriteResponseHandlerTest",
    "ReadExecutorTest",
    "RequestTimeoutTest",
    "ReadSpeculationTest",
    "ReadFailureTest",
    "ReadRepairTest",
)


@dataclass
class CheckResult:
    name: str
    checks: int


def read_text(path):
    full_path = REPO_ROOT / path
    if not full_path.exists():
        raise AssertionError(f"missing file {path}")
    return full_path.read_text(encoding="utf-8")


def require_tokens(label, path, tokens):
    text = read_text(path)
    missing = [token for token in tokens if token not in text]
    if missing:
        formatted = "\n".join(f"  - {token}" for token in missing)
        raise AssertionError(f"{label} token contract failed for {path}:\n{formatted}")
    return CheckResult(f"{label}: {path}", len(tokens))


def require_doc_tokens():
    doc_text = "\n".join(read_text(path) for path in TARGET_DOCS)
    tokens = tuple(DOC_TOKEN_CHECKS) + SCENARIO_IDS
    missing = [token for token in tokens if token not in doc_text]
    if missing:
        formatted = "\n".join(f"  - {token}" for token in missing)
        raise AssertionError(f"doc token contract failed:\n{formatted}")
    return CheckResult("doc tokens", len(tokens))


def run_checks():
    results = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        results.append(require_tokens("source/test", path, tokens))
    results.append(require_doc_tokens())
    return results


def main():
    parser = argparse.ArgumentParser(description="Check StorageProxy coordinator research drift")
    parser.add_argument("--json", action="store_true", help="emit machine-readable summary")
    args = parser.parse_args()

    try:
        results = run_checks()
    except AssertionError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(str(exc), file=sys.stderr)
        return 1

    total = sum(result.checks for result in results)
    summary = {
        "ok": True,
        "checks": total,
        "files": len(SOURCE_TOKEN_CHECKS),
        "scenarios": len(SCENARIO_IDS),
    }
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(
            "OK StorageProxy coordinator drift checks passed "
            f"({total} checks, {len(SCENARIO_IDS)} scenarios)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
