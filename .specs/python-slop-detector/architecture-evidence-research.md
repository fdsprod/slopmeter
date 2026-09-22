# Architecture evidence research

Date: 2026-09-21. Installed versions: Import Linter 2.15 and Grimp 3.17.

## Decision

Reuse the established graph and contract concepts. Do not run an arbitrary target
repository's Import Linter configuration as part of a normal source-only scan.
The tested discovery and extension paths can execute target Python code.

For the first product slice, accept source-bound architecture evidence produced by
a separately run tool, or implement a narrow source-only import adapter with
explicit supported syntax. Treat unresolved imports and unsupported contracts as
coverage gaps. Neither option requires adding Import Linter to runtime dependencies.

If native Grimp analysis is later selected, first decide its dependency policy and
close package-discovery safety gaps. Use documented Grimp graph methods. Keep any
Import Linter internal-report adapter behind a tested version boundary. Do not
parse its human-readable CLI output as a durable interchange format.

## Retained learning tests

Keep `tests/learning/test_architecture_evidence_behavior.py` as documentation of
the external behavior. It is outside the default pytest test paths. These are
observations against installed versions, not a promise about future releases.
The existing `tests/learning/test_import_linter_behavior.py` also remains useful.

| Question | Observed behavior | Product implication |
| --- | --- | --- |
| Can analysis avoid executing a top-level package? | `build_graph` reads a package whose `__init__.py` raises, without raising that exception. Imported module bodies also remain unexecuted. | Ordinary top-level discovery can work under standard import machinery. This probe does not establish a universal no-execution guarantee. |
| Does a `src/` layout work? | Adding the source root to `PYTHONPATH` resolves the package. | Source roots must be explicit; installed environment discovery is not the repository snapshot. |
| Are relative imports resolved? | `from . import storage` becomes a direct service-to-storage edge. | Reuse is viable for ordinary static imports. |
| Are locations available? | `get_import_details` returns importer, imported module, line number, and source line. | File paths and snapshot identity still need an owned source map. |
| Do namespace portions work? | A namespace portion with a regular package below it is analyzed without executing that portion's initializer. | Namespace layouts need separate discovery tests and explicit support. |
| Is a dotted regular root safe? | `observed_parent.child` executes the parent's marker-writing initializer, then raises `NotATopLevelModule`. | Rejecting the error after calling Grimp is too late. A subprocess alone does not enforce source-only analysis. |
| Does the graph include dynamic imports? | `importlib.import_module('observed_dynamic.storage')` creates no internal edge. | An empty graph is not proof that runtime dependencies are absent. |
| Do declared forbidden and layer contracts work? | Both keep the clean package and report a broken contract after adding a forbidden relative import. CLI output includes `(l.2)`. | Existing contract semantics are reusable. Higher layers may depend on lower layers; the reverse direction violates the tested layer declaration. |
| Are indirect violations detected? | The existing CLI probe reports a forbidden dependency through an intermediate module. | Preserve import chains, not only the final forbidden pair. |
| Is configuration reading public? | `api.read_configuration` reads declarations without finding the target package and normalizes `root_package` to `root_packages`. | This API can support config inspection without running the configured contracts. |
| Is structured report access public? | Internal `create_report` produces checks and metadata after private contract registration. The forbidden check uses `invalid_chains`. | Structured access exists, but is outside the documented public Python API. Do not treat its shape as a stable report schema. |
| Can target config execute code? | A configured custom contract imports a target module and writes its marker before the CLI reports its exception. | Never load target `contract_types` during normal scans. Reading config and running config are different operations. |

The first CLI probe initially assumed `importlinter.cli.lint_imports` returned a
success boolean. It returns an integer exit status: 0 for success and 1 for
failure. Its `no_cache=True` option disables caching; passing `cache_dir=None`
alone selects the default cache. The retained tests use the observed behavior.

## Availability and integration limits

`pyproject.toml` lists `import-linter>=2.13,<3` in the development group. Grimp is
its transitive dependency. Neither is declared in the project's runtime dependency
list. Their presence in this checkout does not make them available to wheel users.
The learning work adds no dependency.

Normal scans operate on supplied source evidence, including pinned Git snapshots.
Grimp discovers importable packages through Python's import machinery. That
discovery is not directly interchangeable with the repository's existing source
inventory. Any adapter must establish which exact files were analyzed, avoid
installed-package name collisions, and keep source paths relative to the analyzed
snapshot. The tested package finder uses `importlib.util.find_spec`, which explains
the observed parent-initializer execution.

Top-level success and namespace success do not prove safety with custom import
hooks, shadowed tool packages, all namespace layouts, or arbitrary package names.
Those cases were not exercised. Multiple namespace roots, star imports, conditional
imports, type-checking-only imports, and extension modules also need coverage
decisions before broad support is claimed.

Architecture findings should distinguish direct imports from transitive chains.
A configured forbidden edge is a policy violation within analyzed coverage. An
undeclared boundary, omitted dynamic import, or unresolvable module is not evidence
that the target conforms to an architecture. Ownership boundaries remain separate
from import permissions.

## Public documentation checked

- [Grimp usage](https://grimp.readthedocs.io/en/stable/usage.html) documents graph
  construction, namespace portions, direct import queries, and import details.
- [Import Linter Python API](https://import-linter.readthedocs.io/en/stable/api/)
  documents configuration reading, not structured report construction.
- [Import Linter contract types](https://import-linter.readthedocs.io/en/stable/contract_types/)
  documents forbidden and layered dependency contracts.

The safety observations above come from retained local subprocess tests and
inspection of the installed package finder and contract registration code.

## Validation

With `PYTHONPATH=src`:

```text
.venv/Scripts/python.exe -m pytest tests/learning/test_architecture_evidence_behavior.py tests/learning/test_import_linter_behavior.py
10 passed in 2.69s

.venv/Scripts/python.exe -m ruff check tests/learning/test_architecture_evidence_behavior.py
All checks passed!

.venv/Scripts/python.exe -m ruff format --check tests/learning/test_architecture_evidence_behavior.py
1 file already formatted

.venv/Scripts/python.exe -m pyright --pythonpath .venv/Scripts/python.exe tests/learning/test_architecture_evidence_behavior.py
0 errors, 0 warnings, 0 informations
```

Pyright without an explicit interpreter initially could not resolve `pytest`.
Selecting the existing virtual environment resolved that environment issue.

No product source was changed.
