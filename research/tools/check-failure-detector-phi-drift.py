#!/usr/bin/env python3
#
# Source-only drift check for Failure Detector phi/conviction research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

FAILURE_DETECTOR = "src/java/org/apache/cassandra/gms/FailureDetector.java"
FAILURE_DETECTOR_MBEAN = "src/java/org/apache/cassandra/gms/FailureDetectorMBean.java"
IFAILURE_DETECTOR = "src/java/org/apache/cassandra/gms/IFailureDetector.java"
IFAILURE_DETECTION_EVENT_LISTENER = "src/java/org/apache/cassandra/gms/IFailureDetectionEventListener.java"
GOSSIPER = "src/java/org/apache/cassandra/gms/Gossiper.java"
ENDPOINT_STATE = "src/java/org/apache/cassandra/gms/EndpointState.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
RELEVANT_PROPERTIES = "src/java/org/apache/cassandra/config/CassandraRelevantProperties.java"
NODE_PROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
REPAIR_SESSION = "src/java/org/apache/cassandra/repair/RepairSession.java"
ACTIVE_REPAIR_SERVICE = "src/java/org/apache/cassandra/service/ActiveRepairService.java"
PAXOS_CLEANUP_SESSION = "src/java/org/apache/cassandra/service/paxos/cleanup/PaxosCleanupSession.java"
SIMULATED_FAILURE_DETECTOR = "test/simulator/main/org/apache/cassandra/simulator/systems/SimulatedFailureDetector.java"

FAILURE_DETECTOR_TEST = "test/unit/org/apache/cassandra/gms/FailureDetectorTest.java"
REPAIR_SESSION_TEST = "test/unit/org/apache/cassandra/repair/RepairSessionTest.java"
PAXOS_REPAIR2_TEST = "test/distributed/org/apache/cassandra/distributed/test/PaxosRepair2Test.java"
REPAIR_COORDINATOR_NEIGHBOUR_DOWN = "test/distributed/org/apache/cassandra/distributed/test/RepairCoordinatorNeighbourDown.java"
FORCE_REPAIR_TEST = "test/distributed/org/apache/cassandra/distributed/test/repair/ForceRepairTest.java"
GOSSIP_INFO_TEST = "test/unit/org/apache/cassandra/tools/nodetool/GossipInfoTest.java"

TARGET_DOCS = (
    "research/module-failure-detector-phi-conviction-matrix.md",
    "research/module-failure-detector-phi-drift-checker.md",
    "research/module-gossip-messaging.md",
    "research/module-gossip-messaging-deep-dive.md",
    "research/module-jmx-nodeprobe-fd-drift-checker.md",
    "research/flow-gossip.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "fd_phi_arrival_window_seed",
    "fd_report_generation_version_gate",
    "fd_local_pause_suppression",
    "fd_phi_threshold_and_jmx_scale",
    "fd_config_limits_and_system_properties",
    "fd_conviction_gossip_stage",
    "fd_shutdown_force_conviction",
    "fd_downstream_repair_confidence",
    "fd_simulator_override",
    "fd_observability_and_tests",
)

SOURCE_TOKEN_CHECKS = {
    FAILURE_DETECTOR: (
        'public static final String MBEAN_NAME = "org.apache.cassandra.net:type=FailureDetector";',
        "private static final int SAMPLE_SIZE = 1000;",
        "protected static final long INITIAL_VALUE_NANOS = TimeUnit.NANOSECONDS.convert(getInitialValue(), TimeUnit.MILLISECONDS);",
        "private static final int DEBUG_PERCENTAGE = 80;",
        "private static final long MAX_LOCAL_PAUSE_IN_NANOS = getMaxLocalPause();",
        "MAX_LOCAL_PAUSE_IN_MS.getLong()",
        "FD_INITIAL_VALUE_MS.getLong(Gossiper.intervalInMillis * 2L)",
        "private final double PHI_FACTOR = 1.0 / Math.log(10.0);",
        "private final ConcurrentHashMap<InetAddressAndPort, ArrivalWindow> arrivalSamples = new ConcurrentHashMap<>();",
        "private final List<IFailureDetectionEventListener> fdEvntListeners = new CopyOnWriteArrayList<>();",
        "MBeanWrapper.instance.registerMBean(this, MBEAN_NAME);",
        "public TabularData getPhiValuesWithPort() throws OpenDataException",
        "new Object[]{entry.getKey().toString(withPort), phi * PHI_FACTOR}",
        "public void setPhiConvictThreshold(double phi)",
        "public double getPhiConvictThreshold()",
        "if (ep.equals(FBUtilities.getBroadcastAddressAndPort()))",
        "return true;",
        "public void report(InetAddressAndPort ep)",
        "heartbeatWindow = new ArrivalWindow(SAMPLE_SIZE);",
        "arrivalSamples.putIfAbsent(ep, heartbeatWindow)",
        "public void interpret(InetAddressAndPort ep)",
        "if (diff > MAX_LOCAL_PAUSE_IN_NANOS)",
        'logger.warn("Not marking nodes down due to local pause of {}ns > {}ns"',
        'logger.debug("Still not marking nodes down due to local pause");',
        "double phi = hbWnd.phi(now);",
        "if (PHI_FACTOR * phi > getPhiConvictThreshold())",
        "listener.convict(ep, phi);",
        "PHI_FACTOR * phi * DEBUG_PERCENTAGE / 100.0 > getPhiConvictThreshold()",
        "public void forceConviction(InetAddressAndPort ep)",
        "listener.convict(ep, getPhiConvictThreshold());",
        "arrivalSamples.remove(ep);",
        "fdEvntListeners.add(listener);",
        "fdEvntListeners.remove(listener);",
        "static long calculateMaxInterval()",
        "class ArrayBackedBoundedStats",
        "private final long[] arrivalIntervals;",
        "mean = (double)sum / size();",
        "class ArrivalWindow",
        "private double lastReportedPhi = Double.MIN_VALUE;",
        "private final long MAX_INTERVAL_IN_NANO = getMaxInterval();",
        "FD_MAX_INTERVAL_MS.getLong(TimeUnit.NANOSECONDS.toMillis(FailureDetector.INITIAL_VALUE_NANOS))",
        "if (interArrivalTime <= MAX_INTERVAL_IN_NANO)",
        "arrivalIntervals.add(FailureDetector.INITIAL_VALUE_NANOS);",
        "lastReportedPhi = t / mean();",
    ),
    IFAILURE_DETECTOR: (
        "public boolean isAlive(InetAddressAndPort ep);",
        "public void interpret(InetAddressAndPort ep);",
        "public void report(InetAddressAndPort ep);",
        "public void remove(InetAddressAndPort ep);",
        "public void forceConviction(InetAddressAndPort ep);",
        "public void registerFailureDetectionEventListener(IFailureDetectionEventListener listener);",
        "public void unregisterFailureDetectionEventListener(IFailureDetectionEventListener listener);",
    ),
    IFAILURE_DETECTION_EVENT_LISTENER: (
        "public interface IFailureDetectionEventListener",
        "public void convict(InetAddressAndPort ep, double phi);",
    ),
    FAILURE_DETECTOR_MBEAN: (
        "public void dumpInterArrivalTimes();",
        "public void setPhiConvictThreshold(double phi);",
        "public double getPhiConvictThreshold();",
        "public TabularData getPhiValuesWithPort() throws OpenDataException;",
    ),
    GOSSIPER: (
        "FailureDetector.instance.registerFailureDetectionEventListener(this);",
        "public void convict(InetAddressAndPort endpoint, double phi)",
        "runInGossipStageBlocking(() -> {",
        "if (!epState.isAlive())",
        "if (isShutdown(endpoint))",
        "markAsShutdown(endpoint);",
        "markDead(endpoint, epState);",
        "GossiperDiagnostics.convicted(this, endpoint, phi);",
        "FailureDetector.instance.forceConviction(endpoint);",
        "public void notifyFailureDetector(Map<InetAddressAndPort, EndpointState> remoteEpStateMap)",
        "void notifyFailureDetector(InetAddressAndPort endpoint, EndpointState remoteEndpointState)",
        "if (remoteGeneration > localGeneration)",
        "fd.remove(endpoint);",
        "fd.report(endpoint);",
        "if (remoteGeneration == localGeneration)",
        "if (remoteVersion > localVersion)",
        "public boolean isAlive(InetAddressAndPort endpoint)",
        "return epState.isAlive() && !isDeadState(epState);",
    ),
    ENDPOINT_STATE: (
        "public boolean isAlive()",
        "public void markAlive()",
        "public void markDead()",
    ),
    CONFIG: (
        "public volatile double phi_convict_threshold = 8.0;",
    ),
    DATABASE_DESCRIPTOR: (
        "if (conf.phi_convict_threshold < 5 || conf.phi_convict_threshold > 16)",
        'throw new ConfigurationException("phi_convict_threshold must be between 5 and 16, but was " + conf.phi_convict_threshold, false);',
        "public static double getPhiConvictThreshold()",
        "return conf.phi_convict_threshold;",
        "public static void setPhiConvictThreshold(double phiConvictThreshold)",
        "conf.phi_convict_threshold = phiConvictThreshold;",
    ),
    RELEVANT_PROPERTIES: (
        'FD_INITIAL_VALUE_MS("cassandra.fd_initial_value_ms")',
        'FD_MAX_INTERVAL_MS("cassandra.fd_max_interval_ms")',
        'MAX_LOCAL_PAUSE_IN_MS("cassandra.max_local_pause_in_ms", "5000")',
    ),
    NODE_PROBE: (
        "return withPort ? fdProxy.getPhiValuesWithPort() : fdProxy.getPhiValues();",
    ),
    REPAIR_SESSION: (
        "implements IEndpointStateChangeSubscriber,",
        "IFailureDetectionEventListener,",
        "public void convict(InetAddressAndPort endpoint, double phi)",
        "if (phi < 2 * DatabaseDescriptor.getPhiConvictThreshold())",
        'new IOException(String.format("Endpoint %s died", endpoint))',
    ),
    ACTIVE_REPAIR_SERVICE: (
        "IFailureDetectionEventListener> void registerOnFdAndGossip(final T task)",
        "ctx.failureDetector().registerFailureDetectionEventListener(task);",
        "ctx.failureDetector().unregisterFailureDetectionEventListener(task);",
        "public void convict(InetAddressAndPort ep, double phi)",
        "if (phi < 2 * DatabaseDescriptor.getPhiConvictThreshold() || parentRepairSessions.isEmpty())",
    ),
    PAXOS_CLEANUP_SESSION: (
        "implements Runnable,",
        "IFailureDetectionEventListener,",
        "public void convict(InetAddressAndPort ep, double phi)",
        'maybeKillSession(ep, "convicted by failure detector");',
    ),
    SIMULATED_FAILURE_DETECTOR: (
        "public static class Instance implements IFailureDetector",
        "private static volatile Function<InetSocketAddress, Boolean> OVERRIDE;",
        "private static final Map<IFailureDetectionEventListener, Boolean> LISTENERS",
        "public boolean isAlive(InetAddressAndPort ep)",
        "return override != null ? override : wrapped().isAlive(ep);",
        "LISTENERS.put(listener, Boolean.TRUE);",
        "LISTENERS.remove(listener);",
        "register.accept(ep -> LISTENERS.keySet().forEach(c -> c.convict(InetAddressAndPort.getByAddress(ep), Double.MAX_VALUE)));",
        "public void markDown(InetSocketAddress address)",
    ),
    FAILURE_DETECTOR_TEST: (
        "public void testConvictAfterLeft()",
        "DatabaseDescriptor.setPhiConvictThreshold(0);",
        "FailureDetector.instance.report(leftHost);",
        "FailureDetector.instance.interpret(leftHost);",
        'assertFalse("Left endpoint not convicted", FailureDetector.instance.isAlive(leftHost));',
        "public void testMaxIntervalCalculation()",
        "CassandraRelevantProperties.FD_MAX_INTERVAL_MS.reset();",
        "assertEquals(FailureDetector.INITIAL_VALUE_NANOS, FailureDetector.calculateMaxInterval());",
        "CassandraRelevantProperties.FD_MAX_INTERVAL_MS.setLong(overrideMillis);",
    ),
    REPAIR_SESSION_TEST: (
        "session.convict(remote, Double.MAX_VALUE);",
    ),
    PAXOS_REPAIR2_TEST: (
        "FailureDetector.instance.isAlive(node3)",
    ),
    REPAIR_COORDINATOR_NEIGHBOUR_DOWN: (
        "while (FailureDetector.instance.isAlive(neighbor))",
    ),
    FORCE_REPAIR_TEST: (
        "while (FailureDetector.instance.isAlive(neighbor))",
    ),
    GOSSIP_INFO_TEST: (
        "gossipinfo",
        "--resolve-ip",
    ),
}

DOC_REQUIRED_TOKENS = (
    "Failure Detector Phi And Conviction Matrix",
    "Failure Detector Phi Drift Checker",
    "SAMPLE_SIZE = 1000",
    "PHI_FACTOR",
    "phi_convict_threshold",
    "cassandra.max_local_pause_in_ms",
    "cassandra.fd_initial_value_ms",
    "cassandra.fd_max_interval_ms",
    "MAX_LOCAL_PAUSE_IN_NANOS",
    "ArrivalWindow",
    "ArrayBackedBoundedStats",
    "FailureDetector.report()",
    "FailureDetector.interpret()",
    "Gossiper.notifyFailureDetector()",
    "Gossiper.convict()",
    "RepairSession",
    "ActiveRepairService",
    "PaxosCleanupSession",
    "SimulatedFailureDetector",
    "FailureDetectorTest",
    "RepairSessionTest",
    "PaxosRepair2Test",
    "RepairCoordinatorNeighbourDown",
    "ForceRepairTest",
    "module-failure-detector-phi-conviction-matrix.md",
    "module-failure-detector-phi-drift-checker.md",
    "check-failure-detector-phi-drift.py",
) + SCENARIO_IDS


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def source_checks() -> list[Check]:
    checks: list[Check] = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        for token in tokens:
            checks.append(Check(f"source token {token}", path, token in text))
    return checks


def doc_checks() -> list[Check]:
    docs_text = "\n".join(read(path) for path in TARGET_DOCS)
    return [Check(f"doc token {token}", ",".join(TARGET_DOCS), token in docs_text) for token in DOC_REQUIRED_TOKENS]


def run_checks() -> tuple[list[Check], dict[str, object]]:
    checks = source_checks()
    checks.extend(doc_checks())
    metadata = {
        "scenario_ids": list(SCENARIO_IDS),
        "source_files": sorted(SOURCE_TOKEN_CHECKS.keys()),
        "doc_files": list(TARGET_DOCS),
    }
    return checks, metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Failure Detector phi/conviction research for source/doc drift.")
    parser.add_argument("--json", action="store_true", help="emit JSON metadata and check results")
    args = parser.parse_args()

    try:
        checks, metadata = run_checks()
    except Exception as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2

    failed = [check for check in checks if not check.ok]
    if args.json:
        print(json.dumps({
            "ok": not failed,
            "metadata": metadata,
            "checks": [check.__dict__ for check in checks],
            "failed": [check.__dict__ for check in failed],
        }, indent=2, sort_keys=True))
    elif failed:
        for check in failed:
            print(f"FAIL {check.name} ({check.source})")
    else:
        print(f"OK Failure Detector phi drift checks passed ({len(checks)} checks, {len(SCENARIO_IDS)} scenarios)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
