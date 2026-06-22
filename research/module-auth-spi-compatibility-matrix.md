# Module: Auth SPI Compatibility Matrix

## 范围

本模块补齐 custom authenticator、authorizer、role manager、network authorizer 和 CIDR authorizer 的源码兼容矩阵。它关注扩展实现必须满足的 Java SPI、启动配置约束、cache/bulk-load 语义、system_auth 交互、native/JMX 调用链和测试覆盖。默认实现的内部表结构仍以 `research/module-permission-role-matrix.md` 和 `research/module-schema-cql-auth-native-deep-dive.md` 为主。

## 设计目标

- 把 auth 后端的扩展点从“配置类名”拆成明确的接口方法契约，避免 custom backend 只实现 happy path 后在 CQL、native auth、JMX 或 cache warming 中失败。
- 记录 `AuthConfig.applyAuth()` 的跨组件 gate：authorization/network/CIDR authorization 都要求 authenticator 开启 authentication；`PasswordAuthenticator` 强制搭配 `CassandraRoleManager`。
- 标明 `IRoleManager` 的 mTLS identity 扩展方法和 `IAuthenticator.newSaslNegotiator(InetAddress, Certificate[])` 的证书链入口。
- 用 source-only drift checker 监控 SPI method surface，避免接口新增方法后研究文档继续声称兼容矩阵完整。

## 解决的问题

- custom `IAuthenticator` 如果没有实现 `legacyAuthenticate()`，JMX login 仍会失败；该 legacy hook 明确写在 `src/java/org/apache/cassandra/auth/IAuthenticator.java:100-113`，JMX login 使用在 `src/java/org/apache/cassandra/auth/CassandraLoginModule.java:141-145`。
- custom `IAuthorizer` 如果 `requireAuthorization()` 为 true，但 authenticator 仍是 allow-all，启动会在 `AuthConfig.applyAuth()` 中失败，见 `src/java/org/apache/cassandra/auth/AuthConfig.java:73-81`。
- custom `IRoleManager` 和 `PasswordAuthenticator` 不兼容；源码要求 password backend 必须使用 `CassandraRoleManager`，见 `src/java/org/apache/cassandra/auth/AuthConfig.java:85-90` 和 `src/java/org/apache/cassandra/auth/PasswordAuthenticator.java:59`。
- custom network/CIDR authorizer 也会在 authentication disabled 时被拒绝，见 `src/java/org/apache/cassandra/auth/AuthConfig.java:100-118`。
- cache warming 依赖 `AuthCache.BulkLoader`，如果 custom backend 不提供合适 bulk load，permission/role/network cache 仍可按 miss 加载，但启动预热和 active refresh 行为会不同，见 `src/java/org/apache/cassandra/auth/AuthCache.java:86-120`。

## 设计取舍

- Cassandra 的 SPI 是同步接口，简单直接，但 custom backend 的远程调用会直接落在 auth/cache miss 或 CQL DDL 路径上；高延迟后端必须靠 cache TTL、bulk loader 和 active update 缓冲。
- `IAuthorizer.grant/revoke/list/revokeAll*` 被注释为 optional，但 statement 层和 drop cleanup 仍会调用；不支持的实现应显式抛 `UnsupportedOperationException`，而不是静默成功。
- `IRoleManager.getRoleDetails()` 有默认实现，会调用 `getRoles(grantee, true)` 再逐个 `Roles.fromRoleResource()`；custom backend 若能批量查 detail，应覆盖它减少 N+1 查询。
- mTLS identity methods 是 `IRoleManager` default methods，老实现可编译，但 `MutualTlsAuthenticator` 依赖 `roleForIdentity()` / `authorizedIdentities()` 才能完成 identity -> role 映射，见 `src/java/org/apache/cassandra/auth/MutualTlsAuthenticator.java:150-208`。
- CIDR authorizer 不继承 `AuthCache.BulkLoader`，它有自己的 CIDR groups cache、permissions cache invalidation 和 metrics contract。

## 核心类

| 类 | 作用 |
|---|---|
| `AuthConfig` | 实例化配置的 auth backends、设置 `DatabaseDescriptor` 单例、执行跨 backend dependency gate 和 `validateConfiguration()`，见 `src/java/org/apache/cassandra/auth/AuthConfig.java:41-129`。 |
| `IAuthenticator` | native/JMX login SPI、SASL negotiator、protected resources 和 custom `AuthenticateMessage`，见 `src/java/org/apache/cassandra/auth/IAuthenticator.java:30-160`。 |
| `IAuthorizer` | resource permission SPI，覆盖 authorize/grant/revoke/list/drop cleanup，见 `src/java/org/apache/cassandra/auth/IAuthorizer.java:30-160`。 |
| `IRoleManager` | role/user lifecycle、membership、role detail、custom options、super/login checks 和 mTLS identity mapping，见 `src/java/org/apache/cassandra/auth/IRoleManager.java:35-285`。 |
| `INetworkAuthorizer` | role -> datacenter permissions SPI 和 cleanup hook，见 `src/java/org/apache/cassandra/auth/INetworkAuthorizer.java:23-60`。 |
| `ICIDRAuthorizer` | CIDR groups mapping、role CIDR permissions、cache invalidation、metrics 和 IP access decision，见 `src/java/org/apache/cassandra/auth/ICIDRAuthorizer.java:30-95`。 |
| `AuthCache` | permission/role/network/credential caches 的通用 wrapper，支持 load、bulk load、active update 和 MBean，见 `src/java/org/apache/cassandra/auth/AuthCache.java:55-120`。 |

## 核心接口

### `IAuthenticator` (`auth_spi_i_authenticator`)

- Methods: `requireAuthentication/0`, `protectedResources/0`, `validateConfiguration/0`, `setup/0`, `getAuthenticateMessage/1`, `newSaslNegotiator/1`, `newSaslNegotiator/2`, `legacyAuthenticate/1`
- `getAuthenticateMessage/1` 允许 custom authenticator 返回 driver 已知的 authenticator FQCN；测试 `CustomAuthenticatorTest` 覆盖该行为，见 `test/unit/org/apache/cassandra/auth/CustomAuthenticatorTest.java:39-48`。
- `newSaslNegotiator/2` 接收 peer certificate chain，mTLS authenticator 用它桥接 TLS cert 到 SASL auth，见 `src/java/org/apache/cassandra/auth/IAuthenticator.java:81-98` 和 `src/java/org/apache/cassandra/transport/ServerConnection.java:116-145`。
- `legacyAuthenticate/1` 仍是 JMX login 的兼容入口，不应返回 null。

### `IAuthenticator.SaslNegotiator` (`auth_spi_i_authenticator_sasl_negotiator`)

- Methods: `evaluateResponse/1`, `isComplete/0`, `getAuthenticatedUser/0`
- Native `AUTH_RESPONSE` 会反复调用 `evaluateResponse()`，再用 `isComplete()` 决定返回 `AuthChallenge` 或 `AuthSuccess`，契约写在 `src/java/org/apache/cassandra/auth/IAuthenticator.java:120-160`。
- `getAuthenticatedUser()` 只能在完成后返回非 null user；失败应抛 `AuthenticationException`。

### `IAuthorizer` (`auth_spi_i_authorizer`)

- Methods: `requireAuthorization/0`, `authorize/2`, `grant/4`, `revoke/4`, `list/4`, `revokeAllFrom/1`, `revokeAllOn/1`, `protectedResources/0`, `validateConfiguration/0`, `setup/0`
- `authorize/2` 是 hot path，`PermissionsCache` miss 时调用，见 `src/java/org/apache/cassandra/auth/PermissionsCache.java:28-52`。
- `grant/4`、`revoke/4`、`list/4` 支撑 CQL permission statements；不支持 mutation/list 的 backend 应显式抛 `UnsupportedOperationException`。
- `revokeAllFrom/1` 在 drop role 前清理 role permissions，`revokeAllOn/1` 在 resource drop 后清理 resource permissions，见接口注释 `src/java/org/apache/cassandra/auth/IAuthorizer.java:117-138`。

### `IRoleManager` (`auth_spi_i_role_manager`)

- Methods: `supportedOptions/0`, `alterableOptions/0`, `createRole/3`, `dropRole/2`, `alterRole/3`, `grantRole/3`, `revokeRole/3`, `getRoles/2`, `getRoleDetails/1`, `getAllRoles/0`, `isSuper/1`, `canLogin/1`, `getCustomOptions/1`, `isExistingRole/1`, `protectedResources/0`, `validateConfiguration/0`, `setup/0`, `roleForIdentity/1`, `authorizedIdentities/0`, `addIdentity/2`, `isExistingIdentity/1`, `dropIdentity/1`
- `supportedOptions()` 和 `alterableOptions()` drive CREATE/ALTER ROLE validation; custom role managers must reject unsupported `RoleOptions` predictably.
- `grantRole()` / `revokeRole()` own role inheritance; default `CassandraRoleManager` writes both `roles.member_of` and `role_members`,见 `src/java/org/apache/cassandra/auth/CassandraRoleManager.java:318-354`。
- `getRoleDetails()` default implementation is compatibility glue for older implementations; override it when role details can be loaded in one backend query.
- Identity methods back `ADD IDENTITY` / `DROP IDENTITY` and mTLS role lookup,见 `src/java/org/apache/cassandra/auth/IRoleManager.java:232-285`。

### `INetworkAuthorizer` (`auth_spi_i_network_authorizer`)

- Methods: `requireAuthorization/0`, `setup/0`, `authorize/1`, `setRoleDatacenters/2`, `drop/1`, `validateConfiguration/0`
- `authorize/1` is cache-backed through `NetworkPermissionsCache`,见 `src/java/org/apache/cassandra/auth/NetworkPermissionsCache.java:26-45`。
- `setRoleDatacenters/2` writes role DC permissions; `drop/1` is called when role data must be cleaned up.

### `ICIDRAuthorizer` (`auth_spi_i_cidr_authorizer`)

- Methods: `setup/0`, `initCaches/0`, `getCidrGroupsMappingManager/0`, `getCidrAuthorizerMetrics/0`, `requireAuthorization/0`, `setCidrGroupsForRole/2`, `dropCidrPermissionsForRole/1`, `invalidateCidrPermissionsCache/1`, `validateConfiguration/0`, `loadCidrGroupsCache/0`, `lookupCidrGroupsForIp/1`, `hasAccessFromIp/2`
- `CIDRAuthorizerMode` has `MONITOR` and `ENFORCE`; default Cassandra implementation reads mode from `cidr_authorizer_mode`,见 `src/java/org/apache/cassandra/auth/CassandraCIDRAuthorizer.java:42`。
- `hasAccessFromIp/2` is the final access decision for a role and client IP; monitor mode can record metrics without rejecting.

## 配置合同

### Backend keys (`auth_spi_backend_config_keys`)

- Config keys: `authenticator`, `authorizer`, `role_manager`, `network_authorizer`, `cidr_authorizer`, `internode_authenticator`
- These are `ParameterizedClass` fields in `Config`,见 `src/java/org/apache/cassandra/config/Config.java:82-87` 和 `src/java/org/apache/cassandra/config/Config.java:221`。
- `AuthConfig.authInstantiate()` resolves short names against `org.apache.cassandra.auth` and accepts fully-qualified class names,见 `src/java/org/apache/cassandra/auth/AuthConfig.java:131-148`。

### Dependency gates (`auth_spi_auth_config_dependency_gates`)

- `authorizer.requireAuthorization()` true requires `authenticator.requireAuthentication()` true; otherwise startup throws `ConfigurationException`，见 `src/java/org/apache/cassandra/auth/AuthConfig.java:73-81`。
- `PasswordAuthenticator` requires `CassandraRoleManager`; custom `IRoleManager` cannot be paired with password auth without changing the authenticator，见 `src/java/org/apache/cassandra/auth/AuthConfig.java:85-90`。
- `network_authorizer.requireAuthorization()` true and `cidr_authorizer.requireAuthorization()` true both require authentication enabled，见 `src/java/org/apache/cassandra/auth/AuthConfig.java:100-118`。
- Non-Password/non-mTLS authenticators with non-default credential cache settings only get an info log because those settings are only guaranteed for built-in credential caches，见 `src/java/org/apache/cassandra/auth/AuthConfig.java:56-67`。

### Cache/Bulk Loader (`auth_spi_cache_bulk_loader`)

- `IAuthorizer` and `IRoleManager` extend `AuthCache.BulkLoader`; `INetworkAuthorizer` also extends `AuthCache.BulkLoader<RoleResource, DCPermissions>`。
- `AuthCache` receives both single-key `loadFunction` and `bulkLoadFunction`, so custom backends can participate in warming without changing cache code，见 `src/java/org/apache/cassandra/auth/AuthCache.java:86-120`。
- Default `CassandraAuthorizer.bulkLoader()` and `CassandraRoleManager.bulkLoader()` are referenced by existing docs and tests,见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:454-510`、`src/java/org/apache/cassandra/auth/CassandraRoleManager.java:752-773`。

## 核心数据结构

| 数据结构 | 兼容含义 |
|---|---|
| `RoleResource` | role/user identifier shared by role manager, authorizer, network authorizer and CIDR authorizer. |
| `RoleOptions` / `IRoleManager.Option` | CREATE/ALTER ROLE option surface: `SUPERUSER`、`PASSWORD`、`LOGIN`、`OPTIONS`、`HASHED_PASSWORD`。 |
| `Permission` / `PermissionDetails` | permission enum and LIST PERMISSIONS row details used by authorizer implementations. |
| `IResource` | Data/Function/Role/JMX resource abstraction passed to `authorize()`、`grant()`、`revoke()` and cleanup hooks. |
| `DCPermissions` | network authorizer value object for role datacenter restrictions. |
| `CIDRPermissions` | CIDR authorizer value object for role CIDR group restrictions. |

## 生命周期

Startup:

```text
CassandraDaemon.setup()
  -> DatabaseDescriptor.applyAll()
  -> AuthConfig.applyAuth()
     -> instantiate authenticator / authorizer / role_manager / internode_authenticator / network_authorizer / cidr_authorizer
     -> apply dependency gates
     -> DatabaseDescriptor.set* singletons
     -> validateConfiguration() on every backend
  -> later setup paths initialize system_auth and caches
```

Native login:

```text
client STARTUP
  -> server returns AuthenticateMessage from IAuthenticator.getAuthenticateMessage()
client AUTH_RESPONSE
  -> IAuthenticator.newSaslNegotiator(clientAddress[, certificates])
  -> SaslNegotiator.evaluateResponse()
  -> isComplete()
  -> getAuthenticatedUser()
  -> ClientState.login()
```

Permission check:

```text
CQL statement authorize()
  -> ClientState.ensurePermission()
  -> PermissionsCache.getPermissions(user, resource)
  -> IAuthorizer.authorize(user, resource) on cache miss
```

Role DDL:

```text
CREATE/ALTER/DROP/GRANT/REVOKE ROLE
  -> RoleOptions validated against IRoleManager.supportedOptions()/alterableOptions()
  -> IRoleManager lifecycle or membership method
  -> cache invalidation / authorizer cleanup where needed
```

## Metrics

- `AuthCache` registers MBeans under `org.apache.cassandra.auth:type=...` and exposes cache validity, update interval, max entries and active update controls，见 `src/java/org/apache/cassandra/auth/AuthCache.java:55-120`。
- CIDR authorizer exposes dedicated `CIDRAuthorizerMetrics` through `ICIDRAuthorizer.getCidrAuthorizerMetrics()`，见 `src/java/org/apache/cassandra/auth/ICIDRAuthorizer.java:48-50`。
- Auth failures also appear in client request/native protocol metrics indirectly through failed authentication responses; the SPI itself does not define a metric interface for custom authenticators.

## 日志

- `AuthConfig` logs when credential cache settings may not apply to a custom authenticator，见 `src/java/org/apache/cassandra/auth/AuthConfig.java:56-67`。
- Startup dependency gate violations throw `ConfigurationException`; they are configuration errors, not runtime warnings.
- Default role manager logs password change throttling info/warn on alter role path，见 `src/java/org/apache/cassandra/auth/CassandraRoleManager.java:658-671`。

## 运维关注点

- Enabling a custom authorizer without real authentication is invalid; use a real authenticator first, then switch authorizer/network/CIDR backends.
- A custom role manager paired with mTLS should implement the identity methods, otherwise `ADD IDENTITY` may succeed only if statements are blocked elsewhere and mTLS role lookup can return null.
- `protectedResources()` must include any backend-owned tables/resources that should not be user-modifiable; default implementations protect `system_auth` resources.
- Remote custom backends should set conservative cache validity/update intervals and implement bulk loading where possible; otherwise role/permission cache miss latency becomes query latency.
- JMX authentication uses `legacyAuthenticate()`; do not validate only native protocol SASL during rollout.

## 性能瓶颈

- `IAuthorizer.authorize()` and `IRoleManager.getRoleDetails()` are cache miss paths; slow remote calls increase p99 for authorization-heavy workloads.
- `IRoleManager.getRoleDetails()` default implementation can become N+1 over inherited roles if custom backend does not override it.
- `IAuthorizer.list()` can scan large permission sets when resource/grantee are null; custom backends should implement filtered queries rather than full scans where possible.
- CIDR lookup must be cheap on connect; large CIDR group maps should be cached and measured through `CIDRAuthorizerMetrics`。

## 常见故障

- Startup fails with authorization enabled: authenticator likely returns `requireAuthentication=false` while authorizer/network/CIDR authorizer requires authorization.
- Password auth with custom role manager fails at startup: `PasswordAuthenticator` requires `CassandraRoleManager`。
- Native auth works but JMX login fails: custom authenticator likely omitted `legacyAuthenticate()` behavior.
- mTLS cert accepted but role is anonymous/null: custom role manager did not implement `roleForIdentity()` or identity cache data is empty.
- Permission changes appear delayed: cache validity/update interval and bulk loader behavior may be masking backend state.

## 测试用例

- `CustomAuthenticatorTest` covers custom `getAuthenticateMessage()` FQCN override，见 `test/unit/org/apache/cassandra/auth/CustomAuthenticatorTest.java:39-48`。
- `AuthConfigTest` covers `ParameterizedClass` instantiation for mTLS client and internode authenticators，见 `test/unit/org/apache/cassandra/auth/AuthConfigTest.java:49-93`。
- `PasswordAuthenticatorTest` covers credential cache bulk load and `AuthenticateMessage` name，见 `test/unit/org/apache/cassandra/auth/PasswordAuthenticatorTest.java:191-208`。
- `CassandraAuthorizerTest` / `CassandraAuthorizerTruncatingTest` cover grant/list/cache bulk load and cleanup behavior，见 `test/unit/org/apache/cassandra/auth/CassandraAuthorizerTest.java:29`、`test/unit/org/apache/cassandra/auth/CassandraAuthorizerTruncatingTest.java:92-115`。
- `CassandraRoleManagerTest` covers role lifecycle and membership behavior，见 `test/unit/org/apache/cassandra/auth/CassandraRoleManagerTest.java:44`。
- `AddIdentityStatementTest` and `DropIdentityStatementTest` cover mTLS identity statement integration with `IRoleManager`，见 `test/unit/org/apache/cassandra/cql3/statements/AddIdentityStatementTest.java:85-190`、`test/unit/org/apache/cassandra/cql3/statements/DropIdentityStatementTest.java:75-155`。
- `CassandraNetworkAuthorizerTest` and CIDR authorizer tests cover network/CIDR permission behavior，见 `test/unit/org/apache/cassandra/auth/CassandraNetworkAuthorizerTest.java:113`、`test/unit/org/apache/cassandra/auth/CassandraCIDRAuthorizerMonitorModeTest.java:125`、`test/unit/org/apache/cassandra/auth/CassandraCIDRAuthorizerEnforceModeTest.java:311`。

## Drift Checker

- `python3 research/tools/check-auth-spi-drift.py` verifies method surfaces for `IAuthenticator`、`IAuthenticator.SaslNegotiator`、`IAuthorizer`、`IRoleManager`、`INetworkAuthorizer`、`ICIDRAuthorizer` and the backend config/dependency gate contract.
- `python3 research/tools/check-auth-spi-drift.py --json` emits parsed methods, expected baselines and doc misses for CI/artifact use.
