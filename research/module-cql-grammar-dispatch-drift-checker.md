# CQL Grammar Dispatch Drift Checker

## 范围

`research/tools/check-cql-grammar-dispatch-drift.py` 是 source-only drift check，用来保护 `research/module-cql-grammar-dispatch-exhaustiveness-matrix.md`。

它不运行 ANTLR、不生成 `CqlParser.java`，也不证明 Java exhaustiveness test 已存在。它只做五件事：

- 校验 `build.xml` 的 `check-gen-cql3-grammar` / `gen-cql3-grammar` target 仍以 `src/antlr/*.g` 和 `src/antlr/Cql.g` 为生成入口。
- 解析 `Parser.g` 的 `cqlStatement` dispatch block，确认 43 个 dispatch entries 的名称、顺序和唯一性。
- 确认每个 dispatch entry 在 `Parser.g` 中有对应 rule definition，并记录 return type 边界。
- 校验现有测试 baseline：`CqlParserTest`、`KeywordTestBase`、`ReservedKeywordsTest` 和 auth identity CQL tests 仍存在。
- 扫描 tests 中是否出现真正的 dispatch exhaustiveness marker；如果出现，说明 `cql_dispatch_exhaustiveness_test_gap` 已变化，必须更新矩阵。

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `cql_grammar_generation_target_contract` | `build.xml` grammar generation target |
| `cql_grammar_source_include_contract` | `src/antlr/*.g` up-to-date source set and `Cql.g` imports |
| `cql_grammar_generated_artifact_boundary` | generated parser artifacts are not tracked source |
| `cql_dispatch_parser_rule_contract` | `cqlStatement` 43-entry dispatch baseline |
| `cql_dispatch_rule_definition_contract` | every dispatch entry has a rule definition |
| `cql_dispatch_raw_return_contract` | dispatch return types remain raw/concrete statement boundary |
| `cql_dispatch_bind_marker_after_contract` | common `stmt.setBindVariables(bindVariables)` hook |
| `cql_dispatch_keyword_token_contract` | keyword token tests are not dispatch exhaustiveness tests |
| `cql_dispatch_statement_family_test_baseline` | scattered statement-family tests remain present |
| `cql_dispatch_raw_prepare_checker_boundary` | boundary with existing raw prepare checker |
| `cql_dispatch_exhaustiveness_test_gap` | current lack of Java exhaustiveness matrix test |

## 运行方式

```bash
python3 research/tools/check-cql-grammar-dispatch-drift.py
python3 research/tools/check-cql-grammar-dispatch-drift.py --json
```

成功时输出 dispatch entries、rule definitions、source/test/doc/gap 检查数量。失败时列出缺失 token、dispatch mismatch、缺失 rule definition 或新增 exhaustiveness test candidate。

## 更新规则

- 如果 `Parser.g` 的 `cqlStatement` dispatch 改变，先更新 matrix 的 baseline，再调整 checker 的 expected list。
- 如果新增真正的 Java exhaustiveness test，不要只放过 gap scan；应把 `cql_dispatch_exhaustiveness_test_gap` 改为测试覆盖项，并写明测试文件和 sample 生成/维护方式。
- 如果 generated `CqlParser.java` / `CqlLexer.java` 被提交到仓库，新增 generated artifact consistency 检查，不能继续只依赖 grammar source。
