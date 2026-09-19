"""Explicit review-store writes and read-only source-bound review resolution."""

import os
import tempfile
from contextlib import suppress
from pathlib import Path

from slop_measure.domain.reports import AnalysisReport, ReportCloneGroup, SourceSide
from slop_measure.domain.reviews import (
    CloneReviewAnchor,
    CloneReviewDecision,
    CloneReviewResult,
    CurrentCloneReview,
    MissingCloneReview,
    ReviewDisposition,
    ReviewStore,
    StaleCloneReview,
)
from slop_measure.errors import InputError


def _check_store(path: Path) -> None:
    if path.is_symlink():
        raise InputError("Review store cannot be a symbolic link.")


def load_review_store(path: Path) -> ReviewStore:
    """Read an explicitly selected store without modifying it."""
    try:
        _check_store(path)
        return ReviewStore.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise InputError(f"Cannot load review store: {error}") from error


def _anchor(report: AnalysisReport, group: ReportCloneGroup) -> CloneReviewAnchor:
    try:
        return report.clone_review_anchor(group)
    except ValueError as error:
        raise InputError(str(error)) from error


def _resolve(report: AnalysisReport, decision: CloneReviewDecision) -> CloneReviewResult:
    detail = decision.anchor.detail
    paths = {member.path.root for member in detail.members}
    candidates = tuple(
        group
        for group in report.clone_groups
        if group.source is SourceSide.CURRENT
        and (
            group.id == decision.id
            or (
                group.detail.language == detail.language
                and group.detail.cohort is detail.cohort
                and {member.path.root for member in group.detail.members} == paths
            )
        )
    )
    for group in candidates:
        try:
            anchor = _anchor(report, group)
        except InputError:
            continue
        if anchor == decision.anchor:
            return CurrentCloneReview(decision=decision, group_id=group.id)
    if candidates:
        return StaleCloneReview(
            decision=decision,
            candidate_group_ids=tuple(sorted(group.id for group in candidates)),
            changes=tuple(
                report.clone_review_change(decision, group)
                for group in sorted(candidates, key=lambda item: item.id)
            ),
        )
    return MissingCloneReview(decision=decision)


def apply_reviews(report: AnalysisReport, store: ReviewStore) -> AnalysisReport:
    """Annotate existing evidence without filtering or changing any measured facts."""
    results = tuple(
        _resolve(report, decision) for decision in sorted(store.decisions, key=lambda item: item.id)
    )
    return report.model_copy(update={"review_results": results})


def _write_locked(path: Path, decision: CloneReviewDecision) -> ReviewStore:
    temporary: Path | None = None
    try:
        _check_store(path)
        existing = load_review_store(path) if path.exists() else ReviewStore()
        decisions = {item.id: item for item in existing.decisions}
        decisions[decision.id] = decision
        store = ReviewStore(decisions=tuple(decisions[key] for key in sorted(decisions)))
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write((store.model_dump_json(indent=2) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        _check_store(path)
        os.replace(temporary, path)
        return store
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


# Store destination, evidence selection, and review text are independent public inputs.
def write_clone_review(  # noqa: PLR0913
    path: Path,
    report: AnalysisReport,
    group_id: str,
    *,
    disposition: ReviewDisposition,
    reason: str,
    next_step: str = "",
) -> ReviewStore:
    """Upsert one validated current-source decision with an exclusive atomic write."""
    lock = path.with_name(path.name + ".lock")
    acquired = False
    try:
        _check_store(path)
        group = next(
            (
                item
                for item in report.clone_groups
                if item.id == group_id and item.source is SourceSide.CURRENT
            ),
            None,
        )
        if group is None:
            raise InputError("Clone group must exist in the current source report.")
        decision = CloneReviewDecision(
            id=group_id,
            anchor=_anchor(report, group),
            disposition=disposition,
            reason=reason,
            next_step=next_step,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("x", encoding="utf-8"):
            acquired = True
        return _write_locked(path, decision)
    except (OSError, ValueError) as error:
        raise InputError(f"Cannot write clone review: {error}") from error
    finally:
        if acquired:
            with suppress(OSError):
                lock.unlink(missing_ok=True)
