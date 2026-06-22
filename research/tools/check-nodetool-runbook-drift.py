#!/usr/bin/env python3
#
# Source-only drift check for nodetool command coverage in the research runbook.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
NODETOOL_SOURCE = "src/java/org/apache/cassandra/tools/NodeTool.java"
COMMAND_SOURCE_ROOT = "src/java/org/apache/cassandra/tools"
RUNBOOK_DOC = "research/module-observability-runbook-virtual-schema.md"


@dataclass(frozen=True)
class CommandEntry:
    kind: str
    class_ref: str
    command: str
    source: str


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def command_annotations() -> dict[str, tuple[str, str]]:
    mapping: dict[str, tuple[str, str]] = {}
    for path in sorted((REPO_ROOT / COMMAND_SOURCE_ROOT).rglob("*.java")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'@Command\s*\(\s*name\s*=\s*"([^"]+)".*?class\s+([A-Za-z0-9_]+)', text, re.S):
            mapping[match.group(2)] = (match.group(1), str(path.relative_to(REPO_ROOT)))
    return mapping


def resolve_class(class_ref: str, annotations: dict[str, tuple[str, str]]) -> tuple[str, str]:
    simple_name = class_ref.split(".")[-1]
    if simple_name == "CassHelp":
        return "help", NODETOOL_SOURCE
    if simple_name not in annotations:
        raise ValueError(f"Could not resolve @Command annotation for {class_ref}")
    return annotations[simple_name]


def top_level_command_classes(nodetool_text: str) -> list[str]:
    match = re.search(r"newArrayList\((.*?)\n\s*\);", nodetool_text, re.S)
    if not match:
        raise ValueError("Could not find NodeTool top-level newArrayList command registry")
    return re.findall(r"([A-Za-z0-9_\.]+)\.class", match.group(1))


def grouped_command_classes(nodetool_text: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for match in re.finditer(r'builder\.withGroup\("([^"]+)"\)(.*?);\n', nodetool_text, re.S):
        group_name = match.group(1)
        classes = re.findall(r"withCommand\(([^)]+)\.class\)", match.group(2))
        groups[group_name] = classes
    return groups


def registered_commands() -> tuple[list[CommandEntry], list[CommandEntry]]:
    nodetool_text = read(NODETOOL_SOURCE)
    annotations = command_annotations()

    top_level = []
    for class_ref in top_level_command_classes(nodetool_text):
        command, source = resolve_class(class_ref, annotations)
        top_level.append(CommandEntry("top-level", class_ref, command, source))

    grouped = []
    for group_name, classes in grouped_command_classes(nodetool_text).items():
        for class_ref in classes:
            command, source = resolve_class(class_ref, annotations)
            grouped.append(CommandEntry("group", class_ref, f"{group_name} {command}", source))

    return top_level, grouped


def documented(command: str, runbook_text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(command)}(?![A-Za-z0-9_])", runbook_text) is not None


def check() -> tuple[dict[str, object], bool]:
    top_level, grouped = registered_commands()
    runbook_text = read(RUNBOOK_DOC)

    missing_top_level = [entry for entry in top_level if not documented(entry.command, runbook_text)]
    missing_grouped = [entry for entry in grouped if not documented(entry.command, runbook_text)]
    ok = not missing_top_level and not missing_grouped

    result = {
        "runbook": RUNBOOK_DOC,
        "top_level_count": len(top_level),
        "grouped_count": len(grouped),
        "top_level": [entry.__dict__ for entry in top_level],
        "grouped": [entry.__dict__ for entry in grouped],
        "missing_top_level": [entry.__dict__ for entry in missing_top_level],
        "missing_grouped": [entry.__dict__ for entry in missing_grouped],
    }
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check nodetool command registry coverage in the research runbook.")
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
        print(f"OK nodetool top-level registry: {result['top_level_count']} commands parsed from {NODETOOL_SOURCE}")
        print(f"OK nodetool groups: {result['grouped_count']} grouped commands parsed from {NODETOOL_SOURCE}")
        if result["missing_top_level"]:
            print("Missing top-level commands from runbook:")
            for entry in result["missing_top_level"]:
                print(f"  {entry['command']} ({entry['class_ref']}, {entry['source']})")
        if result["missing_grouped"]:
            print("Missing grouped commands from runbook:")
            for entry in result["missing_grouped"]:
                print(f"  {entry['command']} ({entry['class_ref']}, {entry['source']})")
        if ok:
            print("Nodetool runbook is in sync with parsed command registries.")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
