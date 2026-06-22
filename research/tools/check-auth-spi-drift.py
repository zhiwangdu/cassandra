#!/usr/bin/env python3
#
# Source-only drift check for Cassandra auth SPI compatibility docs.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = (
    "research/module-auth-spi-compatibility-matrix.md",
    "research/module-auth-spi-drift-checker.md",
    "research/module-schema-cql-auth.md",
    "research/module-permission-role-matrix.md",
)


@dataclass(frozen=True)
class InterfaceSpec:
    source: str
    interface: str
    scenario_id: str
    expected_methods: tuple[str, ...]


INTERFACES = (
    InterfaceSpec(
        source="src/java/org/apache/cassandra/auth/IAuthenticator.java",
        interface="IAuthenticator",
        scenario_id="auth_spi_i_authenticator",
        expected_methods=(
            "requireAuthentication/0",
            "protectedResources/0",
            "validateConfiguration/0",
            "setup/0",
            "getAuthenticateMessage/1",
            "newSaslNegotiator/1",
            "newSaslNegotiator/2",
            "legacyAuthenticate/1",
        ),
    ),
    InterfaceSpec(
        source="src/java/org/apache/cassandra/auth/IAuthenticator.java",
        interface="SaslNegotiator",
        scenario_id="auth_spi_i_authenticator_sasl_negotiator",
        expected_methods=("evaluateResponse/1", "isComplete/0", "getAuthenticatedUser/0"),
    ),
    InterfaceSpec(
        source="src/java/org/apache/cassandra/auth/IAuthorizer.java",
        interface="IAuthorizer",
        scenario_id="auth_spi_i_authorizer",
        expected_methods=(
            "requireAuthorization/0",
            "authorize/2",
            "grant/4",
            "revoke/4",
            "list/4",
            "revokeAllFrom/1",
            "revokeAllOn/1",
            "protectedResources/0",
            "validateConfiguration/0",
            "setup/0",
        ),
    ),
    InterfaceSpec(
        source="src/java/org/apache/cassandra/auth/IRoleManager.java",
        interface="IRoleManager",
        scenario_id="auth_spi_i_role_manager",
        expected_methods=(
            "supportedOptions/0",
            "alterableOptions/0",
            "createRole/3",
            "dropRole/2",
            "alterRole/3",
            "grantRole/3",
            "revokeRole/3",
            "getRoles/2",
            "getRoleDetails/1",
            "getAllRoles/0",
            "isSuper/1",
            "canLogin/1",
            "getCustomOptions/1",
            "isExistingRole/1",
            "protectedResources/0",
            "validateConfiguration/0",
            "setup/0",
            "roleForIdentity/1",
            "authorizedIdentities/0",
            "addIdentity/2",
            "isExistingIdentity/1",
            "dropIdentity/1",
        ),
    ),
    InterfaceSpec(
        source="src/java/org/apache/cassandra/auth/INetworkAuthorizer.java",
        interface="INetworkAuthorizer",
        scenario_id="auth_spi_i_network_authorizer",
        expected_methods=(
            "requireAuthorization/0",
            "setup/0",
            "authorize/1",
            "setRoleDatacenters/2",
            "drop/1",
            "validateConfiguration/0",
        ),
    ),
    InterfaceSpec(
        source="src/java/org/apache/cassandra/auth/ICIDRAuthorizer.java",
        interface="ICIDRAuthorizer",
        scenario_id="auth_spi_i_cidr_authorizer",
        expected_methods=(
            "setup/0",
            "initCaches/0",
            "getCidrGroupsMappingManager/0",
            "getCidrAuthorizerMetrics/0",
            "requireAuthorization/0",
            "setCidrGroupsForRole/2",
            "dropCidrPermissionsForRole/1",
            "invalidateCidrPermissionsCache/1",
            "validateConfiguration/0",
            "loadCidrGroupsCache/0",
            "lookupCidrGroupsForIp/1",
            "hasAccessFromIp/2",
        ),
    ),
)


CONFIG_KEYS = (
    "authenticator",
    "authorizer",
    "role_manager",
    "network_authorizer",
    "cidr_authorizer",
    "internode_authenticator",
)

AUTH_CONFIG_CONTRACTS = (
    "credentials_cache_max_entries may not be applicable",
    "authorization enabled which requires",
    "requires \" + CassandraRoleManager.class.getName()",
    "can't be used with \" + conf.authenticator.class_name",
    "can't be used with \" + conf.authenticator",
)


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)
    return text


def find_matching(text: str, open_index: int) -> int:
    depth = 0
    for index in range(open_index, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError(f"Unclosed brace at offset {open_index}")


def interface_body(text: str, interface: str) -> str:
    match = re.search(rf"\binterface\s+{re.escape(interface)}\b", text)
    if not match:
        raise ValueError(f"Could not find interface {interface}")
    open_index = text.find("{", match.end())
    if open_index < 0:
        raise ValueError(f"Could not find body for interface {interface}")
    close_index = find_matching(text, open_index)
    return text[open_index + 1:close_index]


def arity(parameters: str) -> int:
    parameters = parameters.strip()
    if not parameters:
        return 0

    parts: list[str] = []
    start = 0
    angle_depth = 0
    for index, char in enumerate(parameters):
        if char == "<":
            angle_depth += 1
        elif char == ">":
            angle_depth -= 1
        elif char == "," and angle_depth == 0:
            parts.append(parameters[start:index].strip())
            start = index + 1
    parts.append(parameters[start:].strip())
    return len([part for part in parts if part])


def extract_methods(source: str, interface: str) -> tuple[str, ...]:
    text = strip_comments((REPO_ROOT / source).read_text(encoding="utf-8"))
    body = interface_body(text, interface)
    methods: list[str] = []
    depth = 0
    method_pattern = re.compile(
        r"^\s*(?:public\s+)?(?:default\s+)?[A-Za-z0-9_<>, ?\[\].]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)"
    )

    for line in body.splitlines():
        stripped = line.strip()
        if depth == 0:
            if stripped.startswith(("public enum ", "enum ", "public interface ", "interface ")):
                depth += line.count("{") - line.count("}")
                continue
            match = method_pattern.match(line)
            if match and match.group(1) not in {"if", "for", "while", "return", "new", "throw", "catch", "switch"}:
                methods.append(f"{match.group(1)}/{arity(match.group(2))}")
        depth += line.count("{") - line.count("}")
        if depth < 0:
            depth = 0

    return tuple(methods)


def read_docs() -> str:
    parts: list[str] = []
    for doc in DOCS:
        path = REPO_ROOT / doc
        if not path.exists():
            raise FileNotFoundError(f"Missing doc {doc}")
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def documented(token: str, docs_text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])", docs_text) is not None


def config_fields() -> tuple[str, ...]:
    text = strip_comments((REPO_ROOT / "src/java/org/apache/cassandra/config/Config.java").read_text(encoding="utf-8"))
    return tuple(re.findall(r"\bParameterizedClass\s+([A-Za-z0-9_]+)\s*;", text))


def check() -> tuple[list[dict[str, object]], bool]:
    docs_text = read_docs()
    results: list[dict[str, object]] = []
    ok = True

    for spec in INTERFACES:
        parsed = extract_methods(spec.source, spec.interface)
        missing_methods = [method for method in spec.expected_methods if method not in parsed]
        extra_methods = [method for method in parsed if method not in spec.expected_methods]
        missing_docs = [method for method in spec.expected_methods if not documented(method, docs_text)]
        scenario_missing = not documented(spec.scenario_id, docs_text)
        if missing_methods or extra_methods or missing_docs or scenario_missing:
            ok = False
        results.append(
            {
                "kind": "interface",
                "source": spec.source,
                "interface": spec.interface,
                "scenario_id": spec.scenario_id,
                "parsed_methods": parsed,
                "expected_methods": spec.expected_methods,
                "missing_methods": missing_methods,
                "extra_methods": extra_methods,
                "missing_docs": missing_docs,
                "scenario_missing": scenario_missing,
            }
        )

    fields = config_fields()
    missing_config = [key for key in CONFIG_KEYS if key not in fields]
    missing_config_docs = [key for key in CONFIG_KEYS if not documented(key, docs_text)]
    auth_config_text = (REPO_ROOT / "src/java/org/apache/cassandra/auth/AuthConfig.java").read_text(encoding="utf-8")
    missing_auth_config_contracts = [fragment for fragment in AUTH_CONFIG_CONTRACTS if fragment not in auth_config_text]
    missing_auth_config_docs = [
        scenario
        for scenario in ("auth_spi_backend_config_keys", "auth_spi_auth_config_dependency_gates")
        if not documented(scenario, docs_text)
    ]
    if missing_config or missing_config_docs or missing_auth_config_contracts or missing_auth_config_docs:
        ok = False
    results.append(
        {
            "kind": "config",
            "source": "src/java/org/apache/cassandra/config/Config.java",
            "auth_config_source": "src/java/org/apache/cassandra/auth/AuthConfig.java",
            "config_keys": CONFIG_KEYS,
            "parsed_parameterized_fields": fields,
            "missing_config": missing_config,
            "missing_config_docs": missing_config_docs,
            "missing_auth_config_contracts": missing_auth_config_contracts,
            "missing_auth_config_docs": missing_auth_config_docs,
        }
    )

    return results, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check auth SPI compatibility matrix coverage.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable results")
    args = parser.parse_args()

    try:
        results, ok = check()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        for result in results:
            if result["kind"] == "interface":
                issues = result["missing_methods"] or result["extra_methods"] or result["missing_docs"] or result["scenario_missing"]
                status = "OK" if not issues else "MISMATCH"
                print(f"{status} {result['interface']}: {len(result['expected_methods'])} method contracts")
                if issues:
                    for key in ("missing_methods", "extra_methods", "missing_docs"):
                        if result[key]:
                            print(f"  {key}: " + ", ".join(result[key]))
                    if result["scenario_missing"]:
                        print(f"  missing scenario: {result['scenario_id']}")
            else:
                issues = (
                    result["missing_config"]
                    or result["missing_config_docs"]
                    or result["missing_auth_config_contracts"]
                    or result["missing_auth_config_docs"]
                )
                status = "OK" if not issues else "MISMATCH"
                print(f"{status} auth config backend keys: {len(result['config_keys'])} checked keys")
                if issues:
                    for key in (
                        "missing_config",
                        "missing_config_docs",
                        "missing_auth_config_contracts",
                        "missing_auth_config_docs",
                    ):
                        if result[key]:
                            print(f"  {key}: " + ", ".join(result[key]))
        if ok:
            print("Auth SPI compatibility docs are in sync with checked source contracts.")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
