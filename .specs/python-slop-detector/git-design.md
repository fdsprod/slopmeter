# Read-only Git sources

TB-7 adds Git objects to the existing snapshot pipeline. Source bytes remain owned
by the inventory. Analysis does not check out a revision or execute source files.

## Source contract

| Request | Owned identity | Bytes |
|---|---|---|
| Directory root | Resolved directory root | Current eligible filesystem files |
| Git root and revision | Resolved repository root and full commit ID | Committed blobs |

Git roots must name the repository root. Reject nested roots instead of mixing
repository-relative paths with directory-relative paths. Resolve branch and tag
names once. Use the resolved commit for every later object read.

Read tree entries with NUL delimiters. Normal files use the same language routing,
cohort patterns, configured exclusions, and generated markers as directory scans.
Exclude symbolic links and submodules. A tracked file remains eligible even if an
ignore rule matches it. Working-tree inventory retains its existing ignore policy.

Git commands disable optional locks, filesystem monitors, prompts, external diffs,
and text conversion where applicable. Invalid repositories, missing Git, and missing
revisions raise `InvalidSource`. The CLI reports input errors with exit code 2.

## Pairing

1. Match equal paths within one language and cohort.
2. Apply Git rename hints to remaining eligible paths in the same population.
3. Match remaining exact content, then emit additions and deletions.

Hints come from read-only `git diff -M` between resolved commits, or between the
baseline commit and the current working tree. Different repository roots use exact
content matching only. Ignore hints for excluded paths. Reject ambiguous hint sets.
The existing line algorithm measures renamed and edited files from both retained
byte sequences. A rename does not change the meaning of M1.

## Commands

```text
slop score DIRECTORY --rev REVISION
slop tree DIRECTORY --rev REVISION
slop compare BASELINE CURRENT --repo DIRECTORY
slop compare BASELINE WORKTREE --repo DIRECTORY
slop compare BASELINE_DIRECTORY CURRENT_DIRECTORY
```

`scan` retains the same options as `score`. The current repository configuration
applies to both inputs, so settings and calibration stay comparable. `WORKTREE` is
reserved only as the current selector when `--repo` is present.

## Gate

- Committed source reads remain independent of dirty and untracked local files.
- Commit, branch, and tag inputs resolve to the same stable identity.
- Equivalent Git and directory source states produce the same raw measurements.
- Modified renames preserve both paths and exact added/deleted source lines.
- Index bytes, working files, and status remain unchanged after analysis.
- Existing snapshot and directory commands retain their behavior.
