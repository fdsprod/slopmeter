# Public source evaluation

`public-cases.json` records six selected cases from five repositories. It pins
source revisions, source bytes, review labels, and expected detector results.
Use it to check behavior and coverage without changing scores or thresholds.
This is a regression set. It is not a representative precision or recall study.

## Run the cases

From the repository root, download the pinned files and run the evaluation:

```powershell
.\.venv\Scripts\python.exe tools/evaluate.py --manifest evaluation/public-cases.json --cache .tmp/public-evaluation-cache --output .tmp/public-evaluation-first --timeout 180 --fetch
```

For later runs, use the verified cache and a new output directory. Omit `--fetch`
to run without downloads:

```powershell
.\.venv\Scripts\python.exe tools/evaluate.py --manifest evaluation/public-cases.json --cache .tmp/public-evaluation-cache --output .tmp/public-evaluation-repeat --timeout 180
```

The runner analyzes selected source files. It must not import target packages,
install their dependencies, or run their tests. Downloaded source stays in the
ignored cache. Each source entry has a SHA-256 hash. A cached or downloaded file
must match that hash before analysis.

The manifest uses the raw profile (`__raw__`) and disables generated-file markers
for this explicit selection. It does not change application defaults. Paths keep
their original relative names. Each snapshot contains only its listed files,
not the complete repository. These cases therefore do not establish cross-file
resolution, repository-wide clone coverage, architecture coverage, or runtime
behavior. In particular, source imports are parsed rather than resolved by
importing the target.

Keep the analyzer revision and source hashes with each result. A run that changes
the analyzer while work is in progress is not a frozen baseline. An incomplete,
timed-out, or mismatched run does not establish absence of findings.

## Cases and expected interpretations

| Case | Review label | Expected evidence |
|---|---|---|
| [AstrBot fix #10051](https://github.com/AstrBotDevs/AstrBot/pull/10051) | Supported positive | `rerank` has one exception-to-empty-list candidate before the fix and none after. Change review reports the candidate as removed. |
| [AstrBot provider introduction](https://github.com/AstrBotDevs/AstrBot/commit/90a65c35c16187864a4829cdec04535b8ab234c5) | Supported positive | The original file addition introduces the same kind of fallback evidence. The parent has no file at that path. |
| [HTTPX known-encoding predicate](https://github.com/encode/httpx/blob/89599a9541af14bcf906fc4ed58ccbdf403802ba/httpx/_models.py#L56-L64) | Intentional | `_is_known_encoding` returns `False` when codec lookup fails. Keep its candidate visible and persisted. Its documented predicate contract makes this an intentional fallback. |
| [PyRIT fix #2621](https://github.com/microsoft/PyRIT/pull/2621) | Coverage gap | Missing JSON paths previously became an empty string. The selected module has no exception handlers, so `errors` has no subjects to assess. |
| [Werkzeug fix #641](https://github.com/pallets/werkzeug/pull/641) | Coverage gap | Appending response bytes leaves Content-Length stale. All 112 functions remain unresolved by the local stored-count detector. |
| [NetworkX fix #5894](https://github.com/networkx/networkx/pull/5894) | Coverage gap | Replacing the node dictionary leaves a cached view attached to the old dictionary. The selected files have 144 unresolved functions before and 145 after. |

The AstrBot introduction is a real forward parent/child pair. It is not the fix
run backward. The GitHub commit records the provider file as added. This label
establishes introduction of detectable fallback evidence. We have not established
the complete caller contract at that earlier revision. The later fix and its
regression tests support the separate fix case.

HTTPX contains a second candidate in `Headers.__eq__`. Both candidates remain in
the selected module's counts. The manifest also checks the named encoding
predicate and its `LookupError`/`False` evidence so a replacement finding cannot
satisfy the intended control through totals alone. The HTTPX source file is
byte-identical at the two selected revisions.

PyRIT has zero eligible handlers, not a clean contract result. Its fix retains an
empty string for a resolved JSON null while raising for missing paths. That
distinction needs contract information beyond an empty-value syntax rule.

Werkzeug needs byte-length, object-field, header-entry, and cross-method
invalidation reasoning. NetworkX also needs descriptors, cached properties, and
aliases. Enabling methods alone would not address either case. The manifest
checks unresolved coverage and selected method identities as well as zero
findings. When supported scope changes deliberately, review these expectations
against source evidence before updating them.

## Evidence strength and independence

The four fix cases come from merged upstream changes with regression tests. We
read the source, diffs, and tests. We did not run the upstream tests:

- [AstrBot regression tests](https://github.com/AstrBotDevs/AstrBot/blob/081261664caead53312d30118801eed384d86b80/tests/test_xinference_rerank_source.py)
- [PyRIT regression tests](https://github.com/microsoft/PyRIT/blob/4cafa2006e9d813761e19cddb297dfa8f3b905f0/tests/unit/prompt_target/target/test_http_target_parsing.py)
- [Werkzeug regression tests](https://github.com/pallets/werkzeug/blob/7dc1a447a838cebf4077a9e5c2a3cdd8052f6da5/tests/test_wrappers.py)
- [NetworkX regression tests](https://github.com/networkx/networkx/blob/8f04f3927cca4ff1cbbedd2fac16e4a0c80881ad/networkx/classes/tests/test_graph.py)

The JSON checks assert evidence, not defects. A removed finding does not prove a
fix. An intentional finding does not require suppression. An unsupported case is
not a measured false negative within supported scope.

The two AstrBot cases share one repository lineage. NetworkX is already in the
calibration corpus. None of these cases is a fresh independent holdout: they were
selected and inspected during development. Keep future holdouts separate by
repository lineage. Do not pool these observations into calibration populations.

Only metadata and labels are committed here. Downloaded upstream source and
licenses remain external evaluation artifacts under `.tmp`; upstream licensing
still applies to those files.

## Relationship to the earlier public evaluation

The [bounded change evaluation](../.specs/python-slop-detector/change-evidence-evaluation.md)
already records broader HTTPX, Rich, and Black parent/child scans. It covers
changes, architecture, and bounded history under a different source selection.
Those runs contained persisted findings, but no introduced or removed finding.
The Black changes run exceeded its intended 180-second limit, and its history
run was not completed. Analyzer files also changed during that evaluation.

This manifest retains the HTTPX predicate as a smaller interpretation control.
It does not reproduce or replace those full-repository results. The new AstrBot
pairs fill the introduction/removal gap for exception fallback evidence. The
runner's timeout controls address the earlier orchestration limit. Broader
architecture, history, rename, and failure controls remain separate tests or
future evaluation cases.

The [GitHub pilot note](../.specs/python-slop-detector/github-example-pilot-2026-09.md)
records the original investigation and its limits.

## Manifest contract

Schema version 1 has a `cases` list. Each case declares its repository, review
label, rationale, evidence URL, and two snapshots. Each snapshot pins a full
40-character commit ID and a list of relative Python paths with SHA-256 hashes.
An empty list represents a deliberately empty selected scope, as in the AstrBot
introduction's parent. It is not permission to ignore a missing cached file.

Each run selects either a snapshot command (`errors` or `derived`) or change
review across the two snapshots. Checks use RFC 6901 JSON pointers and explicit
expected JSON values. Summary counts sit beside checks for subject identity,
fallback kind, and unresolved state. Expectations require review when an analysis
definition changes. Do not replace them automatically with current output.
