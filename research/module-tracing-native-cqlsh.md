# Module: Tracing Native Protocol And Cqlsh

## 范围

本模块补齐 query tracing 从 native protocol flag、服务端 trace session、`system_traces` 持久化到 cqlsh 展示的链路。Repair tracing、日志框架和 JMX/nodetool 的总体观测入口仍以 `research/module-operations-observability.md` 和 `research/flow-ops-tools.md` 为主。

`system_traces.sessions/events` 的列、写入方、读取方和默认可读授权矩阵见 `research/module-system-tables-core-matrix.md`。

## 设计目标

- 让客户端可以在单个 native request 上显式开启 tracing，并在 response 中拿到 trace session id。
- 让服务端在 `QUERY`、`PREPARE`、`EXECUTE`、`BATCH` 这些 traceable request 上创建 trace session，记录 request metadata、事件和完成时间。
- 让 sampling tracing 通过 `settraceprobability` 复用同一套服务端 trace 写入逻辑，但不改变客户端协议响应。
- 让 cqlsh 能通过 `TRACING ON/OFF`、`SHOW SESSION <uuid>` 和 driver `QueryTrace` 把 `system_traces.sessions/events` 打印成可读表格。

## 解决的问题

- native protocol 的 `TRACING` flag 同时表示请求要求 tracing 与响应携带 tracing id；flag 定义在 `Envelope.Header.Flag`，见 `src/java/org/apache/cassandra/transport/Envelope.java:153-160`。
- inbound request decode 只把 flag 转成 `Request.tracingRequested`，实际 session 创建在 request 执行前统一完成，见 `src/java/org/apache/cassandra/transport/Message.java:427-463` 和 `src/java/org/apache/cassandra/transport/Message.java:236-270`。
- response encode 在 body 前写入 trace UUID 并设置 `TRACING` flag，request encode 则只设置 flag、不写 UUID，见 `src/java/org/apache/cassandra/transport/Message.java:329-417`。
- trace session/event 写入不是同步业务结果的一部分；`TraceStateImpl` 把 mutation 提交给 `Stage.TRACING`，最终以 `ConsistencyLevel.ANY` 写 `system_traces`，见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:63-70` 和 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:104-121`。
- cqlsh 需要避免查询 `system_traces` 时递归 tracing，并在 trace 未及时完整时仍展示 partial session，见 `pylib/cqlshlib/cqlshmain.py:934-960`。

## 设计取舍

- tracing 开关放在 native frame header，而不是 CQL 文本里；这样 `QUERY`、`PREPARE`、`EXECUTE`、`BATCH` 可以共用 `Message.Request.execute()` 的 session 管理，见 `src/java/org/apache/cassandra/transport/Message.java:236-270`。
- 只有客户端显式设置 request tracing flag 时，response 才会带 trace id；概率采样同样会创建 session，但 `response.setTracingId()` 受 `isTracingRequested()` 限制，见 `src/java/org/apache/cassandra/transport/Message.java:241-268`。
- 各 request message 自己负责 `Tracing.instance.begin(...)` 的 request name 和参数，避免 transport 层了解 CQL options/bind variables，见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:135-147` 和 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:213-240`。
- `BATCH` trace 不记录 typed bind values；源码注释说明 batch path 当前没有 typed access，见 `src/java/org/apache/cassandra/transport/messages/BatchMessage.java:243-252`。
- trace event 写失败只 warn，不反向中断被观测的请求；overload 分支见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:112-121`。
- cqlsh trace 展示依赖 Python driver `QueryTrace.populate()`，服务端只保证写 `system_traces` 表，格式化在 `pylib/cqlshlib/tracing.py:24-77`。

## 核心类

| 类 | 作用 |
|---|---|
| `Envelope.Header.Flag` | native frame flag 枚举，包含 `TRACING`、`CUSTOM_PAYLOAD`、`WARNING`、`USE_BETA`。见 `src/java/org/apache/cassandra/transport/Envelope.java:153-180` |
| `Message.Request` | 统一处理 traceable request 的 explicit tracing、probabilistic tracing、session stop 和 response tracing id。见 `src/java/org/apache/cassandra/transport/Message.java:220-270` |
| `Message.Decoder` | 把 inbound frame flag 转为 request tracing request 或 response tracing id。见 `src/java/org/apache/cassandra/transport/Message.java:427-463` |
| `QueryMessage` | `QUERY` 的 trace metadata，包括 query/page size/CL/serial CL。见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:90-147` |
| `PrepareMessage` | `PREPARE` 的 trace metadata，记录原始 query。见 `src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:111-130` |
| `ExecuteMessage` | `EXECUTE` 的 trace metadata，记录 raw CQL、page/CL/serial CL 和 bind values。见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:118-240` |
| `BatchMessage` | `BATCH` 的 trace metadata，记录 CL/serial CL。见 `src/java/org/apache/cassandra/transport/messages/BatchMessage.java:160-252` |
| `Tracing` / `TracingImpl` / `TraceStateImpl` | trace session lifecycle、start/stop/event mutation 和 async write。见 `src/java/org/apache/cassandra/tracing/Tracing.java:72-190`、`src/java/org/apache/cassandra/tracing/TracingImpl.java:40-66`、`src/java/org/apache/cassandra/tracing/TraceStateImpl.java:63-121` |
| `TraceKeyspace` | `system_traces.sessions/events` schema、默认 RF 和 mutation builders。见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:50-113`、`src/java/org/apache/cassandra/tracing/TraceKeyspace.java:115-163` |
| `cqlshlib.tracing` | cqlsh 查询并格式化 `QueryTrace`。见 `pylib/cqlshlib/tracing.py:24-77` |

## 核心接口

- `Message.Request.execute(QueryState, RequestTime)`：request wrapper，创建/停止 trace session 并调用具体 message 的 `execute(..., traceRequest)`，见 `src/java/org/apache/cassandra/transport/Message.java:236-270`。
- `Message.Request.isTraceable()`：默认 false，只有 CQL request message 覆盖为 true；基类和 `QUERY` 示例见 `src/java/org/apache/cassandra/transport/Message.java:220-224`、`src/java/org/apache/cassandra/transport/messages/QueryMessage.java:90-93`。
- `Message.Request.execute(QueryState, RequestTime, boolean traceRequest)`：具体 message 读取 `traceRequest` 后调用 `Tracing.instance.begin(...)`，抽象定义见 `src/java/org/apache/cassandra/transport/Message.java:234`。
- `Tracing.newSession(...)` / `stopSession()`：创建 thread-local trace state、放入 sessions map，并在结束时清理，见 `src/java/org/apache/cassandra/tracing/Tracing.java:158-188`、`src/java/org/apache/cassandra/tracing/Tracing.java:201-215`。
- `Tracing.addTraceHeaders()` / `initializeFromMessage()`：internode message 传播 trace session/type，不属于 native client frame，但决定跨节点事件归并，见 `src/java/org/apache/cassandra/tracing/Tracing.java:248-312`。
- `QueryTrace.populate()` 使用点：cqlsh `SHOW SESSION` 和 statement tracing 都通过 driver trace 对象读取 `system_traces`，见 `pylib/cqlshlib/tracing.py:24-35`、`pylib/cqlshlib/cqlshmain.py:952-960`。

## 核心数据结构

- `Envelope.Header.flags`：native frame flag bitset，decode/serialize 基于 enum ordinal，见 `src/java/org/apache/cassandra/transport/Envelope.java:153-180`。
- `Message.Response.tracingId`：response 内部携带的 `TimeUUID`，encode 时写入 frame body 头部，见 `src/java/org/apache/cassandra/transport/Message.java:293-315`、`src/java/org/apache/cassandra/transport/Message.java:341-370`。
- `Request.tracingRequested`：inbound request 的 explicit tracing 标记，decode 设置、wrapper 读取，见 `src/java/org/apache/cassandra/transport/Message.java:273-280`、`src/java/org/apache/cassandra/transport/Message.java:446-453`。
- `TraceType`：`NONE/QUERY/REPAIR`，query/repair TTL 从 config 读取，见 `src/java/org/apache/cassandra/tracing/Tracing.java:72-100`。
- `Tracing.sessions`：本地 session id 到 `TraceState` 的并发 map，用于跨线程/跨节点 trace state 查找，见 `src/java/org/apache/cassandra/tracing/Tracing.java:107-109`、`src/java/org/apache/cassandra/tracing/Tracing.java:184-188`。
- `system_traces.sessions`：保存 request、parameters、started_at、duration、coordinator/client 等 session 元数据，schema 见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:73-87`。
- `system_traces.events`：保存 activity、source、source_elapsed、thread 等事件，schema 见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:88-100`。

## 生命周期

```text
Client request with TRACING flag
  -> Envelope decode reads header flags
  -> Message.Decoder sets Request.tracingRequested
  -> Dispatcher calls Message.Request.execute(queryState, requestTime)
     -> if isTraceable and tracingRequested:
          Tracing.newSession(explicit session id, customPayload)
     -> concrete Query/Prepare/Execute/Batch execute(..., traceRequest=true)
        -> TracingImpl.begin(request, client, parameters)
        -> request logic emits Tracing.trace(...)
     -> finally Tracing.stopSession()
     -> response.setTracingId(explicit session id)
  -> Message.encode writes tracing id and response TRACING flag
  -> client/driver receives trace id
  -> cqlsh fetches QueryTrace and prints rows
```

概率采样路径从 `StorageService.shouldTraceProbablistically()` 进入 `Tracing.newSession(getCustomPayload())`，但不设置 response trace id，见 `src/java/org/apache/cassandra/transport/Message.java:249-268` 和 `src/java/org/apache/cassandra/service/StorageService.java:6626-6639`。

## 调用链

- 请求 flag decode：`Message.Decoder.decodeMessage()` 判断 request/response、`TRACING`/`CUSTOM_PAYLOAD`/`WARNING` flags，request 分支调用 `req.setTracingRequested()`，见 `src/java/org/apache/cassandra/transport/Message.java:427-453`。
- trace session wrapper：`Message.Request.execute()` 创建 explicit 或 probabilistic session、传入 `traceRequest`、finally stop session，见 `src/java/org/apache/cassandra/transport/Message.java:236-270`。
- `QUERY`：`QueryMessage.execute()` 在 page size 校验后按 `traceRequest` 调用 `traceQuery()`，再 parse/process，见 `src/java/org/apache/cassandra/transport/messages/QueryMessage.java:102-123`。
- `PREPARE`：`PrepareMessage.execute()` 在 `traceRequest` 下 begin "Preparing CQL3 query"，见 `src/java/org/apache/cassandra/transport/messages/PrepareMessage.java:118-130`。
- `EXECUTE`：`ExecuteMessage.execute()` 查 prepared statement、prepare options、调用 `traceQuery()`，`traceQuery()` 展开 bind variables 并截断超长 literal，见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:131-169`、`src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:213-240`。
- `BATCH`：`BatchMessage.execute()` 在 statement prepare 前 begin batch trace，见 `src/java/org/apache/cassandra/transport/messages/BatchMessage.java:173-180`、`src/java/org/apache/cassandra/transport/messages/BatchMessage.java:243-252`。
- cqlsh statement path：`TRACING` 改变 `self.tracing_enabled`，statement 执行时把该值传给 driver `execute_async(..., trace=...)`，见 `pylib/cqlshlib/cqlshmain.py:1659-1678`、`pylib/cqlshlib/cqlshmain.py:990-995`。
- cqlsh display path：statement 完成后调用 `future.get_all_query_traces(...)` 并 `print_trace()`；超时则打印 partial session，见 `pylib/cqlshlib/cqlshmain.py:948-962`。
- `SHOW SESSION`：解析 UUID 后调用 `show_session()`，最终 `print_trace_session()` 使用 `QueryTrace.populate()`，见 `pylib/cqlshlib/cqlshmain.py:1519-1537`、`pylib/cqlshlib/tracing.py:24-35`。

## 配置项

| 配置项 | 定义位置 | 作用 |
|---|---|---|
| `trace_type_query_ttl` | `src/java/org/apache/cassandra/config/Config.java:550-554`、`conf/cassandra.yaml:1750-1754` | query trace 在 `system_traces` 中的 TTL，默认 1d |
| `trace_type_repair_ttl` | `src/java/org/apache/cassandra/config/Config.java:550-554`、`conf/cassandra.yaml:1750-1754` | repair trace 在 `system_traces` 中的 TTL，默认 7d |
| `cassandra.system_traces.default_rf` | `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:536-542`、`src/java/org/apache/cassandra/tracing/TraceKeyspace.java:50-112` | `system_traces` keyspace 默认 RF 下限 |
| `cassandra.wait_for_tracing_events_timeout_secs` | `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:622-627`、`src/java/org/apache/cassandra/tracing/TraceStateImpl.java:53-89` | 请求结束时等待 pending trace event 的时间；默认 0 |
| `cassandra.custom_tracing_class` | `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:176-181`、`src/java/org/apache/cassandra/tracing/Tracing.java:111-129` | 替换默认 `TracingImpl` |
| `settraceprobability` | `src/java/org/apache/cassandra/tools/nodetool/SetTraceProbability.java:27-38`、`src/java/org/apache/cassandra/service/StorageService.java:6626-6639` | runtime sampling tracing 概率，0 到 1 |
| cqlsh `[tracing] max_trace_wait` | `pylib/cqlshlib/cqlshmain.py:360-375`、`pylib/cqlshlib/cqlshmain.py:2088-2098` | cqlsh 等待 trace 完整的最大时间 |

## Metrics

- tracing 没有独立的 Dropwizard metric 类；主要可观测面是 `system_traces.sessions/events` 行、`Stage.TRACING` 执行压力和 trace 写入的 warning。
- native trace flag 自身不增加专属 protocol metric；frame 收发字节仍走 `ClientMessageSizeMetrics`，定义见 `src/java/org/apache/cassandra/metrics/ClientMessageSizeMetrics.java:29-35`。
- trace event 写入通过 `StorageProxy.mutate(..., ANY)`，因此高 tracing 采样会表现为额外 internal write workload，而不是单独的 tracing counter，见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:104-121`。
- cqlsh 侧 trace 获取失败只打印错误，不回写服务端 metric，见 `pylib/cqlshlib/cqlshmain.py:952-962`。

## 日志

- 自定义 tracing class 构造失败时默认退回 `TracingImpl` 并记录 error，见 `src/java/org/apache/cassandra/tracing/Tracing.java:111-129`。
- outbound internode trace 记录失败时只 warn，不影响消息发送，见 `src/java/org/apache/cassandra/tracing/Tracing.java:276-303`。
- `TraceStateImpl.waitForPendingEvents()` 在 trace 级别记录等待与 timeout，异常时 error，见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:76-100`。
- trace mutation 遇到 overload 时 warn "Too many nodes are overloaded to save trace events"，见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:112-121`。
- cqlsh 对 trace 未完成和获取异常分别输出提示，见 `pylib/cqlshlib/cqlshmain.py:952-962`。

## 运维关注点

- `settraceprobability 1` 会让所有 traceable request 进入 trace 写入路径；这会显著增加 `system_traces` 写放大，命令参数校验见 `src/java/org/apache/cassandra/tools/nodetool/SetTraceProbability.java:27-38`。
- 客户端显式 tracing 才能稳定拿到 trace id；概率采样 session 不会在 native response 中返回 id，见 `src/java/org/apache/cassandra/transport/Message.java:249-268`。
- `system_traces` 的 RF 来自 `max(cassandra.system_traces.default_rf, default_keyspace_rf)`，默认 RF 逻辑见 `src/java/org/apache/cassandra/tracing/TraceKeyspace.java:50-112`。
- cqlsh 对 `system_traces` keyspace 的 SELECT 临时关闭 tracing，避免 trace 查询再产生 trace，见 `pylib/cqlshlib/cqlshmain.py:934-941`。
- trace 数据有 TTL，过期后 `SHOW SESSION` 或 driver trace populate 只能显示缺失；TTL config 见 `conf/cassandra.yaml:1750-1754`。
- prepared statement trace 会记录 bound values，且长 literal 截断到约 1000 字符；敏感值风险由客户端是否开启 tracing 决定，见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:225-237`。

## 性能瓶颈

- 每个 trace event 都构造 mutation 并提交 `Stage.TRACING`，高采样时 executor、`system_traces` memtable/commitlog 和 coordinator 写路径都会变热，见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:63-70`、`src/java/org/apache/cassandra/tracing/TraceStateImpl.java:104-121`。
- `cassandra.wait_for_tracing_events_timeout_secs` 大于 0 会让 session stop 等 pending events，改善测试/展示完整性，但可能增加 request tail latency，见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:76-89`。
- cqlsh 在查询结果返回后再拉取 trace；`max_trace_wait` 太大时交互式体验会被 trace populate 拖慢，读取位置见 `pylib/cqlshlib/cqlshmain.py:952-960`。
- prepared query tracing 要把每个 bind value 转成 CQL literal，复杂集合和大字符串会增加 CPU 与 trace row 体积，见 `src/java/org/apache/cassandra/transport/messages/ExecuteMessage.java:225-237`。

## 常见故障

- cqlsh 显示 "Statement trace did not complete..."：driver 在 `max_trace_wait` 内没有拿到完整 trace，cqlsh 会继续按 trace id 展示 partial session，见 `pylib/cqlshlib/cqlshmain.py:952-960`。
- `SHOW SESSION` 找不到 session：trace row 可能尚未写入、TTL 已到期、RF/节点不可用或 trace write overload，cqlsh lookup 入口见 `pylib/cqlshlib/tracing.py:24-35`。
- driver 没拿到 trace id：请求未设置 native `TRACING` flag，或者是服务端概率采样而非显式 tracing；response id 设置条件见 `src/java/org/apache/cassandra/transport/Message.java:267-268`。
- trace events 少于预期：trace writes 使用 async mutation 且 overload 只 warn，见 `src/java/org/apache/cassandra/tracing/TraceStateImpl.java:104-121`。
- batch trace 缺少 bind values：`BatchMessage.traceQuery()` 只记录 CL/serial CL，源码明确没有 typed access，见 `src/java/org/apache/cassandra/transport/messages/BatchMessage.java:243-252`。

## 测试用例

- `TraceCqlTest` 覆盖 driver `enableTracing()` 后 prepared statement trace parameters、bind variables、tuple/map、长字符串截断和 `UNSET`，见 `test/unit/org/apache/cassandra/cql3/TraceCqlTest.java:61-173`。
- `TracingTest` 覆盖 session lifecycle、`get(sessionId)`、custom payload、activity notification 和 progress listener，见 `test/unit/org/apache/cassandra/tracing/TracingTest.java:42-162`。
- cqlsh completion 覆盖 `SHOW SESSION` 和 `TRACING ON/OFF` 语法提示，见 `pylib/cqlshlib/test/test_cqlsh_completion.py:1075-1081`。
- in-JVM distributed test helper 可显式创建 trace session 并查询 `system_traces.events`，见 `test/distributed/org/apache/cassandra/distributed/impl/Coordinator.java:64-76`、`test/distributed/org/apache/cassandra/distributed/impl/TracingUtil.java:69-86`。
- 当前测试侧没有直接覆盖 `Message.encode/decode` 对 native `TRACING` request/response flag 与 response trace UUID 的逐帧断言；协议层风险主要由 driver-level trace tests 间接覆盖。
