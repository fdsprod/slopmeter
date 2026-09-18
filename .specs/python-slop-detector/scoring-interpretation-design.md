# Gradual erosion and report interpretation

The nine-case [review baseline](scoring-review-baseline.md) guides this first tuning
step. M4 version 2 replaces binary callable contributions with excess complexity:

```text
numerator = sum(max(0, CC - threshold) * sqrt(SLOC))
denominator = sum(CC * sqrt(SLOC))
erosion = numerator / denominator
```

At threshold 10, a single CC11 callable now measures 1/11 instead of 1. The
denominator and unavailable states stay unchanged. Flat predicates can still
score higher than useful orchestration refactors; no unvalidated syntax discount
or file-name exception is introduced. The metric estimates structural pressure,
not readability, correctness, or the value of a particular edit.

## Version and calibration

M4 records version `2`; other metric versions stay unchanged. A new packaged
`py-2026.2` profile uses the same six pinned reference projects measured afresh.
It becomes the default. Historical `py-2026.1` resources remain immutable and
cannot calibrate version 2 reports. The saved local review baseline remains an
evaluation artifact, separate from the reference corpus.

## Interpretation contract

One immutable `ReportInterpretation` value supplies the versioned guide for
analysis reports and rule catalogs. It has a purpose, score meaning, metric
meanings, limitations, review steps, and a disposition template. Text is shared
by terminal and JSON outputs; report-specific facts remain in existing provenance,
coverage, metrics, scores, and diagnostics instead of being copied into the guide.

This separates stable interpretation policy from measurements and avoids a second
source of truth for runtime thresholds or profile IDs. The guide explains both
legacy M4 version 1 and current version 2, so parsing a historical report does not
silently describe its binary metric as gradual. Additive interpretation metadata
retains report schema 1.0 and has its own version.

Every successful score, scan, tree, compare, explain, findings, and rules output
contains interpretation. Terminal output includes compact guidance by default,
with expanded metric definitions and review steps under `--verbose`. JSON includes
the complete structured guide and remains parseable without extra terminal text.
A rule catalog does not imply source has been scanned.

The guide distinguishes calibrated points from raw ratios, and high scores from
required changes. It names flat guards and short readable routines as possible
overstatements, and algorithmic difficulty as a possible understatement. It asks
for source location, evidence, context, disposition, and the next step. A no-change
decision requires a concrete reason; generic dismissal or a lower score alone is
not adequate justification for an edit.

## Output encoding

When stdout cannot encode display glyphs, CLI rendering uses ASCII automatically.
Explicit ASCII continues to work. This prevents the existing Windows CP1252
failure from hiding both measurements and their interpretation.

## Validation

Independent test authors define red tests for mass-weighted gradual erosion,
version compatibility, baseline examples, report ownership, CLI coverage of the
guide, and CP1252 output. Current goldens are updated for the intended metric and
guide changes. Rebuild calibration from verified cached repositories, then run
the complete suite, static checks, and package installation checks.
