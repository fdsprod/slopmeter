# Independent evaluation of the 0.4.0 experiments

Evaluation date: 2026-09-21. This evaluation used the installed released wheel,
not the editable working tree. It changed no detector, metric, threshold, profile,
or repository under review.

> [!IMPORTANT]
> These repositories supplied no qualifying positive cases. The run demonstrates
> source coverage and explicit uncertainty, not detection precision or recall.
> Zero findings does not establish that the repositories lack design problems.

## Selection and execution

HTTPX, Rich, and Black were selected before scanning as established public Python
projects with different roles: HTTP client, terminal rendering, and source
formatting. None is this repository or one of the six calibration repositories.
Rich is a runtime dependency of this tool, so the sample is independent of detector
fixtures and calibration, but not wholly independent of its dependency ecosystem.
The pinned releases are historical snapshots, not claims about current heads.

| Repository / release | Resolved commit | License |
|---|---|---|
| [HTTPX 0.28.1](https://github.com/encode/httpx/tree/26d48e0634e6ee9cdc0533996db289ce4b430177) | `26d48e0634e6ee9cdc0533996db289ce4b430177` | BSD-3-Clause, `LICENSE.md` |
| [Rich v14.1.0](https://github.com/Textualize/rich/tree/2dca1b70359dac61e1bbfb6f14ebe19a5ab79c3d) | `2dca1b70359dac61e1bbfb6f14ebe19a5ab79c3d` | MIT, `LICENSE` |
| [Black 25.1.0](https://github.com/psf/black/tree/8a737e727ac5ab2f1d4cf5876720ed276dc8dc4b) | `8a737e727ac5ab2f1d4cf5876720ed276dc8dc4b` | MIT, `LICENSE` |

The runner was Windows, CPython 3.12.14, with an isolated installation of
`slop-measure==0.4.0`. The release tag resolves to
`7798bd998a4e5be984a5f03dc2607326d6da3830`. The wheel SHA256 is
`b9ea3d0ce5af7e6299b81dc919bfd316f5a2fd6250c0e285c7a38499883864ed`.
Each CLI run used a fresh subprocess. Times below include interpreter startup and
JSON serialization; they are single observations, not benchmark distributions.

No target package was installed, imported, or executed. Source inspection used
the tool and a separate `ast.parse` census. The six scan commands returned exit 0.
All three checkouts remained clean after scanning and source inspection.

## Results

Selection used the normal Git inventory and default `**/*.py` production/test
patterns, exclusions, and generated markers. The only external config entry was
`calibration_profile = "__raw__"`; these experiments do not score regardless.
Examples, benchmarks, scripts, and fixtures were retained when the default policy
selected them. They must not be mistaken for deployed production code.

| Repository | Selected files (production / test) | Parsed / failed | Model assessments: analyzed / unresolved | Model findings | Variant assessments: analyzed / unresolved | Seconds models / variants |
|---|---:|---:|---:|---:|---:|---:|
| HTTPX | 60 (23 / 37) | 60 / 0 | 0 / 107 | 0 | 0 / 0 | 1.012 / 0.577 |
| Rich | 190 (124 / 66) | 190 / 0 | 2 / 266 | 0 | 0 / 0 | 1.744 / 0.800 |
| Black | 289 (58 / 231) | 283 / 6 | 0 / 387 | 0 | 0 / 99 | 2.714 / 1.588 |

The file totals are shared by both commands, not additive. Across 539 selected
files, 533 parsed and six failed. The model unresolved rates are 100%, 99.25%,
and 100%; together 760/762 assessments (99.74%). Ordinary classes count in this
denominator. It is not an eligible-dataclass detection rate.

Black's 99 match assessments were all unresolved. The other repositories had no
match assessments, so their variant unresolved rates are undefined, not zero.
There were no independently observed missing, fallback, or exhaustive supported
handlers to adjudicate. A separate AST census found exactly 107/268/387 class
nodes and 0/0/99 match nodes in successfully parsed selected files, agreeing with
the report counts. This checks accounting, not semantic correctness.

Black also reported two generated files and three files outside configured
cohorts, with zero inferred SLOC for those exclusions. No excluded-directory
records occurred. The six failures were formatter input fixtures:
`pep_572_do_not_remove_parens.py`, `type_param_defaults.py`,
`async_as_identifier.py`, `invalid_header.py`, `pattern_matching_invalid.py`, and
`python2_detection.py`, under `tests/data`. The first deliberately contains
grammar cases rejected by Python; the second declares Python 3.13 syntax that
this Python 3.12 run cannot parse. These are explicit coverage limits, not clean
results or six defects in Black.

## Manual source review

All two analyzed model assessments were inspected. There were no supported
positive findings to inspect. Unresolved samples were selected by distinct
reason and source role, rather than claimed to be a random accuracy sample.

| Public source location | Observation and assessment |
|---|---|
| [Rich `_windows.py:6`](https://github.com/Textualize/rich/blob/2dca1b70359dac61e1bbfb6f14ebe19a5ab79c3d/rich/_windows.py#L6) | `WindowsConsoleFeatures` has two boolean fields, no nullable field and no post-init rejection. Its analyzed empty result matches the narrow rule. |
| [Rich `test_pretty.py:166`](https://github.com/Textualize/rich/blob/2dca1b70359dac61e1bbfb6f14ebe19a5ab79c3d/tests/test_pretty.py#L166) | `Empty` is an empty dataclass. Its analyzed empty result is expected; it is not a positive coupled-state example. |
| [HTTPX `_auth.py:22`](https://github.com/encode/httpx/blob/26d48e0634e6ee9cdc0533996db289ce4b430177/httpx/_auth.py#L22), [`_client.py:188`](https://github.com/encode/httpx/blob/26d48e0634e6ee9cdc0533996db289ce4b430177/httpx/_client.py#L188) | `Auth` is an ordinary class; `BaseClient` has explicit construction. Their unresolved outcomes fit the restricted model contract. |
| [Rich `top_lite_simulator.py:15`](https://github.com/Textualize/rich/blob/2dca1b70359dac61e1bbfb6f14ebe19a5ab79c3d/examples/top_lite_simulator.py#L15) | `Process` is a dataclass, but its integer/string/float/datetime/Literal fields are outside the supported field forms. No qualifying cross-field guard was apparent in the inspected declaration. |
| [Black `brackets.py:60`](https://github.com/psf/black/blob/8a737e727ac5ab2f1d4cf5876720ed276dc8dc4b/src/black/brackets.py#L60), [`linegen.py:99`](https://github.com/psf/black/blob/8a737e727ac5ab2f1d4cf5876720ed276dc8dc4b/src/black/linegen.py#L99) | `BracketTracker` uses container and `Optional` fields. `LineGenerator` is inherited and explicitly constructed. The latter was the only class with a post-init method in the independent census; it is explicitly not a dataclass. Neither establishes a missed supported positive. |
| [Black `generate_schema.py:22`](https://github.com/psf/black/blob/8a737e727ac5ab2f1d4cf5876720ed276dc8dc4b/scripts/generate_schema.py#L22) | The real application match is inside a loop, on an attribute, and uses imported Click class patterns. Unresolved is appropriate; finite local Enum/Literal coverage cannot be inferred. |
| [Black `keep_newline_after_match.py:4`](https://github.com/psf/black/blob/8a737e727ac5ab2f1d4cf5876720ed276dc8dc4b/tests/data/cases/keep_newline_after_match.py#L4), [`line_ranges_formatted/pattern_matching.py:5`](https://github.com/psf/black/blob/8a737e727ac5ab2f1d4cf5876720ed276dc8dc4b/tests/data/line_ranges_formatted/pattern_matching.py#L5) | One fixture has an untyped status parameter and duplicated before/after definitions. The other has an unbound subject and mixed sequence/class/mapping patterns. Neither supplies the required local finite typed subject. |

The Black match population contains 98 formatter-fixture matches and one script
match. It is not 99 independent real-world handlers. HTTPX's local
`ClientState(enum.Enum)` is a useful negative candidate: a finite enum alone does
not qualify without a supported match. Neither HTTPX nor Rich contained a match
node in selected parseable source. No project-specific score tuning follows from
any of these observations.

## Controls and limits

Separately, the existing authored integration `SOURCE` fixtures were copied into
`.tmp/evaluation040/seeded-controls` using AST literal extraction, not importing
test modules. The same installed wheel produced one coupled-state finding and
four analyzed variant handlers: two missing, one fallback, one exhaustive.
These sanity checks confirm the release can emit the advertised outcomes.
They are seeded controls, not independent evidence, and are excluded from every
table and rate above.

No precision, recall, false-positive rate, or false-negative rate is estimable
from this sample. The manual checks support a limited conclusion: explicit
uncertainty and two narrow negative outcomes correspond to inspected syntax.
They do not validate usefulness on repositories with eligible positive cases.

Useful next experiments concern coverage and explanations, not scores:

- Distinguish all-class inventory counts from eligible dataclass counts in the
  summary; ordinary classes dominate these results.
- Investigate accepting unrelated dataclass field types while restricting only
  predicate-participating fields. Container/Optional annotations are a concrete
  observed barrier, but extending them needs new independent positive cases.
- Give unresolved matches specific reasons such as missing type annotation,
  non-parameter subject, or class pattern. Black's single generic reason hides
  distinct limitations that the source review could identify.
- Recruit a separate project with locally typed Enum/Literal match handlers.
  Do not relabel broad class-pattern matches as finite variants merely to improve
  this sample's eligibility count.

## Reproduction and retained evidence

Use an isolated installation of the release wheel above. Clone with the listed
tags, then verify `git rev-parse HEAD` against the full commits in the table:

```powershell
git clone --depth 1 --branch 0.28.1 https://github.com/encode/httpx.git .tmp/evaluation040/httpx
git clone --depth 1 --branch v14.1.0 https://github.com/Textualize/rich.git .tmp/evaluation040/rich
git clone --depth 1 --branch 25.1.0 https://github.com/psf/black.git .tmp/evaluation040/black
```

Create `.tmp/evaluation040/evaluation.toml` containing only
`calibration_profile = "__raw__"`. For each checkout run the following two commands
using the isolated installation's `slop`, capture stdout as UTF-8 JSON and stderr
separately, and time each process. Do not use `--strict`: failed files are part of
the measured coverage. `--lang py` records canonical Python selection.

```text
slop models --root .tmp/evaluation040/REPOSITORY --config .tmp/evaluation040/evaluation.toml --lang py --json
slop variants --root .tmp/evaluation040/REPOSITORY --config .tmp/evaluation040/evaluation.toml --lang py --json
```

Local evidence is under `.tmp/evaluation040`: six `REPOSITORY-COMMAND.json` raw
reports, stderr files, `summary.json` with exact argv/runtime/output SHA256,
per-command assessment extracts, three `REPOSITORY-source-hashes.json` manifests,
and three independent `REPOSITORY-ast-census.json` files. Every selected source
hash was checked against actual file bytes, including failed files. The local
runner scripts are `run_evaluation.py`, `audit_sources.py`, and
`check_controls.py`; generated evidence and third-party source are not committed.

The executable used locally is
`.tmp/release040-artifacts-final/test_built_distribution_instal0/environment/Scripts/python.exe`,
invoked with `-c "from slop_measure.cli import app; app()"`; its import resolved
inside that environment's `site-packages`. `PYTHONPATH` was removed and
`PYTHONIOENCODING=utf-8` set. Absolute roots and checkout newline conversion can
change JSON/source hashes across machines; the pinned commits, selection policy,
and Python version are the comparison anchors. A later Python parser can change
Black's syntax-failure counts. Re-run before comparing rates under another runtime.
