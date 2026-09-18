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

The first baseline replay showed that percentile calibration alone still ranked
the original `measure_erosion` file at 42.5 points despite its new 9.1 percent raw
erosion. A small nonzero value can be unusual in a mostly-zero reference band.
The new profile therefore applies `severity-weighted` transformation to M4:
`contribution = percentile * raw_value * weight`. Combined verbosity retains its
percentile transformation. Existing tenths allocation keeps displayed contribution
sums equal to the displayed total.

`ScoreTransform` is a closed enum shared by profile inputs and report contributions.
Historical inputs default to `percentile`, omitted when serialized, so old profile
bytes and report semantics remain valid. The selected transform is recorded with
each adjusted contribution; its multiplier is derived from the existing raw value
instead of stored as duplicated state. Individual metric percentiles stay intact.
This provisional policy changes score meaning and requires the new profile ID.

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

## Baseline replay

The final scorer was run against the unchanged baseline Git revision, not the
modified working tree. The [saved replay](scoring-tuned-baseline.json) includes
the exact command, provenance, raw erosion, and all score contributions. All nine
original CC/SLOC pairs matched, and all nine candidate file ratios matched the
actual version 2 measurements.

| File containing the example | New raw erosion | New file score |
|---|---:|---:|
| `measure_erosion` | 9.1% | 3.9 |
| `_normalized_extensions` | 14.7% | 6.5 |
| `_plain_forwarder` | 28.0% | 10.4 |
| `_contained` | 11.0% | 3.0 |
| `AnalysisService._scan` | 24.3% | 8.5 |
| `render_findings` | 25.8% | 9.3 |
| `aggregate_snapshot` | 32.8% | 13.1 |
| `query_findings` | 29.2% | 10.9 |
| `build_profile` | 10.0% | 2.6 |

These are file results, not individual callable scores. The local examples guide
the policy; the six reference projects supply calibration distributions. This is
a scoring-policy change, not evidence that the unchanged source became better.
The intended orchestration examples now rank above the borderline erosion helper.
Flat-predicate overstatement and algorithmic understatement remain visible in the
table and are explicitly described in every report's guide. External validation
is still needed before treating the policy as broadly established.

The new profile was built from fresh scans of the six verified cached repositories.
After adding severity weighting, the builder reused those same owned version 2
observations; the source measurements and reference distributions did not change.
The historical profile and corpus files were not edited.

The six fresh corpus reports contain 182,882 SLOC and zero diagnostics. The new
manifest SHA-256 is
`c6f32096c104377bf697a57e5175161bb96adcac7eab48d5735a29a711b732f6`.

Final Windows validation: 1,178 deterministic tests passed; the four artifact
checks passed separately against rebuilt wheel and source distributions. All 42
retained learning tests passed. Branch coverage is 96.81 percent. Ruff lint and
formatting, Pyright, and all five import contracts passed. Focused scoring,
erosion, interpretation, rendering, and golden checks passed on Python 3.13 and
3.14 as well as the primary Python 3.12 environment. Hosted Linux and macOS jobs
were not run in this checkout.
