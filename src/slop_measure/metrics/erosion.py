"""Structural erosion derived from total callable mass."""

from math import fsum

from slop_measure.domain.evidence import FunctionEvidence
from slop_measure.domain.metrics import (
    FileMetricScope,
    MeasuredMetric,
    MetricMeasurement,
    MetricResult,
    MetricScope,
    MetricUnit,
    UnavailableMetric,
    UnavailableReason,
)


def measure_erosion(
    functions: tuple[FunctionEvidence, ...], scope: MetricScope, threshold: int
) -> MetricResult:
    """Measure the fraction of mass above a strict complexity threshold."""
    if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold <= 0:
        raise ValueError("complexity threshold must be a positive integer")
    if isinstance(scope, FileMetricScope) and any(
        function.path != scope.path for function in functions
    ):
        raise ValueError("function path must match the file metric scope")
    if not functions:
        return UnavailableMetric(
            metric_id="m4.erosion", scope=scope, reason=UnavailableReason.NO_FUNCTIONS
        )
    total = fsum(function.mass for function in functions)
    eroded = fsum(
        function.mass for function in functions if function.cyclomatic_complexity > threshold
    )
    return MeasuredMetric(
        metric_id="m4.erosion",
        scope=scope,
        raw=MetricMeasurement(
            numerator=eroded, denominator=total, value=eroded / total, unit=MetricUnit.RATIO
        ),
    )
