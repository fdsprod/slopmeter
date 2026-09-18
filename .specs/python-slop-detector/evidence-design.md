# Evidence navigation

TB-8 reads the existing immutable report. Queries do not rerun analyzers or assign
scores to callables. `explain` retains its shipped name and full-report JSON mode.

## Source ownership

File, finding, clone, and change queries take an explicit `SourceSide`, defaulting
to current. A baseline query on a snapshot is an input error. A comparison selector
uses the path on the selected side, including deleted and renamed baseline files.
It does not guess another path or substitute evidence from the other source state.

The explanation shows the selected file's raw metrics, score contributions,
callables, findings, complete clone groups, and diagnostics. A comparison also
shows the matching change, both available paths, line counts, and metric deltas.

## Finding selection

Keep different evidence families in separate collections:

```datamodel
FindingSelection
  patterns: ReportFinding[]
  clone_groups: ReportCloneGroup[]
  functions: ErosionFinding[]

ErosionFinding
  source: SourceSide
  language: string
  cohort: Cohort
  function: FunctionEvidence
```

The default selection contains pattern findings, clone groups, and functions whose
complexity exceeds the configured threshold. A path filter uses an exact normalized
project path. A clone group matches if any member has that path; retain all members
so the duplicate remains explainable. No match returns empty collections.

| Metric filter | Selected evidence |
|---|---|
| `m2` or `m2.pattern-verbosity` | Pattern findings |
| `m3` or `m3.clone-verbosity` | Clone groups |
| `m4` or `m4.erosion` | Eroded functions |
| `combined` or `verbosity.combined` | Pattern findings and clone groups |

Rule and severity filters apply to pattern findings. Other families have no native
rule ID or severity, so those filters exclude them. Do not invent severities for
clone groups or functions. Filters compose. Unknown metrics are input errors.

`findings --json` emits a versioned selection document with analysis identity,
provenance, and all matching evidence. Terminal `--top` never truncates this JSON.
The three collections preserve stable source/path/line/identity ordering.

## Rule catalog

Move the existing immutable rule metadata into the domain layer and retain its old
import as a compatibility export. The application builds a `RuleCatalog` containing
language, catalog version, and entries with metadata plus resolved enabled state.
The renderer has no dependency on the Python adapter. Unknown configured rules
remain configuration errors. Listing rules does not analyze source files.

## Commands

```text
slop explain FILE --root CURRENT --baseline-root BASE --source baseline
slop explain FILE --root REPO --rev CURRENT --baseline-rev BASE --source current
slop findings --root DIRECTORY --path FILE --metric m2 --severity warning
slop findings --root REPO --baseline-rev HEAD --source baseline --json
slop rules --root DIRECTORY --json
```

`--rev` selects a current Git snapshot. Without it, current means the working
directory. `--baseline-root` and `--baseline-rev` are mutually exclusive. A Git
baseline uses the current repository root. All inputs share the current root's
configuration. Display controls follow the existing color, ASCII, width, and
omission conventions.
