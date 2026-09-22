"""Git history observations, separate from product regression tests.

Keep these tests as executable documentation. They never import target code.
The shared Git fixture confines all mutations to its temporary repository.
"""

from pathlib import Path

import pytest
from test_git_behavior import commit_all, run_git

pytest_plugins = ("test_git_behavior",)


def test_first_parent_merge_diff_includes_branch_work_once(git_repository: Path) -> None:
    (git_repository / "main.py").write_bytes(b"VALUE = 1\n")
    root = commit_all(git_repository, "Root").decode()
    run_git(git_repository, "checkout", "--quiet", "-b", "feature")
    (git_repository / "feature.py").write_bytes(b"FEATURE = 1\n")
    feature = commit_all(git_repository, "Feature").decode()
    run_git(git_repository, "checkout", "--quiet", "-b", "integration", root)
    (git_repository / "main.py").write_bytes(b"VALUE = 2\n")
    main = commit_all(git_repository, "Main change").decode()
    run_git(git_repository, "merge", "--quiet", "--no-ff", "feature", "-m", "Merge")
    merge = run_git(git_repository, "rev-parse", "HEAD").stdout.strip().decode()

    # Observed: first-parent traversal excludes the side-branch commit, but
    # explicitly comparing the merge to its first parent retains its source edit.
    commits = run_git(git_repository, "rev-list", "--first-parent", "--reverse", merge)
    assert commits.stdout.decode().splitlines() == [root, main, merge]
    parents = run_git(git_repository, "rev-list", "--parents", "-n", "1", merge)
    assert parents.stdout.decode().split() == [merge, main, feature]
    delta = run_git(
        git_repository,
        "diff",
        "--numstat",
        "-z",
        "--no-ext-diff",
        "--no-textconv",
        main,
        merge,
        "--",
    )
    assert delta.stdout == b"1\t0\tfeature.py\0"


def test_shallow_traversal_root_still_has_a_raw_parent(git_repository: Path) -> None:
    (git_repository / "app.py").write_bytes(b"VALUE = 1\n")
    parent = commit_all(git_repository, "Parent").decode()
    (git_repository / "app.py").write_bytes(b"VALUE = 2\n")
    child = commit_all(git_repository, "Child").decode()
    shallow = git_repository.parent / "shallow"
    run_git(
        git_repository,
        "clone",
        "--quiet",
        "--depth",
        "1",
        "--no-checkout",
        git_repository.as_uri(),
        str(shallow),
    )

    # Observed: rev-list presents a shallow boundary as parentless. The original
    # commit object retains its parent, whose absence must not become a root delta.
    assert run_git(shallow, "rev-parse", "--is-shallow-repository").stdout == b"true\n"
    traversed = run_git(shallow, "rev-list", "--parents", child).stdout.decode().split()
    assert traversed == [child]
    raw = run_git(shallow, "cat-file", "commit", child).stdout
    assert f"parent {parent}\n".encode() in raw
    assert run_git(shallow, "cat-file", "-e", parent, check=False).returncode != 0


def test_blame_preserves_introduction_through_exact_rename(git_repository: Path) -> None:
    (git_repository / "before.py").write_bytes(b"FIRST = 1\nSECOND = 2\n")
    introduced = commit_all(git_repository, "Introduce source").decode()
    run_git(git_repository, "mv", "before.py", "after.py")
    renamed = commit_all(git_repository, "Rename source").decode()
    (git_repository / "after.py").write_bytes(b"FIRST = 1\nSECOND = 3\n")
    commit_all(git_repository, "Rework second line")

    # Observed: blame at the deletion's parent follows a whole-file rename and
    # reports the original commit, line, and filename, independent of current bytes.
    blame = run_git(
        git_repository,
        "blame",
        "--line-porcelain",
        "-L",
        "2,2",
        renamed,
        "--",
        "after.py",
    ).stdout
    assert blame.splitlines()[0] == f"{introduced} 2 2 1".encode()
    assert b"filename before.py\n" in blame
    assert b"\tSECOND = 2\n" in blame


def test_raw_traversal_retains_older_commit_with_newer_parent_timestamp(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2026-09-20T12:00:00+00:00")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2026-09-20T12:00:00+00:00")
    (git_repository / "app.py").write_bytes(b"VALUE = 1\n")
    parent = commit_all(git_repository, "Future-dated parent").decode()
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2026-09-01T12:00:00+00:00")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2026-09-01T12:00:00+00:00")
    (git_repository / "app.py").write_bytes(b"VALUE = 2\n")
    child = commit_all(git_repository, "Backdated child").decode()

    # Observed: dates need not increase with ancestry. A date-limited traversal
    # can omit the newer-dated parent; enumerate pinned ancestry before filtering.
    complete = run_git(git_repository, "rev-list", "--first-parent", "--reverse", child)
    assert complete.stdout.decode().splitlines() == [parent, child]
    filtered = run_git(
        git_repository, "rev-list", "--since=2026-09-10T00:00:00+00:00", child
    )
    assert filtered.stdout == b""


def test_ignore_whitespace_can_hide_string_value_changes(git_repository: Path) -> None:
    (git_repository / "app.py").write_bytes(b'MESSAGE = "two words"\n')
    before = commit_all(git_repository, "String with one space").decode()
    (git_repository / "app.py").write_bytes(b'MESSAGE = "two  words"\n')
    after = commit_all(git_repository, "String with two spaces").decode()
    regular = run_git(git_repository, "diff", "--numstat", before, after, "--")
    ignored = run_git(git_repository, "diff", "-w", "--numstat", before, after, "--")

    # Observed: -w removes a behavior-changing literal edit. It cannot establish
    # formatting-only changes; language-aware evidence must make that judgment.
    assert regular.stdout == b"1\t1\tapp.py\n"
    assert ignored.stdout == b""
