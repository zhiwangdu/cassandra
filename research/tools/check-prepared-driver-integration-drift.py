#!/usr/bin/env python3
#
# Source-only drift check for prepared driver integration coverage research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

PREPARED_HELPER_SOURCE = "src/java/com/datastax/driver/core/PreparedStatementHelper.java"
REPREPARE_BASE_TEST = "test/distributed/org/apache/cassandra/distributed/test/ReprepareTestBase.java"
REPREPARE_NEW_TEST = "test/distributed/org/apache/cassandra/distributed/test/ReprepareNewBehaviourTest.java"
REPREPARE_OLD_TEST = "test/distributed/org/apache/cassandra/distributed/test/ReprepareOldBehaviourTest.java"
REPREPARE_FUZZ_TEST = "test/distributed/org/apache/cassandra/distributed/test/ReprepareFuzzTest.java"
MIXED_MODE_FUZZ_TEST = "test/distributed/org/apache/cassandra/distributed/test/MixedModeFuzzTest.java"
PREPARE_BATCH_TEST = "test/distributed/org/apache/cassandra/distributed/test/PrepareBatchStatementsTest.java"
JAVA_DRIVER_UTILS_TEST = "test/distributed/org/apache/cassandra/distributed/test/JavaDriverUtils.java"
PREPARED_STATEMENTS_TEST = "test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java"
PSTMT_PERSISTENCE_TEST = "test/unit/org/apache/cassandra/cql3/PstmtPersistenceTest.java"
PROTOCOL_NEGOTIATION_TEST = "test/unit/org/apache/cassandra/transport/ProtocolNegotiationTest.java"
PREPARE_MESSAGE_TEST = "test/unit/org/apache/cassandra/transport/messages/PrepareMessageTest.java"
SERDESER_TEST = "test/unit/org/apache/cassandra/transport/SerDeserTest.java"

TARGET_DOCS = (
    "research/module-prepared-driver-integration-gap-matrix.md",
    "research/module-prepared-driver-integration-drift-checker.md",
    "research/module-prepared-statement-compatibility-matrix.md",
    "research/module-schema-cql-auth-native-third-round.md",
    "research/module-schema-cql-auth-native-deep-dive.md",
    "research/module-schema-cql-auth.md",
    "research/module-native-protocol.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "prepared_driver_java_reprepare_runtime",
    "prepared_driver_keyspace_hash_runtime",
    "prepared_driver_mixed_version_runtime",
    "prepared_driver_fuzz_runtime",
    "prepared_driver_protocol_negotiation_boundary",
    "prepared_driver_v4_v5_metadata_boundary",
    "prepared_driver_wire_codec_boundary",
    "prepared_driver_persistence_runtime",
    "prepared_driver_batch_keyspace_runtime",
    "prepared_driver_non_java_gap",
    "prepared_driver_protocol_matrix_gap",
)

SOURCE_TOKEN_CHECKS = {
    PREPARED_HELPER_SOURCE: (
        "public static void assertHashWithoutKeyspace",
        "public static void assertHashWithKeyspace",
        "return computeId(queryString, ks);",
        "return computeId(queryString, null);",
        "return compute(keyspace == null ? queryString : keyspace + queryString);",
    ),
    REPREPARE_BASE_TEST: (
        "public void testReprepare",
        "public void testReprepareTwoKeyspaces",
        "ForceHostLoadBalancingPolicy",
        "QueryProcessor::clearPreparedStatementsCache",
        "session.execute(select.bind())",
        "session.execute(withKeyspace(\"USE %s\"))",
        "can't execute it on",
        "static void newBehaviour",
        "static void oldBehaviour",
    ),
    REPREPARE_NEW_TEST: (
        "testUseWithMultipleKeyspaces",
        "PreparedStatement selectKs1 = session.prepare(query)",
        "PreparedStatement selectKs2 = session.prepare(query)",
        "selectKs2.getQueryKeyspace()",
        "testReprepareNewBehaviour",
        "testReprepareTwoKeyspacesNewBehaviour",
    ),
    REPREPARE_OLD_TEST: (
        "testReprepareMixedVersion",
        "testReprepareTwoKeyspacesMixedVersion",
        "testReprepareUsingOldBehavior",
        "testReprepareMixedVersionWithoutReset",
        "withInstanceInitializer(PrepareBehaviour::oldBehaviour)",
    ),
    REPREPARE_FUZZ_TEST: (
        "com.datastax.driver.core.PreparedStatement",
        "PreparedStatementHelper.assertHashWithoutKeyspace",
        "PreparedStatementHelper.assertHashWithKeyspace",
        "SystemKeyspace.loadPreparedStatements",
        "QueryProcessor.instance.preloadPreparedStatements()",
        "RELOAD_FROM_TABLES",
        "RECONNECT",
        "SWITCH_KEYSPACE",
    ),
    MIXED_MODE_FUZZ_TEST: (
        "com.datastax.driver.core.PreparedStatement",
        "PreparedStatementHelper.assertHashWithoutKeyspace",
        "Action.BUMP_VERSION",
        "Action.BOUNCE_CLIENT",
        "ID mismatch while trying to reprepare",
        "new CassandraVersion(\"4.0.11\")",
        "QueryProcessor.NEW_PREPARED_STATEMENT_BEHAVIOUR_SINCE_40",
        "public static ResultMessage.Prepared prepare",
    ),
    PREPARE_BATCH_TEST: (
        "public void testPreparedBatch",
        "PreparedStatement prepared",
        "s.prepare(batch1)",
        "s.prepare(batch2)",
        "StorageService.instance.getPreparedStatements()",
        "QueryProcessor.clearPreparedStatements(false)",
    ),
    JAVA_DRIVER_UTILS_TEST: (
        "public static com.datastax.driver.core.Cluster create",
        "ProtocolVersion version",
        "builder.withProtocolVersion(version)",
        "Feature.NATIVE_PROTOCOL",
        "Feature.GOSSIP",
    ),
    PREPARED_STATEMENTS_TEST: (
        "testInvalidatePreparedStatementOnAlterV5",
        "testInvalidatePreparedStatementOnAlterV4",
        "testStatementRePreparationOnReconnect",
        "allowBetaProtocolVersion()",
        "testMetadataFlagsWithLWTs",
        "PreparedQueryNotFoundException",
        "Flag.METADATA_CHANGED",
        "testPrepareWithLWT(ProtocolVersion.V4)",
        "testPrepareWithLWT(ProtocolVersion.V5)",
        "testPrepareWithBatchLWT(ProtocolVersion.V4)",
        "testPrepareWithBatchLWT(ProtocolVersion.V5)",
    ),
    PSTMT_PERSISTENCE_TEST: (
        "testCachedPreparedStatements",
        "testPstmtInvalidation",
        "testAsyncPstmtInvalidation",
        "testPreloadPreparedStatements",
        "testPreloadPreparedStatementsUntilCacheFull",
        "SystemKeyspace.PREPARED_STATEMENTS",
        "QueryProcessor.metrics.preparedStatementsEvicted",
    ),
    PROTOCOL_NEGOTIATION_TEST: (
        "serverSupportsV3AndV4AndV5ByDefault",
        "supportV6ConnectionWithBetaOption",
        "olderVersionsAreUnsupported",
        "ProtocolVersion.SUPPORTED.forEach(this::testStreamIdsAcrossNegotiation)",
        "ProtocolVersion.SUPPORTED.forEach(this::validateMessageVersion)",
        "builder.allowBetaProtocolVersion()",
        "builder.withProtocolVersion(requestedVersion)",
    ),
    PREPARE_MESSAGE_TEST: (
        "new PrepareMessage(\"SELECT * FROM keyspace.tbl WHERE name='ßètæ'\", \"keyspace\")",
        "encodeThenDecode(origin, ProtocolVersion.V5)",
    ),
    SERDESER_TEST: (
        "preparedMetadataSerializationTest",
        "for (ProtocolVersion version : ProtocolVersion.SUPPORTED)",
        "if (version == ProtocolVersion.V3)",
        "v3 encoding doesn't include partition key bind indexes",
        "assertEquals(meta, decodedMeta)",
    ),
}

JAVA_DRIVER_PREPARED_ANCHORS = (
    REPREPARE_BASE_TEST,
    REPREPARE_NEW_TEST,
    REPREPARE_OLD_TEST,
    REPREPARE_FUZZ_TEST,
    MIXED_MODE_FUZZ_TEST,
    PREPARE_BATCH_TEST,
    PREPARED_STATEMENTS_TEST,
)

NON_JAVA_DRIVER_PATTERNS = {
    "python_driver": re.compile(r"\b(cassandra\.cluster|from cassandra\.cluster|cassandra-driver)\b"),
    "go_driver": re.compile(r"\b(gocql|github\.com/gocql/gocql)\b"),
    "node_driver": re.compile(r"\b(cassandra-driver-nodejs|nodejs-driver|datastax/nodejs-driver)\b"),
    "rust_driver": re.compile(r"\b(scylla_cql|cassandra_cpp|cassandra-cpp|cdrs_tokio)\b"),
    "java_driver_4": re.compile(r"\bcom\.datastax\.oss\.driver\.api\b"),
}

DOC_REQUIRED_TOKENS = (
    "research/tools/check-prepared-driver-integration-drift.py",
    "research/module-prepared-driver-integration-gap-matrix.md",
    "research/module-prepared-driver-integration-drift-checker.md",
    "com.datastax.driver.core.PreparedStatement",
    "Session.prepare()",
    "ProtocolNegotiationTest",
    "ReprepareTestBase",
    "ReprepareNewBehaviourTest",
    "ReprepareOldBehaviourTest",
    "ReprepareFuzzTest",
    "MixedModeFuzzTest",
    "PreparedStatementHelper",
    "PreparedStatementsTest",
    "PstmtPersistenceTest",
    "PrepareBatchStatementsTest",
    "PrepareMessageTest",
    "SerDeserTest",
    "Python/Go/Node/Rust",
    "V3/V4/V5/V6",
    "force_new_prepared_statement_behaviour",
    "prepared_statements_cache_size",
) + SCENARIO_IDS


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def iter_test_java_files() -> tuple[Path, ...]:
    roots = (
        REPO_ROOT / "test/unit",
        REPO_ROOT / "test/distributed",
        REPO_ROOT / "test/long",
    )
    files = []
    for root in roots:
        if root.exists():
            files.extend(root.rglob("*.java"))
    return tuple(files)


def non_java_driver_hits() -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {name: [] for name in NON_JAVA_DRIVER_PATTERNS}
    for path in iter_test_java_files():
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(REPO_ROOT))
        for name, pattern in NON_JAVA_DRIVER_PATTERNS.items():
            if pattern.search(text):
                hits[name].append(rel)
    return {name: paths for name, paths in hits.items() if paths}


def source_checks() -> tuple[list[Check], dict[str, object]]:
    checks: list[Check] = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(Check(f"source token contract {path}", path, all(token in text for token in tokens)))

    for path in JAVA_DRIVER_PREPARED_ANCHORS:
        text = read(path)
        has_driver_prepare = "com.datastax.driver.core.PreparedStatement" in text and (
            "session.prepare(" in text or ".prepare(" in text
        )
        checks.append(Check(f"Java driver prepared anchor {path}", path, has_driver_prepare))

    negotiation_text = read(PROTOCOL_NEGOTIATION_TEST)
    negotiation_has_no_prepared = (
        "PreparedStatement" not in negotiation_text
        and "session.prepare(" not in negotiation_text
        and ".prepare(" not in negotiation_text
    )
    checks.append(Check("protocol negotiation remains non-prepared boundary",
                        PROTOCOL_NEGOTIATION_TEST,
                        negotiation_has_no_prepared))

    hits = non_java_driver_hits()
    checks.append(Check("non-Java prepared driver matrix remains absent",
                        "test/unit test/distributed test/long",
                        not hits))

    metadata = {
        "java_driver_prepared_anchors": list(JAVA_DRIVER_PREPARED_ANCHORS),
        "non_java_driver_hits": hits,
        "scenario_ids": list(SCENARIO_IDS),
    }
    return checks, metadata


def doc_checks() -> list[Check]:
    docs_text = []
    checks: list[Check] = []
    for path in TARGET_DOCS:
        full_path = REPO_ROOT / path
        exists = full_path.exists()
        checks.append(Check(f"doc exists {path}", path, exists))
        if exists:
            docs_text.append(full_path.read_text(encoding="utf-8"))

    combined = "\n".join(docs_text)
    for token in DOC_REQUIRED_TOKENS:
        checks.append(Check(f"doc token {token}", "research docs", token in combined))

    return checks


def run_checks() -> tuple[list[Check], dict[str, object]]:
    checks, metadata = source_checks()
    checks.extend(doc_checks())
    return checks, metadata


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="emit machine-readable check results")
    args = parser.parse_args(argv)

    checks, metadata = run_checks()
    failed = [check for check in checks if not check.ok]

    if args.json:
        print(json.dumps({
            "ok": not failed,
            "metadata": metadata,
            "checks": [check.__dict__ for check in checks],
        }, indent=2, sort_keys=True))
    else:
        for check in checks:
            status = "OK" if check.ok else "FAIL"
            print(f"{status}: {check.name} [{check.source}]")
        if failed:
            print(f"\n{len(failed)} prepared driver integration drift checks failed", file=sys.stderr)
        else:
            print(f"\nAll {len(checks)} prepared driver integration drift checks passed")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
