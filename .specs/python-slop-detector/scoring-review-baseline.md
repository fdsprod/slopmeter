# Scoring review baseline

Captured on 2026-09-18 from revision `c9c0c769a1b5db0eaba49e2498a881f3ba4323e3`.
The scorer and production code were not changed.

The companion [JSON baseline](scoring-review-baseline.json) preserves nine examples,
source excerpts and hashes, exact callable measurements, current file scores,
effective configuration, analyzer and metric versions, and candidate calculations.

> [!IMPORTANT]
> Review priorities are provisional agent judgments about refactoring value. They
> are not user-approved labels, defect findings, or a representative calibration
> corpus. Candidate percentages are raw measurements, not calibrated scores.

## Capture

```powershell
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\Scripts\slop.exe score . --lang py --top 10 --json
```

UTF-8 avoids the known Unicode output failure in this session. JSON contains all
analyzed files, so `--top 10` does not limit the baseline candidates. Selection
covers production Python only. The report's test-fixture parse error does not
affect these examples. Source was read to assess each candidate; labels were not
assigned from complexity alone.

## Candidate measurements

With the existing threshold of 10:

```text
mass = CC * sqrt(SLOC)
current callable severity = 1 if CC > 10 else 0
candidate callable severity = max(0, CC - 10) / CC
candidate excess mass = max(0, CC - 10) * sqrt(SLOC)
candidate file erosion = sum(mass * candidate severity) / sum(mass)
```

Excess mass is an uncalibrated measure of affected complexity and size. It is
included to evaluate possible review ordering, not adopted as a ranking rule.
SLOC counts owned source lines; it is not the physical span length.

| Callable | CC | SLOC | Current callable severity | Candidate severity | Excess mass | Provisional refactoring priority |
|---|---:|---:|---:|---:|---:|---|
| `measure_erosion` | 11 | 24 | 100% | 9.1% | 4.9 | Low |
| `_normalized_extensions` | 13 | 24 | 100% | 23.1% | 14.7 | Low |
| `_plain_forwarder` | 22 | 30 | 100% | 54.5% | 65.7 | Low |
| `_contained` | 11 | 30 | 100% | 9.1% | 5.5 | Medium |
| `AnalysisService._scan` | 15 | 60 | 100% | 33.3% | 38.7 | High |
| `render_findings` | 15 | 72 | 100% | 33.3% | 42.4 | High |
| `aggregate_snapshot` | 28 | 95 | 100% | 64.3% | 175.4 | High |
| `query_findings` | 23 | 59 | 100% | 56.5% | 99.9 | Medium |
| `build_profile` | 10 | 54 | 0% | 0% | 0.0 | Low; correctness review matters |

## Source review

- [measure_erosion](../../src/slop_measure/metrics/erosion.py): one short validation
  and arithmetic routine. Keep it intact unless its responsibilities change.
- [_normalized_extensions](../../src/slop_measure/languages/registry.py): a flat
  checklist of valid extension syntax. Splitting each predicate would add noise.
- [_plain_forwarder](../../src/slop_measure/languages/python/rules/abstraction.py):
  a narrow, conservative AST predicate. Most complexity comes from eligibility
  guards. Removing guards to improve its score would weaken correctness.
- [_contained](../../src/slop_measure/metrics/clones.py): one-to-one containment
  matching includes recursive reassignment in a nested helper. Its invariant
  deserves an explicit name and explanation despite low excess complexity. The
  displayed measurements belong to `_contained`, not a combined nested-callable score.
- [AnalysisService._scan](../../src/slop_measure/application/service.py): separates
  naturally into adapter execution and scan coordination. Failure handling and
  provenance currently sit inside the same orchestration loop.
- [render_findings](../../src/slop_measure/reporting/evidence.py): sorting, shared
  display-budget allocation, and rendering repeat across three evidence families.
  These responsibilities offer a useful separation while preserving output.
- [aggregate_snapshot](../../src/slop_measure/metrics/aggregate.py): combines
  diagnostic collection, file and clone assembly, cohort construction, coverage,
  and report construction. Review those boundaries first. Comprehensions also
  contribute to its CC; high CC does not imply deep nesting here.
- [query_findings](../../src/slop_measure/reporting/queries.py): mostly declarative
  filters and sorting. Family-specific selectors could help, but it should not
  automatically outrank scan coordination because it contains more predicates.
- [build_profile](../../src/slop_measure/scoring/calibration.py): linear validation
  followed by fixed model construction. An independent review rated it medium
  priority for correctness because its checks protect calibration validity. That
  differs from refactoring urgency, which remains low. Zero excess is not proof
  that code needs no review.

## File-level comparison

All callables in each file participate in these ratios, including callables not
selected as examples. These columns must not be confused with callable severity.

| File | Current erosion | Candidate erosion |
|---|---:|---:|
| `metrics/erosion.py` | 100.0% | 9.1% |
| `languages/registry.py` | 72.9% | 14.7% |
| `languages/python/rules/abstraction.py` | 70.1% | 28.0% |
| `metrics/clones.py` | 81.7% | 11.0% |
| `application/service.py` | 81.0% | 24.3% |
| `reporting/evidence.py` | 77.4% | 25.8% |
| `metrics/aggregate.py` | 62.9% | 32.8% |
| `reporting/queries.py` | 51.6% | 29.2% |
| `scoring/calibration.py` | 43.3% | 10.0% |

## What this baseline tells us

The gradual formula fixes the immediate threshold jump in `measure_erosion`.
It also separates large orchestration from a small borderline function.
It does not resolve every mismatch: `_plain_forwarder` still outranks `_scan`
under both candidate severity and excess mass, while the matching algorithm in
`_contained` remains near the bottom.

Before adopting a ranking, review these provisional comparisons:

- `_scan`, `render_findings`, and `aggregate_snapshot` should rank above
  `measure_erosion` for refactoring value.
- `_scan` should rank above `_plain_forwarder`, despite its lower CC.
- `_contained` deserves more explanation than a similarly sized flat validator.
- A CC10 routine must not be treated as verified safe or maintenance-free.

Additional examples should include deeply nested routines, large linear routines,
flat predicates, and before/after extractions judged useful or cosmetic. Keep
later examples as a separate evaluation set before tuning against them. Do not
infer precise weights or a universal guard-clause discount from these nine cases.

## Verification

All nine callable masses were checked against `CC * sqrt(SLOC)`. All nine current
file erosion values were recomputed from the reported callable facts and matched
the tool. Candidate file values use the full callable population of each file.
No score recalibration, production change, or behavioral test change was made.
