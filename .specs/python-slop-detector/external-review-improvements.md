# Improvements from external review

The external report is one provisional evaluation set. Its private source,
locations, hashes, and review artifacts are not part of this repository. Synthetic
examples verify general behavior; no score weight or threshold is fitted to make
the external repository appear clean. Overlapping subscans must not become
independent calibration projects, and zero pattern matches are not positive-rule
recall evidence.

## Slice 1: assertion-aware test complexity

Question: can source evidence distinguish assertion density from control flow
without erasing the original measurement or breaking historical reports?

Retained Radon learning tests show that paired full and `no_assert=True` runs
identify a callable's own assertion increments, excluding nested scopes. Boolean
expressions inside `assert` are skipped in both modes; boolean method-call
arguments can still add complexity. This difference remains a documented limit.

`FunctionEvidence.assertion_count` is optional: absent means the analyzer did not
provide decomposition, never zero assertions. `control_flow_complexity` derives
from total CC minus known assertion increments. Validation prevents negative flow
or contradictory serialized projections. Original CC, source lines, and raw mass
remain available, so there is one source of truth for each measurement.

M4 version 3 uses assertion-excluded CC for test-cohort callables when decomposition
is available; other adapters retain their supplied CC. Production uses total CC.
Both numerator and denominator use the selected CC, with the existing gradual
formula. The new `py-2026.3` profile remeasures the same six pinned projects with
separate production and test reference populations. Old profiles remain immutable
and incompatible with version 3; there is no weight or threshold retuning.

Assertions in a production-classified self-check remain visible. Classification
continues to use declared path patterns; it does not guess test ownership from
function names or remove an entire mixed-purpose file. Users can select explicit
test patterns or retain tooling/demo scans as separate evaluation strata.

Validation: assertion-only test functions lose excess mass; real control flow
remains; production assertions are preserved; historical unknown decomposition
stays unknown; nested and async callables do not leak counts; JSON and explanation
views show both measurements. Findings use the same effective CC as test M4.

## Slice 2: reference support beside scores

Question: can a reader distinguish a calibrated zero from absent evidence and
see the population behind the score without opening the profile file?

Measured scores own a tagged reference-support value. Historical reports use
`not-recorded`; new reports record a file population with its size band or a
project population with its sample count. Nominal percentile resolution derives
as `100 / sample_count`, in percentile points. Counts are observations, not proof
of independent samples, domain fit, or statistical confidence.

Domain match is explicitly `not-assessed`; the scanner cannot infer an event-driven
service's suitability for a library-heavy corpus from its path. Missing reference
populations have a distinct unavailable reason. Zero-score explanations distinguish
no strictly lower reference observations from weighted values rounded to zero.
Absolute affected lines and excess/total complexity mass remain visible beside
normalized metrics, so a low percentile cannot hide the measured amount of code.

Validation: owned JSON round trips, historical reports, positive sample counts,
file bands, project/file units, zero-score causes, missing populations, and compact
terminal output. Existing calibrated point values do not change in this slice.

## Follow-on slices

| Slice | Architectural question | Required evidence before completion |
|---|---|---|
| Explicit ownership boundaries | Can clone members retain configured ownership and report within-boundary, cross-boundary, or unknown context? | Same raw clone groups/M3; nested-boundary precedence; unknown ownership; no automatic suppression or extraction advice |
| Persistent review dispositions | Can a reviewed item be recognized only while its source and metric identity remain valid? | Required reason and evidence reference; content/version fingerprints; current/stale/missing states; changed evidence resurfaces; read-only scans never write decisions |
| Tooling and embedded checks | Can mixed-purpose code be reported without excluding real implementation or inventing ownership? | Explicit classification policy and reference strata; no function-name guesses; preserve thin self-check entry points |
| Independent evaluation corpus | Do improvements reduce review burden outside the tuning lineage? | Repository-level holdouts; independent adjudication; positive and negative pattern examples; no counting provider copies or overlapping scans as independent projects |
| Additional languages | Can a real adapter meet the evidence contract? | Language-specific parser, coordinates, cohort coverage, rules and calibration; unassessed source remains unassessed |

The first two slices improve measurements and interpretation. The follow-on work
requires explicit ownership and persistence contracts; neither architecture nor
an intentional-duplication disposition is inferred from a numerical score.


## Implementation and validation

Implemented slices 1 and 2 on 2026-09-18. Boundary configuration, persisted decisions,
embedded-check classification, and new language adapters remain follow-on work.
No external private source or report artifacts were added.

- Independent authors committed the assertion and reference-support specifications
  before implementation. Radon learning tests preceded the assertion contract.
- The same six pinned clean checkouts rebuilt `py-2026.3`: 182,882 SLOC and no
  analysis diagnostics. Production populations and score models equal `py-2026.2`
  exactly. Historical profile files were not changed.
- New test project M4 reference ratios range from zero to 0.0246912. These are
  measurements of the same historical corpus, not independent validation of domain
  fit or evidence for new thresholds.
- All 1,217 deterministic tests pass with 96.90% branch-inclusive coverage. The four artifact tests also pass against
  freshly built wheel and source archives. All 50 learning tests pass.
- Focused Python 3.13 and 3.14 runs each pass 408 tests. Ruff, formatting, Pyright,
  and all five import contracts pass.
- A Python-filtered self-scan completes. Its one diagnostic is the intentionally
  invalid `tests/fixtures/basic/bad.py` source fixture. No analyzed source executes.
- Report golden changes preserve historical numeric values. Changes cover new
  evidence, support metadata, current version IDs, and interpretation text.

This is a local implementation validation. It is not a new published release or an
independent adjudication of the external review labels. The corpus remains small
and library-heavy. Do not use these changes alone to justify a quality gate.


### Final self-scan confirmation

After implementation, the requested `slop score . --lang py --top 10` scan took
about 7.3 seconds on this machine. Production: 62 files, score 2.0, M4 11.71%.
The full test cohort remains unavailable because the repository deliberately
contains an invalid parser fixture. Its valid callable evidence remains inspectable.

A separate `tests/unit` scan took about 3.2 seconds and had no diagnostics:
56 test files, score 0.2, M4 0.6192%. Of 26 callables above CC10 using full CC,
only one remains above CC10 using assertion-excluded CC. For example,
`test_valid_sources_produce_exact_owned_file_evidence` is CC17 with 16 assertion
increments and control-flow CC1. Assertions remain in the source and evidence.

The test numerator and denominator were independently recomputed from callable
evidence. Reference support reports six project observations and unassessed domain
match. All tracked Python source hashes stayed unchanged during the scans. The two
scan roots overlap and must not be counted as independent evaluation projects.
Local reports are in `.tmp/feedback-confirmation/` and are not package resources.
