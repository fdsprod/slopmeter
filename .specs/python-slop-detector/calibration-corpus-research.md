# Python calibration corpus research

Status: six snapshots acquired and source paths reviewed, 2026-09-17. No corpus
analysis or profile generation has run as part of this research.

Use historical snapshots of maintained public projects. Select 2019 releases to
precede widespread LLM code assistants. This date policy does not prove exclusive
human authorship. The snapshots themselves are old and need not be supported.

## Candidate set

| Repository | Candidate tag | Release date | Project license | Intended production population |
| --- | --- | --- | --- | --- |
| pallets/flask | `1.1.1` | 2019-07-08 | BSD-3-Clause | Flask package; web framework |
| psf/requests | `v2.22.0` | 2019-05-15 | Apache-2.0 | Requests package; HTTP client |
| pytest-dev/pytest | `5.2.0` | 2019-09-28 | MIT | `_pytest` package and public pytest module; test framework |
| sphinx-doc/sphinx | `v2.2.0` | 2019-08-19 | BSD-2-Clause, with incorporated notices | Sphinx package; documentation tool |
| python-attrs/attrs | `19.2.0` | 2019-10-01 | MIT | `attr` package; object construction library |
| networkx/networkx | `networkx-2.4` | 2019-10-16 | BSD-3-Clause | NetworkX package; graph algorithms |

The root session acquired these snapshots under `.tmp/calibration` and confirmed
their checked-out commit IDs:

| Repository | Commit SHA |
| --- | --- |
| pallets/flask | `ffc68840f821fb0a4c41a7b2b4eaad6d71f539b7` |
| psf/requests | `aeda65bbe57ac5edbcc2d80db85d010befb7d419` |
| pytest-dev/pytest | `068ef90b92a9e9205af31cb3d82e7d2a433ff969` |
| sphinx-doc/sphinx | `bea7b5d4777d6b1216213b6c58eee0c3d133ca94` |
| python-attrs/attrs | `7fcd616aabb4067b07a5bded22bc578d35f9e14d` |
| networkx/networkx | `fd0ecd22723cb30a365511d324841a85caad589c` |

NetworkX's `24d66c1879518478b497242c5a90b793d29de6f8` is an annotated tag
object, not the commit. Use the commit above in the manifest. The pinned root
license files confirm the license column. Sphinx's LICENSE also lists incorporated
software and must be retained in full.

## Pinned path audit

Paths below are relative to each repository. These are manifest policy proposals,
not a completed metric run. Test roots belong to a separate population. Explicit
root selection prevents packaging and documentation scripts entering production.

| Repository | Production roots | Test roots | Specific exclusions |
| --- | --- | --- | --- |
| Flask | `src/flask/` | `tests/` | `tests/test_apps/` fixture applications; `examples/`, `docs/`, root packaging scripts |
| Requests | `requests/` | `tests/` | `tests/testserver/` fixture server; `ext/`, `docs/`, `_appveyor/`, root packaging scripts |
| pytest | `src/_pytest/`, `src/pytest.py` | `testing/` | `testing/example_scripts/`, `testing/freeze/` fixture projects; `bench/`, `extra/`, `scripts/`, `doc/` |
| Sphinx | `sphinx/` | `tests/` | `tests/roots/` fixture projects; `sphinx/util/smartypants.py` incorporated module; `doc/`, `utils/` |
| attrs | `src/attr/` | `tests/`, root `conftest.py` | `docs/`, root packaging scripts |
| NetworkX | `networkx/` except nested test roots | every `networkx/**/tests/` | `doc/`, `examples/`, `tools/`, root packaging scripts |

Keep `sphinx/testing/` and `networkx/testing/` package utilities as production
library code; move their actual nested `tests/` directories to the test cohort.
These are shipped APIs, not the repositories' test suites. Likewise, do not
classify all pytest package code as tests because pytest is a testing framework.

Requests `requests/packages.py` is a compatibility import shim. It contains no
vendored dependency subtree in this snapshot; keep it. Do not install or import
the dependencies it names. No directory named `vendor` or `vendored` was found
in the six snapshots during the path audit.

Sphinx `sphinx/util/smartypants.py` explicitly identifies an extracted Docutils
module, so exclude the whole file as incorporated source. Its license header and
the root LICENSE contain attribution that must remain in the acquired archive.
Sphinx `sphinx/ext/napoleon/docstring.py` includes one attributed NumpyDoc-derived
method. Keep this maintained mixed-origin module and retain its incorporated
notice; do not remove selected methods from physical-source metrics. The same
policy keeps adapted snippets in pytest's config and reports modules. The
exclusion policy targets wholesale incorporated files, not every historical
contribution from another project. Sphinx's incorporated JQuery and Underscore
assets are non-Python and outside the Python population.

This is a bounded root/license/notice audit, not proof that all generated or
mixed-origin material has been identified. Record any further exclusions before
examining metric values. Preserve the discovered and excluded path inventory in
the corpus build output.

## Primary evidence

- Flask: [release history](https://flask.palletsprojects.com/en/stable/changes/)
  includes 1.1.1 and a 2026 release;
  [license](https://flask.palletsprojects.com/en/2.0.x/license).
- Requests: [release history](https://requests.readthedocs.io/en/latest/community/updates/)
  includes 2.22.0 and current releases;
  [repository license declaration](https://github.com/psf/requests).
- pytest: [historical changelog](https://docs.pytest.org/en/6.2.x/changelog.html),
  [license](https://docs.pytest.org/en/7.1.x/license.html), and
  [current releases](https://github.com/pytest-dev/pytest/releases).
- Sphinx: [2.2 release history](https://www.sphinx-doc.org/en/master/changes/2.2.html),
  [2026 release work](https://github.com/sphinx-doc/sphinx/issues), and
  [maintainer discussion of license metadata mismatch](https://github.com/sphinx-doc/sphinx/issues/9274).
  Read the pinned LICENSE and per-file notices rather than relying on classifiers.
- attrs: [historical and current changelog](https://www.attrs.org/en/stable/changelog.html)
  and [license and maintainer](https://www.attrs.org/en/stable/license.html).
- NetworkX: [2.4 release](https://networkx.org/documentation/stable/release/release_2.4.html),
  [version-specific license](https://networkx.org/documentation/networkx-2.4/license.html),
  and [current releases](https://github.com/networkx/networkx/releases).

## Acquisition and population policy

1. Resolve the exact tag with `git ls-remote`, including the `^{}` reference for
   annotated tags. Fetch the selected revision into a local corpus cache. Verify
   `HEAD` against the recorded full commit SHA. Use no target project install,
   imports, hooks, or build steps; analysis requires source bytes only.
2. Preserve license and notice files. Record repository URL, tag, full commit,
   release date, acquisition date, source roots, cohort rules, exclusion rules,
   and content hashes. Pin the analysis versions and effective metric options.
3. Include maintained package source. Keep tests in their own cohort. Explicitly
   identify pytest's `testing` tree and nested NetworkX test trees. Exclude
   vendored code, generated files, documentation examples, benchmark fixtures,
   packaging scripts, and test fixtures from production by recorded policy.
   Do not remove a file because its measured value is inconvenient.
4. Audit parse failures with the current Python parser. Historical syntax and
   compatibility fixtures can be invalid today. Preserve failure counts and
   reasons; do not silently treat failed files as zero. Freeze exclusions before
   reviewing metric values.
5. Save deterministic local evidence first. Derive file populations by the
   approved SLOC bands and project populations from each complete production
   cohort. Compute project raw values from source evidence, never by averaging
   file scores. Record sample counts per band and score model.

## Limits and profile constraints

Six repositories provide only six independent project observations. Empirical
project percentile steps are about one sixth before tie handling. Many files do
not increase the project sample count. This set can prove the calibration path;
it is a small, library-heavy baseline, not a representative Python census.
Large NetworkX populations can dominate pooled file distributions. Record that
sampling choice; do not introduce hidden reweighting. Small file bands may lack
enough samples and must retain an explicit unavailable result.

Keep file and project populations separate. Use combined verbosity and erosion
once each in the first snapshot model. Preserve raw M2 and M3 for explanation.
Callable-free files require an explicit verbosity-only calibrated model; do not
redistribute weights. M1 task-delta calibration requires a different corpus.
Package no profile until pinned snapshots, licenses, coverage, exclusions, metric
versions, rule-set version, sample counts, and corpus manifest hash are reviewed.
