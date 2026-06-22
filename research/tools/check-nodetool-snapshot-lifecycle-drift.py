#!/usr/bin/env python3
#
# Source-only drift check for nodetool snapshot lifecycle research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

NODE_TOOL = "src/java/org/apache/cassandra/tools/NodeTool.java"
NODEPROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
SNAPSHOT_CMD = "src/java/org/apache/cassandra/tools/nodetool/Snapshot.java"
CLEAR_SNAPSHOT_CMD = "src/java/org/apache/cassandra/tools/nodetool/ClearSnapshot.java"
LIST_SNAPSHOTS_CMD = "src/java/org/apache/cassandra/tools/nodetool/ListSnapshots.java"
GET_SNAPSHOT_THROTTLE_CMD = "src/java/org/apache/cassandra/tools/nodetool/GetSnapshotThrottle.java"
SET_SNAPSHOT_THROTTLE_CMD = "src/java/org/apache/cassandra/tools/nodetool/SetSnapshotThrottle.java"
STORAGE_SERVICE_MBEAN = "src/java/org/apache/cassandra/service/StorageServiceMBean.java"
STORAGE_SERVICE = "src/java/org/apache/cassandra/service/StorageService.java"
KEYSPACE = "src/java/org/apache/cassandra/db/Keyspace.java"
COLUMN_FAMILY_STORE = "src/java/org/apache/cassandra/db/ColumnFamilyStore.java"
SNAPSHOT_MANAGER = "src/java/org/apache/cassandra/service/snapshot/SnapshotManager.java"
TABLE_SNAPSHOT = "src/java/org/apache/cassandra/service/snapshot/TableSnapshot.java"
SNAPSHOT_LOADER = "src/java/org/apache/cassandra/service/snapshot/SnapshotLoader.java"
SNAPSHOT_DETAILS_TABULAR_DATA = "src/java/org/apache/cassandra/db/SnapshotDetailsTabularData.java"
SNAPSHOTS_TABLE = "src/java/org/apache/cassandra/db/virtual/SnapshotsTable.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
CASSANDRA_RELEVANT_PROPERTIES = "src/java/org/apache/cassandra/config/CassandraRelevantProperties.java"
CASSANDRA_YAML = "conf/cassandra.yaml"

SNAPSHOTS_TEST = "test/distributed/org/apache/cassandra/distributed/test/SnapshotsTest.java"
EPHEMERAL_SNAPSHOT_TEST = "test/distributed/org/apache/cassandra/distributed/test/EphemeralSnapshotTest.java"
AUTO_SNAPSHOT_TTL_TEST = "test/distributed/org/apache/cassandra/distributed/test/AutoSnapshotTtlTest.java"
CLEAR_SNAPSHOT_TEST = "test/distributed/org/apache/cassandra/distributed/test/ClearSnapshotTest.java"
UNIT_SNAPSHOT_TEST = "test/unit/org/apache/cassandra/tools/nodetool/SnapshotTest.java"
UNIT_CLEAR_SNAPSHOT_TEST = "test/unit/org/apache/cassandra/tools/nodetool/ClearSnapshotTest.java"
SNAPSHOT_MANAGER_TEST = "test/unit/org/apache/cassandra/service/snapshot/SnapshotManagerTest.java"
SNAPSHOT_LOADER_TEST = "test/unit/org/apache/cassandra/service/snapshot/SnapshotLoaderTest.java"
TABLE_SNAPSHOT_TEST = "test/unit/org/apache/cassandra/service/snapshot/TableSnapshotTest.java"
SNAPSHOTS_TABLE_TEST = "test/unit/org/apache/cassandra/db/virtual/SnapshotsTableTest.java"

MATRIX_DOC = "research/module-nodetool-snapshot-lifecycle-matrix.md"
CHECKER_DOC = "research/module-nodetool-snapshot-lifecycle-drift-checker.md"
OPERATIONS_DOC = "research/module-operations-observability.md"
OBS_MAPPING_DOC = "research/module-observability-mapping.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

SCENARIO_IDS = (
    "nodetool_snapshot_command_registry_contract",
    "nodetool_snapshot_take_command_surface_contract",
    "nodetool_snapshot_take_validation_route_contract",
    "nodetool_snapshot_clear_command_guard_contract",
    "nodetool_snapshot_list_command_observability_contract",
    "nodetool_snapshot_throttle_command_contract",
    "snapshot_nodeprobe_mbean_route_contract",
    "snapshot_storage_ttl_dispatch_contract",
    "snapshot_storage_keyspace_table_atomicity_contract",
    "snapshot_cfs_manifest_hardlink_contract",
    "snapshot_clear_filter_ephemeral_contract",
    "snapshot_manager_ttl_cleanup_contract",
    "snapshot_listing_virtual_table_contract",
    "snapshot_config_autosnapshot_contract",
    "snapshot_existing_test_baseline",
    "snapshot_operator_gap",
)

SOURCE_TOKEN_CHECKS = {
    NODE_TOOL: (
        "ClearSnapshot.class",
        "GetSnapshotThrottle.class",
        "ListSnapshots.class",
        "SetSnapshotThrottle.class",
        "Snapshot.class",
    ),
    SNAPSHOT_CMD: (
        '@Command(name = "snapshot", description = "Take a snapshot of specified keyspaces or a snapshot of the specified table")',
        '@Arguments(usage = "[<keyspaces...>]", description = "List of keyspaces. By default, all keyspaces")',
        '@Option(title = "table", name = {"-cf", "--column-family", "--table"}',
        '@Option(title = "tag", name = {"-t", "--tag"}, description = "The name of the snapshot")',
        '@Option(title = "ktlist", name = { "-kt", "--kt-list", "-kc", "--kc.list" }',
        '@Option(title = "skip-flush", name = {"-sf", "--skip-flush"}',
        '@Option(title = "ttl", name = {"--ttl"}, description = "Specify a TTL of created snapshot")',
        'options.put("skipFlush", Boolean.toString(skipFlush));',
        "new DurationSpec.LongNanosecondsBound(ttl)",
        'options.put("ttl", d.toString());',
        "Snapshot name cannot contain",
        "When specifying the Keyspace table list (using -kt,--kt-list,-kc,--kc.list), you must not also specify keyspaces to snapshot",
        "probe.takeMultipleTableSnapshot(snapshotName, options, ktList.split(\",\"));",
        "probe.takeSnapshot(snapshotName, table, options, toArray(keyspaces, String.class));",
    ),
    CLEAR_SNAPSHOT_CMD: (
        '@Command(name = "clearsnapshot", description = "Remove the snapshot with the given name from the given keyspaces")',
        '@Option(title = "snapshot_name", name = "-t", description = "Remove the snapshot with a given name")',
        '@Option(title = "clear_all_snapshots", name = "--all", description = "Removes all snapshots")',
        '@Option(title = "older_than", name = "--older-than", description = "Clear snapshots older than specified time period.")',
        '@Option(title = "older_than_timestamp", name = "--older-than-timestamp"',
        'throw new IllegalArgumentException("Specify snapshot name or --all");',
        'throw new IllegalArgumentException("Specify only one of snapshot name or --all");',
        'throw new IllegalArgumentException("Specify only one of --older-than or --older-than-timestamp");',
        'throw new IllegalArgumentException("Specifying snapshot name together with --older-than flag is not allowed");',
        'throw new IllegalArgumentException("Specifying snapshot name together with --older-than-timestamp flag is not allowed");',
        "Instant.parse(olderThanTimestamp);",
        "new DurationSpec.LongSecondsBound(olderThan).toSeconds();",
        'parameters.put("older_than", olderThan);',
        'parameters.put("older_than_timestamp", olderThanTimestamp);',
        "probe.clearSnapshot(parameters, snapshotName, toArray(keyspaces, String.class));",
    ),
    LIST_SNAPSHOTS_CMD: (
        '@Command(name = "listsnapshots", description = "Lists all the snapshots along with the size on disk and true size.',
        'name = { "-nt", "--no-ttl" }',
        'name = { "-e", "--ephemeral" }',
        'options.put("no_ttl", Boolean.toString(noTTL));',
        'options.put("include_ephemeral", Boolean.toString(includeEphemeral));',
        "probe.getSnapshotDetails(options);",
        'out.println("There are no snapshots");',
        "probe.trueSnapshotsSize();",
        "getTabularType().getIndexNames();",
        "indexNames.subList(0, indexNames.size() - 1)",
        'out.println("\\nTotal TrueDiskSpaceUsed: "',
    ),
    GET_SNAPSHOT_THROTTLE_CMD: (
        '@Command(name = "getsnapshotthrottle", description = "Print the snapshot_links_per_second throttle for snapshot/clearsnapshot")',
        "long throttle = probe.getSnapshotLinksPerSecond();",
        'System.out.println("Current snapshot throttle: " + throttle + " links/s");',
        'System.out.println("Snapshot throttle is disabled");',
    ),
    SET_SNAPSHOT_THROTTLE_CMD: (
        '@Command(name = "setsnapshotthrottle", description = "Set the snapshot_links_per_second cap for snapshot and clearsnapshot throttling")',
        '@Arguments(title = "setsnapshotthrottle", usage = "<throttle>", description = "Value represents hardlinks per second ( snapshot_links_per_second ) , 0 to disable throttling", required = true)',
        "private Long snapshotThrottle = null;",
        "probe.setSnapshotLinksPerSecond(snapshotThrottle);",
    ),
    NODEPROBE: (
        "public long getSnapshotLinksPerSecond()",
        "return ssProxy.getSnapshotLinksPerSecond();",
        "public void setSnapshotLinksPerSecond(long throttle)",
        "ssProxy.setSnapshotLinksPerSecond(throttle);",
        "public void takeSnapshot(String snapshotName, String table, Map<String, String> options, String... keyspaces)",
        "When specifying the table for a snapshot, you must specify one and only one keyspace",
        "ssProxy.takeSnapshot(snapshotName, options, keyspaces[0] + \".\" + table);",
        "ssProxy.takeSnapshot(snapshotName, options, keyspaces);",
        "public void takeMultipleTableSnapshot(String snapshotName, Map<String, String> options, String... tableList)",
        "ssProxy.takeSnapshot(snapshotName, options, tableList);",
        "public void clearSnapshot(Map<String, Object> options, String tag, String... keyspaces)",
        "ssProxy.clearSnapshot(options, tag, keyspaces);",
        "public Map<String, TabularData> getSnapshotDetails(Map<String, String> options)",
        "return ssProxy.getSnapshotDetails(options);",
        "public long trueSnapshotsSize()",
        "return ssProxy.trueSnapshotsSize();",
    ),
    STORAGE_SERVICE_MBEAN: (
        "public void takeSnapshot(String tag, Map<String, String> options, String... entities) throws IOException;",
        "public void clearSnapshot(Map<String, Object> options, String tag, String... keyspaceNames) throws IOException;",
        "public Map<String, TabularData> getSnapshotDetails(Map<String, String> options);",
        "public long trueSnapshotsSize();",
        "public void setSnapshotLinksPerSecond(long throttle);",
        "public long getSnapshotLinksPerSecond();",
    ),
    STORAGE_SERVICE: (
        "public final SnapshotManager snapshotManager = new SnapshotManager();",
        "public void startSnapshotManager()",
        "snapshotManager.start();",
        "public void takeSnapshot(String tag, Map<String, String> options, String... entities) throws IOException",
        'options.containsKey("ttl") ? new DurationSpec.IntSecondsBound(options.get("ttl")) : null;',
        "CassandraRelevantProperties.SNAPSHOT_MIN_ALLOWED_TTL_SECONDS.getInt();",
        'throw new IllegalArgumentException(String.format("ttl for snapshot must be at least %d seconds", minAllowedTtlSecs));',
        'Boolean.parseBoolean(options.getOrDefault("skipFlush", "false"));',
        'entities[0].contains(".")',
        "takeMultipleTableSnapshot(tag, skipFlush, ttl, entities);",
        "takeSnapshot(tag, skipFlush, ttl, entities);",
        "if (operationMode == Mode.JOINING)",
        'throw new IOException("You must supply a snapshot name.");',
        "if (keyspace.snapshotExists(tag))",
        "DatabaseDescriptor.getSnapshotRateLimiter();",
        "Instant creationTime = now();",
        "keyspace.snapshot(tag, null, skipFlush, ttl, snapshotRateLimiter, creationTime);",
        "Map<Keyspace, List<String>> keyspaceColumnfamily",
        "String splittedString[] = StringUtils.split(table, '.');",
        "Add Keyspace columnfamily to map in order to support atomicity for snapshot process.",
        "entry.getKey().snapshot(tag, table, skipFlush, ttl, snapshotRateLimiter, creationTime);",
        "public void clearSnapshot(Map<String, Object> options, String tag, String... keyspaceNames)",
        'Object olderThan = options.get("older_than");',
        'Object olderThanTimestamp = options.get("older_than_timestamp");',
        "Instant.parse((String) olderThanTimestamp).toEpochMilli();",
        "clearKeyspaceSnapshot(keyspace, tag, clearOlderThanTimestamp);",
        "TableSnapshot.shouldClearSnapshot(tag, olderThanTimestamp)",
        'Boolean.parseBoolean(options.getOrDefault("no_ttl", "false"));',
        'Boolean.parseBoolean(options.getOrDefault("include_ephemeral", "false"));',
        "SnapshotDetailsTabularData.from(snapshot, data);",
        "public long trueSnapshotsSize()",
        "SchemaConstants.isLocalSystemKeyspace(keyspace.getName())",
        "public void setSnapshotLinksPerSecond(long throttle)",
        "DatabaseDescriptor.setSnapshotLinksPerSecond(throttle);",
        "return DatabaseDescriptor.getSnapshotLinksPerSecond();",
        "snapshotManager.stop();",
    ),
    KEYSPACE: (
        "public void snapshot(String snapshotName, String columnFamilyName, boolean skipFlush, DurationSpec.IntSecondsBound ttl, RateLimiter rateLimiter, Instant creationTime) throws IOException",
        "cfStore.snapshot(snapshotName, skipFlush, ttl, rateLimiter, creationTime);",
        "Failed taking snapshot. Table",
        "public static String getTimestampedSnapshotNameWithPrefix(String clientSuppliedName, String prefix)",
        "public boolean snapshotExists(String snapshotName)",
    ),
    COLUMN_FAMILY_STORE: (
        "public TableSnapshot snapshotWithoutMemtable(String snapshotName, Predicate<SSTableReader> predicate, boolean ephemeral, DurationSpec.IntSecondsBound ttl, RateLimiter rateLimiter, Instant creationTime)",
        "can not take ephemeral snapshot",
        "validateSnapshotName(snapshotName);",
        "DatabaseDescriptor.getSnapshotRateLimiter();",
        "File snapshotDirectory = Directories.getSnapshotDirectory(ssTable.descriptor, snapshotName);",
        "ssTable.createLinks(snapshotDirectory.path(), rateLimiter); // hard links",
        "SnapshotManifest manifest = new SnapshotManifest(mapToDataFilenames(sstables), ttl, creationTime, ephemeral);",
        "writeSnapshotManifest(manifest, manifestFile);",
        "writeSnapshotSchema(schemaFile);",
        "StorageService.instance.addSnapshot(snapshot);",
        "protected static void clearEphemeralSnapshots(Directories directories)",
        ".filter(TableSnapshot::isEphemeral)",
        "Directories.clearSnapshot(ephemeralSnapshot.getTag(), directories.getCFDirectories(), clearSnapshotRateLimiter);",
        "public TableSnapshot snapshot(String snapshotName, Predicate<SSTableReader> predicate, boolean ephemeral, boolean skipMemtable, DurationSpec.IntSecondsBound ttl, RateLimiter rateLimiter, Instant creationTime)",
        "FlushReason.SNAPSHOT",
        "current.performSnapshot(snapshotName);",
        "return snapshotWithoutMemtable(snapshotName, predicate, ephemeral, ttl, rateLimiter, creationTime);",
        "snapshot(Keyspace.getTimestampedSnapshotNameWithPrefix(name, SNAPSHOT_TRUNCATE_PREFIX), DatabaseDescriptor.getAutoSnapshotTtl());",
        "snapshot(Keyspace.getTimestampedSnapshotNameWithPrefix(name, ColumnFamilyStore.SNAPSHOT_DROP_PREFIX), DatabaseDescriptor.getAutoSnapshotTtl());",
    ),
    SNAPSHOT_MANAGER: (
        'executorFactory().scheduled(false, "SnapshotCleanup")',
        "private final PriorityQueue<TableSnapshot> expiringSnapshots",
        "CassandraRelevantProperties.SNAPSHOT_CLEANUP_INITIAL_DELAY_SECONDS.getInt()",
        "snapshotLoader = new SnapshotLoader(DatabaseDescriptor.getAllDataFileLocations());",
        "public synchronized void start()",
        "addSnapshots(loadSnapshots());",
        "resumeSnapshotCleanup();",
        "if (snapshot.isExpiring())",
        "executor.scheduleWithFixedDelay(this::clearExpiredSnapshots, initialDelaySeconds,",
        "if (!expiredSnapshot.isExpired(now()))",
        "clearSnapshot(expiredSnapshot);",
        "Directories.removeSnapshotDirectory(DatabaseDescriptor.getSnapshotRateLimiter(), snapshotDir);",
        "expiringSnapshots.remove(snapshot);",
    ),
    TABLE_SNAPSHOT: (
        "private final String keyspaceName;",
        "private final String tableName;",
        "private final UUID tableId;",
        "private final String tag;",
        "private final boolean ephemeral;",
        "private final Instant createdAt;",
        "private final Instant expiresAt;",
        "public Instant getCreatedAt()",
        "public boolean isExpired(Instant now)",
        "public boolean isEphemeral()",
        "public boolean isExpiring()",
        "public long computeSizeOnDiskBytes()",
        "public long computeTrueSizeBytes()",
        "SnapshotManifest.deserializeFromJsonFile(manifestFile);",
        'new File(snapshotDir, "ephemeral.snapshot").exists()',
        "public static Predicate<TableSnapshot> shouldClearSnapshot(String tag, long olderThanTimestamp)",
        "Ephemeral snapshots are not removable by a user.",
        "return notEphemeral && shouldClearTag && byTimestamp;",
    ),
    SNAPSHOT_LOADER: (
        'SNAPSHOT_DIR_PATTERN = Pattern.compile("(?<keyspace>\\\\w+)/(?<tableName>\\\\w+)"',
        '"/snapshots/(?<tag>.+)$"',
        "static UUID parseUUID(String uuidWithoutDashes)",
        "loadSnapshotFromDir(snapshotDirMatcher, subdir);",
        "String snapshotId = buildSnapshotId(keyspaceName, tableName, tableId, tag);",
        "new TableSnapshot.Builder(keyspaceName, tableName, tableId, tag)",
        "public Set<TableSnapshot> loadSnapshots(String keyspace)",
        "Files.walkFileTree(dataDir, Collections.emptySet(), maxDepth, visitor);",
    ),
    SNAPSHOT_DETAILS_TABULAR_DATA: (
        '"Snapshot name"',
        '"True size"',
        '"Size on disk"',
        '"Creation time"',
        '"Expiration time"',
        '"Ephemeral"',
        "public static void from(TableSnapshot details, TabularDataSupport result)",
        "details.computeSizeOnDiskBytes()",
        "details.computeTrueSizeBytes()",
        "details.getCreatedAt()",
        "details.getExpiresAt()",
        "details.isEphemeral()",
    ),
    SNAPSHOTS_TABLE: (
        'super(TableMetadata.builder(keyspace, "snapshots")',
        '.comment("available snapshots")',
        ".addPartitionKeyColumn(NAME, UTF8Type.instance)",
        ".addClusteringColumn(KEYSPACE_NAME, UTF8Type.instance)",
        ".addRegularColumn(TRUE_SIZE, LongType.instance)",
        ".addRegularColumn(SIZE_ON_DISK, LongType.instance)",
        ".addRegularColumn(CREATED_AT, TimestampType.instance)",
        ".addRegularColumn(EXPIRES_AT, TimestampType.instance)",
        ".addRegularColumn(EPHEMERAL, BooleanType.instance)",
        "for (TableSnapshot tableSnapshot : StorageService.instance.snapshotManager.loadSnapshots())",
        "tableSnapshot.computeTrueSizeBytes()",
        "tableSnapshot.computeSizeOnDiskBytes()",
        "tableSnapshot.isExpiring()",
        "tableSnapshot.isEphemeral()",
    ),
    CONFIG: (
        "public boolean snapshot_before_compaction = false;",
        "public boolean auto_snapshot = true;",
        "public String auto_snapshot_ttl;",
        "public volatile long snapshot_links_per_second = 0;",
    ),
    DATABASE_DESCRIPTOR: (
        "if (conf.auto_snapshot_ttl != null)",
        "autoSnapshoTtl = new DurationSpec.IntSecondsBound(conf.auto_snapshot_ttl);",
        'throw new ConfigurationException("snapshot_links_per_second must be >= 0");',
        "public static boolean isSnapshotBeforeCompaction()",
        "public static DurationSpec.IntSecondsBound getAutoSnapshotTtl()",
        "return conf.snapshot_links_per_second == 0 ? Long.MAX_VALUE : conf.snapshot_links_per_second;",
        "public static void setSnapshotLinksPerSecond(long throttle)",
        'throw new IllegalArgumentException("Invalid throttle for snapshot_links_per_second: must be positive");',
        "return RateLimiter.create(getSnapshotLinksPerSecond());",
    ),
    CASSANDRA_RELEVANT_PROPERTIES: (
        'SNAPSHOT_CLEANUP_INITIAL_DELAY_SECONDS("cassandra.snapshot.ttl_cleanup_initial_delay_seconds", "5")',
        'SNAPSHOT_CLEANUP_PERIOD_SECONDS("cassandra.snapshot.ttl_cleanup_period_seconds", "60")',
        'SNAPSHOT_MIN_ALLOWED_TTL_SECONDS("cassandra.snapshot.min_allowed_ttl_seconds", "60")',
        'SNAPSHOT_NAME_VALIDATION("cassandra.snapshot.validation", "false")',
    ),
    CASSANDRA_YAML: (
        "snapshot_before_compaction: false",
        "auto_snapshot: true",
        "# auto_snapshot_ttl: 30d",
        "snapshot_links_per_second: 0",
        "The act of creating or clearing a snapshot involves creating or removing",
    ),
    SNAPSHOTS_TEST: (
        "public void testSnapshotsCleanupByTTL()",
        "public void testSnapshotCleanupAfterRestart()",
        "public void testSnapshotInvalidArgument()",
        "public void testListingSnapshotsWithoutTTL()",
        "public void testManualSnapshotCleanup()",
        "public void testSecondaryIndexCleanup()",
        "public void testListSnapshotOfDroppedTable()",
        "public void testTTLSnapshotOfDroppedTable()",
        "public void testTTLSnapshotOfDroppedTableAfterRestart()",
        "public void testExoticSnapshotNames()",
        "public void testSameTimestampOnEachTableOfSnaphot()",
        'nodetoolResult("snapshot", "--ttl"',
        'nodetoolResult("clearsnapshot", "-t", "first")',
        'nodetoolResult("listsnapshots", "-nt")',
    ),
    EPHEMERAL_SNAPSHOT_TEST: (
        "public void testStartupRemovesEphemeralSnapshotOnEphemeralFlagInManifest()",
        "public void testStartupRemovesEphemeralSnapshotOnMarkerFile()",
        "public void testEphemeralSnapshotIsNotClearableFromNodetool()",
        "public void testClearingAllSnapshotsFromNodetoolWillKeepEphemeralSnaphotsIntact()",
        'instance.nodetoolResult("listsnapshots", "-e")',
        'instance.nodetoolResult("clearsnapshot", "-t", snapshotName).asserts().success();',
        "Ephemeral snapshots are not removable by a user.",
        "SnapshotManifest manifestWithEphemeralFlag",
    ),
    AUTO_SNAPSHOT_TTL_TEST: (
        "public void testAutoSnapshotTTlOnTruncate()",
        "public void testAutoSnapshotTTlOnDrop()",
        "public void testAutoSnapshotTTlOnDropAfterRestart()",
        "public void testAutoSnapshotTtlDisabled()",
        '.set("auto_snapshot_ttl", String.format("%ds", FIVE_SECONDS))',
        "SNAPSHOT_TRUNCATE_PREFIX",
        "SNAPSHOT_DROP_PREFIX",
    ),
    CLEAR_SNAPSHOT_TEST: (
        "public void clearSnapshotSlowTest()",
        "public void testSeqClearsSnapshot()",
        '.method(named("snapshotExists"))',
        "logs().watchFor(\"Clearing snapshot\")",
    ),
    UNIT_SNAPSHOT_TEST: (
        "public void testSkipFlushOption()",
        "public void testTTLOption()",
        "public void testInvalidTTLOption()",
        "public void testTableOption()",
        "public void testInvalidTableWithMultipleKeyspacesOption()",
        "public void testInvalidTableWithKeyspaceTableListOption()",
        "public void testKeyspaceTableListOption()",
        'invokeNodetool("snapshot", "-t", "skip_flush", "-sf")',
        "options {skipFlush=true}",
    ),
    UNIT_CLEAR_SNAPSHOT_TEST: (
        "public void testClearSnapshotWithOlderThanFlag()",
        "public void testClearSnapshotWithOlderThanTimestampFlag()",
        "public void testIncompatibleFlags()",
        'invokeNodetool("clearsnapshot", "--older-than", "3h", "--all", "--", KEYSPACE)',
        'invokeNodetool("clearsnapshot", "--older-than-timestamp"',
        "Specify only one of --older-than or --older-than-timestamp",
        "Specifying snapshot name together with --older-than-timestamp flag is not allowed",
        "Invalid duration: 3k",
    ),
    SNAPSHOT_MANAGER_TEST: (
        "public void testLoadSnapshots()",
        "public void testClearExpiredSnapshots()",
        "public void testScheduledCleanup()",
        "public void testClearSnapshot()",
        "public void testConcurrentClearingOfSnapshots()",
    ),
    SNAPSHOT_LOADER_TEST: (
        "public class SnapshotLoaderTest",
        "SNAPSHOT_DIR_PATTERN",
        "loader.loadSnapshots()",
        "ephemeral.snapshot",
        "SnapshotManifest manifest",
    ),
    TABLE_SNAPSHOT_TEST: (
        "public void testSnapshotExpiring()",
        "public void testShouldClearSnapshot()",
        "public void testGetLiveFileFromSnapshotFile",
        "assertTrue(notEphemeral);",
        "assertTrue(shouldClearTag);",
        "assertTrue(byTimestamp);",
    ),
    SNAPSHOTS_TABLE_TEST: (
        "public class SnapshotsTableTest extends CQLTester",
        "new SnapshotsTable(KS_NAME)",
        'execute("SELECT name, keyspace_name, table_name, created_at, expires_at, ephemeral FROM vts.snapshots")',
        "assertRowsIgnoringOrder(result,",
        "StorageService.instance.clearSnapshot(Collections.emptyMap(), SNAPSHOT_NO_TTL, KEYSPACE);",
    ),
}

DOC_REQUIRED_TOKENS = (
    MATRIX_DOC,
    CHECKER_DOC,
    "research/tools/check-nodetool-snapshot-lifecycle-drift.py",
    NODE_TOOL,
    NODEPROBE,
    SNAPSHOT_CMD,
    CLEAR_SNAPSHOT_CMD,
    LIST_SNAPSHOTS_CMD,
    GET_SNAPSHOT_THROTTLE_CMD,
    SET_SNAPSHOT_THROTTLE_CMD,
    STORAGE_SERVICE_MBEAN,
    STORAGE_SERVICE,
    KEYSPACE,
    COLUMN_FAMILY_STORE,
    SNAPSHOT_MANAGER,
    TABLE_SNAPSHOT,
    SNAPSHOT_LOADER,
    SNAPSHOT_DETAILS_TABULAR_DATA,
    SNAPSHOTS_TABLE,
    CONFIG,
    DATABASE_DESCRIPTOR,
    CASSANDRA_RELEVANT_PROPERTIES,
    CASSANDRA_YAML,
    SNAPSHOTS_TEST,
    EPHEMERAL_SNAPSHOT_TEST,
    AUTO_SNAPSHOT_TTL_TEST,
    UNIT_SNAPSHOT_TEST,
    UNIT_CLEAR_SNAPSHOT_TEST,
    SNAPSHOT_MANAGER_TEST,
    TABLE_SNAPSHOT_TEST,
    SNAPSHOTS_TABLE_TEST,
    "snapshot_links_per_second",
    "auto_snapshot_ttl",
    "system_views.snapshots",
    "setsnapshotthrottle",
    "getsnapshotthrottle",
) + SCENARIO_IDS


@dataclass(frozen=True)
class CheckResult:
    name: str
    source: str
    ok: bool
    detail: str = ""


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def all_test_java_text() -> str:
    chunks = []
    for path in sorted((REPO_ROOT / "test").rglob("*.java")):
        try:
            chunks.append(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def source_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        for token in tokens:
            checks.append(CheckResult(f"source token {token}", path, token in text))

    test_text = all_test_java_text()
    gap_tokens = ("setsnapshotthrottle", "getsnapshotthrottle")
    for token in gap_tokens:
        checks.append(CheckResult(f"gap still missing direct test token {token}", "test/**/*.java", token not in test_text))

    return checks


def doc_checks() -> list[CheckResult]:
    matrix = read(MATRIX_DOC)
    checker = read(CHECKER_DOC)
    readme = read(README_DOC)
    source_map = read(SOURCE_MAP_DOC)
    operations = read(OPERATIONS_DOC)
    observability = read(OBS_MAPPING_DOC)
    matrix_and_checker = matrix + "\n" + checker
    all_docs = "\n".join((matrix, checker, readme, source_map, operations, observability))

    checks = [CheckResult(f"scenario documented {scenario}", f"{MATRIX_DOC} / {CHECKER_DOC}", documented(scenario, matrix_and_checker)) for scenario in SCENARIO_IDS]
    checks.extend(CheckResult(f"doc token {token}", "research docs", token in all_docs) for token in DOC_REQUIRED_TOKENS)
    checks.extend(
        [
            CheckResult("README references matrix", README_DOC, MATRIX_DOC.split("/", 1)[1] in readme),
            CheckResult("README references checker", README_DOC, CHECKER_DOC.split("/", 1)[1] in readme and "check-nodetool-snapshot-lifecycle-drift.py" in readme),
            CheckResult("source-map references matrix", SOURCE_MAP_DOC, MATRIX_DOC in source_map),
            CheckResult("source-map references checker", SOURCE_MAP_DOC, "research/tools/check-nodetool-snapshot-lifecycle-drift.py" in source_map),
            CheckResult("operations references snapshot lifecycle", OPERATIONS_DOC, "setsnapshotthrottle" in operations and "SnapshotManager" in operations),
            CheckResult("observability references snapshots virtual table", OBS_MAPPING_DOC, "system_views.snapshots" in observability and "SnapshotDetailsTabularData" in observability),
        ]
    )
    return checks


def check() -> tuple[dict[str, object], bool]:
    sources = source_checks()
    docs = doc_checks()
    result = {
        "scenario_ids": list(SCENARIO_IDS),
        "source_checks": [entry.__dict__ for entry in sources],
        "doc_checks": [entry.__dict__ for entry in docs],
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check nodetool snapshot lifecycle source/doc coverage.")
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
        if failed_sources:
            for entry in failed_sources:
                detail = f" ({entry['detail']})" if entry.get("detail") else ""
                print(f"source: {entry['source']}: failed {entry['name']}{detail}")
        if failed_docs:
            for entry in failed_docs:
                print(f"doc: {entry['source']}: missing {entry['name']}")
        if ok:
            print(f"OK nodetool snapshot lifecycle checks passed ({len(result['scenario_ids'])} scenarios)")
        else:
            print("Nodetool snapshot lifecycle checks failed.", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
