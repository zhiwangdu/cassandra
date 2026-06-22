#!/usr/bin/env python3
#
# Source-only drift check for repair + materialized view consistency research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

TARGET_DOCS = (
    "research/module-repair-materialized-view-consistency-matrix.md",
    "research/module-repair-materialized-view-consistency-drift-checker.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "repair_mv_receiver_write_path_gate",
    "repair_mv_stream_operation_gate",
    "repair_mv_config_toggle_contract",
    "repair_mv_replay_mutation_contract",
    "repair_mv_cleanup_flush_abort_contract",
    "repair_mv_keyspace_apply_view_contract",
    "repair_mv_existing_row_read_contract",
    "repair_mv_update_action_contract",
    "repair_mv_view_replica_write_contract",
    "repair_mv_batchlog_pending_boundary",
    "repair_mv_metrics_observability_contract",
    "repair_mv_auto_repair_gate_contract",
    "repair_mv_existing_tests_baseline",
    "repair_mv_distributed_correctness_gap",
)

SOURCE_TOKEN_CHECKS = {
    "src/java/org/apache/cassandra/db/streaming/CassandraStreamReceiver.java": (
        "private boolean hasViews(ColumnFamilyStore cfs)",
        "View.findAll(cfs.metadata.keyspace, cfs.getTableName())",
        "boolean requiresWritePath(ColumnFamilyStore cfs)",
        "session.streamOperation().requiresViewBuild() && hasViews(cfs) && DatabaseDescriptor.isMaterializedViewsOnRepairEnabled()",
        "private void sendThroughWritePath(ColumnFamilyStore cfs, Collection<SSTableReader> readers)",
        "ColumnFilter filter = ColumnFilter.all(cfs.metadata());",
        "ThrottledUnfilteredIterator.throttle(scanner, MAX_ROWS_PER_BATCH)",
        "PartitionUpdate.fromIterator(throttledPartitions.next(), filter)",
        "ks.apply(new Mutation(",
        "cfs.forceBlockingFlush(ColumnFamilyStore.FlushReason.STREAMS_RECEIVED);",
        "abort();",
    ),
    "src/java/org/apache/cassandra/streaming/StreamOperation.java": (
        "BULK_LOAD(\"Bulk Load\", true, false)",
        "REPAIR(\"Repair\", true, false);",
        "private final boolean requiresViewBuild;",
        "public boolean requiresViewBuild()",
    ),
    "src/java/org/apache/cassandra/config/Config.java": (
        "public boolean materialized_views_enabled = false;",
        "public volatile boolean materialized_views_on_repair_enabled = true;",
        "materialized views data in SSTable go through commit logs during internodes streaming, e.g. repair",
    ),
    "src/java/org/apache/cassandra/config/DatabaseDescriptor.java": (
        "public static boolean isMaterializedViewsOnRepairEnabled()",
        "return conf.materialized_views_on_repair_enabled;",
        "public static void setMaterializedViewsOnRepairEnabled(boolean val)",
        "conf.materialized_views_on_repair_enabled = val;",
    ),
    "src/java/org/apache/cassandra/db/Keyspace.java": (
        "WriteTimeoutException(WriteType.VIEW, ConsistencyLevel.LOCAL_ONE, 0, 1)",
        "columnFamilyStores.get(tableId).metric.viewLockAcquireTime.update(acquireTime, MILLISECONDS);",
        "try (WriteContext ctx = getWriteHandler().beginWrite(mutation, makeDurable))",
        "AtomicLong baseComplete = new AtomicLong(Long.MAX_VALUE);",
        "viewManager.forTable(upd.metadata().id).pushViewReplicaUpdates(upd, makeDurable, baseComplete);",
        "cfs.getWriteHandler().write(upd, ctx, updateIndexes);",
        "baseComplete.set(currentTimeMillis());",
    ),
    "src/java/org/apache/cassandra/db/view/ViewManager.java": (
        "private static final Striped<Lock> LOCKS = Striped.lazyWeakLock(DatabaseDescriptor.getConcurrentViewWriters() * 1024);",
        "public boolean updatesAffectView(Collection<? extends IMutation> mutations, boolean coordinatorBatchlog)",
        "if (!forTable(update.metadata().id).updatedViews(update).isEmpty())",
        "public TableViews forTable(TableId id)",
        "public static Lock acquireLockFor(int keyAndCfidHash)",
    ),
    "src/java/org/apache/cassandra/db/view/TableViews.java": (
        "public void pushViewReplicaUpdates(PartitionUpdate update, boolean writeCommitLog, AtomicLong baseComplete)",
        "Collection<View> views = updatedViews(update);",
        "SinglePartitionReadCommand command = readExistingRowsCommand(update, views, nowInSec);",
        "generateViewUpdates(views, updates, existings, nowInSec, false)",
        "metric.viewReadTime.update(nanoTime() - start, TimeUnit.NANOSECONDS);",
        "StorageProxy.mutateMV(update.partitionKey().getKey(), mutations, writeCommitLog, baseComplete, requestTime);",
        "public Collection<View> updatedViews(PartitionUpdate updates)",
        "private SinglePartitionReadCommand readExistingRowsCommand(PartitionUpdate updates, Collection<View> views, long nowInSec)",
        "if (!affectsAnyViews(key, row, views))",
        "ColumnFilter.all(metadata)",
        "generator.addBaseTableUpdate(existingBaseRow, mergedBaseRow);",
    ),
    "src/java/org/apache/cassandra/db/view/ViewUpdateGenerator.java": (
        "NEW_ENTRY",
        "DELETE_OLD",
        "UPDATE_EXISTING",
        "SWITCH_ENTRY",
        "public void addBaseTableUpdate(Row existingBaseRow, Row mergedBaseRow)",
        "case SWITCH_ENTRY:",
        "deleteOldEntry(existingBaseRow, mergedBaseRow);",
        "private UpdateAction updateAction(Row existingBaseRow, Row mergedBaseRow)",
        "view.baseNonPKColumnsInViewPK",
        "private void updateEntry(Row existingBaseRow, Row mergedBaseRow)",
        "private void deleteOldEntryInternal(Row existingBaseRow, Row mergedBaseRow)",
        "computeLivenessInfoForEntry",
    ),
    "src/java/org/apache/cassandra/service/StorageProxy.java": (
        "public static void mutateMV(ByteBuffer dataKey, Collection<Mutation> mutations, boolean writeCommitLog, AtomicLong baseComplete, Dispatcher.RequestTime requestTime)",
        "final TimeUUID batchUUID = nextTimeUUID();",
        "StorageService.instance.isStarting() || StorageService.instance.isJoining() || StorageService.instance.isMoving()",
        "BatchlogManager.store(Batch.createLocal(batchUUID, FBUtilities.timestampMicros(),",
        "ViewUtils.getViewNaturalEndpoint(replicationStrategy, baseToken, tk)",
        "pendingEndpointsForToken(tk, keyspaceName)",
        "mutation.apply(writeCommitLog);",
        "wrapViewBatchResponseHandler(mutation,",
        "asyncWriteBatchedMutations(wrappers, localDataCenter, Stage.VIEW_MUTATION, requestTime);",
        "viewWriteMetrics.addNano(nanoTime() - startTime);",
        "viewWriteMetrics.viewWriteLatency.update(delay, MILLISECONDS);",
    ),
    "src/java/org/apache/cassandra/db/view/ViewBuilderTask.java": (
        "generateViewUpdates(Collections.singleton(view), data, empty, nowInSec, true)",
        "StorageProxy.mutateMV(key.getKey(), m, true, noBase, Dispatcher.RequestTime.forImmediateExecution())",
    ),
}

TEST_TOKEN_CHECKS = {
    "test/unit/org/apache/cassandra/db/streaming/CassandraStreamReceiverTest.java": (
        "DatabaseDescriptor.setMaterializedViewsOnRepairEnabled(true);",
        "DatabaseDescriptor.setMaterializedViewsEnabled(true);",
        "CREATE MATERIALIZED VIEW IF NOT EXISTS",
        "public void testRequiresWritePathRepair()",
        "public void testRequiresWritePathRepairMVOnly()",
        "when(session.streamOperation()).thenReturn(StreamOperation.REPAIR);",
        "assertTrue(receiver.requiresWritePath(cfs));",
        "DatabaseDescriptor.setMaterializedViewsOnRepairEnabled(false);",
        "assertFalse(receiver.requiresWritePath(cfs));",
    ),
    "test/unit/org/apache/cassandra/cql3/ViewFiltering1Test.java": (
        "CREATE MATERIALIZED VIEW",
        "assertRowsIgnoringOrder(execute(\"SELECT * FROM \" + mv1)",
        "updateView(\"UPDATE %s using timestamp",
        "updateView(\"DELETE b, c FROM %s using timestamp 6 WHERE a=?\", 1);",
        "updateView(\"DELETE FROM %s using timestamp 8 where a=?\", 1);",
        "updateView(\"UPDATE %s using timestamp 9 set b = ?,c = ? where a=?\", 1, 1, 1);",
    ),
    "test/unit/org/apache/cassandra/cql3/ViewFilteringComplexPKTest.java": (
        "CREATE MATERIALIZED VIEW",
        "assertRowsIgnoringOrder(executeView(\"SELECT a, b, c, d FROM %s\")",
        "execute(\"UPDATE %s SET d = ? WHERE a = ? AND b = ? AND c = ?\"",
        "execute(\"DELETE FROM %s WHERE a = ? AND b = ? AND c = ?\"",
        "execute(\"DELETE FROM %s WHERE a = ? AND b = ?\"",
    ),
    "test/unit/org/apache/cassandra/repair/autorepair/AutoRepairParameterizedTest.java": (
        "CREATE MATERIALIZED VIEW %s.%s AS SELECT i, k from %s.%s",
        "DatabaseDescriptor.setMaterializedViewsOnRepairEnabled(false);",
        "getTotalMVTablesConsideredForRepair()",
        "totalMVTablesConsideredForRepair",
        "setMaterializedViewRepairEnabled(repairType, false)",
        "setMaterializedViewRepairEnabled(repairType, true)",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/repair/AutoRepairFlagToggleTest.java": (
        ".set(\"enable_materialized_views\", true)",
        "CREATE MATERIALIZED VIEW test_ks.test_mv",
        "DESCRIBE MATERIALIZED VIEW test_ks.test_mv",
        "SELECT * FROM test_ks.test_mv WHERE pk = 1",
        "Materialized view should still be accessible after scheduler toggles",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/RepairTest.java": (
        "void repair(ICluster<IInvokableInstance> cluster, boolean sequential, String compression) throws Exception",
        "instance.repair(keyspace, options",
        "repair(cluster, true, \"{'class': 'org.apache.cassandra.io.compress.LZ4Compressor'}\");",
        "repair(cluster, false, \"{'enabled': false}\");",
    ),
}

DOC_TOKEN_CHECKS = {
    "research/module-repair-materialized-view-consistency-matrix.md": (
        "CassandraStreamReceiver",
        "Keyspace.apply",
        "TableViews.pushViewReplicaUpdates",
        "ViewUpdateGenerator",
        "StorageProxy.mutateMV",
        "materialized_views_on_repair_enabled",
        "repair_mv_distributed_correctness_gap",
    ),
    "research/module-repair-materialized-view-consistency-drift-checker.md": (
        "check-repair-materialized-view-consistency-drift.py",
        "repair_mv_receiver_write_path_gate",
        "repair_mv_distributed_correctness_gap",
    ),
    "research/README.md": (
        "module-repair-materialized-view-consistency-matrix.md",
        "check-repair-materialized-view-consistency-drift.py",
        "repair_mv_distributed_correctness_gap",
    ),
    "research/notes/source-map.md": (
        "Repair materialized view consistency drift",
        "module-repair-materialized-view-consistency-matrix.md",
        "check-repair-materialized-view-consistency-drift.py",
    ),
}

MV_MARKERS = (
    re.compile(r"CREATE\s+MATERIALIZED\s+VIEW", re.IGNORECASE),
    re.compile(r"DESCRIBE\s+MATERIALIZED\s+VIEW", re.IGNORECASE),
    re.compile(r"materialized_views_on_repair", re.IGNORECASE),
    re.compile(r"Materialized view"),
)

REPAIR_INVOCATION_MARKERS = (
    re.compile(r"nodetoolResult\(\"repair\""),
    re.compile(r"StorageService\.instance\.repair"),
    re.compile(r"\.repair\("),
    re.compile(r"callOnInstance\(repair"),
    re.compile(r"asyncCallsOnInstance\(repair"),
)


@dataclass
class Finding:
    kind: str
    path: str
    detail: str


def read_text(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def check_tokens(kind: str, checks: dict[str, tuple[str, ...]]) -> list[Finding]:
    findings: list[Finding] = []
    for path, tokens in checks.items():
        full_path = REPO_ROOT / path
        if not full_path.exists():
            findings.append(Finding(kind, path, "missing file"))
            continue
        text = full_path.read_text(encoding="utf-8")
        for token in tokens:
            if token not in text:
                findings.append(Finding(kind, path, f"missing token: {token}"))
    return findings


def check_doc_scenarios() -> list[Finding]:
    findings: list[Finding] = []
    for path in TARGET_DOCS:
        full_path = REPO_ROOT / path
        if not full_path.exists():
            findings.append(Finding("doc", path, "missing file"))
            continue
        text = full_path.read_text(encoding="utf-8")
        for scenario_id in SCENARIO_IDS:
            if scenario_id not in text:
                findings.append(Finding("doc", path, f"missing scenario id: {scenario_id}"))
    return findings


def scan_distributed_repair_mv_candidates() -> list[str]:
    candidates: list[str] = []
    for path in sorted((REPO_ROOT / "test/distributed").rglob("*.java")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        has_mv = any(pattern.search(text) for pattern in MV_MARKERS)
        has_repair = any(pattern.search(text) for pattern in REPAIR_INVOCATION_MARKERS)
        if has_mv and has_repair:
            candidates.append(rel)
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="emit machine-readable result")
    args = parser.parse_args()

    source_findings = check_tokens("source", SOURCE_TOKEN_CHECKS)
    test_findings = check_tokens("test", TEST_TOKEN_CHECKS)
    doc_findings = check_tokens("doc", DOC_TOKEN_CHECKS) + check_doc_scenarios()
    gap_candidates = scan_distributed_repair_mv_candidates()

    findings = source_findings + test_findings + doc_findings
    for candidate in gap_candidates:
        findings.append(
            Finding(
                "gap",
                candidate,
                "distributed test now contains both materialized-view and repair invocation markers; update repair_mv_distributed_correctness_gap",
            )
        )

    result = {
        "ok": not findings,
        "source_checks": sum(len(tokens) for tokens in SOURCE_TOKEN_CHECKS.values()),
        "test_checks": sum(len(tokens) for tokens in TEST_TOKEN_CHECKS.values()),
        "doc_checks": sum(len(tokens) for tokens in DOC_TOKEN_CHECKS.values()) + len(TARGET_DOCS) * len(SCENARIO_IDS),
        "gap_candidates": gap_candidates,
        "scenarios": len(SCENARIO_IDS),
        "findings": [finding.__dict__ for finding in findings],
    }

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif findings:
        print("Repair materialized view consistency drift check failed:", file=sys.stderr)
        for finding in findings:
            print(f"- [{finding.kind}] {finding.path}: {finding.detail}", file=sys.stderr)
    else:
        print(
            "OK Repair materialized view consistency drift checks passed "
            f"({result['source_checks']} source checks, "
            f"{result['test_checks']} test checks, "
            f"{len(gap_candidates)} gap candidates, "
            f"{result['doc_checks']} doc checks, "
            f"{result['scenarios']} scenarios)"
        )

    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
