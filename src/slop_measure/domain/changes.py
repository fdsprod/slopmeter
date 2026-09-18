"""Explicit file pairs, exact changed source lines, and checked change projections."""

from collections.abc import Mapping
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    ModelWrapValidatorHandler,
    StringConstraints,
    computed_field,
    model_validator,
)

from slop_measure.domain.metrics import UnavailableReason
from slop_measure.domain.source import ProjectPath

_Count = Annotated[int, Field(ge=0, strict=True)]
_Line = Annotated[int, Field(gt=0, strict=True)]
_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _Change(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="wrap")
    @classmethod
    def validate_projections(cls, value: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        if not isinstance(value, Mapping):
            return handler(value)
        fields = dict(value)
        projections = {
            name: fields.pop(name) for name in cls.model_computed_fields if name in fields
        }
        result = handler(fields)
        if projections:
            expected = result.model_dump(mode="json")
            for name, supplied in projections.items():
                if isinstance(supplied, bool) or supplied != expected[name]:
                    raise ValueError(f"change {name} must match its derived value")
        return result


class AddedFile(_Change):
    kind: Literal["added"] = "added"
    current_path: ProjectPath


class DeletedFile(_Change):
    kind: Literal["deleted"] = "deleted"
    baseline_path: ProjectPath


class _PairedFile(_Change):
    baseline_path: ProjectPath
    current_path: ProjectPath


class _SamePath(_PairedFile):
    @model_validator(mode="after")
    def validate_paths(self) -> Self:
        if self.baseline_path != self.current_path:
            raise ValueError("this file pair requires equal paths")
        return self


class ModifiedFile(_SamePath):
    kind: Literal["modified"] = "modified"


class UnchangedFile(_SamePath):
    kind: Literal["unchanged"] = "unchanged"


class UnresolvedFile(_SamePath):
    """Known matching paths with unreadable content on at least one side."""

    kind: Literal["unresolved"] = "unresolved"


class RenamedFile(_PairedFile):
    kind: Literal["renamed"] = "renamed"

    @model_validator(mode="after")
    def validate_paths(self) -> Self:
        if self.baseline_path == self.current_path:
            raise ValueError("a rename requires different paths")
        return self


FilePair = Annotated[
    AddedFile | DeletedFile | ModifiedFile | UnchangedFile | UnresolvedFile | RenamedFile,
    Field(discriminator="kind"),
]


class MeasuredGrowth(_Change):
    state: Literal["measured"] = "measured"
    value: Annotated[FiniteFloat, Field(ge=-1, strict=True)]


class UnavailableGrowth(_Change):
    state: Literal["unavailable"] = "unavailable"
    reason: Literal["no-baseline-sloc"] = "no-baseline-sloc"


Growth = Annotated[MeasuredGrowth | UnavailableGrowth, Field(discriminator="state")]


class _LineAccounting(_Change):
    state: Literal["measured"] = "measured"
    baseline_sloc: _Count
    current_sloc: _Count

    @computed_field
    @property
    def net(self) -> int:
        return self.current_sloc - self.baseline_sloc

    @computed_field
    @property
    def growth(self) -> Growth:
        return (
            MeasuredGrowth(value=self.net / self.baseline_sloc)
            if self.baseline_sloc
            else UnavailableGrowth()
        )

    def _validate_counts(self, added: int, deleted: int) -> None:
        if added - deleted != self.net:
            raise ValueError("added minus deleted must equal current minus baseline SLOC")
        if added > self.current_sloc or deleted > self.baseline_sloc:
            raise ValueError("changed line counts cannot exceed their source totals")


class MeasuredLineDelta(_LineAccounting):
    added_lines: tuple[_Line, ...]
    deleted_lines: tuple[_Line, ...]

    @computed_field
    @property
    def added(self) -> int:
        return len(self.added_lines)

    @computed_field
    @property
    def deleted(self) -> int:
        return len(self.deleted_lines)

    @model_validator(mode="after")
    def validate_lines(self) -> Self:
        for lines in (self.added_lines, self.deleted_lines):
            if lines != tuple(sorted(set(lines))):
                raise ValueError("changed line numbers must be sorted and unique")
        self._validate_counts(self.added, self.deleted)
        return self


class MeasuredLineTotals(_LineAccounting):
    added: _Count
    deleted: _Count

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        self._validate_counts(self.added, self.deleted)
        return self


class UnavailableLineDelta(_Change):
    state: Literal["unavailable"] = "unavailable"
    reason: UnavailableReason


LineDelta = Annotated[MeasuredLineDelta | UnavailableLineDelta, Field(discriminator="state")]
LineTotals = Annotated[MeasuredLineTotals | UnavailableLineDelta, Field(discriminator="state")]


class MeasuredMetricDelta(_Change):
    state: Literal["measured"] = "measured"
    metric_id: _Text
    value: FiniteFloat
    unit: Literal["ratio", "lines", "points"]


class UnavailableMetricDelta(_Change):
    state: Literal["unavailable"] = "unavailable"
    metric_id: _Text
    reason: Literal[
        "missing-baseline", "missing-current", "unavailable-input", "incompatible-definitions"
    ]


MetricDelta = Annotated[MeasuredMetricDelta | UnavailableMetricDelta, Field(discriminator="state")]


class FileChange(_Change):
    pair: FilePair
    lines: LineDelta
    deltas: tuple[MetricDelta, ...] = ()

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        ids = [delta.metric_id for delta in self.deltas]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate metric delta ID")
        return self
