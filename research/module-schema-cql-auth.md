# Module: Schema, CQL, Auth

## 范围

本模块覆盖 native CQL 请求进入 QueryProcessor、schema transform/migration、auth login/permission/cache 和相关系统表。

## 设计目标

Schema、CQL 和 Auth 共同定义了 Cassandra 的用户可见数据模型、请求执行边界和权限模型。

本轮覆盖目标：

- 从 native protocol `QUERY/PREPARE/EXECUTE/BATCH/AUTH_RESPONSE` 走到 `QueryProcessor`。
- 解释 CQL parse/prepare/process 如何完成 keyspace resolution、bind variables、authorize、validate、execute。
- 解释 DDL statement 如何作为 `SchemaTransformation` 写入 `system_schema`，更新内存 metadata，并通过 migration coordinator 推送/拉取。
- 解释 `ClientState`、`AuthenticatedUser`、`IAuthenticator`、`IAuthorizer`、`IRoleManager`、auth caches 和 `system_auth` 表的职责。
- 标出 prepared statement cache、schema change listener 和权限 cache 的失效边界。

## 解决的问题

- Query execution 必须在 statement 执行前统一授权和校验：`QueryProcessor.processStatement()` 先 `authorize()`，再 `validate()`，最后调用 `statement.execute()`，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:266-279`。
- Prepared statements 需要避免跨 keyspace ambiguity：`QueryProcessor.prepare()` 同时计算 with-keyspace 和 without-keyspace digest，并根据 fully qualified 与当前 keyspace 返回不同 id，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:728-775`。
- Schema mutation 不是直接改全局 map：DDL statement 是 `SchemaTransformation`，`DefaultSchemaUpdateHandler.apply()` 先对 snapshot 产生新 `Keyspaces`，转换为 schema mutations，写入 `SchemaKeyspace`，再更新内存 schema，见 `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:227-252`。
- Schema 需要集群收敛：`MigrationCoordinator` 跟踪各节点 gossip 出来的 schema versions，并周期性拉取仍被节点声明的版本，见 `src/java/org/apache/cassandra/schema/MigrationCoordinator.java:90-98`。
- Auth 不能只看登录：`ClientState.validateLogin()` 还检查本 DC 访问和 CIDR/IP 访问，见 `src/java/org/apache/cassandra/service/ClientState.java:565-579`。
- Schema/Auth system tables 有特殊保护：schema tables 对已认证用户默认可读，auth 依赖资源禁止用户 DDL 修改，见 `src/java/org/apache/cassandra/service/ClientState.java:75-105`、`src/java/org/apache/cassandra/service/ClientState.java:451-472`。

## 设计取舍

- `SchemaTransformation.apply()` 要求对 schema snapshot side-effect free，真正持久化由 update handler 完成，见 `src/java/org/apache/cassandra/schema/SchemaTransformation.java:22-43`。
- `Schema` 持有 distributed keyspaces 与 local keyspaces；local keyspaces 包括 hardcoded system schema，初始化见 `src/java/org/apache/cassandra/schema/Schema.java:118-127`。
- `TableMetadata` 是 immutable；需要稳定引用的代码用 `TableMetadataRef`，schema 更新时只切换 ref 内部的 volatile metadata，见 `src/java/org/apache/cassandra/schema/TableMetadataRef.java:23-83`。
- `QueryProcessor` 作为 `SchemaChangeListener` 监听 schema 变化，table/function/drop 相关变化会失效 prepared statements，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:227-230`、`src/java/org/apache/cassandra/cql3/QueryProcessor.java:1078-1122`。
- Auth permission lookup 通过 `AuthenticatedUser.permissionsCache` 和 `PermissionsCache` 包装 authorizer，cache 是否启用由 authorizer 与配置决定，见 `src/java/org/apache/cassandra/auth/AuthenticatedUser.java:41-54`、`src/java/org/apache/cassandra/auth/PermissionsCache.java:25-47`。
- Role 与 user 是同一抽象：`IRoleManager` 注释明确负责 roles/users、role grants/revokes，见 `src/java/org/apache/cassandra/auth/IRoleManager.java:30-35`。

## 核心类

| 类 | 作用 |
|---|---|
| `QueryMessage` | native QUERY 消息，decode CQL string/options，执行 parse/process。见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:44-87`、`src/java/org/apache/cassandra/transport/messages/QueryMessage.java:101-123` |
| `PrepareMessage` | native PREPARE 消息，支持 v5 keyspace option，调用 query handler prepare。见 `src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:42-109`、`src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:117-130` |
| `ExecuteMessage` | native EXECUTE 消息，查 prepared id、校验 keyspace、prepare query options、process prepared。见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:50-116`、`src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:131-171` |
| `AuthResponse` | native SASL auth response，驱动 authenticator negotiator 并登录 `ClientState`。见 `src/java/org/apache/cassandra/transport/messages/AuthResponse.java:40-98` |
| `QueryProcessor` | CQL parse/prepare/process/batch/prepared cache 管理。定义见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:82-120` |
| `CQLStatement` | CQL statement 公共接口；各 statement 实现 authorize/validate/execute。 |
| `SelectStatement` | SELECT authorization、read CL 校验、ReadQuery 生成与分页。见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:242-292`、`src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:332-350` |
| `ModificationStatement` | INSERT/UPDATE/DELETE authorization、write CL 校验、mutation 生成。见 `src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:247-278`、`src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java:491-530` |
| `AlterSchemaStatement` | DDL statement 基类，同时实现 `SchemaTransformation`。见 `src/java/org/apache/cassandra/cql3/statements/schema/AlterSchemaStatement.java:43-65` |
| `CreateKeyspaceStatement` | keyspace DDL 示例，校验 replication 与 guardrails，返回新增 keyspace metadata。见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateKeyspaceStatement.java:63-98` |
| `CreateTableStatement` | table DDL 示例，构建并校验 `TableMetadata`，写回 keyspace metadata。见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateTableStatement.java:97-124` |
| `Schema` | 内存 schema、metadata refs、listeners、transform/merge。定义见 `src/java/org/apache/cassandra/schema/Schema.java:84-146` |
| `DefaultSchemaUpdateHandler` | online schema update/push/pull/reset 处理器。构造注册 schema push/pull handlers，见 `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:84-120` |
| `MigrationCoordinator` | schema version tracking、pull、announce。定义见 `src/java/org/apache/cassandra/schema/MigrationCoordinator.java:90-120` |
| `ClientState` | per-connection user/keyspace/auth state。定义见 `src/java/org/apache/cassandra/service/ClientState.java:68-112` |
| `AuthenticatedUser` | 登录身份、primary role、permissions/network caches。见 `src/java/org/apache/cassandra/auth/AuthenticatedUser.java:33-75` |
| `AuthKeyspace` | `system_auth` keyspace/table metadata。见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:38-69`、`src/java/org/apache/cassandra/auth/AuthKeyspace.java:155-163` |

## 核心接口

- `QueryHandler.parse()` / `process()` / `prepare()` / `processPrepared()`：native protocol 通过 `ClientState.getCQLQueryHandler()` 调用，典型入口见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:115-118`、`src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:136-169`。
- `CQLStatement.authorize()` / `validate()` / `execute()`：由 `QueryProcessor.processStatement()` 串起来，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:266-279`。
- `Schema.transform(SchemaTransformation, boolean local)`：DDL 的统一内存/持久化/传播入口，见 `src/java/org/apache/cassandra/schema/Schema.java:606-614`。
- `SchemaUpdateHandler.apply()`：把 transformation 应用到 schema storage 并同步其他节点，接口定义见 `src/java/org/apache/cassandra/schema/SchemaUpdateHandler.java:53-60`。
- `IAuthenticator.newSaslNegotiator()`：为每次认证创建 stateful SASL negotiator，见 `src/java/org/apache/cassandra/auth/IAuthenticator.java:70-99`。
- `IAuthorizer.authorize()` / `grant()` / `revoke()` / `revokeAllOn()`：权限查询和权限 DDL 后端接口，见 `src/java/org/apache/cassandra/auth/IAuthorizer.java:28-138`。
- `IRoleManager.createRole()` / `alterRole()` / `grantRole()` / `getRoles()`：role lifecycle 与 inheritance 后端接口，见 `src/java/org/apache/cassandra/auth/IRoleManager.java:60-145`。

## 核心数据结构

- `Keyspaces` / `KeyspaceMetadata` / `TableMetadata`：schema snapshot、keyspace metadata、table metadata。`Schema` 对外返回 keyspace/table metadata 见 `src/java/org/apache/cassandra/schema/Schema.java:317-355`。
- `DistributedSchema`：包含 distributed keyspaces 与 schema version；`Schema.getDistributedSchemaBlocking()` 返回一致 snapshot，见 `src/java/org/apache/cassandra/schema/Schema.java:502-508`。
- `KeyspacesDiff` / `KeyspaceDiff`：schema before/after diff，`Schema.merge()` 根据 dropped/created/altered 执行本地 load/unload/alter，见 `src/java/org/apache/cassandra/schema/Schema.java:644-684`。
- `TableMetadataRef`：持有 immutable table metadata 的 volatile ref，更新时先 `validateCompatibility()`，见 `src/java/org/apache/cassandra/schema/TableMetadataRef.java:73-83`。
- `QueryOptions` / `BatchQueryOptions`：native options、values、CL、page size；`QueryProcessor.processPrepared()` 检查 values 数量，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:851-870`。
- `Prepared` / `MD5Digest`：prepared statement cache key 和缓存项；cache 初始化在 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:93-120`。
- `DataResource` / `FunctionResource` / `RoleResource`：authorization resource hierarchy；`ClientState.ensurePermissionOnResourceChain()` 沿资源链检查，见 `src/java/org/apache/cassandra/service/ClientState.java:523-538`。

## 生命周期

CQL request：

```text
native QueryMessage / ExecuteMessage / BatchMessage
  -> ClientState.getCQLQueryHandler()
  -> QueryProcessor.parse / prepare / getPrepared
  -> QueryProcessor.process / processPrepared / processBatch
     -> bind options and values
     -> statement.authorize(clientState)
     -> statement.validate(clientState)
     -> statement.execute(...)
        -> SelectStatement -> ReadQuery -> StorageProxy/local read
        -> ModificationStatement -> mutations -> StorageProxy.mutateWithTriggers
        -> AlterSchemaStatement -> Schema.transform
```

Schema change：

```text
CREATE/ALTER/DROP ...
  -> AlterSchemaStatement.execute()
     -> reject local system / virtual keyspace changes
     -> Schema.instance.transform(statement, locally)
        -> DefaultSchemaUpdateHandler.apply(transformation, local)
           -> transformation.apply(before.keyspaces)
           -> Keyspaces.diff(before, after)
           -> SchemaKeyspace.convertSchemaDiffToMutations(...)
           -> SchemaKeyspace.applyChanges(...)
           -> updateSchema(...)
              -> Schema.mergeAndUpdateVersion(...)
                 -> merge diff into Keyspace/Table/View objects
                 -> update schema version
              -> migrationCoordinator.announce(...)
           -> if non-local: push schema mutations to peers
     -> grant creator permissions on created resources
     -> return ResultMessage.SchemaChange
```

Auth startup/login/authorization：

```text
StorageService.doAuthSetup()
  -> Schema.transform(updateSystemKeyspace(AuthKeyspace.metadata(), generation))
  -> roleManager/authenticator/authorizer/networkAuthorizer/cidrAuthorizer.setup()
  -> AuthCacheService.initializeAndRegisterCaches()
  -> Schema.registerListener(new AuthSchemaChangeListener())

native AuthResponse
  -> connection.getSaslNegotiator(queryState)
  -> negotiator.evaluateResponse(token)
  -> if complete
     -> AuthenticatedUser user
     -> ClientState.login(user)
        -> user.canLogin()
     -> AuthSuccess

statement authorization
  -> statement.authorize(clientState)
     -> ClientState.ensure*Permission(...)
        -> validateLogin()
        -> prevent system/auth protected modifications
        -> if authorizer enabled: authorize(resource chain)
```

## 调用链

- QUERY：`QueryMessage.execute()` 记录 query event 后调用 `QueryProcessor.process()`，见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:101-128`。
- PREPARE：`PrepareMessage.execute()` 调用 query handler prepare 并返回 prepared metadata，见 `src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:117-145`。
- EXECUTE：`ExecuteMessage.execute()` 取 prepared statement、校验 options 并调用 `QueryProcessor.processPrepared()`，见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:131-171`。
- 普通 statement：`QueryProcessor.processStatement()` 串起 authorize、validate、execute，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:266-279`。
- DDL schema transform：`AlterSchemaStatement.execute()` 调用 `Schema.instance.transform()` 并返回 schema change response，见 `src/java/org/apache/cassandra/cql3/statements/schema/AlterSchemaStatement.java:95-139`。
- Auth 登录：`AuthResponse.execute()` 通过 SASL negotiator 完成认证并登录 `ClientState`，见 `src/java/org/apache/cassandra/transport/messages/AuthResponse.java:72-98`。

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| `prepared_statements_cache_size` | `src/java/org/apache/cassandra/config/Config.java:584-585`、`conf/cassandra.yaml:508` | prepared statement cache 容量 |
| `authenticator` | `src/java/org/apache/cassandra/config/Config.java:82`、`conf/cassandra.yaml:198` | 登录认证后端 |
| `authorizer` | `src/java/org/apache/cassandra/config/Config.java:83`、`conf/cassandra.yaml:217` | 数据/函数/role 权限后端 |
| `role_manager` | `src/java/org/apache/cassandra/config/Config.java:84`、`conf/cassandra.yaml:232` | role/user 存储与继承后端 |
| `network_authorizer` | `src/java/org/apache/cassandra/config/Config.java:86`、`conf/cassandra.yaml:246` | DC 访问授权后端 |
| `cidr_authorizer` | `src/java/org/apache/cassandra/config/Config.java:87`、`conf/cassandra.yaml:261-276` | IP/CIDR 访问授权后端 |
| `traverse_auth_from_root` | `src/java/org/apache/cassandra/config/Config.java:223`、`conf/cassandra.yaml:289` | 权限检查资源链方向 |
| `permissions_validity` / `permissions_update_interval` / `permissions_cache_max_entries` | `src/java/org/apache/cassandra/config/Config.java:89-93`、`conf/cassandra.yaml:327-339` | permissions cache TTL/刷新/容量 |
| `roles_validity` | `src/java/org/apache/cassandra/config/Config.java:95-96`、`conf/cassandra.yaml:300` | roles cache TTL |
| `credentials_validity` | `src/java/org/apache/cassandra/config/Config.java:101-102`、`conf/cassandra.yaml:359` | password credentials cache TTL |
| `auth_cache_warming_enabled` | `src/java/org/apache/cassandra/config/Config.java:749`、`conf/cassandra.yaml:1965` | auth cache startup warming |

## Metrics

- `QueryProcessor.metrics.regularStatementsExecuted` 和 `preparedStatementsExecuted` 分别在普通/prepared 执行中递增，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:366-369`、`src/java/org/apache/cassandra/cql3/QueryProcessor.java:851-870`。
- Prepared statement eviction 更新 `preparedStatementsEvicted`，cache removal listener 定义见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:113-118`、`src/java/org/apache/cassandra/cql3/QueryProcessor.java:123-136`。
- `ClientMetrics.markAuthSuccess()` / `markAuthFailure()` 在 `AuthResponse.execute()` 中更新，见 `src/java/org/apache/cassandra/transport/messages/AuthResponse.java:72-98`。
- Read/write client request metrics 在具体 statement/data path 中更新；例如 NODE_LOCAL read/write 在 `QueryProcessor.processNodeLocal*` 中更新，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:294-334`。

## 日志

- `QueryEvents` 在 query/prepare/execute/batch 成功或失败时被 native messages 调用，见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:113-128`、`src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:167-171`。
- `DefaultSchemaUpdateHandler.waitUntilReady()` 在 schema disagreement 时输出 outstanding schema versions 和跳过检查的 system properties，见 `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:122-145`。
- `MigrationCoordinator.announce()` 把 schema version 写入 gossip `ApplicationState.SCHEMA`，见 `src/java/org/apache/cassandra/schema/MigrationCoordinator.java:574-579`。
- `SchemaChangeNotifier` 将 keyspace-level diff 拆成 table/view/type/function/aggregate 事件，见 `src/java/org/apache/cassandra/schema/SchemaChangeNotifier.java:49-83`。

## 运维关注点

- `system_auth` 的 RF 默认取 `max(system_auth_default_rf, default_keyspace_rf)`，见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:44-69`、`src/java/org/apache/cassandra/auth/AuthKeyspace.java:155-163`；启用 `PasswordAuthenticator`/`CassandraAuthorizer` 后应确认 RF。
- Schema disagreement 可通过 `StorageService.getOutstandingSchemaVersions*()` 查看，入口见 `src/java/org/apache/cassandra/service/StorageService.java:7172-7185`。
- JMX 可触发 `resetLocalSchema()` 和 `reloadLocalSchema()`，入口见 `src/java/org/apache/cassandra/service/StorageService.java:6616-6624`。
- `prepared_statements_cache_size` 太小会导致 eviction；`QueryProcessor` 每分钟记录 eviction warn，见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:120-128`。
- 修改 schema 后 prepared statement 可能失效，driver 需要能处理 `PreparedQueryNotFoundException` 或 metadata changed。
- 普通用户对 system schema/auth 资源有额外保护，不能只看显式 GRANT。

## 性能瓶颈

- Prepared statement cache 太小会造成 eviction 和 driver 端 re-prepare，`QueryProcessor` eviction listener 与 warn 计数见 `src/java/org/apache/cassandra/cql3/QueryProcessor.java:113-136`。
- 大量 schema 变更会触发 schema mutations、内存 schema merge、schema version announce 和 peers push/pull，核心 apply 流程见 `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:227-252`。
- 权限检查在 cache miss 时需要访问 authorizer backend；permissions cache 包装和参数见 `src/java/org/apache/cassandra/auth/PermissionsCache.java:25-47`。
- UDF/UDA、masked columns、复杂 SELECT validation 会增加 statement prepare/execute 前的 CPU 开销，masked column authorize 示例见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:258-270`。
- `executeNet()` 类真实 native protocol 测试会额外消耗 native transport、driver session 和 protocol serialization 成本；单元测试中 internal execute 的差异见 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1517-1585` 和 `test/unit/org/apache/cassandra/cql3/CQLTester.java:1630-1669`。

## 常见故障

- `UnauthorizedException: You have not logged in`：`ClientState.validateLogin()` 在 `user == null` 时抛出，见 `src/java/org/apache/cassandra/service/ClientState.java:565-570`。
- `PreparedQueryNotFoundException`：`ExecuteMessage` 找不到 prepared id，见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:136-140`。
- DDL 被拒绝：`AlterSchemaStatement.execute()` 禁止 local system/virtual keyspace 变更，见 `src/java/org/apache/cassandra/cql3/statements/schema/AlterSchemaStatement.java:107-118`。
- Schema change 未传播：检查 schema push/pull handler 注册与 migration coordinator outstanding versions，见 `src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:92-109`、`src/java/org/apache/cassandra/schema/DefaultSchemaUpdateHandler.java:353-355`。
- Masked columns 查询失败：`SelectStatement.authorize()` 要求 `UNMASK` 或 `SELECT_MASKED`，见 `src/java/org/apache/cassandra/cql3/statements/SelectStatement.java:258-270`。
- Auth cache 过期或未刷新：检查 permissions/roles/credentials validity/update interval 配置，以及 `PermissionsCache`/`RolesCache`/`CredentialsCache`。

## 测试用例

- `test/unit/org/apache/cassandra/cql3/CqlParserTest.java`：parser error listener/duplicate properties 测试见 `test/unit/org/apache/cassandra/cql3/CqlParserTest.java:35-90`。
- `test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java`：prepared invalidation 测试见 `test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java:60-130`。
- `test/unit/org/apache/cassandra/cql3/QueryEventsTest.java`
- `test/unit/org/apache/cassandra/cql3/validation/operations/CreateTest.java`
- `test/unit/org/apache/cassandra/cql3/validation/operations/AlterTest.java`
- `test/unit/org/apache/cassandra/cql3/validation/operations/DropTest.java`
- `test/distributed/org/apache/cassandra/distributed/test/SchemaTest.java`：schema change/read repair 交互见 `test/distributed/org/apache/cassandra/distributed/test/SchemaTest.java:50-110`。
- `test/distributed/org/apache/cassandra/distributed/test/SchemaDisagreementTest.java`
- `test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java`：权限不足断言见 `test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java:74-120`。
- `test/unit/org/apache/cassandra/auth/CassandraRoleManagerTest.java`：role hierarchy/read count 和 cache warming 见 `test/unit/org/apache/cassandra/auth/CassandraRoleManagerTest.java:69-125`。
- `test/distributed/org/apache/cassandra/distributed/test/AuthTest.java`：startup auth setup 与 default role timestamp 见 `test/distributed/org/apache/cassandra/distributed/test/AuthTest.java:52-125`。

## 待继续

- Native protocol frame/dispatcher/backpressure/TLS 已在 `research/module-native-protocol.md`、`research/flow-native-protocol.md` 和 `research/module-schema-cql-auth-native-deep-dive.md` 展开；TLS cert hot reload 和 protocol extras matrix 已在 `research/module-schema-cql-auth-native-third-round.md` 补齐。
- LWT/Paxos、counter 和 batchlog statement execution 已在 `research/module-coordination-lwt-counter-hints.md`、`research/module-coordination-lwt-counter-hints-internals.md` 和相关 flow 文档展开。
- UDF/UDA sandbox、masked columns、默认 role manager/authorizer 后端、mTLS identity mapping 和 virtual table planner 已在 `research/module-schema-cql-auth-native-deep-dive.md` 与 `research/module-schema-cql-auth-native-third-round.md` 补齐。
- role grant/revoke 与 resource permission 的完整源码矩阵已补到 `research/module-permission-role-matrix.md`。custom authenticator/authorizer/role manager/network/CIDR authorizer SPI 兼容矩阵已补到 `research/module-auth-spi-compatibility-matrix.md`，并由 `research/tools/check-auth-spi-drift.py` 保护。prepared statement protocol/id/cache/persistence source compatibility matrix 已补到 `research/module-prepared-statement-compatibility-matrix.md` 并由 `research/tools/check-prepared-statement-compat-drift.py` 保护；Java driver prepared runtime/protocol boundary/non-Java gap matrix 已补到 `research/module-prepared-driver-integration-gap-matrix.md` 并由 `research/tools/check-prepared-driver-integration-drift.py` 保护。native protocol extras negative matrix 已补到 `research/module-native-protocol-extras-negative-matrix.md` 并由 `research/tools/check-native-protocol-extras-drift.py` 保护。native TLS reload source/test coverage matrix 已补到 `research/module-native-tls-reload-coverage-matrix.md` 并由 `research/tools/check-native-tls-reload-drift.py` 保护。后续保留测试/兼容性缺口：真实 native TLS cert reload 端到端 Java test、完整 external driver/protocol prepared integration matrix、protocol extras Java negative tests。
