"""Bounded integration history and source-located observations of line rework."""

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, computed_field, model_validator

from slop_measure.config import AnalysisConfig
from slop_measure.domain.changes import AddedFile, FileChange, _Change
from slop_measure.domain.evidence import DiagnosticSeverity
from slop_measure.domain.reports import Provenance, ReportCoverage, ReportDiagnostic
from slop_measure.domain.source import Cohort, GitSourceIdentity, ProjectPath

_Positive = Annotated[int, Field(gt=0, strict=True)]
_Count = Annotated[int, Field(ge=0, strict=True)]
_Revision = Annotated[str, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class HistoryRequest(_Change):
    root: Path
    start: _Text
    end: _Text
    window_days: _Positive = 14
    max_commits: _Positive = 100
    config: AnalysisConfig = Field(default_factory=AnalysisConfig)


class CompleteHistory(_Change):
    state: Literal["complete"] = "complete"


class PartialHistory(_Change):
    state: Literal["partial"] = "partial"
    reason: Literal["missing-parent", "commit-limit"]
    boundary_commit: _Revision


HistoryTraversal = Annotated[CompleteHistory | PartialHistory, Field(discriminator="state")]


class KnownRework(_Change):
    state: Literal["recent", "outside-window"]
    deleted_path: ProjectPath
    deleted_line: _Positive
    introduced_commit: _Revision
    introduced_path: ProjectPath
    introduced_line: _Positive
    age_seconds: _Count


class UnresolvedRework(_Change):
    state: Literal["unresolved"] = "unresolved"
    deleted_path: ProjectPath
    deleted_line: _Positive
    reason: Literal["unknown-introduction", "timestamp-order"]


ReworkAssessment = Annotated[KnownRework | UnresolvedRework, Field(discriminator="state")]


class MeasuredHistoryCounts(_Change):
    state: Literal["measured"] = "measured"
    added: _Count
    deleted: _Count

    @computed_field
    @property
    def churn(self) -> int:
        return self.added + self.deleted

    @computed_field
    @property
    def net(self) -> int:
        return self.added - self.deleted


class UnavailableHistoryCounts(_Change):
    state: Literal["unavailable"] = "unavailable"
    reason: Literal["unavailable-source"] = "unavailable-source"


HistoryCounts = Annotated[
    MeasuredHistoryCounts | UnavailableHistoryCounts, Field(discriminator="state")
]


class HistoryCohort(_Change):
    language: _Text
    cohort: Cohort
    changes: tuple[FileChange, ...]
    rework: tuple[ReworkAssessment, ...] = ()

    @model_validator(mode="after")
    def validate_rework(self) -> Self:
        removals = {
            (change.pair.baseline_path, line)
            for change in self.changes
            if not isinstance(change.pair, AddedFile) and change.lines.state == "measured"
            for line in change.lines.deleted_lines
        }
        observed = [(item.deleted_path, item.deleted_line) for item in self.rework]
        if len(observed) != len(set(observed)) or set(observed) != removals:
            raise ValueError("history rework must account for every measured deleted source line")
        return self


class HistoryStep(_Change):
    commit: _Revision
    parent: _Revision
    timestamp: Annotated[int, Field(strict=True)]
    cohorts: tuple[HistoryCohort, ...]
    coverage: tuple[ReportCoverage, ...] = ()
    diagnostics: tuple[ReportDiagnostic, ...] = ()

    @computed_field
    @property
    def totals(self) -> HistoryCounts:
        changes = [change for cohort in self.cohorts for change in cohort.changes]
        if any(change.lines.state == "unavailable" for change in changes) or any(
            item.detail.severity is DiagnosticSeverity.ERROR for item in self.diagnostics
        ):
            return UnavailableHistoryCounts()
        return MeasuredHistoryCounts(
            added=sum(change.lines.added for change in changes if change.lines.state == "measured"),
            deleted=sum(
                change.lines.deleted for change in changes if change.lines.state == "measured"
            ),
        )

    @computed_field
    @property
    def added(self) -> int | None:
        totals = self.totals
        return totals.added if totals.state == "measured" else None

    @computed_field
    @property
    def deleted(self) -> int | None:
        totals = self.totals
        return totals.deleted if totals.state == "measured" else None

    @computed_field
    @property
    def churn(self) -> int | None:
        totals = self.totals
        return totals.churn if totals.state == "measured" else None

    @computed_field
    @property
    def net(self) -> int | None:
        totals = self.totals
        return totals.net if totals.state == "measured" else None


class HistoryReport(_Change):
    schema_version: Literal["1"] = "1"
    start: GitSourceIdentity
    end: GitSourceIdentity
    ancestry: Literal["first-parent"] = "first-parent"
    window_days: _Positive
    max_commits: _Positive
    traversal: HistoryTraversal
    provenance: Provenance
    steps: tuple[HistoryStep, ...]

    @model_validator(mode="after")
    def validate_chain(self) -> Self:
        if self.start.root != self.end.root:
            raise ValueError("history endpoints must share one repository root")
        if len(self.steps) > self.max_commits:
            raise ValueError("history steps exceed the requested commit limit")
        for before, after in zip(self.steps, self.steps[1:], strict=False):
            if before.commit != after.parent:
                raise ValueError("history steps must form an ordered first-parent chain")
        if self.steps and self.steps[-1].commit != self.end.revision:
            raise ValueError("history steps must end at the pinned end revision")
        if self.traversal.state == "complete":
            anchor = self.steps[0].parent if self.steps else self.end.revision
            if anchor != self.start.revision:
                raise ValueError("complete history must start at the pinned anchor")
        return self
