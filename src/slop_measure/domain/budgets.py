"""Explicit review budgets with derived counts and incomplete outcomes."""

from collections.abc import Mapping
from enum import StrEnum
from json import dumps
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    StringConstraints,
    computed_field,
    model_validator,
)

from slop_measure.domain.evidence import SourceSpan
from slop_measure.domain.reports import ComparisonAnalysis, SourceSide
from slop_measure.domain.source import ProjectPath


class BudgetMetric(StrEnum):
    INTRODUCED_PATTERNS = "introduced-patterns"
    ADDED_CLONE_MEMBERS = "added-clone-members"
    INTRODUCED_ERRORS = "introduced-errors"


class BudgetState(StrEnum):
    PASSED = "pass"
    EXCEEDED = "exceeded"
    INCOMPLETE = "incomplete"


_Count = Annotated[int, Field(ge=0, strict=True)]
_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _BudgetRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="wrap")
    @classmethod
    def projections(cls, value: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        if not isinstance(value, Mapping):
            return handler(value)
        fields = dict(value)
        supplied = {key: fields.pop(key) for key in cls.model_computed_fields if key in fields}
        result = handler(fields)
        expected = result.model_dump(mode="json")
        if any(
            dumps(value, sort_keys=True) != dumps(expected[key], sort_keys=True)
            for key, value in supplied.items()
        ):
            raise ValueError("budget projections must match their evidence")
        return result


class BudgetLimit(_BudgetRecord):
    metric: BudgetMetric
    maximum: _Count


class BudgetPolicy(_BudgetRecord):
    limits: tuple[BudgetLimit, ...] = ()

    @model_validator(mode="after")
    def unique_metrics(self) -> Self:
        if len({item.metric for item in self.limits}) != len(self.limits):
            raise ValueError("budget metrics must be unique")
        return self


class BudgetEvidence(_BudgetRecord):
    path: ProjectPath
    span: SourceSpan
    kind: _Text


class _IncompleteDetail(_BudgetRecord):
    code: Literal[
        "analysis-limitation",
        "analysis-error",
        "unresolved-pattern",
        "unresolved-clone",
        "unresolved-error",
        "unsupported-handler",
    ]
    message: _Text


class SourceBudgetBlocker(_IncompleteDetail):
    scope: Literal["source"] = "source"
    side: SourceSide
    path: ProjectPath
    span: SourceSpan | None = None


class PopulationBudgetBlocker(_IncompleteDetail):
    scope: Literal["population"] = "population"
    side: SourceSide | None = None
    path: None = None
    span: None = None


BudgetBlocker = Annotated[
    SourceBudgetBlocker | PopulationBudgetBlocker, Field(discriminator="scope")
]


class BudgetCheck(BudgetLimit):
    evidence: tuple[BudgetEvidence, ...] = ()
    incomplete_reasons: tuple[_Text, ...] = ()
    incomplete_details: tuple[BudgetBlocker, ...] = ()

    @model_validator(mode="after")
    def compatible_messages(self) -> Self:
        if self.incomplete_details and set(self.incomplete_reasons) != {
            item.message for item in self.incomplete_details
        }:
            raise ValueError("budget reason messages must match their structured details")
        return self

    @computed_field
    @property
    def observed(self) -> int:
        return len(self.evidence)

    @computed_field
    @property
    def exceeded(self) -> bool:
        return self.observed > self.maximum


class BudgetReport(_BudgetRecord):
    analysis: ComparisonAnalysis
    checks: tuple[BudgetCheck, ...] = ()

    @computed_field
    @property
    def state(self) -> BudgetState:
        if any(check.incomplete_reasons for check in self.checks):
            return BudgetState.INCOMPLETE
        return (
            BudgetState.EXCEEDED
            if any(check.exceeded for check in self.checks)
            else BudgetState.PASSED
        )

    @model_validator(mode="after")
    def unique_metrics(self) -> Self:
        if len({item.metric for item in self.checks}) != len(self.checks):
            raise ValueError("budget results must have unique metrics")
        return self
