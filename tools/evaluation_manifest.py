"""Validate the finite, data-only public evaluation contract."""

import json
import math
import re
from pathlib import PureWindowsPath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

_Name = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")]
_Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
_Revision = Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
_FIRST_PRINTABLE = 32


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("id", check_fields=False)
    @classmethod
    def portable_id(cls, value: str) -> str:
        if PureWindowsPath(value).is_reserved():
            raise ValueError("IDs cannot be reserved Windows device names.")
        return value


def _unique(values: list[str], description: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"Duplicate {description}.")


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    _unique([key for key, _ in items], "JSON object keys")
    return dict(items)


def _invalid_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON value: {value}")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON numbers must be finite.")
    return number


def read_json(data: str | bytes) -> object:
    """Reject duplicate keys and non-JSON numeric constants before model parsing."""
    return json.loads(
        data, object_pairs_hook=_pairs, parse_constant=_invalid_constant, parse_float=_finite_float
    )


class SourceFile(Record):
    path: str
    sha256: _Hash

    @field_validator("path")
    @classmethod
    def safe_python_path(cls, value: str) -> str:
        segments = value.split("/")
        if (
            not value.endswith(".py")
            or any(character in value for character in '\\:<>"|?*')
            or any(ord(character) < _FIRST_PRINTABLE for character in value)
            or any(
                part.casefold() in {"", ".", "..", ".git"} or part.endswith((" ", "."))
                for part in segments
            )
            or any(PureWindowsPath(part).is_reserved() for part in segments)
        ):
            raise ValueError("Source path must be a portable relative Python file path.")
        return value


class Snapshot(Record):
    revision: _Revision
    files: tuple[SourceFile, ...]

    @model_validator(mode="after")
    def unique_files(self) -> Self:
        _unique([item.path.casefold() for item in self.files], "source paths")
        paths = {item.path.casefold() for item in self.files}
        if any(
            "/".join(item.path.casefold().split("/")[:index]) in paths
            for item in self.files
            for index in range(1, len(item.path.split("/")))
        ):
            raise ValueError("A source file cannot also be a directory.")
        return self


class Snapshots(Record):
    before: Snapshot
    after: Snapshot


class Check(Record):
    pointer: str
    equals: JsonValue

    @field_validator("pointer")
    @classmethod
    def valid_pointer(cls, value: str) -> str:
        if (value and not value.startswith("/")) or re.search(r"~(?![01])", value):
            raise ValueError("Check pointer must use RFC 6901 JSON Pointer syntax.")
        return value


class Run(Record):
    id: _Name
    checks: tuple[Check, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_checks(self) -> Self:
        _unique([check.pointer for check in self.checks], "check pointers")
        return self


class SnapshotRun(Run):
    kind: Literal["snapshot"]
    command: Literal["errors", "derived"]
    snapshot: Literal["before", "after"]


class ChangesRun(Run):
    kind: Literal["changes"]


EvaluationRun = Annotated[SnapshotRun | ChangesRun, Field(discriminator="kind")]


class Case(Record):
    id: _Name
    repository: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]
    label: Literal["supported-positive", "intentional", "coverage-gap", "stability"]
    rationale: Annotated[str, Field(min_length=1)]
    evidence_url: Annotated[str, Field(pattern=r"^https://[^\s]+$")]
    snapshots: Snapshots
    runs: tuple[EvaluationRun, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_runs(self) -> Self:
        _unique([run.id.casefold() for run in self.runs], "run IDs")
        if any(part in {".", ".."} for part in self.repository.split("/")):
            raise ValueError("Repository must identify a GitHub owner and repository.")
        return self


class Manifest(Record):
    schema_version: Literal[1]
    cases: tuple[Case, ...] = Field(min_length=1)

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("schema_version must be integer 1.")
        return value

    @model_validator(mode="after")
    def unique_cases(self) -> Self:
        _unique([case.id.casefold() for case in self.cases], "case IDs")
        return self
