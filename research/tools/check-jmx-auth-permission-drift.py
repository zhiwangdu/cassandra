#!/usr/bin/env python3
#
# Source-only drift check for JMX auth permission research coverage.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

MATRIX_DOC = "research/module-jmx-auth-permission-matrix.md"
CHECKER_DOC = "research/module-jmx-auth-permission-drift-checker.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

SCENARIOS = (
    "jmx_auth_proxy_entry_contract",
    "jmx_auth_setup_and_subject_contract",
    "jmx_auth_mbean_server_describe_contract",
    "jmx_auth_method_permission_map_contract",
    "jmx_auth_denied_vulnerable_methods_contract",
    "jmx_auth_exact_root_match_contract",
    "jmx_auth_wildcard_coverage_contract",
    "jmx_auth_cache_loader_contract",
    "jmx_auth_cache_mbean_contract",
    "jmx_auth_virtual_cache_keys_contract",
    "jmx_auth_nodetool_invalidation_contract",
    "jmx_auth_existing_tests_baseline",
)

SOURCE_EXPECTATIONS = {
    "src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java": (
        "public class AuthorizationProxy implements InvocationHandler",
        "private static final Set<String> MBEAN_SERVER_ALLOWED_METHODS",
        '"getDefaultDomain"',
        '"queryMBeans"',
        '"queryNames"',
        "private static final Set<String> DENIED_METHODS",
        '"createMBean"',
        '"deserialize"',
        '"getClassLoader"',
        '"registerMBean"',
        '"unregisterMBean"',
        "public static final JmxPermissionsCache jmxPermissionsCache = new JmxPermissionsCache();",
        'if ("getMBeanServer".equals(methodName))',
        "throw new SecurityException(\"Access denied\");",
        'if (methodName.equals("invoke") && args.length == 4)',
        "checkVulnerableMethods(args);",
        "Subject subject = Subject.getSubject(acc);",
        'if (("setMBeanServer").equals(methodName))',
        "if (subject != null)",
        "if (!isAuthSetupComplete.getAsBoolean())",
        "if (!isAuthzRequired.getAsBoolean())",
        "if (subject == null)",
        "if (DENIED_METHODS.contains(methodName))",
        "Set<Principal> principals = subject.getPrincipals();",
        "RoleResource userResource = RoleResource.role(principals.iterator().next().getName());",
        "if (isSuperuser.test(userResource))",
        "args != null && args[0] instanceof ObjectName",
        "return authorizeMBeanMethod(userResource, methodName, args);",
        "return authorizeMBeanServerMethod(userResource, methodName);",
        "MBEAN_SERVER_ALLOWED_METHODS.contains(methodName)",
        "hasPermission(subject, Permission.DESCRIBE, JMXResource.root())",
        "Permission requiredPermission = getRequiredPermission(methodName);",
        "Set<JMXResource> permittedResources = getPermittedResources(role, requiredPermission);",
        "targetBean.isPattern()",
        "checkPattern(targetBean, permittedResources)",
        "checkExact(targetBean, permittedResources)",
        "if (permittedResources.contains(JMXResource.root()))",
        "Set<ObjectName> targetNames = queryNames.apply(target);",
        "Set<ObjectName> matchingNames = queryNames.apply(ObjectName.getInstance(resource.getObjectName()));",
        "targetNames.removeAll(matchingNames);",
        "ObjectName.getInstance(resource.getObjectName()).apply(target)",
        'case "getAttribute":',
        'case "getAttributes":',
        "return Permission.SELECT;",
        'case "setAttribute":',
        'case "setAttributes":',
        "return Permission.MODIFY;",
        'case "invoke":',
        "return Permission.EXECUTE;",
        'case "getMBeanInfo":',
        'case "queryNames":',
        "return Permission.DESCRIBE;",
        "DatabaseDescriptor.getAuthorizer().list(AuthenticatedUser.SYSTEM_USER, Permission.ALL, null, subject)",
        "details.resource instanceof JMXResource",
        "checkCompilerDirectiveAddMethods(name, operationName);",
        "checkJvmtiLoad(name, operationName);",
        "checkMLetMethods(name, operationName);",
        'operation.equals("compilerDirectivesAdd")',
        'operation.equals("jvmtiAgentLoad")',
        'operation.equals("addURL") || operation.equals("getMBeansFromURL")',
        "public static final class JmxPermissionsCache extends AuthCache<RoleResource, Set<PermissionDetails>>",
        "DatabaseDescriptor::setPermissionsValidity",
        "AuthorizationProxy::loadPermissions",
        "Collections::emptyMap",
        "MBeanWrapper.instance.registerMBean(this, MBEAN_NAME_BASE + DEPRECATED_CACHE_NAME);",
        "public void invalidatePermissions(String roleName)",
        'public static final String CACHE_NAME = "JmxPermissionsCache";',
        'public static final String DEPRECATED_CACHE_NAME = "JMXPermissionsCache";',
    ),
    "src/java/org/apache/cassandra/auth/JMXResource.java": (
        "public class JMXResource implements IResource",
        'private static final String ROOT_NAME = "mbean";',
        "private static final Set<Permission> JMX_PERMISSIONS",
        "Permission.AUTHORIZE",
        "Permission.DESCRIBE",
        "Permission.EXECUTE",
        "Permission.MODIFY",
        "Permission.SELECT",
        "public static JMXResource mbean(String name)",
        "ManagementFactory.getPlatformMBeanServer()",
        "mbs.queryNames(new ObjectName(name), null)",
    ),
    "src/java/org/apache/cassandra/db/virtual/JmxPermissionsCacheKeysTable.java": (
        'TableMetadata.builder(keyspace, "jmx_permissions_cache_keys")',
        ".comment(\"keys in the JMX permissions cache\")",
        ".addPartitionKeyColumn(ROLE, UTF8Type.instance)",
        "AuthorizationProxy.jmxPermissionsCache.getAll()",
        "AuthorizationProxy.jmxPermissionsCache.invalidate(roleResource);",
        "AuthorizationProxy.jmxPermissionsCache.invalidate();",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/InvalidateJmxPermissionsCache.java": (
        '@Command(name = "invalidatejmxpermissionscache", description = "Invalidate the JMX permissions cache")',
        '@Arguments(usage = "[<role>...]", description = "List of roles to invalidate. By default, all roles")',
        "if (args.isEmpty())",
        "probe.invalidateJmxPermissionsCache();",
        "probe.invalidateJmxPermissionsCache(roleName);",
    ),
    "src/java/org/apache/cassandra/tools/NodeProbe.java": (
        "protected AuthorizationProxy.JmxPermissionsCacheMBean jpcProxy;",
        "AuthorizationProxy.JmxPermissionsCacheMBean.CACHE_NAME",
        "jpcProxy = JMX.newMBeanProxy(mbeanServerConn, name, AuthorizationProxy.JmxPermissionsCacheMBean.class);",
        "public void invalidateJmxPermissionsCache()",
        "jpcProxy.invalidate();",
        "public void invalidateJmxPermissionsCache(String roleName)",
        "jpcProxy.invalidatePermissions(roleName);",
        "case AuthorizationProxy.JmxPermissionsCacheMBean.CACHE_NAME:",
    ),
}

TEST_EXPECTATIONS = {
    "test/unit/org/apache/cassandra/auth/jmx/JMXAuthTest.java": (
        "public void readAttribute() throws Throwable",
        "assertPermissionOnResource(Permission.SELECT, tableMBean, proxy::getTableName);",
        "assertPermissionOnResource(Permission.SELECT, JMXResource.root(), proxy::getTableName);",
        "public void writeAttribute() throws Throwable",
        "assertPermissionOnResource(Permission.MODIFY, tableMBean, action);",
        "assertPermissionOnResource(Permission.MODIFY, JMXResource.root(), action);",
        "public void executeMethod() throws Throwable",
        "assertPermissionOnResource(Permission.EXECUTE, tableMBean, proxy::estimateKeys);",
        "assertPermissionOnResource(Permission.EXECUTE, JMXResource.root(), proxy::estimateKeys);",
        "DatabaseDescriptor.getAuthorizer().grant(AuthenticatedUser.SYSTEM_USER,",
    ),
    "test/unit/org/apache/cassandra/auth/jmx/AuthorizationProxyTest.java": (
        "public void roleHasRequiredPermission() throws Throwable",
        "public void roleHasRequiredPermissionOnRootResource() throws Throwable",
        "public void roleHasOtherPermissionOnRootResource() throws Throwable",
        "public void roleHasNoPermissionsButIsSuperuser() throws Throwable",
        "public void roleHasNoPermissionsButAuthzNotRequired() throws Throwable",
        "public void authorizeWhenSubjectIsNull() throws Throwable",
        "public void rejectWhenSubjectNotAuthenticated() throws Throwable",
        "public void authorizeWhenWildcardGrantCoversExactTarget() throws Throwable",
        "public void rejectWhenWildcardGrantDoesNotCoverExactTarget() throws Throwable",
        "public void authorizeWhenWildcardGrantCoversWildcardTarget() throws Throwable",
        "public void rejectWhenWildcardGrantIsDisjointWithWildcardTarget() throws Throwable",
        "public void rejectWhenWildcardGrantIntersectsWithWildcardTarget() throws Throwable",
        "public void authorizeOnTargetWildcardWithPermissionOnRoot() throws Throwable",
        "public void rejectInvocationOfUnknownMethod() throws Throwable",
        "public void rejectInvocationOfRestrictedMethods() throws Throwable",
        "public void authorizeMethodsWithoutMBeanArgumentIfPermissionsGranted() throws Throwable",
        "public void rejectMethodsWithoutMBeanArgumentIfPermissionsNotGranted() throws Throwable",
        "public void rejectWhenAuthSetupIsNotComplete() throws Throwable",
    ),
    "test/unit/org/apache/cassandra/db/virtual/JmxPermissionsCacheKeysTableTest.java": (
        "public class JmxPermissionsCacheKeysTableTest extends CQLTester",
        "SELECT * FROM vts.jmx_permissions_cache_keys",
        "DELETE FROM vts.jmx_permissions_cache_keys WHERE role='role_a'",
        "TRUNCATE vts.jmx_permissions_cache_keys",
        "Column modification is not supported by table vts.jmx_permissions_cache_keys",
        "AuthorizationProxy.jmxPermissionsCache.invalidate();",
    ),
    "test/unit/org/apache/cassandra/tools/nodetool/InvalidateJmxPermissionsCacheTest.java": (
        "public class InvalidateJmxPermissionsCacheTest extends CQLTester",
        'ToolRunner.invokeNodetool("help", "invalidatejmxpermissionscache")',
        "public void testInvalidateSingleJMXPermission()",
        'ToolRunner.invokeNodetool("invalidatejmxpermissionscache", ROLE_A.getRoleName())',
        "public void testInvalidateAllJMXPermissions()",
        'ToolRunner.invokeNodetool("invalidatejmxpermissionscache")',
        "getRolePermissionsReadCount()",
    ),
}

DOC_EXPECTATIONS = {
    MATRIX_DOC: SCENARIOS + (
        "JMX Auth Permission Matrix",
        "AuthorizationProxy",
        "JmxPermissionsCache",
        "system_views.jmx_permissions_cache_keys",
        "invalidatejmxpermissionscache",
        "compilerDirectivesAdd",
        "jvmtiAgentLoad",
    ),
    CHECKER_DOC: SCENARIOS + (
        "JMX Auth Permission Drift Checker",
        "12 scenarios",
        "JmxPermissionsCache",
    ),
    README_DOC: (
        "module-jmx-auth-permission-matrix.md",
        "module-jmx-auth-permission-drift-checker.md",
        "research/tools/check-jmx-auth-permission-drift.py",
    ),
    SOURCE_MAP_DOC: (
        "JMX auth permission",
        "module-jmx-auth-permission-matrix.md",
        "module-jmx-auth-permission-drift-checker.md",
        "research/tools/check-jmx-auth-permission-drift.py",
        "src/java/org/apache/cassandra/auth/jmx/AuthorizationProxy.java:109",
        "src/java/org/apache/cassandra/db/virtual/JmxPermissionsCacheKeysTable.java:26",
        "src/java/org/apache/cassandra/tools/nodetool/InvalidateJmxPermissionsCache.java:28",
    ),
}


@dataclass
class Failure:
    category: str
    path: str
    detail: str


def check_tokens(expectations, category):
    failures = []
    for path, tokens in expectations.items():
        full = REPO_ROOT / path
        if not full.exists():
            failures.append(Failure(category, path, "missing file"))
            continue
        text = full.read_text(encoding="utf-8")
        for token in tokens:
            if token not in text:
                failures.append(Failure(category, path, f"missing token: {token}"))
    return failures


def main(argv):
    parser = argparse.ArgumentParser(description="Check JMX auth permission research coverage for drift.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable result")
    args = parser.parse_args(argv)

    failures = []
    failures.extend(check_tokens(SOURCE_EXPECTATIONS, "source"))
    failures.extend(check_tokens(TEST_EXPECTATIONS, "test"))
    failures.extend(check_tokens(DOC_EXPECTATIONS, "doc"))

    if args.json:
        print(json.dumps({
            "ok": not failures,
            "scenario_count": len(SCENARIOS),
            "failures": [failure.__dict__ for failure in failures],
        }, indent=2, sort_keys=True))
    elif failures:
        for failure in failures:
            print(f"{failure.category}: {failure.path}: {failure.detail}", file=sys.stderr)
    else:
        print(f"OK JMX auth permission drift checks passed ({len(SCENARIOS)} scenarios)")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
