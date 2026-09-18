"""Immutable, language-neutral facts returned by analyzers."""

from collections.abc import Mapping
from enum import StrEnum
from math import sqrt
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    StringConstraints,
    computed_field,
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


class FunctionEvidence(_Evidence):
    """One callable's owned complexity and exact physical source lines."""

    path: ProjectPath
    qualified_name: _Text
    span: SourceSpan
    cyclomatic_complexity: Annotated[int, Field(ge=1, strict=True)]
    sloc_lines: tuple[_Line, ...]

    @computed_field
    @property
    def sloc(self) -> int:
        """Derive size from the authoritative source-line identities."""
        return len(self.sloc_lines)

    @computed_field
    @property
    def mass(self) -> float:
        """Derive callable mass from complexity and source size."""
        return self.cyclomatic_complexity * sqrt(self.sloc)

    @model_validator(mode="wrap")
    @classmethod
    def validate_projections(cls, value: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        if not isinstance(value, Mapping):
            return handler(value)
        values = dict(value)
        projections = {name: values.pop(name) for name in ("sloc", "mass") if name in values}
        result = handler(values)
        for name, supplied in projections.items():
            if isinstance(supplied, bool) or supplied != getattr(result, name):
                raise ValueError(f"function {name} must match its derived value")
        return result

    @model_validator(mode="after")
    def validate_lines(self) -> Self:
        if not self.sloc_lines or self.sloc_lines != tuple(sorted(set(self.sloc_lines))):
            raise ValueError("function source lines must be nonempty, sorted, and unique")
        if self.sloc_lines[0] < self.span.start_line or self.sloc_lines[-1] > self.span.end_line:
            raise ValueError("function source lines must fall within its span")
        return self


def _validate_function_identities(
    functions: tuple[FunctionEvidence, ...], path: ProjectPath
) -> None:
    identities = {
        (function.qualified_name, function.span.start_line, function.span.end_line)
        for function in functions
    }
    if len(identities) != len(functions):
        raise ValueError("duplicate function identity")
    if any(function.path != path for function in functions):
        raise ValueError("function path must match its owning file")


def validate_function_evidence(file: FileEvidence, functions: tuple[FunctionEvidence, ...]) -> None:
    """Check callable projections against their authoritative file evidence."""
    _validate_function_identities(functions, file.path)
    if functions and file.parse_state is not ParseState.PARSED:
        raise ValueError("failed source files cannot contain function evidence")
    for function in functions:
        expected = tuple(
            line
            for line in file.sloc_lines
            if function.span.start_line <= line <= function.span.end_line
        )
        if function.sloc_lines != expected:
            raise ValueError("function source lines must equal its file span intersection")


class AnalyzedFunctions(_Evidence):
    """Successful callable analysis, including a file with no callables."""

    state: Literal["analyzed"] = "analyzed"
    path: ProjectPath
    functions: tuple[FunctionEvidence, ...] = ()

    @model_validator(mode="after")
    def validate_functions(self) -> Self:
        _validate_function_identities(self.functions, self.path)
        return self


class FailedFunctions(_Evidence):
    """An analyzer failure after source parsing succeeded."""

    state: Literal["failed"] = "failed"
    path: ProjectPath
    diagnostic: Diagnostic

    @model_validator(mode="after")
    def validate_diagnostic(self) -> Self:
        if (
            self.diagnostic.path != self.path
            or self.diagnostic.severity is not DiagnosticSeverity.ERROR
        ):
            raise ValueError("failed function analysis requires a same-file error diagnostic")
        return self


FunctionAnalysis = Annotated[AnalyzedFunctions | FailedFunctions, Field(discriminator="state")]


class PatternCategory(StrEnum):
    """The four source-pattern families in the Python catalog."""

    REDUNDANCY = "redundancy"
    CONTROL_FLOW = "control-flow"
    DEFENSIVE = "defensive"
    ABSTRACTION = "abstraction"


class PatternFinding(_Evidence):
    """A rule's source location and explanation, without parser objects."""

    path: ProjectPath
    rule_id: _Text
    category: PatternCategory
    severity: DiagnosticSeverity
    span: SourceSpan
    message: _Text
    remediation: _Text | None = None


def pattern_source_lines(file: FileEvidence, finding: PatternFinding) -> tuple[int, ...]:
    """Resolve a finding to its owning parsed file's physical source lines."""
    if finding.path != file.path or file.parse_state is not ParseState.PARSED:
        raise ValueError("pattern finding requires its owning parsed source file")
    lines = tuple(
        line for line in file.sloc_lines if finding.span.start_line <= line <= finding.span.end_line
    )
    if not lines:
        raise ValueError("pattern finding must intersect source lines")
    return lines


class AnalyzedPatterns(_Evidence):
    """Successful pattern analysis, including a file with no findings."""

    state: Literal["analyzed"] = "analyzed"
    path: ProjectPath
    findings: tuple[PatternFinding, ...] = ()

    @model_validator(mode="after")
    def validate_findings(self) -> Self:
        identities = {
            (finding.rule_id, finding.span.start_line, finding.span.end_line)
            for finding in self.findings
        }
        if len(identities) != len(self.findings):
            raise ValueError("duplicate pattern finding identity")
        if any(finding.path != self.path for finding in self.findings):
            raise ValueError("pattern finding path must match its analysis")
        return self


class FailedPatterns(_Evidence):
    """A pattern analyzer failure after source parsing succeeded."""

    state: Literal["failed"] = "failed"
    path: ProjectPath
    diagnostic: Diagnostic

    @model_validator(mode="after")
    def validate_diagnostic(self) -> Self:
        if (
            self.diagnostic.path != self.path
            or self.diagnostic.severity is not DiagnosticSeverity.ERROR
        ):
            raise ValueError("failed pattern analysis requires a same-file error diagnostic")
        return self


PatternAnalysis = Annotated[AnalyzedPatterns | FailedPatterns, Field(discriminator="state")]


class LanguageEvidence(_Evidence):
    """Owned facts from one language adapter, without parser objects."""

    language: _Text
    capabilities: frozenset[EvidenceCapability]
    files: tuple[FileEvidence, ...]
    # Later metric slices replace empty-only collections with their owned models.
    pattern_analyses: tuple[PatternAnalysis, ...] = ()
    function_analyses: tuple[FunctionAnalysis, ...] = ()
    clone_candidates: tuple[()] = ()
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def patterns(self) -> tuple[PatternFinding, ...]:
        """Read findings from the authoritative per-file pattern outcomes."""
        return tuple(
            finding
            for analysis in self.pattern_analyses
            if isinstance(analysis, AnalyzedPatterns)
            for finding in analysis.findings
        )

    @property
    def functions(self) -> tuple[FunctionEvidence, ...]:
        """Read successful callables without storing a second authoritative list."""
        return tuple(
            function
            for analysis in self.function_analyses
            if isinstance(analysis, AnalyzedFunctions)
            for function in analysis.functions
        )

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

    @model_validator(mode="after")
    def validate_function_analyses(self) -> Self:
        if EvidenceCapability.FUNCTIONS not in self.capabilities:
            if self.function_analyses:
                raise ValueError("function outcomes require the functions capability")
            return self
        files = {
            file.path.root: file for file in self.files if file.parse_state is ParseState.PARSED
        }
        paths = [analysis.path.root for analysis in self.function_analyses]
        if len(paths) != len(set(paths)) or set(paths) != set(files):
            raise ValueError("function outcomes must cover each parsed file exactly once")
        for analysis in self.function_analyses:
            if isinstance(analysis, AnalyzedFunctions):
                validate_function_evidence(files[analysis.path.root], analysis.functions)
        return self

    @model_validator(mode="after")
    def validate_pattern_analyses(self) -> Self:
        if EvidenceCapability.PATTERNS not in self.capabilities:
            if self.pattern_analyses:
                raise ValueError("pattern outcomes require the patterns capability")
            return self
        files = {
            file.path.root: file for file in self.files if file.parse_state is ParseState.PARSED
        }
        paths = [analysis.path.root for analysis in self.pattern_analyses]
        if len(paths) != len(set(paths)) or set(paths) != set(files):
            raise ValueError("pattern outcomes must cover each parsed file exactly once")
        for analysis in self.pattern_analyses:
            if isinstance(analysis, AnalyzedPatterns):
                for finding in analysis.findings:
                    pattern_source_lines(files[analysis.path.root], finding)
        return self
