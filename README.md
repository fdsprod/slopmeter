# Slopmeter

**Agent-first code review for Python.**

[![CI](https://github.com/fdsprod/slopmeter/actions/workflows/ci.yml/badge.svg)](https://github.com/fdsprod/slopmeter/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)
[![GitHub release](https://img.shields.io/github/v/release/fdsprod/slopmeter)](https://github.com/fdsprod/slopmeter/releases)

Slopmeter gives coding agents and reviewers source evidence to assess a change.
It detects redundant patterns, duplicated code, and excess complexity, then shows
where each finding comes from. Change reports distinguish new findings from
existing debt and keep uncertain matches visible.

Use it before a commit, during pull request review, or to choose where a refactor
needs closer inspection. Analysis runs locally, requires no model API key, and
does not execute the source it inspects. It evaluates engineering signals, not
whether a human or an AI wrote the code.

[Quick start](#quick-start) · [Agent workflow](#built-for-coding-agents) ·
[Examples](#see-it-in-action) · [Commands](#command-guide) ·
[Reference](docs/reference.md)

## What it helps you review

| Review question | Evidence |
|---|---|
| Did this change add avoidable repetition? | Introduced pattern findings, clone members, and changes to existing clone groups. |
| Where should I inspect existing code? | File rankings, redundant source lines, clone locations, and callable complexity. |
| Is the change extending existing code or adding new structure? | Added, modified, moved, and unresolved Python declarations. |
| Does it cross a declared dependency boundary? | Direct import violations, module fan-out, and source dependency cycles. |
| Could a fallback hide a failure? | Supported exception handlers that return literal defaults, with surrounding evidence. |
| Does a state check deserve closer review? | Literal `.state` comparisons and experimental model, variant, and derived-state checks. |
| How much recent work was changed again? | Bounded Git history, source churn, and rework with known introduction dates. |

Python is the supported analysis language. New change, architecture, history,
and experimental findings remain separate from calibrated snapshot scores.
See the [reference](docs/reference.md) for each detector's supported scope.

Version 0.7 distinguishes supported edits to existing clones from new copies,
locates incomplete-budget evidence, and shows import execution context. Snapshot
scores and calibration are unchanged. See the [release notes](.specs/python-slop-detector/release-v0.7.0.md).

## Quick start

Install the [v0.7.0 release](https://github.com/fdsprod/slopmeter/releases/tag/v0.7.0)
with [uv](https://docs.astral.sh/uv/getting-started/installation/):

```sh
uv tool install --upgrade --python 3.12 https://github.com/fdsprod/slopmeter/releases/download/v0.7.0/slop_measure-0.7.0-py3-none-any.whl
uv tool update-shell
```

This command installs or upgrades the pinned release. If your `PATH` changes,
open a new terminal. Then run `slop` **from the project you
want to review**:

```sh
# Rank files in the current project.
slop score . --lang py --top 10

# Review the last commit.
slop changes HEAD~1 HEAD --repo .

# Review local work against the latest commit.
slop changes HEAD WORKTREE --repo . --json
```

You can also supply another project's path: `slop score /path/to/project`.
Git revision commands require the repository root in `--repo` and the requested
commits in local history. `WORKTREE` includes eligible untracked files.

The installed command works without a Slopmeter checkout or project-environment
activation. [uv keeps tools in a separate environment](https://docs.astral.sh/uv/guides/tools/).
Python 3.12 or later is required. Normal scans work offline.

Releases are distributed through GitHub. For pip, source installation, Windows
executable paths, and upgrades, see [installation options](docs/reference.md#installation-options).
The package is `slop-measure`, the command is `slop`, and the Python import is
`slop_measure`.

## Built for coding agents

The CLI and [Python API](docs/reference.md#new-python-entry-points) expose reports that an agent can inspect and
compare. JSON retains source locations, evidence, configuration, and coverage
limits. Finding records stay visible when an agent decides to keep the code.

| Agent need | Slopmeter support |
|---|---|
| Read evidence without parsing terminal tables | Native JSON from analysis commands and typed Python reports. |
| Separate new findings from existing debt | Finding continuity across directories, commits, and local work. |
| Avoid treating missing analysis as a clean result | Diagnostics, excluded scope, and explicit unresolved or unavailable outcomes. |
| Leave a review that another person or agent can assess | Saved-report targets and attributed decisions with reasons and next steps. |
| Recheck a decision after an edit | Source-bound review applicability and retained decision history. |
| Apply a repository's chosen limits | Explicit change budgets with distinct exceeded and incomplete outcomes. |

A practical agent workflow is:

1. Run a snapshot or change report with `--json`.
2. Read coverage and diagnostics before interpreting counts.
3. Inspect the cited source and its callers. Check repository conventions and reuse.
4. Classify each reviewed candidate as `actionable`, `defer`, or `no-change`.
5. Make justified changes, run the relevant tests, and generate a fresh report.

For example, give an agent this instruction:

```text
Review my changes using Slopmeter.

Run slop changes HEAD WORKTREE --repo . --json.
Check coverage, diagnostics, and unresolved evidence first.
For each candidate you review, inspect the source and surrounding contracts.
Report its location, evidence, disposition, reason, and next step.
Look for existing repository functionality before proposing new code.
Do not change code solely to lower a score.
After any edit, run the relevant tests and regenerate the report.
```

### Keep an attributed review

Save a native snapshot report as UTF-8, then list its review targets:

```sh
slop score . --lang py --json > snapshot.json
slop review-report list --report snapshot.json --kind pattern --json
```

In Windows PowerShell, use explicit UTF-8 output:

```powershell
slop score . --lang py --json | Set-Content -Encoding utf8 snapshot.json
```

Copy a target ID from `list` and record the decision:

```sh
slop review-report set TARGET_ID --report snapshot.json --store decisions.json --actor reviewer-name --disposition actionable --reason "The returning branch makes this else unnecessary." --next-step "Remove the else and run the behavior tests."
slop review-report show --report snapshot.json --store decisions.json --json
```

`review-report` reads the saved report. Regenerate it after edits to assess whether
a decision still applies. It accepts native `score`, `models`, `variants`,
`derived`, and `errors` reports. Change reports are a separate workflow.
Only explicit review-write commands update the local ledger. See the
[review reference](docs/reference.md#attributed-review-history-for-all-finding-types)
for applicability, history, and compatibility rules.

## See it in action

Suppose `before/` is empty and `after/workflow.py` contains:

```python
def display_name(value):
    if value:
        return value
    else:
        return "unknown"


def require_ready(item):
    assert item.state != "unresolved"
```

### Review the change

```sh
slop changes before after --lang py
```

Output excerpt, captured from the current source checkout:

```text
Patterns: introduced 1, removed 0, persisted 0, changed 0, unresolved 0
  introduced: workflow.py:4 py.redundant-else-after-return
Clone groups: 0; added members: 0
Exception fallbacks: introduced 0, removed 0, persisted 0, changed 0, unresolved 0
Literal state-field comparisons: introduced 1, removed 0, persisted 0, changed 0, unresolved 0
  introduced: workflow.py:9 item.state ne ('unresolved',) (assertion)
```

The first finding points to an unnecessary `else` after a returning branch.
The second identifies a literal state-field comparison. It does not infer the
receiver's type or what its states mean. Review that contract before choosing
an enum, a concrete variant check, or no change.

### Read structured output

```sh
slop changes before after --lang py --json
```

The same report includes these summary fields. Detailed findings, source hashes,
locations, and coverage are omitted from this excerpt:

```json
{
  "summary": {
    "introduced": 1,
    "removed": 0,
    "persisted": 0,
    "changed": 0,
    "unresolved": 0
  },
  "state_dispatch_summary": {
    "introduced": 1,
    "removed": 0,
    "persisted": 0,
    "changed": 0,
    "unresolved": 0
  }
}
```

### Inspect the snapshot

```sh
slop score after --lang py --ascii --no-color
```

File-table excerpt from the same example:

```text
Files (score order)
  File | Score | Patterns | Clones | Erosion
  workflow.py | 50.0/100 | 14.3% | 0.0% | 0.0%

1 finding | use explain for source evidence
```

The score uses the `py-2026.3` reference profile. **50.0 points does not mean
50 percent of the code is bad.** Pattern verbosity here is one flagged line out
of seven source lines. The literal state-field candidate does not affect the score.

## Command guide

Run these commands from the target project. Add `--json` for structured output,
or use `slop COMMAND --help` for the complete options.

| Task | Command |
|---|---|
| Rank files | `slop score . --lang py --top 10` |
| Browse a directory view | `slop tree . --lang py` |
| Explain a file or callable | `slop explain src/app.py --root . --symbol MyClass.method` |
| List clone evidence | `slop findings --root . --metric m3 --json` |
| List available pattern rules | `slop rules --root .` |
| Compare score and metric movement | `slop compare HEAD~1 HEAD --repo .` |
| Review introduced evidence | `slop changes HEAD WORKTREE --repo .` |
| Count declaration changes | `slop surface HEAD~1 HEAD --repo .` |
| Check a declared import policy | `slop architecture --root . --policy architecture.toml` |
| Inspect source churn and rework | `slop history HEAD~20 HEAD --repo . --window-days 14` |
| Review exception fallbacks | `slop errors --root . --lang py` |
| Inspect experimental state-model evidence | `slop models --root .`, `slop variants --root .`, `slop derived --root .` |

`score` and `compare` report calibrated measurements. `changes` reports finding
continuity. `scan` is an alias for `score`. Production and test populations stay
separate. `--top` limits terminal output, not analysis work or JSON evidence.

## Configure the review

Put analysis settings in `slop.toml`, use `[tool.slop]` in `pyproject.toml`, or pass
an explicit file with `--config`. For example:

```toml
languages = ["python"]
test_patterns = ["tests/**/*.py", "**/test_*.py"]
```

Explicit lists replace defaults. Exclusions and generated-file markers affect
coverage. Review the [configuration reference](docs/reference.md#read-a-snapshot)
before changing thresholds or scope.

### Set an explicit change budget

Save this example as `budget.toml`:

```toml
[[limits]]
metric = "introduced-patterns"
maximum = 0
```

```sh
# Advisory report.
slop changes HEAD~1 HEAD --repo . --budget budget.toml

# Enforce the declared limit in automation.
slop changes HEAD~1 HEAD --repo . --budget budget.toml --enforce-budget --json
```

Budgets support `introduced-patterns`, `added-clone-members`, and
`introduced-errors`. Existing unchanged debt does not consume an introduction
budget. The example cap is a policy choice, not a calibrated recommendation.

| Exit code | Meaning |
|---|---|
| `0` | Completed advisory analysis, or an enforced budget passed. |
| `1` | An explicitly enforced budget exceeded its limit. |
| `2` | Invalid arguments, configuration, policy, or source selection. |
| `3` | Strict analysis failed, or an enforced budget has incomplete evidence. |

An incomplete assessment cannot establish a passing enforced budget. With
`--budget --json`, the output contains separate `report` and `budget` objects.
See [budget details](docs/reference.md#explicit-change-budgets) and the
[architecture policy format](docs/reference.md#check-declared-architecture).

## Interpret results

- Use findings to direct source review. Scores measure selected signals against
  a reference corpus. They do not establish correctness or authorship.
- Check coverage first. No findings, no assessed subjects, and failed analysis
  are different results. Excluded files can leave change matching unresolved.
- Keep justified duplication, validation, and fallbacks when contracts require
  them. Record the reason instead of optimizing for a lower count.
- Compare scores only under compatible profiles and settings. The current profile
  uses a small historical Python corpus. It is not a universal quality benchmark.

Semantic reimplementation detection and general cross-file correctness are not
implemented. The [delivery plan](.specs/python-slop-detector/change-evidence-plan.md)
separates supported evidence from remaining research.

## Documentation and development

| Resource | Contents |
|---|---|
| [Reference](docs/reference.md) | Installation options, configuration, measurement definitions, and review contracts. |
| [Pattern catalog](.specs/python-slop-detector/pattern-catalog.md) | Rule IDs, scope, and examples. |
| [Public evaluation](evaluation/README.md) | Reproducible cases, source hashes, expected evidence, and coverage limits. |
| [Change-evidence plan](.specs/python-slop-detector/change-evidence-plan.md) | Implemented features and research backlog. |
| [Releases](https://github.com/fdsprod/slopmeter/releases) | Installable artifacts and release notes. |

For source development, use the pinned uv version, **0.11.14**:

```sh
git clone https://github.com/fdsprod/slopmeter.git
cd slopmeter
uv sync --all-groups --locked
uv run slop score src --lang py
```

The [development checks](docs/reference.md#development-checks) cover linting,
types, package boundaries, tests, and distribution builds. CI runs on Windows,
macOS, and Linux with Python 3.12, 3.13, and 3.14.
