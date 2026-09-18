# Python Slop Detector Specification

**Status**: Approved

## Problem Statement

Python projects can remain functionally correct while they accumulate redundant code,
structural duplication, and concentrated complexity. Existing tools expose parts of
this problem, but they do not provide one deterministic report with evidence and
comparable scores at file and project scope.

## Goals

- [x] Measure M1 LOC delta, M2 pattern verbosity, M3 clone verbosity, and M4
      structural erosion for Python projects.
- [x] Report raw values, normalized scores, and source-level evidence for each
      available measure.
- [x] Produce separate file and project results from the same underlying evidence.
- [x] Keep snapshot quality separate from change pressure when no baseline exists.
- [x] Expose language-neutral contracts so a later TypeScript analyzer can produce
      the same report schema.
- [x] Produce deterministic results without an LLM or network access.

## Out of Scope

- Proving functional correctness.
- Combining security, test coverage, formatting, documentation, or type coverage
  into the slop score.
- Automatically rewriting flagged code in the first release.
- A hosted service or graphical user interface in the first release.
- TypeScript analysis in the first release.
- Treating raw LOC or project size as snapshot slop.

## Measure Definitions

### M1: LOC Delta

For a comparison target:

```text
loc_delta = current_sloc - baseline_sloc
```

The result also records added SLOC, deleted SLOC, baseline SLOC, current SLOC, and
growth rate. M1 is unavailable during a snapshot-only scan. Unavailable is an
explicit result state and is not represented as zero.

### M2: Pattern Verbosity

```text
pattern_verbosity = unique_pattern_flagged_sloc / total_sloc
```

Each finding identifies its rule, category, severity, file, source span, message,
and optional remediation. Lines hit by multiple pattern rules count once in the
ratio.

### M3: Clone Verbosity

```text
clone_verbosity = unique_cloned_sloc / total_sloc
```

Clone detection uses normalized syntax rather than raw text. Clone groups can span
files. Comments, blank lines, docstrings, imports, signatures without duplicated
bodies, and blocks below the configured minimum do not create clone evidence.

### Derived: Combined Verbosity

```text
combined_verbosity =
    size(pattern_flagged_lines union clone_lines) / total_sloc
```

M2 and M3 remain visible, but combined verbosity prevents a line from contributing
twice to the aggregate score.

### M4: Structural Erosion

For each function or method:

```text
mass(function) = cyclomatic_complexity(function) * sqrt(function_sloc)
```

```text
erosion = high_complexity_mass / total_mass
```

A function is high complexity when its cyclomatic complexity is greater than 10 by
default. A scope with no functions returns an explicit not-applicable result rather
than zero.

## Score Semantics

- Every measured scope receives raw M2, M3, combined verbosity, and M4 values.
- Every comparison receives raw M1 values.
- The detector maps raw values to 0-100 scores through a versioned calibration
  profile built from maintained human Python repositories.
- File scores use a file-level reference distribution. Project scores use a
  project-level reference distribution.
- `0` means low detected slop relative to the reference population. `100` means
  high detected slop relative to that population.
- A snapshot slop score combines combined verbosity and erosion. M2 and M3 are not
  added again after their union contributes through combined verbosity.
- A change-pressure score uses M1 and later history measures. It remains separate
  from the snapshot slop score.
- Reports always identify the calibration profile and rule-set versions.

## User Stories

### P1: Scan a Python Project

**User Story**: As a developer, I want to scan a Python directory so that I can see
snapshot slop for each file and for the project.

**Acceptance Criteria**:

1. WHEN the user scans a directory THEN the system SHALL discover supported Python
   source files while honoring configured exclusions.
2. WHEN analysis completes THEN the system SHALL report M2, M3, combined verbosity,
   and M4 raw values for each file and for the project.
3. WHEN a source line contributes to several findings THEN the system SHALL count
   that line once in each union-based metric.
4. WHEN a file has no functions THEN the system SHALL report erosion as not
   applicable.
5. WHEN a file cannot be parsed THEN the system SHALL record a parse diagnostic and
   continue with other files unless strict mode is enabled.

**Independent Test**: Scan a fixture project with known patterns, cross-file clones,
and high-complexity functions. Compare every raw count with the expected manifest.

### P1: Compare Two Project States

**User Story**: As a developer, I want to compare two project states so that I can
measure LOC delta per file and for the project.

**Acceptance Criteria**:

1. WHEN the user supplies two directories THEN the system SHALL calculate M1 from
   their normalized source inventories.
2. WHEN the user supplies supported Git revisions for a target repository THEN the
   system SHALL calculate the same M1 result without modifying the target checkout.
3. WHEN a file is added, deleted, or renamed THEN the system SHALL represent that
   change explicitly.
4. WHEN no baseline is supplied THEN the system SHALL report M1 as unavailable.

**Independent Test**: Compare two fixtures containing added, removed, renamed, and
modified Python files. Verify per-file totals reconcile with the project totals.

### P1: Inspect Evidence

**User Story**: As a developer, I want every score to link to evidence so that I can
decide whether each finding is useful or a false positive.

**Acceptance Criteria**:

1. WHEN a rule flags code THEN the report SHALL include a stable rule identifier and
   exact source span.
2. WHEN duplicate code is found THEN the report SHALL identify every member of the
   clone group.
3. WHEN erosion is nonzero THEN the report SHALL list the functions that contribute
   high-complexity mass.
4. WHEN a score is emitted THEN the report SHALL include the raw inputs used to
   derive it.

**Independent Test**: Select each finding from a fixture report and verify that its
path and span identify the expected source.

### P1: Consume Stable Output

**User Story**: As a tool author, I want a versioned JSON report and Python API so
that CI systems and future interfaces can consume results safely.

**Acceptance Criteria**:

1. WHEN JSON output is requested THEN the system SHALL emit a schema-versioned
   document with project, file, metric, score, finding, diagnostic, and provenance
   records.
2. WHEN the Python API analyzes the same target and configuration THEN it SHALL
   return the same domain result used by the CLI serializer.
3. WHEN a future language adapter supplies valid normalized evidence THEN the core
   scorer SHALL process it without language-specific branches.

**Independent Test**: Analyze one fixture through the API and CLI. Assert equivalent
JSON after removing invocation-only metadata.

### P1: Configure Analysis Boundaries

**User Story**: As a project maintainer, I want to exclude generated, vendored,
fixture, or migration code so that the score represents code I maintain.

**Acceptance Criteria**:

1. WHEN exclusion patterns are configured THEN the system SHALL omit matching files
   from evidence, denominators, and scores.
2. WHEN the target is a Git repository THEN default discovery SHALL honor ignored
   files unless the user overrides that behavior.
3. WHEN configuration changes the rule set, clone threshold, complexity threshold,
   or exclusions THEN the report SHALL record the effective configuration.

**Independent Test**: Scan the same fixture with two configurations. Verify excluded
files have no effect on totals.

### P1: Score Files and Projects

**User Story**: As a developer, I want comparable 0-100 file and project scores so
that I can locate hotspots and track a project over time.

**Acceptance Criteria**:

1. WHEN a compatible calibration profile is installed THEN the system SHALL emit
   file and project snapshot slop scores from their respective reference
   distributions.
2. WHEN no compatible calibration profile exists THEN the system SHALL emit raw
   measures and an explicit score-unavailable state.
3. WHEN project results are calculated THEN the system SHALL aggregate raw evidence
   before scoring rather than averaging file scores.
4. WHEN a score is compared across runs THEN the report SHALL expose enough version
   information to determine whether the comparison is valid.

**Independent Test**: Score fixed fixtures with a fixed calibration profile. Assert
exact scores and verify that adding many clean tiny files does not hide one large
sloppy file through unweighted averaging.

### P2: Enforce a CI Quality Gate

**User Story**: As a maintainer, I want configurable regression thresholds so that
CI fails when a change introduces new slop.

**Acceptance Criteria**:

1. WHEN a comparison exceeds a configured regression budget THEN the CLI SHALL exit
   with a documented nonzero status.
2. WHEN existing debt is unchanged THEN a changed-lines-only gate SHALL not fail
   because of that existing debt.
3. WHEN a gate fails THEN the report SHALL identify the measures and files that
   exceeded the budget.

**Independent Test**: Run the gate against one improving change and one regressing
change. Verify their exit statuses and evidence.

### P2: Add Cognitive Erosion

**User Story**: As a developer, I want nested control flow measured separately so
that hard-to-read functions are found even when cyclomatic complexity is moderate.

**Acceptance Criteria**:

1. WHEN cognitive analysis is enabled THEN the system SHALL report cognitive mass
   and cognitive erosion through the same metric contract.
2. WHEN nesting contributes to cognitive erosion THEN the aggregate score SHALL not
   also count an equivalent nesting pattern penalty without an explicit overlap
   policy.

**Independent Test**: Compare functions with equal cyclomatic complexity but
different nesting depth. Verify their cognitive results differ.

### P2: Add Coupling Analysis

**User Story**: As a developer, I want dependency cycles and excessive module
fan-out identified so that architectural slop is visible.

**Acceptance Criteria**:

1. WHEN project imports form a cycle THEN the system SHALL identify every member of
   that cycle.
2. WHEN file coupling is reported THEN the project result SHALL derive from the
   dependency graph rather than an average of file scores.

**Independent Test**: Analyze an acyclic fixture and a fixture with known dependency
cycles. Verify cycle membership and project totals.

### P2: Add Churn and Rework Analysis

**User Story**: As a maintainer, I want code churn and short-term rework measured so
that unstable code is not hidden by a small net LOC delta.

**Acceptance Criteria**:

1. WHEN history is available THEN the system SHALL distinguish net LOC delta from
   added-plus-deleted churn.
2. WHEN recently added code changes again inside the configured window THEN the
   system SHALL include it in rework evidence.

**Independent Test**: Analyze a fixture Git history with zero net LOC delta and
nonzero churn. Verify the two results remain distinct.

### P3: Add TypeScript Support

**User Story**: As a TypeScript developer, I want the same report contract and score
semantics so that projects in both languages can be compared consistently.

**Acceptance Criteria**:

1. WHEN a TypeScript adapter is installed THEN the system SHALL analyze TypeScript
   files without changing the core report schema.
2. WHEN language-specific rules run THEN findings SHALL identify their language and
   rule-set version.
3. WHEN a mixed-language project is scanned THEN the system SHALL retain per-language
   evidence before project aggregation.

**Independent Test**: Run Python and TypeScript fixture adapters through the same
core aggregation and serialization contract.

## Edge Cases

- WHEN a target contains zero supported SLOC THEN ratio measures SHALL be not
  applicable and the run SHALL complete without division by zero.
- WHEN one file belongs to several clone groups THEN each physical line SHALL count
  once in clone verbosity.
- WHEN files contain generated markers or match exclusions THEN the detector SHALL
  apply one documented inclusion decision before any analyzer runs.
- WHEN paths differ only by platform separators or case rules THEN the detector SHALL
  use normalized project-relative paths in reports.
- WHEN a file is renamed without content changes THEN M1 SHALL expose the rename and
  SHALL not treat all lines as unrelated deletion and addition when rename data is
  available.
- WHEN an analyzer fails THEN the report SHALL retain successful results and record
  which metric is unavailable for which scope.
- WHEN a calibration profile does not match the metric or rule-set version THEN the
  detector SHALL refuse to emit a misleading normalized score.

## Success Criteria

- [ ] Golden fixtures produce exact, repeatable raw metric counts on Windows, macOS,
      and Linux.
- [x] Project totals reconcile with source evidence and per-file totals where the
      metric is additive.
- [x] Every score can be traced to raw values, calibration data, and analyzer
      versions.
- [x] A new language adapter can be demonstrated with a fixture adapter without
      changing core domain models, aggregation, scoring, or JSON serialization.
- [x] Repeated scans of unchanged input and configuration produce byte-stable JSON
      after volatile invocation metadata is excluded.

Windows validation passed on Python 3.12, 3.13, and 3.14. Hosted macOS/Linux
execution is pending a configured Git remote; see [release-validation.md](release-validation.md).

## Approved Product Decisions

- Implement the core in Python 3.12.
- Provide both the `slop` CLI and an importable Python API.
- Reuse maintained parsers and metric libraries behind owned adapter interfaces.
- Own the report model, aggregation, scoring, rule catalog, and user experience.
- Ship M1-M4 first. Keep cognitive erosion, coupling, churn, and TypeScript support
  behind the same extension contracts for later releases.
- Use a 0-100 slop score where higher always means worse.
- Score production and test code separately. Use production as the primary score.
- Show five hotspots by default and expose complete evidence through detail and JSON
  views.
- Use the post-TB-3 [output and CLI direction](cli-output.md): compact visual summaries,
  optional color, file hierarchy, and source-evidence drill-down. Keep raw ratios
  distinct from calibrated scores and keep the current application name.
