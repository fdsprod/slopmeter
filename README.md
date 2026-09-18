# slop.measure

`slop.measure` detects redundant and structurally eroded source code. The first
release targets Python and provides the `slop` command plus an importable API.

The raw scan reports Python source lines, production and test coverage, excluded
files, diagnostics, and M4 structural erosion. M1-M3 metrics and calibrated scores
remain explicitly unavailable. Directory comparisons and Git revision scans arrive
in later slices. See `.specs/python-slop-detector/` for the design and checkpoint.

## Scan a directory

Use the project environment to run a scan:

```text
uv run slop scan .
uv run slop scan tests/fixtures/basic --json
uv run slop scan . --scope all --no-color
uv run slop scan . --strict
```

The default scan continues after file errors. `--strict` stops with exit code 3.
Invalid arguments or configuration return exit code 2. Findings do not cause a
failure. `--scope` selects terminal results; JSON always contains the complete report.

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

M4 measures the share of callable mass above the complexity threshold. Each
function, method, or nested function contributes `CC * sqrt(SLOC)` mass. The default
threshold is `CC > 10`. Set `complexity_threshold` in `slop.toml` or `[tool.slop]`
to change it. Project M4 uses summed mass, not an average of file ratios.

JSON records every callable's name, source span, complexity, exact SLOC lines, and
mass. Terminal output shows mass totals and the largest eroded callables. Files
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
