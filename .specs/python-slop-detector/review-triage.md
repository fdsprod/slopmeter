# Review scope, selection, and legacy supersession

> [!IMPORTANT]
> Decisions remain source-bound judgments. These changes do not change analysis,
> scores, eligibility, or the meaning of a saved report as a snapshot.

## States and authority

| Selected report | Supported review families |
|---|---|
| Score or comparison | Clone, complexity, pattern, using current-side evidence |
| Models | Model |
| Variants | Variant |
| Derived | Derived |

Support follows the report type, not whether it contains any targets. An empty
score report can still establish that clone evidence is absent or unavailable.
A derived report cannot make that assessment about clones.

| Resolution | Meaning |
|---|---|
| `current` | Exact evidence and analysis anchor match |
| `stale` | Compatible candidates exist but their anchor changed or is unavailable |
| `missing` | The selected family has no compatible evidence; not proof of a fix |
| `not-in-selected-report` | This report cannot assess the review family |
| `superseded` (legacy only) | An explicit event links this legacy decision to a replacement history |

Resolution output uses schema 3 for the extended state union. Ledger storage
remains schema 2. Legacy score annotations and schema-1 stores retain their
original state models. The new resolution is a projection and never rewrites a
ledger during a read.

An optional `supersedes_legacy_id` belongs to the attributed replacement event.
It is omitted when absent. This keeps one source of truth for the relationship
and records its actor/time with the judgment. The ledger validates the legacy ID,
clone family, language, cohort, and member paths. A legacy decision can belong to
only one replacement history; no path-based or fingerprint-based automatic link
is created. Source evidence may change because the event is an explicit re-review.

## Slice 1: Report-family applicability

**Question:** Can mixed-family ledgers distinguish unsupported report families
from absent evidence, in both terminal and JSON?

**Scope:** Tagged resolution states, resolver, and terminal. Cover native events
and preserved legacy clone decisions. Keep available-family missing/stale/current
behavior intact, including failed analysis.

**Validation:** Six families against all four report types, empty reports,
legacy decisions, JSON roundtrip, and unchanged stored bytes.

## Slice 2: Reviewable evidence filters

**Question:** Can a reviewer select evidence without confusing catalog size with
the number of flagged findings?

**Scope:** `review-report list --kind KIND` (repeatable), `--cohort production|test`,
and `--hotspots-only`. Kinds are ORed, then combined with the cohort. Hotspots
select callable complexity only, using the saved M4 version and threshold.
Unsupported reports or unknown M4 versions fail explicitly. Default listings
retain every callable and analyzed variant handler, including exhaustive cases.

**Validation:** Stable IDs, combined filters, strict threshold crossing,
assertion-aware M4 v3 tests, historical v1/v2 full complexity, unknown versions,
current-side comparisons, and unchanged source/report/store bytes.

## Slice 3: Explicit legacy supersession

**Question:** Can a reviewer retire a duplicate legacy queue item without erasing
history or implying the replacement is still current?

**Scope:** `review-report set --supersedes LEGACY_ID`, persisted event linkage,
ledger validation, and a legacy `superseded` projection with replacement history
ID and the original linking sequence. Later replacement events preserve the link.
The replacement resolves independently as current, stale, missing, or outside the
selected report family. Legacy data remains intact.

**Validation:** Explicit versus absent link, later updates, stale replacements,
wrong-family/path/unknown-ID rejection, conflicting replacement histories,
atomic failures, and no read-time migration.

## Slice 4: Legacy command guidance

**Question:** Does a schema-2 store passed to a legacy command explain the supported
workflow instead of dumping schema errors?

**Scope:** Shared legacy store loader error, with `review-report show`, `--report`,
`--store`, fresh-report guidance, and the requirement to keep a schema-1 copy for
`score --reviews`. No automatic conversion or annotation filtering.

**Validation:** Legacy score/review entry points, malformed inputs, unchanged
schema-1 behavior, and no writes on rejection.

## Completed validation: 2026-09-21

| Slice | Implementation commit | Independent test commits |
|---|---|---|
| Report-family scope | `abdb98b` | `3d19046` |
| Evidence filtering | `2af4612` | `17e6eda` |
| Explicit supersession | `a77de11` | `bd7db8e`, `503e769`, `0d88102`, `bc7ee4a` |
| Legacy command guidance | `6334376` | `8215a16` |

- Full Windows Python 3.12 suite: **1,658 passed**, four installation cases run
  separately. Branch-inclusive coverage: **95.40 percent**.
- All **84 new cases** passed on Python 3.13 and Python 3.14.
- Wheel/source builds and all four isolated installation checks passed.
- Ruff lint/format, Pyright, and all five import contracts passed.
- CLI inspection confirmed the superseded legacy entry, linking event, actor,
  retained reason, and independently current replacement are visible together.
- An independent source audit found no automatic reapproval or history rewrite.

The released v0.5.0 code and updated code scanned the same final working tree.
Parsed JSON matched exactly for `score`, `models`, `variants`, and `derived`,
including summaries, diagnostics, hashes, and score values. No fields were removed
for this comparison. Raw evidence is retained in `.tmp/review-feedback-20260921/`.
The new resolution states and explicit history links are intentionally different
review-workflow output, separate from those measurement reports.

### Self-scan review

The final scan has 76 complexity hotspots. Four are new and were independently
source-reviewed. All four have a **no-change** disposition; none justifies a
metric adjustment or score-driven rewrite.

| Callable | Effective CC / SLOC | Rationale and remaining risk |
|---|---:|---|
| `select_review_targets` | 13 / 30 | Guards distinct selection rules and reuses saved current-side M4 evidence. Future M4 versions require explicit support. |
| `render_review_resolution` | 11 / 37 | Presents distinct states, legacy relationships, and retained history. Future state additions need explicit rendering checks. |
| `test_invalid_supersession_does_not_write` | 11 / 40 | Builds independent invalid link cases and verifies exact store-byte preservation. Broad exception assertions should be revisited if rejection causes become ambiguous. |
| `test_ledger_validation_rejects_forged_supersession` | 14 / 43 | Builds hostile wire cases, first validates each without the link, then checks linked rejection. More cases may eventually warrant fixture reorganization. |

The CC values correctly count branching and comprehensions. They are review
signals, not established defects. Existing source-bound review records were not
automatically refreshed to clear stale decisions. Changes are committed locally;
this task does not publish a release or push commits.
