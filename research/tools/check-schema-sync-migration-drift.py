#!/usr/bin/env python3
#
# Source-only drift check for schema sync migration research coverage.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

MATRIX_DOC = "research/module-schema-sync-migration-matrix.md"
CHECKER_DOC = "research/module-schema-sync-migration-drift-checker.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

SCENARIOS = (
    "schema_sync_handler_interface_contract",
    "schema_sync_default_handler_registration",
    "schema_sync_apply_diff_mutation_contract",
    "schema_sync_remote_mutation_merge_contract",
    "schema_sync_announce_and_startup_wait_contract",
    "schema_sync_endpoint_version_tracking_contract",
    "schema_sync_pull_selection_compatibility_contract",
    "schema_sync_pull_retry_await_contract",
    "schema_sync_push_viable_nodes_contract",
    "schema_sync_reset_clear_contract",
    "schema_sync_verb_serializer_diagnostics_contract",
    "schema_sync_disagreement_tests_baseline",
)

SOURCE_EXPECTATIONS = {
    "src/java/org/apache/cassandra/schema/SchemaUpdateHandler.java": (
        "public interface SchemaUpdateHandler",
        "void start();",
        "boolean waitUntilReady(Duration timeout);",
        "SchemaTransformationResult apply(SchemaTransformation transformation, boolean local);",
        "void reset(boolean local);",
        "Awaitable clear();",
    ),
    "src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java": (
        "public class DefaultSchemaUpdateHandler implements SchemaUpdateHandler, IEndpointStateChangeSubscriber",
        "CassandraRelevantProperties.BOOTSTRAP_SKIP_SCHEMA_CHECK.getBoolean()",
        "Gossiper.instance.register(this);",
        "SchemaPushVerbHandler.instance.register(msg ->",
        "SchemaPullVerbHandler.instance.register(msg ->",
        "messagingService.send(msg.responseWith(getSchemaMutations()), msg.from());",
        "public boolean waitUntilReady(Duration timeout)",
        "migrationCoordinator.awaitSchemaRequests(timeout.toMillis())",
        "CassandraRelevantProperties.IGNORED_SCHEMA_CHECK_ENDPOINTS.getKey()",
        "CassandraRelevantProperties.IGNORED_SCHEMA_CHECK_VERSIONS.getKey()",
        "public void onChange(InetAddressAndPort endpoint, ApplicationState state, VersionedValue value)",
        "state == ApplicationState.SCHEMA",
        "migrationCoordinator.reportEndpointVersion(endpoint, UUID.fromString(value.value));",
        "synchronized SchemaTransformationResult applyMutations(Collection<Mutation> schemaMutations)",
        "SchemaKeyspace.applyChanges(schemaMutations);",
        "SchemaKeyspace.affectedKeyspaces(schemaMutations)",
        "SchemaKeyspace.fetchKeyspaces(affectedKeyspaces)",
        "SchemaKeyspace.calculateSchemaDigest()",
        "updateSchema(update, false);",
        "public synchronized SchemaTransformationResult apply(SchemaTransformation transformation, boolean local)",
        "SchemaKeyspace.convertSchemaDiffToMutations",
        "migrationCoordinator.pushSchemaMutations(mutations)",
        "SchemaAnnouncementDiagnostics.schemaTransformationAnnounced",
        "migrationCoordinator.announce(update.after.getVersion());",
        "public void reset(boolean local)",
        "migrationCoordinator.reset();",
        "public Awaitable clear()",
        "requestedReset = new AsyncPromise<>();",
        "return SchemaConstants.emptyVersion;",
        "SchemaKeyspace.truncate();",
        "SchemaKeyspace.convertSchemaToMutations();",
        "public Map<UUID, Set<InetAddressAndPort>> getOutstandingSchemaVersions()",
    ),
    "src/java/org/apache/cassandra/schema/MigrationCoordinator.java": (
        "public class MigrationCoordinator",
        "SCHEMA_PULL_INTERVAL_MS",
        "IGNORED_SCHEMA_CHECK_ENDPOINTS",
        "IGNORED_SCHEMA_CHECK_VERSIONS",
        "private static final long PULL_BACKOFF_INTERVAL_MS = 1000",
        "public static final int MAX_OUTSTANDING_VERSION_REQUESTS = 3;",
        "static class VersionInfo",
        "final Set<InetAddressAndPort> endpoints",
        "final Set<InetAddressAndPort> outstandingRequests",
        "final Deque<InetAddressAndPort> requestQueue",
        "private final WaitQueue waitQueue = newWaitQueue();",
        "volatile boolean receivedSchema;",
        "void start()",
        "periodicCheckExecutor.scheduleWithFixedDelay(this::pullUnreceivedSchemaVersions",
        "private synchronized void pullUnreceivedSchemaVersions()",
        "private synchronized Future<Void> maybePullSchema(VersionInfo info)",
        "private boolean shouldPullSchema(UUID version)",
        "private boolean shouldPullFromEndpoint(InetAddressAndPort endpoint)",
        "releaseVersion.startsWith(ourMajorVersion)",
        "messagingService.versions.knows(endpoint)",
        "messagingService.versions.getRaw(endpoint) != MessagingService.current_version",
        "gossiper.isGossipOnlyMember(endpoint)",
        "private boolean shouldPullImmediately(InetAddressAndPort endpoint, UUID version)",
        "SchemaConstants.emptyVersion.equals(localSchemaVersion)",
        "getUptimeFn.getAsLong() < MIGRATION_DELAY_IN_MS",
        "synchronized Future<Void> reportEndpointVersion(InetAddressAndPort endpoint, UUID version)",
        "ignoredEndpoints.contains(endpoint) || IGNORED_VERSIONS.contains(version)",
        "info.requestQueue.addFirst(endpoint);",
        "synchronized void removeAndIgnoreEndpoint(InetAddressAndPort endpoint)",
        "private Future<Void> scheduleSchemaPull(InetAddressAndPort endpoint, VersionInfo info)",
        "void announce(UUID schemaVersion)",
        "gossiper.addLocalApplicationState(ApplicationState.SCHEMA",
        "schemaUpdateCallback.accept(endpoint, mutations);",
        "Message<NoPayload> message = Message.out(Verb.SCHEMA_PULL_REQ, NoPayload.noPayload);",
        "messagingService.sendWithCallback(message, endpoint, callback);",
        "boolean awaitSchemaRequests(long waitMillis)",
        "Gossiper.waitToSettle();",
        "signal.awaitUntilUninterruptibly(deadline)",
        "Message<Collection<Mutation>> message = Message.out(SCHEMA_PUSH_REQ, schemaMutations);",
        "messagingService.send(message, endpoint);",
        "private boolean shouldPushSchemaTo(InetAddressAndPort endpoint)",
        "messagingService.versions.getRaw(endpoint) == MessagingService.current_version",
    ),
    "src/java/org/apache/cassandra/schema/SchemaPushVerbHandler.java": (
        "public final class SchemaPushVerbHandler implements IVerbHandler<Collection<Mutation>>",
        "public static final SchemaPushVerbHandler instance = new SchemaPushVerbHandler();",
        "private final List<Consumer<Message<Collection<Mutation>>>> handlers = new CopyOnWriteArrayList<>();",
        "SchemaAnnouncementDiagnostics.schemataMutationsReceived(message.from());",
        "throw new UnsupportedOperationException(\"There is no handler registered for schema push verb\");",
        "handlers.forEach(h -> h.accept(message));",
    ),
    "src/java/org/apache/cassandra/schema/SchemaPullVerbHandler.java": (
        "public final class SchemaPullVerbHandler implements IVerbHandler<NoPayload>",
        "public static final SchemaPullVerbHandler instance = new SchemaPullVerbHandler();",
        "private final List<Consumer<Message<NoPayload>>> handlers = new CopyOnWriteArrayList<>();",
        "throw new UnsupportedOperationException(\"There is no handler registered for schema pull verb\");",
        "handlers.forEach(h -> h.accept(message));",
    ),
    "src/java/org/apache/cassandra/schema/SchemaVersionVerbHandler.java": (
        "public final class SchemaVersionVerbHandler implements IVerbHandler<NoPayload>",
        "Message<UUID> response = message.responseWith(Schema.instance.getVersion());",
        "MessagingService.instance().send(response, message.from());",
    ),
    "src/java/org/apache/cassandra/schema/SchemaMutationsSerializer.java": (
        "public class SchemaMutationsSerializer implements IVersionedSerializer<Collection<Mutation>>",
        "public static final SchemaMutationsSerializer instance = new SchemaMutationsSerializer();",
        "out.writeInt(schema.size());",
        "Mutation.serializer.serialize(mutation, out, version);",
        "int count = in.readInt();",
        "Mutation.serializer.deserialize(in, version)",
        "mutation.serializedSize(version)",
    ),
    "src/java/org/apache/cassandra/schema/SchemaAnnouncementDiagnostics.java": (
        "static void schemaMutationsAnnounced",
        "public static void schemataMutationsReceived",
        "static void schemaTransformationAnnounced",
        "service.publish(new SchemaAnnouncementEvent",
        "service.isEnabled(SchemaAnnouncementEvent.class, type)",
    ),
    "src/java/org/apache/cassandra/schema/SchemaAnnouncementEvent.java": (
        "final class SchemaAnnouncementEvent extends DiagnosticEvent",
        "SCHEMA_MUTATIONS_ANNOUNCED",
        "SCHEMA_TRANSFORMATION_ANNOUNCED",
        "SCHEMA_MUTATIONS_RECEIVED",
        "ret.put(\"endpointDestinations\", new HashSet<>(eps));",
        "ret.put(\"endpointIgnored\", new HashSet<>(eps));",
        "ret.put(\"statement\", log);",
        "if (sender != null) ret.put(\"sender\", sender.toString());",
    ),
    "src/java/org/apache/cassandra/net/Verb.java": (
        "SCHEMA_PUSH_REQ        (18,  P1, rpcTimeout,      MIGRATION,         () -> SchemaMutationsSerializer.instance",
        "SCHEMA_PULL_REQ        (28,  P1, rpcTimeout,      MIGRATION,         () -> NoPayload.serializer",
        "SCHEMA_VERSION_REQ     (20,  P1, rpcTimeout,      MIGRATION,         () -> NoPayload.serializer",
        "SCHEMA_PULL_RSP        (88,  P1, rpcTimeout,      MIGRATION,         () -> SchemaMutationsSerializer.instance",
        "SCHEMA_VERSION_RSP     (80,  P1, rpcTimeout,      MIGRATION,         () -> UUIDSerializer.serializer",
    ),
}

TEST_EXPECTATIONS = {
    "test/unit/org/apache/cassandra/schema/MigrationCoordinatorTest.java": (
        "public void requestResponseCycle() throws InterruptedException",
        "coordinator.reportEndpointVersion(EP1, V1)",
        "Assert.assertFalse(coordinator.awaitSchemaRequests(1));",
        "request1.right.onFailure(null, null);",
        "request2.right.onResponse(Message.remoteResponse(request2.left, Verb.SCHEMA_PULL_RSP, Collections.emptyList()))",
        "public void versionsAreSignaledWhenDeleted()",
        "public void versionsAreSignaledWhenEndpointsRemoved()",
        "wrapper.coordinator.removeAndIgnoreEndpoint(EP1);",
        "public void dontContactNodesWithSameSchema()",
        "public void dontContactIncompatibleNodes()",
        "public void dontContactDeadNodes()",
        "public void testGossipRace()",
        "public void testWeKeepSendingRequests() throws Exception",
        "public void pullUnreceived()",
        "public void pushSchemaMutationsOnlyToViableNodes() throws UnknownHostException",
        "wrapper.coordinator.pushSchemaMutations(mutations)",
        "public void reset() throws UnknownHostException",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/MigrationCoordinatorTest.java": (
        "public void replaceNode() throws Throwable",
        "withProperties.set(REPLACE_ADDRESS, replacementAddress.getHostAddress());",
        "public void explicitEndpointIgnore() throws Throwable",
        "withProperties.set(IGNORED_SCHEMA_CHECK_ENDPOINTS, ignoredEndpoint.getHostAddress());",
        "public void explicitVersionIgnore() throws Throwable",
        "withProperties.set(IGNORED_SCHEMA_CHECK_VERSIONS, initialVersion.toString() + ',' + oldVersion);",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/SchemaTest.java": (
        "public void schemaReset() throws Throwable",
        "CassandraRelevantProperties.MIGRATION_DELAY.setLong(10000);",
        "CassandraRelevantProperties.SCHEMA_PULL_INTERVAL_MS.setLong(10000);",
        "Schema.instance.updateHandler.clear().awaitUninterruptibly(1, TimeUnit.MINUTES)",
        "Schema.instance.resetLocalSchema()",
        "checkTablesPropagated(cluster.get(1), true, false)",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/SchemaDisagreementTest.java": (
        "public void writeWithInconsequentialSchemaDisagreement() throws Throwable",
        "cluster.schemaChange(withKeyspace(\"ALTER TABLE %s.tbl ADD v2 int\"), 1);",
        "cluster.coordinator(1).execute(withKeyspace(\"INSERT INTO %s.tbl (pk, ck, v1) VALUES (2, 2, 2)\"), ALL);",
    ),
}

DOC_EXPECTATIONS = {
    MATRIX_DOC: SCENARIOS + (
        "Schema Sync Migration Matrix",
        "SchemaUpdateHandler",
        "DefaultSchemaUpdateHandler",
        "MigrationCoordinator",
        "SchemaMutationsSerializer",
        "SchemaAnnouncementEvent",
        "SCHEMA_PULL_REQ",
        "SCHEMA_PUSH_REQ",
    ),
    CHECKER_DOC: SCENARIOS + (
        "Schema Sync Migration Drift Checker",
        "12 scenarios",
        "check-schema-sync-migration-drift.py",
    ),
    README_DOC: (
        "module-schema-sync-migration-matrix.md",
        "module-schema-sync-migration-drift-checker.md",
        "research/tools/check-schema-sync-migration-drift.py",
    ),
    SOURCE_MAP_DOC: (
        "Schema sync migration",
        "module-schema-sync-migration-matrix.md",
        "module-schema-sync-migration-drift-checker.md",
        "research/tools/check-schema-sync-migration-drift.py",
        "src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:84",
        "src/java/org/apache/cassandra/schema/MigrationCoordinator.java:86",
        "src/java/org/apache/cassandra/schema/SchemaPushVerbHandler.java:38",
        "src/java/org/apache/cassandra/net/Verb.java:155",
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
    parser = argparse.ArgumentParser(description="Check schema sync migration research coverage for drift.")
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
        print(f"OK schema sync migration drift checks passed ({len(SCENARIOS)} scenarios)")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
