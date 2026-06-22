#!/usr/bin/env python3
#
# Source-only drift check for Cassandra system table research docs.

import argparse
import glob
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Registry:
    keyspace: str
    source: str
    symbols: tuple[str, ...]
    docs: tuple[str, ...]


REGISTRIES = (
    Registry(
        keyspace="system",
        source="src/java/org/apache/cassandra/db/SystemKeyspace.java",
        symbols=("TABLE_NAMES",),
        docs=(
            "research/module-system-tables.md",
            "research/module-system-tables-core-matrix.md",
            "research/module-schema-cql-auth-native-deep-dive.md",
            "research/module-startup-bootstrap.md",
        ),
    ),
    Registry(
        keyspace="system_schema",
        source="src/java/org/apache/cassandra/schema/SchemaKeyspaceTables.java",
        symbols=("ALL",),
        docs=(
            "research/module-system-tables.md",
            "research/module-schema-cql-auth-native-deep-dive.md",
            "research/module-schema-cql-auth-native-third-round.md",
        ),
    ),
    Registry(
        keyspace="system_traces",
        source="src/java/org/apache/cassandra/tracing/TraceKeyspace.java",
        symbols=("TABLE_NAMES",),
        docs=(
            "research/module-system-tables.md",
            "research/module-system-tables-core-matrix.md",
            "research/module-tracing-native-cqlsh.md",
        ),
    ),
    Registry(
        keyspace="system_auth",
        source="src/java/org/apache/cassandra/auth/AuthKeyspace.java",
        symbols=("TABLE_NAMES",),
        docs=(
            "research/module-system-tables.md",
            "research/module-schema-cql-auth-native-deep-dive.md",
            "research/module-permission-role-matrix.md",
        ),
    ),
    Registry(
        keyspace="system_distributed",
        source="src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java",
        symbols=("TABLE_NAMES", "TABLE_NAMES_WITH_AUTO_REPAIR"),
        docs=(
            "research/module-system-tables.md",
            "research/module-system-distributed-state-matrix.md",
            "research/module-repair-streaming-autorepair-netty.md",
        ),
    ),
)


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)
    return text


def string_constants(text: str) -> dict[str, str]:
    pattern = re.compile(r"\bstatic\s+final\s+String\s+([A-Za-z0-9_]+)\s*=\s*\"([^\"]+)\"")
    return {name: value for name, value in pattern.findall(text)}


def find_immutable_args(text: str, symbol: str) -> list[str]:
    pattern = re.compile(rf"\b{re.escape(symbol)}\b\s*=\s*Immutable(?:Set|List)\.of\s*\(")
    match = pattern.search(text)
    if not match:
        raise ValueError(f"Could not find ImmutableSet/List declaration for {symbol}")

    start = match.end() - 1
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                body = text[start + 1:index]
                return [part.strip() for part in body.split(",") if part.strip()]
    raise ValueError(f"Unclosed ImmutableSet/List declaration for {symbol}")


def resolve_args(args: list[str], constants: dict[str, str], source: str, symbol: str) -> list[str]:
    names: list[str] = []
    unresolved: list[str] = []

    for arg in args:
        if arg.startswith('"') and arg.endswith('"'):
            names.append(arg[1:-1])
        elif arg in constants:
            names.append(constants[arg])
        else:
            unresolved.append(arg)

    if unresolved:
        raise ValueError(f"{source}:{symbol} has unresolved entries: {', '.join(unresolved)}")

    return sorted(set(names))


def extract_registry(registry: Registry) -> list[str]:
    source_path = REPO_ROOT / registry.source
    text = strip_comments(source_path.read_text(encoding="utf-8"))
    constants = string_constants(text)

    names: set[str] = set()
    for symbol in registry.symbols:
        args = find_immutable_args(text, symbol)
        names.update(resolve_args(args, constants, registry.source, symbol))

    return sorted(names)


def read_doc_text(patterns: tuple[str, ...]) -> str:
    parts: list[str] = []
    for pattern in patterns:
        matches = sorted(glob.glob(str(REPO_ROOT / pattern)))
        if not matches:
            raise FileNotFoundError(f"No research docs matched {pattern}")
        for match in matches:
            parts.append(Path(match).read_text(encoding="utf-8"))
    return "\n".join(parts)


def documented(table: str, docs_text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(table)}(?![A-Za-z0-9_])", docs_text) is not None


def check() -> tuple[list[dict[str, object]], bool]:
    results: list[dict[str, object]] = []
    ok = True

    for registry in REGISTRIES:
        tables = extract_registry(registry)
        docs_text = read_doc_text(registry.docs)
        missing = [table for table in tables if not documented(table, docs_text)]
        if missing:
            ok = False
        results.append(
            {
                "keyspace": registry.keyspace,
                "source": registry.source,
                "symbols": list(registry.symbols),
                "docs": list(registry.docs),
                "tables": tables,
                "missing": missing,
            }
        )

    return results, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check system table registry coverage in research docs.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    try:
        results, ok = check()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        for result in results:
            status = "OK" if not result["missing"] else "MISSING"
            print(f"{status} {result['keyspace']}: {len(result['tables'])} table names from {result['source']}")
            if result["missing"]:
                print("  missing from docs: " + ", ".join(result["missing"]))
        if ok:
            print("System table research docs are in sync with parsed table registries.")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
