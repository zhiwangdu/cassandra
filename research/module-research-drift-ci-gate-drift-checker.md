# Research Drift CI Gate Drift Checker

`research/tools/check-research-drift-ci-gate-drift.py` protects the research drift checker CI gate matrix from source/doc drift. It is intentionally source-only: it reads `research/tools`, `build.xml`, CircleCI config files, Jenkins profiles, README and source-map.

## What It Checks

| Area | Checks |
| --- | --- |
| Inventory | There are 79 `research/tools/check-*.py` files, including this checker and key adjacent checkers. |
| Tool shape | Research checkers keep the Python shebang and repo-local layout. |
| Runner | `research/tools/run-research-drift-checks.py` discovers `check-*.py`, supports selection/parallelism/JSON output, and is not counted as a checker. |
| Ant boundary | `build.xml` still has the `check` and test targets, and does not invoke research drift checkers. |
| CircleCI boundary | `.circleci/config_template.yml`, generated configs and `generate.sh` still define pre-commit/test workflows without research checker invocation. |
| Jenkins boundary | `.jenkins/Jenkinsfile` still defines pre/post-commit profiles without research checker stage. |
| Docs | Matrix, README and source-map mention the scenario IDs, paths and run command. |

## Run

```bash
python3 research/tools/check-research-drift-ci-gate-drift.py
```

Expected output:

```text
OK research drift CI gate checks passed (79 checkers, 10 scenarios)
```

Use JSON output when wiring automation:

```bash
python3 research/tools/check-research-drift-ci-gate-drift.py --json
```

## Scenario IDs

- `research_checker_inventory_contract`
- `research_checker_source_only_contract`
- `research_checker_json_output_contract`
- `research_checker_local_runner_contract`
- `research_ant_check_precommit_boundary`
- `research_circleci_precommit_boundary`
- `research_jenkins_profile_boundary`
- `research_checker_adjacency_runbook_contract`
- `research_checker_ci_absence_contract`
- `research_checker_future_ci_gate_gap`

## Maintenance

- When adding/removing a checker, update `EXPECTED_CHECKER_COUNT`, this matrix and the README/source-map entries in the same change.
- When changing the local runner command surface, update the runner scenario tokens here and in the checker.
- When a research checker becomes CI-gated, change the absence contract into a positive contract with the exact command and artifact path.
- Keep adjacent checker references narrow; this checker should protect the gate boundary, not duplicate every module checker.
