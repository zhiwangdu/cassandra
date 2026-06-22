#!/usr/bin/env python3
#
# Source-only drift check for Cassandra system table column contracts.

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DOC = "research/module-system-table-column-contract.md"


@dataclass(frozen=True)
class SourceSpec:
    keyspace: str
    source: str
    constant_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableContract:
    keyspace: str
    table: str
    source: str
    columns: tuple[str, ...]
    primary_key: str
    deprecated_columns: tuple[str, ...]

    @property
    def full_name(self) -> str:
        return f"{self.keyspace}.{self.table}"

    @property
    def scenario_id(self) -> str:
        suffix = re.sub(r"[^a-z0-9]+", "_", f"{self.keyspace}_{self.table.lower()}").strip("_")
        return f"system_table_column_{suffix}"


SOURCES = (
    SourceSpec("system", "src/java/org/apache/cassandra/db/SystemKeyspace.java"),
    SourceSpec(
        "system_schema",
        "src/java/org/apache/cassandra/schema/SchemaKeyspace.java",
        ("src/java/org/apache/cassandra/schema/SchemaKeyspaceTables.java",),
    ),
    SourceSpec("system_traces", "src/java/org/apache/cassandra/tracing/TraceKeyspace.java"),
    SourceSpec("system_auth", "src/java/org/apache/cassandra/auth/AuthKeyspace.java"),
    SourceSpec("system_distributed", "src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java"),
)


def strip_comments(text: str) -> str:
    result: list[str] = []
    index = 0
    in_string = False
    in_char = False
    in_line_comment = False
    in_block_comment = False

    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
                result.append(char)
            else:
                result.append(" ")
            index += 1
            continue

        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
                result.extend("  ")
                index += 2
            else:
                result.append("\n" if char == "\n" else " ")
                index += 1
            continue

        if in_string:
            result.append(char)
            if char == "\\" and next_char:
                result.append(next_char)
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue

        if in_char:
            result.append(char)
            if char == "\\" and next_char:
                result.append(next_char)
                index += 2
                continue
            if char == "'":
                in_char = False
            index += 1
            continue

        if char == "/" and next_char == "/":
            in_line_comment = True
            result.extend("  ")
            index += 2
            continue

        if char == "/" and next_char == "*":
            in_block_comment = True
            result.extend("  ")
            index += 2
            continue

        if char == '"':
            in_string = True
        elif char == "'":
            in_char = True
        result.append(char)
        index += 1

    return "".join(result)


def find_matching(text: str, open_index: int, open_char: str = "(", close_char: str = ")") -> int:
    depth = 0
    in_string = False
    in_char = False
    index = open_index

    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""

        if in_string:
            if char == "\\" and next_char:
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue

        if in_char:
            if char == "\\" and next_char:
                index += 2
                continue
            if char == "'":
                in_char = False
            index += 1
            continue

        if char == '"':
            in_string = True
        elif char == "'":
            in_char = True
        elif char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index
        index += 1

    raise ValueError(f"Unclosed {open_char} at offset {open_index}")


def split_top_level(text: str, delimiter: str) -> list[str]:
    parts: list[str] = []
    start = 0
    paren_depth = 0
    angle_depth = 0
    bracket_depth = 0
    brace_depth = 0
    in_string = False
    in_char = False
    index = 0

    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""

        if in_string:
            if char == "\\" and next_char:
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue

        if in_char:
            if char == "\\" and next_char:
                index += 2
                continue
            if char == "'":
                in_char = False
            index += 1
            continue

        if char == '"':
            in_string = True
        elif char == "'":
            in_char = True
        elif char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth -= 1
        elif char == "<":
            angle_depth += 1
        elif char == ">":
            angle_depth -= 1
        elif char == "[":
            bracket_depth += 1
        elif char == "]":
            bracket_depth -= 1
        elif char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth -= 1
        elif (
            char == delimiter
            and paren_depth == 0
            and angle_depth == 0
            and bracket_depth == 0
            and brace_depth == 0
        ):
            parts.append(text[start:index].strip())
            start = index + 1
        index += 1

    parts.append(text[start:].strip())
    return [part for part in parts if part]


def string_constants(text: str) -> dict[str, str]:
    constants: dict[str, str] = {}
    pattern = re.compile(r"\bstatic\s+final\s+String\s+([A-Za-z0-9_]+)\s*=\s*(\"(?:\\.|[^\"\\])*\")\s*;")
    for name, literal in pattern.findall(text):
        constants[name] = ast.literal_eval(literal)
    return constants


def eval_java_string_expr(expr: str, constants: dict[str, str]) -> str:
    values: list[str] = []
    for part in split_top_level(expr, "+"):
        token = part.strip()
        if not token:
            continue
        if token.startswith('"') and token.endswith('"'):
            values.append(ast.literal_eval(token))
        elif token in constants:
            values.append(constants[token])
        elif token.startswith("(") and token.endswith(")") and "?" in token:
            values.append(eval_java_conditional_string(token[1:-1], constants))
        else:
            raise ValueError(f"unsupported Java string expression token: {token}")
    return "".join(values)


def eval_java_conditional_string(expr: str, constants: dict[str, str]) -> str:
    condition_and_true = split_top_level(expr, "?")
    if len(condition_and_true) != 2:
        raise ValueError(f"unsupported Java conditional string expression: {expr}")

    true_and_false = split_top_level(condition_and_true[1], ":")
    if len(true_and_false) != 2:
        raise ValueError(f"unsupported Java conditional string expression: {expr}")

    true_value = eval_java_string_expr(true_and_false[0], constants)
    false_value = eval_java_string_expr(true_and_false[1], constants)
    if false_value:
        raise ValueError(f"unsupported non-empty false branch in Java conditional string expression: {expr}")

    # Capture the maximum source ABI for optional feature-flag columns.
    return true_value


def resolve_table_name(expr: str, constants: dict[str, str]) -> str:
    token = expr.strip()
    if token.startswith('"') and token.endswith('"'):
        return ast.literal_eval(token)
    if token in constants:
        return constants[token]
    raise ValueError(f"unsupported table name expression: {token}")


def normalize_primary_key(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip())
    normalized = re.sub(r"(?i)PRIMARY\s+KEY\s*\(", "PRIMARY KEY (", normalized)
    normalized = re.sub(r"\s*,\s*", ", ", normalized)
    normalized = re.sub(r"\(\s+", "(", normalized)
    normalized = re.sub(r"\s+\)", ")", normalized)
    return normalized


def parse_create_table(cql: str) -> tuple[tuple[str, ...], str]:
    match = re.search(r"(?i)\bCREATE\s+TABLE\b", cql)
    if not match:
        raise ValueError(f"not a CREATE TABLE statement: {cql}")

    open_index = cql.find("(", match.end())
    if open_index < 0:
        raise ValueError(f"CREATE TABLE without column body: {cql}")
    close_index = find_matching(cql, open_index)
    body = cql[open_index + 1:close_index]

    columns: list[str] = []
    primary_key = ""
    for entry in split_top_level(body, ","):
        normalized = re.sub(r"\s+", " ", entry.strip())
        if re.match(r"(?i)^PRIMARY\s+KEY", normalized):
            primary_key = normalize_primary_key(normalized)
            continue
        column_match = re.match(r'"([^"]+)"|([A-Za-z0-9_]+)', normalized)
        if not column_match:
            raise ValueError(f"Could not parse column entry: {entry}")
        columns.append(column_match.group(1) or column_match.group(2))

    if not primary_key:
        raise ValueError(f"CREATE TABLE without PRIMARY KEY: {cql}")

    return tuple(columns), primary_key


def deprecated_columns_after_call(text: str, call_end: int) -> tuple[str, ...]:
    statement_end = text.find(";", call_end)
    if statement_end < 0:
        return ()
    chain = text[call_end:statement_end]
    return tuple(re.findall(r"\.recordDeprecatedSystemColumn\s*\(\s*\"([^\"]+)\"", chain))


def extract_contracts(spec: SourceSpec) -> list[TableContract]:
    source_path = REPO_ROOT / spec.source
    text = strip_comments(source_path.read_text(encoding="utf-8"))
    constants = string_constants(text)
    for constant_source in spec.constant_sources:
        constants.update(string_constants(strip_comments((REPO_ROOT / constant_source).read_text(encoding="utf-8"))))
    contracts: list[TableContract] = []

    for match in re.finditer(r"(?<![A-Za-z0-9_.])parse\s*\(", text):
        open_index = text.find("(", match.start())
        close_index = find_matching(text, open_index)
        args = split_top_level(text[open_index + 1:close_index], ",")
        if len(args) < 3:
            continue

        try:
            table = resolve_table_name(args[0], constants)
            cql = eval_java_string_expr(args[2], constants)
        except ValueError:
            continue

        if not re.search(r"(?i)\bCREATE\s+TABLE\b", cql):
            continue

        columns, primary_key = parse_create_table(cql)
        contracts.append(
            TableContract(
                keyspace=spec.keyspace,
                table=table,
                source=spec.source,
                columns=columns,
                primary_key=primary_key,
                deprecated_columns=deprecated_columns_after_call(text, close_index),
            )
        )

    return contracts


def extract_all_contracts() -> list[TableContract]:
    contracts: list[TableContract] = []
    for spec in SOURCES:
        contracts.extend(extract_contracts(spec))
    return contracts


def parse_contract_doc() -> dict[str, dict[str, object]]:
    doc_path = REPO_ROOT / CONTRACT_DOC
    text = doc_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^### `(?P<full_name>[^`]+)` \(`(?P<scenario>[^`]+)`\)\n(?P<body>.*?)(?=^### `|\Z)",
        re.M | re.S,
    )
    sections: dict[str, dict[str, object]] = {}
    for match in pattern.finditer(text):
        body = match.group("body")
        columns_match = re.search(r"^- Columns: (?P<value>.+)$", body, re.M)
        primary_key_match = re.search(r"^- Primary key: `(?P<value>[^`]+)`", body, re.M)
        deprecated_match = re.search(r"^- Deprecated columns: (?P<value>.+)$", body, re.M)

        columns = tuple(re.findall(r"`([^`]+)`", columns_match.group("value"))) if columns_match else ()
        deprecated_columns = tuple(re.findall(r"`([^`]+)`", deprecated_match.group("value"))) if deprecated_match else ()
        sections[match.group("scenario")] = {
            "full_name": match.group("full_name"),
            "columns": columns,
            "primary_key": normalize_primary_key(primary_key_match.group("value")) if primary_key_match else "",
            "deprecated_columns": deprecated_columns,
        }
    return sections


def compare_contracts(contracts: list[TableContract], doc_sections: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for contract in contracts:
        section = doc_sections.get(contract.scenario_id)
        problems: list[str] = []
        if section is None:
            problems.append("missing scenario section")
            section = {}
        else:
            if section.get("full_name") != contract.full_name:
                problems.append(f"full name {section.get('full_name')!r} != {contract.full_name!r}")
            if tuple(section.get("columns", ())) != contract.columns:
                problems.append(
                    "columns "
                    + json.dumps(section.get("columns", ()), ensure_ascii=False)
                    + " != "
                    + json.dumps(contract.columns, ensure_ascii=False)
                )
            if section.get("primary_key") != contract.primary_key:
                problems.append(f"primary key {section.get('primary_key')!r} != {contract.primary_key!r}")
            if tuple(section.get("deprecated_columns", ())) != contract.deprecated_columns:
                problems.append(
                    "deprecated columns "
                    + json.dumps(section.get("deprecated_columns", ()), ensure_ascii=False)
                    + " != "
                    + json.dumps(contract.deprecated_columns, ensure_ascii=False)
                )

        results.append(
            {
                "keyspace": contract.keyspace,
                "table": contract.table,
                "scenario_id": contract.scenario_id,
                "source": contract.source,
                "columns": contract.columns,
                "primary_key": contract.primary_key,
                "deprecated_columns": contract.deprecated_columns,
                "problems": problems,
            }
        )
    return results


def markdown_for_contracts(contracts: list[TableContract]) -> str:
    lines: list[str] = []
    for contract in contracts:
        lines.append(f"### `{contract.full_name}` (`{contract.scenario_id}`)")
        lines.append(f"- Source: `{contract.source}`")
        lines.append("- Columns: " + ", ".join(f"`{column}`" for column in contract.columns))
        lines.append(f"- Primary key: `{contract.primary_key}`")
        if contract.deprecated_columns:
            lines.append("- Deprecated columns: " + ", ".join(f"`{column}`" for column in contract.deprecated_columns))
        else:
            lines.append("- Deprecated columns: none")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check system table column contracts in research docs.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable check results")
    parser.add_argument("--dump-markdown", action="store_true", help="emit markdown sections parsed from source")
    args = parser.parse_args()

    try:
        contracts = extract_all_contracts()
        if args.dump_markdown:
            print(markdown_for_contracts(contracts))
            return 0

        results = compare_contracts(contracts, parse_contract_doc())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    ok = all(not result["problems"] for result in results)
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        by_keyspace: dict[str, list[dict[str, object]]] = {}
        for result in results:
            by_keyspace.setdefault(str(result["keyspace"]), []).append(result)
        for keyspace, keyspace_results in by_keyspace.items():
            missing = [result for result in keyspace_results if result["problems"]]
            status = "OK" if not missing else "MISMATCH"
            print(f"{status} {keyspace}: {len(keyspace_results)} table column contracts")
            for result in missing:
                print(f"  {result['table']} ({result['scenario_id']}):")
                for problem in result["problems"]:
                    print(f"    - {problem}")
        if ok:
            print("System table column contracts are in sync with parsed source CQL definitions.")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
