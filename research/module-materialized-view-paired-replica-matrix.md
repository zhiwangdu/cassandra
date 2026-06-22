# Module: Materialized View Paired Replica Matrix

This matrix isolates the materialized view paired-replica algorithm from view row generation and view build replay. It explains how a base replica maps a base-token write to exactly one natural view replica, how `StorageProxy.mutateMV()` handles topology movement and pending endpoints, and which tests currently prove only the local algorithm rather than distributed range movement.

## Scenario IDs

| Scenario | Protected behavior |
| --- | --- |
| `mv_pair_viewutils_cardinality_contract` | `ViewUtils.getViewNaturalEndpoint()` pairs base and view replicas by same cardinality after removing shared endpoints. |
| `mv_pair_local_view_replica_preference` | If this node is already a natural view replica, the local view replica is selected immediately. |
| `mv_pair_local_dc_filter_contract` | `NetworkTopologyStrategy` pairing is restricted to the local datacenter. |
| `mv_pair_shared_endpoint_filter_contract` | Endpoints shared by base and view natural replica sets are filtered so they self-select instead of skewing cardinality. |
| `mv_pair_non_base_replica_empty_contract` | A node that is not a base replica for the base token gets `Optional.empty()` and must not directly pick a remote view replica. |
| `mv_pair_starting_batchlog_contract` | A starting/joining/moving node writes all MV mutations to local batchlog because paired replicas may be stale. |
| `mv_pair_pending_endpoint_write_contract` | Pending view endpoints convert local/self fast path into ordinary writes so pending replicas receive view mutations. |
| `mv_pair_local_apply_fastpath_contract` | Self paired endpoint with joined state and no pending endpoints applies the view mutation locally and decrements batchlog cleanup. |
| `mv_pair_remote_stage_contract` | Non-local paired endpoints use `ReplicaLayout.forTokenWrite()` and `Stage.VIEW_MUTATION`. |
| `mv_pair_batchlog_metrics_contract` | Non-local MV mutations are stored in local batchlog until response handlers clean them up; view write metrics track latency and pending replicas. |
| `mv_pair_existing_tests_baseline` | Existing `ViewUtilsTest` covers NTS cardinality, local preference and non-base empty result. |
| `mv_pair_range_movement_distributed_gap` | No distributed test currently combines MV paired replicas with move/decommission/bootstrap/pending range behavior. |

## Design Goals

- Preserve the one-to-one base-replica to view-replica mapping that lets Cassandra avoid writing each MV mutation to all natural view replicas.
- Make the NTS local-DC rule explicit so cross-DC topology changes are not misread as global-ring pairing.
- Explain why pending endpoints and topology transitions deliberately fall back to ordinary writes or local batchlog instead of the local apply fast path.
- Keep the current test boundary clear: `ViewUtilsTest` proves the pure pairing algorithm, while range movement with real MV writes remains a distributed coverage gap.

## Source Matrix

| Scenario | Source anchors | Test / evidence | Operational meaning |
| --- | --- | --- | --- |
| `mv_pair_viewutils_cardinality_contract` | `ViewUtils.getViewNaturalEndpoint()` reads natural base/view replicas, filters shared endpoints, asserts filtered set sizes match and returns the view replica at the same index as the local base replica; see `src/java/org/apache/cassandra/db/view/ViewUtils.java:60-104`. | `ViewUtilsTest.testGetIndexNaturalEndpoint()` sets up NTS RF=1 per DC and asserts the expected paired endpoint; see `test/unit/org/apache/cassandra/db/view/ViewUtilsTest.java:61-89`. | Pairing is cardinality-based, not simply nearest endpoint or coordinator-selected endpoint. |
| `mv_pair_local_view_replica_preference` | Before cardinality filtering, `ViewUtils` returns any natural view replica that is `Replica::isSelf`; see `src/java/org/apache/cassandra/db/view/ViewUtils.java:66-68`. | `ViewUtilsTest.testLocalHostPreference()` uses RF=2 per DC and asserts localhost is preferred; see `test/unit/org/apache/cassandra/db/view/ViewUtilsTest.java:92-120`. | If the local node stores the view row naturally, it should apply locally instead of selecting a different same-cardinality endpoint. |
| `mv_pair_local_dc_filter_contract` | `isLocalDC` keeps all replicas for non-NTS, but under `NetworkTopologyStrategy` only keeps replicas whose snitch DC equals `DatabaseDescriptor.getEndpointSnitch().getLocalDatacenter()`; see `src/java/org/apache/cassandra/db/view/ViewUtils.java:62-73`. | `ViewUtilsTest` installs `PropertyFileSnitch`, populates DC1/DC2 tokens and uses NTS options; see `test/unit/org/apache/cassandra/db/view/ViewUtilsTest.java:51-58` and `test/unit/org/apache/cassandra/db/view/ViewUtilsTest.java:67-80`. | A DC1 base replica does not pair itself against DC2 view replica cardinality. |
| `mv_pair_shared_endpoint_filter_contract` | Base replicas filter out endpoints also present in natural view replicas and view replicas filter out endpoints present in natural base replicas; see `src/java/org/apache/cassandra/db/view/ViewUtils.java:75-82`. | Covered indirectly by `testLocalHostPreference()` where shared endpoints would skew cardinality without local preference/filtering. | Shared ownership is a self-write case; leaving shared endpoints in both lists would shift indexes and misroute non-shared pairs. |
| `mv_pair_non_base_replica_empty_contract` | If no filtered base replica is self, `ViewUtils` returns `Optional.empty()`; see `src/java/org/apache/cassandra/db/view/ViewUtils.java:89-101`. | `ViewUtilsTest.testBaseTokenDoesNotBelongToLocalReplicaShouldReturnEmpty()` asserts empty result; see `test/unit/org/apache/cassandra/db/view/ViewUtilsTest.java:122-149`. | A node that receives an MV mutation but is not a base owner should not invent a paired remote endpoint from stale metadata. |
| `mv_pair_starting_batchlog_contract` | `StorageProxy.mutateMV()` stores all MV mutations in local batchlog while the node is starting, joining or moving; see `src/java/org/apache/cassandra/service/StorageProxy.java:1021-1028`. | Source-only contract; no focused distributed test currently combines MV writes with node move/join states. | During topology transitions, local ring metadata can be stale, so local batchlog is the conservative durability fallback. |
| `mv_pair_pending_endpoint_write_contract` | `mutateMV()` reads `pendingEndpointsForToken()` for the view token; self paired endpoints only local-apply when pending replicas are empty, otherwise it builds an ordinary write layout with pending replicas; see `src/java/org/apache/cassandra/service/StorageProxy.java:1049-1089`. | `TokenMetadata.pendingEndpointsForToken()` is covered by `PendingRangeMapsTest`, but not in MV write context; see `src/java/org/apache/cassandra/locator/TokenMetadata.java:1320-1327` and `test/unit/org/apache/cassandra/locator/PendingRangeMapsTest.java:67-107`. | Pending view owners must receive view mutations during bootstrap/move/decommission windows. |
| `mv_pair_local_apply_fastpath_contract` | If paired endpoint is self, the node is joined and there are no pending endpoints, `mutation.apply(writeCommitLog)` runs locally, removes the mutation from `nonLocalMutations` and decrements cleanup; see `src/java/org/apache/cassandra/service/StorageProxy.java:1064-1076`. | `ViewComplexDeletionsTest.testNoBatchlogCleanupForLocalMutations()` protects the local cleanup behavior; see `test/unit/org/apache/cassandra/cql3/ViewComplexDeletionsTest.java:255`. | Local MV rows should not wait on remote write handlers or batchlog cleanup when the local node is the complete target. |
| `mv_pair_remote_stage_contract` | Remote/pending path builds `ReplicaLayout.forTokenWrite(...)`, wraps a view batch response handler and later calls `asyncWriteBatchedMutations(..., Stage.VIEW_MUTATION, ...)`; see `src/java/org/apache/cassandra/service/StorageProxy.java:1084-1106`. `Stage.VIEW_MUTATION` is configured as `ViewMutationStage`; see `src/java/org/apache/cassandra/concurrent/Stage.java:48`. | `CQLTester.waitForViewMutations()` waits for `Stage.VIEW_MUTATION` pending and active task counts to reach zero; see `test/unit/org/apache/cassandra/cql3/CQLTester.java:1164-1165`. | Remote view writes have their own executor and can backlog independently from base mutation stages. |
| `mv_pair_batchlog_metrics_contract` | Non-local mutations are stored in a local batchlog before remote writes, cleanup removes the batchlog after responses, and `viewWriteMetrics` records total view write time and base-complete latency; see `src/java/org/apache/cassandra/service/StorageProxy.java:1038-1041`, `src/java/org/apache/cassandra/service/StorageProxy.java:1100-1112` and `src/java/org/apache/cassandra/service/StorageProxy.java:1425-1441`. | `ViewWriteMetrics` defines `ViewReplicasAttempted`, `ViewReplicasSuccess`, `ViewWriteLatency` and `ViewPendingMutations`; see `src/java/org/apache/cassandra/metrics/ViewWriteMetrics.java:27-57`. | MV correctness can depend on batchlog replay after a base write returns; metrics reveal pending/success imbalance. |
| `mv_pair_existing_tests_baseline` | Unit tests cover pure pairing and local cleanup; distributed tests cover MV schema/accessibility but not topology movement with paired replica assertions. | `ViewUtilsTest`, `ViewComplexDeletionsTest`, `AutoRepairFlagToggleTest` and `AllowAutoSnapshotTest` are the current nearest tests. | Existing coverage is useful but narrow; it should not be presented as proof of distributed pending-range correctness. |
| `mv_pair_range_movement_distributed_gap` | Current `test/distributed` has MV tests and topology/repair tests, but no single distributed test combines MV writes with move/decommission/bootstrap or explicit pending view endpoints. | `research/tools/check-materialized-view-paired-replica-drift.py` negative scan fails if such a test appears. | The highest-risk production corner case remains pending range or stale metadata while MV writes are in flight. |

## Lifecycle

```text
Base replica generates one or more view mutations
  -> StorageProxy.mutateMV(dataKey, viewMutations, writeCommitLog, baseComplete, requestTime)
     -> if node starting/joining/moving:
          BatchlogManager.store(local batchlog for all view mutations)
          return
     -> baseToken = token(dataKey)
     -> for each view mutation:
          viewToken = mutation.key().getToken()
          replicationStrategy = Keyspace.open(viewKeyspace).getReplicationStrategy()
          pairedEndpoint = ViewUtils.getViewNaturalEndpoint(replicationStrategy, baseToken, viewToken)
          pendingReplicas = TokenMetadata.pendingEndpointsForToken(viewToken, viewKeyspace)
          if pairedEndpoint empty:
             keep mutation in local batchlog for later replay
          else if pairedEndpoint is self and node joined and no pending replicas:
             mutation.apply(writeCommitLog)
             cleanup.decrement()
          else:
             ReplicaLayout.forTokenWrite(natural=pairedEndpoint, pending=pendingReplicas)
             wrapViewBatchResponseHandler(...)
     -> store remaining nonLocalMutations in local batchlog
     -> asyncWriteBatchedMutations(..., Stage.VIEW_MUTATION, ...)
```

## Configuration, Metrics And Logs

| Area | Evidence | Operational note |
| --- | --- | --- |
| View write executor | `Stage.VIEW_MUTATION` uses `DatabaseDescriptor.getConcurrentViewWriters()` / `setConcurrentViewWriters()`; see `src/java/org/apache/cassandra/concurrent/Stage.java:48` and `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:2442-2448`. | Increasing view writers affects remote MV write throughput, not paired endpoint selection. |
| View write metrics | `ViewWriteMetrics` exposes attempted/success/pending/latency metrics; see `src/java/org/apache/cassandra/metrics/ViewWriteMetrics.java:27-57`. | `ViewPendingMutations` staying non-zero points at remote view write or batchlog cleanup lag. |
| Batchlog fallback | `mutateMV()` stores all mutations while starting/joining/moving and stores remaining non-local mutations before remote writes; see `src/java/org/apache/cassandra/service/StorageProxy.java:1021-1028` and `src/java/org/apache/cassandra/service/StorageProxy.java:1100-1106`. | Local batchlog is intentional for topology uncertainty; it is not automatically evidence of failed MV writes. |
| Range movement warning | When no paired endpoint exists and no pending endpoints are known, `mutateMV()` logs a range movement warning and leaves the mutation in local batchlog; see `src/java/org/apache/cassandra/service/StorageProxy.java:1052-1061`. | Repeated warnings suggest stale metadata or a topology operation racing MV writes. |

## Current Gaps

- `mv_pair_range_movement_distributed_gap`: add a 2+ node distributed test that creates a base table and MV, starts move/decommission/bootstrap or creates pending ranges, writes data that routes to remote view replicas, and asserts the view converges after local batchlog replay.
- Add a focused test for pending endpoint behavior where paired endpoint is self but pending replicas are non-empty, proving ordinary write fanout to pending owners.
- Existing `ViewUtilsTest` uses NTS and local snitch setup, but does not exercise SimpleStrategy/non-NTS pairing explicitly.

## Verification

- `python3 research/tools/check-materialized-view-paired-replica-drift.py`
- `python3 research/tools/run-research-drift-checks.py --pattern materialized-view`
- Adjacent checks:
  - `python3 research/tools/check-materialized-view-build-status-drift.py`
  - `python3 research/tools/check-repair-materialized-view-consistency-drift.py`
  - `python3 research/tools/check-storageproxy-coordinator-drift.py`
