# Nodetool Routing And Locator Matrix

This matrix covers the nodetool commands that locate token ownership or local SSTable placement for a key: `getendpoints`, `getsstables` and `describering`. These commands sit between topology observability and storage-engine inspection. They are read-only, but their output is often used during incident response, repair planning and single-key data placement debugging.

## Source Contract

| Scenario | Contract | Source anchors | Operational meaning |
| --- | --- | --- | --- |
| `nodetool_routing_command_registry_contract` | `NodeTool.execute()` registers `DescribeRing`, `GetEndpoints` and `GetSSTables` in the top-level nodetool command set. | `src/java/org/apache/cassandra/tools/NodeTool.java:98`、`src/java/org/apache/cassandra/tools/NodeTool.java:113`、`src/java/org/apache/cassandra/tools/NodeTool.java:150`、`src/java/org/apache/cassandra/tools/NodeTool.java:156` | These are regular nodetool commands and inherit global JMX options such as `--host`, `--port`, credentials and `--print-port`. |
| `nodetool_getendpoints_surface_contract` | `getendpoints` requires exactly `<keyspace> <table> <key>` and prints either legacy host addresses or with-port endpoint strings depending on global `--print-port`. | `src/java/org/apache/cassandra/tools/nodetool/GetEndpoints.java:31`、`src/java/org/apache/cassandra/tools/nodetool/GetEndpoints.java:34`、`src/java/org/apache/cassandra/tools/nodetool/GetEndpoints.java:40`、`src/java/org/apache/cassandra/tools/nodetool/GetEndpoints.java:45` | Without `--print-port`, same-IP multi-instance clusters can lose identity; with `--print-port`, output follows the StorageService with-port JMX contract. |
| `nodetool_getendpoints_mbean_route_contract` | `NodeProbe.getEndpointsWithPort()` calls `StorageServiceMBean.getNaturalEndpointsWithPort(keyspace, cf, key)`; legacy `getEndpoints()` calls deprecated `getNaturalEndpoints(keyspace, cf, key)`. | `src/java/org/apache/cassandra/tools/NodeProbe.java:1109`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1114`、`src/java/org/apache/cassandra/service/StorageServiceMBean.java:257`、`src/java/org/apache/cassandra/service/StorageServiceMBean.java:258` | The command reports natural replicas for the partition key, not live replicas, pending replicas, or coordinator selection. |
| `nodetool_getendpoints_partition_key_contract` | `StorageService.getNaturalReplicasForToken(keyspace, cf, key)` converts the CLI key through table metadata partition key type, hashes it with the partitioner and asks the keyspace replication strategy for natural replicas. Unknown keyspace/table throws `IllegalArgumentException`. | `src/java/org/apache/cassandra/service/StorageService.java:5174`、`src/java/org/apache/cassandra/service/StorageService.java:5179`、`src/java/org/apache/cassandra/service/StorageService.java:5190`、`src/java/org/apache/cassandra/service/StorageService.java:5192`、`src/java/org/apache/cassandra/service/StorageService.java:5200` | Composite/typed partition keys must use the table type's string representation; output reflects schema and replication strategy, not SSTable contents. |
| `nodetool_describering_surface_contract` | `describering` requires a keyspace, prints `Schema Version:` and `TokenRange:`, then calls `NodeProbe.describeRing(keyspace, printPort)` and indents each token range string. | `src/java/org/apache/cassandra/tools/nodetool/DescribeRing.java:30`、`src/java/org/apache/cassandra/tools/nodetool/DescribeRing.java:33`、`src/java/org/apache/cassandra/tools/nodetool/DescribeRing.java:40`、`src/java/org/apache/cassandra/tools/nodetool/DescribeRing.java:44` | The command gives a JMX-compatible ring range dump for one keyspace, not the live status table shown by `status` or token-row table shown by `ring`. |
| `nodetool_describering_storage_contract` | `NodeProbe.describeRing()` chooses `describeRingWithPortJMX()` when `--print-port` is set, otherwise deprecated `describeRingJMX()`. `StorageService.describeRing()` rejects missing keyspaces and `LocalStrategy`, builds ranges from range-to-endpoint maps and converts each `TokenRange` to a string. | `src/java/org/apache/cassandra/tools/NodeProbe.java:1687`、`src/java/org/apache/cassandra/service/StorageServiceMBean.java:188`、`src/java/org/apache/cassandra/service/StorageServiceMBean.java:189`、`src/java/org/apache/cassandra/service/StorageService.java:2596`、`src/java/org/apache/cassandra/service/StorageService.java:2601`、`src/java/org/apache/cassandra/service/StorageService.java:2613`、`src/java/org/apache/cassandra/service/StorageService.java:2654` | `describering` is replication-aware by keyspace and can fail before printing ranges if keyspace metadata is absent or local-only. |
| `nodetool_describering_tokenrange_format_contract` | `TokenRange` preserves backward-compatible `toString()` shape: `start_token`, `end_token`, `endpoints`, `rpc_endpoints` and `endpoint_details`; `EndpointDetails` includes host plus optional datacenter/rack and respects with-port formatting. | `src/java/org/apache/cassandra/service/TokenRange.java:29`、`src/java/org/apache/cassandra/service/TokenRange.java:57`、`src/java/org/apache/cassandra/service/TokenRange.java:75`、`src/java/org/apache/cassandra/service/TokenRange.java:92`、`src/java/org/apache/cassandra/service/TokenRange.java:123`、`src/java/org/apache/cassandra/service/TokenRange.java:128` | Scripts parsing `describering` depend on this historical string format; changing it is a compatibility break even if Java types remain intact. |
| `nodetool_getsstables_surface_contract` | `getsstables` requires `<keyspace> <cfname> <key>` and supports `-hf/--hex-format` plus `-l/--show-levels`. Level output is only used when the table reports leveled compaction. | `src/java/org/apache/cassandra/tools/nodetool/GetSSTables.java:33`、`src/java/org/apache/cassandra/tools/nodetool/GetSSTables.java:36`、`src/java/org/apache/cassandra/tools/nodetool/GetSSTables.java:41`、`src/java/org/apache/cassandra/tools/nodetool/GetSSTables.java:50`、`src/java/org/apache/cassandra/tools/nodetool/GetSSTables.java:55` | The command is local to the contacted node; it does not ask every natural replica for its SSTable ownership. |
| `nodetool_getsstables_cfs_contract` | `NodeProbe` resolves the table `ColumnFamilyStoreMBean` and calls `getSSTablesForKey()` or `getSSTablesForKeyWithLevel()`. The CFS implementation scans only live SSTables, converts the key from hex or partition-key string type, decorates it, then checks `SSTableReader.getPosition(..., Operator.EQ, false)`. | `src/java/org/apache/cassandra/tools/NodeProbe.java:1119`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1125`、`src/java/org/apache/cassandra/tools/NodeProbe.java:1131`、`src/java/org/apache/cassandra/db/ColumnFamilyStoreMBean.java:157`、`src/java/org/apache/cassandra/db/ColumnFamilyStoreMBean.java:174`、`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:2008`、`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:2038`、`src/java/org/apache/cassandra/db/ColumnFamilyStore.java:2048` | Results can be empty if the key is not in live SSTables, is only in memtable, has been compacted away, or is queried on the wrong replica. |
| `nodetool_routing_existing_test_baseline` | Current direct coverage includes `BooleanTest` invoking `nodetoolResult("getsstables", ...)`, `SchemaCQLHelperTest` protecting boolean composite partition key parsing for `getSSTablesForKey()`, and `GossipSettlesTest` asserting with-port natural endpoint compatibility. | `test/distributed/org/apache/cassandra/distributed/test/BooleanTest.java:31`、`test/distributed/org/apache/cassandra/distributed/test/BooleanTest.java:38`、`test/unit/org/apache/cassandra/db/SchemaCQLHelperTest.java:597`、`test/unit/org/apache/cassandra/db/SchemaCQLHelperTest.java:609`、`test/distributed/org/apache/cassandra/distributed/test/GossipSettlesTest.java:81`、`test/distributed/org/apache/cassandra/distributed/test/GossipSettlesTest.java:85` | There is still no focused distributed output assertion for `getendpoints --print-port`, `describering --print-port`, or `getsstables --show-levels`. |

## Call Graph

```text
nodetool getendpoints [--print-port] <ks> <table> <key>
  -> GetEndpoints.execute(NodeProbe)
  -> NodeProbe.getEndpointsWithPort() or getEndpoints()
  -> StorageServiceMBean.getNaturalEndpointsWithPort() or getNaturalEndpoints()
  -> StorageService.getNaturalReplicasForToken(ks, table, key)
  -> Schema.instance.getKeyspaceMetadata(ks).getTableOrViewNullable(table)
  -> TableMetadata.partitionKeyType.fromString(key)
  -> tokenMetadata.partitioner.getToken(key)
  -> Keyspace.open(ks).getReplicationStrategy().getNaturalReplicasForToken(token)

nodetool describering [--print-port] <ks>
  -> DescribeRing.execute(NodeProbe)
  -> NodeProbe.getSchemaVersion()
  -> NodeProbe.describeRing(ks, printPort)
  -> StorageServiceMBean.describeRingWithPortJMX() or describeRingJMX()
  -> StorageService.describeRing(ks, includeOnlyLocalDC=false, withPort)
  -> getRangeToAddressMap(ks)
  -> TokenRange.create(..., endpoints, withPort).toString(withPort)

nodetool getsstables [-hf] [-l] <ks> <cf> <key>
  -> GetSSTables.execute(NodeProbe)
  -> NodeProbe.isLeveledCompaction(ks, cf) when --show-levels is set
  -> ColumnFamilyStoreMBean.getSSTablesForKeyWithLevel(key, hexFormat)
     or ColumnFamilyStoreMBean.getSSTablesForKey(key, hexFormat)
  -> ColumnFamilyStore.withSSTablesForKey(key, hexFormat, mapper)
  -> metadata().partitionKeyType.fromString(key) or ByteBufferUtil.hexToBytes(key)
  -> select(View.select(SSTableSet.LIVE, decoratedKey))
  -> SSTableReader.getPosition(decoratedKey, EQ, false)
```

## Output And Failure Semantics

| Command | Output source | Key interpretation | Main failure modes |
| --- | --- | --- | --- |
| `getendpoints` | Natural replica endpoints from `StorageService` | `TableMetadata.partitionKeyType.fromString(key)` | Unknown keyspace/table, malformed partition key string, stale schema, replication strategy changes. |
| `describering` | `TokenRange.toString(withPort)` for keyspace ranges | No partition key input | Missing keyspace, `LocalStrategy`, parser breakage in downstream scripts if string format changes. |
| `getsstables` | Local `ColumnFamilyStore` live SSTable scan | Hex bytes with `-hf`, otherwise partition key type string | Key only in memtable, compaction race, wrong node, malformed key string, non-LCS table with `--show-levels` falling back to plain output. |

## Tests And Gaps

- `BooleanTest.booleanTest()` calls `nodetoolResult("getsstables", KEYSPACE, "tbl", "1:true")` after writing composite boolean partition keys.
- `SchemaCQLHelperTest.testBooleanCompositeKey()` calls `ColumnFamilyStore.getSSTablesForKey("false:true")` and guards against serializer position corruption.
- `GossipSettlesTest` asserts that `getNaturalEndpointsWithPort()` matches legacy natural endpoints plus storage port for both table/key and ByteBuffer overloads.
- Remaining gap: add focused distributed nodetool output tests for `getendpoints --print-port`, `describering --print-port`, `getsstables --hex-format` and `getsstables --show-levels` on an LCS table.
