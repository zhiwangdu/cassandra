# Module: CQL Parser Raw Prepare Matrix

## 范围

本模块补齐 CQL Parser 到 raw statement prepare 的源码矩阵：ANTLR wrapper、`Cql.g` root rule、`Parser.g` statement dispatch、bind marker 收集、`QueryProcessor.parseStatement()` / `parseAndPrepare()`、SELECT/Modification/BATCH raw prepare 和测试覆盖。Prepared statement wire/id/cache 的更深兼容矩阵仍见 `research/module-prepared-statement-compatibility-matrix.md`。

当前源码基线：

- `CQLFragmentParser.parseAnyUnhandled()` 创建 `ErrorCollector`、`CqlLexer`、`CommonTokenStream`、`CqlParser`，并在 parse 后调用 `throwFirstSyntaxError()`，见 `src/java/org/apache/cassandra/cql3/CQLFragmentParser.java:63`。
- `Cql.g` 的 root `query` rule 要求一个 `cqlStatement` 加可选分号并到 `EOF`，见 `src/antlr/Cql.g:133`。
- `Parser.g` 的 `cqlStatement` 当前 dispatch 43 个 statement rule，并在 `@after` 把 parser 收集的 bind variables 写入 `CQLStatement.Raw`，见 `src/antlr/Parser.g:207`。
- Parser 阶段只构造 raw statement 和 `AbstractMarker.Raw`/`INRaw`/tuple/json markers；真实 receiver type 和 `ColumnSpecification` 在 prepare 阶段补齐，见 `src/antlr/Parser.g:28`、`src/java/org/apache/cassandra/cql3/AbstractMarker.java:42`、`src/java/org/apache/cassandra/cql3/VariableSpecifications.java:33`。
- `QueryProcessor.parseAndPrepare()` 在 parse 后设置 qualified keyspace、调用 `raw.prepare(clientState)` 和 `statement.validate(clientState)`，再测量 prepared entry size，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:441`。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `cql_parser_wrapper_error_collection` | `CQLFragmentParser` / `ErrorCollector` 的 lexer/parser error listener、snippet 和 first syntax error contract。 |
| `cql_parser_root_query_contract` | `Cql.g` root query rule：single `cqlStatement`、optional semicolons、`EOF`。 |
| `cql_parser_statement_dispatch` | `Parser.g` `cqlStatement` 的 43 个 statement dispatch entries。 |
| `cql_parser_bind_marker_collection` | positional/named/IN/tuple/json bind markers are collected during parse and attached to raw statement. |
| `cql_parser_raw_prepare_boundary` | parser only returns `CQLStatement.Raw`; schema/client-state validation happens in `raw.prepare()` and `validate()`。 |
| `cql_parser_select_prepare_planner_boundary` | `SelectStatement.RawStatement.prepare()` validates table, selection, restrictions, ordering, limits and filtering. |
| `cql_parser_modification_batch_prepare` | `ModificationStatement.Parsed` and `BatchStatement.Parsed` prepare attributes, conditions, restrictions and nested statements. |
| `cql_parser_keyword_identity_contract` | Lexer/parser identity keywords and `ADD/DROP IDENTITY` dispatch are part of the CQL grammar surface. |
| `cql_parser_test_coverage_surface` | Parser listener tests, duplicate property tests, prepared/custom-expression tests, PREPARE codec keyspace test and remaining generated grammar exhaustiveness gap. |

## Statement Dispatch Baseline

`cql_parser_statement_dispatch` 当前保护以下 43 个 `Parser.g` rule names：

| Group | Rules |
|---|---|
| Data | `selectStatement`、`insertStatement`、`updateStatement`、`batchStatement`、`deleteStatement`、`truncateStatement` |
| Session | `useStatement` |
| Schema | `createKeyspaceStatement`、`createTableStatement`、`createIndexStatement`、`dropKeyspaceStatement`、`dropTableStatement`、`dropIndexStatement`、`alterTableStatement`、`alterKeyspaceStatement`、`createTriggerStatement`、`dropTriggerStatement`、`createTypeStatement`、`alterTypeStatement`、`dropTypeStatement`、`createFunctionStatement`、`dropFunctionStatement`、`createAggregateStatement`、`dropAggregateStatement`、`createMaterializedViewStatement`、`dropMaterializedViewStatement`、`alterMaterializedViewStatement` |
| Auth / Permission | `grantPermissionsStatement`、`revokePermissionsStatement`、`listPermissionsStatement`、`createUserStatement`、`alterUserStatement`、`dropUserStatement`、`listUsersStatement`、`createRoleStatement`、`alterRoleStatement`、`dropRoleStatement`、`listRolesStatement`、`grantRoleStatement`、`revokeRoleStatement` |
| Introspection / Identity | `describeStatement`、`addIdentityStatement`、`dropIdentityStatement` |

Adding, removing or renaming any dispatch entry must update this matrix, tests and `research/tools/check-cql-parser-raw-prepare-drift.py` together.

## 调用图

```text
native QUERY/PREPARE text
  -> QueryProcessor.parseStatement(query)
     -> CQLFragmentParser.parseAnyUnhandled(CqlParser::query, query)
        -> ErrorCollector + CqlLexer + CqlParser
        -> Cql.g query
        -> Parser.g cqlStatement
           -> one Raw statement from statement dispatch
           -> @after stmt.setBindVariables(bindVariables)
        -> ErrorCollector.throwFirstSyntaxError()
  -> QueryProcessor.parseAndPrepare(query, clientState, isInternal, measure)
     -> if raw is QualifiedStatement: setKeyspace(clientState)
     -> raw.prepare(clientState)
        -> SelectStatement.RawStatement.prepare(...)
        -> ModificationStatement.Parsed.prepare(...)
        -> BatchStatement.Parsed.prepare(...)
        -> schema/auth/schema statement prepare variants
     -> statement.validate(clientState)
     -> QueryProcessor.Prepared(statement, raw CQL/keyspace/fullyQualified)
     -> optional measurePstmnt()
```

## 设计目标

- Keep grammar parsing separate from schema-aware validation so syntax can be recognized without opening table metadata.
- Make bind marker ordering stable from parser collection through `VariableSpecifications` and prepared metadata.
- Ensure parser recovery does not hide syntax errors that Cassandra will ignore anyway.
- Keep statement dispatch explicit so new CQL statement families are visible in research and tests.
- Preserve the current root query contract of one statement plus trailing semicolons and EOF.

## 解决的问题

- Parser-level grammar can accept constructs that only become invalid after schema/type/permission validation.
- Bind markers need stable indexes before receiver types are known.
- `SELECT json` / `SELECT distinct` ambiguity is resolved in grammar before raw prepare.
- Batch prepare must reuse a single bind-variable list across nested modification statements.
- Grammar changes can silently add CQL surface area unless statement dispatch and tests are tracked.

## 设计取舍

- ANTLR generated parser is wrapped by Cassandra-specific `CQLFragmentParser` and `ErrorCollector` rather than exposing raw ANTLR exceptions.
- `Parser.g` overrides recovery to avoid wasted work and duplicate misleading errors.
- `CQLStatement.Raw` carries `VariableSpecifications` only after `cqlStatement` completes; raw statement classes do not own marker collection individually.
- `QueryProcessor.parseAndPrepare()` accepts a race where two threads prepare the same query because prepared cache insertion is idempotent enough for this path.
- Prepared entry size is measured after raw prepare; parse-only paths avoid cache sizing.

## 核心类

| 类/文件 | 作用 |
|---|---|
| `src/antlr/Cql.g` | Root `query` rule and EOF/semicolon contract. |
| `src/antlr/Lexer.g` | Keyword token surface including permission and identity keywords. |
| `src/antlr/Parser.g` | Statement dispatch, bind marker collection and grammar recovery overrides. |
| `CQLFragmentParser` | Parser wrapper and syntax error conversion. |
| `src/java/org/apache/cassandra/cql3/ErrorCollector.java` / `ErrorCollector` | Error listener that records parser/lexer syntax errors and snippets. |
| `CQLStatement.Raw` | Parser output interface with attached `VariableSpecifications`. |
| `QueryProcessor` | `parseStatement()`、`getStatement()`、`parseAndPrepare()` boundary. |
| `AbstractMarker` / `VariableSpecifications` | Bind marker index/spec receiver bridge. |
| `SelectStatement.RawStatement` | SELECT raw prepare into selection/restrictions/limits/read planner input. |
| `ModificationStatement.Parsed` | INSERT/UPDATE/DELETE raw prepare into attributes/conditions/restrictions. |
| `BatchStatement.Parsed` | Batch raw prepare across nested modifications and batch attributes. |
| `research/tools/check-cql-parser-raw-prepare-drift.py` | Source-to-doc drift checker for this matrix. |

## 核心接口

- `CQLFragmentParser.CQLParserFunction<R>`：generated parser method callback。
- `CQLFragmentParser.parseAny()` / `parseAnyUnhandled()`：wrapped and unwrapped parser entrypoints。
- `CqlParser.query()`：generated root parser method from `Cql.g`。
- `CQLStatement.Raw.setBindVariables()` / `prepare(ClientState)`：parse result to executable statement boundary。
- `QueryProcessor.parseStatement()` / `parseAndPrepare()` / `getStatement()`：CQL text to executable statement boundary。
- `VariableSpecifications.add()` / `getBindVariables()` / `getPartitionKeyBindVariableIndexes()`：bind variable receiver metadata。

## 配置项

| 配置项 | Source | 语义 |
|---|---|---|
| `prepared_statements_cache_size` / `prepared_statements_cache_size_mb` | `src/java/org/apache/cassandra/config/Config.java`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java` | Prepared cache size; parse/raw prepare itself does not use this until prepared entry measurement/store. |
| `force_new_prepared_statement_behaviour` | `src/java/org/apache/cassandra/config/Config.java`、`src/java/org/apache/cassandra/cql3/QueryProcessor.java` | Prepared id behavior gate after raw prepare; detailed matrix in prepared compatibility docs. |

## Metrics

- Parser-only failures have no dedicated metric; they surface through query failure events and client errors.
- Prepared execution metrics (`PreparedStatementsExecuted` and friends) are updated after prepare/cache path, not by ANTLR parser itself.
- Parser/prepare CPU is paid for unprepared QUERY and PREPARE; EXECUTE reuses the prepared statement and only prepares options/bind values.

## 日志

- `QueryProcessor.parseStatement()` logs `The statement: [...] could not be parsed.` for runtime parse failures before throwing `SyntaxException`，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:933`。
- `ErrorCollector` emits enhanced syntax messages with snippet context when parser errors are collected.
- Prepared cache eviction warning belongs to `QueryProcessor` cache, not the parser layer.

## 运维关注点

- Syntax errors and invalid request errors have different root causes: syntax comes from lexer/parser; invalid request usually comes from `raw.prepare()` or `validate()`.
- A query may parse successfully but fail prepare because keyspace/table/type/function metadata is missing or incompatible.
- Adding a keyword can affect previously legal identifiers; update Lexer/Parser docs and parser tests together.
- Bind variable count/order errors are usually marker collection versus `QueryOptions.prepare()` mismatches; check `VariableSpecifications` and prepared metadata.

## 性能瓶颈

- Repeated unprepared QUERY pays ANTLR parse and raw prepare on every execution.
- PREPARE pays parser/raw prepare once, then stores measured prepared statement metadata.
- Complex SELECT restrictions, functions, UDFs and aggregations shift cost from parser into raw prepare and validation.
- Batch prepare walks nested modification statements and collects marker specs across all entries.

## 常见故障

- `SyntaxException` with snippet: parser/lexer rejected the text before schema-aware prepare.
- `Invalid query, must be a ... statement`: caller used `parseStatement(query, klass, type)` with a mismatched raw statement class.
- `Bind variables cannot be used for index names`: grammar/prepare explicitly rejects a marker in custom index expression name position.
- Missing keyspace/table errors after parse: `QualifiedStatement.setKeyspace()` or `Schema.instance.validateTable()` failed during prepare.
- New grammar rule parses but docs/checker fail: update the dispatch baseline and test coverage matrix.

## 测试用例

- `CqlParserTest.testAddErrorListener()` and `testRemoveErrorListener()` cover parser listener and no-recovery behavior，见 `test/unit/org/apache/cassandra/cql3/CqlParserTest.java:35`。
- `CqlParserTest.testDuplicateProperties()` covers parser-level duplicate property error collection，见 `test/unit/org/apache/cassandra/cql3/CqlParserTest.java:79`。
- `PreparedStatementsTest.prepareAndExecuteWithCustomExpressions()` covers prepared custom expression bind-marker boundary and the index-name marker rejection，见 `test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java:241`。
- `PrepareMessageTest.testEncodeThenDecode()` covers native PREPARE codec keyspace query string round-trip，见 `test/unit/org/apache/cassandra/transport/messages/PrepareMessageTest.java:29`。
- `cql_parser_test_coverage_surface`: existing tests cover parser listeners and selected prepare paths, but there is no generated exhaustiveness test that compares every `Parser.g` `cqlStatement` dispatch entry against a test matrix; the drift checker keeps that gap explicit.
