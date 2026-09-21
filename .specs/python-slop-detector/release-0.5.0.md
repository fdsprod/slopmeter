# Slopmeter v0.5.0

This release adds attributed review history, experimental stored-count analysis,
and coverage summaries that show what the experiments actually assessed.
Calibration, thresholds, scoring formulas, pattern rules, and clone detection
remain unchanged.

## Experimental coverage and explanations

`models`, `variants`, and `derived` now put coverage before detailed findings:
files analyzed/failed, subjects encountered/assessed/unresolved, findings, and
grouped unresolved reasons. JSON includes the same computed `summary`.

`Nothing assessed` differs from assessed subjects with no findings. Class counts
include ordinary classes and test fakes; they do not measure business-model
coverage or recall. Failed files contribute no inferred subject count. Missing
and fallback variant handlers count as findings; exhaustive handlers do not prove
branch correctness.

Variant explanations now identify unsupported scope/signatures, non-leading
matches, subject shapes, annotations, bindings, declarations, and patterns.
These explanations preserve the supported syntax and successful evidence.

## Stored-count review

```powershell
slop derived --root . --lang py
slop derived --root C:/project --config C:/reviews/project.toml --json
```

This experimental command connects a stored `len(items)`, a length-increasing
list mutation, and a later read without recomputation. It supports straight-line
local list literals with `append`, nonempty literal `extend`, and `insert`.
Unknown calls, aliases, control flow, object fields, and uncertain bindings remain
unresolved. A stored count can be an intentional snapshot; review the consumer's
contract. The command never executes source and makes no score or M2 contribution.

## Attributed review history

```powershell
slop score . --lang py --json | Set-Content -Encoding utf8 snapshot.json
slop review-report list --report snapshot.json
slop review-report set TARGET_ID --report snapshot.json --store decisions.json --actor reviewer-name --disposition defer --reason "Review when the contract changes." --next-step "Check failure paths."
slop review-report show --report snapshot.json --store decisions.json
```

The new workflow accepts saved JSON from `score`, `models`, `variants`, and
`derived`. It retains clone, complexity, pattern, model, variant, and derived-state
decisions with an explicit actor, UTC timestamp, rationale, next step, and history.
Failed and unresolved experimental results are not review targets.

These commands inspect saved reports. Generate a fresh report to check current
source. Reads do not write stores, and changes are never automatically approved.
New clone decisions bind their members' effective boundary assignments; unrelated
declarations do not invalidate them. Changed member assignments, source bytes,
evidence, or analysis definitions still do. Comment-only edits still require review.

## Fixes and compatibility

- Model review rejects class-local `bool` shadowing instead of claiming a built-in
  Boolean field. Supported unshadowed evidence is unchanged.
- Findings from historical M4 v1/v2 reports use full complexity. M4 v3 uses the
  cohort-specific basis. Missing or unknown versions do not invent classifications.
- Default calibration remains `py-2026.3`, M4 version 3, with the same six historical
  reference projects. No project-specific score tuning was introduced.
- The current reader accepts old experimental reports without a summary and
  validates supplied summaries against detailed evidence. Older readers may reject
  the new additive summary field; upgrade readers before consuming new reports.
- Schema-1 clone stores remain readable. The first explicit `review-report set`
  write preserves old decisions under `legacy_decisions` in a schema-2 ledger.
  Legacy decisions retain whole-policy invalidation. Use `review-report` afterward;
  the original `review` commands remain schema-1-only. Keep a copy for legacy use.
- Review evidence, source selection, profile identity, and scan root must stay
  comparable. Keep separate stores for independent roots.

## Validation

- 1,574 deterministic tests passed with 95.20% branch-inclusive coverage; four
  clean wheel/source installation checks passed separately.
- All 69 new coverage/explanation cases passed on Python 3.13 and 3.14.
- Ruff, Pyright, and all five import contracts passed.
- On identical final source, ordinary score JSON matched the pre-change
  implementation exactly before the version bump. Experimental evidence matched
  after removing only summaries and unresolved variant reason text.
- Independent HTTPX/Rich/Black evaluation supplied no eligible positive cases.
  Self-scans likewise expose narrow experimental coverage. These results do not
  establish detector precision, recall, or a general correctness guarantee.

Use the tool for advisory review. Assets include a wheel, source distribution,
and SHA-256 checksums.
