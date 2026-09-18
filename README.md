# slop.measure

`slop.measure` detects redundant and structurally eroded source code. The first
release targets Python and provides the `slop` command plus an importable API.

The raw scan reports Python source lines, production and test coverage, excluded
files, diagnostics, M2 pattern verbosity, M3 clone verbosity, their combined line
union, and M4 structural erosion. Compatible calibration profiles add file and
project scores. Directory comparisons add exact M1 and metric changes. M1 remains
unavailable for snapshots. Git revision scans arrive in the next slice. See
`.specs/python-slop-detector/` for the design and checkpoint.

## Read a snapshot

Use the project environment to run a scan:

```text
uv run slop score .
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

M4 measures the share of callable mass above the complexity threshold. Each
function, method, or nested function contributes `CC * sqrt(SLOC)` mass. The default
threshold is `CC > 10`. Set `complexity_threshold` in `slop.toml` or `[tool.slop]`
to change it. Project M4 uses summed mass, not an average of file ratios.

JSON records every callable's name, source span, complexity, exact SLOC lines, and
mass. Verbose terminal output shows mass totals and the largest eroded callables. Files
without callables report `no-functions`. A complexity failure preserves source-line
counts and makes M4 unavailable for that file and its cohort.

Snapshot scores compare combined verbosity and erosion with a named reference
population. Each input contributes half the score. M2 and M3 do not contribute
again. The project score uses project raw measurements and a project population;
it does not average file scores. Files use separate SLOC bands. Production and
test populations remain separate.

The percentile counts reference values strictly below the measured value. A raw
zero receives zero points. Contributions use one decimal place and sum exactly
to the displayed score. The profile defines the score bands. Callable-free files
can use a separate verbosity-only model when enough reference samples exist.
Missing or incompatible calibration leaves the raw evidence available.

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

Both sides use the current directory's resolved configuration. The comparison
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
contract tests. The malformed source fixture is excluded from code linting and type
checking.

Retained dependency learning tests run separately:

```text
uv run pytest tests/learning
```

Tree-sitter is constrained below 0.26. The retained coordinate regression test
reproduces invalid coordinate reads with 0.26.0 and passes with locked 0.25.2.
