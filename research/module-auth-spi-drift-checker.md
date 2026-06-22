# Module: Auth SPI Drift Checker

## 范围

本模块记录 `research/tools/check-auth-spi-drift.py` 的用途、输入和维护方式。它把 Cassandra auth 扩展接口的源码 method surface 与 `research/module-auth-spi-compatibility-matrix.md` 对齐，覆盖 custom authenticator、authorizer、role manager、network authorizer、CIDR authorizer 和 `AuthConfig` 启动 gate。

## 设计目标

- 在不编译 Cassandra 的前提下解析 auth SPI interfaces，发现接口新增/删除方法后文档未更新的 drift。
- 用 `name/arity` 区分 overloaded methods，例如 `newSaslNegotiator/1` 和 `newSaslNegotiator/2`。
- 同时检查 `Config` 中 backend `ParameterizedClass` keys 和 `AuthConfig.applyAuth()` 的 dependency gate 字符串，避免只覆盖接口而漏掉启动兼容条件。
- 让 Auth/Permission 模块的 custom backend 兼容矩阵有可运行的 source-only gate。

## 核心数据结构

| 数据结构 | 字段 |
|---|---|
| `InterfaceSpec` | `source`、`interface`、`scenario_id`、`expected_methods` |
| `CONFIG_KEYS` | `authenticator`、`authorizer`、`role_manager`、`network_authorizer`、`cidr_authorizer`、`internode_authenticator` |
| `AUTH_CONFIG_CONTRACTS` | credential cache warning、authentication-required gates、PasswordAuthenticator/CassandraRoleManager gate |

## 调用链

```text
main()
  -> check()
     -> read_docs()
     -> extract_methods(source, interface)
        -> strip_comments()
        -> interface_body()
        -> line-level method declaration parse
     -> config_fields()
     -> AuthConfig source substring checks
     -> documented(method/scenario, docs_text)
  -> print OK/MISMATCH per interface and config contract
```

## 覆盖场景

- `auth_spi_i_authenticator`
- `auth_spi_i_authenticator_sasl_negotiator`
- `auth_spi_i_authorizer`
- `auth_spi_i_role_manager`
- `auth_spi_i_network_authorizer`
- `auth_spi_i_cidr_authorizer`
- `auth_spi_backend_config_keys`
- `auth_spi_auth_config_dependency_gates`

## 命令

```bash
python3 research/tools/check-auth-spi-drift.py
python3 research/tools/check-auth-spi-drift.py --json
```

返回 0 表示 interface method list、backend config key 和 AuthConfig gate 均与文档同步；返回 1 表示源码或文档 drift；返回 2 表示解析/文件错误。

## 运维关注点

- 如果 auth SPI 增加 method，先确认 custom backend 是否必须实现；若是 default method，也要在矩阵中标明兼容语义。
- 如果 `AuthConfig` gate 文案改动但语义未变，应更新 checker 的 source fragment 和文档描述。
- checker 只校验 method name/arity，不校验参数类型、throws 或 return type；若后续 SPI 改动频繁，应扩展到 signature-level comparison。

## 测试用例

- `python3 research/tools/check-auth-spi-drift.py`：本地 source-only drift check，当前应返回 0。
- `python3 research/tools/check-auth-spi-drift.py --json`：输出每个 interface 的 parsed/expected methods 和缺失文档项。
