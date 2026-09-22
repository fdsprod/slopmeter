# Exception fallback evaluation

Evaluation date: 2026-09-21. This experiment is advisory and unscored.
Source was parsed, not imported or executed. No threshold, calibration profile,
or production/test classification was changed.

## Independent source review

We reused the pinned HTTPX, Rich, and Black checkouts from the
[earlier independent evaluation](independent-evaluation-040.md). These are public
historical snapshots, not claims about current project heads. They are separate
from the calibration corpus. Rich is also a runtime dependency of Slopmeter.

An independent agent selected and labeled 15 handlers from source before reading
detector output. It did not read the detector implementation. Nine labels predict
syntax candidates, two predict assessed handlers without findings, and four
predict unresolved syntax. All 15 matched the initial report. The agent then
reviewed all 30 reported candidates.

| Repository | Parsed files | Failed files | Handlers | Assessed | Unresolved | Candidates |
|---|---:|---:|---:|---:|---:|---:|
| HTTPX 0.28.1 | 60 | 0 | 59 | 35 | 24 | 6 |
| Rich v14.1.0 | 190 | 0 | 110 | 61 | 49 | 9 |
| Black 25.1.0 | 283 | 6 | 160 | 66 | 94 | 15 |

Black's failures are formatter fixtures with invalid or Python-version-specific
syntax. They do not receive invented handler counts. Scans include selected tests
and utilities; the candidate total is not a production defect count. All three
checkouts remained clean.

The reviewed cases show why a syntax candidate is not a defect:

| Case | Evidence and interpretation |
|---|---|
| HTTPX `peek_filelike_length` | Returns `None` when length is unavailable. Callers distinguish it from zero and can select chunked transfer. Preserve that contract. |
| HTTPX `is_ipv4_hostname`, Rich `Console.is_terminal`, Black `matches_grammar` | Exceptions supply the negative answer of a predicate. `False` is intentional. |
| Rich `get_fileno` | The documented return contract permits `None`; the caller checks it. |
| Rich `_is_dataclass_repr` | Attribute access can fail even when no protected call is present. Empty operation evidence does not mean no possible exception. |
| Rich `loop_first` | A generator's bare return ends iteration. It remains unresolved under this experiment's scope. |
| Black `find_pyproject_toml` | An optional configuration failure is logged and returns `None`; the caller handles it. Logging does not suppress syntax evidence. |
| Black `Converter.parse_graminit_h` | `False` explicitly signals failure and a diagnostic is printed. `Converter.run` ignores the boolean; this merits caller review but does not prove the handler claims success. |
| Black response objects and `set()` fallbacks | Constructor calls remain unresolved; the detector does not invent their contracts. |

**No application defect was confirmed.** Most candidates are intentional
sentinels or predicates visible in source. This selected sample does not estimate
precision or recall. It supports keeping the experiment separate from scores and
preserving review reasons instead of suppressing findings to fit these projects.

## Self-review

The new command found one candidate in Slopmeter:
`FilesystemSourceProvider._safe_git_leaf` returns `False` for a Git-listed path
that no longer exists. This is an eligibility predicate, not a promise to load
source. Its caller omits deleted paths. The adjacent broader `OSError` branch
keeps inaccessible paths so the read stage can retain failure diagnostics.
Decision: no code change and no evaluator exception.

The first score scan exposed five new complexity hotspots. The scope correction
added a sixth. Each was reviewed:

| Callable | Initial CC | Decision |
|---|---:|---|
| `inspect_errors` | 13 | Retain distinct inventory, failure, diagnostic, and strict-mode decisions. The boundary tests cover their behavior. |
| `ErrorReviewReport.summary` | 11 | Retain coverage derived from owned outcomes. The filters are real metric inputs; no special exemption. |
| `_context` | 11 | Correct the scope traversal used by generator detection, as described below. Do not change the complexity metric. |
| `_fallback_kind` | 14 | Retain explicit distinctions among literal forms, especially `False` versus numeric zero. |
| `_literal` | 12 | Retain recursive syntax checks so dynamic values are not claimed as known literals. |
| `_definition_headers` (added by the correction) | 12 | Keep eager defaults and decorators separate from nested bodies and uncertain declaration annotations. These are required syntax distinctions. |

Independent code review found three related general defects in the first
implementation. Nested definition headers lost protected-call evidence; a `yield`
in a default argument could escape generator detection; and a protected span
could start after a decorator. Decorators and defaults execute in the enclosing
scope, unlike nested function bodies. Independent regression tests precede the
correction. These are detector correctness fixes, not project-specific scoring
changes. The correction also keeps local annotation expressions and lazy type
aliases out of eager-operation evidence. Calls or yields in nested declaration
annotations remain explicitly unresolved. This avoids guessing runtime annotation
semantics from syntax alone.

## Evidence and validation

Local evidence is retained under `.tmp/error-review/`: complete scans, the
predeclared source labels, all-candidate review, self-review, same-source report
comparisons, and isolated installation checks. Temporary reports are not release
assets or new calibration observations.

Final validation after the scope correction:

- Full suite: **1,779 passed, 4 skipped**, with **95.40%** branch-inclusive coverage.
  The four build-gated cases passed separately against wheel and source installs.
- All **121 new tests** passed on Python 3.12, 3.13, and 3.14.
- Learning/performance checks: **52 passed, 1 skipped**.
- Ruff, formatting, Pyright, and all five import contracts passed. Dependency
  audit found no known vulnerabilities in the auditable dependencies.
- On identical final source, `score`, `models`, `variants`, and `derived` reports
  exactly match pre-feature commit `422a852`, without removing any fields.
- Final self-scan: 62 handlers, 41 assessed, 21 unresolved, and the one intentional
  missing-file predicate described above. The failed file is the existing
  intentional parse-error fixture; it is not hidden or counted as assessed.
- Final external scans retain exactly the same file outcomes, evidence, and
  summaries as the independently reviewed reports. All three checkouts are clean.

The final score scan has six new complexity hotspots, all covered in the table.
No existing hotspot changed its effective complexity. The score evaluator,
calibration, and thresholds remain unchanged.
