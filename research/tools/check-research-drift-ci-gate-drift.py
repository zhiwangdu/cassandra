#!/usr/bin/env python3
#
# Source-only drift check for research drift checker CI gate coverage.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_CHECKER_COUNT = 80

MATRIX_DOC = "research/module-research-drift-ci-gate-matrix.md"
CHECKER_DOC = "research/module-research-drift-ci-gate-drift-checker.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"
RUNNER = "research/tools/run-research-drift-checks.py"

SCENARIOS = (
    "research_checker_inventory_contract",
    "research_checker_source_only_contract",
    "research_checker_json_output_contract",
    "research_checker_local_runner_contract",
    "research_ant_check_precommit_boundary",
    "research_circleci_precommit_boundary",
    "research_jenkins_profile_boundary",
    "research_checker_adjacency_runbook_contract",
    "research_checker_ci_absence_contract",
    "research_checker_future_ci_gate_gap",
)

CI_PATHS = (
    "build.xml",
    ".circleci/generate.sh",
    ".circleci/config_template.yml",
    ".circleci/config.yml",
    ".circleci/config.yml.FREE",
    ".circleci/config.yml.PAID",
    ".jenkins/Jenkinsfile",
)

ANCHOR_CHECKERS = (
    "research/tools/check-research-drift-ci-gate-drift.py",
    "research/tools/check-testing-ci-generator-drift.py",
    "research/tools/check-testing-runtime-harness-drift.py",
    "research/tools/check-nodetool-runbook-drift.py",
    "research/tools/check-nodetool-option-risk-drift.py",
    "research/tools/check-nodetool-cache-runtime-drift.py",
    "research/tools/check-nodetool-snapshot-lifecycle-drift.py",
    "research/tools/check-materialized-view-build-status-drift.py",
    "research/tools/check-materialized-view-paired-replica-drift.py",
    "research/tools/check-query-processor-execution-drift.py",
    "research/tools/check-cql-trigger-execution-drift.py",
    "research/tools/check-read-operation-monitoring-drift.py",
    "research/tools/check-read-warning-abort-thresholds-drift.py",
    "research/tools/check-row-index-read-size-thresholds-drift.py",
    "research/tools/check-jmx-compatibility-drift.py",
    "research/tools/check-guardrails-framework-drift.py",
)

DOC_TOKENS = (
    MATRIX_DOC,
    CHECKER_DOC,
    "research/tools/check-research-drift-ci-gate-drift.py",
    RUNNER,
    "research/tools/check-*.py",
    "build.xml",
    ".circleci/config_template.yml",
    ".circleci/generate.sh",
    ".jenkins/Jenkinsfile",
    "80",
    "Ant",
    "CircleCI",
    "Jenkins",
) + SCENARIOS + ANCHOR_CHECKERS


@dataclass(frozen=True)
class CheckResult:
    name: str
    source: str
    ok: bool
    detail: str = ""


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def checker_paths() -> list[str]:
    return sorted(rel(path) for path in (REPO_ROOT / "research/tools").glob("check-*.py"))


def contains_ci_invocation(text: str) -> bool:
    patterns = (
        r"research/tools/check-[A-Za-z0-9_-]+\.py",
        r"python3\s+research/tools",
        r"python\s+research/tools",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def source_checks() -> list[CheckResult]:
    tools = checker_paths()
    tool_set = set(tools)
    build_xml = read("build.xml")
    circle_template = read(".circleci/config_template.yml")
    circle_generate = read(".circleci/generate.sh")
    circle_config = read(".circleci/config.yml")
    circle_free = read(".circleci/config.yml.FREE")
    circle_paid = read(".circleci/config.yml.PAID")
    jenkins = read(".jenkins/Jenkinsfile")
    testing_ci_checker = read("research/tools/check-testing-ci-generator-drift.py")
    runner = read(RUNNER)

    checks: list[CheckResult] = [
        CheckResult("checker count", "research/tools/check-*.py", len(tools) == EXPECTED_CHECKER_COUNT, f"found {len(tools)}"),
        CheckResult("checker names unique", "research/tools/check-*.py", len(tools) == len(tool_set)),
        CheckResult("anchor checkers exist", "research/tools", all(path in tool_set for path in ANCHOR_CHECKERS)),
        CheckResult("runner is outside checker inventory", RUNNER, RUNNER not in tool_set and (REPO_ROOT / RUNNER).is_file()),
        CheckResult("runner discovers checkers", RUNNER, 'glob("check-*.py")' in runner and "discover_checkers()" in runner),
        CheckResult("runner supports selection and JSON", RUNNER, all(token in runner for token in ("--list", "--pattern", "--exclude", "--jobs", "--timeout", "--json"))),
        CheckResult("runner empty exclude preserves selection", RUNNER, "if not exclude:" in runner),
        CheckResult("runner uses subprocess and sys.executable", RUNNER, "subprocess.run" in runner and "sys.executable" in runner),
        CheckResult("runner supports parallel execution", RUNNER, "ThreadPoolExecutor" in runner and "as_completed" in runner),
        CheckResult("all checkers use python3 shebang", "research/tools/check-*.py", all(read(path).startswith("#!/usr/bin/env python3\n") for path in tools)),
        CheckResult("all checkers are repo local", "research/tools/check-*.py", all("Path(__file__).resolve().parents[2]" in read(path) for path in tools)),
        CheckResult("Ant check target exists", "build.xml", '<target name="check"' in build_xml and "pre-commit and locally" in build_xml and 'unless="check.skip"' in build_xml),
        CheckResult("Ant unit and dtest targets exist", "build.xml", all(token in build_xml for token in ('<target name="test"', '<target name="testclasslist"', '<target name="test-jvm-dtest"', '<target name="test-simulator-dtest"'))),
        CheckResult("Ant does not invoke research checkers", "build.xml", not contains_ci_invocation(build_xml)),
        CheckResult("CircleCI template pre-commit workflows exist", ".circleci/config_template.yml", "j11_pre-commit_jobs" in circle_template and "j17_pre-commit_jobs" in circle_template and "java11_pre-commit_tests" in circle_template and "java17_pre-commit_tests" in circle_template),
        CheckResult("CircleCI template has test jobs", ".circleci/config_template.yml", "j11_unit_tests" in circle_template and "j11_jvm_dtests" in circle_template and "j11_simulator_dtests" in circle_template and "testclasslist" in circle_template),
        CheckResult("CircleCI generator maps dev workflows", ".circleci/generate.sh", 'rename_workflow "$1" "java11_pre-commit_tests" "java11_dev_tests"' in circle_generate and 'rename_workflow "$1" "java17_pre-commit_tests" "java17_dev_tests"' in circle_generate),
        CheckResult("Generated CircleCI configs keep pre-commit workflows", ".circleci/config*.yml", all("java11_pre-commit_tests" in text and "java17_pre-commit_tests" in text for text in (circle_config, circle_free, circle_paid))),
        CheckResult("CircleCI does not invoke research checkers", ".circleci/*", not any(contains_ci_invocation(text) for text in (circle_template, circle_generate, circle_config, circle_free, circle_paid))),
        CheckResult("Jenkins pipeline profiles exist", ".jenkins/Jenkinsfile", "def pipelineProfiles()" in jenkins and "'pre-commit'" in jenkins and "'post-commit'" in jenkins),
        CheckResult("Jenkins profiles include test stages", ".jenkins/Jenkinsfile", all(token in jenkins for token in ("'lint'", "'test'", "'jvm-dtest'", "'simulator-dtest'", "'dtest'"))),
        CheckResult("Jenkins does not invoke research checkers", ".jenkins/Jenkinsfile", not contains_ci_invocation(jenkins)),
        CheckResult("Testing CI generator checker still covers CircleCI", "research/tools/check-testing-ci-generator-drift.py", ".circleci/config_template.yml" in testing_ci_checker and ".circleci/generate.sh" in testing_ci_checker and "CircleCI generator source/doc drift" in testing_ci_checker),
    ]
    return checks


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def doc_checks() -> list[CheckResult]:
    matrix = read(MATRIX_DOC)
    checker = read(CHECKER_DOC)
    readme = read(README_DOC)
    source_map = read(SOURCE_MAP_DOC)
    matrix_and_checker = matrix + "\n" + checker
    all_docs = "\n".join((matrix, checker, readme, source_map))

    checks = [CheckResult(f"scenario documented {scenario}", f"{MATRIX_DOC} / {CHECKER_DOC}", documented(scenario, matrix_and_checker)) for scenario in SCENARIOS]
    checks.extend(CheckResult(f"doc token {token}", "research docs", token in all_docs) for token in DOC_TOKENS)
    checks.extend(
        [
            CheckResult("README references matrix", README_DOC, MATRIX_DOC.split("/", 1)[1] in readme),
            CheckResult("README references checker", README_DOC, CHECKER_DOC.split("/", 1)[1] in readme and "check-research-drift-ci-gate-drift.py" in readme),
            CheckResult("source-map references matrix", SOURCE_MAP_DOC, MATRIX_DOC in source_map),
            CheckResult("source-map references checker", SOURCE_MAP_DOC, "research/tools/check-research-drift-ci-gate-drift.py" in source_map),
        ]
    )
    return checks


def check() -> tuple[dict[str, object], bool]:
    tools = checker_paths()
    sources = source_checks()
    docs = doc_checks()
    result = {
        "expected_checker_count": EXPECTED_CHECKER_COUNT,
        "checker_count": len(tools),
        "checkers": tools,
        "ci_paths": list(CI_PATHS),
        "runner": RUNNER,
        "scenario_ids": list(SCENARIOS),
        "source_checks": [entry.__dict__ for entry in sources],
        "doc_checks": [entry.__dict__ for entry in docs],
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check research drift checker CI gate source/doc coverage.")
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
        if failed_sources:
            for entry in failed_sources:
                detail = f" ({entry['detail']})" if entry.get("detail") else ""
                print(f"source: {entry['source']}: failed {entry['name']}{detail}")
        if failed_docs:
            for entry in failed_docs:
                print(f"doc: {entry['source']}: missing {entry['name']}")
        if ok:
            print(f"OK research drift CI gate checks passed ({result['checker_count']} checkers, {len(result['scenario_ids'])} scenarios)")
        else:
            print("Research drift CI gate checks failed.", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
