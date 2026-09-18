"""Build deterministic raw snapshot reports from source and adapter facts."""

from dataclasses import dataclass
from hashlib import sha256

from slop_measure import __version__
from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import (
    AnalyzedFunctions,
    AnalyzedPatterns,
    CloneAnalysis,
    CloneGroup,
    Coverage,
    CoverageState,
    Diagnostic,
    DiagnosticSeverity,
    EvidenceCapability,
    FailedClones,
    FailedFunctions,
    FailedPatterns,
    FileEvidence,
    FunctionAnalysis,
    FunctionEvidence,
    LanguageEvidence,
    ParseState,
    PatternAnalysis,
    PatternFinding,
)
from slop_measure.domain.inventory import SourceInventory
from slop_measure.domain.metrics import (
    FileMetricScope,
    MeasuredMetric,
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
    ReportCloneGroup,
    ReportCoverage,
    ReportDiagnostic,
    ReportFinding,
    ScoreUnavailableReason,
    SnapshotAnalysis,
    SnapshotCohortReport,
    UnavailableSnapshotScore,
)
from slop_measure.domain.source import Cohort, SourceIdentity
from slop_measure.metrics.clones import group_clones
from slop_measure.metrics.erosion import measure_erosion
from slop_measure.metrics.verbosity import (
    measure_clones,
    measure_combined_verbosity,
    measure_patterns,
)

_SNAPSHOT_METRICS = (
    "m2.pattern-verbosity",
    "m3.clone-verbosity",
    "m4.erosion",
    "verbosity.combined",
)


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


@dataclass(frozen=True)
class _PatternContext:
    """Keep pattern failures separate from callable analysis."""

    analyses: tuple[PatternAnalysis, ...] | None
    diagnostics: tuple[ReportDiagnostic, ...]

    def measure(self, base: UnavailableMetric, files: tuple[FileEvidence, ...]) -> MetricResult:
        if self.analyses is None or base.reason in {
            UnavailableReason.PARSE_FAILED,
            UnavailableReason.ANALYZER_FAILED,
        }:
            return base
        paths = {file.path.root for file in files}
        outcomes = tuple(item for item in self.analyses if item.path.root in paths)
        failures = tuple(item.diagnostic for item in outcomes if isinstance(item, FailedPatterns))
        if failures:
            diagnostic = next(item for item in self.diagnostics if item.detail in failures)
            return UnavailableMetric(
                metric_id="m2.pattern-verbosity",
                scope=base.scope,
                reason=UnavailableReason.ANALYZER_FAILED,
                diagnostic_id=diagnostic.id,
            )
        findings = tuple(
            finding
            for item in outcomes
            if isinstance(item, AnalyzedPatterns)
            for finding in item.findings
        )
        return measure_patterns(files, findings, base.scope)


@dataclass(frozen=True)
class _CloneContext:
    analyses: tuple[CloneAnalysis, ...] | None
    groups: tuple[CloneGroup, ...]
    diagnostics: tuple[ReportDiagnostic, ...]

    def selected_groups(self, files: tuple[FileEvidence, ...]) -> tuple[CloneGroup, ...]:
        paths = {file.path.root for file in files}
        return tuple(
            group
            for group in self.groups
            if any(member.path.root in paths for member in group.members)
        )

    def measure(self, base: UnavailableMetric, files: tuple[FileEvidence, ...]) -> MetricResult:
        if self.analyses is None or base.reason in {
            UnavailableReason.PARSE_FAILED,
            UnavailableReason.ANALYZER_FAILED,
        }:
            return base
        paths = {file.path.root for file in files}
        failures = tuple(
            outcome.diagnostic
            for outcome in self.analyses
            if isinstance(outcome, FailedClones) and outcome.path.root in paths
        )
        if failures:
            diagnostic = next(item for item in self.diagnostics if item.detail in failures)
            return UnavailableMetric(
                metric_id=base.metric_id,
                scope=base.scope,
                reason=UnavailableReason.ANALYZER_FAILED,
                diagnostic_id=diagnostic.id,
            )
        return measure_clones(files, self.selected_groups(files), base.scope)


@dataclass(frozen=True)
class _SnapshotMetrics:
    erosion: _ErosionContext
    patterns: _PatternContext
    clones: _CloneContext

    def combined(
        self, pattern: MetricResult, clone: MetricResult, files: tuple[FileEvidence, ...]
    ) -> MetricResult:
        for metric in (pattern, clone):
            if isinstance(metric, UnavailableMetric):
                return metric.model_copy(update={"metric_id": "verbosity.combined"})
        paths = {file.path.root for file in files}
        findings = tuple(
            finding
            for outcome in self.patterns.analyses or ()
            if isinstance(outcome, AnalyzedPatterns) and outcome.path.root in paths
            for finding in outcome.findings
        )
        return measure_combined_verbosity(
            files, findings, self.clones.selected_groups(files), pattern.scope
        )

    def measure(
        self,
        scope: MetricScope,
        files: tuple[FileEvidence, ...],
        failure: tuple[UnavailableReason, str | None],
    ) -> tuple[MetricResult, ...]:
        base = _metrics(scope, *failure)
        patterns = self.patterns.measure(base[1], files)
        clones = self.clones.measure(base[2], files)
        return (
            base[0],
            patterns,
            clones,
            self.erosion.measure(base[3], files),
            self.combined(patterns, clones, files),
        )


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


def _score(
    reason: UnavailableReason, metrics: tuple[MetricResult, ...]
) -> UnavailableSnapshotScore:
    available = {metric.metric_id for metric in metrics if isinstance(metric, MeasuredMetric)}
    if {"verbosity.combined", "m4.erosion"} <= available:
        return UnavailableSnapshotScore(reason=ScoreUnavailableReason.CALIBRATION_MISSING)
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
    metrics: _SnapshotMetrics,
) -> CohortResult:
    results: list[FileResult] = []
    for file in files:
        reason, diagnostic_id = _state((file,), diagnostics)
        file_metrics = metrics.measure(
            FileMetricScope(path=file.path, cohort=cohort), (file,), (reason, diagnostic_id)
        )
        results.append(
            FileResult(
                evidence=file,
                functions=metrics.erosion.functions((file,)),
                metrics=file_metrics,
                score=_score(reason, file_metrics),
            )
        )
    reason, diagnostic_id = _state(files, diagnostics)
    if project_errors:
        reason, diagnostic_id = _failure_reason(project_errors[0].detail), project_errors[0].id
    project_metrics = metrics.measure(
        ProjectMetricScope(cohort=cohort), files, (reason, diagnostic_id)
    )
    return CohortResult(
        files=tuple(results),
        metrics=project_metrics,
        score=_score(reason, project_metrics),
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


def _snapshot_metrics(
    language: str,
    evidence: tuple[LanguageEvidence, ...],
    diagnostics: tuple[ReportDiagnostic, ...],
    config: AnalysisConfig,
    groups: tuple[CloneGroup, ...],
) -> _SnapshotMetrics:
    functions = tuple(
        item
        for item in evidence
        if item.language == language and EvidenceCapability.FUNCTIONS in item.capabilities
    )
    patterns = tuple(
        item
        for item in evidence
        if item.language == language and EvidenceCapability.PATTERNS in item.capabilities
    )
    clones = tuple(
        item
        for item in evidence
        if item.language == language and EvidenceCapability.CLONES in item.capabilities
    )
    return _SnapshotMetrics(
        erosion=_ErosionContext(
            tuple(analysis for item in functions for analysis in item.function_analyses)
            if functions
            else None,
            diagnostics,
            config.complexity_threshold,
        ),
        patterns=_PatternContext(
            tuple(analysis for item in patterns for analysis in item.pattern_analyses)
            if patterns
            else None,
            diagnostics,
        ),
        clones=_CloneContext(
            tuple(outcome for item in clones for outcome in item.clone_analyses)
            if clones
            else None,
            tuple(group for group in groups if group.language == language),
            diagnostics,
        ),
    )


def _findings(evidence: tuple[LanguageEvidence, ...]) -> tuple[ReportFinding, ...]:
    def key(finding: PatternFinding) -> tuple[str, int, int, str]:
        return (finding.path.root, finding.span.start_line, finding.span.end_line, finding.rule_id)

    ordered = sorted((finding for item in evidence for finding in item.patterns), key=key)
    return tuple(
        ReportFinding(id=f"finding-{index:04d}", detail=finding)
        for index, finding in enumerate(ordered, start=1)
    )


def _versions(evidence: tuple[LanguageEvidence, ...]) -> tuple[MetricVersion, ...]:
    families = (
        (EvidenceCapability.PATTERNS, "m2.pattern-verbosity"),
        (EvidenceCapability.CLONES, "m3.clone-verbosity"),
        (EvidenceCapability.FUNCTIONS, "m4.erosion"),
    )
    versions = tuple(
        MetricVersion(metric_id=metric_id, version="1")
        for capability, metric_id in families
        if any(capability in item.capabilities for item in evidence)
    )
    if any(
        {EvidenceCapability.PATTERNS, EvidenceCapability.CLONES} <= item.capabilities
        for item in evidence
    ):
        versions += (MetricVersion(metric_id="verbosity.combined", version="1"),)
    return versions


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
        + tuple(
            analysis.diagnostic
            for language in evidence
            for analysis in language.pattern_analyses
            if isinstance(analysis, FailedPatterns)
        )
        + tuple(
            outcome.diagnostic
            for language in evidence
            for outcome in language.clone_analyses
            if isinstance(outcome, FailedClones)
        )
    )
    files = tuple(
        sorted(
            inventory.failed_files
            + tuple(file for language in evidence for file in language.files),
            key=lambda file: file.path.root,
        )
    )
    groups = group_clones(
        files, tuple(candidate for language in evidence for candidate in language.clone_candidates)
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
        metrics = _snapshot_metrics(language, evidence, diagnostics, config, groups)
        for cohort in Cohort:
            members = tuple(
                file for file in files if file.language == language and file.cohort is cohort
            )
            cohorts.append(
                SnapshotCohortReport(
                    language=language,
                    cohort=cohort,
                    current=_cohort_result(members, cohort, diagnostics, project_errors, metrics),
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
            metrics=_versions(evidence),
        ),
        cohorts=tuple(cohorts),
        coverage=tuple(sorted(coverage, key=_coverage_key)),
        diagnostics=diagnostics,
        findings=_findings(evidence),
        clone_groups=tuple(
            ReportCloneGroup(
                id="clone-" + sha256(group.model_dump_json().encode()).hexdigest()[:20],
                detail=group,
            )
            for group in groups
        ),
    )
