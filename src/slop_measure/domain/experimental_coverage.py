"""Derive experimental coverage from owned outcomes, never imported counters."""

from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ModelWrapValidatorHandler, model_validator

_Count = Annotated[int, Field(ge=0, strict=True)]
CoverageUnit = Literal["class-declarations", "match-handlers", "functions"]


class UnresolvedReasonCount(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str
    count: Annotated[int, Field(gt=0, strict=True)]


class ExperimentalCoverage(BaseModel):
    """Read-only projection; the enclosing report validates it against its evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit: CoverageUnit
    files_analyzed: _Count
    files_failed: _Count
    encountered: _Count
    assessed: _Count
    unresolved: _Count
    findings: _Count
    unresolved_reasons: tuple[UnresolvedReasonCount, ...]


def summarize_coverage(
    *,
    unit: CoverageUnit,
    file_states: Iterable[Literal["analyzed", "failed"]],
    assessed: int,
    findings: int,
    unresolved_reasons: Iterable[str],
) -> ExperimentalCoverage:
    files = Counter(file_states)
    reasons = Counter(unresolved_reasons)
    unresolved = reasons.total()
    return ExperimentalCoverage(
        unit=unit,
        files_analyzed=files["analyzed"],
        files_failed=files["failed"],
        encountered=assessed + unresolved,
        assessed=assessed,
        unresolved=unresolved,
        findings=findings,
        unresolved_reasons=tuple(
            UnresolvedReasonCount(reason=reason, count=count)
            for reason, count in sorted(reasons.items())
        ),
    )


class ExperimentalReport(BaseModel, ABC):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @property
    @abstractmethod
    def summary(self) -> ExperimentalCoverage:
        """Project coverage from the concrete report's subject outcomes."""

    @model_validator(mode="wrap")
    @classmethod
    def validate_summary(cls, value: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        if not isinstance(value, Mapping) or "summary" not in value:
            return handler(value)
        fields = dict(value)
        supplied = ExperimentalCoverage.model_validate(fields.pop("summary"))
        result = handler(fields)
        if supplied != result.summary:
            raise ValueError("experimental summary must match the detailed file outcomes")
        return result
