"""Finite variant coverage evidence without a calibrated score."""

from collections.abc import Mapping
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


class _VariantEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _contains(outer: SourceSpan, inner: SourceSpan) -> bool:
    return outer.start_line <= inner.start_line <= inner.end_line <= outer.end_line


class VariantCase(_VariantEvidence):
    name: _Text
    span: SourceSpan


class VariantDeclaration(_VariantEvidence):
    name: _Text
    kind: Literal["enum", "literal"]
    span: SourceSpan
    cases: Annotated[tuple[VariantCase, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_cases(self) -> Self:
        if len({case.name for case in self.cases}) != len(self.cases):
            raise ValueError("variant declaration cases must be unique")
        if any(not _contains(self.span, case.span) for case in self.cases):
            raise ValueError("variant cases must belong to the declaration span")
        return self


class ExplicitVariantBranch(_VariantEvidence):
    kind: Literal["cases"] = "cases"
    span: SourceSpan
    cases: Annotated[tuple[_Text, ...], Field(min_length=1)]
    conditional: bool = False

    @model_validator(mode="after")
    def validate_cases(self) -> Self:
        if len(set(self.cases)) != len(self.cases):
            raise ValueError("branch cases must be unique")
        return self


class FallbackVariantBranch(_VariantEvidence):
    kind: Literal["fallback"] = "fallback"
    span: SourceSpan
    conditional: bool = False


VariantBranch = Annotated[
    ExplicitVariantBranch | FallbackVariantBranch, Field(discriminator="kind")
]


class AnalyzedVariantHandler(_VariantEvidence):
    state: Literal["analyzed"] = "analyzed"
    symbol: _Text
    subject: _Text
    span: SourceSpan
    declaration: VariantDeclaration
    branches: Annotated[tuple[VariantBranch, ...], Field(min_length=1)]

    @computed_field
    @property
    def not_explicitly_covered(self) -> tuple[str, ...]:
        covered = {
            name
            for branch in self.branches
            if branch.kind == "cases" and not branch.conditional
            for name in branch.cases
        }
        return tuple(case.name for case in self.declaration.cases if case.name not in covered)

    @computed_field
    @property
    def coverage(self) -> Literal["exhaustive", "missing", "fallback"]:
        if not self.not_explicitly_covered:
            return "exhaustive"
        if any(branch.kind == "fallback" and not branch.conditional for branch in self.branches):
            return "fallback"
        return "missing"

    @model_validator(mode="wrap")
    @classmethod
    def validate_projection(cls, value: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        if not isinstance(value, Mapping):
            return handler(value)
        fields = dict(value)
        coverage = fields.pop("coverage", None)
        unhandled = fields.pop("not_explicitly_covered", None)
        result = handler(fields)
        if "coverage" in value and coverage != result.coverage:
            raise ValueError("variant coverage must match its branches")
        if "not_explicitly_covered" in value and unhandled not in (
            result.not_explicitly_covered,
            list(result.not_explicitly_covered),
        ):
            raise ValueError("explicit coverage gaps must match declaration and branches")
        return result

    @model_validator(mode="after")
    def validate_branches(self) -> Self:
        names = {case.name for case in self.declaration.cases}
        for branch in self.branches:
            if not _contains(self.span, branch.span):
                raise ValueError("variant branch must belong to the handler span")
            if branch.kind == "cases" and not set(branch.cases) <= names:
                raise ValueError("branch cases must belong to the variant declaration")
        return self


class UnresolvedVariantHandler(_VariantEvidence):
    state: Literal["unresolved"] = "unresolved"
    symbol: _Text
    subject: _Text
    span: SourceSpan
    reason: _Text


VariantHandler = Annotated[
    AnalyzedVariantHandler | UnresolvedVariantHandler, Field(discriminator="state")
]


class AnalyzedVariantFile(_VariantEvidence):
    state: Literal["analyzed"] = "analyzed"
    path: ProjectPath
    cohort: Cohort
    source_sha256: _Hash
    handlers: tuple[VariantHandler, ...] = ()


class FailedVariantFile(_VariantEvidence):
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
            raise ValueError("failed variant analysis requires an error for its source path")
        return self


VariantFileResult = Annotated[AnalyzedVariantFile | FailedVariantFile, Field(discriminator="state")]


class VariantReviewReport(ExperimentalReport):
    schema_version: Literal["1"] = "1"
    experiment: Literal["py-variant-review-1"] = "py-variant-review-1"
    tool_version: _Text
    source: DirectorySourceIdentity
    config: AnalysisConfig
    files: tuple[VariantFileResult, ...] = ()
    inventory_coverage: tuple[Coverage, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    excluded_directories: tuple[ExcludedDirectory, ...] = ()
    interpretation: tuple[str, ...] = (
        "Experimental variant review: no score or M2 contribution. "
        "Calibrated scores are unchanged.",
        "Missing means known cases lack unconditional explicit branches or a catch-all. "
        "Intentional partial handlers are possible; review the handler contract.",
        "Fallback means known cases use a catch-all instead of explicit branches. "
        "A catch-all may be intentional at a compatibility boundary.",
        "Guarded branches do not prove full coverage. Exhaustive syntax does not "
        "establish that branch bodies are correct.",
        "Only local finite Enum/Literal declarations and first-statement typed match "
        "handlers are supported. Unresolved handlers remain unassessed. No findings "
        "means no qualifying evidence in this limited experiment.",
        "Source is parsed, never imported or executed. This is not a full type checker. "
        "Independent holdouts are needed before estimating precision or assigning scores.",
    )

    @computed_field
    @property
    def summary(self) -> ExperimentalCoverage:
        files = [file for file in self.files if file.state == "analyzed"]
        handlers = [handler for file in files for handler in file.handlers]
        return summarize_coverage(
            unit="match-handlers",
            file_states=(file.state for file in self.files),
            assessed=sum(handler.state == "analyzed" for handler in handlers),
            findings=sum(
                handler.coverage != "exhaustive"
                for handler in handlers
                if handler.state == "analyzed"
            ),
            unresolved_reasons=(
                handler.reason for handler in handlers if handler.state == "unresolved"
            ),
        )

    @model_validator(mode="after")
    def validate_files(self) -> Self:
        if len({file.path.root for file in self.files}) != len(self.files):
            raise ValueError("variant review requires one outcome per source file")
        if any(
            file.diagnostic not in self.diagnostics for file in self.files if file.state == "failed"
        ):
            raise ValueError("failed file diagnostics must remain in the report")
        return self
