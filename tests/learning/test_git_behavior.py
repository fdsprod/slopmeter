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
