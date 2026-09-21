# Saved-report review workflow, version 2

## Scope

Keep judgments outside measurements. The new `review-report` command reads saved
JSON from `score`, `models`, `variants`, or `derived`. It does not rescan a checkout,
execute source, suppress findings, or change a score. Comparison reports expose
only current-side evidence. The original `review` commands and schema-1 store
remain compatible and keep their existing conservative anchor semantics.

The first version supports six review kinds: `clone`, `complexity`, `pattern`,
`model`, `variant`, and `derived`. Unsupported or failed experimental outcomes are
not review targets. An analyzed variant handler is a target even when exhaustive:
syntactic coverage does not establish whether a fallback or partial handler is
correct. Complexity targets are reported functions, not just functions over a
threshold. Models and derived targets are actual findings.

## Owned records

New module `domain.review_workflow` contains frozen, extra-forbid models.

- `ReviewLocation(path: ProjectPath, span: SourceSpan)`.
- `ReviewSubject(kind: ReviewKind, language, cohort, symbol, locations,
  evidence_fingerprint)`. `ReviewKind` has the six values above. Locations are
  nonempty, unique, sorted by path/start/end. The fingerprint is lowercase SHA-256
  of the complete relevant evidence projection, serialized as canonical JSON.
  `symbol` identifies a callable, rule ID, model, or clone family (`clone`).
- `NoReviewBoundary(state='not-applicable')` and
  `RelevantReviewBoundary(state='relevant', assignments)` form a tagged policy.
  Assignments are sorted, unique, and cover the subject's unique member paths.
  Only clone anchors use relevant assignments. Each assignment is the effective
  longest-prefix boundary name or null, using the existing component-safe rule.
  Unrelated declarations and declaration order do not change this policy.
- `ReviewAnchor(subject, source_hashes, boundary, analysis_fingerprint)`.
  Source hashes exactly cover sorted unique subject paths. All hashes are strict
  lowercase SHA-256 strings. Clone analysis binds M3 version, normalization and
  clone thresholds. Complexity binds M4 version, analyzer version and complexity
  threshold. Patterns bind rule-set/analyzer versions. Experimental kinds bind
  their experiment version. Calibration choice and unrelated config do not bind.
- `ReviewableTarget(state='reviewable', id, anchor)` and
  `UnavailableReviewTarget(state='unavailable', id, subject, reason)` form
  `ReviewTarget`. Reasons are `source-hash-unavailable` or `analysis-unavailable`.
  IDs are `kind:` plus SHA-256 of the canonical subject. They do not include
  source bytes, boundary assignments, calibration or unrelated configuration.
  Models validate that supplied IDs match this derived identity.
- `ReviewDecision(anchor, disposition, reason, next_step='')` uses existing
  actionable/defer/no-change dispositions. Reason must be nonblank.
- `ReviewEvent(sequence, review_id, actor, recorded_at, decision)` records one
  explicit write. Sequence is a strict positive integer. Actor is explicit,
  nonblank text. Recorded time is timezone-aware UTC. No user identity is guessed.
- `ReviewLedger(schema_version='2', legacy_decisions=(), events=())` retains an
  append-only ordered event stream. Sequences are contiguous starting at one.
  Events for a review ID must refer to the same kind/language/cohort/symbol and
  unique source paths. Earlier decision text, actor, time and anchor remain intact.
  Legacy decisions retain their original schema-1 `CloneReviewDecision` objects.
  Their unique IDs cannot collide with new event review IDs.

The target ID binds an evidence snapshot. A review ID binds the history of a
judgment. When evidence changes its target ID can change. Explicit `--review ID`
attaches a new decision to an existing compatible history. Without that option,
the current target ID is the review ID. No automatic history merge is attempted.

## Resolution

New `application.review_workflow` exports:

```python
review_targets(report) -> tuple[ReviewTarget, ...]
load_review_report(path: Path) -> SupportedReviewReport
load_review_ledger(path: Path) -> ReviewLedger
write_review(path, report, target_id, *, actor, disposition, reason,
             next_step='', review_id=None) -> ReviewLedger
resolve_reviews(report, ledger) -> ReviewResolutionReport
```

`SupportedReviewReport` is the closed union of AnalysisReport, ModelReviewReport,
VariantReviewReport and DerivedReviewReport. Saved report loading validates the
existing report type; it does not infer a new report from arbitrary JSON.

Resolve only the latest event for each review ID. Candidates share the subject's
kind, language, cohort, symbol and unique source paths. Exact anchor equality is
required for `current`. Candidate existence with any mismatch or unavailable
anchor gives `stale`. No candidate gives `missing` with reason
`evidence-absent-or-unavailable`; it does not mean fixed. Multiple candidates are
retained, sorted by target ID. No similarity matching or semantic reapproval.

Result records are tagged by state:

- `CurrentReview(state='current', event, target_id)`.
- `StaleReview(state='stale', event, changes)`; changes is a nonempty tuple of
  `ReviewTargetChange(target_id, candidate: ReviewTarget, causes)`, one record per
  candidate. The ID must equal the owned candidate ID. The current candidate
  exposes exact before/after source hashes and boundary assignments for display.
  Unavailable candidates retain their explicit reason. Causes are a
  nonempty unique tuple of closed strings: `source-changed`, `source-unavailable`,
  `evidence-changed`, `boundary-policy-changed`, `analysis-definition-changed`, or
  `analysis-unavailable`. Locations remain available in the event/target subject.
- `MissingReview(state='missing', event,
  reason='evidence-absent-or-unavailable')`.

`ReviewResolutionReport(schema_version='2', results, legacy_results, events)`
includes full history and latest resolutions. Legacy results use existing clone
resolution against an AnalysisReport, with the whole-policy fingerprint unchanged.
With an experimental report they are missing, never automatically current.

An unrelated boundary edit leaves a new clone decision current. A changed
effective assignment, exact member bytes, evidence or relevant analysis definition
still makes it stale. Schema-1 decisions continue to become stale on any boundary
policy change. Importing a schema-1 store performs no write. Its first explicit
new write retains original decisions under `legacy_decisions` in schema 2.

## CLI and storage

New `cli_reviews.py` exports `app`, mounted by root at `review-report`:

```text
slop review-report list --report snapshot.json [--json]
slop review-report set TARGET --report snapshot.json --store reviews.json \
  --actor reviewer-name --disposition defer --reason "Separate contracts" \
  [--next-step "Recheck the interface" --review EXISTING_ID]
slop review-report show --report snapshot.json --store reviews.json [--json]
```

List JSON is `{"targets": [...]}`. Show JSON is ReviewResolutionReport. Terminal
output shows locations, kind, target/review IDs, disposition, actor, UTC time,
reason, next step, and stale causes. It states that it describes the saved report
and does not change measurements. Set validates report, target, text and history
compatibility before changing store bytes. Unavailable targets cannot be recorded.

Use an exclusive sibling `.lock` and a same-directory temporary file, flush/fsync,
then `os.replace`. Reject symlink stores. Preserve existing bytes on validation,
lock or replace failure; clean only locks and temporary files owned by this write.
Read-only list/show never create or update the store. Missing explicit files and
invalid report/store schemas raise InputError and CLI exit 2.

## Design checks and validation

The closed target and result unions separate unavailable evidence from current
judgments. One immutable event stream is authoritative for history; latest status
is a projection recomputed from the selected report. Legacy anchors remain a
distinct compatibility boundary rather than being silently weakened.

Independent tests precede implementation. Cover all six kinds, exact byte and
evidence invalidation, relevant versus unrelated boundary edits, actor/time/history,
schema-1 retention, missing hashes, failed experimental records, current-side
comparison selection, explicit re-review, atomic errors, malformed saved input,
and unchanged raw reports and scores. Commit tests separately from implementation.
