#!/usr/bin/env python3
#
# Source-only drift check for CQL trigger execution research coverage.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

PARSER = "src/antlr/Parser.g"
CREATE_TRIGGER = "src/java/org/apache/cassandra/cql3/statements/schema/CreateTriggerStatement.java"
DROP_TRIGGER = "src/java/org/apache/cassandra/cql3/statements/schema/DropTriggerStatement.java"
TRIGGER_METADATA = "src/java/org/apache/cassandra/schema/TriggerMetadata.java"
TRIGGERS = "src/java/org/apache/cassandra/schema/Triggers.java"
TABLE_METADATA = "src/java/org/apache/cassandra/schema/TableMetadata.java"
SCHEMA_KEYSPACE = "src/java/org/apache/cassandra/schema/SchemaKeyspace.java"
I_TRIGGER = "src/java/org/apache/cassandra/triggers/ITrigger.java"
TRIGGER_EXECUTOR = "src/java/org/apache/cassandra/triggers/TriggerExecutor.java"
CUSTOM_CLASS_LOADER = "src/java/org/apache/cassandra/triggers/CustomClassLoader.java"
MODIFICATION_STATEMENT = "src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java"
BATCH_STATEMENT = "src/java/org/apache/cassandra/cql3/statements/BatchStatement.java"
STORAGE_PROXY = "src/java/org/apache/cassandra/service/StorageProxy.java"
NODE_TOOL = "src/java/org/apache/cassandra/tools/NodeTool.java"
NODE_PROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
RELOAD_TRIGGERS = "src/java/org/apache/cassandra/tools/nodetool/ReloadTriggers.java"
FBUTILITIES = "src/java/org/apache/cassandra/utils/FBUtilities.java"
CASSANDRA_RELEVANT_PROPERTIES = "src/java/org/apache/cassandra/config/CassandraRelevantProperties.java"
JVM_SERVER_OPTIONS = "conf/jvm-server.options"
AUDIT_LOG_ENTRY_TYPE = "src/java/org/apache/cassandra/audit/AuditLogEntryType.java"

TRIGGERS_TEST = "test/unit/org/apache/cassandra/triggers/TriggersTest.java"
TRIGGER_EXECUTOR_TEST = "test/unit/org/apache/cassandra/triggers/TriggerExecutorTest.java"
TRIGGERS_SCHEMA_TEST = "test/unit/org/apache/cassandra/triggers/TriggersSchemaTest.java"
AUDIT_LOGGER_TEST = "test/unit/org/apache/cassandra/audit/AuditLoggerTest.java"

MATRIX_DOC = "research/module-cql-trigger-execution-matrix.md"
CHECKER_DOC = "research/module-cql-trigger-execution-drift-checker.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

SCENARIO_IDS = (
    "cql_trigger_grammar_contract",
    "cql_trigger_create_authorization_load_contract",
    "cql_trigger_drop_authorization_contract",
    "cql_trigger_metadata_contract",
    "cql_trigger_system_schema_contract",
    "cql_trigger_classloader_reload_contract",
    "cql_trigger_directory_config_contract",
    "cql_trigger_ordinary_write_contract",
    "cql_trigger_batch_atomic_contract",
    "cql_trigger_cas_single_partition_contract",
    "cql_trigger_validation_contract",
    "cql_trigger_nodetool_reload_contract",
    "cql_trigger_audit_contract",
    "cql_trigger_tests_baseline",
    "cql_trigger_distributed_gap",
)

SOURCE_TOKEN_CHECKS = {
    PARSER: (
        "createTriggerStatement returns [CreateTriggerStatement.Raw stmt]",
        "K_CREATE K_TRIGGER",
        "K_ON cf=columnFamilyName K_USING cls=STRING_LITERAL",
        "new CreateTriggerStatement.Raw(cf, name.toString(), $cls.text, ifNotExists)",
        "dropTriggerStatement returns [DropTriggerStatement.Raw stmt]",
        "K_DROP K_TRIGGER",
        "new DropTriggerStatement.Raw(cf, name.toString(), ifExists)",
    ),
    CREATE_TRIGGER: (
        "public final class CreateTriggerStatement extends AlterSchemaStatement",
        "if (table.isView())",
        "Cannot CREATE TRIGGER for a materialized view",
        "table.triggers.get(triggerName).orElse(null)",
        "if (ifNotExists)",
        "TriggerExecutor.instance.loadTriggerInstance(triggerClass);",
        "Trigger class '%s' couldn't be loaded",
        "table.triggers.with(TriggerMetadata.create(triggerName, triggerClass))",
        "client.ensureIsSuperuser(\"Only superusers are allowed to perform CREATE TRIGGER queries\");",
        "AuditLogEntryType.CREATE_TRIGGER",
        "return new CreateTriggerStatement(keyspaceName, tableName.getName(), triggerName, triggerClass, ifNotExists);",
    ),
    DROP_TRIGGER: (
        "public final class DropTriggerStatement extends AlterSchemaStatement",
        "table.triggers.get(triggerName).orElse(null)",
        "if (ifExists)",
        "Trigger '%s' on '%s.%s' doesn't exist",
        "table.triggers.without(triggerName)",
        "client.ensureIsSuperuser(\"Only superusers are allowed to perfrom DROP TRIGGER queries\");",
        "AuditLogEntryType.DROP_TRIGGER",
        "return new DropTriggerStatement(keyspaceName, tableName.getName(), triggerName, ifExists);",
    ),
    TRIGGER_METADATA: (
        "public static final String CLASS = \"class\";",
        "public final String name;",
        "public final String classOption;",
        "public static TriggerMetadata create(String name, String classOption)",
    ),
    TRIGGERS: (
        "public final class Triggers implements Iterable<TriggerMetadata>",
        "private final ImmutableMap<String, TriggerMetadata> triggers;",
        "public static Triggers none()",
        "public Optional<TriggerMetadata> get(String name)",
        "public Triggers with(TriggerMetadata trigger)",
        "Trigger %s already exists",
        "public Triggers without(String name)",
        "Trigger %s doesn't exists",
    ),
    TABLE_METADATA: (
        "public final Triggers triggers;",
        "triggers = builder.triggers;",
        "public TableMetadata withSwapped(Triggers triggers)",
        "private Triggers triggers = Triggers.none();",
        "public Builder triggers(Triggers val)",
    ),
    SCHEMA_KEYSPACE: (
        "private static final TableMetadata Triggers =",
        "CREATE TABLE %s (",
        "trigger_name text,",
        "options frozen<map<text, text>>,",
        "PRIMARY KEY ((keyspace_name), table_name, trigger_name))",
        "for (TriggerMetadata trigger : table.triggers)",
        "addTriggerToSchemaMutation(table, trigger, builder);",
        "dropTriggerFromSchemaMutation(oldTable, trigger, builder);",
        "private static MapDifference<String, TriggerMetadata> triggersDiff",
        "builder.update(Triggers)",
        ".row(table.name, trigger.name)",
        ".add(\"options\", Collections.singletonMap(\"class\", trigger.classOption));",
        "builder.update(Triggers).row(table.name, trigger.name).delete();",
        "private static Triggers fetchTriggers(String keyspace, String table)",
        "SELECT * FROM %s.%s WHERE keyspace_name = ? AND table_name = ?",
        "row.getFrozenTextMap(\"options\").get(\"class\")",
    ),
    I_TRIGGER: (
        "public interface ITrigger",
        "Implementation of this interface should only have a constructor without parameters",
        "ITrigger implementation should be state-less",
        "public Collection<Mutation> augment(Partition update);",
    ),
    TRIGGER_EXECUTOR: (
        "public static final TriggerExecutor instance = new TriggerExecutor();",
        "private final Map<String, ITrigger> cachedTriggers = Maps.newConcurrentMap();",
        "private volatile ClassLoader customClassLoader;",
        "public void reloadClasses()",
        "File triggerDirectory = FBUtilities.cassandraTriggerDir();",
        "customClassLoader = new CustomClassLoader(parent, triggerDirectory);",
        "cachedTriggers.clear();",
        "public PartitionUpdate execute(PartitionUpdate updates)",
        "validateForSinglePartition(updates.metadata().id,",
        "return PartitionUpdate.merge(augmented);",
        "public Collection<Mutation> execute(Collection<? extends IMutation> mutations)",
        "if (mutation instanceof CounterMutation)",
        "Counter mutations and trigger mutations cannot be applied together atomically.",
        "return mergeMutations(Iterables.concat(originalMutations, augmentedMutations));",
        "ListMultimap<Pair<String, ByteBuffer>, Mutation> groupedMutations = ArrayListMultimap.create();",
        "private List<PartitionUpdate> validateForSinglePartition",
        "validateSamePartition(tableId, key, update);",
        "Partition key of additional mutation does not match primary update key",
        "table of additional mutation does not match primary update table",
        "QueryProcessor.validateKey(mutation.key().getKey());",
        "update.validate();",
        "Thread.currentThread().setContextClassLoader(customClassLoader);",
        "ITrigger trigger = cachedTriggers.get(td.classOption);",
        "trigger = loadTriggerInstance(td.classOption);",
        "cachedTriggers.put(td.classOption, trigger);",
        "Collection<Mutation> temp = trigger.augment(update);",
        "Thread.currentThread().setContextClassLoader(parent);",
        "public synchronized ITrigger loadTriggerInstance(String triggerClass) throws Exception",
        "return (ITrigger) customClassLoader.loadClass(triggerClass).getConstructor().newInstance();",
    ),
    CUSTOM_CLASS_LOADER: (
        "public class CustomClassLoader extends URLClassLoader",
        "private final Map<String, Class<?>> cache = new ConcurrentHashMap<>();",
        "public CustomClassLoader(ClassLoader parent, File classPathDir)",
        "addClassPath(classPathDir);",
        "BiPredicate<File, String> filter = (ignore, name) -> name.endsWith(\".jar\");",
        "File lib = new File(FileUtils.getTempDir(), \"lib\");",
        "logger.info(\"Loading new jar {}\", inputJar.absolutePath());",
        "copy(inputJar.toPath(), out.toPath(), StandardCopyOption.REPLACE_EXISTING);",
        "addURL(out.toPath().toUri().toURL());",
        "return parent.loadClass(name);",
        "Class<?> clazz = this.findClass(name);",
        "cache.put(name, clazz);",
    ),
    MODIFICATION_STATEMENT: (
        "return hasConditions()",
        "executeWithoutCondition(queryState, options, requestTime)",
        "StorageProxy.mutateWithTriggers(mutations, cl, false, requestTime);",
        "static RowIterator casInternal(ClientState state, CQL3CasRequest request, long timestamp, long nowInSeconds)",
        "updates = TriggerExecutor.instance.execute(updates);",
        "proposal.makeMutation().apply();",
    ),
    BATCH_STATEMENT: (
        "if (hasConditions)",
        "executeWithoutConditions(getMutations(clientState, options, false, timestamp, nowInSeconds, requestTime),",
        "boolean mutateAtomic = (isLogged() && mutations.size() > 1);",
        "StorageProxy.mutateWithTriggers(mutations, cl, mutateAtomic, requestTime);",
    ),
    STORAGE_PROXY: (
        "updates = TriggerExecutor.instance.execute(updates);",
        "public static void mutateWithTriggers(List<? extends IMutation> mutations,",
        "Collection<Mutation> augmented = TriggerExecutor.instance.execute(mutations);",
        "boolean updatesView = Keyspace.open(mutations.iterator().next().getKeyspaceName())",
        "if (augmented != null)",
        "mutateAtomically(augmented, consistencyLevel, updatesView, requestTime);",
        "if (mutateAtomically || updatesView)",
        "public void reloadTriggerClasses() { TriggerExecutor.instance.reloadClasses(); }",
    ),
    NODE_TOOL: (
        "ReloadTriggers.class,",
    ),
    NODE_PROBE: (
        "public void reloadTriggers()",
        "spProxy.reloadTriggerClasses();",
    ),
    RELOAD_TRIGGERS: (
        "@Command(name = \"reloadtriggers\", description = \"Reload trigger classes\")",
        "public class ReloadTriggers extends NodeToolCmd",
        "probe.reloadTriggers();",
    ),
    FBUTILITIES: (
        "public static File cassandraTriggerDir()",
        "if (TRIGGERS_DIR.getString() != null)",
        "triggerDir = new File(TRIGGERS_DIR.getString());",
        "URL confDir = FBUtilities.class.getClassLoader().getResource(DEFAULT_TRIGGER_DIR);",
        "Trigger directory doesn't exist, please create it and try again.",
    ),
    CASSANDRA_RELEVANT_PROPERTIES: (
        "TRIGGERS_DIR(\"cassandra.triggers_dir\")",
    ),
    JVM_SERVER_OPTIONS: (
        "Set the default location for the trigger JARs. (Default: conf/triggers)",
        "#-Dcassandra.triggers_dir=directory",
    ),
    AUDIT_LOG_ENTRY_TYPE: (
        "DROP_TRIGGER(AuditLogEntryCategory.DDL)",
        "CREATE_TRIGGER(AuditLogEntryCategory.DDL)",
    ),
}

TEST_TOKEN_CHECKS = {
    TRIGGERS_TEST: (
        "public class TriggersTest",
        "CREATE TRIGGER trigger_1 ON %s.%s USING '%s'",
        "public void executeTriggerOnCqlInsert()",
        "public void executeTriggerOnCqlBatchInsert()",
        "public void executeTriggerOnCqlInsertWithConditions()",
        "public void executeTriggerOnCqlBatchWithConditions()",
        "onCqlUpdateWithConditionsRejectGeneratedUpdatesForDifferentPartition",
        "onCqlUpdateWithConditionsRejectGeneratedUpdatesForDifferentTable",
        "ifTriggerThrowsErrorNoMutationsAreApplied",
        "assertUpdateNotExecuted(cf, 11);",
        "public static class TestTrigger implements ITrigger",
        "public static class CrossPartitionTrigger implements ITrigger",
        "public static class CrossTableTrigger implements ITrigger",
        "public static class ErrorTrigger implements ITrigger",
    ),
    TRIGGER_EXECUTOR_TEST: (
        "public class TriggerExecutorTest",
        "public void sameKeySameCfColumnFamilies()",
        "public void sameKeyDifferentCfColumnFamilies()",
        "public void differentKeyColumnFamilies()",
        "public void noTriggerMutations()",
        "public void sameKeySameCfRowMutations()",
        "public void sameKeyDifferentCfRowMutations()",
        "public void sameKeyDifferentKsRowMutations()",
        "public void differentKeyRowMutations()",
        "TriggerExecutor.instance.execute(Arrays.asList(rm1, rm2))",
        "public static class NoOpTrigger implements ITrigger",
        "public static class SameKeySameCfTrigger implements ITrigger",
        "public static class SameKeyDifferentCfTrigger implements ITrigger",
        "public static class SameKeyDifferentKsTrigger implements ITrigger",
        "public static class DifferentKeyTrigger implements ITrigger",
    ),
    TRIGGERS_SCHEMA_TEST: (
        "public class TriggersSchemaTest",
        "public void newKsContainsCfWithTrigger()",
        "public void addNewCfWithTriggerToKs()",
        "public void addTriggerToCf()",
        "public void removeTriggerFromCf()",
        ".triggers(Triggers.of(td))",
        "tm1.triggers.without(triggerName)",
    ),
    AUDIT_LOGGER_TEST: (
        "public void testCqlTriggerAuditing()",
        "DROP TRIGGER IF EXISTS",
        "AuditLogEntryType.DROP_TRIGGER",
    ),
}

DOC_TOKENS = (
    MATRIX_DOC,
    CHECKER_DOC,
    "research/tools/check-cql-trigger-execution-drift.py",
    "TriggerExecutor",
    "ITrigger",
    "CustomClassLoader",
    "CreateTriggerStatement",
    "DropTriggerStatement",
    "system_schema.triggers",
    "reloadtriggers",
    "cassandra.triggers_dir",
) + SCENARIO_IDS


@dataclass(frozen=True)
class CheckResult:
    name: str
    source: str
    ok: bool
    detail: str = ""


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def token_checks(checks: dict[str, tuple[str, ...]], group: str) -> list[CheckResult]:
    results: list[CheckResult] = []
    for path, tokens in checks.items():
        text = read(path)
        for token in tokens:
            results.append(CheckResult(f"{group} token {token}", path, token in text))
    return results


def source_checks() -> list[CheckResult]:
    return token_checks(SOURCE_TOKEN_CHECKS, "source")


def dedicated_distributed_trigger_tests() -> list[str]:
    distributed = REPO_ROOT / "test/distributed"
    return sorted(str(path.relative_to(REPO_ROOT)) for path in distributed.rglob("*Trigger*.java"))


def test_checks() -> list[CheckResult]:
    checks = token_checks(TEST_TOKEN_CHECKS, "test")
    distributed_trigger_tests = dedicated_distributed_trigger_tests()
    checks.append(CheckResult("distributed trigger gap", "test/distributed", len(distributed_trigger_tests) == 0, ", ".join(distributed_trigger_tests)))
    return checks


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def doc_checks() -> list[CheckResult]:
    matrix = read(MATRIX_DOC)
    checker = read(CHECKER_DOC)
    readme = read(README_DOC)
    source_map = read(SOURCE_MAP_DOC)
    matrix_and_checker = matrix + "\n" + checker
    all_docs = "\n".join((matrix, checker, readme, source_map))

    checks = [CheckResult(f"scenario documented {scenario}", f"{MATRIX_DOC} / {CHECKER_DOC}", documented(scenario, matrix_and_checker)) for scenario in SCENARIO_IDS]
    checks.extend(CheckResult(f"doc token {token}", "research docs", token in all_docs) for token in DOC_TOKENS)
    checks.extend(
        [
            CheckResult("README references matrix", README_DOC, MATRIX_DOC.split("/", 1)[1] in readme),
            CheckResult("README references checker", README_DOC, CHECKER_DOC.split("/", 1)[1] in readme and "check-cql-trigger-execution-drift.py" in readme),
            CheckResult("source-map references matrix", SOURCE_MAP_DOC, MATRIX_DOC in source_map),
            CheckResult("source-map references checker", SOURCE_MAP_DOC, "research/tools/check-cql-trigger-execution-drift.py" in source_map),
        ]
    )
    return checks


def check() -> tuple[dict[str, object], bool]:
    sources = source_checks()
    tests = test_checks()
    docs = doc_checks()
    result = {
        "scenario_ids": list(SCENARIO_IDS),
        "source_checks": [entry.__dict__ for entry in sources],
        "test_checks": [entry.__dict__ for entry in tests],
        "doc_checks": [entry.__dict__ for entry in docs],
        "distributed_trigger_tests": dedicated_distributed_trigger_tests(),
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in tests) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check CQL trigger execution source/test/doc coverage.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    try:
        result, ok = check()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        failed_sources = [entry for entry in result["source_checks"] if not entry["ok"]]
        failed_tests = [entry for entry in result["test_checks"] if not entry["ok"]]
        failed_docs = [entry for entry in result["doc_checks"] if not entry["ok"]]
        if failed_sources:
            for entry in failed_sources:
                print(f"source: {entry['source']}: missing {entry['name']}")
        if failed_tests:
            for entry in failed_tests:
                detail = f" ({entry['detail']})" if entry.get("detail") else ""
                print(f"test: {entry['source']}: failed {entry['name']}{detail}")
        if failed_docs:
            for entry in failed_docs:
                print(f"doc: {entry['source']}: missing {entry['name']}")
        if ok:
            print(f"OK CQL trigger execution checks passed ({len(result['scenario_ids'])} scenarios)")
        else:
            print("CQL trigger execution checks failed.", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
