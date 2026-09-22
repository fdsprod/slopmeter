"""Source-owned continuity evidence, separate from exact-source review validity."""

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

from slop_measure.domain.change_states import FindingChangeState
from slop_measure.domain.clone_changes import CloneGroupChange
from slop_measure.domain.error_changes import ErrorChange, ErrorCoverage
from slop_measure.domain.error_review import ErrorReviewReport
from slop_measure.domain.evidence import PatternFinding
from slop_measure.domain.reports import (
    ComparisonAnalysis,
    Provenance,
    ReportCoverage,
    ReportDiagnostic,
    ReportExcludedDirectory,
)
from slop_measure.domain.source import Cohort, ProjectPath
from slop_measure.domain.state_dispatch import StateDispatchChange

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PatternOccurrence(_Record):
    finding: PatternFinding
    language: _Text
    cohort: Cohort
    source_sha256: _Hash


class IntroducedPattern(_Record):
    state: Literal[FindingChangeState.INTRODUCED] = FindingChangeState.INTRODUCED
    current: PatternOccurrence


class RemovedPattern(_Record):
    state: Literal[FindingChangeState.REMOVED] = FindingChangeState.REMOVED
    baseline: PatternOccurrence


class _PairedPattern(_Record):
    baseline: PatternOccurrence
    current: PatternOccurrence

    @model_validator(mode="after")
    def compatible(self) -> Self:
        old, new = self.baseline, self.current
        if (old.language, old.cohort, old.finding.rule_id) != (
            new.language,
            new.cohort,
            new.finding.rule_id,
        ):
            raise ValueError("pattern continuity requires the same population and rule")
        return self


class PersistedPattern(_PairedPattern):
    state: Literal[FindingChangeState.PERSISTED] = FindingChangeState.PERSISTED


class ChangedPattern(_PairedPattern):
    state: Literal[FindingChangeState.CHANGED] = FindingChangeState.CHANGED


class UnresolvedPatterns(_Record):
    state: Literal[FindingChangeState.UNRESOLVED] = FindingChangeState.UNRESOLVED
    baseline: tuple[PatternOccurrence, ...] = ()
    current: tuple[PatternOccurrence, ...] = ()
    reason: _Text

    @model_validator(mode="after")
    def nonempty(self) -> Self:
        if not self.baseline and not self.current:
            raise ValueError("unresolved matching requires candidate evidence")
        return self


PatternChange = Annotated[
    IntroducedPattern | RemovedPattern | PersistedPattern | ChangedPattern | UnresolvedPatterns,
    Field(discriminator="state"),
]


class ComparisonLimitation(_Record):
    language: _Text
    cohort: Cohort
    path: ProjectPath | None = None
    reason: _Text


class ChangeReviewReport(_Record):
    schema_version: Literal["1"] = "1"
    experiment: Literal["change-review-1"] = "change-review-1"
    analysis: ComparisonAnalysis
    provenance: Provenance
    patterns: tuple[PatternChange, ...] = ()
    clones: tuple[CloneGroupChange, ...] = ()
    errors: tuple[ErrorChange, ...] = ()
    state_dispatch: tuple[StateDispatchChange, ...] = ()
    state_dispatch_interpretation: tuple[str, ...] = (
        "Raw string state tests are syntax evidence; receiver types and defects are not inferred.",
        "Review enum members or concrete variant checks when the value selects behavior.",
    )
    error_coverage: tuple[ErrorCoverage, ...] = ()
    error_experiment: Literal["py-error-fallback-1"] = "py-error-fallback-1"
    error_interpretation: tuple[str, ...] = ErrorReviewReport.model_fields["interpretation"].default
    limitations: tuple[ComparisonLimitation, ...] = ()
    coverage: tuple[ReportCoverage, ...] = ()
    diagnostics: tuple[ReportDiagnostic, ...] = ()
    excluded_directories: tuple[ReportExcludedDirectory, ...] = ()

    @model_validator(mode="after")
    def unique_ownership(self) -> Self:
        owned: set[tuple[object, ...]] = set()
        for change in self.patterns:
            for side in ("baseline", "current"):
                value = getattr(change, side, ())
                occurrences = value if isinstance(value, tuple) else (value,)
                for occurrence in occurrences:
                    item = occurrence.finding
                    key = (
                        side,
                        occurrence.language,
                        occurrence.cohort,
                        item.path.root,
                        item.rule_id,
                        item.span.start_line,
                        item.span.end_line,
                    )
                    if key in owned:
                        raise ValueError("each source occurrence must have one change owner")
                    owned.add(key)
        return self

    @model_validator(mode="after")
    def unique_dispatch_ownership(self) -> Self:
        owned: set[tuple[object, ...]] = set()
        for change in self.state_dispatch:
            for side in ("baseline", "current"):
                value = getattr(change, side, ())
                occurrences = value if isinstance(value, tuple) else (value,)
                for item in occurrences:
                    key = (
                        side,
                        item.language,
                        item.cohort,
                        item.path.root,
                        item.span.start_line,
                        item.span.end_line,
                        item.start_column,
                        item.end_column,
                    )
                    if key in owned:
                        raise ValueError("each state comparison must have one change owner")
                    owned.add(key)
        return self

    @computed_field
    @property
    def summary(self) -> dict[str, int]:
        return {
            state: sum(item.state == state for item in self.patterns)
            for state in FindingChangeState
        }

    @computed_field
    @property
    def error_summary(self) -> dict[str, int]:
        return {
            state: sum(item.state == state for item in self.errors) for state in FindingChangeState
        }

    @computed_field
    @property
    def state_dispatch_summary(self) -> dict[str, int]:
        return {
            state: sum(item.state == state for item in self.state_dispatch)
            for state in FindingChangeState
        }

    @model_validator(mode="wrap")
    @classmethod
    def validate_summary(cls, value: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        if not isinstance(value, Mapping):
            return handler(value)
        fields = dict(value)
        supplied = {
            name: fields.pop(name)
            for name in ("summary", "error_summary", "state_dispatch_summary")
            if name in fields
        }
        result = handler(fields)
        for name, counts in supplied.items():
            if (
                not isinstance(counts, dict)
                or any(type(count) is not int for count in counts.values())
                or counts != getattr(result, name)
            ):
                raise ValueError("summary must match owned change evidence")
        return result
