#!/usr/bin/env python3
#
# Source/test/doc drift check for Cassandra testing runtime harness research.

import argparse
import glob
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

CQL_TESTER = "test/unit/org/apache/cassandra/cql3/CQLTester.java"
SERVER_TEST_UTILS = "test/unit/org/apache/cassandra/ServerTestUtils.java"
SCHEMA_LOADER = "test/unit/org/apache/cassandra/SchemaLoader.java"
BUILD_XML = "build.xml"
CLUSTER = "test/distributed/org/apache/cassandra/distributed/Cluster.java"
UPGRADEABLE_CLUSTER = "test/distributed/org/apache/cassandra/distributed/UpgradeableCluster.java"
ABSTRACT_CLUSTER = "test/distributed/org/apache/cassandra/distributed/impl/AbstractCluster.java"
INSTANCE = "test/distributed/org/apache/cassandra/distributed/impl/Instance.java"
INSTANCE_CONFIG = "test/distributed/org/apache/cassandra/distributed/impl/InstanceConfig.java"
ISOLATED_EXECUTOR = "test/distributed/org/apache/cassandra/distributed/impl/IsolatedExecutor.java"
COORDINATOR = "test/distributed/org/apache/cassandra/distributed/impl/Coordinator.java"
ICOORDINATOR = "test/distributed/org/apache/cassandra/distributed/api/ICoordinator.java"
MESSAGE_FILTERS = "test/distributed/org/apache/cassandra/distributed/impl/MessageFilters.java"
INTERNAL_NODE_PROBE = "test/distributed/org/apache/cassandra/distributed/mock/nodetool/InternalNodeProbe.java"
UPGRADE_TEST_BASE = "test/distributed/org/apache/cassandra/distributed/upgrade/UpgradeTestBase.java"
BYTEMAN = "test/distributed/org/apache/cassandra/distributed/shared/Byteman.java"

TEST_BASE_IMPL = "test/distributed/org/apache/cassandra/distributed/test/TestBaseImpl.java"
ABSTRACT_CLUSTER_TEST = "test/distributed/org/apache/cassandra/distributed/impl/AbstractClusterTest.java"
JVM_DTEST_TEST = "test/distributed/org/apache/cassandra/distributed/test/JVMDTestTest.java"
NATIVE_PROTOCOL_TEST = "test/distributed/org/apache/cassandra/distributed/test/NativeProtocolTest.java"
HINTED_HANDOFF_NODETOOL_TEST = "test/distributed/org/apache/cassandra/distributed/test/HintedHandoffNodetoolTest.java"
TRIVIAL_SIMULATION_TEST = "test/simulator/test/org/apache/cassandra/simulator/test/TrivialSimulationTest.java"
SHORT_PAXOS_SIMULATION_TEST = "test/simulator/test/org/apache/cassandra/simulator/test/ShortPaxosSimulationTest.java"
MONITOR_TRANSFORMER_TEST = "test/simulator/test/org/apache/cassandra/simulator/test/MonitorMethodTransformerTest.java"
SIMULATION_TEST_BASE = "test/simulator/test/org/apache/cassandra/simulator/test/SimulationTestBase.java"
COMPACTIONS_BYTEMAN_TEST = "test/unit/org/apache/cassandra/db/compaction/CompactionsBytemanTest.java"
DIRECT_IO_BYTEMAN_TEST = "test/unit/org/apache/cassandra/db/commitlog/DirectIOSegmentBytemanTest.java"
STREAM_FAILURE_BTM = "test/resources/byteman/stream_failure.btm"

SIMULATION_RUNNER = "test/simulator/main/org/apache/cassandra/simulator/SimulationRunner.java"
CLUSTER_SIMULATION = "test/simulator/main/org/apache/cassandra/simulator/ClusterSimulation.java"
ACTION_PLAN = "test/simulator/main/org/apache/cassandra/simulator/ActionPlan.java"
ACTION_SCHEDULE = "test/simulator/main/org/apache/cassandra/simulator/ActionSchedule.java"
SIMULATED_MESSAGE_DELIVERY = "test/simulator/main/org/apache/cassandra/simulator/systems/SimulatedMessageDelivery.java"
PAXOS_SIMULATION_RUNNER = "test/simulator/main/org/apache/cassandra/simulator/paxos/PaxosSimulationRunner.java"
HISTORY_CHECKER = "test/simulator/main/org/apache/cassandra/simulator/paxos/HistoryChecker.java"

PARENT_POM = ".build/parent-pom-template.xml"
BUILD_DEPS = ".build/cassandra-build-deps-template.xml"

TARGET_DOCS = (
    "research/module-testing-framework.md",
    "research/module-testing-internals.md",
    "research/module-testing-simulator-ci.md",
    "research/module-testing-runtime-harness-matrix.md",
    "research/module-testing-runtime-harness-drift-checker.md",
    "research/module-testing-ci-generator-matrix.md",
    "research/flow-test-execution.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "testing_unit_cql_internal_harness",
    "testing_cql_native_protocol_harness",
    "testing_schema_loader_server_prepare",
    "testing_injvm_cluster_lifecycle",
    "testing_injvm_instance_isolation",
    "testing_injvm_schema_query_harness",
    "testing_injvm_message_filter_faults",
    "testing_injvm_nodetool_probe",
    "testing_upgrade_dtest_lifecycle",
    "testing_simulator_agent_schedule",
    "testing_byteman_fault_injection",
    "testing_ant_runner_targets",
    "testing_dtest_api_artifact_boundary",
)

SOURCE_TOKEN_CHECKS = {
    CQL_TESTER: (
        "public abstract class CQLTester",
        "public static void setUpClass()",
        "public void beforeTest() throws Throwable",
        "public void afterTest() throws Throwable",
        "protected static void requireNetwork() throws ConfigurationException",
        "private static void startServices()",
        "private static void startServer(Consumer<Server.Builder> decorator)",
        "protected static ResultMessage schemaChange(String query)",
        "protected com.datastax.driver.core.ResultSet executeNet(ProtocolVersion protocolVersion, ConsistencyLevel consistency, String query)",
        "protected Session sessionNet(ProtocolVersion protocolVersion)",
        "public UntypedResultSet executeFormattedQuery(String query, Object... values)",
        "public static abstract class InMemory extends CQLTester",
    ),
    SERVER_TEST_UTILS: (
        "public static void daemonInitialization()",
        "DatabaseDescriptor.daemonInitialization();",
        "public static void prepareServer()",
    ),
    SCHEMA_LOADER: (
        "public static void loadSchema() throws ConfigurationException",
        "prepareServer();",
        "startGossiper();",
        "public static void startGossiper()",
        "ALLOW_UNSAFE_JOIN.setBoolean(true);",
    ),
    BUILD_XML: (
        '<macrodef name="testmacrohelper">',
        '<taskdef name="junit-timeout"',
        '<junit-timeout fork="on"',
        '<target name="test" depends="maybe-build-test" description="Test Runner">',
        '<target name="dtest-jar" depends="build-test, build" description="Create dtest-compatible jar, including all dependencies">',
        "dtest-api-*.jar",
        '<target name="test-jvm-dtest" depends="maybe-build-test" description="Execute in-jvm dtests">',
        '<target name="test-jvm-dtest-latest" depends="maybe-build-test" description="Execute in-jvm dtests with latest configuration">',
        '<target name="test-simulator-dtest" depends="maybe-build-test" description="Execute simulator dtests">',
        '-Dcassandra.test.simulator.determinismcheck=strict',
        '<target name="test-jvm-upgrade-dtest" depends="maybe-build-test" description="Execute in-jvm dtests">',
    ),
    CLUSTER: (
        "public class Cluster extends AbstractCluster<IInvokableInstance>",
        "protected IInvokableInstance newInstanceWrapper(Versions.Version version, IInstanceConfig config)",
        "public static Builder build()",
        "public static Cluster create(int nodeCount) throws Throwable",
        "withVersion(CURRENT_VERSION);",
    ),
    UPGRADEABLE_CLUSTER: (
        "public class UpgradeableCluster extends AbstractCluster<IUpgradeableInstance> implements AutoCloseable",
        "config.set(Constants.KEY_DTEST_API_CONFIG_CHECK, false);",
        "public static Builder build()",
        "public static UpgradeableCluster create(int nodeCount, Versions.Version version, Consumer<IInstanceConfig> configUpdater, Consumer<Builder> builderUpdater) throws IOException",
    ),
    ABSTRACT_CLUSTER: (
        "public abstract class AbstractCluster<I extends IInstance> implements ICluster<I>, AutoCloseable",
        "public static abstract class AbstractBuilder<I extends IInstance, C extends ICluster, B extends AbstractBuilder<I, C, B>>",
        "CassandraRelevantProperties.DTEST_IS_IN_JVM_DTEST.setBoolean(true);",
        "public InstanceConfig createInstanceConfig(int nodeNum)",
        "protected I newInstanceWrapperInternal(Versions.Version version, IInstanceConfig config)",
        "public IMessageFilters filters()",
        "public synchronized void setMessageSink(IMessageSink sink)",
        "public void deliverMessage(InetSocketAddress to, IMessage message)",
        "public IMessageFilters.Builder verbs(Verb... verbs)",
        "public void schemaChange(String query)",
        "public class AllMembersAliveMonitor extends ChangeMonitor",
        "public void startup()",
        "public void close()",
    ),
    INSTANCE: (
        "public class Instance extends IsolatedExecutor implements IInvokableInstance",
        "public LogAction logs()",
        "public void receiveMessage(IMessage message)",
        "public void startup(ICluster cluster)",
        "public Future<Void> shutdown(boolean graceful)",
        "public Metrics metrics()",
        "public NodeToolResult nodetoolResult(boolean withNotifications, String... commandAndArgs)",
        "DTestNodeTool nodetool = new DTestNodeTool(withNotifications, output.delegate)",
        "public static class DTestNodeTool extends NodeTool implements AutoCloseable",
        "super(new InternalNodeProbeFactory(withNotifications), output);",
    ),
    INSTANCE_CONFIG: (
        "public class InstanceConfig implements IInstanceConfig",
        "private final Map<String, Object> params = new TreeMap<>();",
        "private final Map<String, Object> dtestParams = new TreeMap<>();",
        'this    .set("num_tokens", initial_token.size())',
        '.set("commitlog_sync", "periodic")',
        '.set("auto_bootstrap", false)',
        '.set("commitlog_disk_access_mode", "legacy");',
        "if (CassandraRelevantProperties.DTEST_JVM_DTESTS_USE_LATEST.getBoolean())",
        '.set("memtable_allocation_type", "offheap_objects")',
        '.set("storage_compatibility_mode", "NONE");',
        "public InstanceConfig with(Feature featureFlag)",
        "public InstanceConfig set(String fieldName, Object value)",
    ),
    ISOLATED_EXECUTOR: (
        "public class IsolatedExecutor implements IIsolatedExecutor",
        "public Future<Void> shutdown()",
        "public <T extends Serializable> T transfer(T in)",
    ),
    COORDINATOR: (
        "public class Coordinator implements ICoordinator",
        "public SimpleQueryResult executeWithResult(String query, ConsistencyLevel consistencyLevel, Object... boundValues)",
        "return instance().sync(() -> unsafeExecuteInternal(query, consistencyLevel, boundValues)).call();",
        "public static SimpleQueryResult unsafeExecuteInternal(String query, ConsistencyLevel consistencyLevel, Object[] boundValues)",
        "return CoordinatorHelper.unsafeExecuteInternal(query, null, consistencyLevel, boundValues);",
        "public SimpleQueryResult executeWithResult(String query, ConsistencyLevel serialConsistencyLevel, ConsistencyLevel commitConsistencyLevel, Object... boundValues)",
        "public QueryResult executeWithPagingWithResult(String query, ConsistencyLevel consistencyLevelOrigin, int pageSize, Object... boundValues)",
        "assert prepared instanceof SelectStatement : \"Only SELECT statements can be executed with paging\";",
        "QueryOptions initialOptions = QueryOptions.create(toCassandraCL(consistencyLevel),",
    ),
    ICOORDINATOR: (
        "default Object[][] execute(String query, ConsistencyLevel consistencyLevel, Object... boundValues)",
        "SimpleQueryResult executeWithResult(String query, ConsistencyLevel consistencyLevel, Object... boundValues);",
        "QueryResult executeWithPagingWithResult(String query, ConsistencyLevel consistencyLevel, int pageSize, Object... boundValues);",
    ),
    MESSAGE_FILTERS: (
        "public class MessageFilters implements IMessageFilters",
        "public boolean permitInbound(int from, int to, IMessage msg)",
        "public boolean permitOutbound(int from, int to, IMessage msg)",
        "public Filter on()",
        "public Builder from(int... nums)",
        "public Builder to(int... nums)",
        "public IMessageFilters.Builder verbs(int... verbs)",
        "public IMessageFilters.Builder messagesMatching(Matcher matcher)",
        "public IMessageFilters.Filter drop()",
    ),
    INTERNAL_NODE_PROBE: (
        "public class InternalNodeProbe extends NodeProbe",
        "protected void connect()",
        "StorageService.instance",
        "MessagingService.instance()",
        "StreamManager.instance",
        "CompactionManager.instance",
        "FailureDetector.instance",
    ),
    UPGRADE_TEST_BASE: (
        "public class UpgradeTestBase extends DistributedTestBase",
        "ICluster.setup();",
        "public static class TestCase implements ThrowingRunnable",
        "private final List<TestVersions> upgrade = new ArrayList<>();",
        "public TestCase upgradesToCurrentFrom(Semver lowerBound)",
        "public TestCase runAfterNodeUpgrade(RunOnClusterAndNode runAfterNodeUpgrade)",
        "public TestCase runAfterClusterUpgrade(RunOnCluster runAfterClusterUpgrade)",
        "public void run() throws Throwable",
        "cluster.get(n).shutdown().get();",
        "cluster.get(n).setVersion(nextVersion);",
        "cluster.get(n).startup();",
    ),
    BYTEMAN: (
        "public final class Byteman",
        "private static final boolean DEBUG_TRANSFORMATIONS = TEST_BYTEMAN_TRANSFORMATIONS_DEBUG.getBoolean();",
        "private final Transformer transformer;",
        "public static Byteman createFromScripts(String... scripts)",
        "public static Byteman createFromText(String text)",
        "this.transformer = new Transformer(null, null, scripts, texts, false);",
        "public void install(ClassLoader cl)",
        "private static Set<String> extractClasses(List<String> texts)",
    ),
    SIMULATION_RUNNER: (
        "public class SimulationRunner",
        "public static void beforeAll()",
        '@Option(name = { "--seed" }',
        '@Option(name = { "--simulations"}',
        '@Option(name = { "--network-drop-chance" }',
        '@Option(name = { "--scheduler-delay" }',
        "protected void propagate(B builder)",
        "throw new SimulationException(seed, t);",
    ),
    CLUSTER_SIMULATION: (
        "public class ClusterSimulation<S extends Simulation> implements AutoCloseable",
        "S create(SimulatedSystems simulated, RunnableActionScheduler scheduler, Cluster cluster, ClusterActions.Options options);",
        "public SimulatedFutureActionScheduler futureActionScheduler(int nodeCount, SimulatedTime time, RandomSource random)",
        "return new SimulatedFutureActionScheduler(kind, nodeCount, random, time,",
        "delivery = new SimulatedMessageDelivery(cluster);",
        "SimulatedFutureActionScheduler futureActionScheduler = builder.futureActionScheduler(numOfNodes, time, random);",
        "randomizedConfig.put(\"network_scheduler\", futureActionScheduler.getKind().toString());",
    ),
    ACTION_PLAN: (
        "public class ActionPlan",
        "public ActionPlan(ActionList pre, List<ActionList> interleave, ActionList post)",
        "public CloseableIterator<?> iterator(ActionSchedule.Mode mode, long runForNanos, LongSupplier schedulerJitter, SimulatedTime time, RunnableActionScheduler runnableScheduler, FutureActionScheduler futureScheduler)",
        "return new ActionSchedule(time, futureScheduler, schedulerJitter, runnableScheduler,",
    ),
    ACTION_SCHEDULE: (
        "public class ActionSchedule implements CloseableIterator<Object>, LongConsumer",
        "final FutureActionScheduler scheduler;",
        "final RunnableActionScheduler runnableScheduler;",
        "public ActionSchedule(SimulatedTime time, FutureActionScheduler futureScheduler, LongSupplier schedulerJitter, RunnableActionScheduler runnableScheduler, Work... moreWork)",
    ),
    SIMULATED_MESSAGE_DELIVERY: (
        "public class SimulatedMessageDelivery implements IMessageSink",
        "public SimulatedMessageDelivery(ICluster<? extends IInvokableInstance> cluster)",
        "cluster.setMessageSink(this);",
    ),
    PAXOS_SIMULATION_RUNNER: (
        "public class PaxosSimulationRunner extends SimulationRunner",
        "static void propagateTo(String consistency, boolean withStateCache, boolean withoutStateCache, String variant, String toVariant, PaxosClusterSimulation.Builder builder)",
    ),
    HISTORY_CHECKER: (
        "class HistoryChecker",
        "HistoryChecker(int primaryKey)",
    ),
    PARENT_POM: (
        "<groupId>org.apache.cassandra</groupId>",
        "<artifactId>dtest-api</artifactId>",
        "<version>0.0.18</version>",
    ),
    BUILD_DEPS: (
        "<artifactId>dtest-api</artifactId>",
    ),
}

TEST_TOKEN_CHECKS = {
    TEST_BASE_IMPL: (
        "public class TestBaseImpl extends DistributedTestBase",
        "public static void beforeClass() throws Throwable",
        "ICluster.setup();",
    ),
    ABSTRACT_CLUSTER_TEST: (
        "public class AbstractClusterTest",
        'ConfigUpdate.of("num_tokens", 4',
        "vnode is enabled and num_tokens is defined in test without GOSSIP or setting initial_token",
    ),
    JVM_DTEST_TEST: (
        "public class JVMDTestTest extends TestBaseImpl",
        "Cluster.build(1).start()",
        "cluster.schemaChange(\"CREATE TABLE \"+KEYSPACE+\".tbl",
        "logs.grep(\"JVM Arguments\")",
        "schemaChangeIgnoringStoppedInstances",
    ),
    NATIVE_PROTOCOL_TEST: (
        "public class NativeProtocolTest extends TestBaseImpl",
        "com.datastax.driver.core.Cluster.builder().addContactPoint(\"127.0.0.1\").build()",
        '.set("start_native_transport", "false")',
    ),
    HINTED_HANDOFF_NODETOOL_TEST: (
        "public class HintedHandoffNodetoolTest extends TestBaseImpl",
        "nodetoolResult(\"statushandoff\")",
        "nodetoolResult(\"disablehandoff\")",
        "nodetoolResult(\"pausehandoff\")",
        "nodetoolResult(\"sethintedhandoffthrottlekb\"",
    ),
    TRIVIAL_SIMULATION_TEST: (
        "public class TrivialSimulationTest extends SimulationTestBase",
        "public void trivialTest() throws IOException",
        "public void componentTest()",
        "public void identityHashMapTest()",
    ),
    SHORT_PAXOS_SIMULATION_TEST: (
        "public class ShortPaxosSimulationTest",
        "public void simulationTest() throws IOException",
        "PaxosSimulationRunner.main(",
        "public void selfReconcileTest() throws IOException",
    ),
    MONITOR_TRANSFORMER_TEST: (
        "public class MonitorMethodTransformerTest extends SimulationTestBase",
        "ClassWithSynchronizedMethods.synchronizedMethodWithParams(thread, iteration);",
        "ExecutorFactory.Global.executorFactory().pooled(\"name\", 10);",
    ),
    SIMULATION_TEST_BASE: (
        "public class SimulationTestBase",
        "public static void simulate(Function<DTestClusterSimulation, ActionList> init,",
        "public static void simulate(IIsolatedExecutor.SerializableRunnable[] runnables,",
    ),
    COMPACTIONS_BYTEMAN_TEST: (
        "@RunWith(BMUnitRunner.class)",
        "public class CompactionsBytemanTest extends CQLTester",
        "@BMRules(rules = { @BMRule(name = \"One SSTable too big for remaining disk space test\"",
        "@BMRule(name = \"Stop all compactions\"",
    ),
    DIRECT_IO_BYTEMAN_TEST: (
        "@RunWith(BMUnitRunner.class)",
        "public class DirectIOSegmentBytemanTest",
        "@BMRules(rules = { @BMRule(name = \"Commitlog dir do not support direct io\"",
    ),
    STREAM_FAILURE_BTM: (
        "METHOD prepareAck",
        "AT INVOKE startStreamingFiles",
    ),
}

DOC_REQUIRED_TOKENS = (
    "research/module-testing-runtime-harness-matrix.md",
    "research/module-testing-runtime-harness-drift-checker.md",
    "research/tools/check-testing-runtime-harness-drift.py",
    "CQLTester",
    "ServerTestUtils",
    "SchemaLoader",
    "Cluster",
    "AbstractCluster",
    "Instance",
    "Coordinator",
    "MessageFilters",
    "InternalNodeProbe",
    "UpgradeableCluster",
    "UpgradeTestBase",
    "SimulationRunner",
    "ClusterSimulation",
    "ActionPlan",
    "ActionSchedule",
    "Byteman",
    "dtest-api-*.jar",
    "test-jvm-dtest",
    "test-simulator-dtest",
    "test-jvm-upgrade-dtest",
) + SCENARIO_IDS


@dataclass(frozen=True)
class Check:
    kind: str
    path: str
    token: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def token_checks(kind: str, checks: dict[str, tuple[str, ...]]) -> list[Check]:
    results: list[Check] = []
    for path, tokens in checks.items():
        text = read(path)
        results.extend(Check(kind, path, token, token in text) for token in tokens)
    return results


def find_dtest_api_artifacts() -> list[str]:
    matches: list[str] = []
    for pattern in ("**/*dtest-api*", "**/*dtest*api*"):
        for match in glob.glob(str(REPO_ROOT / pattern), recursive=True):
            rel = str(Path(match).relative_to(REPO_ROOT))
            if rel.startswith(".git/"):
                continue
            if rel.startswith("research/"):
                continue
            matches.append(rel)
    return sorted(set(matches))


def artifact_checks() -> list[Check]:
    artifacts = find_dtest_api_artifacts()
    return [Check("artifact", "**/*dtest-api*", "no inspectable dtest-api artifact in checkout", not artifacts)]


def doc_checks() -> list[Check]:
    text = "\n".join(read(path) for path in TARGET_DOCS)
    checks = [Check("doc", " / ".join(TARGET_DOCS), token, token in text) for token in DOC_REQUIRED_TOKENS]
    checks.extend(Check("scenario", " / ".join(TARGET_DOCS), scenario, documented(scenario, text)) for scenario in SCENARIO_IDS)
    return checks


def all_checks() -> list[Check]:
    return (
        token_checks("source", SOURCE_TOKEN_CHECKS)
        + token_checks("test", TEST_TOKEN_CHECKS)
        + artifact_checks()
        + doc_checks()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Testing Framework runtime harness research drift.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable check results")
    args = parser.parse_args()

    checks = all_checks()
    failures = [check for check in checks if not check.ok]

    if args.json:
        print(json.dumps([check.__dict__ for check in checks], indent=2, sort_keys=True))

    if failures:
        if not args.json:
            print("Testing runtime harness drift check failed:")
            for failure in failures:
                print(f"- [{failure.kind}] {failure.path}: {failure.token}")
        return 1

    if not args.json:
        source_count = sum(1 for check in checks if check.kind == "source")
        test_count = sum(1 for check in checks if check.kind == "test")
        print(f"OK testing runtime harness drift checks passed ({source_count} source checks, {test_count} test checks, {len(SCENARIO_IDS)} scenarios)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
