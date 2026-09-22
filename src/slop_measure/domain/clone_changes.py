"""Clone relationships derive from source-owned member continuity."""

from collections.abc import Mapping
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


class ChangedCloneMember(_Change):
    state: Literal[FindingChangeState.CHANGED] = FindingChangeState.CHANGED
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
    IntroducedCloneMember
    | RemovedCloneMember
    | PersistedCloneMember
    | ChangedCloneMember
    | UnresolvedCloneMembers,
    Field(discriminator="state"),
]


class CloneGroupChange(_Change):
    language: _Text
    cohort: Cohort
    normalization_version: _Text
    fingerprint: _Hash
    baseline_fingerprint: _Hash | None = None
    current_fingerprint: _Hash | None = None
    members: tuple[CloneMemberChange, ...]

    @model_validator(mode="before")
    @classmethod
    def legacy_fingerprints(cls, value: object) -> object:
        """Old reports describe one normalization on both observed sides."""
        if not isinstance(value, Mapping):
            return value
        fields = dict(value)
        for side in ("baseline", "current"):
            present = any(
                bool(item.get(side)) if isinstance(item, Mapping) else bool(getattr(item, side, ()))
                for item in fields.get("members", ())
            )
            fields.setdefault(f"{side}_fingerprint", fields.get("fingerprint") if present else None)
        return fields

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
    def modified(self) -> int:
        return sum(isinstance(item, ChangedCloneMember) for item in self.members)

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
        return (
            CloneGroupState.CHANGED
            if self.added or self.removed or self.modified
            else CloneGroupState.PERSISTED
        )

    @model_validator(mode="after")
    def fingerprint_ownership(self) -> Self:
        for side in ("baseline", "current"):
            if bool(getattr(self, side)) != (getattr(self, f"{side}_fingerprint") is not None):
                raise ValueError("clone side fingerprint requires observed side members")
        if self.fingerprint != (self.current_fingerprint or self.baseline_fingerprint):
            raise ValueError("clone fingerprint must name current or remaining baseline evidence")
        same = self.baseline_fingerprint == self.current_fingerprint
        if self.modified and same:
            raise ValueError("changed clone members require different fingerprints")
        if not same and any(isinstance(item, PersistedCloneMember) for item in self.members):
            raise ValueError("persisted clone members require the same fingerprint")
        return self

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
