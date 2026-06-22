#!/usr/bin/env python3
#
# Source-only drift check for Guardrails framework research coverage.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

MATRIX_DOC = "research/module-guardrails-framework-matrix.md"
CHECKER_DOC = "research/module-guardrails-framework-drift-checker.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

GUARDRAILS_SOURCE = "src/java/org/apache/cassandra/db/guardrails/Guardrails.java"

EXPECTED_GUARDRAILS = (
    "keyspaces",
    "tables",
    "columnsPerTable",
    "secondaryIndexesPerTable",
    "createSecondaryIndexesEnabled",
    "materializedViewsPerTable",
    "tableProperties",
    "userTimestampsEnabled",
    "groupByEnabled",
    "alterTableEnabled",
    "dropTruncateTableEnabled",
    "dropKeyspaceEnabled",
    "uncompressedTablesEnabled",
    "compactTablesEnabled",
    "zeroTTLOnTWCSEnabled",
    "intersectFilteringQueryEnabled",
    "pageSize",
    "partitionKeysInSelect",
    "readBeforeWriteListOperationsEnabled",
    "allowFilteringEnabled",
    "simpleStrategyEnabled",
    "inSelectCartesianProduct",
    "readConsistencyLevels",
    "writeConsistencyLevels",
    "partitionSize",
    "partitionTombstones",
    "columnValueSize",
    "collectionSize",
    "itemsPerCollection",
    "fieldsPerUDT",
    "vectorTypeEnabled",
    "vectorDimensions",
    "localDataDiskUsage",
    "replicaDiskUsage",
    "minimumReplicationFactor",
    "maximumReplicationFactor",
    "maximumAllowableTimestamp",
    "minimumAllowableTimestamp",
    "saiSSTableIndexesPerQuery",
    "saiStringTermSize",
    "saiFrozenTermSize",
    "saiVectorTermSize",
    "nonPartitionRestrictedIndexQueryEnabled",
)

SCENARIOS = (
    "guardrails_framework_entrypoint_contract",
    "guardrails_config_provider_contract",
    "guardrails_options_validation_contract",
    "guardrails_threshold_contract",
    "guardrails_enable_flag_contract",
    "guardrails_values_predicates_contract",
    "guardrails_diagnostics_event_contract",
    "guardrails_mbean_runtime_config_contract",
    "guardrails_nodetool_runtime_config_contract",
    "guardrails_client_bypass_contract",
    "guardrails_cql_schema_entrypoints_contract",
    "guardrails_read_write_entrypoints_contract",
    "guardrails_storage_index_background_entrypoints_contract",
    "guardrails_existing_unit_tests_baseline",
    "guardrails_existing_distributed_tests_baseline",
    "guardrails_framework_ci_drift_checker_gap",
)

SOURCE_EXPECTATIONS = {
    "src/java/org/apache/cassandra/db/guardrails/Guardrails.java": (
        "public final class Guardrails implements GuardrailsMBean",
        'public static final String MBEAN_NAME = "org.apache.cassandra.db:type=Guardrails";',
        "public static final GuardrailsConfigProvider CONFIG_PROVIDER = GuardrailsConfigProvider.instance;",
        "private static final GuardrailsOptions DEFAULT_CONFIG = DatabaseDescriptor.getGuardrailsConfig();",
        "MBeanWrapper.instance.registerMBean(this, MBEAN_NAME);",
        'new Values<>("read_consistency_levels"',
        'new Values<>("write_consistency_levels"',
        'new PercentageThreshold("local_data_disk_usage"',
        'new Predicates<>("replica_disk_usage"',
        "DiskUsageBroadcaster.instance::isStuffed",
        "DiskUsageBroadcaster.instance::isFull",
        "CassandraRelevantProperties.DISK_USAGE_NOTIFY_INTERVAL_MS.getLong()",
    ),
    "src/java/org/apache/cassandra/db/guardrails/Guardrail.java": (
        "DatabaseDescriptor.isDaemonInitialized() && (state == null || state.isOrdinaryUser())",
        "ClientWarn.instance.warn(message);",
        "Tracing.trace(message);",
        "GuardrailsDiagnostics.warned(name, decorateMessage(redactedMessage));",
        "GuardrailsDiagnostics.failed(name, decorateMessage(redactedMessage));",
        "throw new GuardrailViolatedException(message);",
        'String decoratedMessage = String.format("Guardrail %s violated: %s", name, message);',
        "private boolean skipNotifying(boolean isWarn)",
    ),
    "src/java/org/apache/cassandra/db/guardrails/GuardrailsConfigProvider.java": (
        "CUSTOM_GUARDRAILS_CONFIG_PROVIDER_CLASS.getString() == null",
        "new Default() : build(CUSTOM_GUARDRAILS_CONFIG_PROVIDER_CLASS.getString())",
        'FBUtilities.construct(customImpl, "custom guardrails config provider")',
        "return DatabaseDescriptor.getGuardrailsConfig();",
    ),
    "src/java/org/apache/cassandra/db/guardrails/GuardrailsConfig.java": (
        "settings here must only be used by the {@link Guardrails} class",
        "int getKeyspacesWarnThreshold();",
        "boolean getSecondaryIndexesEnabled();",
        "Set<ConsistencyLevel> getReadConsistencyLevelsWarned();",
        "DataStorageSpec.LongBytesBound getPartitionSizeWarnThreshold();",
        "DurationSpec.LongMicrosecondsBound getMaximumTimestampWarnThreshold();",
        "boolean getNonPartitionRestrictedQueryEnabled();",
    ),
    "src/java/org/apache/cassandra/db/guardrails/Threshold.java": (
        "return failThreshold.applyAsLong(state) > 0 || warnThreshold.applyAsLong(state) > 0;",
        "public boolean triggersOn(long value, @Nullable ClientState state)",
        "public boolean warnsOn(long value, @Nullable ClientState state)",
        "public boolean failsOn(long value, @Nullable ClientState state)",
        "long failValue = failValue(state);",
        "triggerFail(value, failValue, what, containsUserData, state);",
        "triggerWarn(value, warnValue, what, containsUserData);",
        "containsUserData ? redactedErrMsg(false, value, failValue) : fullMessage",
    ),
    "src/java/org/apache/cassandra/db/guardrails/MaxThreshold.java": (
        "return value > threshold;",
        "return failValue <= 0 ? Long.MAX_VALUE : failValue;",
        "return warnValue <= 0 ? Long.MAX_VALUE : warnValue;",
    ),
    "src/java/org/apache/cassandra/db/guardrails/MinThreshold.java": (
        "return value < threshold;",
        "return failValue <= 0 ? Long.MIN_VALUE : failValue;",
        "return warnValue <= 0 ? Long.MIN_VALUE : warnValue;",
    ),
    "src/java/org/apache/cassandra/db/guardrails/PercentageThreshold.java": (
        'String.format("%d%%", value)',
        'String.format("%d%%", thresholdValue)',
    ),
    "src/java/org/apache/cassandra/db/guardrails/EnableFlag.java": (
        "return !enabled(state) || enabled.test(state);",
        "public void ensureEnabled(String featureName, @Nullable ClientState state)",
        'fail(featureName + " is not allowed", state);',
        'warn(featureName + " is not recommended");',
    ),
    "src/java/org/apache/cassandra/db/guardrails/Values.java": (
        "Set<T> toDisallow = Sets.intersection(values, disallowed);",
        "Set<T> toIgnore = Sets.intersection(values, ignored);",
        "toIgnore.forEach(ignoreAction);",
        "Set<T> toWarn = Sets.intersection(values, warned);",
    ),
    "src/java/org/apache/cassandra/db/guardrails/Predicates.java": (
        "failurePredicate.apply(state).test(value)",
        "warnPredicate.apply(state).test(value)",
        "messageProvider.createMessage(false, value)",
    ),
    "src/java/org/apache/cassandra/db/guardrails/GuardrailsDiagnostics.java": (
        "DiagnosticEventService.instance()",
        "service.publish(new GuardrailEvent(GuardrailEventType.WARNED, name, message));",
        "service.publish(new GuardrailEvent(GuardrailEventType.FAILED, name, message));",
    ),
    "src/java/org/apache/cassandra/db/guardrails/GuardrailEvent.java": (
        "WARNED, FAILED",
        'ret.put("name", name);',
        'ret.put("message", message);',
    ),
    "src/java/org/apache/cassandra/config/Config.java": (
        "public volatile int keyspaces_warn_threshold = -1;",
        "public volatile Set<String> table_properties_warned = Collections.emptySet();",
        "public volatile Set<ConsistencyLevel> read_consistency_levels_warned = Collections.emptySet();",
        "public volatile int vector_dimensions_warn_threshold = -1;",
        "public volatile int data_disk_usage_percentage_warn_threshold = -1;",
        "public volatile int sai_sstable_indexes_per_query_warn_threshold = 32;",
    ),
    "src/java/org/apache/cassandra/config/GuardrailsOptions.java": (
        'validateMaxIntThreshold(config.keyspaces_warn_threshold, config.keyspaces_fail_threshold, "keyspaces");',
        'validateTableProperties(config.table_properties_warned, "table_properties_warned")',
        'validateConsistencyLevels(config.read_consistency_levels_warned, "read_consistency_levels_warned")',
        'validateSizeThreshold(config.partition_size_warn_threshold, config.partition_size_fail_threshold, false, "partition_size");',
        'validatePercentageThreshold(config.data_disk_usage_percentage_warn_threshold, config.data_disk_usage_percentage_fail_threshold, "data_disk_usage_percentage");',
        'validateTimestampThreshold(config.maximum_timestamp_warn_threshold, config.maximum_timestamp_fail_threshold, "maximum_timestamp");',
        'updatePropertyWithLogging("keyspaces_warn_threshold"',
        'updatePropertyWithLogging("read_consistency_levels_warned"',
        'updatePropertyWithLogging("sai_sstable_indexes_per_query_warn_threshold"',
    ),
    "src/java/org/apache/cassandra/config/DatabaseDescriptor.java": (
        "private static GuardrailsOptions guardrails;",
        "public static GuardrailsOptions getGuardrailsConfig()",
        "guardrails = new GuardrailsOptions(conf);",
        "Invalid guardrails configuration",
    ),
    "src/java/org/apache/cassandra/config/CassandraRelevantProperties.java": (
        'CUSTOM_GUARDRAILS_CONFIG_PROVIDER_CLASS("cassandra.custom_guardrails_config_provider_class")',
        'DISK_USAGE_NOTIFY_INTERVAL_MS("cassandra.disk_usage.notify_interval_ms", convertToString(TimeUnit.MINUTES.toMillis(30)))',
    ),
    "src/java/org/apache/cassandra/db/guardrails/GuardrailsMBean.java": (
        "public interface GuardrailsMBean",
        "void setKeyspacesThreshold(int warn, int fail);",
        "void setTablePropertiesWarnedCSV(String properties);",
        "void setReadConsistencyLevelsWarned(Set<String> consistencyLevels);",
        "void setDataDiskUsagePercentageThreshold(int warn, int fail);",
        "void setSaiSSTableIndexesPerQueryThreshold(int warn, int fail);",
        "void setIntersectFilteringQueryEnabled(boolean value);",
    ),
    "src/java/org/apache/cassandra/tools/NodeProbe.java": (
        "name = new ObjectName(Guardrails.MBEAN_NAME);",
        "grProxy = JMX.newMBeanProxy(mbeanServerConn, name, GuardrailsMBean.class);",
        "public GuardrailsMBean getGuardrailsMBean()",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/GuardrailsConfigCommand.java": (
        '@Command(name = "getguardrailsconfig"',
        '@Command(name = "setguardrailsconfig"',
        'allowedValues = { "values", "thresholds", "flags", "others" }',
        "parseGuardrailNames(probe.getGuardrailsMBean().getClass().getDeclaredMethods(), guardrailName)",
        'snakeCase.replace("_warn_", "_")',
        "Collections.reverse(thresholdArgs);",
        'value.equals("null") ? "" : value',
        'value.equals("null") || value.equals("[]")',
        '"ZeroTTLOnTWCSEnabled", "zero_ttl_on_twcs_enabled"',
        '"NonPartitionRestrictedQueryEnabled", "non_partition_restricted_index_query_enabled"',
        'Set.of("intersect_filtering_query_warned", "zero_ttl_on_twcs_warned")',
        "public enum GuardrailCategory",
    ),
    "src/java/org/apache/cassandra/service/StorageService.java": (
        "Converters.TABLE_COUNT_THRESHOLD_TO_GUARDRAIL.unconvert(Guardrails.instance.getTablesWarnThreshold())",
        "Guardrails.instance.setTablesThreshold",
        "Converters.KEYSPACE_COUNT_THRESHOLD_TO_GUARDRAIL.unconvert(Guardrails.instance.getKeyspacesWarnThreshold())",
        "Guardrails.instance.setPartitionTombstonesThreshold",
    ),
    "src/java/org/apache/cassandra/cql3/statements/schema/CreateKeyspaceStatement.java": (
        'Guardrails.simpleStrategyEnabled.ensureEnabled("SimpleStrategy", state);',
        "Guardrails.keyspaces.guard(Schema.instance.getUserKeyspaces().size() + 1, keyspaceName, false, state);",
    ),
    "src/java/org/apache/cassandra/cql3/statements/schema/AlterKeyspaceStatement.java": (
        "Guardrails.simpleStrategyEnabled.ensureEnabled(state);",
    ),
    "src/java/org/apache/cassandra/locator/SimpleStrategy.java": (
        "Guardrails.minimumReplicationFactor.guard(rf.fullReplicas, keyspaceName, false, state);",
        "Guardrails.maximumReplicationFactor.guard(rf.fullReplicas, keyspaceName, false, state);",
    ),
    "src/java/org/apache/cassandra/locator/NetworkTopologyStrategy.java": (
        "Guardrails.minimumReplicationFactor.guard(rf.fullReplicas, keyspaceName, false, state);",
        "Guardrails.maximumReplicationFactor.guard(rf.fullReplicas, keyspaceName, false, state);",
    ),
    "src/java/org/apache/cassandra/cql3/statements/schema/CreateTableStatement.java": (
        "Guardrails.uncompressedTablesEnabled.ensureEnabled(state);",
        "Guardrails.tableProperties.guard(attrs.updatedProperties(), attrs::removeProperty, state);",
        "Guardrails.columnsPerTable.guard(rawColumns.size(), tableName, false, state);",
        "Guardrails.tables.guard(totalUserTables + 1, tableName, false, state);",
        "Guardrails.compactTablesEnabled.ensureEnabled(state);",
    ),
    "src/java/org/apache/cassandra/cql3/statements/schema/AlterTableStatement.java": (
        'Guardrails.alterTableEnabled.ensureEnabled("ALTER TABLE changing columns", state);',
        "Guardrails.columnsPerTable.guard(tableBuilder.numColumns(), tableName, false, state);",
        "Guardrails.tableProperties.guard(attrs.updatedProperties(), attrs::removeProperty, state);",
        "Guardrails.uncompressedTablesEnabled.ensureEnabled(state);",
    ),
    "src/java/org/apache/cassandra/cql3/statements/schema/CreateViewStatement.java": (
        "Guardrails.tableProperties.guard(attrs.updatedProperties(), attrs::removeProperty, state);",
        "Guardrails.materializedViewsPerTable.guard",
    ),
    "src/java/org/apache/cassandra/cql3/statements/schema/AlterViewStatement.java": (
        "Guardrails.tableProperties.guard(attrs.updatedProperties(), attrs::removeProperty, state);",
    ),
    "src/java/org/apache/cassandra/cql3/statements/schema/CreateIndexStatement.java": (
        'Guardrails.createSecondaryIndexesEnabled.ensureEnabled("Creating secondary indexes", state);',
        "Guardrails.secondaryIndexesPerTable.guard(table.indexes.size() + 1",
    ),
    "src/java/org/apache/cassandra/cql3/statements/schema/CreateTypeStatement.java": (
        "Guardrails.fieldsPerUDT.guard(fieldNames.size(), typeName, false, state);",
    ),
    "src/java/org/apache/cassandra/cql3/statements/schema/AlterTypeStatement.java": (
        "Guardrails.fieldsPerUDT.guard(userType.size() + 1, userType.getNameAsString(), false, state);",
    ),
    "src/java/org/apache/cassandra/cql3/statements/schema/DropKeyspaceStatement.java": (
        "Guardrails.dropKeyspaceEnabled.ensureEnabled(state);",
    ),
    "src/java/org/apache/cassandra/cql3/statements/schema/DropTableStatement.java": (
        "Guardrails.dropTruncateTableEnabled.ensureEnabled(state);",
    ),
    "src/java/org/apache/cassandra/cql3/statements/TruncateStatement.java": (
        "Guardrails.dropTruncateTableEnabled.ensureEnabled(state);",
    ),
    "src/java/org/apache/cassandra/cql3/statements/schema/AlterSchemaStatement.java": (
        "Guardrails.zeroTTLOnTWCSEnabled.ensureEnabled(state);",
    ),
    "src/java/org/apache/cassandra/cql3/statements/SelectStatement.java": (
        "Guardrails.allowFilteringEnabled.ensureEnabled(state);",
        "Guardrails.readConsistencyLevels.guard(EnumSet.of(cl), state.getClientState());",
        "Guardrails.nonPartitionRestrictedIndexQueryEnabled.ensureEnabled(state);",
        "Guardrails.pageSize.guard(pageSize, table(), false, state.getClientState());",
        "Guardrails.partitionKeysInSelect.guard(keys.size(), table.name, false, state);",
        "Guardrails.intersectFilteringQueryEnabled.ensureEnabled(state);",
        "Guardrails.groupByEnabled.ensureEnabled(state);",
    ),
    "src/java/org/apache/cassandra/cql3/restrictions/PartitionKeySingleRestrictionSet.java": (
        "Guardrails.inSelectCartesianProduct.enabled(state)",
        'Guardrails.inSelectCartesianProduct.guard(builder.buildSize(), "partition key", false, state);',
    ),
    "src/java/org/apache/cassandra/cql3/restrictions/ClusteringColumnRestrictions.java": (
        "Guardrails.inSelectCartesianProduct.enabled(state)",
        'Guardrails.inSelectCartesianProduct.guard(builder.buildSize(), "clustering key", false, state);',
    ),
    "src/java/org/apache/cassandra/cql3/restrictions/StatementRestrictions.java": (
        "return Guardrails.allowFilteringEnabled.isEnabled(state)",
    ),
    "src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java": (
        "Guardrails.userTimestampsEnabled.ensureEnabled(state);",
        "Guardrails.replicaDiskUsage.enabled(state)",
        "Guardrails.replicaDiskUsage.guard(replica.endpoint(), state);",
        "Guardrails.maximumAllowableTimestamp.guard(ts, table(), false, queryState.getClientState());",
        "Guardrails.minimumAllowableTimestamp.guard(ts, table(), false, queryState.getClientState());",
        "Guardrails.writeConsistencyLevels.guard(EnumSet.of(options.getConsistency(), options.getSerialConsistency())",
    ),
    "src/java/org/apache/cassandra/cql3/statements/BatchStatement.java": (
        "Guardrails.writeConsistencyLevels.guard(EnumSet.of(options.getConsistency(), options.getSerialConsistency())",
    ),
    "src/java/org/apache/cassandra/cql3/Lists.java": (
        "Guardrails.readBeforeWriteListOperationsEnabled",
        "Guardrails.itemsPerCollection.guard(elements.size(), column.name.toString(), false, params.clientState);",
        "Guardrails.collectionSize.guard(dataSize, column.name.toString(), false, params.clientState);",
    ),
    "src/java/org/apache/cassandra/cql3/Sets.java": (
        "Guardrails.itemsPerCollection.guard(elements.size(), column.name.toString(), false, params.clientState);",
        "Guardrails.collectionSize.guard(dataSize, column.name.toString(), false, params.clientState);",
    ),
    "src/java/org/apache/cassandra/cql3/Maps.java": (
        "Guardrails.itemsPerCollection.guard(elements.size(), column.name.toString(), false, params.clientState);",
        "Guardrails.collectionSize.guard(dataSize, column.name.toString(), false, params.clientState);",
    ),
    "src/java/org/apache/cassandra/cql3/UpdateParameters.java": (
        "Guardrails.columnValueSize.guard(path.dataSize(), column.name.toString(), false, clientState);",
        "Guardrails.columnValueSize.guard(value.remaining(), column.name.toString(), false, clientState);",
    ),
    "src/java/org/apache/cassandra/cql3/CQL3Type.java": (
        "Guardrails.vectorTypeEnabled.ensureEnabled(name, state);",
        "Guardrails.vectorDimensions.guard(dimensions, name, false, state);",
    ),
    "src/java/org/apache/cassandra/io/sstable/format/SortedTableWriter.java": (
        "guardPartitionThreshold(Guardrails.partitionSize, key, rowSize);",
        "guardPartitionThreshold(Guardrails.partitionTombstones, key, metadataCollector.totalTombstones);",
        "Guardrails.collectionSize.guard(cellsSize, msg, true, null);",
        "Guardrails.itemsPerCollection.guard(cellsCount, msg, true, null);",
    ),
    "src/java/org/apache/cassandra/service/disk/usage/DiskUsageMonitor.java": (
        "private final Supplier<GuardrailsConfig> guardrailsConfigSupplier = () -> Guardrails.CONFIG_PROVIDER.getOrCreate(null);",
        "Guardrails.localDataDiskUsage.guard(percentageCeiling, state.toString(), false, null);",
        "Guardrails.localDataDiskUsage.failsOn(usagePercentage, null)",
        "Guardrails.localDataDiskUsage.warnsOn(usagePercentage, null)",
    ),
    "src/java/org/apache/cassandra/index/sai/plan/QueryController.java": (
        "Guardrails.saiSSTableIndexesPerQuery.failsOn(referencedIndexes, null)",
        "Guardrails.saiSSTableIndexesPerQuery.warnsOn(referencedIndexes, null)",
    ),
    "src/java/org/apache/cassandra/index/sai/StorageAttachedIndex.java": (
        "Guardrails.saiVectorTermSize",
        "Guardrails.saiFrozenTermSize",
        "Guardrails.saiStringTermSize",
    ),
    "conf/cassandra.yaml": (
        "keyspaces_warn_threshold",
        "table_properties_warned",
        "read_consistency_levels_warned",
        "vector_dimensions_warn_threshold",
        "data_disk_usage_percentage_warn_threshold",
        "sai_sstable_indexes_per_query_warn_threshold",
    ),
    "conf/cassandra_latest.yaml": (
        "keyspaces_warn_threshold",
        "table_properties_warned",
        "read_consistency_levels_warned",
        "vector_dimensions_warn_threshold",
        "data_disk_usage_percentage_warn_threshold",
        "sai_sstable_indexes_per_query_warn_threshold",
    ),
}

TEST_EXPECTATIONS = {
    "test/unit/org/apache/cassandra/db/guardrails/GuardrailsTest.java": (
        "public void testMaxThresholdUsers()",
        "public void testMinThresholdUsers()",
        "public void testEnableFlagUsers()",
        "public void testValuesUsers()",
        "public void testPredicatesUsers()",
    ),
    "test/unit/org/apache/cassandra/db/guardrails/GuardrailTester.java": (
        "ClientState.forInternalCalls()",
        "ClientState.forExternalCalls",
        "protected final void testExcludedUsers",
        "DiagnosticEventService.instance().subscribe(GuardrailEvent.class, listener);",
        "ClientWarn.instance.captureWarnings();",
        "listener.assertWarned(redactedMessages);",
        "listener.assertFailed(redactedMessages.get(messages.size() - 1));",
        "public class Listener implements Consumer<GuardrailEvent>",
    ),
    "test/unit/org/apache/cassandra/db/guardrails/GuardrailsConfigProviderTest.java": (
        "GuardrailsConfigProvider.build(name)",
        "CustomProvider extends GuardrailsConfigProvider.Default",
        'GuardrailsConfigProvider.build("unexistent_class")',
    ),
    "test/unit/org/apache/cassandra/tools/nodetool/GuardrailsConfigCommandsTest.java": (
        'invokeNodetool("getguardrailsconfig")',
        'invokeNodetool("getguardrailsconfig", "--expand")',
        'invokeNodetool("getguardrailsconfig", "-c", "flags")',
        'invokeNodetool("setguardrailsconfig", "keyspaces_threshold", "10", "20", "30")',
        "testParsedGuardrailNamesFromMBeanExistInCassandraYaml",
        "ALL_FLAGS_GETTER_OUTPUT",
        "ALL_THRESHOLDS_GETTER_OUTPUT",
        "ALL_VALUES_GETTER_OUTPUT",
    ),
    "test/unit/org/apache/cassandra/db/guardrails/ThresholdTester.java": (
        "extends GuardrailTester",
        "private final long warnThreshold;",
        "private final long failThreshold;",
        "testValidationOfThresholdProperties",
    ),
    "test/unit/org/apache/cassandra/db/guardrails/ValueThresholdTester.java": (
        "extends ThresholdTester",
        "assertWarns(column, query",
        "assertFails(column, query",
    ),
    "test/unit/org/apache/cassandra/db/guardrails/GuardrailDiskUsageTest.java": (
        "Guardrails.localDataDiskUsage.resetLastNotifyTime();",
        "Guardrails.replicaDiskUsage.resetLastNotifyTime();",
    ),
    "test/unit/org/apache/cassandra/db/guardrails/GuardrailReadConsistencyLevelsTest.java": (
        "Guardrails.readConsistencyLevels",
    ),
    "test/unit/org/apache/cassandra/db/guardrails/GuardrailWriteConsistencyLevelsTest.java": (
        "Guardrails.writeConsistencyLevels",
    ),
    "test/unit/org/apache/cassandra/db/guardrails/GuardrailTablePropertiesTest.java": (
        "Guardrails.tableProperties",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/guardrails/GuardrailTester.java": (
        "create a regular user, since the default superuser is excluded from guardrails",
        "assertWarnsOnSSTableWrite",
        "assertFailsOnSSTableWrite",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/guardrails/GuardrailDiskUsageTest.java": (
        "Tests the guardrails for disk usage",
        "Guardrails#localDataDiskUsage",
        "Guardrails#replicaDiskUsage",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/guardrails/GuardrailPartitionSizeTest.java": (
        "GuardrailPartitionSizeTest extends GuardrailTester",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/guardrails/GuardrailCollectionSizeOnSSTableWriteTest.java": (
        "GuardrailCollectionSizeTest",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/guardrails/GuardrailItemsPerCollectionOnSSTableWriteTest.java": (
        "GuardrailItemsPerCollectionTest",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/guardrails/GuardrailNonPartitionRestrictedQueryTest.java": (
        "Guardrails.nonPartitionRestrictedIndexQueryEnabled.reason",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/guardrails/IntersectFilteringQueryTest.java": (
        "Guardrails.intersectFilteringQueryEnabled.reason",
    ),
}

DOC_SYMBOLS = (
    "Guardrails",
    "Guardrail",
    "GuardrailsConfig",
    "GuardrailsConfigProvider",
    "GuardrailsOptions",
    "GuardrailsMBean",
    "GuardrailsConfigCommand",
    "GuardrailsDiagnostics",
    "GuardrailEvent",
    "Threshold",
    "MaxThreshold",
    "MinThreshold",
    "PercentageThreshold",
    "EnableFlag",
    "Values",
    "Predicates",
    "ClientWarn",
    "Tracing",
    "DiagnosticEventService",
    "GuardrailViolatedException",
    "cassandra.custom_guardrails_config_provider_class",
    "getguardrailsconfig",
    "setguardrailsconfig",
)

INDEX_EXPECTATIONS = {
    README_DOC: (
        "module-guardrails-framework-matrix.md",
        "module-guardrails-framework-drift-checker.md",
        "check-guardrails-framework-drift.py",
    ),
    SOURCE_MAP_DOC: (
        "Guardrails framework",
        "module-guardrails-framework-matrix.md",
        "check-guardrails-framework-drift.py",
        "GuardrailsConfigCommand.java",
    ),
}

CI_NEGATIVE_PATTERNS = (
    ".circleci",
    "build.xml",
    ".github",
)


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    ok: bool
    detail: str = ""


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def all_tokens_present(path: str, tokens: tuple[str, ...]) -> list[Check]:
    text = read(path)
    return [
        Check(f"{path} token {index + 1}", path, token in text, token)
        for index, token in enumerate(tokens)
    ]


def parse_guardrail_definitions() -> dict[str, str]:
    text = read(GUARDRAILS_SOURCE)
    pattern = re.compile(
        r"public\s+static\s+final\s+"
        r"(?P<type>MaxThreshold|MinThreshold|PercentageThreshold|EnableFlag|Values<[^>]+>|Predicates<[^>]+>)\s+"
        r"(?P<name>[A-Za-z0-9_]+)\s*=",
        re.M,
    )
    return {match.group("name"): match.group("type") for match in pattern.finditer(text)}


def guardrail_definition_checks() -> tuple[list[Check], dict[str, object]]:
    definitions = parse_guardrail_definitions()
    actual = set(definitions)
    expected = set(EXPECTED_GUARDRAILS)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    checks = [
        Check("expected guardrail count", GUARDRAILS_SOURCE, len(actual) == len(EXPECTED_GUARDRAILS),
              f"expected {len(EXPECTED_GUARDRAILS)}, actual {len(actual)}"),
        Check("expected guardrail names", GUARDRAILS_SOURCE, not missing, ", ".join(missing)),
        Check("unexpected guardrail names", GUARDRAILS_SOURCE, not extra, ", ".join(extra)),
    ]
    kinds = sorted(set(definitions.values()))
    for kind in ("MaxThreshold", "MinThreshold", "PercentageThreshold", "EnableFlag",
                 "Values<ConsistencyLevel>", "Values<String>", "Predicates<InetAddressAndPort>"):
        checks.append(Check(f"guardrail kind {kind}", GUARDRAILS_SOURCE, kind in kinds, ", ".join(kinds)))

    summary = {
        "count": len(actual),
        "expected_count": len(EXPECTED_GUARDRAILS),
        "missing": missing,
        "extra": extra,
        "definitions": definitions,
    }
    return checks, summary


def doc_checks() -> list[Check]:
    matrix = read(MATRIX_DOC)
    checker = read(CHECKER_DOC)
    doc_text = matrix + "\n" + checker
    checks: list[Check] = []

    for scenario in SCENARIOS:
        checks.append(Check(f"documented scenario {scenario}", f"{MATRIX_DOC} / {CHECKER_DOC}", scenario in doc_text, scenario))

    for symbol in DOC_SYMBOLS:
        checks.append(Check(f"documented symbol {symbol}", f"{MATRIX_DOC} / {CHECKER_DOC}", symbol in doc_text, symbol))

    for guardrail in EXPECTED_GUARDRAILS:
        checks.append(Check(f"documented guardrail {guardrail}", MATRIX_DOC, guardrail in matrix, guardrail))

    for path, tokens in INDEX_EXPECTATIONS.items():
        checks.extend(all_tokens_present(path, tokens))

    return checks


def source_checks() -> list[Check]:
    checks: list[Check] = []
    for path, tokens in SOURCE_EXPECTATIONS.items():
        checks.extend(all_tokens_present(path, tokens))
    guardrail_checks, _ = guardrail_definition_checks()
    checks.extend(guardrail_checks)
    return checks


def test_checks() -> list[Check]:
    checks: list[Check] = []
    for path, tokens in TEST_EXPECTATIONS.items():
        checks.extend(all_tokens_present(path, tokens))
    return checks


def ci_gap_checks() -> tuple[list[Check], list[str]]:
    hits: list[str] = []
    for rel in CI_NEGATIVE_PATTERNS:
        root = REPO_ROOT / rel
        if not root.exists():
            continue
        files = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
        for path in files:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "check-guardrails-framework-drift.py" in text:
                hits.append(str(path.relative_to(REPO_ROOT)))

    return [
        Check("guardrails framework checker not wired into CI yet",
              " / ".join(CI_NEGATIVE_PATTERNS),
              not hits,
              ", ".join(hits)),
    ], hits


def check() -> tuple[dict[str, object], bool]:
    _, guardrail_summary = guardrail_definition_checks()
    checks = []
    checks.extend(source_checks())
    checks.extend(test_checks())
    checks.extend(doc_checks())
    gap_checks, ci_hits = ci_gap_checks()
    checks.extend(gap_checks)

    failed = [entry for entry in checks if not entry.ok]
    result = {
        "guardrail_summary": guardrail_summary,
        "scenario_count": len(SCENARIOS),
        "source_file_count": len(SOURCE_EXPECTATIONS),
        "test_file_count": len(TEST_EXPECTATIONS),
        "doc_files": [MATRIX_DOC, CHECKER_DOC, README_DOC, SOURCE_MAP_DOC],
        "ci_hits_for_gap": ci_hits,
        "checks": [entry.__dict__ for entry in checks],
        "failed_checks": [entry.__dict__ for entry in failed],
    }
    return result, not failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Guardrails framework research coverage for source/test/doc drift.")
    parser.add_argument("--json", action="store_true", help="print full JSON report")
    args = parser.parse_args()

    result, ok = check()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif ok:
        summary = result["guardrail_summary"]
        print(
            "OK guardrails framework drift checks passed "
            f"({summary['count']} guardrails, "
            f"{result['source_file_count']} source files, "
            f"{result['test_file_count']} test files, "
            f"{result['scenario_count']} scenarios)"
        )
    else:
        print("FAIL guardrails framework drift checks failed:")
        for entry in result["failed_checks"]:
            detail = f" :: {entry['detail']}" if entry.get("detail") else ""
            print(f" - {entry['name']} [{entry['source']}]{detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
