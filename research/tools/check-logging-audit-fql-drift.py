#!/usr/bin/env python3
#
# Source-only drift check for Logging/Audit/FQL operations research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

LOGBACK = "conf/logback.xml"
LOGBACK_TOOLS = "conf/logback-tools.xml"
CASSANDRA_YAML = "conf/cassandra.yaml"
LOGGING_SUPPORT_FACTORY = "src/java/org/apache/cassandra/utils/logging/LoggingSupportFactory.java"
LOGBACK_SUPPORT = "src/java/org/apache/cassandra/utils/logging/LogbackLoggingSupport.java"
VIRTUAL_TABLE_APPENDER = "src/java/org/apache/cassandra/utils/logging/VirtualTableAppender.java"
LOG_MESSAGES_TABLE = "src/java/org/apache/cassandra/db/virtual/LogMessagesTable.java"
STORAGE_SERVICE = "src/java/org/apache/cassandra/service/StorageService.java"
STORAGE_SERVICE_MBEAN = "src/java/org/apache/cassandra/service/StorageServiceMBean.java"
NODE_TOOL = "src/java/org/apache/cassandra/tools/NodeTool.java"
NODE_PROBE = "src/java/org/apache/cassandra/tools/NodeProbe.java"
SET_LOGGING_LEVEL = "src/java/org/apache/cassandra/tools/nodetool/SetLoggingLevel.java"
GET_LOGGING_LEVELS = "src/java/org/apache/cassandra/tools/nodetool/GetLoggingLevels.java"
CASSANDRA_RELEVANT_PROPERTIES = "src/java/org/apache/cassandra/config/CassandraRelevantProperties.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"

AUDIT_LOG_OPTIONS = "src/java/org/apache/cassandra/audit/AuditLogOptions.java"
AUDIT_LOG_FILTER = "src/java/org/apache/cassandra/audit/AuditLogFilter.java"
AUDIT_LOG_MANAGER = "src/java/org/apache/cassandra/audit/AuditLogManager.java"
BIN_AUDIT_LOGGER = "src/java/org/apache/cassandra/audit/BinAuditLogger.java"
FILE_AUDIT_LOGGER = "src/java/org/apache/cassandra/audit/FileAuditLogger.java"
AUDIT_LOG_ENTRY = "src/java/org/apache/cassandra/audit/AuditLogEntry.java"
ENABLE_AUDIT_LOG = "src/java/org/apache/cassandra/tools/nodetool/EnableAuditLog.java"
GET_AUDIT_LOG = "src/java/org/apache/cassandra/tools/nodetool/GetAuditLog.java"
DISABLE_AUDIT_LOG = "src/java/org/apache/cassandra/tools/nodetool/DisableAuditLog.java"

FULL_QUERY_LOGGER_OPTIONS = "src/java/org/apache/cassandra/fql/FullQueryLoggerOptions.java"
FULL_QUERY_LOGGER = "src/java/org/apache/cassandra/fql/FullQueryLogger.java"
ENABLE_FULL_QUERY_LOG = "src/java/org/apache/cassandra/tools/nodetool/EnableFullQueryLog.java"
GET_FULL_QUERY_LOG = "src/java/org/apache/cassandra/tools/nodetool/GetFullQueryLog.java"
RESET_FULL_QUERY_LOG = "src/java/org/apache/cassandra/tools/nodetool/ResetFullQueryLog.java"
DISABLE_FULL_QUERY_LOG = "src/java/org/apache/cassandra/tools/nodetool/DisableFullQueryLog.java"

BINLOG = "src/java/org/apache/cassandra/utils/binlog/BinLog.java"
BINLOG_OPTIONS = "src/java/org/apache/cassandra/utils/binlog/BinLogOptions.java"
EXTERNAL_ARCHIVER = "src/java/org/apache/cassandra/utils/binlog/ExternalArchiver.java"
DELETING_ARCHIVER = "src/java/org/apache/cassandra/utils/binlog/DeletingArchiver.java"

LOG_MESSAGES_TABLE_TEST = "test/unit/org/apache/cassandra/db/virtual/LogMessagesTableTest.java"
VIRTUAL_TABLE_LOGS_TEST = "test/distributed/org/apache/cassandra/distributed/test/VirtualTableLogsTest.java"
AUDIT_LOG_FILTER_TEST = "test/unit/org/apache/cassandra/audit/AuditLogFilterTest.java"
AUDIT_LOGGER_TEST = "test/unit/org/apache/cassandra/audit/AuditLoggerTest.java"
AUDIT_LOGGER_AUTH_TEST = "test/unit/org/apache/cassandra/audit/AuditLoggerAuthTest.java"
CQL_USER_AUDIT_TEST = "test/unit/org/apache/cassandra/transport/CQLUserAuditTest.java"
GET_AUDIT_LOG_TEST = "test/unit/org/apache/cassandra/tools/nodetool/GetAuditLogTest.java"
STORAGE_SERVICE_SERVER_TEST = "test/unit/org/apache/cassandra/service/StorageServiceServerTest.java"
FULL_QUERY_LOGGER_TEST = "test/unit/org/apache/cassandra/fql/FullQueryLoggerTest.java"
GET_FULL_QUERY_LOG_TEST = "test/unit/org/apache/cassandra/tools/nodetool/GetFullQueryLogTest.java"
FQL_REPLAY_DDL_TEST = "test/distributed/org/apache/cassandra/distributed/test/fql/FqlReplayDDLExclusionTest.java"

TARGET_DOCS = (
    "research/module-operations-observability.md",
    "research/module-observability-internals.md",
    "research/module-logging-audit-fql-operations-matrix.md",
    "research/module-logging-audit-fql-drift-checker.md",
    "research/flow-ops-tools.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "logging_ops_logback_file_appenders",
    "logging_ops_dynamic_level_jmx_nodetool",
    "logging_ops_logback_support_boundary",
    "logging_ops_virtual_table_buffer",
    "logging_ops_audit_options_defaults_filters",
    "logging_ops_audit_listener_lifecycle",
    "logging_ops_audit_nodetool_archive_gate",
    "logging_ops_fql_enable_reset_payload",
    "logging_ops_fql_nodetool_archive_gate",
    "logging_ops_binlog_backpressure_archiver",
    "logging_ops_external_collection_gap",
)

SOURCE_TOKEN_CHECKS = {
    LOGBACK: (
        '<configuration scan="true" scanPeriod="60 seconds">',
        '<appender name="SYSTEMLOG" class="ch.qos.logback.core.rolling.RollingFileAppender">',
        '<appender name="DEBUGLOG" class="ch.qos.logback.core.rolling.RollingFileAppender">',
        '<appender name="ASYNCDEBUGLOG" class="ch.qos.logback.classic.AsyncAppender">',
        '<appender name="STDOUT" class="ch.qos.logback.core.ConsoleAppender">',
        '<file>${cassandra.logdir}/system.log</file>',
        '<file>${cassandra.logdir}/debug.log</file>',
        '<appender name="CQLLOG" class="org.apache.cassandra.utils.logging.VirtualTableAppender">',
        '<root level="INFO">',
    ),
    LOGBACK_TOOLS: (
        '<appender name="STDERR" class="ch.qos.logback.core.ConsoleAppender">',
        '<target>System.err</target>',
        '<root level="WARN">',
    ),
    LOGGING_SUPPORT_FACTORY: (
        'String loggerFactoryClass = LoggerFactory.getILoggerFactory().getClass().getName();',
        'if (loggerFactoryClass.contains("logback"))',
        'loggingSupport = FBUtilities.instanceOrConstruct("org.apache.cassandra.utils.logging.LogbackLoggingSupport", "LogbackLoggingSupport");',
        'loggingSupport = new NoOpFallbackLoggingSupport();',
        'You will not be able to dynamically manage log levels via JMX',
    ),
    LOGBACK_SUPPORT: (
        "public void onStartup()",
        "checkOnlyOneVirtualTableAppender();",
        "new SMAwareReconfigureOnChangeFilter(reconfigureOnChangeFilter)",
        "public void setLoggingLevel(String classQualifier, String rawLevel) throws Exception",
        "if (StringUtils.isBlank(classQualifier) && StringUtils.isBlank(rawLevel))",
        "new ContextInitializer(lc).autoConfig();",
        "else if (StringUtils.isNotBlank(classQualifier) && StringUtils.isBlank(rawLevel))",
        "logBackLogger.setLevel(null);",
        "Level level = Level.toLevel(rawLevel);",
        "public Map<String, String> getLoggingLevels()",
        "private void checkOnlyOneVirtualTableAppender()",
        "throw new IllegalStateException(String.format(\"There are multiple appenders of class %s",
    ),
    VIRTUAL_TABLE_APPENDER: (
        'public static final String APPENDER_NAME = "CQLLOG";',
        "private static final Set<String> forbiddenLoggers = ImmutableSet.of(FileAuditLogger.class.getName());",
        "private final List<LoggingEvent> messageBuffer = new LinkedList<>();",
        "if (!forbiddenLoggers.contains(eventObject.getLoggerName()))",
        "logs = getVirtualTable();",
        "addToBuffer(eventObject);",
        "public void flushBuffer()",
        "messageBuffer.forEach(vtable::add);",
        "if (messageBuffer.size() < LOGS_VIRTUAL_TABLE_DEFAULT_ROWS)",
    ),
    LOG_MESSAGES_TABLE: (
        "public static final int LOGS_VIRTUAL_TABLE_MIN_ROWS = 1000;",
        "public static final int LOGS_VIRTUAL_TABLE_DEFAULT_ROWS = 50_000;",
        "public static final int LOGS_VIRTUAL_TABLE_MAX_ROWS = 100_000;",
        'public static final String TABLE_NAME = "system_logs";',
        "addPartitionKeyColumn(TIMESTAMP_COLUMN_NAME, TimestampType.instance)",
        "addClusteringColumn(ORDER_IN_MILLISECOND_COLUMN_NAME, Int32Type.instance)",
        "public void add(LoggingEvent event)",
        "public void truncate()",
        "public boolean allowFilteringImplicitly()",
        "static int resolveBufferSize()",
        "LOGS_VIRTUAL_TABLE_MAX_ROWS.getInt()",
        "if (size() == maxSize)",
        "removeLast();",
        "addFirst(t);",
    ),
    STORAGE_SERVICE_MBEAN: (
        "public void setLoggingLevel(String classQualifier, String level) throws Exception;",
        "public Map<String,String> getLoggingLevels();",
        "public void enableAuditLog(String loggerName",
        "public void disableAuditLog();",
        "public void enableFullQueryLogger(String path",
        "public void resetFullQueryLogger();",
        "public void stopFullQueryLogger();",
    ),
    STORAGE_SERVICE: (
        "public void setLoggingLevel(String classQualifier, String rawLevel) throws Exception",
        "LoggingSupportFactory.getLoggingSupport().setLoggingLevel(classQualifier, rawLevel);",
        "public Map<String,String> getLoggingLevels()",
        "LoggingSupportFactory.getLoggingSupport().getLoggingLevels();",
        "public void disableAuditLog()",
        "AuditLogManager.instance.disableAuditLog();",
        "Can't enable audit log archiving via nodetool unless audit_logging_options.allow_nodetool_archive_command is set to true",
        "AuditLogManager.instance.enable(options);",
        "public void enableFullQueryLogger(String path, String rollCycle, Boolean blocking",
        "Can't enable full query log archiving via nodetool unless full_query_logging_options.allow_nodetool_archive_command is set to true",
        "Preconditions.checkNotNull(path, \"cassandra.yaml did not set log_dir and not set as parameter\");",
        "FullQueryLogger.instance.enableWithoutClean",
        "FullQueryLogger.instance.reset(DatabaseDescriptor.getFullQueryLogOptions().log_dir);",
        "FullQueryLogger.instance.stop();",
    ),
    NODE_TOOL: (
        "DisableAuditLog.class,",
        "DisableFullQueryLog.class,",
        "EnableAuditLog.class,",
        "EnableFullQueryLog.class,",
        "GetAuditLog.class,",
        "GetFullQueryLog.class,",
        "GetLoggingLevels.class,",
        "ResetFullQueryLog.class,",
        "SetLoggingLevel.class,",
    ),
    NODE_PROBE: (
        "public void setLoggingLevel(String classQualifier, String level)",
        "ssProxy.setLoggingLevel(classQualifier, level);",
        "public Map<String, String> getLoggingLevels()",
        "return ssProxy.getLoggingLevels();",
        "public void enableAuditLog(String loggerName, Map<String, String> parameters",
        "ssProxy.enableAuditLog(loggerName, parameters",
        "public FullQueryLoggerOptions getFullQueryLoggerOptions()",
        "FullQueryLoggerOptionsCompositeData.fromCompositeData(ssProxy.getFullQueryLoggerOptions());",
        "public AuditLogOptions getAuditLogOptions()",
        "AuditLogOptionsCompositeData.fromCompositeData(almProxy.getAuditLogOptionsData());",
    ),
    SET_LOGGING_LEVEL: (
        '@Command(name = "setlogginglevel"',
        'Available components:  bootstrap, compaction, repair, streaming, cql, ring',
        'if (target.equals("bootstrap"))',
        'else if (target.equals("repair"))',
        'else if (target.equals("streaming"))',
        'else if (target.equals("compaction"))',
        'else if (target.equals("cql"))',
        'else if (target.equals("ring"))',
        "probe.setLoggingLevel(classQualifier, level);",
    ),
    GET_LOGGING_LEVELS: (
        '@Command(name = "getlogginglevels"',
        'probe.output().out.printf("%n%-50s%10s%n", "Logger Name", "Log Level");',
        "for (Map.Entry<String, String> entry : probe.getLoggingLevels().entrySet())",
    ),
    CASSANDRA_RELEVANT_PROPERTIES: (
        'LOGBACK_CONFIGURATION_FILE("logback.configurationFile")',
        'LOGS_VIRTUAL_TABLE_MAX_ROWS("cassandra.virtual.logs.max.rows"',
        'LOG_DIR("cassandra.logdir", ".")',
        'LOG_DIR_AUDIT("cassandra.logdir.audit")',
    ),
    CONFIG: (
        "public volatile AuditLogOptions audit_logging_options = new AuditLogOptions();",
        "public volatile FullQueryLoggerOptions full_query_logging_options = new FullQueryLoggerOptions();",
        "public volatile boolean diagnostic_events_enabled = false;",
    ),
    DATABASE_DESCRIPTOR: (
        "public static FullQueryLoggerOptions getFullQueryLogOptions()",
        "return  conf.full_query_logging_options;",
        "public static void setFullQueryLogOptions(FullQueryLoggerOptions options)",
        "public static AuditLogOptions getAuditLoggingOptions()",
        "return conf.audit_logging_options;",
        "public static void setAuditLoggingOptions(AuditLogOptions auditLoggingOptions)",
        "conf.audit_logging_options = new AuditLogOptions.Builder(auditLoggingOptions).build();",
    ),
    CASSANDRA_YAML: (
        "slow_query_log_timeout: 500ms",
        "audit_logging_options:",
        "enabled: false",
        "- class_name: BinAuditLogger",
        "excluded_keyspaces: system, system_schema, system_virtual_schema",
        "max_queue_weight: 268435456 # 256 MiB",
        "max_log_size: 17179869184 # 16 GiB",
        "full_query_logging_options:",
        "allow_nodetool_archive_command: false",
    ),
    AUDIT_LOG_OPTIONS: (
        "public volatile boolean enabled = false;",
        "new ParameterizedClass(BinAuditLogger.class.getSimpleName(), Collections.emptyMap())",
        'public String excluded_keyspaces = "system,system_schema,system_virtual_schema";',
        "String auditLogDir = CassandraRelevantProperties.LOG_DIR_AUDIT.getString();",
        'String logDir = CassandraRelevantProperties.LOG_DIR.getString() + "/audit";',
        "validateCategories(options.included_categories);",
        "validateCategories(options.excluded_categories);",
        "this.maxQueueWeight = opts.max_queue_weight;",
        "sanitise(includedCategories).map(v -> this.includedCategories = v.toUpperCase());",
        "AuditLogOptions.validate(opts);",
        "AuditLogEntryCategory.valueOf(includedCategory);",
    ),
    AUDIT_LOG_FILTER: (
        "static AuditLogFilter create(AuditLogOptions auditLogOptions)",
        "IncludeExcludeHolder keyspaces = loadInputSets(auditLogOptions.included_keyspaces, auditLogOptions.excluded_keyspaces);",
        "boolean isFiltered(AuditLogEntry auditLogEntry)",
        "return isFiltered(auditLogEntry.getKeyspace(), includedKeyspaces, excludedKeyspaces)",
    ),
    AUDIT_LOG_MANAGER: (
        "public class AuditLogManager implements QueryEvents.Listener, AuthEvents.Listener, AuditLogManagerMBean",
        'public static final String MBEAN_NAME = "org.apache.cassandra.db:type=AuditLogManager";',
        "public CompositeData getAuditLogOptionsData()",
        "if (!filter.isFiltered(logEntry))",
        "public synchronized void disableAuditLog()",
        "unregisterAsListener();",
        "auditLogger = new NoOpAuditLogger(Collections.emptyMap());",
        "public synchronized void enable(AuditLogOptions auditLogOptions) throws ConfigurationException",
        "auditLogger = getAuditLogger(auditLogOptions);",
        "filter = AuditLogFilter.create(auditLogOptions);",
        "registerAsListener();",
        "oldLogger.stop();",
        "QueryEvents.instance.registerListener(this);",
        "AuthEvents.instance.registerListener(this);",
        "public void querySuccess(CQLStatement statement",
        "public void batchFailure(BatchStatement.Type batchType",
        "public void authSuccess(QueryState state)",
        "public void authFailure(QueryState state, Exception cause)",
    ),
    BIN_AUDIT_LOGGER: (
        'public static final String AUDITLOG_TYPE = "audit";',
        "new BinLog.Builder().path(File.getPath(auditLoggingOptions.audit_logs_dir))",
        ".rollCycle(auditLoggingOptions.roll_cycle)",
        ".blocking(auditLoggingOptions.block)",
        ".maxQueueWeight(auditLoggingOptions.max_queue_weight)",
        ".maxLogSize(auditLoggingOptions.max_log_size)",
        ".archiveCommand(auditLoggingOptions.archive_command)",
        ".maxArchiveRetries(auditLoggingOptions.max_archive_retries)",
        ".build(false);",
        "binLog.logRecord(new Message(auditLogEntry.getLogString()));",
        "public int weight()",
    ),
    FILE_AUDIT_LOGGER: (
        "public class FileAuditLogger implements IAuditLogger",
        "logger.info(auditLogEntry.getLogString());",
        "enabled = false;",
    ),
    AUDIT_LOG_ENTRY: (
        "String getLogString()",
        'builder.append("user:").append(user)',
        '.append("|host:").append(host)',
        '.append("|source:").append(source.getAddress());',
        '.append("|timestamp:").append(timestamp)',
        '.append("|type:").append(type)',
        '.append("|category:").append(type.getCategory());',
        '.append("|operation:").append(operation);',
    ),
    ENABLE_AUDIT_LOG: (
        '@Command(name = "enableauditlog"',
        '@Option(title = "logger", name = { "--logger" }',
        '@Option(title = "included_keyspaces", name = { "--included-keyspaces" }',
        '@Option(title = "archive_command", name = {"--archive-command"}',
        "if (!blocking.equalsIgnoreCase(\"TRUE\") && !blocking.equalsIgnoreCase(\"FALSE\"))",
        "probe.enableAuditLog(logger, Collections.EMPTY_MAP",
    ),
    GET_AUDIT_LOG: (
        '@Command(name = "getauditlog"',
        'tableBuilder.add("enabled", Boolean.toString(probe.getStorageService().isAuditLogEnabled()));',
        'tableBuilder.add("logger", options.logger.class_name);',
        'tableBuilder.add("audit_logs_dir", options.audit_logs_dir);',
        'tableBuilder.add("archive_command", options.archive_command);',
        'tableBuilder.add("included_keyspaces", options.included_keyspaces);',
        'tableBuilder.add("excluded_users", options.excluded_users);',
    ),
    DISABLE_AUDIT_LOG: (
        '@Command(name = "disableauditlog"',
        "probe.disableAuditLog();",
    ),
    FULL_QUERY_LOGGER_OPTIONS: (
        "public class FullQueryLoggerOptions extends BinLogOptions",
        "public String log_dir = StringUtils.EMPTY;",
    ),
    FULL_QUERY_LOGGER: (
        "public static final FullQueryLogger instance = new FullQueryLogger();",
        "public synchronized void enable(Path path, String rollCycle, boolean blocking",
        ".build(true);",
        "public synchronized void enableWithoutClean(Path path, String rollCycle, boolean blocking",
        ".build(false);",
        "QueryEvents.instance.registerListener(this);",
        "public FullQueryLoggerOptions getFullQueryLoggerOptions()",
        "options.log_dir = binLog.path.toString();",
        "public synchronized void stop()",
        "QueryEvents.instance.unregisterListener(this);",
        "public synchronized void reset(String fullQueryLogPath)",
        "Set<File> pathsToClean = Sets.newHashSet();",
        "accumulate = BinLog.cleanDirectory(f, accumulate);",
        "public void batchSuccess(BatchStatement.Type type",
        "public void querySuccess(CQLStatement statement",
        "BinLog binLog = this.binLog;",
        "binLog.logRecord(wrappedQuery);",
        'return SINGLE_QUERY;',
        'return BATCH;',
        "wire.write(QUERY_OPTIONS).bytes(BytesStore.wrap(queryOptionsBuffer.nioBuffer()));",
        "wire.write(KEYSPACE).text(keyspace);",
    ),
    ENABLE_FULL_QUERY_LOG: (
        '@Command(name = "enablefullquerylog"',
        '@Option(title = "path", name = {"--path"}',
        '@Option(title = "archive_command", name = {"--archive-command"}',
        "if (!blocking.equalsIgnoreCase(\"TRUE\") && !blocking.equalsIgnoreCase(\"FALSE\"))",
        "probe.enableFullQueryLogger(path, rollCycle, bblocking, maxQueueWeight, maxLogSize, archiveCommand, archiveRetries);",
    ),
    GET_FULL_QUERY_LOG: (
        '@Command(name = "getfullquerylog"',
        'tableBuilder.add("enabled", Boolean.toString(probe.getStorageService().isFullQueryLogEnabled()));',
        'tableBuilder.add("log_dir", options.log_dir);',
        'tableBuilder.add("archive_command", options.archive_command);',
        'tableBuilder.add("max_archive_retries", Long.toString(options.max_archive_retries));',
    ),
    RESET_FULL_QUERY_LOG: (
        '@Command(name = "resetfullquerylog"',
        "probe.resetFullQueryLogger();",
    ),
    DISABLE_FULL_QUERY_LOG: (
        '@Command(name = "disablefullquerylog"',
        "probe.stopFullQueryLogger();",
    ),
    BINLOG_OPTIONS: (
        "public String archive_command = StringUtils.EMPTY;",
        "public boolean allow_nodetool_archive_command = false;",
        'public String roll_cycle = "HOURLY";',
        "public boolean block = true;",
        "public int max_queue_weight = 256 * 1024 * 1024;",
        "public long max_log_size = 16L * 1024L * 1024L * 1024L;",
        "public int max_archive_retries = 10;",
    ),
    BINLOG: (
        'private static final NoSpamLogger.NoSpamLogStatement droppedSamplesStatement = noSpamLogger.getStatement("Dropped {} binary log samples", 1, TimeUnit.MINUTES);',
        "final WeightedQueue<ReleaseableWriteMarshallable> sampleQueue;",
        "private final boolean blocking;",
        "private static final Set<Path> currentPaths = Collections.synchronizedSet(new HashSet<>());",
        "sampleQueue.put(NO_OP);",
        "currentPaths.remove(path);",
        "public void logRecord(ReleaseableWriteMarshallable record)",
        "if (blocking)",
        "put(record);",
        "if (!offer(record))",
        "logDroppedSample();",
        "droppedSamplesSinceLastLog.incrementAndGet();",
        "public Builder path(Path path)",
        "Preconditions.checkArgument((pathAsFile.exists() && pathAsFile.isDirectory()) || (!pathAsFile.exists() && pathAsFile.tryCreateDirectories())",
        "public Builder rollCycle(String rollCycle)",
        "public BinLog build(boolean cleanDirectory)",
        "if (currentPaths.contains(path))",
        "throw new IllegalStateException(\"Already logging to \" + path);",
        "Strings.isNullOrEmpty(archiveCommand) ? new DeletingArchiver(maxLogSize) : new ExternalArchiver(archiveCommand, path, maxArchiveRetries);",
        "if (cleanDirectory)",
    ),
    EXTERNAL_ARCHIVER: (
        "private static final Pattern PATH = Pattern.compile(\"%path\");",
        "private final DelayQueue<DelayFile> archiveQueue = new DelayQueue<>();",
        "archiveExisting(path);",
        "archiveQueue.add(new DelayFile(file, 0, TimeUnit.MILLISECONDS, 0));",
        "if (toArchive.retries < maxRetries)",
        "archiveExisting(path);",
    ),
    DELETING_ARCHIVER: (
        "public class DeletingArchiver implements BinLogArchiver",
        "private final long maxLogSize;",
        "while (bytesInStoreFiles > maxLogSize & !chronicleStoreFiles.isEmpty())",
        "Failed to delete chronicle store file",
        "Deleted chronicle store file",
    ),
    LOG_MESSAGES_TABLE_TEST: (
        "public void testLimitedCapacity()",
        "assertEquals(100, numberOfPartitions());",
        "public void testMultipleLogsInSameMillisecond()",
        "public void testResolvingBufferSize()",
        "LOGS_VIRTUAL_TABLE_MAX_ROWS.setInt(-1);",
        "LOGS_VIRTUAL_TABLE_MAX_ROWS.setInt(50001);",
    ),
    VIRTUAL_TABLE_LOGS_TEST: (
        "public void testVTableOutput()",
        'LOGBACK_CONFIGURATION_FILE, "test/conf/logback-dtest_with_vtable_appender.xml"',
        "rows.forEach(message -> assertTrue(Level.toLevel(message.level).isGreaterOrEqual(Level.INFO)));",
        "public void testMultipleAppendersFailToStartNode()",
        'LOGBACK_CONFIGURATION_FILE.setString("test/conf/logback-dtest_with_vtable_appender_invalid.xml");',
        "VirtualTableAppender.class.getName()",
        "CQLLOG,CQLLOG2",
    ),
    AUDIT_LOG_FILTER_TEST: (
        "public class AuditLogFilterTest",
        "isFiltered",
    ),
    AUDIT_LOGGER_TEST: (
        "public void testAuditLogFilters()",
        "public void testAuditLogFiltersTransitions()",
        "assertEquals(1, QueryEvents.instance.listenerCount());",
        "assertEquals(1, AuthEvents.instance.listenerCount());",
        "assertEquals(0, QueryEvents.instance.listenerCount());",
        "public void testConflictingPaths()",
        "fail(\"Conflicting directories - should throw exception\");",
        "public void testConflictingPathsFQLFirst()",
    ),
    AUDIT_LOGGER_AUTH_TEST: (
        "public void testCqlLoginAuditing()",
        "public void testCqlGRANTAuditing()",
        "public void testUNAUTHORIZED_ATTEMPTAuditing()",
    ),
    CQL_USER_AUDIT_TEST: (
        "AuditLogEntryType.LOGIN_ERROR",
        "AuditLogEntryType.LOGIN_SUCCESS",
    ),
    GET_AUDIT_LOG_TEST: (
        "ToolRunner.invokeNodetool(\"getauditlog\")",
        "ToolRunner.invokeNodetool(\"disableauditlog\")",
        "ToolRunner.invokeNodetool(\"enableauditlog\")",
        "ToolRunner.invokeNodetool(\"enableauditlog\",",
        "assertThat(output).contains(\"logger BinAuditLogger\");",
        "assertThat(output).contains(\"excluded_keyspaces system,system_schema,system_virtual_schema\");",
    ),
    STORAGE_SERVICE_SERVER_TEST: (
        "public void testAuditLogEnableLoggerNotFound()",
        "public void testAuditLogEnableLoggerTransitions()",
    ),
    FULL_QUERY_LOGGER_TEST: (
        "public void testConfigureNullPath()",
        "public void testConfigureInvalidRollCycle()",
        "public void testConfigureInvalidMaxQueueWeight()",
        "public void testResetCleansPaths()",
        "public void testDoubleConfigure()",
        "public void testEnabledReset()",
        "public void testEnabledStop()",
        "DatabaseDescriptor.getFullQueryLogOptions().allow_nodetool_archive_command = false;",
        "Can't enable full query log archiving via nodetool",
        "options.allow_nodetool_archive_command = true;",
        "FullQueryLogger.instance.querySuccess(null, query, QueryOptions.DEFAULT",
        "FullQueryLogger.instance.batchSuccess(type,",
    ),
    GET_FULL_QUERY_LOG_TEST: (
        "ToolRunner.invokeNodetool(\"getfullquerylog\")",
        "ToolRunner.invokeNodetool(\"resetfullquerylog\")",
        "ToolRunner.invokeNodetool(\"disablefullquerylog\")",
        "ToolRunner.invokeNodetool(\"enablefullquerylog\",",
        "assertThat(output).contains(\"archive_command /path/to/script.sh %path\");",
        "assertThat(output).contains(\"roll_cycle DAILY\");",
    ),
    FQL_REPLAY_DDL_TEST: (
        'node.nodetool("enablefullquerylog", "--path", temporaryFolder.getRoot().getAbsolutePath());',
        "FullQueryLogTool",
        "--keyspace",
    ),
}

DOC_REQUIRED_TOKENS = (
    "research/tools/check-logging-audit-fql-drift.py",
    "research/module-logging-audit-fql-operations-matrix.md",
    "research/module-logging-audit-fql-drift-checker.md",
    "LoggingSupportFactory",
    "LogbackLoggingSupport",
    "VirtualTableAppender",
    "LogMessagesTable",
    "AuditLogManager",
    "BinAuditLogger",
    "FullQueryLogger",
    "BinLog",
    "EnableAuditLog",
    "EnableFullQueryLog",
    "ExternalArchiver",
    "DeletingArchiver",
    "logging_ops_external_collection_gap",
)

EXTERNAL_LOG_COLLECTOR_MARKERS = (
    "filebeat",
    "fluent-bit",
    "fluentbit",
    "logstash",
    "promtail",
    "vector.dev",
    "vector.toml",
)


@dataclass(frozen=True)
class Check:
    name: str
    path: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def source_checks() -> list[Check]:
    checks: list[Check] = []
    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(Check(f"source token contract {path}", path, all(token in text for token in tokens)))

    deployment_files = [
        path
        for path in REPO_ROOT.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and "build" not in path.parts
        and path.suffix.lower() in {".yml", ".yaml", ".xml", ".conf", ".properties", ".toml", ".json"}
    ]
    external_hits = []
    for path in deployment_files:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        if any(marker in text for marker in EXTERNAL_LOG_COLLECTOR_MARKERS):
            external_hits.append(str(path.relative_to(REPO_ROOT)))
    checks.append(Check(
        "gap still open: no source-owned external log collector configuration",
        "repository config files",
        not external_hits,
    ))

    return checks


def doc_checks() -> list[Check]:
    docs = {path: read(path) for path in TARGET_DOCS}
    combined = "\n".join(docs.values())
    checks = [Check(f"target doc exists {path}", path, bool(text.strip())) for path, text in docs.items()]
    checks.extend(Check(f"doc token {token}", "research", token in combined) for token in DOC_REQUIRED_TOKENS)

    matrix = docs["research/module-logging-audit-fql-operations-matrix.md"]
    drift_doc = docs["research/module-logging-audit-fql-drift-checker.md"]
    for scenario in SCENARIO_IDS:
        checks.append(Check(f"scenario coverage {scenario}", "research", scenario in matrix and scenario in drift_doc))

    return checks


def run_checks() -> list[Check]:
    return source_checks() + doc_checks()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Logging/Audit/FQL research drift.")
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
        print("FAIL logging/audit/FQL drift check")
        for failure in failures:
            print(f"- {failure.name}: {failure.path}")
    else:
        print(f"OK logging/audit/FQL drift check: {len(checks)} checks")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
