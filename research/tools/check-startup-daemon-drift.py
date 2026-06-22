#!/usr/bin/env python3
#
# Source-only drift check for Startup daemon research coverage.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

CASSANDRA_DAEMON = "src/java/org/apache/cassandra/service/CassandraDaemon.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
STARTUP_CHECKS = "src/java/org/apache/cassandra/service/StartupChecks.java"
STARTUP_CHECKS_OPTIONS = "src/java/org/apache/cassandra/config/StartupChecksOptions.java"
FILE_SYSTEM_OWNERSHIP_CHECK = "src/java/org/apache/cassandra/service/FileSystemOwnershipCheck.java"
DATA_RESURRECTION_CHECK = "src/java/org/apache/cassandra/service/DataResurrectionCheck.java"
STARTUP_CLUSTER_CONNECTIVITY_CHECKER = "src/java/org/apache/cassandra/net/StartupClusterConnectivityChecker.java"
NATIVE_TRANSPORT_SERVICE = "src/java/org/apache/cassandra/service/NativeTransportService.java"
STORAGE_SERVICE = "src/java/org/apache/cassandra/service/StorageService.java"
ENABLE_BINARY = "src/java/org/apache/cassandra/tools/nodetool/EnableBinary.java"
DISABLE_BINARY = "src/java/org/apache/cassandra/tools/nodetool/DisableBinary.java"
CASSANDRA_YAML = "conf/cassandra.yaml"

STARTUP_CHECKS_TEST = "test/unit/org/apache/cassandra/service/StartupChecksTest.java"
STARTUP_CHECK_OPTIONS_TEST = "test/unit/org/apache/cassandra/config/StartupCheckOptionsTest.java"
ABSTRACT_FILESYSTEM_OWNERSHIP_CHECK_TEST = "test/unit/org/apache/cassandra/service/AbstractFilesystemOwnershipCheckTest.java"
SYSTEM_PROPERTIES_FILESYSTEM_OWNERSHIP_CHECK_TEST = "test/unit/org/apache/cassandra/service/SystemPropertiesBasedFileSystemOwnershipCheckTest.java"
YAML_FILESYSTEM_OWNERSHIP_CHECK_TEST = "test/unit/org/apache/cassandra/service/YamlBasedFileSystemOwnershipCheckTest.java"
DATA_RESURRECTION_CHECK_TEST = "test/distributed/org/apache/cassandra/distributed/test/DataResurrectionCheckTest.java"
STARTUP_CLUSTER_CONNECTIVITY_CHECKER_TEST = "test/unit/org/apache/cassandra/net/StartupClusterConnectivityCheckerTest.java"
NATIVE_TRANSPORT_SERVICE_TEST = "test/unit/org/apache/cassandra/service/NativeTransportServiceTest.java"
BOOTSTRAP_BINARY_DISABLED_TEST = "test/distributed/org/apache/cassandra/distributed/test/BootstrapBinaryDisabledTest.java"
NODETOOL_ENABLE_DISABLE_BINARY_TEST = "test/distributed/org/apache/cassandra/distributed/test/NodeToolEnableDisableBinaryTest.java"
DATABASE_DESCRIPTOR_TEST = "test/unit/org/apache/cassandra/config/DatabaseDescriptorTest.java"
NATIVE_TRANSPORT_ENCRYPTION_OPTIONS_TEST = "test/distributed/org/apache/cassandra/distributed/test/NativeTransportEncryptionOptionsTest.java"

TARGET_DOCS = (
    "research/module-startup-daemon-deep-dive.md",
    "research/module-startup-daemon-drift-checker.md",
    "research/module-startup-bootstrap.md",
    "research/flow-bootstrap.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "startup_daemon_lifecycle_order",
    "startup_config_initialization_modes",
    "startup_checks_default_preflight",
    "startup_check_options_gate",
    "startup_filesystem_ownership_gate",
    "startup_data_resurrection_gate",
    "startup_native_transport_gate",
    "startup_native_transport_tls_dual_port",
    "startup_block_for_peers_gate",
    "startup_existing_tests_baseline",
)

DEFAULT_STARTUP_CHECK_TOKENS = (
    "checkKernelBug1057843",
    "checkJemalloc",
    "checkLz4Native",
    "checkValidLaunchDate",
    "checkJMXPorts",
    "checkJMXProperties",
    "inspectJvmOptions",
    "checkNativeLibraryInitialization",
    "initSigarLibrary",
    "checkMaxMapCount",
    "checkReadAheadKbSetting",
    "checkDataDirs",
    "checkSSTablesFormat",
    "checkSystemKeyspaceState",
    "checkDatacenter",
    "checkRack",
    "checkLegacyAuthTables",
    "new DataResurrectionCheck()",
)

SOURCE_TOKEN_CHECKS = {
    CASSANDRA_DAEMON: (
        "this.startupChecks = new StartupChecks().withDefaultTests().withTest(new FileSystemOwnershipCheck());",
        "CommitLog.instance.start();",
        "runStartupChecks();",
        "SystemKeyspace.snapshotOnVersionChange();",
        "SystemKeyspace.persistLocalMetadata();",
        "Schema.instance.loadFromDisk();",
        "setupVirtualKeyspaces();",
        "loadRowAndKeyCacheAsync().get();",
        "CommitLog.instance.recoverSegmentsOnDisk();",
        "StorageService.instance.initServer();",
        "StorageService.instance.doAuthSetup(false);",
        "initializeClientTransports();",
        "AuthCacheService.instance.warmCaches();",
        "PaxosState.startAutoRepairs();",
        "completeSetup();",
        "StartupClusterConnectivityChecker.create(DatabaseDescriptor.getBlockForPeersTimeoutInSeconds(),",
        "connectivityChecker.execute(Gossiper.instance.getEndpoints(), DatabaseDescriptor.getEndpointSnitch()::getDatacenter);",
        "validateTransportsCanStart();",
        "if (START_NATIVE_TRANSPORT.getBoolean() || (nativeFlag == null && DatabaseDescriptor.startNativeTransport()))",
        "if (!SystemKeyspace.bootstrapComplete())",
        "nativeTransportService.start();",
        "StorageService.instance.setRpcReady(true);",
    ),
    DATABASE_DESCRIPTOR: (
        "public static void daemonInitialization(Supplier<Config> config) throws ConfigurationException",
        "throw new AssertionError(\"toolInitialization() already called\");",
        "throw new AssertionError(\"clientInitialization() already called\");",
        "setConfig(config.get());",
        "applyAll();",
        "AuthConfig.applyAuth();",
        "public static void toolInitialization(boolean failIfDaemonOrClient)",
        "applyCompatibilityMode();",
        "applySimpleConfig();",
        "applySnitch();",
        "public static void clientInitialization(boolean failIfDaemonOrTool, Supplier<Config> configSupplier)",
        "Config.setClientMode(true);",
        "private static void applyAll() throws ConfigurationException",
        "applyStartupChecks();",
        "startupChecksOptions = new StartupChecksOptions(conf.startup_checks);",
        "public static boolean startNativeTransport()",
        "return conf.start_native_transport;",
        "return conf.block_for_peers_in_remote_dcs;",
        "return conf.block_for_peers_timeout_in_secs;",
        "return conf.autocompaction_on_startup_enabled;",
        "Encryption must be enabled in client_encryption_options for native_transport_port_ssl",
    ),
    CONFIG: (
        "public boolean start_native_transport = true;",
        "public int native_transport_port = 9042;",
        "public Integer native_transport_port_ssl = null;",
        "public int block_for_peers_timeout_in_secs = 10;",
        "public boolean block_for_peers_in_remote_dcs = false;",
        "public boolean autocompaction_on_startup_enabled = AUTOCOMPACTION_ON_STARTUP_ENABLED.getBoolean();",
        "public volatile Map<StartupCheckType, Map<String, Object>> startup_checks = new HashMap<>();",
    ),
    STARTUP_CHECKS: DEFAULT_STARTUP_CHECK_TOKENS + (
        "public enum StartupCheckType",
        "non_configurable_check",
        "check_filesystem_ownership(true)",
        "check_dc",
        "check_rack",
        "check_data_resurrection(true)",
        "public void verify(StartupChecksOptions options) throws StartupException",
        "test.execute(options);",
        "test.postAction(options);",
        "public static final StartupCheck checkDataDirs",
        "Directories.verifyFullPermissions(dir, dataDir)",
        "public static final StartupCheck checkSSTablesFormat",
        "Detected unreadable sstables",
        "UUID sstable identifiers are disabled",
        "public static final StartupCheck checkSystemKeyspaceState",
        "SystemKeyspace.checkHealth();",
        "public static final StartupCheck checkDatacenter",
        "Cannot start node if snitch's data center",
        "public static final StartupCheck checkRack",
        "Cannot start node if snitch's rack",
    ),
    STARTUP_CHECKS_OPTIONS: (
        "public static final String ENABLED_PROPERTY = \"enabled\";",
        "private final Map<StartupCheckType, Map<String, Object>> options = new EnumMap<>(StartupCheckType.class);",
        "public void set(final StartupCheckType startupCheckType, final String key, final Object value)",
        "if (startupCheckType != non_configurable_check)",
        "public void enable(final StartupCheckType startupCheckType)",
        "public void disable(final StartupCheckType startupCheckType)",
        "else if (startupCheckType.disabledByDefault)",
        "options.get(non_configurable_check).clear();",
        "options.get(non_configurable_check).put(ENABLED_PROPERTY, TRUE);",
    ),
    FILE_SYSTEM_OWNERSHIP_CHECK: (
        "public static final String FILE_SYSTEM_CHECK_OWNERSHIP_TOKEN = \"CassandraOwnershipToken\";",
        "public static final String DEFAULT_FS_OWNERSHIP_FILENAME = \".cassandra_fs_ownership\";",
        "return check_filesystem_ownership;",
        "public void execute(StartupChecksOptions options) throws StartupException",
        "foundPerTargetDir.containsValue(0)",
        "MULTIPLE_OWNERSHIP_FILES",
        "INCONSISTENT_FILES_FOUND",
        "int version = getIntProperty(fromDisk, VERSION);",
        "if (volumeCount != foundProperties.size())",
        "if (!expectedToken.equals(token))",
        "public boolean isEnabled(StartupChecksOptions options)",
        "FILE_SYSTEM_CHECK_ENABLE.getBoolean(enabledFromYaml)",
        "public String getFsOwnershipFilename(Map<String, Object> config)",
        "public String getOwnershipToken(Map<String, Object> config)",
    ),
    DATA_RESURRECTION_CHECK: (
        "public static final String HEARTBEAT_FILE_CONFIG_PROPERTY = \"heartbeat_file\";",
        "public static final String EXCLUDED_KEYSPACES_CONFIG_PROPERTY = \"excluded_keyspaces\";",
        "public static final String EXCLUDED_TABLES_CONFIG_PROPERTY = \"excluded_tables\";",
        "public static final String DEFAULT_HEARTBEAT_FILE = \"cassandra-heartbeat\";",
        "@JsonProperty(\"last_heartbeat\")",
        "public void execute(StartupChecksOptions options) throws StartupException",
        "if (options.isDisabled(getStartupCheckType()))",
        "Heartbeat.deserializeFromJsonFile(heartbeatFile)",
        "Instant lastModified = Instant.ofEpochMilli(heartbeatFile.lastModified());",
        "long gcGraceMillis = ((long) userTable.gcPeriod) * 1000;",
        "Invalid tables: %s",
        "public void postAction(StartupChecksOptions options)",
        "ScheduledExecutors.scheduledTasks.scheduleAtFixedRate",
        "CHECK_DATA_RESURRECTION_HEARTBEAT_PERIOD",
    ),
    STARTUP_CLUSTER_CONNECTIVITY_CHECKER: (
        "public static StartupClusterConnectivityChecker create(long timeoutSecs, boolean blockForRemoteDcs)",
        "if (peers == null || this.timeoutNanos < 0)",
        "datacenterToPeers.keySet().retainAll(Collections.singleton(localDc));",
        "AckMap acks = new AckMap(3, peers);",
        "Gossiper.instance.register(listener);",
        "sendPingMessages(peers, dcToRemainingPeers, acks, peerToDatacenter::get);",
        "Gossiper.instance.unregister(listener);",
        "Timed out after",
        "Message<PingRequest> small = Message.out(PING_REQ, PingRequest.forSmall);",
        "Message<PingRequest> large = Message.out(PING_REQ, PingRequest.forLarge);",
        "MessagingService.instance().sendWithCallback(small, peer, responseHandler, SMALL_MESSAGES);",
        "MessagingService.instance().sendWithCallback(large, peer, responseHandler, LARGE_MESSAGES);",
    ),
    NATIVE_TRANSPORT_SERVICE: (
        "public class NativeTransportService",
        "synchronized void initialize()",
        "if (useEpoll())",
        "workerGroup = new EpollEventLoopGroup();",
        "workerGroup = new NioEventLoopGroup();",
        "int nativePort = DatabaseDescriptor.getNativeTransportPort();",
        "int nativePortSSL = DatabaseDescriptor.getNativeTransportPortSSL();",
        "EncryptionOptions.TlsEncryptionPolicy encryptionPolicy = DatabaseDescriptor.getNativeProtocolEncryptionOptions().tlsEncryptionPolicy();",
        "regularPortServer = builder.withTlsEncryptionPolicy(EncryptionOptions.TlsEncryptionPolicy.UNENCRYPTED).withPort(nativePort).build();",
        "tlsPortServer = builder.withTlsEncryptionPolicy(encryptionPolicy).withPort(nativePortSSL).build();",
        "ClientMetrics.instance.init(servers);",
        "servers.forEach(Server::start);",
        "servers.forEach((s) -> s.stop(force));",
        "Dispatcher.shutdown();",
    ),
    STORAGE_SERVICE: (
        "public void registerDaemon(CassandraDaemon daemon)",
        "public synchronized void startNativeTransport()",
        "checkServiceAllowedToStart(\"native transport\");",
        "daemon.startNativeTransport();",
        "public void stopNativeTransport(boolean force)",
        "daemon.stopNativeTransport(force);",
        "public synchronized void initServer(int schemaTimeoutMillis, int ringTimeoutMillis) throws ConfigurationException",
        "logger.info(\"Native protocol supported versions: {} (default: {})\"",
        "registerMBeans();",
        "prepareToJoin();",
        "joinTokenRing(schemaTimeoutMillis, ringTimeoutMillis);",
        "completeInitialization();",
    ),
    ENABLE_BINARY: (
        "@Command(name = \"enablebinary\", description = \"Reenable native transport (binary protocol)\")",
        "probe.startNativeTransport();",
    ),
    DISABLE_BINARY: (
        "@Command(name = \"disablebinary\", description = \"Disable native transport (binary protocol)\")",
        "@Option(title = \"force\", name = { \"-f\", \"--force\"}",
        "probe.stopNativeTransport(force);",
    ),
    CASSANDRA_YAML: (
        "start_native_transport: true",
        "native_transport_port: 9042",
        "native_transport_port_ssl: 9142",
        "#startup_checks:",
        "#  check_filesystem_ownership:",
        "#    ownership_token:",
        "#  check_dc:",
        "#  check_rack:",
        "#  check_data_resurrection:",
        "#    heartbeat_file:",
        "#    excluded_keyspaces:",
        "#    excluded_tables:",
    ),
}

TEST_TOKEN_CHECKS = {
    STARTUP_CHECKS_TEST: (
        "public void failStartupIfInvalidSSTablesFound()",
        "Detected unreadable sstables",
        "public void checkReadAheadKbSettingCheck()",
        "public void testGetReadAheadKBPath()",
        "public void maxMapCountCheck()",
        "public void testDataResurrectionCheck()",
        "Invalid tables: abc.def",
        "public void testDataResurrectionCheckLastModifiedFallback()",
        "public void testKernelBug1057843Check()",
        "testKernelBug1057843Check(\"ext4\", DiskAccessMode.direct, new Semver(\"6.1.64.1-generic\"), true);",
    ),
    STARTUP_CHECK_OPTIONS_TEST: (
        "public void testStartupOptionsConfigApplication()",
        "public void testNoOptions()",
        "public void testEmptyDisabledValues()",
        "public void testChecksDisabledByDefaultAreNotEnabled()",
        "public void testExcludedKeyspacesInDataResurrectionCheckOptions()",
        "public void testExcludedTablesInDataResurrectionCheckOptions()",
    ),
    ABSTRACT_FILESYSTEM_OWNERSHIP_CHECK_TEST: (
        "public void skipCheckDisabledIfSystemPropertyIsEmpty()",
        "public void skipCheckDisabledIfSystemPropertyIsFalseButOptionsEnabled()",
        "public void checkEnabledButClusterPropertyIsEmpty()",
        "public void noRootDirectoryPresent()",
        "public void noDirectoryStructureOrTokenFilePresent()",
        "public void multipleFilesFoundInSameTree()",
    ),
    SYSTEM_PROPERTIES_FILESYSTEM_OWNERSHIP_CHECK_TEST: (
        "public class SystemPropertiesBasedFileSystemOwnershipCheckTest extends AbstractFilesystemOwnershipCheckTest",
        "FILE_SYSTEM_CHECK_OWNERSHIP_TOKEN",
        "FILE_SYSTEM_CHECK_ENABLE",
    ),
    YAML_FILESYSTEM_OWNERSHIP_CHECK_TEST: (
        "public class YamlBasedFileSystemOwnershipCheckTest extends AbstractFilesystemOwnershipCheckTest",
        "options.getConfig(check_filesystem_ownership).put(ENABLED_PROPERTY, \"true\");",
        "options.getConfig(check_filesystem_ownership).put(\"ownership_token\", token);",
    ),
    DATA_RESURRECTION_CHECK_TEST: (
        "public void testDataResurrectionCheck()",
        ".set(\"startup_checks\",",
        "checkHeartbeat(instance);",
        "CREATE TABLE %s.tb1 (pk text PRIMARY KEY) WITH gc_grace_seconds = 10",
        "Invalid tables",
        "EXCLUDED_KEYSPACES_CONFIG_PROPERTY",
        "EXCLUDED_TABLES_CONFIG_PROPERTY",
        "DEFAULT_HEARTBEAT_FILE",
    ),
    STARTUP_CLUSTER_CONNECTIVITY_CHECKER_TEST: (
        "localQuorumConnectivityChecker = new StartupClusterConnectivityChecker(TIMEOUT_NANOS, false);",
        "globalQuorumConnectivityChecker = new StartupClusterConnectivityChecker(TIMEOUT_NANOS, true);",
        "noopChecker = new StartupClusterConnectivityChecker(-1, false);",
        "zeroWaitChecker = new StartupClusterConnectivityChecker(0, false);",
        "public void execute_HappyPath()",
        "public void execute_NotAlive()",
        "public void execute_NoConnectionsAcks()",
        "public void execute_LocalQuorum()",
        "public void execute_GlobalQuorum()",
        "public void execute_Noop()",
        "public void execute_ZeroWaitHasConnections()",
    ),
    NATIVE_TRANSPORT_SERVICE_TEST: (
        "public void testServiceCanBeStopped()",
        "public void testIgnoresStartOnAlreadyStarted()",
        "public void testDestroy()",
        "public void testConcurrentStarts()",
        "public void testPlainDefaultPort()",
        "public void testSSLOnly()",
        "public void testSSLOptional()",
        "public void testSSLPortWithOptionalEncryption()",
        "public void testSSLPortWithDisabledEncryption()",
        "public void testSSLPortWithEnabledSSL()",
    ),
    BOOTSTRAP_BINARY_DISABLED_TEST: (
        "public class BootstrapBinaryDisabledTest extends TestBaseImpl",
        "config.put(\"authenticator\", \"org.apache.cassandra.auth.PasswordAuthenticator\");",
        "assertLogHas(node, isWriteSurvey ?",
        "Not starting client transports in write_survey mode as it's bootstrapping or auth is enabled",
        "Node is not yet bootstrapped completely",
        "node.nodetoolResult(\"bootstrap\", \"resume\").asserts().success();",
        "node.logs().watchFor(\"Starting listening for CQL clients\");",
    ),
    NODETOOL_ENABLE_DISABLE_BINARY_TEST: (
        "public void testMaybeChangeDocs()",
        "nodetool disablebinary - Disable native transport (binary protocol)",
        "nodetool enablebinary - Reenable native transport (binary protocol)",
        "public void testEnableDisableBinary()",
        "ToolRunner.invokeNodetoolJvmDtest(cluster.get(1), \"disablebinary\")",
        "ToolRunner.invokeNodetoolJvmDtest(cluster.get(1), \"enablebinary\")",
        "assertFalse(canConnect());",
        "assertTrue(canConnect());",
    ),
    DATABASE_DESCRIPTOR_TEST: (
        "public void testConfigurationLoader() throws Exception",
        "CONFIG_LOADER.setString(testLoader.getClass().getName());",
        "ConfigurationLoader Test",
    ),
    NATIVE_TRANSPORT_ENCRYPTION_OPTIONS_TEST: (
        "native_transport_port_ssl",
        "client_encryption_options",
        "TLS native connection should be possible",
    ),
}

DOC_REQUIRED_TOKENS = (
    "CassandraDaemon",
    "DatabaseDescriptor",
    "StartupChecks",
    "StartupChecksOptions",
    "FileSystemOwnershipCheck",
    "DataResurrectionCheck",
    "StartupClusterConnectivityChecker",
    "NativeTransportService",
    "StorageService",
    "start_native_transport",
    "native_transport_port_ssl",
    "block_for_peers_timeout_in_secs",
    "block_for_peers_in_remote_dcs",
    "startup_checks",
    "check_filesystem_ownership",
    "check_data_resurrection",
    "autocompaction_on_startup_enabled",
    "StartupChecksTest",
    "StartupCheckOptionsTest",
    "NativeTransportServiceTest",
    "BootstrapBinaryDisabledTest",
    "NodeToolEnableDisableBinaryTest",
    "StartupClusterConnectivityCheckerTest",
    "DataResurrectionCheckTest",
    "AbstractFilesystemOwnershipCheckTest",
    "Startup 第二轮",
    "cold-start integration",
) + DEFAULT_STARTUP_CHECK_TOKENS + tuple(SOURCE_TOKEN_CHECKS.keys()) + tuple(TEST_TOKEN_CHECKS.keys()) + SCENARIO_IDS


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
        checks.append(Check(f"source token contract {path}", path, all(token in text for token in tokens)))
    for path, tokens in TEST_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(Check(f"test token contract {path}", path, all(token in text for token in tokens)))
    return checks


def doc_checks() -> list[Check]:
    docs = {path: read(path) for path in TARGET_DOCS}
    combined = "\n".join(docs.values())
    checks = [Check(f"target doc exists {path}", path, bool(text.strip())) for path, text in docs.items()]
    checks.extend(Check(f"doc token {token}", "research", token in combined) for token in DOC_REQUIRED_TOKENS)

    matrix = docs["research/module-startup-daemon-deep-dive.md"]
    drift_doc = docs["research/module-startup-daemon-drift-checker.md"]
    for scenario in SCENARIO_IDS:
        checks.append(Check(f"scenario coverage {scenario}", "research", scenario in matrix and scenario in drift_doc))

    return checks


def run_checks() -> list[Check]:
    return source_checks() + doc_checks()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Startup daemon research drift.")
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
            print("FAIL Startup daemon drift check")
            for failure in failures:
                print(f"- {failure.name} ({failure.source})")
        else:
            print(f"OK Startup daemon drift check: {len(checks)} checks")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
