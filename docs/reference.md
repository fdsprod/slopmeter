# Slopmeter reference

[Back to the README](../README.md)

Detailed installation, measurement, configuration, and review contracts.
Start with the [quick start](../README.md#quick-start) for a first scan.

## Contents

- [Installation options](#installation-options)
- [Read a score or give it to an agent](#read-a-score-or-give-it-to-an-agent)
- [Read a snapshot](#read-a-snapshot)
- [Compare directories](#compare-directories)
- [Compare Git revisions](#compare-git-revisions)
- [Review introduced evidence](#review-introduced-evidence)
- [Measure declaration surface](#measure-declaration-surface)
- [Check declared architecture](#check-declared-architecture)
- [Inspect observed history](#inspect-observed-history)
- [Follow the evidence](#follow-the-evidence)
- [Experimental data-model review](#experimental-data-model-review)
- [Experimental variant review](#experimental-variant-review)
- [Experimental derived-state review](#experimental-derived-state-review)
- [Experimental exception fallback review](#experimental-exception-fallback-review)
- [Development checks](#development-checks)
- [Ownership and clone review](#ownership-and-clone-review)

## Installation options

For a command available across projects, follow the
[release quick start](../README.md#quick-start). The wheel URL pins v0.6.0.
To install a later release, repeat `uv tool install` with that release's wheel URL
from [GitHub Releases](https://github.com/fdsprod/slopmeter/releases).
`uv tool upgrade slop-measure` does not select a new URL for a pinned wheel.
To uninstall, run `uv tool uninstall slop-measure`.

### Install with pip

The same wheel is installable with pip into your chosen Python environment:

```text
python -m pip install https://github.com/fdsprod/slopmeter/releases/download/v0.6.0/slop_measure-0.6.0-py3-none-any.whl
```

Use Python 3.12 or later. With pip, activate that environment or put its scripts
directory on `PATH` to run `slop` directly. The user-level uv installation above
handles this separately from your project environments. Official releases are
currently distributed through GitHub; these instructions do not claim a PyPI
publication under `slop-measure`.

### Install from source

Use Python 3.12 or later; the test matrix covers Python 3.12, 3.13, and 3.14.
Clone this repository and install into a virtual environment.

**Windows PowerShell:**

```powershell
git clone https://github.com/fdsprod/slopmeter.git
cd slopmeter
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\slop.exe score . --lang py --top 10
```

Replace `-3.12` with `-3.13` or `-3.14` if that is your installed Python version.
To scan another project, run this from the Slopmeter checkout:

```powershell
.\.venv\Scripts\slop.exe score C:\path\to\your-project --lang py --top 10
.\.venv\Scripts\slop.exe score C:\path\to\your-project --lang py --json
```

**macOS or Linux:**

```sh
git clone https://github.com/fdsprod/slopmeter.git
cd slopmeter
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/slop score /path/to/your-project --lang py --top 10
```

Check that `python3` is version 3.12 or later. These commands do not require
activating the environment. With an activated environment, use `slop` directly.
There is no need to copy this tool into the target repository.

For development, use uv **0.11.14**, pinned in `pyproject.toml`:

```text
uv sync --all-groups --locked
uv run slop score . --lang py --top 10
```

The `uv run slop` examples below assume you are in this checkout. With the pip
installation, replace `uv run slop` with your environment's `slop` executable.
After pulling updates, repeat `pip install .` or `uv sync --all-groups --locked`.

Git must be on `PATH` for revision analysis and Git ignore discovery. Directory
analysis works without Git, using configured exclusions. Calibration profiles
are packaged with the tool; normal scans require no network access.

## Read a score or give it to an agent

Lower scores indicate less measured redundancy and excess complexity under the
selected calibration profile. A high score is a reason to inspect source, not an
instruction to refactor it. A low score does not prove correctness. Raw percentages
and calibrated points are different measurements.

Snapshot and ordinary comparison reports include **How to read this report**. Use `--verbose` for
the full guide or `--json` to give an agent structured measurements, provenance,
and interpretation together. Findings JSON also retains diagnostics, coverage,
and excluded directories, so empty findings do not conceal incomplete analysis.

A useful instruction for an agent is:

> Read the report's interpretation and check coverage and diagnostics first.
> Inspect the source behind the highest-ranked results. For each candidate,
> report a location, evidence, an actionable/defer/no-change disposition, a
> concrete reason, remaining risk, and the next step. Do not change code merely
> to lower a score.

The default profile is **`py-2026.3`**. Erosion grows gradually above the complexity
threshold, and its score contribution scales with raw severity. A small excess
therefore cannot dominate solely because it is unusual in the reference corpus.
Scores from the previous profile are not directly comparable. Flat predicates
can still be overstated, and difficult algorithms can be understated; these limits
are included in the guide.

Scanning this repository includes the deliberately malformed
`tests/fixtures/basic/bad.py`. Its parse diagnostic is expected and can make the
test cohort partial. Use `slop score src --lang py` to inspect only the tool source.

## Read a snapshot

Use the project environment to run a scan:

```text
uv run slop score .
uv run slop score . --lang py --top 10
uv run slop score tests/fixtures/basic --json
uv run slop score . --scope all --ascii --no-color
uv run slop score . --verbose --top 10
uv run slop tree src
uv run slop explain src/slop_measure/api.py --root .
uv run slop explain src/slop_measure/api.py --root . --symbol scan
uv run slop score . --strict
```

The default scan continues after file errors. `--strict` stops with exit code 3.
Invalid arguments or configuration return exit code 2. Snapshot findings do not
cause a failure. Explicit change-budget enforcement has separate outcomes below.
`scan` remains an alias for the same snapshot analysis. `--scope` and
`--top` select terminal results. JSON always contains the complete report.

Use `--lang py` to select Python before files are read or analyzed. `--langs` is
an alias. Both options accept comma-separated names and can be repeated. Language
IDs and file extensions are accepted, so `python`, `py`, and `.py` select the same
analyzer. This release includes only Python; other language names return an input
error. Without a selection, all installed analyzers are used. Set
`languages = ["python"]` in `slop.toml` to keep that selection for a project.

In a Git working tree, discovery respects Git ignore rules, including nested
`.gitignore` files. Tracked files remain eligible even when an ignore rule matches
them. Ignored directories are skipped without walking their contents. Reports
show their directory count; `--verbose` and JSON also show their paths and reasons.
Their unknown file counts are not added to coverage totals. Without Git, configured
whole-directory exclusions such as `vendor/**` also skip traversal.

From PowerShell, run the installed command directly with:

```powershell
.\.venv\Scripts\slop.exe score . --lang py --top 10
```

The summary shows measured percentages and bars first. Lower values mean less
flagged code. These raw percentages are not calibrated scores. Unavailable metrics
show a reason instead of a bar. Production and test results stay separate. File
rows show the highest calibrated scores first when a compatible profile is available.

`tree` shows files under their directories. `explain` shows a file's metrics,
findings, and callable facts. `--symbol` selects an exact qualified callable name.
If that name occurs more than once, add `--line` with its definition start line.

Color is automatic for a terminal and disabled for redirected output or `NO_COLOR`.
Use `--color always` to force color, `--no-color` to disable it, and `--ascii` for
plain character bars and tree branches. Narrow views remove secondary columns.
The CLI also falls back to ASCII when the output encoding cannot represent its
display characters, including Windows CP1252 output streams.

The Python API returns the same report as the CLI:

```python
from pathlib import Path

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan

report = scan(SnapshotRequest(
    target=DirectorySourceReference(root=Path(".")),
    config=AnalysisConfig(),
))
print(report.model_dump_json(indent=2))
```

CLI settings merge in this order: defaults, `[tool.slop]` in the target root's
`pyproject.toml`, the target root's `slop.toml`, then explicit CLI arguments. API
requests receive resolved configuration and do not load files implicitly.

For example, a target-local `slop.toml` can set:

```toml
production_patterns = ["src/**/*.py"]
test_patterns = ["tests/**/*.py", "**/test_*.py"]
exclusions = [".venv/**", "vendor/**", "generated/**", "**/__pycache__/**"]
generated_markers = ["@generated", "Generated by"]
clone_min_statements = 2
clone_min_sloc = 6
complexity_threshold = 10
calibration_profile = "py-2026.3"
default_hotspot_count = 5
strict = false
```

Explicit lists replace their defaults. Threshold or rule changes can make the
packaged calibration incompatible; raw measurements remain available. Source,
rule-selection, and report-selection errors inherit `slop_measure.errors.InputError`.
Invalid API configuration or request models raise Pydantic `ValidationError`.
Strict analysis failures raise
`AnalysisFailure`. CLI input errors return 2, analysis failures return 3, and
completed advisory analyses return 0 even when findings are present. An explicit
`changes --enforce-budget` request can also return 1 for an exceeded budget.

M2 measures the fraction of source lines flagged by the twenty Python pattern rules.
Overlapping findings count each line once. Rules cover redundant expressions,
control flow, defensive code, and small abstraction patterns. JSON includes each
finding's rule ID, category, severity, source span, message, and review suggestion.
These findings identify code to review. They do not prove bugs or apply fixes.

Use rule IDs from the [catalog](../.specs/python-slop-detector/pattern-catalog.md) in
`slop.toml` to select or disable rules:

```toml
disabled_rules = ["py.single-use-return-binding", "py.trivial-wrapper"]
```

An empty `enabled_rules` set selects all rules. A nonempty set selects only those
IDs. Disabled rules are then removed. Unknown IDs are configuration errors.
The report records the selection and rule-set version. A pattern analyzer failure
makes M2 unavailable for that file and its cohort while preserving M4 results.

M3 measures the fraction of source lines in duplicated statement blocks. The
Python detector ignores whitespace and comments, including explicit line
continuations. It can match consistently renamed callable parameters and local
variables. Operators, literal spelling, external names, attributes, and keyword
names stay significant. Uncertain binding contexts retain exact names.

The default minimum is two direct statements and six SLOC. Set
`clone_min_statements` and `clone_min_sloc` to change those limits. Candidates are
complete executable runs within each suite, including nested suites. Imports,
definitions, and actual docstrings separate runs. Partial subranges within unequal
larger runs are outside this version's detection guarantee.

Clone groups stay within a language and cohort. Summary and explanation views
link each group to its member files and line spans. M3 counts overlapping clone
lines once. Combined verbosity unions M2 and M3 lines, so their overlap contributes
once. A clone analyzer failure makes M3 and combined verbosity unavailable for
the affected file and cohort while preserving M2 and M4.

M4 version 3 measures excess complexity gradually. In test files, `CC` below means
assertion-excluded complexity. Production files retain full Radon complexity.
Each function, method, or nested function contributes `CC * sqrt(SLOC)` total mass. Its excess mass is
`max(0, CC - threshold) * sqrt(SLOC)`. M4 divides summed excess mass by summed total
mass. With the default threshold of 10, a file with one CC11 function measures
9.1 percent, rather than the 100 percent produced by version 1. Set
`complexity_threshold` in `slop.toml` or `[tool.slop]` to change it. Project M4 uses
summed mass, not an average of file ratios.

Callable evidence retains full `cyclomatic_complexity` and `mass`. New Python
reports also show `assertion_count` and derived `control_flow_complexity`.
Test M4 uses the latter for both excess and total mass. This removes the incentive
to delete thorough assertions. It does not normalize every test style: Radon skips
boolean expressions inside plain `assert`, but counts them in method-call arguments.
Historical evidence without assertion counts remains explicitly unknown and uses
its original complexity when measured again.

Classification still uses file paths. An embedded self-check in a production file
remains production logic. Use a separate scan for demo/tooling strata when assembling
an evaluation corpus. The tool does not infer architecture or test intent from names
of callables.

JSON records every callable's name, source span, complexity, exact SLOC lines, and
mass. Verbose terminal output shows mass totals and the largest eroded callables. Files
without callables report `no-functions`. A complexity failure preserves source-line
counts and makes M4 unavailable for that file and its cohort.

Snapshot scores compare combined verbosity and erosion with a named reference
population. Each input has weight 0.5. In `py-2026.3`, erosion's contribution is
`percentile * raw erosion * weight`; combined verbosity uses `percentile * weight`.
This keeps a small excess from dominating merely because it is uncommon in the
reference population. Contributions record their transform and sum to the displayed
score. Individual metric percentiles remain available. M2 and M3 do not contribute
again. The project score uses project raw measurements and a project population;
it does not average file scores. Files use separate SLOC bands. Production and
test populations remain separate.

The default `py-2026.3` calibration profile uses M4 version 3 and the same six
pinned reference projects as earlier profiles. Both cohorts were rebuilt from source.
Historical `py-2026.1` and `py-2026.2` resources remain unchanged, but their
erosion distributions cannot score version 3 measurements. Do not directly compare scores across those profiles.

Snapshot and ordinary comparison views include **How to read this report**.
The compact guide explains score direction, common overstatements and
understatements, coverage limits, and an evidence-based review format. `--verbose`
adds metric definitions and review steps. JSON includes the full versioned
`interpretation` object; API reports and rule catalogs own the same guidance.
The rules command lists checks without scanning source.

A high score is a reason to inspect code, not a requirement to refactor. Flat
guards and short readable functions can score disproportionately; subtle algorithms
can score low. Record `actionable`, `defer`, or `no-change` with a source location,
evidence, a concrete reason, remaining risk, and the next step. Do not split code
only to lower its score or dismiss evidence only because a metric is imperfect.
The [nine-example review baseline](../.specs/python-slop-detector/scoring-review-baseline.md)
records the initial tuning cases and remaining limitations.

The percentile counts reference values strictly below the measured value. A raw
zero receives zero points. Contributions use one decimal place and sum exactly
to the displayed score. The profile defines the score bands. Callable-free files
can use a separate verbosity-only model when enough reference samples exist.
Missing or incompatible calibration leaves the raw evidence available.
Missing reference populations have their own `calibration-population-missing` reason.

Each new calibrated score records `reference_support`: file or project observation
count, file SLOC band when applicable, and a nominal percentile step of `100 / N`.
The terminal shows this beside the score. These counts describe the selected reference.
They are not confidence intervals. Domain match is explicitly **not assessed**.
Six project observations cannot establish a representative service-specific baseline.
A zero score with nonzero raw evidence includes an explanation of percentile zero or
rounding. Unavailable populations stay unavailable.

Use the affected/total SLOC and excess/total complexity mass with percentile ranks
when choosing what to inspect. Clone SLOC counts all occurrences, not removable lines.
Independent providers or deployables can justify duplication. Keep that evidence and
record the ownership decision instead of extracting shared code only to lower a score.
Configured architectural boundaries and persistent clone review dispositions add
review context without suppressing findings or changing scores. All-zero pattern results
provide no evidence of detector sensitivity without known positive examples.

The initial corpus contains six pinned 2019 Python project snapshots. It provides
a small, library-heavy reference, not a representative census or proof of code
authorship. Project percentile steps are coarse. File populations pool eligible
files, so larger projects have more influence. The
[corpus policy](../.specs/python-slop-detector/calibration-corpus-research.md) records
revisions, licenses, exclusions, and limits.

Test patterns take precedence over production patterns. Exclusions, Git-ignore
rules, and generated markers apply before parsing. Tracked Git files remain eligible
even if an ignore pattern matches them. The scanner does not execute source files
or traverse symbolic links and Windows junctions.

## Compare directories

```text
uv run slop compare path/to/before path/to/after
uv run slop compare path/to/before path/to/after --scope all --ascii --no-color
uv run slop compare path/to/before path/to/after --json
```

Both sides use the AFTER directory's resolved configuration. The comparison
retains both complete snapshots and their source-owned evidence. M1 records
baseline and current SLOC, added and deleted source lines, net change, and growth
rate. Growth is unavailable when baseline SLOC is zero. Size growth is not a
quality judgment, and M1 has no calibrated change-pressure score.

Equal paths match first. Remaining exact-content files can match as renames.
Duplicate content pairs in stable path order. Moves between production and test
populations are separate deletions and additions. Line comparisons ignore line
terminator differences, but exact directory rename matching uses complete bytes.

Raw metric changes are current minus baseline. Score changes require the same
profile and model. Added or deleted files have unavailable ratio comparisons;
their missing side is not treated as zero. Source failures preserve successful
results and diagnostics. The default view bounds file details; JSON keeps every
change, including unchanged files.

## Compare Git revisions

Git inputs read committed objects without a checkout:

```text
uv run slop score . --rev HEAD
uv run slop tree . --rev HEAD
uv run slop compare HEAD~1 HEAD --repo .
uv run slop compare HEAD WORKTREE --repo . --ascii --no-color
```

The directory must be the repository root. Branches, tags, and commit IDs resolve
to a full commit ID in the report. `WORKTREE` selects current tracked and eligible
untracked files. Both inputs use the repository's current configuration.
Git rename metadata can match edited renames. Missing revisions return exit code 2.
Analysis does not change the index or working tree, fetch objects, or run source
files. Symbolic links and submodules are excluded.

## Review introduced evidence

`changes` compares the existing detectors' evidence across two source states.
It reports what appeared, persisted, changed, or disappeared. It keeps uncertain
matches unresolved. It does not alter snapshot scores or saved review validity.

```text
slop changes path/to/before path/to/after --lang py
slop changes HEAD~1 HEAD --repo . --lang py --json
slop changes HEAD WORKTREE --repo . --config review-config.toml
```

Directory, Git, `WORKTREE`, and configuration selection follow `compare`.
The JSON report contains these independent evidence families:

| Field | Meaning and supported scope |
|---|---|
| `patterns` / `summary` | Introduced, removed, persisted, changed, or unresolved occurrences from the existing Python pattern rules. |
| `clones` | Clone member relationships and group outcomes: introduced, removed, persisted, changed, expanded, contracted, or unresolved. Adding a third copy remains visible when a group already existed. |
| `errors` / `error_summary` | Changes in the existing literal exception-fallback candidates. `error_coverage` retains analyzed and unresolved handlers on both sides. |
| `state_dispatch` / `state_dispatch_summary` | Changes in direct raw-string comparisons against `.state` in assertions, `if`, and `while` conditions. |

Source hashes, spans, populations, diagnostics, and matching limits remain in the
report. A line shift can preserve a finding. A failed parse, excluded counterpart,
or ambiguous match cannot establish that an old finding was fixed. Clone matching
uses the existing normalized syntax vocabulary. It does not prove equivalent
behavior between different implementations. Group splits and competing matches
can remain unresolved.

For edited Python clone runs, correspondence requires a mapped file, a unique
declaration and statement suite, and a majority of unchanged complete statements
with at least two distinct anchors. A matching file or function name alone is
insufficient. Supported edits become `changed` members, counted in `modified`,
with separate `baseline_fingerprint` and `current_fingerprint` fields. Editing
four existing copies can therefore report four modifications and zero additions;
adding a fifth copy still reports one addition. Weak matches and competing group
relationships remain unresolved. This does not renew a stale review.

Excluded files can appear only as aggregate language/cohort counts in the existing
inventory. Without their paths, an exclusion can make all unmatched additions
and removals in that population unresolved. Matched source relationships remain
usable. Do not read the remaining counts as complete change counts when these
limits are present.

The exception check retains its narrow scope. It finds supported handlers that
return literal defaults where another return provides a different result.
It does not infer whether the caller treats that value as success. Inspect the
caller contract before changing an intentional predicate or sentinel return.

The raw state check supports `==`, `!=`, `in`, and `not in` with literal strings.
It includes boolean combinations in the supported test contexts. Enum member
comparisons and concrete variant checks are outside this candidate pattern.
The report does not infer receiver types or the semantic domain. A `.state` field
can contain geographic values, lifecycle values, or another vocabulary. Inspect
the receiver and caller contract before recommending a type or behavior change.
A literal comparison is review evidence, not proof of a bug.

Finding continuity and review validity serve different purposes. Exact file
changes can invalidate a saved review even when its finding persists. These new
reports do not automatically approve, suppress, or migrate review decisions.

### Explicit change budgets

Save a separate policy file, for example `budget.toml`:

```toml
[[limits]]
metric = "introduced-patterns"
maximum = 0

[[limits]]
metric = "added-clone-members"
maximum = 0

[[limits]]
metric = "introduced-errors"
maximum = 0
```

These are the three supported budget metrics. Limits must be nonnegative integers
and each metric can occur once. Omitted metrics have no cap. The values above are
an example policy, not calibrated recommendations. Budgets do not currently cover
raw state tests, symbol surface, architecture violations, or history.

```text
slop changes HEAD~1 HEAD --repo . --budget budget.toml
slop changes HEAD~1 HEAD --repo . --budget budget.toml --enforce-budget --json
```

Budget output links observed introductions to source evidence. Existing unchanged
debt does not consume an introduction budget. Unsupported or unresolved evidence
can make a check incomplete. An incomplete budget takes precedence over an
exceeded result, while each check still exposes its observed count and cap.

Each check includes `incomplete_details`: a reason code, message, and source side,
path, and span when known. Aggregate limits use population scope. Old comparison
limits that do not record a source side retain that uncertainty in the message.
The text-only `incomplete_reasons` field remains available for older readers.
An unchanged unsupported handler still makes the error check incomplete; a lack
of observed introductions does not establish that all introductions were assessed.

Without `--enforce-budget`, a completed budget report is advisory and returns 0.
With `--budget --json`, output has `report` and `budget` objects. Without a budget,
JSON is the change report itself.

| Exit code | Meaning |
|---|---|
| `0` | Completed advisory report, or an enforced budget passed. |
| `1` | Explicitly enforced budget exceeded. |
| `2` | Invalid input, policy, source selection, or missing required option. |
| `3` | Enforced budget incomplete, or strict analysis failed. |

`--enforce-budget` requires `--budget`. A missing or invalid policy cannot silently
disable enforcement. Architecture and history commands remain advisory.

## Measure declaration surface

```text
slop surface path/to/before path/to/after --lang py
slop surface HEAD~1 HEAD --repo . --json
```

`surface` reports added, removed, modified, moved, unchanged, and unresolved Python
declarations. It includes classes, synchronous and asynchronous functions, methods,
and nested declarations. Each occurrence retains its qualified name, source span,
file hash, and AST fingerprint. Comments and formatting do not change that
fingerprint. Names, literals, annotations, and decorators remain significant.

The novel declaration ratio is `added / (added + modified)`. Removed, moved, and
unchanged declarations are outside its denominator. Empty denominators and
incomplete correspondence produce an unavailable ratio. This is a structural
count, not a historical percentile or a judgment that a change is too large.
Changing a method can count both the method and its containing class as modified.

Unique exact syntax moves can preserve declarations across files. Git rename
evidence can support a renamed-and-edited file. A possible declaration rename,
move with edits without that evidence, duplicate qualified name, or competing
move remains unresolved. Moves between production and test cohorts remain
separate additions and removals. Failed or excluded counterpart source cannot
prove that unmatched declarations were added or removed.

## Check declared architecture

Save a separate `architecture.toml` with roots relative to the analyzed repository:

```toml
source_roots = ["src"]

[[forbidden]]
source = "app.controllers"
target = "app.storage"
```

```text
slop architecture --root . --policy architecture.toml --lang py
slop architecture --root . --rev HEAD --policy architecture.toml --json
```

Rules forbid direct imports between the named modules and their descendants.
The report includes source-located internal edges, violations, module fan-out,
and cycles as strongly connected components. Ownership boundaries used for clone
review do not establish import permissions.

This resolver reads selected Python source. It does not run Import Linter target
configuration or import target packages. Conditional imports describe possible
source relationships, not guaranteed runtime execution. External imports are not
resolved against installed packages or registries. Dynamic imports, star imports,
missing internal modules, and ambiguous package members remain unresolved.
The command does not enforce transitive layer rules or fail on a violation.
Check coverage before interpreting an empty violation list.

Each import observation has a `context` with `execution` (`eager`, `deferred`, or
legacy `unknown`) and `guards` (`conditional` and/or `type-checking`). Function
bodies are deferred; class bodies use their enclosing context. Positive guards
using an unshadowed module-level `typing.TYPE_CHECKING` import or alias receive
the type-checking label. Other conditions remain conditional. Shadowing checks are
conservative and do not execute code or resolve runtime mutation.

Annotation and lazy type-alias expressions retain `unknown` timing. Their
evaluation depends on Python version and annotation policy. Observed dynamic
namespace writes or mutation of a typing alias prevent a type-checking claim.

Cycle output includes edge paths and contexts. Type-checking and deferred edges
remain in the static graph and in declared-rule checks; their presence alone
does not prove an import-time failure. Old reports without context load as unknown.
New context, clone-continuity, and budget-detail fields are additive; older strict
report readers can reject them. Snapshot score reports and calibration are unchanged.

## Inspect observed history

```text
slop history HEAD~20 HEAD --repo . --window-days 14 --max-commits 100
slop history BASE_COMMIT END_COMMIT --repo . --lang py --json
```

History pins both endpoints and reads the first-parent range `(start, end]`.
Each step compares a commit with its first parent. A merge counts integrated
source once. The report keeps source-line additions, deletions, churn
(`added + deleted`), and net growth separate. It does not execute target code,
check out a revision, or fetch missing history.

Rework means a source line introduced in the observed range was later removed
or replaced. Its introduction and removal timestamps determine whether its age
falls within `--window-days`. Anchor lines have unknown introduction ages.
Backdated removal timestamps remain unresolved. Exact file renames preserve
known origins. Formatting and block moves can contribute to line churn, so the
count is not a measure of semantic rewriting.

The default limit is 100 commits and the default recent-age window is 14 days.
A commit limit or missing parent produces explicit partial traversal. Missing
source objects raise an input error. Parse failures retain unavailable counts
and diagnostics. A complete requested range can exist inside a shallow repository.
No overall rework percentage, future defect prediction, or history score is added.

### New Python entry points

The CLI and API use the same reports. Import these functions from `slop_measure.api`:

| Function | Inputs |
|---|---|
| `review_change` | Existing `ComparisonRequest` |
| `review_surface` | Existing `ComparisonRequest` |
| `evaluate_budget` | Change report and `domain.budgets.BudgetPolicy` |
| `inspect_architecture` | Existing `SnapshotRequest` and `domain.architecture.ArchitecturePolicy` |
| `analyze_history` | `domain.history.HistoryRequest` with `root`, `start`, `end`, `config`, `window_days`, and `max_commits` |

API callers supply resolved configuration. Source, budget, and architecture
policies do not load implicitly. All new evidence stays separate from calibrated
snapshot scores. The [delivery plan](../.specs/python-slop-detector/change-evidence-plan.md)
records the implemented slices and the remaining research backlog.

## Follow the evidence

```text
uv run slop findings --root . --metric m2 --severity warning
uv run slop findings --root . --path src/slop_measure/api.py --json
uv run slop findings --root . --metric m4 --top 10
uv run slop rules --root .
uv run slop rules --root . --json
uv run slop explain old.py --root after --baseline-root before --source baseline
uv run slop explain src/app.py --root . --rev HEAD --baseline-rev HEAD~1
uv run slop findings --root . --baseline-rev HEAD --source baseline --json
```

`findings` lists pattern findings, complete clone groups, and callables above the
configured complexity threshold. Filters compose: `--path` selects an exact
project-relative path, `--metric` selects `m2`, `m3`, `m4`, or `combined`, and
`--rule` selects an exact pattern rule ID. `--severity` accepts `info`, `warning`,
or `error`. Rule and severity filters select patterns only because clone groups
and callables have no rule ID or severity. Selecting a clone member keeps its
complete group visible. `--top` limits terminal records only.

Findings JSON contains analysis identity, provenance, interpretation, coverage,
diagnostics, excluded directories, and all matching evidence.
`explain --json` continues to return the complete analysis report. `rules` lists
the installed catalog version, metadata, and configured enabled state without
analyzing source files.

Comparison explanations select current evidence by default. Use `--source baseline`
for deleted files or the old path of a rename. The view includes the selected file's
evidence and its whole-file change. Callable views show raw facts, not a callable
score or callable-level LOC delta. `--baseline-root` and `--baseline-rev` cannot be
combined. A baseline revision uses the repository given by `--root`.

## Experimental data-model review

### Coverage summaries

Version 0.5.0 adds a coverage summary before the detailed output of `models`,
`variants`, and `derived`. The JSON report includes the same computed `summary`:

| Count | Meaning |
|---|---|
| Files analyzed / failed | File outcomes; a parsed file may contain no supported subjects |
| Encountered | Class declarations, match handlers, or functions in parsed files |
| Assessed / unresolved | Subjects inside / outside the experiment's supported scope |
| Findings | Model or derived-state candidates; missing/fallback variant handlers |
| Unresolved reasons | Counts grouped by the stated reason |

`Nothing assessed` means the experiment could not assess any subject. It differs
from assessed subjects with no findings. Neither result establishes correctness.
Class counts include ordinary classes and test fakes; they are not counts of
identified business models or a measure of detector recall. Failed files have no
inferred class, handler, or function count. Exhaustive variant handlers count as
assessed, but not as missing/fallback findings.

Summaries are derived from detailed outcomes. The current reader accepts older
reports without a summary and rejects supplied summaries that contradict the
evidence. Saved review identities and detector eligibility are unchanged. These
reporting changes first appear in v0.5.0.

### Coupled-state evidence

The `models` command includes an experimental coupled-state check. It is separate
from calibrated scores:

```powershell
slop models --root . --lang py
slop models --root . --config C:/reviews/slop.toml --json
```

The check looks for a same-file dataclass with a boolean field and a nullable
`T | None` field. Its `__post_init__` must explicitly reject a combination, and at
least two distinct functions typed with that model must repeat the same guard.
The report shows the field declarations, rejecting predicate, and consumer
locations. Field shape alone never creates a finding. This version checks only the
first statement after a docstring in each validator or consumer. All directly
annotated fields must use the supported boolean or nullable forms. Custom
constructors, disabled dataclass initialization, and replaced fields are unresolved.

A finding means **review repeated validation**, not remove it. Separate trust
boundaries can require the same check. Consider a tagged union only when it fits
the domain and preserves public or stored data contracts. Do not split a model or
remove checks merely to reduce duplication.

This first experiment resolves direct dataclass imports, including import aliases,
and local bare model annotations, including quoted names. Predicate matching
normalizes only the receiver name. It does not prove logical equivalence or follow
cross-file consumers. Pydantic, TypedDict, inheritance, nested models, `Optional`
aliases, and uncertain bindings remain unresolved. Reports list unresolved model
classes separately from analyzed models with no findings. No findings means only
that this narrow check found no qualifying evidence, not that a model is sound.

The command uses the normal source inventory, Git ignores, exclusions, generated
markers, and production/test classification. It reads source without importing or
executing it. Parse/read failures remain visible; `--strict` exits with code 3 on
analysis errors. The JSON report includes exact source hashes, effective config,
experiment version, related locations, skipped coverage, and diagnostics. There
is no score, M2 contribution, or automatic fix. Clone review stores do not cover
these experimental findings yet.

## Experimental variant review

Use `variants` to inspect explicitly typed `match` handlers:

```powershell
slop variants --root . --lang py
slop variants --root . --config C:/reviews/slop.toml --json
```

The report connects a same-file `Enum`, `IntEnum`, `StrEnum`, or named `Literal`
declaration to its handled and unhandled cases. It separates three outcomes:

- **Missing:** some declared cases have no unconditional branch or catch-all.
- **Fallback:** an unconditional catch-all covers cases without explicit branches.
  Review whether that fallback is intentional and appropriate.
- **Exhaustive:** every declared case has an unconditional explicit branch. This
  does not establish that the branch bodies are correct.

Guarded branches do not prove full coverage. An intentional partial handler can
receive a missing-case note; the tool cannot infer its contract. Type checkers
remain the broader check for exhaustiveness. This experiment uses local syntax
and does not resolve project imports or run a type checker.

The first version supports direct imports (including aliases), simple unique
string/integer enum values or all-`auto()` members, and string/integer `Literal`
aliases. It checks the first statement after a docstring in an undecorated top-level
function, with a fixed parameter typed as a local declaration. OR patterns and
capture/wildcard fallbacks are supported. Unsupported patterns, enum aliases,
custom enum behavior, nested or later matches, reassignment, and ambiguous bindings
are reported as unresolved. No finding means no qualifying evidence in this scope.

Version 0.5.0 gives specific reasons for unsupported handler scope or
signature, match placement, subject shape, annotations, bindings, declarations,
and patterns. It identifies the first blocking check, not every limitation in a
handler. These explanations do not expand the accepted syntax. They help decide
what source needs manual review; they are not instructions to rewrite code into
the detector's supported shape.

Like `models`, this command keeps source hashes, locations, discovery coverage and
failures visible. It supports external config and `--strict`, never executes source,
and has no score or M2 contribution. Both commands are available in v0.5.0.

## Experimental derived-state review

Version 0.5.0 adds the `derived` command:

```powershell
slop derived --root . --lang py
slop derived --root . --config C:/review-config/project.toml --json
```

It connects three locations: a stored `count = len(items)`, a length-increasing
mutation of `items`, and a later read of `count` without recomputation. The first
slice supports local list literals in straight-line functions, with `append`,
nonempty literal `extend`, and `insert`. Unknown calls, aliases, branches, object
fields, and uncertain bindings remain unresolved. Source is never executed.

A candidate may be an intentional snapshot. Review whether the consumer needs
the original count or the current count before changing code. Findings remain
experimental and have no effect on M2 or calibrated scores.

The [independent v0.4.0 evaluation](../.specs/python-slop-detector/independent-evaluation-040.md)
ran `models` and `variants` on pinned HTTPX, Rich, and Black snapshots. It found
very limited supported coverage, with no qualifying positive cases. The results
do not establish precision or recall. Synthetic controls are recorded separately.

## Experimental exception fallback review

The `errors` command is available in v0.6.0:

```powershell
slop errors --root . --lang py
slop errors --root . --config C:/review-config/project.toml --json
```

It looks for exception handlers that return a literal empty/default value while
the same function has another non-default explicit return outside its exception handlers.
For example, a handler that returns `[]` after a failed fetch can look like a
successful fetch with no results. Each candidate shows the caught exception,
protected source span and calls, fallback return, and other return locations.
Calls are possible operations; the report does not identify which call raised.
Operation evidence includes eager definition headers such as decorators and
defaults. It omits nested bodies, annotations, and lazy type expressions; an
empty call list does not prove that the protected body cannot raise. Calls or
yields in nested declaration annotations remain unresolved.

Supported fallbacks are `None` (including bare `return`), `False`, numeric zero,
empty strings/bytes, and empty list/dict/tuple literals. Named values and calls
such as `Failure(error)` remain unresolved. The detector does not infer exception
inheritance or return contracts. Logging before a fallback does not suppress a
candidate.

The first slice supports functions, async functions, methods, and nested functions.
Conditional handler flow, generators, `except*`, dynamic exception expressions,
and enclosing `finally` blocks remain unresolved. Normal-return evidence is
syntactic: it does not prove reachability or that callers treat a fallback as
success. Coverage counts exception handlers, not all functions or defects.

**An intentional fallback can be correct.** Check the caller contract: can it
distinguish an empty result from failure, and does it need to? Preserve a useful
fallback when appropriate. Consider an explicit failure result or propagation
only when the contract requires it. No automatic fix is proposed.

This command parses source without executing it. It preserves source hashes,
discovery coverage, diagnostics, and unsupported reasons. `--strict` fails on
analysis errors, not on findings or unresolved syntax. Findings are experimental,
unscored, and do not change M2 or calibrated scores. Independent positive and
negative controls do not establish real-project precision or recall.

The [initial source evaluation](../.specs/python-slop-detector/error-fallback-evaluation.md)
reviewed all 30 candidates in pinned HTTPX, Rich, and Black snapshots. Most were
intentional predicates or documented fallback values. No defect was confirmed.
This evidence supports review use, not automatic failure gates.

Save the JSON outside the scanned source, then retain an attributed review:

```powershell
slop errors --root . --json | Set-Content -Encoding utf8 C:/reviews/errors.json
slop review-report list --report C:/reviews/errors.json --kind error
slop review-report set TARGET_ID --report C:/reviews/errors.json --store C:/reviews/decisions.json --actor reviewer-name --disposition defer --reason "Check how callers distinguish unavailable data from an empty result."
slop review-report show --report C:/reviews/errors.json --store C:/reviews/decisions.json
```

These commands review a saved snapshot. Generate fresh JSON to check whether a
decision still applies. An error review resolved against a score report is
`not-in-selected-report`, not evidence that its source finding disappeared.

## Development checks

Use uv 0.11.14, the version pinned in `pyproject.toml`. Create or update the locked
environment:

```text
uv sync --all-groups --locked
```

Run the same checks that CI uses:

```text
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run lint-imports --no-cache
uv run pytest --cov=slop_measure --cov-report=term-missing
uv run pip-audit
uv build
uv run slop --help
```

CI enforces five package dependency boundaries and a 90 percent coverage floor with
branch measurement enabled. The normal suite runs unit, golden, and architecture
contract and integration tests. The malformed source fixture is excluded from code linting and type
checking.

Retained dependency learning tests run separately:

```text
uv run pytest tests/learning
```

Tree-sitter is constrained below 0.26. The retained coordinate regression test
reproduces invalid coordinate reads with 0.26.0 and passes with locked 0.25.2.

Release artifact tests run after `uv build`. Set `SLOP_RELEASE_DIST` to the absolute
`dist` directory and run `uv run pytest tests/integration/test_distribution.py`.
Set `SLOP_RELEASE_CONSTRAINTS` to requirements exported from the lock to keep runtime
dependencies pinned. The release CI performs both steps on each matrix platform.

The retained benchmark generates exactly 100,000 source lines and measures a full
scan in a fresh process:

```text
uv run python tools/benchmark.py --output .tmp/benchmark.json
uv run pytest tests/performance
```

The small benchmark tests run by default when that directory is selected. Set
`SLOP_RUN_PERFORMANCE=1` to include the full 100,000-SLOC test. Generated files remain
under unique directories inside `.tmp/benchmark`. Peak memory includes native parser
allocations. Timing starts before source discovery and ends after calibration;
fixture generation and terminal rendering are outside the measurement.

See the [release validation record](../.specs/python-slop-detector/release-validation.md)
for the original release gates. The
[review-context validation](../.specs/python-slop-detector/review-context.md)
records 1,290 deterministic tests, 50 learning tests, four package checks, and
96.98 percent branch-inclusive coverage on Windows Python 3.12. The 73 new workflow
and integrity checks also pass on Python 3.13 and 3.14. These are local results; the
[GitHub Actions workflow](../.github/workflows/ci.yml) defines the full nine-cell
Windows, macOS, and Linux matrix.

## Ownership and clone review

Declare boundaries explicitly in `slop.toml` (or `[[tool.slop.boundaries]]` in
`pyproject.toml`):

```toml
[[boundaries]]
name = "service-a"
prefix = "src/services/a"

[[boundaries]]
name = "service-b"
prefix = "src/services/b"
```

For `pyproject.toml`, use the same fields under the namespaced tables:

```toml
[[tool.slop.boundaries]]
name = "provider-a"
prefix = "src/providers/a"

[[tool.slop.boundaries]]
name = "provider-b"
prefix = "src/providers/b"
```

By default, put the configuration in the directory you pass as the scan root. A subdirectory
scan does not inherit boundary declarations from its parent. Rebase the prefixes
when using a different scan root. If both configuration files declare boundaries,
the `slop.toml` list replaces the `pyproject.toml` list.

External configuration and detailed stale explanations are supported.

To keep configuration outside the repository, select a file explicitly:

```powershell
slop score . --config C:/review-config/service.toml --lang py --top 10
slop findings --root . --config C:/review-config/service.toml --metric m3
slop review show --root . --config C:/review-config/service.toml --store C:/review-config/reviews.json
```

`--config` works on `score`, `scan`, `tree`, `compare`, `changes`, `surface`,
`architecture`, `history`, `explain`, `findings`, `rules`, `models`, `variants`,
`derived`, `errors`, `review set`,
and `review show`.
Put it after the command name. An explicit
file replaces both local config files. Settings come from defaults, then that file,
then CLI overrides such as `--lang` and `--strict`. A missing or invalid explicit
file is an error. The CLI does not fall back to local settings.

Use standalone Slop TOML for external files. A file named exactly `pyproject.toml`
uses its `[tool.slop]` table instead. Relative `--config` paths start at the shell's
working directory. Boundary prefixes and source patterns still start at the scan
root, not the config directory. Comparisons use the selected settings for both
source states. Reports retain effective settings, not the external config path.
Moving an identical config file does not invalidate reviews.

Names and normalized prefixes must each be unique. Absolute paths, `..`, and glob
patterns are rejected. For nested boundaries, a declaration for `src/providers/a`
takes precedence over one for `src/providers`.

Prefixes are paths relative to the scan root, not globs. The longest matching path
prefix wins. A clone group is `within-boundary` or `cross-boundary` only when every
member is assigned. Otherwise its relation is `unknown`, with unmatched files shown
as `unassigned`. A cross-boundary clone is not automatically intentional or actionable.
Boundary labels never change clone detection, metrics, calibrated scores, or ranking.

Save a reviewed clone decision with a reason:

```powershell
slop findings --root . --metric m3
slop review set CLONE_ID --root . --store reviews.json --disposition no-change --reason "These adapters evolve under separate contracts." --next-step "Check each adapter when the contract changes."
slop score . --lang py --reviews reviews.json
slop findings --root . --metric m3 --reviews reviews.json --json
slop review show --root . --store reviews.json --json
```

Dispositions are `actionable`, `defer`, or `no-change`. Only `review set` writes the
store. Scans and `review show` only read it. Review annotations preserve findings,
scores, and file order. The store is explicit and local; scans do not discover or
create one automatically.

A decision is `current` only when the clone evidence, exact member-file bytes,
configured boundary policy, and clone measurement definition still match. A source
edit can make it `stale` even if normalized clone tokens stay the same. The tool
hashes whole member files, so a comment or unrelated edit can also require review.
The policy fingerprint covers every boundary declaration. Adding an unrelated
declaration still requires review. If the group is absent or unavailable, its decision is `missing`, not fixed.
Review the source again before using `review set` to replace a decision. Historical
reports without source hashes cannot create or confirm a current decision.

Stale results explain changes for each candidate group. JSON includes structured
causes for changed source hashes, changed clone evidence, changed boundary policy,
changed clone analysis definition, or unavailable identity evidence. Terminal output
names changed member files and the affected components. These explanations do not
approve the old decision or change scores.

The tool cannot infer that an edit was harmless from a changed hash. Saved policy
and analysis fingerprints cannot identify an old declaration or threshold, so those
causes stay at the component level. Older reports without explanations remain
readable. Existing review stores need no migration. Use version control for review
history if needed; the store still replaces the decision for a given group ID and
does not record reviewer identity or timestamps.

Stores contain relative locations and hashes, not source text. They can still
contain sensitive paths and reviewer notes; choose where to keep them. Persistence
in this legacy workflow covers clone groups and the current snapshot side only. Use separate
stores for independent scan roots. Boundary prefixes are also relative to each root.

### Attributed review history for all finding types

The new `review-report` workflow reads saved native JSON from `score`, `models`,
`variants`, or `derived`. It supports clones, callable complexity, pattern findings,
model findings, analyzed variant handlers, and derived-state findings. Failed and
unresolved experimental results are not reviewable targets. This workflow is
available in v0.5.0.

Version 0.6.0 also accepts `errors` reports and the `error` review kind.
Only candidate exception fallbacks become review targets.

Save JSON using UTF-8. For example, in PowerShell:

```powershell
slop score . --lang py --json | Set-Content -Encoding utf8 snapshot.json
slop review-report list --report snapshot.json
slop review-report set TARGET_ID --report snapshot.json --store decisions.json --actor reviewer-name --disposition defer --reason "Review this workflow when its contract changes." --next-step "Check retry and failure paths."
slop review-report show --report snapshot.json --store decisions.json
```

Copy a target ID from `list`. Each write appends the explicit actor, UTC timestamp,
decision, rationale, next step, and evidence anchor. `show --json` includes full
history. To attach a fresh decision to an existing compatible history after the
evidence changes, pass `--review REVIEW_ID` to `set`. Earlier events remain intact.
The tool does not infer the reviewer's identity or automatically approve changes.

**These commands inspect the saved report, not the live checkout.** Generate a
fresh native report and run `show` against it to check applicability after edits.
Keep one explicit ledger per project and scan root. Relative paths and hashes do
not identify a repository globally. List and show do not write the ledger.

New clone decisions bind the effective ownership assignments of their members.
An unrelated boundary declaration leaves them current. A changed member assignment,
exact file bytes, relevant evidence, or detector definition makes them stale.
Stale output shows the changed files and hashes, evidence locations, or previous
and current ownership assignments. Comment-only edits still require review:
equal syntax does not establish that a reviewer note remains applicable.

Schema-1 clone stores remain readable. Their first explicit write through
`review-report set` preserves the old decisions under `legacy_decisions` in a
schema-2 ledger. Legacy anchors retain their whole-policy invalidation rule.
This does not reapprove or weaken old decisions. Use the new workflow for that
ledger afterward; the legacy `review` commands still use schema 1. Keep a copy if
you need both workflows. Missing evidence means absent or unavailable, not fixed.

### Review triage

The following changes are available in v0.6.0.

`review-report show` now distinguishes `not-in-selected-report` from `missing`.
A score report can assess clone, complexity, and pattern reviews. Each experimental
report can assess only its own family. Reviews from other families remain in the
output and history, but are not placed in a missing-evidence queue. This also
applies to retained legacy clone decisions. Within a supported family, `missing`
still means absent or unavailable evidence, never proof of a fix.

Select evidence from a saved report with list filters:

```powershell
slop review-report list --report snapshot.json --kind clone --kind pattern --cohort production
slop review-report list --report snapshot.json --kind complexity --cohort test --hotspots-only
```

Repeated kinds are combined with OR; cohort selection is applied with AND.
`--hotspots-only` selects callable complexity above the saved report's threshold.
It uses full CC for M4 v1/v2 and the cohort-specific basis for v3. Reports without
a known M4 basis and incompatible kind selections fail explicitly. The default
list still includes all callables and analyzed variant handlers, even exhaustive
handlers. Its size is a reviewable-evidence count, not a defect count. Filters do
not change targets, IDs, reports, scores, or ledgers.

To explicitly replace a legacy clone judgment, copy its ID from `show` and save
a new decision with `--supersedes`:

```powershell
slop review-report set TARGET_ID --report snapshot.json --store decisions.json --actor reviewer-name --disposition no-change --reason "Reviewed the current ownership and source." --next-step "Retain contract checks." --supersedes LEGACY_ID
```

This records the relationship in the new attributed event. It requires the same
clone language, cohort, and member paths; the reviewer must verify the semantic
relationship. Source evidence may have changed. No link is inferred automatically.
A legacy decision can have only one replacement history. Later decisions using
`--review REVIEW_ID` retain the original link, even without repeating `--supersedes`.

The legacy entry becomes `superseded` and points to the linking event and replacement
history. The original decision stays intact. The replacement independently resolves
as current, stale, missing, or outside the selected report. Superseded does not
mean approved, fixed, or currently applicable.

Resolution JSON now uses **schema 3** for these new states. Ledger storage stays
**schema 2**, with an optional `supersedes_legacy_id` on explicit linking events.
Existing ledgers load without migration; reads do not write them. Older versions
cannot consume schema-3 resolutions or ledgers containing the new event field.
Keep an unchanged copy if an older reader is still required.

`score --reviews` and the original `review` commands remain schema-1-only. Passing
a schema-2 ledger now gives instructions to generate a fresh saved report and use
`review-report show --report ... --store ...`. No automatic conversion occurs.

Callable explanations label the retained `mass` field as **full-CC mass**. They show
the version-specific M4 basis, effective CC, effective mass, numerator, and threshold
separately. File rankings include clone percentages at narrow and wide widths.
`Pattern findings (0)` counts pattern rules only, not complexity or clones.

Production callables whose assertions alone cause a threshold crossing receive a
classification-review hint. This does not move them into the test cohort or change
their score. Inspect intent before separating self-test scenarios or configuring
file-level test paths. Do not exclude a mixed-purpose file merely to lower a score.

### Public detector evaluation (source checkout)

The [public evaluation suite](../evaluation/README.md) retains pinned examples,
source hashes, review labels, and expected raw evidence. It includes a real
exception-fallback introduction and fix, an intentional fallback, and unsupported
derived-state and response-contract cases. These selected-file cases test evidence
and coverage. They do not establish defect precision or change calibrated scores.

Run `tools/evaluate.py` with the checked-in manifest and a verified source cache.
Source downloads require `--fetch`. Each run needs a new output directory. The
runner keeps full reports, checks expected values, and marks timeouts or incomplete
evidence explicitly. Target source and upstream tests are never executed. See the
suite documentation for commands, exit codes, and scope limits.
