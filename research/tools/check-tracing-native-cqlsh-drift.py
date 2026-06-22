#!/usr/bin/env python3
#
# Source-only drift check for tracing native/cqlsh operations research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

ENVELOPE_SOURCE = "src/java/org/apache/cassandra/transport/Envelope.java"
MESSAGE_SOURCE = "src/java/org/apache/cassandra/transport/Message.java"
QUERY_SOURCE = "src/java/org/apache/cassandra/transport/messages/QueryMessage.java"
PREPARE_SOURCE = "src/java/org/apache/cassandra/transport/messages/PrepareMessage.java"
EXECUTE_SOURCE = "src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java"
BATCH_SOURCE = "src/java/org/apache/cassandra/transport/messages/BatchMessage.java"
TRACING_SOURCE = "src/java/org/apache/cassandra/tracing/Tracing.java"
TRACING_IMPL_SOURCE = "src/java/org/apache/cassandra/tracing/TracingImpl.java"
TRACE_STATE_IMPL_SOURCE = "src/java/org/apache/cassandra/tracing/TraceStateImpl.java"
TRACE_KEYSPACE_SOURCE = "src/java/org/apache/cassandra/tracing/TraceKeyspace.java"
STORAGE_SERVICE_SOURCE = "src/java/org/apache/cassandra/service/StorageService.java"
SET_TRACE_PROBABILITY_SOURCE = "src/java/org/apache/cassandra/tools/nodetool/SetTraceProbability.java"
CQLSH_MAIN = "pylib/cqlshlib/cqlshmain.py"
CQLSH_TRACING = "pylib/cqlshlib/tracing.py"

TRACE_CQL_TEST = "test/unit/org/apache/cassandra/cql3/TraceCqlTest.java"
TRACING_TEST = "test/unit/org/apache/cassandra/tracing/TracingTest.java"
CQLSH_COMPLETION_TEST = "pylib/cqlshlib/test/test_cqlsh_completion.py"
DTEST_COORDINATOR = "test/distributed/org/apache/cassandra/distributed/impl/Coordinator.java"
DTEST_TRACING_UTIL = "test/distributed/org/apache/cassandra/distributed/impl/TracingUtil.java"

TARGET_DOCS = (
    "research/module-tracing-native-cqlsh.md",
    "research/module-tracing-native-cqlsh-matrix.md",
    "research/module-tracing-native-cqlsh-drift-checker.md",
    "research/flow-native-protocol.md",
    "research/flow-cql-request.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "tracing_native_flag_decode_encode",
    "tracing_request_wrapper_lifecycle",
    "tracing_query_prepare_execute_batch_begin",
    "tracing_probabilistic_sampling_boundary",
    "tracing_system_traces_mutation_async",
    "tracing_internode_propagation",
    "tracing_cqlsh_toggle_show_session",
    "tracing_config_ttl_wait_custom_class",
    "tracing_test_coverage_and_frame_gap",
)

SOURCE_TOKEN_CHECKS = {
    ENVELOPE_SOURCE: (
        "public enum Flag",
        "COMPRESSED,\n            TRACING,\n            CUSTOM_PAYLOAD,\n            WARNING,\n            USE_BETA;",
        "public static EnumSet<Flag> deserialize(int flags)",
        "public static int serialize(EnumSet<Flag> flags)",
    ),
    MESSAGE_SOURCE: (
        "protected boolean isTraceable()",
        "protected abstract Response execute(QueryState queryState, Dispatcher.RequestTime requestTime, boolean traceRequest);",
        "public final Response execute(QueryState queryState, Dispatcher.RequestTime requestTime)",
        "if (isTraceable())",
        "if (isTracingRequested())",
        "tracingSessionId = nextTimeUUID();",
        "Tracing.instance.newSession(tracingSessionId, getCustomPayload());",
        "else if (StorageService.instance.shouldTraceProbablistically())",
        "Tracing.instance.newSession(getCustomPayload());",
        "if (shouldTrace)\n                    Tracing.instance.stopSession();",
        "if (isTraceable() && isTracingRequested())\n                response.setTracingId(tracingSessionId);",
        "void setTracingRequested()",
        "boolean isTracingRequested()",
        "if (((Request)this).isTracingRequested())\n                    flags.add(Envelope.Header.Flag.TRACING);",
        "CBUtil.writeUUID(tracingId, body);",
        "flags.add(Envelope.Header.Flag.TRACING);",
        "TimeUUID tracingId = isRequest || !isTracing ? null : CBUtil.readTimeUUID(inbound.body);",
        "if (isTracing)\n                    req.setTracingRequested();",
        "if (isTracing)\n                    ((Response) message).setTracingId(tracingId);",
    ),
    QUERY_SOURCE: (
        "protected boolean isTraceable()",
        "protected boolean isTrackable()",
        "if (traceRequest)\n                traceQuery(state);",
        'builder.put("query", query);',
        'builder.put("page_size", Integer.toString(options.getPageSize()));',
        'builder.put("consistency_level", options.getConsistency().name());',
        'builder.put("serial_consistency_level", options.getSerialConsistency().name());',
        'Tracing.instance.begin("Execute CQL3 query", state.getClientAddress(), builder.build());',
    ),
    PREPARE_SOURCE: (
        "protected boolean isTraceable()",
        'Tracing.instance.begin("Preparing CQL3 query", state.getClientAddress(), ImmutableMap.of("query", query));',
        "queryHandler.prepare(query, clientState, getCustomPayload());",
    ),
    EXECUTE_SOURCE: (
        "protected boolean isTraceable()",
        "protected boolean isTrackable()",
        "if (traceRequest)\n                traceQuery(state, prepared);",
        'builder.put("query", prepared.rawCQLStatement);',
        'String boundValue = (bytes == ByteBufferUtil.UNSET_BYTE_BUFFER) ? "<unset>" : cs.type.asCQL3Type().toCQLLiteral(bytes);',
        'boundValue = boundValue.substring(0, 1000) + "...\'";',
        'builder.put("bound_var_" + i + \'_\' + boundName, boundValue);',
        'Tracing.instance.begin("Execute CQL3 prepared query", state.getClientAddress(), builder.build());',
    ),
    BATCH_SOURCE: (
        "protected boolean isTraceable()",
        "protected boolean isTrackable()",
        "if (traceRequest)\n                traceQuery(state);",
        "TODO we don't have [typed] access to CQL bind variables here.  CASSANDRA-4560 is open to add support.",
        'Tracing.instance.begin("Execute batch of CQL3 queries", state.getClientAddress(), builder.build());',
    ),
    TRACING_SOURCE: (
        "public enum TraceType",
        "NONE,\n        QUERY,\n        REPAIR;",
        "private static final int[] TTLS = { DatabaseDescriptor.getTracetypeQueryTTL(),",
        "String customTracingClass = CUSTOM_TRACING_CLASS.getString();",
        "protected final ConcurrentMap<TimeUUID, TraceState> sessions = new ConcurrentHashMap<>();",
        "public TimeUUID newSession(Map<String,ByteBuffer> customPayload)",
        "public TimeUUID newSession(TimeUUID sessionId, Map<String,ByteBuffer> customPayload)",
        "TraceState ts = newTraceState(localAddress, sessionId, traceType);",
        "sessions.put(sessionId, ts);",
        "public void stopSession()",
        "stopSessionImpl();",
        "sessions.remove(state.sessionId);",
        "public TraceState initializeFromMessage(final Message.Header header)",
        "final TimeUUID sessionId = header.traceSession();",
        "return new ExpiredTraceState(newTraceState(header.from, sessionId, traceType));",
        "public void traceOutgoingMessage(Message<?> message, int serializedSize, InetAddressAndPort sendTo)",
        "String logMessage = String.format(\"Sending %s message to %s message size %d bytes\", message.verb(), sendTo,",
        "public Map<ParamType, Object> addTraceHeaders(Map<ParamType, Object> addToMutable)",
        "addToMutable.put(ParamType.TRACE_SESSION, Tracing.instance.getSessionId());",
        "addToMutable.put(ParamType.TRACE_TYPE, Tracing.instance.getTraceType());",
    ),
    TRACING_IMPL_SOURCE: (
        "state.executeMutation(TraceKeyspace.makeStopSessionMutation(sessionId, elapsed, ttl));",
        "state.executeMutation(TraceKeyspace.makeStartSessionMutation(sessionId, client, parameters, request, startedAt, command, ttl));",
        "Stage.TRACING.execute(new WrappedRunnable()",
        "TraceStateImpl.mutateWithCatch(TraceKeyspace.makeEventMutation(sessionId, message, -1, threadName, ttl));",
    ),
    TRACE_STATE_IMPL_SOURCE: (
        "public static int WAIT_FOR_PENDING_EVENTS_TIMEOUT_SECS = CassandraRelevantProperties.WAIT_FOR_TRACING_EVENTS_TIMEOUT_SECS.getInt();",
        "private final Set<Future<?>> pendingFutures = ConcurrentHashMap.newKeySet();",
        "executeMutation(TraceKeyspace.makeEventMutation(sessionIdBytes, message, elapsed, threadName, ttl));",
        "FutureCombiner.allOf(Arrays.asList(pendingFutures.toArray(new Future<?>[pendingFutures.size()])))",
        "Future<Void> fut = Stage.TRACING.executor().submit(() -> mutateWithCatch(mutation), null);",
        "StorageProxy.mutate(singletonList(mutation), ANY, Dispatcher.RequestTime.forImmediateExecution());",
        'Tracing.logger.warn("Too many nodes are overloaded to save trace events");',
    ),
    TRACE_KEYSPACE_SOURCE: (
        "private static final int DEFAULT_RF = CassandraRelevantProperties.SYSTEM_TRACES_DEFAULT_RF.getInt();",
        'public static final String SESSIONS = "sessions";',
        'public static final String EVENTS = "events";',
        "CREATE TABLE %s (",
        "parameters map<text, text>,",
        "source_elapsed int,",
        "KeyspaceParams.simple(Math.max(DEFAULT_RF, DatabaseDescriptor.getDefaultKeyspaceRF()))",
        "static Mutation makeStartSessionMutation",
        "static Mutation makeStopSessionMutation",
        "static Mutation makeEventMutation",
    ),
    STORAGE_SERVICE_SOURCE: (
        "public void setTraceProbability(double probability)",
        "public double getTraceProbability()",
        "public boolean shouldTraceProbablistically()",
        "return traceProbability != 0 && ThreadLocalRandom.current().nextDouble() < traceProbability;",
    ),
    SET_TRACE_PROBABILITY_SOURCE: (
        '@Command(name = "settraceprobability"',
        "Trace probability between 0 and 1",
        "checkArgument(traceProbability >= 0 && traceProbability <= 1, \"Trace probability must be between 0 and 1\");",
        "probe.setTraceProbability(traceProbability);",
    ),
    CQLSH_MAIN: (
        "self.tracing_enabled = self.tracing_enabled and not stop_tracing",
        "future.get_all_query_traces(max_wait_per=self.max_trace_wait, query_cl=self.consistency_level)",
        "Statement trace did not complete within %d seconds; trace data may be incomplete.",
        "self.show_session(trace_id, partial_session=True)",
        "SHOW SESSION <sessionid>",
        "self.show_session(UUID(session_id))",
        '= self.on_off_switch("TRACING", self.tracing_enabled, parsed.get_binding(\'switch\'))',
        "argvalues.max_trace_wait = option_with_default(configs.getfloat, 'tracing', 'max_trace_wait',",
    ),
    CQLSH_TRACING: (
        "trace = QueryTrace(session_id, session)",
        "trace.populate(wait_for_complete=wait_for_complete)",
        "print_trace(shell, trace)",
        "rows = make_trace_rows(trace)",
        "names = ['activity', 'timestamp', 'source', 'source_elapsed', 'client']",
        "rows.append(['Request complete'",
    ),
    TRACE_CQL_TEST: (
        "public void testCqlStatementTracing()",
        "requireNetwork();",
        ".enableTracing();",
        "getExecutionInfo().getQueryTrace();",
        'assertEquals(cql, trace.getParameters().get("query"));',
        'assertEquals("1", trace.getParameters().get("bound_var_0_id"));',
        'assertEquals(Arrays.asList("13", "\'lukasz\'", "(3, \'bar\', 2.1)", "<unset>"), new ArrayList<>(boundParameters.values()));',
    ),
    TRACING_TEST: (
        "public void test()",
        "public void test_get()",
        "public void test_get_uuid()",
        "public void test_customPayload()",
        "public void test_states()",
        "public void test_progress_listener()",
    ),
    CQLSH_COMPLETION_TEST: (
        "self.trycompletions('SHOW SESSION ', choices=['<uuid>'])",
        "self.trycompletions('TRACING ', choices=[';', '<enter>', 'OFF', 'ON'])",
    ),
    DTEST_COORDINATOR: (
        "public Future<SimpleQueryResult> asyncExecuteWithTracingWithResult",
        "Tracing.instance.newSession(TimeUUID.fromUuid(sessionId), Collections.emptyMap());",
        "Tracing.instance.stopSession();",
    ),
    DTEST_TRACING_UTIL: (
        "public static List<TraceEntry> getTrace(AbstractCluster cluster, UUID sessionId, ConsistencyLevel cl)",
        '"FROM system_traces.events WHERE session_id = ?", cl, sessionId);',
    ),
}

QUERY_MESSAGE_PROFILES = {
    "QueryMessage": (QUERY_SOURCE, True, True),
    "PrepareMessage": (PREPARE_SOURCE, True, False),
    "ExecuteMessage": (EXECUTE_SOURCE, True, True),
    "BatchMessage": (BATCH_SOURCE, True, True),
}

DOC_REQUIRED_TOKENS = (
    "module-tracing-native-cqlsh.md",
    "module-tracing-native-cqlsh-matrix.md",
    "module-tracing-native-cqlsh-drift-checker.md",
    "check-tracing-native-cqlsh-drift.py",
    ENVELOPE_SOURCE,
    MESSAGE_SOURCE,
    QUERY_SOURCE,
    PREPARE_SOURCE,
    EXECUTE_SOURCE,
    BATCH_SOURCE,
    TRACING_SOURCE,
    TRACING_IMPL_SOURCE,
    TRACE_STATE_IMPL_SOURCE,
    TRACE_KEYSPACE_SOURCE,
    STORAGE_SERVICE_SOURCE,
    SET_TRACE_PROBABILITY_SOURCE,
    CQLSH_MAIN,
    CQLSH_TRACING,
    TRACE_CQL_TEST,
    TRACING_TEST,
    CQLSH_COMPLETION_TEST,
    DTEST_COORDINATOR,
    DTEST_TRACING_UTIL,
    "Envelope.Header.Flag",
    "Message.Request",
    "Message.Decoder.decodeMessage",
    "QueryMessage",
    "PrepareMessage",
    "ExecuteMessage",
    "BatchMessage",
    "TraceKeyspace",
    "TraceStateImpl",
    "StorageService.shouldTraceProbablistically",
    "settraceprobability",
    "TRACING ON/OFF",
    "SHOW SESSION",
    "system_traces",
    "frame-level",
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


def class_body(text: str, class_name: str) -> str:
    match = re.search(rf"\bpublic\s+class\s+{re.escape(class_name)}\b[^\{{]*\{{", text)
    if not match:
        raise ValueError(f"Could not locate class {class_name}")

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
    return text[start:index - 1]


def method_returns_true(body: str, method_name: str) -> bool:
    match = re.search(rf"\bprotected\s+boolean\s+{re.escape(method_name)}\s*\(\s*\)\s*\{{(.*?)\n\s*\}}", body, re.S)
    return bool(match and "return true;" in match.group(1))


def method_overridden(body: str, method_name: str) -> bool:
    return re.search(rf"\bprotected\s+boolean\s+{re.escape(method_name)}\s*\(", body) is not None


def source_checks() -> list[Check]:
    checks = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        for token in tokens:
            checks.append(Check(f"source token {token[:72]!r}", path, token in text))
    return checks


def query_message_profile_checks() -> list[Check]:
    checks = []
    for class_name, (path, expected_traceable, expected_trackable) in QUERY_MESSAGE_PROFILES.items():
        body = class_body(read(path), class_name)
        traceable = method_returns_true(body, "isTraceable")
        trackable = method_returns_true(body, "isTrackable")
        trackable_overridden = method_overridden(body, "isTrackable")
        checks.append(Check(f"query profile {class_name} traceable", path, traceable == expected_traceable))
        checks.append(Check(f"query profile {class_name} trackable", path, trackable == expected_trackable))
        if not expected_trackable:
            checks.append(Check(f"query profile {class_name} inherits non-trackable", path, not trackable_overridden))
    return checks


def doc_checks() -> list[Check]:
    docs = {}
    checks = []
    for path in TARGET_DOCS:
        doc_path = REPO_ROOT / path
        exists = doc_path.exists()
        checks.append(Check("doc exists", path, exists))
        docs[path] = doc_path.read_text(encoding="utf-8") if exists else ""

    combined = "\n".join(docs.values())
    for token in DOC_REQUIRED_TOKENS:
        checks.append(Check(f"doc token {token}", "research docs", token in combined))

    readme = docs["research/README.md"]
    source_map = docs["research/notes/source-map.md"]
    for token in ("module-tracing-native-cqlsh-matrix.md", "module-tracing-native-cqlsh-drift-checker.md", "check-tracing-native-cqlsh-drift.py"):
        checks.append(Check(f"README links {token}", "research/README.md", token in readme))
        checks.append(Check(f"source-map links {token}", "research/notes/source-map.md", token in source_map))

    matrix = docs["research/module-tracing-native-cqlsh-matrix.md"]
    for scenario_id in SCENARIO_IDS:
        checks.append(Check(f"matrix scenario {scenario_id}", "research/module-tracing-native-cqlsh-matrix.md", documented(scenario_id, matrix)))

    return checks


def test_gap_checks() -> list[Check]:
    transport_tests = "\n".join(path.read_text(encoding="utf-8") for path in (REPO_ROOT / "test/unit/org/apache/cassandra/transport").glob("*.java"))
    frame_tokens = (
        "setTracingRequested",
        "setTracingId",
        "Envelope.Header.Flag.TRACING",
        "CBUtil.readTimeUUID",
    )
    gap_still_open = not any(token in transport_tests for token in frame_tokens)
    docs = "\n".join(read(path) for path in TARGET_DOCS if (REPO_ROOT / path).exists())
    return [
        Check("frame-level gap remains explicit", "test/unit/org/apache/cassandra/transport", gap_still_open),
        Check("frame-level gap documented", "research docs", "frame-level" in docs and "native frame-level test gap" in docs),
    ]


def check() -> tuple[bool, list[Check]]:
    checks = []
    checks.extend(source_checks())
    checks.extend(query_message_profile_checks())
    checks.extend(doc_checks())
    checks.extend(test_gap_checks())
    return all(item.ok for item in checks), checks


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Check tracing native/cqlsh research drift")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args(argv)

    ok, checks = check()
    if args.json:
        print(json.dumps({"ok": ok, "checks": [item.__dict__ for item in checks]}, indent=2, sort_keys=True))
    else:
        for item in checks:
            if not item.ok:
                print(f"FAIL {item.name} [{item.source}]")
        if ok:
            print(f"OK tracing native/cqlsh drift checks passed ({len(checks)} checks)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
