#!/usr/bin/env python3
#
# Source-only drift check for system keyspace replication/RF research coverage.

import argparse
import glob
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_CONSTANTS_SOURCE = "src/java/org/apache/cassandra/schema/SchemaConstants.java"
PROPERTIES_SOURCE = "src/java/org/apache/cassandra/config/CassandraRelevantProperties.java"
RF_MATRIX_DOCS = ("research/module-consistency-replication-third-round.md",)


@dataclass(frozen=True)
class Classification:
    kind: str
    symbol: str


@dataclass(frozen=True)
class LocalMetadata:
    keyspace: str
    source: str
    keyspace_constant: str


@dataclass(frozen=True)
class ReplicatedRF:
    keyspace: str
    source: str
    property_symbol: str


CLASSIFICATIONS = (
    Classification("local", "LOCAL_SYSTEM_KEYSPACE_NAMES"),
    Classification("virtual", "VIRTUAL_SYSTEM_KEYSPACE_NAMES"),
    Classification("replicated", "REPLICATED_SYSTEM_KEYSPACE_NAMES"),
)

LOCAL_METADATA = (
    LocalMetadata("system", "src/java/org/apache/cassandra/db/SystemKeyspace.java", "SYSTEM_KEYSPACE_NAME"),
    LocalMetadata("system_schema", "src/java/org/apache/cassandra/schema/SchemaKeyspace.java", "SCHEMA_KEYSPACE_NAME"),
)

REPLICATED_RF = (
    ReplicatedRF("system_auth", "src/java/org/apache/cassandra/auth/AuthKeyspace.java", "SYSTEM_AUTH_DEFAULT_RF"),
    ReplicatedRF("system_traces", "src/java/org/apache/cassandra/tracing/TraceKeyspace.java", "SYSTEM_TRACES_DEFAULT_RF"),
    ReplicatedRF("system_distributed", "src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java", "SYSTEM_DISTRIBUTED_DEFAULT_RF"),
)


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)
    return text


def string_constants(text: str) -> dict[str, str]:
    pattern = re.compile(r"\bstatic\s+final\s+String\s+([A-Za-z0-9_]+)\s*=\s*\"([^\"]+)\"")
    return {name: value for name, value in pattern.findall(text)}


def find_immutable_args(text: str, symbol: str) -> list[str]:
    pattern = re.compile(rf"\b{re.escape(symbol)}\b\s*=\s*ImmutableSet\.of\s*\(")
    match = pattern.search(text)
    if not match:
        raise ValueError(f"Could not find ImmutableSet declaration for {symbol}")

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
    raise ValueError(f"Unclosed ImmutableSet declaration for {symbol}")


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


def classifications() -> dict[str, list[str]]:
    text = strip_comments(read(SCHEMA_CONSTANTS_SOURCE))
    constants = string_constants(text)
    result: dict[str, list[str]] = {}
    for classification in CLASSIFICATIONS:
        args = find_immutable_args(text, classification.symbol)
        result[classification.kind] = resolve_args(args, constants, SCHEMA_CONSTANTS_SOURCE, classification.symbol)
    return result


def property_default(symbol: str) -> tuple[str, str]:
    text = read(PROPERTIES_SOURCE)
    match = re.search(rf"\b{re.escape(symbol)}\s*\(\s*\"([^\"]+)\"\s*,\s*\"([^\"]+)\"\s*\)", text)
    if not match:
        raise ValueError(f"Could not find property {symbol} in {PROPERTIES_SOURCE}")
    return match.group(1), match.group(2)


def has_default_rf_binding(source: str, property_symbol: str) -> bool:
    text = read(source)
    pattern = re.compile(
        rf"\bDEFAULT_RF\s*=\s*CassandraRelevantProperties\.{re.escape(property_symbol)}\.getInt\s*\(\s*\)"
    )
    return pattern.search(text) is not None


def has_simple_max_default_rf(source: str) -> bool:
    text = read(source)
    pattern = re.compile(
        r"KeyspaceParams\.simple\s*\(\s*Math\.max\s*\(\s*DEFAULT_RF\s*,\s*"
        r"DatabaseDescriptor\.getDefaultKeyspaceRF\s*\(\s*\)\s*\)\s*\)",
        re.S,
    )
    return pattern.search(text) is not None


def has_local_metadata(source: str, keyspace_constant: str) -> bool:
    text = read(source)
    pattern = re.compile(
        rf"KeyspaceMetadata\.create\s*\(\s*SchemaConstants\.{re.escape(keyspace_constant)}\s*,\s*"
        r"KeyspaceParams\.local\s*\(\s*\)",
        re.S,
    )
    return pattern.search(text) is not None


def read_doc_text(patterns: tuple[str, ...]) -> str:
    parts: list[str] = []
    for pattern in patterns:
        matches = sorted(glob.glob(str(REPO_ROOT / pattern)))
        if not matches:
            raise FileNotFoundError(f"No research docs matched {pattern}")
        for match in matches:
            parts.append(Path(match).read_text(encoding="utf-8"))
    return "\n".join(parts)


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def check() -> tuple[dict[str, object], bool]:
    doc_text = read_doc_text(RF_MATRIX_DOCS)
    class_map = classifications()

    missing_classification_docs = {
        kind: [name for name in names if not documented(name, doc_text)]
        for kind, names in class_map.items()
    }

    local_results = []
    for entry in LOCAL_METADATA:
        local_results.append(
            {
                "keyspace": entry.keyspace,
                "source": entry.source,
                "keyspace_constant": entry.keyspace_constant,
                "uses_keyspace_params_local": has_local_metadata(entry.source, entry.keyspace_constant),
                "documented": documented(entry.keyspace, doc_text),
            }
        )

    replicated_results = []
    for entry in REPLICATED_RF:
        property_name, default_rf = property_default(entry.property_symbol)
        replicated_results.append(
            {
                "keyspace": entry.keyspace,
                "source": entry.source,
                "property_symbol": entry.property_symbol,
                "property_name": property_name,
                "default_rf": default_rf,
                "has_default_rf_binding": has_default_rf_binding(entry.source, entry.property_symbol),
                "has_simple_max_default_rf": has_simple_max_default_rf(entry.source),
                "documented_keyspace": documented(entry.keyspace, doc_text),
                "documented_property": documented(property_name, doc_text),
            }
        )

    result = {
        "schema_constants": SCHEMA_CONSTANTS_SOURCE,
        "properties_source": PROPERTIES_SOURCE,
        "docs": list(RF_MATRIX_DOCS),
        "classifications": class_map,
        "missing_classification_docs": missing_classification_docs,
        "local_metadata": local_results,
        "replicated_rf": replicated_results,
    }

    ok = not any(missing_classification_docs.values())
    ok = ok and all(entry["uses_keyspace_params_local"] and entry["documented"] for entry in local_results)
    ok = ok and all(
        entry["has_default_rf_binding"]
        and entry["has_simple_max_default_rf"]
        and entry["documented_keyspace"]
        and entry["documented_property"]
        for entry in replicated_results
    )
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check system keyspace RF/category coverage in research docs.")
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
        for kind, names in result["classifications"].items():
            missing = result["missing_classification_docs"][kind]
            status = "OK" if not missing else "MISSING"
            print(f"{status} {kind} system keyspaces: {', '.join(names)}")
            if missing:
                print("  missing from docs: " + ", ".join(missing))

        for entry in result["local_metadata"]:
            status = "OK" if entry["uses_keyspace_params_local"] and entry["documented"] else "MISSING"
            print(f"{status} local metadata: {entry['keyspace']} from {entry['source']}")
            if not entry["uses_keyspace_params_local"]:
                print("  source does not match KeyspaceParams.local() metadata contract")
            if not entry["documented"]:
                print("  keyspace missing from docs")

        for entry in result["replicated_rf"]:
            status = (
                "OK"
                if entry["has_default_rf_binding"]
                and entry["has_simple_max_default_rf"]
                and entry["documented_keyspace"]
                and entry["documented_property"]
                else "MISSING"
            )
            print(
                f"{status} replicated RF: {entry['keyspace']} uses {entry['property_name']} "
                f"default {entry['default_rf']} from {entry['source']}"
            )
            if not entry["has_default_rf_binding"]:
                print(f"  source does not bind DEFAULT_RF to {entry['property_symbol']}")
            if not entry["has_simple_max_default_rf"]:
                print("  source does not use KeyspaceParams.simple(Math.max(DEFAULT_RF, DatabaseDescriptor.getDefaultKeyspaceRF()))")
            if not entry["documented_keyspace"]:
                print("  keyspace missing from docs")
            if not entry["documented_property"]:
                print("  RF property missing from docs")

        if ok:
            print("System keyspace RF research docs are in sync with parsed source contracts.")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
