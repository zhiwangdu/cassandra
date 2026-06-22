# CQL Grammar Dispatch Exhaustiveness Matrix

## 研究目标

`research/module-cql-parser-raw-prepare-matrix.md` 已经覆盖 CQL 文本从 `Cql.g` root rule 到 raw prepare 的主链路。本矩阵进一步收紧 grammar generation 与 `Parser.g` `cqlStatement` dispatch 的 exhaustiveness 边界：当前仓库不提交 generated `CqlParser.java` / `CqlLexer.java`，`build.xml` 在构建时从 `src/antlr/*.g` 生成 parser，因此 source-only 研究必须直接解析 grammar，并把“缺少生成后 dispatch exhaustiveness Java test”显式保留为缺口。

## 场景矩阵

| 场景 ID | 保护内容 | 源码/测试锚点 | 风险 |
|---|---|---|---|
| `cql_grammar_generation_target_contract` | `build.xml` 的 `gen-cql3-grammar` 用 ANTLR 3.5.2 从 `src/antlr/Cql.g` 生成到 `build.src.gen-java` | `build.xml:434-459`、`.build/build-resolver.xml:130-132` | 构建生成入口改变后，grammar drift checker 可能只看源码而漏掉生成方式 |
| `cql_grammar_source_include_contract` | `check-gen-cql3-grammar` 用 `src/antlr/*.g` 判断 `Cql.tokens` 是否 up-to-date，`Cql.g` 明确 `import Parser,Lexer` | `build.xml:437-443`、`src/antlr/Cql.g:20-27` | 修改 `Lexer.g` / `Parser.g` 应触发重新生成；遗漏会导致旧 parser 进入测试 |
| `cql_grammar_generated_artifact_boundary` | 当前 checkout 没有 tracked generated `CqlParser.java` / `CqlLexer.java`，研究与 CI 应以 grammar source 和 build target 为准 | `rg --files` 当前只返回 `src/antlr/*.g` | 如果 generated source 被提交，需要新增 generated-vs-grammar diff gate |
| `cql_dispatch_parser_rule_contract` | `Parser.g` `cqlStatement` 当前有 43 个 dispatch entries，顺序和名称是 CQL statement surface 的 source of truth | `src/antlr/Parser.g:207-252` | 新增 CQL statement 若只加 grammar 不更新矩阵，会绕过研究索引 |
| `cql_dispatch_rule_definition_contract` | 每个 dispatch entry 必须在 `Parser.g` 有对应 `rule returns [...]` 定义 | `src/antlr/Parser.g:257`、`src/antlr/Parser.g:267`、`src/antlr/Parser.g:485`、`src/antlr/Parser.g:1251` | dispatch 名称重命名或残留会造成生成失败或未覆盖语义漂移 |
| `cql_dispatch_raw_return_contract` | dispatch entries 返回 `CQLStatement.Raw` 子类或 concrete statement；schema-aware validation 仍在 prepare/statement class 中 | `src/antlr/Parser.g:267`、`src/antlr/Parser.g:485`、`src/antlr/Parser.g:640`、`src/antlr/Parser.g:1072` | 返回 executable statement 与 raw statement 边界混淆会影响 prepare/cache/permission 语义 |
| `cql_dispatch_bind_marker_after_contract` | `@after` 对非 null `stmt` 调用 `stmt.setBindVariables(bindVariables)`，保证每个 dispatch branch 统一绑定 marker list | `src/antlr/Parser.g:207-209`、`src/java/org/apache/cassandra/cql3/CQLStatement.java:99-114` | 新 branch 若绕过 `@after` 或返回 null，会破坏 prepared metadata |
| `cql_dispatch_keyword_token_contract` | `Lexer.g` keyword surface 和 `KeywordTestBase` 的 generated tokenNames 扫描只覆盖 token/keyword，不覆盖 statement dispatch exhaustiveness | `src/antlr/Lexer.g:60-125`、`test/unit/org/apache/cassandra/cql3/KeywordTestBase.java:40-85` | keyword test 绿不能证明新 statement rule 有 parser-level regression coverage |
| `cql_dispatch_statement_family_test_baseline` | 现有 tests 覆盖 listener、reserved keywords、selected operations/schema/auth/MV/identity flows，但不是 43-entry dispatch matrix | `test/unit/org/apache/cassandra/cql3/CqlParserTest.java:34-86`、`test/unit/org/apache/cassandra/cql3/ReservedKeywordsTest.java:28-42`、`test/unit/org/apache/cassandra/auth/GrantAndRevokeTest.java:499-560` | 分散测试可以漏掉新 grammar branch 的最小 parse sample |
| `cql_dispatch_raw_prepare_checker_boundary` | `check-cql-parser-raw-prepare-drift.py` 已保护 raw prepare 与 43-entry list；本 checker 专注 generation target、rule definitions 和 exhaustiveness gap | `research/tools/check-cql-parser-raw-prepare-drift.py:28-72` | 两个 checker 职责混淆会让 raw prepare 变化和 generated-test 缺口互相遮蔽 |
| `cql_dispatch_exhaustiveness_test_gap` | 当前没有 Java test 从 `Parser.g` 派生/枚举 43 个 `cqlStatement` dispatch entries 并对每个 entry 绑定 parse sample | `research/tools/check-cql-grammar-dispatch-drift.py` gap scan | 新增 statement family 时，只有 source checker 会提醒更新矩阵，JUnit 不会自动要求样例 |

## Dispatch Baseline

`cql_dispatch_parser_rule_contract` 当前保护 43 个 dispatch entries：

```text
selectStatement
insertStatement
updateStatement
batchStatement
deleteStatement
useStatement
truncateStatement
createKeyspaceStatement
createTableStatement
createIndexStatement
dropKeyspaceStatement
dropTableStatement
dropIndexStatement
alterTableStatement
alterKeyspaceStatement
grantPermissionsStatement
revokePermissionsStatement
listPermissionsStatement
createUserStatement
alterUserStatement
dropUserStatement
listUsersStatement
createTriggerStatement
dropTriggerStatement
createTypeStatement
alterTypeStatement
dropTypeStatement
createFunctionStatement
dropFunctionStatement
createAggregateStatement
dropAggregateStatement
createRoleStatement
alterRoleStatement
dropRoleStatement
listRolesStatement
grantRoleStatement
revokeRoleStatement
createMaterializedViewStatement
dropMaterializedViewStatement
alterMaterializedViewStatement
describeStatement
addIdentityStatement
dropIdentityStatement
```

## 调用图

```text
build/test target
  -> check-gen-cql3-grammar
     -> targetfile build.src.gen-java/.../Cql.tokens
     -> srcfiles src/antlr/*.g
  -> gen-cql3-grammar
     -> org.antlr.Tool
        -> src/antlr/Cql.g
           -> import Parser,Lexer
           -> query -> cqlStatement (';')* EOF
        -> generated CqlParser / CqlLexer under build.src.gen-java

runtime parse
  -> CQLFragmentParser.parseAnyUnhandled(CqlParser::query, query)
     -> generated CqlParser.query()
        -> Parser.g cqlStatement
           -> exactly one of 43 dispatch entries
           -> @after stmt.setBindVariables(bindVariables)
     -> raw.prepare(clientState)
```

## 设计取舍

- Generated parser is build output, not source-of-record in this checkout; source research must inspect `src/antlr/*.g` and `build.xml`.
- `Parser.g` keeps statement dispatch explicit instead of dynamic registration, which makes drift checking possible.
- `KeywordTestBase` is generated-token aware, but statement coverage is still scattered across operation/schema/auth tests.
- A future exhaustiveness JUnit should map every dispatch entry to a minimal valid/invalid parse sample, plus expected raw statement class or parse failure boundary.

## 运维与开发关注点

- Adding a CQL keyword in `Lexer.g` may require cqlsh keyword sync and keyword tests, but it does not automatically update `cqlStatement`.
- Adding a new statement requires at least four edits: lexer/parser grammar, raw/statement implementation, parser/prepare tests, and research/checker baseline.
- Generated parser failures usually surface during `gen-cql3-grammar` or Java compilation, not at runtime.
- If generated parser artifacts become tracked, add a generated-vs-grammar checksum or method-presence check before treating source-only evidence as complete.

## 测试覆盖与缺口

- `CqlParserTest` covers parser error listener behavior and duplicate property parsing helpers, but does not enumerate statement branches.
- `KeywordTestBase` derives keyword rows from `CqlParser.tokenNames`, which proves generated token visibility but not dispatch samples.
- `ReservedKeywordsTest` checks reserved keywords in an `ALTER TABLE ... ADD` context.
- Auth identity CQL (`ADD IDENTITY` / `DROP IDENTITY`) is covered through auth tests such as `GrantAndRevokeTest`, but those are semantic permission flows rather than grammar exhaustiveness tests.
- 当前缺口：没有 generated grammar dispatch exhaustiveness Java test。新增该 test 后，应把 `cql_dispatch_exhaustiveness_test_gap` 改为具体覆盖项，并记录 sample source、expected raw class 和失败模式。
