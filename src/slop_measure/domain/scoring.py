"""Immutable calibration populations, policies, and score contribution facts."""

from collections.abc import Mapping
from decimal import Decimal
from math import isclose
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    ModelWrapValidatorHandler,
    StringConstraints,
    computed_field,
    field_serializer,
    model_validator,
)

from slop_measure.config import AnalysisConfig
from slop_measure.domain.metrics import MetricVersion
from slop_measure.domain.source import Cohort

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_PositiveInt = Annotated[int, Field(gt=0, strict=True)]
_Ratio = Annotated[FiniteFloat, Field(ge=0, le=1)]
_Points = Annotated[FiniteFloat, Field(ge=0, le=100)]
ScoreInput = Literal["verbosity.combined", "m4.erosion"]
_REQUIRED_VERSIONS = frozenset(
    {"m2.pattern-verbosity", "m3.clone-verbosity", "verbosity.combined", "m4.erosion"}
)


class _CalibrationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _unique(values: tuple[object, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate calibration {label}")


class CalibrationSettings(_CalibrationModel):
    """Metric options that must match the reference observations."""

    clone_min_statements: _PositiveInt = 2
    clone_min_sloc: _PositiveInt = 6
    complexity_threshold: _PositiveInt = 10
    enabled_rules: frozenset[_Text] = frozenset()
    disabled_rules: frozenset[_Text] = frozenset()

    @classmethod
    def from_config(cls, config: AnalysisConfig) -> Self:
        """Project only metric-defining options from the resolved scan settings."""
        return cls.model_validate(config.model_dump(include=set(cls.model_fields)))

    @model_validator(mode="after")
    def validate_rules(self) -> Self:
        if self.enabled_rules & self.disabled_rules:
            raise ValueError("calibration rules cannot be both enabled and disabled")
        return self

    @field_serializer("enabled_rules", "disabled_rules", when_used="json")
    def serialize_rules(self, values: frozenset[str]) -> list[str]:
        return sorted(values)


class MetricDistribution(_CalibrationModel):
    """Sorted raw observations from complete model samples."""

    metric_id: Literal[
        "verbosity.combined", "m4.erosion", "m2.pattern-verbosity", "m3.clone-verbosity"
    ]
    values: Annotated[tuple[_Ratio, ...], Field(min_length=1)]

    @computed_field
    @property
    def sample_count(self) -> int:
        return len(self.values)

    @model_validator(mode="wrap")
    @classmethod
    def validate_projection(cls, value: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        if not isinstance(value, Mapping):
            return handler(value)
        fields = dict(value)
        count = fields.pop("sample_count", None)
        result = handler(fields)
        if "sample_count" in value and (isinstance(count, bool) or count != result.sample_count):
            raise ValueError("distribution sample count must match its observations")
        return result

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if tuple(sorted(self.values)) != self.values:
            raise ValueError("reference observations must be sorted")
        return self


class MetricWeight(_CalibrationModel):
    metric_id: ScoreInput
    weight: Annotated[FiniteFloat, Field(gt=0, le=1)]


class ScoreModel(_CalibrationModel):
    """An explicit input set without missing-metric weight redistribution."""

    model_id: _Text
    eligibility: Literal["all-metrics", "no-functions"]
    inputs: Annotated[tuple[MetricWeight, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_inputs(self) -> Self:
        keys = tuple(item.metric_id for item in self.inputs)
        _unique(keys, "model input")
        required = {"verbosity.combined"}
        if self.eligibility == "all-metrics":
            required.add("m4.erosion")
        if set(keys) != required:
            raise ValueError("score model inputs must match its eligibility")
        if not isclose(sum(item.weight for item in self.inputs), 1, rel_tol=0, abs_tol=1e-12):
            raise ValueError("score model weights must sum to one")
        return self


class _Population(_CalibrationModel):
    cohort: Cohort
    model_id: _Text
    distributions: Annotated[tuple[MetricDistribution, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_distributions(self) -> Self:
        _unique(tuple(item.metric_id for item in self.distributions), "distribution")
        if len({item.sample_count for item in self.distributions}) != 1:
            raise ValueError("model distributions must describe the same complete samples")
        return self


class FilePopulation(_Population):
    """File observations in an inclusive-lower, exclusive-upper SLOC band."""

    kind: Literal["file"] = "file"
    min_sloc: _PositiveInt
    max_sloc: _PositiveInt | None = None

    @model_validator(mode="after")
    def validate_band(self) -> Self:
        if self.max_sloc is not None and self.max_sloc <= self.min_sloc:
            raise ValueError("file population requires a nonempty SLOC band")
        return self


class ProjectPopulation(_Population):
    """One observation per complete project, independent of its file count."""

    kind: Literal["project"] = "project"


ReferencePopulation = Annotated[FilePopulation | ProjectPopulation, Field(discriminator="kind")]


class ScoreBand(_CalibrationModel):
    """A profile-owned label beginning at the inclusive lower point value."""

    label: _Text
    lower: Annotated[FiniteFloat, Field(ge=0, lt=100)]


class ScoreContribution(_CalibrationModel):
    """The raw input, percentile, weight, and allocated displayed points."""

    metric_id: ScoreInput
    raw_value: _Ratio
    percentile: _Points
    weight: Annotated[FiniteFloat, Field(gt=0, le=1)]
    points: _Points

    @model_validator(mode="after")
    def validate_precision(self) -> Self:
        points = Decimal(str(self.points))
        if points != points.quantize(Decimal("0.1")):
            raise ValueError("contribution points must have at most one decimal place")
        return self


def _validate_population_ranges(populations: tuple[ReferencePopulation, ...]) -> None:
    for index, first in enumerate(populations):
        for second in populations[index + 1 :]:
            if (first.kind, first.cohort, first.model_id) != (
                second.kind,
                second.cohort,
                second.model_id,
            ):
                continue
            if isinstance(first, ProjectPopulation) or isinstance(second, ProjectPopulation):
                raise ValueError("duplicate project reference population")
            if first.min_sloc < (second.max_sloc or float("inf")) and second.min_sloc < (
                first.max_sloc or float("inf")
            ):
                raise ValueError("file reference SLOC bands cannot overlap")


class CalibrationProfile(_CalibrationModel):
    """A reproducible reference population and its versioned scoring policy."""

    schema_version: Literal["1.0"] = "1.0"
    profile_id: _Text
    language: _Text
    rule_set_version: _Text
    clone_normalization_version: _Text
    metric_versions: tuple[MetricVersion, ...]
    settings: CalibrationSettings
    corpus_manifest_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    percentile_policy: Literal["strictly-below-zero-floor"] = "strictly-below-zero-floor"
    populations: Annotated[tuple[ReferencePopulation, ...], Field(min_length=1)]
    score_models: Annotated[tuple[ScoreModel, ...], Field(min_length=1)]
    bands: Annotated[tuple[ScoreBand, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_models(self) -> Self:
        _unique(tuple(item.model_id for item in self.score_models), "model ID")
        _unique(tuple(item.eligibility for item in self.score_models), "model eligibility")
        versions = tuple(item.metric_id for item in self.metric_versions)
        _unique(versions, "metric version")
        if set(versions) != _REQUIRED_VERSIONS:
            raise ValueError("calibration requires the complete snapshot metric version set")
        models = {model.model_id: model for model in self.score_models}
        for population in self.populations:
            model = models.get(population.model_id)
            if model is None:
                raise ValueError("reference population has no score model")
            if not {item.metric_id for item in model.inputs} <= {
                item.metric_id for item in population.distributions
            }:
                raise ValueError("reference distributions must include model inputs")
        _validate_population_ranges(self.populations)
        return self

    @model_validator(mode="after")
    def validate_bands(self) -> Self:
        lowers = tuple(band.lower for band in self.bands)
        if lowers[0] != 0 or lowers != tuple(sorted(set(lowers))):
            raise ValueError("score bands must start at zero and increase")
        _unique(tuple(band.label for band in self.bands), "band label")
        return self
