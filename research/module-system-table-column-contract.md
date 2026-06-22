# Module: System Table Column Contract

## 范围

本模块把源码中的 system table `CREATE TABLE` 定义导出为逐表列契约，覆盖 `SystemKeyspace`、`SchemaKeyspace`、`TraceKeyspace`、`AuthKeyspace` 和 `SystemDistributedKeyspace` 中由 `parse(..., "CREATE TABLE %s ...")` 构建的 `TableMetadata`。它补上表名 registry drift checker 没有覆盖的列名、主键和 deprecated system column 标记。

`system_schema.tables` 和 `system_schema.views` 的 `auto_repair` 列由 `AUTOREPAIR_ENABLE` 条件控制；本 contract 记录源码最大 ABI，以便 feature-flag 列变化时触发 drift。

## 设计目标

- 让 `research` 中有一份可被脚本校验的 system table column ABI，后续新增/删除列时能立即暴露 drift。
- 用源码 CQL 字符串作为事实来源，而不是从运行中 schema dump 或手工复制表结构。
- 同时记录 legacy 表，例如 `system.peers`、`system.size_estimates` 和 `system.sstable_activity`，因为它们仍在 metadata/pre-flight 集合或升级兼容路径中出现。
- 对 `system.local` 的 `recordDeprecatedSystemColumn("thrift_version", ...)` 单独记录 deprecated column marker，避免把它误当成当前 CQL 列。
- 对 `SchemaKeyspace` 中的 optional `auto_repair` CQL fragment 采用 true 分支，确保文档覆盖启用 auto-repair 时出现的 schema ABI。

## 核心接口

- `SystemKeyspace.parse()`：解析 `system` local keyspace 表 CQL，并追加 local table 参数，见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:527-533`。
- `SchemaKeyspace.parse()`：解析 `system_schema` local keyspace 的 keyspaces/tables/columns/views/indexes/types/functions/aggregates 等表，见 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:90-293`。
- `TraceKeyspace.parse()`：解析 `system_traces.sessions/events`，见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:101-107`。
- `AuthKeyspace.parse()`：解析 `system_auth` replicated auth tables，见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:146-152`。
- `SystemDistributedKeyspace.parse()`：解析 `system_distributed` replicated state tables，见 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:206-210`。
- `research/tools/check-system-table-column-drift.py`：直接解析上述源码、生成 scenario id，并校验本文件每个 section 的列、主键和 deprecated column 标记。

## Source Contracts

### `system.batches` (`system_table_column_system_batches`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `id`, `mutations`, `version`
- Primary key: `PRIMARY KEY ((id))`
- Deprecated columns: none

### `system.paxos` (`system_table_column_system_paxos`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `row_key`, `cf_id`, `in_progress_ballot`, `in_progress_read_ballot`, `most_recent_commit`, `most_recent_commit_at`, `most_recent_commit_version`, `proposal`, `proposal_ballot`, `proposal_version`
- Primary key: `PRIMARY KEY ((row_key), cf_id)`
- Deprecated columns: none

### `system.IndexInfo` (`system_table_column_system_indexinfo`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `table_name`, `index_name`, `value`
- Primary key: `PRIMARY KEY ((table_name), index_name)`
- Deprecated columns: none

### `system.paxos_repair_history` (`system_table_column_system_paxos_repair_history`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `keyspace_name`, `table_name`, `points`
- Primary key: `PRIMARY KEY (keyspace_name, table_name)`
- Deprecated columns: none

### `system.local` (`system_table_column_system_local`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `key`, `bootstrapped`, `broadcast_address`, `broadcast_port`, `cluster_name`, `cql_version`, `data_center`, `gossip_generation`, `host_id`, `listen_address`, `listen_port`, `native_protocol_version`, `partitioner`, `rack`, `release_version`, `rpc_address`, `rpc_port`, `schema_version`, `tokens`, `truncated_at`
- Primary key: `PRIMARY KEY ((key))`
- Deprecated columns: `thrift_version`

### `system.peers_v2` (`system_table_column_system_peers_v2`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `peer`, `peer_port`, `data_center`, `host_id`, `preferred_ip`, `preferred_port`, `rack`, `release_version`, `native_address`, `native_port`, `schema_version`, `tokens`
- Primary key: `PRIMARY KEY ((peer), peer_port)`
- Deprecated columns: none

### `system.peer_events_v2` (`system_table_column_system_peer_events_v2`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `peer`, `peer_port`, `hints_dropped`
- Primary key: `PRIMARY KEY ((peer), peer_port)`
- Deprecated columns: none

### `system.compaction_history` (`system_table_column_system_compaction_history`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `id`, `bytes_in`, `bytes_out`, `columnfamily_name`, `compacted_at`, `keyspace_name`, `rows_merged`, `compaction_properties`
- Primary key: `PRIMARY KEY ((id))`
- Deprecated columns: none

### `system.sstable_activity` (`system_table_column_system_sstable_activity`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `keyspace_name`, `columnfamily_name`, `generation`, `rate_120m`, `rate_15m`
- Primary key: `PRIMARY KEY ((keyspace_name, columnfamily_name, generation))`
- Deprecated columns: none

### `system.sstable_activity_v2` (`system_table_column_system_sstable_activity_v2`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `keyspace_name`, `table_name`, `id`, `rate_120m`, `rate_15m`
- Primary key: `PRIMARY KEY ((keyspace_name, table_name, id))`
- Deprecated columns: none

### `system.size_estimates` (`system_table_column_system_size_estimates`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `keyspace_name`, `table_name`, `range_start`, `range_end`, `mean_partition_size`, `partitions_count`
- Primary key: `PRIMARY KEY ((keyspace_name), table_name, range_start, range_end)`
- Deprecated columns: none

### `system.table_estimates` (`system_table_column_system_table_estimates`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `keyspace_name`, `table_name`, `range_type`, `range_start`, `range_end`, `mean_partition_size`, `partitions_count`
- Primary key: `PRIMARY KEY ((keyspace_name), table_name, range_type, range_start, range_end)`
- Deprecated columns: none

### `system.available_ranges_v2` (`system_table_column_system_available_ranges_v2`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `keyspace_name`, `full_ranges`, `transient_ranges`
- Primary key: `PRIMARY KEY ((keyspace_name))`
- Deprecated columns: none

### `system.transferred_ranges_v2` (`system_table_column_system_transferred_ranges_v2`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `operation`, `peer`, `peer_port`, `keyspace_name`, `ranges`
- Primary key: `PRIMARY KEY ((operation, keyspace_name), peer, peer_port)`
- Deprecated columns: none

### `system.view_builds_in_progress` (`system_table_column_system_view_builds_in_progress`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `keyspace_name`, `view_name`, `start_token`, `end_token`, `last_token`, `keys_built`
- Primary key: `PRIMARY KEY ((keyspace_name), view_name, start_token, end_token)`
- Deprecated columns: none

### `system.built_views` (`system_table_column_system_built_views`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `keyspace_name`, `view_name`, `status_replicated`
- Primary key: `PRIMARY KEY ((keyspace_name), view_name)`
- Deprecated columns: none

### `system.top_partitions` (`system_table_column_system_top_partitions`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `keyspace_name`, `table_name`, `top_type`, `top`, `last_update`
- Primary key: `PRIMARY KEY (keyspace_name, table_name, top_type)`
- Deprecated columns: none

### `system.prepared_statements` (`system_table_column_system_prepared_statements`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `prepared_id`, `logged_keyspace`, `query_string`
- Primary key: `PRIMARY KEY ((prepared_id))`
- Deprecated columns: none

### `system.repairs` (`system_table_column_system_repairs`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `parent_id`, `started_at`, `last_update`, `repaired_at`, `state`, `coordinator`, `coordinator_port`, `participants`, `participants_wp`, `ranges`, `cfids`
- Primary key: `PRIMARY KEY (parent_id)`
- Deprecated columns: none

### `system.peers` (`system_table_column_system_peers`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `peer`, `data_center`, `host_id`, `preferred_ip`, `rack`, `release_version`, `rpc_address`, `schema_version`, `tokens`
- Primary key: `PRIMARY KEY ((peer))`
- Deprecated columns: none

### `system.peer_events` (`system_table_column_system_peer_events`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `peer`, `hints_dropped`
- Primary key: `PRIMARY KEY ((peer))`
- Deprecated columns: none

### `system.transferred_ranges` (`system_table_column_system_transferred_ranges`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `operation`, `peer`, `keyspace_name`, `ranges`
- Primary key: `PRIMARY KEY ((operation, keyspace_name), peer)`
- Deprecated columns: none

### `system.available_ranges` (`system_table_column_system_available_ranges`)
- Source: `src/java/org/apache/cassandra/db/SystemKeyspace.java`
- Columns: `keyspace_name`, `ranges`
- Primary key: `PRIMARY KEY ((keyspace_name))`
- Deprecated columns: none

### `system_schema.keyspaces` (`system_table_column_system_schema_keyspaces`)
- Source: `src/java/org/apache/cassandra/schema/SchemaKeyspace.java`
- Columns: `keyspace_name`, `durable_writes`, `replication`
- Primary key: `PRIMARY KEY ((keyspace_name))`
- Deprecated columns: none

### `system_schema.tables` (`system_table_column_system_schema_tables`)
- Source: `src/java/org/apache/cassandra/schema/SchemaKeyspace.java`
- Columns: `keyspace_name`, `table_name`, `allow_auto_snapshot`, `bloom_filter_fp_chance`, `caching`, `comment`, `compaction`, `compression`, `memtable`, `crc_check_chance`, `dclocal_read_repair_chance`, `default_time_to_live`, `extensions`, `flags`, `gc_grace_seconds`, `incremental_backups`, `id`, `max_index_interval`, `memtable_flush_period_in_ms`, `min_index_interval`, `read_repair_chance`, `speculative_retry`, `additional_write_policy`, `cdc`, `read_repair`, `auto_repair`
- Primary key: `PRIMARY KEY ((keyspace_name), table_name)`
- Deprecated columns: none

### `system_schema.columns` (`system_table_column_system_schema_columns`)
- Source: `src/java/org/apache/cassandra/schema/SchemaKeyspace.java`
- Columns: `keyspace_name`, `table_name`, `column_name`, `clustering_order`, `column_name_bytes`, `kind`, `position`, `type`
- Primary key: `PRIMARY KEY ((keyspace_name), table_name, column_name)`
- Deprecated columns: none

### `system_schema.column_masks` (`system_table_column_system_schema_column_masks`)
- Source: `src/java/org/apache/cassandra/schema/SchemaKeyspace.java`
- Columns: `keyspace_name`, `table_name`, `column_name`, `function_keyspace`, `function_name`, `function_argument_types`, `function_argument_values`, `function_argument_nulls`
- Primary key: `PRIMARY KEY ((keyspace_name), table_name, column_name)`
- Deprecated columns: none

### `system_schema.dropped_columns` (`system_table_column_system_schema_dropped_columns`)
- Source: `src/java/org/apache/cassandra/schema/SchemaKeyspace.java`
- Columns: `keyspace_name`, `table_name`, `column_name`, `dropped_time`, `kind`, `type`
- Primary key: `PRIMARY KEY ((keyspace_name), table_name, column_name)`
- Deprecated columns: none

### `system_schema.triggers` (`system_table_column_system_schema_triggers`)
- Source: `src/java/org/apache/cassandra/schema/SchemaKeyspace.java`
- Columns: `keyspace_name`, `table_name`, `trigger_name`, `options`
- Primary key: `PRIMARY KEY ((keyspace_name), table_name, trigger_name)`
- Deprecated columns: none

### `system_schema.views` (`system_table_column_system_schema_views`)
- Source: `src/java/org/apache/cassandra/schema/SchemaKeyspace.java`
- Columns: `keyspace_name`, `view_name`, `base_table_id`, `base_table_name`, `where_clause`, `allow_auto_snapshot`, `bloom_filter_fp_chance`, `caching`, `comment`, `compaction`, `compression`, `memtable`, `crc_check_chance`, `dclocal_read_repair_chance`, `default_time_to_live`, `extensions`, `gc_grace_seconds`, `incremental_backups`, `id`, `include_all_columns`, `max_index_interval`, `memtable_flush_period_in_ms`, `min_index_interval`, `read_repair_chance`, `speculative_retry`, `additional_write_policy`, `cdc`, `read_repair`, `auto_repair`
- Primary key: `PRIMARY KEY ((keyspace_name), view_name)`
- Deprecated columns: none

### `system_schema.indexes` (`system_table_column_system_schema_indexes`)
- Source: `src/java/org/apache/cassandra/schema/SchemaKeyspace.java`
- Columns: `keyspace_name`, `table_name`, `index_name`, `kind`, `options`
- Primary key: `PRIMARY KEY ((keyspace_name), table_name, index_name)`
- Deprecated columns: none

### `system_schema.types` (`system_table_column_system_schema_types`)
- Source: `src/java/org/apache/cassandra/schema/SchemaKeyspace.java`
- Columns: `keyspace_name`, `type_name`, `field_names`, `field_types`
- Primary key: `PRIMARY KEY ((keyspace_name), type_name)`
- Deprecated columns: none

### `system_schema.functions` (`system_table_column_system_schema_functions`)
- Source: `src/java/org/apache/cassandra/schema/SchemaKeyspace.java`
- Columns: `keyspace_name`, `function_name`, `argument_types`, `argument_names`, `body`, `language`, `return_type`, `called_on_null_input`
- Primary key: `PRIMARY KEY ((keyspace_name), function_name, argument_types)`
- Deprecated columns: none

### `system_schema.aggregates` (`system_table_column_system_schema_aggregates`)
- Source: `src/java/org/apache/cassandra/schema/SchemaKeyspace.java`
- Columns: `keyspace_name`, `aggregate_name`, `argument_types`, `final_func`, `initcond`, `return_type`, `state_func`, `state_type`
- Primary key: `PRIMARY KEY ((keyspace_name), aggregate_name, argument_types)`
- Deprecated columns: none

### `system_traces.sessions` (`system_table_column_system_traces_sessions`)
- Source: `src/java/org/apache/cassandra/tracing/TraceKeyspace.java`
- Columns: `session_id`, `command`, `client`, `coordinator`, `coordinator_port`, `duration`, `parameters`, `request`, `started_at`
- Primary key: `PRIMARY KEY ((session_id))`
- Deprecated columns: none

### `system_traces.events` (`system_table_column_system_traces_events`)
- Source: `src/java/org/apache/cassandra/tracing/TraceKeyspace.java`
- Columns: `session_id`, `event_id`, `activity`, `source`, `source_port`, `source_elapsed`, `thread`
- Primary key: `PRIMARY KEY ((session_id), event_id)`
- Deprecated columns: none

### `system_auth.roles` (`system_table_column_system_auth_roles`)
- Source: `src/java/org/apache/cassandra/auth/AuthKeyspace.java`
- Columns: `role`, `is_superuser`, `can_login`, `salted_hash`, `member_of`
- Primary key: `PRIMARY KEY (role)`
- Deprecated columns: none

### `system_auth.identity_to_role` (`system_table_column_system_auth_identity_to_role`)
- Source: `src/java/org/apache/cassandra/auth/AuthKeyspace.java`
- Columns: `identity`, `role`
- Primary key: `PRIMARY KEY (identity)`
- Deprecated columns: none

### `system_auth.role_members` (`system_table_column_system_auth_role_members`)
- Source: `src/java/org/apache/cassandra/auth/AuthKeyspace.java`
- Columns: `role`, `member`
- Primary key: `PRIMARY KEY (role, member)`
- Deprecated columns: none

### `system_auth.role_permissions` (`system_table_column_system_auth_role_permissions`)
- Source: `src/java/org/apache/cassandra/auth/AuthKeyspace.java`
- Columns: `role`, `resource`, `permissions`
- Primary key: `PRIMARY KEY (role, resource)`
- Deprecated columns: none

### `system_auth.resource_role_permissons_index` (`system_table_column_system_auth_resource_role_permissons_index`)
- Source: `src/java/org/apache/cassandra/auth/AuthKeyspace.java`
- Columns: `resource`, `role`
- Primary key: `PRIMARY KEY (resource, role)`
- Deprecated columns: none

### `system_auth.network_permissions` (`system_table_column_system_auth_network_permissions`)
- Source: `src/java/org/apache/cassandra/auth/AuthKeyspace.java`
- Columns: `role`, `dcs`
- Primary key: `PRIMARY KEY (role)`
- Deprecated columns: none

### `system_auth.cidr_permissions` (`system_table_column_system_auth_cidr_permissions`)
- Source: `src/java/org/apache/cassandra/auth/AuthKeyspace.java`
- Columns: `role`, `cidr_groups`
- Primary key: `PRIMARY KEY (role)`
- Deprecated columns: none

### `system_auth.cidr_groups` (`system_table_column_system_auth_cidr_groups`)
- Source: `src/java/org/apache/cassandra/auth/AuthKeyspace.java`
- Columns: `cidr_group`, `cidrs`
- Primary key: `PRIMARY KEY (cidr_group)`
- Deprecated columns: none

### `system_distributed.repair_history` (`system_table_column_system_distributed_repair_history`)
- Source: `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java`
- Columns: `keyspace_name`, `columnfamily_name`, `id`, `parent_id`, `range_begin`, `range_end`, `coordinator`, `coordinator_port`, `participants`, `participants_v2`, `exception_message`, `exception_stacktrace`, `status`, `started_at`, `finished_at`
- Primary key: `PRIMARY KEY ((keyspace_name, columnfamily_name), id)`
- Deprecated columns: none

### `system_distributed.parent_repair_history` (`system_table_column_system_distributed_parent_repair_history`)
- Source: `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java`
- Columns: `parent_id`, `keyspace_name`, `columnfamily_names`, `started_at`, `finished_at`, `exception_message`, `exception_stacktrace`, `requested_ranges`, `successful_ranges`, `options`
- Primary key: `PRIMARY KEY (parent_id)`
- Deprecated columns: none

### `system_distributed.view_build_status` (`system_table_column_system_distributed_view_build_status`)
- Source: `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java`
- Columns: `keyspace_name`, `view_name`, `host_id`, `status`
- Primary key: `PRIMARY KEY ((keyspace_name, view_name), host_id)`
- Deprecated columns: none

### `system_distributed.partition_denylist` (`system_table_column_system_distributed_partition_denylist`)
- Source: `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java`
- Columns: `ks_name`, `table_name`, `key`
- Primary key: `PRIMARY KEY ((ks_name, table_name), key)`
- Deprecated columns: none

### `system_distributed.auto_repair_history` (`system_table_column_system_distributed_auto_repair_history`)
- Source: `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java`
- Columns: `host_id`, `repair_type`, `repair_turn`, `repair_start_ts`, `repair_finish_ts`, `delete_hosts`, `delete_hosts_update_time`, `force_repair`
- Primary key: `PRIMARY KEY (repair_type, host_id)`
- Deprecated columns: none

### `system_distributed.auto_repair_priority` (`system_table_column_system_distributed_auto_repair_priority`)
- Source: `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java`
- Columns: `repair_type`, `repair_priority`
- Primary key: `PRIMARY KEY (repair_type)`
- Deprecated columns: none

## 运维关注点

- 表名 drift checker 只能发现新增表没进文档；本 contract 会在列名、主键或 deprecated marker 变化时失败。
- `system_schema.tables` 和 `system_schema.views` 的 `auto_repair` 是 feature-flag optional column；禁用 auto-repair 的运行环境可能不会暴露该列，但源码 contract 仍要求研究文档覆盖。
- `system_auth.resource_role_permissons_index` 的表名拼写沿用源码常量，文档和 checker 不做自动纠正。
- `system.local.thrift_version` 不是当前 CQL 列，而是 `recordDeprecatedSystemColumn` 标记；升级兼容排查时应区别对待。
- legacy 表保留在 contract 中是为了升级兼容和 pre-flight 检查，不代表新写入路径应继续依赖它们。

## 测试用例

- `python3 research/tools/check-system-table-column-drift.py`：校验本文件与源码 `CREATE TABLE` 定义一致。
- `python3 research/tools/check-system-table-column-drift.py --dump-markdown`：从源码重新生成本文件使用的 section 形态，便于审查新增/删除列。
- `python3 research/tools/check-system-table-drift.py`：补充校验表名 registry 是否进入 research 文档。
