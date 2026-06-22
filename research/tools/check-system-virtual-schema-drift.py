#!/usr/bin/env python3
#
# Source/test/doc drift check for system_virtual_schema.columns research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

VIRTUAL_SCHEMA = "src/java/org/apache/cassandra/db/virtual/VirtualSchemaKeyspace.java"
VIRTUAL_REGISTRY = "src/java/org/apache/cassandra/db/virtual/VirtualKeyspaceRegistry.java"
VIRTUAL_KEYSPACE = "src/java/org/apache/cassandra/db/virtual/VirtualKeyspace.java"
VIRTUAL_TABLE = "src/java/org/apache/cassandra/db/virtual/VirtualTable.java"
ABSTRACT_VIRTUAL_TABLE = "src/java/org/apache/cassandra/db/virtual/AbstractVirtualTable.java"
SINGLE_READ = "src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java"
RANGE_READ = "src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java"
STATEMENT_RESTRICTIONS = "src/java/org/apache/cassandra/cql3/restrictions/StatementRestrictions.java"
CASSANDRA_DAEMON = "src/java/org/apache/cassandra/service/CassandraDaemon.java"
CLIENT_STATE = "src/java/org/apache/cassandra/service/ClientState.java"
READ_VERB = "src/java/org/apache/cassandra/db/ReadCommandVerbHandler.java"
VIRTUAL_MUTATION = "src/java/org/apache/cassandra/db/virtual/VirtualMutation.java"
SCHEMA_CONSTANTS = "src/java/org/apache/cassandra/schema/SchemaConstants.java"
COLUMN_METADATA = "src/java/org/apache/cassandra/schema/ColumnMetadata.java"

VIRTUAL_TABLE_TEST = "test/unit/org/apache/cassandra/cql3/validation/entities/VirtualTableTest.java"
DESCRIBE_TEST = "test/unit/org/apache/cassandra/cql3/statements/DescribeStatementTest.java"
INTERNODE_TEST = "test/distributed/org/apache/cassandra/distributed/test/VirtualTableFromInternodeTest.java"
CQL_TESTER = "test/unit/org/apache/cassandra/cql3/CQLTester.java"
GRANT_REVOKE_TEST = "test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java"

TARGET_DOCS = (
    "research/module-system-virtual-schema-columns-matrix.md",
    "research/module-system-virtual-schema-drift-checker.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "system_virtual_schema_registration_contract",
    "system_virtual_schema_keyspaces_contract",
    "system_virtual_schema_tables_contract",
    "system_virtual_schema_columns_schema_contract",
    "system_virtual_schema_columns_projection_contract",
    "system_virtual_schema_columns_self_row_content_contract",
    "system_virtual_schema_read_single_partition_contract",
    "system_virtual_schema_read_range_contract",
    "system_virtual_schema_filtering_contract",
    "system_virtual_schema_default_read_permission_contract",
    "system_virtual_schema_dml_ddl_guard_contract",
    "system_virtual_schema_internode_read_contract",
    "system_virtual_schema_select_data_test_gap",
    "system_virtual_schema_existing_tests_baseline",
)

SOURCE_TOKEN_CHECKS = {
    SCHEMA_CONSTANTS: (
        'public static final String VIRTUAL_SCHEMA = "system_virtual_schema";',
        'public static final String VIRTUAL_VIEWS = "system_views";',
        "VIRTUAL_SYSTEM_KEYSPACE_NAMES",
    ),
    COLUMN_METADATA: (
        "public static final int NO_POSITION = -1;",
        "public enum ClusteringOrder",
        "ASC, DESC, NONE",
        "public enum Kind",
        "PARTITION_KEY",
        "CLUSTERING",
        "REGULAR",
        "STATIC",
        "return this == PARTITION_KEY || this == CLUSTERING;",
        "assert (position == NO_POSITION) == !kind.isPrimaryKeyKind();",
    ),
    VIRTUAL_SCHEMA: (
        "public final class VirtualSchemaKeyspace extends VirtualKeyspace",
        "public static final VirtualSchemaKeyspace instance = new VirtualSchemaKeyspace();",
        "super(VIRTUAL_SCHEMA, ImmutableList.of(new VirtualKeyspaces(VIRTUAL_SCHEMA), new VirtualTables(VIRTUAL_SCHEMA), new VirtualColumns(VIRTUAL_SCHEMA)));",
        'builder(keyspace, "keyspaces")',
        'builder(keyspace, "tables")',
        'builder(keyspace, "columns")',
        "private static final String KEYSPACE_NAME = \"keyspace_name\";",
        "private static final String TABLE_NAME = \"table_name\";",
        "private static final String COLUMN_NAME = \"column_name\";",
        "private static final String CLUSTERING_ORDER = \"clustering_order\";",
        "private static final String COLUMN_NAME_BYTES = \"column_name_bytes\";",
        "private static final String KIND = \"kind\";",
        "private static final String POSITION = \"position\";",
        "private static final String TYPE = \"type\";",
        ".addPartitionKeyColumn(KEYSPACE_NAME, UTF8Type.instance)",
        ".addClusteringColumn(TABLE_NAME, UTF8Type.instance)",
        ".addClusteringColumn(COLUMN_NAME, UTF8Type.instance)",
        ".addRegularColumn(CLUSTERING_ORDER, UTF8Type.instance)",
        ".addRegularColumn(COLUMN_NAME_BYTES, BytesType.instance)",
        ".addRegularColumn(KIND, UTF8Type.instance)",
        ".addRegularColumn(POSITION, Int32Type.instance)",
        ".addRegularColumn(TYPE, UTF8Type.instance)",
        "for (KeyspaceMetadata keyspace : VirtualKeyspaceRegistry.instance.virtualKeyspacesMetadata())",
        "for (TableMetadata table : keyspace.tables)",
        "for (ColumnMetadata column : table.columns())",
        "result.row(column.ksName, column.cfName, column.name.toString())",
        ".column(CLUSTERING_ORDER, column.clusteringOrder().toString().toLowerCase())",
        ".column(COLUMN_NAME_BYTES, column.name.bytes)",
        ".column(KIND, column.kind.toString().toLowerCase())",
        ".column(POSITION, column.position())",
        ".column(TYPE, column.type.asCQL3Type().toString());",
    ),
    VIRTUAL_REGISTRY: (
        "public final class VirtualKeyspaceRegistry",
        "private final Map<String, VirtualKeyspace> virtualKeyspaces = new ConcurrentHashMap<>();",
        "private final Map<TableId, VirtualTable> virtualTables = new ConcurrentHashMap<>();",
        "public void register(VirtualKeyspace keyspace)",
        "previous.tables().forEach(t -> virtualTables.remove(t));",
        "keyspace.tables().forEach(t -> virtualTables.put(t.metadata().id, t));",
        "public VirtualTable getTableNullable(TableId id)",
        "public Iterable<KeyspaceMetadata> virtualKeyspacesMetadata()",
    ),
    VIRTUAL_KEYSPACE: (
        "public class VirtualKeyspace",
        "public VirtualKeyspace(String name, Collection<VirtualTable> tables)",
        "this.tables = ImmutableList.copyOf(tables);",
        "metadata = KeyspaceMetadata.virtual(name, Tables.of(Iterables.transform(tables, VirtualTable::metadata)));",
    ),
    VIRTUAL_TABLE: (
        "public interface VirtualTable",
        "TableMetadata metadata();",
        "void apply(PartitionUpdate update);",
        "UnfilteredPartitionIterator select(DecoratedKey partitionKey, ClusteringIndexFilter clusteringIndexFilter, ColumnFilter columnFilter);",
        "UnfilteredPartitionIterator select(DataRange dataRange, ColumnFilter columnFilter);",
        "void truncate();",
        "default boolean allowFilteringImplicitly()",
    ),
    ABSTRACT_VIRTUAL_TABLE: (
        "public abstract class AbstractVirtualTable implements VirtualTable",
        "if (!metadata.isVirtual())",
        "public abstract DataSet data();",
        "public DataSet data(DecoratedKey partitionKey)",
        "return data();",
        "public final UnfilteredPartitionIterator select(DecoratedKey partitionKey, ClusteringIndexFilter clusteringIndexFilter, ColumnFilter columnFilter)",
        "Partition partition = data(partitionKey).getPartition(partitionKey);",
        "public final UnfilteredPartitionIterator select(DataRange dataRange, ColumnFilter columnFilter)",
        "DataSet data = data();",
        "throw new InvalidRequestException(\"Modification is not supported by table \" + metadata);",
        "throw new InvalidRequestException(\"Truncation is not supported by table \" + metadata);",
    ),
    SINGLE_READ: (
        "if (metadata.isVirtual())",
        "return new VirtualTableSinglePartitionReadCommand(isDigest,",
        "public static class VirtualTableGroup extends Group",
        "public static class VirtualTableSinglePartitionReadCommand extends SinglePartitionReadCommand",
        "VirtualTable view = VirtualKeyspaceRegistry.instance.getTableNullable(metadata().id);",
        "UnfilteredPartitionIterator resultIterator = view.select(partitionKey, clusteringIndexFilter, columnFilter());",
        "return ReadExecutionController.empty();",
    ),
    RANGE_READ: (
        "if (metadata.isVirtual())",
        "return new VirtualTablePartitionRangeReadCommand(isDigest,",
        "public static class VirtualTablePartitionRangeReadCommand extends PartitionRangeReadCommand",
        "VirtualTable view = VirtualKeyspaceRegistry.instance.getTableNullable(metadata().id);",
        "UnfilteredPartitionIterator resultIterator = view.select(dataRange, columnFilter());",
        "return ReadExecutionController.empty();",
    ),
    STATEMENT_RESTRICTIONS: (
        "public boolean requiresAllowFilteringIfNotSpecified()",
        "if (!table.isVirtual())",
        "VirtualTable tableNullable = VirtualKeyspaceRegistry.instance.getTableNullable(table.id);",
        "return !tableNullable.allowFilteringImplicitly();",
    ),
    CASSANDRA_DAEMON: (
        "public void setupVirtualKeyspaces()",
        "VirtualKeyspaceRegistry.instance.register(VirtualSchemaKeyspace.instance);",
        "VirtualKeyspaceRegistry.instance.register(SystemViewsKeyspace.instance);",
    ),
    CLIENT_STATE: (
        "VirtualSchemaKeyspace.instance.tables().forEach(t -> readableBuilder.add(t.metadata().resource));",
        "READABLE_SYSTEM_RESOURCES = readableBuilder.build();",
        "if (SchemaConstants.isSystemKeyspace(keyspace))",
    ),
    READ_VERB: (
        "private void validateTransientStatus(Message<ReadCommand> message)",
        "if (command.metadata().isVirtual())",
        "return;",
    ),
    VIRTUAL_MUTATION: (
        "public final class VirtualMutation implements IMutation",
        "Mainly overrides {@link #apply()} to go straight to {@link VirtualTable#apply(PartitionUpdate)}",
        "modifications.forEach((id, update) -> VirtualKeyspaceRegistry.instance.getTableNullable(id).apply(update));",
    ),
}

TEST_TOKEN_CHECKS = {
    VIRTUAL_TABLE_TEST: (
        "VirtualKeyspaceRegistry.instance.register(new VirtualKeyspace(KS_NAME, ImmutableList.of(vt1, vt2, vt3, vt4, vt5)));",
        "public boolean allowFilteringImplicitly()",
        "SELECT * FROM test_virtual_ks.vt1 WHERE pk IN ('pk2', 'pk1') AND c IN ('c2', 'c1')",
        "executeNetWithPaging",
        "Modification is not supported by table test_virtual_ks.vt1",
        "Error during truncate: Truncation is not supported by table test_virtual_ks.vt1",
        "Virtual keyspace 'test_virtual_ks' is not user-modifiable",
        "testDisallowedFilteringOnRegularColumn",
        "testAllowedFilteringOnRegularColumn",
    ),
    DESCRIBE_TEST: (
        "public void testDescribeVirtualTables()",
        "DESCRIBE ONLY KEYSPACE system_virtual_schema;",
        "DESCRIBE TABLE system_virtual_schema.columns;",
        "VIRTUAL TABLE system_virtual_schema.columns",
        "PRIMARY KEY (keyspace_name, table_name, column_name)",
        "AND comment = 'virtual column definitions';",
    ),
    INTERNODE_TEST: (
        "public void normal()",
        "SELECT * FROM system_views.settings",
        "public void readCommandAccessVirtualTable()",
        "QueryProcessor.executeAsync(address, \"SELECT * FROM system_views.settings\")",
        "public void readCommandAccessVirtualTableSinglePartition()",
        "public void readCommandAccessVirtualTableMultiplePartition()",
    ),
    CQL_TESTER: (
        "VirtualKeyspaceRegistry.instance.register(VirtualSchemaKeyspace.instance);",
        "StorageService.instance.initServer();",
    ),
    GRANT_REVOKE_TEST: (
        "public void testGrantOnVirtualKeyspaces()",
        "GRANT SELECT PERMISSION ON KEYSPACE system_virtual_schema",
        "GRANT SELECT PERMISSION ON KEYSPACE system_views",
        "REVOKE SELECT PERMISSION ON KEYSPACE system_virtual_schema",
        "REVOKE SELECT PERMISSION ON KEYSPACE system_views",
    ),
}

DOC_REQUIRED_TOKENS = (
    "research/tools/check-system-virtual-schema-drift.py",
    "research/module-system-virtual-schema-columns-matrix.md",
    "research/module-system-virtual-schema-drift-checker.md",
    "VirtualSchemaKeyspace",
    "VirtualKeyspaceRegistry",
    "VirtualColumns",
    "ColumnMetadata",
    "SinglePartitionReadCommand",
    "PartitionRangeReadCommand",
    "StatementRestrictions",
    "DescribeStatementTest",
    "system_virtual_schema_columns_self_row_content_contract",
    "partition_key",
    "clustering",
    "regular",
    "NO_POSITION",
)

TEST_ROOTS = (
    "test/unit",
    "test/distributed",
)


@dataclass(frozen=True)
class Check:
    name: str
    path: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def source_checks() -> list[Check]:
    checks: list[Check] = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(Check(f"source token contract {path}", path, all(token in text for token in tokens)))
    return checks


def test_checks() -> list[Check]:
    checks: list[Check] = []
    for path, tokens in TEST_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(Check(f"test token contract {path}", path, all(token in text for token in tokens)))
    return checks


def select_gap_checks() -> list[Check]:
    hits: list[str] = []
    pattern = re.compile(r"select\b[^;\n]*\bsystem_virtual_schema\.columns\b", re.I)

    for root in TEST_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.java"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if pattern.search(text):
                hits.append(str(path.relative_to(REPO_ROOT)))

    return [
        Check(
            "gap still open: no direct SELECT assertions for system_virtual_schema.columns row data",
            "test SELECT system_virtual_schema.columns",
            not hits,
        )
    ]


def doc_checks() -> list[Check]:
    docs = {path: read(path) for path in TARGET_DOCS}
    combined = "\n".join(docs.values())
    checks = [Check(f"target doc exists {path}", path, bool(text.strip())) for path, text in docs.items()]
    checks.extend(Check(f"doc token {token}", "research", token in combined) for token in DOC_REQUIRED_TOKENS)

    matrix = docs["research/module-system-virtual-schema-columns-matrix.md"]
    drift_doc = docs["research/module-system-virtual-schema-drift-checker.md"]
    for scenario in SCENARIO_IDS:
        checks.append(Check(f"scenario coverage {scenario}", "research", scenario in matrix and scenario in drift_doc))

    return checks


def run_checks() -> list[Check]:
    return source_checks() + test_checks() + select_gap_checks() + doc_checks()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check system virtual schema research drift.")
    parser.add_argument("--json", action="store_true", help="Emit check results as JSON.")
    args = parser.parse_args()

    checks = run_checks()
    failures = [check for check in checks if not check.ok]

    if args.json:
        print(json.dumps([check.__dict__ for check in checks], indent=2, sort_keys=True))

    if failures:
        if not args.json:
            print("FAILED system virtual schema drift checks:", file=sys.stderr)
            for check in failures:
                print(f"- {check.name} ({check.path})", file=sys.stderr)
        return 1

    if not args.json:
        print(
            "OK system virtual schema drift checks passed "
            f"({len(SOURCE_TOKEN_CHECKS)} source files, "
            f"{len(TEST_TOKEN_CHECKS)} test files, "
            f"{len(TARGET_DOCS)} docs, "
            f"{len(SCENARIO_IDS)} scenarios)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
