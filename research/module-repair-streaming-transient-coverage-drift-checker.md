# Repair/Streaming Transient Coverage Drift Checker

## 范围

`research/tools/check-repair-streaming-transient-coverage-drift.py` 是 source-only drift check，用来保护 `research/module-repair-streaming-transient-fault-coverage.md` 中的 transient repair/streaming fault coverage matrix。

它不启动 Cassandra、不跑 JUnit，也不证明缺失场景已经实现。它只做三件事：

- 校验当前源码仍保留 transient-aware repair sync、owned range validation、pending write guard 和 transient read guard 的关键合同。
- 校验 unit/distributed tests 仍覆盖这些合同的现有测试点。
- 扫描 `test/distributed` 中 transient RF/streaming repair fault marker；如果 upstream 新增了真正的 distributed transient repair/streaming failure test，checker 会失败，提示更新研究文档和缺口判断。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `transient_standard_sync_direction` | `RepairJob.createStandardSyncTasks()` 对 transient/full pair 的 request/transfer/asymmetric/skip 规则 |
| `transient_optimized_sync_no_target` | optimised repair sync 不把 transient endpoint 当 target |
| `local_sync_request_transfer_flags` | `LocalSyncTask` request/transfer flags 到 stream plan 的映射 |
| `repair_validation_owned_range_rejection` | repair validation out-of-owned-range 行为和 metric |
| `stream_request_owned_range_rejection` | stream prepare 合并 full+transient ranges 后校验和 rejection |
| `mutation_pending_range_acceptance` | mutation/read-repair receiver 接受 pending range 写入 |
| `transient_read_full_replica_requirement` | read path 至少需要 full replica，digest 只发 full |
| `pending_bootstrap_write_distribution` | pending write distributed test 仍存在 |
| `generic_repair_stream_failure_injection` | generic repair stream failure dtest 仍存在 |
| `generic_stream_failure_visibility` | generic streaming failure log/virtual table dtests 仍存在 |
| `distributed_transient_repair_streaming_gap` | 当前 distributed tree 仍没有 transient RF + repair/streaming failure injection 组合 |

## 运行方式

```bash
python3 research/tools/check-repair-streaming-transient-coverage-drift.py
python3 research/tools/check-repair-streaming-transient-coverage-drift.py --json
```

成功时输出源码检查、文档检查和 distributed transient marker scan 的通过数量。失败时会列出具体缺失 token 或新增 marker 文件。

## 更新规则

- 如果 `RepairJob`、`LocalSyncTask`、`OwnedRanges`、`StreamSession` 或 pending write/read transient guard 的源码合同改变，先更新 `module-repair-streaming-transient-fault-coverage.md`，再调整 checker token。
- 如果新增了真正的 transient repair/streaming distributed fault test，不要只改 checker allow-list；应把 `distributed_transient_repair_streaming_gap` 改成具体覆盖场景，并把新测试文件和断言写进 module 文档。
- 如果 `test/distributed/org/apache/cassandra/distributed/test/ring/BootstrapTest.java` 中 `transient_ranges` available-ranges V2 用例移动或重命名，更新 marker allow-list，并确认它仍不是 transient RF repair/streaming failure injection。
