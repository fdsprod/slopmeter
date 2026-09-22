"""Clone relationships derive from source-owned member continuity."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, computed_field, model_validator

from slop_measure.domain.change_states import FindingChangeState
from slop_measure.domain.changes import _Change
from slop_measure.domain.evidence import CloneMember
from slop_measure.domain.source import Cohort

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
_MIN_GROUP_MEMBERS = 2


class CloneGroupState(StrEnum):
    INTRODUCED = "introduced"
    REMOVED = "removed"
    PERSISTED = "persisted"
    CHANGED = "changed"
    EXPANDED = "expanded"
    CONTRACTED = "contracted"
    UNRESOLVED = "unresolved"


class CloneOccurrence(_Change):
    member: CloneMember
    source_sha256: _Hash


class IntroducedCloneMember(_Change):
    state: Literal[FindingChangeState.INTRODUCED] = FindingChangeState.INTRODUCED
    current: CloneOccurrence


class RemovedCloneMember(_Change):
    state: Literal[FindingChangeState.REMOVED] = FindingChangeState.REMOVED
    baseline: CloneOccurrence


class PersistedCloneMember(_Change):
    state: Literal[FindingChangeState.PERSISTED] = FindingChangeState.PERSISTED
    baseline: CloneOccurrence
    current: CloneOccurrence


class UnresolvedCloneMembers(_Change):
    state: Literal[FindingChangeState.UNRESOLVED] = FindingChangeState.UNRESOLVED
    baseline: tuple[CloneOccurrence, ...] = ()
    current: tuple[CloneOccurrence, ...] = ()
    reason: _Text

    @model_validator(mode="after")
    def has_candidates(self) -> Self:
        if not self.baseline and not self.current:
            raise ValueError("unresolved clones require observed members")
        return self


CloneMemberChange = Annotated[
    IntroducedCloneMember | RemovedCloneMember | PersistedCloneMember | UnresolvedCloneMembers,
    Field(discriminator="state"),
]


class CloneGroupChange(_Change):
    language: _Text
    cohort: Cohort
    normalization_version: _Text
    fingerprint: _Hash
    members: tuple[CloneMemberChange, ...]

    def _side(self, side: str) -> tuple[CloneOccurrence, ...]:
        result = []
        for item in self.members:
            value = getattr(item, side, ())
            result.extend(value if isinstance(value, tuple) else (value,))
        return tuple(result)

    @computed_field
    @property
    def baseline(self) -> tuple[CloneOccurrence, ...]:
        return self._side("baseline")

    @computed_field
    @property
    def current(self) -> tuple[CloneOccurrence, ...]:
        return self._side("current")

    @computed_field
    @property
    def added(self) -> int:
        return sum(isinstance(item, IntroducedCloneMember) for item in self.members)

    @computed_field
    @property
    def removed(self) -> int:
        return sum(isinstance(item, RemovedCloneMember) for item in self.members)

    @computed_field
    @property
    def state(self) -> CloneGroupState:
        if any(isinstance(item, UnresolvedCloneMembers) for item in self.members):
            return CloneGroupState.UNRESOLVED
        before, after = len(self.baseline), len(self.current)
        if before < _MIN_GROUP_MEMBERS:
            return CloneGroupState.INTRODUCED
        if after < _MIN_GROUP_MEMBERS:
            return CloneGroupState.REMOVED
        if after != before:
            return CloneGroupState.EXPANDED if after > before else CloneGroupState.CONTRACTED
        return CloneGroupState.CHANGED if self.added or self.removed else CloneGroupState.PERSISTED

    @model_validator(mode="after")
    def ownership(self) -> Self:
        if max(len(self.baseline), len(self.current)) < _MIN_GROUP_MEMBERS:
            raise ValueError("clone changes require a group on at least one side")
        for occurrences in (self.baseline, self.current):
            keys = [
                (x.member.path.root, x.member.span.start_line, x.member.span.end_line)
                for x in occurrences
            ]
            if len(keys) != len(set(keys)):
                raise ValueError("clone members require unique ownership on each side")
        return self
