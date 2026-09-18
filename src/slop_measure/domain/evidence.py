"""Immutable, language-neutral facts returned by analyzers."""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    model_validator,
)

from slop_measure.domain.source import Cohort, ProjectPath

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_Count = Annotated[int, Field(ge=0, strict=True)]
_Line = Annotated[int, Field(ge=1, strict=True)]


class _Evidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DiagnosticSeverity(StrEnum):
    """The severity of an analysis notice."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class SourceSpan(_Evidence):
    """An inclusive range of one-based physical source lines."""

    start_line: _Line
    end_line: _Line

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("source span end must not precede its start")
        return self


class Diagnostic(_Evidence):
    """A stable analysis notice with an optional source location."""

    severity: DiagnosticSeverity
    code: _Text
    message: _Text
    path: ProjectPath | None = None
    span: SourceSpan | None = None

    @model_validator(mode="after")
    def validate_location(self) -> Self:
        if self.span is not None and self.path is None:
            raise ValueError("a diagnostic source span requires a path")
        return self


class CoverageState(StrEnum):
    """The disposition of an inventory population."""

    SCORED = "scored"
    EXCLUDED = "excluded"
    UNSUPPORTED = "unsupported"


class Coverage(_Evidence):
    """An immutable projection of inventory totals for one population."""

    state: CoverageState
    cohort: Cohort
    language: _Text
    file_count: _Count
    sloc: _Count
    reason: _Text | None = None


class ParseState(StrEnum):
    """The outcome of parsing one source file."""

    PARSED = "parsed"
    FAILED = "failed"


class FileEvidence(_Evidence):
    """Exact source-line identities and a checked count projection."""

    path: ProjectPath
    language: _Text
    cohort: Cohort
    sloc: _Count
    sloc_lines: tuple[_Line, ...]
    parse_state: ParseState

    @model_validator(mode="after")
    def validate_lines(self) -> Self:
        if self.sloc_lines != tuple(sorted(set(self.sloc_lines))):
            raise ValueError("SLOC lines must be sorted and unique")
        if self.sloc != len(self.sloc_lines):
            raise ValueError("SLOC count must match the exact source lines")
        return self


class EvidenceCapability(StrEnum):
    """An evidence family supported by a language adapter."""

    FILES = "files"
    PATTERNS = "patterns"
    FUNCTIONS = "functions"
    CLONES = "clones"


class LanguageEvidence(_Evidence):
    """Owned facts from one language adapter, without parser objects."""

    language: _Text
    capabilities: frozenset[EvidenceCapability]
    files: tuple[FileEvidence, ...]
    # Later metric slices replace empty-only collections with their owned models.
    patterns: tuple[()] = ()
    functions: tuple[()] = ()
    clone_candidates: tuple[()] = ()
    diagnostics: tuple[Diagnostic, ...] = ()

    @field_serializer("capabilities", when_used="json")
    def serialize_capabilities(self, values: frozenset[EvidenceCapability]) -> list[str]:
        return sorted(capability.value for capability in values)

    @model_validator(mode="after")
    def validate_files(self) -> Self:
        paths = [file.path.root for file in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("language evidence cannot contain duplicate file paths")
        if any(file.language != self.language for file in self.files):
            raise ValueError("file language must match the adapter language")
        return self
