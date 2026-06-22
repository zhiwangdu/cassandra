#!/usr/bin/env python3
#
# Source-only drift check for native protocol extra flag negative matrix coverage.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

MESSAGE_SOURCE = "src/java/org/apache/cassandra/transport/Message.java"
DISPATCHER_SOURCE = "src/java/org/apache/cassandra/transport/Dispatcher.java"

OPTIONS_SOURCE = "src/java/org/apache/cassandra/transport/messages/OptionsMessage.java"
STARTUP_SOURCE = "src/java/org/apache/cassandra/transport/messages/StartupMessage.java"
AUTH_RESPONSE_SOURCE = "src/java/org/apache/cassandra/transport/messages/AuthResponse.java"
QUERY_SOURCE = "src/java/org/apache/cassandra/transport/messages/QueryMessage.java"
PREPARE_SOURCE = "src/java/org/apache/cassandra/transport/messages/PrepareMessage.java"
EXECUTE_SOURCE = "src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java"
BATCH_SOURCE = "src/java/org/apache/cassandra/transport/messages/BatchMessage.java"

ERROR_SOURCE = "src/java/org/apache/cassandra/transport/messages/ErrorMessage.java"
EVENT_SOURCE = "src/java/org/apache/cassandra/transport/messages/EventMessage.java"
SUPPORTED_SOURCE = "src/java/org/apache/cassandra/transport/messages/SupportedMessage.java"
AUTHENTICATE_SOURCE = "src/java/org/apache/cassandra/transport/messages/AuthenticateMessage.java"
AUTH_CHALLENGE_SOURCE = "src/java/org/apache/cassandra/transport/messages/AuthChallenge.java"
AUTH_SUCCESS_SOURCE = "src/java/org/apache/cassandra/transport/messages/AuthSuccess.java"

MESSAGE_PAYLOAD_TEST = "test/unit/org/apache/cassandra/transport/MessagePayloadTest.java"
PROTOCOL_NEGOTIATION_TEST = "test/unit/org/apache/cassandra/transport/ProtocolNegotiationTest.java"
RATE_LIMITING_TEST = "test/unit/org/apache/cassandra/transport/RateLimitingTest.java"
CLIENT_RESOURCE_LIMITS_TEST = "test/unit/org/apache/cassandra/transport/ClientResourceLimitsTest.java"
ERROR_MESSAGE_TEST = "test/unit/org/apache/cassandra/transport/ErrorMessageTest.java"
AUTHENTICATE_MESSAGE_TEST = "test/unit/org/apache/cassandra/transport/messages/AuthenticateMessageTest.java"
AUTH_MESSAGE_SIZE_LIMIT_TEST = "test/unit/org/apache/cassandra/transport/AuthMessageSizeLimitTest.java"

TARGET_DOCS = (
    "research/module-native-protocol-extras-negative-matrix.md",
    "research/module-native-protocol-extras-drift-checker.md",
    "research/module-native-protocol.md",
    "research/module-native-protocol-wire-contract.md",
    "research/module-schema-cql-auth-native-third-round.md",
    "research/flow-native-protocol.md",
    "research/README.md",
    "research/notes/source-map.md",
)

REQUEST_TARGETS = {
    "OPTIONS": ("OptionsMessage", OPTIONS_SOURCE),
    "STARTUP": ("StartupMessage", STARTUP_SOURCE),
    "AUTH_RESPONSE": ("AuthResponse", AUTH_RESPONSE_SOURCE),
}

TRACEABLE_COMPARISON_TARGETS = {
    "QUERY": ("QueryMessage", QUERY_SOURCE, True, True),
    "PREPARE": ("PrepareMessage", PREPARE_SOURCE, True, False),
    "EXECUTE": ("ExecuteMessage", EXECUTE_SOURCE, True, True),
    "BATCH": ("BatchMessage", BATCH_SOURCE, True, True),
}

RESPONSE_TARGETS = {
    "ERROR": ("ErrorMessage", ERROR_SOURCE),
    "EVENT": ("EventMessage", EVENT_SOURCE),
    "SUPPORTED": ("SupportedMessage", SUPPORTED_SOURCE),
    "AUTHENTICATE": ("AuthenticateMessage", AUTHENTICATE_SOURCE),
    "AUTH_CHALLENGE": ("AuthChallenge", AUTH_CHALLENGE_SOURCE),
    "AUTH_SUCCESS": ("AuthSuccess", AUTH_SUCCESS_SOURCE),
}

SCENARIO_IDS = (
    "native_protocol_extras_frame_prelude_contract",
    "native_protocol_extras_custom_payload_version_gate",
    "native_protocol_extras_request_tracing_noop_matrix",
    "native_protocol_extras_request_warning_flag_negative",
    "native_protocol_extras_warning_tracking_gate",
    "native_protocol_extras_options_startup_auth_payload_negative",
    "native_protocol_extras_error_event_response_matrix",
    "native_protocol_extras_auth_response_family_matrix",
    "native_protocol_extras_test_coverage_gap",
)

SOURCE_TOKEN_CHECKS = {
    MESSAGE_SOURCE: (
        "protected boolean isTraceable()",
        "protected boolean isTrackable()",
        "if (isTraceable())",
        "if (isTraceable() && isTracingRequested())",
        "Tracing.instance.newSession(tracingSessionId, getCustomPayload())",
        "List<String> warnings = isRequest || !hasWarning ? null : CBUtil.readStringList(inbound.body)",
        "if (isTracing)\n                    req.setTracingRequested();",
        "Must not send frame with CUSTOM_PAYLOAD flag for native protocol version < 4",
        "Received frame with CUSTOM_PAYLOAD flag for native protocol version < 4",
    ),
    DISPATCHER_SOURCE: (
        "if (connection.getVersion().isGreaterOrEqualTo(ProtocolVersion.V4))\n            ClientWarn.instance.captureWarnings();",
        "if (request.isTrackable())\n            CoordinatorWarnings.init();",
        "response.setWarnings(ClientWarn.instance.getWarnings());",
        "if (request.isTrackable())\n                CoordinatorWarnings.done();",
        "error.setWarnings(ClientWarn.instance.getWarnings());",
    ),
    OPTIONS_SOURCE: (
        "public class OptionsMessage extends Message.Request",
        "public int encodedSize(OptionsMessage msg, ProtocolVersion version)",
        "return 0;",
        "return new SupportedMessage(supported);",
    ),
    STARTUP_SOURCE: (
        "public class StartupMessage extends Message.Request",
        "return new StartupMessage(upperCaseKeys(CBUtil.readStringMap(body)));",
        "return authenticator.getAuthenticateMessage(clientState);",
        "return new ReadyMessage();",
    ),
    AUTH_RESPONSE_SOURCE: (
        "public class AuthResponse extends Message.Request",
        'throw new ProtocolException("SASL Authentication is not supported in version 1 of the protocol")',
        "return new AuthSuccess(challenge);",
        "return new AuthChallenge(challenge);",
        "return ErrorMessage.fromException(e);",
    ),
    ERROR_SOURCE: ("public class ErrorMessage extends Message.Response", "public static final Message.Codec<ErrorMessage> codec"),
    EVENT_SOURCE: ("public class EventMessage extends Message.Response", "this.setStreamId(-1);"),
    SUPPORTED_SOURCE: ("public class SupportedMessage extends Message.Response", "CBUtil.writeStringToStringListMap(msg.supported, dest);"),
    AUTHENTICATE_SOURCE: ("public class AuthenticateMessage extends Message.Response", "CBUtil.writeAsciiString(msg.authenticator, dest);"),
    AUTH_CHALLENGE_SOURCE: ("public class AuthChallenge extends Message.Response", "CBUtil.writeValue(challenge.token, dest);"),
    AUTH_SUCCESS_SOURCE: ("public class AuthSuccess extends Message.Response", "CBUtil.writeValue(success.token, dest);"),
}

DOC_REQUIRED_TOKENS = (
    "module-native-protocol-extras-negative-matrix.md",
    "module-native-protocol-extras-drift-checker.md",
    "check-native-protocol-extras-drift.py",
    MESSAGE_SOURCE,
    DISPATCHER_SOURCE,
    OPTIONS_SOURCE,
    STARTUP_SOURCE,
    AUTH_RESPONSE_SOURCE,
    ERROR_SOURCE,
    EVENT_SOURCE,
    SUPPORTED_SOURCE,
    AUTHENTICATE_SOURCE,
    AUTH_CHALLENGE_SOURCE,
    AUTH_SUCCESS_SOURCE,
    MESSAGE_PAYLOAD_TEST,
    PROTOCOL_NEGOTIATION_TEST,
    RATE_LIMITING_TEST,
    CLIENT_RESOURCE_LIMITS_TEST,
    ERROR_MESSAGE_TEST,
    AUTHENTICATE_MESSAGE_TEST,
    AUTH_MESSAGE_SIZE_LIMIT_TEST,
    "OPTIONS",
    "STARTUP",
    "AUTH_RESPONSE",
    "ERROR",
    "EVENT",
    "SUPPORTED",
    "AUTHENTICATE",
    "AUTH_CHALLENGE",
    "AUTH_SUCCESS",
    "CUSTOM_PAYLOAD",
    "TRACING",
    "WARNING",
) + SCENARIO_IDS


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def class_body(text: str, class_name: str) -> tuple[str, str]:
    match = re.search(rf"\bpublic\s+class\s+{re.escape(class_name)}\s+extends\s+Message\.(Request|Response)\b[^\{{]*\{{", text)
    if not match:
        raise ValueError(f"Could not locate message class {class_name}")

    parent = match.group(1)
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
        raise ValueError(f"Could not parse class {class_name}")
    return parent, text[start:index - 1]


def method_returns_true(body: str, method_name: str) -> bool:
    match = re.search(rf"\bprotected\s+boolean\s+{re.escape(method_name)}\s*\(\s*\)\s*\{{(.*?)\n\s*\}}", body, re.S)
    return bool(match and "return true;" in match.group(1))


def method_overridden(body: str, method_name: str) -> bool:
    return re.search(rf"\bprotected\s+boolean\s+{re.escape(method_name)}\s*\(", body) is not None


def class_profile(class_name: str, path: str) -> dict[str, object]:
    parent, body = class_body(read(path), class_name)
    return {
        "class": class_name,
        "path": path,
        "parent": parent,
        "traceable": method_returns_true(body, "isTraceable"),
        "trackable": method_returns_true(body, "isTrackable"),
        "overrides_traceable": method_overridden(body, "isTraceable"),
        "overrides_trackable": method_overridden(body, "isTrackable"),
        "uses_custom_payload": "getCustomPayload()" in body,
    }


def order_check(text: str, tokens: tuple[str, ...]) -> bool:
    positions = []
    for token in tokens:
        index = text.find(token)
        if index == -1:
            return False
        positions.append(index)
    return positions == sorted(positions)


def source_checks() -> tuple[list[Check], dict[str, object]]:
    checks = []
    metadata: dict[str, object] = {}

    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(Check(f"source token contract {path}", path, all(token in text for token in tokens)))

    message_text = read(MESSAGE_SOURCE)
    checks.extend(
        (
            Check(
                "Message response prelude order",
                MESSAGE_SOURCE,
                order_check(message_text, ("CBUtil.writeUUID(tracingId, body)", "CBUtil.writeStringList(warnings, body)", "CBUtil.writeBytesMap(customPayload, body)")),
            ),
            Check(
                "Message request prelude has custom payload body only",
                MESSAGE_SOURCE,
                "if (((Request)this).isTracingRequested())\n                    flags.add(Envelope.Header.Flag.TRACING);" in message_text
                and "CBUtil.writeBytesMap(payload, body)" in message_text,
            ),
            Check(
                "Message custom payload version gates",
                MESSAGE_SOURCE,
                "Must not send frame with CUSTOM_PAYLOAD flag for native protocol version < 4" in message_text
                and "Received frame with CUSTOM_PAYLOAD flag for native protocol version < 4" in message_text,
            ),
        )
    )

    request_profiles = {name: class_profile(class_name, path) for name, (class_name, path) in REQUEST_TARGETS.items()}
    comparison_profiles = {name: class_profile(class_name, path) for name, (class_name, path, _, _) in TRACEABLE_COMPARISON_TARGETS.items()}
    response_profiles = {name: class_profile(class_name, path) for name, (class_name, path) in RESPONSE_TARGETS.items()}

    for name, profile in request_profiles.items():
        checks.append(
            Check(
                f"request profile {name} remains non-traceable non-trackable and payload-unused",
                str(profile["path"]),
                profile["parent"] == "Request"
                and not profile["overrides_traceable"]
                and not profile["overrides_trackable"]
                and not profile["uses_custom_payload"],
            )
        )

    for name, (class_name, path, expected_traceable, expected_trackable) in TRACEABLE_COMPARISON_TARGETS.items():
        profile = comparison_profiles[name]
        checks.append(
            Check(
                f"comparison request profile {name}",
                path,
                profile["parent"] == "Request"
                and profile["traceable"] == expected_traceable
                and profile["trackable"] == expected_trackable,
            )
        )

    for name, profile in response_profiles.items():
        checks.append(Check(f"response profile {name} extends Message.Response", str(profile["path"]), profile["parent"] == "Response"))

    payload_test = read(MESSAGE_PAYLOAD_TEST)
    negotiation_test = read(PROTOCOL_NEGOTIATION_TEST)
    rate_test = read(RATE_LIMITING_TEST)
    limits_test = read(CLIENT_RESOURCE_LIMITS_TEST)
    error_test = read(ERROR_MESSAGE_TEST)
    auth_message_test = read(AUTHENTICATE_MESSAGE_TEST)
    auth_size_test = read(AUTH_MESSAGE_SIZE_LIMIT_TEST)

    checks.extend(
        (
            Check(
                "MessagePayloadTest covers query-like payload but not target handshake/auth payload",
                MESSAGE_PAYLOAD_TEST,
                all(token in payload_test for token in ("queryMessage.setCustomPayload", "prepareMessage.setCustomPayload", "executeMessage.setCustomPayload", "batchMessage.setCustomPayload"))
                and not any(token in payload_test for token in ("OptionsMessage", "StartupMessage", "AuthResponse")),
            ),
            Check(
                "ProtocolNegotiationTest covers OPTIONS and STARTUP without extras",
                PROTOCOL_NEGOTIATION_TEST,
                "OptionsMessage options = new OptionsMessage();" in negotiation_test
                and "StartupMessage startup = new StartupMessage" in negotiation_test
                and "setCustomPayload" not in negotiation_test,
            ),
            Check(
                "Warning tests cover V4+ query warning attachment",
                f"{RATE_LIMITING_TEST} / {CLIENT_RESOURCE_LIMITS_TEST}",
                "assertWarningsContain(response, BACKPRESSURE_WARNING_SNIPPET)" in rate_test
                and 'assertWarningsContain(aboveThresholdResponse, "bytes in flight")' in limits_test,
            ),
            Check(
                "Error and auth tests cover bodies but not generic extras",
                f"{ERROR_MESSAGE_TEST} / {AUTHENTICATE_MESSAGE_TEST} / {AUTH_MESSAGE_SIZE_LIMIT_TEST}",
                "encodeThenDecode(ErrorMessage.fromException" in error_test
                and "encodeThenDecode(origin, ProtocolVersion.V5)" in auth_message_test
                and "new AuthResponse(authenticator.initialResponse())" in auth_size_test
                and "setCustomPayload" not in auth_message_test
                and "setCustomPayload" not in auth_size_test,
            ),
        )
    )

    metadata["non_traceable_request_targets"] = list(request_profiles)
    metadata["traceable_comparison_targets"] = [name for name, profile in comparison_profiles.items() if profile["traceable"]]
    metadata["trackable_comparison_targets"] = [name for name, profile in comparison_profiles.items() if profile["trackable"]]
    metadata["response_targets"] = list(response_profiles)
    metadata["request_profiles"] = request_profiles
    metadata["comparison_profiles"] = comparison_profiles
    metadata["response_profiles"] = response_profiles
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
            "dispatcher": DISPATCHER_SOURCE,
            "request_targets": {name: path for name, (_, path) in REQUEST_TARGETS.items()},
            "comparison_targets": {name: path for name, (_, path, _, _) in TRACEABLE_COMPARISON_TARGETS.items()},
            "response_targets": {name: path for name, (_, path) in RESPONSE_TARGETS.items()},
            "tests": [
                MESSAGE_PAYLOAD_TEST,
                PROTOCOL_NEGOTIATION_TEST,
                RATE_LIMITING_TEST,
                CLIENT_RESOURCE_LIMITS_TEST,
                ERROR_MESSAGE_TEST,
                AUTHENTICATE_MESSAGE_TEST,
                AUTH_MESSAGE_SIZE_LIMIT_TEST,
            ],
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
    parser = argparse.ArgumentParser(description="Check native protocol extra flag negative matrix source/doc drift.")
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
            print("Native protocol extras drift check failed.")
            for entry in failed_sources + failed_docs:
                print(f"- {entry['name']} ({entry['source']})")
        else:
            metadata = result["metadata"]
            print(
                "Native protocol extras drift check passed: "
                f"{len(metadata['non_traceable_request_targets'])} non-traceable request targets, "
                f"{len(metadata['traceable_comparison_targets'])} traceable comparison requests, "
                f"{len(metadata['trackable_comparison_targets'])} trackable comparison requests, "
                f"{len(metadata['response_targets'])} response targets."
            )

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
