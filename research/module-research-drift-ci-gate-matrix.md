# Research Drift Checker CI Gate Matrix

本矩阵把 `research/tools/check-*.py` 这组 source-only drift checker 纳入测试框架视角，明确当前 checkout 的 Ant、CircleCI、Jenkins gate 能覆盖什么，以及哪些研究校验仍需要人工或后续 CI 接入。它不替代各模块 checker 的业务语义；它只保护 checker inventory、CI 入口和未接入状态不被误读。

## Source Contract

| Scenario | Contract | Source anchors | Operational meaning |
| --- | --- | --- | --- |
| `research_checker_inventory_contract` | 当前 research 目录有 71 个 `research/tools/check-*.py` drift checker；新增或删除 checker 时必须同步本矩阵。 | `research/tools/check-research-drift-ci-gate-drift.py:17`, `research/tools/check-testing-ci-generator-drift.py:3`, `research/tools/check-nodetool-runbook-drift.py:3` | 让研究知识库自己的校验入口可枚举，而不是散落在 README 或提交记录里。 |
| `research_checker_source_only_contract` | checker 都是 repo-local Python 脚本，以源码、测试文件和 research 文档为输入，不启动 Cassandra 节点。 | `research/tools/check-research-drift-ci-gate-drift.py:69`, `research/tools/check-read-repair-repaired-data-drift.py:3` | 适合本地快速跑，也适合作为轻量 CI/pre-commit 阶段，但不能替代 Java/runtime 测试。 |
| `research_checker_json_output_contract` | 多数 checker 已提供 `--json` 输出；CI 接入时应优先保留机器可读 artifact，人工维护时仍使用文本输出。 | `research/tools/check-testing-ci-generator-drift.py:247`, `research/tools/check-nodetool-runbook-drift.py:135` | JSON 是后续统一 gate/报告的自然接口；没有 JSON 的老 checker 需要在接入前补齐或用 wrapper 规范化。 |
| `research_checker_local_runner_contract` | `research/tools/run-research-drift-checks.py` 统一发现 `check-*.py`，支持 `--list`、`--pattern`、`--exclude`、`--jobs`、`--timeout` 和 `--json`，但自身不进入 checker inventory。 | `research/tools/run-research-drift-checks.py:16`, `research/tools/run-research-drift-checks.py:33`, `research/tools/run-research-drift-checks.py:87` | 先提供本地/CI 可复用入口，再决定是否接入 Ant/CircleCI/Jenkins。 |
| `research_ant_check_precommit_boundary` | `build.xml` 的 `check` target 是 pre-commit/local verification 入口，但当前不调用 `research/tools/check-*.py`。 | `build.xml:551`, `build.xml:1665`, `build.xml:1762` | Ant gate 证明 Java/Python/CQL test targets，不证明 research drift checker 全量通过。 |
| `research_circleci_precommit_boundary` | CircleCI template/generated configs 定义 Java 11/17 pre-commit workflows、unit/JVM/simulator/dtest jobs 和 artifacts，但当前不调用 research checker。 | `.circleci/config_template.yml:799`, `.circleci/config_template.yml:1558`, `.circleci/generate.sh:414` | CircleCI 覆盖测试执行面和 generated config drift；research checker 仍需单独跑。 |
| `research_jenkins_profile_boundary` | Jenkins profiles 把 lint、unit、JVM dtest、simulator dtest、Python dtest 等组成 pre/post-commit profile，但当前没有 research checker stage。 | `.jenkins/Jenkinsfile:140`, `.jenkins/Jenkinsfile:186`, `.jenkins/Jenkinsfile:327` | Jenkins profile green 不等于 research KB 与源码同步。 |
| `research_checker_adjacency_runbook_contract` | 模块文档中提到的相邻 checker 仍按模块运行，例如 testing CI generator、nodetool、JMX compatibility 和 guardrails checker。 | `research/tools/check-testing-ci-generator-drift.py:246`, `research/tools/check-nodetool-runbook-drift.py:135`, `research/tools/check-jmx-compatibility-drift.py:14` | 修改 CI/JMX/nodetool/guardrails 相关源码时，应跑本矩阵 checker 加相邻模块 checker。 |
| `research_checker_ci_absence_contract` | `build.xml`、`.circleci/*`、`.jenkins/Jenkinsfile` 当前均不包含 `research/tools/check-` 或 `python3 research/tools` 调用。 | `research/tools/check-research-drift-ci-gate-drift.py:109` | 这是显式缺口，不是遗漏；若后续接入 CI，本场景和 README 状态应同步改为已接入。 |
| `research_checker_future_ci_gate_gap` | 本地 wrapper 已具备 discovery/selection/JSON 输出；下一步是决定 Ant/CircleCI/Jenkins 的 profile、artifact path 和 changed-module selection 规则。 | `research/tools/run-research-drift-checks.py`, `research/module-testing-ci-generator-matrix.md`, `research/module-nodetool-drift-checker.md`, `research/module-jmx-compatibility-dump-matrix.md` | 避免把 60+ 个 checker 直接塞进慢路径；先建立分层 gate 和失败报告。 |

## CI Boundary

```text
Developer / CI entry
  -> Ant build.xml check/test/testclasslist/test-jvm-dtest/test-simulator-dtest
  -> CircleCI generated pre-commit workflows
  -> Jenkins profile pipeline
  -> Java/unit/dtest/simulator/python-dtest evidence

Research drift evidence
  -> python3 research/tools/run-research-drift-checks.py --pattern <area>
  -> python3 research/tools/check-*.py
  -> source/test/doc token and gap checks
  -> currently manual, per-slice verification, or local wrapper execution
  -> no build.xml/.circleci/.jenkins automatic gate in this checkout
```

## Operational Notes

- A green Java CI run does not prove `research/` is current. It proves the selected build/test profile passed.
- A green research checker does not prove runtime behavior. It proves the matrix still matches source/test/doc anchors and recorded gaps.
- When a module changes, run the module checker directly or via `run-research-drift-checks.py --pattern <module>`, plus this CI gate checker if the change affects checker inventory, CI config, testing infrastructure, JMX/nodetool operation surfaces, or README/source-map indexing.
- If a new checker is added, update this matrix count and `research/tools/check-research-drift-ci-gate-drift.py`.
- If CI starts invoking research checkers, replace `research_checker_ci_absence_contract` with a positive gate contract and cite the exact Ant/CircleCI/Jenkins command.

## Suggested Gate Shape

```text
research/tools/run-research-drift-checks.py
  -> discover research/tools/check-*.py
  -> --list selected checkers
  -> --pattern/--exclude for changed-module or area-specific runs
  -> --jobs for local/CI parallelism
  -> --json for machine-readable aggregate output
  -> future CI profile stores the aggregate JSON/text artifact
```

## Verification

- `python3 research/tools/check-research-drift-ci-gate-drift.py`
- `python3 research/tools/run-research-drift-checks.py --list --pattern jmx`
- `python3 research/tools/run-research-drift-checks.py --pattern research-drift-ci-gate`
- Adjacent checks when touching this area:
  - `python3 research/tools/check-testing-ci-generator-drift.py`
  - `python3 research/tools/check-testing-runtime-harness-drift.py`
  - `python3 research/tools/check-nodetool-runbook-drift.py`
  - `python3 research/tools/check-nodetool-option-risk-drift.py`
  - `python3 research/tools/check-jmx-compatibility-drift.py`
