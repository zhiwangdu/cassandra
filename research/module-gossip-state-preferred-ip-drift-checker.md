# Module: Gossip State Preferred IP Drift Checker

## 范围

`research/tools/check-gossip-state-preferred-ip-drift.py` 是 `research/module-gossip-state-preferred-ip-coverage.md` 的 source/test/gap drift checker。它保护 Gossip 第五轮研究中关于 digest task、gossip stage mutation guard、endpoint state merge、application state wire compatibility、legacy state filtering、alive/dead ECHO gate、shadow round、shutdown announce、preferred IP reconnect 和剩余 distributed test 缺口的判断。

当前基线：

- Gossip round、state merge、legacy/new application state 过滤和 status notification order 都有源码锚点，并有 `GossiperTest` / `EndpointStateTest` 覆盖。
- Shadow round 有 delayed ACK、bad ACK 和 assassinated self unit coverage；shutdown announce 有 mixed-mode serde 和 distributed token metadata coverage。
- Preferred IP reconnect 有 source baseline 和 authenticator-deny unit coverage；preferred IP reconnect distributed test 仍是 gap still open。
- `ReconnectableSnitchHelper.onJoin()` 当前没有 legacy `INTERNAL_IP` fallback，属于 documented source risk；checker 会在该行为变化时要求更新研究结论。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `gossip_digest_task_baseline` | `GossipTask` wait/listen、heartbeat、digest SYN、live/unreachable/seed/status check source contract。 |
| `gossip_stage_mutation_guard` | `Stage.GOSSIP` mutation guard 和 strict runtime checks behavior。 |
| `gossip_endpoint_state_merge` | generation/version merge、future generation rejection、major state change、same-generation incremental state apply。 |
| `gossip_application_state_wire_compat` | `ApplicationState` ordinal/padding/new-vs-legacy state wire contract。 |
| `gossip_status_notification_order` | `STATUS`/`STATUS_WITH_PORT` first notification and legacy status skip behavior。 |
| `gossip_legacy_state_filter` | `EndpointState` and `Gossiper.applyNewStates()` legacy field filtering. |
| `gossip_echo_mark_alive_dead` | ECHO_REQ gate before `realMarkAlive()` and subscriber `onAlive`/`onDead` notification. |
| `gossip_shadow_round_startup_gate` | shadow round empty SYN, startup safety check and all-seeds-in-shadow exit. |
| `gossip_shutdown_announce` | shutdown app-state publish, `GOSSIP_SHUTDOWN` message and mixed-mode serde/test coverage. |
| `gossip_preferred_ip_reconnect_baseline` | snitch internal address publish, reconnect auth/DC gates and onChange/onAlive fallback behavior. |
| `gossip_preferred_ip_distributed_gap` | Current absence of distributed preferred-IP reconnect coverage. |
| `gossip_reconnect_onjoin_legacy_gap` | Current duplicated `INTERNAL_ADDRESS_AND_PORT` lookup in `onJoin()` and missing legacy fallback. |
| `gossip_existing_tests_baseline` | Existing unit/distributed tests that anchor the matrix. |

## 设计目标

- Fail when gossip source contracts move without a research update.
- Fail when preferred-IP reconnect gains distributed coverage so the matrix stops calling it missing.
- Fail when the documented `onJoin()` legacy fallback risk is fixed or otherwise changed, forcing a doc update.
- Keep state merge coverage separate from messaging verb/TLS/frame coverage, which remains protected by `check-messaging-verb-matrix-drift.py`.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-gossip-state-preferred-ip-drift.py` | Source/test/gap drift checker. |
| `Gossiper` | Gossip task, state mutation guard, FD report, merge/notification, shadow round and shutdown announce. |
| `EndpointState` / `ApplicationState` / `VersionedValue` | Gossip state data model, wire compatibility and legacy filtering. |
| `GossipingPropertyFileSnitch` | Publishes internal address state and registers reconnect helper. |
| `ReconnectableSnitchHelper` | Converts gossip internal address updates into preferred IP reconnect attempts. |
| `GossiperTest` / `EndpointStateTest` / `ShadowRoundTest` / `GossipShutdownTest` / `GossipTest` | Current test anchors. |

## 运维关注点

- A green checker means the documented source/test/gap baseline still matches this checkout; it does not mean the preferred-IP distributed gap has been implemented.
- If a distributed preferred-IP reconnect test lands, replace `gossip_preferred_ip_distributed_gap` with covered scenario IDs and update the gap predicate.
- If `ReconnectableSnitchHelper.onJoin()` gains a legacy `INTERNAL_IP` fallback, update the onJoin() legacy fallback risk section and add/point to the new test.
- If `ApplicationState` wire enum changes, review mixed-version compatibility before only updating line anchors.

## 常见故障

- `source token contract ... Gossiper.java` fails: gossip round, merge, shadow round or shutdown source changed.
- `source token contract ... ReconnectableSnitchHelper.java` fails: preferred-IP reconnect gates or subscriber behavior changed.
- `onJoin legacy fallback risk changed` fails: the documented duplicated lookup/missing fallback changed and the research needs refresh.
- `gap still open ...` fails: a distributed preferred-IP reconnect test probably landed and the gap is no longer accurate.
- `doc token ...` fails: scenario IDs, source paths, test anchors or explicit gap language disappeared from docs/indexes.

## 运行方式

- `python3 research/tools/check-gossip-state-preferred-ip-drift.py`
- `python3 research/tools/check-gossip-state-preferred-ip-drift.py --json`
- Related validation: `python3 -m py_compile research/tools/check-gossip-state-preferred-ip-drift.py`
