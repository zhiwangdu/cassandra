# Testing CI Generator Drift Checker

## 范围

`research/tools/check-testing-ci-generator-drift.py` 是 source-only drift check，用来保护 `research/module-testing-ci-generator-matrix.md` 中的 CircleCI generator、FREE/PAID generated config、repeated-test env var、changed-test mapping 和 dtest API artifact 边界。

它不运行 `circleci config process`，也不重新生成 `.circleci/config.yml`。原因是生成依赖外部 CircleCI CLI，而且直接生成会修改仓库文件。checker 只读取当前源码树中已经提交的 shell/YAML/XML/Markdown，校验能够稳定证明的合同。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `ci_generator_default_free` | 默认 `.circleci/config.yml` 必须等同 `.circleci/config.yml.FREE` |
| `ci_generator_paid_patch` | PAID patch 和 `.circleci/config.yml.PAID` 必须保留高 parallelism/resource-class 信号 |
| `ci_generator_env_allowlist` | `generate.sh` 的 `-e` allowlist 必须是 template 中可配置 env var 的子集，并在研究文档中覆盖 |
| `ci_generator_changed_test_detection` | unit/long/stress/fqltool/simulator/JVM dtest/JVM upgrade dtest 的 changed-test path mapping 必须存在 |
| `ci_generator_repeated_job_pruning` | 未设置 repeated env var 时，生成器仍删除对应 repeated jobs |
| `ci_generated_free_paid_artifacts` | `config.yml`、`config.yml.FREE`、`config.yml.PAID`、template 和 PAID patch 都存在且含关键生成信号 |
| `ci_dtest_api_artifact_boundary` | 当前树仍只有 dtest-api 声明/消费点，没有可解压的 `dtest-api-*.jar` artifact |
| `ci_docs_generator_workflow` | `.circleci/readme.md` 和研究文档仍说明 permanent change 要改 template/patch 后生成 |

## 运行方式

```bash
python3 research/tools/check-testing-ci-generator-drift.py
python3 research/tools/check-testing-ci-generator-drift.py --json
```

成功时输出 allowlist/env var 数量、changed-test mapping 数量和 dtest API artifact scan。失败时会列出 drift 的 source/doc 检查项。

## 更新规则

- 如果 `.circleci/config_template.yml` 增加新的经常手动改动的 env var，应同步 `.circleci/generate.sh` allowlist、`.circleci/readme.md` 和 `module-testing-ci-generator-matrix.md`。
- 如果 `generate.sh` changed-test mapping 新增测试目录，应同步本 checker 的 mapping 表和 testing CI module。
- 如果仓库加入 `dtest-api-*.jar` 或其他可解压 artifact，应把 `ci_dtest_api_artifact_boundary` 从“缺失 artifact”改成“artifact public API 清单”，并补类/方法级研究。
- 如果默认 `config.yml` 不再等同 FREE config，应更新 README、research 文档和 checker；当前源码说明默认 `config.yml` 是 FREE copy。
