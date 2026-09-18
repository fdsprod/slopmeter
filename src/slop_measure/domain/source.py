"""Source locations, identities, and immutable documents."""

from __future__ import annotations

from enum import StrEnum
from hashlib import sha256
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StringConstraints,
    computed_field,
    field_validator,
)


class Cohort(StrEnum):
    """A source population that receives an independent score."""

    PRODUCTION = "production"
    TEST = "test"


class ProjectPath(RootModel[str]):
    """A normalized path relative to the analyzed project root."""

    model_config = ConfigDict(frozen=True)

    @field_validator("root", mode="before")
    @classmethod
    def validate_root(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("project path must be a string")
        if not value or "\0" in value:
            raise ValueError("project path must be nonempty and cannot contain NUL")

        windows_path = PureWindowsPath(value)
        posix_path = PurePosixPath(value)
        if windows_path.drive or windows_path.is_absolute() or posix_path.is_absolute():
            raise ValueError("project path must be relative")

        normalized = value.replace("\\", "/")
        segments = normalized.split("/")
        if any(segment in {"", ".", ".."} for segment in segments):
            raise ValueError("project path cannot contain empty, dot, or parent segments")
        return "/".join(segments)


_NonemptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _SourceLocation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    root: Path


class DirectorySourceReference(_SourceLocation):
    """A request to read the current state of one directory."""

    kind: Literal["directory"] = "directory"


class GitSourceReference(_SourceLocation):
    """A request to resolve and read one Git revision."""

    kind: Literal["git"] = "git"
    revision: _NonemptyText


SourceReference = Annotated[
    DirectorySourceReference | GitSourceReference,
    Field(discriminator="kind"),
]


class DirectorySourceIdentity(_SourceLocation):
    """The resolved identity of one directory snapshot."""

    kind: Literal["directory"] = "directory"


class GitSourceIdentity(_SourceLocation):
    """The resolved, stable identity of one Git snapshot."""

    kind: Literal["git"] = "git"
    revision: _NonemptyText


SourceIdentity = Annotated[
    DirectorySourceIdentity | GitSourceIdentity,
    Field(discriminator="kind"),
]


class SourceDocument(BaseModel):
    """Exact source bytes and their normalized project identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: ProjectPath
    content: bytes
    language: _NonemptyText
    cohort: Cohort

    @computed_field
    @property
    def content_hash(self) -> str:
        """Return the SHA-256 identity derived from the exact source bytes."""
        return sha256(self.content).hexdigest()
