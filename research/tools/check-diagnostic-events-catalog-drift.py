#!/usr/bin/env python3
#
# Source-only drift check for DiagnosticEvent catalog coverage.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = "src/java"
CATALOG_DOC = "research/module-diagnostic-events-catalog.md"
AUDIT_TYPE_SOURCE = "src/java/org/apache/cassandra/audit/AuditLogEntryType.java"


EXPECTED_NO_DIRECT_PUBLISH = {
    ("org.apache.cassandra.dht.tokenallocator.TokenAllocatorEvent", "TOKENS_ALLOCATED"),
    ("org.apache.cassandra.hints.HintEvent", "DISPATCHING_STARTED"),
    ("org.apache.cassandra.hints.HintEvent", "DISPATCHING_PAUSED"),
    ("org.apache.cassandra.hints.HintEvent", "DISPATCHING_RESUMED"),
    ("org.apache.cassandra.hints.HintEvent", "DISPATCHING_SHUTDOWN"),
    ("org.apache.cassandra.locator.TokenMetadataEvent", "PENDING_RANGE_CALCULATION_COMPLETED"),
}


@dataclass(frozen=True)
class EventClass:
    fqn: str
    class_name: str
    source: str
    type_source: str
    event_types: tuple[str, ...]
    published_types: tuple[str, ...]


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)
    return text


def source_fqn(path: Path) -> str:
    rel = path.relative_to(REPO_ROOT / SOURCE_ROOT).with_suffix("")
    return ".".join(rel.parts)


def class_declaration(text: str) -> re.Match[str] | None:
    return re.search(r"\bclass\s+([A-Za-z0-9_]+)(?:<[^>{}]+>)?\s+extends\s+DiagnosticEvent\b", text)


def enum_constants(text: str, enum_name: str) -> tuple[str, ...]:
    match = re.search(rf"\benum\s+{re.escape(enum_name)}\s*\{{(.*?)\n\s*\}}", text, flags=re.S)
    if not match:
        raise ValueError(f"Could not find enum {enum_name}")

    body = strip_comments(match.group(1)).split(";", 1)[0]
    constants: list[str] = []
    for raw in body.replace("\n", " ").split(","):
        name = raw.strip().split("(", 1)[0].strip()
        if name and re.fullmatch(r"[A-Z0-9_]+", name):
            constants.append(name)
    return tuple(constants)


def event_type_enums(text: str) -> list[str]:
    return re.findall(r"\benum\s+([A-Za-z0-9_]*EventType)\s*\{", text)


def publish_contexts(class_name: str) -> list[str]:
    pattern = re.compile(rf"\bnew\s+{re.escape(class_name)}(?:<[^>]*>|<>)?\s*\(")
    contexts: list[str] = []

    for path in sorted((REPO_ROOT / SOURCE_ROOT).rglob("*.java")):
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for index, line in enumerate(lines):
            if pattern.search(line):
                contexts.append("\n".join(lines[index:index + 24]))

    return contexts


def published_types(class_name: str, event_types: tuple[str, ...]) -> tuple[str, ...]:
    contexts = "\n".join(publish_contexts(class_name))
    return tuple(event_type for event_type in event_types if re.search(rf"\b{re.escape(event_type)}\b", contexts))


def production_event_classes() -> list[EventClass]:
    events: list[EventClass] = []
    source_root = REPO_ROOT / SOURCE_ROOT
    audit_types = enum_constants(read(AUDIT_TYPE_SOURCE), "AuditLogEntryType")

    for path in sorted(source_root.rglob("*.java")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        match = class_declaration(text)
        if not match:
            continue

        class_name = match.group(1)
        source = str(path.relative_to(REPO_ROOT))
        fqn = source_fqn(path)

        if class_name == "AuditEvent":
            event_types = audit_types
            type_source = AUDIT_TYPE_SOURCE
            published = event_types
        else:
            enums = event_type_enums(text)
            if len(enums) != 1:
                raise ValueError(f"{source} must contain exactly one *EventType enum; found {enums}")
            event_types = enum_constants(text, enums[0])
            type_source = source
            published = published_types(class_name, event_types)

        events.append(
            EventClass(
                fqn=fqn,
                class_name=class_name,
                source=source,
                type_source=type_source,
                event_types=event_types,
                published_types=published,
            )
        )

    return events


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def check() -> tuple[dict[str, object], bool]:
    catalog_text = read(CATALOG_DOC)
    events = production_event_classes()

    missing_classes = [event for event in events if event.fqn not in catalog_text and event.class_name not in catalog_text]
    missing_types = [
        {"event_class": event.fqn, "type": event_type, "source": event.type_source}
        for event in events
        for event_type in event.event_types
        if not documented(event_type, catalog_text)
    ]

    actual_no_direct_publish = {
        (event.fqn, event_type)
        for event in events
        if event.class_name != "AuditEvent"
        for event_type in event.event_types
        if event_type not in event.published_types
    }
    unexpected_no_direct_publish = sorted(actual_no_direct_publish - EXPECTED_NO_DIRECT_PUBLISH)
    stale_expected_no_direct_publish = sorted(EXPECTED_NO_DIRECT_PUBLISH - actual_no_direct_publish)

    result = {
        "catalog": CATALOG_DOC,
        "event_class_count": len(events),
        "event_type_count": sum(len(event.event_types) for event in events),
        "events": [
            {
                "fqn": event.fqn,
                "class_name": event.class_name,
                "source": event.source,
                "type_source": event.type_source,
                "event_types": list(event.event_types),
                "published_types": list(event.published_types),
                "no_direct_publish": [
                    event_type
                    for event_type in event.event_types
                    if event.class_name != "AuditEvent" and event_type not in event.published_types
                ],
            }
            for event in events
        ],
        "missing_classes": [event.__dict__ for event in missing_classes],
        "missing_types": missing_types,
        "expected_no_direct_publish": [
            {"event_class": event_class, "type": event_type}
            for event_class, event_type in sorted(EXPECTED_NO_DIRECT_PUBLISH)
        ],
        "unexpected_no_direct_publish": [
            {"event_class": event_class, "type": event_type}
            for event_class, event_type in unexpected_no_direct_publish
        ],
        "stale_expected_no_direct_publish": [
            {"event_class": event_class, "type": event_type}
            for event_class, event_type in stale_expected_no_direct_publish
        ],
    }
    ok = not missing_classes and not missing_types and not unexpected_no_direct_publish and not stale_expected_no_direct_publish
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check DiagnosticEvent source coverage in the research catalog.")
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
        print(f"OK diagnostic event classes: {result['event_class_count']} subclasses parsed from {SOURCE_ROOT}")
        print(f"OK diagnostic event types: {result['event_type_count']} type constants checked against {CATALOG_DOC}")
        print(f"OK expected no-direct-publish notes: {len(result['expected_no_direct_publish'])} source enum values tracked")
        if result["missing_classes"]:
            print("Missing DiagnosticEvent classes from catalog:")
            for event in result["missing_classes"]:
                print(f"  {event['fqn']} ({event['source']})")
        if result["missing_types"]:
            print("Missing DiagnosticEvent type constants from catalog:")
            for item in result["missing_types"]:
                print(f"  {item['event_class']}#{item['type']} ({item['source']})")
        if result["unexpected_no_direct_publish"]:
            print("New enum values without direct publish sites:")
            for item in result["unexpected_no_direct_publish"]:
                print(f"  {item['event_class']}#{item['type']}")
        if result["stale_expected_no_direct_publish"]:
            print("Expected no-direct-publish values now have publish sites or disappeared:")
            for item in result["stale_expected_no_direct_publish"]:
                print(f"  {item['event_class']}#{item['type']}")
        if ok:
            print("Diagnostic Events catalog is in sync with parsed source event classes and type enums.")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
