#!/usr/bin/env python3
#
# Source-only drift check for standalone SSTable tool runbook coverage.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER_DIRS = ("bin", "tools/bin")
RUNBOOK_DOC = "research/module-sstable-tools-safety-runbook.md"

EXPECTED_EXCLUDED_WRAPPERS = {
    "bin/sstableloader": "BulkLoader is a streaming/bulk-load utility, not a standalone SSTable safety tool.",
}


@dataclass(frozen=True)
class ToolWrapper:
    tool: str
    wrapper: str
    class_ref: str
    source: str


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def java_source_for(class_ref: str) -> str:
    if not class_ref.startswith("org.apache.cassandra."):
        raise ValueError(f"Unexpected non-Cassandra class reference: {class_ref}")
    return "src/java/" + class_ref.replace(".", "/") + ".java"


def simple_class(class_ref: str) -> str:
    return class_ref.rsplit(".", 1)[-1]


def parse_wrapper(path: Path) -> ToolWrapper:
    rel = str(path.relative_to(REPO_ROOT))
    text = path.read_text(encoding="utf-8")
    matches = re.findall(r"\borg\.apache\.cassandra\.tools\.[A-Za-z0-9_]+(?:\$[A-Za-z0-9_]+)?\b", text)
    if not matches:
        raise ValueError(f"Could not find org.apache.cassandra.tools main class in {rel}")
    class_ref = matches[-1]
    return ToolWrapper(
        tool=path.name,
        wrapper=rel,
        class_ref=class_ref,
        source=java_source_for(class_ref),
    )


def wrappers() -> tuple[list[ToolWrapper], list[ToolWrapper]]:
    included: list[ToolWrapper] = []
    excluded: list[ToolWrapper] = []

    for wrapper_dir in WRAPPER_DIRS:
        for path in sorted((REPO_ROOT / wrapper_dir).glob("sstable*")):
            if not path.is_file():
                continue
            entry = parse_wrapper(path)
            if entry.wrapper in EXPECTED_EXCLUDED_WRAPPERS:
                excluded.append(entry)
            else:
                included.append(entry)

    return included, excluded


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def check() -> tuple[dict[str, object], bool]:
    runbook_text = read(RUNBOOK_DOC)
    included, excluded = wrappers()
    seen_wrappers = {entry.wrapper for entry in included + excluded}

    missing_sources = [entry for entry in included if not (REPO_ROOT / entry.source).exists()]
    missing_tool_names = [entry for entry in included if not documented(entry.tool, runbook_text)]
    missing_classes = [entry for entry in included if not documented(simple_class(entry.class_ref), runbook_text)]
    stale_exclusions = sorted(set(EXPECTED_EXCLUDED_WRAPPERS) - seen_wrappers)
    unexpected_exclusions = [
        entry
        for entry in excluded
        if not (REPO_ROOT / entry.source).exists()
    ]

    result = {
        "runbook": RUNBOOK_DOC,
        "wrapper_dirs": list(WRAPPER_DIRS),
        "included_count": len(included),
        "excluded_count": len(excluded),
        "included": [entry.__dict__ for entry in included],
        "excluded": [
            {
                **entry.__dict__,
                "reason": EXPECTED_EXCLUDED_WRAPPERS[entry.wrapper],
            }
            for entry in excluded
        ],
        "missing_sources": [entry.__dict__ for entry in missing_sources],
        "missing_tool_names": [entry.__dict__ for entry in missing_tool_names],
        "missing_classes": [entry.__dict__ for entry in missing_classes],
        "stale_exclusions": stale_exclusions,
        "unexpected_exclusions": [entry.__dict__ for entry in unexpected_exclusions],
    }

    ok = not any((missing_sources, missing_tool_names, missing_classes, stale_exclusions, unexpected_exclusions))
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check SSTable tool wrapper coverage in the research runbook.")
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
        print(f"OK SSTable tool wrappers: {result['included_count']} included wrappers parsed from bin/ and tools/bin/")
        print(f"OK SSTable tool exclusions: {result['excluded_count']} explicit out-of-scope wrappers tracked")
        if result["missing_sources"]:
            print("Wrappers whose Java main class source is missing:")
            for entry in result["missing_sources"]:
                print(f"  {entry['wrapper']} -> {entry['class_ref']} ({entry['source']})")
        if result["missing_tool_names"]:
            print("Wrapper tool names missing from runbook:")
            for entry in result["missing_tool_names"]:
                print(f"  {entry['tool']} ({entry['wrapper']})")
        if result["missing_classes"]:
            print("Wrapper Java main classes missing from runbook:")
            for entry in result["missing_classes"]:
                print(f"  {entry['class_ref']} ({entry['wrapper']})")
        if result["stale_exclusions"]:
            print("Expected excluded wrappers no longer exist:")
            for wrapper in result["stale_exclusions"]:
                print(f"  {wrapper}")
        if result["unexpected_exclusions"]:
            print("Excluded wrappers whose Java main class source is missing:")
            for entry in result["unexpected_exclusions"]:
                print(f"  {entry['wrapper']} -> {entry['class_ref']} ({entry['source']})")
        if ok:
            print("SSTable tools runbook is in sync with parsed wrapper scripts.")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
