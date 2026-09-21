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
