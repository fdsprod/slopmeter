"""Raw state comparisons are syntax evidence, not inferred receiver types."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from slop_measure.domain.change_states import FindingChangeState
from slop_measure.domain.evidence import SourceSpan
from slop_measure.domain.source import Cohort, ProjectPath

_Text = Annotated[str, StringConstraints(min_length=1)]
_Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class StateOperator(StrEnum):
    EQ = "eq"
    NE = "ne"
    IN = "in"
    NOT_IN = "not-in"


class DispatchContext(StrEnum):
    ASSERTION = "assertion"
    CONDITION = "condition"


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class StateDispatchOccurrence(_Record):
    path: ProjectPath
    span: SourceSpan
    start_column: Annotated[int, Field(ge=0, strict=True)]
    end_column: Annotated[int, Field(ge=0, strict=True)]
    source_sha256: _Hash
    language: Literal["python"] = "python"
    cohort: Cohort
    symbol: str
    subject: _Text
    operator: StateOperator
    values: Annotated[tuple[str, ...], Field(min_length=1)]
    context: DispatchContext


class IntroducedStateDispatch(_Record):
    state: Literal[FindingChangeState.INTRODUCED] = FindingChangeState.INTRODUCED
    current: StateDispatchOccurrence


class RemovedStateDispatch(_Record):
    state: Literal[FindingChangeState.REMOVED] = FindingChangeState.REMOVED
    baseline: StateDispatchOccurrence


class _PairedDispatch(_Record):
    baseline: StateDispatchOccurrence
    current: StateDispatchOccurrence

    @model_validator(mode="after")
    def same_population(self) -> Self:
        if self.baseline.cohort != self.current.cohort:
            raise ValueError("state comparison continuity requires the same cohort")
        return self


class PersistedStateDispatch(_PairedDispatch):
    state: Literal[FindingChangeState.PERSISTED] = FindingChangeState.PERSISTED


class ChangedStateDispatch(_PairedDispatch):
    state: Literal[FindingChangeState.CHANGED] = FindingChangeState.CHANGED


class UnresolvedStateDispatch(_Record):
    state: Literal[FindingChangeState.UNRESOLVED] = FindingChangeState.UNRESOLVED
    baseline: tuple[StateDispatchOccurrence, ...] = ()
    current: tuple[StateDispatchOccurrence, ...] = ()
    reason: _Text

    @model_validator(mode="after")
    def has_candidates(self) -> Self:
        if not self.baseline and not self.current:
            raise ValueError("unresolved state comparisons require observed candidates")
        return self


StateDispatchChange = Annotated[
    IntroducedStateDispatch
    | RemovedStateDispatch
    | PersistedStateDispatch
    | ChangedStateDispatch
    | UnresolvedStateDispatch,
    Field(discriminator="state"),
]
