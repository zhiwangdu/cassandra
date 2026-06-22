#!/usr/bin/env python3
#
# Source-only drift check for counter repair/compaction research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

COUNTER_MUTATION = "src/java/org/apache/cassandra/db/CounterMutation.java"
COUNTER_CONTEXT = "src/java/org/apache/cassandra/db/context/CounterContext.java"
DIGEST = "src/java/org/apache/cassandra/db/Digest.java"
CASSANDRA_VALIDATION_ITERATOR = "src/java/org/apache/cassandra/db/repair/CassandraValidationIterator.java"
COMPACTION_ITERATOR = "src/java/org/apache/cassandra/db/compaction/CompactionIterator.java"
COLUMN_FAMILY_STORE = "src/java/org/apache/cassandra/db/ColumnFamilyStore.java"
ROW_ITERATOR_MERGE_LISTENER = "src/java/org/apache/cassandra/service/reads/repair/RowIteratorMergeListener.java"
CACHE_SERVICE = "src/java/org/apache/cassandra/service/CacheService.java"
STORAGE_SERVICE = "src/java/org/apache/cassandra/service/StorageService.java"
ABSTRACT_COMPACTION_STRATEGY = "src/java/org/apache/cassandra/db/compaction/AbstractCompactionStrategy.java"
CASSANDRA_YAML = "conf/cassandra.yaml"

COUNTER_MUTATION_TEST = "test/unit/org/apache/cassandra/db/CounterMutationTest.java"
COUNTER_CONTEXT_TEST = "test/unit/org/apache/cassandra/db/context/CounterContextTest.java"
DISTRIBUTED_COUNTERS_TEST = "test/distributed/org/apache/cassandra/distributed/test/CountersTest.java"
READ_COMMAND_TEST = "test/unit/org/apache/cassandra/db/ReadCommandTest.java"
COUNTER_CELL_TEST = "test/unit/org/apache/cassandra/db/CounterCellTest.java"

TARGET_DOCS = (
    "research/module-coordination-counter-repair-compaction-matrix.md",
    "research/module-coordination-counter-repair-compaction-drift-checker.md",
    "research/module-coordination-fault-coverage-runbook.md",
    "research/module-coordination-fault-coverage-drift-checker.md",
    "research/module-coordination-lwt-counter-hints-deep-dive.md",
    "research/module-coordination-lwt-counter-hints-internals.md",
    "research/flow-counter-write.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "coordination_counter_delete_tombstone_shadow",
    "coordination_counter_read_before_write_tombstone_filter",
    "coordination_counter_context_merge_self_heal",
    "coordination_counter_local_shard_cleanup",
    "coordination_counter_digest_empty_legacy_context",
    "coordination_counter_repair_validation_tombstone_purge",
    "coordination_counter_read_repair_deletion_boundary",
    "coordination_counter_cache_invalidation_boundary",
    "coordination_counter_repair_compaction_dtest_gap",
    "coordination_existing_counter_tests_baseline",
)

SOURCE_TOKEN_CHECKS = {
    COUNTER_MUTATION: (
        "public Supplier<Mutation> hintOnFailure()",
        "return null;",
        "public Mutation applyCounterMutation() throws WriteTimeoutException",
        "grabCounterLocks(keyspace, locks);",
        "changes.collectCounterMarks();",
        "updateWithCurrentValuesFromCFS(marks, cfs);",
        "SinglePartitionReadCommand.create(cfs.metadata(), nowInSec, key(), builder.build(), filter);",
        "UnfilteredRowIterators.filter(cmd.queryMemtableAndDisk(cfs, controller), nowInSec)",
        "updateWithCurrentValue(mark, CounterContext.instance().getLocalClockAndCount(cell.buffer()), cfs);",
        "markIter.remove();",
        "public long getTimeout(TimeUnit unit)",
        "DatabaseDescriptor.getCounterWriteRpcTimeout(unit);",
    ),
    COUNTER_CONTEXT: (
        "private Relationship compare(ContextState leftState, ContextState rightState)",
        "invalid global counter shard detected",
        "CompactionManager.isCompactor(Thread.currentThread())",
        "invalid remote counter shard detected",
        "public <V> long total(V context, ValueAccessor<V> accessor)",
        "public <V> boolean shouldClearLocal(V context, ValueAccessor<V> accessor)",
        "public <V>  boolean hasLegacyShards(V context, ValueAccessor<V> accessor)",
        "public ByteBuffer markLocalToBeCleared(ByteBuffer context)",
        "public <V> V clearAllLocal(V context, ValueAccessor<V> accessor)",
    ),
    DIGEST: (
        "public static Digest forRepairedDataTracking()",
        "public <V> Digest updateWithCounterContext(V context, ValueAccessor<V> accessor)",
        "if (accessor.isEmpty(context))",
        "CounterContext.instance().hasLegacyShards(context, accessor)",
        "Note that this skips the header entirely",
        "int pos = CounterContext.headerLength(context, accessor);",
        "accessor.digest(context, pos, len, this);",
    ),
    CASSANDRA_VALIDATION_ITERATOR: (
        "private static class ValidationCompactionController extends CompactionController",
        "public LongPredicate getPurgeEvaluator(DecoratedKey key)",
        "return time -> true;",
        "public static long getDefaultGcBefore(ColumnFamilyStore cfs, long nowInSec)",
        "private static class ValidationCompactionIterator extends CompactionIterator",
        "super(OperationType.VALIDATION, scanners, controller, nowInSec",
    ),
    COMPACTION_ITERATOR: (
        "private static class GarbageSkippingUnfilteredRowIterator",
        "Rows.removeShadowedCells(dataRow, tombRow, activeDeletionTime)",
        "cellLevelGC = controller.tombstoneOption == TombstoneOption.CELL;",
        "controller.shadowSources(partition.partitionKey(), !cellLevelGC)",
        "return new GarbageSkippingUnfilteredRowIterator(partition, UnfilteredRowIterators.merge(iters), cellLevelGC);",
    ),
    COLUMN_FAMILY_STORE: (
        "if (metadata().isCounter())",
        "CacheService.instance.invalidateCounterCacheForCf(metadata());",
        "public int invalidateCounterCache(Collection<Bounds<Token>> boundsToInvalidate)",
        "CacheService.instance.counterCache.remove(key);",
        "public ClockAndCount getCachedCounter(ByteBuffer partitionKey, Clustering<?> clustering, ColumnMetadata column, CellPath path)",
        "public void putCachedCounter(ByteBuffer partitionKey, Clustering<?> clustering, ColumnMetadata column, CellPath path, ClockAndCount clockAndCount)",
        "public boolean isCounterCacheEnabled()",
    ),
    ROW_ITERATOR_MERGE_LISTENER: (
        "public void onMergedPartitionLevelDeletion(DeletionTime mergedDeletion, DeletionTime[] versions)",
        "applyToPartition(i, p -> p.addPartitionDeletion(mergedDeletion));",
        "public void onMergedRows(Row merged, Row[] versions)",
        "Rows.diff(diffListener, merged, versions);",
        "public void onMergedRangeTombstoneMarkers(RangeTombstoneMarker merged, RangeTombstoneMarker[] versions)",
    ),
    CACHE_SERVICE: (
        "COUNTER_CACHE(\"CounterCache\")",
        "public final AutoSavingCache<CounterCacheKey, ClockAndCount> counterCache;",
        "private AutoSavingCache<CounterCacheKey, ClockAndCount> initCounterCache()",
        "public void invalidateCounterCache()",
        "public static class CounterCacheSerializer extends CacheSerializer<CounterCacheKey, ClockAndCount>",
    ),
    STORAGE_SERVICE: (
        "public int garbageCollect(String tombstoneOptionString, int jobs, String keyspaceName, String... tableNames)",
        "TombstoneOption tombstoneOption = TombstoneOption.valueOf(tombstoneOptionString);",
        "cfs.garbageCollect(tombstoneOption, jobs);",
    ),
    ABSTRACT_COMPACTION_STRATEGY: (
        "protected static final String TOMBSTONE_THRESHOLD_OPTION = \"tombstone_threshold\";",
        "protected static final String TOMBSTONE_COMPACTION_INTERVAL_OPTION = \"tombstone_compaction_interval\";",
        "public static final String ONLY_PURGE_REPAIRED_TOMBSTONES = \"only_purge_repaired_tombstones\";",
        "protected boolean worthDroppingTombstones(SSTableReader sstable, long gcBefore)",
    ),
    CASSANDRA_YAML: (
        "counter_cache_size:",
        "counter_cache_save_period:",
        "counter_cache_keys_to_save:",
        "concurrent_counter_writes:",
        "counter_write_request_timeout:",
    ),
    COUNTER_MUTATION_TEST: (
        "public void testDeletes() throws WriteTimeoutException",
        ".delete(cOne)",
        ".add(\"val2\", -5L)",
        "assertEquals(null, row.getCell(cOne));",
        "RowUpdateBuilder.deleteRow(cfs.metadata(), 6, \"key1\", \"cc\").applyUnsafe();",
        "Util.assertEmpty(Util.cmd(cfs).includeRow(\"cc\").columns(\"val\", \"val2\").build());",
    ),
    COUNTER_CONTEXT_TEST: (
        "public void testClearLocal()",
        "cc.markLocalToBeCleared(state.context)",
        "cc.clearAllLocal(marked, ByteBufferAccessor.instance)",
        "assertTrue(cc.shouldClearLocal(marked, ByteBufferAccessor.instance));",
        "assertEquals(2, cleared.getShort(cleared.position()));",
    ),
    DISTRIBUTED_COUNTERS_TEST: (
        "public void testEmptyContext() throws IOException",
        "\"repaired_data_tracking_for_partition_reads_enabled\", true",
        "\"repaired_data_tracking_for_range_reads_enabled\", true",
        "mutateRepairMetadata(descriptor, System.currentTimeMillis(), null, false);",
        "select a,d from %s.t where a = 'a1'",
    ),
    READ_COMMAND_TEST: (
        "public void dontIncludeLegacyCounterContextInDigest()",
        ".addLegacyCounterCell(\"c\", 0L)",
        ".addLegacyCounterCell(\"c\", 1L)",
        "public void purgeGCableTombstonesBeforeCalculatingDigest()",
        "controller.getRepairedDataDigest();",
        "assertDigestsDiffer(digestsWithTombstones.get(key), digestWithoutTombstones);",
    ),
    COUNTER_CELL_TEST: (
        "public void testReconcile()",
        "public void testUpdateDigest() throws Exception",
        "CounterContext.instance().clearAllLocal",
    ),
}

DOC_REQUIRED_TOKENS = (
    "research/tools/check-coordination-counter-repair-compaction-drift.py",
    "research/module-coordination-counter-repair-compaction-matrix.md",
    "research/module-coordination-counter-repair-compaction-drift-checker.md",
    "CounterMutation",
    "CounterContext",
    "Digest.forRepairedDataTracking",
    "CassandraValidationIterator",
    "CompactionIterator",
    "ColumnFamilyStore",
    "RowIteratorMergeListener",
    "CounterMutationTest.testDeletes",
    "CounterContextTest.testClearLocal",
    "CountersTest.testEmptyContext",
    "ReadCommandTest",
    "counter_write_request_timeout",
    "concurrent_counter_writes",
    "counter_cache_size",
    "gc_grace_seconds",
    "tombstone_threshold",
    "counter tombstone + repair/compaction",
    "distributed",
    "gap",
) + tuple(SOURCE_TOKEN_CHECKS.keys()) + SCENARIO_IDS


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def java_files(root: str) -> tuple[Path, ...]:
    return tuple((REPO_ROOT / root).rglob("*.java"))


def relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def has_counter_table_schema(text: str) -> bool:
    return bool(re.search(r"CREATE\s+TABLE[\s\S]{0,400}\bcounter\b", text, re.IGNORECASE))


def files_matching(roots: tuple[str, ...], predicate) -> list[str]:
    hits: list[str] = []
    for root in roots:
        for path in java_files(root):
            text = path.read_text(encoding="utf-8")
            if predicate(text, relative(path)):
                hits.append(relative(path))
    return hits


def source_checks() -> list[Check]:
    checks: list[Check] = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(Check(f"source token contract {path}", path, all(token in text for token in tokens)))

    counter_repair_compaction_hits = files_matching(
        ("test/distributed",),
        lambda text, _path: (
            has_counter_table_schema(text)
            and ("nodetoolResult(\"repair\"" in text or ".nodetool(\"repair\"" in text or "nodetool(\"repair\"" in text)
            and ("nodetoolResult(\"compact\"" in text or ".nodetool(\"compact\"" in text or "disableautocompaction" in text or ".compact(" in text)
            and ("DELETE" in text.upper() or "tombstone" in text.lower())
        ),
    )
    checks.append(Check(
        "gap still open: no distributed counter delete repair compaction assertion",
        "test/distributed",
        not counter_repair_compaction_hits,
    ))

    counter_read_repair_delete_hits = files_matching(
        ("test/distributed",),
        lambda text, _path: (
            has_counter_table_schema(text)
            and ("read repair" in text.lower() or "ReadRepair" in text or "read_repair" in text.lower())
            and ("DELETE" in text.upper() or "tombstone" in text.lower())
        ),
    )
    checks.append(Check(
        "gap still open: no counter-specific read repair deletion distributed test",
        "test/distributed",
        not counter_read_repair_delete_hits,
    ))

    return checks


def doc_checks() -> list[Check]:
    docs = {path: read(path) for path in TARGET_DOCS}
    combined = "\n".join(docs.values())
    checks = [Check(f"target doc exists {path}", path, bool(text.strip())) for path, text in docs.items()]
    checks.extend(Check(f"doc token {token}", "research", token in combined) for token in DOC_REQUIRED_TOKENS)

    matrix = docs["research/module-coordination-counter-repair-compaction-matrix.md"]
    drift_doc = docs["research/module-coordination-counter-repair-compaction-drift-checker.md"]
    for scenario in SCENARIO_IDS:
        checks.append(Check(f"scenario coverage {scenario}", "research", scenario in matrix and scenario in drift_doc))

    return checks


def run_checks() -> list[Check]:
    return source_checks() + doc_checks()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check counter repair/compaction research drift.")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args()

    checks = run_checks()
    failures = [check for check in checks if not check.ok]

    if args.json:
        print(json.dumps(
            {
                "ok": not failures,
                "checks": [check.__dict__ for check in checks],
                "failures": [check.__dict__ for check in failures],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ))
    elif failures:
        print("Counter repair/compaction drift check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure.name} [{failure.source}]", file=sys.stderr)
    else:
        print(f"OK counter repair/compaction drift check: {len(checks)} checks")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
