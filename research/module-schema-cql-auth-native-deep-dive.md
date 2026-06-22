# Schema/CQL/Auth/Native Deep Dive

## 范围

本文补充 `research/module-schema-cql-auth.md`、`research/module-native-protocol.md` 和 `research/module-system-tables.md` 的第二轮源码细节，聚焦五个缺口：

- UDF/UDA 的 DDL 校验、`system_schema` 持久化、Java UDF sandbox、异步执行和超时。
- `system_schema`、`system.local`、`system.peers_v2`、`system_auth`、`system_distributed` 中最常用于排障和兼容性的列语义。
- CQL `GRANT`、`REVOKE`、`LIST PERMISSIONS` 的 statement 层和默认 `CassandraAuthorizer` 后端表写入。
- 默认认证/角色/网络/CIDR 后端对 `system_auth` 的内部查询、缓存和一致性级别。
- native protocol 的 TLS/dual-port、V5 large-message 分帧、CRC、warnings、custom payload 和 tracing extra flags。

不展开 CQL grammar 的 token 级规则、所有 virtual table planner 分支、证书热加载细节和完整 driver 兼容矩阵；这些保留到第三轮。

## 设计目标

- UDF/UDA 要把用户提交的 CQL 元数据转换成可复制、可 diff、可 drop 的 schema 对象，同时在执行时限制语言、类加载权限、线程和超时，避免任意代码破坏 JVM。入口在 `src/java/org/apache/cassandra/cql3/statements/schema/CreateFunctionStatement.java:80`、`src/java/org/apache/cassandra/cql3/statements/schema/CreateAggregateStatement.java:90`，运行时在 `src/java/org/apache/cassandra/cql3/functions/UDFunction.java:364`。
- system 表要给客户端、driver、运维工具和节点自身提供稳定的 CQL 可见元数据视图。schema 表定义集中在 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:90`，节点本地/peer 状态在 `src/java/org/apache/cassandra/db/SystemKeyspace.java:264` 和 `src/java/org/apache/cassandra/db/SystemKeyspace.java:292`。
- 权限语句要先确认 actor、resource、grantee 和目标 permission 的合法性，再把变更交给 authorizer；默认实现用 `system_auth.role_permissions` 保存权限集合，用 `system_auth.resource_role_index` 支撑按 resource 反查。statement 骨架在 `src/java/org/apache/cassandra/cql3/statements/PermissionsManagementStatement.java:47`，默认后端在 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:97`。
- native transport 要在认证、协议协商、压缩、背压和 response encode 之间保持清晰边界：TLS 先于协议处理进入 Netty pipeline，大消息按 frame 切分，warnings/custom payload/tracing 作为 envelope extra 数据编码。TLS 分支在 `src/java/org/apache/cassandra/transport/PipelineConfigurator.java:173`，large-message 说明在 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:59`。

## 解决的问题

- UDF/UDA schema 安全：`CREATE FUNCTION` 校验函数名、参数名重复、显式 frozen、返回类型、`OR REPLACE`/`IF NOT EXISTS` 互斥，并拒绝用 function 覆盖 aggregate；`CREATE AGGREGATE` 还校验 state/final function 的参数和返回类型。见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateFunctionStatement.java:80`、`src/java/org/apache/cassandra/cql3/statements/schema/CreateAggregateStatement.java:90`。
- UDF 运行安全：只允许 Java UDF，且 `user_defined_functions_enabled` 必须开启；执行失败包装成 `FunctionExecutionException`，超时会发 `ClientWarn` 并按 timeout policy 交给 `JVMStabilityInspector`。见 `src/java/org/apache/cassandra/cql3/functions/UDFunction.java:427`、`src/java/org/apache/cassandra/cql3/functions/UDFunction.java:486`。
- system 表兼容：`system_schema.tables` 保留废弃 read repair chance 列以兼容旧 driver，同时追加 auto repair 可选列；`system_schema.column_masks` 独立保存 mask function 和参数；`system.local`/`peers_v2` 把 gossip、address、port、host id、schema version 和 tokens 映射成 CQL 行。见 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:102`、`src/java/org/apache/cassandra/schema/SchemaKeyspace.java:148`、`src/java/org/apache/cassandra/db/SystemKeyspace.java:264`、`src/java/org/apache/cassandra/db/SystemKeyspace.java:292`。
- 权限可撤销和可枚举：grant/revoke 不只是更新 role 行，还维护 resource 到 role 的反向索引；role drop 和 resource drop 通过 logged batch 清理两张表，避免 orphan permission。见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:97`、`src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:128`、`src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:172`。
- 大 CQL 消息和背压：V5 handler 从 envelope header 得到显式 message size，持有 per-connection/per-endpoint/global permits 到 response encode 后释放；超过限制时可暂停 socket read，也可按 `THROW_ON_OVERLOAD` 抛错。见 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:64`、`src/java/org/apache/cassandra/transport/CQLMessageHandler.java:480`。

## 设计取舍

- UDF 选择默认关闭。`conf/cassandra.yaml:1758` 和 `src/java/org/apache/cassandra/config/Config.java:587` 都把 `user_defined_functions_enabled` 设为 false，避免新集群默认暴露 Java 执行面。
- UDF async execution 有安全和成本权衡。开启线程池会增加每次调用开销，但能隔离执行、实现 warn/fail timeout；关闭线程需要 `allow_insecure_udfs`，并绕开 security manager。相关配置在 `src/java/org/apache/cassandra/config/Config.java:614`、`src/java/org/apache/cassandra/config/Config.java:630`。
- UDA 不被视为 pure function。`UDAggregate.isPure()` 返回 false，避免 planner 把聚合执行折叠成可复用纯表达式。见 `src/java/org/apache/cassandra/cql3/functions/UDAggregate.java:93`。
- `LIST PERMISSIONS` 在只有 resource、没有 grantee 时会构造带 `ALLOW FILTERING` 的查询，这是为了支持按 resource 枚举权限；反向索引主要服务 revoke-all-on/drop resource。见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:363`。
- native dual port 继续存在但已 deprecated。`conf/cassandra.yaml:1024` 描述 dedicated SSL port，`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:925` 会打印弃用警告，并禁止 `native_transport_port_ssl` 在 encryption policy 为 `UNENCRYPTED` 时使用。
- LZ4 frame 为 payload 追加 CRC32；unprotected frame 只校验 header CRC24。压缩 frame 的完整布局在 `src/java/org/apache/cassandra/net/FrameDecoderLZ4.java:32`，非压缩 frame 在 `src/java/org/apache/cassandra/net/FrameDecoderUnprotected.java:34`。

## 核心类

- `CreateFunctionStatement`：把 raw argument/return type 解析为 UDF 类型，处理 `OR REPLACE`、`IF NOT EXISTS`、function/aggregate 冲突和 function resource 授权。见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateFunctionStatement.java:40`、`src/java/org/apache/cassandra/cql3/statements/schema/CreateFunctionStatement.java:178`。
- `CreateAggregateStatement`：解析 state type、state function、final function、initcond，创建 `UDAggregate` 并写回 keyspace metadata。见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateAggregateStatement.java:50`、`src/java/org/apache/cassandra/cql3/statements/schema/CreateAggregateStatement.java:90`。
- `UDFunction`：统一 UDF 执行入口、nullability short-circuit、async warn/fail timeout、broken function fallback 和 CQL 反序列化字符串输出。见 `src/java/org/apache/cassandra/cql3/functions/UDFunction.java:231`、`src/java/org/apache/cassandra/cql3/functions/UDFunction.java:328`、`src/java/org/apache/cassandra/cql3/functions/UDFunction.java:364`。
- `JavaBasedUDFunction`：生成 Java source、ECJ 编译、bytecode verifier、无权限 `ProtectionDomain` 和 per-UDF class loader。见 `src/java/org/apache/cassandra/cql3/functions/JavaBasedUDFunction.java:74`、`src/java/org/apache/cassandra/cql3/functions/JavaBasedUDFunction.java:150`、`src/java/org/apache/cassandra/cql3/functions/JavaBasedUDFunction.java:240`、`src/java/org/apache/cassandra/cql3/functions/JavaBasedUDFunction.java:700`。
- `UDAggregate`：保存 state/result 类型、state/final function 和 initcond；每个 aggregation 创建 stateful `Aggregate` 对象。见 `src/java/org/apache/cassandra/cql3/functions/UDAggregate.java:35`、`src/java/org/apache/cassandra/cql3/functions/UDAggregate.java:167`。
- `SchemaKeyspace`：定义 system_schema 表，把 function/aggregate metadata 写成 schema mutation，再从行读回 `UDFunction`/`UDAggregate`。见 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:242`、`src/java/org/apache/cassandra/schema/SchemaKeyspace.java:899`、`src/java/org/apache/cassandra/schema/SchemaKeyspace.java:927`、`src/java/org/apache/cassandra/schema/SchemaKeyspace.java:1328`。
- `SystemKeyspace`：定义 `system.local` 和 `system.peers_v2`，持久化 local metadata、tokens、schema version、peer DC/rack/address/native address。见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:264`、`src/java/org/apache/cassandra/db/SystemKeyspace.java:580`、`src/java/org/apache/cassandra/db/SystemKeyspace.java:836`、`src/java/org/apache/cassandra/db/SystemKeyspace.java:860`。
- `AuthKeyspace`：定义默认 auth 后端所有持久表，包括 roles、identity mapping、role membership、permissions、network permissions 和 CIDR tables。见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:72`。
- `PasswordAuthenticator`：凭 `system_auth.roles.salted_hash` 做 BCrypt 校验，并用 `CredentialsCache` 缓存查询结果。见 `src/java/org/apache/cassandra/auth/PasswordAuthenticator.java:70`、`src/java/org/apache/cassandra/auth/PasswordAuthenticator.java:138`。
- `CassandraRoleManager`：创建/删除/修改 role、role grant/revoke、默认 superuser 初始化、角色继承闭包和 role cache 预热。见 `src/java/org/apache/cassandra/auth/CassandraRoleManager.java:260`、`src/java/org/apache/cassandra/auth/CassandraRoleManager.java:316`、`src/java/org/apache/cassandra/auth/CassandraRoleManager.java:440`、`src/java/org/apache/cassandra/auth/CassandraRoleManager.java:521`。
- `CassandraAuthorizer`：默认权限后端，负责 grant/revoke/list、drop role/resource 清理、auth CL 选择和 cache bulk load。见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:80`、`src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:97`、`src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:315`、`src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:444`。
- `NativeTransportService` 和 `PipelineConfigurator`：按 TLS policy 构造 regular/tls server 和 Netty pipeline。见 `src/java/org/apache/cassandra/service/NativeTransportService.java:86`、`src/java/org/apache/cassandra/transport/PipelineConfigurator.java:160`。
- `Message`、`CQLMessageHandler`、`Flusher`：编码 request/response flags、解码 tracing/warnings/custom payload、累积大消息、释放 permits、把大 response 切成多 frame。见 `src/java/org/apache/cassandra/transport/Message.java:331`、`src/java/org/apache/cassandra/transport/Message.java:427`、`src/java/org/apache/cassandra/transport/CQLMessageHandler.java:56`、`src/java/org/apache/cassandra/transport/Flusher.java:164`。

## 核心接口

- `UserFunction`/`ScalarFunction`/`AggregateFunction` 是 UDF/UDA 与 native function 统一执行面；`UserFunctions` 是 keyspace metadata 里的 immutable 容器。见 `src/java/org/apache/cassandra/schema/UserFunctions.java:37`、`src/java/org/apache/cassandra/schema/UserFunctions.java:170`、`src/java/org/apache/cassandra/schema/UserFunctions.java:241`。
- `IAuthorizer` 定义 grant/revoke/list/revokeAll hook，statement 层只依赖该接口。见 `src/java/org/apache/cassandra/auth/IAuthorizer.java:57`、`src/java/org/apache/cassandra/auth/IAuthorizer.java:79`、`src/java/org/apache/cassandra/auth/IAuthorizer.java:101`。
- `IAuthenticator`、`IRoleManager`、`INetworkAuthorizer`、`ICIDRAuthorizer` 分别支撑登录、角色、DC 网络权限和 CIDR 登录过滤；默认实现都落到 `system_auth`。证据集中在 `src/java/org/apache/cassandra/auth/PasswordAuthenticator.java:93`、`src/java/org/apache/cassandra/auth/CassandraRoleManager.java:751`、`src/java/org/apache/cassandra/auth/CassandraNetworkAuthorizer.java:55`、`src/java/org/apache/cassandra/auth/CIDRPermissionsManager.java:63`。
- `QueryHandler` 是 native message 到 query processor 的抽象入口，custom payload 通过 query/prepare/execute/batch 方法传入处理器。见 `src/java/org/apache/cassandra/cql3/QueryHandler.java:34`、`test/unit/org/apache/cassandra/transport/MessagePayloadTest.java:394`。
- `FrameDecoder`/`FrameEncoder` 是 V5 frame 边界。pipeline 根据 startup compression 选择 CRC 或 LZ4 编解码，见 `src/java/org/apache/cassandra/transport/PipelineConfigurator.java:356`。

## 核心数据结构

- `system_schema.functions` 的主键是 keyspace/function/argument_types，保存 argument_names、body、language、return_type、called_on_null_input。定义在 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:242`。
- `system_schema.aggregates` 保存 aggregate_name、argument_types、state_func、state_type、final_func、return_type、initcond。定义在 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:256`。
- `UserFunctions` 以 keyspace 内 immutable collection 管理 UDF/UDA，提供 `find()`、`withAddedOrUpdated()` 和 diff。见 `src/java/org/apache/cassandra/schema/UserFunctions.java:37`、`src/java/org/apache/cassandra/schema/UserFunctions.java:302`。
- `system_schema.keyspaces/tables/columns/views/indexes/types` 是 driver 和 tooling 读取 schema 的主要表族；其中 `system_schema.tables` 包含 compaction/compression/caching/memtable/flags/read_repair/auto_repair 等 table params，`system_schema.columns` 保存 column kind、position、clustering_order 和类型。源码列契约已纳入 `research/module-system-table-column-contract.md` 并由 `research/tools/check-system-table-column-drift.py` 校验；定义见 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:91`、`src/java/org/apache/cassandra/schema/SchemaKeyspace.java:102`、`src/java/org/apache/cassandra/schema/SchemaKeyspace.java:134`、`src/java/org/apache/cassandra/schema/SchemaKeyspace.java:186`、`src/java/org/apache/cassandra/schema/SchemaKeyspace.java:221`、`src/java/org/apache/cassandra/schema/SchemaKeyspace.java:232`。
- `system.local` 保存本地 node identity、地址/端口、版本、DC/rack、schema_version、tokens 和 truncation map；`system.peers_v2` 保存 peer endpoint+port、preferred endpoint、native address、schema_version 和 tokens。定义在 `src/java/org/apache/cassandra/db/SystemKeyspace.java:264`、`src/java/org/apache/cassandra/db/SystemKeyspace.java:292`。
- `system_auth.roles` 保存 role 属性和 `salted_hash`；`role_members`/`roles.member_of` 双向维护 role inheritance；`role_permissions` 保存 role/resource -> permissions 集合；`resource_role_index` 支撑 resource -> role 反查；`network_permissions`、`cidr_permissions`、`cidr_groups` 保存网络登录限制。定义在 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:72`、`src/java/org/apache/cassandra/auth/AuthKeyspace.java:92`、`src/java/org/apache/cassandra/auth/AuthKeyspace.java:100`、`src/java/org/apache/cassandra/auth/AuthKeyspace.java:109`、`src/java/org/apache/cassandra/auth/AuthKeyspace.java:117`、`src/java/org/apache/cassandra/auth/AuthKeyspace.java:127`、`src/java/org/apache/cassandra/auth/AuthKeyspace.java:138`。
- `system_distributed.parent_repair_history`、`view_build_status`、`partition_denylist`、`auto_repair_history` 和 `auto_repair_priority` 是跨节点运维状态。定义在 `src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:146`、`src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:166`、`src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:176`、`src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:186`、`src/java/org/apache/cassandra/schema/SystemDistributedKeyspace.java:199`。
- native response extra data 由 envelope flags 驱动：tracing id、warnings、custom payload 都在 message body 前缀部分编码/解码。见 `src/java/org/apache/cassandra/transport/Message.java:331`、`src/java/org/apache/cassandra/transport/Message.java:427`。

## 生命周期

1. `CREATE FUNCTION`/`CREATE AGGREGATE` 被 parser 构造成 schema statement，执行 `apply()` 做类型、名称、权限和替换语义校验，返回带新增/更新 `UserFunctions` 的 keyspace metadata。入口是 `src/java/org/apache/cassandra/cql3/statements/schema/CreateFunctionStatement.java:80`、`src/java/org/apache/cassandra/cql3/statements/schema/CreateAggregateStatement.java:90`。
2. schema mutation 写入 `system_schema.functions` 或 `system_schema.aggregates`，schema pull/push 时再从行重建 UDF/UDA。写入在 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:899`、`src/java/org/apache/cassandra/schema/SchemaKeyspace.java:927`。
3. 查询执行表达式调用 UDF 时，`UDFunction.execute()` 先检查配置与 language，再按 nullability 决定是否 short-circuit，最后同步或异步执行 Java UDF。入口在 `src/java/org/apache/cassandra/cql3/functions/UDFunction.java:364`。
4. UDA 聚合时，`UDAggregate.newAggregate()` 创建 per-query state holder，state function 更新 state，final function 计算结果。见 `src/java/org/apache/cassandra/cql3/functions/UDAggregate.java:167`。
5. 节点启动和 gossip 更新会刷新 system 表：local metadata 在 `persistLocalMetadata()` 写入；tokens、schema version、peer info 分别由 `updateTokens()`、`updateSchemaVersion()`、`updatePeerInfo()` 等方法维护。见 `src/java/org/apache/cassandra/db/SystemKeyspace.java:580`、`src/java/org/apache/cassandra/db/SystemKeyspace.java:836`、`src/java/org/apache/cassandra/db/SystemKeyspace.java:897`、`src/java/org/apache/cassandra/db/SystemKeyspace.java:860`。
6. 登录时，`PasswordAuthenticator.authenticate()` 查 credentials cache；miss 时用 prepared statement 从 `system_auth.roles` 读 `salted_hash`，再 BCrypt 校验。见 `src/java/org/apache/cassandra/auth/PasswordAuthenticator.java:138`、`src/java/org/apache/cassandra/auth/PasswordAuthenticator.java:165`。
7. role lifecycle 通过 `CassandraRoleManager` 写 `system_auth.roles`、`role_members`、`identity_to_role`，drop role 时还触发 permission cleanup。见 `src/java/org/apache/cassandra/auth/CassandraRoleManager.java:260`、`src/java/org/apache/cassandra/auth/CassandraRoleManager.java:288`、`src/java/org/apache/cassandra/auth/CassandraRoleManager.java:558`。
8. permission lifecycle 从 `GRANT`/`REVOKE` statement 进入 authorizer；成功 grant 写 permission set 并添加 lookup entry，revoke 减去 existing permission 并移除 lookup entry。见 `src/java/org/apache/cassandra/cql3/statements/GrantPermissionsStatement.java:66`、`src/java/org/apache/cassandra/cql3/statements/RevokePermissionsStatement.java:48`、`src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:97`。
9. native 连接启动时，server 按 native/tls port 和 encryption policy 构造监听端口；pipeline 先装 TLS detector 或 `SslHandler`，再装 frame decoder/encoder、message handler 和 dispatcher。见 `src/java/org/apache/cassandra/service/NativeTransportService.java:86`、`src/java/org/apache/cassandra/transport/PipelineConfigurator.java:173`、`src/java/org/apache/cassandra/transport/PipelineConfigurator.java:278`。
10. large response flush 时，第一帧写 envelope header，其余帧继续写 body slice，所有 frame 都以 `selfContained=false` 发送。见 `src/java/org/apache/cassandra/transport/Flusher.java:164`。

## 调用链

### UDF/UDA DDL

```text
CREATE FUNCTION
  -> CreateFunctionStatement.apply()
  -> UDFunction.assertUdfsEnabled()
  -> raw types prepare -> udfType()
  -> UDFunction.create()
  -> KeyspaceMetadata.userFunctions.withAddedOrUpdated()
  -> SchemaKeyspace.addFunctionToSchemaMutation()
```

证据：`src/java/org/apache/cassandra/cql3/statements/schema/CreateFunctionStatement.java:80`、`src/java/org/apache/cassandra/cql3/functions/UDFunction.java:231`、`src/java/org/apache/cassandra/schema/SchemaKeyspace.java:899`。

```text
CREATE AGGREGATE
  -> CreateAggregateStatement.apply()
  -> resolve state type and argument types
  -> find state UDF and optional final UDF
  -> validate initcond
  -> UDAggregate.create()
  -> SchemaKeyspace.addAggregateToSchemaMutation()
```

证据：`src/java/org/apache/cassandra/cql3/statements/schema/CreateAggregateStatement.java:90`、`src/java/org/apache/cassandra/cql3/functions/UDAggregate.java:65`、`src/java/org/apache/cassandra/schema/SchemaKeyspace.java:927`。

### Permission CQL

```text
GRANT/REVOKE/LIST
  -> PermissionsManagementStatement.validate()
  -> correct resource, resource.exists(), role exists
  -> authorize() requires AUTHORIZE plus target permissions
  -> CassandraAuthorizer.grant()/revoke()/list()
  -> system_auth.role_permissions and resource_role_index
```

证据：`src/java/org/apache/cassandra/cql3/statements/PermissionsManagementStatement.java:47`、`src/java/org/apache/cassandra/cql3/statements/PermissionsManagementStatement.java:64`、`src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:97`、`src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:315`。

### Default Auth Login

```text
AUTH_RESPONSE / SASL
  -> PasswordAuthenticator.authenticate()
  -> CredentialsCache.get(role)
  -> queryHashedPassword(role)
  -> SELECT salted_hash FROM system_auth.roles WHERE role = ?
  -> BCrypt.checkpw()
```

证据：`src/java/org/apache/cassandra/auth/PasswordAuthenticator.java:138`、`src/java/org/apache/cassandra/auth/PasswordAuthenticator.java:165`、`src/java/org/apache/cassandra/auth/PasswordAuthenticator.java:212`。

### Native TLS And Frames

```text
connection accepted
  -> NativeTransportService chooses regular/tls server
  -> PipelineConfigurator.configureInitialPipeline()
  -> encryptionConfig(): detector or SslHandler
  -> modern pipeline selects CRC/LZ4 frame codec
  -> CQLMessageHandler accumulates/deserializes messages
  -> Dispatcher executes request
  -> Message.encode() writes tracing/warnings/custom payload extras
  -> Flusher splits large responses into frames
```

证据：`src/java/org/apache/cassandra/service/NativeTransportService.java:86`、`src/java/org/apache/cassandra/transport/PipelineConfigurator.java:160`、`src/java/org/apache/cassandra/transport/PipelineConfigurator.java:356`、`src/java/org/apache/cassandra/transport/CQLMessageHandler.java:56`、`src/java/org/apache/cassandra/transport/Message.java:331`、`src/java/org/apache/cassandra/transport/Flusher.java:164`。

## 配置项

- UDF 开关：`user_defined_functions_enabled` 默认 false；scripted UDF 也默认 false 并已废弃。见 `conf/cassandra.yaml:1758`、`src/java/org/apache/cassandra/config/Config.java:587`、`src/java/org/apache/cassandra/config/Config.java:592`。
- UDF thread/sandbox：`user_defined_functions_threads_enabled` 默认 true；关闭线程时要求 `allow_insecure_udfs`，`allow_extra_insecure_udfs` 会放宽更多 JDK class/resource 禁止列表。见 `src/java/org/apache/cassandra/config/Config.java:614`、`src/java/org/apache/cassandra/config/Config.java:630`。
- UDF timeout：warn/fail timeout 与 `user_function_timeout_policy` 在 config 中定义；warn 必须小于 fail，校验在 `DatabaseDescriptor`。见 `src/java/org/apache/cassandra/config/Config.java:642`、`src/java/org/apache/cassandra/config/Config.java:655`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:878`。
- native port/TLS：`native_transport_port` 默认 9042；`native_transport_port_ssl` 是 deprecated dual-port；`client_encryption_options.enabled/optional/require_client_auth/require_endpoint_verification` 决定 TLS policy 和 client cert 校验。见 `conf/cassandra.yaml:1018`、`conf/cassandra.yaml:1024`、`conf/cassandra.yaml:1699`、`src/java/org/apache/cassandra/config/EncryptionOptions.java:420`。
- native frame/message limits：`native_transport_max_frame_size` 默认 16MiB 并要求正数且小于 `Integer.MAX_VALUE`；`native_transport_max_message_size` 默认根据 heap/request in-flight 推导，显式配置不能超过 global/per-IP request data in-flight。见 `conf/cassandra.yaml:1040`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:619`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:903`。
- native request memory：`native_transport_max_request_data_in_flight` 默认 heap 10%，per-IP 默认 heap 2.5%；receive queue 默认 1MiB。见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:649`、`src/java/org/apache/cassandra/config/Config.java:301`。
- overload strategy：`native_transport_throw_on_overload` 默认 false，控制 pause read 还是抛 overload exception。见 `src/java/org/apache/cassandra/config/Config.java:1393`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:2377`。
- auth 后端 CL：`CassandraAuthorizer` 和 `CassandraRoleManager` 从 `AuthProperties` 读取 auth read/write consistency；默认 superuser 使用独立的 `DEFAULT_SUPERUSER_CONSISTENCY_LEVEL`。见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:430`、`src/java/org/apache/cassandra/auth/CassandraRoleManager.java:713`。

## Metrics

- UDF 本身不暴露独立 per-function metrics；主要可见信号来自 tracing、client warnings 和 query latency。UDF 执行会调用 `Tracing.trace()`，见 `src/java/org/apache/cassandra/cql3/functions/UDFunction.java:380`。
- auth cache 可通过 virtual table/MBean 观察 credentials、roles、permissions、network permissions、CIDR permissions cache keys；JMX/nodetool cache 操作在观测文档已有索引，后端 bulk load 入口在 `src/java/org/apache/cassandra/auth/PasswordAuthenticator.java:93`、`src/java/org/apache/cassandra/auth/CassandraRoleManager.java:751`、`src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:444`。
- CIDR authorizer 有专门的 metrics virtual table 测试覆盖，见 `test/unit/org/apache/cassandra/db/virtual/CIDRFilteringMetricsTableTest.java:57`。
- native transport 使用 request bytes in-flight、queue/backpressure、message size 和 client metrics；large-message permit 生命周期在 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:64`，response encode 后释放在 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:480`。
- frame corruption 和 large-message release 行为由 `test/unit/org/apache/cassandra/transport/CQLConnectionTest.java:164`、`test/unit/org/apache/cassandra/transport/RateLimitingTest.java:118` 覆盖。

## 日志

- UDF 执行失败在 `UDFunction.execute()` trace/debug 记录，并包装为 `FunctionExecutionException`；warn timeout 会 `logger.warn` 并发送 client warning。见 `src/java/org/apache/cassandra/cql3/functions/UDFunction.java:387`、`src/java/org/apache/cassandra/cql3/functions/UDFunction.java:500`。
- Java UDF 编译错误会通过 ECJ problem list 构造 validation error；class loader 和 bytecode verifier 在 `JavaBasedUDFunction` 中执行。见 `src/java/org/apache/cassandra/cql3/functions/JavaBasedUDFunction.java:240`。
- dual native port 会在配置应用时打印 deprecated warning，见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:925`。
- optional/encrypted CQL TLS pipeline 会打印 debug 日志，见 `src/java/org/apache/cassandra/transport/PipelineConfigurator.java:181`、`src/java/org/apache/cassandra/transport/PipelineConfigurator.java:220`。
- response warnings 出现在 protocol v4+；如果低版本 response 带 warning，`Message.encode()` 会记录 warning 并丢弃 warnings。见 `src/java/org/apache/cassandra/transport/Message.java:345`。
- CRC corruption 被转换为 `ProtocolException`，测试断言错误消息包含 unrecoverable CRC mismatch，见 `test/unit/org/apache/cassandra/transport/CQLConnectionTest.java:164`。

## 运维关注点

- 开启 UDF 前先确认 workload、timeout policy 和 sandbox 需求。默认关闭是有意设计；若关闭 UDF threads 必须同时开启 insecure UDF，风险明显高于默认 async 线程池。见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:878`。
- UDF warn/fail timeout 不是慢查询优化工具，而是 JVM 防护线。`ignore` policy 只改变超时后的 VM 处理，不改变单次 UDF 已经消耗 CPU 的事实。见 `src/java/org/apache/cassandra/cql3/functions/UDFunction.java:549`。
- `system_schema` 逐列语义对 driver 兼容很敏感；不要因为代码里字段“废弃”就删除 system_schema 列，`SchemaKeyspace` 仍保留 read repair chance 等兼容列。见 `src/java/org/apache/cassandra/schema/SchemaKeyspace.java:102`。
- `system.local`/`peers_v2` 的 address/port 字段来自本地 config 和 gossip state；排查 driver 连接、preferred IP、schema disagreement 时应同时看 system 表和 gossip。更新入口在 `src/java/org/apache/cassandra/service/StorageService.java:2860`、`src/java/org/apache/cassandra/service/StorageService.java:2959`。
- auth 后端依赖 `system_auth` replication。跨 DC 扩容或 RF 调整后，应关注 auth 表读写一致性、default superuser 初始化和角色缓存预热。相关行为由 `test/distributed/org/apache/cassandra/distributed/test/UpdateSystemAuthAfterDCExpansionTest.java:117` 覆盖。
- 使用 native dual-port 时要记住它在 5.0 已 deprecated，并且 encryption policy 为 unencrypted 时会直接配置失败。见 `conf/cassandra.yaml:1024`、`src/java/org/apache/cassandra/config/DatabaseDescriptor.java:933`。
- TLS optional 模式会在同一个 port 接受明文和 TLS，只适合迁移阶段；长期安全目标应使用 encrypted policy 和必要的 client auth/endpoint verification。pipeline 行为见 `src/java/org/apache/cassandra/transport/PipelineConfigurator.java:181`。
- 大 CQL message 会占用 request data in-flight permits 到 response encode 后释放；批量/大 payload 客户端需要与 `native_transport_max_message_size`、global/per-IP in-flight 配合调参。见 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:64`。

## 性能瓶颈

- UDF async 执行每次调用有线程切换和 future 开销，源码注释标出约 100us 级额外开销；对每行调用的函数会放大。见 `src/java/org/apache/cassandra/cql3/functions/UDFunction.java:375`。
- Java UDF 首次创建需要 source 生成、ECJ 编译、bytecode verifier、class load；DDL 频繁变更会把编译成本暴露到 schema change 路径。见 `src/java/org/apache/cassandra/cql3/functions/JavaBasedUDFunction.java:240`。
- UDA state function 对每个输入行更新 state，final function 只在 compute 时执行；state 类型过大或 initcond 复杂会增加聚合内存和 CPU。见 `src/java/org/apache/cassandra/cql3/functions/UDAggregate.java:167`。
- `LIST PERMISSIONS` 如果按 resource 枚举且没有指定 grantee，会走 filtering query；权限集合很大时应优先按 role/resource 精确查。见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:363`。
- `PasswordAuthenticator` 每次 cache miss 都会读 `system_auth.roles` 并执行 BCrypt；错误密码暴力尝试主要消耗 CPU。见 `src/java/org/apache/cassandra/auth/PasswordAuthenticator.java:117`、`src/java/org/apache/cassandra/auth/PasswordAuthenticator.java:165`。
- native large message 会在 event loop 累积所有 frame 后再反序列化完整 envelope；大 payload 会增加 event loop 占用和内存 permit 压力。见 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:59`。
- LZ4 frame 比 unprotected frame 多 payload CRC32 和压缩/解压成本，但能在压缩流上检测 body corruption。见 `src/java/org/apache/cassandra/net/FrameDecoderLZ4.java:124`。

## 常见故障

- `User-defined functions are disabled`：`user_defined_functions_enabled` 未开启或语言不是 Java，抛错来自 `src/java/org/apache/cassandra/cql3/functions/UDFunction.java:427`。
- UDF 超时：warn timeout 先返回 client warning，fail timeout 抛 `FunctionExecutionException` 并触发 timeout policy；根因通常是函数 CPU/IO 行为不受控。见 `src/java/org/apache/cassandra/cql3/functions/UDFunction.java:486`。
- `CREATE AGGREGATE` state/final function 不匹配：state function 参数必须是 state type 加 aggregate args，返回值必须兼容 state type；final function 必须只接收 state type。见 `src/java/org/apache/cassandra/cql3/statements/schema/CreateAggregateStatement.java:90`。
- `GRANT`/`REVOKE` 对 system keyspace 失败：非 virtual system keyspace/table 只允许 `SELECT`、`DESCRIBE`、`ALTER` 等受限 permission；校验在 `src/java/org/apache/cassandra/cql3/statements/GrantPermissionsStatement.java:48` 和 `src/java/org/apache/cassandra/auth/Permission.java:73`。
- `LIST PERMISSIONS` 未授权：非 super/system/self 用户必须拥有 root/grantee `DESCRIBE`，见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:315`。
- 认证失败但 role 存在：可能是 `salted_hash` 缺失、hash 无效、cache sentinel 或 BCrypt mismatch；路径在 `src/java/org/apache/cassandra/auth/PasswordAuthenticator.java:117`、`src/java/org/apache/cassandra/auth/PasswordAuthenticator.java:138`。
- native SSL port 配置失败：`native_transport_port_ssl` 与 regular port 不同但 `client_encryption_options` 未启用，会抛配置异常。见 `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:933`。
- custom payload 在 protocol v3 失败：custom payload flag 要求 protocol v4+，编码/解码都会拒绝低版本。见 `src/java/org/apache/cassandra/transport/Message.java:359`、`src/java/org/apache/cassandra/transport/Message.java:438`。
- CRC mismatch 关闭连接或返回 protocol error：LZ4 frame body CRC32 或 header CRC24 失败会被视为 corrupt frame，测试覆盖在 `test/unit/org/apache/cassandra/transport/CQLConnectionTest.java:164`。
- multi-frame auth 阶段消息过大：认证尚未完成时处理 multi-frame CQL message 会被拒绝，错误前缀在 `src/java/org/apache/cassandra/transport/CQLMessageHandler.java:86`，限制测试在 `test/unit/org/apache/cassandra/transport/AuthMessageSizeLimitTest.java:37`。

## 测试用例

- UDF/UDA：`test/unit/org/apache/cassandra/cql3/validation/entities/UFTest.java`、`test/unit/org/apache/cassandra/cql3/validation/entities/UFJavaTest.java`、`test/unit/org/apache/cassandra/cql3/validation/entities/UFAuthTest.java`、`test/unit/org/apache/cassandra/cql3/validation/entities/UFSecurityTest.java`、`test/unit/org/apache/cassandra/cql3/validation/entities/UFVerifierTest.java`。
- system schema/table：`test/unit/org/apache/cassandra/schema/SchemaKeyspaceTest.java`、`test/unit/org/apache/cassandra/db/SystemKeyspaceTest.java`、`test/unit/org/apache/cassandra/cql3/SystemKeyspaceTablesNamesTest.java`。
- auth/permission/role：`test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java`、`test/unit/org/apache/cassandra/auth/CassandraAuthorizerTest.java`、`test/unit/org/apache/cassandra/auth/CassandraRoleManagerTest.java`、`test/unit/org/apache/cassandra/auth/PasswordAuthenticatorTest.java`、`test/unit/org/apache/cassandra/auth/RolesTest.java`、`test/distributed/org/apache/cassandra/distributed/test/AuthTest.java`。
- network/CIDR auth：`test/unit/org/apache/cassandra/auth/CassandraNetworkAuthorizerTest.java`、`test/unit/org/apache/cassandra/auth/CassandraCIDRAuthorizerEnforceModeTest.java`、`test/unit/org/apache/cassandra/auth/CassandraCIDRAuthorizerMonitorModeTest.java`、`test/unit/org/apache/cassandra/auth/CIDRGroupsMappingManagerTest.java`、`test/unit/org/apache/cassandra/auth/CIDRGroupsMappingTableTest.java`。
- native TLS：`test/distributed/org/apache/cassandra/distributed/test/NativeTransportEncryptionOptionsTest.java` 覆盖 dual port、accepted TLS protocols、cipher suites、endpoint verification 和 client auth。
- native custom payload：`test/unit/org/apache/cassandra/transport/MessagePayloadTest.java:145` 覆盖 query/prepare/execute/batch 请求和响应 payload，`test/unit/org/apache/cassandra/transport/MessagePayloadTest.java:394` 验证 query handler 接收到 payload。
- native limits/backpressure/CRC：`test/unit/org/apache/cassandra/transport/RateLimitingTest.java:118`、`test/unit/org/apache/cassandra/transport/MessageSizeLimitTest.java:38`、`test/unit/org/apache/cassandra/transport/AuthMessageSizeLimitTest.java:37`、`test/unit/org/apache/cassandra/transport/CQLConnectionTest.java:164`。

## 待继续

- CQL grammar/raw prepare、prepared cache keyspace 语义、native cert hot reload、mTLS identity mapping/password fallback、protocol extras matrix 和 virtual table CQL planner 已在 `research/module-schema-cql-auth-native-third-round.md` 补齐。
- role grant/revoke 与 resource permission 的完整源码矩阵已补到 `research/module-permission-role-matrix.md`；custom auth backend SPI 兼容矩阵已补到 `research/module-auth-spi-compatibility-matrix.md` 并由 `research/tools/check-auth-spi-drift.py` 保护；prepared Java driver runtime/protocol boundary/non-Java gap matrix 已补到 `research/module-prepared-driver-integration-gap-matrix.md` 并由 `research/tools/check-prepared-driver-integration-drift.py` 保护；native protocol extras negative matrix 已补到 `research/module-native-protocol-extras-negative-matrix.md` 并由 `research/tools/check-native-protocol-extras-drift.py` 保护；native TLS reload source/test coverage matrix 已补到 `research/module-native-tls-reload-coverage-matrix.md` 并由 `research/tools/check-native-tls-reload-drift.py` 保护。后续保留测试/兼容性缺口：真实 native TLS cert reload 端到端 Java test、跨 driver/protocol prepared compatibility matrix、protocol extras Java negative tests。
