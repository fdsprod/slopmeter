# Python reference corpus

`corpus-2026.3.toml` pins six source snapshots and the source-selection policy for
`py-2026.3` with assertion-aware test M4 version 3. Historical `corpus.toml` and `py-2026.1`
resources retain the version 1 baseline. `corpus-2026.2.toml` and `py-2026.2`
retain the version 2 baseline. The source cache was acquired on
2026-09-18. Keep the cache outside
the package. Do not install or execute code from the reference projects.

> [!NOTE]
> This is a small historical reference. It does not establish authorship or
> represent all Python projects. See the
> [corpus review](../../.specs/python-slop-detector/calibration-corpus-research.md)
> for sources, license notices, and population limits.

Use one clean Git checkout per manifest project under a cache directory. Name
each checkout after its `name` field. Check out its exact `revision`. Preserve
the license file and all other tracked files. The builder validates the pinned
commit and clean worktree before analysis.

Run the builder from the repository root in the locked development environment:

```text
uv run python tools/calibrate.py --manifest calibration/python/corpus-2026.3.toml --cache .tmp/calibration --output .tmp/calibration-output/py-2026.3.json --evidence-dir .tmp/calibration-2026.3-evidence
```

The output contains the profile and an exact copy of its corpus manifest. The
profile records the manifest SHA-256, metric versions, rule-set version, clone
normalization version, and effective metric settings. Local evidence records
source hashes and raw analysis reports. Keep that evidence outside package
resources. Review the evidence before copying the two profile files into
`src/slop_measure/scoring/resources/`.

| Population | Observation | Minimum count |
|---|---|---|
| Project | One complete raw cohort per repository | 5 |
| File | One complete file in its cohort and SLOC band | 5 |
| Callable-free file | Combined verbosity with explicit `no-functions` erosion | 5 |

File bands are 1–20, 21–100, 101–500, and 501 or more SLOC. Empty files do not
enter the reference. Failed and unsupported measurements do not become zeros.
Underpopulated bands have no calibration. Optional M2 and M3 distributions use
the same complete observations as their model, so they do not change its sample
count or add score contributions.

The full model weights combined verbosity and erosion equally. The separate
callable-free model weights combined verbosity at one. Percentiles count values
strictly below the measurement; zero measurements receive zero points. The
profile labels scores below 40 as `low`, 40 through 69.9 as `moderate`, and 70 or
more as `high`. These are reference-relative review labels, not defect rates.

## Corpus review

All six pinned snapshots parsed without analysis diagnostics under the locked
Python 3.12 environment. The selected files contain 182,882 SLOC. The final
provenance audit excluded one incorporated stemmer and one generated splitter
before packaging. No file was excluded because of a measured value.

| Project | Production files / SLOC | Test files / SLOC |
|---|---:|---:|
| attrs | 10 / 1,934 | 17 / 3,437 |
| Flask | 20 / 3,605 | 21 / 5,379 |
| NetworkX | 267 / 28,916 | 260 / 32,601 |
| pytest | 56 / 14,102 | 58 / 32,071 |
| Requests | 18 / 2,543 | 12 / 3,004 |
| Sphinx | 173 / 38,486 | 89 / 16,804 |

The reviewed populations have these complete observation counts:

| SLOC band | Production full model | Test full model | Production callable-free |
|---|---:|---:|---:|
| 1–20 | 39 | 47 | 35 |
| 21–100 | 207 | 159 | 9 |
| 101–500 | 216 | 180 | unavailable |
| 501+ | 31 | 42 | unavailable |
| Project | 6 | 6 | unavailable |

Test callable-free populations do not meet the minimum. Neither cohort has a
callable-free project reference. These missing populations remain unavailable.
The current profile uses M4 version `3` and version `1` for the other metrics.
It uses rule set `py-patterns-1` and normalization `py-clones-1`. No source files are redistributed in the profile package.

M4 version 3 uses assertion-excluded complexity for test excess and total mass.
Production uses full complexity. This is a measurement correction, not a threshold
fit to an external repository. The weights, source pins, and selection policy are
unchanged. Separate test populations are rebuilt from source under this definition.

Reference counts and nominal percentile steps are support metadata, not statistical
confidence or evidence of domain fit. Future corpus work must include independent
service and contract projects, known positive pattern cases, and holdouts grouped by
repository lineage. Overlapping subscans and copied providers are not independent
projects. Private external evaluation source, paths, and hashes are not packaged.
