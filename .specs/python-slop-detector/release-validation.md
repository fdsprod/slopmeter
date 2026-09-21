# Python MVP release validation

> Release status: the implemented features described here shipped in [v0.4.0](https://github.com/fdsprod/slopmeter/releases/tag/v0.4.0). Hosted CI passed. Validation counts and pre-release status statements below describe the original checkpoint.

Date: 2026-09-18. Package: `slop-measure` 0.1.0. Command: `slop`.

TB-1 through TB-8 passed their recorded gates. TB-9 adds consistent public error
mapping, language-neutral contracts, a native-memory benchmark, clean artifact
installation checks, and a nine-cell release matrix.

## Acceptance mapping

| P1 acceptance group | Retained automated evidence |
|---|---|
| Scan supported Python and preserve partial results | `tests/golden/test_scan_basic.py`, `tests/unit/sources/test_filesystem.py`, Python adapter and metric unit suites |
| Exact M2/M3 unions and M4 callable mass | `tests/golden/test_patterns.py`, `tests/golden/test_clones.py`, metric and complexity unit suites |
| Directory M1, additions, deletions, renames, and no-baseline states | `tests/golden/test_directory_comparison.py`, `tests/unit/metrics/test_line_delta.py`, domain change and ownership suites |
| Git M1 without checkout changes | `tests/integration/test_git_comparison.py`, `tests/unit/sources/test_git_source.py`, rename matching suite |
| Exact findings, clone members, eroded callables, and score inputs | `tests/golden/test_explainability.py`, `tests/unit/reporting/test_evidence_queries.py`, `tests/integration/test_git_evidence.py` |
| Versioned JSON and equivalent public API | Snapshot/comparison golden suites, CLI unit and integration suites |
| Future-language evidence through scoring and rendering | `tests/contract/test_language_adapter.py`, `tests/contract/test_determinism.py` |
| Configuration boundaries, effective settings, and exclusions | `tests/unit/test_config.py`, source-provider tests, calibrated compatibility tests |
| File/project calibration, unavailable scores, and raw aggregation | Scoring unit suite and `tests/golden/test_scoring.py` |
| Stable errors and installation | `tests/unit/test_public_errors.py`, `tests/integration/test_distribution.py` |

The fake adapter produces an invented language. Its exact M2, M3, combined,
erosion, calibrated score, and comparison totals pass through the ordinary core.
Reversed registry and evidence order produce identical serialized reports.

## Platform validation

Python 3.12, 3.13, and 3.14 are released supported branches in the
[Python version table](https://devguide.python.org/versions/). The CI matrix runs
each on Windows, macOS, and Linux. Each cell uses locked dependencies and runs
deterministic tests, retained learning tests, benchmark accounting, builds, and
isolated wheel/source installations. Static checks and dependency audit run first.

Local Windows checks use Python 3.12.14, 3.13.13, and 3.14.5. The latter two live in
ignored workspace environments and do not replace system interpreters.

| Check | Local result |
|---|---|
| Deterministic suite on each Python version | 1,114 passed; four artifact cases run separately |
| Wheel/source installation and archive scope on each version | Four passed |
| Retained learning tests on each version | 41 passed |
| Small benchmark harness tests on each version | Two passed; full run performed directly |
| Python 3.12 branch coverage | 96.66 percent; required floor 90 percent |
| Ruff format/lint, Pyright, import-linter | Passed; five import contracts kept |
| Locked dependency resolution | Passed with uv 0.11.14 |
| Dependency audit | No known vulnerabilities; unpublished local package excluded from index audit |
| Full 100,000-SLOC benchmark | 51.77 seconds, 124.75 MiB peak, zero diagnostics |

The four artifact cases passed against the rebuilt wheel and source archive on all
three local Python versions. Together with the ordinary suite, all 1,118 release
test cases have been exercised successfully per local Python version.

Hosted CI has not run: this checkout has no configured Git remote. Linux and macOS
execution remain an external validation item. No result in this record claims that
the nine hosted jobs passed.

## Distribution checks

Wheel and source archive installation tests create separate environments, install
each artifact under exported runtime constraints, and run from outside the checkout.
They verify installed module paths, `slop --help`, JSON analysis, rules, a measured
default score, packaged profile bytes, and the companion manifest digest.

The ordinary test suite skips four artifact cases until `SLOP_RELEASE_DIST` names built
artifacts. The release gate runs them explicitly; a skip is not a package pass.

Archive inspection found that Hatch's default source selection included a local
settings file and tool cache. An independent failing archive test preceded an
explicit source-archive allowlist. The rebuilt archive contains no local settings,
tool caches, virtual environments, or repository metadata. Wheel and source member
checks run alongside the two clean-install cases. No artifact was published.

## Performance method

`tools/benchmark.py` generates 100 files with 100 ten-line functions each. Literal
values vary deterministically. The retained source digest makes the fixture
reproducible. Small tests prove exact accounting, repeatable source hashes, fresh
output directories, and isolation from an enclosing repository's ignore rules.

A fresh worker measures the complete scan through calibration. Peak resident memory
uses the operating system's process peak and includes native parser allocations.
Fixture generation and presentation are outside the timed interval. This is a
synthetic throughput baseline, not a bound for every Python project.

The first completed run on an AMD Ryzen 9 7900X3D, Windows 11, Python 3.12.14
measured **614.51 seconds** and **128,913,408 bytes** peak RSS for exactly 100,000
SLOC, with zero diagnostics. Its source SHA-256 is
`d779bfc7b7b83e1162a307034023d56408628990ac27a7cc4f59ee9b88e61f87`.

Review found repeated whole-file tokenization in pattern guards. Before changing
the implementation, two independent failing tests established a work budget:
tokenize each immutable parsed source unit once, preserving typed-binding behavior.
The follow-up benchmark target is at most 120 seconds and 256 MiB peak RSS on this
same machine and fixture. These are local investigation budgets, not portable CI
timing guarantees. The full benchmark test has a separate 30-minute safety timeout;
small tests retain their original timeout.

The per-unit immutable token cache reduced the same workload to **51.77 seconds**
and **130,805,760 bytes** peak RSS (124.75 MiB): an **11.87-fold** observed speedup.
The source digest, configuration, exact file/SLOC counts, and zero-diagnostic result
match the initial run. Both budgets pass. All 148 focused pattern, work-budget, and
adapter tests pass without changing rule versions or calibration. The cache lasts
only as long as its parsed file; it has no global retention.

The [retained machine-readable measurements](performance-baseline.json) contain both
runs and the budgets. Generated source roots are omitted from that checked-in record;
the complete original outputs and generated fixtures remain in ignored `.tmp` paths.

## Learning-test disposition

All 41 external-behavior tests remain in `tests/learning` and run separately from
the deterministic suite. They cover Radon traversal and spans, Tree-sitter syntax
and coordinate behavior, Git object/mode/rename reads, and terminal dependencies.
The Tree-sitter coordinate regression retains the evidence for the `<0.26` runtime
constraint. No learning test was silently removed after implementation.

## Scope limits

This release implements the Python P1 stories and TB-1 through TB-9 code scope.
History trends, CI regression budgets, changed-line gates, cognitive erosion,
coupling, churn, and a real TypeScript adapter remain later work. The initial
calibration is a small historical reference and does not prove authorship.
