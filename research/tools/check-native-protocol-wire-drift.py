#!/usr/bin/env python3
#
# Source-only drift check for native protocol wire contract research coverage.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

MESSAGE_SOURCE = "src/java/org/apache/cassandra/transport/Message.java"
PROTOCOL_VERSION_SOURCE = "src/java/org/apache/cassandra/transport/ProtocolVersion.java"
ENVELOPE_SOURCE = "src/java/org/apache/cassandra/transport/Envelope.java"
QUERY_OPTIONS_SOURCE = "src/java/org/apache/cassandra/cql3/QueryOptions.java"
EVENT_SOURCE = "src/java/org/apache/cassandra/transport/Event.java"
EXCEPTION_CODE_SOURCE = "src/java/org/apache/cassandra/exceptions/ExceptionCode.java"
REGISTER_MESSAGE_SOURCE = "src/java/org/apache/cassandra/transport/messages/RegisterMessage.java"

TARGET_DOCS = (
    "research/module-native-protocol-wire-contract.md",
    "research/module-native-protocol-wire-drift-checker.md",
    "research/module-native-protocol.md",
    "research/flow-native-protocol.md",
)

EXPECTED_MESSAGE_TYPES = (
    ("ERROR", 0, "RESPONSE", "ErrorMessage.codec"),
    ("STARTUP", 1, "REQUEST", "StartupMessage.codec"),
    ("READY", 2, "RESPONSE", "ReadyMessage.codec"),
    ("AUTHENTICATE", 3, "RESPONSE", "AuthenticateMessage.codec"),
    ("CREDENTIALS", 4, "REQUEST", "UnsupportedMessageCodec.instance"),
    ("OPTIONS", 5, "REQUEST", "OptionsMessage.codec"),
    ("SUPPORTED", 6, "RESPONSE", "SupportedMessage.codec"),
    ("QUERY", 7, "REQUEST", "QueryMessage.codec"),
    ("RESULT", 8, "RESPONSE", "ResultMessage.codec"),
    ("PREPARE", 9, "REQUEST", "PrepareMessage.codec"),
    ("EXECUTE", 10, "REQUEST", "ExecuteMessage.codec"),
    ("REGISTER", 11, "REQUEST", "RegisterMessage.codec"),
    ("EVENT", 12, "RESPONSE", "EventMessage.codec"),
    ("BATCH", 13, "REQUEST", "BatchMessage.codec"),
    ("AUTH_CHALLENGE", 14, "RESPONSE", "AuthChallenge.codec"),
    ("AUTH_RESPONSE", 15, "REQUEST", "AuthResponse.codec"),
    ("AUTH_SUCCESS", 16, "RESPONSE", "AuthSuccess.codec"),
)

EXPECTED_PROTOCOL_VERSIONS = (
    ("V1", 1, "v1", False),
    ("V2", 2, "v2", False),
    ("V3", 3, "v3", False),
    ("V4", 4, "v4", False),
    ("V5", 5, "v5", False),
    ("V6", 6, "v6-beta", True),
)

EXPECTED_SUPPORTED_VERSIONS = ("V3", "V4", "V5", "V6")
EXPECTED_CURRENT_VERSION = "V5"
EXPECTED_BETA_VERSION = "V6"
EXPECTED_KNOWN_INVALID_VERSIONS = (66, 65)

EXPECTED_ENVELOPE_FLAGS = (
    "COMPRESSED",
    "TRACING",
    "CUSTOM_PAYLOAD",
    "WARNING",
    "USE_BETA",
)

EXPECTED_QUERY_OPTION_FLAGS = (
    "VALUES",
    "SKIP_METADATA",
    "PAGE_SIZE",
    "PAGING_STATE",
    "SERIAL_CONSISTENCY",
    "TIMESTAMP",
    "NAMES_FOR_VALUES",
    "KEYSPACE",
    "NOW_IN_SECONDS",
)

EXPECTED_EVENT_TYPES = (
    ("TOPOLOGY_CHANGE", "V3"),
    ("STATUS_CHANGE", "V3"),
    ("SCHEMA_CHANGE", "V3"),
    ("TRACE_COMPLETE", "V4"),
)

EXPECTED_TOPOLOGY_CHANGES = ("NEW_NODE", "REMOVED_NODE", "MOVED_NODE")
EXPECTED_STATUS_CHANGES = ("UP", "DOWN")
EXPECTED_SCHEMA_CHANGES = ("CREATED", "UPDATED", "DROPPED")
EXPECTED_SCHEMA_TARGETS = ("KEYSPACE", "TABLE", "TYPE", "FUNCTION", "AGGREGATE")

EXPECTED_EXCEPTION_CODES = (
    ("SERVER_ERROR", 0x0000),
    ("PROTOCOL_ERROR", 0x000A),
    ("BAD_CREDENTIALS", 0x0100),
    ("UNAVAILABLE", 0x1000),
    ("OVERLOADED", 0x1001),
    ("IS_BOOTSTRAPPING", 0x1002),
    ("TRUNCATE_ERROR", 0x1003),
    ("WRITE_TIMEOUT", 0x1100),
    ("READ_TIMEOUT", 0x1200),
    ("READ_FAILURE", 0x1300),
    ("FUNCTION_FAILURE", 0x1400),
    ("WRITE_FAILURE", 0x1500),
    ("CDC_WRITE_FAILURE", 0x1600),
    ("CAS_WRITE_UNKNOWN", 0x1700),
    ("SYNTAX_ERROR", 0x2000),
    ("UNAUTHORIZED", 0x2100),
    ("INVALID", 0x2200),
    ("CONFIG_ERROR", 0x2300),
    ("ALREADY_EXISTS", 0x2400),
    ("UNPREPARED", 0x2500),
)

SCENARIO_IDS = (
    "native_protocol_message_opcode_baseline",
    "native_protocol_version_baseline",
    "native_protocol_envelope_flag_baseline",
    "native_protocol_query_option_flag_baseline",
    "native_protocol_event_type_baseline",
    "native_protocol_error_code_baseline",
    "native_protocol_payload_warning_tracing_contract",
    "native_protocol_negative_test_surface",
    "native_protocol_driver_compatibility_gap",
)

SOURCE_TOKEN_CHECKS = {
    MESSAGE_SOURCE: (
        "public static Type fromOpcode(int opcode, Direction direction)",
        "Wrong protocol direction",
        "UnsupportedMessageCodec.instance",
        "flags.add(Envelope.Header.Flag.TRACING)",
        "flags.add(Envelope.Header.Flag.WARNING)",
        "flags.add(Envelope.Header.Flag.CUSTOM_PAYLOAD)",
        "flags.add(Envelope.Header.Flag.USE_BETA)",
        "Received frame with CUSTOM_PAYLOAD flag for native protocol version < 4",
    ),
    PROTOCOL_VERSION_SOURCE: (
        "SUPPORTED_VERSIONS = new ProtocolVersion[] { V3, V4, V5, V6 }",
        "public final static ProtocolVersion CURRENT = V5",
        "public final static Optional<ProtocolVersion> BETA = Optional.of(V6)",
        "KNOWN_INVALID_VERSIONS = { 66, 65 }",
        "Rejecting Protocol Version %s < %s.",
    ),
    ENVELOPE_SOURCE: (
        "Beta version of the protocol used (%s), but USE_BETA flag is unset",
        "Header.Flag.deserialize(flags)",
        "Request is too big: length %d exceeds maximum allowed length %d.",
    ),
    QUERY_OPTIONS_SOURCE: (
        "version.isGreaterOrEqualTo(ProtocolVersion.V5)",
        "body.readUnsignedInt()",
        "body.readUnsignedByte()",
        "flags.add(Flag.KEYSPACE)",
        "flags.add(Flag.NOW_IN_SECONDS)",
        "Out of bound timestamp",
    ),
    EVENT_SOURCE: (
        "TRACE_COMPLETE(ProtocolVersion.V4)",
        "Event \" + eventType.name() + \" not valid for protocol version",
        "public enum Change { NEW_NODE, REMOVED_NODE, MOVED_NODE }",
        "public enum Status { UP, DOWN }",
        "public enum Target { KEYSPACE, TABLE, TYPE, FUNCTION, AGGREGATE }",
    ),
    EXCEPTION_CODE_SOURCE: (
        "valueToCode.put(code.value, code)",
        "Unknown error code %d",
    ),
    REGISTER_MESSAGE_SOURCE: (
        "eventTypes.add(CBUtil.readEnumValue(Event.Type.class, body))",
        "type.minimumVersion.isGreaterThan(connection.getVersion())",
        "register(type, connection().channel())",
    ),
}

DOC_REQUIRED_TOKENS = (
    "17 Message.Type opcodes",
    "6 ProtocolVersion enum constants",
    "CURRENT=V5",
    "BETA=V6",
    "66",
    "65",
    "5 Envelope.Header.Flag values",
    "9 QueryOptions.Codec.Flag values",
    "4 Event.Type values",
    "20 ExceptionCode",
    MESSAGE_SOURCE,
    PROTOCOL_VERSION_SOURCE,
    ENVELOPE_SOURCE,
    QUERY_OPTIONS_SOURCE,
    EVENT_SOURCE,
    EXCEPTION_CODE_SOURCE,
    "ProtocolVersionTest.java",
    "ProtocolNegotiationTest.java",
    "ProtocolErrorTest.java",
    "SerDeserTest.java",
    "MessagePayloadTest.java",
    "ErrorMessageTest.java",
) + tuple(entry[0] for entry in EXPECTED_MESSAGE_TYPES) + EXPECTED_ENVELOPE_FLAGS + EXPECTED_QUERY_OPTION_FLAGS + tuple(entry[0] for entry in EXPECTED_EVENT_TYPES) + tuple(entry[0] for entry in EXPECTED_EXCEPTION_CODES)


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def enum_body(text: str, enum_name: str) -> str:
    match = re.search(rf"\b(?:public|private)\s+enum\s+{re.escape(enum_name)}\b[^\{{]*\{{", text)
    if not match:
        raise ValueError(f"Could not locate enum {enum_name}")
    start = match.end()
    depth = 1
    index = start
    while index < len(text) and depth:
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
        index += 1
    if depth:
        raise ValueError(f"Could not parse enum {enum_name}")
    return text[start:index - 1]


def enum_entries_before_semicolon(body: str) -> str:
    semi = body.find(";")
    if semi == -1:
        semi = len(body)
    return body[:semi]


def simple_enum_values(text: str, enum_name: str) -> tuple[str, ...]:
    entries = enum_entries_before_semicolon(enum_body(text, enum_name))
    return tuple(re.findall(r"\b([A-Z][A-Z0-9_]+)\b(?:\s*,|\s*$)", entries))


def message_types() -> tuple[tuple[str, int, str, str], ...]:
    body = enum_entries_before_semicolon(enum_body(read(MESSAGE_SOURCE), "Type"))
    entries = []
    for name, opcode, direction, codec in re.findall(
        r"\b([A-Z_]+)\s*\(\s*(\d+)\s*,\s*Direction\.(REQUEST|RESPONSE)\s*,\s*([A-Za-z0-9_.]+)\s*\)",
        body,
    ):
        entries.append((name, int(opcode), direction, codec))
    return tuple(entries)


def protocol_versions() -> tuple[tuple[str, int, str, bool], ...]:
    body = enum_entries_before_semicolon(enum_body(read(PROTOCOL_VERSION_SOURCE), "ProtocolVersion"))
    entries = []
    for name, number, description, beta in re.findall(
        r"\b(V\d+)\s*\(\s*(\d+)\s*,\s*\"([^\"]+)\"\s*,\s*(true|false)\s*\)",
        body,
    ):
        entries.append((name, int(number), description, beta == "true"))
    return tuple(entries)


def supported_versions() -> tuple[str, ...]:
    text = read(PROTOCOL_VERSION_SOURCE)
    match = re.search(r"SUPPORTED_VERSIONS\s*=\s*new ProtocolVersion\[\]\s*\{\s*([^}]+?)\s*\}", text, re.S)
    if not match:
        raise ValueError("Could not locate SUPPORTED_VERSIONS")
    return tuple(re.findall(r"\bV\d+\b", match.group(1)))


def current_version() -> str:
    text = read(PROTOCOL_VERSION_SOURCE)
    match = re.search(r"\bCURRENT\s*=\s*(V\d+)\b", text)
    if not match:
        raise ValueError("Could not locate CURRENT")
    return match.group(1)


def beta_version() -> str:
    text = read(PROTOCOL_VERSION_SOURCE)
    match = re.search(r"\bBETA\s*=\s*Optional\.of\((V\d+)\)", text)
    if not match:
        raise ValueError("Could not locate BETA")
    return match.group(1)


def known_invalid_versions() -> tuple[int, ...]:
    text = read(PROTOCOL_VERSION_SOURCE)
    match = re.search(r"KNOWN_INVALID_VERSIONS\s*=\s*\{\s*([^}]+?)\s*\}", text, re.S)
    if not match:
        raise ValueError("Could not locate KNOWN_INVALID_VERSIONS")
    return tuple(int(value) for value in re.findall(r"\d+", match.group(1)))


def envelope_flags() -> tuple[str, ...]:
    return simple_enum_values(read(ENVELOPE_SOURCE), "Flag")


def query_option_flags() -> tuple[str, ...]:
    return simple_enum_values(read(QUERY_OPTIONS_SOURCE), "Flag")


def event_types() -> tuple[tuple[str, str], ...]:
    body = enum_entries_before_semicolon(enum_body(read(EVENT_SOURCE), "Type"))
    entries = []
    for name, minimum in re.findall(r"\b([A-Z_]+)\s*\(\s*ProtocolVersion\.(V\d+)\s*\)", body):
        entries.append((name, minimum))
    return tuple(entries)


def event_nested_enum(enum_name: str) -> tuple[str, ...]:
    return simple_enum_values(read(EVENT_SOURCE), enum_name)


def exception_codes() -> tuple[tuple[str, int], ...]:
    body = enum_entries_before_semicolon(enum_body(read(EXCEPTION_CODE_SOURCE), "ExceptionCode"))
    entries = []
    for name, value in re.findall(r"\b([A-Z_]+)\s*\(\s*(0x[0-9A-Fa-f]+)\s*\)", body):
        entries.append((name, int(value, 16)))
    return tuple(entries)


def source_checks() -> tuple[list[Check], dict[str, object]]:
    messages = message_types()
    versions = protocol_versions()
    supported = supported_versions()
    current = current_version()
    beta = beta_version()
    invalid = known_invalid_versions()
    header_flags = envelope_flags()
    option_flags = query_option_flags()
    events = event_types()
    topology_changes = event_nested_enum("Change")
    status_changes = event_nested_enum("Status")
    schema_targets = event_nested_enum("Target")
    errors = exception_codes()

    checks = [
        Check("Message.Type tuples match baseline", MESSAGE_SOURCE, messages == EXPECTED_MESSAGE_TYPES),
        Check("ProtocolVersion enum tuples match baseline", PROTOCOL_VERSION_SOURCE, versions == EXPECTED_PROTOCOL_VERSIONS),
        Check("ProtocolVersion supported/current/beta baseline", PROTOCOL_VERSION_SOURCE, supported == EXPECTED_SUPPORTED_VERSIONS and current == EXPECTED_CURRENT_VERSION and beta == EXPECTED_BETA_VERSION and invalid == EXPECTED_KNOWN_INVALID_VERSIONS),
        Check("Envelope.Header.Flag order matches baseline", ENVELOPE_SOURCE, header_flags == EXPECTED_ENVELOPE_FLAGS),
        Check("QueryOptions.Codec.Flag order matches baseline", QUERY_OPTIONS_SOURCE, option_flags == EXPECTED_QUERY_OPTION_FLAGS),
        Check("Event.Type tuples match baseline", EVENT_SOURCE, events == EXPECTED_EVENT_TYPES),
        Check("Event topology changes match baseline", EVENT_SOURCE, topology_changes == EXPECTED_TOPOLOGY_CHANGES),
        Check("Event status changes match baseline", EVENT_SOURCE, status_changes == EXPECTED_STATUS_CHANGES),
        Check("Event schema changes match baseline", EVENT_SOURCE, EXPECTED_SCHEMA_CHANGES == EXPECTED_SCHEMA_CHANGES and "public enum Change { CREATED, UPDATED, DROPPED }" in read(EVENT_SOURCE)),
        Check("Event schema targets match baseline", EVENT_SOURCE, schema_targets == EXPECTED_SCHEMA_TARGETS),
        Check("ExceptionCode values match baseline", EXCEPTION_CODE_SOURCE, errors == EXPECTED_EXCEPTION_CODES),
    ]

    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(Check(f"source token contract {path}", path, all(token in text for token in tokens)))

    metadata = {
        "message_type_count": len(messages),
        "protocol_version_count": len(versions),
        "supported_versions": list(supported),
        "current_version": current,
        "beta_version": beta,
        "known_invalid_versions": list(invalid),
        "envelope_flag_count": len(header_flags),
        "query_option_flag_count": len(option_flags),
        "event_type_count": len(events),
        "exception_code_count": len(errors),
        "message_types": [{"name": name, "opcode": opcode, "direction": direction, "codec": codec} for name, opcode, direction, codec in messages],
        "protocol_versions": [{"name": name, "number": number, "description": description, "beta": beta_flag} for name, number, description, beta_flag in versions],
        "envelope_flags": list(header_flags),
        "query_option_flags": list(option_flags),
        "event_types": [{"name": name, "minimum_version": minimum} for name, minimum in events],
        "exception_codes": [{"name": name, "value": value} for name, value in errors],
    }
    return checks, metadata


def read_doc_text() -> str:
    return "\n".join(read(path) for path in TARGET_DOCS)


def doc_checks() -> list[Check]:
    text = read_doc_text()
    checks = [Check(f"doc scenario {scenario}", " / ".join(TARGET_DOCS), documented(scenario, text)) for scenario in SCENARIO_IDS]
    checks.extend(Check(f"doc token {token}", " / ".join(TARGET_DOCS), token in text) for token in DOC_REQUIRED_TOKENS)
    return checks


def check() -> tuple[dict[str, object], bool]:
    sources, metadata = source_checks()
    docs = doc_checks()
    result = {
        "sources": {
            "message": MESSAGE_SOURCE,
            "protocol_version": PROTOCOL_VERSION_SOURCE,
            "envelope": ENVELOPE_SOURCE,
            "query_options": QUERY_OPTIONS_SOURCE,
            "event": EVENT_SOURCE,
            "exception_code": EXCEPTION_CODE_SOURCE,
            "register_message": REGISTER_MESSAGE_SOURCE,
        },
        "docs": list(TARGET_DOCS),
        "scenario_ids": list(SCENARIO_IDS),
        "metadata": metadata,
        "source_checks": [entry.__dict__ for entry in sources],
        "doc_checks": [entry.__dict__ for entry in docs],
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check native protocol wire source/doc drift.")
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
        failed_sources = [entry for entry in result["source_checks"] if not entry["ok"]]
        failed_docs = [entry for entry in result["doc_checks"] if not entry["ok"]]
        if failed_sources or failed_docs:
            print("Native protocol wire drift check failed.")
            for entry in failed_sources + failed_docs:
                print(f"- {entry['name']} ({entry['source']})")
        else:
            metadata = result["metadata"]
            print(
                "Native protocol wire drift check passed: "
                f"{metadata['message_type_count']} opcodes, "
                f"{metadata['protocol_version_count']} protocol versions, "
                f"{metadata['envelope_flag_count']} envelope flags, "
                f"{metadata['query_option_flag_count']} query option flags, "
                f"{metadata['event_type_count']} event types, "
                f"{metadata['exception_code_count']} error codes."
            )

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
