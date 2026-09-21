"""Experimental relationship evidence, separate from calibrated metrics."""

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


class _ReviewEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelField(_ReviewEvidence):
    name: _Text
    kind: Literal["boolean", "nullable"]
    span: SourceSpan


class GuardLocation(_ReviewEvidence):
    symbol: _Text
    span: SourceSpan


class CoupledStateFinding(_ReviewEvidence):
    kind: Literal["coupled-state"] = "coupled-state"
    fields: Annotated[tuple[ModelField, ...], Field(min_length=2)]
    predicate: _Text
    validator: GuardLocation
    consumers: Annotated[tuple[GuardLocation, ...], Field(min_length=2)]

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if len({item.name for item in self.fields}) != len(self.fields):
            raise ValueError("coupled fields must have unique names")
        if {item.kind for item in self.fields} != {"boolean", "nullable"}:
            raise ValueError("coupled evidence requires boolean and nullable fields")
        if len({item.symbol for item in self.consumers}) != len(self.consumers):
            raise ValueError("coupled evidence requires distinct consumer symbols")
        return self


class AnalyzedModel(_ReviewEvidence):
    state: Literal["analyzed"] = "analyzed"
    name: _Text
    span: SourceSpan
    findings: tuple[CoupledStateFinding, ...] = ()

    @model_validator(mode="after")
    def validate_locations(self) -> Self:
        for finding in self.findings:
            spans = (finding.validator.span, *(field.span for field in finding.fields))
            if any(
                span.start_line < self.span.start_line or span.end_line > self.span.end_line
                for span in spans
            ):
                raise ValueError("field and validator locations must belong to the model")
        return self


class UnresolvedModel(_ReviewEvidence):
    state: Literal["unresolved"] = "unresolved"
    name: _Text
    span: SourceSpan
    reason: _Text


ModelAssessment = Annotated[AnalyzedModel | UnresolvedModel, Field(discriminator="state")]


class AnalyzedModelFile(_ReviewEvidence):
    state: Literal["analyzed"] = "analyzed"
    path: ProjectPath
    cohort: Cohort
    source_sha256: _Hash
    models: tuple[ModelAssessment, ...] = ()


class FailedModelFile(_ReviewEvidence):
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
            raise ValueError("failed model analysis requires an error for its source path")
        return self


ModelFileResult = Annotated[AnalyzedModelFile | FailedModelFile, Field(discriminator="state")]


class ModelReviewReport(ExperimentalReport):
    schema_version: Literal["1"] = "1"
    experiment: Literal["py-coupled-state-1"] = "py-coupled-state-1"
    tool_version: _Text
    source: DirectorySourceIdentity
    config: AnalysisConfig
    files: tuple[ModelFileResult, ...] = ()
    inventory_coverage: tuple[Coverage, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    excluded_directories: tuple[ExcludedDirectory, ...] = ()
    interpretation: tuple[str, ...] = (
        "Experimental review evidence: no score or M2 contribution. "
        "Calibrated scores are unchanged.",
        "A repeated guard is not a defect. Separate trust boundaries may require validation.",
        "Only same-file direct dataclasses, boolean/nullable fields, and explicit typed "
        "top-level consumers are supported. Predicates match structurally, not logically.",
        "Unresolved models remain unassessed. No findings means no qualifying evidence within "
        "this limited experiment. Unannotated, nested, aliased, and cross-file consumers "
        "are not resolved. Review source before redesigning a public or stored model.",
        "Source is parsed, never imported or executed. Independent holdouts are needed "
        "before estimating precision or assigning score weights.",
    )

    @computed_field
    @property
    def summary(self) -> ExperimentalCoverage:
        files = [file for file in self.files if file.state == "analyzed"]
        models = [model for file in files for model in file.models]
        return summarize_coverage(
            unit="class-declarations",
            file_states=(file.state for file in self.files),
            assessed=sum(model.state == "analyzed" for model in models),
            findings=sum(len(model.findings) for model in models if model.state == "analyzed"),
            unresolved_reasons=(model.reason for model in models if model.state == "unresolved"),
        )

    @model_validator(mode="after")
    def validate_files(self) -> Self:
        if len({file.path.root for file in self.files}) != len(self.files):
            raise ValueError("model review requires one outcome per source file")
        if any(
            file.diagnostic not in self.diagnostics for file in self.files if file.state == "failed"
        ):
            raise ValueError("failed file diagnostics must remain in the report")
        return self
