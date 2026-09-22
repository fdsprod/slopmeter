"""Select saved review evidence without changing its identity or measured population."""

from slop_measure.domain.derived_review import DerivedReviewReport
from slop_measure.domain.model_review import ModelReviewReport
from slop_measure.domain.reports import AnalysisReport, SourceSide
from slop_measure.domain.review_workflow import ReviewKind, ReviewTarget, fingerprint
from slop_measure.domain.source import Cohort
from slop_measure.domain.variant_review import VariantReviewReport
from slop_measure.errors import SelectionError
from slop_measure.reporting.queries import query_findings


def _hotspot_evidence(report: AnalysisReport) -> frozenset[tuple[str, Cohort, str]]:
    version = next(
        (item.version for item in report.provenance.metrics if item.metric_id == "m4.erosion"),
        None,
    )
    if version not in {"1", "2", "3"}:
        raise SelectionError(
            "--hotspots-only requires a supported M4 metric version (1, 2, or 3). "
            f"Saved report version: {version or 'missing'}."
        )
    return frozenset(
        (item.language, item.cohort, fingerprint(item.function.model_dump(mode="json")))
        for item in query_findings(report, metric="m4", source=SourceSide.CURRENT).functions
    )


def select_review_targets(
    report: AnalysisReport | ModelReviewReport | VariantReviewReport | DerivedReviewReport,
    targets: tuple[ReviewTarget, ...],
    *,
    kinds: frozenset[ReviewKind] = frozenset(),
    cohort: Cohort | None = None,
    hotspots_only: bool = False,
) -> tuple[ReviewTarget, ...]:
    """Apply kind union, cohort intersection, and optional versioned M4 selection."""
    hotspots = None
    if hotspots_only:
        if kinds and ReviewKind.COMPLEXITY not in kinds:
            raise SelectionError("--hotspots-only requires --kind complexity or no --kind.")
        if not isinstance(report, AnalysisReport):
            raise SelectionError("--hotspots-only requires a saved score report with M4 evidence.")
        hotspots = _hotspot_evidence(report)
        kinds = frozenset({ReviewKind.COMPLEXITY})
    selected = []
    for target in targets:
        subject = target.anchor.subject if target.state == "reviewable" else target.subject
        if kinds and subject.kind not in kinds:
            continue
        if cohort is not None and subject.cohort is not cohort:
            continue
        if (
            hotspots is not None
            and (subject.language, subject.cohort, subject.evidence_fingerprint) not in hotspots
        ):
            continue
        selected.append(target)
    return tuple(selected)
