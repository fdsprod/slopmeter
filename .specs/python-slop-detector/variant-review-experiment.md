# Experimental missing-variant review

> Release status: the implemented features described here shipped in [v0.4.0](https://github.com/fdsprod/slopmeter/releases/tag/v0.4.0). Hosted CI passed. Validation counts and pre-release status statements below describe the original checkpoint.

## Thin slice

Question: can source-only review connect locally declared finite variants to an
explicit typed match handler without changing calibrated metrics?

`slop variants --root . [--config FILE] [--lang py] [--strict] [--json]` reuses
source inventory and emits a separate report. No source executes. No new M2 rule,
threshold, or scoring weight. Directory sources only. Existing models command is
unchanged. Native syntax analysis is limited to a finite local vocabulary; it is
not a replacement for type checker exhaustiveness diagnostics.

Scope: top-level local Enum/IntEnum/StrEnum declarations with directly imported
base names (import aliases allowed), and named Literal aliases with directly
imported Literal (aliases allowed). Accept simple string/integer enum values with
no aliases, or all zero-argument enum auto() members. Reject mixed auto/literal,
aliases, custom enum behavior/inheritance, ambiguous names and dynamic values.
Literal aliases support string/integer constants; duplicate/equality-colliding
values and other forms remain unresolved. Plain assignment, TypeAlias-annotated
assignment and non-generic PEP695 type statements can declare named Literal aliases.

Handlers are undecorated top-level functions with a fixed parameter typed as a
bare local declaration name (quoted bare names allowed). Only a first statement
match after an optional docstring is supported. The subject must be that parameter.
Reassigned/aliased subjects, type shadowing, uncertain bindings, nested handlers,
unsupported patterns, cross-file types, or additional control-flow are unresolved.
Do not execute annotations, imports, default expressions or enum constructors.

Patterns: explicit Enum.Member or supported literal values, OR patterns, and
capture/wildcard catch-alls. Guarded branches are conditional, including guarded
wildcards; they do not establish full coverage. Matching compares known cases,
not body semantics. An unguarded catch-all covers remaining cases but does not
establish whether that fallback is intentional or correct. Complete explicit case
coverage is exhaustive. No inference of correctness from exhaustive syntax.

## Contract

New domain.variant_review frozen extra-forbid types:
- VariantCase(name, span), VariantDeclaration(name, kind=enum|literal, span,
  cases nonempty unique names).
- ExplicitVariantBranch(kind=cases, span, cases nonempty unique strings,
  conditional bool=false), FallbackVariantBranch(kind=fallback, span,
  conditional bool=false), union VariantBranch tagged by kind.
- AnalyzedVariantHandler(state=analyzed, symbol, subject, span, declaration,
  branches). Branch cases must belong to the declaration and spans to the match.
  Computed not_explicitly_covered lists declared names not covered by unconditional
  explicit branches in declaration order. Computed coverage is exhaustive if that
  list is empty, otherwise fallback if an unconditional fallback exists, else
  missing. Imported computed fields must match derivation. A fallback record is
  distinct from an explicit branch, so empty cases cannot falsely prove coverage.
- UnresolvedVariantHandler(state=unresolved, symbol, subject, span, reason).
  One record per match, with match span and function symbol. Unknown subjects and
  bindings have an explicit reason. Do not silently omit unsupported matches.
- AnalyzedVariantFile(state=analyzed,path,cohort,source_sha256,handlers default()).
- FailedVariantFile(state=failed,path,cohort,optional source_sha256,diagnostic).
- VariantReviewReport(schema_version=1,experiment=py-variant-review-1,tool_version,
  source DirectorySourceIdentity,config,files,inventory_coverage,diagnostics,
  excluded_directories,interpretation). No score. One outcome per selected file.

Names for enum cases are `Type.MEMBER`; Literal cases use Python repr of their
constant value. Declaration/branch/handler locations are source spans in the
containing file. Report uncertainty without claiming a missing case is a defect.

Detector API languages.python.variant_review.analyze_variants(SourceDocument).
Application API application.variants.inspect_variants(SnapshotRequest).

## Validation

Independent paired tests precede implementation. Include omitted enum/literal
case, exhaustive handling, OR cases, guarded explicit cases, unconditional and
guarded catch-alls, intentional partial handler wording, aliases, shadowing,
parameter reassignment, nested matches, unknown patterns and parse failures.
Validate external config/Git ignores, no target execution, full source locations,
JSON integrity and ordinary scoring stability. Run on this repository and seeded
fixtures. Independent holdouts remain necessary before any calibration.


## Completed validation

Coverage is derived from declaration and branch evidence, rather than stored as an
independent decision. Guarded cases remain distinct from unconditional branches.
The `not_explicitly_covered` name avoids claiming a case is unhandled when a
catch-all covers it. Imported projections must agree with their evidence.

- 1,424 deterministic tests passed on Windows Python 3.12, with 95.46 percent
  branch-inclusive coverage. All four wheel/source installation checks passed.
- All 47 new detector/domain/CLI cases passed on Python 3.13 and 3.14. Ruff,
  formatting, Pyright and all five import contracts passed.
- The installed wheel also ran `variants` successfully on the seeded example.
- Paired tests include guarded/wildcard/OR cases, all three Literal alias forms,
  Enum/IntEnum/StrEnum and import aliases, ambiguous/default/annotation bindings,
  capture and variadic shadowing, invalid or aliased values, conditional/nested/
  late matches, unsupported patterns, failures, source selection and no execution.
- Seeded CLI output: two missing-case notes (Enum and Literal), one fallback note,
  and one explicitly exhaustive handler. All related locations were retained.
- This repository: 176 selected Python files, one intentional parse-error fixture,
  and two unresolved matches outside the supported scope. No assessed missing,
  fallback, or exhaustive handlers. This supplies no real-repository recall claim.
- Official v0.3.0 and updated ordinary score JSON are exactly equal on the same
  working tree. The preceding experimental build and current `models` JSON also
  match exactly. No scoring resources, thresholds, or rules changed.
- Local evidence: `.tmp/variants-confirmation/` contains source-bound self and
  seeded reports, terminal views, both scoring reports and both model reports.
  No private external evaluation material was copied or published.

These changes are committed locally. They are not in the published v0.3.0 release.
Independent labeled repositories are still required before estimating precision,
recall or score calibration for this experiment.
