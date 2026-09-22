"""Compare raw state tests using the existing source pairs and coverage checks."""

from slop_measure.application.change_review import _stable_pairs, _uncertain
from slop_measure.domain.evidence import ParseState
from slop_measure.domain.inventory import SourceInventory
from slop_measure.domain.reports import AnalysisReport, ComparisonCohortReport, SourceSide
from slop_measure.domain.source import SourceDocument
from slop_measure.domain.state_dispatch import (
    ChangedStateDispatch,
    IntroducedStateDispatch,
    PersistedStateDispatch,
    RemovedStateDispatch,
    StateDispatchChange,
    StateDispatchOccurrence,
    UnresolvedStateDispatch,
)
from slop_measure.languages.python.state_dispatch import inspect_state_dispatch
from slop_measure.metrics.loc_delta import aligned_line_pairs


def _site(item: StateDispatchOccurrence) -> tuple[object, ...]:
    return item.symbol, item.subject, item.context


def _signature(item: StateDispatchOccurrence) -> tuple[object, ...]:
    return *_site(item), item.operator, item.values


def _match(
    old: tuple[StateDispatchOccurrence, ...],
    new: tuple[StateDispatchOccurrence, ...],
    documents: tuple[SourceDocument, SourceDocument],
) -> tuple[StateDispatchChange, ...]:
    remaining_old, remaining_new = list(old), list(new)
    result: list[StateDispatchChange] = []
    lines = dict(aligned_line_pairs(*documents))
    for signature in sorted({_signature(item) for item in old}, key=str):
        left = [item for item in remaining_old if _signature(item) == signature]
        right = [item for item in remaining_new if _signature(item) == signature]
        for before, after in _stable_pairs(left, right, lines, lambda item: item.span):
            result.append(PersistedStateDispatch(baseline=before, current=after))
            remaining_old.remove(before)
            remaining_new.remove(after)
    for site in sorted({_site(item) for item in remaining_old}, key=str):
        left = [item for item in remaining_old if _site(item) == site]
        right = [item for item in remaining_new if _site(item) == site]
        if len(left) == len(right) == 1:
            result.append(ChangedStateDispatch(baseline=left[0], current=right[0]))
            remaining_old.remove(left[0])
            remaining_new.remove(right[0])
    if remaining_old and remaining_new:
        result.append(
            UnresolvedStateDispatch(
                baseline=tuple(remaining_old),
                current=tuple(remaining_new),
                reason="Rewritten or repeated state comparisons lack unique correspondence.",
            )
        )
    else:
        result.extend(RemovedStateDispatch(baseline=item) for item in remaining_old)
        result.extend(IntroducedStateDispatch(current=item) for item in remaining_new)
    return tuple(result)


def compare_state_dispatch(
    report: AnalysisReport, baseline: SourceInventory, current: SourceInventory
) -> tuple[StateDispatchChange, ...]:
    cohorts = [
        item
        for item in report.cohorts
        if isinstance(item, ComparisonCohortReport) and item.language == "python"
    ]
    files = {
        (side, file.evidence.path.root): file
        for cohort in cohorts
        for side, snapshot in (
            (SourceSide.BASELINE, cohort.baseline),
            (SourceSide.CURRENT, cohort.current),
        )
        for file in snapshot.files
    }
    documents = {
        (side, document.path.root): document
        for side, inventory in ((SourceSide.BASELINE, baseline), (SourceSide.CURRENT, current))
        for document in inventory.documents
    }
    occurrences = {
        key: inspect_state_dispatch(documents[key])
        for key, file in files.items()
        if file.evidence.parse_state is ParseState.PARSED
    }
    changes: list[StateDispatchChange] = []
    for cohort in cohorts:
        for change in cohort.changes:
            pair = change.pair
            old_path, new_path = (
                getattr(pair, "baseline_path", None),
                getattr(pair, "current_path", None),
            )
            old_key = SourceSide.BASELINE, old_path.root if old_path else ""
            new_key = SourceSide.CURRENT, new_path.root if new_path else ""
            old, new = occurrences.get(old_key, ()), occurrences.get(new_key, ())
            if not old and not new:
                continue
            left, right = files.get(old_key), files.get(new_key)
            if _uncertain(report, left, right):
                changes.append(
                    UnresolvedStateDispatch(
                        baseline=old,
                        current=new,
                        reason="One side has missing or unassessed state comparisons.",
                    )
                )
            elif left is None:
                changes.extend(IntroducedStateDispatch(current=item) for item in new)
            elif right is None:
                changes.extend(RemovedStateDispatch(baseline=item) for item in old)
            else:
                changes.extend(_match(old, new, (documents[old_key], documents[new_key])))
    return tuple(changes)
