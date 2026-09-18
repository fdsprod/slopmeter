"""Compare owned snapshot results without fabricating missing-side values."""

from slop_measure.domain.changes import MeasuredMetricDelta, MetricDelta, UnavailableMetricDelta
from slop_measure.domain.metrics import MeasuredMetric, MetricResult, MetricUnit
from slop_measure.domain.reports import (
    CohortResult,
    FileResult,
    MeasuredSnapshotScore,
    SnapshotScore,
)

_RAW_IDS = ("m2.pattern-verbosity", "m3.clone-verbosity", "m4.erosion", "verbosity.combined")
_Result = FileResult | CohortResult


def _raw_delta(
    metric_id: str, baseline: MetricResult | None, current: MetricResult | None
) -> MetricDelta:
    if baseline is None:
        return UnavailableMetricDelta(metric_id=metric_id, reason="missing-baseline")
    if current is None:
        return UnavailableMetricDelta(metric_id=metric_id, reason="missing-current")
    if not isinstance(baseline, MeasuredMetric) or not isinstance(current, MeasuredMetric):
        return UnavailableMetricDelta(metric_id=metric_id, reason="unavailable-input")
    if baseline.raw.unit is not current.raw.unit or (
        baseline.scope.kind,
        baseline.scope.cohort,
    ) != (current.scope.kind, current.scope.cohort):
        return UnavailableMetricDelta(metric_id=metric_id, reason="incompatible-definitions")
    return MeasuredMetricDelta(
        metric_id=metric_id,
        value=current.raw.value - baseline.raw.value,
        unit="ratio" if current.raw.unit is MetricUnit.RATIO else "lines",
    )


def _score_delta(baseline: SnapshotScore | None, current: SnapshotScore | None) -> MetricDelta:
    metric_id = "snapshot.score"
    if baseline is None:
        return UnavailableMetricDelta(metric_id=metric_id, reason="missing-baseline")
    if current is None:
        return UnavailableMetricDelta(metric_id=metric_id, reason="missing-current")
    if not isinstance(baseline, MeasuredSnapshotScore) or not isinstance(
        current, MeasuredSnapshotScore
    ):
        return UnavailableMetricDelta(metric_id=metric_id, reason="unavailable-input")
    if (baseline.profile_id, baseline.model_id) != (current.profile_id, current.model_id):
        return UnavailableMetricDelta(metric_id=metric_id, reason="incompatible-definitions")
    return MeasuredMetricDelta(
        metric_id=metric_id, value=current.points - baseline.points, unit="points"
    )


def metric_deltas(baseline: _Result | None, current: _Result | None) -> tuple[MetricDelta, ...]:
    """Return stable raw and compatible score deltas, current minus baseline."""
    if baseline is None and current is None:
        raise ValueError("Metric comparison requires at least one source result.")
    if baseline is not None and current is not None and type(baseline) is not type(current):
        raise ValueError("Metric comparison cannot mix file and project results.")
    if (
        isinstance(baseline, FileResult)
        and isinstance(current, FileResult)
        and (baseline.evidence.language, baseline.evidence.cohort)
        != (current.evidence.language, current.evidence.cohort)
    ):
        raise ValueError("Metric comparison cannot cross language or cohort boundaries.")
    old = {item.metric_id: item for item in baseline.metrics} if baseline is not None else {}
    new = {item.metric_id: item for item in current.metrics} if current is not None else {}
    deltas = [
        _raw_delta(metric_id, old.get(metric_id), new.get(metric_id)) for metric_id in _RAW_IDS
    ]
    deltas.append(
        _score_delta(
            baseline.score if baseline is not None else None,
            current.score if current is not None else None,
        )
    )
    return tuple(sorted(deltas, key=lambda item: item.metric_id))
