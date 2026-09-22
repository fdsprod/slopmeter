"""Review saved evidence with attributed history and exact applicability checks."""

import json
import os
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from slop_measure.application._review_targets import SupportedReviewReport, review_targets
from slop_measure.application.reviews import apply_reviews
from slop_measure.domain.derived_review import DerivedReviewReport
from slop_measure.domain.error_review import ErrorReviewReport
from slop_measure.domain.model_review import ModelReviewReport
from slop_measure.domain.reports import AnalysisReport
from slop_measure.domain.review_workflow import (
    CurrentReview,
    LegacyReviewOutsideReport,
    LegacyReviewResult,
    MissingReview,
    ReviewCause,
    ReviewDecision,
    ReviewEvent,
    ReviewKind,
    ReviewLedger,
    ReviewOutsideReport,
    ReviewResolutionReport,
    ReviewResult,
    ReviewSubject,
    ReviewTarget,
    ReviewTargetChange,
    StaleReview,
    SupersededLegacyReview,
    subject_key,
)
from slop_measure.domain.reviews import ReviewDisposition, ReviewStore
from slop_measure.domain.variant_review import VariantReviewReport
from slop_measure.errors import InputError

__all__ = [
    "load_review_ledger",
    "load_review_report",
    "resolve_reviews",
    "review_targets",
    "write_review",
]


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("saved input must be a JSON object")
    return value


def load_review_report(path: Path) -> SupportedReviewReport:
    """Validate one supported native report without reading its original source root."""
    try:
        payload = _read(path)
        if "experiment" not in payload:
            return AnalysisReport.model_validate(payload)
        match payload["experiment"]:
            case "py-coupled-state-1":
                return ModelReviewReport.model_validate(payload)
            case "py-variant-review-1":
                return VariantReviewReport.model_validate(payload)
            case "py-derived-state-1":
                return DerivedReviewReport.model_validate(payload)
            case "py-error-fallback-1":
                return ErrorReviewReport.model_validate(payload)
            case _:
                raise ValueError("unsupported saved report experiment")
    except (OSError, ValueError) as error:
        raise InputError(f"Cannot load review report: {error}") from error


def _check_store(path: Path) -> None:
    if path.is_symlink():
        raise InputError("Review store cannot be a symbolic link.")


def load_review_ledger(path: Path) -> ReviewLedger:
    """Read either version without changing its bytes or weakening legacy anchors."""
    try:
        _check_store(path)
        payload = _read(path)
        if payload.get("schema_version", "1") == "1":
            return ReviewLedger(legacy_decisions=ReviewStore.model_validate(payload).decisions)
        return ReviewLedger.model_validate(payload)
    except (OSError, ValueError) as error:
        raise InputError(f"Cannot load review store: {error}") from error


def _subject(target: ReviewTarget) -> ReviewSubject:
    return target.anchor.subject if target.state == "reviewable" else target.subject


def _changes(event: ReviewEvent, candidate: ReviewTarget) -> ReviewTargetChange:
    previous = event.decision.anchor
    causes: list[ReviewCause] = []
    subject = _subject(candidate)
    if subject != previous.subject:
        causes.append("evidence-changed")
    if candidate.state == "unavailable":
        causes.append(
            "source-unavailable"
            if candidate.reason == "source-hash-unavailable"
            else "analysis-unavailable"
        )
    else:
        anchor = candidate.anchor
        if anchor.source_hashes != previous.source_hashes:
            causes.append("source-changed")
        if anchor.boundary != previous.boundary:
            causes.append("boundary-policy-changed")
        if anchor.analysis_fingerprint != previous.analysis_fingerprint:
            causes.append("analysis-definition-changed")
    return ReviewTargetChange(target_id=candidate.id, candidate=candidate, causes=tuple(causes))


def _resolve(
    event: ReviewEvent, targets: tuple[ReviewTarget, ...], kinds: frozenset[ReviewKind]
) -> ReviewResult:
    anchor = event.decision.anchor
    if anchor.subject.kind not in kinds:
        return ReviewOutsideReport(event=event)
    candidates = tuple(
        item for item in targets if subject_key(_subject(item)) == subject_key(anchor.subject)
    )
    for item in candidates:
        if item.state == "reviewable" and item.anchor == anchor:
            return CurrentReview(event=event, target_id=item.id)
    if candidates:
        return StaleReview(event=event, changes=tuple(_changes(event, item) for item in candidates))
    return MissingReview(event=event)


def _report_kinds(report: SupportedReviewReport) -> frozenset[ReviewKind]:
    if isinstance(report, AnalysisReport):
        return frozenset((ReviewKind.CLONE, ReviewKind.COMPLEXITY, ReviewKind.PATTERN))
    if isinstance(report, ModelReviewReport):
        return frozenset((ReviewKind.MODEL,))
    if isinstance(report, VariantReviewReport):
        return frozenset((ReviewKind.VARIANT,))
    if isinstance(report, DerivedReviewReport):
        return frozenset((ReviewKind.DERIVED,))
    return frozenset((ReviewKind.ERROR,))


def _legacy_results(
    report: SupportedReviewReport, ledger: ReviewLedger
) -> tuple[LegacyReviewResult, ...]:
    if isinstance(report, AnalysisReport):
        legacy = apply_reviews(
            report, ReviewStore(decisions=ledger.legacy_decisions)
        ).review_results
    else:
        legacy = tuple(LegacyReviewOutsideReport(decision=item) for item in ledger.legacy_decisions)
    links: dict[str, ReviewEvent] = {}
    for event in ledger.events:
        if event.supersedes_legacy_id is not None:
            links.setdefault(event.supersedes_legacy_id, event)
    return tuple(
        SupersededLegacyReview(
            decision=result.decision, review_id=event.review_id, sequence=event.sequence
        )
        if (event := links.get(result.decision.id)) is not None
        else result
        for result in legacy
    )


def resolve_reviews(report: SupportedReviewReport, ledger: ReviewLedger) -> ReviewResolutionReport:
    """Resolve latest judgments against the selected saved report, not the filesystem."""
    targets = review_targets(report)
    kinds = _report_kinds(report)
    latest = {event.review_id: event for event in ledger.events}
    return ReviewResolutionReport(
        results=tuple(_resolve(latest[key], targets, kinds) for key in sorted(latest)),
        legacy_results=_legacy_results(report, ledger),
        events=ledger.events,
    )


def _replace(path: Path, ledger: ReviewLedger) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write((ledger.model_dump_json(indent=2) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        _check_store(path)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


def _append(path: Path, event: ReviewEvent, explicit_history: bool) -> ReviewLedger:
    previous = load_review_ledger(path) if path.exists() else ReviewLedger()
    if explicit_history and event.review_id not in {item.review_id for item in previous.events}:
        raise InputError("Explicit review ID must name an existing review history.")
    event = event.model_copy(update={"sequence": len(previous.events) + 1})
    ledger = ReviewLedger(
        legacy_decisions=previous.legacy_decisions, events=(*previous.events, event)
    )
    _replace(path, ledger)
    return ledger


# Explicit attribution, destination, evidence and judgment are independent public inputs.
def write_review(  # noqa: PLR0913
    path: Path,
    report: SupportedReviewReport,
    target_id: str,
    *,
    actor: str,
    disposition: ReviewDisposition,
    reason: str,
    next_step: str = "",
    review_id: str | None = None,
    supersedes_legacy_id: str | None = None,
) -> ReviewLedger:
    """Append one explicit judgment atomically, preserving every preceding event."""
    lock = path.with_name(path.name + ".lock")
    acquired = False
    try:
        _check_store(path)
        target = next((item for item in review_targets(report) if item.id == target_id), None)
        if target is None or target.state != "reviewable":
            raise InputError(
                "Review target is absent or its source/analysis anchor is unavailable."
            )
        event = ReviewEvent(
            sequence=1,
            review_id=review_id if review_id is not None else target.id,
            actor=actor,
            recorded_at=datetime.now(UTC),
            decision=ReviewDecision(
                anchor=target.anchor, disposition=disposition, reason=reason, next_step=next_step
            ),
            supersedes_legacy_id=supersedes_legacy_id,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("x", encoding="utf-8"):
            acquired = True
        return _append(path, event, review_id is not None)
    except (OSError, ValueError) as error:
        raise InputError(f"Cannot write review: {error}") from error
    finally:
        if acquired:
            with suppress(OSError):
                lock.unlink(missing_ok=True)
