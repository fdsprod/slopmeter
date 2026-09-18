# slop.measure

`slop.measure` detects redundant and structurally eroded source code. The first
release targets Python and provides the `slop` command plus an importable API.

The project is under active development. See
`.specs/python-slop-detector/` for the approved specification and design.

## Development checks

Create or update the locked environment:

```text
uv sync --all-groups --locked
```

Run the same checks that CI uses:

```text
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest --cov=slop_measure --cov-report=term-missing
uv run pip-audit
uv build
uv run slop --help
```

The architecture check, `uv run lint-imports`, becomes required when the first
domain, adapter, application, and reporting packages exist. Learning and performance
tests use separate commands and do not run as part of the normal deterministic suite.
