# Streaming Transfer Compatibility Drift Checker

## 范围

`research/tools/check-streaming-transfer-compatibility-drift.py` 是 source-only drift check，用来保护 `research/module-streaming-transfer-compatibility-matrix.md` 中的 streaming transfer compatibility matrix。

它不启动 Cassandra、不跑 JUnit，也不证明 mixed-version/TLS/`internode_compression` streaming 场景已经实现。它只做四件事：

- 校验 streaming handshake、TLS optional fallback、inbound streaming pipeline、control/file multiplex、SSTable transfer writer/reader、stream compression format、zero-copy/TLS fallback、state/netstats/metrics 等源码合同仍存在。
- 校验现有 unit/distributed tests 仍覆盖分层 baseline：serializer、semaphore/control failure、entire file count、netstats、`system_views.streaming`、ordinary internode encryption、messaging handshake optional fallback 和 isolated `internode_compression` config。
- 校验研究文档和索引仍引用所有 compatibility 场景 ID。
- 扫描 `test/distributed` 是否新增了同时包含 streaming marker、TLS marker、`internode_compression` marker 和 upgrade/mixed-version marker 的 Java 测试；如果发现，说明显式缺口已变化，必须更新矩阵。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `streaming_handshake_framing_contract` | streaming handshake MOD bit、version/framing flags 和 inbound `UNPROTECTED` streaming pipeline |
| `streaming_ssl_optional_fallback_contract` | optional TLS 下 streaming outbound fallback 策略 |
| `streaming_inbound_tls_policy_contract` | inbound TLS policy handler 与 ordinary internode TLS 测试 baseline |
| `streaming_control_file_channel_contract` | control/file channel 分离、`NettyStreamingChannel.acquireOut()` 单文件约束 |
| `streaming_file_semaphore_keepalive_contract` | file transfer semaphore、failure path 与 control failure baseline |
| `streaming_tls_zero_copy_fallback_contract` | TLS 下 entire SSTable zero-copy 回退到 user-space buffer |
| `streaming_internode_compression_boundary` | `internode_compression` 只作用于 messaging frame，不作用于 streaming payload |
| `streaming_stream_compression_format_contract` | `StreamCompressionSerializer` LZ4 chunk header/payload 格式 |
| `streaming_outgoing_file_header_contract` | `CassandraStreamHeader` wire header 与 outgoing file decision |
| `streaming_partial_uncompressed_contract` | partial uncompressed writer/reader 通过 stream compression 传输 |
| `streaming_partial_compressed_contract` | compressed SSTable partial writer/reader 通过 compressed chunk bytes 传输 |
| `streaming_entire_sstable_contract` | entire SSTable component manifest、writer/reader 和 count baseline |
| `streaming_state_netstats_observability_contract` | `StreamingState`、`system_views.streaming`、`nodetool netstats` 和 streaming metrics |
| `streaming_receive_failure_contract` | receive/read failure 到 `session.onError()` 和 failure visibility |
| `streaming_existing_tests_baseline` | 当前分层测试基线仍存在 |
| `streaming_mixed_tls_compression_gap` | 当前缺少 mixed-version + TLS + `internode_compression` + streaming transfer 组合 dtest |

## 运行方式

```bash
python3 research/tools/check-streaming-transfer-compatibility-drift.py
python3 research/tools/check-streaming-transfer-compatibility-drift.py --json
```

成功时输出源码检查、测试检查、gap scan、文档检查和场景数量。失败时列出具体缺失 token、缺失文档场景或新增的组合测试候选文件。

## 更新规则

- 如果 `HandshakeProtocol`、`InboundConnectionInitiator`、`NettyStreamingConnectionFactory`、`StreamingMultiplexedChannel`、`AsyncStreamingOutputPlus` 或 `Cassandra*Stream*` reader/writer 的源码合同改变，先更新 `module-streaming-transfer-compatibility-matrix.md`，再调整 checker token。
- 如果新增真正的 mixed-version/TLS/`internode_compression` streaming distributed/upgrade test，不要只放过 gap scan；应把 `streaming_mixed_tls_compression_gap` 改为具体覆盖项，并写明测试文件、触发操作、断言和剩余缺口。
- 如果 upstream 把 `internode_compression` 或 TLS 配置测试迁移到别的文件，更新 test token checks，并确认它仍不是 streaming transfer compatibility coverage。
