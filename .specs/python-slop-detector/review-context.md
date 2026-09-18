# Review context without score tuning

No change in this work may tune thresholds, weights, exclusions, or reference
populations to make this repository look better. The external repeat assessment
is regression feedback from the same lineage, not an independent calibration set.
Private source, paths, source hashes, and evaluation artifacts stay external.

## TB-1: Explain the ranked file and callable

Question: can readers identify the measured score driver and selected M4 basis
at the location where they review evidence?

Scope: terminal rankings include clones at narrow and wide widths; callable
rows label full-CC mass and separately explain effective CC, mass, numerator,
threshold, and version-specific basis. Pattern counts name their family. A
production callable whose threshold crossing comes from assertions gets a
classification-review hint. This does not infer test intent or change its cohort.

Validation: synthetic clone-driven scores remain unchanged; historical M4v1/v2
retain their definitions; unknown versions are unavailable; v3 tests show the
assertion-excluded basis. The callable JSON mass field keeps its existing meaning.
Budget: presentation and derived formatting only, with no metric changes.

## TB-2: Configured ownership around real clone groups

Question: can declared architectural boundaries annotate a full scan without
changing its clone population or calibration?

Scope: named, normalized path prefixes in configuration, longest component-prefix
selection, explicit unassigned members, and a derived within/cross/unknown relation.
Annotations live outside raw clone detail. Their policy fingerprint is independent
of declaration ordering. Reports validate the annotation against their own policy.

Validation: config/API/CLI/JSON and baseline/current comparison paths; same clone
IDs, raw details, metric results, and scores with or without boundary declarations.
Budget: prefix labels only; no inferred services, ownership parser, or suppression.

## TB-3: Source-bound clone review decisions

Question: can a reviewer carry an intentional/deferred/actionable clone decision
forward without silently applying it to changed evidence?

Scope: explicit review set/show commands and optional review-store input to reports.
Only review set writes. Frozen store records retain a required reason and optional
next step, raw clone identity, exact member-file hashes, boundary policy, and clone
measurement definition. Current/stale/missing are separate result types. Missing
means absent or unavailable evidence, never proof of a fix.

Validation: source edits that preserve normalized clone tokens still make decisions
stale; boundary/settings changes also invalidate them; missing groups stay visible;
malformed stores and concurrent writers cannot replace good data. Ordinary reports
remain read-only and preserve all findings, ordering, metrics, and calibrated scores.
Budget: clone decisions only, one explicit local JSON store, current snapshot side.
No automatic fixes, automatic acceptance, score discounting, or remote publication.

The data shape separates evidence from review judgments. Boundary relations derive
from assignments, and review applicability derives from retained source and policy
identity. Explicit tagged review states prevent a missing item from masquerading
as a current acceptance. The existing raw facts remain the authority for scoring.

## Still outside this iteration

Broader calibration requires independently sourced service/contract repositories,
lineage-level holdouts, adjudicated labels, and positive pattern controls. The six
historical reference projects remain unchanged. This iteration adds neither new
languages nor automatic embedded-test reclassification. It does not convert the
overall score into a quality gate.


## Validation completed

All three slices are implemented. Independent test authors committed the contracts
before implementation. The final local suite passed 1,290 tests with 96.98%
branch-inclusive coverage; its four artifact checks were run separately and passed
against newly built wheel and source distributions. The 73 new workflow/integrity
checks also pass under Python 3.13 and 3.14. Ruff, formatting, Pyright, and all five
import contracts pass.

A controlled self-scan used both the installed v0.2.0 wheel and the updated working
tree against the same current source. Their cohort metrics, scores, callable facts,
coverage, pattern findings, clone groups, and diagnostics match exactly. The only
new file evidence is the exact source SHA-256 used to bind review decisions. Source
files stayed byte-identical during the scans. Both versions report production score
2.0 and M4 12.0781% over 67 files. The full test cohort remains unavailable because
of the deliberately invalid parser fixture. The updated scan took about 7.3 seconds;
this one observation is not a performance benchmark.

Synthetic tests separately prove that boundary labels and loaded review decisions
preserve all scores and raw findings. Comment-only edits preserve normalized clone
identity but make the saved decision stale. Missing evidence never becomes an
acceptance. Store validation, exclusive locks, symlink rejection, failed atomic
replacement, and imported-report tampering have retained tests. Golden updates
change presentation and source identity only, not historical numeric results.

Local confirmation artifacts are in `.tmp/review-context-confirmation/`. No
calibration resource, score weight, threshold, or default exclusion changed.
This working-tree feature set has not been published as a release.
