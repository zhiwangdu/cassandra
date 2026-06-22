#!/usr/bin/env python3
#
# Source-only drift check for prepared statement compatibility research coverage.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

PREPARE_MESSAGE_SOURCE = "src/java/org/apache/cassandra/transport/messages/PrepareMessage.java"
EXECUTE_MESSAGE_SOURCE = "src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java"
RESULT_MESSAGE_SOURCE = "src/java/org/apache/cassandra/transport/messages/ResultMessage.java"
QUERY_PROCESSOR_SOURCE = "src/java/org/apache/cassandra/cql3/QueryProcessor.java"
QUERY_HANDLER_SOURCE = "src/java/org/apache/cassandra/cql3/QueryHandler.java"
RESULT_SET_SOURCE = "src/java/org/apache/cassandra/cql3/ResultSet.java"
SYSTEM_KEYSPACE_SOURCE = "src/java/org/apache/cassandra/db/SystemKeyspace.java"
CQL_METRICS_SOURCE = "src/java/org/apache/cassandra/metrics/CQLMetrics.java"
CONFIG_SOURCE = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR_SOURCE = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"

TARGET_DOCS = (
    "research/module-prepared-statement-compatibility-matrix.md",
    "research/module-prepared-statement-compat-drift-checker.md",
    "research/module-schema-cql-auth-native-third-round.md",
    "research/module-schema-cql-auth.md",
    "research/module-native-protocol.md",
    "research/flow-cql-request.md",
    "research/notes/source-map.md",
)

EXPECTED_RESULT_SET_FLAGS = (
    "GLOBAL_TABLES_SPEC",
    "HAS_MORE_PAGES",
    "NO_METADATA",
    "METADATA_CHANGED",
)

EXPECTED_SYSTEM_PREPARED_COLUMNS = (
    "prepared_id",
    "logged_keyspace",
    "query_string",
)

EXPECTED_CQL_PREPARED_METRICS = (
    "PreparedStatementsExecuted",
    "PreparedStatementsEvicted",
    "PreparedStatementsCount",
    "PreparedStatementsRatio",
)

EXPECTED_UPGRADE_VERSION = "4.0.2"
EXPECTED_PRELOAD_PAGE_SIZE = 5000

SCENARIO_IDS = (
    "prepared_prepare_v5_keyspace_flag",
    "prepared_execute_v5_result_metadata_id",
    "prepared_result_prepared_v5_result_metadata_id",
    "prepared_id_four_hash_matrix",
    "prepared_new_behaviour_upgrade_gate",
    "prepared_cache_persistence_contract",
    "prepared_schema_invalidation_contract",
    "prepared_metadata_flag_contract",
    "prepared_metrics_and_logs_contract",
    "prepared_test_coverage_surface",
    "prepared_external_driver_gap",
)

SOURCE_TOKEN_CHECKS = {
    PREPARE_MESSAGE_SOURCE: (
        "version.isGreaterOrEqualTo(ProtocolVersion.V5)",
        "int flags = (int)body.readUnsignedInt()",
        "(flags & 0x1) == 0x1",
        "CBUtil.writeAsciiString(msg.keyspace, dest)",
        "state.getClientState().cloneWithKeyspaceIfSet(keyspace)",
        "QueryEvents.instance.notifyPrepareSuccess",
        "QueryEvents.instance.notifyPrepareFailure",
        "Keyspace is set via query options. This is considered dangerous",
    ),
    EXECUTE_MESSAGE_SOURCE: (
        "MD5Digest statementId = MD5Digest.wrap(CBUtil.readBytes(body))",
        "if (version.isGreaterOrEqualTo(ProtocolVersion.V5))",
        "resultMetadataId = MD5Digest.wrap(CBUtil.readBytes(body))",
        "throw new PreparedQueryNotFoundException(statementId)",
        "warnAboutUseWithPreparedStatements(statementId, prepared.keyspace)",
        "QueryOptions.addColumnSpecifications(options, prepared.statement.getBindVariables())",
        "resultMetadata.setMetadataChanged()",
        "resultMetadata.setSkipMetadata()",
        "prepared.resultMetadataId.equals(resultMetadata.getResultMetadataId())",
    ),
    RESULT_MESSAGE_SOURCE: (
        "public static class Prepared extends ResultMessage",
        "if (version.isGreaterOrEqualTo(ProtocolVersion.V5))",
        "CBUtil.writeBytes(prepared.resultMetadataId.bytes, dest)",
        "ResultSet.PreparedMetadata.codec.encode(prepared.metadata, dest, version)",
        "ResultSet.ResultMetadata.codec.encode(prepared.resultMetadata, dest, version)",
    ),
    QUERY_PROCESSOR_SOURCE: (
        'NEW_PREPARED_STATEMENT_BEHAVIOUR_SINCE_40 = new CassandraVersion("4.0.2")',
        "PRELOAD_PREPARED_STATEMENTS_FETCH_SIZE = 5000",
        "DatabaseDescriptor.getForceNewPreparedStatementBehaviour()",
        "Gossiper.instance.getMinVersion",
        "hashWithoutKeyspace = computeId(queryString, null)",
        "hashWithKeyspace = computeId(queryString, clientState.getRawKeyspace())",
        "String toHash = keyspace == null ? queryString : keyspace + queryString",
        "storePreparedStatement(queryString, null, prepared)",
        "storePreparedStatement(queryString, clientState.getRawKeyspace(), prepared)",
        "SystemKeyspace.writePreparedStatement(keyspace, statementId, queryString, prepared.timestamp)",
        "removeInvalidPreparedStatementsForFunction",
        "removeInvalidPreparedStatements(before.keyspace, before.name)",
        "prepared statements discarded in the last minute because cache limit reached",
    ),
    QUERY_HANDLER_SOURCE: (
        "public final MD5Digest resultMetadataId",
        "public final String rawCQLStatement",
        "public final String keyspace",
        "public final boolean fullyQualified",
        "this.timestamp = ClientState.getTimestamp()",
    ),
    RESULT_SET_SOURCE: (
        "public void setSkipMetadata()",
        "public void setMetadataChanged()",
        "assert version.isGreaterOrEqualTo(ProtocolVersion.V5) : \"MetadataChanged flag is not supported before native protocol v5\"",
        "CBUtil.writeBytes(m.getResultMetadataId().bytes, dest)",
        "if (version.isGreaterOrEqualTo(ProtocolVersion.V4))",
        "statement.getPartitionKeyBindVariableIndexes()",
        "static MD5Digest computeResultMetadataId",
    ),
    SYSTEM_KEYSPACE_SOURCE: (
        "prepared_id blob",
        "logged_keyspace text",
        "query_string text",
        "writePreparedStatement(String loggedKeyspace, MD5Digest key, String cql, long timestamp)",
        "loadPreparedStatements(TriFunction<MD5Digest, String, String, Prepared> onLoaded, int pageSize)",
        "preparedBytesLoadThreshold = (long) (PREPARED_STATEMENT_CACHE_SIZE_BYTES * 1.1)",
        "Consider truncating {}.{} to clear out leaked prepared statements.",
    ),
    CQL_METRICS_SOURCE: EXPECTED_CQL_PREPARED_METRICS,
    CONFIG_SOURCE: (
        "force_new_prepared_statement_behaviour",
        "prepared_statements_cache_size",
        "prepared_statements_cache_size_mb",
    ),
    DATABASE_DESCRIPTOR_SOURCE: (
        "getPreparedStatementsCacheSizeMiB()",
        "getForceNewPreparedStatementBehaviour()",
        "setForceNewPreparedStatementBehaviour(boolean value)",
        "max(1/256 of Heap (in MiB), 10MiB)",
    ),
}

DOC_REQUIRED_TOKENS = (
    "4.0.2",
    "5000",
    "prepared_statements_cache_size",
    "force_new_prepared_statement_behaviour",
    "system.prepared_statements",
    "prepared_id",
    "logged_keyspace",
    "query_string",
    "PreparedStatementsExecuted",
    "PreparedStatementsEvicted",
    "PreparedStatementsCount",
    "PreparedStatementsRatio",
    PREPARE_MESSAGE_SOURCE,
    EXECUTE_MESSAGE_SOURCE,
    RESULT_MESSAGE_SOURCE,
    QUERY_PROCESSOR_SOURCE,
    QUERY_HANDLER_SOURCE,
    RESULT_SET_SOURCE,
    SYSTEM_KEYSPACE_SOURCE,
    CQL_METRICS_SOURCE,
    "PreparedStatementsTest.java",
    "PstmtPersistenceTest.java",
    "PreparedStatementTest.java",
    "PrepareMessageTest.java",
    "SerDeserTest.java",
    "PrepareBatchStatementsTest.java",
) + SCENARIO_IDS + EXPECTED_RESULT_SET_FLAGS + EXPECTED_SYSTEM_PREPARED_COLUMNS + EXPECTED_CQL_PREPARED_METRICS


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def result_set_flags() -> tuple[str, ...]:
    text = read(RESULT_SET_SOURCE)
    match = re.search(r"public enum Flag\s*\{(.*?)\n\s*public static EnumSet<Flag> deserialize", text, re.S)
    if not match:
        raise ValueError("Could not locate ResultSet.Flag enum")
    return tuple(re.findall(r"\b([A-Z][A-Z0-9_]+)\s*,?", match.group(1).split(";")[0]))


def system_prepared_columns() -> tuple[str, ...]:
    text = read(SYSTEM_KEYSPACE_SOURCE)
    match = re.search(r"private static final TableMetadata PreparedStatements\s*=\s*parse\(.*?CREATE TABLE %s \(\"(.*?)PRIMARY KEY", text, re.S)
    if not match:
        raise ValueError("Could not locate SystemKeyspace.PreparedStatements table")
    return tuple(re.findall(r"\+\s*\"([a-z_]+)\s+[a-z]+,", match.group(1)))


def cql_prepared_metrics() -> tuple[str, ...]:
    text = read(CQL_METRICS_SOURCE)
    return tuple(name for name in EXPECTED_CQL_PREPARED_METRICS if f'createMetricName("{name}")' in text)


def upgrade_version() -> str:
    text = read(QUERY_PROCESSOR_SOURCE)
    match = re.search(r'NEW_PREPARED_STATEMENT_BEHAVIOUR_SINCE_40\s*=\s*new CassandraVersion\("([^"]+)"\)', text)
    if not match:
        raise ValueError("Could not locate prepared behavior upgrade version")
    return match.group(1)


def preload_page_size() -> int:
    text = read(QUERY_PROCESSOR_SOURCE)
    match = re.search(r"PRELOAD_PREPARED_STATEMENTS_FETCH_SIZE\s*=\s*(\d+)", text)
    if not match:
        raise ValueError("Could not locate preload page size")
    return int(match.group(1))


def source_checks() -> tuple[list[Check], dict[str, object]]:
    flags = result_set_flags()
    columns = system_prepared_columns()
    metrics = cql_prepared_metrics()
    version = upgrade_version()
    page_size = preload_page_size()

    checks = [
        Check("Prepared behavior upgrade version matches baseline", QUERY_PROCESSOR_SOURCE, version == EXPECTED_UPGRADE_VERSION),
        Check("Prepared preload page size matches baseline", QUERY_PROCESSOR_SOURCE, page_size == EXPECTED_PRELOAD_PAGE_SIZE),
        Check("ResultSet.Flag order matches baseline", RESULT_SET_SOURCE, flags == EXPECTED_RESULT_SET_FLAGS),
        Check("system.prepared_statements columns match baseline", SYSTEM_KEYSPACE_SOURCE, columns == EXPECTED_SYSTEM_PREPARED_COLUMNS),
        Check("CQL prepared metrics match baseline", CQL_METRICS_SOURCE, metrics == EXPECTED_CQL_PREPARED_METRICS),
    ]

    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(Check(f"source token contract {path}", path, all(token in text for token in tokens)))

    metadata = {
        "upgrade_version": version,
        "preload_page_size": page_size,
        "result_set_flags": list(flags),
        "system_prepared_columns": list(columns),
        "cql_prepared_metrics": list(metrics),
    }
    return checks, metadata


def read_doc_text() -> str:
    return "\n".join(read(path) for path in TARGET_DOCS)


def doc_checks() -> list[Check]:
    text = read_doc_text()
    return [Check(f"doc token {token}", " / ".join(TARGET_DOCS), token in text if token.endswith(".java") or "/" in token else documented(token, text)) for token in DOC_REQUIRED_TOKENS]


def check() -> tuple[dict[str, object], bool]:
    sources, metadata = source_checks()
    docs = doc_checks()
    result = {
        "sources": {
            "prepare_message": PREPARE_MESSAGE_SOURCE,
            "execute_message": EXECUTE_MESSAGE_SOURCE,
            "result_message": RESULT_MESSAGE_SOURCE,
            "query_processor": QUERY_PROCESSOR_SOURCE,
            "query_handler": QUERY_HANDLER_SOURCE,
            "result_set": RESULT_SET_SOURCE,
            "system_keyspace": SYSTEM_KEYSPACE_SOURCE,
            "cql_metrics": CQL_METRICS_SOURCE,
            "config": CONFIG_SOURCE,
            "database_descriptor": DATABASE_DESCRIPTOR_SOURCE,
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
    parser = argparse.ArgumentParser(description="Check prepared statement compatibility source/doc drift.")
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
            print("Prepared statement compatibility drift check failed.")
            for entry in failed_sources + failed_docs:
                print(f"- {entry['name']} ({entry['source']})")
        else:
            metadata = result["metadata"]
            print(
                "Prepared statement compatibility drift check passed: "
                f"upgrade gate {metadata['upgrade_version']}, "
                f"preload page size {metadata['preload_page_size']}, "
                f"{len(metadata['result_set_flags'])} metadata flags, "
                f"{len(metadata['system_prepared_columns'])} system columns, "
                f"{len(metadata['cql_prepared_metrics'])} CQL metrics."
            )

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
