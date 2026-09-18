"""Source-bound clone decisions, separate from evidence and metric values."""

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


class StaleCloneReview(_ReviewModel):
    state: Literal["stale"] = "stale"
    decision: CloneReviewDecision
    candidate_group_ids: Annotated[tuple[_Text, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        if len(set(self.candidate_group_ids)) != len(self.candidate_group_ids):
            raise ValueError("stale review candidate IDs must be unique")
        return self


class MissingCloneReview(_ReviewModel):
    state: Literal["missing"] = "missing"
    decision: CloneReviewDecision
    reason: Literal["evidence-absent-or-unavailable"] = "evidence-absent-or-unavailable"


CloneReviewResult = Annotated[
    CurrentCloneReview | StaleCloneReview | MissingCloneReview, Field(discriminator="state")
]


def clone_analysis_fingerprint(
    metric_version: str, normalization_version: str, min_statements: int, min_sloc: int
) -> str:
    """Bind a review only to settings and versions that define clone evidence."""
    payload = (metric_version, normalization_version, min_statements, min_sloc)
    return sha256(dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
