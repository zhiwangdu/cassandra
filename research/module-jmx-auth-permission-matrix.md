# JMX Auth Permission Matrix

本矩阵补齐 JMX authorization 的源码合同：Cassandra 的 JMX 权限不直接走普通 CQL `ClientState.ensurePermission()` 资源链，而是由 `AuthorizationProxy` 对 `MBeanServer` 调用做方法分类、ObjectName exact/wildcard 覆盖判断、危险 JDK operation 拦截和单独的 JMX permission cache。

## Source Contract

| Scenario | Contract | Source anchors | Test anchors |
| --- | --- | --- | --- |
| `jmx_auth_proxy_entry_contract` | `AuthorizationProxy.invoke()` 是远程 JMX 调用入口；本地 connector `setMBeanServer` 可初始化 server，远程 subject 调用 `setMBeanServer` 或 `getMBeanServer` 必须拒绝。 | `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:109`, `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:135` | `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:167` |
| `jmx_auth_setup_and_subject_contract` | auth setup 未完成时拒绝访问；authorization 关闭或 connector 本地调用放行；远程 subject 必须有 principal，superuser 可绕过具体 grant 检查。 | `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:176`, `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:186`, `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:201` | `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:141`, `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:153`, `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:191`, `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:384` |
| `jmx_auth_mbean_server_describe_contract` | 不带 `ObjectName` 的允许方法仅限描述型 MBeanServer 方法，并要求 root `JMXResource` 上的 `DESCRIBE`。 | `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:83`, `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:226` | `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:367`, `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:378` |
| `jmx_auth_method_permission_map_contract` | 带 `ObjectName` 的方法按方法名映射：`getAttribute(s)` -> `SELECT`，`setAttribute(s)` -> `MODIFY`，`invoke` -> `EXECUTE`，query/metadata 类方法 -> `DESCRIBE`；未知方法拒绝。 | `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:409`, `src/java/org/apache/cassandra/auth/JMXResource.java:42` | `test/unit/org/apache/cassandra/auth/jmx/JMXAuthTest.java:117`, `test/unit/org/apache/cassandra/auth/jmx/JMXAuthTest.java:143`, `test/unit/org/apache/cassandra/auth/jmx/JMXAuthTest.java:170`, `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:326` |
| `jmx_auth_denied_vulnerable_methods_contract` | 部分 `MBeanServer` 管理方法永远拒绝；`invoke` 会额外拦截 DiagnosticCommand compiler directives/JVMTI load 和 MLet `addURL/getMBeansFromURL`。 | `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:95`, `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:486` | `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:346` |
| `jmx_auth_exact_root_match_contract` | 对 exact `ObjectName`，root JMX grant 可覆盖全部 MBeans；否则任一 granted ObjectName pattern 能 `apply(target)` 即可放行。 | `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:381`, `src/java/org/apache/cassandra/auth/JMXResource.java:30` | `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:64`, `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:95`, `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:212`, `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:227` |
| `jmx_auth_wildcard_coverage_contract` | 对 wildcard target，root grant 可覆盖全部；否则要查询 target 匹配到的全部 MBeans，并由 granted resource patterns 的匹配集合完全覆盖，交集不足仍拒绝。 | `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:333`, `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:349` | `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:243`, `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:260`, `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:280`, `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:310` |
| `jmx_auth_cache_loader_contract` | `JmxPermissionsCache` 不复用普通 permissions cache；它按 role 调 `IAuthorizer.list(SYSTEM_USER, Permission.ALL, null, subject)`，只保留 `JMXResource` permission details。 | `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:469`, `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:551` | `test/unit/org/apache/cassandra/tools/nodetool/InvalidateJmxPermissionsCacheTest.java:45` |
| `jmx_auth_cache_mbean_contract` | JMX permission cache 复用普通 permission cache TTL/update/max entries/active update 配置入口，并注册新旧 MBean 名称；MBean 支持按 role invalidation。 | `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:551`, `src/java/org/apache/cassandra/tools/NodeProbe.java:171`, `src/java/org/apache/cassandra/tools/NodeProbe.java:608` | `test/unit/org/apache/cassandra/tools/nodetool/InvalidateJmxPermissionsCacheTest.java:75`, `test/unit/org/apache/cassandra/tools/nodetool/InvalidateJmxPermissionsCacheTest.java:123` |
| `jmx_auth_virtual_cache_keys_contract` | `system_views.jmx_permissions_cache_keys` 暴露 JMX permission cache keys，支持 partition delete 和 truncate invalidation，不支持 insert/update。 | `src/java/org/apache/cassandra/db/virtual/JmxPermissionsCacheKeysTable.java:26` | `test/unit/org/apache/cassandra/db/virtual/JmxPermissionsCacheKeysTableTest.java:48`, `test/unit/org/apache/cassandra/db/virtual/JmxPermissionsCacheKeysTableTest.java:129`, `test/unit/org/apache/cassandra/db/virtual/JmxPermissionsCacheKeysTableTest.java:144` |
| `jmx_auth_nodetool_invalidation_contract` | `nodetool invalidatejmxpermissionscache [role...]` 不带 role 时清空全部 cache，带 role 时逐个调用 `NodeProbe.invalidateJmxPermissionsCache(role)`。 | `src/java/org/apache/cassandra/tools/nodetool/InvalidateJmxPermissionsCache.java:28`, `src/java/org/apache/cassandra/tools/NodeProbe.java:608` | `test/unit/org/apache/cassandra/tools/nodetool/InvalidateJmxPermissionsCacheTest.java:45`, `test/unit/org/apache/cassandra/tools/nodetool/InvalidateJmxPermissionsCacheTest.java:75`, `test/unit/org/apache/cassandra/tools/nodetool/InvalidateJmxPermissionsCacheTest.java:123` |
| `jmx_auth_existing_tests_baseline` | 现有 tests 覆盖 exact/pattern/root grants、method permission mapping、restricted methods、auth setup gate、virtual cache key table 和 nodetool invalidation。 | `test/unit/org/apache/cassandra/auth/jmx/JMXAuthTest.java`, `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java`, `test/unit/org/apache/cassandra/db/virtual/JmxPermissionsCacheKeysTableTest.java`, `test/unit/org/apache/cassandra/tools/nodetool/InvalidateJmxPermissionsCacheTest.java` | same |

## Design Goals

- 让 JMX 管理面使用 Cassandra role/permission 体系，而不是 JVM/JMX 原生 flat role 文件。
- 支持 exact ObjectName、wildcard grant 和 wildcard target，同时避免 wildcard target 被部分 grant 误放行。
- 对高风险 JDK MBean operations 做硬拒绝，即使用户拥有 root JMX permission 也不能远程加载代码或读取任意文件。
- 为 JMX permission cache 提供和普通 auth cache 一致的 MBean、virtual table 与 nodetool invalidation 面。

## Problems Solved

- 普通 `IResource` parent chain 无法表达 JMX wildcard 覆盖关系；`AuthorizationProxy` 通过 `ObjectName.apply()` 和 `queryNames()` 做 exact/pattern 匹配。
- JMX 管理方法的权限语义不同于 CQL：读 attribute 是 `SELECT`，写 attribute 是 `MODIFY`，operation invoke 是 `EXECUTE`，metadata/query 是 `DESCRIBE`。
- JMX 权限检查通常连续访问同一 role 的多个 MBean；单独的 `JmxPermissionsCache` 避免每个 ObjectName 都重新扫 authorizer。
- 运维需要快速回收 JMX 权限；`invalidatejmxpermissionscache` 和 `system_views.jmx_permissions_cache_keys` 提供全量/按 role 失效。

## Design Tradeoffs

- JMX cache loader 读取该 role 的所有 permission details 后过滤 `JMXResource`，实现简单且能支持 wildcard 覆盖；代价是 role permission 很多时一次 miss 较重。
- wildcard target 要求目标集合被 granted resource 集合完全覆盖，避免交集误授权；代价是需要 `MBeanServer.queryNames()`，MBean 很多时成本高于 exact check。
- root JMX permission 是高权限捷径，能覆盖所有 exact/wildcard target；它仍不能绕过 hard-denied vulnerable methods。
- cache TTL/update/max entries 复用普通 permissions cache 配置，减少配置面；代价是 JMX cache 不能独立调优。

## Core Classes

| Class | Responsibility |
| --- | --- |
| `AuthorizationProxy` | `MBeanServer` invocation handler，做 subject 解析、method permission 映射、denied method 拦截、exact/wildcard 授权判断。 |
| `JMXResource` | JMX root/mbean resource，定义 `AUTHORIZE/DESCRIBE/EXECUTE/MODIFY/SELECT` permission set 和 ObjectName existence。 |
| `AuthorizationProxy.JmxPermissionsCache` | role -> JMX permission details cache，MBean 名称为 `JmxPermissionsCache`，并保留 deprecated `JMXPermissionsCache`。 |
| `JmxPermissionsCacheKeysTable` | `system_views.jmx_permissions_cache_keys` virtual table，支持读 cache keys、delete partition、truncate。 |
| `InvalidateJmxPermissionsCache` | nodetool 子命令，按 role 或全量失效 JMX permission cache。 |
| `NodeProbe` | JMX client facade，连接 `AuthorizationProxy.JmxPermissionsCacheMBean` 并暴露 invalidation 方法。 |

## Lifecycle

```text
remote JMX client
  -> JMXAuthenticator attaches CassandraPrincipal to Subject
  -> AuthorizationProxy.invoke(proxy, method, args)
     -> reject getMBeanServer / remote setMBeanServer / denied methods
     -> check auth setup complete and authorization enabled
     -> resolve first Principal to RoleResource
     -> superuser bypass?
     -> method without ObjectName:
        -> require DESCRIBE on JMXResource.root()
     -> method with ObjectName:
        -> map method name to Permission
        -> JmxPermissionsCache.get(role)
           -> IAuthorizer.list(SYSTEM_USER, Permission.ALL, null, role)
           -> filter details.resource instanceof JMXResource
        -> exact target: root grant or ObjectName.apply(target)
        -> wildcard target: queryNames(target), subtract grants coverage, require empty set
```

## Configuration And Operations

| Surface | Contract | Evidence |
| --- | --- | --- |
| `authorizer` | JMX auth only matters when authorization is required; otherwise proxy allows calls after setup/local checks. | `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:186` |
| permissions cache settings | JMX cache uses `permissions_validity` / update interval / max entries / active update from `DatabaseDescriptor`. | `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:559` |
| JMX cache MBean | `org.apache.cassandra.auth:type=JmxPermissionsCache` plus deprecated `JMXPermissionsCache`. | `src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:551` |
| virtual table | `system_views.jmx_permissions_cache_keys` lists role cache keys and supports delete/truncate. | `src/java/org/apache/cassandra/db/virtual/JmxPermissionsCacheKeysTable.java:26` |
| nodetool | `invalidatejmxpermissionscache [role...]` clears all or named role entries. | `src/java/org/apache/cassandra/tools/nodetool/InvalidateJmxPermissionsCache.java:28` |

## Operational Notes

- Grant JMX permissions on the narrowest ObjectName that covers the intended MBean set; root `ALL MBEANS` grants are broad.
- For wildcard target calls such as `queryNames("java.lang:*")`, every matched MBean must be covered by grants, not just one.
- After changing JMX grants, invalidate `JmxPermissionsCache` through nodetool, JMX MBean or `system_views.jmx_permissions_cache_keys` to avoid waiting for TTL.
- A grant on a risky JDK MBean still cannot execute hard-denied operations such as `compilerDirectivesAdd`, `jvmtiAgentLoad` or MLet URL loading.

## Performance Bottlenecks

- JMX cache miss calls `IAuthorizer.list()` and filters all returned permission details for the role.
- Wildcard target authorization calls `queryNames()` and does set subtraction over all matching MBeans.
- Very short permissions cache TTL increases JMX metadata/query overhead for tools that call many MBeans.

## Common Failures

- `Access Denied` before permissions are checked: auth setup may not be complete, subject may be unauthenticated, or method may be denied globally.
- `getDomains`/`queryNames(null)` denied despite MBean grants: non-ObjectName MBeanServer methods require root `DESCRIBE`.
- Exact MBean access denied despite wildcard grant: verify the granted ObjectName pattern actually `apply()` matches the target ObjectName.
- Wildcard target denied despite overlapping grants: all target matches must be covered.
- Recently granted JMX permission not visible: invalidate `JmxPermissionsCache` or wait for permissions cache validity interval.

## Test Cases

- `test/unit/org/apache/cassandra/auth/jmx/JMXAuthTest.java:117`：SELECT exact/pattern/root MBean grant behavior.
- `test/unit/org/apache/cassandra/auth/jmx/JMXAuthTest.java:143`：MODIFY exact/pattern/root MBean grant behavior.
- `test/unit/org/apache/cassandra/auth/jmx/JMXAuthTest.java:170`：EXECUTE exact/pattern/root MBean grant behavior.
- `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:95`：root resource grant and wrong permission rejection.
- `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:212`：wildcard grant covers exact target.
- `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:243`：wildcard grant covers wildcard target.
- `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:280`：intersecting wildcard grants do not cover a wider wildcard target.
- `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:346`：restricted methods are rejected.
- `test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java:384`：auth setup incomplete rejects access.
- `test/unit/org/apache/cassandra/db/virtual/JmxPermissionsCacheKeysTableTest.java:48`：virtual cache key table select/delete/truncate.
- `test/unit/org/apache/cassandra/tools/nodetool/InvalidateJmxPermissionsCacheTest.java:45`：nodetool help contract.
- `test/unit/org/apache/cassandra/tools/nodetool/InvalidateJmxPermissionsCacheTest.java:75`：single-role invalidation reloads cache.
- `test/unit/org/apache/cassandra/tools/nodetool/InvalidateJmxPermissionsCacheTest.java:123`：all-role invalidation reloads cache.
