#!/usr/bin/env python3
"""Validate replication placement/pending-range research against source tokens."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]

ARS = "src/java/org/apache/cassandra/locator/AbstractReplicationStrategy.java"
SIMPLE = "src/java/org/apache/cassandra/locator/SimpleStrategy.java"
NTS = "src/java/org/apache/cassandra/locator/NetworkTopologyStrategy.java"
RF = "src/java/org/apache/cassandra/locator/ReplicationFactor.java"
TOKEN_METADATA = "src/java/org/apache/cassandra/locator/TokenMetadata.java"
PENDING_SERVICE = "src/java/org/apache/cassandra/service/PendingRangeCalculatorService.java"
REPLICATION_PARAMS = "src/java/org/apache/cassandra/schema/ReplicationParams.java"
KEYSPACE_METADATA = "src/java/org/apache/cassandra/schema/KeyspaceMetadata.java"
REPLICA_PLANS = "src/java/org/apache/cassandra/locator/ReplicaPlans.java"
STORAGE_PROXY = "src/java/org/apache/cassandra/service/StorageProxy.java"
STORAGE_SERVICE = "src/java/org/apache/cassandra/service/StorageService.java"

SCENARIO_IDS = (
    "replication_params_strategy_resolution_contract",
    "replication_factor_transient_validation_contract",
    "simple_strategy_ring_replica_contract",
    "nts_dc_rack_replica_contract",
    "nts_rf_auto_expand_validation_contract",
    "replica_cache_range_map_contract",
    "pending_range_leave_bootstrap_move_contract",
    "pending_range_service_async_contract",
    "replica_plan_write_pending_contract",
    "replica_plan_read_each_quorum_contract",
    "replica_plan_lwt_pending_boundary",
    "materialized_view_pending_write_contract",
    "storage_service_replica_observability_contract",
    "replication_existing_test_baseline",
    "replication_pending_distributed_gap",
)

TARGET_DOCS = (
    "research/module-replication-placement-pending-range-matrix.md",
    "research/module-replication-placement-drift-checker.md",
    "research/module-consistency-replication.md",
    "research/module-consistency-replication-deep-dive.md",
    "research/module-consistency-replication-third-round.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SOURCE_TOKEN_CHECKS = {
    REPLICATION_PARAMS: (
        "public final Class<? extends AbstractReplicationStrategy> klass;",
        "static ReplicationParams simple(int replicationFactor)",
        "static ReplicationParams nts(Object... args)",
        "public void validate(String name, ClientState state)",
        "AbstractReplicationStrategy.validateReplicationStrategy(name, klass, tmd, eps, options, state);",
        "public static ReplicationParams fromMapWithDefaults(Map<String, String> map, Map<String, String> previousOptions)",
        "Class<? extends AbstractReplicationStrategy> klass = AbstractReplicationStrategy.getClass(className);",
        "AbstractReplicationStrategy.prepareReplicationStrategyOptions(klass, options, previousOptions);",
    ),
    KEYSPACE_METADATA: (
        "public AbstractReplicationStrategy createReplicationStrategy()",
        "return AbstractReplicationStrategy.createReplicationStrategy(name,",
        "StorageService.instance.getTokenMetadata(),",
        "DatabaseDescriptor.getEndpointSnitch(),",
        "params.replication.options);",
    ),
    ARS: (
        "private final ReplicaCache<Token, EndpointsForRange> replicas = new ReplicaCache<>();",
        "public EndpointsForToken getNaturalReplicasForToken(RingPosition<?> searchPosition)",
        "public EndpointsForRange getNaturalReplicas(RingPosition<?> searchPosition)",
        "long currentRingVersion = tokenMetadata.getRingVersion();",
        "TokenMetadata tm = tokenMetadata.cachedOnlyTokenMap();",
        "endpoints = calculateNaturalReplicas(searchToken, tm);",
        "replicas.put(tm.getRingVersion(), keyToken, endpoints);",
        "public boolean isTokenInLocalNaturalOrPendingRange(Token token)",
        "public abstract EndpointsForRange calculateNaturalReplicas(Token searchToken, TokenMetadata tokenMetadata);",
        "public RangesByEndpoint getAddressReplicas(TokenMetadata metadata)",
        "public EndpointsByRange getRangeAddresses(TokenMetadata metadata)",
        "public RangesAtEndpoint getPendingAddressRanges(TokenMetadata metadata, Collection<Token> pendingTokens, InetAddressAndPort pendingAddress)",
        "public static void prepareReplicationStrategyOptions(Class<? extends AbstractReplicationStrategy> strategyClass,",
        "Method method = strategyClass.getDeclaredMethod(\"prepareOptions\", Map.class, Map.class);",
        "public static void validateReplicationStrategy(String keyspaceName,",
        "if (strategy.hasTransientReplicas() && !DatabaseDescriptor.isTransientReplicationEnabled())",
        "if (\"org.apache.cassandra.locator.OldNetworkTopologyStrategy\".equals(className))",
        "protected void validateReplicationFactor(String s) throws ConfigurationException",
    ),
    RF: (
        "public final int allReplicas;",
        "public final int fullReplicas;",
        "public int transientReplicas()",
        "public boolean hasTransientReplicas()",
        "static void validate(int totalRF, int transientRF)",
        "Preconditions.checkArgument(transientRF == 0 || DatabaseDescriptor.isTransientReplicationEnabled(),",
        "Preconditions.checkArgument(totalRF >= 0,",
        "Preconditions.checkArgument(transientRF == 0 || transientRF < totalRF,",
        "Preconditions.checkArgument(DatabaseDescriptor.getNumTokens() == 1,",
        "Gossiper.instance.getReleaseVersion(endpoint) != null && Gossiper.instance.getReleaseVersion(endpoint).major < 4",
        "public static ReplicationFactor withTransient(int totalReplicas, int transientReplicas)",
        "public static ReplicationFactor fromString(String s)",
        "String[] parts = s.split(\"/\");",
        "public String toParseableString()",
    ),
    SIMPLE: (
        "public class SimpleStrategy extends AbstractReplicationStrategy",
        "public static final String REPLICATION_FACTOR = \"replication_factor\";",
        "this.rf = ReplicationFactor.fromString(this.configOptions.get(REPLICATION_FACTOR));",
        "public EndpointsForRange calculateNaturalReplicas(Token token, TokenMetadata metadata)",
        "ArrayList<Token> ring = metadata.sortedTokens();",
        "Token replicaEnd = TokenMetadata.firstToken(ring, token);",
        "Iterator<Token> iter = TokenMetadata.ringIterator(ring, token, false);",
        "while (replicas.size() < rf.allReplicas && iter.hasNext())",
        "replicas.add(new Replica(ep, replicaRange, replicas.size() < rf.fullReplicas));",
        "throw new ConfigurationException(\"SimpleStrategy requires a replication_factor strategy option.\");",
        "Guardrails.minimumReplicationFactor.guard(rf.fullReplicas, keyspaceName, false, state);",
        "protected static void prepareOptions(Map<String, String> options, Map<String, String> previousOptions)",
    ),
    NTS: (
        "public class NetworkTopologyStrategy extends AbstractReplicationStrategy",
        "public static final String REPLICATION_FACTOR = \"replication_factor\";",
        "private final Map<String, ReplicationFactor> datacenters;",
        "private final ReplicationFactor aggregateRf;",
        "if (dc.equalsIgnoreCase(REPLICATION_FACTOR))",
        "ReplicationFactor rf = ReplicationFactor.fromString(entry.getValue());",
        "aggregateRf = ReplicationFactor.withTransient(replicas, trans);",
        "private static final class DatacenterEndpoints",
        "this.rfLeft = Math.min(rf.allReplicas, nodeCount);",
        "acceptableRackRepeats = rf.allReplicas - rackCount;",
        "transients = Math.max(rf.transientReplicas() - reduceTransients, 0);",
        "boolean addEndpointAndCheckIfDone(InetAddressAndPort ep, Pair<String,String> location, Range<Token> replicatedRange)",
        "if (replicas.endpoints().contains(ep))",
        "Replica replica = new Replica(ep, replicatedRange, rfLeft > transients);",
        "public EndpointsForRange calculateNaturalReplicas(Token searchToken, TokenMetadata tokenMetadata)",
        "Topology topology = tokenMetadata.getTopology();",
        "Multimap<String, InetAddressAndPort> allEndpoints = topology.getDatacenterEndpoints();",
        "Map<String, ImmutableMultimap<String, InetAddressAndPort>> racks = topology.getDatacenterRacks();",
        "Iterator<Token> tokenIter = TokenMetadata.ringIterator(sortedTokens, searchToken, false);",
        "protected static void prepareOptions(Map<String, String> options, Map<String, String> previousOptions)",
        "String replication = options.remove(REPLICATION_FACTOR);",
        "Datacenters.getValidDatacenters()",
        "options.values().removeAll(Collections.singleton(\"0\"));",
        "if (this.configOptions.isEmpty())",
        "if (keyspaceName.equalsIgnoreCase(SchemaConstants.AUTH_KEYSPACE_NAME))",
        "Guardrails.maximumReplicationFactor.guard(rf.fullReplicas, keyspaceName, false, state);",
    ),
    TOKEN_METADATA: (
        "private final ConcurrentMap<String, PendingRangeMaps> pendingRanges = new ConcurrentHashMap<String, PendingRangeMaps>();",
        "public EndpointsByRange getPendingRangesMM(String keyspaceName)",
        "public PendingRangeMaps getPendingRanges(String keyspaceName)",
        "public RangesAtEndpoint getPendingRanges(String keyspaceName, InetAddressAndPort endpoint)",
        "public void setPendingRangesUnsafe(String keyspaceName, Multimap<Range<Token>, Replica> rangeMap)",
        "public void calculatePendingRanges(AbstractReplicationStrategy strategy, String keyspaceName)",
        "TokenMetadataDiagnostics.pendingRangeCalculationStarted(this, keyspaceName);",
        "unsafeCalculatePendingRanges(strategy, keyspaceName);",
        "public void unsafeCalculatePendingRanges(AbstractReplicationStrategy strategy, String keyspaceName)",
        "bootstrapTokensClone  = new BiMultiValMap<>(this.bootstrapTokens);",
        "leavingEndpointsClone = new HashSet<>(this.leavingEndpoints);",
        "movingEndpointsClone = new HashSet<>(this.movingEndpoints);",
        "pendingRanges.put(keyspaceName, calculatePendingRanges(strategy, metadata, bootstrapTokensClone,",
        "private static PendingRangeMaps calculatePendingRanges(AbstractReplicationStrategy strategy,",
        "RangesByEndpoint addressRanges = strategy.getAddressReplicas(metadata);",
        "TokenMetadata allLeftMetadata = removeEndpoints(metadata.cloneOnlyTokenMap(), leavingEndpoints);",
        "for (InetAddressAndPort endpoint : leavingEndpoints)",
        "EndpointsForRange currentReplicas = strategy.calculateNaturalReplicas(range.right, metadata);",
        "EndpointsForRange newReplicas = strategy.calculateNaturalReplicas(range.right, allLeftMetadata);",
        "newPendingRanges.addPendingRange(range, pendingReplica);",
        "Multimap<InetAddressAndPort, Token> bootstrapAddresses = bootstrapTokens.inverse();",
        "cloned.updateNormalTokens(tokens, endpoint);",
        "for (Pair<Token, InetAddressAndPort> moving : movingEndpoints)",
        "allLeftMetadata.updateNormalToken(moving.left, endpoint);",
        "Set<InetAddressAndPort> difference = Sets.difference(newEndpoints, currentEndpoints);",
        "newPendingRanges.addPendingRange(pendingReplica.range(), pendingReplica);",
    ),
    PENDING_SERVICE: (
        "public class PendingRangeCalculatorService",
        "private final SequentialExecutorPlus executor = executorFactory()",
        ".configureSequential(\"PendingRangeCalculator\")",
        "private final AtLeastOnceTrigger update = executor.atLeastOnceTrigger(() -> {",
        "Collection<String> keyspaces = Schema.instance.distributedKeyspaces().names();",
        "for (String keyspaceName : keyspaces)",
        "calculatePendingRanges(Keyspace.open(keyspaceName).getReplicationStrategy(), keyspaceName);",
        "public void update()",
        "public void blockUntilFinished()",
        "public static void calculatePendingRanges(AbstractReplicationStrategy strategy, String keyspaceName)",
    ),
    REPLICA_PLANS: (
        "public static ReplicaPlan.ForWrite forWrite(Keyspace keyspace, ConsistencyLevel consistencyLevel, Token token, Selector selector)",
        "public static ReplicaPlan.ForWrite forWrite(Keyspace keyspace, ConsistencyLevel consistencyLevel, EndpointsForToken natural, EndpointsForToken pending, Predicate<Replica> isAlive, Selector selector)",
        "ReplicaLayout.ForTokenWrite live = liveAndDown.filter(isAlive);",
        "EndpointsForToken contacts = selector.select(consistencyLevel, liveAndDown, live);",
        "assureSufficientLiveReplicasForWrite(replicationStrategy, consistencyLevel, live.all(), liveAndDown.pending());",
        "return new ReplicaPlan.ForWrite(keyspace, replicationStrategy, consistencyLevel, liveAndDown.pending(), liveAndDown.all(), live.all(), contacts);",
        "public static final Selector writeAll = new Selector()",
        "public static final Selector writeNormal = new Selector()",
        "contacts.addAll(filter(liveAndDown.natural(), Replica::isFull));",
        "contacts.addAll(liveAndDown.pending());",
        "ObjectIntHashMap<String> requiredPerDc = eachQuorumForWrite(liveAndDown.replicationStrategy(), liveAndDown.pending());",
        "public static ReplicaPlan.ForPaxosWrite forPaxos(Keyspace keyspace, DecoratedKey key, ConsistencyLevel consistencyForPaxos)",
        "if (liveAndDown.pending().size() > 1)",
        "Cannot perform LWT operation as there is more than one",
        "private static <E extends Endpoints<E>> E contactForRead(AbstractReplicationStrategy replicationStrategy, ConsistencyLevel consistencyLevel, boolean alwaysSpeculate, E candidates)",
        "if (consistencyLevel == EACH_QUORUM && replicationStrategy instanceof NetworkTopologyStrategy)",
        "return contactForEachQuorumRead((NetworkTopologyStrategy) replicationStrategy, candidates);",
        "public static ReplicaPlan.ForTokenRead forRead(Keyspace keyspace,",
        "ReplicaLayout.forTokenReadLiveSorted(replicationStrategy, token).natural()",
        "assureSufficientLiveReplicasForRead(replicationStrategy, consistencyLevel, contacts);",
        "public static ReplicaPlan.ForRangeRead forRangeRead(Keyspace keyspace,",
    ),
    STORAGE_PROXY: (
        "public static void mutateMV(ByteBuffer dataKey, Collection<Mutation> mutations, boolean writeCommitLog, AtomicLong baseComplete, Dispatcher.RequestTime requestTime)",
        "Optional<Replica> pairedEndpoint = ViewUtils.getViewNaturalEndpoint(replicationStrategy, baseToken, tk);",
        "EndpointsForToken pendingReplicas = StorageService.instance.getTokenMetadata().pendingEndpointsForToken(tk, keyspaceName);",
        "if (pairedEndpoint.get().isSelf() && StorageService.instance.isJoined()",
        "&& pendingReplicas.isEmpty())",
        "ReplicaLayout.ForTokenWrite liveAndDown = ReplicaLayout.forTokenWrite(replicationStrategy,",
        "pendingReplicas);",
    ),
    STORAGE_SERVICE: (
        "public List<Range<Token>> getLocalAndPendingRanges(String ks)",
        "for (Replica r : keyspace.getReplicationStrategy().getAddressReplicas(broadcastAddress))",
        "for (Replica r : getTokenMetadata().getPendingRanges(ks, broadcastAddress))",
        "public Map<List<String>, List<String>> getPendingRangeToEndpointMap(String keyspace)",
        "public Map<List<String>, List<String>> getPendingRangeToEndpointWithPortMap(String keyspace)",
        "for (Map.Entry<Range<Token>, EndpointsForRange> entry : tokenMetadata.getPendingRangesMM(keyspace).asMap().entrySet())",
        "public EndpointsByRange getRangeToAddressMap(String keyspace)",
        "public List<InetAddress> getNaturalEndpoints(String keyspaceName, String cf, String key)",
        "public List<String> getNaturalEndpointsWithPort(String keyspaceName, String cf, String key)",
        "public List<String> getNaturalEndpointsWithPort(String keyspaceName, ByteBuffer key)",
    ),
}

TEST_TOKEN_CHECKS = {
    "test/unit/org/apache/cassandra/locator/ReplicationFactorTest.java": (
        "public class ReplicationFactorTest",
        "public void shouldParseValidRF()",
        "assertRfParse(\"3/1\", 3, 1);",
        "public void shouldFailOnInvalidRF()",
        "assertRfParseFailure(\"3/3\", \"Transient replicas must be zero, or less than total replication factor\");",
        "public void shouldRoundTripParseTransientRF()",
    ),
    "test/unit/org/apache/cassandra/locator/SimpleStrategyTest.java": (
        "public class SimpleStrategyTest",
        "public void testMultiDCSimpleStrategyEndpoints()",
        "PendingRangeCalculatorService.calculatePendingRanges(strategy, keyspaceName);",
        "public void testSimpleStrategyThrowsConfigurationException()",
        "expectedEx.expectMessage(\"SimpleStrategy requires a replication_factor strategy option.\");",
        "public void shouldWarnOnHigherReplicationFactorThanNodes()",
    ),
    "test/unit/org/apache/cassandra/locator/NetworkTopologyStrategyTest.java": (
        "public class NetworkTopologyStrategyTest",
        "new NetworkTopologyStrategy(KEYSPACE, metadata, snitch, configOptions);",
        "public void shouldRejectReplicationFactorOption()",
        "expectedEx.expectMessage(REPLICATION_FACTOR + \" should not appear\");",
        "public void shouldWarnOnHigherReplicationFactorThanNodesInDC()",
        "assertTrue(ClientWarn.instance.getWarnings().stream().anyMatch(s -> s.contains(\"Your replication factor\")));",
    ),
    "test/unit/org/apache/cassandra/locator/PendingRangesTest.java": (
        "public void calculatePendingRangesForConcurrentReplacements()",
        "tm.calculatePendingRanges(replicationStrategy, KEYSPACE);",
        "assertPendingRanges(tm.getPendingRanges(KEYSPACE), expected);",
        "assertPendingRanges(tm.getPendingRangesMM(KEYSPACE), expected);",
        "public void testConcurrentAdjacentLeaveAndMove()",
        "tm.addMovingEndpoint(newToken, node3);",
    ),
    "test/unit/org/apache/cassandra/locator/ReplicaPlansTest.java": (
        "public class ReplicaPlansTest",
        "public void testWriteEachQuorum()",
        "ReplicaPlans.forWrite(ks, ConsistencyLevel.EACH_QUORUM, natural, pending, Predicates.alwaysTrue(), ReplicaPlans.writeNormal);",
        "EndpointsForToken expectContacts = EndpointsForToken.of(token, full(EP1), full(EP2), full(EP4), full(EP5));",
    ),
    "test/unit/org/apache/cassandra/locator/AssureSufficientLiveNodesTest.java": (
        "addDatacenterShouldNotCausesUnavailableWithEachQuorumTest",
        "raceOnRemoveDatacenterNotCausesUnavailable",
        "increaseReplicationFactorShouldNotCausesUnavailableTest",
        "ReplicaPlans.forRead(keyspace, tk, null, EACH_QUORUM, NeverSpeculativeRetryPolicy.INSTANCE)",
        "ReplicaPlans.forWrite(keyspace, LOCAL_QUORUM, tk, ReplicaPlans.writeNormal)",
    ),
    "test/unit/org/apache/cassandra/service/StorageServiceServerTest.java": (
        "testLocalPrimaryRangeForEndpointWithNetworkTopologyStrategy",
        "testPrimaryRangeForEndpointWithinDCWithNetworkTopologyStrategy",
        "testPrimaryRangesWithSimpleStrategy",
        "testPrimaryRangeForEndpointWithinDCWithSimpleStrategy",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/ring/PendingWritesTest.java": (
        "public class PendingWritesTest",
        "PendingRangeCalculatorService.instance.update();",
        "PendingRangeCalculatorService.instance.blockUntilFinished();",
        "Node \" + e.getKey() + \" has incorrect row state",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/NetworkTopologyTest.java": (
        "noWarningForNetworkTopologyStategyConfigOnRestart",
        "CREATE KEYSPACE \" + KEYSPACE +",
        "Ignoring Unrecognized strategy option",
        "Assert.assertTrue(\"Not expected to see the warning about unrecognized option\", result.isEmpty());",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java": (
        "return String.format(\"ALTER KEYSPACE \" + SchemaConstants.AUTH_KEYSPACE_NAME +",
        "\" WITH replication = {'class': 'NetworkTopologyStrategy', %s};\", ntsOptions);",
        "String initialDatacenters = \"'replication_factor': '1'\";",
        "String beforeDecommissionedDatacenters = \"'replication_factor': '1', 'dc2': '1'\";",
    ),
}

DOC_REQUIRED_TOKENS = (
    "module-replication-placement-pending-range-matrix.md",
    "module-replication-placement-drift-checker.md",
    "check-replication-placement-drift.py",
    "ReplicationParams.fromMapWithDefaults",
    "AbstractReplicationStrategy.prepareReplicationStrategyOptions",
    "ReplicationFactor.fromString",
    "SimpleStrategy.calculateNaturalReplicas",
    "NetworkTopologyStrategy.prepareOptions",
    "TokenMetadata.calculatePendingRanges",
    "PendingRangeCalculatorService",
    "ReplicaPlans.forWrite",
    "ReplicaPlans.forRead",
    "ReplicaPlans.forPaxos",
    "StorageProxy.mutateMV",
    "StorageService.getPendingRangeToEndpointWithPortMap",
    "ReplicationFactorTest",
    "SimpleStrategyTest",
    "NetworkTopologyStrategyTest",
    "PendingRangesTest",
    "ReplicaPlansTest",
    "AssureSufficientLiveNodesTest",
    "PendingWritesTest",
    "NetworkTopologyTest",
    "replication_pending_distributed_gap",
)


@dataclass(frozen=True)
class Failure:
    kind: str
    path: str
    token: str


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def check_tokens(checks: dict[str, Iterable[str]], kind: str) -> list[Failure]:
    failures: list[Failure] = []
    for path, tokens in checks.items():
        try:
            text = read_text(path)
        except FileNotFoundError:
            failures.append(Failure(kind, path, "<missing file>"))
            continue
        for token in tokens:
            if token not in text:
                failures.append(Failure(kind, path, token))
    return failures


def check_docs() -> list[Failure]:
    failures: list[Failure] = []
    docs = []
    for path in TARGET_DOCS:
        try:
            docs.append(read_text(path))
        except FileNotFoundError:
            failures.append(Failure("doc", path, "<missing file>"))
    combined = "\n".join(docs)

    for scenario_id in SCENARIO_IDS:
        if scenario_id not in combined:
            failures.append(Failure("doc", "research docs", scenario_id))

    for token in DOC_REQUIRED_TOKENS:
        if token not in combined:
            failures.append(Failure("doc", "research docs", token))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit structured JSON")
    args = parser.parse_args()

    source_failures = check_tokens(SOURCE_TOKEN_CHECKS, "source")
    test_failures = check_tokens(TEST_TOKEN_CHECKS, "test")
    doc_failures = check_docs()
    failures = source_failures + test_failures + doc_failures

    source_count = sum(len(tokens) for tokens in SOURCE_TOKEN_CHECKS.values())
    test_count = sum(len(tokens) for tokens in TEST_TOKEN_CHECKS.values())
    doc_count = len(SCENARIO_IDS) + len(DOC_REQUIRED_TOKENS)

    if args.json:
        payload = {
            "ok": not failures,
            "source_checks": source_count,
            "test_checks": test_count,
            "doc_checks": doc_count,
            "scenario_ids": list(SCENARIO_IDS),
            "failures": [failure.__dict__ for failure in failures],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif failures:
        for failure in failures:
            print(f"ERROR {failure.kind} token missing in {failure.path}: {failure.token}", file=sys.stderr)
    else:
        print(
            "OK Replication placement/pending-range drift checks passed "
            f"({source_count} source checks, {test_count} test checks, {doc_count} doc checks, {len(SCENARIO_IDS)} scenarios)"
        )

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
