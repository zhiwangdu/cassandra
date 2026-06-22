# Module: CQL Parser Raw Prepare Drift Checker

## 范围

`research/tools/check-cql-parser-raw-prepare-drift.py` 是 source-only drift check，用来保护 CQL parser/raw prepare matrix 的源码覆盖。它验证 `Cql.g` root query rule、`Parser.g` statement dispatch 和 bind marker collection、`CQLFragmentParser`/`ErrorCollector` wrapper、`QueryProcessor.parseStatement()`/`parseAndPrepare()`、SELECT/Modification/BATCH raw prepare、测试锚点和 generated dispatch exhaustiveness gap。

当前基线：

- `Cql.g` root `query` rule parses one `cqlStatement`, optional semicolons and EOF.
- `Parser.g` `cqlStatement` dispatch has 43 statement entries.
- Parser collects positional, named, IN, tuple, tuple-IN and JSON bind markers before raw prepare.
- `QueryProcessor.parseAndPrepare()` sets qualified keyspace, runs `raw.prepare()`, validates and optionally measures prepared size.
- Existing tests cover listener behavior, duplicate properties, custom expression marker boundary and PREPARE codec keyspace, but not generated dispatch exhaustiveness.

## 覆盖场景

| 场景 ID | 保护内容 |
|---|---|
| `cql_parser_wrapper_error_collection` | Parser wrapper, lexer/parser listeners and `ErrorCollector.throwFirstSyntaxError()`. |
| `cql_parser_root_query_contract` | `Cql.g` query root with optional semicolons and EOF. |
| `cql_parser_statement_dispatch` | `Parser.g` 43-entry `cqlStatement` dispatch baseline. |
| `cql_parser_bind_marker_collection` | Bind marker creation and `stmt.setBindVariables(bindVariables)`. |
| `cql_parser_raw_prepare_boundary` | Raw parse output versus schema-aware prepare/validate boundary. |
| `cql_parser_select_prepare_planner_boundary` | SELECT raw prepare restrictions/selection/order/filter/limit boundary. |
| `cql_parser_modification_batch_prepare` | Modification and batch raw prepare marker/condition/attribute boundary. |
| `cql_parser_keyword_identity_contract` | Lexer identity keywords and ADD/DROP IDENTITY grammar dispatch. |
| `cql_parser_test_coverage_surface` | Test anchors and explicit generated dispatch coverage gap. |

## 设计目标

- Fail when grammar dispatch changes without updating research coverage.
- Fail when parse/raw prepare boundaries drift from the documented lifecycle.
- Keep README/source-map/matrix/checker docs synchronized.
- Preserve a visible generated dispatch test gap until explicit grammar coverage exists.

## 核心类

| 类/脚本 | 作用 |
|---|---|
| `research/tools/check-cql-parser-raw-prepare-drift.py` | Parses `Parser.g` dispatch and validates source/doc/test contracts. |
| `Cql.g` / `Parser.g` / `Lexer.g` | ANTLR root rule, statement grammar and token surface. |
| `CQLFragmentParser` / `ErrorCollector` | Parser wrapper and syntax error collection. |
| `QueryProcessor` | Parse, raw prepare, keyspace set and validation boundary. |
| `CQLStatement.Raw` / `VariableSpecifications` / `AbstractMarker` | Raw statement and bind marker contracts. |
| `SelectStatement.RawStatement` / `ModificationStatement.Parsed` / `BatchStatement.Parsed` | Main raw prepare targets. |

## 核心接口

- `parser_dispatch_entries()`：parses `Parser.g` `cqlStatement` dispatch entries.
- `source_checks()`：checks source token contracts and dispatch baseline.
- `doc_checks()`：checks matrix/checker/README/source-map coverage.
- `test_gap_checks()`：keeps generated dispatch test gap explicit.
- `check()`：returns JSON-friendly results and pass/fail status.

## 生命周期

```text
developer changes CQL grammar or raw prepare code
  -> run python3 research/tools/check-cql-parser-raw-prepare-drift.py
  -> checker validates grammar/root/dispatch/bind marker/source/test baseline
  -> checker validates matrix, drift doc, README and source-map references
  -> update grammar tests, matrix, checker baseline, and indexes together
```

## 运维关注点

- This checker does not regenerate ANTLR output or run CQL tests; it protects source-visible contracts.
- If a new CQL statement is added, update `EXPECTED_DISPATCH_RULES`, matrix grouping and tests together.
- If generated parser exhaustiveness tests are added, update the gap check instead of deleting the scenario.

## 常见故障

- `Parser.g dispatch entries` fails: the CQL statement surface changed.
- `source token ...` fails: parse/raw prepare behavior moved or changed.
- `doc token ...` fails: research docs or indexes missed a new source/test anchor.
- `generated dispatch gap remains explicit` fails: tests now mention dispatch exhaustiveness; update the documented coverage state.

## 测试用例

- `python3 research/tools/check-cql-parser-raw-prepare-drift.py`。
- `python3 research/tools/check-cql-parser-raw-prepare-drift.py --json`。
- Related test anchors: `test/unit/org/apache/cassandra/cql3/CqlParserTest.java`、`test/unit/org/apache/cassandra/cql3/PreparedStatementsTest.java`、`test/unit/org/apache/cassandra/transport/messages/PrepareMessageTest.java`。
