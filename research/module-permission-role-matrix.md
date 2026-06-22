# Permission And Role Matrix 源码研究

## 范围

本文补齐权限模块的第四轮源码缺口，聚焦 CQL resource permission 矩阵、`GRANT ROLE`/`REVOKE ROLE` 角色继承、`LIST PERMISSIONS` 可见性、默认 `CassandraAuthorizer`/`CassandraRoleManager` 存储结构、auth cache 观测与测试覆盖。

custom authenticator/authorizer/role manager/network/CIDR authorizer 的 SPI method surface、启动 gate、cache/bulk-load 合同和兼容性风险见 `research/module-auth-spi-compatibility-matrix.md`，并由 `research/tools/check-auth-spi-drift.py` 做 source-only drift check。

本矩阵的默认 permission/resource/role/backend/cache 合同由 `research/tools/check-permission-role-drift.py` 做 source-only drift check，checker 说明见 `research/module-permission-role-drift-checker.md`。

不展开 password/mTLS/CIDR/network authorizer 的登录细节；这些已在 `research/module-schema-cql-auth-native-deep-dive.md` 与 `research/module-schema-cql-auth-native-third-round.md` 覆盖。

## Source Contract

| Scenario | Contract | Source anchors | Test anchors |
| --- | --- | --- | --- |
| `permission_role_enum_order_contract` | `Permission` enum 顺序是序列化/自定义 authorizer 兼容合同；新增 permission 只能追加，并同步 `Permission.ALL`、resource permission set、语法和行为测试。 | `src/java/org/apache/cassandra/auth/Permission.java:32`, `src/java/org/apache/cassandra/auth/Permission.java:64` | `test/unit/org/apache/cassandra/cql3/validation/miscellaneous/RoleSyntaxTest.java:116` |
| `permission_role_resource_matrix_contract` | `DataResource`、`FunctionResource`、`RoleResource`、`JMXResource` 自己声明 grantable permission set，statement 层只负责 validate/authorize。 | `src/java/org/apache/cassandra/auth/DataResource.java:45`, `src/java/org/apache/cassandra/auth/FunctionResource.java:56`, `src/java/org/apache/cassandra/auth/RoleResource.java:43`, `src/java/org/apache/cassandra/auth/JMXResource.java:42` | `test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java:75`, `test/unit/org/apache/cassandra/auth/FunctionResourceTest.java:34`, `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java` |
| `permission_role_grant_revoke_statement_contract` | Permission GRANT/REVOKE 必须验证登录、grantee、resource、`AUTHORIZE` 和目标 permission，再调用 `IAuthorizer.grant/revoke`。 | `src/java/org/apache/cassandra/cql3/statements/PermissionsManagementStatement.java:45`, `src/java/org/apache/cassandra/cql3/statements/GrantPermissionsStatement.java:63`, `src/java/org/apache/cassandra/cql3/statements/RevokePermissionsStatement.java:45` | `test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java:75`, `test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java:386` |
| `permission_role_system_keyspace_guard_contract` | 非 virtual system keyspace/table 只能授予 `SELECT`、`DESCRIBE`、`ALTER` 等允许权限；ALL KEYSPACES 对普通用户不覆盖 system keyspace 写权限。 | `src/java/org/apache/cassandra/cql3/statements/GrantPermissionsStatement.java:47`, `src/java/org/apache/cassandra/auth/Permission.java:69`, `src/java/org/apache/cassandra/service/ClientState.java:485` | `test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java:411`, `test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java:438` |
| `permission_role_membership_contract` | Role GRANT/REVOKE 与 resource permission 分开：`RoleManagementStatement` 只要求 actor 对被操作 role 有 `AUTHORIZE`，默认 role manager 同步 `roles.member_of` 和 `role_members`，并拒绝重复/循环 membership。 | `src/java/org/apache/cassandra/cql3/statements/RoleManagementStatement.java:42`, `src/java/org/apache/cassandra/auth/CassandraRoleManager.java:318`, `src/java/org/apache/cassandra/auth/CassandraRoleManager.java:339` | `test/unit/org/apache/cassandra/auth/CassandraRoleManagerTest.java:70`, `test/unit/org/apache/cassandra/auth/CassandraRoleManagerTest.java:124` |
| `permission_role_list_visibility_contract` | `LIST PERMISSIONS` 可递归列 resource parent chain；默认 authorizer 对非 super/system/self 请求者要求 root role 或 grantee role 的 `DESCRIBE`。 | `src/java/org/apache/cassandra/cql3/statements/ListPermissionsStatement.java:67`, `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:311` | `test/unit/org/apache/cassandra/auth/CassandraAuthorizerTest.java:46`, `test/unit/org/apache/cassandra/cql3/validation/miscellaneous/RoleSyntaxTest.java:159` |
| `permission_role_backend_storage_contract` | 默认 backend 使用 `system_auth.roles`、`role_members`、`role_permissions` 和保留拼写的 `resource_role_permissons_index`；grant/revoke/drop cleanup 必须同时维护正向 permission set 与反向 resource lookup。 | `src/java/org/apache/cassandra/auth/AuthKeyspace.java:56`, `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:97`, `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:130` | `test/unit/org/apache/cassandra/auth/CassandraAuthorizerTruncatingTest.java:72` |
| `permission_role_auth_chain_contract` | 普通授权沿 resource parent chain 查找；`traverse_auth_from_root` 可反转查找顺序；system keyspace 对 ordinary user 使用受限 chain。 | `src/java/org/apache/cassandra/service/ClientState.java:451`, `src/java/org/apache/cassandra/service/ClientState.java:523`, `conf/cassandra.yaml:284` | `test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java:438` |
| `permission_role_cache_contract` | Permissions/Roles cache 包装 backend miss path、bulk loader、validity/update/max entries/active update MBean 和 remote config guard；权限回收受 cache TTL 与 invalidation 影响。 | `src/java/org/apache/cassandra/auth/PermissionsCache.java:25`, `src/java/org/apache/cassandra/auth/RolesCache.java:26`, `src/java/org/apache/cassandra/auth/AuthCache.java:268`, `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:454`, `src/java/org/apache/cassandra/auth/CassandraRoleManager.java:752` | `test/unit/org/apache/cassandra/auth/RolesTest.java:64`, `test/unit/org/apache/cassandra/auth/CassandraRoleManagerTest.java:124`, `test/unit/org/apache/cassandra/auth/CassandraAuthorizerTruncatingTest.java:72` |
| `permission_role_virtual_cache_keys_contract` | `system_views.permissions_cache_keys` 与 `roles_cache_keys` 暴露 cache key 并支持 partition delete/truncate invalidation，invalid resource delete no-op。 | `src/java/org/apache/cassandra/db/virtual/PermissionsCacheKeysTable.java:28`, `src/java/org/apache/cassandra/db/virtual/RolesCacheKeysTable.java:26` | `test/unit/org/apache/cassandra/db/virtual/PermissionsCacheKeysTableTest.java:84`, `test/unit/org/apache/cassandra/db/virtual/RolesCacheKeysTableTest.java:69` |
| `permission_role_audit_warning_contract` | Grant/revoke/list/role statements 必须保留 audit context；重复 grant 或 missing revoke 通过 `ClientWarn` 返回 warning。 | `src/java/org/apache/cassandra/cql3/statements/GrantPermissionsStatement.java:69`, `src/java/org/apache/cassandra/cql3/statements/RevokePermissionsStatement.java:50`, `src/java/org/apache/cassandra/cql3/statements/ListPermissionsStatement.java:139`, `src/java/org/apache/cassandra/cql3/statements/GrantRoleStatement.java:47` | `test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java:386` |
| `permission_role_existing_tests_baseline` | 现有 tests 覆盖 keyspace/all tables/system/virtual keyspace grants、identity permission、LIST 可见性、cache bulk-load、role cache 和 permission syntax。 | `test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java`, `test/unit/org/apache/cassandra/auth/CassandraAuthorizerTest.java`, `test/unit/org/apache/cassandra/auth/CassandraRoleManagerTest.java`, `test/unit/org/apache/cassandra/cql3/validation/miscellaneous/RoleSyntaxTest.java` | same |
| `permission_role_spi_boundary` | 本矩阵只保护默认 permission/role backend 语义；custom backend method surface、startup gate 和 SPI 兼容由 auth SPI matrix/checker 保护。 | `research/module-auth-spi-compatibility-matrix.md`, `research/tools/check-auth-spi-drift.py` | `test/unit/org/apache/cassandra/auth/StubAuthorizer.java` |

## 设计目标

- 权限枚举要同时服务 data/schema、role management、permission management、UDF、masking 与 JMX authorization。`Permission` 固定 enum 顺序，并定义 `CREATE`、`ALTER`、`DROP`、`SELECT`、`MODIFY`、`AUTHORIZE`、`DESCRIBE`、`EXECUTE`、`UNMASK`、`SELECT_MASKED`，见 `src/java/org/apache/cassandra/auth/Permission.java:32-75`。
- Resource 自己声明可授予权限，避免 statement 层硬编码所有组合。`DataResource`、`FunctionResource`、`RoleResource`、`JMXResource` 分别在 `applicablePermissions()` 所属类中定义权限集合，见 `src/java/org/apache/cassandra/auth/DataResource.java:45-72`、`src/java/org/apache/cassandra/auth/FunctionResource.java:56-72`、`src/java/org/apache/cassandra/auth/RoleResource.java:43-53`、`src/java/org/apache/cassandra/auth/JMXResource.java:42-47`。
- Permission grant/revoke 要求 actor 同时拥有目标 resource 的 `AUTHORIZE` 与被授予或撤销的具体 permission，见 `src/java/org/apache/cassandra/cql3/statements/PermissionsManagementStatement.java:61-72`。
- Role grant/revoke 与 resource permission 分开建模：role membership 由 `IRoleManager.grantRole/revokeRole` 写 `system_auth.roles.member_of` 和 `system_auth.role_members`，resource permissions 由 `IAuthorizer.grant/revoke` 写 `system_auth.role_permissions` 和 `resource_role_permissons_index`，见 `src/java/org/apache/cassandra/auth/CassandraRoleManager.java:318-354`、`src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:97-128`、`src/java/org/apache/cassandra/auth/AuthKeyspace.java:56-114`。
- 普通授权检查要沿 resource parent chain 查找，且 `traverse_auth_from_root` 可控制从子到父或从父到子遍历，见 `src/java/org/apache/cassandra/service/ClientState.java:523-541` 与 `conf/cassandra.yaml:289`。

## 解决的问题

- Resource 层级解决“一次授权覆盖多个对象”的问题：`data` 覆盖 keyspace/table，`data/<ks>/*` 覆盖 keyspace 内所有表，`functions` 覆盖 UDF/UDA 集合，`roles` 覆盖 role 管理，见 `src/java/org/apache/cassandra/auth/DataResource.java:35-36`、`src/java/org/apache/cassandra/auth/FunctionResource.java:44-47`、`src/java/org/apache/cassandra/auth/RoleResource.java:43-53`。
- `GRANT`/`REVOKE` 的双重权限检查解决了委托授权边界：只有能 `AUTHORIZE` 且自己已经拥有目标 permission 的 actor 才能把该 permission 给别人或收回，见 `src/java/org/apache/cassandra/cql3/statements/PermissionsManagementStatement.java:66-71`。
- 默认 authorizer 的反向索引解决了 drop cleanup：drop role 走 `revokeAllFrom()` 删除 role 的 permission 行和 reverse index，drop resource 走 `revokeAllOn()` 删除 resource 上所有 role grants，见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:130-190`。
- Role inheritance 解决了权限复用：`CassandraAuthorizer.authorize()` 对用户的 role closure 逐个读取 direct permissions 后合并，见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:73-88`；role closure 由 `CassandraRoleManager.collectRoles()` 递归展开，见 `src/java/org/apache/cassandra/auth/CassandraRoleManager.java:520-541`。
- `LIST PERMISSIONS` 解决了可审计性，但通过 role `DESCRIBE` 限制跨用户查看。非 super/system/self 请求者必须有 root role 或 grantee role 的 `DESCRIBE`，见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:311-337`。
- 系统 keyspace 限制解决了“ALL KEYSPACES 误写系统表”的问题：非 virtual system keyspace/table 不能授予 `Permission.INVALID_FOR_SYSTEM_KEYSPACES` 中的权限，见 `src/java/org/apache/cassandra/cql3/statements/GrantPermissionsStatement.java:47-61` 与 `src/java/org/apache/cassandra/auth/Permission.java:69-75`。

## 设计取舍

- Permission matrix 放在 resource 类而不是 CQL grammar 中，优点是新增 resource 时可以局部定义 `applicablePermissions()`；代价是语法允许的组合仍要到 validation/authorization 阶段才能失败。
- Role grant 只要求 actor 对被授予的 role 有 `AUTHORIZE`，不要求对 grantee role 有额外权限；授权点在 `RoleManagementStatement.authorize()`，实际 membership 写入在 `GrantRoleStatement.execute()`，见 `src/java/org/apache/cassandra/cql3/statements/RoleManagementStatement.java:42-45`、`src/java/org/apache/cassandra/cql3/statements/GrantRoleStatement.java:38-41`。
- `CassandraRoleManager.grantRole()` 在写入前检查双向 membership closure，避免直接重复和循环继承；这需要读取 role closure，见 `src/java/org/apache/cassandra/auth/CassandraRoleManager.java:318-328`。
- `LIST PERMISSIONS` 按 resource 且不指定 grantee 时使用 `ALLOW FILTERING` 查询 `role_permissions`，这是为了支持按 resource 审计；性能上更推荐按 role/resource 精确查询，见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:363-380`。
- Permission cache 与 roles cache 默认短 TTL，降低 system_auth 读放大；代价是 grant/revoke 生效可能受 cache validity、async refresh 和手动 invalidation 影响，见 `src/java/org/apache/cassandra/auth/PermissionsCache.java:28-47`、`src/java/org/apache/cassandra/auth/RolesCache.java:30-45`、`conf/cassandra.yaml:300-345`。

## 核心类

| 类 | 作用 |
|---|---|
| `Permission` | 全部 permission 枚举、`ALL`、`NONE`、system keyspace denylist，见 `src/java/org/apache/cassandra/auth/Permission.java:32-75` |
| `DataResource` | `data`/keyspace/all-tables/table 层级和 data permission set，见 `src/java/org/apache/cassandra/auth/DataResource.java:45-72`、`src/java/org/apache/cassandra/auth/DataResource.java:181-192` |
| `FunctionResource` | `functions`/keyspace/function 层级，collection 支持 `CREATE/ALTER/DROP/AUTHORIZE/EXECUTE`，function 支持 `ALTER/DROP/AUTHORIZE/EXECUTE`，见 `src/java/org/apache/cassandra/auth/FunctionResource.java:56-72` |
| `RoleResource` | `roles` root 与 `roles/<role>`，root 支持 `CREATE/ALTER/DROP/AUTHORIZE/DESCRIBE`，role 支持 `ALTER/DROP/AUTHORIZE/DESCRIBE`，见 `src/java/org/apache/cassandra/auth/RoleResource.java:43-53` |
| `JMXResource` | JMX MBean resource，支持 `AUTHORIZE/DESCRIBE/EXECUTE/MODIFY/SELECT`，见 `src/java/org/apache/cassandra/auth/JMXResource.java:42-47` |
| `PermissionsManagementStatement` | GRANT/REVOKE 共用 validate/authorize：登录、grantee 存在、resource 修正和存在、`AUTHORIZE` 加目标 permission 检查，见 `src/java/org/apache/cassandra/cql3/statements/PermissionsManagementStatement.java:45-72` |
| `GrantPermissionsStatement` / `RevokePermissionsStatement` | 调用 authorizer grant/revoke、client warning、audit context，见 `src/java/org/apache/cassandra/cql3/statements/GrantPermissionsStatement.java:47-92`、`src/java/org/apache/cassandra/cql3/statements/RevokePermissionsStatement.java:45-80` |
| `ListPermissionsStatement` | 验证 resource/grantee，递归列出 parent chain，并把 `PermissionDetails` 转为 rows，见 `src/java/org/apache/cassandra/cql3/statements/ListPermissionsStatement.java:67-125` |
| `RoleManagementStatement` / `GrantRoleStatement` / `RevokeRoleStatement` | role grant/revoke statement 骨架和执行入口，见 `src/java/org/apache/cassandra/cql3/statements/RoleManagementStatement.java:31-56`、`src/java/org/apache/cassandra/cql3/statements/GrantRoleStatement.java:31-41`、`src/java/org/apache/cassandra/cql3/statements/RevokeRoleStatement.java:31-41` |
| `ClientState` | 资源链授权、system keyspace 保护、auth protected resources 保护，见 `src/java/org/apache/cassandra/service/ClientState.java:451-541` |
| `CassandraAuthorizer` | 默认 permission backend：authorize/grant/revoke/list/revokeAll/cache bulk load，见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:73-128`、`src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:311-337`、`src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:454-510` |
| `CassandraRoleManager` | 默认 role backend：role lifecycle、membership、closure、cache bulk load，见 `src/java/org/apache/cassandra/auth/CassandraRoleManager.java:263-360`、`src/java/org/apache/cassandra/auth/CassandraRoleManager.java:752-773` |

## 核心接口

- `IResource.getName()/getParent()/exists()/applicablePermissions()`：resource 层级和 grantable permission 的统一接口；各实现见 `DataResource`、`FunctionResource`、`RoleResource`、`JMXResource`。
- `IAuthorizer.authorize/grant/revoke/list/revokeAllFrom/revokeAllOn`：statement 层不关心后端表结构，只依赖 authorizer 接口，见 `src/java/org/apache/cassandra/auth/IAuthorizer.java:28-138`。
- `IRoleManager.createRole/alterRole/dropRole/grantRole/revokeRole/getRoles/getRoleDetails`：role lifecycle 与 inherited role closure 接口，见 `src/java/org/apache/cassandra/auth/IRoleManager.java:60-145`。
- `AuthCache.BulkLoader`：authorizer 和 role manager 可提供启动预热数据，permission cache bulk load 见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:454-510`，roles cache bulk load 见 `src/java/org/apache/cassandra/auth/CassandraRoleManager.java:752-773`。
- `PermissionsCacheMBean` 与 `RolesCacheMBean`：继承 `AuthCacheMBean`，暴露 validity/update interval/max entries/active update/estimated size 和 invalidation 能力，见 `src/java/org/apache/cassandra/auth/PermissionsCacheMBean.java:21-24`、`src/java/org/apache/cassandra/auth/RolesCacheMBean.java:21-24`、`src/java/org/apache/cassandra/auth/AuthCache.java:268-315`。

## 核心数据结构

- Permission enum：`CREATE/ALTER/DROP` 用于 schema 和 role management，`SELECT/MODIFY` 用于 data access，`AUTHORIZE` 用于 grant/revoke，`DESCRIBE` 用于 roles listing，`EXECUTE` 用于 UDF/UDA，`UNMASK/SELECT_MASKED` 用于动态数据脱敏，见 `src/java/org/apache/cassandra/auth/Permission.java:34-63`。
- Data resource 名称：`data`、`data/<keyspace>`、`data/<keyspace>/*`、`data/<keyspace>/<table>`；parent chain 是 table -> all tables -> keyspace -> root，见 `src/java/org/apache/cassandra/auth/DataResource.java:35-36`、`src/java/org/apache/cassandra/auth/DataResource.java:181-192`。
- Function resource 名称：`functions`、`functions/<keyspace>`、`functions/<keyspace>/<function>[arg_types]`，见 `src/java/org/apache/cassandra/auth/FunctionResource.java:44-47`、`src/java/org/apache/cassandra/auth/FunctionResource.java:217-227`。
- Role resource 名称：`roles` 与 `roles/<role>`，单个 role parent 是 root，见 `src/java/org/apache/cassandra/auth/RoleResource.java:55-115`、`src/java/org/apache/cassandra/auth/RoleResource.java:132-152`。
- `system_auth.roles`：`role`、`is_superuser`、`can_login`、`salted_hash`、`member_of`，保存 role 属性和直接 granted roles，见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:71-80`。
- `system_auth.role_members`：`role, member` 反查哪些 role 被授予给哪些 member，见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:91-97`。
- `system_auth.role_permissions`：`role, resource, permissions set<text>`，保存直接 permission grants，见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:99-106`。
- `system_auth.resource_role_permissons_index`：`resource, role` 反向索引，表名保留源码里的拼写，见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:56-60`、`src/java/org/apache/cassandra/auth/AuthKeyspace.java:108-114`。
- `PermissionDetails`：`LIST PERMISSIONS` 的 role/resource/permission 行模型，由 `CassandraAuthorizer.listPermissionsForRole()` 构造，见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:340-360`。

## 生命周期

Resource permission GRANT：

1. Parser 生成 `GrantPermissionsStatement`。
2. `PermissionsManagementStatement.validate()` 要求非 anonymous，检查 grantee role 存在，修正未指定 keyspace 的 table resource，并确认 resource 存在，见 `src/java/org/apache/cassandra/cql3/statements/PermissionsManagementStatement.java:45-59`。
3. `GrantPermissionsStatement.validate()` 对非 virtual system keyspace/table 套用 system keyspace denylist，见 `src/java/org/apache/cassandra/cql3/statements/GrantPermissionsStatement.java:47-61`。
4. `authorize()` 要求 actor 对 resource chain 拥有 `AUTHORIZE` 与每个目标 permission，见 `src/java/org/apache/cassandra/cql3/statements/PermissionsManagementStatement.java:61-72`。
5. `CassandraAuthorizer.grant()` 读取 existing permissions，只把新增权限写入 `role_permissions`，并添加 `resource_role_permissons_index`，见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:97-111`、`src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:275-308`。

Resource permission REVOKE：

1. validate/authorize 与 grant 共用同一基类。
2. `RevokePermissionsStatement.execute()` 调用 `CassandraAuthorizer.revoke()`，见 `src/java/org/apache/cassandra/cql3/statements/RevokePermissionsStatement.java:45-49`。
3. 后端只移除确实存在的权限，并删除 reverse index entry，见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:114-128`、`src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:289-297`。
4. 如果 revoke 未命中全部请求权限且请求不是 `ALL`，通过 `ClientWarn` 返回 warning，见 `src/java/org/apache/cassandra/cql3/statements/RevokePermissionsStatement.java:50-63`。

Role grant/revoke：

1. `RoleManagementStatement.validate()` 要求 actor 已登录且 role/grantee 都存在，见 `src/java/org/apache/cassandra/cql3/statements/RoleManagementStatement.java:47-56`。
2. `RoleManagementStatement.authorize()` 要求 actor 对被授予或撤销的 role 有 `AUTHORIZE`，见 `src/java/org/apache/cassandra/cql3/statements/RoleManagementStatement.java:42-45`。
3. `GrantRoleStatement.execute()` 调用 `IRoleManager.grantRole()`；默认实现先检查重复/循环 membership，再更新 grantee 的 `roles.member_of` 并插入 `role_members(role, member)`，见 `src/java/org/apache/cassandra/cql3/statements/GrantRoleStatement.java:38-41`、`src/java/org/apache/cassandra/auth/CassandraRoleManager.java:318-337`。
4. `RevokeRoleStatement.execute()` 调用 `IRoleManager.revokeRole()`；默认实现要求 revokee 是该 role 的直接成员，然后从两处 membership 结构移除，见 `src/java/org/apache/cassandra/cql3/statements/RevokeRoleStatement.java:38-41`、`src/java/org/apache/cassandra/auth/CassandraRoleManager.java:339-354`。

LIST PERMISSIONS：

1. `ListPermissionsStatement.validate()` 要求登录，检查 resource 存在和 grantee 存在，见 `src/java/org/apache/cassandra/cql3/statements/ListPermissionsStatement.java:67-80`。
2. 如果指定 `RECURSIVE` resource，statement 对 `Resources.chain(resource)` 的每个 resource 调用 authorizer list，见 `src/java/org/apache/cassandra/cql3/statements/ListPermissionsStatement.java:88-104`。
3. `CassandraAuthorizer.list()` 对非 super/system/self actor 施加 `DESCRIBE` gate，再对 grantee 的 inherited roles 展开 permission details，见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:311-337`。

Auth cache lifecycle：

1. `AuthCacheService.initializeAndRegisterCaches()` 注册 `AuthenticatedUser.permissionsCache` 与 `Roles.cache`，见 `src/java/org/apache/cassandra/auth/AuthCacheService.java:55-76`、`src/java/org/apache/cassandra/auth/AuthenticatedUser.java:41-54`、`src/java/org/apache/cassandra/auth/Roles.java:36-43`。
2. `PermissionsCache.getPermissions()` 以 `(AuthenticatedUser, IResource)` 为 key，cache miss 时调用 `IAuthorizer.authorize()`，见 `src/java/org/apache/cassandra/auth/PermissionsCache.java:28-52`。
3. `RolesCache` 以 primary `RoleResource` 为 key，cache miss 时调用 `IRoleManager.getRoleDetails()`，见 `src/java/org/apache/cassandra/auth/RolesCache.java:30-64`。
4. 启用 auth cache warming 时，authorizer/role manager bulk loader 可预填 inherited permission/role closure，见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:454-510`、`src/java/org/apache/cassandra/auth/CassandraRoleManager.java:752-773`、`conf/cassandra.yaml:1965`。

## 调用链

Permission check during statement authorization：

```text
statement.authorize(clientState)
  -> ClientState.ensure*Permission(permission, resource)
  -> validateLogin()
  -> reject protected auth schema DDL / restricted system keyspace DDL
  -> ensurePermission(permission, resource)
  -> Resources.chain(resource)
  -> maybe reverse chain if traverse_auth_from_root=true
  -> AuthenticatedUser.getPermissions(resource)
  -> PermissionsCache.get(user, resource)
  -> CassandraAuthorizer.authorize(user, resource)
  -> for each inherited role: SELECT permissions FROM system_auth.role_permissions
```

Resource permission grant：

```text
GRANT <permissions> ON <resource> TO <role>
  -> PermissionsManagementStatement.validate()
  -> GrantPermissionsStatement.validate()
  -> PermissionsManagementStatement.authorize()
     -> ensure AUTHORIZE on resource chain
     -> ensure each target permission on resource chain
  -> CassandraAuthorizer.grant()
  -> UPDATE system_auth.role_permissions
  -> INSERT system_auth.resource_role_permissons_index
```

Role grant：

```text
GRANT <role> TO <grantee>
  -> RoleManagementStatement.validate()
  -> RoleManagementStatement.authorize()
     -> AUTHORIZE on RoleResource.role(<role>)
  -> GrantRoleStatement.execute()
  -> CassandraRoleManager.grantRole()
     -> reject duplicate/circular membership
     -> UPDATE system_auth.roles SET member_of += <role> WHERE role=<grantee>
     -> INSERT system_auth.role_members(role, member)
```

LIST PERMISSIONS：

```text
LIST [permissions] ON [resource] OF [role]
  -> ListPermissionsStatement.validate()
  -> if recursive: Resources.chain(resource)
  -> CassandraAuthorizer.list()
     -> super/system/self/DESCRIBE visibility gate
     -> DatabaseDescriptor.getRoleManager().getRoles(grantee, true)
     -> SELECT role, resource, permissions FROM system_auth.role_permissions
     -> PermissionDetails rows
```

## 配置项

| 配置项 | 作用 | 证据 |
|---|---|---|
| `authorizer` | 是否启用 CassandraAuthorizer 或 AllowAllAuthorizer；CassandraAuthorizer 使用 `system_auth.role_permissions` | `conf/cassandra.yaml:211-217` |
| `role_manager` | role lifecycle 和 role grant/revoke 后端；默认 `CassandraRoleManager` 使用 `system_auth` | `conf/cassandra.yaml:219-232` |
| `traverse_auth_from_root` | resource chain 从 root 到 leaf 或 leaf 到 root 查询 | `conf/cassandra.yaml:284-289`、`src/java/org/apache/cassandra/service/ClientState.java:528-536` |
| `roles_validity` / `roles_update_interval` / `roles_cache_active_update` / `roles_cache_max_entries` | roles cache TTL、refresh、主动更新和容量 | `conf/cassandra.yaml:300-318`、`src/java/org/apache/cassandra/auth/RolesCache.java:30-45` |
| `permissions_validity` / `permissions_update_interval` / `permissions_cache_active_update` / `permissions_cache_max_entries` | permissions cache TTL、refresh、主动更新和容量 | `conf/cassandra.yaml:327-345`、`src/java/org/apache/cassandra/auth/PermissionsCache.java:28-47` |
| `auth_read_consistency_level` / `auth_write_consistency_level` | `system_auth` 读写一致性级别，默认读 LOCAL_QUORUM、写 EACH_QUORUM | `conf/cassandra.yaml:1960-1961`、`src/java/org/apache/cassandra/auth/AuthProperties.java:26-55` |
| `auth_cache_warming_enabled` | 启动完成前预热 auth caches，减少 reconnect herd 的 cache miss | `conf/cassandra.yaml:1965`、`src/java/org/apache/cassandra/service/CassandraDaemon.java:447-448` |

## Metrics

- Permission/role authorization 没有专属 per-resource metrics；主要观测面是 auth cache MBean、virtual table cache key、auth backend日志和 client unauthorized/warning。
- `AuthCache` MBean 暴露 validity、update interval、max entries、active update、estimated size 和 invalidation 操作，见 `src/java/org/apache/cassandra/auth/AuthCache.java:268-315`。
- `PermissionsCache` 与 `RolesCache` 分别注册为 `PermissionsCache`、`RolesCache` MBean，见 `src/java/org/apache/cassandra/auth/PermissionsCacheMBean.java:21-24`、`src/java/org/apache/cassandra/auth/RolesCacheMBean.java:21-24`。
- `system_views.permissions_cache_keys` 显示 `(role, resource)` cache keys，并支持 delete/truncate invalidation，见 `src/java/org/apache/cassandra/db/virtual/PermissionsCacheKeysTable.java:28-70` 与测试 `test/unit/org/apache/cassandra/db/virtual/PermissionsCacheKeysTableTest.java:84-155`。
- `system_views.roles_cache_keys` 显示 role cache keys，并支持 delete/truncate invalidation，见 `src/java/org/apache/cassandra/db/virtual/RolesCacheKeysTable.java:26-58` 与测试 `test/unit/org/apache/cassandra/db/virtual/RolesCacheKeysTableTest.java:69-140`。
- cache warmup 会记录 “Warming permissions cache from role_permissions table” 和 “Warming roles cache from roles table”，见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:465-469`、`src/java/org/apache/cassandra/auth/CassandraRoleManager.java:759-760`。

## 日志

- `CassandraAuthorizer.authorize()` 读取失败时 debug 记录 “Failed to authorize ...”，再抛 `UnauthorizedException`，见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:90-94`。
- `revokeAllFrom()` 和 `revokeAllOn()` 清理失败时 warn 记录无法撤销 role 或 resource 上的 permissions，见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:166-190`。
- `GrantPermissionsStatement` 对已经存在的 grant 返回 client warning，`RevokePermissionsStatement` 对不存在的 grant 返回 client warning，见 `src/java/org/apache/cassandra/cql3/statements/GrantPermissionsStatement.java:69-83`、`src/java/org/apache/cassandra/cql3/statements/RevokePermissionsStatement.java:50-64`。
- `CassandraRoleManager.setupDefaultRole()` 创建默认 superuser 或因节点未就绪跳过时记录 info/warn，见 `src/java/org/apache/cassandra/auth/CassandraRoleManager.java:428-455`。
- password 变更限流虽然不是 permission matrix 主线，但 role manager alter path 会在 password change 和限流时记录 info/warn，见 `src/java/org/apache/cassandra/auth/CassandraRoleManager.java:658-671`。
- GRANT/REVOKE/LIST 使用 audit context：permission grant/revoke 设置 `AuditLogEntryType.GRANT/REVOKE` 和 resource，role grant/revoke 设置 GRANT/REVOKE，list permissions 设置 `LIST_PERMISSIONS`，见 `src/java/org/apache/cassandra/cql3/statements/GrantPermissionsStatement.java:88-92`、`src/java/org/apache/cassandra/cql3/statements/RevokePermissionsStatement.java:75-80`、`src/java/org/apache/cassandra/cql3/statements/ListPermissionsStatement.java:139-143`。

## 运维关注点

- 启用 `CassandraAuthorizer` 或 `CassandraRoleManager` 后必须确认 `system_auth` RF 和 auth read/write CL；YAML 注释明确要求提高 `system_auth` RF，见 `conf/cassandra.yaml:211-232`。
- `GRANT ALL ON ALL KEYSPACES` 对普通用户不覆盖 system keyspace 写权限；system table 修改需要 system keyspace 上的显式受限 permission，而且 DDL 修改仍受 `ClientState.preventSystemKSSchemaModification()` 保护，见 `src/java/org/apache/cassandra/service/ClientState.java:485-503`、`src/java/org/apache/cassandra/service/ClientState.java:544-563`。
- 默认 `CassandraAuthorizer.revoke()` 在任何成功 revoke 后都会调用 `removeLookupEntry()`，不会先检查 `role_permissions` 是否仍保留同 resource 的其他 permission；排查 drop resource cleanup 时应同时核对 `role_permissions` 与 `resource_role_permissons_index`，见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:114-128`、`src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:289-297`。
- Role membership 改变后，已有 session 的 effective permissions 可能受 roles/permissions cache TTL 影响；紧急回收权限时要 invalidaterolescache/invalidatepermissionscache 或删 `system_views.*_cache_keys` 对应 key。
- `LIST PERMISSIONS OF <role>` 对 inherited roles 会展开 role closure，因此审计结果可能包含从被授予角色继承来的 permission，见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:329-337`。
- `resource_role_permissons_index` 只保存 resource -> role reverse lookup，不保存 permission set；真正 permission set 在 `role_permissions`，见 `src/java/org/apache/cassandra/auth/AuthKeyspace.java:99-114`。
- `DESCRIBE` 不是 data read permission。它主要服务 role/list 可见性；查询表仍需要 `SELECT`，见 `src/java/org/apache/cassandra/auth/Permission.java:49-57`。

## 性能瓶颈

- 单次授权检查在 cache miss 时会对 resource chain 的每一层调用 authorizer；每层又要对 inherited role closure 查询 direct permissions，见 `src/java/org/apache/cassandra/service/ClientState.java:528-536`、`src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:73-88`。
- Role closure 大时，`CassandraRoleManager.collectRoles()` 递归展开 membership；`filter()` 去重避免并行层级重复读取，但仍受角色图规模影响，见 `src/java/org/apache/cassandra/auth/CassandraRoleManager.java:520-541`。
- `LIST PERMISSIONS` 按 resource 且无 grantee 时使用 filtering query，权限表大时成本较高，见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:363-380`。
- cache active update 会在后台按 update interval 刷新 cache key；TTL 过短会把 auth table 读放大，TTL 过长会延迟权限回收，配置见 `conf/cassandra.yaml:300-345`。
- cache bulk load 会扫描 `system_auth.role_permissions` 或 `system_auth.roles` 并构建 inherited entries，适合启动预热但会把 role/permission 图规模集中暴露到启动阶段，见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:454-510`、`src/java/org/apache/cassandra/auth/CassandraRoleManager.java:752-773`。

## 常见故障

- `User <role> has no <permission> permission on <resource> or any of its parents`：resource chain 未找到权限，错误在 `ClientState.ensurePermissionOnResourceChain()` 抛出，见 `src/java/org/apache/cassandra/service/ClientState.java:528-541`。
- `Role <name> doesn't exist` 或 `Resource <resource> doesn't exist`：GRANT/REVOKE validate 阶段失败，见 `src/java/org/apache/cassandra/cql3/statements/PermissionsManagementStatement.java:45-59`。
- `Granting permissions on system keyspaces is strictly limited`：向非 virtual system keyspace/table 授予被禁止 permission，见 `src/java/org/apache/cassandra/cql3/statements/GrantPermissionsStatement.java:47-61`。
- `Role '<role>' was already granted ...`：重复 grant 返回 warning，不是 hard failure，见 `src/java/org/apache/cassandra/cql3/statements/GrantPermissionsStatement.java:69-83`。
- `Role '<role>' was not granted ...`：revoke 不存在的 permission 返回 warning，见 `src/java/org/apache/cassandra/cql3/statements/RevokePermissionsStatement.java:50-64`。
- `You are not authorized to view <role>'s permissions`：LIST PERMISSIONS actor 不是 super/system/self，也没有 role `DESCRIBE`，见 `src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:311-327`。
- `<role> is a member of <role>`：role grant 会形成重复或循环 membership，`CassandraRoleManager.grantRole()` 拒绝，见 `src/java/org/apache/cassandra/auth/CassandraRoleManager.java:318-328`。
- `<role> is not a member of <role>`：revoke role 时 revokee 没有直接 membership，见 `src/java/org/apache/cassandra/auth/CassandraRoleManager.java:339-345`。

## 测试用例

- `test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java:74-140`：keyspace-level grant 后 CREATE 可用，但 ALTER/DROP/SELECT/MODIFY 等未授予权限被拒绝。
- `test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java:390-407`：重复 grant 与 missing revoke warning。
- `test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java:413-487`：system keyspace denylist、ALL KEYSPACES 对 system 表无效、virtual keyspace SELECT grant/revoke。
- `test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java:490-555`：ADD/DROP IDENTITY 对 role permission/superuser 的约束。
- `test/unit/org/apache/cassandra/auth/CassandraAuthorizerTest.java:43-93`：parent role 创建 child 后可 list 自身与 child permissions，child 不能 list parent/other permissions。
- `test/unit/org/apache/cassandra/auth/CassandraAuthorizerTruncatingTest.java:72-118`：permission cache bulk load 合并 inherited roles，只为具有 LOGIN 的 role 生成 cache entries。
- `test/unit/org/apache/cassandra/auth/RolesTest.java:64-114`：superuser、login、role details、role resources cache 命中和默认 superuser CL。
- `test/unit/org/apache/cassandra/auth/CassandraRoleManagerTest.java:70-154`：role detail 读取数量、roles cache bulk load 和多层 role hierarchy。
- `test/unit/org/apache/cassandra/db/virtual/PermissionsCacheKeysTableTest.java:84-155`：permissions cache keys virtual table 查询、delete partition、truncate 和 invalid resource no-op。
- `test/unit/org/apache/cassandra/db/virtual/RolesCacheKeysTableTest.java:69-140`：roles cache keys virtual table 查询、delete partition 和 truncate。
- `test/unit/org/apache/cassandra/cql3/validation/miscellaneous/RoleSyntaxTest.java:116-155`：GRANT/REVOKE permission syntax 覆盖 role/data resource、多 permission、`PERMISSION` 关键字可选形式。
- `test/unit/org/apache/cassandra/cql3/validation/miscellaneous/RoleSyntaxTest.java:176-181`：LIST ROLES OF 语法。
