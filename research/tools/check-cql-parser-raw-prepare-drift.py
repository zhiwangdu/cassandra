#!/usr/bin/env python3
#
# Source-only drift check for CQL parser/raw prepare research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

CQL_GRAMMAR = "src/antlr/Cql.g"
PARSER_GRAMMAR = "src/antlr/Parser.g"
LEXER_GRAMMAR = "src/antlr/Lexer.g"
CQL_FRAGMENT_PARSER = "src/java/org/apache/cassandra/cql3/CQLFragmentParser.java"
ERROR_COLLECTOR = "src/java/org/apache/cassandra/cql3/ErrorCollector.java"
QUERY_PROCESSOR = "src/java/org/apache/cassandra/cql3/QueryProcessor.java"
CQL_STATEMENT = "src/java/org/apache/cassandra/cql3/CQLStatement.java"
VARIABLE_SPECIFICATIONS = "src/java/org/apache/cassandra/cql3/VariableSpecifications.java"
ABSTRACT_MARKER = "src/java/org/apache/cassandra/cql3/AbstractMarker.java"
SELECT_STATEMENT = "src/java/org/apache/cassandra/cql3/statements/SelectStatement.java"
MODIFICATION_STATEMENT = "src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java"
BATCH_STATEMENT = "src/java/org/apache/cassandra/cql3/statements/BatchStatement.java"

CQL_PARSER_TEST = "test/unit/org/apache/cassandra/cql3/CqlParserTest.java"
PREPARED_STATEMENTS_TEST = "test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java"
PREPARE_MESSAGE_TEST = "test/unit/org/apache/cassandra/transport/messages/PrepareMessageTest.java"

TARGET_DOCS = (
    "research/module-cql-parser-raw-prepare-matrix.md",
    "research/module-cql-parser-raw-prepare-drift-checker.md",
    "research/module-schema-cql-auth-native-third-round.md",
    "research/module-schema-cql-auth.md",
    "research/module-prepared-statement-compatibility-matrix.md",
    "research/flow-cql-request.md",
    "research/README.md",
    "research/notes/source-map.md",
)

EXPECTED_DISPATCH_RULES = (
    "selectStatement",
    "insertStatement",
    "updateStatement",
    "batchStatement",
    "deleteStatement",
    "useStatement",
    "truncateStatement",
    "createKeyspaceStatement",
    "createTableStatement",
    "createIndexStatement",
    "dropKeyspaceStatement",
    "dropTableStatement",
    "dropIndexStatement",
    "alterTableStatement",
    "alterKeyspaceStatement",
    "grantPermissionsStatement",
    "revokePermissionsStatement",
    "listPermissionsStatement",
    "createUserStatement",
    "alterUserStatement",
    "dropUserStatement",
    "listUsersStatement",
    "createTriggerStatement",
    "dropTriggerStatement",
    "createTypeStatement",
    "alterTypeStatement",
    "dropTypeStatement",
    "createFunctionStatement",
    "dropFunctionStatement",
    "createAggregateStatement",
    "dropAggregateStatement",
    "createRoleStatement",
    "alterRoleStatement",
    "dropRoleStatement",
    "listRolesStatement",
    "grantRoleStatement",
    "revokeRoleStatement",
    "createMaterializedViewStatement",
    "dropMaterializedViewStatement",
    "alterMaterializedViewStatement",
    "describeStatement",
    "addIdentityStatement",
    "dropIdentityStatement",
)

SCENARIO_IDS = (
    "cql_parser_wrapper_error_collection",
    "cql_parser_root_query_contract",
    "cql_parser_statement_dispatch",
    "cql_parser_bind_marker_collection",
    "cql_parser_raw_prepare_boundary",
    "cql_parser_select_prepare_planner_boundary",
    "cql_parser_modification_batch_prepare",
    "cql_parser_keyword_identity_contract",
    "cql_parser_test_coverage_surface",
)

SOURCE_TOKEN_CHECKS = {
    CQL_GRAMMAR: (
        "query returns [CQLStatement.Raw stmnt]",
        ": st=cqlStatement (';')* EOF { $stmnt = st; }",
    ),
    PARSER_GRAMMAR: (
        "protected final List<ColumnIdentifier> bindVariables = new ArrayList<ColumnIdentifier>();",
        "public AbstractMarker.Raw newBindVariables(ColumnIdentifier name)",
        "public AbstractMarker.INRaw newINBindVariables(ColumnIdentifier name)",
        "public Tuples.Raw newTupleBindVariables(ColumnIdentifier name)",
        "public Tuples.INRaw newTupleINBindVariables(ColumnIdentifier name)",
        "public Json.Marker newJsonBindVariables(ColumnIdentifier name)",
        "protected Object recoverFromMismatchedToken(IntStream input, int ttype, BitSet follow) throws RecognitionException",
        "throw new MismatchedTokenException(ttype, input);",
        "public void recover(IntStream input, RecognitionException re)",
        "cqlStatement returns [CQLStatement.Raw stmt]",
        "@after{ if (stmt != null) stmt.setBindVariables(bindVariables); }",
        "selectStatement returns [SelectStatement.RawStatement expr]",
        "insertStatement returns [ModificationStatement.Parsed expr]",
        "updateStatement returns [UpdateStatement.ParsedUpdate expr]",
        "batchStatement returns [BatchStatement.Parsed expr]",
        "addIdentityStatement returns [AddIdentityStatement stmt]",
        "dropIdentityStatement returns [DropIdentityStatement stmt]",
    ),
    LEXER_GRAMMAR: (
        "K_SELECT:      S E L E C T;",
        "K_INSERT:      I N S E R T;",
        "K_UPDATE:      U P D A T E;",
        "K_BATCH:       B A T C H;",
        "K_ADD:         A D D;",
        "K_IDENTITY:    I D E N T I T Y;",
    ),
    CQL_FRAGMENT_PARSER: (
        "public interface CQLParserFunction<R>",
        "return parseAnyUnhandled(parserFunction, input);",
        "ErrorCollector errorCollector = new ErrorCollector(input);",
        "CqlLexer lexer = new CqlLexer(stream);",
        "lexer.addErrorListener(errorCollector);",
        "CqlParser parser = new CqlParser(tokenStream);",
        "parser.addErrorListener(errorCollector);",
        "R r = parserFunction.parse(parser);",
        "errorCollector.throwFirstSyntaxError();",
    ),
    ERROR_COLLECTOR: (
        "private static final int FIRST_TOKEN_OFFSET = 10;",
        "private static final int LAST_TOKEN_OFFSET = 2;",
        "private final LinkedList<String> errorMsgs = new LinkedList<>();",
        "public void syntaxError(BaseRecognizer recognizer, String[] tokenNames, RecognitionException e)",
        "if (recognizer instanceof Parser)",
        "appendQuerySnippet((Parser) recognizer, builder);",
        "public void throwFirstSyntaxError() throws SyntaxException",
        "throw new SyntaxException(errorMsgs.getFirst());",
    ),
    QUERY_PROCESSOR: (
        "public static Prepared parseAndPrepare(String query, ClientState clientState, boolean isInternal, boolean measure) throws RequestValidationException",
        "CQLStatement.Raw raw = parseStatement(query);",
        "if (raw instanceof QualifiedStatement)",
        "fullyQualified = qualifiedStatement.isFullyQualified();",
        "qualifiedStatement.setKeyspace(clientState);",
        "CQLStatement statement = raw.prepare(clientState);",
        "statement.validate(clientState);",
        "res.pstmntSize = measurePstmnt(res);",
        "public static CQLStatement.Raw parseStatement(String queryStr) throws SyntaxException",
        "return CQLFragmentParser.parseAnyUnhandled(CqlParser::query, queryStr);",
        'logger.error(String.format("The statement: [%s] could not be parsed.", queryStr), re);',
        "public static <T extends CQLStatement.Raw> T parseStatement(String queryStr, Class<T> klass, String type) throws SyntaxException",
        '"Invalid query, must be a " + type + " statement but was: " + stmt.getClass()',
    ),
    CQL_STATEMENT: (
        "public static abstract class Raw",
        "protected VariableSpecifications bindVariables;",
        "public void setBindVariables(List<ColumnIdentifier> variables)",
        "bindVariables = new VariableSpecifications(variables);",
        "public abstract CQLStatement prepare(ClientState state);",
    ),
    VARIABLE_SPECIFICATIONS: (
        "private final List<ColumnIdentifier> variableNames;",
        "private final List<ColumnSpecification> specs;",
        "private final ColumnMetadata[] targetColumns;",
        "this.specs = Arrays.asList(new ColumnSpecification[variableNames.size()]);",
        "public List<ColumnSpecification> getBindVariables()",
        "public short[] getPartitionKeyBindVariableIndexes(TableMetadata metadata)",
        "public void add(int bindIndex, ColumnSpecification spec)",
        "specs.set(bindIndex, spec);",
    ),
    ABSTRACT_MARKER: (
        "protected final int bindIndex;",
        "protected final ColumnSpecification receiver;",
        "public void collectMarkerSpecification(VariableSpecifications boundNames)",
        "boundNames.add(bindIndex, receiver);",
        "public static class Raw extends Term.Raw",
        "return new Lists.Marker(bindIndex, receiver);",
        "return new Sets.Marker(bindIndex, receiver);",
        "return new Maps.Marker(bindIndex, receiver);",
        "return new UserTypes.Marker(bindIndex, receiver);",
        "return new Constants.Marker(bindIndex, receiver);",
    ),
    SELECT_STATEMENT: (
        "public static class RawStatement extends QualifiedStatement",
        "public SelectStatement prepare(ClientState state)",
        "return prepare(state, false);",
        "TableMetadata table = Schema.instance.validateTable(keyspace(), name());",
        "List<Selectable> selectables = RawSelector.toSelectables(selectClause, table);",
        "StatementRestrictions restrictions = prepareRestrictions(state, table, bindVariables, orderings, containsOnlyStaticColumns, forView);",
        "Selection selection = prepareSelection(table,",
        "checkNeedsFiltering(table, restrictions);",
        "prepareLimit(bindVariables, limit, keyspace(), limitReceiver())",
    ),
    MODIFICATION_STATEMENT: (
        "public static abstract class Parsed extends QualifiedStatement",
        "public ModificationStatement prepare(ClientState state)",
        "return prepare(state, bindVariables);",
        "TableMetadata metadata = Schema.instance.validateTable(keyspace(), name());",
        "Attributes preparedAttributes = attrs.prepare(keyspace(), name());",
        "preparedAttributes.collectMarkerSpecification(bindVariables);",
        "Conditions preparedConditions = prepareConditions(metadata, bindVariables);",
        "ColumnCondition condition = entry.right.prepare(keyspace(), def, metadata);",
        "condition.collectMarkerSpecification(bindVariables);",
        "protected abstract ModificationStatement prepareInternal(ClientState state,",
    ),
    BATCH_STATEMENT: (
        "public BatchStatement prepare(ClientState state)",
        "parsedStatements.forEach(s -> statements.add(s.prepare(state, bindVariables)));",
        'Attributes prepAttrs = attrs.prepare("[batch]", "[batch]");',
        "prepAttrs.collectMarkerSpecification(bindVariables);",
        "BatchStatement batchStatement = new BatchStatement(type, bindVariables, statements, prepAttrs);",
        "batchStatement.validate();",
    ),
    CQL_PARSER_TEST: (
        "public void testAddErrorListener()",
        "public void testRemoveErrorListener()",
        "public void testDuplicateProperties()",
        "parser.addErrorListener(firstCounter);",
        "parser.removeErrorListener(secondCounter);",
        "assertNull(parser.query());",
        "parseAndCountErrors(\"properties = { 'foo' : 'value1', 'foo': 'value2' };\", 1",
    ),
    PREPARED_STATEMENTS_TEST: (
        "public void prepareAndExecuteWithCustomExpressions()",
        "PreparedStatement prepared1 = session.prepare",
        "PreparedStatement prepared2 = session.prepare",
        'session.prepare(String.format("SELECT * FROM %s.%s WHERE expr(?,',
        'assertEquals("Bind variables cannot be used for index names", e.getMessage());',
    ),
    PREPARE_MESSAGE_TEST: (
        "public void testEncodeThenDecode()",
        'new PrepareMessage("SELECT * FROM keyspace.tbl WHERE name=',
        "encodeThenDecode(origin, ProtocolVersion.V5);",
        "Assert.assertEquals(origin.toString(), newMessage.toString());",
    ),
}

DOC_REQUIRED_TOKENS = (
    "module-cql-parser-raw-prepare-matrix.md",
    "module-cql-parser-raw-prepare-drift-checker.md",
    "check-cql-parser-raw-prepare-drift.py",
    CQL_GRAMMAR,
    PARSER_GRAMMAR,
    LEXER_GRAMMAR,
    CQL_FRAGMENT_PARSER,
    ERROR_COLLECTOR,
    QUERY_PROCESSOR,
    CQL_STATEMENT,
    VARIABLE_SPECIFICATIONS,
    ABSTRACT_MARKER,
    SELECT_STATEMENT,
    MODIFICATION_STATEMENT,
    BATCH_STATEMENT,
    CQL_PARSER_TEST,
    PREPARED_STATEMENTS_TEST,
    PREPARE_MESSAGE_TEST,
    "CQLFragmentParser.parseAnyUnhandled",
    "CqlParser::query",
    "CQLStatement.Raw",
    "VariableSpecifications",
    "AbstractMarker.Raw",
    "SelectStatement.RawStatement",
    "ModificationStatement.Parsed",
    "BatchStatement.Parsed",
    "prepared_statements_cache_size",
    "force_new_prepared_statement_behaviour",
    "43",
    "generated dispatch",
) + SCENARIO_IDS + EXPECTED_DISPATCH_RULES


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def parser_dispatch_entries() -> tuple[str, ...]:
    text = read(PARSER_GRAMMAR)
    match = re.search(r"cqlStatement returns \[CQLStatement\.Raw stmt\](.*?);\n\n/\*", text, re.S)
    if not match:
        raise ValueError("Could not locate Parser.g cqlStatement dispatch")
    body = match.group(1)
    return tuple(re.findall(r"(?:^|\n)\s*(?::|\|)\s*st\d+\s*=\s*([A-Za-z0-9_]+)", body))


def source_checks() -> list[Check]:
    checks = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        for token in tokens:
            checks.append(Check(f"source token {token[:72]!r}", path, token in text))

    entries = parser_dispatch_entries()
    checks.append(Check("Parser.g dispatch entries match expected", PARSER_GRAMMAR, entries == EXPECTED_DISPATCH_RULES))
    checks.append(Check("Parser.g dispatch entry count is 43", PARSER_GRAMMAR, len(entries) == 43))
    checks.append(Check("Parser.g dispatch entries are unique", PARSER_GRAMMAR, len(entries) == len(set(entries))))
    return checks


def doc_checks() -> list[Check]:
    docs = {}
    checks = []
    for path in TARGET_DOCS:
        doc_path = REPO_ROOT / path
        exists = doc_path.exists()
        checks.append(Check("doc exists", path, exists))
        docs[path] = doc_path.read_text(encoding="utf-8") if exists else ""

    combined = "\n".join(docs.values())
    for token in DOC_REQUIRED_TOKENS:
        checks.append(Check(f"doc token {token}", "research docs", token in combined))

    readme = docs["research/README.md"]
    source_map = docs["research/notes/source-map.md"]
    for token in ("module-cql-parser-raw-prepare-matrix.md", "module-cql-parser-raw-prepare-drift-checker.md", "check-cql-parser-raw-prepare-drift.py"):
        checks.append(Check(f"README links {token}", "research/README.md", token in readme))
        checks.append(Check(f"source-map links {token}", "research/notes/source-map.md", token in source_map))

    matrix = docs["research/module-cql-parser-raw-prepare-matrix.md"]
    for scenario_id in SCENARIO_IDS:
        checks.append(Check(f"matrix scenario {scenario_id}", "research/module-cql-parser-raw-prepare-matrix.md", documented(scenario_id, matrix)))
    for rule in EXPECTED_DISPATCH_RULES:
        checks.append(Check(f"matrix dispatch rule {rule}", "research/module-cql-parser-raw-prepare-matrix.md", documented(rule, matrix)))
    return checks


def test_gap_checks() -> list[Check]:
    test_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "test/unit/org/apache/cassandra/cql3").glob("*.java")
    )
    gap_still_open = "EXPECTED_DISPATCH_RULES" not in test_text and "cqlStatement dispatch" not in test_text
    docs = "\n".join(read(path) for path in TARGET_DOCS if (REPO_ROOT / path).exists())
    return [
        Check("generated dispatch gap remains explicit", "test/unit/org/apache/cassandra/cql3", gap_still_open),
        Check("generated dispatch gap documented", "research docs", "generated dispatch" in docs and "cql_parser_test_coverage_surface" in docs),
    ]


def check() -> tuple[bool, list[Check]]:
    checks = []
    checks.extend(source_checks())
    checks.extend(doc_checks())
    checks.extend(test_gap_checks())
    return all(item.ok for item in checks), checks


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Check CQL parser/raw prepare research drift")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args(argv)

    ok, checks = check()
    if args.json:
        print(json.dumps({"ok": ok, "checks": [item.__dict__ for item in checks]}, indent=2, sort_keys=True))
    else:
        for item in checks:
            if not item.ok:
                print(f"FAIL {item.name} [{item.source}]")
        if ok:
            print(f"OK CQL parser/raw prepare drift checks passed ({len(checks)} checks)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
