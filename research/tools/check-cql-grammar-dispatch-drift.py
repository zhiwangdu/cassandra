#!/usr/bin/env python3
#
# Source-only drift check for CQL grammar dispatch exhaustiveness research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

BUILD_XML = "build.xml"
CQL_GRAMMAR = "src/antlr/Cql.g"
PARSER_GRAMMAR = "src/antlr/Parser.g"
LEXER_GRAMMAR = "src/antlr/Lexer.g"
RAW_PREPARE_CHECKER = "research/tools/check-cql-parser-raw-prepare-drift.py"

TARGET_DOCS = (
    "research/module-cql-grammar-dispatch-exhaustiveness-matrix.md",
    "research/module-cql-grammar-dispatch-drift-checker.md",
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
    "cql_grammar_generation_target_contract",
    "cql_grammar_source_include_contract",
    "cql_grammar_generated_artifact_boundary",
    "cql_dispatch_parser_rule_contract",
    "cql_dispatch_rule_definition_contract",
    "cql_dispatch_raw_return_contract",
    "cql_dispatch_bind_marker_after_contract",
    "cql_dispatch_keyword_token_contract",
    "cql_dispatch_statement_family_test_baseline",
    "cql_dispatch_raw_prepare_checker_boundary",
    "cql_dispatch_exhaustiveness_test_gap",
)

SOURCE_TOKEN_CHECKS = {
    BUILD_XML: (
        '<target name="check-gen-cql3-grammar">',
        'targetfile="${build.src.gen-java}/org/apache/cassandra/cql3/Cql.tokens"',
        '<srcfiles dir="${build.src.antlr}">',
        '<include name="*.g"/>',
        '<target name="gen-cql3-grammar" depends="check-gen-cql3-grammar" unless="cql3current">',
        '<java classname="org.antlr.Tool"',
        '<arg value="${build.src.antlr}/Cql.g" />',
        '<arg value="${build.src.gen-java}/org/apache/cassandra/cql3/" />',
        '<arg value="-Xmaxinlinedfastates"/>',
    ),
    CQL_GRAMMAR: (
        "grammar Cql;",
        "import Parser,Lexer;",
        "query returns [CQLStatement.Raw stmnt]",
        ": st=cqlStatement (';')* EOF { $stmnt = st; }",
        "public void addErrorListener(ErrorListener listener)",
        "protected Object recoverFromMismatchedToken(IntStream input, int ttype, BitSet follow) throws RecognitionException",
    ),
    PARSER_GRAMMAR: (
        "cqlStatement returns [CQLStatement.Raw stmt]",
        "@after{ if (stmt != null) stmt.setBindVariables(bindVariables); }",
        "st1= selectStatement",
        "st43=dropIdentityStatement",
        "protected final List<ColumnIdentifier> bindVariables = new ArrayList<ColumnIdentifier>();",
    ),
    LEXER_GRAMMAR: (
        "When adding a new unreserved keyword, add entry to unreserved keywords in Parser.g.",
        "K_SELECT:      S E L E C T;",
        "K_MATERIALIZED:M A T E R I A L I Z E D;",
        "K_IDENTITY:    I D E N T I T Y;",
    ),
    RAW_PREPARE_CHECKER: (
        "EXPECTED_DISPATCH_RULES = (",
        "parser_dispatch_entries()",
        "Parser.g dispatch entries match expected",
        "Parser.g dispatch entry count is 43",
    ),
}

TEST_TOKEN_CHECKS = {
    "test/unit/org/apache/cassandra/cql3/CqlParserTest.java": (
        "public void testAddErrorListener()",
        "public void testRemoveErrorListener()",
        "public void testDuplicateProperties()",
        "CqlLexer lexer = new CqlLexer(stream);",
        "CqlParser parser = new CqlParser(tokenStream);",
    ),
    "test/unit/org/apache/cassandra/cql3/KeywordTestBase.java": (
        "Arrays.stream(CqlParser.tokenNames)",
        ".filter(k -> k.startsWith(\"K_\"))",
        "ReservedKeywords.isReserved(keyword)",
        "schemaChange(createStatement);",
    ),
    "test/unit/org/apache/cassandra/cql3/ReservedKeywordsTest.java": (
        "for (String reservedWord : ReservedKeywords.reservedKeywords)",
        "QueryProcessor.parseStatement(String.format(\"ALTER TABLE ks.t ADD %s TEXT\", reservedWord));",
        "SyntaxException",
    ),
    "test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java": (
        "ADD IDENTITY 'id1' TO ROLE",
        "DROP IDENTITY 'simpleUserId'",
        "DROP IDENTITY IF EXISTS 'nonExistentUserId'",
    ),
}

DOC_TOKEN_CHECKS = {
    "research/module-cql-grammar-dispatch-exhaustiveness-matrix.md": (
        "Parser.g",
        "build.xml",
        "gen-cql3-grammar",
        "CqlParser.java",
        "cql_dispatch_exhaustiveness_test_gap",
    ),
    "research/module-cql-grammar-dispatch-drift-checker.md": (
        "check-cql-grammar-dispatch-drift.py",
        "cql_dispatch_parser_rule_contract",
        "cql_dispatch_exhaustiveness_test_gap",
    ),
    "research/README.md": (
        "module-cql-grammar-dispatch-exhaustiveness-matrix.md",
        "module-cql-grammar-dispatch-drift-checker.md",
        "check-cql-grammar-dispatch-drift.py",
    ),
    "research/notes/source-map.md": (
        "CQL grammar dispatch exhaustiveness",
        "module-cql-grammar-dispatch-exhaustiveness-matrix.md",
        "check-cql-grammar-dispatch-drift.py",
    ),
}

EXHAUSTIVENESS_MARKERS = (
    re.compile(r"EXPECTED_DISPATCH_RULES"),
    re.compile(r"cqlStatement dispatch"),
    re.compile(r"selectStatement.*dropIdentityStatement", re.S),
    re.compile(r"Parser\.g.*dispatch", re.S),
)


@dataclass
class Finding:
    kind: str
    path: str
    detail: str


def read_text(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def check_tokens(kind: str, checks: dict[str, tuple[str, ...]]) -> list[Finding]:
    findings: list[Finding] = []
    for path, tokens in checks.items():
        full_path = REPO_ROOT / path
        if not full_path.exists():
            findings.append(Finding(kind, path, "missing file"))
            continue
        text = full_path.read_text(encoding="utf-8")
        for token in tokens:
            if token not in text:
                findings.append(Finding(kind, path, f"missing token: {token}"))
    return findings


def parser_dispatch_entries() -> tuple[str, ...]:
    text = read_text(PARSER_GRAMMAR)
    match = re.search(r"cqlStatement returns \[CQLStatement\.Raw stmt\](.*?);\n\n/\*", text, re.S)
    if not match:
        raise ValueError("Could not locate Parser.g cqlStatement dispatch")
    body = match.group(1)
    return tuple(re.findall(r"(?:^|\n)\s*(?::|\|)\s*st\d+\s*=\s*([A-Za-z0-9_]+)", body))


def parser_rule_return_types() -> dict[str, str]:
    text = read_text(PARSER_GRAMMAR)
    return {
        name.strip(): returns.strip()
        for name, returns in re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+returns\s+\[([^\]]+)\]", text, re.M)
    }


def check_dispatch_contract() -> tuple[list[Finding], dict[str, str], tuple[str, ...]]:
    findings: list[Finding] = []
    entries = parser_dispatch_entries()
    return_types = parser_rule_return_types()

    if entries != EXPECTED_DISPATCH_RULES:
        findings.append(
            Finding(
                "dispatch",
                PARSER_GRAMMAR,
                f"dispatch entries changed: expected {len(EXPECTED_DISPATCH_RULES)}, got {len(entries)}",
            )
        )
    if len(entries) != 43:
        findings.append(Finding("dispatch", PARSER_GRAMMAR, f"expected 43 dispatch entries, got {len(entries)}"))
    if len(entries) != len(set(entries)):
        findings.append(Finding("dispatch", PARSER_GRAMMAR, "dispatch entries are not unique"))

    for entry in entries:
        if entry not in return_types:
            findings.append(Finding("dispatch", PARSER_GRAMMAR, f"missing rule definition for {entry}"))

    for entry in EXPECTED_DISPATCH_RULES:
        if entry not in return_types:
            findings.append(Finding("dispatch", PARSER_GRAMMAR, f"expected rule definition missing: {entry}"))

    return findings, return_types, entries


def check_generated_artifact_boundary() -> list[Finding]:
    tracked = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in REPO_ROOT.rglob("CqlParser.java")
        if ".git" not in path.parts
    ]
    tracked += [
        path.relative_to(REPO_ROOT).as_posix()
        for path in REPO_ROOT.rglob("CqlLexer.java")
        if ".git" not in path.parts
    ]
    return [Finding("generated", path, "generated CQL parser artifact is present; update generated artifact boundary") for path in sorted(tracked)]


def check_gap_candidates() -> list[Finding]:
    findings: list[Finding] = []
    for base in ("test/unit", "test/distributed"):
        root = REPO_ROOT / base
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.java")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            text = path.read_text(encoding="utf-8")
            if rel.endswith("CqlParserTest.java") and "selectStatement" not in text:
                continue
            if any(pattern.search(text) for pattern in EXHAUSTIVENESS_MARKERS):
                findings.append(
                    Finding(
                        "gap",
                        rel,
                        "possible CQL dispatch exhaustiveness test exists; update cql_dispatch_exhaustiveness_test_gap",
                    )
                )
    return findings


def check_docs() -> list[Finding]:
    findings = check_tokens("doc", DOC_TOKEN_CHECKS)
    for path in TARGET_DOCS:
        full_path = REPO_ROOT / path
        if not full_path.exists():
            findings.append(Finding("doc", path, "missing file"))
            continue
        text = full_path.read_text(encoding="utf-8")
        for scenario_id in SCENARIO_IDS:
            if scenario_id not in text:
                findings.append(Finding("doc", path, f"missing scenario id: {scenario_id}"))
    matrix_text = read_text("research/module-cql-grammar-dispatch-exhaustiveness-matrix.md")
    for rule in EXPECTED_DISPATCH_RULES:
        if rule not in matrix_text:
            findings.append(Finding("doc", "research/module-cql-grammar-dispatch-exhaustiveness-matrix.md", f"missing dispatch rule: {rule}"))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="emit machine-readable result")
    args = parser.parse_args()

    dispatch_findings, return_types, entries = check_dispatch_contract()
    findings = (
        check_tokens("source", SOURCE_TOKEN_CHECKS)
        + check_tokens("test", TEST_TOKEN_CHECKS)
        + dispatch_findings
        + check_generated_artifact_boundary()
        + check_docs()
        + check_gap_candidates()
    )

    result = {
        "ok": not findings,
        "dispatch_entries": list(entries),
        "dispatch_count": len(entries),
        "rule_definitions": {rule: return_types.get(rule) for rule in entries},
        "source_checks": sum(len(tokens) for tokens in SOURCE_TOKEN_CHECKS.values()),
        "test_checks": sum(len(tokens) for tokens in TEST_TOKEN_CHECKS.values()),
        "doc_checks": sum(len(tokens) for tokens in DOC_TOKEN_CHECKS.values()) + len(TARGET_DOCS) * (len(SCENARIO_IDS) + len(EXPECTED_DISPATCH_RULES)),
        "scenarios": len(SCENARIO_IDS),
        "findings": [finding.__dict__ for finding in findings],
    }

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif findings:
        print("CQL grammar dispatch drift check failed:", file=sys.stderr)
        for finding in findings:
            print(f"- [{finding.kind}] {finding.path}: {finding.detail}", file=sys.stderr)
    else:
        print(
            "OK CQL grammar dispatch drift checks passed "
            f"({result['dispatch_count']} dispatch entries, "
            f"{len(result['rule_definitions'])} rule definitions, "
            f"{result['source_checks']} source checks, "
            f"{result['test_checks']} test checks, "
            f"{result['doc_checks']} doc checks, "
            f"{result['scenarios']} scenarios)"
        )

    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
