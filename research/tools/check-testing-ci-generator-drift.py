#!/usr/bin/env python3
#
# Source-only drift check for CircleCI generator research coverage.

import argparse
import glob
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

SOURCE_PATHS = {
    "generate": ".circleci/generate.sh",
    "template": ".circleci/config_template.yml",
    "paid_patch": ".circleci/config_template.yml.PAID.patch",
    "config": ".circleci/config.yml",
    "config_free": ".circleci/config.yml.FREE",
    "config_paid": ".circleci/config.yml.PAID",
    "circleci_readme": ".circleci/readme.md",
    "build_xml": "build.xml",
    "parent_pom": ".build/parent-pom-template.xml",
    "build_deps": ".build/cassandra-build-deps-template.xml",
}

TARGET_DOCS = (
    "research/module-testing-ci-generator-matrix.md",
    "research/module-testing-ci-generator-drift-checker.md",
)

SCENARIO_IDS = (
    "ci_generator_default_free",
    "ci_generator_paid_patch",
    "ci_generator_env_allowlist",
    "ci_generator_changed_test_detection",
    "ci_generator_repeated_job_pruning",
    "ci_generated_free_paid_artifacts",
    "ci_dtest_api_artifact_boundary",
    "ci_docs_generator_workflow",
)

EXPECTED_ALLOWLIST = (
    "DTEST_REPO",
    "DTEST_BRANCH",
    "REPEATED_TESTS_STOP_ON_FAILURE",
    "REPEATED_UTESTS",
    "REPEATED_UTESTS_COUNT",
    "REPEATED_UTESTS_FQLTOOL",
    "REPEATED_UTESTS_FQLTOOL_COUNT",
    "REPEATED_UTESTS_LONG",
    "REPEATED_UTESTS_LONG_COUNT",
    "REPEATED_UTESTS_STRESS",
    "REPEATED_UTESTS_STRESS_COUNT",
    "REPEATED_SIMULATOR_DTESTS",
    "REPEATED_SIMULATOR_DTESTS_COUNT",
    "REPEATED_JVM_DTESTS",
    "REPEATED_JVM_DTESTS_COUNT",
    "REPEATED_JVM_UPGRADE_DTESTS",
    "REPEATED_JVM_UPGRADE_DTESTS_COUNT",
    "REPEATED_DTESTS",
    "REPEATED_DTESTS_COUNT",
    "REPEATED_LARGE_DTESTS",
    "REPEATED_LARGE_DTESTS_COUNT",
    "REPEATED_UPGRADE_DTESTS",
    "REPEATED_UPGRADE_DTESTS_COUNT",
    "REPEATED_ANT_TEST_TARGET",
    "REPEATED_ANT_TEST_CLASS",
    "REPEATED_ANT_TEST_METHODS",
    "REPEATED_ANT_TEST_VNODES",
    "REPEATED_ANT_TEST_COUNT",
)

CHANGED_TEST_MAPPINGS = (
    ("REPEATED_UTESTS", "test/unit/", "org.apache.cassandra"),
    ("REPEATED_UTESTS_LONG", "test/long/", "org.apache.cassandra"),
    ("REPEATED_UTESTS_STRESS", "tools/stress/test/unit/", "org.apache.cassandra.stress"),
    ("REPEATED_UTESTS_FQLTOOL", "tools/fqltool/test/unit/", "org.apache.cassandra.fqltool"),
    ("REPEATED_SIMULATOR_DTESTS", "test/simulator/test/", "org.apache.cassandra.simulator.test"),
    ("REPEATED_JVM_DTESTS", "test/distributed/", "org.apache.cassandra.distributed.test"),
    ("REPEATED_JVM_UPGRADE_DTESTS", "test/distributed/", "org.apache.cassandra.distributed.upgrade"),
)

REPEATED_PRUNE_GROUPS = {
    "REPEATED_UTESTS": ("j11_unit_tests_repeat", "j17_unit_tests_repeat"),
    "REPEATED_UTESTS_LONG": ("j11_utests_long_repeat", "j17_utests_long_repeat"),
    "REPEATED_UTESTS_STRESS": ("j11_utests_stress_repeat", "j17_utests_stress_repeat"),
    "REPEATED_UTESTS_FQLTOOL": ("j11_utests_fqltool_repeat", "j17_utests_fqltool_repeat"),
    "REPEATED_SIMULATOR_DTESTS": ("j11_simulator_dtests_repeat",),
    "REPEATED_JVM_DTESTS": ("j11_jvm_dtests_repeat", "j17_jvm_dtests_repeat"),
    "REPEATED_JVM_UPGRADE_DTESTS": ("j11_jvm_upgrade_dtests_repeat",),
    "REPEATED_DTESTS": ("j11_dtests_repeat", "j17_dtests_repeat"),
    "REPEATED_LARGE_DTESTS": ("j11_dtests_large_repeat", "j17_dtests_large_repeat"),
    "REPEATED_UPGRADE_DTESTS": ("j11_upgrade_dtests_repeat",),
    "REPEATED_ANT_TEST_CLASS": ("j11_repeated_ant_test", "j17_repeated_ant_test"),
}

DOC_REQUIRED_TOKENS = (
    ".circleci/generate.sh",
    ".circleci/config_template.yml",
    ".circleci/config_template.yml.PAID.patch",
    ".circleci/config.yml.FREE",
    ".circleci/config.yml.PAID",
    "circleci config process",
    "dtest-api",
    "dtest-jar",
    "ci_generator_env_allowlist",
    "ci_dtest_api_artifact_boundary",
) + EXPECTED_ALLOWLIST


@dataclass(frozen=True)
class SourceCheck:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def template_env_keys() -> set[str]:
    text = read(SOURCE_PATHS["template"])
    block = text.split("j11_par_executor:", 1)[0]
    return set(re.findall(r"^    ([A-Z0-9_]+):", block, re.M))


def generate_allowlist() -> set[str]:
    text = read(SOURCE_PATHS["generate"])
    return set(re.findall(r'\[ "\$key" != "([^"]+)" \]', text))


def find_dtest_api_artifacts() -> list[str]:
    matches: list[str] = []
    for pattern in ("**/*dtest-api*", "**/*dtest*api*"):
        for match in glob.glob(str(REPO_ROOT / pattern), recursive=True):
            rel = str(Path(match).relative_to(REPO_ROOT))
            if rel.startswith(".git/"):
                continue
            if rel in (SOURCE_PATHS["parent_pom"], SOURCE_PATHS["build_deps"]):
                continue
            matches.append(rel)
    return sorted(set(matches))


def source_checks() -> list[SourceCheck]:
    generate = read(SOURCE_PATHS["generate"])
    template = read(SOURCE_PATHS["template"])
    paid_patch = read(SOURCE_PATHS["paid_patch"])
    config = read(SOURCE_PATHS["config"])
    config_free = read(SOURCE_PATHS["config_free"])
    config_paid = read(SOURCE_PATHS["config_paid"])
    readme = read(SOURCE_PATHS["circleci_readme"])
    build_xml = read(SOURCE_PATHS["build_xml"])
    parent_pom = read(SOURCE_PATHS["parent_pom"])
    build_deps = read(SOURCE_PATHS["build_deps"])

    env_keys = template_env_keys()
    allowlist = generate_allowlist()
    expected = set(EXPECTED_ALLOWLIST)

    checks: list[SourceCheck] = [
        SourceCheck("Generated default config is FREE config", f"{SOURCE_PATHS['config']} / {SOURCE_PATHS['config_free']}", config == config_free),
        SourceCheck("Generated FREE and PAID configs differ", f"{SOURCE_PATHS['config_free']} / {SOURCE_PATHS['config_paid']}", config_free != config_paid),
        SourceCheck("Generated config files exist with CircleCI version", ".circleci/config*.yml", all("version: 2" in text for text in (config, config_free, config_paid))),
        SourceCheck("Template has default env vars block", SOURCE_PATHS["template"], "default_env_vars: &default_env_vars" in template and "DTEST_REPO: https://github.com/apache/cassandra-dtest.git" in template and "REPEATED_ANT_TEST_COUNT: 500" in template),
        SourceCheck("Generate allowlist matches expected keys", SOURCE_PATHS["generate"], allowlist == expected),
        SourceCheck("Generate allowlist is subset of template env vars", f"{SOURCE_PATHS['generate']} / {SOURCE_PATHS['template']}", allowlist.issubset(env_keys)),
        SourceCheck("Template includes all expected allowlist keys", SOURCE_PATHS["template"], expected.issubset(env_keys)),
        SourceCheck("Generate has main mode flags", SOURCE_PATHS["generate"], all(token in generate for token in ("-a Generate", "-f Generate", "-p Generate", "-d Minimal", "-s Skip automatic"))),
        SourceCheck("Generate enforces incompatible modes", SOURCE_PATHS["generate"], "Cannot use option -f with options -a or -p" in generate and "Cannot use option -p with options -a or -f" in generate and "Cannot use option -a with options -f, -p or -e" in generate),
        SourceCheck("Generate invokes CircleCI process for free/all", SOURCE_PATHS["generate"], "circleci config process $BASEDIR/config_template.yml" in generate and "cat $BASEDIR/license.yml" in generate),
        SourceCheck("Generate applies PAID patch", SOURCE_PATHS["generate"], "patch -o $BASEDIR/config_template.yml.PAID" in generate and "config_template.yml.PAID.patch" in generate),
        SourceCheck("Generate all mode copies FREE to default", SOURCE_PATHS["generate"], "cp $BASEDIR/config.yml.FREE $BASEDIR/config.yml" in generate),
        SourceCheck("Generate checks base branch for changed tests", SOURCE_PATHS["generate"], "BASE_BRANCH=cassandra-5.0" in generate and "git show ${BASE_BRANCH}" in generate and "git --no-pager diff --name-only --diff-filter=AMR ${BASE_BRANCH}...HEAD" in generate),
        SourceCheck("Generate rejects dev-min with repeated detection", SOURCE_PATHS["generate"], '-d doesn\'t support repeated tests. Use -s to skip it.' in generate),
        SourceCheck("Generate replaces env vars in config", SOURCE_PATHS["generate"], 'sed -i.bak "s|- $key:.*|- $key: $val|"' in generate),
        SourceCheck("Generate defines repeated job pruning", SOURCE_PATHS["generate"], "delete_repeated_jobs()" in generate and "delete_job \"$1\"" in generate),
        SourceCheck("Generate defines dev-min pruning", SOURCE_PATHS["generate"], "build_dev_min_jobs()" in generate and "java11_dev_tests" in generate and "java17_dev_tests" in generate),
        SourceCheck("PAID patch raises parallelism", SOURCE_PATHS["paid_patch"], "parallelism: 25" in paid_patch and "parallelism: 50" in paid_patch and "parallelism: 100" in paid_patch),
        SourceCheck("PAID patch adds resource classes", SOURCE_PATHS["paid_patch"], "exec_resource_class: large" in paid_patch and "exec_resource_class: xlarge" in paid_patch),
        SourceCheck("PAID generated config has paid resources", SOURCE_PATHS["config_paid"], "parallelism: 25" in config_paid and "parallelism: 50" in config_paid and "parallelism: 100" in config_paid and "resource_class: xlarge" in config_paid),
        SourceCheck("FREE generated config has conservative repeated parallelism", SOURCE_PATHS["config_free"], "parallelism: 4" in config_free and "- REPEATED_UTESTS_COUNT: 500" in config_free and "- REPEATED_LARGE_DTESTS_COUNT: 100" in config_free),
        SourceCheck("Template contains timing split commands", SOURCE_PATHS["template"], "circleci tests split --split-by=timings --timings-type=filename" in template and "circleci tests split --split-by=timings --timings-type=classname" in template),
        SourceCheck("Template stores test results and artifacts", SOURCE_PATHS["template"], "store_test_results:" in template and "store_artifacts:" in template and "/tmp/results/repeated_utests" in template and "system_views" not in template),
        SourceCheck("Template contains repeated Python and JUnit commands", SOURCE_PATHS["template"], "run_repeated_utests:" in template and "run_repeated_dtest:" in template and "REPEATED_TESTS_STOP_ON_FAILURE" in template),
        SourceCheck("CircleCI README documents generated default/free/paid", SOURCE_PATHS["circleci_readme"], "automatically generated by the `generate.sh` script" in readme and "config.yml.FREE" in readme and "config.yml.PAID" in readme and "default `config.yml` file is just a copy of `config.yml.FREE`" in readme),
        SourceCheck("CircleCI README documents permanent workflow", SOURCE_PATHS["circleci_readme"], "regenerate the `config.yml`, `config.yml.FREE` and `config.yml.PAID`" in readme and "`-a` flag" in readme),
        SourceCheck("CircleCI README documents env override and repeated tests", SOURCE_PATHS["circleci_readme"], "DTEST_REPO" in readme and "REPEATED_UTESTS" in readme and "REPEATED_JVM_DTESTS" in readme and "REPEATED_ANT_TEST_TARGET" in readme),
        SourceCheck("Parent pom declares dtest-api dependency", SOURCE_PATHS["parent_pom"], "<groupId>org.apache.cassandra</groupId>" in parent_pom and "<artifactId>dtest-api</artifactId>" in parent_pom and "<version>0.0.18</version>" in parent_pom),
        SourceCheck("Build deps declares dtest-api", SOURCE_PATHS["build_deps"], "<artifactId>dtest-api</artifactId>" in build_deps),
        SourceCheck("Build dtest-jar consumes dtest-api jar", SOURCE_PATHS["build_xml"], '<target name="dtest-jar"' in build_xml and "dtest-api-*.jar" in build_xml and 'jarfile="${build.dir}/dtest-${base.version}.jar"' in build_xml),
        SourceCheck("Current tree has no dtest-api artifact to inspect", "**/*dtest-api*", not find_dtest_api_artifacts()),
    ]

    for env, path, package in CHANGED_TEST_MAPPINGS:
        checks.append(SourceCheck(f"Changed-test mapping {env}", SOURCE_PATHS["generate"], f'add_diff_tests "{env}" "{path}" "{package}"' in generate))

    for env, jobs in REPEATED_PRUNE_GROUPS.items():
        ok = f'grep -q "{env}="' in generate and all(job in generate for job in jobs)
        checks.append(SourceCheck(f"Repeated job pruning {env}", SOURCE_PATHS["generate"], ok))

    return checks


def read_doc_text() -> str:
    return "\n".join(read(path) for path in TARGET_DOCS)


def doc_checks() -> list[SourceCheck]:
    text = read_doc_text()
    checks = [SourceCheck(f"doc scenario {scenario}", " / ".join(TARGET_DOCS), documented(scenario, text)) for scenario in SCENARIO_IDS]
    checks.extend(SourceCheck(f"doc token {token}", " / ".join(TARGET_DOCS), token in text) for token in DOC_REQUIRED_TOKENS)
    return checks


def check() -> tuple[dict[str, object], bool]:
    sources = source_checks()
    docs = doc_checks()
    result = {
        "source_paths": SOURCE_PATHS,
        "docs": list(TARGET_DOCS),
        "scenario_ids": list(SCENARIO_IDS),
        "template_env_keys": sorted(template_env_keys()),
        "generate_allowlist": sorted(generate_allowlist()),
        "changed_test_mappings": [
            {"env": env, "path": path, "package": package}
            for env, path, package in CHANGED_TEST_MAPPINGS
        ],
        "dtest_api_artifacts": find_dtest_api_artifacts(),
        "source_checks": [entry.__dict__ for entry in sources],
        "doc_checks": [entry.__dict__ for entry in docs],
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check CircleCI generator source/doc drift.")
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
        failed_sources = [entry for entry in result["source_checks"] if not entry["ok"]]
        failed_docs = [entry for entry in result["doc_checks"] if not entry["ok"]]

        print(f"OK CircleCI generator scenario IDs expected: {len(result['scenario_ids'])}")
        print(f"OK template env keys parsed: {len(result['template_env_keys'])}")
        print(f"OK generate allowlist parsed: {len(result['generate_allowlist'])}")
        print(f"OK changed-test mappings expected: {len(result['changed_test_mappings'])}")
        print(f"{'OK' if not failed_sources else 'FAILED'} CircleCI generator source checks: {len(result['source_checks']) - len(failed_sources)}/{len(result['source_checks'])}")
        print(f"{'OK' if not failed_docs else 'FAILED'} CircleCI generator doc checks: {len(result['doc_checks']) - len(failed_docs)}/{len(result['doc_checks'])}")
        print(f"OK dtest-api artifacts found: {len(result['dtest_api_artifacts'])}")

        if failed_sources or failed_docs:
            print("CircleCI generator source/doc checks failed:")
            for entry in failed_sources + failed_docs:
                print(f"  - {entry['name']} ({entry['source']})")
        else:
            print("CircleCI generator source/doc checks passed.")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
