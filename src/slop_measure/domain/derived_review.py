"""Ordered local derivation evidence, separate from calibrated metrics."""

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


class _DerivedEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DerivedStateFinding(_DerivedEvidence):
    kind: Literal["stale-derived-state"] = "stale-derived-state"
    derived_name: _Text
    source_name: _Text
    derivation: SourceSpan
    mutation: SourceSpan
    read: SourceSpan
    mutation_kind: Literal["append", "extend", "insert"]

    @model_validator(mode="after")
    def validate_trace(self) -> Self:
        if self.derived_name == self.source_name:
            raise ValueError("derived and source names must be distinct")
        if not (
            self.derivation.end_line <= self.mutation.start_line
            and self.mutation.end_line <= self.read.start_line
        ):
            raise ValueError("derived evidence must follow derivation, mutation, read order")
        return self


class AnalyzedDerivedFunction(_DerivedEvidence):
    state: Literal["analyzed"] = "analyzed"
    symbol: _Text
    span: SourceSpan
    findings: tuple[DerivedStateFinding, ...] = ()

    @model_validator(mode="after")
    def validate_spans(self) -> Self:
        if any(
            not (
                self.span.start_line
                <= item.derivation.start_line
                <= item.read.end_line
                <= self.span.end_line
            )
            for item in self.findings
        ):
            raise ValueError("derived evidence must belong to its function")
        return self


class UnresolvedDerivedFunction(_DerivedEvidence):
    state: Literal["unresolved"] = "unresolved"
    symbol: _Text
    span: SourceSpan
    reason: _Text


DerivedFunction = Annotated[
    AnalyzedDerivedFunction | UnresolvedDerivedFunction, Field(discriminator="state")
]


class AnalyzedDerivedFile(_DerivedEvidence):
    state: Literal["analyzed"] = "analyzed"
    path: ProjectPath
    cohort: Cohort
    source_sha256: _Hash
    functions: tuple[DerivedFunction, ...] = ()


class FailedDerivedFile(_DerivedEvidence):
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
            raise ValueError("failed derived analysis requires an error for its source path")
        return self


DerivedFileResult = Annotated[AnalyzedDerivedFile | FailedDerivedFile, Field(discriminator="state")]


class DerivedReviewReport(ExperimentalReport):
    schema_version: Literal["1"] = "1"
    experiment: Literal["py-derived-state-1"] = "py-derived-state-1"
    tool_version: _Text
    source: DirectorySourceIdentity
    config: AnalysisConfig
    files: tuple[DerivedFileResult, ...] = ()
    inventory_coverage: tuple[Coverage, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    excluded_directories: tuple[ExcludedDirectory, ...] = ()
    interpretation: tuple[str, ...] = (
        "Experimental derived-state review: no score or M2 contribution. "
        "Calibrated scores are unchanged.",
        "Each candidate connects a stored list length, a length-increasing mutation, "
        "and a later read without recomputation. Review whether the count should be current.",
        "An intentional snapshot can be correct. A candidate does not prove a defect "
        "or justify replacing a snapshot with live state.",
        "Only straight-line local list literals and append, nonempty literal extend, "
        "and insert are supported. Aliases, unknown calls, control flow, object fields, "
        "and uncertain bindings remain unresolved, not clean.",
        "Source is parsed, never imported or executed. No findings means no qualifying "
        "evidence in this narrow experiment. Independent evaluation is required before scoring.",
    )

    @computed_field
    @property
    def summary(self) -> ExperimentalCoverage:
        files = [file for file in self.files if file.state == "analyzed"]
        functions = [function for file in files for function in file.functions]
        return summarize_coverage(
            unit="functions",
            file_states=(file.state for file in self.files),
            assessed=sum(function.state == "analyzed" for function in functions),
            findings=sum(
                len(function.findings) for function in functions if function.state == "analyzed"
            ),
            unresolved_reasons=(
                function.reason for function in functions if function.state == "unresolved"
            ),
        )

    @model_validator(mode="after")
    def validate_files(self) -> Self:
        if len({file.path.root for file in self.files}) != len(self.files):
            raise ValueError("derived review requires one outcome per source file")
        if any(
            file.diagnostic not in self.diagnostics for file in self.files if file.state == "failed"
        ):
            raise ValueError("failed file diagnostics must remain in the report")
        return self
