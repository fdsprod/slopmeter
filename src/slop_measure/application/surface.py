"""Compare source declarations while preserving ambiguity and source coverage."""

from collections import defaultdict
from collections.abc import Callable

from slop_measure.application.comparison import assemble_comparison
from slop_measure.application.service import AnalysisService, _Snapshot
from slop_measure.domain.change_review import ComparisonLimitation
from slop_measure.domain.changes import AddedFile, DeletedFile
from slop_measure.domain.evidence import CoverageState, ParseState
from slop_measure.domain.reports import ComparisonAnalysis, ComparisonCohortReport, SourceSide
from slop_measure.domain.requests import ComparisonRequest, SnapshotRequest
from slop_measure.domain.source import Cohort, GitSourceIdentity, ProjectPath
from slop_measure.domain.surface import (
    AddedSymbol,
    PairedSymbol,
    RemovedSymbol,
    SurfaceFile,
    SurfaceReviewReport,
    SymbolChange,
    SymbolChangeState,
    UnresolvedSymbols,
)
from slop_measure.languages.python.symbols import SymbolSyntax, extract_symbols
from slop_measure.sources.git import rename_pairs

_FileKey = tuple[str, Cohort, str]
_Key = tuple[object, ...]


def _file_key(symbol: SymbolSyntax) -> _FileKey:
    occurrence = symbol.occurrence
    return occurrence.language, occurrence.cohort, occurrence.path.root


def _collect(snapshot: _Snapshot) -> tuple[list[SymbolSyntax], set[_FileKey]]:
    documents = {doc.path.root: doc for doc in snapshot.inventory.documents}
    symbols = []
    failed = set()
    for cohort in snapshot.report.cohorts:
        for file in cohort.current.files:
            evidence = file.evidence
            key = (cohort.language, cohort.cohort, evidence.path.root)
            if evidence.parse_state is ParseState.FAILED or cohort.language != "python":
                failed.add(key)
            else:
                symbols.extend(extract_symbols(documents[evidence.path.root]))
    return symbols, failed


def _groups(
    symbols: list[SymbolSyntax], key: Callable[[SymbolSyntax], _Key]
) -> dict[_Key, list[SymbolSyntax]]:
    grouped: dict[_Key, list[SymbolSyntax]] = defaultdict(list)
    for symbol in symbols:
        grouped[key(symbol)].append(symbol)
    return grouped


class _Matcher:
    def __init__(self, baseline: list[SymbolSyntax], current: list[SymbolSyntax]) -> None:
        self.baseline = baseline
        self.current = current
        self.changes: list[SymbolChange] = []

    def _consume(self, old: list[SymbolSyntax], new: list[SymbolSyntax]) -> None:
        old_set, new_set = set(old), set(new)
        self.baseline = [item for item in self.baseline if item not in old_set]
        self.current = [item for item in self.current if item not in new_set]

    def unresolved(self, old: list[SymbolSyntax], new: list[SymbolSyntax], reason: str) -> None:
        if old or new:
            self.changes.append(
                UnresolvedSymbols(
                    baseline=tuple(item.occurrence for item in old),
                    current=tuple(item.occurrence for item in new),
                    reason=reason,
                )
            )
            self._consume(old, new)

    def unavailable(
        self, files: tuple[SurfaceFile, ...], failed: tuple[set[_FileKey], set[_FileKey]]
    ) -> None:
        for file in files:
            old_path = None if isinstance(file.pair, AddedFile) else file.pair.baseline_path.root
            new_path = None if isinstance(file.pair, DeletedFile) else file.pair.current_path.root
            old_key = (file.language, file.cohort, old_path)
            new_key = (file.language, file.cohort, new_path)
            if old_key in failed[0] or new_key in failed[1]:
                self.unresolved(
                    [item for item in self.baseline if _file_key(item) == old_key],
                    [item for item in self.current if _file_key(item) == new_key],
                    "source-unavailable",
                )

    def names(self, renames: tuple[tuple[ProjectPath, ProjectPath], ...]) -> None:
        mapping = {old.root: new.root for old, new in renames}

        def old_key(symbol: SymbolSyntax) -> _Key:
            item = symbol.occurrence
            return (
                item.language,
                item.cohort,
                mapping.get(item.path.root, item.path.root),
                item.kind,
                item.qualified_name,
            )

        def new_key(symbol: SymbolSyntax) -> _Key:
            item = symbol.occurrence
            return (*_file_key(symbol), item.kind, item.qualified_name)

        old_groups, new_groups = _groups(self.baseline, old_key), _groups(self.current, new_key)
        for key in sorted(old_groups.keys() | new_groups.keys()):
            old, new = old_groups.get(key, []), new_groups.get(key, [])
            if len(old) > 1 or len(new) > 1:
                self.unresolved(old, new, "duplicate-qualified-name")
            elif old and new:
                self.pair(old[0], new[0])

    def pair(self, old: SymbolSyntax, new: SymbolSyntax) -> None:
        before, after = old.occurrence, new.occurrence
        if before.ast_fingerprint != after.ast_fingerprint:
            state = SymbolChangeState.MODIFIED
        else:
            state = (
                SymbolChangeState.UNCHANGED
                if before.path == after.path
                else SymbolChangeState.MOVED
            )
        self.changes.append(PairedSymbol(state=state, baseline=before, current=after))
        self._consume([old], [new])

    def moves(self) -> None:
        def key(symbol: SymbolSyntax) -> _Key:
            item = symbol.occurrence
            return (
                item.language,
                item.cohort,
                item.kind,
                item.qualified_name,
                item.ast_fingerprint,
            )

        old_groups, new_groups = _groups(self.baseline, key), _groups(self.current, key)
        for identity in sorted(old_groups.keys() & new_groups.keys()):
            old, new = old_groups[identity], new_groups[identity]
            if len(old) == len(new) == 1:
                self.pair(old[0], new[0])
            else:
                self.unresolved(old, new, "competing-move-candidates")

    def possible_renames(self) -> None:
        def key(symbol: SymbolSyntax) -> _Key:
            item = symbol.occurrence
            return item.language, item.cohort, item.kind, symbol.rename_fingerprint

        old_groups, new_groups = _groups(self.baseline, key), _groups(self.current, key)
        for identity in sorted(old_groups.keys() & new_groups.keys()):
            self.unresolved(
                old_groups[identity], new_groups[identity], "possible-declaration-rename"
            )

    def possible_move_edits(self) -> None:
        def key(symbol: SymbolSyntax) -> _Key:
            item = symbol.occurrence
            return item.language, item.cohort, item.kind, item.qualified_name

        old_groups, new_groups = _groups(self.baseline, key), _groups(self.current, key)
        for identity in sorted(old_groups.keys() & new_groups.keys()):
            self.unresolved(old_groups[identity], new_groups[identity], "possible-move-and-edit")

    def incomplete_populations(
        self, populations: tuple[set[tuple[str, Cohort]], set[tuple[str, Cohort]]]
    ) -> None:
        for population in sorted(populations[0] | populations[1]):
            self.unresolved(
                [
                    item
                    for item in self.baseline
                    if _file_key(item)[:2] == population and population in populations[1]
                ],
                [
                    item
                    for item in self.current
                    if _file_key(item)[:2] == population and population in populations[0]
                ],
                "counterpart-source-unavailable",
            )

    def finish(self) -> tuple[SymbolChange, ...]:
        self.changes.extend(RemovedSymbol(baseline=item.occurrence) for item in self.baseline)
        self.changes.extend(AddedSymbol(current=item.occurrence) for item in self.current)
        return tuple(sorted(self.changes, key=_change_order))


def _change_order(change: SymbolChange) -> tuple[object, ...]:
    if isinstance(change, UnresolvedSymbols):
        item = (change.current or change.baseline)[0]
    elif isinstance(change, RemovedSymbol):
        item = change.baseline
    else:
        item = change.current
    return item.language, item.cohort, item.path.root, item.span.start_line, change.state


def review_surface(request: ComparisonRequest) -> SurfaceReviewReport:
    """Report added and modified declaration syntax without assigning a quality score."""
    service = AnalysisService()
    before = service._scan(SnapshotRequest(target=request.baseline, config=request.config))
    after = service._scan(SnapshotRequest(target=request.current, config=request.config))
    hints = (
        rename_pairs(before.report.analysis.current, after.report.analysis.current)
        if isinstance(before.report.analysis.current, GitSourceIdentity)
        else ()
    )
    comparison = assemble_comparison(
        before.report, after.report, before.inventory, after.inventory, renames=hints
    )
    if not isinstance(comparison.analysis, ComparisonAnalysis):
        raise ValueError("surface review requires a comparison")
    files = tuple(
        SurfaceFile(language=cohort.language, cohort=cohort.cohort, pair=change.pair)
        for cohort in comparison.cohorts
        if isinstance(cohort, ComparisonCohortReport)
        for change in cohort.changes
    )
    baseline, old_failed = _collect(before)
    current, new_failed = _collect(after)
    matcher = _Matcher(baseline, current)
    matcher.unavailable(files, (old_failed, new_failed))
    matcher.names(hints)
    matcher.moves()
    matcher.possible_renames()
    matcher.possible_move_edits()
    incomplete = (
        {(language, cohort) for language, cohort, _ in old_failed},
        {(language, cohort) for language, cohort, _ in new_failed},
    )
    for item in comparison.coverage:
        if item.detail.state is not CoverageState.SCORED and item.detail.file_count:
            side = 0 if item.source is SourceSide.BASELINE else 1
            incomplete[side].add((item.detail.language, item.detail.cohort))
    matcher.incomplete_populations(incomplete)
    limitations = tuple(
        ComparisonLimitation(
            language=language,
            cohort=cohort,
            path=ProjectPath(path),
            reason=f"{side.value} source declarations unavailable",
        )
        for side, failed in ((SourceSide.BASELINE, old_failed), (SourceSide.CURRENT, new_failed))
        for language, cohort, path in sorted(failed)
    ) + tuple(
        ComparisonLimitation(
            language=item.detail.language,
            cohort=item.detail.cohort,
            reason=f"{item.source.value}: {item.detail.reason}",
        )
        for item in comparison.coverage
        if item.detail.state is not CoverageState.SCORED and item.detail.file_count
    )
    return SurfaceReviewReport(
        analysis=comparison.analysis,
        provenance=comparison.provenance,
        files=files,
        symbols=matcher.finish(),
        limitations=limitations,
        coverage=comparison.coverage,
        diagnostics=comparison.diagnostics,
        excluded_directories=comparison.excluded_directories,
    )
