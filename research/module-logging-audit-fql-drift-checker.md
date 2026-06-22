# Module: Logging Audit FQL Drift Checker

## 目的

`research/tools/check-logging-audit-fql-drift.py` 是 Logging/Audit/FQL operations matrix 的源码漂移检查器。它读取当前 checkout 的源码、配置、测试和 `research/` 文档，确保 logging 运行面没有因为源码变化而让研究材料变旧。

## 覆盖范围

检查器覆盖以下场景 ID：

- `logging_ops_logback_file_appenders`
- `logging_ops_dynamic_level_jmx_nodetool`
- `logging_ops_logback_support_boundary`
- `logging_ops_virtual_table_buffer`
- `logging_ops_audit_options_defaults_filters`
- `logging_ops_audit_listener_lifecycle`
- `logging_ops_audit_nodetool_archive_gate`
- `logging_ops_fql_enable_reset_payload`
- `logging_ops_fql_nodetool_archive_gate`
- `logging_ops_binlog_backpressure_archiver`
- `logging_ops_external_collection_gap`

## 源码锚点

- logback/runtime levels：`conf/logback.xml`、`conf/logback-tools.xml`、`src/java/org/apache/cassandra/utils/logging/LoggingSupportFactory.java`、`src/java/org/apache/cassandra/utils/logging/LogbackLoggingSupport.java`、`src/java/org/apache/cassandra/tools/nodetool/SetLoggingLevel.java`、`src/java/org/apache/cassandra/tools/nodetool/GetLoggingLevels.java`
- virtual log table：`src/java/org/apache/cassandra/utils/logging/VirtualTableAppender.java`、`src/java/org/apache/cassandra/db/virtual/LogMessagesTable.java`
- audit：`src/java/org/apache/cassandra/audit/AuditLogOptions.java`、`src/java/org/apache/cassandra/audit/AuditLogManager.java`、`src/java/org/apache/cassandra/audit/BinAuditLogger.java`、`src/java/org/apache/cassandra/audit/FileAuditLogger.java`
- FQL：`src/java/org/apache/cassandra/fql/FullQueryLoggerOptions.java`、`src/java/org/apache/cassandra/fql/FullQueryLogger.java`
- shared binlog：`src/java/org/apache/cassandra/utils/binlog/BinLog.java`、`BinLogOptions.java`、`DeletingArchiver.java`、`ExternalArchiver.java`
- JMX/nodetool/config：`src/java/org/apache/cassandra/service/StorageService.java`、`StorageServiceMBean.java`、`src/java/org/apache/cassandra/tools/NodeProbe.java`、`conf/cassandra.yaml`
- Tests：`LogMessagesTableTest`、`VirtualTableLogsTest`、`AuditLoggerTest`、`AuditLoggerAuthTest`、`GetAuditLogTest`、`FullQueryLoggerTest`、`GetFullQueryLogTest`

## 运行方式

```bash
python3 research/tools/check-logging-audit-fql-drift.py
```

成功时输出类似：

```text
OK logging/audit/FQL drift check: N checks
```

失败时会列出缺失的 source token、doc token 或 gap 状态变化。若将来仓库加入外部日志 collector 配置，检查器会提示更新 `logging_ops_external_collection_gap`。

## 不覆盖

- 不启动 Cassandra，也不验证实际 logback rolling 文件内容。
- 不执行 archive command。
- 不验证部署侧日志采集器、SIEM、对象存储归档或保留策略。
