# Slopmeter

Slopmeter is a Python code-review tool for people and coding agents. It measures
redundant patterns, duplicated code, and excess complexity, then shows the source
behind each result. It can scan a directory or compare directories and Git
revisions. It does not execute target code or apply fixes.

The command is **`slop`**, the Python package is **`slop-measure`**, and the import
name is **`slop_measure`**. Terminal reports use the internal name `slop.measure`.
Only Python analysis is currently implemented. This is an early 0.2.0 project;
scores are review signals, not defect probabilities or proof of AI authorship.

## Quick start

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
are packaged with the tool; normal scans require no network access. Installation
here is from source, not a claimed PyPI release.

## Commands

| Task | Command |
|---|---|
| Rank files in a project | `slop score PATH --lang py --top 10` |
| Get a complete machine-readable report | `slop score PATH --lang py --json` |
| Include test results in the terminal view | `slop score PATH --scope all` |
| View files by directory | `slop tree PATH --lang py` |
| Explain a file | `slop explain src/app.py --root PATH` |
| Explain one callable | `slop explain src/app.py --root PATH --symbol MyClass.method` |
| List matching evidence | `slop findings --root PATH --metric m4` |
| List available pattern rules | `slop rules --root PATH` |
| Compare two directories | `slop compare BEFORE AFTER` |
| Compare Git revisions | `slop compare HEAD~1 HEAD --repo PATH` |
| Compare a commit with local work | `slop compare HEAD WORKTREE --repo PATH` |

Run `slop --help` or `slop COMMAND --help` for all options. `scan` is an alias for
`score`. `--top` limits displayed rows, not analysis work. `--lang` filters files
before reading and analysis; `--langs` is an alias with comma-separated or repeated
values. Only installed language adapters can be selected.

## Read a score or give it to an agent

Lower scores indicate less measured redundancy and excess complexity under the
selected calibration profile. A high score is a reason to inspect source, not an
instruction to refactor it. A low score does not prove correctness. Raw percentages
and calibrated points are different measurements.

Every successful report includes **How to read this report**. Use `--verbose` for
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
Invalid arguments or configuration return exit code 2. Findings do not cause a
failure. `scan` remains an alias for the same snapshot analysis. `--scope` and
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
completed analyses return 0 even when findings are present.

M2 measures the fraction of source lines flagged by the twenty Python pattern rules.
Overlapping findings count each line once. Rules cover redundant expressions,
control flow, defensive code, and small abstraction patterns. JSON includes each
finding's rule ID, category, severity, source span, message, and review suggestion.
These findings identify code to review. They do not prove bugs or apply fixes.

Use rule IDs from the [catalog](.specs/python-slop-detector/pattern-catalog.md) in
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

Every successful analysis command and rules listing includes **How to read this
report**. The compact guide explains score direction, common overstatements and
understatements, coverage limits, and an evidence-based review format. `--verbose`
adds metric definitions and review steps. JSON includes the full versioned
`interpretation` object; API reports and rule catalogs own the same guidance.
The rules command lists checks without scanning source.

A high score is a reason to inspect code, not a requirement to refactor. Flat
guards and short readable functions can score disproportionately; subtle algorithms
can score low. Record `actionable`, `defer`, or `no-change` with a source location,
evidence, a concrete reason, remaining risk, and the next step. Do not split code
only to lower its score or dismiss evidence only because a metric is imperfect.
The [nine-example review baseline](.specs/python-slop-detector/scoring-review-baseline.md)
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
Persistent review dispositions and configured architectural boundaries are planned.
This version does not yet store or automatically apply them. All-zero pattern results
provide no evidence of detector sensitivity without known positive examples.

The initial corpus contains six pinned 2019 Python project snapshots. It provides
a small, library-heavy reference, not a representative census or proof of code
authorship. Project percentile steps are coarse. File populations pool eligible
files, so larger projects have more influence. The
[corpus policy](.specs/python-slop-detector/calibration-corpus-research.md) records
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

See the [release validation record](.specs/python-slop-detector/release-validation.md)
for the original release gates. The
[scoring and interpretation validation](.specs/python-slop-detector/scoring-interpretation-design.md)
records the latest change: 1,178 deterministic tests, 42 learning tests, four
package checks, and 96.81 percent branch coverage on Windows Python 3.12, with
focused checks on Python 3.13 and 3.14. These are local results; the
[GitHub Actions workflow](.github/workflows/ci.yml) defines the full nine-cell
Windows, macOS, and Linux matrix.
