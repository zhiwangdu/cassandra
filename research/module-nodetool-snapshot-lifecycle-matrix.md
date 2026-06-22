# Nodetool Snapshot Lifecycle Matrix

This matrix isolates operator-facing snapshot commands from the broader storage engine and observability research. It covers `snapshot`, `clearsnapshot`, `listsnapshots`, `getsnapshotthrottle`, `setsnapshotthrottle`, the `NodeProbe -> StorageServiceMBean` route, `StorageService` dispatch, `SnapshotManager` TTL cleanup, `system_views.snapshots`, auto snapshots and the remaining CLI coverage gaps.

## Source Contract

| Scenario | Contract | Source anchors | Operational meaning |
| --- | --- | --- | --- |
| `nodetool_snapshot_command_registry_contract` | `NodeTool` registers `snapshot`, `clearsnapshot`, `listsnapshots`, `getsnapshotthrottle` and `setsnapshotthrottle` as top-level commands. | `src/java/org/apache/cassandra/tools/NodeTool.java:112`, `src/java/org/apache/cassandra/tools/NodeTool.java:158`, `src/java/org/apache/cassandra/tools/NodeTool.java:178`, `src/java/org/apache/cassandra/tools/NodeTool.java:220`, `src/java/org/apache/cassandra/tools/NodeTool.java:225` | A missing registry class removes an operator command even if the command implementation still compiles. |
| `nodetool_snapshot_take_command_surface_contract` | `snapshot` accepts keyspace args, `--table`, `--tag`, `--kt-list`, `--skip-flush` and `--ttl`, builds `skipFlush`/`ttl` options and rejects path separators in the tag. | `src/java/org/apache/cassandra/tools/nodetool/Snapshot.java:39`, `src/java/org/apache/cassandra/tools/nodetool/Snapshot.java:42`, `src/java/org/apache/cassandra/tools/nodetool/Snapshot.java:45`, `src/java/org/apache/cassandra/tools/nodetool/Snapshot.java:48`, `src/java/org/apache/cassandra/tools/nodetool/Snapshot.java:51`, `src/java/org/apache/cassandra/tools/nodetool/Snapshot.java:54`, `src/java/org/apache/cassandra/tools/nodetool/Snapshot.java:57`, `src/java/org/apache/cassandra/tools/nodetool/Snapshot.java:70` | `--skip-flush` can omit unflushed memtable data; `--ttl` creates an expiring snapshot tracked by the snapshot manager. |
| `nodetool_snapshot_take_validation_route_contract` | `snapshot -kt` is mutually exclusive with keyspaces/table and routes to `NodeProbe.takeMultipleTableSnapshot()`. Otherwise it routes keyspaces/table to `NodeProbe.takeSnapshot()`. | `src/java/org/apache/cassandra/tools/nodetool/Snapshot.java:82`, `src/java/org/apache/cassandra/tools/nodetool/Snapshot.java:89`, `src/java/org/apache/cassandra/tools/nodetool/Snapshot.java:96`, `src/java/org/apache/cassandra/tools/nodetool/Snapshot.java:111`, `src/java/org/apache/cassandra/tools/NodeProbe.java:902`, `src/java/org/apache/cassandra/tools/NodeProbe.java:927` | Table-scoped snapshots use `keyspace.table` entities in the service layer, while keyspace snapshots pass keyspace names directly. |
| `nodetool_snapshot_clear_command_guard_contract` | `clearsnapshot` requires either `-t` or `--all`; rejects tag plus `--all`, both age filters, and tag plus age filter; validates ISO timestamps and duration strings before calling `NodeProbe.clearSnapshot()`. | `src/java/org/apache/cassandra/tools/nodetool/ClearSnapshot.java:39`, `src/java/org/apache/cassandra/tools/nodetool/ClearSnapshot.java:45`, `src/java/org/apache/cassandra/tools/nodetool/ClearSnapshot.java:48`, `src/java/org/apache/cassandra/tools/nodetool/ClearSnapshot.java:51`, `src/java/org/apache/cassandra/tools/nodetool/ClearSnapshot.java:61`, `src/java/org/apache/cassandra/tools/nodetool/ClearSnapshot.java:67`, `src/java/org/apache/cassandra/tools/nodetool/ClearSnapshot.java:76`, `src/java/org/apache/cassandra/tools/nodetool/ClearSnapshot.java:117`, `src/java/org/apache/cassandra/tools/nodetool/ClearSnapshot.java:123` | Age-based deletion is a bulk filter, not a tag-specific delete; invalid combinations fail before JMX mutation. |
| `nodetool_snapshot_list_command_observability_contract` | `listsnapshots` passes `no_ttl` and `include_ephemeral` options to `getSnapshotDetails()`, hides the ephemeral column unless `-e` is set and prints `Total TrueDiskSpaceUsed`. | `src/java/org/apache/cassandra/tools/nodetool/ListSnapshots.java:35`, `src/java/org/apache/cassandra/tools/nodetool/ListSnapshots.java:38`, `src/java/org/apache/cassandra/tools/nodetool/ListSnapshots.java:43`, `src/java/org/apache/cassandra/tools/nodetool/ListSnapshots.java:56`, `src/java/org/apache/cassandra/tools/nodetool/ListSnapshots.java:60`, `src/java/org/apache/cassandra/tools/nodetool/ListSnapshots.java:67`, `src/java/org/apache/cassandra/tools/nodetool/ListSnapshots.java:72`, `src/java/org/apache/cassandra/tools/nodetool/ListSnapshots.java:91` | Listing snapshots can touch filesystem metadata and true-size computation; `-nt` and `-e` are display filters, not deletion controls. |
| `nodetool_snapshot_throttle_command_contract` | `getsnapshotthrottle` and `setsnapshotthrottle` read/write `snapshot_links_per_second` through `NodeProbe`; `0` disables throttling at the command surface. | `src/java/org/apache/cassandra/tools/nodetool/GetSnapshotThrottle.java:24`, `src/java/org/apache/cassandra/tools/nodetool/GetSnapshotThrottle.java:30`, `src/java/org/apache/cassandra/tools/nodetool/SetSnapshotThrottle.java:25`, `src/java/org/apache/cassandra/tools/nodetool/SetSnapshotThrottle.java:28`, `src/java/org/apache/cassandra/tools/nodetool/SetSnapshotThrottle.java:34`, `src/java/org/apache/cassandra/tools/NodeProbe.java:884`, `src/java/org/apache/cassandra/tools/NodeProbe.java:889` | The throttle is node-local runtime state. It affects hardlink creation and deletion rate for snapshot operations. |
| `snapshot_nodeprobe_mbean_route_contract` | `NodeProbe` routes snapshot create/clear/list/true-size/throttle calls to `StorageServiceMBean`; table snapshots require exactly one keyspace and are converted to `keyspace.table`. | `src/java/org/apache/cassandra/tools/NodeProbe.java:902`, `src/java/org/apache/cassandra/tools/NodeProbe.java:911`, `src/java/org/apache/cassandra/tools/NodeProbe.java:932`, `src/java/org/apache/cassandra/tools/NodeProbe.java:964`, `src/java/org/apache/cassandra/tools/NodeProbe.java:969`, `src/java/org/apache/cassandra/tools/NodeProbe.java:981`, `src/java/org/apache/cassandra/service/StorageServiceMBean.java:291`, `src/java/org/apache/cassandra/service/StorageServiceMBean.java:312` | JMX auth, MBean compatibility and service-side validation sit between nodetool and storage engine snapshot mutation. |
| `snapshot_storage_ttl_dispatch_contract` | `StorageService.takeSnapshot()` parses `ttl`, enforces `SNAPSHOT_MIN_ALLOWED_TTL_SECONDS`, parses `skipFlush`, then dispatches to keyspace or multi-table snapshot based on `keyspace.table` entities. | `src/java/org/apache/cassandra/service/StorageService.java:4334`, `src/java/org/apache/cassandra/service/StorageService.java:4336`, `src/java/org/apache/cassandra/service/StorageService.java:4339`, `src/java/org/apache/cassandra/service/StorageService.java:4344`, `src/java/org/apache/cassandra/service/StorageService.java:4345`, `src/java/org/apache/cassandra/service/StorageService.java:4351` | TTL validation is service-side, so direct JMX calls keep the same minimum TTL semantics as nodetool. |
| `snapshot_storage_keyspace_table_atomicity_contract` | Keyspace snapshots reject JOINING mode, empty tags and duplicate snapshot names; multi-table snapshots validate every `keyspace.table` before taking any snapshot and use one creation time across tables. | `src/java/org/apache/cassandra/service/StorageService.java:4457`, `src/java/org/apache/cassandra/service/StorageService.java:4459`, `src/java/org/apache/cassandra/service/StorageService.java:4461`, `src/java/org/apache/cassandra/service/StorageService.java:4477`, `src/java/org/apache/cassandra/service/StorageService.java:4503`, `src/java/org/apache/cassandra/service/StorageService.java:4537`, `src/java/org/apache/cassandra/service/StorageService.java:4549`, `src/java/org/apache/cassandra/service/StorageService.java:4555` | Multi-table snapshots are validated as a unit to avoid partial operator-visible snapshot sets. |
| `snapshot_cfs_manifest_hardlink_contract` | `Keyspace.snapshot()` fans out to `ColumnFamilyStore.snapshot()`. CFS flushes or snapshots dirty memtables unless `skipMemtable` is true, creates hard links with the snapshot rate limiter, writes manifest/schema files and registers the `TableSnapshot` with `StorageService`. | `src/java/org/apache/cassandra/db/Keyspace.java:251`, `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:2137`, `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:2156`, `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:2157`, `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:2213`, `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:2226`, `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:2230`, `src/java/org/apache/cassandra/db/ColumnFamilyStore.java:2375` | Snapshot correctness depends on hard links plus manifest metadata; `skip-flush` changes what in-memory state is included. |
| `snapshot_clear_filter_ephemeral_contract` | `StorageService.clearSnapshot()` scans data directories, parses `older_than` or `older_than_timestamp`, filters loaded snapshots through `TableSnapshot.shouldClearSnapshot()` and refuses to remove ephemeral snapshots. | `src/java/org/apache/cassandra/service/StorageService.java:4583`, `src/java/org/apache/cassandra/service/StorageService.java:4591`, `src/java/org/apache/cassandra/service/StorageService.java:4603`, `src/java/org/apache/cassandra/service/StorageService.java:4617`, `src/java/org/apache/cassandra/service/StorageService.java:4627`, `src/java/org/apache/cassandra/service/StorageService.java:4643`, `src/java/org/apache/cassandra/service/snapshot/TableSnapshot.java:334`, `src/java/org/apache/cassandra/service/snapshot/TableSnapshot.java:340` | User-driven cleanup cannot remove repair/session ephemeral snapshots; those are startup-cleaned by CFS. |
| `snapshot_manager_ttl_cleanup_contract` | `SnapshotManager` loads snapshots from all data directories, indexes only expiring snapshots in a priority queue, schedules fixed-delay cleanup and deletes expired snapshot directories with the snapshot rate limiter. | `src/java/org/apache/cassandra/service/snapshot/SnapshotManager.java:50`, `src/java/org/apache/cassandra/service/snapshot/SnapshotManager.java:65`, `src/java/org/apache/cassandra/service/snapshot/SnapshotManager.java:86`, `src/java/org/apache/cassandra/service/snapshot/SnapshotManager.java:102`, `src/java/org/apache/cassandra/service/snapshot/SnapshotManager.java:131`, `src/java/org/apache/cassandra/service/snapshot/SnapshotManager.java:143`, `src/java/org/apache/cassandra/service/snapshot/SnapshotManager.java:159`, `src/java/org/apache/cassandra/service/snapshot/SnapshotLoader.java:60` | TTL cleanup is background, local and filesystem based; it is not a cluster-coordinated delete. |
| `snapshot_listing_virtual_table_contract` | `SnapshotDetailsTabularData` and `system_views.snapshots` expose tag, keyspace/table, true size, size on disk, creation, expiration and ephemeral state from `TableSnapshot`. | `src/java/org/apache/cassandra/db/SnapshotDetailsTabularData.java:28`, `src/java/org/apache/cassandra/db/SnapshotDetailsTabularData.java:73`, `src/java/org/apache/cassandra/db/virtual/SnapshotsTable.java:45`, `src/java/org/apache/cassandra/db/virtual/SnapshotsTable.java:65`, `src/java/org/apache/cassandra/db/virtual/SnapshotsTable.java:70`, `src/java/org/apache/cassandra/db/virtual/SnapshotsTable.java:74`, `test/unit/org/apache/cassandra/db/virtual/SnapshotsTableTest.java:67` | Both nodetool and virtual tables derive from the same snapshot metadata but shape output differently. |
| `snapshot_config_autosnapshot_contract` | `Config` and `cassandra.yaml` define `snapshot_before_compaction`, `auto_snapshot`, `auto_snapshot_ttl` and `snapshot_links_per_second`; `DatabaseDescriptor` validates/parses them and maps `0` throttle to an unbounded rate limiter. | `src/java/org/apache/cassandra/config/Config.java:312`, `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:486`, `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:941`, `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3521`, `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:3526`, `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:509`, `conf/cassandra.yaml:1137` | Drop/truncate auto snapshots and runtime snapshot throttle are configuration-backed but still node-local in effect. |
| `snapshot_existing_test_baseline` | Current tests cover nodetool option parsing for `snapshot --skip-flush`/`--ttl`/`--table`/`--kt-list`, `clearsnapshot --older-than`/`--older-than-timestamp` and incompatible flags, distributed TTL/list/clear flows, dropped-table snapshots, exotic names, equal creation timestamps, auto snapshot TTL, ephemeral cleanup/unclearability, snapshot manager cleanup, snapshot loader/table metadata and `system_views.snapshots`. | `test/unit/org/apache/cassandra/tools/nodetool/SnapshotTest.java:91`, `test/unit/org/apache/cassandra/tools/nodetool/ClearSnapshotTest.java:114`, `test/distributed/org/apache/cassandra/distributed/test/SnapshotsTest.java:86`, `test/distributed/org/apache/cassandra/distributed/test/SnapshotsTest.java:130`, `test/distributed/org/apache/cassandra/distributed/test/SnapshotsTest.java:143`, `test/distributed/org/apache/cassandra/distributed/test/SnapshotsTest.java:163`, `test/distributed/org/apache/cassandra/distributed/test/EphemeralSnapshotTest.java:95`, `test/distributed/org/apache/cassandra/distributed/test/AutoSnapshotTtlTest.java:66`, `test/unit/org/apache/cassandra/service/snapshot/SnapshotManagerTest.java:79`, `test/unit/org/apache/cassandra/service/snapshot/TableSnapshotTest.java:257`, `test/unit/org/apache/cassandra/db/virtual/SnapshotsTableTest.java:67` | The core lifecycle and most option guards are tested, but throttle command coverage remains source-only. |
| `snapshot_operator_gap` | Remaining focused gaps: no direct nodetool tests for `setsnapshotthrottle` / `getsnapshotthrottle`, and no explicit end-to-end `snapshot --skip-flush` data inclusion/exclusion assertion beyond command option parsing. | `research/tools/check-nodetool-snapshot-lifecycle-drift.py`, `test/unit/org/apache/cassandra/tools/nodetool/SnapshotTest.java`, `test/unit/org/apache/cassandra/tools/nodetool/ClearSnapshotTest.java` | When throttle tests land, update this matrix and remove the negative gap checks. |

## Call Graph

```text
nodetool snapshot [-t tag] [--ttl ttl] [--skip-flush] [ks...] | [-kt ks.tbl,...]
  -> Snapshot.execute(NodeProbe)
  -> validate tag and mutually exclusive keyspace/table list shape
  -> NodeProbe.takeSnapshot(...) or takeMultipleTableSnapshot(...)
  -> StorageServiceMBean.takeSnapshot(tag, options, entities)
  -> StorageService.takeSnapshot(tag, options, entities)
  -> parse ttl and skipFlush
  -> StorageService.takeSnapshot(...) or takeMultipleTableSnapshot(...)
  -> Keyspace.snapshot(...)
  -> ColumnFamilyStore.snapshot(...)
  -> optionally switch/snapshot dirty memtable
  -> ColumnFamilyStore.snapshotWithoutMemtable(...)
  -> SSTableReader.createLinks(snapshotDirectory, rateLimiter)
  -> write manifest/schema
  -> StorageService.addSnapshot(TableSnapshot)
  -> SnapshotManager.addSnapshot(snapshot) when expiring
```

```text
nodetool clearsnapshot -t tag | --all [--older-than duration | --older-than-timestamp instant]
  -> ClearSnapshot.execute(NodeProbe)
  -> validate guard combinations and age syntax
  -> NodeProbe.clearSnapshot(options, tag, keyspaces)
  -> StorageServiceMBean.clearSnapshot(options, tag, keyspaces)
  -> StorageService.clearSnapshot(...)
  -> scan data_file_directories for keyspaces
  -> SnapshotManager.loadSnapshots(keyspace)
  -> TableSnapshot.shouldClearSnapshot(tag, timestamp)
  -> SnapshotManager.clearSnapshot(snapshot)
  -> Directories.removeSnapshotDirectory(rateLimiter, snapshotDir)
```

```text
nodetool listsnapshots [-nt] [-e]
  -> ListSnapshots.execute(NodeProbe)
  -> NodeProbe.getSnapshotDetails(options)
  -> StorageService.getSnapshotDetails(options)
  -> SnapshotManager.loadSnapshots()
  -> filter expiring/ephemeral rows
  -> SnapshotDetailsTabularData.from(TableSnapshot, TabularDataSupport)
  -> print rows and NodeProbe.trueSnapshotsSize()
```

```text
SELECT * FROM system_views.snapshots
  -> SnapshotsTable.data()
  -> StorageService.instance.snapshotManager.loadSnapshots()
  -> TableSnapshot.computeTrueSizeBytes()
  -> TableSnapshot.computeSizeOnDiskBytes()
  -> CQL virtual table rows
```

## Operational Notes

- Snapshot commands mutate or inspect the contacted node only. Cluster-wide snapshot posture needs per-node execution or external orchestration.
- `snapshot --skip-flush` avoids blocking flush and can exclude dirty memtable data from the hard-linked SSTable set.
- TTL snapshots are cleaned by the local `SnapshotCleanup` executor after `expiresAt`; cleanup timing depends on `cassandra.snapshot.ttl_cleanup_*` properties.
- `clearsnapshot --all` does not remove ephemeral snapshots. Ephemeral leftovers are cleared during CFS startup via `ColumnFamilyStore.clearEphemeralSnapshots()`.
- `snapshot_links_per_second` throttles link creation and deletion. `0` is disabled in YAML/CLI terms and becomes an effectively unbounded rate limiter internally.
- `listsnapshots` and `system_views.snapshots` can walk snapshot directories and compute true size; avoid high-frequency polling on nodes with many snapshots or large data directories.

## Tests And Gaps

- `SnapshotTest` covers nodetool `snapshot` option parsing for custom names, invalid names, `--skip-flush`, `--ttl`, `--table` and `--kt-list`.
- `ClearSnapshotTest` in `test/unit/org/apache/cassandra/tools/nodetool` covers `clearsnapshot --older-than`, `--older-than-timestamp` and incompatible flag failures.
- `SnapshotsTest` covers TTL cleanup, restart cleanup, invalid TTL, `listsnapshots -nt`, manual clear by tag, secondary-index table-list cleanup, dropped table snapshots, exotic names and same timestamp output.
- `EphemeralSnapshotTest` covers manifest and legacy-marker ephemeral handling, `listsnapshots -e`, user cleanup refusal and startup cleanup.
- `AutoSnapshotTtlTest` covers `auto_snapshot_ttl` for TRUNCATE/DROP and the disabled-TTL behavior.
- `SnapshotManagerTest`, `SnapshotLoaderTest`, `TableSnapshotTest` and `SnapshotsTableTest` cover service metadata, cleanup queue, loading, filter predicate and virtual table output.
- Remaining gap: direct CLI coverage for snapshot throttle commands and end-to-end `snapshot --skip-flush` data inclusion/exclusion contents.
