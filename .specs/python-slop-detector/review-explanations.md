# Explain retained review changes

This pass addresses review friction from the v0.3.0 repeat assessment. It does not
change thresholds, weights, calibration, classification, clone detection, or review
applicability. The external assessment remains one repository lineage, not an
independent calibration population. No private evaluation artifacts are included.

## External configuration

Question: can a reviewer scan original source through the CLI while keeping config
outside that repository?

An explicit `--config` replaces root-local discovery. Defaults, selected file, and
CLI overrides define the result. The exact basename `pyproject.toml` selects the
`tool.slop` table; other filenames contain standalone Slop settings. Configuration
paths are invocation-relative. Source patterns and boundaries remain root-relative.
Both comparison sides use the same effective configuration. Effective settings,
not the external file location, enter reports and review anchors.

## Stale explanations

Question: can a reviewer see why an old clone decision no longer matches without
silently approving that decision?

Explanations are report projections, separate from persisted decisions. Each stale
candidate has tagged causes for changed bytes, missing source identity, changed
clone evidence, policy fingerprint changes, analysis definition changes, or missing
analysis identity. Changed and unavailable evidence are distinct states. Imported
explanations must agree with report evidence. Historical results without this
projection remain readable. Store version and anchor shape are unchanged.

This shape prevents missing identity from being presented as a known source edit.
The report derives and validates causes from the same evidence used for matching.
No cause overrides exact anchor equality. A policy hash cannot identify which old
declaration changed, and a source hash cannot prove that a change was harmless.

Whole-file hashes and whole-policy fingerprints remain conservative. Multi-prefix
ownership, narrower invalidation, audit attribution/history, non-clone review
persistence, and broader calibration are separate future work.

## Validation

- 1,327 deterministic tests passed on Windows Python 3.12. Four artifact tests
  skipped in that run and passed separately against wheel and source installations.
- Branch-inclusive coverage: 96.98 percent.
- 50 retained dependency learning tests and two small benchmark checks passed.
  The opt-in full performance benchmark was not run.
- 75 external-config and review checks passed on Python 3.13 and 3.14. Final
  renderer wording and test typing cleanup were verified on Python 3.12.
- Ruff lint and format, Pyright, and all five import contracts passed.
- The official installed v0.3.0 and updated tool emitted exactly equal parsed JSON
  on this same working tree with `score . --lang py --json`. Production: 67 files,
  8,061 SLOC, score 2.0. Test analysis remains partial because the deliberate
  `tests/fixtures/basic/bad.py` parse-error fixture is included. No new diagnostic.
- A real CLI scan of this checkout with an external config preserved every cohort,
  score, raw measurement, coverage record, finding, and diagnostic. Effective
  boundary declarations were added without changing scoring.
- Local proof artifacts: `.tmp/feedback030-confirmation/`, with both reports,
  terminal output, external config, and the configured scan. No external/private
  project material was copied into these artifacts.

Changes are committed locally. Version and published release remain v0.3.0 until
an explicit release step. The new options are available from this source checkout.
