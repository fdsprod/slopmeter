"""Versioned, attributed review history independent of measured reports."""

from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from json import dumps
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from slop_measure.domain.boundaries import BoundaryAssignment
from slop_measure.domain.evidence import SourceSpan
from slop_measure.domain.reviews import (
    CloneReviewDecision,
    CloneReviewResult,
    ReviewDisposition,
    SourceHash,
)
from slop_measure.domain.source import Cohort, ProjectPath

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def fingerprint(value: object) -> str:
    """Hash a canonical JSON projection, not its input formatting."""
    return sha256(
        dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReviewKind(StrEnum):
    CLONE = "clone"
    COMPLEXITY = "complexity"
    PATTERN = "pattern"
    MODEL = "model"
    VARIANT = "variant"
    DERIVED = "derived"


class ReviewLocation(_Record):
    path: ProjectPath
    span: SourceSpan


class ReviewSubject(_Record):
    kind: ReviewKind
    language: _Text
    cohort: Cohort
    symbol: _Text
    locations: Annotated[tuple[ReviewLocation, ...], Field(min_length=1)]
    evidence_fingerprint: _Hash

    @model_validator(mode="after")
    def validate_locations(self) -> Self:
        keys = [
            (item.path.root, item.span.start_line, item.span.end_line) for item in self.locations
        ]
        if keys != sorted(set(keys)):
            raise ValueError("review locations must be sorted and unique")
        return self


def subject_paths(subject: ReviewSubject) -> tuple[str, ...]:
    return tuple(sorted({location.path.root for location in subject.locations}))


def subject_key(subject: ReviewSubject) -> tuple[ReviewKind, str, Cohort, str, tuple[str, ...]]:
    return subject.kind, subject.language, subject.cohort, subject.symbol, subject_paths(subject)


def target_id(subject: ReviewSubject) -> str:
    return f"{subject.kind.value}:{fingerprint(subject.model_dump(mode='json'))}"


class NoReviewBoundary(_Record):
    state: Literal["not-applicable"] = "not-applicable"


class RelevantReviewBoundary(_Record):
    state: Literal["relevant"] = "relevant"
    assignments: Annotated[tuple[BoundaryAssignment, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_paths(self) -> Self:
        paths = [item.path.root for item in self.assignments]
        if paths != sorted(set(paths)):
            raise ValueError("boundary assignments must be sorted and unique")
        return self


ReviewBoundary = Annotated[NoReviewBoundary | RelevantReviewBoundary, Field(discriminator="state")]


class ReviewAnchor(_Record):
    subject: ReviewSubject
    source_hashes: tuple[SourceHash, ...]
    boundary: ReviewBoundary
    analysis_fingerprint: _Hash

    @model_validator(mode="after")
    def validate_ownership(self) -> Self:
        paths = subject_paths(self.subject)
        if tuple(item.path.root for item in self.source_hashes) != paths:
            raise ValueError("review source hashes must exactly cover sorted subject paths")
        if self.subject.kind is ReviewKind.CLONE:
            if (
                self.boundary.state != "relevant"
                or tuple(item.path.root for item in self.boundary.assignments) != paths
            ):
                raise ValueError("clone boundaries must cover every member path")
        elif self.boundary.state != "not-applicable":
            raise ValueError("only clone reviews have boundary assignments")
        return self


class ReviewableTarget(_Record):
    state: Literal["reviewable"] = "reviewable"
    id: _Text
    anchor: ReviewAnchor

    @model_validator(mode="after")
    def validate_id(self) -> Self:
        if self.id != target_id(self.anchor.subject):
            raise ValueError("review target ID must match its owned subject")
        return self


class UnavailableReviewTarget(_Record):
    state: Literal["unavailable"] = "unavailable"
    id: _Text
    subject: ReviewSubject
    reason: Literal["source-hash-unavailable", "analysis-unavailable"]

    @model_validator(mode="after")
    def validate_id(self) -> Self:
        if self.id != target_id(self.subject):
            raise ValueError("review target ID must match its owned subject")
        return self


ReviewTarget = Annotated[ReviewableTarget | UnavailableReviewTarget, Field(discriminator="state")]


class ReviewDecision(_Record):
    anchor: ReviewAnchor
    disposition: ReviewDisposition
    reason: _Text
    next_step: str = ""


class ReviewEvent(_Record):
    sequence: Annotated[int, Field(gt=0, strict=True)]
    review_id: _Text
    actor: _Text
    recorded_at: datetime
    decision: ReviewDecision

    @model_validator(mode="after")
    def validate_time(self) -> Self:
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() != timedelta(0):
            raise ValueError("review timestamps must be timezone-aware UTC")
        return self


class ReviewLedger(_Record):
    schema_version: Literal["2"] = "2"
    legacy_decisions: tuple[CloneReviewDecision, ...] = ()
    events: tuple[ReviewEvent, ...] = ()

    @model_validator(mode="after")
    def validate_history(self) -> Self:
        legacy = {item.id for item in self.legacy_decisions}
        if len(legacy) != len(self.legacy_decisions):
            raise ValueError("legacy review IDs must be unique")
        histories = {}
        for index, event in enumerate(self.events, start=1):
            if event.sequence != index or event.review_id in legacy:
                raise ValueError(
                    "review sequences must be contiguous and IDs must not collide with legacy IDs"
                )
            key = subject_key(event.decision.anchor.subject)
            if event.review_id in histories and histories[event.review_id] != key:
                raise ValueError("review history cannot change its subject family")
            histories[event.review_id] = key
        return self


class CurrentReview(_Record):
    state: Literal["current"] = "current"
    event: ReviewEvent
    target_id: _Text


ReviewCause = Literal[
    "source-changed",
    "source-unavailable",
    "evidence-changed",
    "boundary-policy-changed",
    "analysis-definition-changed",
    "analysis-unavailable",
]


class ReviewTargetChange(_Record):
    target_id: _Text
    candidate: ReviewTarget
    causes: Annotated[tuple[ReviewCause, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_causes(self) -> Self:
        if self.target_id != self.candidate.id:
            raise ValueError("review change target ID must match its candidate")
        if len(set(self.causes)) != len(self.causes):
            raise ValueError("review change causes must be unique")
        return self


class StaleReview(_Record):
    state: Literal["stale"] = "stale"
    event: ReviewEvent
    changes: Annotated[tuple[ReviewTargetChange, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_targets(self) -> Self:
        if len({change.target_id for change in self.changes}) != len(self.changes):
            raise ValueError("stale review targets must be unique")
        return self


class MissingReview(_Record):
    state: Literal["missing"] = "missing"
    event: ReviewEvent
    reason: Literal["evidence-absent-or-unavailable"] = "evidence-absent-or-unavailable"


class ReviewOutsideReport(_Record):
    state: Literal["not-in-selected-report"] = "not-in-selected-report"
    event: ReviewEvent
    reason: Literal["review-family-not-in-selected-report"] = "review-family-not-in-selected-report"


class LegacyReviewOutsideReport(_Record):
    state: Literal["not-in-selected-report"] = "not-in-selected-report"
    decision: CloneReviewDecision
    reason: Literal["review-family-not-in-selected-report"] = "review-family-not-in-selected-report"


ReviewResult = Annotated[
    CurrentReview | StaleReview | MissingReview | ReviewOutsideReport,
    Field(discriminator="state"),
]
LegacyReviewResult = Annotated[
    CloneReviewResult | LegacyReviewOutsideReport, Field(discriminator="state")
]


class ReviewResolutionReport(_Record):
    schema_version: Literal["3"] = "3"
    results: tuple[ReviewResult, ...] = ()
    legacy_results: tuple[LegacyReviewResult, ...] = ()
    events: tuple[ReviewEvent, ...] = ()
