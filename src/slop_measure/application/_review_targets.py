"""Project typed report evidence into source-bound review targets."""

from collections.abc import Iterator, Mapping

from pydantic import BaseModel

from slop_measure.domain.boundaries import clone_boundary_context
from slop_measure.domain.derived_review import DerivedReviewReport
from slop_measure.domain.model_review import ModelReviewReport
from slop_measure.domain.reports import AnalysisReport, SourceSide
from slop_measure.domain.review_workflow import (
    NoReviewBoundary,
    RelevantReviewBoundary,
    ReviewableTarget,
    ReviewAnchor,
    ReviewBoundary,
    ReviewKind,
    ReviewLocation,
    ReviewSubject,
    ReviewTarget,
    UnavailableReviewTarget,
    fingerprint,
    subject_paths,
    target_id,
)
from slop_measure.domain.reviews import SourceHash
from slop_measure.domain.source import Cohort, ProjectPath
from slop_measure.domain.variant_review import VariantReviewReport

SupportedReviewReport = (
    AnalysisReport | ModelReviewReport | VariantReviewReport | DerivedReviewReport
)


# The population, human location, and typed evidence are independent subject inputs.
def _subject(  # noqa: PLR0913, PLR0917
    kind: ReviewKind,
    language: str,
    cohort: Cohort,
    symbol: str,
    locations: tuple[ReviewLocation, ...],
    evidence: BaseModel,
) -> ReviewSubject:
    by_location = {
        (item.path.root, item.span.start_line, item.span.end_line): item for item in locations
    }
    return ReviewSubject(
        kind=kind,
        language=language,
        cohort=cohort,
        symbol=symbol,
        locations=tuple(by_location[key] for key in sorted(by_location)),
        evidence_fingerprint=fingerprint(evidence.model_dump(mode="json")),
    )


def _target(
    subject: ReviewSubject,
    sources: Mapping[str, str | None],
    analysis: str | None,
    boundary: ReviewBoundary | None = None,
) -> ReviewTarget:
    paths = subject_paths(subject)
    if any(sources.get(path) is None for path in paths):
        return UnavailableReviewTarget(
            id=target_id(subject), subject=subject, reason="source-hash-unavailable"
        )
    if analysis is None:
        return UnavailableReviewTarget(
            id=target_id(subject), subject=subject, reason="analysis-unavailable"
        )
    return ReviewableTarget(
        id=target_id(subject),
        anchor=ReviewAnchor(
            subject=subject,
            source_hashes=tuple(
                SourceHash(path=ProjectPath(path), sha256=value)
                for path in paths
                if (value := sources[path]) is not None
            ),
            boundary=boundary if boundary is not None else NoReviewBoundary(),
            analysis_fingerprint=analysis,
        ),
    )


def _analysis(report: AnalysisReport, language: str, kind: ReviewKind) -> str | None:
    analyzer = next(
        (item for item in report.provenance.analyzers if item.language == language), None
    )
    if analyzer is None:
        return None
    config = report.provenance.config
    if kind is ReviewKind.PATTERN:
        return (
            fingerprint((analyzer.adapter_version, analyzer.rule_set_version))
            if analyzer.rule_set_version
            else None
        )
    metric_id = "m3.clone-verbosity" if kind is ReviewKind.CLONE else "m4.erosion"
    metric = next(
        (item.version for item in report.provenance.metrics if item.metric_id == metric_id), None
    )
    if metric is None:
        return None
    if kind is ReviewKind.CLONE:
        return (
            fingerprint(
                (
                    metric,
                    analyzer.clone_normalization_version,
                    config.clone_min_statements,
                    config.clone_min_sloc,
                )
            )
            if analyzer.clone_normalization_version
            else None
        )
    return fingerprint((metric, analyzer.adapter_version, config.complexity_threshold))


def _snapshot_targets(report: AnalysisReport) -> Iterator[ReviewTarget]:
    files = {
        file.evidence.path.root: file for cohort in report.cohorts for file in cohort.current.files
    }
    sources = {path: file.source_sha256 for path, file in files.items()}
    for group in report.clone_groups:
        if group.source is not SourceSide.CURRENT:
            continue
        detail = group.detail
        subject = _subject(
            ReviewKind.CLONE,
            detail.language,
            detail.cohort,
            "clone",
            tuple(ReviewLocation(path=item.path, span=item.span) for item in detail.members),
            detail,
        )
        boundary = RelevantReviewBoundary(
            assignments=clone_boundary_context(
                tuple(item.path for item in detail.members), report.provenance.config.boundaries
            ).members
        )
        yield _target(
            subject, sources, _analysis(report, detail.language, ReviewKind.CLONE), boundary
        )
    for finding in report.findings:
        if finding.source is not SourceSide.CURRENT:
            continue
        item = finding.detail
        file = files[item.path.root].evidence
        subject = _subject(
            ReviewKind.PATTERN,
            file.language,
            file.cohort,
            item.rule_id,
            (ReviewLocation(path=item.path, span=item.span),),
            item,
        )
        yield _target(subject, sources, _analysis(report, file.language, ReviewKind.PATTERN))
    for file in files.values():
        evidence = file.evidence
        for function in file.functions:
            subject = _subject(
                ReviewKind.COMPLEXITY,
                evidence.language,
                evidence.cohort,
                function.qualified_name,
                (ReviewLocation(path=evidence.path, span=function.span),),
                function,
            )
            yield _target(
                subject, sources, _analysis(report, evidence.language, ReviewKind.COMPLEXITY)
            )


def _model_subjects(report: ModelReviewReport) -> Iterator[ReviewSubject]:
    for file in report.files:
        if file.state != "analyzed":
            continue
        for model in file.models:
            if model.state != "analyzed":
                continue
            for finding in model.findings:
                spans = (
                    finding.validator.span,
                    *(item.span for item in finding.fields),
                    *(item.span for item in finding.consumers),
                )
                yield _subject(
                    ReviewKind.MODEL,
                    "python",
                    file.cohort,
                    model.name,
                    tuple(ReviewLocation(path=file.path, span=span) for span in spans),
                    finding,
                )


def _variant_subjects(report: VariantReviewReport) -> Iterator[ReviewSubject]:
    for file in report.files:
        if file.state != "analyzed":
            continue
        for handler in file.handlers:
            if handler.state == "analyzed":
                yield _subject(
                    ReviewKind.VARIANT,
                    "python",
                    file.cohort,
                    handler.symbol,
                    (ReviewLocation(path=file.path, span=handler.span),),
                    handler,
                )


def _derived_subjects(report: DerivedReviewReport) -> Iterator[ReviewSubject]:
    for file in report.files:
        if file.state != "analyzed":
            continue
        for function in file.functions:
            if function.state != "analyzed":
                continue
            for finding in function.findings:
                symbol = f"{function.symbol}:{finding.derived_name}:{finding.source_name}"
                spans = (finding.derivation, finding.mutation, finding.read)
                yield _subject(
                    ReviewKind.DERIVED,
                    "python",
                    file.cohort,
                    symbol,
                    tuple(ReviewLocation(path=file.path, span=span) for span in spans),
                    finding,
                )


def review_targets(report: SupportedReviewReport) -> tuple[ReviewTarget, ...]:
    """List exact owned evidence without applying thresholds or changing the report."""
    if isinstance(report, AnalysisReport):
        targets = tuple(_snapshot_targets(report))
    else:
        sources = {file.path.root: file.source_sha256 for file in report.files}
        if isinstance(report, ModelReviewReport):
            subjects = _model_subjects(report)
        elif isinstance(report, VariantReviewReport):
            subjects = _variant_subjects(report)
        else:
            subjects = _derived_subjects(report)
        targets = tuple(
            _target(subject, sources, fingerprint(report.experiment)) for subject in subjects
        )
    by_id = {item.id: item for item in targets}
    return tuple(by_id[key] for key in sorted(by_id))
