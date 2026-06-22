# Permission Role Drift Checker

`research/tools/check-permission-role-drift.py` protects `module-permission-role-matrix.md` from source drift. It is source-only and fast: it does not start Cassandra, create roles, or run CQL tests.

## What It Checks

| Area | Checks |
| --- | --- |
| Permission enum | Verifies the documented `Permission` enum order stays `CREATE, ALTER, DROP, SELECT, MODIFY, AUTHORIZE, DESCRIBE, EXECUTE, UNMASK, SELECT_MASKED`; Cassandra notes that authorizer implementations may encode ordinals. |
| Resource permission sets | Ensures `DataResource`, `FunctionResource`, `RoleResource`, and `JMXResource` still expose the documented grantable permission surfaces. |
| Statement flow | Checks GRANT/REVOKE/LIST permission statements and GRANT/REVOKE role statements still validate login, role/resource existence, `AUTHORIZE`, client warnings and audit contexts. |
| Default backend | Checks `AuthKeyspace`, `CassandraAuthorizer`, `CassandraRoleManager`, `ClientState`, roles/permissions caches and virtual cache-key tables still match the matrix contracts. |
| Tests | Ensures the matrix still points to grant/revoke behavior tests, LIST visibility, cache bulk-load tests, virtual cache-key table tests and role syntax tests. |
| Docs | Ensures README and source-map link the matrix, checker doc and script, and that every `permission_role_*` scenario appears in both docs. |

## Run

```bash
python3 research/tools/check-permission-role-drift.py
```

Expected output:

```text
OK permission role drift checks passed (10 permissions, 13 scenarios)
```

## Scenario IDs

- `permission_role_enum_order_contract`
- `permission_role_resource_matrix_contract`
- `permission_role_grant_revoke_statement_contract`
- `permission_role_system_keyspace_guard_contract`
- `permission_role_membership_contract`
- `permission_role_list_visibility_contract`
- `permission_role_backend_storage_contract`
- `permission_role_auth_chain_contract`
- `permission_role_cache_contract`
- `permission_role_virtual_cache_keys_contract`
- `permission_role_audit_warning_contract`
- `permission_role_existing_tests_baseline`
- `permission_role_spi_boundary`

## Maintenance

- If a permission enum value is added, append it only, then update the checker expected order, the resource matrix and affected syntax/behavior tests.
- If a resource class changes grantable permissions, update `module-permission-role-matrix.md` and this checker in the same change.
- If `system_auth` table names or reverse-index semantics change, update both the matrix and operational notes; the checker intentionally protects the historical `resource_role_permissons_index` spelling.
- If this checker is wired into CI, add the CI entry to the matrix and README.
