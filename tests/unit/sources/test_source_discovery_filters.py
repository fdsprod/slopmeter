"""Discovery prunes excluded trees and filters languages before reading source bytes."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from test_filesystem import InventoryAdapter, git, write

from slop_measure.config import AnalysisConfig
from slop_measure.languages.registry import LanguageRegistry
from slop_measure.sources.filesystem import FilesystemSourceProvider
from slop_measure.sources.git import GitSourceProvider


def source(root: Path, **options: object) -> FilesystemSourceProvider:
    return FilesystemSourceProvider(
        root=root,
        config=AnalysisConfig.model_validate({"production_patterns": ["**/*"], **options}),
        registry=LanguageRegistry(
            (
                InventoryAdapter(language_id="alpha", extensions=frozenset({".one"})),
                InventoryAdapter(language_id="beta", extensions=frozenset({".two"})),
            )
        ),
    )


@pytest.fixture(autouse=True)
def isolated_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


def test_git_discovery_uses_eligible_paths_without_walking_ignored_subtrees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git(tmp_path, "init", "--quiet")
    write(tmp_path, ".gitignore", b"blocked/**\nignored.one\n")
    for path in (
        "blocked/tracked.one",
        "blocked/deep/unread.one",
        "ignored.one",
        "kept.one",
        "deleted.one",
    ):
        write(tmp_path, path)
    git(tmp_path, "add", "--force", "blocked/tracked.one", "deleted.one")
    (tmp_path / "deleted.one").unlink()

    def unexpected_walk(*_args, **_kwargs):
        raise AssertionError("Git discovery must not walk ignored source subtrees")

    monkeypatch.setattr(os, "walk", unexpected_walk)
    inventory = source(tmp_path).inventory()
    assert [document.path.root for document in inventory.documents] == [
        "blocked/tracked.one",
        "kept.one",
    ]
    assert inventory.failed_files == inventory.diagnostics == ()
    assert [(item.path.root, item.reason) for item in inventory.excluded_directories] == [
        ("blocked/deep", "git ignored")
    ]
    ignored = [item for item in inventory.coverage if item.reason == "git ignored"]
    assert len(ignored) == 1 and ignored[0].file_count == 1
    assert ignored[0].language == "alpha"


def test_non_git_terminal_subtree_exclusion_prunes_before_descending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tmp_path, "vendor/deep/unread.one")
    write(tmp_path, "kept.one")
    original = os.walk

    def bounded_walk(*args, **kwargs):
        for root, dirs, files in original(*args, **kwargs):
            assert Path(root) != tmp_path / "vendor", "Configured excluded subtree was visited"
            yield root, dirs, files

    monkeypatch.setattr(os, "walk", bounded_walk)
    inventory = source(tmp_path, exclusions=("vendor/**",)).inventory()
    assert [document.path.root for document in inventory.documents] == ["kept.one"]
    assert inventory.coverage == ()
    assert [(item.path.root, item.reason) for item in inventory.excluded_directories] == [
        ("vendor", "configured exclusion")
    ]


def test_directory_name_exclusion_alone_does_not_exclude_descendants(tmp_path: Path) -> None:
    write(tmp_path, "vendor/kept.one")
    inventory = source(tmp_path, exclusions=("vendor",)).inventory()
    assert [document.path.root for document in inventory.documents] == ["vendor/kept.one"]
    assert inventory.excluded_directories == ()


def test_language_filter_prevents_nonselected_and_unsupported_byte_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("selected.one", "not_selected.two", "unsupported.unknown"):
        write(tmp_path, name)
    original = Path.read_bytes

    def selected_only(path: Path) -> bytes:
        assert path.suffix not in {".two", ".unknown"}, "Nonselected source bytes were opened"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", selected_only)
    inventory = source(tmp_path, languages=frozenset({"alpha"})).inventory()
    assert [document.path.root for document in inventory.documents] == ["selected.one"]
    assert inventory.failed_files == inventory.diagnostics == inventory.coverage == ()


def test_empty_language_filter_keeps_all_registry_languages(tmp_path: Path) -> None:
    write(tmp_path, "a.one")
    write(tmp_path, "b.two")
    inventory = source(tmp_path, languages=frozenset()).inventory()
    assert {document.language for document in inventory.documents} == {"alpha", "beta"}


def test_git_nested_root_collapses_ignored_descendants_into_one_directory(tmp_path: Path) -> None:
    git(tmp_path, "init", "--quiet")
    write(tmp_path, "nested/.gitignore", b"cache/**\n")
    write(tmp_path, "nested/cache/deep/ignored.one")
    write(tmp_path, "nested/kept.one")
    inventory = source(tmp_path / "nested").inventory()
    assert [document.path.root for document in inventory.documents] == ["kept.one"]
    assert [(item.path.root, item.reason) for item in inventory.excluded_directories] == [
        ("cache", "git ignored")
    ]
    assert not any(item.reason == "git ignored" for item in inventory.coverage)


def test_git_indexed_path_never_follows_replaced_parent_symlink_or_junction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git(tmp_path, "init", "--quiet")
    tracked = write(tmp_path, "package/tracked.one")
    git(tmp_path, "add", "package/tracked.one")
    tracked.unlink()
    tracked.parent.rmdir()
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    external = write(outside, "tracked.one", b"PRIVATE = 1\n")
    try:
        tracked.parent.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        if os.name != "nt":
            pytest.skip(f"Directory link unavailable: {error}")
        command = shutil.which("cmd")
        assert command is not None
        result = subprocess.run(  # noqa: S603
            [command, "/c", "mklink", "/J", str(tracked.parent), str(outside)],
            check=False,
            capture_output=True,
        )
        if result.returncode:
            pytest.skip("Directory symlink and junction creation unavailable")
    original = Path.read_bytes

    def no_follow(path: Path) -> bytes:
        assert path != tracked, "Indexed path followed a redirected parent"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", no_follow)
    inventory = source(tmp_path).inventory()
    assert inventory.documents == inventory.failed_files == inventory.diagnostics == ()
    assert external.read_bytes() == b"PRIVATE = 1\n"


def test_git_revision_language_filter_skips_nonselected_blob_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git(tmp_path, "init", "--quiet")
    git(tmp_path, "config", "user.name", "Source filter test")
    git(tmp_path, "config", "user.email", "filter@example.invalid")
    for path in ("selected.one", "not_selected.two", "unsupported.unknown"):
        write(tmp_path, path, path.encode() + b"\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "--quiet", "-m", "Source language populations")
    blocked = [
        git(tmp_path, "rev-parse", f"HEAD:{path}").strip().decode()
        for path in ("not_selected.two", "unsupported.unknown")
    ]
    original = subprocess.run

    def selected_blobs_only(*args, **kwargs):
        command = args[0]
        if "cat-file" in command:
            requested = " ".join(map(str, command)) + str(kwargs.get("input", ""))
            assert not any(blob in requested for blob in blocked), "Nonselected blob was opened"
        return original(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", selected_blobs_only)
    provider = GitSourceProvider(
        root=tmp_path,
        revision="HEAD",
        config=AnalysisConfig.model_validate(
            {"production_patterns": ["**/*"], "languages": ["alpha"]}
        ),
        registry=LanguageRegistry(
            (
                InventoryAdapter(language_id="alpha", extensions=frozenset({".one"})),
                InventoryAdapter(language_id="beta", extensions=frozenset({".two"})),
            )
        ),
    )
    inventory = provider.inventory()
    assert [document.path.root for document in inventory.documents] == ["selected.one"]
    assert inventory.coverage == inventory.failed_files == inventory.diagnostics == ()
