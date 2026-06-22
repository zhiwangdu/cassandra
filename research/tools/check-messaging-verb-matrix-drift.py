#!/usr/bin/env python3
#
# Source-only drift check for internode Verb coverage in the messaging matrix.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VERB_SOURCE = "src/java/org/apache/cassandra/net/Verb.java"
MATRIX_DOC = "research/module-messaging-verb-semantics.md"


@dataclass(frozen=True)
class VerbEntry:
    name: str
    line: int
    source: str = VERB_SOURCE


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def verb_entries() -> list[VerbEntry]:
    lines = read(VERB_SOURCE).splitlines()
    in_enum = False
    entries: list[VerbEntry] = []

    for line_no, line in enumerate(lines, 1):
        if not in_enum:
            if re.search(r"\bpublic\s+enum\s+Verb\b", line):
                in_enum = True
            continue

        if re.match(r"\s*;", line):
            break

        match = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*\(", line)
        if match:
            entries.append(VerbEntry(match.group(1), line_no))

    if not entries:
        raise ValueError(f"Could not parse verb constants from {VERB_SOURCE}")
    return entries


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def check() -> tuple[dict[str, object], bool]:
    entries = verb_entries()
    matrix_text = read(MATRIX_DOC)

    missing_verbs = [entry for entry in entries if not documented(entry.name, matrix_text)]
    result = {
        "source": VERB_SOURCE,
        "matrix": MATRIX_DOC,
        "verb_count": len(entries),
        "verbs": [entry.__dict__ for entry in entries],
        "missing_verbs": [entry.__dict__ for entry in missing_verbs],
    }
    return result, not missing_verbs


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Verb.java coverage in the messaging semantics matrix.")
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
        print(f"OK messaging verbs parsed: {result['verb_count']} constants from {VERB_SOURCE}")
        if result["missing_verbs"]:
            print("Verb constants missing from messaging matrix:")
            for entry in result["missing_verbs"]:
                print(f"  {entry['name']} ({entry['source']}:{entry['line']})")
        if ok:
            print("Messaging verb matrix is in sync with parsed Verb.java constants.")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
