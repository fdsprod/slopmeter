"""Build deterministic raw snapshot reports from source and adapter facts."""

from slop_measure import __version__
from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import (
    Coverage,
    CoverageState,
    Diagnostic,
    DiagnosticSeverity,
    FileEvidence,
    LanguageEvidence,
    ParseState,
)
from slop_measure.domain.inventory import SourceInventory
from slop_measure.domain.metrics import (
    FileMetricScope,
    MetricScope,
    ProjectMetricScope,
    UnavailableMetric,
    UnavailableReason,
)
from slop_measure.domain.reports import (
    AnalysisReport,
    AnalyzerVersion,
    CohortResult,
    FileResult,
    Provenance,
    ReportCoverage,
    ReportDiagnostic,
    ScoreUnavailableReason,
    SnapshotAnalysis,
    SnapshotCohortReport,
    UnavailableSnapshotScore,
)
from slop_measure.domain.source import Cohort, SourceIdentity

_SNAPSHOT_METRICS = ("m2.pattern-verbosity", "m3.clone-verbosity", "m4.erosion")


def _diagnostic_key(item: Diagnostic) -> tuple[str, int, int, str, str, str]:
    return (
        item.path.root if item.path else "",
        item.span.start_line if item.span else 0,
        item.span.end_line if item.span else 0,
        item.code,
        item.severity.value,
        item.message,
    )


def _diagnostics(details: tuple[Diagnostic, ...]) -> tuple[ReportDiagnostic, ...]:
    return tuple(
        ReportDiagnostic(id=f"diagnostic-{index:04d}", detail=detail)
        for index, detail in enumerate(sorted(set(details), key=_diagnostic_key), start=1)
    )


def _failure_reason(detail: Diagnostic) -> UnavailableReason:
    if detail.code in {"analyzer.failed", "source.read-error"}:
        return UnavailableReason.ANALYZER_FAILED
    return UnavailableReason.PARSE_FAILED


def _state(
    files: tuple[FileEvidence, ...], diagnostics: tuple[ReportDiagnostic, ...]
) -> tuple[UnavailableReason, str | None]:
    failed = {file.path.root for file in files if file.parse_state is ParseState.FAILED}
    if failed:
        for item in diagnostics:
            detail = item.detail
            if (
                detail.path
                and detail.path.root in failed
                and detail.severity is DiagnosticSeverity.ERROR
            ):
                return _failure_reason(detail), item.id
        return UnavailableReason.PARSE_FAILED, None
    if not sum(file.sloc for file in files):
        return UnavailableReason.NO_SOURCE_LINES, None
    return UnavailableReason.UNSUPPORTED_CAPABILITY, None


def _metrics(
    scope: MetricScope, reason: UnavailableReason, diagnostic_id: str | None
) -> tuple[UnavailableMetric, ...]:
    return (
        UnavailableMetric(
            metric_id="m1.loc-delta", scope=scope, reason=UnavailableReason.NO_BASELINE
        ),
        *(
            UnavailableMetric(
                metric_id=metric_id, scope=scope, reason=reason, diagnostic_id=diagnostic_id
            )
            for metric_id in _SNAPSHOT_METRICS
        ),
    )


def _score(reason: UnavailableReason) -> UnavailableSnapshotScore:
    return UnavailableSnapshotScore(
        reason=ScoreUnavailableReason.NO_SOURCE_LINES
        if reason is UnavailableReason.NO_SOURCE_LINES
        else ScoreUnavailableReason.REQUIRED_METRIC_UNAVAILABLE
    )


def _cohort_result(
    files: tuple[FileEvidence, ...],
    cohort: Cohort,
    diagnostics: tuple[ReportDiagnostic, ...],
    project_errors: tuple[ReportDiagnostic, ...],
) -> CohortResult:
    results: list[FileResult] = []
    for file in files:
        reason, diagnostic_id = _state((file,), diagnostics)
        results.append(
            FileResult(
                evidence=file,
                metrics=_metrics(
                    FileMetricScope(path=file.path, cohort=cohort), reason, diagnostic_id
                ),
                score=_score(reason),
            )
        )
    reason, diagnostic_id = _state(files, diagnostics)
    if project_errors:
        reason, diagnostic_id = _failure_reason(project_errors[0].detail), project_errors[0].id
    return CohortResult(
        files=tuple(results),
        metrics=_metrics(ProjectMetricScope(cohort=cohort), reason, diagnostic_id),
        score=_score(reason),
    )


def _coverage_key(item: ReportCoverage) -> tuple[str, str, str, str]:
    detail = item.detail
    return detail.state.value, detail.cohort.value, detail.language, detail.reason or ""


def _project_errors(
    language: str,
    inventory: SourceInventory,
    evidence: tuple[LanguageEvidence, ...],
    diagnostics: tuple[ReportDiagnostic, ...],
) -> tuple[ReportDiagnostic, ...]:
    failed_paths = {file.path.root for file in inventory.failed_files}
    unassigned = {
        _diagnostic_key(item)
        for item in inventory.diagnostics
        if (item.path is None or item.path.root not in failed_paths)
        and item.severity is DiagnosticSeverity.ERROR
    }
    unassigned.update(
        _diagnostic_key(item)
        for result in evidence
        if result.language == language
        for item in result.diagnostics
        if item.path is None and item.severity is DiagnosticSeverity.ERROR
    )
    return tuple(item for item in diagnostics if _diagnostic_key(item.detail) in unassigned)


def aggregate_snapshot(
    identity: SourceIdentity,
    inventory: SourceInventory,
    evidence: tuple[LanguageEvidence, ...],
    config: AnalysisConfig,
    *,
    analyzers: tuple[AnalyzerVersion, ...] = (),
) -> AnalysisReport:
    """Aggregate raw coverage. Snapshot metric algorithms arrive in later slices."""
    diagnostics = _diagnostics(
        inventory.diagnostics
        + tuple(item for language in evidence for item in language.diagnostics)
    )
    files = tuple(
        sorted(
            inventory.failed_files
            + tuple(file for language in evidence for file in language.files),
            key=lambda file: file.path.root,
        )
    )
    languages = sorted(
        {item.language for item in evidence}
        | {item.language for item in analyzers}
        | {file.language for file in files}
    )
    cohorts: list[SnapshotCohortReport] = []
    coverage = [ReportCoverage(detail=item) for item in inventory.coverage]
    for language in languages:
        project_errors = _project_errors(language, inventory, evidence, diagnostics)
        for cohort in Cohort:
            members = tuple(
                file for file in files if file.language == language and file.cohort is cohort
            )
            cohorts.append(
                SnapshotCohortReport(
                    language=language,
                    cohort=cohort,
                    current=_cohort_result(members, cohort, diagnostics, project_errors),
                )
            )
            coverage.append(
                ReportCoverage(
                    detail=Coverage(
                        state=CoverageState.SCORED,
                        cohort=cohort,
                        language=language,
                        file_count=len(members),
                        sloc=sum(file.sloc for file in members),
                    )
                )
            )
    return AnalysisReport(
        analysis=SnapshotAnalysis(current=identity),
        provenance=Provenance(
            tool_version=__version__,
            config=config,
            analyzers=tuple(sorted(analyzers, key=lambda item: item.language)),
        ),
        cohorts=tuple(cohorts),
        coverage=tuple(sorted(coverage, key=_coverage_key)),
        diagnostics=diagnostics,
    )
