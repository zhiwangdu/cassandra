#!/usr/bin/env python3
#
# Source-only drift check for startup ordered marker research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

CASSANDRA_DAEMON = "src/java/org/apache/cassandra/service/CassandraDaemon.java"
STARTUP_CHECKS = "src/java/org/apache/cassandra/service/StartupChecks.java"
STORAGE_SERVICE = "src/java/org/apache/cassandra/service/StorageService.java"
NATIVE_TRANSPORT_SERVICE = "src/java/org/apache/cassandra/service/NativeTransportService.java"
PIPELINE_CONFIGURATOR = "src/java/org/apache/cassandra/transport/PipelineConfigurator.java"
SERVER = "src/java/org/apache/cassandra/transport/Server.java"
INSTANCE = "test/distributed/org/apache/cassandra/distributed/impl/Instance.java"
BOOTSTRAP_TEST = "test/distributed/org/apache/cassandra/distributed/test/ring/BootstrapTest.java"
BOOTSTRAP_BINARY_DISABLED_TEST = "test/distributed/org/apache/cassandra/distributed/test/BootstrapBinaryDisabledTest.java"
AUTH_TEST = "test/distributed/org/apache/cassandra/distributed/test/AuthTest.java"
NODETOOL_ENABLE_DISABLE_BINARY_TEST = "test/distributed/org/apache/cassandra/distributed/test/NodeToolEnableDisableBinaryTest.java"
NATIVE_TRANSPORT_SERVICE_TEST = "test/unit/org/apache/cassandra/service/NativeTransportServiceTest.java"
JVMD_TEST_TEST = "test/distributed/org/apache/cassandra/distributed/test/JVMDTestTest.java"

TARGET_DOCS = (
    "research/module-startup-ordered-log-marker-matrix.md",
    "research/module-startup-ordered-marker-drift-checker.md",
    "research/module-startup-cold-start-integration-matrix.md",
    "research/module-startup-cold-integration-drift-checker.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "startup_marker_jmx_before_checks",
    "startup_marker_preflight_before_system_writes",
    "startup_marker_schema_storage_before_mbean",
    "startup_marker_mbean_during_bootstrap",
    "startup_marker_auth_before_transport",
    "startup_marker_complete_setup_before_start",
    "startup_marker_transport_gate_before_listen",
    "startup_marker_listen_before_rpc_ready",
    "startup_marker_startup_complete_after_start",
    "startup_marker_stop_deactivate_inverse",
    "startup_marker_injvm_dtest_order_divergence",
    "startup_marker_ordered_e2e_gap",
)

SOURCE_TOKEN_CHECKS = {
    CASSANDRA_DAEMON: (
        "maybeInitJmx();",
        "logSystemInfo(logger);",
        "CommitLog.instance.start();",
        "runStartupChecks();",
        "SystemKeyspace.snapshotOnVersionChange();",
        "SystemKeyspace.persistLocalMetadata();",
        "Schema.instance.loadFromDisk();",
        "setupVirtualKeyspaces();",
        "scrubDataDirectories();",
        "loadRowAndKeyCacheAsync().get();",
        "CommitLog.instance.recoverSegmentsOnDisk();",
        "ActiveRepairService.instance().start();",
        "StreamManager.instance.start();",
        "QueryProcessor.instance.preloadPreparedStatements();",
        "StorageService.instance.registerDaemon(this);",
        "StorageService.instance.initServer();",
        "Gossiper.waitToSettle();",
        "StorageService.instance.doAuthSetup(false);",
        "initializeClientTransports();",
        "AuthCacheService.instance.warmCaches();",
        "PaxosState.startAutoRepairs();",
        "completeSetup();",
        "StartupClusterConnectivityChecker.create(DatabaseDescriptor.getBlockForPeersTimeoutInSeconds(),",
        "connectivityChecker.execute(Gossiper.instance.getEndpoints(), DatabaseDescriptor.getEndpointSnitch()::getDatacenter);",
        "validateTransportsCanStart();",
        "startClientTransports();",
        "logger.info(\"Startup complete\");",
        "throw new IllegalStateException(\"Node is not yet bootstrapped completely.",
        "throw new IllegalStateException(\"Not starting client transports in write_survey mode as it's bootstrapping or \" +",
        "nativeTransportService.start();",
        "StorageService.instance.setRpcReady(true);",
        "StorageService.instance.setRpcReady(false);",
    ),
    STARTUP_CHECKS: (
        "public void verify(StartupChecksOptions options) throws StartupException",
        "for (StartupCheck test : preFlightChecks)",
        "test.execute(options);",
        "test.postAction(options);",
        "logger.warn(\"Failed to run startup check post-action on \" + test.getStartupCheckType());",
        "public static final StartupCheck checkJMXPorts",
        "logger.info(\"JMX is enabled to receive remote connections on port: {}\", jmxPort);",
        "public static final StartupCheck checkDataDirs",
        "public static final StartupCheck checkSSTablesFormat",
    ),
    STORAGE_SERVICE: (
        "public synchronized void initServer(int schemaTimeoutMillis, int ringTimeoutMillis) throws ConfigurationException",
        "logger.info(\"Cassandra version: {}\", FBUtilities.getReleaseVersionString());",
        "logger.info(\"Git SHA: {}\", FBUtilities.getGitSHA());",
        "logger.info(\"Native protocol supported versions: {} (default: {})\"",
        "registerMBeans();",
        "prepareToJoin();",
        "joinTokenRing(schemaTimeoutMillis, ringTimeoutMillis);",
        "doAuthSetup(true);",
        "completeInitialization();",
        "private void registerMBeans()",
        "MBeanWrapper.instance.registerMBean(this, jmxObjectName);",
        "public void registerDaemon(CassandraDaemon daemon)",
        "this.daemon = daemon;",
        "private final AtomicBoolean authSetupCalled = new AtomicBoolean(false);",
        "public void doAuthSetup(boolean setUpSchema)",
        "if (!authSetupCalled.getAndSet(true))",
        "authSetupComplete = true;",
        "public boolean authSetupCalled()",
        "public void setRpcReady(boolean value)",
        "Gossiper.instance.addLocalApplicationState(ApplicationState.RPC_READY, valueFactory.rpcReady(value));",
    ),
    NATIVE_TRANSPORT_SERVICE: (
        "public void start()",
        "logger.info(\"Using Netty Version: {}\", Version.identify().entrySet());",
        "initialize();",
        "servers.forEach(Server::start);",
        "public void stop(boolean force)",
        "servers.forEach((s) -> s.stop(force));",
        "public boolean isRunning()",
    ),
    PIPELINE_CONFIGURATOR: (
        "logger.info(\"Starting listening for CQL clients on {} ({})...\", socket, tlsEncryptionPolicy.description());",
        "return bootstrap.bind(socket);",
    ),
    SERVER: (
        "public synchronized void start()",
        "pipelineConfigurator.initializeChannel(workerGroup, socket, connectionFactory)",
        "isRunning.set(true);",
        "private void close(boolean force)",
        "logger.info(\"Stop listening for CQL clients\");",
    ),
    INSTANCE: (
        "if (config.has(JMX))",
        "startJmx();",
        "DatabaseDescriptor.daemonInitialization();",
        "CassandraDaemon.getInstanceForTesting().runStartupChecks();",
        "SystemKeyspace.persistLocalMetadata(config::hostId);",
        "StorageService.instance.registerDaemon(CassandraDaemon.getInstanceForTesting());",
        "StorageService.instance.initServer();",
        "Gossiper.waitToSettle();",
        "CassandraDaemon.getInstanceForTesting().completeSetup();",
        "CassandraDaemon.getInstanceForTesting().initializeClientTransports();",
        "CassandraDaemon.getInstanceForTesting().start();",
        "PaxosState.startAutoRepairs();",
    ),
}

TEST_TOKEN_CHECKS = {
    BOOTSTRAP_TEST: (
        "testStorageServiceMBeanIsPublishedOnJMXDuringBootstrap",
        "JMX.newMBeanProxy(mbsc, new ObjectName(\"org.apache.cassandra.db:type=StorageService\"), StorageServiceMBean.class);",
        "assertEquals(sp.getOperationMode(), StorageService.Mode.JOINING.toString());",
    ),
    BOOTSTRAP_BINARY_DISABLED_TEST: (
        "Not starting client transports in write_survey mode as it's bootstrapping or auth is enabled",
        "Node is not yet bootstrapped completely",
        "node.nodetoolResult(\"bootstrap\", \"resume\").asserts().success();",
        "node.logs().watchFor(\"Starting listening for CQL clients\");",
    ),
    AUTH_TEST: (
        "authSetupIsCalledAfterStartup",
        "StorageService.instance.authSetupCalled()",
    ),
    NODETOOL_ENABLE_DISABLE_BINARY_TEST: (
        "testEnableDisableBinary",
        "containsIgnoringCase(\"Stop listening for CQL clients\")",
        "containsIgnoringCase(\"Starting listening for CQL clients\")",
        "assertTrue(canConnect());",
        "assertFalse(canConnect());",
    ),
    NATIVE_TRANSPORT_SERVICE_TEST: (
        "testServiceCanBeStopped",
        "testIgnoresStartOnAlreadyStarted",
        "testConcurrentStarts",
        "testPlainDefaultPort",
        "testSSLOptional",
        "testSSLPortWithOptionalEncryption",
    ),
    JVMD_TEST_TEST: (
        "LogAction logs = cluster.get(1).logs();",
        "logs.grep(\"JVM Arguments\")",
    ),
}

DOC_REQUIRED_TOKENS = (
    "research/tools/check-startup-ordered-marker-drift.py",
    "research/module-startup-ordered-log-marker-matrix.md",
    "research/module-startup-ordered-marker-drift-checker.md",
    "CassandraDaemon",
    "StartupChecks",
    "StorageService",
    "NativeTransportService",
    "PipelineConfigurator",
    "Server",
    "Instance.startup",
    "Startup complete",
    "Starting listening for CQL clients",
    "StorageServiceMBean",
    "authSetupCalled",
    "RPC_READY",
    "LogAction",
    "BootstrapBinaryDisabledTest",
    "NodeToolEnableDisableBinaryTest",
    "startup_marker_ordered_e2e_gap",
) + tuple(SOURCE_TOKEN_CHECKS.keys()) + tuple(TEST_TOKEN_CHECKS.keys()) + SCENARIO_IDS

ORDERED_E2E_TOKENS = (
    "Startup complete",
    "Starting listening for CQL clients",
    "StorageServiceMBean",
    "authSetupCalled",
)

LOG_ASSERTION_TOKENS = (
    "logs().watchFor",
    "logs().grep",
    "LogAction",
)


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def token_checks(mapping: dict[str, tuple[str, ...]], category: str) -> list[Check]:
    checks: list[Check] = []
    for path, tokens in mapping.items():
        text = read(path)
        missing = [token for token in tokens if token not in text]
        checks.append(Check(f"{category} {path}", path, not missing))
    return checks


def doc_checks() -> list[Check]:
    docs = {path: read(path) for path in TARGET_DOCS}
    combined = "\n".join(docs.values())
    checks = [Check(f"target doc exists {path}", path, bool(text.strip())) for path, text in docs.items()]

    for token in DOC_REQUIRED_TOKENS:
        checks.append(Check(f"doc token {token}", "research", token in combined))

    matrix = docs["research/module-startup-ordered-log-marker-matrix.md"]
    drift_doc = docs["research/module-startup-ordered-marker-drift-checker.md"]
    for scenario in SCENARIO_IDS:
        checks.append(Check(f"scenario coverage {scenario}", TARGET_DOCS[0], scenario in matrix and scenario in drift_doc))

    return checks


def ordered_e2e_gap_checks() -> list[Check]:
    candidates: list[str] = []
    for root in ("test/unit", "test/distributed"):
        for path in sorted((REPO_ROOT / root).rglob("*.java")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if all(token in text for token in ORDERED_E2E_TOKENS) and any(token in text for token in LOG_ASSERTION_TOKENS):
                candidates.append(str(path.relative_to(REPO_ROOT)))

    return [
        Check(
            "gap still open: no single ordered startup marker E2E test",
            "test/unit test/distributed",
            not candidates,
        )
    ]


def run_checks() -> list[Check]:
    return (
        token_checks(SOURCE_TOKEN_CHECKS, "source token contract")
        + token_checks(TEST_TOKEN_CHECKS, "test token contract")
        + doc_checks()
        + ordered_e2e_gap_checks()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Check startup ordered marker research drift.")
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
            print("FAIL startup ordered marker drift check")
            for failure in failures:
                print(f"- {failure.name} ({failure.source})")
        else:
            print(f"OK startup ordered marker drift check: {len(checks)} checks")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
