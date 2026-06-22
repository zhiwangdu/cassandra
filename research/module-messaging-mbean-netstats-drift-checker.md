# Messaging MBean Netstats Drift Checker

`research/tools/check-messaging-mbean-netstats-drift.py` protects the MessagingService JMX/nodetool observability matrix from source/doc drift. It is source-only: it parses `MessagingServiceMBean.java`, checks implementation and nodetool source tokens, verifies relevant test anchors, and confirms README/source-map coverage.

## What It Checks

| Area | Checks |
| --- | --- |
| Interface | `MessagingServiceMBean` still has 27 methods in the documented order and 13 deprecated compatibility methods. |
| Implementation | `MessagingServiceMBeanImpl` still registers `org.apache.cassandra.net:type=MessagingService`, maps large/small/urgent pool counters, reports dropped/timeout metrics, keeps removed backpressure semantics, routes TLS reload to `SSLFactory.forceCheckCertFiles()`, and reads endpoint messaging versions. |
| NodeProbe | `NodeProbe.connect()` still creates the `MessagingServiceMBean` proxy; `getDroppedMessages()`、`reloadSslCerts()`、`getMessagingServiceProxy()` still route through `msProxy`. |
| Netstats | `nodetool netstats` still uses the 9 with-port pool counter methods and prints `Large messages`、`Small messages`、`Gossip messages`. |
| Tests | `NetStatsTest`、`GossipSettlesTest` and `JMXGetterCheckTest` keep the help/output, with-port compatibility and removed backpressure runtime anchors. |
| Docs | Matrix, README, source-map and messaging verb docs mention scenario IDs, method count, paths and checker command. |

## Run

```bash
python3 research/tools/check-messaging-mbean-netstats-drift.py
```

Expected output:

```text
OK messaging MBean/netstats checks passed (27 methods, 9 scenarios)
```

Use JSON output for inventory or CI wiring:

```bash
python3 research/tools/check-messaging-mbean-netstats-drift.py --json
```

## Scenario IDs

- `messaging_mbean_method_baseline`
- `messaging_mbean_registration_contract`
- `messaging_mbean_pool_counter_mapping`
- `messaging_mbean_timeout_drop_contract`
- `messaging_mbean_backpressure_removed_contract`
- `messaging_mbean_nodeprobe_routes`
- `messaging_netstats_pool_aggregation_contract`
- `messaging_mbean_with_port_compatibility_test`
- `messaging_mbean_tls_reload_route`

## Maintenance

- If `MessagingServiceMBean` adds/removes/renames a method, update `EXPECTED_MBEAN_METHODS`, the matrix method table and any JMX compatibility notes together.
- If `NetStats` starts printing per-peer rows, different pools or timeout/dropped fields, update the netstats scenario instead of only adding tokens.
- If backpressure support returns, replace the removed-feature contract and update `JMXGetterCheckTest` assumptions.
- If `reloadSslCertificates` gains a focused NodeProbe/JMX test, cite it here and in the native TLS reload matrix.
