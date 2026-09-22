"""Exception fallback evidence, separate from calibrated scores."""

from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    model_validator,
)

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import (
    Coverage,
    Diagnostic,
    DiagnosticSeverity,
    ExcludedDirectory,
    SourceSpan,
)
from slop_measure.domain.experimental_coverage import (
    ExperimentalCoverage,
    ExperimentalReport,
    summarize_coverage,
)
from slop_measure.domain.source import Cohort, DirectorySourceIdentity, ProjectPath

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ErrorFallbackKind = Literal[
    "none",
    "false",
    "zero",
    "empty-string",
    "empty-bytes",
    "empty-list",
    "empty-dict",
    "empty-tuple",
]


class _ErrorEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ErrorExpression(_ErrorEvidence):
    span: SourceSpan
    expression: _Text


class ErrorFallbackFinding(_ErrorEvidence):
    kind: Literal["error-as-success"] = "error-as-success"
    caught: _Text
    protected: SourceSpan
    operations: tuple[ErrorExpression, ...]
    fallback: ErrorExpression
    fallback_kind: ErrorFallbackKind
    normal_returns: Annotated[tuple[ErrorExpression, ...], Field(min_length=1)]


class AnalyzedErrorHandler(_ErrorEvidence):
    state: Literal["analyzed"] = "analyzed"
    symbol: _Text
    span: SourceSpan
    findings: tuple[ErrorFallbackFinding, ...] = ()


class UnresolvedErrorHandler(_ErrorEvidence):
    state: Literal["unresolved"] = "unresolved"
    symbol: _Text
    span: SourceSpan
    reason: _Text


ErrorHandler = Annotated[
    AnalyzedErrorHandler | UnresolvedErrorHandler, Field(discriminator="state")
]


class AnalyzedErrorFile(_ErrorEvidence):
    state: Literal["analyzed"] = "analyzed"
    path: ProjectPath
    cohort: Cohort
    source_sha256: _Hash
    handlers: tuple[ErrorHandler, ...] = ()


class FailedErrorFile(_ErrorEvidence):
    state: Literal["failed"] = "failed"
    path: ProjectPath
    cohort: Cohort
    source_sha256: _Hash | None = None
    diagnostic: Diagnostic

    @model_validator(mode="after")
    def validate_failure(self) -> Self:
        if (
            self.diagnostic.path != self.path
            or self.diagnostic.severity is not DiagnosticSeverity.ERROR
        ):
            raise ValueError("failed error analysis requires an error for its source path")
        return self


ErrorFileResult = Annotated[AnalyzedErrorFile | FailedErrorFile, Field(discriminator="state")]


class ErrorReviewReport(ExperimentalReport):
    schema_version: Literal["1"] = "1"
    experiment: Literal["py-error-fallback-1"] = "py-error-fallback-1"
    tool_version: _Text
    source: DirectorySourceIdentity
    config: AnalysisConfig
    files: tuple[ErrorFileResult, ...] = ()
    inventory_coverage: tuple[Coverage, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    excluded_directories: tuple[ExcludedDirectory, ...] = ()
    interpretation: tuple[str, ...] = (
        "Experimental exception fallback review: no score or M2 contribution. "
        "Calibrated scores are unchanged.",
        "Candidates connect an exception handler's literal/default return to non-default "
        "explicit returns in the same function. This is syntactic corroboration, not proof "
        "of reachability, return-type equivalence, or business intent.",
        "Protected calls are possible operations, not attribution of which operation raised. "
        "Exception spelling does not establish inheritance or a builtin binding.",
        "None, False, and empty containers can be intentional failure or snapshot results. "
        "Review the caller contract, observability, and whether failure needs a distinct result. "
        "Logging alone does not prove a fallback is safe.",
        "Conditional flow, early exits, indirect values, except*, dynamic exception expressions, "
        "generators, module/class handlers, and enclosing finally blocks remain unresolved.",
        "Source is parsed, never imported or executed. No findings means no qualifying evidence "
        "in this limited experiment. Independent evaluation is required before scoring.",
    )

    @computed_field
    @property
    def summary(self) -> ExperimentalCoverage:
        files = [file for file in self.files if file.state == "analyzed"]
        handlers = [handler for file in files for handler in file.handlers]
        return summarize_coverage(
            unit="exception-handlers",
            file_states=(file.state for file in self.files),
            assessed=sum(handler.state == "analyzed" for handler in handlers),
            findings=sum(
                len(handler.findings) for handler in handlers if handler.state == "analyzed"
            ),
            unresolved_reasons=(
                handler.reason for handler in handlers if handler.state == "unresolved"
            ),
        )

    @model_validator(mode="after")
    def validate_files(self) -> Self:
        if len({file.path.root for file in self.files}) != len(self.files):
            raise ValueError("error review requires one outcome per source file")
        if any(
            file.diagnostic not in self.diagnostics for file in self.files if file.state == "failed"
        ):
            raise ValueError("failed file diagnostics must remain in the report")
        return self
