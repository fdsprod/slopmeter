"""Source-bound clone decisions, separate from evidence and metric values."""

from collections.abc import Mapping
from enum import StrEnum
from hashlib import sha256
from json import dumps
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from slop_measure.domain.evidence import CloneGroup
from slop_measure.domain.source import ProjectPath

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class _ReviewModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReviewDisposition(StrEnum):
    ACTIONABLE = "actionable"
    DEFER = "defer"
    NO_CHANGE = "no-change"


class SourceHash(_ReviewModel):
    path: ProjectPath
    sha256: _Hash


class CloneReviewAnchor(_ReviewModel):
    detail: CloneGroup
    source_hashes: tuple[SourceHash, ...]
    policy_fingerprint: _Hash
    analysis_fingerprint: _Hash

    @model_validator(mode="after")
    def validate_sources(self) -> Self:
        expected = sorted({member.path.root for member in self.detail.members})
        if [item.path.root for item in self.source_hashes] != expected:
            raise ValueError("review source hashes must match sorted unique clone member paths")
        return self


class CloneReviewDecision(_ReviewModel):
    id: _Text
    anchor: CloneReviewAnchor
    disposition: ReviewDisposition
    reason: _Text
    next_step: str = ""


class ReviewStore(_ReviewModel):
    schema_version: Literal["1"] = "1"
    decisions: tuple[CloneReviewDecision, ...] = ()

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        if len({item.id for item in self.decisions}) != len(self.decisions):
            raise ValueError("review decisions require unique IDs")
        return self


class CurrentCloneReview(_ReviewModel):
    state: Literal["current"] = "current"
    decision: CloneReviewDecision
    group_id: _Text


class ReviewSourceChanged(_ReviewModel):
    kind: Literal["source-changed"] = "source-changed"
    path: ProjectPath
    previous_sha256: _Hash
    current_sha256: _Hash


class ReviewSourceUnavailable(_ReviewModel):
    kind: Literal["source-unavailable"] = "source-unavailable"
    path: ProjectPath


class ReviewCloneEvidenceChanged(_ReviewModel):
    kind: Literal["clone-evidence-changed"] = "clone-evidence-changed"
    fields: Annotated[tuple[_Text, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        if len(set(self.fields)) != len(self.fields) or any(
            name not in CloneGroup.model_fields for name in self.fields
        ):
            raise ValueError("changed clone fields must be unique model field names")
        return self


class ReviewBoundaryPolicyChanged(_ReviewModel):
    kind: Literal["boundary-policy-changed"] = "boundary-policy-changed"
    previous_fingerprint: _Hash
    current_fingerprint: _Hash


class ReviewAnalysisDefinitionChanged(_ReviewModel):
    kind: Literal["analysis-definition-changed"] = "analysis-definition-changed"
    previous_fingerprint: _Hash
    current_fingerprint: _Hash


class ReviewAnalysisUnavailable(_ReviewModel):
    kind: Literal["analysis-unavailable"] = "analysis-unavailable"


CloneReviewCause = Annotated[
    ReviewSourceChanged
    | ReviewSourceUnavailable
    | ReviewCloneEvidenceChanged
    | ReviewBoundaryPolicyChanged
    | ReviewAnalysisDefinitionChanged
    | ReviewAnalysisUnavailable,
    Field(discriminator="kind"),
]


class CloneReviewChange(_ReviewModel):
    group_id: _Text
    causes: Annotated[tuple[CloneReviewCause, ...], Field(min_length=1)]


class StaleCloneReview(_ReviewModel):
    state: Literal["stale"] = "stale"
    decision: CloneReviewDecision
    candidate_group_ids: Annotated[tuple[_Text, ...], Field(min_length=1)]
    changes: tuple[CloneReviewChange, ...] = Field(default=(), exclude_if=lambda value: not value)

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        if len(set(self.candidate_group_ids)) != len(self.candidate_group_ids):
            raise ValueError("stale review candidate IDs must be unique")
        if self.changes and (
            len(self.changes) != len(self.candidate_group_ids)
            or {item.group_id for item in self.changes} != set(self.candidate_group_ids)
        ):
            raise ValueError("stale changes must cover every candidate exactly once")
        return self


class MissingCloneReview(_ReviewModel):
    state: Literal["missing"] = "missing"
    decision: CloneReviewDecision
    reason: Literal["evidence-absent-or-unavailable"] = "evidence-absent-or-unavailable"


CloneReviewResult = Annotated[
    CurrentCloneReview | StaleCloneReview | MissingCloneReview, Field(discriminator="state")
]


def clone_review_causes(
    previous: CloneReviewAnchor,
    detail: CloneGroup,
    source_hashes: Mapping[str, str | None],
    policy_fingerprint: str,
    analysis_fingerprint: str | None,
) -> tuple[CloneReviewCause, ...]:
    """Describe only differences established by the saved anchor and current evidence."""
    causes: list[CloneReviewCause] = []
    for source in previous.source_hashes:
        current = source_hashes.get(source.path.root)
        if current is None:
            causes.append(ReviewSourceUnavailable(path=source.path))
        elif current != source.sha256:
            causes.append(
                ReviewSourceChanged(
                    path=source.path, previous_sha256=source.sha256, current_sha256=current
                )
            )
    fields = tuple(
        name
        for name in CloneGroup.model_fields
        if getattr(previous.detail, name) != getattr(detail, name)
    )
    if fields:
        causes.append(ReviewCloneEvidenceChanged(fields=fields))
    if previous.policy_fingerprint != policy_fingerprint:
        causes.append(
            ReviewBoundaryPolicyChanged(
                previous_fingerprint=previous.policy_fingerprint,
                current_fingerprint=policy_fingerprint,
            )
        )
    if analysis_fingerprint is None:
        causes.append(ReviewAnalysisUnavailable())
    elif previous.analysis_fingerprint != analysis_fingerprint:
        causes.append(
            ReviewAnalysisDefinitionChanged(
                previous_fingerprint=previous.analysis_fingerprint,
                current_fingerprint=analysis_fingerprint,
            )
        )
    return tuple(causes)


def clone_analysis_fingerprint(
    metric_version: str, normalization_version: str, min_statements: int, min_sloc: int
) -> str:
    """Bind a review only to settings and versions that define clone evidence."""
    payload = (metric_version, normalization_version, min_statements, min_sloc)
    return sha256(dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
