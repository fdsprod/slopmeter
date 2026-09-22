# Change evidence implementation checkpoint

Updated 2026-09-21 after the user resumed work with unrestricted filesystem
permissions. The earlier pause has ended. The implementation is in the source
checkout. Integrated tests and distribution checks passed. Final static and
working-tree checks follow this documentation commit. No push or release is claimed.

## Implemented scope

- `changes`: pattern, clone-member, and exception-fallback continuity, plus raw
  string state-dispatch evidence. Missing or ambiguous counterparts remain visible.
- Explicit advisory budget policies, with optional enforcement and separate pass,
  exceeded, and incomplete outcomes.
- `surface`: Python declaration and file changes, conservative moves, and a
  derived novel declaration ratio.
- `architecture`: direct static import edges, declared forbidden relationships,
  module fan-out, and cycles.
- `history`: bounded pinned first-parent history, source churn, and observed
  recent line rework.
- Shared enum outcome vocabularies and concrete variant dispatch. Wire strings
  remain compatible. No new detector weights, probabilities, or calibrated scores.

The [delivery plan](change-evidence-plan.md) gives the exact slice scope and maps
the remaining original research. The [README](../../README.md) documents commands,
policy formats, interpretation, source safety, and exit codes.

## Recorded work and focused checks

| Work | Evidence |
|---|---|
| Architecture learning/research | `6dbae98`; independent direct-import policy tests followed. |
| Pattern continuity test contract | `071e6c6`; separately authored from the implementation. |
| History learning/research | `27ea702`; five direct Git learning tests passed. |
| History test contract | `df4e1c7`; later independent tests cover merges, renames, timestamp order, parser failure, and imported reports. |
| History implementation/shared line alignment | `72cf653`; focused history/line-delta/learning run had 28 passing tests with CLI validation handled in integration. |
| Surface test contract | `7c954aa`, extended by `9086727`. |
| Surface implementation | `5202b66`; 24 independent API/CLI tests passed, with focused Ruff, formatting, and Pyright checks. |
| Enum wire learning | `8e1bd4d`; establishes Pydantic `Literal[StrEnum member]` JSON behavior. |

These are focused implementation records, not the final repository gate. Root
integration includes API/CLI wiring and later hardening. Record final results
below only after the actual runs finish.

## Evaluation limits

The [public example pilot](github-example-pilot-2026-09.md) inspected four selected
upstream fix/test pairs using pinned source. One AstrBot fallback case is
supported. PyRIT, Werkzeug, and NetworkX remain coverage-gap examples. Upstream
historical tests were not executed. The sample does not establish precision,
recall, or calibrated maintenance risk.

Synthetic controls, self-review, and independent public-source examples must stay
separate. Existing `.tmp/evaluation040` and calibration checkouts expose one
reachable commit each. They do not supply historical change pairs without more
history. Calibration repositories are not new held-out projects.

The existing inventory can report excluded files only as aggregate counts for a
language/cohort, without their paths. An exclusion can therefore make all
unmatched additions/removals in that population unresolved. Matched source
relationships remain usable. Do not report these conservative counts as complete
change counts or relax uncertainty merely to make enforcement pass.

## Integrated validation

Runtime: Windows, Python 3.12.14. Root orchestration recorded these results after
freezing the implementation source:

| Check | Result |
|---|---|
| Main test suite | 1,962 passed, four skipped. Distribution checks ran separately. |
| Coverage | 93.25%, above the required repository threshold. |
| Learning and performance suites | 69 passed, one skipped. |
| Distribution tests | Four passed, covering wheel and source distribution. |
| Isolated installed command smoke checks | `changes`, enforced budgets, `surface`, `architecture`, and `history` passed for both artifacts. |
| Import contracts | All five passed. |
| Pyright | Zero errors. |
| Ruff | Source and tests passed. Final whole-repository check follows the learning-test formatting and temporary-directory cleanup. |
| Dependency audit | No known vulnerabilities in audited installed dependencies. The local package was skipped because it is not on PyPI. |

The source-only self-review compared baseline `73b9680` with the frozen working
source. Selection used `src/**/*.py` with generated markers disabled. Raw state
dispatch had 40 persisted occurrences, zero introduced/removed/unresolved
occurrences, and zero comparison limitations. This is a source-syntax result,
not an independent quality label.

The broader whole-project comparison withheld introduction/removal claims where
aggregate exclusion counts made correspondence incomplete. The source-only run
does not erase that limit or establish complete counts for the broader scan.

Final whole-repository Ruff/formatting, working-tree, and commit checks remain
for root orchestration after this documentation commit. A separate format-only
commit reflows one learning-test call without changing assertions.

Do not replace a failed or unavailable check with a completion claim. Keep the
command, runtime, outcome, and any justified limit with the final validation note.

## Working environment and ownership

Use a fresh dedicated `--basetemp .tmp/<run-name>` for test runs. Old external
pytest temporary directories had access errors before the permission change.
Temporary directory fixtures should set `GIT_CEILING_DIRECTORIES` so Git does not
discover the parent repository through ignored `.tmp` paths. Set `PYTHONPATH` to
the checkout's `src` directory when using the local test environment.

Independent tests remain owned by their authors. The user's untracked `.claude/`
directory is outside this change. Do not remove unrelated files while completing
validation. Source scans must not execute target code, target configuration,
external diff commands, or text converters. Normal scans do not fetch objects or
resolve external packages over the network.
