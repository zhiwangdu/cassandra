# Schema/CQL/Auth/Native 第三轮源码研究

## 范围

本文补齐 Schema/CQL/Auth/Native 第二轮之后的源码缺口：CQL grammar 到 raw prepare/cache、native TLS certificate hot reload、mTLS identity mapping 与 password fallback、native protocol tracing/warnings/custom payload flag 矩阵，以及普通 virtual table 的 CQL planner/read command/filter/paging 边界。

已有主线文档保留：`research/module-schema-cql-auth.md` 覆盖 QueryProcessor/schema/auth 基础链路，`research/module-schema-cql-auth-native-deep-dive.md` 覆盖 UDF/UDA、system/auth/system_distributed 表、grant/revoke/list、默认 auth backend、native frames/large-message/custom payload 基础行为，`research/flow-cql-request.md` 与 `research/flow-schema-change.md` 覆盖请求和 schema change 调用图。

## 设计目标

- CQL grammar 目标是把文本 CQL 解析为只包含语法结构和原始 term/marker 的 `CQLStatement.Raw`，再由 `raw.prepare()` 在当前 schema/client state 下完成 keyspace、table、type、restriction、bind variable spec 和 statement validation。入口见 `src/java/org/apache/cassandra/cql3/CQLFragmentParser.java:29-83`、`src/antlr/Parser.g:203-253`、`src/java/org/apache/cassandra/cql3/QueryProcessor.java:441-470`。
- Prepared statement 目标是在协议层返回稳定 statement id 与 result metadata id，同时避免不同 keyspace 下的非 fully-qualified statement 混淆。`QueryProcessor.prepare()` 同时计算带 keyspace 和不带 keyspace的 MD5，并按 fully-qualified/legacy 行为存两种 cache entry，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:728-790`。
- TLS hot reload 目标是不重启节点即可让新连接使用新的 SSL context，并在证书文件损坏时保留旧 context。`SSLFactory.checkCachedContextsForReload()` 先验证新 context，再清除对应 cache key，失败只记录错误，见 `src/java/org/apache/cassandra/security/SSLFactory.java:175-243`。
- mTLS 目标是把 TLS client certificate 的身份映射到 Cassandra role。`ServerConnection` 从 Netty `SslHandler` 取 peer certificates，`MutualTlsAuthenticator` 用 validator 抽取 identity，再通过 role manager/identity cache 找 role，见 `src/java/org/apache/cassandra/transport/ServerConnection.java:116-145` 与 `src/java/org/apache/cassandra/auth/MutualTlsAuthenticator.java:150-208`。
- Virtual table planner 目标是复用 CQL SELECT 的 restriction/filter/paging 机制，但在 read command execute 时转到 `VirtualTable.select()`，避免 StorageProxy replica read。关键路径见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:1206-1267`、`src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:1295-1320`、`src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java:553-565`。

## 解决的问题

- Parser 与 prepare 分层解决了语法可解析但 schema/type 不合法的问题：ANTLR 只构造 raw statement 和 bind marker，`raw.prepare()` 才能基于 `ClientState` 和 `Schema` 验证真实 table/type/function。marker 收集见 `src/antlr/Parser.g:28-73`，prepare 分层见 `src/java/org/apache/cassandra/cql3/CQLStatement.java:94-106`。
- Keyspace-sensitive prepared id 解决了同一 CQL 在不同 keyspace 下语义不同的问题；同时保留旧 id 以支持滚动升级期间的 pre-4.0.2 行为，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:728-790`。
- TLS hot reload 解决了证书轮换必须重启的问题；但只影响后续创建的 Netty SSL contexts，现有连接不会被强制重握手，cache 清理语义见 `src/java/org/apache/cassandra/security/SSLFactory.java:224-243`。
- mTLS identity table 解决了 certificate identity 到 Cassandra role 的授权映射问题，表定义在 `system_auth.identity_to_role`，见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:82-90`。
- Protocol extra flags 解决了 tracing、warnings 和 custom payload 与 message body 的兼容问题。flags 在 `Message.encode()` 外层写入，在 `Message.Decoder.decodeMessage()` 外层读取，并对 protocol v4 以下 custom payload 做拒绝，见 `src/java/org/apache/cassandra/transport/Message.java:331-389` 与 `src/java/org/apache/cassandra/transport/Message.java:430-463`。
- Virtual table read path 解决了虚拟系统视图使用普通 CQL 查询的问题，同时把 provider 成本暴露在 `data()`、`data(partitionKey)` 和 `allowFilteringImplicitly()` 的实现选择上，见 `src/java/org/apache/cassandra/db/virtual/VirtualTable.java:31-90` 与 `src/java/org/apache/cassandra/db/virtual/AbstractVirtualTable.java:44-127`。

## 设计取舍

- Grammar 选择 ANTLR 生成 parser/lexer，Cassandra 自己覆盖 parser recovery，使错误不被 ANTLR 自动吞掉；测试确认 mismatched token 只报一次，见 `src/antlr/Parser.g:170-199` 与 `test/unit/org/apache/cassandra/cql3/CqlParserTest.java:40-90`。
- Bind marker 在 parser 阶段只记录 index/name，具体 receiver type 在 term/restriction/selection prepare 时补齐。这样支持 named/positional marker、IN marker、tuple marker、JSON marker，但错误要等 prepare 才能暴露，见 `src/antlr/Parser.g:28-73`、`src/java/org/apache/cassandra/cql3/AbstractMarker.java:42-75`、`src/java/org/apache/cassandra/cql3/VariableSpecifications.java:25-86`。
- Prepared cache 以 Caffeine weighted cache 存 executable statement，容量来自 `prepared_statements_cache_size`；过大 statement 被拒绝，schema/table/function 变化会删除受影响 entry，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:106-136`、`src/java/org/apache/cassandra/cql3/QueryProcessor.java:805-839`、`src/java/org/apache/cassandra/cql3/QueryProcessor.java:975-1025`。
- Hot reload 只清理 SSL context cache，而不是在线替换 channel 里的 `SslHandler`。这避免打断已有连接，代价是证书轮换验证需要新连接或手动 reload 后的 context creation 才能观察，见 `src/java/org/apache/cassandra/security/SSLFactory.java:175-243`。
- `MutualTlsWithPasswordFallbackAuthenticator` 只有在没有 client certificate chain 时才回退 password；只要提供证书，就走 mTLS negotiator，见 `src/java/org/apache/cassandra/auth/MutualTlsWithPasswordFallbackAuthenticator.java:22-52`。
- Virtual table 默认允许 implicit filtering，这是为了让系统视图更容易查询；具体表可以覆盖为 false，让普通 CQL 的 ALLOW FILTERING 保护重新生效，见 `src/java/org/apache/cassandra/db/virtual/VirtualTable.java:81-90` 与 `src/java/org/apache/cassandra/cql3/restrictions/StatementRestrictions.java:360-367`。

## 核心类

- `src/antlr/Parser.g`、`src/antlr/Lexer.g`、`src/java/org/apache/cassandra/cql3/CQLFragmentParser.java`：ANTLR grammar、keyword token 和 parser wrapper。`cqlStatement` 的 `@after` 把 parser 收集的 bindVariables 写回 raw statement，见 `src/antlr/Parser.g:203-253`。
- `src/java/org/apache/cassandra/cql3/CQLStatement.java` 与 `src/java/org/apache/cassandra/cql3/statements/QualifiedStatement.java`：Raw statement prepare contract 和 keyspace resolution contract，见 `src/java/org/apache/cassandra/cql3/CQLStatement.java:94-106` 与 `src/java/org/apache/cassandra/cql3/statements/QualifiedStatement.java:27-66`。
- `src/java/org/apache/cassandra/cql3/QueryProcessor.java`：parse/prepare/process/prepared cache/schema invalidation 中枢。核心路径见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:441-470`、`src/java/org/apache/cassandra/cql3/QueryProcessor.java:728-839`、`src/java/org/apache/cassandra/cql3/QueryProcessor.java:851-870`。
- `src/java/org/apache/cassandra/transport/messages/PrepareMessage.java`、`src/java/org/apache/cassandra/transport/messages/QueryMessage.java`、`src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java`、`src/java/org/apache/cassandra/transport/messages/BatchMessage.java`：traceable/trackable native requests，custom payload 传入 query handler，见 `src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:112-145`、`src/java/org/apache/cassandra/transport/messages/QueryMessage.java:90-128`、`src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:119-180`、`src/java/org/apache/cassandra/transport/messages/BatchMessage.java:161-185`。
- `src/java/org/apache/cassandra/security/SSLFactory.java`、`src/java/org/apache/cassandra/config/EncryptionOptions.java`、`src/java/org/apache/cassandra/tools/ReloadSslCertificates.java`：SSL context cache、factory initialization、hot reload scheduler 和 nodetool reload entry，见 `src/java/org/apache/cassandra/security/SSLFactory.java:133-170`、`src/java/org/apache/cassandra/security/SSLFactory.java:175-285`、`src/java/org/apache/cassandra/tools/ReloadSslCertificates.java:25-38`。
- `src/java/org/apache/cassandra/auth/MutualTlsAuthenticator.java`、`src/java/org/apache/cassandra/auth/MutualTlsWithPasswordFallbackAuthenticator.java`、`src/java/org/apache/cassandra/auth/SpiffeCertificateValidator.java`：client mTLS authenticator、password fallback、SPIFFE SAN identity extraction，见 `src/java/org/apache/cassandra/auth/MutualTlsAuthenticator.java:62-121`、`src/java/org/apache/cassandra/auth/MutualTlsWithPasswordFallbackAuthenticator.java:22-52`、`src/java/org/apache/cassandra/auth/SpiffeCertificateValidator.java:47-89`。
- `src/java/org/apache/cassandra/cql3/statements/AddIdentityStatement.java`、`src/java/org/apache/cassandra/cql3/statements/DropIdentityStatement.java`、`src/java/org/apache/cassandra/auth/CassandraRoleManager.java`：identity mapping CQL 与默认 role manager persistence，见 `src/java/org/apache/cassandra/cql3/statements/AddIdentityStatement.java:36-85`、`src/java/org/apache/cassandra/cql3/statements/DropIdentityStatement.java:36-96`、`src/java/org/apache/cassandra/auth/CassandraRoleManager.java:176-230`。
- `src/java/org/apache/cassandra/db/virtual/VirtualTable.java`、`src/java/org/apache/cassandra/db/virtual/AbstractVirtualTable.java`、`src/java/org/apache/cassandra/db/virtual/VirtualKeyspaceRegistry.java`：virtual table provider API、default dataset adapter 和 registry，见 `src/java/org/apache/cassandra/db/virtual/VirtualTable.java:31-90`、`src/java/org/apache/cassandra/db/virtual/AbstractVirtualTable.java:44-127`、`src/java/org/apache/cassandra/db/virtual/VirtualKeyspaceRegistry.java:30-80`。

## 核心接口

- `CQLStatement.Raw.prepare(ClientState)`：raw-to-executable statement 的统一接口，见 `src/java/org/apache/cassandra/cql3/CQLStatement.java:94-106`。
- `QueryHandler.prepare/process/processPrepared/processBatch`：native request 与 QueryProcessor/custom query handler 的接口，custom payload 参数通过这里传递，调用点见 `src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:117-145` 与测试 handler 见 `test/unit/org/apache/cassandra/transport/MessagePayloadTest.java:390-460`。
- `IAuthenticator.newSaslNegotiator(InetAddress, Certificate[])`：mTLS authenticator 接收 peer certificate chain 的扩展接口，见 `src/java/org/apache/cassandra/auth/IAuthenticator.java:84-99` 与 `src/java/org/apache/cassandra/transport/ServerConnection.java:116-145`。
- `MutualTlsCertificateValidator`：抽取 certificate identity 并验证 certificate chain 的接口，SPIFFE 实现见 `src/java/org/apache/cassandra/auth/SpiffeCertificateValidator.java:47-89`。
- `IRoleManager.roleForIdentity/authorizedIdentities/addIdentity/dropIdentity`：mTLS identity 表与 role manager 的接口，见 `src/java/org/apache/cassandra/auth/IRoleManager.java:232-285`。
- `VirtualTable.select(partitionKey, filter, columns)` 与 `VirtualTable.select(dataRange, columns)`：single-partition 与 range virtual read 的 provider 接口，见 `src/java/org/apache/cassandra/db/virtual/VirtualTable.java:55-74`。

## 核心数据结构

- `Parser.bindVariables`：parser 全局收集 marker name/index，`cqlStatement` 结束时写入 raw statement，见 `src/antlr/Parser.g:28-73` 与 `src/antlr/Parser.g:203-253`。
- `VariableSpecifications`：prepared statement 的 bind variable column specs、named marker receiver 和 partition-key marker indexes，见 `src/java/org/apache/cassandra/cql3/VariableSpecifications.java:25-86`。
- `QueryProcessor.Prepared`：保存 executable statement、raw CQL、fullyQualified flag、keyspace 和 measured cache size，使用点见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:441-470` 与 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:805-839`。
- `ResultSet.PreparedMetadata` 与 `ResultSet.ResultMetadata`：native PREPARED response 的 bind metadata/result metadata 和 result metadata id，创建见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:812-837`。
- `Envelope.Header.Flag.TRACING`、`WARNING`、`CUSTOM_PAYLOAD`、`USE_BETA`：native protocol extra flag。request tracing/custom payload 和 response tracing/warnings/custom payload 都在 `Message.encode/decodeMessage()` 处理，见 `src/java/org/apache/cassandra/transport/Message.java:331-389` 与 `src/java/org/apache/cassandra/transport/Message.java:430-463`。
- `system_auth.identity_to_role`：identity 到 role 的 mTLS 授权表，schema 为 `identity text PRIMARY KEY, role text`，见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:82-90`。
- `MutualTlsAuthenticator.IdentityCache`：基于 credentials cache 配置的 identity-to-role loading cache，loader 调用 `DatabaseDescriptor.getRoleManager().roleForIdentity(identity)`，见 `src/java/org/apache/cassandra/auth/MutualTlsAuthenticator.java:189-207`。
- `AbstractVirtualTable.DataSet`、`Partition`：virtual table provider 把任意内存/运行时状态投影为 partition/row iterator 的适配结构，见 `src/java/org/apache/cassandra/db/virtual/AbstractVirtualTable.java:129-176`。

## 生命周期

CQL parse/prepare 生命周期：

1. `QueryMessage` 或 `PrepareMessage` 进入 query handler。普通 query 先 `parse()` 再 `process()`，prepare 直接 `prepare()`，见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:101-128` 与 `src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:117-145`。
2. `QueryProcessor.parseStatement()` 通过 `CQLFragmentParser.parseAnyUnhandled(CqlParser::query, query)` 调用 generated parser，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:893-940`。
3. Parser 根据 grammar 生成 raw statement，并把 `?`、`:name`、IN/tuple/JSON marker 写到 `bindVariables`，见 `src/antlr/Parser.g:28-73` 与 `src/antlr/Parser.g:203-253`。
4. `parseAndPrepare()` 对 `QualifiedStatement` 解析 keyspace，调用 `raw.prepare(clientState)` 和 `statement.validate(clientState)`，然后构造 `Prepared`，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:441-470`。
5. `prepare()` 按 fully-qualified 与 current keyspace 存 prepared cache；`EXECUTE` 取出 statement 后用 `options.prepare(statement.getBindVariables())` 补齐 bind 值/spec 并执行，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:728-839` 与 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:131-180`。

TLS/mTLS 生命周期：

1. 启动应用 config 时，`DatabaseDescriptor.applySslContext()` 校验 internode/native SSL context 并初始化 hot reload scheduler，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1268-1280`。
2. `SSLFactory.initHotReloading()` 调用 server/client ssl context factory 的 `initHotReloading()`，并定时调 `checkCertFilesForHotReloading()`，见 `src/java/org/apache/cassandra/security/SSLFactory.java:250-285`。
3. 定时或 nodetool `reloadssl` 调用会检查 cached SSL contexts；如果 factory `shouldReload()` 或 force reload 为 true，则先创建/验证新 context，成功才清 cache，见 `src/java/org/apache/cassandra/security/SSLFactory.java:175-243`、`src/java/org/apache/cassandra/tools/NodeProbe.java:2348-2355`、`src/java/org/apache/cassandra/net/MessagingServiceMBeanImpl.java:272-280`。
4. Native auth 阶段，`AuthResponse.execute()` 从 `ServerConnection` 取得 SASL negotiator；ServerConnection 从 pipeline 的 `ssl` handler 取 peer certificates 并传给 authenticator，见 `src/java/org/apache/cassandra/transport/messages/AuthResponse.java:72-98` 与 `src/java/org/apache/cassandra/transport/ServerConnection.java:116-145`。
5. mTLS negotiator 校验证书、抽取 identity、查 identity cache/role manager，成功返回 `AuthenticatedUser(role)`；fallback authenticator 在无证书时走 password negotiator，见 `src/java/org/apache/cassandra/auth/MutualTlsAuthenticator.java:150-208` 与 `src/java/org/apache/cassandra/auth/MutualTlsWithPasswordFallbackAuthenticator.java:45-52`。

Virtual table read 生命周期：

1. `SelectStatement.RawStatement.prepare()` 获取 `TableMetadata`，构建 selection、restrictions、aggregation、limits，并调用 `checkNeedsFiltering()`，见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:1206-1267`。
2. `SelectStatement.execute()` 用普通 CQL read planner 构造 single-partition group 或 range command，并选择 no-pager 或 pager execution，见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:280-360`。
3. 如果 metadata 是 virtual table，single-partition group 使用 `VirtualTableGroup`，range command 和 single partition command 的 `executeLocally()` 都从 `VirtualKeyspaceRegistry` 找 provider 并调用 `select()`，见 `src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:1295-1320`、`src/java/org/apache/cassandra/db/SinglePartitionReadCommand.java:1413-1426`、`src/java/org/apache/cassandra/db/PartitionRangeReadCommand.java:553-565`。
4. `AbstractVirtualTable` 默认把 provider 的 `DataSet` 转成 `UnfilteredPartitionIterator`，再套 row filter、data limits 和 paging，见 `src/java/org/apache/cassandra/db/virtual/AbstractVirtualTable.java:68-127`。

## 调用链

CQL raw prepare：

```text
PrepareMessage.execute
  -> QueryHandler.prepare(query, clientState, customPayload)
  -> QueryProcessor.prepare
  -> QueryProcessor.parseAndPrepare
  -> QueryProcessor.parseStatement
  -> CQLFragmentParser.parseAnyUnhandled(CqlParser::query)
  -> Parser.cqlStatement
  -> raw.setBindVariables(bindVariables)
  -> QualifiedStatement.setKeyspace(clientState)
  -> raw.prepare(clientState)
  -> statement.validate(clientState)
  -> QueryProcessor.storePreparedStatement
```

mTLS login：

```text
AuthResponse.execute
  -> ServerConnection.getSaslNegotiator(queryState)
  -> ServerConnection.certificates()
  -> IAuthenticator.newSaslNegotiator(clientAddress, certificates)
  -> MutualTlsAuthenticator.CertificateNegotiator.getAuthenticatedUser
  -> MutualTlsCertificateValidator.isValidCertificate / identity
  -> IdentityCache.get(identity)
  -> CassandraRoleManager.roleForIdentity(identity)
  -> ClientState.login(AuthenticatedUser(role))
```

Virtual table SELECT：

```text
SelectStatement.RawStatement.prepare
  -> StatementRestrictions(...)
  -> checkNeedsFiltering(table, restrictions)
  -> SelectStatement.execute
  -> getQuery(...)
  -> SinglePartitionReadQuery.createGroup / PartitionRangeReadQuery.create
  -> command.executeLocally(ReadExecutionController.empty())
  -> VirtualKeyspaceRegistry.getTableNullable(tableId)
  -> VirtualTable.select(...)
  -> rowFilter + limits + pager
```

## 配置项

- `prepared_statements_cache_size` 控制 prepared cache 容量，定义见 `src/java/org/apache/cassandra/config/Config.java:584-585` 与 `conf/cassandra.yaml:508`。
- `authenticator` 可配置 `MutualTlsAuthenticator` 或 `MutualTlsWithPasswordFallbackAuthenticator`，`validator_class_name` 示例在 YAML 注释中，见 `conf/cassandra.yaml:193-205`。
- mTLS client auth 需要 `client_encryption_options.enabled=true` 和 `require_client_auth=true`；`MutualTlsAuthenticator` 启动时强制检查，见 `conf/cassandra.yaml:1688-1730` 与 `src/java/org/apache/cassandra/auth/MutualTlsAuthenticator.java:180-186`。
- `client_encryption_options.ssl_context_factory` 决定 SSL context factory；`EncryptionOptions.applyConfig()` 初始化 factory instance，见 `conf/cassandra.yaml:1705-1714` 与 `src/java/org/apache/cassandra/config/EncryptionOptions.java:216-307`。
- credentials cache 参数也被 mTLS identity cache 复用：`credentials_validity`、`credentials_update_interval`、`credentials_cache_max_entries`、`credentials_cache_active_update`，identity cache 构造见 `src/java/org/apache/cassandra/auth/MutualTlsAuthenticator.java:189-207`。
- `native_transport_port_ssl` 是 deprecated dual port；如果 client encryption 未启用会配置失败，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:921-936`。

## Metrics

- Prepared statement execution 由 `QueryProcessor.metrics.regularStatementsExecuted` 与 `preparedStatementsExecuted` 计数，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:359-369` 与 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:851-870`。
- Prepared statement eviction 由 cache removal listener 更新 `preparedStatementsEvicted`，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:113-136`。
- Native authentication 成功/失败在 `AuthResponse.execute()` 中更新 `ClientMetrics.markAuthSuccess()` 与 `markAuthFailure()`，见 `src/java/org/apache/cassandra/transport/messages/AuthResponse.java:72-98`。
- mTLS identity cache 注册到 `AuthCacheService`，可按 auth cache/MBean/virtual table 路径观察 cache keys；注册点见 `src/java/org/apache/cassandra/auth/MutualTlsAuthenticator.java:71-88` 与 cache 定义见 `src/java/org/apache/cassandra/auth/MutualTlsAuthenticator.java:189-207`。
- Native request backpressure 和 warnings 与 request tracking 相关；traceable/trackable request 包括 QUERY、EXECUTE、BATCH，PREPARE traceable 但不 track warnings，见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:90-101`、`src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:119-130`、`src/java/org/apache/cassandra/transport/messages/BatchMessage.java:161-172`、`src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:112-116`。

## 日志

- Parse failure 会在 `QueryProcessor.parseStatement()` 记录 statement 和 exception 后抛 `SyntaxException`，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:893-940`。
- Query/prepare/execute/batch 成功与失败通过 `QueryEvents` 通知；入口分别在 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:101-128`、`src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:117-145`、`src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:131-180`。
- SSL hot reload 成功会记录 certificates updated 并重置 context cache；失败会记录 “Failed to hot reload the SSL Certificates” 且保留旧 context，见 `src/java/org/apache/cassandra/security/SSLFactory.java:197-220`。
- mTLS 无法抽取 identity、identity 未授权或 certificate 不支持时用 no-spam logger 记录错误并抛 `AuthenticationException`，见 `src/java/org/apache/cassandra/auth/MutualTlsAuthenticator.java:150-177`。
- Response warnings 如果出现在 protocol v3 或更低会被记录为 server warning 并丢弃；custom payload 在低版本则直接 `ProtocolException`，见 `src/java/org/apache/cassandra/transport/Message.java:345-363`。

## 运维关注点

- 修改 CQL grammar 后要同时关注 parser rule、raw statement prepare、CQL docs 和 parser tests。新增 ADD/DROP IDENTITY 同时触及 lexer keyword、parser statement dispatch、statement implementation、role manager persistence 和 permissions tests，见 `src/antlr/Lexer.g:104-160`、`src/antlr/Parser.g:1238-1275`、`test/unit/org/apache/cassandra/cql3/statements/AddIdentityStatementTest.java:85-190`、`test/unit/org/apache/cassandra/cql3/statements/DropIdentityStatementTest.java:75-155`。
- Prepared statement cache 太小会导致 driver reprepare；schema alter/drop/function change 会主动 invalidation，相关测试覆盖 schema change 后 `PreparedQueryNotFoundException`，见 `test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java:280-380`。
- 证书 reload 是新连接生效模型。使用 `nodetool reloadssl` 只能强制检查和清 cache，不会重启 native transport 或关闭旧连接，入口见 `src/java/org/apache/cassandra/tools/ReloadSslCertificates.java:25-38`。
- mTLS 上线要先把身份写入 `system_auth.identity_to_role`，再启用 client certificate auth；文档示例和 CQL 语法见 `doc/modules/cassandra/pages/getting-started/mtlsauthenticators.adoc:29-67` 与 `doc/modules/cassandra/pages/developing/cql/cql_singlefile.adoc:2382-2421`。
- password fallback 模式适合迁移期，但一旦客户端提供证书就不会尝试 password fallback；无证书或空证书链才回退，见 `src/java/org/apache/cassandra/auth/MutualTlsWithPasswordFallbackAuthenticator.java:45-52`。
- Virtual table provider 要小心 `data()` 全量构造成本。range query、filter、count 和 paging 都可能先构造 provider dataset，再由 row filter/limits 裁剪，默认实现见 `src/java/org/apache/cassandra/db/virtual/AbstractVirtualTable.java:68-127`。

## 性能瓶颈

- Parser/prepare CPU 在每次 unprepared QUERY 或 PREPARE 时发生；prepared EXECUTE 只做 bind count/spec 校验和 statement execution，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:441-470` 与 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:851-870`。
- Prepared cache entry 会深度测量对象大小；很大的 statement 被拒绝以保护 cache，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:468-470` 与 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:817-826`。
- TLS reload 的验证会创建 Netty SSL contexts，代价较高；cache 的目的正是避免频繁重建，见 `src/java/org/apache/cassandra/security/SSLFactory.java:52-56` 与 `src/java/org/apache/cassandra/security/SSLFactory.java:133-170`。
- mTLS cache miss 会读取 `system_auth.identity_to_role`，再受 credentials cache TTL/active update 影响；role manager 查询见 `src/java/org/apache/cassandra/auth/CassandraRoleManager.java:176-230`。
- Virtual table single partition provider 可重写 `data(partitionKey)` 减少全量 dataset 构造；未重写时仍调用 `data()`，见 `src/java/org/apache/cassandra/db/virtual/AbstractVirtualTable.java:57-76`。
- Protocol custom payload 会随 request/response body 额外编码 byte map；低版本拒绝会关闭或错误响应，测试覆盖 v3 拒绝，见 `test/unit/org/apache/cassandra/transport/MessagePayloadTest.java:265-365`。

## 常见故障

- `SyntaxException`：ANTLR parser 或 error collector 报错，先看 `QueryProcessor.parseStatement()` 和 `CqlParser` error listener，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:893-940` 与 `src/java/org/apache/cassandra/cql3/CQLFragmentParser.java:61-83`。
- `Invalid amount of bind variables`：EXECUTE 的 values 数与 prepared bind specs 不一致，检查 `statement.getBindVariables()` 与 `QueryOptions.prepare()`，见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:131-180` 与 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:851-870`。
- Prepared id 在不同 keyspace 下行为异常：非 fully-qualified prepared statement 依赖当前 keyspace，ExecuteMessage 会 warn/error，但不会重写 statement，见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:141-152`。
- `Failed to hot reload the SSL Certificates`：新证书/keystore/truststore 验证失败，旧 context 会保留；失败测试见 `test/unit/org/apache/cassandra/security/SSLFactoryTest.java:232-282`。
- `MutualTlsAuthenticator requires client_encryption_options.enabled...`：mTLS authenticator 要求 native TLS 和 client auth，见 `src/java/org/apache/cassandra/auth/MutualTlsAuthenticator.java:180-186`。
- `Certificate identity ... not authorized`：certificate validator 抽出的 identity 不在 `identity_to_role` 或 cache 尚未刷新，见 `src/java/org/apache/cassandra/auth/MutualTlsAuthenticator.java:150-177` 与 `test/unit/org/apache/cassandra/auth/MutualTlsAuthenticatorTest.java:103-150`。
- protocol v3 custom payload 失败：CUSTOM_PAYLOAD flag 只允许 v4+，见 `src/java/org/apache/cassandra/transport/Message.java:359-363` 与 `test/unit/org/apache/cassandra/transport/MessagePayloadTest.java:265-365`。
- Virtual table 过滤查询失败：provider 覆盖 `allowFilteringImplicitly=false` 时，普通 CQL filtering 仍需 ALLOW FILTERING，见 `src/java/org/apache/cassandra/cql3/restrictions/StatementRestrictions.java:360-367` 与 `test/unit/org/apache/cassandra/cql3/validation/entities/VirtualTableTest.java:1030-1085`。

## 测试用例

- Grammar/raw prepare：`test/unit/org/apache/cassandra/cql3/CqlParserTest.java:40-90` 覆盖 parser error listener/recovery；`test/unit/org/apache/cassandra/transport/messages/PrepareMessageTest.java:27-39` 覆盖 v5 PREPARE codec keyspace；`test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java:200-459` 覆盖 reconnect/reprepare、metadata flags、LWT 与 schema change invalidation；prepared compatibility source matrix 和 drift checker 见 `research/module-prepared-statement-compatibility-matrix.md` 与 `research/tools/check-prepared-statement-compat-drift.py`；Java driver reprepare/hash/keyspace/mixed-mode/fuzz runtime 覆盖和 non-Java gap matrix 见 `research/module-prepared-driver-integration-gap-matrix.md` 与 `research/tools/check-prepared-driver-integration-drift.py`。
- mTLS identity：`test/unit/org/apache/cassandra/auth/MutualTlsAuthenticatorTest.java:75-150` 覆盖 authorized/unauthorized/invalid certificate 和 identity cache refresh；`test/unit/org/apache/cassandra/auth/MutualTlsWithPasswordFallbackAuthenticatorTest.java:42-91` 覆盖无证书 password fallback 与有证书 mTLS negotiator；`test/unit/org/apache/cassandra/auth/SpiffeCertificateValidatorTest.java:35-58` 覆盖 SPIFFE SAN extraction。
- Identity CQL/permissions：`test/unit/org/apache/cassandra/cql3/statements/AddIdentityStatementTest.java:85-190`、`test/unit/org/apache/cassandra/cql3/statements/DropIdentityStatementTest.java:75-155`、`test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java:485-565`。
- TLS hot reload：`test/unit/org/apache/cassandra/security/SSLFactoryTest.java:100-135` 覆盖 happy path context replacement，`test/unit/org/apache/cassandra/security/SSLFactoryTest.java:232-282` 覆盖坏文件/坏密码不清旧 context。
- Protocol extras：`test/unit/org/apache/cassandra/transport/MessagePayloadTest.java:145-260` 覆盖 v4/v5 QUERY/PREPARE/EXECUTE/BATCH request and response payload，`test/unit/org/apache/cassandra/transport/MessagePayloadTest.java:265-365` 覆盖 v3 custom payload 拒绝，`test/unit/org/apache/cassandra/cql3/TraceCqlTest.java:60-125` 覆盖 prepared tracing bind variables，`test/unit/org/apache/cassandra/transport/RateLimitingTest.java:210-235` 覆盖 v4+ backpressure warnings；`OPTIONS`/`STARTUP`/`AUTH_RESPONSE` 和 `ERROR`/`EVENT`/auth response family 负例矩阵与 drift checker 见 `research/module-native-protocol-extras-negative-matrix.md` 与 `research/tools/check-native-protocol-extras-drift.py`。
- Virtual table planner：`test/unit/org/apache/cassandra/cql3/validation/entities/VirtualTableTest.java:410-465` 覆盖 multi-partition/range/paging/count，`test/unit/org/apache/cassandra/cql3/validation/entities/VirtualTableTest.java:1030-1085` 覆盖 implicit filtering 禁用，`test/distributed/org/apache/cassandra/distributed/test/VirtualTableFromInternodeTest.java:70-130` 覆盖 internode read command 访问 virtual table。
- 当前剩余缺口：prepared statement 已补 source-level protocol/id/cache/persistence compatibility matrix，并补 Java driver runtime/protocol boundary/non-Java gap matrix；仍缺完整 external driver/protocol integration matrix；TLS hot reload 已补 SSLFactory/cache、JKS/PEM file watch、native pipeline、JMX、mTLS 与 existing tests coverage matrix，但仍缺真实 native connection 端到端轮换 Java test；protocol extras 已补 source-level negative matrix，仍缺对应 Java negative tests 和完整 external driver 覆盖。
