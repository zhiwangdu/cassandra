# Module: Nodetool Option Drift Checker

## 范围

`research/tools/check-nodetool-option-risk-drift.py` 是 source-only drift check，用来保护 `research/module-nodetool-option-risk-matrix.md` 的 nodetool `@Option` / `@Arguments` 风险覆盖。

它覆盖 `src/java/org/apache/cassandra/tools/NodeTool.java`、`src/java/org/apache/cassandra/tools/ListCIDRGroups.java` 和 `src/java/org/apache/cassandra/tools/nodetool/*.java`。当前 baseline 是 180 @Option、76 @Arguments、94 annotated source files。`JMXTool.java` 明确不纳入该 baseline，因为它不是 `NodeTool.execute()` command registry 的一部分。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `nodetool_global_jmx_connection_options` | 全局 JMX target、auth、password-file 和 print-port 参数。 |
| `nodetool_repair_scope_and_safety_options` | repair keyspace/table、DC/host/token、preview/validate/full、Paxos、pull/force 等参数。 |
| `nodetool_topology_change_arguments` | rebuild/move/removenode/assassinate/decommission/bootstrap resume 的 positional 和 force 参数。 |
| `nodetool_data_rewrite_options` | compact/scrub/verify/import/cleanup/garbagecollect/stop/sstablerepairedset 的 rewrite、validation、metadata mutation 参数。 |
| `nodetool_streaming_throughput_units` | stream/inter-DC stream throughput 的 Mbps、MiB/s、entire-SSTable 和 precise output 参数。 |
| `nodetool_audit_fql_runtime_options` | audit log 和 full query log runtime queue、roll、path、archive、blocking 参数。 |
| `nodetool_auth_cache_runtime_options` | auth/cache validity、update interval、max entries、active update 和 invalidation 参数。 |
| `nodetool_snapshot_cleanup_filters` | snapshot/clearsnapshot 的 keyspace/table/tag/ttl/time filter 参数。 |
| `nodetool_table_selection_arguments` | `[<keyspace> <tables>...]`、`[<keyspace.table>...]`、directory/CIDR group 等选择参数。 |
| `nodetool_output_format_options` | json/yaml/sort/top/human/vtable/port display 参数。 |
| `nodetool_guardrail_runtime_options` | get/set guardrails runtime config 的 category、expand、name/value 参数。 |
| `nodetool_sampler_runtime_options` | profileload sampler、capacity、top、interval、stop/list 参数。 |

## 运行方式

```bash
python3 research/tools/check-nodetool-option-risk-drift.py
python3 research/tools/check-nodetool-option-risk-drift.py --json
```

成功时输出 annotation counts、annotated file count 和同步确认。失败时输出新增/删除 annotated file、source contract 失败或 doc token 失败。

## 设计取舍

- checker 不运行 nodetool，不连接 JMX，也不加载 Airline parser；它只读取 Java source 和 research markdown。
- file set + annotation count 是粗粒度 drift gate；`SOURCE_EXPECTATIONS` 是高风险命令的细粒度 token gate。
- 文档检查要求 matrix 和 checker 文档同时保留 scenario ids、关键 source files、关键 tests 和 baseline counts。
- 新增 option 后，维护者需要判断是更新 baseline、扩充 `SOURCE_EXPECTATIONS`，还是明确排除不属于 nodetool registry 的 standalone tool。

## 更新规则

- 新增 nodetool command file 且包含 `@Option` / `@Arguments`：更新 `ANNOTATION_SOURCE_FILES`、baseline counts、risk matrix 和 source-map。
- 新增高风险 option：把 token 加入 `SOURCE_EXPECTATIONS`，并在 `module-nodetool-option-risk-matrix.md` 对应 scenario id 下说明风险。
- 修改 repair/topology/rewrite/runtime-control 参数：同步测试锚点，尤其是 `NodeToolCommandTest.java`、`NodeToolTest.java`、`SetAuthCacheConfigTest.java`、`SetAutoRepairConfigTest.java`、`SetGetStreamThroughputTest.java`、`SetGetInterDCStreamThroughputTest.java`、`ClearSnapshotTest.java`、`VerifyTest.java`、`ScrubToolTest.java`、`ImportTest.java`。
- 如果 `JMXTool.java` 需要 option-level drift coverage，应新增 JMXTool 专项 checker，不应混入 nodetool baseline。

## 常见故障

- `annotated file set matches baseline` 失败：新增或移除 annotation-bearing command file。
- `option annotation count matches baseline` 失败：新增或删除 `@Option`。
- `arguments annotation count matches baseline` 失败：新增或删除 `@Arguments`。
- `source contract <path>` 失败：高风险 token 移动、改名或消失，需要重读源码并更新 matrix。
- `doc scenario` 或 `doc token` 失败：研究文档没有覆盖 checker 要求的风险类别、source path、test anchor 或 baseline 数字。
