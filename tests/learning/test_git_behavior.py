"""Learning tests that record the Git CLI behavior used by the source provider.

These tests interrogate Git directly. They do not exercise project production code.
Every mutation is confined to pytest's temporary directory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="Git is not installed")


def run_git(
    repository: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    """Run Git without consulting machine-wide user or system configuration."""
    git_executable = shutil.which("git")
    if git_executable is None:
        raise RuntimeError("Git is not installed")
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return subprocess.run(  # noqa: S603 - arguments are fixed by these learning tests
        [git_executable, *arguments],
        cwd=repository,
        env=environment,
        check=check,
        capture_output=True,
    )


@pytest.fixture
def git_repository() -> Iterator[Path]:
    # Keep the temporary checkout inside the writable workspace. Some managed
    # environments deny access to pytest's operating-system temp root.
    temporary_root = Path.cwd() / ".tmp"
    temporary_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="git-learning-", dir=temporary_root) as directory:
        repository = Path(directory) / "repository"
        repository.mkdir()
        run_git(repository, "init", "--quiet")
        run_git(repository, "config", "user.name", "Slop Measure Learning Test")
        run_git(repository, "config", "user.email", "learning-test@example.invalid")
        run_git(repository, "config", "core.autocrlf", "false")
        yield repository


def commit_all(repository: Path, message: str) -> bytes:
    run_git(repository, "add", "--all")
    run_git(repository, "commit", "--quiet", "--message", message)
    return run_git(repository, "rev-parse", "HEAD").stdout.strip()


def nul_fields(output: bytes) -> list[bytes]:
    return [field for field in output.split(b"\0") if field]


def test_revision_inventory_and_blob_reads_are_independent_of_working_tree(
    git_repository: Path,
) -> None:
    source_path = git_repository / "package" / "module.py"
    source_path.parent.mkdir()
    committed_content = b'def value():\n    return "committed"\n'
    source_path.write_bytes(committed_content)
    commit_all(git_repository, "Add source")

    # Observed: ls-tree returns revision-relative paths, delimited safely by NUL.
    revision_paths = nul_fields(
        run_git(git_repository, "ls-tree", "-r", "--name-only", "-z", "HEAD").stdout
    )
    assert revision_paths == [b"package/module.py"]

    # Observed: cat-file returns the exact committed blob bytes without a checkout.
    committed_blob = run_git(git_repository, "cat-file", "blob", "HEAD:package/module.py").stdout
    assert committed_blob == committed_content

    working_content = b'def value():\n    return "working tree"\n'
    source_path.write_bytes(working_content)

    # Observed: filesystem reads see edits while object reads remain pinned to HEAD.
    assert source_path.read_bytes() == working_content
    assert (
        run_git(git_repository, "cat-file", "blob", "HEAD:package/module.py").stdout
        == committed_content
    )
    assert nul_fields(run_git(git_repository, "status", "--porcelain=v1", "-z").stdout) == [
        b" M package/module.py"
    ]


def test_file_discovery_can_include_untracked_files_and_exclude_ignored_files(
    git_repository: Path,
) -> None:
    (git_repository / ".gitignore").write_text("*.generated.py\n", encoding="utf-8")
    tracked_path = git_repository / "package" / "tracked.py"
    tracked_path.parent.mkdir()
    tracked_path.write_text("TRACKED = True\n", encoding="utf-8")
    commit_all(git_repository, "Add tracked files and ignore rule")

    untracked_path = git_repository / "package" / "untracked.py"
    untracked_path.write_text("UNTRACKED = True\n", encoding="utf-8")
    ignored_path = git_repository / "package" / "cache.generated.py"
    ignored_path.write_text("GENERATED = True\n", encoding="utf-8")

    # Observed: this single command lists tracked and eligible untracked paths, but
    # applies repository ignore rules. Git emits project-relative slash paths.
    discoverable_paths = set(
        nul_fields(
            run_git(
                git_repository,
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ).stdout
        )
    )
    assert discoverable_paths == {
        b".gitignore",
        b"package/tracked.py",
        b"package/untracked.py",
    }

    # Observed: check-ignore returns zero only for the ignored candidate.
    assert (
        run_git(
            git_repository, "check-ignore", "--quiet", str(ignored_path), check=False
        ).returncode
        == 0
    )
    assert (
        run_git(
            git_repository, "check-ignore", "--quiet", str(untracked_path), check=False
        ).returncode
        == 1
    )


def test_diff_reports_an_exact_rename_between_revisions(git_repository: Path) -> None:
    original_path = git_repository / "before.py"
    original_path.write_text("def answer():\n    return 42\n", encoding="utf-8")
    baseline_revision = commit_all(git_repository, "Add original path")

    run_git(git_repository, "mv", "before.py", "after.py")
    current_revision = commit_all(git_repository, "Rename source")

    # Observed: -M identifies an unchanged file as an R100 rename. With -z, the
    # status, old path, and new path are separate NUL-delimited fields.
    rename_fields = nul_fields(
        run_git(
            git_repository,
            "diff",
            "--name-status",
            "-z",
            "-M",
            baseline_revision.decode("ascii"),
            current_revision.decode("ascii"),
        ).stdout
    )
    assert rename_fields == [b"R100", b"before.py", b"after.py"]

    # Observed: comparing committed revisions does not alter the current checkout.
    assert run_git(git_repository, "status", "--porcelain=v1").stdout == b""


def test_modified_rename_metadata_has_three_nul_fields(git_repository: Path) -> None:
    original = b"".join(f"VALUE_{index} = {index}\n".encode() for index in range(30))
    (git_repository / "before name.py").write_bytes(original)
    baseline = commit_all(git_repository, "Before edited rename")
    run_git(git_repository, "mv", "before name.py", "after name.py")
    (git_repository / "after name.py").write_bytes(original + b"ADDED = 1\n")
    current = commit_all(git_repository, "Edited rename")
    fields = nul_fields(
        run_git(
            git_repository,
            "diff",
            "--name-status",
            "-z",
            "-M",
            baseline.decode(),
            current.decode(),
            "--",
        ).stdout
    )
    # Observed: edited renames carry a similarity score below100 and preserve
    # spaces in separately NUL-delimited source and destination names.
    assert len(fields) == 3
    assert fields[0].startswith(b"R")
    assert 50 <= int(fields[0][1:]) < 100
    assert fields[1:] == [b"before name.py", b"after name.py"]


def test_ls_tree_modes_distinguish_regular_symlink_and_gitlink_without_checkout(
    git_repository: Path,
) -> None:
    (git_repository / "regular.py").write_bytes(b"VALUE = 1\n")
    parent = commit_all(git_repository, "Regular source")
    blob = run_git(git_repository, "rev-parse", "HEAD:regular.py").stdout.strip().decode()
    run_git(git_repository, "update-index", "--add", "--cacheinfo", f"120000,{blob},linked.py")
    run_git(
        git_repository, "update-index", "--add", "--cacheinfo", f"160000,{parent.decode()},nested"
    )
    run_git(git_repository, "commit", "--quiet", "--message", "Special tree entries")
    fields = nul_fields(run_git(git_repository, "ls-tree", "-r", "-z", "HEAD").stdout)
    records = {}
    for field in fields:
        metadata, path = field.split(b"\t", 1)
        mode, object_type, object_id = metadata.split(b" ")
        records[path] = (mode, object_type, object_id)
    # Observed: index-created modes expose symlinks and submodules without OS
    # symlink privileges or fetching a nested repository. gitlinks are commits.
    assert records[b"regular.py"] == (b"100644", b"blob", blob.encode())
    assert records[b"linked.py"] == (b"120000", b"blob", blob.encode())
    assert records[b"nested"] == (b"160000", b"commit", parent)


def test_revision_resolution_uses_end_of_options_and_requires_a_commit(
    git_repository: Path,
) -> None:
    (git_repository / "app.py").write_bytes(b"VALUE = 1\n")
    revision = commit_all(git_repository, "Resolve source")
    resolved = run_git(git_repository, "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}")
    assert resolved.stdout.strip() == revision
    # Observed: optionlike revisions remain operands and fail; they do not
    # change rev-parse behavior. A blob object also fails the commit peel.
    for invalid in ("missing^{commit}", "--help^{commit}", "HEAD:app.py^{commit}"):
        result = run_git(
            git_repository, "rev-parse", "--verify", "--end-of-options", invalid, check=False
        )
        assert result.returncode != 0


def test_ignored_directory_listing_keeps_forced_tracked_children_and_relative_subroots(
    git_repository: Path,
) -> None:
    (git_repository / ".gitignore").write_text(
        "ignored/**\nonlyignored/**\ncache.py\n", encoding="utf-8"
    )
    for path in (
        "ignored/tracked.py",
        "ignored/deep/cache.py",
        "onlyignored/deep/cache.py",
        "cache.py",
        "eligible.py",
        "nested/ok.py",
        "nested/junk/cache.py",
    ):
        target = git_repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"VALUE = 1\n")
    (git_repository / "nested/.gitignore").write_text("junk/**\n", encoding="utf-8")
    run_git(git_repository, "add", "--force", "ignored/tracked.py")
    ignored = nul_fields(
        run_git(
            git_repository,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "--directory",
            "-z",
            "--",
            ".",
        ).stdout
    )
    eligible = nul_fields(
        run_git(
            git_repository,
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            ".",
        ).stdout
    )
    # Observed: complete ignored subtrees use trailing-slash directory records,
    # while a forced tracked child stays eligible inside an otherwise ignored tree.
    assert set(ignored) == {
        b"cache.py",
        b"ignored/deep/",
        b"onlyignored/",
        b"onlyignored/deep/",
        b"nested/junk/",
        b"nested/junk/cache.py",
    }
    assert b"ignored/tracked.py" in eligible and b"eligible.py" in eligible
    assert not any(b"cache.py" in path for path in eligible)
    nested = nul_fields(
        run_git(
            git_repository / "nested",
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "--directory",
            "-z",
            "--",
            ".",
        ).stdout
    )
    # Observed: running below the worktree root emits paths relative to that cwd.
    assert nested == [b"junk/", b"junk/cache.py"]
