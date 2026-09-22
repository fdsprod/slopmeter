# Bounded evaluation of change evidence

Date: 2026-09-21 (America/Los_Angeles).

Change review and architecture completed for all three public pairs with every
change-evidence family enabled. History completed for HTTPX and Rich. Black change
review exceeded the intended time budget; its history was not completed. These
observations are not calibration evidence.

## Scope and source identities

This evaluation reads committed Git objects. It does not import target packages,
run their tests, or install their dependencies. The public corpus contains exactly
three first-parent pairs from the cached HTTPX, Rich, and Black repositories.
A collaborator-run Slopmeter self-check is reported separately.

| Repository | Baseline | Current | Change |
| --- | --- | --- | --- |
| HTTPX | `8ecb86f0d74ffc52d4663214fae9526bee89358d` | `89599a9541af14bcf906fc4ed58ccbdf403802ba` | Continue certificate configuration when `verify=False` |
| Rich | `9c9b011187bba772dca57653c9114005b489f005` | `a75a9a9838814cffb68cefe3522fc47c8ddce768` | Reuse one console-size observation when constructing options |
| Black | `d330deea00e199b99dea59fb4643305408c19a9b` | `8a737e727ac5ab2f1d4cf5876720ed276dc8dc4b` | Release documentation; no Python source changes |

The public origins were checked before fetching:
`https://github.com/encode/httpx.git`,
`https://github.com/Textualize/rich.git`, and
`https://github.com/psf/black.git`.
HTTPX and Rich each required two additional parent layers. Black required one.
The bounded fetches did not check out other revisions.

All analyses use `AnalysisConfig(calibration_profile="__raw__")`. Final Black
analysis adds the explicit exclusion `tests/data/**`. These files contain formatter
fixtures, including deliberately invalid Python. The exclusion narrows the result;
it is not evidence that those files are clean. Other default exclusions remain.

Architecture reads `.` as the source root for HTTPX and Rich, and `src` for Black.
No architecture policy is invented for the public projects. Their
zero forbidden-edge counts mean no declared rules were violated, not that their
architecture conforms to an inferred design.

History uses `max_commits=1`, `window_days=14`, and first-parent traversal. A deleted
line present at the baseline has an unknown introduction date. A one-step range
cannot establish its recent-rework age.

## Final measurements

The analyzer source is pinned by implementation commit
`8a07a8d560fd3fae471881948ab10b1310ca9304`. The runner started at repository revision
`146d9fdbaa1bbc219a46a66fbce52af55e186e22` with those implementation files still
uncommitted. Source hashes before and after the run are retained with the raw
reports. They differ in four files: `application/change_review.py`,
`reporting/architecture.py`, `reporting/change_review.py`, and
`reporting/surface.py`. The coordinator reports that the application change was
formatter-only. Renderer commit `a5ab475` improves source path and revision labels
without changing JSON. These changes were not followed by another expensive scan.
The differing hashes remain disclosed; this is not a byte-identical source epoch.

| Repository | Pattern lineage | Clone groups | Exception fallback lineage | Raw state dispatch |
| --- | --- | --- | --- | --- |
| HTTPX | 8 persisted | 6 persisted | 5 persisted; 1 unresolved | No candidates |
| Rich | 77 persisted | 3 persisted | 9 persisted | No candidates |
| Black | 45 persisted | 1 persisted | 15 persisted | No candidates |

None of the three public pairs introduced or removed a reported finding. HTTPX's
one unresolved error record is the nested fallback in `peek_filelike_length`.
The surrounding handler is outside assessed coverage. It was not reported as
removed or fixed.

| Repository | Selected Python files | Current source lines | Assessed / unresolved exception handlers | Architecture |
| --- | --- | --- | --- | --- |
| HTTPX | 60 | 12,216 | 35 / 24 | 60 analyzed files; 16 unresolved imports; 2 source cycles |
| Rich | 190 | 29,858 | 61 / 49 | 190 analyzed files; 27 unresolved imports; 1 source cycle |
| Black | 72 | 100,641 | 62 / 32 | 39 analyzed files; 33 unresolved files; 4 unresolved imports; 2 source cycles |

These handler totals describe each snapshot; they are not numbers of defects.
HTTPX, Rich, and Black also retain inventory coverage for 65, 337, and 97 non-Python
or otherwise unsupported files respectively. Black records 255 excluded files.
Its architecture source-root policy leaves 33 selected files outside assessed
module coverage. No selected Python file failed parsing in these runs. No public
architecture rules were declared, so zero violation counts are not conformance
results.

Both history ranges completed one step. HTTPX has 3 added and 4 deleted source
lines, for churn 7 and net -1. Rich has 4 added and 3 deleted source lines, for churn
7 and net +1. Every deleted line has an unresolved introduction age because it
already existed at the baseline. None is classified as recent rework.

| Repository | Change review | Architecture | History |
| --- | --- | --- | --- |
| HTTPX | 12.371 s | 2.065 s | 10.422 s |
| Rich | 31.246 s | 7.064 s | 27.303 s |
| Black | 203.386 s | 2.382 s | Not completed |

Times include report construction and JSON round-trip validation. They are single
wall-clock observations on a shared development machine. All eight completed
reports round-tripped successfully. Target Git status remained unchanged.

Black was attempted again with the declared `tests/data/**` exclusion. Its change
review completed in 203.386 seconds, exceeding the intended 180-second cutoff
before the next poll returned. The completed result is retained as an over-budget
measurement. Architecture then completed; the runner was stopped before history
completed. This was not successful enforcement of a hard 180-second timeout.
No complete history or whole-repository coverage claim is inferred for Black.
Its selected source still includes large profiling inputs such as
`profiling/dict_huge.py`, `profiling/list_huge.py`, and `profiling/mix_huge.py`.
There was no further scope expansion or threshold tuning.

## Initial measurements retained for provenance

Initial analyzer revision: `4cfb1f53c35539841e4356af16fd2e7acfb74a3b`, plus uncommitted
integration changes. The exact Python source hashes and tracked-diff digest are
saved under `.tmp/change-evaluation/`. Source files were still being edited, so
these measurements do not claim a frozen or reproducible analyzer build.

| Repository | Pattern lineage | Clone groups | Architecture coverage | History |
| --- | --- | --- | --- | --- |
| HTTPX | 8 persisted; no introduced, removed, changed, or unresolved pattern records | 6 persisted | 60 analyzed files; 16 unresolved imports; 2 source dependency cycles | Complete one-step range; 3 added and 4 deleted source lines |
| Rich | 77 persisted; no introduced, removed, changed, or unresolved pattern records | 3 persisted | 190 analyzed files; 27 unresolved imports; 1 source dependency cycle | Complete one-step range; 4 added and 3 deleted source lines |

HTTPX comparison, architecture, and history took 14.120 s, 2.117 s, and 13.979 s.
Rich took 32.338 s, 5.825 s, and 29.806 s. These are single wall-clock observations
on the shared development machine, not performance benchmarks.

The initial full-root Black comparison was stopped after more than 180 seconds
without a completed report. It included the formatter's entire source-fixture
corpus. Completed HTTPX and Rich artifacts were preserved. The final Black scope
was then declared as the explicit fixture exclusion above. This is an evaluation
scope change, not a detector or threshold change.

## Independently inspected cases

The following checks use the committed source and patch, not test assertions that
mirror the detector implementation.

- **HTTPX keep case.** The patch removes an early return in
  `httpx/_config.py:create_ssl_context`. The resulting code reaches the existing
  certificate-loading branch. Its 3 added and 4 deleted source lines agree with
  the history report. Pattern and clone evidence remains persisted.
- **Rich keep case.** `rich/console.py:Console.options` stores `self.size` once and
  reuses its dimensions. This avoids repeated size observations and keeps the
  options consistent with that observation. The report introduces no new pattern
  finding or clone group. The patch's 4 added and 3 deleted source lines agree
  with history.
- **Positive syntax observation, unchanged debt.** HTTPX's
  `httpx/_client.py:_get_proxy_map` retains an `else` after the preceding branch
  returns on every path. The source confirms the reported redundant-else syntax.
  The report correctly labels it persisted. This is not an independently labeled
  maintenance defect or a reason to fail the current patch.
- **Architecture interpretation keep case.** HTTPX's `_types.py` imports domain
  types under `TYPE_CHECKING`. These imports contribute to the source graph, so its
  cycles do not establish runtime import cycles. The report explicitly includes
  conditional source relationships and retains star imports as unresolved.
- **Exception fallback keep case.** HTTPX's `_is_known_encoding` explicitly returns
  `False` when `codecs.lookup` raises `LookupError`, and `True` otherwise. This is
  the documented boolean predicate contract. Its persisted fallback candidate is
  valid syntax evidence but does not establish error masking. This concrete case
  supports keeping exception fallback evidence unscored.
- **Black control selected before final analysis.** Its pair changes only three
  documentation files. It should introduce no Python-source regression. Any
  pre-existing parse failure or excluded fixture must remain a coverage limit.
  Its completed, fixture-excluded change report preserves all observed findings
  and introduces none. This verifies the keep case only within that selected scope.

No public change in this small selection provides an independently labeled new
slop defect. No precision, recall, or predictive-maintenance claim follows from
these results. The Slopmeter self-check is not held-out evidence.

The collaborator-run self-check compares
`73b9680f417da8eaf35e02bbf2daba7b55cf2f80` with the integrated implementation.
It selects source under `src` and disables generated-marker exclusions so marker
constants in the analyzer cannot hide its own source. It reports 40 persisted raw
state-dispatch findings, no introduced or unresolved findings in that family, and
no limitations in that selected scan. The broader self-scan had uncertainty from
aggregated excluded coverage and was not used for introduced-finding counts.
These are self-check results supplied by the coordinating agent, not independently
labeled public examples.

Synthetic controls remain separate in the independent lineage, clone, exception,
architecture, and history tests. They test defined behavior such as a third clone
copy, a failed renamed source, and an unresolved fallback. They do not establish
field precision.

## Reproduction and artifacts

The following commands were run from the Slopmeter workspace:

```powershell
git -C .tmp/evaluation040/httpx fetch --deepen=1 --no-tags origin 26d48e0634e6ee9cdc0533996db289ce4b430177
git -C .tmp/evaluation040/rich fetch --deepen=1 --no-tags origin 2dca1b70359dac61e1bbfb6f14ebe19a5ab79c3d
git -C .tmp/evaluation040/black fetch --deepen=1 --no-tags origin 8a737e727ac5ab2f1d4cf5876720ed276dc8dc4b
git -C .tmp/evaluation040/httpx fetch --deepen=1 --no-tags origin 26d48e0634e6ee9cdc0533996db289ce4b430177
git -C .tmp/evaluation040/rich fetch --deepen=1 --no-tags origin 2dca1b70359dac61e1bbfb6f14ebe19a5ab79c3d
$env:PYTHONPATH='src'
.venv/Scripts/python.exe .tmp/change-evaluation/run_initial_evaluation.py
.venv/Scripts/python.exe .tmp/change-evaluation/run_evaluation.py
```

The initial runner was originally named `run_evaluation.py`; its exact source was
copied to `run_initial_evaluation.py` before declaring the final scope. The final
runner is `.tmp/change-evaluation/run_evaluation.py`. It saves its reports under
`.tmp/change-evaluation/final/` and records source hashes before and after.

Each source has a pinned identity file, Python patch, architecture policy, and
separate raw JSON reports. The initial aborted run is recorded in
`.tmp/change-evaluation/initial-aborted.json`. Final completed reports, timings,
identities, and coverage are under `.tmp/change-evaluation/final/`. Its
`completion.json` records the unfinished Black history and the time-budget overrun.
`tool-source-drift.json` lists the four changed analyzer files.

## Findings to retain

The available reports distinguish unsupported coverage from absence of findings.
They do not label unresolved imports as clean, and history does not assign an age
to baseline lines with unknown origins. The source-fixture and profiling-input
cost on Black needs an enforced timeout or an explicitly smaller sample before
using this corpus for routine evaluation.

Aggregated excluded coverage cannot always distinguish an absent counterpart from
an unassessed file. A candidate in an affected cohort can therefore remain
unresolved even when the visible file appears new. This conservative result does
not prove that the candidate is new, absent, or clean.

A separate synthetic regression exposed a mapped rename whose current source
failed parsing but whose clone group was reported as removed. Test commit
`385f2c6` captures it through public Git comparison APIs. The implementation was
then corrected. This bug was not found in the public sample and is not counted as
a natural positive.
