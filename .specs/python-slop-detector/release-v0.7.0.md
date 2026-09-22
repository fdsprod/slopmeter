# Slopmeter v0.7.0

This release improves clone change matching, budget explanations, and import
context. It preserves snapshot measurements and calibration. The README now
starts with an agent review workflow; the detailed reference is under `docs/`.

## Edited clones and new copies

`changes` can now retain correspondence when a clone's normalized syntax changes.
Four existing copies edited together report four modified members and zero
additions. A fifth copy still reports one addition. This corrects introduction
budgets that previously counted coordinated edits as new copies.

Matching requires mapped files, unique declaration owners and statement suites,
and a majority of unchanged complete statements with at least two distinct
anchors. Matching names alone do not prove continuity. Weak matches, duplicate
qualified declarations, and competing split/merge relationships remain unresolved.

JSON includes `baseline_fingerprint`, `current_fingerprint`, and `modified`.
Changed members retain evidence from both sides. Saved reviews still become
stale when their source or evidence changes; correspondence does not reapprove them.

## Budget explanations

Budget checks now include `incomplete_details` with reason codes, source sides,
paths, and spans when available. Terminal output shows those locations. Aggregate
limits retain population scope rather than invented file locations. The existing
`incomplete_reasons` messages remain available.

Unchanged unsupported handlers still make the error budget incomplete. These
changes do not turn missing coverage into a passing result. Budgets remain
advisory unless `--enforce-budget` is explicitly selected.

## Literal state comparisons

`.state` comparisons are described as syntax evidence with unknown semantic
intent. A field can contain geographic, lifecycle, or other values. The detector
keeps the observations without recommending lifecycle types from the field name
alone. No values are suppressed or placed on a project-specific allowlist.

## Import context

`architecture` adds execution and guard context to import observations:

- Eager syntax, deferred function bodies, or unknown timing.
- Conditional and recognized positive `typing.TYPE_CHECKING` guards.
- Conservative handling of shadowing, alias mutation, and dynamic namespace writes.
- Unknown timing for annotation and lazy type-alias expressions.

Cycle output includes edge paths and contexts. All static edges still contribute
to cycles and declared-rule checks. A type-checking or deferred edge does not
prove an import-time failure. No target code is executed.

## Compatibility and limits

- Snapshot scoring is unchanged: profile `py-2026.3`, M4 version 3, the same six
  historical reference projects, and unchanged thresholds and weights.
- Existing change and architecture reports load. Missing legacy import context
  remains unknown. Older strict readers can reject the new additive report fields.
- Review stores and ledgers need no migration for these changes. Source changes
  still require review; no automatic approval or suppression was added.
- Broader calibration and independent detector holdouts remain future work.
  Scores and experimental findings remain advisory review evidence.

## Validation

The implementation passed 2,069 deterministic tests with 93.83% package coverage.
Four wheel/source archive and isolated-install checks passed separately. Learning
and performance checks passed 69 tests with one skip. The cached public source
evaluation passed all 16 jobs and 137 checks. These selected cases are regression
evidence, not population precision/recall estimates.

A self-scan found no new pattern or exception-fallback candidates. On identical
source, complete score JSON matched the v0.6.0 executable before the version bump.
No evaluator thresholds were changed to favor this repository.

## Install or upgrade

Install the command in an isolated tool environment:

```sh
uv tool install --upgrade --python 3.12 https://github.com/fdsprod/slopmeter/releases/download/v0.7.0/slop_measure-0.7.0-py3-none-any.whl
uv tool update-shell
slop score . --lang py --top 10
```

Or install with pip in your selected Python environment:

```sh
python -m pip install --upgrade https://github.com/fdsprod/slopmeter/releases/download/v0.7.0/slop_measure-0.7.0-py3-none-any.whl
```

Python 3.12 or later is required. The release includes the wheel, source archive,
and `SHA256SUMS.txt`. Packages are distributed through GitHub releases.
