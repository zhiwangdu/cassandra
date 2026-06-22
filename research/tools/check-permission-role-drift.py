#!/usr/bin/env python3
#
# Source-only drift check for permission/role research coverage.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

MATRIX_DOC = "research/module-permission-role-matrix.md"
CHECKER_DOC = "research/module-permission-role-drift-checker.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

EXPECTED_PERMISSION_ORDER = (
    "CREATE",
    "ALTER",
    "DROP",
    "SELECT",
    "MODIFY",
    "AUTHORIZE",
    "DESCRIBE",
    "EXECUTE",
    "UNMASK",
    "SELECT_MASKED",
)

SCENARIOS = (
    "permission_role_enum_order_contract",
    "permission_role_resource_matrix_contract",
    "permission_role_grant_revoke_statement_contract",
    "permission_role_system_keyspace_guard_contract",
    "permission_role_membership_contract",
    "permission_role_list_visibility_contract",
    "permission_role_backend_storage_contract",
    "permission_role_auth_chain_contract",
    "permission_role_cache_contract",
    "permission_role_virtual_cache_keys_contract",
    "permission_role_audit_warning_contract",
    "permission_role_existing_tests_baseline",
    "permission_role_spi_boundary",
)

SOURCE_EXPECTATIONS = {
    "src/java/org/apache/cassandra/auth/Permission.java": (
        "IAuthorizer implementations may encode permissions using ordinals",
        "Sets.immutableEnumSet(EnumSet.range(Permission.CREATE, Permission.SELECT_MASKED));",
        "public static final Set<Permission> NONE = ImmutableSet.of();",
        "public static final Set<Permission> INVALID_FOR_SYSTEM_KEYSPACES",
        "EnumSet.complementOf(EnumSet.of(Permission.SELECT, Permission.DESCRIBE, Permission.ALTER))",
    ),
    "src/java/org/apache/cassandra/auth/DataResource.java": (
        "public class DataResource implements IResource",
        "ROOT, KEYSPACE, ALL_TABLES, TABLE",
        "private static final Set<Permission> TABLE_LEVEL_PERMISSIONS",
        "private static final Set<Permission> ALL_TABLES_LEVEL_PERMISSIONS",
        "private static final Set<Permission> KEYSPACE_LEVEL_PERMISSIONS",
        "Permission.UNMASK",
        "Permission.SELECT_MASKED",
        'private static final String ROOT_NAME = "data";',
        "public static DataResource allTables(String keyspace)",
        "return root();",
    ),
    "src/java/org/apache/cassandra/auth/FunctionResource.java": (
        "public class FunctionResource implements IResource",
        "ROOT, KEYSPACE, FUNCTION",
        "private static final Set<Permission> COLLECTION_LEVEL_PERMISSIONS",
        "private static final Set<Permission> SCALAR_FUNCTION_PERMISSIONS",
        "private static final Set<Permission> AGGREGATE_FUNCTION_PERMISSIONS",
        "Permission.EXECUTE",
        'private static final String ROOT_NAME = "functions";',
    ),
    "src/java/org/apache/cassandra/auth/RoleResource.java": (
        "public class RoleResource implements IResource, Comparable<RoleResource>",
        "ROOT, ROLE",
        "private static final Set<Permission> ROOT_LEVEL_PERMISSIONS",
        "private static final Set<Permission> ROLE_LEVEL_PERMISSIONS",
        "Permission.DESCRIBE",
        'private static final String ROOT_NAME = "roles";',
        "public static RoleResource role(String name)",
    ),
    "src/java/org/apache/cassandra/auth/JMXResource.java": (
        "public class JMXResource implements IResource",
        "ROOT, MBEAN",
        'private static final String ROOT_NAME = "mbean";',
        "private static final Set<Permission> JMX_PERMISSIONS",
        "Permission.EXECUTE",
        "Permission.MODIFY",
        "Permission.SELECT",
    ),
    "src/java/org/apache/cassandra/auth/AuthKeyspace.java": (
        'public static final String ROLES = "roles";',
        'public static final String ROLE_MEMBERS = "role_members";',
        'public static final String ROLE_PERMISSIONS = "role_permissions";',
        'public static final String RESOURCE_ROLE_INDEX = "resource_role_permissons_index";',
        'public static final String NETWORK_PERMISSIONS = "network_permissions";',
        'public static final String CIDR_PERMISSIONS = "cidr_permissions";',
        'public static final String CIDR_GROUPS = "cidr_groups";',
        'public static final String IDENTITY_TO_ROLES = "identity_to_role";',
        "member_of set<text>",
        "permissions set<text>",
        "PRIMARY KEY(role, resource)",
        "PRIMARY KEY(resource, role)",
        "Tables.of(Roles, RoleMembers, RolePermissions,",
    ),
    "src/java/org/apache/cassandra/cql3/statements/PermissionsManagementStatement.java": (
        "state.ensureNotAnonymous();",
        "DatabaseDescriptor.getRoleManager().isExistingRole(grantee)",
        "resource = maybeCorrectResource(resource, state);",
        "if (!resource.exists())",
        "state.ensurePermission(Permission.AUTHORIZE, resource);",
        "for (Permission p : permissions)",
        "state.ensurePermission(p, resource);",
    ),
    "src/java/org/apache/cassandra/cql3/statements/GrantPermissionsStatement.java": (
        "public class GrantPermissionsStatement extends PermissionsManagementStatement",
        "SchemaConstants.isNonVirtualSystemKeyspace(data.getKeyspace())",
        "Permission.INVALID_FOR_SYSTEM_KEYSPACES",
        "Granting permissions on system keyspaces is strictly limited",
        "Set<Permission> granted = authorizer.grant(state.getUser(), permissions, resource, grantee);",
        "ClientWarn.instance.warn(String.format(\"Role '%s' was already granted %s on %s\"",
        "new AuditLogContext(AuditLogEntryType.GRANT, keyspace, resource.getName())",
    ),
    "src/java/org/apache/cassandra/cql3/statements/RevokePermissionsStatement.java": (
        "public class RevokePermissionsStatement extends PermissionsManagementStatement",
        "Set<Permission> revoked = authorizer.revoke(state.getUser(), permissions, resource, grantee);",
        "ClientWarn.instance.warn(String.format(\"Role '%s' was not granted %s on %s\"",
        "new AuditLogContext(AuditLogEntryType.REVOKE, keyspace, resource.getName())",
    ),
    "src/java/org/apache/cassandra/cql3/statements/ListPermissionsStatement.java": (
        "public class ListPermissionsStatement extends AuthorizationStatement",
        'private static final String CF = "permissions";',
        "state.ensureNotAnonymous();",
        "for (IResource r : Resources.chain(resource))",
        "DatabaseDescriptor.getAuthorizer().list(state.getUser(), permissions, resource, grantee)",
        "result.addColumnValue(UTF8Type.instance.decompose(pd.grantee));",
        "new AuditLogContext(AuditLogEntryType.LIST_PERMISSIONS)",
    ),
    "src/java/org/apache/cassandra/cql3/statements/RoleManagementStatement.java": (
        "public abstract class RoleManagementStatement extends AuthenticationStatement",
        "super.checkPermission(state, Permission.AUTHORIZE, role);",
        "state.ensureNotAnonymous();",
        "DatabaseDescriptor.getRoleManager().isExistingRole(role)",
        "DatabaseDescriptor.getRoleManager().isExistingRole(grantee)",
    ),
    "src/java/org/apache/cassandra/cql3/statements/GrantRoleStatement.java": (
        "public class GrantRoleStatement extends RoleManagementStatement",
        "DatabaseDescriptor.getRoleManager().grantRole(state.getUser(), role, grantee);",
        "new AuditLogContext(AuditLogEntryType.GRANT)",
    ),
    "src/java/org/apache/cassandra/cql3/statements/RevokeRoleStatement.java": (
        "public class RevokeRoleStatement extends RoleManagementStatement",
        "DatabaseDescriptor.getRoleManager().revokeRole(state.getUser(), role, grantee);",
        "new AuditLogContext(AuditLogEntryType.REVOKE)",
    ),
    "src/java/org/apache/cassandra/auth/CassandraAuthorizer.java": (
        "public class CassandraAuthorizer implements IAuthorizer",
        "for (Role role: user.getRoleDetails())",
        "modifyRolePermissions(nonExistingPermissions, resource, grantee, \"+\");",
        "addLookupEntry(resource, grantee);",
        "modifyRolePermissions(existingPermissions, resource, revokee, \"-\");",
        "removeLookupEntry(resource, revokee);",
        "AuthKeyspace.ROLE_PERMISSIONS",
        "AuthKeyspace.RESOURCE_ROLE_INDEX",
        "DELETE FROM %s.%s WHERE resource = '%s' AND role = '%s'",
        "INSERT INTO %s.%s (resource, role) VALUES ('%s','%s')",
        "performer.getPermissions(RoleResource.root()).contains(Permission.DESCRIBE)",
        "DatabaseDescriptor.getRoleManager().getRoles(grantee, true)",
        'query += " ALLOW FILTERING";',
        "logger.info(\"Warming permissions cache from role_permissions table\");",
        "Roles.canLogin(roleResource)",
    ),
    "src/java/org/apache/cassandra/auth/CassandraRoleManager.java": (
        "public class CassandraRoleManager implements IRoleManager",
        "if (getRoles(grantee, true).contains(role))",
        "if (getRoles(role, true).contains(grantee))",
        "modifyRoleMembership(grantee.getRoleName(), role.getRoleName(), \"+\");",
        "INSERT INTO %s.%s (role, member) values ('%s', '%s')",
        "if (!getRoles(revokee, false).contains(role))",
        "modifyRoleMembership(revokee.getRoleName(), role.getRoleName(), \"-\");",
        "DELETE FROM %s.%s WHERE role = '%s' and member = '%s'",
        "private Stream<Role> collectRoles(Role role, boolean includeInherited, Predicate<String> distinctFilter, Function<String, Role> loaderFunction)",
        "return seen::add;",
        "logger.info(\"Warming roles cache from roles table\");",
    ),
    "src/java/org/apache/cassandra/service/ClientState.java": (
        "public void ensurePermission(Permission perm, IResource resource)",
        "if (!DatabaseDescriptor.getAuthorizer().requireAuthorization())",
        "SchemaConstants.isSystemKeyspace(keyspace)",
        "ensurePermissionOnResourceChain(perm, Resources.chain(dataResource, IResource::hasParent));",
        "if (DatabaseDescriptor.getAuthFromRoot())",
        "resources = Lists.reverse(resources);",
        "throw new UnauthorizedException(String.format(\"User %s has no %s permission on %s or any of its parents\"",
        "preventSystemKSSchemaModification(keyspace, resource, perm);",
    ),
    "src/java/org/apache/cassandra/auth/PermissionsCache.java": (
        "public class PermissionsCache extends AuthCache<Pair<AuthenticatedUser, IResource>, Set<Permission>>",
        "DatabaseDescriptor::setPermissionsValidity",
        "(p) -> authorizer.authorize(p.left, p.right)",
        "authorizer.bulkLoader()",
        "public Set<Permission> getPermissions(AuthenticatedUser user, IResource resource)",
        "public void invalidatePermissions(String roleName, String resourceName)",
    ),
    "src/java/org/apache/cassandra/auth/RolesCache.java": (
        "public class RolesCache extends AuthCache<RoleResource, Set<Role>> implements RolesCacheMBean",
        "DatabaseDescriptor::setRolesValidity",
        "roleManager::getRoleDetails",
        "roleManager.bulkLoader()",
        "Set<RoleResource> getRoleResources(RoleResource primaryRole)",
        "public void invalidateRoles(String roleName)",
    ),
    "src/java/org/apache/cassandra/auth/AuthCache.java": (
        "public synchronized void setValidity(int validityPeriod)",
        "public synchronized void setUpdateInterval(int updateInterval)",
        "public synchronized void setMaxEntries(int maxEntries)",
        "public synchronized void setActiveUpdate(boolean update)",
        "public long getEstimatedSize()",
        "Remote configuration of auth caches is disabled",
    ),
    "src/java/org/apache/cassandra/db/virtual/PermissionsCacheKeysTable.java": (
        'TableMetadata.builder(keyspace, "permissions_cache_keys")',
        ".addPartitionKeyColumn(ROLE, UTF8Type.instance)",
        ".addPartitionKeyColumn(RESOURCE, UTF8Type.instance)",
        "AuthenticatedUser.permissionsCache.getAll()",
        "AuthenticatedUser.permissionsCache.invalidate(Pair.create(user, resource));",
        "AuthenticatedUser.permissionsCache.invalidate();",
        "resourceFromNameIfExists",
    ),
    "src/java/org/apache/cassandra/db/virtual/RolesCacheKeysTable.java": (
        'TableMetadata.builder(keyspace, "roles_cache_keys")',
        ".addPartitionKeyColumn(ROLE, UTF8Type.instance)",
        "Roles.cache.getAll()",
        "Roles.cache.invalidate(roleResource);",
        "Roles.cache.invalidate();",
    ),
}

TEST_EXPECTATIONS = {
    "test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java": (
        "public class GrantAndRevokeTest extends CQLTester",
        "public void testGrantedKeyspace() throws Throwable",
        "public void testGrantedAllTables() throws Throwable",
        "public void testWarnings() throws Throwable",
        "Role '\" + user + \"' was already granted SELECT on <keyspace revoke_yeah>",
        "public void testSpecificGrantsOnSystemKeyspaces() throws Throwable",
        "Permission.INVALID_FOR_SYSTEM_KEYSPACES",
        "public void testGrantOnAllKeyspaces() throws Throwable",
        "public void testGrantOnVirtualKeyspaces() throws Throwable",
        "public void testAddIdentityPermissions() throws Throwable",
        "public void testRemoveIdentityPermissionsWithSpecificRolePermission() throws Throwable",
    ),
    "test/unit/org/apache/cassandra/auth/CassandraAuthorizerTest.java": (
        "public void testListPermissionsOfChildByParent() throws Throwable",
        "GRANT CREATE ON ALL ROLES TO %s",
    ),
    "test/unit/org/apache/cassandra/auth/CassandraAuthorizerTruncatingTest.java": (
        "public void testBulkLoadingForAuthCache()",
        "public void testBulkLoadingForAuthCachWithEmptyTable()",
    ),
    "test/unit/org/apache/cassandra/auth/RolesTest.java": (
        "public void superuserStatusIsCached()",
        "public void loginPrivilegeIsCached()",
        "public void grantedRoleDetailsAreCached()",
        "public void grantedRoleResourcesAreCached()",
        "public void confirmSuperUserConsistency()",
    ),
    "test/unit/org/apache/cassandra/auth/CassandraRoleManagerTest.java": (
        "public void getGrantedRolesImplMinimizesReads()",
        "public void warmCacheLoadsAllEntries()",
        "public void warmCacheWithEmptyTable()",
    ),
    "test/unit/org/apache/cassandra/db/virtual/PermissionsCacheKeysTableTest.java": (
        "SELECT * FROM vts.permissions_cache_keys",
        "DELETE FROM vts.permissions_cache_keys WHERE role='role_a' AND resource='data'",
        "DELETE FROM vts.permissions_cache_keys WHERE role='role_a' AND resource='invalid_resource'",
        "TRUNCATE vts.permissions_cache_keys",
        "Column modification is not supported by table vts.permissions_cache_keys",
    ),
    "test/unit/org/apache/cassandra/db/virtual/RolesCacheKeysTableTest.java": (
        "SELECT * FROM vts.roles_cache_keys",
        "DELETE FROM vts.roles_cache_keys WHERE role='role_a'",
        "DELETE FROM vts.roles_cache_keys WHERE role='invalid_role'",
        "TRUNCATE vts.roles_cache_keys",
        "Column modification is not supported by table vts.roles_cache_keys",
    ),
    "test/unit/org/apache/cassandra/cql3/validation/miscellaneous/RoleSyntaxTest.java": (
        "GRANT ALTER ON ROLE %s TO %s",
        "GRANT SELECT PERMISSION ON KEYSPACE ks TO %s",
        "REVOKE MODIFY, SELECT ON ALL KEYSPACES FROM %s",
        "LIST ALL PERMISSIONS ON ALL ROLES OF %s",
        "LIST MODIFY, SELECT PERMISSION ON KEYSPACE ks OF %s",
        'assertValidSyntax("LIST ROLES OF r1");',
    ),
}

DOC_EXPECTATIONS = {
    MATRIX_DOC: SCENARIOS + (
        "Permission And Role Matrix",
        "Permission enum",
        "resource_role_permissons_index",
        "LIST PERMISSIONS",
        "Auth cache lifecycle",
        "research/tools/check-permission-role-drift.py",
    ),
    CHECKER_DOC: SCENARIOS + (
        "Permission Role Drift Checker",
        "10 permissions",
        "13 scenarios",
        "resource_role_permissons_index",
    ),
    README_DOC: (
        "module-permission-role-matrix.md",
        "module-permission-role-drift-checker.md",
        "research/tools/check-permission-role-drift.py",
        "| Permission |",
    ),
    SOURCE_MAP_DOC: (
        "Permission role matrix",
        "module-permission-role-matrix.md",
        "module-permission-role-drift-checker.md",
        "research/tools/check-permission-role-drift.py",
        "src/java/org/apache/cassandra/auth/Permission.java:32",
        "src/java/org/apache/cassandra/auth/CassandraAuthorizer.java:73",
        "src/java/org/apache/cassandra/auth/CassandraRoleManager.java:318",
    ),
}


@dataclass
class Failure:
    category: str
    path: str
    detail: str


def read(path):
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def enum_body(text, enum_name):
    match = re.search(rf"\benum\s+{re.escape(enum_name)}\b", text)
    if not match:
        raise ValueError(f"Could not find enum {enum_name}")
    open_index = text.find("{", match.end())
    if open_index < 0:
        raise ValueError(f"Could not find body for enum {enum_name}")
    depth = 0
    for index in range(open_index, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[open_index + 1:index]
    raise ValueError(f"Unclosed enum {enum_name}")


def parse_permission_order():
    body = enum_body(read("src/java/org/apache/cassandra/auth/Permission.java"), "Permission")
    declarations = body.split(";", 1)[0]
    declarations = re.sub(r"/\*.*?\*/", "", declarations, flags=re.S)
    declarations = re.sub(r"//.*", "", declarations)
    return tuple(token.strip() for token in declarations.split(",") if token.strip())


def check_permission_order():
    actual = parse_permission_order()
    if actual != EXPECTED_PERMISSION_ORDER:
        return [Failure("enum", "Permission", f"expected {EXPECTED_PERMISSION_ORDER}, observed {actual}")], actual
    return [], actual


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
    parser = argparse.ArgumentParser(description="Check permission/role research coverage for drift.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable result")
    args = parser.parse_args(argv)

    failures = []
    order_failures, permission_order = check_permission_order()
    failures.extend(order_failures)
    failures.extend(check_tokens(SOURCE_EXPECTATIONS, "source"))
    failures.extend(check_tokens(TEST_EXPECTATIONS, "test"))
    failures.extend(check_tokens(DOC_EXPECTATIONS, "doc"))

    if args.json:
        print(json.dumps({
            "ok": not failures,
            "permission_order": permission_order,
            "scenario_count": len(SCENARIOS),
            "failures": [failure.__dict__ for failure in failures],
        }, indent=2, sort_keys=True))
    elif failures:
        for failure in failures:
            print(f"{failure.category}: {failure.path}: {failure.detail}", file=sys.stderr)
    else:
        print(
            "OK permission role drift checks passed "
            f"({len(permission_order)} permissions, {len(SCENARIOS)} scenarios)"
        )

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
