# Offline history evidence

Research date: 2026-09-21. This is a design recommendation, not an implemented
history command. The first slice should report source-line churn and observed
recent rework. Neither measurement establishes a defect or AI authorship.

## Existing contracts to reuse

- [Git sources](git-design.md) resolve revisions once and read committed blobs
  without checkout changes. The runner disables replacement objects, lazy fetch,
  prompts, and filesystem monitors. Diff calls disable external diffs and textconv.
- [Comparison](comparison-design.md) already pairs paths and renames and records
  exact added/deleted source-line numbers. Its language-aware SLOC policy excludes
  comments and docstrings. Git `--numstat` counts physical lines and is not a
  substitute for that policy.
- [The specification](spec.md) separates change pressure from snapshot quality.
  Keep history evidence unscored until independent change-level evaluation exists.

Use the same source selection, adapter versions, and configuration for every
revision. Carry those identities into the history report. Do not import target
packages, execute their tests, invoke hooks, or fetch missing objects.

## External behavior established

Five learning tests in
[`test_history_behavior.py`](../../tests/learning/test_history_behavior.py)
passed against Git `2.51.0.windows.2` on Windows with Python 3.12. They interrogate
Git directly and reuse the existing isolated repository fixture. Retain them as
executable documentation outside the normal production test suite.

| Question | Observation | Design consequence |
|---|---|---|
| How should merges count? | First-parent traversal omits side-branch commits. A merge-to-first-parent diff includes the merged source change. | Select one explicit integration history. Do not sum all-parent diffs. |
| Can a parentless traversal entry establish a root? | A depth-one clone emits a parentless `rev-list` entry, but the raw commit still names its missing parent. | Inspect raw parent headers and shallow state; never count a shallow tip as all-new source. |
| Does blame follow an exact rename? | Parent-revision porcelain blame reports the original commit, original path, and original line after a whole-file rename. | Blame can support investigation, but is not by itself source-line introduction evidence. |
| Do commit timestamps follow ancestry? | A backdated child can precede its parent by timestamp. `rev-list --since` can stop before that newer-dated parent. | Enumerate bounded pinned ancestry before applying date policy. Record timestamp anomalies. |
| Does `git diff -w` identify formatting? | It hides a changed number of spaces inside a string literal. | Never use whitespace-insensitive diff as proof that behavior is unchanged. |

Existing learning tests already cover pinned blob reads, exact/edited renames,
NUL-delimited paths, symlinks, and gitlinks. Those tests were not duplicated.

## Minimal request and result

A request pins a repository, a start commit, an end commit, a positive recent-age
window in seconds, and a maximum number of commits. The start commit is an anchor:
the range is `(start, end]`. Require it to lie on the end commit's first-parent
chain. Arbitrary branch comparisons remain the existing comparison command's job.
An explicit end commit anchors the observation horizon; wall-clock time does not
silently alter the result. Report both full object IDs and the ancestry policy.

The first-parent choice measures integration into the selected branch. A squashed
or merged change is introduced at integration for this measure. It does not claim
to reconstruct the original authoring time or all activity on side branches.

Enumerate commit identities and raw parent headers without date-based early exit.
Read committer timestamps separately from traversal order. Use the first parent
as each step's baseline, including merge commits. For a verified real root, an
empty source inventory can supply the baseline. If a configured anchor, parent,
tree, or blob is unavailable, preserve the available evidence and report the gap.

Each commit step records its commit and first-parent IDs, committer timestamp,
paired paths, measured or unavailable added/deleted SLOC, and coverage. Reuse the
existing exact line-delta model. `churn = added + deleted` and `net = added - deleted`
are checked projections, not separate mutable values. A replacement can have
zero net SLOC and positive churn.

Prefer tagged outcomes over independent flags:

- A complete traversal contains its ordered steps and explicit anchor.
- A partial traversal contains observed steps and a reason, such as missing parent,
  shallow boundary, missing object, or commit limit. Partial totals must be labelled
  observed totals; they are not estimates of the missing history.
- A step's source comparison is measured or unavailable. A failed parser does not
  become a zero delta.
- A deleted line's recent-age assessment is recent, outside the window, or
  unresolved with a reason. An unresolved assessment does not enter the denominator
  of a recent-rework fraction as a negative case.

An invalid revision or invalid range is a request error. Available but incomplete
history is a coverage result. A later implementation must distinguish these paths.

## Rework meaning and line identity

Define the first measure narrowly: a source line was introduced on this
first-parent chain and was deleted or replaced by a later step within the requested
age window. Retain its introduction commit/path/line and its removal
commit/path/line. Count each introduction event at most once as reworked. A newly
written replacement has its own introduction event.

Track line identity forward using the existing byte-line comparison and paired
paths. Carry introduction identity across aligned unchanged lines and exact file
renames. Intersect line mappings with each side's SLOC membership; a line newly
classified as source is a new SLOC introduction even if its bytes did not change.
This is one reason Git blame alone cannot supply the metric. Another is that blame
can attribute merged lines to side-branch commits excluded from the chosen history.

For each removal with a known introduction, calculate age from the two committer
timestamps. An age in `[0, window]` is recent. A negative age is an explicit
timestamp anomaly, not zero or an absolute-value duration. An unknown introduction
age remains unresolved until enough predecessor history is available.

The start snapshot's lines have unknown introduction ages. To classify their early
removals, optionally inspect predecessor commits within the explicit work limit.
Do not stop at the first old timestamp: later ancestry can contain newer dates.
If the history limit or missing objects prevent establishing an introduction,
report it as unknown. Do not claim a complete rework rate from the anchor alone.

For a first release, report rework events and their eligible/unknown population
instead of one overall percentage. Future survival measurements need both a
follow-up window and a censoring policy: a line introduced near the end commit
has not had a full observation window. It is not a demonstrated stable line.

## Moves, formatting, and limits

Whole-file renames use the existing conservative pairing contract. An unchanged
rename creates no churn and preserves known line introductions. Edited renames
retain exact changed lines. Ambiguous pairing stays visible.

Arbitrary intra-file or cross-file block moves are not proven identities in the
first slice. They may contribute to observed line churn. Report that limitation;
do not describe such churn as semantic rewriting or automatically penalize it.
Future move detection needs its own supported and ambiguous outcomes.

Line-ending and final-newline normalization should remain the existing comparison
policy. Formatting edits otherwise contribute to physical source-line churn.
Neither `-w` nor equal AST structure proves absence of meaningful changes in
Python, especially for strings, annotations, tooling directives, and indentation.
Do not silently discard those events under a broad formatting filter.

Keep normal history scans offline. Detect shallow repositories, inspect raw
parents, and retain missing-object failures. A complete requested first-parent
range can still be available inside a shallow repository; repository shallow state
alone must not invalidate an otherwise complete range. It can limit introduction
age coverage beyond the anchor.

## Local public-source inventory

Only names and pinned commit identities are recorded here. On 2026-09-21, all nine
checkouts below were shallow and exposed exactly one reachable commit. None can
supply an independent historical change pair without acquiring more history.
The first three were prior evaluation inputs; the remaining six were calibration
inputs and must not be presented as a new held-out population.

| Local public checkout | Pinned HEAD |
|---|---|
| `.tmp/evaluation040/black` | `8a737e727ac5ab2f1d4cf5876720ed276dc8dc4b` |
| `.tmp/evaluation040/httpx` | `26d48e0634e6ee9cdc0533996db289ce4b430177` |
| `.tmp/evaluation040/rich` | `2dca1b70359dac61e1bbfb6f14ebe19a5ab79c3d` |
| `.tmp/calibration/attrs` | `7fcd616aabb4067b07a5bded22bc578d35f9e14d` |
| `.tmp/calibration/flask` | `ffc68840f821fb0a4c41a7b2b4eaad6d71f539b7` |
| `.tmp/calibration/networkx` | `fd0ecd22723cb30a365511d324841a85caad589c` |
| `.tmp/calibration/pytest` | `068ef90b92a9e9205af31cb3d82e7d2a433ff969` |
| `.tmp/calibration/requests` | `aeda65bbe57ac5edbcc2d80db85d010befb7d419` |
| `.tmp/calibration/sphinx` | `bea7b5d4777d6b1216213b6c58eee0c3d133ca94` |

## Evaluation before scoring

Use synthetic histories to verify exact mechanics: zero net with positive churn,
recent replacement, unchanged rename, edited rename, merge, shallow boundary,
missing objects, backdated commits, syntax failures, SLOC membership transitions,
and an introduction near the observation horizon. Keep these labelled as controls.
They establish accounting behavior, not real-world usefulness or precision.

Select a separate public change sample before scanning. Record repository, commit
pair, selection method, source role, observation horizon, and whether the project
or change informed implementation. Prior evaluation inputs may be reused for
regression checks, but are not newly held-out evidence. Calibration projects do
not validate out-of-sample calibration performance.

Review source and requirements independently of detector output. Labels should
distinguish actionable maintenance concern, intentional keep, unsupported case,
and insufficient evidence. Preserve reasons and disagreement rather than deriving
labels from detector findings or churn alone. Agent reviews are provisional;
they must not be represented as independent human ground truth.

Report supported-case coverage, unresolved reasons, actionable precision among
adjudicated emitted findings, and review effort. Recall requires independently
identified positive cases, including cases the detector did not emit. A sample
with zero positive labels cannot establish recall. The earlier
[independent evaluation](independent-evaluation-040.md) correctly reports this limit.

To test whether introduced findings predict rework, freeze findings at introduction
and measure later history without using later information to tune that same sample.
Define follow-up length and incomplete observations before scoring. Compare change
size and source role so that larger changes do not win solely by exposing more
lines. Report association, not proof that a finding caused the rework.

Keep new evidence unscored until those labels and an evaluation split exist.
No independent positive change labels were acquired by this research task.
