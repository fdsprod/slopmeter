"""Run a snapshot through source discovery, adapters, and owned aggregation."""

from dataclasses import dataclass

from slop_measure.application.comparison import assemble_comparison
from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import (
    Diagnostic,
    DiagnosticSeverity,
    FileEvidence,
    LanguageEvidence,
    ParseState,
)
from slop_measure.domain.inventory import SourceInventory
from slop_measure.domain.reports import AnalysisReport, AnalyzerVersion, ScoreUnavailableReason
from slop_measure.domain.requests import ComparisonRequest, SnapshotRequest
from slop_measure.domain.scoring import CalibrationProfile
from slop_measure.domain.source import DirectorySourceReference, GitSourceIdentity, SourceDocument
from slop_measure.errors import AnalysisFailure
from slop_measure.languages.base import LanguageAdapter
from slop_measure.languages.python.adapter import PythonAdapter
from slop_measure.languages.registry import LanguageRegistry
from slop_measure.metrics.aggregate import aggregate_snapshot
from slop_measure.scoring.engine import score_report
from slop_measure.scoring.profiles import load_profile
from slop_measure.sources.filesystem import FilesystemSourceProvider
from slop_measure.sources.git import GitSourceProvider, rename_pairs


def _failed_adapter(language: str, documents: tuple[SourceDocument, ...]) -> LanguageEvidence:
    return LanguageEvidence(
        language=language,
        capabilities=frozenset(),
        files=tuple(
            FileEvidence(
                path=document.path,
                language=language,
                cohort=document.cohort,
                sloc=0,
                sloc_lines=(),
                parse_state=ParseState.FAILED,
            )
            for document in documents
        ),
        diagnostics=tuple(
            Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="analyzer.failed",
                message=f"The {language} analyzer failed.",
                path=document.path,
            )
            for document in documents
        )
        or (
            Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="analyzer.failed",
                message=f"The {language} analyzer failed.",
            ),
        ),
    )


def _validate_evidence(
    adapter: LanguageAdapter, documents: tuple[SourceDocument, ...], evidence: LanguageEvidence
) -> None:
    expected = {doc.path.root: (doc.language, doc.cohort) for doc in documents}
    actual = {file.path.root: (file.language, file.cohort) for file in evidence.files}
    if evidence.language != adapter.language_id or expected != actual:
        raise ValueError("adapter evidence must account for every input source exactly once")
    if not evidence.capabilities <= adapter.capabilities:
        raise ValueError("adapter evidence includes undeclared capabilities")
    error_paths = {
        item.path.root if item.path else None
        for item in evidence.diagnostics
        if item.severity is DiagnosticSeverity.ERROR
    }
    if None not in error_paths and any(
        file.parse_state is ParseState.FAILED and file.path.root not in error_paths
        for file in evidence.files
    ):
        raise ValueError("failed adapter files require an error diagnostic")


@dataclass(frozen=True)
class _Snapshot:
    report: AnalysisReport
    inventory: SourceInventory


def _calibration(
    config: AnalysisConfig,
) -> tuple[CalibrationProfile | None, ScoreUnavailableReason | None]:
    try:
        return load_profile(config.calibration_profile), None
    except ValueError:
        return None, ScoreUnavailableReason.CALIBRATION_INCOMPATIBLE


class AnalysisService:
    """Coordinate an explicit registry without putting language rules in the core."""

    def __init__(self, registry: LanguageRegistry | None = None) -> None:
        self.registry = registry if registry is not None else LanguageRegistry((PythonAdapter(),))

    def scan(self, request: SnapshotRequest) -> AnalysisReport:
        """Analyze a directory and apply strict failure policy after collecting evidence."""
        snapshot = self._scan(request)
        profile, failure = _calibration(request.config)
        return score_report(snapshot.report, profile, failure=failure)

    def compare(self, request: ComparisonRequest) -> AnalysisReport:
        """Compare two retained snapshots using one configuration and calibration."""
        baseline = self._scan(SnapshotRequest(target=request.baseline, config=request.config))
        current = self._scan(SnapshotRequest(target=request.current, config=request.config))
        profile, failure = _calibration(request.config)
        return assemble_comparison(
            score_report(baseline.report, profile, failure=failure),
            score_report(current.report, profile, failure=failure),
            baseline.inventory,
            current.inventory,
            renames=(
                rename_pairs(baseline.report.analysis.current, current.report.analysis.current)
                if isinstance(baseline.report.analysis.current, GitSourceIdentity)
                else ()
            ),
        )

    def _scan(self, request: SnapshotRequest) -> _Snapshot:
        for adapter in self.registry.adapters:
            validate_config = getattr(adapter, "validate_config", None)
            if validate_config is not None:
                validate_config(request.config)
        provider = (
            FilesystemSourceProvider(request.target.root, request.config, self.registry)
            if isinstance(request.target, DirectorySourceReference)
            else GitSourceProvider(
                request.target.root, request.target.revision, request.config, self.registry
            )
        )
        inventory = provider.inventory()
        evidence: list[LanguageEvidence] = []
        versions: list[AnalyzerVersion] = []
        for adapter in self.registry.adapters:
            documents = tuple(
                doc for doc in inventory.documents if doc.language == adapter.language_id
            )
            try:
                result = adapter.analyze(documents, request.config)
                _validate_evidence(adapter, documents, result)
            except Exception:
                result = _failed_adapter(adapter.language_id, documents)
            evidence.append(result)
            versions.append(
                AnalyzerVersion(
                    language=adapter.language_id,
                    adapter_version=getattr(adapter, "adapter_version", "unversioned"),
                    rule_set_version=getattr(adapter, "rule_set_version", None),
                    clone_normalization_version=getattr(
                        adapter, "clone_normalization_version", None
                    ),
                )
            )
        report = aggregate_snapshot(
            provider.identity(),
            inventory,
            tuple(evidence),
            request.config,
            analyzers=tuple(versions),
        )
        failures = [
            item.detail
            for item in report.diagnostics
            if item.detail.severity is DiagnosticSeverity.ERROR
        ]
        if request.config.strict and failures:
            first = failures[0]
            location = f"{first.path.root}: " if first.path else ""
            raise AnalysisFailure(f"Strict analysis failed: {location}{first.message}")
        return _Snapshot(report, inventory)
