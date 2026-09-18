"""Configured ownership context without changes to clone evidence or scoring."""

from collections.abc import Mapping
from hashlib import sha256
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

from slop_measure.domain.source import ProjectPath

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _BoundaryModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BoundaryDeclaration(_BoundaryModel):
    """A user-named project-relative prefix, without inferred architecture."""

    name: _Text
    prefix: ProjectPath

    @model_validator(mode="after")
    def validate_prefix(self) -> Self:
        if any(character in self.prefix.root for character in "*?[]"):
            raise ValueError("boundary prefixes cannot contain glob syntax")
        return self


class BoundaryAssignment(_BoundaryModel):
    """The declared boundary for one clone member file, if configured."""

    path: ProjectPath
    boundary: _Text | None


class CloneBoundaryContext(_BoundaryModel):
    """Owned assignments with a relation derived from complete membership."""

    members: Annotated[tuple[BoundaryAssignment, ...], Field(min_length=1)]
    policy_fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

    @computed_field
    @property
    def relation(self) -> Literal["within-boundary", "cross-boundary", "unknown"]:
        labels = {member.boundary for member in self.members}
        if None in labels:
            return "unknown"
        return "within-boundary" if len(labels) == 1 else "cross-boundary"

    @model_validator(mode="wrap")
    @classmethod
    def validate_projection(cls, value: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        if not isinstance(value, Mapping):
            return handler(value)
        fields = dict(value)
        relation = fields.pop("relation", None)
        result = handler(fields)
        if "relation" in value and relation != result.relation:
            raise ValueError("boundary relation must match its member assignments")
        return result

    @model_validator(mode="after")
    def validate_members(self) -> Self:
        if len({member.path.root for member in self.members}) != len(self.members):
            raise ValueError("boundary context requires unique member paths")
        return self


def clone_boundary_context(
    paths: tuple[ProjectPath, ...], declarations: tuple[BoundaryDeclaration, ...]
) -> CloneBoundaryContext:
    """Apply longest component prefixes and fingerprint the canonical declaration set."""
    policy = sorted((item.name, item.prefix.root) for item in declarations)
    fingerprint = sha256(
        dumps(policy, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()
    ordered = sorted(declarations, key=lambda item: (-len(item.prefix.root.split("/")), item.name))
    members = tuple(
        BoundaryAssignment(
            path=ProjectPath(path),
            boundary=next(
                (
                    item.name
                    for item in ordered
                    if path == item.prefix.root or path.startswith(item.prefix.root + "/")
                ),
                None,
            ),
        )
        for path in sorted({path.root for path in paths})
    )
    return CloneBoundaryContext(members=members, policy_fingerprint=fingerprint)
