# Language selection and directory discovery

`AnalysisConfig.languages` is an immutable set. An empty set selects all installed
adapters and is omitted from serialized configuration to preserve existing report
output. The service resolves language IDs and extension aliases through the
registry before validation or discovery. Reports store canonical language IDs.
The CLI accepts repeated `--lang` or `--langs` options with comma-separated values.

Git working-tree discovery uses Git's tracked and untracked eligible paths. It
does not walk ignored subtrees. Tracked ignored files remain eligible, deleted
working-tree files are absent, and redirected parent directories are not followed.
Git's grouped ignored output can repeat descendants; discovery collapses those
records. Without Git, only exclusions that prove an entire subtree is excluded
can prune traversal. Language selection applies before source bytes are read in
both working trees and Git revisions.

`ExcludedDirectory(path, reason)` records a skipped directory without inventing
a file count. `SourceInventory.excluded_directories` carries these records into
`AnalysisReport.excluded_directories`, where each record belongs to the current
or baseline source. Per-file coverage continues to count only known files. Empty
report collections are omitted for compatibility. Terminal output summarizes
directory counts and expands paths and reasons with `--verbose`.

## Local measurement

On the development checkout on 2026-09-18, the old inventory walked 122,954 files
and took 33.449 seconds. The revised inventory with Python selected took 0.195
seconds, returned 146 source documents, recorded 31 excluded directories, and
reported no discovery errors. These are local observations, not fixed limits.

`slop score . --lang py --top 10 --ascii --no-color` completed in 5.586 seconds.
Its only diagnostic came from the deliberately invalid fixture
`tests/fixtures/basic/bad.py`. Git still performs its own path discovery; the
change removes the application's full recursive walk of the working tree.

## Validation

Windows Python 3.12: 1,142 deterministic tests passed, with the four artifact
cases run separately and passing against rebuilt wheel and source packages.
All 42 retained learning tests passed. Branch coverage is 96.66 percent.
Ruff lint and formatting, Pyright, and all five import contracts passed.
Focused language, source, basic golden, and Git learning checks also passed on
Python 3.13 and 3.14. Hosted platform jobs were not run for this change.
