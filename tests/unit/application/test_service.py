"""Service and aggregation contracts across independently supplied adapters."""

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from slop_measure.application.service import AnalysisService
from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import (
    Diagnostic,
    DiagnosticSeverity,
    EvidenceCapability,
    FileEvidence,
    LanguageEvidence,
    ParseState,
)
from slop_measure.domain.inventory import SourceInventory
from slop_measure.domain.requests import SnapshotRequest
from slop_measure.domain.source import (
    Cohort,
    DirectorySourceIdentity,
    DirectorySourceReference,
    ProjectPath,
    SourceDocument,
)
from slop_measure.errors import AnalysisFailure
from slop_measure.languages.registry import LanguageRegistry
from slop_measure.metrics.aggregate import aggregate_snapshot
from slop_measure.reporting.json import serialize_report


@pytest.fixture(autouse=True)
def isolate_parent_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


@dataclass(frozen=True)
class OtherLanguageAdapter:
    language_id: str = "other"
    extensions: frozenset[str] = frozenset({".other"})
    capabilities: frozenset[EvidenceCapability] = frozenset({EvidenceCapability.FILES})

    def analyze(
        self, documents: tuple[SourceDocument, ...], config: AnalysisConfig
    ) -> LanguageEvidence:
        assert all(item.language == self.language_id for item in documents)
        return LanguageEvidence(
            language=self.language_id,
            capabilities=self.capabilities,
            files=tuple(
                FileEvidence(
                    path=item.path,
                    language=self.language_id,
                    cohort=item.cohort,
                    sloc=1,
                    sloc_lines=(1,),
                    parse_state=ParseState.PARSED,
                )
                for item in documents
            ),
        )


@dataclass(frozen=True)
class BrokenAdapter:
    language_id: str = "broken"
    extensions: frozenset[str] = frozenset({".broken"})
    capabilities: frozenset[EvidenceCapability] = frozenset({EvidenceCapability.FILES})

    def analyze(
        self, documents: tuple[SourceDocument, ...], config: AnalysisConfig
    ) -> LanguageEvidence:
        raise RuntimeError("test analyzer failure")


def request(root: Path, *, strict: bool = False) -> SnapshotRequest:
    return SnapshotRequest(
        target=DirectorySourceReference(root=root),
        config=AnalysisConfig(production_patterns=("**/*",), strict=strict),
    )


def test_service_isolates_adapter_failure_and_preserves_other_language(tmp_path: Path) -> None:
    (tmp_path / "bad.broken").write_bytes(b"source")
    (tmp_path / "good.other").write_bytes(b"source")
    service = AnalysisService(LanguageRegistry((BrokenAdapter(), OtherLanguageAdapter())))

    report = service.scan(request(tmp_path))
    cohorts = {
        item.language: item.current for item in report.cohorts if item.cohort is Cohort.PRODUCTION
    }
    broken = cohorts["broken"].model_dump(mode="json")
    other = cohorts["other"].model_dump(mode="json")

    assert broken["files"][0]["evidence"]["parse_state"] == "failed"
    assert broken["files"][0]["evidence"]["sloc"] == 0
    assert [item["reason"] for item in broken["metrics"]] == [
        "no-baseline",
        "analyzer-failed",
        "analyzer-failed",
        "analyzer-failed",
        "analyzer-failed",
    ]
    assert broken["score"]["reason"] == "required-metric-unavailable"
    assert other["files"][0]["evidence"]["sloc"] == 1
    assert [item["reason"] for item in other["metrics"]][1:] == ["unsupported-capability"] * 4
    assert report.diagnostics[0].detail.code == "analyzer.failed"
    assert report.diagnostics[0].detail.path == ProjectPath("bad.broken")
    assert all(item.adapter_version == "unversioned" for item in report.provenance.analyzers)
    assert all(item.clone_normalization_version is None for item in report.provenance.analyzers)
    with pytest.raises(AnalysisFailure):
        service.scan(request(tmp_path, strict=True))


def failed_file(path: str) -> FileEvidence:
    return FileEvidence(
        path=ProjectPath(path),
        language="python",
        cohort=Cohort.PRODUCTION,
        sloc=0,
        sloc_lines=(),
        parse_state=ParseState.FAILED,
    )


def parse_diagnostic(path: str) -> Diagnostic:
    return Diagnostic(
        severity=DiagnosticSeverity.ERROR,
        code="python.parse-error",
        message="Source could not be parsed.",
        path=ProjectPath(path),
    )


def test_aggregate_sorts_deduplicates_and_links_diagnostics_without_averaging(
    tmp_path: Path,
) -> None:
    good = FileEvidence(
        path=ProjectPath("good.py"),
        language="python",
        cohort=Cohort.PRODUCTION,
        sloc=3,
        sloc_lines=(1, 2, 3),
        parse_state=ParseState.PARSED,
    )
    diagnostics = (parse_diagnostic("z.py"), parse_diagnostic("a.py"), parse_diagnostic("a.py"))
    evidence = LanguageEvidence(
        language="python",
        capabilities=frozenset({EvidenceCapability.FILES}),
        files=(failed_file("z.py"), good, failed_file("a.py")),
        diagnostics=diagnostics,
    )
    report = aggregate_snapshot(
        DirectorySourceIdentity(root=tmp_path), SourceInventory(), (evidence,), AnalysisConfig()
    )
    production = next(item.current for item in report.cohorts if item.cohort is Cohort.PRODUCTION)
    assert [item.evidence.path.root for item in production.files] == ["a.py", "good.py", "z.py"]
    assert [
        (item.id, item.detail.path.root if item.detail.path else None)
        for item in report.diagnostics
    ] == [("diagnostic-0001", "a.py"), ("diagnostic-0002", "z.py")]
    coverage = next(
        item.detail for item in report.coverage if item.detail.cohort is Cohort.PRODUCTION
    )
    assert coverage.file_count == 3 and coverage.sloc == 3
    payload = production.model_dump(mode="json")
    assert all(item["diagnostic_id"] == "diagnostic-0001" for item in payload["metrics"][1:])
    assert all(
        item["diagnostic_id"] == "diagnostic-0002" for item in payload["files"][2]["metrics"][1:]
    )
    reordered = evidence.model_copy(
        update={
            "files": tuple(reversed(evidence.files)),
            "diagnostics": tuple(reversed(diagnostics)),
        }
    )
    repeated = aggregate_snapshot(
        DirectorySourceIdentity(root=tmp_path), SourceInventory(), (reordered,), AnalysisConfig()
    )
    assert serialize_report(report) == serialize_report(repeated)


def test_read_errors_are_strict_failures_and_retained_as_failed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "blocked.other"
    path.write_bytes(b"source")
    original = Path.read_bytes

    def read_bytes(target: Path) -> bytes:
        if target == path:
            raise PermissionError("fixture denial")
        return original(target)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    service = AnalysisService(LanguageRegistry((OtherLanguageAdapter(),)))
    report = service.scan(request(tmp_path))
    assert report.diagnostics[0].detail.code == "source.read-error"
    production = next(item.current for item in report.cohorts if item.cohort is Cohort.PRODUCTION)
    assert production.files[0].evidence.parse_state is ParseState.FAILED
    with pytest.raises(AnalysisFailure):
        service.scan(request(tmp_path, strict=True))


@dataclass(frozen=True)
class InconsistentAdapter:
    mode: str
    language_id: str = "other"
    extensions: frozenset[str] = frozenset({".other"})
    capabilities: frozenset[EvidenceCapability] = frozenset({EvidenceCapability.FILES})

    def analyze(
        self, documents: tuple[SourceDocument, ...], config: AnalysisConfig
    ) -> LanguageEvidence:
        language = "unexpected" if self.mode == "language" else self.language_id
        files = tuple(
            FileEvidence(
                path=document.path,
                language=language,
                cohort=Cohort.TEST if self.mode == "cohort" else document.cohort,
                sloc=0 if self.mode == "silent-failure" else 1,
                sloc_lines=() if self.mode == "silent-failure" else (1,),
                parse_state=ParseState.FAILED
                if self.mode == "silent-failure"
                else ParseState.PARSED,
            )
            for document in documents
        )
        if self.mode == "missing":
            files = files[1:]
        elif self.mode == "extra":
            files += (
                FileEvidence(
                    path=ProjectPath("invented.other"),
                    language=language,
                    cohort=Cohort.PRODUCTION,
                    sloc=0,
                    sloc_lines=(),
                    parse_state=ParseState.PARSED,
                ),
            )
        capabilities = (
            self.capabilities | {EvidenceCapability.CLONES}
            if self.mode == "capabilities"
            else self.capabilities
        )
        return LanguageEvidence(
            language=language, capabilities=frozenset(capabilities), files=files
        )


@pytest.mark.parametrize(
    "mode", ["missing", "extra", "cohort", "language", "capabilities", "silent-failure"]
)
def test_inconsistent_adapter_output_fails_batch_without_losing_source(
    tmp_path: Path, mode: str
) -> None:
    for name in ("a.other", "b.other"):
        (tmp_path / name).write_bytes(b"source")
    service = AnalysisService(LanguageRegistry((InconsistentAdapter(mode),)))

    report = service.scan(request(tmp_path))

    files = [file for cohort in report.cohorts for file in cohort.current.files]
    assert [file.evidence.path.root for file in files] == ["a.other", "b.other"]
    assert all(file.evidence.parse_state is ParseState.FAILED for file in files)
    assert all(file.evidence.cohort is Cohort.PRODUCTION for file in files)
    assert all(file.evidence.language == "other" for file in files)
    assert len(report.diagnostics) == 2
    assert all(item.detail.code == "analyzer.failed" for item in report.diagnostics)
    with pytest.raises(AnalysisFailure):
        service.scan(request(tmp_path, strict=True))


def test_invalid_adapter_language_on_empty_input_has_project_error(tmp_path: Path) -> None:
    service = AnalysisService(LanguageRegistry((InconsistentAdapter("language"),)))
    report = service.scan(request(tmp_path))

    assert len(report.diagnostics) == 1
    assert report.diagnostics[0].detail.code == "analyzer.failed"
    assert report.diagnostics[0].detail.path is None
    with pytest.raises(AnalysisFailure):
        service.scan(request(tmp_path, strict=True))


def test_adapter_exception_on_empty_input_has_project_error(tmp_path: Path) -> None:
    service = AnalysisService(LanguageRegistry((BrokenAdapter(),)))
    report = service.scan(request(tmp_path))
    assert len(report.diagnostics) == 1
    assert report.diagnostics[0].detail.code == "analyzer.failed"
    assert report.diagnostics[0].detail.path is None
    with pytest.raises(AnalysisFailure):
        service.scan(request(tmp_path, strict=True))


def test_directory_read_error_keeps_other_source_and_fails_strict_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "healthy.other").write_bytes(b"source")

    def walk(root, topdown=True, onerror=None, followlinks=False):
        yield str(root), ["blocked"], ["healthy.other"]
        if onerror is not None:
            onerror(PermissionError(13, "fixture directory denied", str(tmp_path / "blocked")))

    monkeypatch.setattr(os, "walk", walk)
    service = AnalysisService(LanguageRegistry((OtherLanguageAdapter(),)))
    report = service.scan(request(tmp_path))

    assert len(report.diagnostics) == 1
    assert report.diagnostics[0].detail.code == "source.read-error"
    assert report.diagnostics[0].detail.path == ProjectPath("blocked")
    assert any(cohort.current.files for cohort in report.cohorts)
    with pytest.raises(AnalysisFailure):
        service.scan(request(tmp_path, strict=True))


def test_aggregate_parse_failure_reason_is_independent_of_language(tmp_path: Path) -> None:
    evidence = LanguageEvidence(
        language="other",
        capabilities=frozenset({EvidenceCapability.FILES}),
        files=(
            FileEvidence(
                path=ProjectPath("bad.other"),
                language="other",
                cohort=Cohort.PRODUCTION,
                sloc=0,
                sloc_lines=(),
                parse_state=ParseState.FAILED,
            ),
        ),
        diagnostics=(
            Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="other.parse-error",
                message="Parse failed.",
                path=ProjectPath("bad.other"),
            ),
        ),
    )
    report = aggregate_snapshot(
        DirectorySourceIdentity(root=tmp_path), SourceInventory(), (evidence,), AnalysisConfig()
    )
    production = next(item.current for item in report.cohorts if item.cohort is Cohort.PRODUCTION)
    payload = production.model_dump(mode="json")

    assert [item["reason"] for item in payload["metrics"]][1:] == ["parse-failed"] * 4
    assert [item["reason"] for item in payload["files"][0]["metrics"]][1:] == ["parse-failed"] * 4
