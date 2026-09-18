"""Metric scopes and explicit measured or unavailable results."""

from enum import StrEnum
from math import isclose
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StringConstraints, model_validator

from slop_measure.domain.source import Cohort, ProjectPath

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _MetricModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProjectMetricScope(_MetricModel):
    """A complete project population."""

    kind: Literal["project"] = "project"
    cohort: Cohort


class FileMetricScope(_MetricModel):
    """One source file within its population."""

    kind: Literal["file"] = "file"
    path: ProjectPath
    cohort: Cohort


MetricScope = Annotated[ProjectMetricScope | FileMetricScope, Field(discriminator="kind")]


class MetricUnit(StrEnum):
    """Units supported by raw metric values."""

    RATIO = "ratio"
    LINES = "lines"


class MetricMeasurement(_MetricModel):
    """An immutable projection of a metric calculation and its raw inputs."""

    numerator: FiniteFloat
    denominator: FiniteFloat
    value: FiniteFloat
    unit: MetricUnit

    @model_validator(mode="after")
    def validate_ratio(self) -> Self:
        if self.unit is MetricUnit.RATIO:
            if self.denominator <= 0:
                raise ValueError("a measured ratio requires a positive denominator")
            if not isclose(self.value, self.numerator / self.denominator):
                raise ValueError("ratio value must match numerator divided by denominator")
        return self


class CalibratedScore(_MetricModel):
    """Points produced by a named calibration profile."""

    points: Annotated[FiniteFloat, Field(ge=0, le=100)]
    profile_id: _Text


class UnavailableReason(StrEnum):
    """Stable reasons why a metric or calibration cannot be supplied."""

    NO_BASELINE = "no-baseline"
    NO_SOURCE_LINES = "no-source-lines"
    NO_FUNCTIONS = "no-functions"
    UNSUPPORTED_LANGUAGE = "unsupported-language"
    PARSE_FAILED = "parse-failed"
    ANALYZER_FAILED = "analyzer-failed"
    CALIBRATION_MISSING = "calibration-missing"
    CALIBRATION_INCOMPATIBLE = "calibration-incompatible"


class MeasuredMetric(_MetricModel):
    """A raw metric, including a valid zero, with optional calibration."""

    state: Literal["measured"] = "measured"
    metric_id: _Text
    scope: MetricScope
    raw: MetricMeasurement
    score: CalibratedScore | None = None


class UnavailableMetric(_MetricModel):
    """An unavailable metric without a fabricated raw value or score."""

    state: Literal["unavailable"] = "unavailable"
    metric_id: _Text
    scope: MetricScope
    reason: UnavailableReason
    diagnostic_id: _Text | None = None


MetricResult = Annotated[MeasuredMetric | UnavailableMetric, Field(discriminator="state")]
