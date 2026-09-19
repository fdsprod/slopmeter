"""Versioned reports with source-specific results and checked evidence links."""

from collections.abc import Hashable, Iterable, Iterator
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StringConstraints, model_validator

from slop_measure.config import AnalysisConfig
from slop_measure.domain.boundaries import CloneBoundaryContext, clone_boundary_context
from slop_measure.domain.changes import FileChange, LineTotals, MetricDelta
from slop_measure.domain.comparison_validation import validate_cohort_changes
from slop_measure.domain.evidence import (
    CloneGroup,
    Coverage,
    Diagnostic,
    ExcludedDirectory,
    FileEvidence,
    FunctionEvidence,
    PatternFinding,
    pattern_source_lines,
    validate_clone_member,
    validate_function_evidence,
)
from slop_measure.domain.interpretation import ReportInterpretation
from slop_measure.domain.metrics import (
    FileMetricScope,
    MetricResult,
    MetricVersion,
    ProjectMetricScope,
    UnavailableMetric,
)
from slop_measure.domain.reviews import (
    CloneReviewAnchor,
    CloneReviewChange,
    CloneReviewDecision,
    CloneReviewResult,
    SourceHash,
    clone_analysis_fingerprint,
    clone_review_causes,
)
from slop_measure.domain.scoring import ReferenceSupport, ScoreContribution, UnknownReferenceSupport
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
    CALIBRATION_POPULATION_MISSING = "calibration-population-missing"
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
    reference_support: ReferenceSupport = Field(
        default_factory=UnknownReferenceSupport,
        exclude_if=lambda value: isinstance(value, UnknownReferenceSupport),
    )

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
    source_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
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
    line_delta: LineTotals
    changes: tuple[FileChange, ...] = ()
    deltas: tuple[MetricDelta, ...] = ()
    metrics: tuple[MetricResult, ...] = ()

    @model_validator(mode="after")
    def validate_comparison(self) -> Self:
        _validate_population(self.baseline, self.language, self.cohort)
        _validate_project_metrics(self.metrics)
        if any(metric.scope.cohort is not self.cohort for metric in self.metrics):
            raise ValueError("comparison metric must match its owning cohort")
        validate_cohort_changes(self)
        return self


CohortReport = Annotated[SnapshotCohortReport | ComparisonCohortReport, Field(discriminator="kind")]


class ReportCoverage(_ReportModel):
    """Inventory coverage associated with one source state."""

    source: SourceSide = SourceSide.CURRENT
    detail: Coverage


class ReportExcludedDirectory(_ReportModel):
    """An uncounted directory exclusion associated with one source state."""

    source: SourceSide = SourceSide.CURRENT
    detail: ExcludedDirectory


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
    boundary_context: CloneBoundaryContext | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


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
    interpretation: ReportInterpretation = Field(default_factory=ReportInterpretation)
    analysis: Analysis
    provenance: Provenance
    coverage: tuple[ReportCoverage, ...] = ()
    excluded_directories: tuple[ReportExcludedDirectory, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    cohorts: tuple[CohortReport, ...] = ()
    findings: tuple[ReportFinding, ...] = ()
    clone_groups: tuple[ReportCloneGroup, ...] = ()
    review_results: tuple[CloneReviewResult, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    diagnostics: tuple[ReportDiagnostic, ...] = ()

    def clone_review_anchor(self, group: ReportCloneGroup) -> CloneReviewAnchor:
        """Derive applicability from this report's current evidence and policy."""
        if group.source is not SourceSide.CURRENT or group not in self.clone_groups:
            raise ValueError("clone review requires an owned current group")
        files = {
            file.evidence.path.root: file
            for cohort in self.cohorts
            for file in cohort.current.files
        }
        paths = tuple(member.path for member in group.detail.members)
        hashes = []
        for path in sorted({path.root for path in paths}):
            file = files.get(path)
            if file is None or file.source_sha256 is None:
                raise ValueError("clone review requires exact source hashes for every member file")
            hashes.append(SourceHash(path=file.evidence.path, sha256=file.source_sha256))
        version = next(
            (
                item.version
                for item in self.provenance.metrics
                if item.metric_id == "m3.clone-verbosity"
            ),
            None,
        )
        if version is None:
            raise ValueError("clone review requires the clone metric version")
        config = self.provenance.config
        return CloneReviewAnchor(
            detail=group.detail,
            source_hashes=tuple(hashes),
            policy_fingerprint=clone_boundary_context(paths, config.boundaries).policy_fingerprint,
            analysis_fingerprint=clone_analysis_fingerprint(
                version,
                group.detail.normalization_version,
                config.clone_min_statements,
                config.clone_min_sloc,
            ),
        )

    def clone_review_change(
        self, decision: CloneReviewDecision, group: ReportCloneGroup
    ) -> CloneReviewChange:
        """Derive a stale explanation from this report, including unavailable inputs."""
        if group.source is not SourceSide.CURRENT or group not in self.clone_groups:
            raise ValueError("clone review requires an owned current group")
        hashes = {
            file.evidence.path.root: file.source_sha256
            for cohort in self.cohorts
            for file in cohort.current.files
        }
        config = self.provenance.config
        version = next(
            (
                item.version
                for item in self.provenance.metrics
                if item.metric_id == "m3.clone-verbosity"
            ),
            None,
        )
        analysis = (
            None
            if version is None
            else clone_analysis_fingerprint(
                version,
                group.detail.normalization_version,
                config.clone_min_statements,
                config.clone_min_sloc,
            )
        )
        policy = clone_boundary_context(
            tuple(member.path for member in group.detail.members), config.boundaries
        ).policy_fingerprint
        return CloneReviewChange(
            group_id=group.id,
            causes=clone_review_causes(decision.anchor, group.detail, hashes, policy, analysis),
        )

    @model_validator(mode="after")
    def validate_reviews(self) -> Self:
        _require_unique((result.decision.id for result in self.review_results), "review decision")
        groups = {
            group.id: group for group in self.clone_groups if group.source is SourceSide.CURRENT
        }
        for result in self.review_results:
            if result.state == "current":
                group = groups.get(result.group_id)
                if group is None or result.decision.anchor != self.clone_review_anchor(group):
                    raise ValueError("current clone review must match its source and policy anchor")
            elif result.state == "stale" and any(
                key not in groups for key in result.candidate_group_ids
            ):
                raise ValueError("stale review candidates must refer to current clone groups")
            if result.state == "stale" and result.changes:
                for change in result.changes:
                    if change != self.clone_review_change(result.decision, groups[change.group_id]):
                        raise ValueError("stale review changes must match current evidence")
        return self

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
            if (
                record.boundary_context is not None
                and record.boundary_context
                != clone_boundary_context(
                    tuple(member.path for member in group.members),
                    self.provenance.config.boundaries,
                )
            ):
                raise ValueError(
                    "clone boundary context must match its members and configured policy"
                )
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
            item.source is SourceSide.BASELINE
            for item in (*self.coverage, *self.diagnostics, *self.excluded_directories)
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
        _require_unique(
            ((item.source, item.detail.path.root) for item in self.excluded_directories),
            "excluded directory",
        )
        diagnostics = {item.id: item for item in self.diagnostics}
        for cohort in self.cohorts:
            for source, metric in _source_metrics(cohort):
                _validate_diagnostic_link(metric, frozenset({source}), diagnostics)
            if isinstance(cohort, ComparisonCohortReport):
                for metric in cohort.metrics:
                    _validate_diagnostic_link(metric, frozenset(SourceSide), diagnostics)
        return self
