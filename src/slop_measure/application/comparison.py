"""Assemble two owned snapshots without rereading their source documents."""

from dataclasses import dataclass

from slop_measure.domain.changes import FileChange, LineTotals, UnavailableLineDelta
from slop_measure.domain.evidence import DiagnosticSeverity
from slop_measure.domain.inventory import SourceInventory
from slop_measure.domain.metrics import (
    MeasuredMetric,
    MetricMeasurement,
    MetricResult,
    MetricUnit,
    MetricVersion,
    ProjectMetricScope,
    UnavailableMetric,
    UnavailableReason,
)
from slop_measure.domain.reports import (
    AnalysisReport,
    CohortResult,
    ComparisonAnalysis,
    ComparisonCohortReport,
    ScoreUnavailableReason,
    SnapshotAnalysis,
    SourceSide,
    UnavailableSnapshotScore,
)
from slop_measure.domain.source import Cohort, ProjectPath, SourceDocument
from slop_measure.metrics.deltas import metric_deltas
from slop_measure.metrics.loc_delta import measure_line_delta, sum_line_deltas
from slop_measure.sources.compare import match_files


def _remap_metrics(metrics: tuple[MetricResult, ...], side: SourceSide) -> tuple[MetricResult, ...]:
    return tuple(
        metric.model_copy(update={"diagnostic_id": f"{side.value}:{metric.diagnostic_id}"})
        if isinstance(metric, UnavailableMetric) and metric.diagnostic_id is not None
        else metric
        for metric in metrics
    )


def _remap_result(result: CohortResult, side: SourceSide) -> CohortResult:
    return result.model_copy(
        update={
            "metrics": _remap_metrics(result.metrics, side),
            "files": tuple(
                file.model_copy(update={"metrics": _remap_metrics(file.metrics, side)})
                for file in result.files
            ),
        }
    )


def _empty(cohort: Cohort) -> CohortResult:
    return CohortResult(
        score=UnavailableSnapshotScore(reason=ScoreUnavailableReason.NO_SOURCE_LINES),
        metrics=tuple(
            UnavailableMetric(
                metric_id=metric_id,
                scope=ProjectMetricScope(cohort=cohort),
                reason=UnavailableReason.NO_SOURCE_LINES,
            )
            for metric_id in (
                "m2.pattern-verbosity",
                "m3.clone-verbosity",
                "m4.erosion",
                "verbosity.combined",
            )
        ),
    )


@dataclass(frozen=True)
class _Side:
    report: AnalysisReport
    documents: dict[str, SourceDocument]
    cohorts: dict[tuple[str, Cohort], CohortResult]

    @classmethod
    def from_snapshot(cls, report: AnalysisReport, inventory: SourceInventory, side: SourceSide):
        return cls(
            report,
            {doc.path.root: doc for doc in inventory.documents},
            {
                (item.language, item.cohort): _remap_result(item.current, side)
                for item in report.cohorts
            },
        )

    def unassigned_error(self) -> bool:
        paths = {
            file.evidence.path.root for cohort in self.cohorts.values() for file in cohort.files
        }
        return any(
            item.detail.severity is DiagnosticSeverity.ERROR
            and (item.detail.path is None or item.detail.path.root not in paths)
            for item in self.report.diagnostics
        )


def _changes(
    baseline: CohortResult,
    current: CohortResult,
    before: _Side,
    after: _Side,
    renames: tuple[tuple[ProjectPath, ProjectPath], ...],
) -> tuple[FileChange, ...]:
    old = {file.evidence.path.root: file for file in baseline.files}
    new = {file.evidence.path.root: file for file in current.files}
    pairs = match_files(
        tuple(before.documents[path] for path in old if path in before.documents),
        tuple(after.documents[path] for path in new if path in after.documents),
        baseline_unreadable=tuple(
            old[path].evidence for path in old if path not in before.documents
        ),
        current_unreadable=tuple(new[path].evidence for path in new if path not in after.documents),
        renames=renames,
    )
    changes = []
    for pair in pairs:
        baseline_path = getattr(pair, "baseline_path", None)
        current_path = getattr(pair, "current_path", None)
        old_path = baseline_path.root if baseline_path is not None else ""
        new_path = current_path.root if current_path is not None else ""
        old_file, new_file = old.get(old_path), new.get(new_path)
        changes.append(
            FileChange(
                pair=pair,
                lines=measure_line_delta(
                    before.documents.get(old_path),
                    after.documents.get(new_path),
                    old_file.evidence if old_file is not None else None,
                    new_file.evidence if new_file is not None else None,
                ),
                deltas=metric_deltas(old_file, new_file),
            )
        )
    return tuple(changes)


def _m1(cohort: Cohort, totals: LineTotals) -> MetricResult:
    scope = ProjectMetricScope(cohort=cohort)
    if totals.state == "unavailable":
        return UnavailableMetric(metric_id="m1.loc-delta", scope=scope, reason=totals.reason)
    return MeasuredMetric(
        metric_id="m1.loc-delta",
        scope=scope,
        raw=MetricMeasurement(
            numerator=totals.added,
            denominator=totals.deleted,
            value=totals.net,
            unit=MetricUnit.LINES,
        ),
    )


def _cohorts(
    before: _Side, after: _Side, renames: tuple[tuple[ProjectPath, ProjectPath], ...]
) -> tuple[ComparisonCohortReport, ...]:
    cohorts = []
    unknown_source = before.unassigned_error() or after.unassigned_error()
    for language, cohort in sorted(before.cohorts.keys() | after.cohorts.keys()):
        baseline = before.cohorts.get((language, cohort), _empty(cohort))
        current = after.cohorts.get((language, cohort), _empty(cohort))
        changes = _changes(baseline, current, before, after, renames)
        totals = (
            UnavailableLineDelta(reason=UnavailableReason.PARSE_FAILED)
            if unknown_source
            else sum_line_deltas(changes)
        )
        cohorts.append(
            ComparisonCohortReport(
                language=language,
                cohort=cohort,
                baseline=baseline,
                current=current,
                changes=changes,
                line_delta=totals,
                metrics=(_m1(cohort, totals),),
                deltas=metric_deltas(baseline, current),
            )
        )
    return tuple(cohorts)


def _measured_ids(report: AnalysisReport) -> set[str]:
    return {
        metric.metric_id
        for cohort in report.cohorts
        for result in (cohort.current, *cohort.current.files)
        for metric in result.metrics
        if isinstance(metric, MeasuredMetric)
    }


def _compatible_versions(
    baseline: AnalysisReport, current: AnalysisReport
) -> tuple[MetricVersion, ...]:
    if baseline.provenance.model_copy(update={"metrics": ()}) != current.provenance.model_copy(
        update={"metrics": ()}
    ):
        raise ValueError("comparison snapshots require matching provenance")
    versions: dict[str, str] = {}
    for report in (baseline, current):
        available = {item.metric_id: item.version for item in report.provenance.metrics}
        if not _measured_ids(report) <= available.keys():
            raise ValueError("measured comparison inputs require metric versions")
        for metric_id, version in available.items():
            if metric_id in versions and versions[metric_id] != version:
                raise ValueError("comparison snapshots have conflicting metric versions")
            versions[metric_id] = version
    versions["m1.loc-delta"] = "1"
    return tuple(
        MetricVersion(metric_id=key, version=value) for key, value in sorted(versions.items())
    )


def assemble_comparison(
    baseline: AnalysisReport,
    current: AnalysisReport,
    baseline_inventory: SourceInventory,
    current_inventory: SourceInventory,
    *,
    renames: tuple[tuple[ProjectPath, ProjectPath], ...] = (),
) -> AnalysisReport:
    """Preserve source facts and require compatible snapshot provenance."""
    if not isinstance(baseline.analysis, SnapshotAnalysis) or not isinstance(
        current.analysis, SnapshotAnalysis
    ):
        raise ValueError("comparison assembly requires two snapshot reports")
    versions = _compatible_versions(baseline, current)
    sides = ((SourceSide.BASELINE, baseline), (SourceSide.CURRENT, current))
    return AnalysisReport(
        analysis=ComparisonAnalysis(
            baseline=baseline.analysis.current, current=current.analysis.current
        ),
        provenance=current.provenance.model_copy(update={"metrics": versions}),
        cohorts=_cohorts(
            _Side.from_snapshot(baseline, baseline_inventory, SourceSide.BASELINE),
            _Side.from_snapshot(current, current_inventory, SourceSide.CURRENT),
            renames,
        ),
        coverage=tuple(
            item.model_copy(update={"source": side})
            for side, report in sides
            for item in report.coverage
        ),
        excluded_directories=tuple(
            item.model_copy(update={"source": side})
            for side, report in sides
            for item in report.excluded_directories
        ),
        findings=tuple(
            item.model_copy(update={"id": f"{side.value}:{item.id}", "source": side})
            for side, report in sides
            for item in report.findings
        ),
        clone_groups=tuple(
            item.model_copy(update={"id": f"{side.value}:{item.id}", "source": side})
            for side, report in sides
            for item in report.clone_groups
        ),
        diagnostics=tuple(
            item.model_copy(update={"id": f"{side.value}:{item.id}", "source": side})
            for side, report in sides
            for item in report.diagnostics
        ),
    )
