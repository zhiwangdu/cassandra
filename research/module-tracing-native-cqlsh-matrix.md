# Module: Tracing Native Cqlsh Operations Matrix

## 范围

本模块把 query tracing 从 native frame flag 到 `system_traces`、internode propagation、cqlsh 展示和测试缺口拆成可检查矩阵。它补强 `research/module-tracing-native-cqlsh.md`，并和 `research/flow-native-protocol.md`、`research/flow-cql-request.md` 共享 native/CQL 调用链锚点。

当前源码基线：

- Header flag bit order 由 `Envelope.Header.Flag` 固定，`TRACING` 位于 `COMPRESSED` 后、`CUSTOM_PAYLOAD` 前；顺序变动就是 wire ABI 变动，见 `src/java/org/apache/cassandra/transport/Envelope.java:153`。
- Request decode 只把 `TRACING` header bit 转成 `Request.tracingRequested`；response decode 才从 body prelude 读取 trace UUID，见 `src/java/org/apache/cassandra/transport/Message.java:427`。
- `Message.Request.execute()` 只有在 `isTraceable()` 为 true 时才创建 tracing session；显式 request tracing 会把 `nextTimeUUID()` 写入 response，概率采样不会把 trace id 回给客户端，见 `src/java/org/apache/cassandra/transport/Message.java:236`。
- `QueryMessage`、`PrepareMessage`、`ExecuteMessage`、`BatchMessage` 是 native CQL tracing 的 request entrypoints，分别负责自己的 `Tracing.instance.begin(...)` request name 和参数，见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:89`、`src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:111`、`src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:118`、`src/java/org/apache/cassandra/transport/messages/BatchMessage.java:160`。
- `TraceStateImpl` 把 session/event mutations 提交到 `Stage.TRACING`，最终用 `ConsistencyLevel.ANY` 写 `system_traces`；overload 只 warn，见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:63`、`src/java/org/apache/cassandra/tracing/TraceStateImpl.java:104`。
- cqlsh 通过 `TRACING ON/OFF` 控制 driver request tracing，并通过 `QueryTrace.populate()` 格式化 `system_traces`，见 `pylib/cqlshlib/cqlshmain.py:934`、`pylib/cqlshlib/cqlshmain.py:952`、`pylib/cqlshlib/tracing.py:24`。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `tracing_native_flag_decode_encode` | `Envelope.Header.Flag.TRACING` bit order、request header-only flag、response trace UUID prelude、decode/encode 对称性。 |
| `tracing_request_wrapper_lifecycle` | `Request.execute()` 显式/概率 tracing 分支、`Tracing.newSession()`、`finally stopSession()`、response trace id 只返回显式请求。 |
| `tracing_query_prepare_execute_batch_begin` | QUERY/PREPARE/EXECUTE/BATCH 的 `isTraceable()` 和 `Tracing.instance.begin(...)` request name/parameters。 |
| `tracing_probabilistic_sampling_boundary` | `StorageService.shouldTraceProbablistically()` 和 nodetool `settraceprobability` 的 0..1 gate；概率采样无客户端 trace id。 |
| `tracing_system_traces_mutation_async` | `TraceKeyspace` schema、start/stop/event mutation builder、`Stage.TRACING` async write、`ANY` consistency 和 overload warn。 |
| `tracing_internode_propagation` | `TRACE_SESSION`/`TRACE_TYPE` message params、`initializeFromMessage()`、response expired state 和 outbound message trace。 |
| `tracing_cqlsh_toggle_show_session` | cqlsh `TRACING ON/OFF`、`SHOW SESSION`、system_traces recursion guard、partial session fallback 和 table formatting。 |
| `tracing_config_ttl_wait_custom_class` | query/repair TTL、system_traces default RF、pending event wait timeout、custom tracing class fallback 和 cqlsh max wait。 |
| `tracing_test_coverage_and_frame_gap` | 现有 `TraceCqlTest`/`TracingTest`/cqlsh completion/distributed helper 覆盖面，以及 native frame-level test gap。 |

## Source Contract

### Native Frame Contract

| Direction | Trigger | Body prelude | Result |
|---|---|---|---|
| Request decode | Header contains `TRACING` | None | `Message.Decoder.decodeMessage()` calls `req.setTracingRequested()` after attaching connection, see `src/java/org/apache/cassandra/transport/Message.java:446`。 |
| Request encode | `Request.isTracingRequested()` | None | `Message.encode()` adds `Envelope.Header.Flag.TRACING` but does not write a trace UUID into the request body, see `src/java/org/apache/cassandra/transport/Message.java:382`。 |
| Response encode | `Response.getTracingId() != null` | Trace UUID before warnings/custom payload | `CBUtil.writeUUID(tracingId, body)` then adds `TRACING` flag, see `src/java/org/apache/cassandra/transport/Message.java:338`。 |
| Response decode | Header contains `TRACING` and message direction is response | Trace UUID | `CBUtil.readTimeUUID(inbound.body)` then `setTracingId(tracingId)`, see `src/java/org/apache/cassandra/transport/Message.java:427`。 |

`tracing_native_flag_decode_encode` should be treated as native protocol ABI coverage: the flag bit order in `Envelope.Header.Flag` and the response prelude order in `Message.encode()` must be kept in sync with any driver compatibility notes.

### Request Lifecycle

```text
Message.Decoder.decodeMessage()
  -> if request and TRACING flag: Request.setTracingRequested()
  -> Dispatcher executes Request.execute(queryState, requestTime)
     -> if isTraceable() and isTracingRequested()
        -> tracingSessionId = nextTimeUUID()
        -> Tracing.instance.newSession(tracingSessionId, customPayload)
     -> else if isTraceable() and StorageService.shouldTraceProbablistically()
        -> Tracing.instance.newSession(customPayload)
     -> concrete message execute(..., shouldTrace)
        -> if shouldTrace: Tracing.instance.begin(...)
     -> finally if shouldTrace: Tracing.instance.stopSession()
     -> if explicit request tracing: response.setTracingId(tracingSessionId)
  -> Message.encode(response)
     -> write trace UUID body prelude and TRACING response flag
```

The important operational edge is that `tracing_probabilistic_sampling_boundary` creates `system_traces` rows but does not disclose the generated id to the client, because `response.setTracingId()` is gated by `isTracingRequested()`.

### Query Message Matrix

| Message | Traceable | Trackable | Trace request name | Parameters |
|---|---:|---:|---|---|
| `QUERY` / `QueryMessage` | true | true | `Execute CQL3 query` | `query`、optional `page_size`、`consistency_level`、`serial_consistency_level`，见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:135`。 |
| `PREPARE` / `PrepareMessage` | true | false inherited | `Preparing CQL3 query` | `query` only，见 `src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:122`。 |
| `EXECUTE` / `ExecuteMessage` | true | true | `Execute CQL3 prepared query` | page/CL/serial CL、raw prepared CQL、`bound_var_<index>_<name>`，long values truncated，UNSET becomes `<unset>`，见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:213`。 |
| `BATCH` / `BatchMessage` | true | true | `Execute batch of CQL3 queries` | CL and serial CL only; typed bind variables are explicitly missing pending CASSANDRA-4560，见 `src/java/org/apache/cassandra/transport/messages/BatchMessage.java:243`。 |

## 设计目标

- 把 native frame-level tracing 和 CQL request semantic tracing 分开，避免把 request header bit 误解成 body trace UUID。
- 明确显式 tracing 与 nodetool 概率采样在客户端可见性上的差异。
- 固化 `system_traces.sessions/events` 写入不是业务请求同步成功条件的事实。
- 把 cqlsh 展示能力与服务端 trace 写入/driver `QueryTrace` 读取边界分开。
- 让测试缺口可追踪：当前没有直接 frame-level Java test 断言 native `TRACING` request/response encode/decode。

## 解决的问题

- Drivers set `TRACING` as a header flag, not as a request body field; a server response must carry a UUID prelude before the response body for explicit tracing.
- `settraceprobability` is an operator sampling tool, not an API for clients to discover trace ids.
- Query tracing metadata is not centralized in transport; each CQL message chooses its trace request name and parameter map.
- High trace volume can overload `Stage.TRACING` and `system_traces` writes without failing the original request.
- cqlsh must avoid tracing its own reads from `system_traces` to prevent recursive trace generation.

## 设计取舍

- `Message.Request.isTraceable()` defaults false, so handshake/auth/OPTIONS paths can accept a frame flag without creating trace sessions.
- `Message.Request.execute()` owns start/stop lifecycle, while concrete request classes own `Tracing.instance.begin(...)` contents; this avoids leaking CQL option parsing into transport.
- Trace writes use async mutations at `ConsistencyLevel.ANY`; this makes tracing best-effort and low-latency for business requests, but operators must tolerate missing/partial traces.
- `TraceType` TTLs are config-backed and serialized by ordinal; enum order is compatibility-sensitive.
- cqlsh formats trace output client-side from driver `QueryTrace`, rather than requiring a server-side display API.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `Envelope.Header.Flag` | Native header flags and bit order; `TRACING` is the query tracing wire bit. |
| `Message.Request` | Traceable gate、explicit/probabilistic session creation、stop lifecycle and response trace id assignment. |
| `Message.encode()` / `Message.Decoder.decodeMessage()` | Native frame tracing flag and response trace UUID prelude encode/decode. |
| `QueryMessage` / `PrepareMessage` / `ExecuteMessage` / `BatchMessage` | CQL request-specific trace begin metadata. |
| `Tracing` / `TracingImpl` / `TraceStateImpl` | Session map、thread-local state、internode propagation、async mutation writes. |
| `TraceKeyspace` | `system_traces.sessions/events` schema and mutation builders. |
| `StorageService` / `SetTraceProbability` | Probabilistic tracing runtime state and nodetool control. |
| `cqlshlib.cqlshmain` / `cqlshlib.tracing` | `TRACING`/`SHOW SESSION` shell UX and trace table rendering. |
| `research/tools/check-tracing-native-cqlsh-drift.py` | Source-to-doc drift checker for this matrix. |

## 核心接口

- `Message.Request.isTraceable()` / `setTracingRequested()` / `isTracingRequested()`：native request tracing gate。
- `Message.Request.execute(QueryState, RequestTime)`：显式/概率 tracing lifecycle wrapper。
- `Message.Response.setTracingId()` / `getTracingId()`：response trace UUID prelude source。
- `Tracing.newSession(...)` / `begin(...)` / `stopSession()`：session lifecycle。
- `Tracing.initializeFromMessage()` / `addTraceHeaders()` / `traceOutgoingMessage()`：internode trace context propagation。
- `TraceStateImpl.executeMutation()` / `mutateWithCatch()`：async `system_traces` write path。
- `StorageService.setTraceProbability()` / `shouldTraceProbablistically()`：operator sampling gate。
- `print_trace_session()` / `print_trace()`：cqlsh display path。

## 配置项

| 配置项 | Source | 语义 |
|---|---|---|
| `trace_type_query_ttl` | `src/java/org/apache/cassandra/config/Config.java:550`、`src/java/org/apache/cassandra/tracing/Tracing.java:93` | Query trace rows TTL，默认 1 day。 |
| `trace_type_repair_ttl` | `src/java/org/apache/cassandra/config/Config.java:550`、`src/java/org/apache/cassandra/tracing/Tracing.java:93` | Repair trace rows TTL，默认 7 days。 |
| `cassandra.system_traces.default_rf` | `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:536`、`src/java/org/apache/cassandra/tracing/TraceKeyspace.java:50` | `system_traces` keyspace RF 下限。 |
| `cassandra.wait_for_tracing_events_timeout_secs` | `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:495`、`src/java/org/apache/cassandra/tracing/TraceStateImpl.java:53` | Session stop 时等待 pending trace event 的测试/运行时 timeout。 |
| `cassandra.custom_tracing_class` | `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:176`、`src/java/org/apache/cassandra/tracing/Tracing.java:111` | 自定义 tracing implementation；构造失败 fallback 到 `TracingImpl`。 |
| cqlsh `[tracing] max_trace_wait` | `pylib/cqlshlib/cqlshmain.py:2097` | cqlsh 等待 driver trace 完整的最大时间。 |

## Metrics

- Tracing 没有独立 Dropwizard metrics family；主要观测面是 `system_traces.sessions/events`、`Stage.TRACING` executor 压力和 warning 日志。
- `settraceprobability 1` 会让所有 traceable request 都进入 trace write path；这会放大 commitlog/memtable/system table 写入。
- cqlsh trace fetch 失败只打印错误或 partial session，不写服务端 metrics。
- `system_traces` rows TTL 到期后，cqlsh/driver 只能看到 missing session 或 incomplete event list。

## 日志

- `TraceStateImpl.mutateWithCatch()` 遇到 `OverloadedException` 记录 `Too many nodes are overloaded to save trace events`，不会抛回业务请求，见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:112`。
- 自定义 tracing class 构造失败会 error 并 fallback，见 `src/java/org/apache/cassandra/tracing/Tracing.java:123`。
- `Tracing.traceOutgoingMessage()` 捕获异常后 warn 并忽略，见 `src/java/org/apache/cassandra/tracing/Tracing.java:276`。
- cqlsh 在 trace 未完成时打印 `Statement trace did not complete...` 并尝试按 trace id 展示 partial session，见 `pylib/cqlshlib/cqlshmain.py:956`。

## 运维关注点

- 生产环境不应长时间使用高概率 tracing；它是诊断采样工具，会写 `system_traces` 并消耗 `Stage.TRACING`。
- 调查 missing trace 时区分三类原因：客户端没有显式 tracing、概率采样没有返回 trace id、trace rows 尚未写入或已 TTL 过期。
- 如果 `system_traces` RF 过低，节点故障时 trace 可读性会比业务数据更差；RF 由 `max(system_traces.default_rf, default_keyspace_rf)` 创建。
- cqlsh 读取 `system_traces` 时会临时关闭 tracing；不要把这种行为误判为 `TRACING OFF` 全局状态改变。
- Native protocol compatibility 测试需要覆盖 request flag decode 和 response UUID prelude，不能只依赖 driver-level `enableTracing()`。

## 性能瓶颈

- 每个 trace event 都构造 mutation 并提交到 `Stage.TRACING.executor()`，高采样时会出现 executor backlog。
- `TraceStateImpl.waitForPendingEvents()` 可等待 pending event futures；timeout 配得过高会拉长 traced request 尾部延迟。
- `system_traces.events` 写入是宽分区按 `session_id` 聚集；单个 trace session 事件过多会增加读取/格式化成本。
- cqlsh 在业务 future 完成后再拉取 trace，`max_trace_wait` 太大时交互式查询会被 trace populate 拖慢。

## 常见故障

- Client receives no trace id: request was not explicit tracing, message was not traceable, or the trace came from probabilistic sampling.
- cqlsh shows incomplete trace: trace mutations still pending、`Stage.TRACING` overloaded、`max_trace_wait` too small or trace rows already expired.
- `SHOW SESSION` says session was not found: UUID wrong、TTL expired、RF/node availability issue or async write failure.
- Batch trace has no bound variable details: current `BatchMessage.traceQuery()` intentionally lacks typed bind access pending CASSANDRA-4560.
- Response frame parser breaks after tracing change: response trace UUID prelude order or `Envelope.Header.Flag` bit order drifted.

## 测试用例

- `TraceCqlTest.testCqlStatementTracing()` covers driver `enableTracing()` prepared statement parameters, bind variables, long value truncation and `UNSET`，见 `test/unit/org/apache/cassandra/cql3/TraceCqlTest.java:61`。
- `TracingTest` covers lifecycle, `get(sessionId)`, custom payload, activity notification and progress listener，见 `test/unit/org/apache/cassandra/tracing/TracingTest.java:42`。
- cqlsh completion covers `SHOW SESSION` and `TRACING ON/OFF` syntax only，见 `pylib/cqlshlib/test/test_cqlsh_completion.py:1075`。
- in-JVM distributed helper can create a known trace session and query `system_traces.events`，见 `test/distributed/org/apache/cassandra/distributed/impl/Coordinator.java:64`、`test/distributed/org/apache/cassandra/distributed/impl/TracingUtil.java:69`。
- `tracing_test_coverage_and_frame_gap`: current tests do not directly assert `Message.encode()`/`Message.Decoder.decodeMessage()` native `TRACING` request flag and response trace UUID prelude at frame level.
