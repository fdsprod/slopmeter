"""Source declaration changes with derived counts and explicit uncertain correspondence."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Literal, Self, assert_never

from pydantic import (
    Field,
    ModelWrapValidatorHandler,
    StringConstraints,
    TypeAdapter,
    computed_field,
    model_validator,
)

from slop_measure.domain.change_review import ComparisonLimitation
from slop_measure.domain.changes import FilePair, _Change
from slop_measure.domain.evidence import SourceSpan
from slop_measure.domain.reports import (
    ComparisonAnalysis,
    Provenance,
    ReportCoverage,
    ReportDiagnostic,
    ReportExcludedDirectory,
    SourceSide,
)
from slop_measure.domain.source import Cohort, ProjectPath

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class SymbolChangeState(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    MOVED = "moved"
    UNCHANGED = "unchanged"
    UNRESOLVED = "unresolved"


class SymbolOccurrence(_Change):
    language: Literal["python"] = "python"
    cohort: Cohort
    path: ProjectPath
    kind: Literal["function", "class"]
    qualified_name: _Text
    span: SourceSpan
    source_sha256: _Hash
    ast_fingerprint: _Hash


class AddedSymbol(_Change):
    state: Literal[SymbolChangeState.ADDED] = SymbolChangeState.ADDED
    current: SymbolOccurrence


class RemovedSymbol(_Change):
    state: Literal[SymbolChangeState.REMOVED] = SymbolChangeState.REMOVED
    baseline: SymbolOccurrence


class PairedSymbol(_Change):
    state: Literal[SymbolChangeState.MODIFIED, SymbolChangeState.MOVED, SymbolChangeState.UNCHANGED]
    baseline: SymbolOccurrence
    current: SymbolOccurrence

    @model_validator(mode="after")
    def validate_pair(self) -> Self:
        old, new = self.baseline, self.current
        if (old.language, old.cohort, old.kind, old.qualified_name) != (
            new.language,
            new.cohort,
            new.kind,
            new.qualified_name,
        ):
            raise ValueError("paired symbols require the same population, kind, and qualified name")
        same_syntax = old.ast_fingerprint == new.ast_fingerprint
        if self.state is SymbolChangeState.MODIFIED and same_syntax:
            raise ValueError("modified symbols require changed declaration syntax")
        if self.state in {SymbolChangeState.MOVED, SymbolChangeState.UNCHANGED} and not same_syntax:
            raise ValueError("unchanged or moved symbols require equal declaration syntax")
        if self.state is SymbolChangeState.MOVED and old.path == new.path:
            raise ValueError("moved symbols require different source paths")
        if self.state is SymbolChangeState.UNCHANGED and old.path != new.path:
            raise ValueError("unchanged symbols require the same source path")
        return self


class UnresolvedSymbols(_Change):
    state: Literal[SymbolChangeState.UNRESOLVED] = SymbolChangeState.UNRESOLVED
    baseline: tuple[SymbolOccurrence, ...] = ()
    current: tuple[SymbolOccurrence, ...] = ()
    reason: _Text

    @model_validator(mode="after")
    def require_candidates(self) -> Self:
        if not self.baseline and not self.current:
            raise ValueError("unresolved symbols require at least one source declaration")
        return self


SymbolChange = Annotated[
    AddedSymbol | RemovedSymbol | PairedSymbol | UnresolvedSymbols, Field(discriminator="state")
]


def symbol_sides(
    change: SymbolChange,
) -> tuple[tuple[SourceSide, tuple[SymbolOccurrence, ...]], ...]:
    """Expose only the source payloads owned by the concrete change variant."""
    if isinstance(change, AddedSymbol):
        return ((SourceSide.CURRENT, (change.current,)),)
    if isinstance(change, RemovedSymbol):
        return ((SourceSide.BASELINE, (change.baseline,)),)
    if isinstance(change, PairedSymbol):
        return (
            (SourceSide.BASELINE, (change.baseline,)),
            (SourceSide.CURRENT, (change.current,)),
        )
    if isinstance(change, UnresolvedSymbols):
        return ((SourceSide.BASELINE, change.baseline), (SourceSide.CURRENT, change.current))
    assert_never(change)


class SurfaceFile(_Change):
    language: _Text
    cohort: Cohort
    pair: FilePair


class MeasuredNovelRatio(_Change):
    state: Literal["measured"] = "measured"
    value: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False, strict=True)]


class UnavailableNovelRatio(_Change):
    state: Literal["unavailable"] = "unavailable"
    reason: Literal["no-added-or-modified-symbols", "incomplete-symbol-comparison"]


NovelRatio = Annotated[MeasuredNovelRatio | UnavailableNovelRatio, Field(discriminator="state")]
_NOVEL_RATIO = TypeAdapter(NovelRatio)


class SurfaceReviewReport(_Change):
    schema_version: Literal["1"] = "1"
    experiment: Literal["surface-review-1"] = "surface-review-1"
    analysis: ComparisonAnalysis
    provenance: Provenance
    files: tuple[SurfaceFile, ...] = ()
    symbols: tuple[SymbolChange, ...] = ()
    limitations: tuple[ComparisonLimitation, ...] = ()
    coverage: tuple[ReportCoverage, ...] = ()
    diagnostics: tuple[ReportDiagnostic, ...] = ()
    excluded_directories: tuple[ReportExcludedDirectory, ...] = ()

    @computed_field
    @property
    def summary(self) -> dict[str, int]:
        return {
            state.value: sum(item.state is state for item in self.symbols)
            for state in SymbolChangeState
        }

    @computed_field
    @property
    def file_summary(self) -> dict[str, int]:
        return {
            kind: sum(item.pair.kind == kind for item in self.files)
            for kind in ("added", "deleted", "modified", "renamed", "unchanged", "unresolved")
        }

    @computed_field
    @property
    def novel_ratio(self) -> NovelRatio:
        summary = self.summary
        if summary[SymbolChangeState.UNRESOLVED] or self.limitations:
            return UnavailableNovelRatio(reason="incomplete-symbol-comparison")
        denominator = summary[SymbolChangeState.ADDED] + summary[SymbolChangeState.MODIFIED]
        if denominator == 0:
            return UnavailableNovelRatio(reason="no-added-or-modified-symbols")
        return MeasuredNovelRatio(value=summary[SymbolChangeState.ADDED] / denominator)

    @model_validator(mode="after")
    def unique_ownership(self) -> Self:
        owned: set[tuple[object, ...]] = set()
        for change in self.symbols:
            for side, occurrences in symbol_sides(change):
                for occurrence in occurrences:
                    key = (
                        side,
                        occurrence.language,
                        occurrence.cohort,
                        occurrence.path.root,
                        occurrence.kind,
                        occurrence.qualified_name,
                        occurrence.span.start_line,
                    )
                    if key in owned:
                        raise ValueError("a source declaration must have exactly one change owner")
                    owned.add(key)
        return self

    @model_validator(mode="wrap")
    @classmethod
    def validate_projection_types(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        if isinstance(value, Mapping):
            for name in ("summary", "file_summary"):
                if name in value and (
                    not isinstance(value[name], dict)
                    or any(type(count) is not int for count in value[name].values())
                ):
                    raise ValueError("surface summary counts must be integers")
            if "novel_ratio" in value:
                _NOVEL_RATIO.validate_python(value["novel_ratio"])
        return handler(value)
