"""Versioned reports with source-specific results and checked evidence links."""

from collections.abc import Hashable, Iterable, Iterator
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StringConstraints, model_validator

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import (
    CloneGroup,
    Coverage,
    Diagnostic,
    FileEvidence,
    FunctionEvidence,
    PatternFinding,
    pattern_source_lines,
    validate_clone_member,
    validate_function_evidence,
)
from slop_measure.domain.metrics import (
    FileMetricScope,
    MetricResult,
    MetricVersion,
    ProjectMetricScope,
    UnavailableMetric,
)
from slop_measure.domain.scoring import ScoreContribution
from slop_measure.domain.source import Cohort, SourceIdentity

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _require_unique(values: Iterable[Hashable], label: str) -> None:
    keys = tuple(values)
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate {label}")


class _ReportModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SourceSide(StrEnum):
    """The source state that owns a report record."""

    CURRENT = "current"
    BASELINE = "baseline"


class SnapshotAnalysis(_ReportModel):
    """The resolved source identity of a snapshot."""

    kind: Literal["snapshot"] = "snapshot"
    current: SourceIdentity


class ComparisonAnalysis(_ReportModel):
    """The two resolved source identities of a comparison."""

    kind: Literal["comparison"] = "comparison"
    baseline: SourceIdentity
    current: SourceIdentity


Analysis = Annotated[SnapshotAnalysis | ComparisonAnalysis, Field(discriminator="kind")]


class AnalyzerVersion(_ReportModel):
    """The adapter and optional rule catalog used for one language."""

    language: _Text
    adapter_version: _Text
    rule_set_version: _Text | None = None
    clone_normalization_version: _Text | None = None


class Provenance(_ReportModel):
    """Resolved settings and the versions that produced the report."""

    tool_version: _Text
    config: AnalysisConfig
    analyzers: tuple[AnalyzerVersion, ...] = ()
    metrics: tuple[MetricVersion, ...] = ()

    @model_validator(mode="after")
    def validate_versions(self) -> Self:
        _require_unique((item.language for item in self.analyzers), "analyzer language")
        _require_unique((item.metric_id for item in self.metrics), "metric version")
        return self


class ScoreUnavailableReason(StrEnum):
    """Reasons why evidence cannot produce a calibrated snapshot score."""

    CALIBRATION_MISSING = "calibration-missing"
    CALIBRATION_INCOMPATIBLE = "calibration-incompatible"
    NO_SOURCE_LINES = "no-source-lines"
    REQUIRED_METRIC_UNAVAILABLE = "required-metric-unavailable"


class MeasuredSnapshotScore(_ReportModel):
    """A calibrated snapshot score, where higher points mean worse slop."""

    state: Literal["measured"] = "measured"
    points: Annotated[FiniteFloat, Field(ge=0, le=100)]
    profile_id: _Text
    model_id: _Text
    band: _Text
    contributions: Annotated[tuple[ScoreContribution, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_contributions(self) -> Self:
        _require_unique((item.metric_id for item in self.contributions), "score contribution")
        total = sum((Decimal(str(item.points)) for item in self.contributions), Decimal(0))
        if Decimal(str(self.points)) != total:
            raise ValueError("snapshot points must equal the displayed contribution sum")
        return self


class UnavailableSnapshotScore(_ReportModel):
    """An explicit scoring outcome without a fabricated point value."""

    state: Literal["unavailable"] = "unavailable"
    reason: ScoreUnavailableReason


SnapshotScore = Annotated[
    MeasuredSnapshotScore | UnavailableSnapshotScore, Field(discriminator="state")
]


class FileResult(_ReportModel):
    """Source facts and derived results for one file."""

    evidence: FileEvidence
    functions: tuple[FunctionEvidence, ...] = ()
    metrics: tuple[MetricResult, ...] = ()
    score: SnapshotScore

    @model_validator(mode="after")
    def validate_metrics(self) -> Self:
        validate_function_evidence(self.evidence, self.functions)
        _require_unique((metric.metric_id for metric in self.metrics), "file metric")
        for metric in self.metrics:
            if not isinstance(metric.scope, FileMetricScope):
                raise ValueError("file results require file metric scopes")
            if metric.scope.path != self.evidence.path:
                raise ValueError("file metric path must match its evidence")
            if metric.scope.cohort is not self.evidence.cohort:
                raise ValueError("file metric cohort must match its evidence")
        return self


def _validate_project_metrics(metrics: tuple[MetricResult, ...]) -> None:
    _require_unique((metric.metric_id for metric in metrics), "project metric")
    if any(not isinstance(metric.scope, ProjectMetricScope) for metric in metrics):
        raise ValueError("cohort results require project metric scopes")


class CohortResult(_ReportModel):
    """Results for one language population in one source state."""

    files: tuple[FileResult, ...] = ()
    metrics: tuple[MetricResult, ...] = ()
    score: SnapshotScore

    @model_validator(mode="after")
    def validate_members(self) -> Self:
        _require_unique((file.evidence.path.root for file in self.files), "file path")
        _validate_project_metrics(self.metrics)
        return self


def _validate_population(result: CohortResult, language: str, cohort: Cohort) -> None:
    for file in result.files:
        if file.evidence.language != language or file.evidence.cohort is not cohort:
            raise ValueError("file evidence must match its owning language and cohort")
    if any(metric.scope.cohort is not cohort for metric in result.metrics):
        raise ValueError("project metric must match its owning cohort")


class _CohortReport(_ReportModel):
    language: _Text
    cohort: Cohort
    current: CohortResult

    @model_validator(mode="after")
    def validate_current(self) -> Self:
        _validate_population(self.current, self.language, self.cohort)
        return self


class SnapshotCohortReport(_CohortReport):
    """One snapshot population with no baseline state."""

    kind: Literal["snapshot"] = "snapshot"


class ComparisonCohortReport(_CohortReport):
    """Two source populations and their derived comparison metrics."""

    kind: Literal["comparison"] = "comparison"
    baseline: CohortResult
    metrics: tuple[MetricResult, ...] = ()

    @model_validator(mode="after")
    def validate_comparison(self) -> Self:
        _validate_population(self.baseline, self.language, self.cohort)
        _validate_project_metrics(self.metrics)
        if any(metric.scope.cohort is not self.cohort for metric in self.metrics):
            raise ValueError("comparison metric must match its owning cohort")
        return self


CohortReport = Annotated[SnapshotCohortReport | ComparisonCohortReport, Field(discriminator="kind")]


class ReportCoverage(_ReportModel):
    """Inventory coverage associated with one source state."""

    source: SourceSide = SourceSide.CURRENT
    detail: Coverage


class ReportDiagnostic(_ReportModel):
    """A report-owned identifier for an adapter or pipeline diagnostic."""

    id: _Text
    source: SourceSide = SourceSide.CURRENT
    detail: Diagnostic


class ReportFinding(_ReportModel):
    """A unique report-owned finding associated with one source state."""

    id: _Text
    source: SourceSide = SourceSide.CURRENT
    detail: PatternFinding


class ReportCloneGroup(_ReportModel):
    """A stable clone group linked to its owning source state."""

    id: _Text
    source: SourceSide = SourceSide.CURRENT
    detail: CloneGroup


def _source_results(cohort: CohortReport) -> Iterator[tuple[SourceSide, CohortResult]]:
    yield SourceSide.CURRENT, cohort.current
    if isinstance(cohort, ComparisonCohortReport):
        yield SourceSide.BASELINE, cohort.baseline


def _source_metrics(cohort: CohortReport) -> Iterator[tuple[SourceSide, MetricResult]]:
    for source, result in _source_results(cohort):
        for metric in result.metrics:
            yield source, metric
        for file in result.files:
            for metric in file.metrics:
                yield source, metric


def _validate_diagnostic_link(
    metric: MetricResult,
    sources: frozenset[SourceSide],
    diagnostics: dict[str, ReportDiagnostic],
) -> None:
    if not isinstance(metric, UnavailableMetric) or metric.diagnostic_id is None:
        return
    diagnostic = diagnostics.get(metric.diagnostic_id)
    if diagnostic is None:
        raise ValueError(f"metric diagnostic does not exist: {metric.diagnostic_id}")
    if diagnostic.source not in sources:
        raise ValueError("metric diagnostic must belong to the same source state")
    if (
        isinstance(metric.scope, FileMetricScope)
        and diagnostic.detail.path is not None
        and diagnostic.detail.path != metric.scope.path
    ):
        raise ValueError("metric diagnostic path must match the file metric scope")


class AnalysisReport(_ReportModel):
    """The versioned source of truth for JSON and terminal renderers."""

    schema_version: Literal["1.0"] = "1.0"
    analysis: Analysis
    provenance: Provenance
    coverage: tuple[ReportCoverage, ...] = ()
    cohorts: tuple[CohortReport, ...] = ()
    findings: tuple[ReportFinding, ...] = ()
    clone_groups: tuple[ReportCloneGroup, ...] = ()
    diagnostics: tuple[ReportDiagnostic, ...] = ()

    @model_validator(mode="after")
    def validate_clones(self) -> Self:
        _require_unique((group.id for group in self.clone_groups), "clone group ID")
        files = {
            (source, file.evidence.path.root): file.evidence
            for cohort in self.cohorts
            for source, result in _source_results(cohort)
            for file in result.files
        }
        for record in self.clone_groups:
            group = record.detail
            for member in group.members:
                file = files.get((record.source, member.path.root))
                if file is None:
                    raise ValueError("clone member must exist in its source state")
                if file.language != group.language or file.cohort is not group.cohort:
                    raise ValueError("clone member must match its group's language and cohort")
                validate_clone_member(file, member)
        return self

    @model_validator(mode="after")
    def validate_ownership(self) -> Self:
        if any(cohort.kind != self.analysis.kind for cohort in self.cohorts):
            raise ValueError("analysis and cohort report kinds must agree")
        _require_unique(((cohort.language, cohort.cohort) for cohort in self.cohorts), "cohort")
        _require_unique(
            (
                (source, file.evidence.path.root)
                for cohort in self.cohorts
                for source, result in _source_results(cohort)
                for file in result.files
            ),
            "source file path",
        )
        return self

    @model_validator(mode="after")
    def validate_findings(self) -> Self:
        _require_unique((finding.id for finding in self.findings), "finding ID")
        _require_unique(
            (
                (
                    finding.source,
                    finding.detail.path.root,
                    finding.detail.rule_id,
                    finding.detail.span.start_line,
                    finding.detail.span.end_line,
                )
                for finding in self.findings
            ),
            "finding identity",
        )
        files = {
            (source, file.evidence.path.root): file.evidence
            for cohort in self.cohorts
            for source, result in _source_results(cohort)
            for file in result.files
        }
        for finding in self.findings:
            file = files.get((finding.source, finding.detail.path.root))
            if file is None:
                raise ValueError("finding must refer to an existing file in its source state")
            pattern_source_lines(file, finding.detail)
        return self

    @model_validator(mode="after")
    def validate_metadata(self) -> Self:
        if isinstance(self.analysis, SnapshotAnalysis) and any(
            item.source is SourceSide.BASELINE for item in (*self.coverage, *self.diagnostics)
        ):
            raise ValueError("snapshot reports cannot contain baseline metadata")
        _require_unique(
            (
                (item.source, detail.state, detail.cohort, detail.language, detail.reason)
                for item in self.coverage
                for detail in (item.detail,)
            ),
            "coverage record",
        )
        _require_unique((item.id for item in self.diagnostics), "diagnostic ID")
        diagnostics = {item.id: item for item in self.diagnostics}
        for cohort in self.cohorts:
            for source, metric in _source_metrics(cohort):
                _validate_diagnostic_link(metric, frozenset({source}), diagnostics)
            if isinstance(cohort, ComparisonCohortReport):
                for metric in cohort.metrics:
                    _validate_diagnostic_link(metric, frozenset(SourceSide), diagnostics)
        return self
