"""Build deterministic raw snapshot reports from source and adapter facts."""

from dataclasses import dataclass

from slop_measure import __version__
from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import (
    AnalyzedFunctions,
    Coverage,
    CoverageState,
    Diagnostic,
    DiagnosticSeverity,
    EvidenceCapability,
    FailedFunctions,
    FileEvidence,
    FunctionAnalysis,
    FunctionEvidence,
    LanguageEvidence,
    ParseState,
)
from slop_measure.domain.inventory import SourceInventory
from slop_measure.domain.metrics import (
    FileMetricScope,
    MetricResult,
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
    MetricVersion,
    Provenance,
    ReportCoverage,
    ReportDiagnostic,
    ScoreUnavailableReason,
    SnapshotAnalysis,
    SnapshotCohortReport,
    UnavailableSnapshotScore,
)
from slop_measure.domain.source import Cohort, SourceIdentity
from slop_measure.metrics.erosion import measure_erosion

_SNAPSHOT_METRICS = ("m2.pattern-verbosity", "m3.clone-verbosity", "m4.erosion")


@dataclass(frozen=True)
class _ErosionContext:
    """Keep function outcomes and diagnostic ownership for one language."""

    analyses: tuple[FunctionAnalysis, ...] | None
    diagnostics: tuple[ReportDiagnostic, ...]
    threshold: int

    def functions(self, files: tuple[FileEvidence, ...]) -> tuple[FunctionEvidence, ...]:
        paths = {file.path.root for file in files}
        functions = (
            function
            for analysis in self.analyses or ()
            if isinstance(analysis, AnalyzedFunctions) and analysis.path.root in paths
            for function in analysis.functions
        )
        return tuple(
            sorted(
                functions,
                key=lambda function: (
                    function.path.root,
                    function.span.start_line,
                    function.span.end_line,
                    function.qualified_name,
                ),
            )
        )

    def measure(self, base: UnavailableMetric, files: tuple[FileEvidence, ...]) -> MetricResult:
        if self.analyses is None or base.reason in {
            UnavailableReason.PARSE_FAILED,
            UnavailableReason.ANALYZER_FAILED,
        }:
            return base
        paths = {file.path.root for file in files}
        failures = tuple(
            analysis.diagnostic
            for analysis in self.analyses
            if isinstance(analysis, FailedFunctions) and analysis.path.root in paths
        )
        if failures:
            diagnostic = next(item for item in self.diagnostics if item.detail in failures)
            return UnavailableMetric(
                metric_id="m4.erosion",
                scope=base.scope,
                reason=UnavailableReason.ANALYZER_FAILED,
                diagnostic_id=diagnostic.id,
            )
        return measure_erosion(self.functions(files), base.scope, self.threshold)

    def metrics(
        self,
        scope: MetricScope,
        files: tuple[FileEvidence, ...],
        failure: tuple[UnavailableReason, str | None],
    ) -> tuple[MetricResult, ...]:
        base = _metrics(scope, *failure)
        return (*base[:-1], self.measure(base[-1], files))


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
    erosion: _ErosionContext,
) -> CohortResult:
    results: list[FileResult] = []
    for file in files:
        reason, diagnostic_id = _state((file,), diagnostics)
        results.append(
            FileResult(
                evidence=file,
                functions=erosion.functions((file,)),
                metrics=erosion.metrics(
                    FileMetricScope(path=file.path, cohort=cohort), (file,), (reason, diagnostic_id)
                ),
                score=_score(reason),
            )
        )
    reason, diagnostic_id = _state(files, diagnostics)
    if project_errors:
        reason, diagnostic_id = _failure_reason(project_errors[0].detail), project_errors[0].id
    return CohortResult(
        files=tuple(results),
        metrics=erosion.metrics(ProjectMetricScope(cohort=cohort), files, (reason, diagnostic_id)),
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
    """Aggregate source coverage and raw metrics without averaging file ratios."""
    diagnostics = _diagnostics(
        inventory.diagnostics
        + tuple(item for language in evidence for item in language.diagnostics)
        + tuple(
            analysis.diagnostic
            for language in evidence
            for analysis in language.function_analyses
            if isinstance(analysis, FailedFunctions)
        )
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
        supported = tuple(
            item
            for item in evidence
            if item.language == language and EvidenceCapability.FUNCTIONS in item.capabilities
        )
        erosion = _ErosionContext(
            tuple(analysis for item in supported for analysis in item.function_analyses)
            if supported
            else None,
            diagnostics,
            config.complexity_threshold,
        )
        for cohort in Cohort:
            members = tuple(
                file for file in files if file.language == language and file.cohort is cohort
            )
            cohorts.append(
                SnapshotCohortReport(
                    language=language,
                    cohort=cohort,
                    current=_cohort_result(members, cohort, diagnostics, project_errors, erosion),
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
            metrics=(MetricVersion(metric_id="m4.erosion", version="1"),)
            if any(EvidenceCapability.FUNCTIONS in item.capabilities for item in evidence)
            else (),
        ),
        cohorts=tuple(cohorts),
        coverage=tuple(sorted(coverage, key=_coverage_key)),
        diagnostics=diagnostics,
    )
