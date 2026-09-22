# GitHub example pilot

Date: 2026-09-21. Research only. No detector, metric, threshold, or calibration
changes were made by this task. Other work already present in the checkout was
left untouched.

## Result

A small search found four merged fixes with regression tests. We inspected the
production diffs, tests, and exact before/fix source, then ran the existing static
detectors. Target code and historical tests were not imported or executed.
Slopmeter source revision: `73b9680f417da8eaf35e02bbf2daba7b55cf2f80`.

| Case | Upstream behavior | Actual Slopmeter result |
|---|---|---|
| [AstrBot #10051](https://github.com/AstrBotDevs/AstrBot/pull/10051) | A failed reranker returned `[]`, which replaced valid retrieval results. The fix propagates the exception so the caller retains those results. | `errors` finds one candidate in `XinferenceRerankProvider.rerank` before the fix and none afterward. |
| [PyRIT #2621](https://github.com/microsoft/PyRIT/pull/2621) | A missing JSON response path became an empty string. The fix raises on missing paths while retaining the valid JSON-null behavior. | No exception handlers occur in the selected module, before or after. This is outside `errors` coverage. |
| [Werkzeug #641](https://github.com/pallets/werkzeug/pull/641) | Appending response content left a stored Content-Length stale. The fix removes the header so it can be recomputed. | Related methods remain explicitly unresolved by `derived` before and after. |
| [NetworkX #5894](https://github.com/networkx/networkx/pull/5894) | Replacing the node dictionary left the cached node view attached to the old dictionary. The fix invalidates that view. | Related methods remain explicitly unresolved by `derived` before and after. |

## What these cases establish

AstrBot supplies a useful supported positive with an upstream fix/test pair. Its
handler already logged the exception, including traceback information; logging
did not make the returned value safe for its caller. We also inspected the pinned
retrieval manager: its assignment replaces results on a normal return, while its
exception branch preserves the prior results. The same PR fixes an uninitialized
model branch outside an exception handler; Slopmeter does not detect that second
path. It does not establish the full caller contract automatically.

PyRIT shows a broader failure-result problem than exception handling. A blanket
rule against empty strings would be wrong: a resolved JSON null remains a valid
empty return after the fix. Extending coverage needs evidence about the contract,
not simply another empty-value pattern.

Werkzeug requires connecting a stored byte length, a mutation through another
method, and later conditional recomputation. It is not `len` of the response
list. NetworkX additionally needs cached-property, descriptor, and alias
semantics. Merely allowing methods in the current detector would not resolve
either dependency. NetworkX is already in our calibration corpus, so this case
cannot count as a new independent calibration or holdout repository.

The upstream tests give stronger labels than suspicious syntax alone, but we did
not rerun them. This is a selected four-case sample, not a precision/recall study.
The unsupported cases must not be reported as clean or counted as supported-scope
false negatives.

## Pinned evidence

For AstrBot and PyRIT, the pair uses the merged fix and its first parent. For
Werkzeug and NetworkX, it uses the concrete production/test fix commit included
in the merged PR and that commit's parent.

| Repository | Before | Fix |
|---|---|---|
| AstrBotDevs/AstrBot | `8492df45e0f5a3360cc0532cce40246cbd501e16` | `081261664caead53312d30118801eed384d86b80` |
| microsoft/PyRIT | `0ef3ecee6c80b96aa0c2e07bb122801bc273bfba` | `4cafa2006e9d813761e19cddb297dfa8f3b905f0` |
| pallets/werkzeug | `80d674429f3ea76a706e6dc2419a3cecf7b2a33b` | `7dc1a447a838cebf4077a9e5c2a3cdd8052f6da5` |
| networkx/networkx | `98060487ad192918cfc2415fc0b5c309ff2d3565` | `8f04f3927cca4ff1cbbedd2fac16e4a0c80881ad` |

Local artifacts are under `.tmp/github-example-pilot/`:

- `errors/`: PR and diff metadata, pinned source/test files, AstrBot caller source,
  source hashes, complete per-file results, `summary.json`, and the fetch/analysis
  script. The selected symbols are `XinferenceRerankProvider.rerank` and
  `_fetch_key`.
- `derived/`: exact source/test/license files, PR/issue/commit metadata,
  `cases.json`, `analysis-summary.json`, detailed `notes.md`, and fetch/analysis
  scripts. Related symbols include `set_data`, `write`, `get_wsgi_headers`,
  `nodes`, and descriptor `__set__`.

The later [public evaluation manifest](../../evaluation/README.md) retains these
cases with source hashes and expected evidence. Downloaded upstream source remains
in the ignored artifact directory.

## Recommended next step

Retain AstrBot as a positive evaluation pair beside the intentional fallback
examples already reviewed. Keep the other three as explicit coverage-gap cases.
For a future derived-state expansion, start by designing how object-field
dependencies and invalidation are represented, using the Werkzeug case as a
concrete target. Keep calibration and scoring unchanged until a broader,
independently labeled sample supports a change.
