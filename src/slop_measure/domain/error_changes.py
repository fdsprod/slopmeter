"""Exception fallback continuity retains detector evidence and assessment coverage."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from slop_measure.domain.error_review import ErrorFallbackFinding, ErrorFileResult
from slop_measure.domain.evidence import SourceSpan
from slop_measure.domain.reports import SourceSide
from slop_measure.domain.source import Cohort, ProjectPath

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class _ErrorChange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ErrorOccurrence(_ErrorChange):
    path: ProjectPath
    language: Literal["python"] = "python"
    cohort: Cohort
    source_sha256: _Hash
    symbol: _Text
    span: SourceSpan
    finding: ErrorFallbackFinding


class ErrorCoverage(_ErrorChange):
    source: SourceSide
    detail: ErrorFileResult


class IntroducedError(_ErrorChange):
    state: Literal["introduced"] = "introduced"
    current: ErrorOccurrence


class RemovedError(_ErrorChange):
    state: Literal["removed"] = "removed"
    baseline: ErrorOccurrence


class _PairedError(_ErrorChange):
    baseline: ErrorOccurrence
    current: ErrorOccurrence

    @model_validator(mode="after")
    def compatible_population(self) -> Self:
        if self.baseline.cohort != self.current.cohort:
            raise ValueError("error continuity requires the same source cohort")
        return self


class PersistedError(_PairedError):
    state: Literal["persisted"] = "persisted"


class ChangedError(_PairedError):
    state: Literal["changed"] = "changed"


class UnresolvedErrors(_ErrorChange):
    state: Literal["unresolved"] = "unresolved"
    baseline: tuple[ErrorOccurrence, ...] = ()
    current: tuple[ErrorOccurrence, ...] = ()
    reason: _Text

    @model_validator(mode="after")
    def require_evidence(self) -> Self:
        if not self.baseline and not self.current:
            raise ValueError("unresolved error matching requires candidate evidence")
        return self


ErrorChange = Annotated[
    IntroducedError | RemovedError | PersistedError | ChangedError | UnresolvedErrors,
    Field(discriminator="state"),
]
