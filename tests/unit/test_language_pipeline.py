"""Selected analyzers and skipped directory evidence preserve report ownership."""

from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError

from slop_measure.application.comparison import assemble_comparison
from slop_measure.application.service import AnalysisService
from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import EvidenceCapability, ExcludedDirectory, LanguageEvidence
from slop_measure.domain.inventory import SourceInventory
from slop_measure.domain.reports import AnalysisReport, ReportExcludedDirectory
from slop_measure.domain.requests import SnapshotRequest
from slop_measure.domain.source import (
    DirectorySourceIdentity,
    DirectorySourceReference,
    ProjectPath,
)
from slop_measure.languages.registry import LanguageRegistry
from slop_measure.metrics.aggregate import aggregate_snapshot
from slop_measure.reporting.comparison import render_comparison
from slop_measure.reporting.terminal import render_snapshot


def report(root: Path, entries: tuple[ExcludedDirectory, ...] = ()) -> AnalysisReport:
    return aggregate_snapshot(
        DirectorySourceIdentity(root=root),
        SourceInventory(excluded_directories=entries),
        (),
        AnalysisConfig(),
    )


def test_empty_directory_records_are_omitted_from_snapshot_serialization(tmp_path: Path) -> None:
    empty = report(tmp_path)
    assert empty.excluded_directories == ()
    assert "excluded_directories" not in empty.model_dump()
    assert "excluded_directories" not in empty.model_dump(mode="json")


def test_directory_exclusion_is_owned_evidence_without_invented_file_counts(tmp_path: Path) -> None:
    entry = ExcludedDirectory(path=ProjectPath("vendor"), reason="configured directory exclusion")
    snapshot = report(tmp_path, (entry,))
    assert snapshot.excluded_directories == (ReportExcludedDirectory(detail=entry),)
    assert snapshot.coverage == ()
    assert AnalysisReport.model_validate_json(snapshot.model_dump_json()) == snapshot
    with pytest.raises(ValidationError):
        entry.reason = "changed"
    payload = snapshot.model_dump(mode="json")
    payload["excluded_directories"][0]["source"] = "baseline"
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)


def test_comparison_preserves_both_sides_directory_exclusions(tmp_path: Path) -> None:
    entry = ExcludedDirectory(path=ProjectPath("vendor"), reason="configured directory exclusion")
    before, after = report(tmp_path / "before", (entry,)), report(tmp_path / "after", (entry,))
    inventory = SourceInventory(excluded_directories=(entry,))
    compared = assemble_comparison(before, after, inventory, inventory)
    assert {
        (item.source.value, item.detail.path.root) for item in compared.excluded_directories
    } == {("baseline", "vendor"), ("current", "vendor")}
    assert compared.coverage == ()


def test_duplicate_same_source_excluded_directory_is_rejected(tmp_path: Path) -> None:
    entry = ExcludedDirectory(path=ProjectPath("vendor"), reason="configured directory exclusion")
    payload = report(tmp_path, (entry,)).model_dump(mode="json")
    payload["excluded_directories"].append(payload["excluded_directories"][0])
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)


def test_comparison_terminal_reports_excluded_directories_on_both_sides(tmp_path: Path) -> None:
    before_entry = ExcludedDirectory(path=ProjectPath("vendor"), reason="baseline exclusion")
    after_entry = ExcludedDirectory(path=ProjectPath("vendor"), reason="current exclusion")
    before = report(tmp_path / "before", (before_entry,))
    after = report(tmp_path / "after", (after_entry,))
    compared = assemble_comparison(
        before,
        after,
        SourceInventory(excluded_directories=(before_entry,)),
        SourceInventory(excluded_directories=(after_entry,)),
    )
    compact = render_comparison(compared, ascii=True, color=False)
    assert "2 excluded directories (contents not scanned)" in compact
    assert "vendor" not in compact
    detailed = render_comparison(compared, ascii=True, color=False, verbose=True)
    assert "baseline" in detailed.lower() and "current" in detailed.lower()
    assert detailed.count("vendor") == 2
    assert "baseline exclusion" in detailed and "current exclusion" in detailed


def test_terminal_directory_exclusions_are_compact_until_verbose(tmp_path: Path) -> None:
    entries = tuple(
        ExcludedDirectory(path=ProjectPath(path), reason="configured directory exclusion")
        for path in ("vendor", "generated")
    )
    snapshot = report(tmp_path, entries)
    compact = render_snapshot(snapshot, ascii=True, color=False)
    assert "2 excluded directories (contents not scanned)" in compact
    assert "vendor" not in compact and "generated" not in compact
    detailed = render_snapshot(snapshot, ascii=True, color=False, verbose=True)
    assert "vendor" in detailed and "generated" in detailed
    assert "configured directory exclusion" in detailed


def test_language_filter_skips_unselected_analysis_and_configuration_hooks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    calls: list[str] = []

    @dataclass(frozen=True)
    class Adapter:
        language_id: str
        extensions: frozenset[str]
        capabilities: frozenset[EvidenceCapability] = frozenset()
        adapter_version: str = "fixture-1"

        def validate_config(self, config):
            calls.append(f"validate:{self.language_id}")

        def analyze(self, documents, config):
            calls.append(f"analyze:{self.language_id}")
            assert documents == ()
            return LanguageEvidence(language=self.language_id, capabilities=frozenset())

    service = AnalysisService(
        LanguageRegistry(
            (Adapter("python", frozenset({".py"})), Adapter("other", frozenset({".other"})))
        )
    )
    snapshot = service.scan(
        SnapshotRequest(
            target=DirectorySourceReference(root=tmp_path),
            config=AnalysisConfig(languages=frozenset({"python"})),
        )
    )
    assert calls == ["validate:python", "analyze:python"]
    assert [item.language for item in snapshot.provenance.analyzers] == ["python"]
    assert snapshot.provenance.config.languages == frozenset({"python"})
