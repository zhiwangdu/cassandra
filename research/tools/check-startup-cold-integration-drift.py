#!/usr/bin/env python3
#
# Source-only drift check for Startup cold-start integration research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

CASSANDRA_DAEMON = "src/java/org/apache/cassandra/service/CassandraDaemon.java"
STORAGE_SERVICE = "src/java/org/apache/cassandra/service/StorageService.java"
NATIVE_TRANSPORT_SERVICE = "src/java/org/apache/cassandra/service/NativeTransportService.java"
DEFAULT_FS_ERROR_HANDLER = "src/java/org/apache/cassandra/service/DefaultFSErrorHandler.java"
JVM_STABILITY_INSPECTOR = "src/java/org/apache/cassandra/utils/JVMStabilityInspector.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
CASSANDRA_YAML = "conf/cassandra.yaml"

BOOTSTRAP_TEST = "test/distributed/org/apache/cassandra/distributed/test/ring/BootstrapTest.java"
BOOTSTRAP_BINARY_DISABLED_TEST = "test/distributed/org/apache/cassandra/distributed/test/BootstrapBinaryDisabledTest.java"
AUTH_TEST = "test/distributed/org/apache/cassandra/distributed/test/AuthTest.java"
NODETOOL_ENABLE_DISABLE_BINARY_TEST = "test/distributed/org/apache/cassandra/distributed/test/NodeToolEnableDisableBinaryTest.java"
DISABLE_BINARY_TEST = "test/distributed/org/apache/cassandra/distributed/test/DisableBinaryTest.java"
DEFAULT_FS_ERROR_HANDLER_TEST = "test/unit/org/apache/cassandra/service/DefaultFSErrorHandlerTest.java"
DISK_FAILURE_POLICY_TEST = "test/unit/org/apache/cassandra/service/DiskFailurePolicyTest.java"
COMMITLOG_FAILURE_POLICY_TEST = "test/unit/org/apache/cassandra/db/commitlog/CommitLogFailurePolicyTest.java"
NATIVE_TRANSPORT_SERVICE_TEST = "test/unit/org/apache/cassandra/service/NativeTransportServiceTest.java"

TARGET_DOCS = (
    "research/module-startup-cold-start-integration-matrix.md",
    "research/module-startup-cold-integration-drift-checker.md",
    "research/module-startup-daemon-deep-dive.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "startup_cold_jmx_early_bootstrap",
    "startup_cold_daemon_registration_order",
    "startup_cold_complete_setup_marker",
    "startup_cold_native_rpc_ready_gate",
    "startup_cold_bootstrap_binary_gate",
    "startup_cold_auth_setup_ready",
    "startup_cold_jmx_binary_operator_path",
    "startup_cold_failure_policy_boundary",
    "startup_cold_log_marker_gap",
    "startup_cold_existing_tests_baseline",
)

SOURCE_TOKEN_CHECKS = {
    CASSANDRA_DAEMON: (
        "private boolean setupCompleted;",
        "this.setupCompleted = false;",
        "FileUtils.setFSErrorHandler(new DefaultFSErrorHandler());",
        "maybeInitJmx();",
        "jmxServer = JMXServerUtils.createJMXServer(Integer.parseInt(jmxPort), localOnly);",
        "CommitLog.instance.start();",
        "runStartupChecks();",
        "SystemKeyspace.persistLocalMetadata();",
        "Schema.instance.loadFromDisk();",
        "loadRowAndKeyCacheAsync().get();",
        "CommitLog.instance.recoverSegmentsOnDisk();",
        "StorageService.instance.registerDaemon(this);",
        "StorageService.instance.initServer();",
        "StorageService.instance.doAuthSetup(false);",
        "initializeClientTransports();",
        "AuthCacheService.instance.warmCaches();",
        "PaxosState.startAutoRepairs();",
        "completeSetup();",
        "setupCompleted = true;",
        "public boolean setupCompleted()",
        "StartupClusterConnectivityChecker.create(DatabaseDescriptor.getBlockForPeersTimeoutInSeconds(),",
        "connectivityChecker.execute(Gossiper.instance.getEndpoints(), DatabaseDescriptor.getEndpointSnitch()::getDatacenter);",
        "validateTransportsCanStart();",
        "startClientTransports();",
        "logger.info(\"Startup complete\");",
        "throw new IllegalStateException(\"Node is not yet bootstrapped completely.",
        "throw new IllegalStateException(\"setup() must be called first for CassandraDaemon\");",
        "nativeTransportService.start();",
        "StorageService.instance.setRpcReady(true);",
        "StorageService.instance.setRpcReady(false);",
    ),
    STORAGE_SERVICE: (
        "private final AtomicBoolean authSetupCalled = new AtomicBoolean(false);",
        "private void registerMBeans()",
        "MBeanWrapper.instance.registerMBean(this, jmxObjectName);",
        "MBeanWrapper.instance.registerMBean(StreamManager.instance, StreamManager.OBJECT_NAME);",
        "public void registerDaemon(CassandraDaemon daemon)",
        "this.daemon = daemon;",
        "public synchronized void startNativeTransport()",
        "checkServiceAllowedToStart(\"native transport\");",
        "throw new IllegalStateException(\"No configured daemon\");",
        "daemon.startNativeTransport();",
        "public void stopNativeTransport(boolean force)",
        "daemon.stopNativeTransport(force);",
        "public boolean isDaemonSetupCompleted()",
        "return daemon != null && daemon.setupCompleted();",
        "public synchronized void initServer(int schemaTimeoutMillis, int ringTimeoutMillis) throws ConfigurationException",
        "logger.info(\"Native protocol supported versions: {} (default: {})\"",
        "registerMBeans();",
        "prepareToJoin();",
        "joinTokenRing(schemaTimeoutMillis, ringTimeoutMillis);",
        "doAuthSetup(true);",
        "completeInitialization();",
        "public void setRpcReady(boolean value)",
        "Gossiper.instance.addLocalApplicationState(ApplicationState.RPC_READY, valueFactory.rpcReady(value));",
        "public boolean authSetupCalled()",
    ),
    NATIVE_TRANSPORT_SERVICE: (
        "public class NativeTransportService",
        "synchronized void initialize()",
        "servers.forEach(Server::start);",
        "servers.forEach((s) -> s.stop(force));",
        "public boolean isRunning()",
        "ClientMetrics.instance.init(servers);",
    ),
    DEFAULT_FS_ERROR_HANDLER: (
        "public class DefaultFSErrorHandler implements FSErrorHandler",
        "if (!StorageService.instance.isDaemonSetupCompleted())",
        "handleStartupFSError(e);",
        "handleStartupFSError(Throwable t)",
        "Exiting forcefully due to file system exception on startup",
        "JVMStabilityInspector.killCurrentJVM(t, true);",
        "StorageService.instance.stopTransports();",
    ),
    JVM_STABILITY_INSPECTOR: (
        "private static void inspectCommitLogError(Throwable t)",
        "if (!StorageService.instance.isDaemonSetupCompleted())",
        "logger.error(\"Exiting due to error while processing commit log during initialization.\", t);",
        "killer.killCurrentJVM(t, true);",
        "DatabaseDescriptor.getCommitFailurePolicy() == Config.CommitFailurePolicy.die",
    ),
    CONFIG: (
        "public boolean start_native_transport = true;",
        "public int block_for_peers_timeout_in_secs = 10;",
        "public boolean block_for_peers_in_remote_dcs = false;",
        "public boolean autocompaction_on_startup_enabled",
        "public CommitFailurePolicy commit_failure_policy",
        "public DiskFailurePolicy disk_failure_policy",
    ),
    CASSANDRA_YAML: (
        "start_native_transport: true",
    ),
}

TEST_TOKEN_CHECKS = {
    BOOTSTRAP_TEST: (
        "public void bootstrapJMXStatus()",
        "assertEquals(\"IN_PROGRESS\", StorageService.instance.getBootstrapState());",
        "public void testStorageServiceMBeanIsPublishedOnJMXDuringBootstrap()",
        "JMX.newMBeanProxy(mbsc, new ObjectName(\"org.apache.cassandra.db:type=StorageService\"), StorageServiceMBean.class);",
        "assertEquals(sp.getOperationMode(), StorageService.Mode.JOINING.toString());",
    ),
    BOOTSTRAP_BINARY_DISABLED_TEST: (
        "public class BootstrapBinaryDisabledTest",
        "Not starting client transports in write_survey mode as it's bootstrapping or auth is enabled",
        "Node is not yet bootstrapped completely",
        "node.nodetoolResult(\"bootstrap\", \"resume\").asserts().success();",
        "node.logs().watchFor(\"Starting listening for CQL clients\");",
    ),
    AUTH_TEST: (
        "public void authSetupIsCalledAfterStartup()",
        "StorageService.instance.authSetupCalled()",
    ),
    NODETOOL_ENABLE_DISABLE_BINARY_TEST: (
        "public void testEnableDisableBinary()",
        "ToolRunner.invokeNodetoolJvmDtest(cluster.get(1), \"disablebinary\")",
        "containsIgnoringCase(\"Stop listening for CQL clients\")",
        "ToolRunner.invokeNodetoolJvmDtest(cluster.get(1), \"enablebinary\")",
        "containsIgnoringCase(\"Starting listening for CQL clients\")",
        "assertTrue(canConnect());",
        "assertFalse(canConnect());",
    ),
    DISABLE_BINARY_TEST: (
        "CassandraDaemon.getInstanceForTesting().nativeTransportService().isRunning()",
        "Should have thrown OverloadedException",
    ),
    DEFAULT_FS_ERROR_HANDLER_TEST: (
        "public class DefaultFSErrorHandlerTest",
        "daemon.completeSetup(); //startup must be completed, otherwise FS error will kill JVM regardless of failure policy",
        "StorageService.instance.registerDaemon(daemon);",
        "public void testFSErrors()",
        "public void testCorruptSSTableException()",
    ),
    DISK_FAILURE_POLICY_TEST: (
        "public class DiskFailurePolicyTest",
        "boolean isStartUpInProgress",
        "daemon.completeSetup(); //mark startup completed",
        "expectJVMKilledQuiet",
    ),
    COMMITLOG_FAILURE_POLICY_TEST: (
        "public class CommitLogFailurePolicyTest",
        "testCommitFailurePolicy_stop",
        "testCommitFailurePolicy_die",
        "testCommitFailurePolicy_ignore_beforeStartup",
        "startup was not completed successfuly",
        "Assert.assertTrue(killerForTests.wasKilledQuietly());",
        "testCommitFailurePolicy_ignore_afterStartup",
    ),
    NATIVE_TRANSPORT_SERVICE_TEST: (
        "public void testServiceCanBeStopped()",
        "public void testIgnoresStartOnAlreadyStarted()",
        "public void testConcurrentStarts()",
        "public void testPlainDefaultPort()",
        "public void testSSLOptional()",
        "public void testSSLPortWithOptionalEncryption()",
    ),
}

DOC_TOKEN_CHECKS = {
    "research/module-startup-cold-start-integration-matrix.md": (
        *SCENARIO_IDS,
        CASSANDRA_DAEMON,
        STORAGE_SERVICE,
        DEFAULT_FS_ERROR_HANDLER,
        JVM_STABILITY_INSPECTOR,
        BOOTSTRAP_BINARY_DISABLED_TEST,
        BOOTSTRAP_TEST,
        "gap still open",
    ),
    "research/module-startup-cold-integration-drift-checker.md": (
        *SCENARIO_IDS,
        "python3 research/tools/check-startup-cold-integration-drift.py",
        "gap still open",
    ),
    "research/module-startup-daemon-deep-dive.md": (
        "module-startup-cold-start-integration-matrix.md",
        "check-startup-cold-integration-drift.py",
    ),
    "research/README.md": (
        "module-startup-cold-start-integration-matrix.md",
        "module-startup-cold-integration-drift-checker.md",
        "research/tools/check-startup-cold-integration-drift.py",
        "Startup | 第四轮源码侧完成",
        "startup_cold_log_marker_gap",
    ),
    "research/notes/source-map.md": (
        "Startup cold-start integration",
        "research/tools/check-startup-cold-integration-drift.py",
        "startup_cold_jmx_early_bootstrap",
        "test/distributed/org/apache/cassandra/distributed/test/ring/BootstrapTest.java",
        "test/unit/org/apache/cassandra/db/commitlog/CommitLogFailurePolicyTest.java",
    ),
}

FULL_COLD_START_GAP_TOKENS = (
    "startup_cold_log_marker",
    "cold-start log marker",
    "Startup complete",
    "StorageServiceMBean",
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


def check_full_log_marker_gap(results):
    matches = []
    for root in ("test/unit", "test/distributed"):
        for path in (REPO_ROOT / root).rglob("*.java"):
            content = path.read_text(encoding="utf-8", errors="ignore")
            if all(token in content for token in FULL_COLD_START_GAP_TOKENS):
                matches.append(str(path.relative_to(REPO_ROOT)))

    if matches:
        add_result(results, "FAIL", "gap still open", "startup cold log marker E2E", "possible full marker test found: " + ", ".join(matches[:20]))
    else:
        add_result(results, "PASS", "gap still open", "startup cold log marker E2E", "no full ordered cold-start marker test found")


def run_checks():
    results = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        check_tokens(results, "source token contract", path, tokens)
    for path, tokens in TEST_TOKEN_CHECKS.items():
        check_tokens(results, "test token contract", path, tokens)
    for path, tokens in DOC_TOKEN_CHECKS.items():
        check_tokens(results, "doc token contract", path, tokens)
    check_full_log_marker_gap(results)
    return results


def as_json(results):
    return {
        "total": len(results),
        "passed": sum(1 for result in results if result.status == "PASS"),
        "failed": [result.__dict__ for result in results if result.status == "FAIL"],
    }


def main():
    parser = argparse.ArgumentParser(description="Check Startup cold-start integration research drift.")
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
        print(f"All {len(results)} Startup cold-start integration drift checks passed")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
