# slop.measure

`slop.measure` detects redundant and structurally eroded source code. The first
release targets Python and provides the `slop` command plus an importable API.

The raw scan reports Python source lines, production and test coverage, excluded
files, diagnostics, M2 pattern verbosity, and M4 structural erosion. M1, M3, and
calibrated scores remain explicitly unavailable. Directory comparisons and Git revision scans arrive
in later slices. See `.specs/python-slop-detector/` for the design and checkpoint.

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
rows use path order until calibrated hotspot scores are available.

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

M4 measures the share of callable mass above the complexity threshold. Each
function, method, or nested function contributes `CC * sqrt(SLOC)` mass. The default
threshold is `CC > 10`. Set `complexity_threshold` in `slop.toml` or `[tool.slop]`
to change it. Project M4 uses summed mass, not an average of file ratios.

JSON records every callable's name, source span, complexity, exact SLOC lines, and
mass. Verbose terminal output shows mass totals and the largest eroded callables. Files
without callables report `no-functions`. A complexity failure preserves source-line
counts and makes M4 unavailable for that file and its cohort.

Test patterns take precedence over production patterns. Exclusions, Git-ignore
rules, and generated markers apply before parsing. Tracked Git files remain eligible
even if an ignore pattern matches them. The scanner does not execute source files
or traverse symbolic links and Windows junctions.

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

CI enforces four package dependency boundaries and a 90 percent coverage floor with
branch measurement enabled. The normal suite runs unit, golden, and architecture
contract tests. The malformed source fixture is excluded from code linting and type
checking.

Retained dependency learning tests run separately:

```text
uv run pytest tests/learning
```
