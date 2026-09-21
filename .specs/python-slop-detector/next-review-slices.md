# Evidence and review workflow follow-up

These slices implement the next four priorities after v0.4.0. They do not change
calibration, metric formulas, thresholds, source selection, or scoring weights.
Each implementation follows independent test contracts and has its own commit.

## TB-1: Independent evaluation

**Question:** What can the released model and variant experiments assess in
independent public repositories?

**Scope:** At least three pinned public repository snapshots outside this project
and its calibration corpus. Parse source without running target code. Retain raw
reports locally and record reproducible commands, source identities, coverage,
manually reviewed examples, and uncertainty in a checked-in summary.

**Validation:** Separate real examples from synthetic controls. Do not infer
precision or recall from zero findings or treat unresolved analysis as clean.

## TB-2: Stale derived counts

**Question:** Can one command show a local derivation, a mutation, and a later read
without recomputation, with source locations and explicit coverage limits?

**Layers:** Python AST -> owned evidence -> directory application -> JSON/CLI.

**Scope:** `slop derived` inspects straight-line local list literals, a stored
`len(items)`, supported list mutations, and a later read of the stored count.
Unsupported bindings, aliases, calls, and control flow remain unassessed. The
report describes a review candidate: an intentional snapshot may be correct.

**Data shape:** File and function outcomes are tagged analyzed/unresolved/failed
variants. Findings contain ordered derivation, mutation, and read locations.
Failure cannot coexist with successful findings for that file. No score is stored.
This keeps analysis failure separate from an assessed function with no candidate.

**Validation:** Independent positive and keep-case tests, source integrity,
strict failures, external configuration, CLI output, and unchanged ordinary scores.

## TB-3: Retain decisions for each evidence type

**Question:** Can a reviewer retain a decision for a pattern, complexity hotspot,
or experimental finding as well as a clone?

**Layers:** Saved native report -> typed review subject -> atomic ledger -> CLI.

**Scope:** An additive saved-report workflow with source-bound subjects. Keep
legacy clone stores readable. Retain explicit reviewer identity, UTC time, and
previous decisions. Reads do not write or approve decisions.

**Validation:** Every supported evidence type can be listed, reviewed, and
rechecked. Failed or absent evidence is not a fix. Scores and findings stay intact.

## TB-4: Relevant policy dependencies

**Question:** Can new clone reviews remain current when unrelated ownership
declarations change while relevant source, ownership, and detector changes remain
visible?

**Scope:** New review anchors bind the effective boundary assignments of their
members. Legacy anchors keep their original whole-policy contract. Exact source
bytes still matter. A comment edit is not automatically approved as harmless.

**Validation:** Unrelated declarations preserve new decisions; changed member
assignments stale them. Source changes show old/new identities. Re-review appends
history. No automatic migration or silent approval of old decisions.

## Completed validation, 2026-09-21

All four slices are complete as source-checkout features. The published release
remains v0.4.0; this follow-up has not been pushed or released.

- Independent evaluation: three pinned public repositories, 539 selected Python
  files, 533 parsed, six malformed formatter fixtures. Two model assessments were
  supported negatives; 760 were unresolved. All 99 variant assessments were
  unresolved. No eligible positive cases occurred. These observations do not
  establish precision or recall. See [the evaluation](independent-evaluation-040.md).
- Independent test authorship preceded implementation. Separate commits retain
  red contracts and regression cases. Another agent reviewed builtin shadowing
  and saved-review persistence. Confirmed shadowing gaps received tests and fixes.
- Full Windows Python 3.12 suite: 1,498 passed, four distribution cases skipped
  for the separate artifact gate. Branch-inclusive coverage: 94.63 percent.
- All four isolated wheel/source installation cases passed. An installed wheel
  also ran the derived positive/recomputed negative fixture and saved-report
  list/set/show lifecycle successfully.
- All 74 new derived and review-workflow cases passed on Python 3.13 and 3.14.
  The focused new/legacy review gate passed 84 cases.
- Retained learning tests and small performance checks passed; the full opt-in
  performance benchmark was not run. Ruff lint/format, Pyright with the project
  interpreter, and all five import contracts passed. No dependency changed.
- The released v0.4.0 executable and updated executable scanned this same final
  Python source tree. Their ordinary score JSON was exactly equal. Calibration,
  metric definitions, source selection, and scoring were not tuned.
- The new derived scan selected 189 files. One intentional malformed fixture
  failed parsing. Two functions were analyzed, 1,481 were unresolved, and no
  candidates were found. This is limited coverage, not a clean result.
- Local proof artifacts are under `.tmp/followup-confirmation/`. Public evaluation
  clones and raw reports stay under `.tmp/evaluation040/`. Neither source corpus
  nor generated reports are committed. No private external evaluation artifacts
  were accessed or published.

The saved-report ledger supports all six evidence kinds. New clone anchors depend
on effective member ownership assignments, while legacy anchors keep whole-policy
matching. Source bytes remain exact. Comment-only edits still require review.
Actor, UTC timestamp, rationale, next step, and earlier decisions survive explicit
re-review. Reads leave ledger bytes and measured reports unchanged.
