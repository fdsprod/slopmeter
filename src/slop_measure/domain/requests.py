"""Separate snapshot and comparison requests with shared resolved settings."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from slop_measure.config import AnalysisConfig
from slop_measure.domain.source import SourceReference


class SnapshotRequest(BaseModel):
    """Analyze one source state without a baseline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["snapshot"] = "snapshot"
    target: SourceReference
    config: AnalysisConfig


class ComparisonRequest(BaseModel):
    """Analyze two source states under the same configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["comparison"] = "comparison"
    baseline: SourceReference
    current: SourceReference
    config: AnalysisConfig


AnalysisRequest = Annotated[SnapshotRequest | ComparisonRequest, Field(discriminator="kind")]
