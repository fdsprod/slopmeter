# Experimental coverage and unresolved explanations

> [!IMPORTANT]
> This change explains the existing detection scope. It does not widen eligibility,
> change findings or scores, or infer correctness from an empty result.

## Data shape

Each experimental report exposes a computed `summary`. The detailed file and
subject outcomes remain authoritative. Old reports without a summary still load;
an imported summary must agree with those outcomes. A frozen summary projection
prevents consumers from maintaining a second set of counters.

| Field | Meaning |
|---|---|
| `unit` | `class-declarations`, `match-handlers`, or `functions` |
| `files_analyzed`, `files_failed` | File outcomes, separate from subject eligibility |
| `encountered` | Assessed plus unresolved subjects in successfully parsed files |
| `assessed`, `unresolved` | Subject outcomes within the experiment's supported scope |
| `findings` | Model/derived candidates, or missing/fallback variant handlers |
| `unresolved_reasons` | Sorted reason/count groups from unresolved subjects |

All class declarations count, including ordinary classes and test fakes. These
counts do not identify business models or estimate recall. Failed files have no
inferred subject count. An exhaustive variant handler is assessed but is not a
missing/fallback finding; its branch bodies can still be incorrect.

## Slice 1: Coverage from evidence to CLI

**Question:** Can each experimental command show what it actually assessed before
showing findings, while retaining report loading and saved review compatibility?

**Layers:** Existing report evidence → computed summary → terminal and JSON.

**Budget:** One shared summary projection and formatter, three report properties,
and the three experimental renderers. No adapter or scoring changes.

**Validation:** Mixed assessed/unresolved/failed inputs reconcile; no assessed
subjects says `Nothing assessed`; assessed negatives have different wording;
grouped reasons agree with detailed results; old and new JSON load; forged
summaries fail validation; saved targets retain their identities.

## Slice 2: Explain unresolved variant handlers

**Question:** Can a reviewer distinguish unsupported scope, signature, match
placement, subject shape, annotation, binding, declaration, and pattern without
changing which handlers are accepted?

**Layers:** Existing AST/binding checks → unresolved reason → JSON and terminal.

**Budget:** The variant adapter's rejection paths and tests. Retain the current
reason string and experiment identity. Do not infer imported declarations or
introduce cross-file analysis.

**Validation:** Independent paired fixtures distinguish rejection causes and keep
supported missing/fallback/exhaustive outcomes. Same-source comparisons retain
all facts except reason text and the additive report summary.

## Boundaries

Pydantic, cross-file contracts, non-leading handlers, calibration expansion, and
new scoring rules remain separate research work. Existing review ledger features
already provide attribution, history, and relevant clone-boundary dependencies.
Whole-file comment edits still invalidate source-bound reviews.

## Implementation and validation: 2026-09-21

Coverage shipped locally in `819f46c`, after independent failing-test commits
`5d509c0` and `c3c9116`. Variant explanations shipped locally in `c3bc55c`, after
independent failing-test commit `f5a30fc`. No release or push is part of this task.

- Full Python 3.12 suite: **1,574 passed**, four installation cases run separately;
  branch-inclusive coverage **95.20 percent**.
- Wheel and source distribution built; all four clean installation checks passed.
- All 69 new cases passed on both Python 3.13 and Python 3.14.
- Ruff lint/format, Pyright, and all five import contracts passed.
- An independent source review found no eligibility or review-identity changes.
- A detector comparison across 275 documents retained the same variant outcomes
  and evidence, excluding unresolved reason text.

Both baseline commit `7c73cf2` and the updated implementation scanned the same
final working tree. Ordinary score JSON matched exactly. Model and derived
reports matched after removing only the new summary. Variant reports matched
after also removing unresolved-handler reason text. Successful evidence, source
hashes, configuration, failures, and experiment identities stayed unchanged.
Raw reports and comparisons are under `.tmp/coverage-feedback-20260921/`.

The final self-scan selected 193 Python files: 192 parsed, and the intentional
malformed fixture failed. Failed files contribute no inferred subject counts.

| Experiment | Encountered | Assessed | Unresolved | Findings |
|---|---:|---:|---:|---:|
| Models: class declarations | 223 | 0 | 223 | 0 |
| Variants: match handlers | 3 | 0 | 3 | 0 |
| Derived: functions | 1,511 | 2 | 1,509 | 0 |

These results demonstrate the coverage limit, not source correctness. The three
variant reasons are now a non-leading match, an unsupported `ast.AST` annotation,
and no supported local declaration for `ScoreTransform`.

### Review of new self-scan hotspots

All three new summary properties have CC11. Independent source review retained
each with **no change**. Their comprehensions and filters produce a valid CC
measurement; the threshold crossing does not establish a defect.

| Property | SLOC | Rationale |
|---|---:|---|
| `ModelReviewReport.summary` | 10 | Counts assessed classes, individual findings, and unresolved reasons from owned outcomes |
| `VariantReviewReport.summary` | 16 | Counts missing/fallback handlers as findings and excludes exhaustive handlers |
| `DerivedReviewReport.summary` | 14 | Counts individual traces, which can exceed the number of affected functions |

The properties use several linear passes and intermediate lists. No performance
problem was established. Future subject states or coverage categories require
reviewing these projections. No code or evaluator change is justified solely to
reduce their CC. The prior `_handler_type` hotspot was split to carry distinct
rejection reasons; its reduced per-function CC is not a measured quality gain.
