# Review-context feedback checkpoint

Implemented on 2026-09-22 after the external v0.6.0 assessment. These changes
improve change correspondence and interpretation. They do not change snapshot
metrics, calibration, thresholds, or source-bound review validity.

## Changes

- Edited clone groups retain before/current fingerprints and modified members.
  Correspondence needs mapped files, unique declaration owners and suites, and
  a majority of unchanged complete statements with two distinct anchors.
  Four edited copies count as four modifications, not four additions. A fifth
  copy still counts as one addition. Weak correspondence, repeated qualified
  declarations, and competing split/merge mappings remain unresolved.
- Budgets retain structured blockers with reason codes, source sides, paths,
  and spans when available. Population limits retain missing location context.
  Unsupported unchanged handlers still make the error budget incomplete.
- Literal `.state` comparisons retain unknown semantic intent. Geographic and
  lifecycle examples use the same rule; there is no value blacklist.
- Import observations retain timing and guard context. Static edges, cycles, and
  policy checks remain intact. Annotations and lazy type aliases have unknown
  timing. Shadowing and observed typing-module mutations prevent type-only
  claims. Legacy imports without context remain unknown.

The new budget source/population union prevents invented locations. Import timing
and guards remain separate because a deferred body can also have a type-checking
guard. Clone correspondence uses explicit unrelated, uncertain, and anchored
states. Compatibility message fields are checked against structured evidence.

## Validation

Independent agents authored failing behavior tests before implementation. Tests
also found generator outer-iterable timing, duplicate declaration ambiguity, and
typing-alias mutation cases. Each received a code fix. Final pending test markers
were removed. No evaluator rule was relaxed to favor this repository.

| Check | Result |
|---|---|
| Full deterministic suite | 2,069 passed, 4 distribution tests skipped in this run |
| Package branch coverage | 93.83%; required minimum 90% |
| Separate wheel/source installation and archive checks | 4 passed |
| Learning and performance tests | 69 passed, 1 skipped |
| Ruff check and format, Pyright | Passed |
| Import Linter | All five contracts kept |
| Cached public source evaluation | 16 jobs, 137 checks passed |
| Dependency audit | No known dependency vulnerabilities; unpublished local package skipped |

The cached public run checks reproducibility of selected cases. It does not add
independent holdouts or establish population precision/recall. No private source
or external review ledger was copied into this repository.

The first full run overlapped the duplicate-declaration fix and failed that case.
The final frozen-source run above passed. Package checks first encountered an old
artifact directory, then the wrong global uv version. A clean output directory
and the project's pinned uv resolved both setup errors.

## Self-review

Ran the requested `slop score . --lang py --top 10` and separate source-only
score, error, change, and architecture scans. The whole-repository scan remains
partial because its fixture corpus contains an intentional syntax error and
generated-marker examples. The source-only score JSON exactly matches the
released v0.6.0 executable on the same bytes, with no fields removed.

The source error scan has 70 handlers: 46 assessed, 24 unresolved, and one existing
candidate in `FilesystemSourceProvider._safe_git_leaf`. Its false return means
the filesystem item is absent; it is an intentional predicate contract. The
change scan finds zero new pattern or exception-fallback candidates. It finds no
clone groups in this repository; synthetic controls establish the clone fix.

Reviewed complexity findings in changed files:

| Callable or group | CC / SLOC | Decision and remaining risk |
|---|---|---|
| `_typing_bindings` | 28 / 35 | Retain explicit binding and mutation checks. Tests cover shadowing, alias mutation, import ordering, and dynamic writes. Runtime mutation remains beyond static proof. |
| `_guard` | 11 / 15 | Retain the two supported positive guard forms. Compound and negative conditions remain conditional. |
| `import_contexts` | 18 / 46 | Retain visible context precedence. Tests cover definition expressions, deferred bodies, generator iterables, and unknown annotations. New Python syntax needs explicit controls. |
| `_group_edges`, `_modified_members` | 14 / 24; 15 / 16 | Retain matching and ambiguity checks. Split/merge and multiple-site controls pass. Weak matches remain unresolved. |
| `CloneSyntaxIndex.run` | 11 / 20 | Retain complete-statement and unique-owner checks. No name-only identity claim. |
| `incomplete_details` | 13 / 43 | Retain metric-specific blockers and both source sides. Unchanged unsupported evidence does not establish a pass. |
| `render_architecture` | 11 / 31 | Retain source-located cycle edges and context labels. Output checks cover deferred/type-only cycles. |

Other hotspots in changed files are existing callable bodies: `_evidence`,
`_unassessed`, `_match_members`, `_package_members`, `_from_import`, and
`_dynamic_names`. No behavior defect was established from their complexity.
The measurements are valid observations; none justifies a project-specific
threshold change or a helper split solely to reduce the score.

Local evidence is under `.tmp/feedback-final-*.json`,
`.tmp/feedback-full-final.log`, `.tmp/feedback-public-final/`, and
`.tmp/feedback-distribution-verified.log`. These generated artifacts are not
committed. Broader calibration and independent holdouts remain future work.
