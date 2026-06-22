# Module: StorageProxy Coordinator Drift Checker

## 范围

`research/tools/check-storageproxy-coordinator-drift.py` 是 `research/module-storageproxy-coordinator-timeout-matrix.md` 的 source/test/doc drift checker。它保护普通 `StorageProxy` coordinator 的写入 response handler、读 executor/speculation、`ReadCallback` timeout/failure/warning、digest mismatch/read repair、JMX/config 操作面和现有测试基线。

当前基线：

- `StorageProxy.mutate()` / `performWrite()` / `sendToHintedReplicas()` 串起 ordinary write coordinator，`AbstractWriteResponseHandler.get()` 负责 timeout/failure 区分，handler 子类负责普通/local/EACH_QUORUM ack 语义。
- `StorageProxy.read()` / `readRegular()` / `fetchRows()` 串起 ordinary read coordinator，`AbstractReadExecutor` 根据 `speculative_retry` 选择 executor 并保护 native deadline。
- `ReadCallback.awaitResults()` 是 read timeout/failure/warning/abort 映射中心，`DigestResolver`/`DataResolver`/`ReadRepair` 负责 digest mismatch 后的 full data reconciliation 和 repair writes。
- `StorageProxyMBean` 暴露 read/write timeout、read repair counters、logging timer 和 repaired-data tracking toggles。
- 现有测试覆盖 write ideal CL、read speculation、ordinary request timeout、read failure race 和 read repair behavior；ordinary write cheap quorum backup 和完整 read warning/abort combination matrix 仍是 source-protected gaps。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `storageproxy_write_response_handler_lifecycle` | `StorageProxy.mutate()` to `AbstractWriteResponseHandler.get()` write lifecycle and ideal CL delegate. |
| `storageproxy_write_timeout_failure_metrics` | Write timeout/failure classification, CL.ANY hints, write metrics and coordinator write latency. |
| `storageproxy_write_local_remote_hint_dispatch` | `sendToHintedReplicas()` local apply, remote send, down-replica expiration and hint submit branch. |
| `storageproxy_write_cheap_quorum_additional_replicas` | Ordinary write cheap-quorum backup and `additionalWrites` metric. |
| `storageproxy_read_safety_denylist_dispatch` | Bootstrap safety, partition denylist and serial-vs-ordinary read dispatch. |
| `storageproxy_read_executor_selection_speculation` | `speculative_retry` executor selection, EACH_QUORUM exclusion, insufficient replicas and native deadline guard. |
| `storageproxy_read_callback_timeout_failure_warning` | `ReadCallback.awaitResults()` data-present requirement, warning context, abort and timeout/failure exception mapping. |
| `storageproxy_read_digest_mismatch_repair` | Digest mismatch, full data repair reads, repaired-data tracking and diagnostic start event. |
| `storageproxy_read_repair_write_blocking` | Iterator-close repair write speculation/await and blocking vs read-only read repair strategy. |
| `storageproxy_coordinator_latency_metrics` | Read/write client request metrics and table coordinator latency metrics. |
| `storageproxy_mbean_operational_surface` | StorageProxy JMX timeout setters, read repair counters, logging timer and repaired-data tracking toggles. |
| `storageproxy_existing_tests_baseline` | Unit/distributed test anchors and current focused-test gaps. |

## 设计目标

- Fail when core ordinary read/write coordinator source contracts move without updating research docs.
- Fail when test names or coverage anchors move without updating the matrix.
- Keep source-protected gaps explicit: a green checker means docs match current source, not that missing cheap-quorum or full warning/abort tests exist.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-storageproxy-coordinator-drift.py` | Source/test/doc drift checker. |
| `StorageProxy` | Ordinary read/write coordinator entry and metrics owner. |
| `AbstractWriteResponseHandler` / `WriteResponseHandler` / DC handlers | Write ack, timeout/failure and ideal CL accounting. |
| `ReadCallback` | Read response wait, warnings, abort, timeout and failure mapping. |
| `AbstractReadExecutor` | Read request fan-out, speculation and digest mismatch bridge. |
| `DigestResolver` / `DataResolver` | Digest comparison and full data reconciliation. |
| `ReadRepair` / `BlockingReadRepair` / `ReadOnlyReadRepair` | Digest mismatch repair reads and optional repair writes. |
| `StorageProxyMBean` | Runtime timeout, read repair, denylist and diagnostics controls. |

## 运维关注点

- Checker failures in `StorageProxy.java` usually mean the coordinator call graph, metrics or hint/read-repair boundary moved.
- Checker failures in handler/executor classes usually mean timeout/failure or speculation semantics changed and the runbook must be updated.
- Checker failures in tests are useful: they may indicate test renames, stronger coverage, or newly closed gaps.

## 常见故障

- `source token contract ... AbstractWriteResponseHandler.java` fails: write timeout/failure classification or cheap quorum backup changed.
- `source token contract ... ReadCallback.java` fails: read callback exception mapping or warning/abort path changed.
- `source token contract ... AbstractReadExecutor.java` fails: speculation or digest mismatch handoff changed.
- `doc token ...` fails: matrix, README or source map no longer names a protected scenario/path/test/config.

## 运行方式

- `python3 research/tools/check-storageproxy-coordinator-drift.py`
- `python3 research/tools/check-storageproxy-coordinator-drift.py --json`
- Related validation: `python3 -m py_compile research/tools/check-storageproxy-coordinator-drift.py`
