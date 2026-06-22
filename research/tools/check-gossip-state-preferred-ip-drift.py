#!/usr/bin/env python3
#
# Source-only drift check for Gossip state and preferred-IP coverage research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

GOSSIPER = "src/java/org/apache/cassandra/gms/Gossiper.java"
APPLICATION_STATE = "src/java/org/apache/cassandra/gms/ApplicationState.java"
ENDPOINT_STATE = "src/java/org/apache/cassandra/gms/EndpointState.java"
VERSIONED_VALUE = "src/java/org/apache/cassandra/gms/VersionedValue.java"
GOSSIPING_PROPERTY_FILE_SNITCH = "src/java/org/apache/cassandra/locator/GossipingPropertyFileSnitch.java"
RECONNECTABLE_SNITCH_HELPER = "src/java/org/apache/cassandra/locator/ReconnectableSnitchHelper.java"

GOSSIPER_TEST = "test/unit/org/apache/cassandra/gms/GossiperTest.java"
ENDPOINT_STATE_TEST = "test/unit/org/apache/cassandra/gms/EndpointStateTest.java"
SHADOW_ROUND_TEST = "test/unit/org/apache/cassandra/gms/ShadowRoundTest.java"
GOSSIP_SHUTDOWN_TEST = "test/unit/org/apache/cassandra/gms/GossipShutdownTest.java"
RECONNECTABLE_SNITCH_HELPER_TEST = "test/unit/org/apache/cassandra/locator/ReconnectableSnitchHelperTest.java"
DISTRIBUTED_GOSSIP_TEST = "test/distributed/org/apache/cassandra/distributed/test/GossipTest.java"

TARGET_DOCS = (
    "research/module-gossip-state-preferred-ip-coverage.md",
    "research/module-gossip-state-preferred-ip-drift-checker.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "gossip_digest_task_baseline",
    "gossip_stage_mutation_guard",
    "gossip_endpoint_state_merge",
    "gossip_application_state_wire_compat",
    "gossip_status_notification_order",
    "gossip_legacy_state_filter",
    "gossip_echo_mark_alive_dead",
    "gossip_shadow_round_startup_gate",
    "gossip_shutdown_announce",
    "gossip_preferred_ip_reconnect_baseline",
    "gossip_preferred_ip_distributed_gap",
    "gossip_reconnect_onjoin_legacy_gap",
    "gossip_existing_tests_baseline",
)

SOURCE_TOKEN_CHECKS = {
    GOSSIPER: (
        "private static void checkProperThreadForStateMutation()",
        "Stage.GOSSIP.executor().inExecutor()",
        "IllegalStateException e = new IllegalStateException(\"Attempting gossip state mutation from illegal thread: \" + Thread.currentThread().getName());",
        "MessagingService.instance().waitUntilListening();",
        "endpointStateMap.get(getBroadcastAddressAndPort()).updateHeartBeat();",
        "Gossiper.instance.makeGossipDigest(gDigests);",
        "Message<GossipDigestSyn> message = Message.out(GOSSIP_DIGEST_SYN, digestSynMessage);",
        "boolean gossipedToSeed = doGossipToLiveMember(message);",
        "maybeGossipToUnreachableMember(message);",
        "maybeGossipToSeed(message);",
        "doStatusCheck();",
        "FailureDetector.instance.registerFailureDetectionEventListener(this);",
        "void notifyFailureDetector(InetAddressAndPort endpoint, EndpointState remoteEndpointState)",
        "fd.remove(endpoint);",
        "fd.report(endpoint);",
        "Message<NoPayload> echoMessage = Message.out(ECHO_REQ, noPayload);",
        "MessagingService.instance().sendWithCallback(echoMessage, addr, echoHandler);",
        "runInGossipStageBlocking(() -> {",
        "subscriber.onAlive(addr, localState);",
        "subscriber.onDead(addr, localState);",
        "public void applyStateLocally(Map<InetAddressAndPort, EndpointState> epStateMap)",
        "remoteState.removeMajorVersion3LegacyApplicationStates();",
        "remoteGeneration > localTime + MAX_GENERATION_DIFFERENCE",
        "handleMajorStateChange(ep, remoteState);",
        "applyNewStates(ep, localEpStatePtr, remoteState, hasMajorVersion3Nodes);",
        "markAlive(ep, localEpStatePtr);",
        "localState.addApplicationStates(updatedStates, remoteState.getHeartBeatState());",
        "case STATUS:",
        "case STATUS_WITH_PORT:",
        "ApplicationState.INTERNAL_IP == updatedEntry.getKey() && localState.containsApplicationState(ApplicationState.INTERNAL_ADDRESS_AND_PORT)",
        "public synchronized Map<InetAddressAndPort, EndpointState> doShadowRound(Set<InetAddressAndPort> peers)",
        "MessagingService.instance().send(message, seed);",
        "if (!isSeed)",
        "throw new RuntimeException(\"Unable to gossip with any peers\");",
        "boolean sufficientForStartupSafetyCheck(Map<InetAddressAndPort, EndpointState> epStateMap)",
        "seedsInShadowRound.containsAll(seeds)",
        "addLocalApplicationState(ApplicationState.STATUS_WITH_PORT, StorageService.instance.valueFactory.shutdown(true));",
        "addLocalApplicationState(ApplicationState.STATUS, StorageService.instance.valueFactory.shutdown(true));",
        "Message<GossipShutdown> message = Message.out(Verb.GOSSIP_SHUTDOWN, new GossipShutdown(clone));",
    ),
    APPLICATION_STATE: (
        "Gossip uses the ordinal of this enum in the messages it exchanges",
        "@Deprecated(since = \"4.0\") STATUS",
        "@Deprecated(since = \"4.0\") INTERNAL_IP",
        "INTERNAL_ADDRESS_AND_PORT, //Replacement for INTERNAL_IP with up to two ports",
        "NATIVE_ADDRESS_AND_PORT, //Replacement for RPC_ADDRESS",
        "STATUS_WITH_PORT, //Replacement for STATUS",
        "DO NOT EDIT OR REMOVE PADDING STATES BELOW",
    ),
    ENDPOINT_STATE: (
        "private static class View",
        "private final AtomicReference<View> ref;",
        "public EndpointState(EndpointState other)",
        "public void addApplicationStates(Set<Map.Entry<ApplicationState, VersionedValue>> values, @Nullable HeartBeatState hbState)",
        "this.ref.compareAndSet(view, new View(hbState == null ? view.hbState : hbState, copy))",
        "void removeMajorVersion3LegacyApplicationStates()",
        "private boolean hasLegacyFields()",
        "private static Map<ApplicationState, VersionedValue> filterMajorVersion3LegacyApplicationStates(Map<ApplicationState, VersionedValue> states)",
        "case INTERNAL_IP:",
        "return !states.containsKey(ApplicationState.INTERNAL_ADDRESS_AND_PORT);",
        "case STATUS:",
        "return !states.containsKey(ApplicationState.STATUS_WITH_PORT);",
        "case RPC_ADDRESS:",
        "return !states.containsKey(ApplicationState.NATIVE_ADDRESS_AND_PORT);",
    ),
    VERSIONED_VALUE: (
        "public VersionedValue hibernate(boolean value)",
        "public VersionedValue shutdown(boolean value)",
        "return new VersionedValue(VersionedValue.SHUTDOWN + VersionedValue.DELIMITER + value);",
        "public VersionedValue internalIP(InetAddress private_ip)",
        "return new VersionedValue(private_ip.getHostAddress());",
        "public VersionedValue internalAddressAndPort(InetAddressAndPort private_ip_and_port)",
        "return new VersionedValue(private_ip_and_port.getHostAddressAndPort());",
    ),
    GOSSIPING_PROPERTY_FILE_SNITCH: (
        "preferLocal = Boolean.parseBoolean(properties.get(\"prefer_local\", \"false\"));",
        "public String getDatacenter(InetAddressAndPort endpoint)",
        "return epState.getApplicationState(ApplicationState.DC).value;",
        "public String getRack(InetAddressAndPort endpoint)",
        "return epState.getApplicationState(ApplicationState.RACK).value;",
        "public void gossiperStarting()",
        "Gossiper.instance.addLocalApplicationState(ApplicationState.INTERNAL_ADDRESS_AND_PORT",
        "Gossiper.instance.addLocalApplicationState(ApplicationState.INTERNAL_IP",
        "new ReconnectableSnitchHelper(this, myDC, preferLocal)",
        "Gossiper.instance.register(pendingHelper);",
        "Gossiper.instance.unregister(pendingHelper);",
    ),
    RECONNECTABLE_SNITCH_HELPER: (
        "public class ReconnectableSnitchHelper implements IEndpointStateChangeSubscriber",
        "OUTBOUND_PRECONNECT",
        "new OutboundConnectionSettings(publicAddress, localAddress).withDefaults(ConnectionCategory.MESSAGING)",
        "settings.authenticator().authenticate(settings.to.getAddress(), settings.to.getPort(), null, OUTBOUND_PRECONNECT)",
        "snitch.getDatacenter(publicAddress).equals(localDc)",
        "MessagingService.instance().maybeReconnectWithNewIp(publicAddress, localAddress);",
        "public void onJoin(InetAddressAndPort endpoint, EndpointState epState)",
        "if (preferLocal && !Gossiper.instance.isDeadState(epState))",
        "public void onChange(InetAddressAndPort endpoint, ApplicationState state, VersionedValue value)",
        "state == ApplicationState.INTERNAL_ADDRESS_AND_PORT",
        "state == ApplicationState.INTERNAL_IP",
        "Only use INTERNAL_IP if INTERNAL_ADDRESS_AND_PORT is unavailable",
        "public void onAlive(InetAddressAndPort endpoint, EndpointState state)",
        "internalIPAndPorts != null ? internalIPAndPorts : internalIP",
    ),
    GOSSIPER_TEST: (
        "public void testLargeGenerationJump()",
        "Gossiper.MAX_GENERATION_DIFFERENCE + 1",
        "Gossiper.MAX_GENERATION_DIFFERENCE * 10",
        "public void testDuplicatedStateUpdate()",
        "proposedRemoteState.updateHeartBeat();",
        "assertEquals(1, stateChangedNum);",
        "public void testNotFireDuplicatedNotificationsWithUpdateContainsOldAndNewState()",
        "It should only fire notification for STATUS_WITH_PORT",
        "It should not fire notification for STATUS",
    ),
    ENDPOINT_STATE_TEST: (
        "public void testMultiThreadedReadConsistency()",
        "private void innerTestMultiThreadedReadConsistency()",
        "public void testMultiThreadWriteConsistency()",
        "state.addApplicationStates(states);",
        "assertTrue(values.containsKey(ApplicationState.INTERNAL_IP));",
    ),
    SHADOW_ROUND_TEST: (
        "public void testDelayedResponse()",
        "MockMessagingService.when(verb(Verb.GOSSIP_DIGEST_SYN))",
        "MockMessagingService.when(verb(Verb.GOSSIP_DIGEST_ACK2)).dontReply();",
        "MockMessagingService.when(verb(Verb.SCHEMA_PULL_REQ)).dontReply();",
        "public void testBadAckInShadow()",
        "Unable to gossip with any peers",
        "public void testPreviouslyAssassinatedInShadow()",
        "VersionedValue.STATUS_LEFT",
    ),
    GOSSIP_SHUTDOWN_TEST: (
        "public void mixedMode()",
        "private static final int BEFORE_CHANGE = MessagingService.Version.VERSION_40.value;",
        "private static final int AFTER_CHANGE = MessagingService.Version.VERSION_50.value;",
        "Message<GossipShutdown> message = Message.out(Verb.GOSSIP_SHUTDOWN",
        "Assertions.assertThat(serde(message, BEFORE_CHANGE)).isNull();",
        "Assertions.assertThat(serde(message, AFTER_CHANGE)).isInstanceOf(GossipShutdown.class);",
    ),
    RECONNECTABLE_SNITCH_HELPER_TEST: (
        "public void failedAuthentication()",
        "MessagingServiceTest.ALLOW_NOTHING_AUTHENTICATOR",
        "ReconnectableSnitchHelper.reconnect(address, address, null, null);",
    ),
    DISTRIBUTED_GOSSIP_TEST: (
        "public void nodeDownDuringMove()",
        "Gossiper.instance.addLocalApplicationState(ApplicationState.STATUS_WITH_PORT",
        "public void gossipShutdownUpdatesTokenMetadata()",
        "Marked \" + node2.broadcastAddress() + \" as shutdown",
        "assertPendingRangesForPeer(false, movingAddress, cluster);",
        "public void restartGossipOnGossippingOnlyMember()",
    ),
}

DOC_TOKEN_CHECKS = {
    "research/module-gossip-state-preferred-ip-coverage.md": (
        *SCENARIO_IDS,
        GOSSIPER,
        APPLICATION_STATE,
        ENDPOINT_STATE,
        GOSSIPING_PROPERTY_FILE_SNITCH,
        RECONNECTABLE_SNITCH_HELPER,
        GOSSIPER_TEST,
        SHADOW_ROUND_TEST,
        RECONNECTABLE_SNITCH_HELPER_TEST,
        "gap still open",
    ),
    "research/module-gossip-state-preferred-ip-drift-checker.md": (
        *SCENARIO_IDS,
        "python3 research/tools/check-gossip-state-preferred-ip-drift.py",
        "gap still open",
        "onJoin() legacy fallback risk",
    ),
    "research/README.md": (
        "module-gossip-state-preferred-ip-coverage.md",
        "module-gossip-state-preferred-ip-drift-checker.md",
        "research/tools/check-gossip-state-preferred-ip-drift.py",
        "Gossip | 第五轮源码侧完成",
        "preferred IP reconnect distributed test",
    ),
    "research/notes/source-map.md": (
        "Gossip state/preferred IP coverage",
        "research/tools/check-gossip-state-preferred-ip-drift.py",
        "gossip_preferred_ip_distributed_gap",
        "test/unit/org/apache/cassandra/gms/ShadowRoundTest.java",
        "test/unit/org/apache/cassandra/gms/GossipShutdownTest.java",
    ),
}

DISTRIBUTED_PREFERRED_IP_GAP_TOKENS = (
    "ReconnectableSnitchHelper",
    "maybeReconnectWithNewIp",
    "prefer_local",
)


@dataclass
class CheckResult:
    status: str
    category: str
    target: str
    detail: str


def read_text(path):
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def add_result(results, status, category, target, detail):
    results.append(CheckResult(status, category, target, detail))


def check_tokens(results, category, path, tokens):
    try:
        content = read_text(path)
    except FileNotFoundError:
        add_result(results, "FAIL", category, path, "missing file")
        return

    for token in tokens:
        if token in content:
            add_result(results, "PASS", category, path, token)
        else:
            add_result(results, "FAIL", category, path, f"missing token: {token}")


def check_onjoin_legacy_risk(results):
    content = read_text(RECONNECTABLE_SNITCH_HELPER)
    start = content.index("public void onJoin")
    end = content.index("public void onChange", start)
    block = content[start:end]
    count = block.count("epState.getApplicationState(ApplicationState.INTERNAL_ADDRESS_AND_PORT)")
    if count == 2 and "ApplicationState.INTERNAL_IP" not in block:
        add_result(results, "PASS", "source behavior", RECONNECTABLE_SNITCH_HELPER, "onJoin legacy fallback risk still matches docs")
    else:
        add_result(results, "FAIL", "source behavior", RECONNECTABLE_SNITCH_HELPER, "onJoin legacy fallback risk changed; update research")


def check_distributed_gap(results):
    matches = []
    for path in (REPO_ROOT / "test/distributed").rglob("*.java"):
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="latin-1")
        for token in DISTRIBUTED_PREFERRED_IP_GAP_TOKENS:
            if token in content:
                matches.append(f"{path.relative_to(REPO_ROOT)}:{token}")

    if matches:
        add_result(results, "FAIL", "gap still open", "test/distributed", "distributed preferred-IP coverage may exist: " + ", ".join(matches[:20]))
    else:
        add_result(results, "PASS", "gap still open", "test/distributed", "no distributed preferred-IP reconnect coverage found")


def run_checks():
    results = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        check_tokens(results, "source token contract", path, tokens)
    for path, tokens in DOC_TOKEN_CHECKS.items():
        check_tokens(results, "doc token contract", path, tokens)
    check_onjoin_legacy_risk(results)
    check_distributed_gap(results)
    return results


def as_json(results):
    return {
        "total": len(results),
        "passed": sum(1 for result in results if result.status == "PASS"),
        "failed": [result.__dict__ for result in results if result.status == "FAIL"],
    }


def main():
    parser = argparse.ArgumentParser(description="Check Gossip state/preferred-IP research drift.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args()

    results = run_checks()
    failures = [result for result in results if result.status == "FAIL"]

    if args.json:
        print(json.dumps(as_json(results), indent=2, sort_keys=True))
    elif failures:
        for failure in failures:
            print(f"FAIL [{failure.category}] {failure.target}: {failure.detail}")
        print(f"{len(failures)} of {len(results)} checks failed")
    else:
        print(f"All {len(results)} Gossip state/preferred-IP drift checks passed")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
