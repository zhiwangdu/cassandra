#!/usr/bin/env python3
#
# Source-only drift check for consistency-level guardrail profile coverage.

import argparse
import glob
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CL_SOURCE = "src/java/org/apache/cassandra/db/ConsistencyLevel.java"
GUARDRAILS_SOURCE = "src/java/org/apache/cassandra/db/guardrails/Guardrails.java"
CONFIG_SOURCE = "src/java/org/apache/cassandra/config/Config.java"
OPTIONS_SOURCE = "src/java/org/apache/cassandra/config/GuardrailsOptions.java"
MBEAN_SOURCE = "src/java/org/apache/cassandra/db/guardrails/GuardrailsMBean.java"
PROVIDER_SOURCE = "src/java/org/apache/cassandra/db/guardrails/GuardrailsConfigProvider.java"
PROPERTIES_SOURCE = "src/java/org/apache/cassandra/config/CassandraRelevantProperties.java"
PROFILE_DOCS = ("research/module-consistency-guardrail-profiles.md",)
YAML_SOURCES = ("conf/cassandra.yaml", "conf/cassandra_latest.yaml")

ENTRYPOINTS = {
    "read_select": "src/java/org/apache/cassandra/cql3/statements/SelectStatement.java",
    "write_modification": "src/java/org/apache/cassandra/cql3/statements/ModificationStatement.java",
    "write_batch": "src/java/org/apache/cassandra/cql3/statements/BatchStatement.java",
}

TEST_SOURCES = (
    "test/unit/org/apache/cassandra/db/guardrails/GuardrailConsistencyLevelsTester.java",
    "test/unit/org/apache/cassandra/db/guardrails/GuardrailReadConsistencyLevelsTest.java",
    "test/unit/org/apache/cassandra/db/guardrails/GuardrailWriteConsistencyLevelsTest.java",
    "test/unit/org/apache/cassandra/db/guardrails/GuardrailsConfigProviderTest.java",
)

PROPERTIES = (
    "read_consistency_levels_warned",
    "read_consistency_levels_disallowed",
    "write_consistency_levels_warned",
    "write_consistency_levels_disallowed",
)

EXPECTED_PROFILES = (
    "profile_default_observe",
    "profile_local_dc_oltp",
    "profile_no_lwt_service",
    "profile_cross_dc_strict",
    "profile_bulk_ingest",
)


@dataclass(frozen=True)
class SourceCheck:
    name: str
    source: str
    ok: bool


@dataclass(frozen=True)
class Profile:
    name: str
    properties: dict[str, list[str]]


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)
    return text


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def consistency_levels() -> list[str]:
    lines = strip_comments(read(CL_SOURCE)).splitlines()
    in_enum = False
    entries: list[str] = []

    for line in lines:
        if not in_enum:
            if re.search(r"\bpublic\s+enum\s+ConsistencyLevel\b", line):
                in_enum = True
            continue

        if re.match(r"\s*;", line):
            break

        match = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*\(", line)
        if match:
            entries.append(match.group(1))

    if not entries:
        raise ValueError(f"Could not parse consistency levels from {CL_SOURCE}")
    return entries


def source_checks() -> list[SourceCheck]:
    guardrails = read(GUARDRAILS_SOURCE)
    config = read(CONFIG_SOURCE)
    options = read(OPTIONS_SOURCE)
    mbean = read(MBEAN_SOURCE)
    provider = read(PROVIDER_SOURCE)
    properties_source = read(PROPERTIES_SOURCE)
    tests = "\n".join(read(path) for path in TEST_SOURCES)

    checks: list[SourceCheck] = [
        SourceCheck("read Values guardrail", GUARDRAILS_SOURCE, 'new Values<>("read_consistency_levels"' in guardrails),
        SourceCheck("write Values guardrail", GUARDRAILS_SOURCE, 'new Values<>("write_consistency_levels"' in guardrails),
        SourceCheck("read select entrypoint", ENTRYPOINTS["read_select"], re.search(r"Guardrails\.readConsistencyLevels\.guard\s*\(\s*EnumSet\.of\s*\(\s*cl\s*\)", read(ENTRYPOINTS["read_select"]), re.S) is not None),
        SourceCheck("write modification entrypoint", ENTRYPOINTS["write_modification"], re.search(r"Guardrails\.writeConsistencyLevels\.guard\s*\(\s*EnumSet\.of\s*\(\s*options\.getConsistency\s*\(\s*\)\s*,\s*options\.getSerialConsistency\s*\(\s*\)\s*\)", read(ENTRYPOINTS["write_modification"]), re.S) is not None),
        SourceCheck("write batch entrypoint", ENTRYPOINTS["write_batch"], re.search(r"Guardrails\.writeConsistencyLevels\.guard\s*\(\s*EnumSet\.of\s*\(\s*options\.getConsistency\s*\(\s*\)\s*,\s*options\.getSerialConsistency\s*\(\s*\)\s*\)", read(ENTRYPOINTS["write_batch"]), re.S) is not None),
        SourceCheck("custom config provider property source", PROPERTIES_SOURCE, 'CUSTOM_GUARDRAILS_CONFIG_PROVIDER_CLASS("cassandra.custom_guardrails_config_provider_class")' in properties_source),
        SourceCheck("custom config provider runtime hook", PROVIDER_SOURCE, "CUSTOM_GUARDRAILS_CONFIG_PROVIDER_CLASS.getString()" in provider and "getOrCreate(@Nullable ClientState state)" in provider),
        SourceCheck("test accepts all consistency levels", TEST_SOURCES[0], "EnumSet.allOf(ConsistencyLevel.class)" in tests),
    ]

    for prop in PROPERTIES:
        camel = "".join(part.capitalize() for part in prop.split("_"))
        checks.extend(
            [
                SourceCheck(f"config default {prop}", CONFIG_SOURCE, re.search(rf"Set<ConsistencyLevel>\s+{re.escape(prop)}\s*=\s*Collections\.emptySet\(\)", config) is not None),
                SourceCheck(f"options validate {prop}", OPTIONS_SOURCE, f'validateConsistencyLevels(config.{prop}, "{prop}")' in options),
                SourceCheck(f"options update {prop}", OPTIONS_SOURCE, f'updatePropertyWithLogging("{prop}"' in options),
                SourceCheck(f"mbean get {prop}", MBEAN_SOURCE, f"get{camel}()" in mbean),
                SourceCheck(f"mbean set {prop}", MBEAN_SOURCE, f"set{camel}(Set<String> consistencyLevels)" in mbean),
                SourceCheck(f"mbean get csv {prop}", MBEAN_SOURCE, f"get{camel}CSV()" in mbean),
                SourceCheck(f"mbean set csv {prop}", MBEAN_SOURCE, f"set{camel}CSV(String consistencyLevels)" in mbean),
                SourceCheck(f"tests mention {prop}", " / ".join(TEST_SOURCES), prop in tests),
            ]
        )

    for yaml_source in YAML_SOURCES:
        yaml_text = read(yaml_source)
        for prop in PROPERTIES:
            checks.append(SourceCheck(f"yaml template {prop}", yaml_source, prop in yaml_text))

    return checks


def read_doc_text(patterns: tuple[str, ...]) -> str:
    parts: list[str] = []
    for pattern in patterns:
        matches = sorted(glob.glob(str(REPO_ROOT / pattern)))
        if not matches:
            raise FileNotFoundError(f"No research docs matched {pattern}")
        for match in matches:
            parts.append(Path(match).read_text(encoding="utf-8"))
    return "\n".join(parts)


def parse_array(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw:
        return []
    values: list[str] = []
    for item in raw.split(","):
        token = item.strip().strip("'\"`")
        if token:
            values.append(token)
    return values


def parse_profiles(text: str) -> list[Profile]:
    heading = re.compile(r"^###\s+`?(profile_[A-Za-z0-9_]+)`?\s*$", re.M)
    matches = list(heading.finditer(text))
    profiles: list[Profile] = []

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end]
        yaml_match = re.search(r"```yaml\s*\n(.*?)```", block, re.S)
        if not yaml_match:
            profiles.append(Profile(match.group(1), {}))
            continue

        properties: dict[str, list[str]] = {}
        for line in yaml_match.group(1).splitlines():
            prop_match = re.match(r"\s*([a-z_]+)\s*:\s*\[(.*?)\]\s*$", line)
            if prop_match:
                properties[prop_match.group(1)] = parse_array(prop_match.group(2))
        profiles.append(Profile(match.group(1), properties))

    return profiles


def check() -> tuple[dict[str, object], bool]:
    cl_entries = consistency_levels()
    cl_set = set(cl_entries)
    doc_text = read_doc_text(PROFILE_DOCS)
    profiles = parse_profiles(doc_text)
    checks = source_checks()

    documented_cls = [cl for cl in cl_entries if documented(cl, doc_text)]
    missing_cls = [cl for cl in cl_entries if cl not in documented_cls]
    missing_properties = [prop for prop in PROPERTIES if not documented(prop, doc_text)]
    missing_profiles = [profile for profile in EXPECTED_PROFILES if profile not in {entry.name for entry in profiles}]

    profile_results = []
    for profile in profiles:
        missing_profile_props = [prop for prop in PROPERTIES if prop not in profile.properties]
        extra_profile_props = [prop for prop in profile.properties if prop not in PROPERTIES]
        invalid_values = {
            prop: [value for value in values if value not in cl_set]
            for prop, values in profile.properties.items()
        }
        invalid_values = {prop: values for prop, values in invalid_values.items() if values}
        duplicate_values = {
            prop: sorted({value for value in values if values.count(value) > 1})
            for prop, values in profile.properties.items()
        }
        duplicate_values = {prop: values for prop, values in duplicate_values.items() if values}
        profile_results.append(
            {
                "name": profile.name,
                "properties": profile.properties,
                "missing_properties": missing_profile_props,
                "extra_properties": extra_profile_props,
                "invalid_values": invalid_values,
                "duplicate_values": duplicate_values,
            }
        )

    result = {
        "consistency_level_source": CL_SOURCE,
        "profile_docs": list(PROFILE_DOCS),
        "properties": list(PROPERTIES),
        "expected_profiles": list(EXPECTED_PROFILES),
        "consistency_levels": cl_entries,
        "missing_consistency_levels_from_docs": missing_cls,
        "missing_properties_from_docs": missing_properties,
        "missing_profiles": missing_profiles,
        "source_checks": [entry.__dict__ for entry in checks],
        "profiles": profile_results,
    }

    ok = not missing_cls and not missing_properties and not missing_profiles
    ok = ok and all(entry.ok for entry in checks)
    ok = ok and all(
        not profile["missing_properties"]
        and not profile["extra_properties"]
        and not profile["invalid_values"]
        and not profile["duplicate_values"]
        for profile in profile_results
    )
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check consistency-level guardrail profile coverage in research docs.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    try:
        result, ok = check()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"OK consistency levels parsed: {len(result['consistency_levels'])} constants from {CL_SOURCE}")
        print(f"OK profiles parsed: {len(result['profiles'])} profiles from {', '.join(PROFILE_DOCS)}")

        failed_checks = [entry for entry in result["source_checks"] if not entry["ok"]]
        if failed_checks:
            print("Source contract checks failed:")
            for entry in failed_checks:
                print(f"  {entry['name']} ({entry['source']})")

        if result["missing_consistency_levels_from_docs"]:
            print("ConsistencyLevel constants missing from profile docs:")
            for name in result["missing_consistency_levels_from_docs"]:
                print(f"  {name}")

        if result["missing_properties_from_docs"]:
            print("Guardrail properties missing from profile docs:")
            for name in result["missing_properties_from_docs"]:
                print(f"  {name}")

        if result["missing_profiles"]:
            print("Expected profile IDs missing from profile docs:")
            for name in result["missing_profiles"]:
                print(f"  {name}")

        for profile in result["profiles"]:
            if profile["missing_properties"] or profile["extra_properties"] or profile["invalid_values"] or profile["duplicate_values"]:
                print(f"Profile {profile['name']} has drift:")
                if profile["missing_properties"]:
                    print("  missing properties: " + ", ".join(profile["missing_properties"]))
                if profile["extra_properties"]:
                    print("  extra properties: " + ", ".join(profile["extra_properties"]))
                if profile["invalid_values"]:
                    print("  invalid CL values: " + json.dumps(profile["invalid_values"], sort_keys=True))
                if profile["duplicate_values"]:
                    print("  duplicate CL values: " + json.dumps(profile["duplicate_values"], sort_keys=True))

        if ok:
            print("Consistency guardrail profile research docs are in sync with parsed source contracts.")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
