"""Compare complete byte lines, then account for each side's owned source lines."""

from difflib import SequenceMatcher

from slop_measure.domain.changes import (
    FileChange,
    LineDelta,
    LineTotals,
    MeasuredLineDelta,
    MeasuredLineTotals,
    UnavailableLineDelta,
)
from slop_measure.domain.evidence import FileEvidence, ParseState
from slop_measure.domain.metrics import UnavailableReason
from slop_measure.domain.source import SourceDocument


def _validate_side(document: SourceDocument | None, file: FileEvidence | None) -> None:
    if file is None:
        if document is not None:
            raise ValueError("A source document requires its owning file evidence.")
        return
    if document is None:
        if file.parse_state is ParseState.PARSED:
            raise ValueError("A parsed file requires its complete source document.")
        return
    if (document.path, document.language, document.cohort) != (
        file.path,
        file.language,
        file.cohort,
    ):
        raise ValueError("Comparison source must match its file evidence.")


def _byte_lines(document: SourceDocument | None) -> tuple[bytes, ...]:
    content = document.content if document is not None else b""
    lines = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    return tuple(lines)


def _owned_lines(file: FileEvidence | None, line_count: int) -> set[int]:
    lines = set(file.sloc_lines) if file is not None else set()
    if lines and max(lines) > line_count:
        raise ValueError("Owned source lines cannot extend beyond the complete source.")
    return lines


def _changed_lines(
    before: tuple[bytes, ...], after: tuple[bytes, ...], old: set[int], new: set[int]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    added: set[int] = set()
    deleted: set[int] = set()
    for kind, old_start, old_end, new_start, new_end in SequenceMatcher(
        None, before, after, autojunk=False
    ).get_opcodes():
        if kind == "equal":
            for old_index, new_index in zip(
                range(old_start + 1, old_end + 1), range(new_start + 1, new_end + 1), strict=True
            ):
                if old_index in old and new_index not in new:
                    deleted.add(old_index)
                elif new_index in new and old_index not in old:
                    added.add(new_index)
        else:
            deleted.update(old.intersection(range(old_start + 1, old_end + 1)))
            added.update(new.intersection(range(new_start + 1, new_end + 1)))
    return tuple(sorted(added)), tuple(sorted(deleted))


def measure_line_delta(
    baseline: SourceDocument | None,
    current: SourceDocument | None,
    baseline_file: FileEvidence | None,
    current_file: FileEvidence | None,
) -> LineDelta:
    """Return exact added and deleted SLOC, or explicit source failure."""
    if baseline_file is None and current_file is None:
        raise ValueError("A line comparison requires at least one file.")
    _validate_side(baseline, baseline_file)
    _validate_side(current, current_file)
    if (
        baseline_file is not None
        and current_file is not None
        and (baseline_file.language, baseline_file.cohort)
        != (current_file.language, current_file.cohort)
    ):
        raise ValueError("A line comparison cannot cross language or cohort boundaries.")
    if any(
        file is not None and file.parse_state is ParseState.FAILED
        for file in (baseline_file, current_file)
    ):
        return UnavailableLineDelta(reason=UnavailableReason.PARSE_FAILED)
    before, after = _byte_lines(baseline), _byte_lines(current)
    old, new = _owned_lines(baseline_file, len(before)), _owned_lines(current_file, len(after))
    added, deleted = _changed_lines(before, after, old, new)
    return MeasuredLineDelta(
        baseline_sloc=len(old), current_sloc=len(new), added_lines=added, deleted_lines=deleted
    )


def sum_line_deltas(changes: tuple[FileChange, ...]) -> LineTotals:
    """Sum complete line evidence without averaging file growth rates."""
    unavailable = tuple(
        change.lines for change in changes if isinstance(change.lines, UnavailableLineDelta)
    )
    if unavailable:
        return min(
            unavailable,
            key=lambda item: (item.reason is not UnavailableReason.PARSE_FAILED, item.reason.value),
        )
    measured = tuple(
        change.lines for change in changes if isinstance(change.lines, MeasuredLineDelta)
    )
    return MeasuredLineTotals(
        baseline_sloc=sum(item.baseline_sloc for item in measured),
        current_sloc=sum(item.current_sloc for item in measured),
        added=sum(item.added for item in measured),
        deleted=sum(item.deleted for item in measured),
    )
