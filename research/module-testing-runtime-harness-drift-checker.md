# Module: Testing Runtime Harness Drift Checker

## 范围

`research/tools/check-testing-runtime-harness-drift.py` 是 Testing Framework runtime harness 的 source/test/doc drift checker。它保护 `research/module-testing-runtime-harness-matrix.md` 中关于 CQLTester、SchemaLoader/ServerTestUtils、in-JVM dtest cluster、instance isolation、schema/query coordinator、message filters、nodetool mock probe、upgrade dtest、simulator、Byteman、Ant runner targets 和 dtest API artifact boundary 的源码合同。

## 保护的场景

| 场景 ID | 保护内容 |
|---|---|
| `testing_unit_cql_internal_harness` | `CQLTester.setUpClass()`、`beforeTest()`、`afterTest()`、`schemaChange()`、`executeFormattedQuery()` 和 internal CQL 边界。 |
| `testing_cql_native_protocol_harness` | `executeNet()`、`sessionNet()`、`requireNetwork()`、`startServices()`、`startServer()` 和 Java driver/native path。 |
| `testing_schema_loader_server_prepare` | `SchemaLoader.loadSchema()`、`startGossiper()`、`ServerTestUtils.daemonInitialization()` 和 `prepareServer()`。 |
| `testing_injvm_cluster_lifecycle` | `Cluster.build()`、`AbstractCluster.AbstractBuilder`、`createInstanceConfig()`、`startup()`、`close()` 和 live member monitor。 |
| `testing_injvm_instance_isolation` | `Instance`/`IsolatedExecutor`/`InstanceConfig` 的 classloader、config、startup/shutdown 和 latest config surface。 |
| `testing_injvm_schema_query_harness` | `AbstractCluster.schemaChange()`、`Coordinator.executeWithResult()`、paging、`ICoordinator` API。 |
| `testing_injvm_message_filter_faults` | `MessageFilters`、`IMessageSink`、`deliverMessage()`、`Instance.receiveMessage()` 和 drop filter。 |
| `testing_injvm_nodetool_probe` | `Instance.nodetoolResult()`、`DTestNodeTool`、`InternalNodeProbe` 和 nodetool dtest anchors。 |
| `testing_upgrade_dtest_lifecycle` | `UpgradeableCluster`、`KEY_DTEST_API_CONFIG_CHECK`、`UpgradeTestBase.TestCase.run()` 节点升级循环。 |
| `testing_simulator_agent_schedule` | simulator Ant target、`SimulationRunner`、`ClusterSimulation`、`ActionPlan`/`ActionSchedule`、Paxos runner/history checker。 |
| `testing_byteman_fault_injection` | dtest shared `Byteman` helper、BMUnitRunner tests 和 resource script anchors。 |
| `testing_ant_runner_targets` | `build.xml` 的 unit/dtest/simulator/upgrade/dtest-jar targets。 |
| `testing_dtest_api_artifact_boundary` | `dtest-api-*.jar` 仍是外部 artifact；当前 checkout 没有可解压清单。 |

## 检查内容

- source token checks：验证关键源码文件仍包含矩阵引用的方法、字段、target 或配置 token。
- test anchor checks：验证当前源码树仍有代表性测试锚点，如 `JVMDTestTest`、`AbstractClusterTest`、`NativeProtocolTest`、`HintedHandoffNodetoolTest`、simulator smoke tests 和 Byteman tests。
- artifact boundary check：扫描当前 checkout，确认没有可直接检查的 `dtest-api` artifact；如果 artifact 出现，checker 会失败，提示补完整 API 清单。
- doc checks：验证新增 matrix、已有 testing 文档、README 和 source-map 中仍包含场景 ID、关键路径和 checker 路径。

## 调用链

```text
python3 research/tools/check-testing-runtime-harness-drift.py
  -> source_checks()
     -> read source files
     -> verify exact tokens
     -> scan dtest-api artifact absence
  -> doc_checks()
     -> combine target research docs
     -> verify scenario ids and required tokens
  -> print count or JSON
```

## 运行方式

```bash
python3 research/tools/check-testing-runtime-harness-drift.py
python3 research/tools/check-testing-runtime-harness-drift.py --json
```

## 成功含义

成功表示当前 checkout 的 testing runtime harness 源码合同、已有测试锚点、外部 dtest API artifact 边界和 research 文档保持一致。

## 不覆盖内容

- 不运行 Ant/JUnit/dtest/simulator。
- 不验证 CircleCI config 生成器；该部分由 `research/tools/check-testing-ci-generator-drift.py` 保护。
- 不枚举外部 `dtest-api-*.jar` 内的完整 API；artifact 出现后应新增专门清单和 checker。
- 不证明 remote JMX/TLS/OS network 行为，因为 in-JVM nodetool 和 message filter 都是进程内 harness。

## 失败处理

- source token missing：先确认是否源码重构，再更新 matrix 和 checker 中的真实方法名/路径。
- test anchor missing：确认测试是重命名、删除还是覆盖变弱；覆盖变弱时要在 matrix 中保留 gap。
- artifact boundary failure：说明 `dtest-api` artifact 进入源码树，应补 public class/method 清单并更新 `testing_dtest_api_artifact_boundary`。
- doc token missing：补回场景 ID、路径或 checker 引用，避免 README/source-map 与矩阵脱节。
