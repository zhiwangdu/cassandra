# JMX Auth Permission Drift Checker

`research/tools/check-jmx-auth-permission-drift.py` protects the JMX auth permission matrix from source drift. It is source-only and fast: it does not start JMX, Cassandra, or nodetool.

## What It Checks

| Area | Checks |
| --- | --- |
| Proxy entry | `AuthorizationProxy.invoke()` still rejects direct MBeanServer access, supports connector-only setup and gates remote subjects through `authorize()`. |
| Permission mapping | JMX method names still map to `SELECT`, `MODIFY`, `EXECUTE`, and `DESCRIBE` as documented; unknown methods still fail. |
| Pattern matching | Root, exact ObjectName, wildcard grant and wildcard target coverage logic still uses `ObjectName.apply()` and `queryNames()` coverage. |
| Vulnerable methods | Denied MBeanServer methods and risky DiagnosticCommand/MLet operations remain blocked. |
| Cache and operations | `JmxPermissionsCache`, MBean names, virtual cache-key table, `NodeProbe` and nodetool invalidation remain aligned. |
| Tests and docs | Matrix, README, source-map and existing unit test anchors still contain the documented contracts and scenario IDs. |

## Run

```bash
python3 research/tools/check-jmx-auth-permission-drift.py
```

Expected output:

```text
OK JMX auth permission drift checks passed (12 scenarios)
```

## Scenario IDs

- `jmx_auth_proxy_entry_contract`
- `jmx_auth_setup_and_subject_contract`
- `jmx_auth_mbean_server_describe_contract`
- `jmx_auth_method_permission_map_contract`
- `jmx_auth_denied_vulnerable_methods_contract`
- `jmx_auth_exact_root_match_contract`
- `jmx_auth_wildcard_coverage_contract`
- `jmx_auth_cache_loader_contract`
- `jmx_auth_cache_mbean_contract`
- `jmx_auth_virtual_cache_keys_contract`
- `jmx_auth_nodetool_invalidation_contract`
- `jmx_auth_existing_tests_baseline`

## Maintenance

- If `AuthorizationProxy.getRequiredPermission()` changes, update the matrix and tests for JMX method permission semantics.
- If a new hard-denied JMX operation is added, document the vulnerability class and add a source token here.
- If JMX cache naming or invalidation changes, update this matrix, `module-observability-internals.md` and nodetool docs together.
