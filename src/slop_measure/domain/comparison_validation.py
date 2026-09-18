"""Check comparison projections against their two authoritative source states."""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import TYPE_CHECKING, Literal

from slop_measure.domain.changes import MeasuredLineDelta, MeasuredLineTotals
from slop_measure.domain.evidence import ParseState
from slop_measure.domain.metrics import MetricUnit

if TYPE_CHECKING:
    from slop_measure.domain.changes import FileChange, MetricDelta
    from slop_measure.domain.reports import CohortResult, ComparisonCohortReport, FileResult


@dataclass(frozen=True)
class _Comparable:
    value: float
    unit: str
    definition: tuple[str, ...] = ()


def _input(
    result: FileResult | CohortResult | None, metric_id: str
) -> _Comparable | Literal["missing", "unavailable"]:
    if result is None:
        return "missing"
    if metric_id == "snapshot.score":
        score = result.score
        return (
            _Comparable(score.points, "points", (score.profile_id, score.model_id))
            if score.state == "measured"
            else "unavailable"
        )
    metric = next((item for item in result.metrics if item.metric_id == metric_id), None)
    if metric is None:
        return "missing"
    return (
        _Comparable(metric.raw.value, metric.raw.unit.value)
        if metric.state == "measured"
        else "unavailable"
    )


def _reason(
    before: _Comparable | str, after: _Comparable | str
) -> (
    Literal["missing-baseline", "missing-current", "unavailable-input", "incompatible-definitions"]
    | None
):
    if before == "missing":
        return "missing-baseline"
    if after == "missing":
        return "missing-current"
    if isinstance(before, str) or isinstance(after, str):
        return "unavailable-input"
    if (before.unit, before.definition) != (after.unit, after.definition):
        return "incompatible-definitions"
    return None


def validate_deltas(
    deltas: tuple[MetricDelta, ...],
    baseline: FileResult | CohortResult | None,
    current: FileResult | CohortResult | None,
) -> None:
    """Validate every supplied delta without requiring absent optional metrics."""
    identifiers = [item.metric_id for item in deltas]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate comparison metric delta")
    for delta in deltas:
        before, after = _input(baseline, delta.metric_id), _input(current, delta.metric_id)
        reason = _reason(before, after)
        if delta.state == "unavailable":
            if reason != delta.reason:
                raise ValueError("metric delta reason must match its source inputs")
        elif (
            reason is not None
            or not isinstance(before, _Comparable)
            or not isinstance(after, _Comparable)
            or delta.unit != after.unit
            or not isclose(delta.value, after.value - before.value, abs_tol=1e-12)
        ):
            raise ValueError("metric delta must equal its current minus baseline input")


def _validate_file_lines(
    change: FileChange, baseline: FileResult | None, current: FileResult | None
) -> None:
    lines = change.lines
    if not isinstance(lines, MeasuredLineDelta):
        return
    for file, sloc, changed in (
        (baseline, lines.baseline_sloc, lines.deleted_lines),
        (current, lines.current_sloc, lines.added_lines),
    ):
        if file is None:
            if sloc or changed:
                raise ValueError("an absent file cannot own source lines")
        elif (
            file.evidence.parse_state is not ParseState.PARSED
            or sloc != file.evidence.sloc
            or not set(changed) <= set(file.evidence.sloc_lines)
        ):
            raise ValueError("changed lines must belong to their parsed source file")


def _validate_totals(cohort: ComparisonCohortReport) -> None:
    totals = cohort.line_delta
    if isinstance(totals, MeasuredLineTotals):
        measured = tuple(
            change.lines for change in cohort.changes if isinstance(change.lines, MeasuredLineDelta)
        )
        expected = (
            sum(file.evidence.sloc for file in cohort.baseline.files),
            sum(file.evidence.sloc for file in cohort.current.files),
            sum(item.added for item in measured),
            sum(item.deleted for item in measured),
        )
        if len(measured) != len(cohort.changes) or expected != (
            totals.baseline_sloc,
            totals.current_sloc,
            totals.added,
            totals.deleted,
        ):
            raise ValueError("project line totals must reconcile with every file change")
    for metric in cohort.metrics:
        if metric.metric_id != "m1.loc-delta":
            continue
        if metric.state != totals.state:
            raise ValueError("M1 availability must match line totals")
        if (
            metric.state == "measured"
            and isinstance(totals, MeasuredLineTotals)
            and (
                metric.raw.unit,
                metric.raw.numerator,
                metric.raw.denominator,
                metric.raw.value,
            )
            != (
                MetricUnit.LINES,
                totals.added,
                totals.deleted,
                totals.net,
            )
        ):
            raise ValueError("M1 raw values must equal the owned line totals")


def validate_cohort_changes(cohort: ComparisonCohortReport) -> None:
    """Require one complete pairing of each side and reconcile all supplied projections."""
    baseline = {file.evidence.path.root: file for file in cohort.baseline.files}
    current = {file.evidence.path.root: file for file in cohort.current.files}
    seen_before: list[str] = []
    seen_after: list[str] = []
    for change in cohort.changes:
        before_path = getattr(change.pair, "baseline_path", None)
        after_path = getattr(change.pair, "current_path", None)
        before = baseline.get(before_path.root) if before_path is not None else None
        after = current.get(after_path.root) if after_path is not None else None
        if before_path is not None:
            seen_before.append(before_path.root)
        if after_path is not None:
            seen_after.append(after_path.root)
        _validate_file_lines(change, before, after)
        validate_deltas(change.deltas, before, after)
    if sorted(seen_before) != sorted(baseline) or sorted(seen_after) != sorted(current):
        raise ValueError("comparison must pair every source file exactly once")
    _validate_totals(cohort)
    validate_deltas(cohort.deltas, cohort.baseline, cohort.current)
