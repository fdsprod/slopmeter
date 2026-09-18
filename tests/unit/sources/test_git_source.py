"""Git inventory reads pinned object bytes without modifying a checkout."""

from pathlib import Path

import pytest
from test_filesystem import InventoryAdapter, coverage_rows, git, write

from slop_measure.config import AnalysisConfig
from slop_measure.domain.source import GitSourceIdentity
from slop_measure.errors import InvalidSource
from slop_measure.languages.registry import LanguageRegistry
from slop_measure.sources.git import GitSourceProvider


def test_invalid_source_is_a_value_error() -> None:
    assert issubclass(InvalidSource, ValueError)


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    git(tmp_path, "init", "--quiet")
    git(tmp_path, "config", "user.name", "Git Source Test")
    git(tmp_path, "config", "user.email", "git-source@example.invalid")
    git(tmp_path, "config", "core.autocrlf", "false")
    return tmp_path


def commit(root: Path) -> str:
    git(root, "add", "--all")
    git(root, "commit", "--quiet", "-m", "Snapshot")
    return git(root, "rev-parse", "HEAD").strip().decode()


def provider(root: Path, revision: str = "HEAD", **config: object) -> GitSourceProvider:
    return GitSourceProvider(
        root=root,
        revision=revision,
        config=AnalysisConfig.model_validate(config),
        registry=LanguageRegistry((InventoryAdapter(),)),
    )


def test_identity_pins_full_commit_and_inventory_is_sorted_exact_and_worktree_independent(
    repository: Path,
) -> None:
    content = b"raise RuntimeError('must not execute')\r\n# \xff\n"
    write(repository, "z space.py", content)
    write(repository, "src/a.py", b"A = 1\n")
    first = commit(repository)
    source = provider(repository)
    assert source.identity() == GitSourceIdentity(root=repository.resolve(), revision=first)
    write(repository, "z space.py", b"changed\n")
    write(repository, "later.py", b"LATER = 1\n")
    commit(repository)
    write(repository, "src/a.py", b"dirty tracked edit\n")
    write(repository, "untracked.py", b"not in revision\n")
    status_before = git(repository, "status", "--porcelain=v1", "-z")
    head_before = git(repository, "rev-parse", "HEAD")
    index_before = (repository / ".git/index").read_bytes()
    inventory = source.inventory()
    assert [item.path.root for item in inventory.documents] == ["src/a.py", "z space.py"]
    assert inventory.documents[1].content == content
    assert inventory.documents[0].content == b"A = 1\n"
    assert source.inventory() == inventory
    assert source.identity().revision == first
    assert git(repository, "status", "--porcelain=v1", "-z") == status_before
    assert git(repository, "rev-parse", "HEAD") == head_before
    assert (repository / ".git/index").read_bytes() == index_before
    assert (repository / "src/a.py").read_bytes() == b"dirty tracked edit\n"


def test_revision_inventory_applies_owned_cohorts_exclusions_generated_and_unsupported_policy(
    repository: Path,
) -> None:
    for path in ("kept.py", "tests/test_one.py", "vendor/a.py", "outside.pyi", "notes.txt"):
        write(repository, path)
    write(repository, "generated.py", b"# @generated\nVALUE = 1\n")
    commit(repository)
    inventory = provider(repository, exclusions=("vendor/**",)).inventory()
    assert [(item.path.root, item.cohort.value) for item in inventory.documents] == [
        ("kept.py", "production"),
        ("tests/test_one.py", "test"),
    ]
    assert set(coverage_rows(inventory)) == {
        ("excluded", "production", "python", "configured exclusion", 1),
        ("excluded", "production", "python", "generated marker", 1),
        ("excluded", "production", "python", "outside configured cohorts", 1),
        ("unsupported", "production", "txt", "no language adapter", 1),
    }
    assert inventory.diagnostics == inventory.failed_files == ()
    assert len(inventory.documents) + sum(item.file_count for item in inventory.coverage) == 6


def test_committed_ignore_file_does_not_remove_tracked_revision_source(repository: Path) -> None:
    write(repository, ".gitignore", b"ignored.py\n")
    write(repository, "ignored.py", b"TRACKED = 1\n")
    git(repository, "add", "--force", "ignored.py")
    commit(repository)
    assert [item.path.root for item in provider(repository).inventory().documents] == ["ignored.py"]


def test_symlink_and_submodule_modes_are_excluded_without_reading_target_paths(
    repository: Path,
) -> None:
    write(repository, "regular.py", b"VALUE = 1\n")
    parent = commit(repository)
    blob = git(repository, "rev-parse", "HEAD:regular.py").strip().decode()
    git(repository, "update-index", "--add", "--cacheinfo", f"120000,{blob},linked.py")
    git(repository, "update-index", "--add", "--cacheinfo", f"160000,{parent},nested")
    git(repository, "commit", "--quiet", "-m", "Special tree entries")
    inventory = provider(repository).inventory()
    assert [item.path.root for item in inventory.documents] == ["regular.py"]
    assert {item.reason for item in inventory.coverage} == {"symlink", "submodule"}
    assert sum(item.file_count for item in inventory.coverage) == 2
    assert inventory.failed_files == inventory.diagnostics == ()


@pytest.mark.parametrize("revision", ["missing", "--help", "HEAD:app.py"])
def test_invalid_or_non_commit_revisions_raise_invalid_source(
    repository: Path, revision: str
) -> None:
    write(repository, "app.py")
    commit(repository)
    with pytest.raises(InvalidSource):
        provider(repository, revision).inventory()


def test_nonrepository_nested_root_and_missing_git_raise_invalid_source(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(repository, "nested/app.py")
    commit(repository)
    with pytest.raises(InvalidSource):
        provider(repository / "nested").inventory()
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    with pytest.raises(InvalidSource):
        provider(outside).inventory()
    monkeypatch.setenv("PATH", "")
    with pytest.raises(InvalidSource):
        provider(repository).inventory()
