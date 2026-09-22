# Reproducible public evaluation

## Purpose

Retain the public examples as repeatable checks of detector evidence and coverage.
The evaluation does not change detectors, scores, thresholds, or calibration.
Upstream source is downloaded only on explicit request and is never executed.

## Data contract

A versioned manifest identifies each repository, exact commit pair, selected source
paths, SHA-256 hashes, interpretation, and expected report values. Snapshot runs
and change runs are separate tagged shapes. Each check compares a JSON pointer in
the full report with an explicit expected value.

Job outcomes are passed, mismatch, timeout, or error. A completed evaluation can
contain mismatches. Timeout, missing evidence, invalid evidence, or analyzer drift
makes the evaluation incomplete. A matching coverage-gap expectation is not a
successful defect detection. These states prevent missing output from becoming a
zero-finding success.

## TB-1: Reproduce a pinned source finding

**Question answered:** Can a manifest produce a verified static report offline?

**Layers touched:** Manifest, verified source cache, isolated analyzer, report,
expected-result comparison, command exit status.

**Scope:** Selected Python files, errors and derived snapshots, change comparisons.
Target packages and tests are not imported. Full repository acquisition and new
detector behavior are outside this slice. Keep the runner and its contract tests
small enough to inspect as one developer tool.

**Validation:** Independently authored tests cover a supported positive, mismatch,
coverage gap, invalid cache, invalid manifest, and a target import sentinel.

## TB-2: Bound execution and preserve provenance

**Question answered:** Does an interrupted or changed run remain visibly incomplete?

**Layers touched:** Worker process, timeout, raw artifacts, analyzer identity,
source verification, summary.

**Scope:** Kill and reap a timed-out analyzer process. Preserve job failures and
reports in a fresh output directory. Record analyzer and input hashes, and reject
source drift as a completed evaluation.

**Validation:** A real child-process timeout returns promptly, produces an incomplete
result, and exits nonzero. Existing output directories cannot be reused silently.

## TB-3: Exercise public positive, intentional, and unsupported cases

**Question answered:** Do real pinned cases retain their documented evidence states?

**Layers touched:** Public manifest, source acquisition, offline replay, detector
reports, labeled evaluation documentation.

**Scope:** AstrBot introduction and fix, an intentional HTTPX fallback, PyRIT,
Werkzeug, and NetworkX coverage gaps. Keep the previous full HTTPX/Rich/Black
evaluation as separate evidence with its original scope. New selected-file scans
do not reproduce or replace its whole-repository counts.

**Validation:** Run the checked-in manifest against verified source bytes. Retain
full reports and exact expected/observed differences. Report uncovered behavior and
repository-lineage overlap. NetworkX is not an independent calibration holdout.

## Commit and validation sequence

Commit the plan, independent contract tests, implementation, public cases, and
verified documentation as separate units. Tests establish failure before the
runner is implemented. Run focused checks, static checks, the project suite, and
the public evaluation before completing the task. Downloaded source and generated
reports stay under ignored `.tmp/` paths.
