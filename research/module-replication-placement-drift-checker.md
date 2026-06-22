# Module: Replication Placement Drift Checker

## 范围

本模块记录 `research/tools/check-replication-placement-drift.py` 的用途、输入、输出和维护方式。它保护 `research/module-replication-placement-pending-range-matrix.md` 中的 replication strategy placement、RF/transient validation、pending range、ReplicaPlan read/write、MV pending write 和 StorageService/JMX observability 合同。

## 设计目标

- 用 `ReplicationParams`、`KeyspaceMetadata` 和 `AbstractReplicationStrategy` 作为 keyspace replication strategy resolution 的源码事实来源。
- 用 `ReplicationFactor`、`SimpleStrategy`、`NetworkTopologyStrategy` 保护 RF parse、full/transient 标记、DC/rack placement 和 NTS auto-expansion。
- 用 `TokenMetadata` 与 `PendingRangeCalculatorService` 保护 leave/bootstrap/move pending range 保守计算。
- 用 `ReplicaPlans`、`StorageProxy` 和 `StorageService` 保护 coordinator/JMX 使用 natural 和 pending replicas 的边界。
- 要求研究文档保留本轮 15 个 scenario IDs 和测试基线/gap 标记。

## 解决的问题

- Replication 语义分散在 schema、locator、service、StorageProxy 和 tests 中，容易只维护 consistency-level 文档而漏掉 placement/pending-range 合同。
- NTS `replication_factor` auto-expansion、pending range conservative writes 和 LWT multi-pending boundary 是易漂移的细节，需要 source/doc 同步检查。
- checker 可在不启动 Cassandra、不运行 dtest 的情况下提示源码重构导致研究文档引用过期。

## 设计取舍

- checker 使用精确字符串和文件存在性检查，不解析 Java AST；源码重构但语义不变时，应同步更新 checker token。
- checker 不执行 unit/dtest；测试项只验证关键测试文件仍包含目标场景、断言或 helper 调用。
- 文档检查只验证 scenario IDs、关键类/配置/测试名存在，不约束 Markdown 表格布局。

## 核心接口

- `check_source_tokens()`：按 path/token 列表验证源码合同。
- `check_test_tokens()`：验证测试基线仍包含关键用例和断言。
- `check_doc_tokens()`：验证研究文档和索引覆盖 scenario IDs、checker 命令、测试名和 gap。
- `--json`：输出 source/test/doc check 计数和失败项，适合 CI artifact。

## 生命周期

```text
developer changes replication strategy, TokenMetadata pending ranges, ReplicaPlans, StorageProxy MV writes, or StorageService JMX surfaces
  -> run python3 research/tools/check-replication-placement-drift.py
  -> checker validates source/test/doc tokens
  -> source drift requires updating matrix + checker
  -> doc drift requires updating research references/index rows
```

## 运维关注点

- checker 只证明 research 与当前源码同步，不证明跨 DC replacement、LWT multi-pending 或 JMX CLI 层端到端覆盖已经存在。
- 如果新增真实 distributed tests，应把 `replication_pending_distributed_gap` 拆成已覆盖项，并同步扩展 checker 的 test tokens。
- 适合与 consistency guardrail、dynamic snitch、system keyspace RF、repair/streaming transient checker 一起运行。

## 命令

```bash
python3 research/tools/check-replication-placement-drift.py
python3 research/tools/check-replication-placement-drift.py --json
```
