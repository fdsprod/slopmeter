"""Filesystem inventory contracts, independent of parsing and scoring."""

import os
import shutil
import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import (
    CoverageState,
    DiagnosticSeverity,
    EvidenceCapability,
    FileEvidence,
    LanguageEvidence,
    ParseState,
)
from slop_measure.domain.inventory import SourceInventory
from slop_measure.domain.source import Cohort, DirectorySourceIdentity, SourceDocument
from slop_measure.languages.registry import LanguageRegistry
from slop_measure.sources.filesystem import FilesystemSourceProvider


@pytest.fixture(autouse=True)
def isolate_parent_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


@dataclass(frozen=True)
class InventoryAdapter:
    """Supply routing only: discovery must not invoke analysis."""

    language_id: str = "python"
    extensions: frozenset[str] = frozenset({".py", ".pyi"})
    capabilities: frozenset[EvidenceCapability] = frozenset({EvidenceCapability.FILES})

    def analyze(
        self, documents: tuple[SourceDocument, ...], config: AnalysisConfig
    ) -> LanguageEvidence:
        raise AssertionError("Inventory must not analyze or execute target source")


def provider(root: Path, **overrides: object) -> FilesystemSourceProvider:
    return FilesystemSourceProvider(
        root=root,
        config=AnalysisConfig.model_validate(overrides),
        registry=LanguageRegistry((InventoryAdapter(),)),
    )


def write(root: Path, path: str, content: bytes = b"VALUE = 1\n") -> Path:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def coverage_rows(inventory: SourceInventory) -> list[tuple[str, str, str, str | None, int]]:
    return [
        (item.state.value, item.cohort.value, item.language, item.reason, item.file_count)
        for item in inventory.coverage
    ]


def test_identity_resolves_root_and_inventory_preserves_sorted_exact_source(tmp_path: Path) -> None:
    content = b"raise RuntimeError('must not execute')\r\n# \xff\n"
    write(tmp_path, "z.py", content)
    write(tmp_path, "src/A.py", b"A = 1\n")
    source = provider(tmp_path / "src" / "..")

    assert source.identity() == DirectorySourceIdentity(root=tmp_path.resolve())
    inventory = source.inventory()

    assert [item.path.root for item in inventory.documents] == ["src/A.py", "z.py"]
    assert inventory.documents[1].content == content
    assert inventory.documents[1].content_hash == sha256(content).hexdigest()
    assert all(item.language == "python" for item in inventory.documents)
    assert all(item.cohort is Cohort.PRODUCTION for item in inventory.documents)
    assert inventory.coverage == inventory.diagnostics == inventory.failed_files == ()
    assert source.inventory() == inventory


def test_registry_supplies_extensions_and_test_patterns_take_precedence(tmp_path: Path) -> None:
    for path in ("root.pyi", "tests/unit.pyi", "pkg/test_one.py", "plain.py"):
        write(tmp_path, path)
    inventory = provider(
        tmp_path,
        production_patterns=("**/*.py", "**/*.pyi"),
        test_patterns=("tests/**/*.pyi", "**/test_*.py"),
    ).inventory()

    assert [(item.path.root, item.cohort) for item in inventory.documents] == [
        ("pkg/test_one.py", Cohort.TEST),
        ("plain.py", Cohort.PRODUCTION),
        ("root.pyi", Cohort.PRODUCTION),
        ("tests/unit.pyi", Cohort.TEST),
    ]


def test_globs_are_root_relative_segment_aware_and_case_sensitive(tmp_path: Path) -> None:
    for path in ("a.py", "src/a.py", "src/deep/a.py", "other/src/a.py", "src/UPPER.PY"):
        write(tmp_path, path)
    one_segment = provider(
        tmp_path, production_patterns=(r"src\*.py",), test_patterns=()
    ).inventory()
    recursive = provider(
        tmp_path, production_patterns=(r"src\**\*.py",), test_patterns=()
    ).inventory()

    assert [item.path.root for item in one_segment.documents] == ["src/a.py"]
    assert [item.path.root for item in recursive.documents] == ["src/a.py", "src/deep/a.py"]
    assert sum(item.file_count for item in recursive.coverage) == 3
    assert all(item.reason == "outside configured cohorts" for item in recursive.coverage)


def test_exclusions_generated_markers_and_unsupported_files_reconcile_coverage(
    tmp_path: Path,
) -> None:
    for path in ("vendor/a.py", "vendor/b.py", "vendor/readme.txt"):
        write(tmp_path, path)
    write(tmp_path, "generated.py", b"# @generated\nVALUE = 1\n")
    write(tmp_path, "kept.py")
    write(tmp_path, "outside.pyi")
    write(tmp_path, "notes.txt")
    write(tmp_path, "LICENSE")
    write(tmp_path, "tests/fixture.json")
    inventory = provider(
        tmp_path, exclusions=("vendor/**",), test_patterns=("tests/**",)
    ).inventory()

    assert [item.path.root for item in inventory.documents] == ["kept.py"]
    rows = coverage_rows(inventory)
    assert rows == sorted(rows)
    assert set(rows) == {
        ("excluded", "production", "python", "configured exclusion", 2),
        ("excluded", "production", "txt", "configured exclusion", 1),
        ("excluded", "production", "python", "generated marker", 1),
        ("excluded", "production", "python", "outside configured cohorts", 1),
        ("unsupported", "production", "txt", "no language adapter", 1),
        ("unsupported", "production", "unknown", "no language adapter", 1),
        ("unsupported", "test", "json", "no language adapter", 1),
    }
    assert all(item.sloc == 0 for item in inventory.coverage)
    assert len(inventory.documents) + sum(item.file_count for item in inventory.coverage) == 9


def test_generated_markers_match_utf8_bytes_and_can_be_disabled(tmp_path: Path) -> None:
    write(tmp_path, "generated.py", "# généré\nVALUE = 1\n".encode())
    assert provider(tmp_path, generated_markers=("généré",)).inventory().documents == ()
    assert len(provider(tmp_path, generated_markers=()).inventory().documents) == 1


def test_git_metadata_is_pruned_even_without_configured_exclusions(tmp_path: Path) -> None:
    write(tmp_path, ".git/objects/fake.py")
    write(tmp_path, "kept.py")
    inventory = provider(tmp_path, exclusions=()).inventory()
    assert [item.path.root for item in inventory.documents] == ["kept.py"]
    assert inventory.coverage == ()


def test_read_failure_is_reported_and_other_files_continue(tmp_path: Path, monkeypatch) -> None:
    blocked = write(tmp_path, "broken.py")
    write(tmp_path, "healthy.py")
    original = Path.read_bytes

    def read_bytes(path: Path) -> bytes:
        if path == blocked:
            raise PermissionError("fixture read denied")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    inventory = provider(tmp_path).inventory()

    assert [item.path.root for item in inventory.documents] == ["healthy.py"]
    assert len(inventory.failed_files) == len(inventory.diagnostics) == 1
    failed = inventory.failed_files[0]
    assert failed.path.root == "broken.py"
    assert failed.parse_state is ParseState.FAILED
    assert failed.sloc == 0 and failed.sloc_lines == ()
    diagnostic = inventory.diagnostics[0]
    assert diagnostic.code == "source.read-error"
    assert diagnostic.severity is DiagnosticSeverity.ERROR
    assert diagnostic.path == failed.path


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_provider_rejects_missing_or_non_directory_roots(tmp_path: Path, kind: str) -> None:
    target = tmp_path / "target"
    if kind == "file":
        target.write_bytes(b"content")
    with pytest.raises(ValueError):
        provider(target).inventory()


def test_symlinks_are_not_read_or_traversed(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    external = write(tmp_path, "outside/secret.py")
    try:
        (target / "linked.py").symlink_to(external)
        (target / "linked_dir").symlink_to(external.parent, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Symlink creation unavailable: {error}")
    inventory = provider(target).inventory()
    assert inventory.documents == ()
    assert inventory.failed_files == inventory.diagnostics == ()
    assert ("excluded", "production", "python", "symlink", 1) in coverage_rows(inventory)
    assert all(item.reason == "symlink" for item in inventory.coverage)


def git(root: Path, *arguments: str) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        pytest.skip("Git is not installed")
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(  # noqa: S603 - fixed test arguments in a temporary repository
        [executable, *arguments], cwd=root, env=environment, check=True, capture_output=True
    ).stdout


def test_git_inventory_keeps_tracked_ignored_files_and_never_changes_index(tmp_path: Path) -> None:
    git(tmp_path, "init", "--quiet")
    write(tmp_path, ".gitignore", b"*.generated.py\n")
    write(tmp_path, "tracked.generated.py")
    git(tmp_path, "add", "--force", "tracked.generated.py")
    write(tmp_path, "ignored.generated.py")
    write(tmp_path, "untracked.py")
    before_status = git(tmp_path, "status", "--porcelain=v1", "-z")
    before_index = (tmp_path / ".git/index").read_bytes()

    inventory = provider(tmp_path).inventory()

    assert [item.path.root for item in inventory.documents] == [
        "tracked.generated.py",
        "untracked.py",
    ]
    assert ("excluded", "production", "python", "git ignored", 1) in coverage_rows(inventory)
    assert git(tmp_path, "status", "--porcelain=v1", "-z") == before_status
    assert (tmp_path / ".git/index").read_bytes() == before_index


def test_source_inventory_is_immutable_and_rejects_extra_fields() -> None:
    inventory = SourceInventory()
    assert (
        inventory.documents
        == inventory.coverage
        == inventory.diagnostics
        == inventory.failed_files
        == ()
    )
    with pytest.raises(ValidationError):
        inventory.documents = ()
    with pytest.raises(ValidationError):
        SourceInventory.model_validate({"unexpected": True})


def test_source_inventory_rejects_scored_coverage() -> None:
    with pytest.raises(ValidationError):
        SourceInventory.model_validate(
            {
                "coverage": [
                    {
                        "state": CoverageState.SCORED,
                        "cohort": "production",
                        "language": "python",
                        "file_count": 1,
                        "sloc": 1,
                    }
                ]
            }
        )


def test_directory_walk_errors_are_diagnostics_not_silent_omissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tmp_path, "healthy.py")

    def walk(root, topdown=True, onerror=None, followlinks=False):
        yield str(root), ["blocked"], ["healthy.py"]
        if onerror is not None:
            onerror(PermissionError(13, "fixture directory denied", str(tmp_path / "blocked")))

    monkeypatch.setattr(os, "walk", walk)
    inventory = provider(tmp_path).inventory()
    assert [item.path.root for item in inventory.documents] == ["healthy.py"]
    assert len(inventory.diagnostics) == 1
    assert inventory.diagnostics[0].code == "source.read-error"
    assert inventory.diagnostics[0].severity is DiagnosticSeverity.ERROR
    assert inventory.diagnostics[0].path is not None
    assert inventory.diagnostics[0].path.root == "blocked"


@pytest.mark.parametrize("conflict", ["duplicate-documents", "duplicate-failures", "overlap"])
def test_inventory_paths_have_one_discovery_outcome(conflict: str) -> None:
    document = SourceDocument.model_validate(
        {"path": "app.py", "content": b"x = 1\n", "language": "python", "cohort": "production"}
    )
    failed = FileEvidence.model_validate(
        {
            "path": "app.py",
            "language": "python",
            "cohort": "production",
            "sloc": 0,
            "sloc_lines": (),
            "parse_state": "failed",
        }
    )
    values = (
        {"documents": (document, document)}
        if conflict == "duplicate-documents"
        else {"failed_files": (failed, failed)}
        if conflict == "duplicate-failures"
        else {"documents": (document,), "failed_files": (failed,)}
    )
    with pytest.raises(ValidationError):
        SourceInventory.model_validate(values)


@pytest.mark.parametrize("state,lines", [("parsed", ()), ("failed", (1,))])
def test_inventory_failure_evidence_requires_failed_state_and_no_source_lines(
    state: str, lines: tuple[int, ...]
) -> None:
    with pytest.raises(ValidationError):
        SourceInventory.model_validate(
            {
                "failed_files": [
                    {
                        "path": "app.py",
                        "language": "python",
                        "cohort": "production",
                        "sloc": len(lines),
                        "sloc_lines": lines,
                        "parse_state": state,
                    }
                ]
            }
        )
