# Public evaluation checkpoint

The runner is implemented at `60e71dbb6ceab84a4d88cb0c3ba70b3c9b819cb3`.
The public run recorded that revision with no source or runner changes. Later
documentation commits do not change the analyzer fingerprint.

## Public evidence

The checked-in manifest contains six cases from five repository lineages.
All 16 jobs and 137 expected-value checks passed. Analyzer fingerprints and
materialized source hashes matched before and after the run. The result is at
`.tmp/public-evaluation-verified/result.json`, with full reports, verified source,
manifest, dependency versions, and worker records beside it.

- AstrBot's natural file addition introduces one exception-fallback candidate.
- The later AstrBot fix removes one candidate. This is not independent proof of
  correctness or a claim that its earlier caller contract was fully established.
- HTTPX's intentional encoding predicate remains visible and persisted.
- PyRIT remains outside exception-handler coverage. Werkzeug and NetworkX remain
  unresolved by the local stored-count analysis.

A separate empty-cache `--fetch` run downloaded both pinned AstrBot fix files.
Their SHA-256 hashes matched, and all three jobs and 24 checks passed. Its result
is `.tmp/public-fetch-smoke/output/result.json`. No target module or upstream test
was executed in either evaluation. Downloaded source is not committed.

These are selected regression cases, not a precision/recall study or independent
holdout. The complete interpretation and reproduction commands are in
[`evaluation/README.md`](../../evaluation/README.md).

## Verification

Validation used Windows and Python 3.12.14.

| Check | Result |
|---|---|
| Independent evaluation CLI tests | 34 passed |
| Full default test suite | 1,996 passed, four skipped |
| Package coverage | 93.25%; this does not measure coverage of the developer tools |
| Ruff lint and formatting | Passed; 245 Python files formatted |
| Pyright, project and explicit new tool files | No errors or warnings |
| Import contracts | All five kept |
| Wheel and source build | Passed |
| Source archive contents | Manifest, documentation, and four runner modules present; local artifacts absent |

The four skipped tests require separately configured release-install environments.
They were not run for this developer-tool change. No release was published and no
version was changed. This validation does not claim the CI platform matrix ran.

The tests were authored independently of implementation. Their initial expected
failures were committed before the implementation. Temporary pending markers were
removed in the implementation commit. The final change-report parse-failure case
was independently authored after implementation and passed immediately. It is not
claimed as test-first evidence.

## Self-review

Ran `slop score . --lang py --top 10 --json` against the working tree and retained
the report at `.tmp/public-evaluation-self-score.json`. The four new tool files
have no pattern or clone findings in that whole-project scan. Three complexity
hotspots remain:

| Callable | CC / source lines | Review decision |
|---|---|---|
| `SourceFile.safe_python_path` | 11 / 14 | Keep explicit portable-path rejection checks. No benefit established from splitting the predicate. |
| `_pointer` | 11 / 17 | Keep dictionary and array lookup, pointer decoding, and missing-value handling together. |
| `execute` | 17 / 65 | Keep case/job sequencing and incomplete-result handling visible. Review this orchestration when adding another workflow. |

These are real control-flow measurements. No threshold or metric change is
justified by these particular files. Review did not establish a behavior defect
in the three callables, and no score-driven refactor was made.

The default whole-project scan retains the expected syntax diagnostic for
`tests/fixtures/basic/bad.py`. It also skips the new test module because that
module contains a generated-marker fixture string. A separate external config
selected only that test module and disabled generated markers. That supplemental
scan retained the test cohort, found no diagnostics, patterns, internal clones,
or effective complexity hotspots, and is saved at
`.tmp/public-evaluation-test-self-score.json`. Its clone scope is only that file;
it is not a replacement whole-project clone result. No project configuration or
source classification was changed.

## Remaining work

The runner currently supports selected-file `errors`, `derived`, and `changes`
reports. Whole-repository architecture/history evaluation, broader holdouts, and
object-field dependency/invalidation support remain separate work. The prior
HTTPX/Rich/Black evaluation retains its original scope and limitations.
