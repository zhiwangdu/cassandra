# Flow: CQL Request And Auth

## 目标

CQL request 链路解释 native protocol 请求如何进入 `QueryProcessor`，如何完成 parse/prepare、登录态与权限检查、statement validation，并最终进入读写或 schema 执行路径。

## 文字版调用图

普通 QUERY：

```text
native frame QUERY
  -> QueryMessage.codec.decode(...)
     -> query string + QueryOptions
  -> QueryMessage.execute(queryState, requestTime, trace)
     -> validate page size
     -> ClientState.getCQLQueryHandler()
     -> queryHandler.parse(query, state, options)
        -> QueryProcessor.parse(...)
           -> getStatement(query, clientState.cloneWithKeyspaceIfSet(options.keyspace))
              -> parseStatement(query)
                 -> CQLFragmentParser.parseAnyUnhandled(CqlParser::query, query)
              -> QualifiedStatement.setKeyspace(clientState)
              -> raw.prepare(clientState)
     -> queryHandler.process(statement, state, options, payload, requestTime)
        -> QueryProcessor.process(...)
           -> options.prepare(bind variables)
           -> metrics.regularStatementsExecuted++
           -> processStatement(...)
              -> statement.authorize(clientState)
              -> statement.validate(clientState)
              -> statement.execute(queryState, options, requestTime)
```

PREPARE/EXECUTE：

```text
native frame PREPARE
  -> PrepareMessage.execute(...)
     -> decode query and optional V5 keyspace flag
     -> clone ClientState with v5 keyspace if provided
     -> QueryProcessor.prepare(query, clientState)
        -> compute id with and without keyspace
        -> choose rolling-upgrade/new prepared behavior
        -> parseAndPrepare(...)
           -> parseStatement(...)
           -> raw.prepare(clientState)
           -> statement.validate(clientState)
        -> store prepared statement under one or two ids
        -> return ResultMessage.Prepared(statementId, resultMetadataId, metadata)

native frame EXECUTE
  -> ExecuteMessage.execute(...)
     -> decode statementId and optional V5 resultMetadataId
     -> handler.getPrepared(statementId)
     -> warn if unqualified prepared statement keyspace differs
     -> options.prepare(statement.bindVariables)
     -> QueryProcessor.processPrepared(...)
        -> verify marker/value count
        -> metrics.preparedStatementsExecuted++
        -> processStatement(...)
     -> set METADATA_CHANGED / NO_METADATA for rows response
```

AUTH_RESPONSE：

```text
native frame AUTH_RESPONSE
  -> AuthResponse.execute(queryState, requestTime, trace)
     -> ServerConnection.getSaslNegotiator(queryState)
     -> negotiator.evaluateResponse(token)
     -> if negotiator.isComplete()
        -> AuthenticatedUser user
        -> queryState.getClientState().login(user)
           -> user.canLogin()
           -> set ClientState.user
        -> ClientMetrics.markAuthSuccess()
        -> AuthSuccess
     -> else AuthChallenge
```

Statement examples：

```text
SELECT
  -> SelectStatement.authorize()
     -> SELECT on base table or view base table
     -> EXECUTE on functions
     -> UNMASK or SELECT_MASKED when querying masked restricted columns
  -> SelectStatement.execute()
     -> CL validateForRead()
     -> guardrail read CL
     -> getQuery(...)
     -> StorageProxy/local read path

INSERT/UPDATE/DELETE
  -> ModificationStatement.authorize()
     -> MODIFY on table
     -> SELECT if CAS
     -> SELECT base table + MODIFY views if materialized views exist
     -> EXECUTE on functions
  -> ModificationStatement.execute()
     -> CL validateForWrite/counter
     -> getMutations(...)
     -> StorageProxy.mutateWithTriggers(...)

DDL
  -> AlterSchemaStatement.authorize()
  -> AlterSchemaStatement.execute()
     -> Schema.transform(...)
```

## 关键源码锚点

| 阶段 | 文件/方法 |
|---|---|
| Query decode | `QueryMessage.codec`：`src/java/org/apache/cassandra/transport/messages/QueryMessage.java:44-77` |
| Query execute | `QueryMessage.execute()`：`src/java/org/apache/cassandra/transport/messages/QueryMessage.java:101-128` |
| Prepare decode/execute | `PrepareMessage.codec` / `execute()`：`src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:47-99`、`src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:117-130` |
| Execute decode/execute | `ExecuteMessage.codec` / `execute()`：`src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:54-104`、`src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:131-171` |
| Auth response | `AuthResponse.execute()`：`src/java/org/apache/cassandra/transport/messages/AuthResponse.java:72-98` |
| QueryProcessor cache init | `QueryProcessor` static cache：`src/java/org/apache/cassandra/cql3/QueryProcessor.java:93-120` |
| Statement parse | `QueryProcessor.getStatement()` / `parseStatement()`：`src/java/org/apache/cassandra/cql3/QueryProcessor.java:893-928` |
| Normal process | `QueryProcessor.process()`：`src/java/org/apache/cassandra/cql3/QueryProcessor.java:359-369` |
| Process statement | `QueryProcessor.processStatement()`：`src/java/org/apache/cassandra/cql3/QueryProcessor.java:266-279` |
| Parse and prepare | `QueryProcessor.parseAndPrepare()`：`src/java/org/apache/cassandra/cql3/QueryProcessor.java:441-470` |
| Prepare store | `QueryProcessor.prepare()`：`src/java/org/apache/cassandra/cql3/QueryProcessor.java:728-775` |
| Prepared process | `QueryProcessor.processPrepared()`：`src/java/org/apache/cassandra/cql3/QueryProcessor.java:851-870` |
| Batch process | `QueryProcessor.processBatch()`：`src/java/org/apache/cassandra/cql3/QueryProcessor.java:883-890` |
| Select authorization | `SelectStatement.authorize()`：`src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:242-270` |
| Select execution | `SelectStatement.execute()`：`src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:280-350` |
| Write authorization | `ModificationStatement.authorize()`：`src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:247-269` |
| Write execution | `ModificationStatement.execute()`：`src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:491-530` |
| Internal write | `ModificationStatement.executeInternalWithoutCondition()`：`src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:686-693` |
| CAS internal | `ModificationStatement.casInternal()`：`src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:706-726` |
| ClientState external/internal | `ClientState.forExternalCalls()` / `forInternalCalls()`：`src/java/org/apache/cassandra/service/ClientState.java:190-210` |
| Login | `ClientState.login()`：`src/java/org/apache/cassandra/service/ClientState.java:375-383` |
| Login validation | `ClientState.validateLogin()`：`src/java/org/apache/cassandra/service/ClientState.java:565-579` |
| Permission chain | `ClientState.ensurePermissionOnResourceChain()`：`src/java/org/apache/cassandra/service/ClientState.java:523-538` |
| System/auth protection | `ClientState.ensurePermission()`：`src/java/org/apache/cassandra/service/ClientState.java:451-503` |
| Permission/role matrix | resource permission sets、GRANT/REVOKE、role grant/revoke、LIST PERMISSIONS：`research/module-permission-role-matrix.md` |

## Auth 语义

- 如果 authenticator 不要求认证，external `ClientState` 初始化为 anonymous user，见 `src/java/org/apache/cassandra/service/ClientState.java:171-177`。
- `IAuthenticator` 的 SASL negotiator 是每次认证一个新实例，接口说明见 `src/java/org/apache/cassandra/auth/IAuthenticator.java:70-99`。
- `PasswordAuthenticator` 从 `system_auth.roles` 读取 bcrypt salted hash，并要求使用 `CassandraRoleManager`，见 `src/java/org/apache/cassandra/auth/PasswordAuthenticator.java:53-60`、`src/java/org/apache/cassandra/auth/PasswordAuthenticator.java:87-109`。
- `ClientState.ensurePermission()` 在 authorizer 不要求授权时直接放行；否则沿 resource chain 检查，并对 system keyspace、auth protected resources 做额外保护，见 `src/java/org/apache/cassandra/service/ClientState.java:475-503`。
- `Roles.canLogin()` 只看 primary role 自身的 login bit，不继承，见 `src/java/org/apache/cassandra/auth/Roles.java:109-130`。
- resource permission 矩阵由 `DataResource`、`FunctionResource`、`RoleResource` 和 `JMXResource` 自己声明；role grant/revoke 与 permission grant/revoke 分别落到 role manager 和 authorizer，完整矩阵见 `research/module-permission-role-matrix.md`。

## Prepared Statement 语义

- Prepared cache 是 Caffeine weighted cache，容量来自 `prepared_statements_cache_size`，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:106-120`。
- 非 fully qualified statement 会保存 keyspace-sensitive id；`ExecuteMessage` 发现当前 keyspace 与 prepared keyspace 不一致时只 warn/error，不重写 statement，见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:141-152`。
- Schema 改变可能导致 prepared invalidation；`QueryProcessor` 构造时注册 listener，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:227-230`。
- ALTER TABLE 是否影响 prepared statements 由 `TableMetadata.changeAffectsPreparedStatements()` 判定，见 `src/java/org/apache/cassandra/schema/TableMetadata.java:661-670`。

## 排查路径

1. Parse/prepare 失败：从 native message 的 `QueryEvents.notify*Failure` 找 query 和 exception，再看 `QueryProcessor.parseStatement()` 是否抛 Syntax/InvalidRequest。
2. `Invalid amount of bind variables`：普通 query/prepared query 都会在 `QueryProcessor` 校验 marker/value 数，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:359-369`、`src/java/org/apache/cassandra/cql3/QueryProcessor.java:851-870`。
3. `PreparedQueryNotFoundException`：看 prepared cache eviction、schema invalidation、driver 是否处理 reprepare，入口见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:136-140`。
4. Unauthorized：先确认是否登录，再看具体 statement 的 `authorize()` 要求的是 SELECT/MODIFY/ALTER/DROP/EXECUTE/UNMASK 哪一种权限。
5. 系统表或 auth 表 DDL 失败：检查 `ClientState.preventSystemKSSchemaModification()` 和 protected auth resources，见 `src/java/org/apache/cassandra/service/ClientState.java:544-563`。
6. NODE_LOCAL 查询异常：`QueryProcessor.processNodeLocalStatement()` 要求 system property 启用，并仅支持 BATCH/UPDATE/INSERT/DELETE/SELECT，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:281-334`。

## 测试用例

- `test/unit/org/apache/cassandra/cql3/CqlParserTest.java`
- `test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java`
- `test/unit/org/apache/cassandra/cql3/QueryEventsTest.java`
- `test/unit/org/apache/cassandra/cql3/validation/operations/SelectTest.java`
- `test/unit/org/apache/cassandra/cql3/validation/operations/InsertTest.java`
- `test/unit/org/apache/cassandra/cql3/validation/operations/UpdateTest.java`
- `test/unit/org/apache/cassandra/cql3/validation/operations/BatchTest.java`
- `test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java`
- `test/unit/org/apache/cassandra/auth/PasswordAuthenticatorTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/AuthTest.java`
