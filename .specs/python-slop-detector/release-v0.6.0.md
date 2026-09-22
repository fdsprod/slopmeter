# Slopmeter v0.6.0

This release adds change-focused review and a repeatable public evaluation suite.
It keeps raw evidence, uncertain matches, and analysis limits visible. New review
signals do not contribute to calibrated snapshot scores.

## New commands

- `errors` reports supported exception handlers that return literal defaults while
  another return supplies a different result. Reports retain protected operations,
  locations, and assessed/unresolved coverage. Inspect the caller contract before
  treating a candidate as an error disguised as success. Saved reports support
  attributed decisions through the new `error` review family.
- `changes` compares directory, Git, and `WORKTREE` evidence. It tracks pattern
  occurrences, clone membership, exception fallbacks, and direct raw-string tests
  of `.state`. It distinguishes introductions, removals, persistence, changes,
  and unresolved correspondence. Clone groups also expose expansion/contraction.
- `surface` reports Python declaration additions, changes, removals, and supported
  moves, with an explicit unavailable state when correspondence is incomplete.
- `architecture` checks declared direct import restrictions and reports module
  fan-out and source dependency cycles. Dynamic or ambiguous imports remain
  unresolved. Source relationships do not prove runtime dependencies.
- `history` reads a bounded first-parent Git range. It reports source churn and
  recent rework for lines with known introduction dates. Missing history and
  unknown ages remain explicit. This is not files-changing-together analysis.

```text
slop errors --root . --lang py --json
slop changes HEAD~1 HEAD --repo . --lang py --json
slop surface HEAD~1 HEAD --repo . --json
slop architecture --root . --policy architecture.toml --json
slop history HEAD~20 HEAD --repo . --window-days 14 --max-commits 100
```

## Explicit policies

Change budgets are separate from `slop.toml` and ownership labels. For example:

```toml
[[limits]]
metric = "introduced-errors"
maximum = 0
```

Use `slop changes HEAD~1 HEAD --repo . --budget budget.toml` for advisory output.
Add `--enforce-budget` only when enforcing a chosen policy. Supported limits are
`introduced-patterns`, `added-clone-members`, and `introduced-errors`. An enforced
exceeded budget exits 1; incomplete evidence exits 3. Invalid inputs exit 2.
The example cap is not a calibrated recommendation.

Architecture uses a separate policy, with roots relative to the analyzed source:

```toml
source_roots = ["src"]

[[forbidden]]
source = "app.controllers"
target = "app.storage"
```

These rules cover direct imports and descendants of the declared modules.
Ownership labels do not create import permissions. Architecture remains advisory.
Existing external `--config` selection remains available for analysis settings.

## Review workflow and compatibility

- Mixed-family ledgers now distinguish `not-in-selected-report` from `missing`.
  An absent report family no longer creates a misleading missing-evidence queue.
- `review-report list` supports repeated `--kind`, `--cohort`, and
  `--hotspots-only` filters. These select evidence without changing measurements.
- `review-report set --supersedes LEGACY_ID` explicitly links a new clone judgment
  to a legacy decision. The legacy entry becomes `superseded`; history remains.
  No automatic reapproval or source-change suppression occurs.
- Review-resolution JSON is now **schema 3**. Ledger storage remains **schema 2**,
  with optional `supersedes_legacy_id` on linking events. Existing ledgers load
  without migration. Older readers cannot consume schema-3 resolutions or the
  new ledger field. Preserve an unchanged copy when an older reader is required.
- `score --reviews` and legacy `review` still accept schema-1 clone stores only.
  Schema-2 errors now explain how to use `review-report` with a fresh saved report.

## Public evaluation suite

The source archive and checkout include `evaluation/public-cases.json`, usage
instructions, and `tools/evaluate.py`. The wheel does not install this developer
tool as a command.

The suite pins six cases from five repository lineages: AstrBot introduction and
fix, an intentional HTTPX fallback, and PyRIT/Werkzeug/NetworkX coverage gaps. It
checks source hashes, preserves complete reports, enforces worker deadlines, and
records analyzer/runtime identity. It runs offline from a verified cache;
downloads require `--fetch`. Target code and upstream tests are never executed.

All 16 evaluation jobs and 137 checks passed on the implementation revision.
A separate fresh-download AstrBot run passed 24 checks. These are selected
regression examples, not a precision/recall study or independent holdout. The
object-field and cross-method derived-state examples remain unsupported.

## Measurement compatibility and validation

The calibration resources remain unchanged: profile `py-2026.3`, M4 version 3,
and the same six historical reference projects. No new weights or thresholds were
introduced. Scores remain review signals, not a general correctness gate.

The implementation passed 1,996 tests on Windows Python 3.12.14 with 93.25%
package coverage. Four release-install tests were skipped in that development
run. Ruff, Pyright, five import contracts, and wheel/source builds passed. The
version bump also passed all 58 targeted golden and CLI tests. Release artifact
installation and CI results are verified separately before publication.

Install the attached wheel with Python 3.12 or later:

```text
python -m pip install --upgrade slop_measure-0.6.0-py3-none-any.whl
```

The release includes the wheel, source archive, and `SHA256SUMS.txt`.
