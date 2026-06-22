# Testing CI Generator Matrix

## 范围

本文覆盖 Cassandra 5.0 源码树中测试 CI 配置的生成器、模板参数和 dtest API artifact 边界。重点是 `.circleci/generate.sh`、`.circleci/config_template.yml`、`.circleci/config_template.yml.PAID.patch`、生成后的 `.circleci/config.yml`/`.circleci/config.yml.FREE`/`.circleci/config.yml.PAID`、`.circleci/readme.md`、`build.xml` 以及 `.build/parent-pom-template.xml`、`.build/cassandra-build-deps-template.xml` 中的 dtest API 依赖线索。

当前 checkout 未包含可直接解压检查的 `dtest-api-*.jar` 或同名 API artifact；本地可证明的是依赖声明、Ant 打包入口和 CI 使用边界，而不是外部 jar 内的完整 API 清单。`find . -iname '*dtest-api*' -o -iname '*dtest*api*'` 在当前树没有返回文件；源码侧仍能看到 `dtest-jar` 会从 `${test.lib}/jars` 解压 `dtest-api-*.jar`，并和 Cassandra/test classes 一起打进 `build/dtest-${base.version}.jar`，见 `build.xml:1733-1760`。

## 设计目标

- 用一个 reusable template 生成 CircleCI 真正读取的配置，避免手写 `.circleci/config.yml` 与模板漂移。`.circleci/readme.md:21-31` 明确 `config.yml` 由 `.circleci/generate.sh` 从 `.circleci/config_template.yml` 生成，默认 `config.yml` 是 FREE 资源版本。
- 让同一套测试定义在 FREE、PAID 和本地开发最小 sanity check 之间切换：`-f` 生成 FREE，`-p` 生成 PAID，`-a` 同时生成提交用的 `config.yml`、`config.yml.FREE`、`config.yml.PAID`，`-d` 删除大量 job 只保留开发快速检查，见 `.circleci/generate.sh:31-40`、`.circleci/generate.sh:164-197`、`.circleci/generate.sh:353-426`。
- 自动发现新建或修改的测试并生成 repeated jobs，用于发现 flake；也允许用 `-e` 精确指定测试列表、迭代次数和 dtest 仓库/分支，见 `.circleci/generate.sh:204-247`、`.circleci/readme.md:71-121`。
- 在 CircleCI 内按历史 timing 拆分普通 JUnit/Python dtest，同时对 repeated tests 按容器数分摊迭代次数，而不是再用 `circleci tests split`，见 `.circleci/config_template.yml:2774-2798`、`.circleci/config_template.yml:2956-3039`、`.circleci/config_template.yml:3160-3296`、`.circleci/config_template.yml:3445-3515`。
- 保留 dtest API 外部 artifact 的接入点：Maven template 声明 `org.apache.cassandra:dtest-api:0.0.18`，build deps template 声明 `dtest-api`，Ant dtest jar 打包会解压 `dtest-api-*.jar`，见 `.build/parent-pom-template.xml:534-539`、`.build/cassandra-build-deps-template.xml:85-88`、`build.xml:1741-1742`。

## 解决的问题

- **配置漂移**：模板、FREE/PAID 生成文件和默认 `config.yml` 如果手工维护，容易在 job、executor、env var 上不一致。生成器把永久修改收敛到 `.circleci/config_template.yml` 和 `.circleci/config_template.yml.PAID.patch`，再用 `-a` 生成提交文件，见 `.circleci/readme.md:157-168`。
- **资源成本**：默认 FREE config 使用低 parallelism；PAID patch 提升资源等级和并发，尤其对 Python dtest、大型 vnode dtest、repeated dtest 有明显差异，见 `.circleci/config_template.yml:157-252`、`.circleci/config_template.yml.PAID.patch:3-141`。
- **flake 复现**：changed-test detection 把改动的 `*Test.java` 映射到对应 repeated env var；手动列表可以覆盖 Python dtest、JVM dtest、simulator dtest 和任意 Ant target，见 `.circleci/generate.sh:214-247`、`.circleci/readme.md:94-121`。
- **外部 dtest 选择**：`DTEST_REPO` 和 `DTEST_BRANCH` 默认指向 Apache dtest trunk，但可通过 `-e` 在临时 config 中替换，见 `.circleci/config_template.yml:40-41`、`.circleci/readme.md:49-68`。
- **结果可追溯**：普通和 repeated jobs 都保存 JUnit XML、stdout、logs 或 dtest logs，见 `.circleci/config_template.yml:2822-2829`、`.circleci/config_template.yml:2927-2934`、`.circleci/config_template.yml:3044-3051`、`.circleci/config_template.yml:3296-3306`、`.circleci/config_template.yml:3517-3524`。

## 设计取舍

- **生成文件提交入库，而不是运行时生成**：CircleCI 只读取 `.circleci/config.yml`；项目保留 `.circleci/config.yml.FREE` 和 `.circleci/config.yml.PAID` 作为可切换产物，牺牲仓库噪声换取 CI UI 可直接执行，见 `.circleci/readme.md:21-31`。
- **PAID 资源用 patch 表达**：`.circleci/config_template.yml.PAID.patch` 在生成时临时 patch 模板，再 `circleci config process`，避免在模板里复制两套 executor/job。代价是 patch hunk 与模板行结构强耦合，见 `.circleci/generate.sh:171-177`、`.circleci/generate.sh:190-194`。
- **env var 白名单硬编码在 shell**：`generate.sh` 对 `-e` key 做显式 allowlist，默认拒绝未知 key；这降低 typo 悄悄进入 YAML 的风险，但每新增高频变量都必须同步模板、脚本和文档，见 `.circleci/config_template.yml:21-28`、`.circleci/generate.sh:123-158`。
- **changed-test detection 只覆盖 Java 源内的 `*Test.java`**：脚本自动映射 unit/long/stress/fqltool/simulator/JVM distributed/upgrade tests，不自动发现 Python dtest 文件；Python dtest repeated 列表依赖手动 `REPEATED_DTESTS`/`REPEATED_LARGE_DTESTS`/`REPEATED_UPGRADE_DTESTS`，见 `.circleci/generate.sh:238-247`、`.circleci/config_template.yml:106-130`。
- **repeated jobs 复制测试迭代，而不是拆分测试集合**：普通 JUnit/dtest 使用 CircleCI timing split；repeated job 按 `count / CIRCLE_NODE_TOTAL` 分摊循环次数。这样适合发现单测 flake，但当 count 小于容器数时会出现空容器，见 `.circleci/config_template.yml:2793-2798`、`.circleci/config_template.yml:2990-2999`、`.circleci/config_template.yml:3186-3190`、`.circleci/config_template.yml:3335-3343`、`.circleci/config_template.yml:3473-3481`。
- **外部 dtest API 不在源码树内展开**：源码树声明和消费 `dtest-api`，但完整 API 需要拿到 `dtest-api-*.jar` 后解压或从发布源仓库读取。本文件不推断缺失 jar 内的类/方法。

## 核心类

这里的核心“类”主要是脚本、YAML anchor、job 和 Ant target：

| 单元 | 角色 |
|---|---|
| `.circleci/generate.sh` | CircleCI config 生成器；解析 `-a/-f/-p/-d/-b/-s/-e/-i`，校验 env var，生成 FREE/PAID/default config，替换 env var，删除未启用 repeated jobs，构建 dev-min job 集合，见 `.circleci/generate.sh:31-80`、`.circleci/generate.sh:82-162`、`.circleci/generate.sh:418-426`。 |
| `.circleci/config_template.yml` | 真实 job/workflow/command/executor 的 reusable source；包含默认 env var、FREE executor parallelism、普通测试 split command、repeated command，见 `.circleci/config_template.yml:21-155`、`.circleci/config_template.yml:157-252`、`.circleci/config_template.yml:2774-3051`、`.circleci/config_template.yml:3160-3524`。 |
| `.circleci/config_template.yml.PAID.patch` | 付费资源 patch；提升 executor `resource_class` 和 parallelism，并把部分 dtest job 映射到 large/very large executor，见 `.circleci/config_template.yml.PAID.patch:3-141`、`.circleci/config_template.yml.PAID.patch:143-180`。 |
| `.circleci/config.yml` | CircleCI 实际读取的生成文件；FREE 是默认提交形态，临时 `-f/-p/-e` 也会覆盖它，见 `.circleci/readme.md:21-47`。 |
| `build.xml` target `dtest-jar` | 创建 dtest-compatible jar，复制 main/test/conf classes，解压 `dtest-api-*.jar` 和依赖 jar，再打成 `build/dtest-${base.version}.jar`，见 `build.xml:1733-1760`。 |
| `.build/parent-pom-template.xml` / `.build/cassandra-build-deps-template.xml` | Maven/build deps 层声明 `org.apache.cassandra:dtest-api`，见 `.build/parent-pom-template.xml:534-539`、`.build/cassandra-build-deps-template.xml:85-88`。 |

## 核心接口

### 生成器 CLI

| 参数 | 语义 | 主要边界 |
|---|---|---|
| `-a` | 从模板生成 `config.yml`、`config.yml.FREE`、`config.yml.PAID`；用于永久提交 | 不允许和 `-f/-p/-e` 同用；禁用 changed-test detection，见 `.circleci/generate.sh:31-37`、`.circleci/generate.sh:179-197`。 |
| `-f` | 生成 FREE 资源版 `config.yml` | 不允许和 `-a/-p` 同用；可配合 `-e` 临时替换 env var，见 `.circleci/generate.sh:39`、`.circleci/generate.sh:164-169`。 |
| `-p` | 生成 PAID 资源版 `config.yml` | 先 patch 模板到临时 PAID 文件，再处理 YAML，见 `.circleci/generate.sh:40`、`.circleci/generate.sh:171-177`。 |
| `-d` | 删除大部分 job，保留 dev sanity check | 与自动 repeated detection 不兼容，必须配 `-s`，见 `.circleci/generate.sh:37-38`、`.circleci/generate.sh:160-162`、`.circleci/generate.sh:353-426`。 |
| `-b` | 指定 changed-test detection 的 base branch | 默认 `cassandra-5.0`；branch 不存在会退出 2，见 `.circleci/generate.sh:21`、`.circleci/generate.sh:41-43`、`.circleci/generate.sh:204-212`。 |
| `-s` | 跳过自动检测改动测试 | 手动 repeated list 或 test 太多时使用，见 `.circleci/generate.sh:44-45`、`.circleci/generate.sh:112-113`。 |
| `-e key=value` | 替换生成后 config 中的 env var | 默认检查 key 是否在 allowlist；同一命令可重复多次，见 `.circleci/generate.sh:46-78`、`.circleci/generate.sh:101-107`、`.circleci/generate.sh:249-260`。 |
| `-i` | 忽略未知 env var | 绕过 allowlist，风险是 typo 可能进入 config，见 `.circleci/generate.sh:79`、`.circleci/generate.sh:110-111`。 |

### changed-test 映射

| Git diff 路径 | 目标 env var | package filter |
|---|---|---|
| `test/unit/` | `REPEATED_UTESTS` | `org.apache.cassandra` |
| `test/long/` | `REPEATED_UTESTS_LONG` | `org.apache.cassandra` |
| `tools/stress/test/unit/` | `REPEATED_UTESTS_STRESS` | `org.apache.cassandra.stress` |
| `tools/fqltool/test/unit/` | `REPEATED_UTESTS_FQLTOOL` | `org.apache.cassandra.fqltool` |
| `test/simulator/test/` | `REPEATED_SIMULATOR_DTESTS` | `org.apache.cassandra.simulator.test` |
| `test/distributed/` | `REPEATED_JVM_DTESTS` | `org.apache.cassandra.distributed.test` |
| `test/distributed/` | `REPEATED_JVM_UPGRADE_DTESTS` | `org.apache.cassandra.distributed.upgrade` |

映射逻辑来自 `.circleci/generate.sh:214-247`：`git diff --name-only --diff-filter=AMR ${BASE_BRANCH}...HEAD` 过滤 `Test.java`，去掉 `.java`，把路径 `/` 转成 Java package，再按 package filter 保留。

## 核心数据结构

- **默认 env var map**：`.circleci/config_template.yml:21-155` 定义基础环境、dtest repo/branch、repeated test list/count、任意 Ant repeated target 的 class/method/vnodes/count。
- **allowlist**：`.circleci/generate.sh:123-158` 是 `-e` 可修改 key 的事实来源。模板注释要求新增高频 env var 时同步脚本和文档，见 `.circleci/config_template.yml:21-28`。
- **executor anchors**：FREE 模板中 JDK 11/17 parallel executors 默认 parallelism 为 4 或 1，repeated executors 默认 parallelism 为 4，见 `.circleci/config_template.yml:157-252`。PAID patch 把主要 parallelism 提到 25/10/4，并新增 large/very-large executor，见 `.circleci/config_template.yml.PAID.patch:3-141`。
- **workflow/job tree**：模板先定义 workflow job 列表，例如 `j11_separate_jobs` 中每组 job 有 approval gate 和 build dependency，见 `.circleci/config_template.yml:254-420`；生成器随后可删除未启用 repeated jobs，见 `.circleci/generate.sh:278-341`。
- **split files**：JUnit 普通任务用 `/tmp/all_java_unit_tests.txt`、`/tmp/java_tests_${CIRCLE_NODE_INDEX}.txt`、`/tmp/java_tests_${CIRCLE_NODE_INDEX}_final.txt`；Python dtest 用 `/tmp/all_dtest_tests_<tag>`、`/tmp/split_dtest_tests_<tag>.txt`、`/tmp/split_dtest_tests_<tag>_final.txt`，见 `.circleci/config_template.yml:2793-2799`、`.circleci/config_template.yml:2990-2999`。
- **result/artifact directories**：JUnit 输出在 `/tmp/cassandra/build/test/output` 和 `/tmp/cassandra/build/test/logs`；Python dtest 输出 `/tmp/results/dtests`、`/tmp/dtest`、`~/cassandra-dtest/logs`；repeated JUnit 输出 `/tmp/results/repeated_utests` 或 `/tmp/results/repeated_utest`，见 `.circleci/config_template.yml:2822-2829`、`.circleci/config_template.yml:2927-2934`、`.circleci/config_template.yml:3044-3051`、`.circleci/config_template.yml:3296-3306`、`.circleci/config_template.yml:3433-3442`。
- **dtest API dependency**：POM template pin 到 `org.apache.cassandra:dtest-api:0.0.18`，build deps template 声明 artifact，Ant 从 `${test.lib}/jars` 解压 `dtest-api-*.jar`，见 `.build/parent-pom-template.xml:534-539`、`.build/cassandra-build-deps-template.xml:85-88`、`build.xml:1741-1742`。

## 生命周期

1. **永久 CI 变更**：编辑 `.circleci/config_template.yml` 或 `.circleci/config_template.yml.PAID.patch`，运行 `.circleci/generate.sh` 的 `-a` 模式，提交更新后的 `.circleci/config.yml`、`.circleci/config.yml.FREE`、`.circleci/config.yml.PAID`。官方流程见 `.circleci/readme.md:157-168`。
2. **临时资源切换**：用 `.circleci/generate.sh` 的 `-f` 或 `-p` 模式只覆盖 `.circleci/config.yml`；也可以直接复制 `.circleci/config.yml.FREE`/`.circleci/config.yml.PAID`，见 `.circleci/readme.md:33-47`。
3. **临时 env var 注入**：通过多个 `-e key=value` 指定 dtest repo/branch、repeated list/count 或 Ant target。生成器先用 allowlist 校验，然后用 `sed` 替换 `config.yml` 中对应 `- KEY:` 行，见 `.circleci/generate.sh:123-158`、`.circleci/generate.sh:249-260`。
4. **changed-test detection**：除 `-a` 和 `-s` 外，生成器基于 `${BASE_BRANCH}...HEAD` 自动发现 Java `*Test.java` 改动，追加到对应 repeated env var，见 `.circleci/generate.sh:204-247`。
5. **job 裁剪**：生成器删除没有对应 repeated env var 的 repeated jobs；`-d` 再额外删除大部分重型 job 并重命名 workflow 为 dev tests，见 `.circleci/generate.sh:278-341`、`.circleci/generate.sh:353-426`。
6. **CI 执行**：普通 JUnit/Python dtest 先生成 split list，再运行 Ant/pytest 并保存 artifacts；repeated jobs 计算本容器迭代数，循环执行指定 test，按 pass/fail 分类保存 stdout、XML、logs，见 `.circleci/config_template.yml:2774-3051`、`.circleci/config_template.yml:3160-3524`。
7. **dtest jar 构建**：`build.xml` 的 `dtest-jar` target 依赖 `build-test` 和 `build`，复制 main/test/conf classes，解压 test lib/build lib jars，最后生成 `dtest-${base.version}.jar`，见 `build.xml:1733-1760`。

## 调用链

### 生成器主链

`developer command` -> `.circleci/generate.sh` parse flags -> validate `-e` allowlist -> generate FREE/PAID/default config via `circleci config process` and optional `patch` -> detect changed Java tests -> replace env vars in `.circleci/config.yml` -> delete unused repeated jobs -> optional dev-min pruning。

关键源码锚点：`.circleci/generate.sh:82-162`、`.circleci/generate.sh:164-197`、`.circleci/generate.sh:204-260`、`.circleci/generate.sh:278-341`、`.circleci/generate.sh:353-426`。

### 普通 JUnit 链

`create_junit_containers` -> `circleci tests glob` 收集 `test/<classlistprefix>/**/*.java` -> `circleci tests split --split-by=timings --timings-type=filename` -> 写 `/tmp/java_tests_${CIRCLE_NODE_INDEX}_final.txt` -> `run_parallel_junit_tests` 调 Ant `testclasslist*` 并传 `-Dtest.classlistfile` -> 保存 JUnit XML/logs。

关键源码锚点：`.circleci/config_template.yml:2774-2799`、`.circleci/config_template.yml:2896-2934`。

### 普通 Python dtest 链

`create_dtest_containers` -> 激活 dtest venv -> `run_dtests.py --dtest-print-tests-only` 输出候选 dtest -> 可选 grep filter -> `circleci tests split --split-by=timings --timings-type=classname` -> `run_dtests` 读取 split file -> `pytest ... --cassandra-dir=/home/cassandra/cassandra --keep-test-dir` -> 保存 pytest XML、stdout、dtest logs。

关键源码锚点：`.circleci/config_template.yml:2956-3000`、`.circleci/config_template.yml:3001-3051`。

### repeated JUnit / JVM dtest / simulator 链

`REPEATED_*` env var 或 changed-test detection -> generator 保留对应 repeated job -> `run_repeated_utests` 合并手动/自动 test list 并去重 -> 按 `CIRCLE_NODE_TOTAL` 分摊 count -> 支持 `Class#method` -> 对普通 unit target 使用短类名，对 JVM dtest target 使用全限定名 -> `ant <target> ... -Dno-build-test=true` -> 按 pass/fail 保存 stdout/XML/logs -> 可用 `REPEATED_TESTS_STOP_ON_FAILURE` 提前停止。

关键源码锚点：`.circleci/config_template.yml:3053-3158`、`.circleci/config_template.yml:3160-3306`。

### repeated Python dtest 链

`REPEATED_DTESTS`/`REPEATED_LARGE_DTESTS`/`REPEATED_UPGRADE_DTESTS` -> generator 保留对应 repeated dtest job -> `run_repeated_dtest` 按容器分摊 count -> 拼接 pytest tests arg、vnodes arg、upgrade arg、stop-on-failure `-x` -> `pytest --count=<count> ...` -> 保存 XML、stdout、dtest logs。

关键源码锚点：`.circleci/config_template.yml:2498-2651`、`.circleci/config_template.yml:3445-3524`。

### dtest API artifact 链

Maven/build-deps 声明 `org.apache.cassandra:dtest-api` -> test lib 获取 `dtest-api-*.jar` -> `build.xml` `dtest-jar` target 解压该 jar 到 `${build.dir}/dtest` -> 与 Cassandra main/test/conf classes 和其他依赖一起打包为 dtest-compatible jar。

关键源码锚点：`.build/parent-pom-template.xml:534-539`、`.build/cassandra-build-deps-template.xml:85-88`、`build.xml:1733-1760`。

## 配置项

### 基础环境

| 配置 | 默认/语义 | 源码锚点 |
|---|---|---|
| `DTEST_REPO` | `https://github.com/apache/cassandra-dtest.git` | `.circleci/config_template.yml:40` |
| `DTEST_BRANCH` | `trunk` | `.circleci/config_template.yml:41` |
| `CASSANDRA_SKIP_SYNC` | CI 中跳过 sync 降低 flaky/perf 问题 | `.circleci/config_template.yml:38-39` |
| `CASS_DRIVER_NO_EXTENSIONS` / `CASS_DRIVER_NO_CYTHON` | Python driver 禁用扩展/Cython | `.circleci/config_template.yml:36-37` |
| `CCM_MAX_HEAP_SIZE` / `CCM_HEAP_NEWSIZE` | dtest/CCM JVM heap 默认值 | `.circleci/config_template.yml:42-43` |

### repeated test 矩阵

| 类别 | 手动列表变量 | count 变量 | 默认 count | 自动检测 |
|---|---|---|---|---|
| 普通 unit | `REPEATED_UTESTS` | `REPEATED_UTESTS_COUNT` | `500` | `test/unit/` |
| FQL tool unit | `REPEATED_UTESTS_FQLTOOL` | `REPEATED_UTESTS_FQLTOOL_COUNT` | `500` | `tools/fqltool/test/unit/` |
| long unit | `REPEATED_UTESTS_LONG` | `REPEATED_UTESTS_LONG_COUNT` | `100` | `test/long/` |
| stress unit | `REPEATED_UTESTS_STRESS` | `REPEATED_UTESTS_STRESS_COUNT` | `500` | `tools/stress/test/unit/` |
| simulator dtest | `REPEATED_SIMULATOR_DTESTS` | `REPEATED_SIMULATOR_DTESTS_COUNT` | `500` | `test/simulator/test/` |
| JVM dtest | `REPEATED_JVM_DTESTS` | `REPEATED_JVM_DTESTS_COUNT` | `500` | `test/distributed/` + `org.apache.cassandra.distributed.test` |
| JVM upgrade dtest | `REPEATED_JVM_UPGRADE_DTESTS` | `REPEATED_JVM_UPGRADE_DTESTS_COUNT` | `500` | `test/distributed/` + `org.apache.cassandra.distributed.upgrade` |
| Python dtest | `REPEATED_DTESTS` | `REPEATED_DTESTS_COUNT` | `500` | 手动 |
| Python large dtest | `REPEATED_LARGE_DTESTS` | `REPEATED_LARGE_DTESTS_COUNT` | `100` | 手动 |
| Python upgrade dtest | `REPEATED_UPGRADE_DTESTS` | `REPEATED_UPGRADE_DTESTS_COUNT` | `25` | 手动 |
| 任意 Ant target | `REPEATED_ANT_TEST_CLASS` + `REPEATED_ANT_TEST_TARGET` + `REPEATED_ANT_TEST_METHODS` + `REPEATED_ANT_TEST_VNODES` | `REPEATED_ANT_TEST_COUNT` | `500` | 手动 |

默认值和示例见 `.circleci/config_template.yml:45-155`，脚本文档示例见 `.circleci/readme.md:71-150`。

### 资源矩阵

| 配置 | FREE 模板 | PAID patch |
|---|---|---|
| JDK11/JDK17 parallel executors | `j11_par_executor`/`j17_par_executor` parallelism `4`，small/medium 多为 `1`，见 `.circleci/config_template.yml:157-222` | 主 parallel executors 提升到 medium + `25`，small 到 `10` 或 `4`，medium 到 xlarge + `4`，新增 large/very-large executor，见 `.circleci/config_template.yml.PAID.patch:3-99` |
| repeated executors | JVM upgrade/unit/dtest repeated 默认 parallelism `4`，见 `.circleci/config_template.yml:224-252` | repeated unit/JVM upgrade/dtest 提升到 medium/large/xlarge + `25`，见 `.circleci/config_template.yml.PAID.patch:101-141` |
| Python vnode/latest dtest | FREE 多使用普通 parallel executor | PAID 将部分 vnode/latest dtest job 切换到 large executor，见 `.circleci/config_template.yml.PAID.patch:143-180` |

## Metrics

- CircleCI 普通测试依赖历史 timing 做 `circleci tests split --split-by=timings`，JUnit 用 `--timings-type=filename`，Python dtest 用 `--timings-type=classname`，见 `.circleci/config_template.yml:2793-2798`、`.circleci/config_template.yml:2990-2999`。
- job 结果通过 `store_test_results` 上传给 CircleCI；JUnit、simulator、parallel JUnit、Python dtest、repeated JUnit、repeated Python dtest 均有独立路径，见 `.circleci/config_template.yml:2822-2829`、`.circleci/config_template.yml:2927-2934`、`.circleci/config_template.yml:3044-3051`、`.circleci/config_template.yml:3296-3306`、`.circleci/config_template.yml:3517-3524`。
- 这里没有 Cassandra runtime metrics；CI 的主要观测数据是 CircleCI timing、JUnit XML、pytest XML、stdout 和 log artifacts。

## 日志

- 普通 JUnit/simulator jobs 保存 `/tmp/cassandra/build/test/logs` 为 `logs` artifact，见 `.circleci/config_template.yml:2824-2829`、`.circleci/config_template.yml:2929-2934`。
- Python dtest jobs 保存 `/tmp/dtest` stdout 和 `~/cassandra-dtest/logs`，见 `.circleci/config_template.yml:3036-3051`。
- repeated JUnit jobs把每次迭代 stdout、XML、logs 按 `passes`/`fails` 和 iteration number 归档，见 `.circleci/config_template.yml:3268-3287`、`.circleci/config_template.yml:3296-3306`。
- repeated Python dtest jobs通过 `tee /tmp/dtest/stdout.txt` 保存 pytest stdout，并上传 dtest logs，见 `.circleci/config_template.yml:3513-3524`。

## 运维关注点

- **永久修改必须重生成**：直接编辑 `.circleci/config.yml` 只适合临时 patch；永久变更应改 template/patch 后运行 `generate.sh -a`，见 `.circleci/readme.md:157-168`。
- **CircleCI CLI 是生成依赖**：`generate.sh` 调用 `circleci config process`，README 明确需要安装 CircleCI CLI，见 `.circleci/readme.md:44-47`、`.circleci/readme.md:157-162`。
- **base branch 必须存在**：自动检测默认用 `cassandra-5.0`，本地仓库没有该 ref 时需要 `-b origin/cassandra-5.0` 或 `-s`，见 `.circleci/generate.sh:21`、`.circleci/generate.sh:204-212`。
- **unknown env var 默认失败**：新增或临时变量如果不在 allowlist 会 `die`；可用 `-i` 绕过，但更推荐同步 `.circleci/config_template.yml`、`.circleci/generate.sh` 和 `.circleci/readme.md`，见 `.circleci/config_template.yml:21-28`、`.circleci/generate.sh:123-158`。
- **PAID/FREE 切换会覆盖 generated config**：`-f/-p/-a` 都会改 `.circleci/config.yml` 或生成文件；README 提醒之前的 swap/edit 会被覆盖，见 `.circleci/readme.md:164-170`。
- **dtest API 完整清单需要外部 artifact**：当前源码只声明和消费 `dtest-api`，没有 jar 可解压；获取 `dtest-api-*.jar` 后应补充类/方法/API 版本清单，并和 `test/distributed/org/apache/cassandra/distributed/api` 本地接口区分。

## 性能瓶颈

- FREE 配置 parallelism 保守，Python dtest、large dtest 和 repeated dtest 总耗时会明显受限；PAID patch 专门提高 parallelism 和 resource class，见 `.circleci/config_template.yml:157-252`、`.circleci/config_template.yml.PAID.patch:3-141`。
- repeated tests 不用 timing split，而是每个容器跑相同测试的若干迭代；如果 count 远大于 parallelism 效果好，如果 count 小于容器数则出现空容器，见 `.circleci/config_template.yml:3335-3343`、`.circleci/config_template.yml:3473-3481`。
- Python large dtests `test_network_topology_strategy` 和 `test_network_topology_strategy_each_quorum` 循环运行需要 XLarge container，否则可能出现 `NO HOST AVAILABLE`，见 `.circleci/readme.md:153-155`。
- dtest venv 的依赖安装假设 docker image 已预装 requirements；如果 image 没更新，会在运行时安装并拖慢 job，见 `.circleci/config_template.yml:2936-2955`。

## 常见故障

- **`Unknown base branch`**：`generate.sh` 在 changed-test detection 前执行 `git show ${BASE_BRANCH}`；失败时退出并提示用 `-b` 选择有效 branch，见 `.circleci/generate.sh:204-212`。
- **`Unrecognised environment variable name`**：`-e` key 不在 allowlist；修正 key、更新 allowlist，或临时使用 `-i`，见 `.circleci/generate.sh:123-158`。
- **`-d doesn't support repeated tests`**：`-d` 与自动 changed-test detection 同用会失败；需要配 `-s`，见 `.circleci/generate.sh:160-162`。
- **Repeated job 没跑任何测试**：相关 list 变量为空、class/count 为 `<nil>`、count 小于等于 0，或 count 小于容器数导致部分容器空跑；见 `.circleci/config_template.yml:3327-3343`、`.circleci/config_template.yml:3465-3481`。
- **Python dtest split 为空**：filter pattern 未匹配会退出 0；split 后当前容器没有测试会退出 1 并提示调低 parallelism，见 `.circleci/config_template.yml:2991-2999`、`.circleci/config_template.yml:3037-3043`。
- **dtest jar/API 缺失**：本地没有 `dtest-api-*.jar` 时不能枚举外部 API；`build.xml` 期望该 jar 出现在 `${test.lib}/jars`，见 `build.xml:1741-1742`。

## 测试用例

- **生成器自检对象**：`.circleci/config.yml`、`.circleci/config.yml.FREE`、`.circleci/config.yml.PAID` 是模板处理后的可检查产物；README 要求永久修改后运行 `generate.sh -a` 并提交这些文件，见 `.circleci/readme.md:157-168`。
- **普通 JUnit split 测试路径**：`create_junit_containers` + `run_parallel_junit_tests` 覆盖 unit/long/stress/fqltool 等 Ant classlist targets，源码锚点为 `.circleci/config_template.yml:2774-2799`、`.circleci/config_template.yml:2896-2934`。
- **普通 Python dtest split 测试路径**：`create_dtest_containers` + `run_dtests` 覆盖 vnode/latest/large/upgrade/cqlsh 等 dtest job 的共同执行骨架，源码锚点为 `.circleci/config_template.yml:2956-3051`。
- **Repeated JUnit/JVM/simulator 测试路径**：`run_repeated_utests` 和 `run_repeated_utest` 覆盖自动检测、手动列表和任意 Ant target 的循环执行，源码锚点为 `.circleci/config_template.yml:3160-3442`。
- **Repeated Python dtest 测试路径**：`run_repeated_dtest` 覆盖 `--count`、vnodes、upgrade、stop-on-failure 和 artifact 上传，源码锚点为 `.circleci/config_template.yml:3445-3524`。
- **dtest API artifact 待补测试**：拿到 `dtest-api-*.jar` 后应新增 artifact 解压清单、public class/method 对照、与 `build.xml:1733-1760` 打包结果的一致性检查；当前源码树无法完成该清单。

## Drift 检查

- `research/tools/check-testing-ci-generator-drift.py` 校验 `ci_generator_default_free`、`ci_generator_paid_patch`、`ci_generator_env_allowlist`、`ci_generator_changed_test_detection`、`ci_generator_repeated_job_pruning`、`ci_generated_free_paid_artifacts`、`ci_dtest_api_artifact_boundary` 和 `ci_docs_generator_workflow`。
- checker 不运行 `circleci config process`，只读取 `.circleci/generate.sh`、`.circleci/config_template.yml`、`.circleci/config_template.yml.PAID.patch`、`.circleci/config.yml`、`.circleci/config.yml.FREE`、`.circleci/config.yml.PAID`、`.circleci/readme.md`、`build.xml`、`.build/parent-pom-template.xml`、`.build/cassandra-build-deps-template.xml` 和本文档。
- 设计与运行方式见 `research/module-testing-ci-generator-drift-checker.md`。
