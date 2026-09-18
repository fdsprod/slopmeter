"""M1 counts owned source lines after matching complete byte-line sequences."""

import pytest

from slop_measure.domain.changes import (
    FileChange,
    MeasuredLineDelta,
    MeasuredLineTotals,
    UnavailableLineDelta,
)
from slop_measure.domain.evidence import FileEvidence
from slop_measure.domain.source import SourceDocument
from slop_measure.metrics.loc_delta import measure_line_delta, sum_line_deltas


def side(content: bytes, lines: tuple[int, ...], *, path: str = "app.py", failed: bool = False):
    document = SourceDocument.model_validate(
        {"path": path, "content": content, "language": "python", "cohort": "production"}
    )
    evidence = FileEvidence.model_validate(
        {
            "path": path,
            "language": "python",
            "cohort": "production",
            "sloc": len(lines),
            "sloc_lines": lines,
            "parse_state": "failed" if failed else "parsed",
        }
    )
    return document, evidence


def diff(
    before: bytes, old_lines: tuple[int, ...], after: bytes, new_lines: tuple[int, ...]
) -> MeasuredLineDelta:
    old, old_evidence = side(before, old_lines)
    new, new_evidence = side(after, new_lines)
    result = measure_line_delta(old, new, old_evidence, new_evidence)
    assert isinstance(result, MeasuredLineDelta)
    assert result.net == len(new_lines) - len(old_lines)
    return result


def test_replacement_and_insertions_intersect_their_own_source_line_sets() -> None:
    result = diff(
        b"keep\n# comment\nold\n", (1, 3), b"keep\n# new comment\nnew\nextra\n", (1, 3, 4)
    )
    assert result.added_lines == (3, 4)
    assert result.deleted_lines == (3,)
    assert (result.added, result.deleted, result.net) == (2, 1, 1)
    assert result.growth.state == "measured"
    assert result.growth.value == 0.5


def test_complete_line_alignment_does_not_match_filtered_source_lines_out_of_context() -> None:
    result = diff(b"x\ntext\nx\n", (1, 3), b"x\nx\ntext\nx\n", (1, 2, 4))
    assert result.added_lines == (1,)
    assert result.deleted_lines == ()


def test_equal_text_that_changes_source_membership_counts_as_added_and_deleted() -> None:
    result = diff(b"a\nb\nc\n", (1, 2), b"a\nb\nc\n", (2, 3))
    assert result.added_lines == (3,)
    assert result.deleted_lines == (1,)
    assert result.net == 0


@pytest.mark.parametrize("after", [b"a\nb", b"a\r\nb\r\n", b"a\rb\r"])
def test_line_terminators_and_final_newline_do_not_count_as_churn(after: bytes) -> None:
    result = diff(b"a\nb\n", (1, 2), after, (1, 2))
    assert result.added_lines == result.deleted_lines == ()


def test_non_utf8_bytes_are_compared_without_decoding() -> None:
    result = diff(b"\xff\nold\n", (1, 2), b"\xff\nnew\n", (1, 2))
    assert result.added_lines == result.deleted_lines == (2,)


def test_repeated_lines_use_exact_matching_without_autojunk() -> None:
    before = b"a\n" * 250 + b"b\n"
    after = b"b\n" + b"a\n" * 250
    result = diff(before, tuple(range(1, 252)), after, tuple(range(1, 252)))
    assert result.added_lines == (1,)
    assert result.deleted_lines == (251,)


def test_added_deleted_and_empty_files_have_explicit_growth_states() -> None:
    document, evidence = side(b"x\n#comment\ny\n", (1, 3))
    added = measure_line_delta(None, document, None, evidence)
    deleted = measure_line_delta(document, None, evidence, None)
    assert isinstance(added, MeasuredLineDelta)
    assert isinstance(deleted, MeasuredLineDelta)
    assert added.added_lines == deleted.deleted_lines == (1, 3)
    assert added.baseline_sloc == deleted.current_sloc == 0
    assert added.growth.state == "unavailable"
    assert added.growth.reason == "no-baseline-sloc"
    assert deleted.growth.state == "measured"
    assert deleted.growth.value == -1
    empty = diff(b"", (), b"", ())
    assert empty.growth.state == "unavailable"


def test_exact_rename_has_zero_churn_but_parse_failure_stays_unavailable() -> None:
    old, old_evidence = side(b"x\n", (1,), path="old.py")
    new, new_evidence = side(b"x\n", (1,), path="new.py")
    result = measure_line_delta(old, new, old_evidence, new_evidence)
    assert isinstance(result, MeasuredLineDelta)
    assert result.added == result.deleted == 0
    failed, failed_evidence = side(b"x\n", (), path="new.py", failed=True)
    unavailable = measure_line_delta(old, failed, old_evidence, failed_evidence)
    assert isinstance(unavailable, UnavailableLineDelta)
    assert unavailable.reason == "parse-failed"


def test_missing_both_sides_and_mismatched_evidence_are_invalid() -> None:
    with pytest.raises(ValueError):
        measure_line_delta(None, None, None, None)
    document, evidence = side(b"x", (1,))
    _, wrong = side(b"x", (1,), path="wrong.py")
    with pytest.raises(ValueError):
        measure_line_delta(document, document, evidence, wrong)
    with pytest.raises(ValueError):
        measure_line_delta(document, None, None, None)


def change(path: str, lines: MeasuredLineDelta | UnavailableLineDelta) -> FileChange:
    return FileChange.model_validate(
        {
            "pair": {"kind": "modified", "baseline_path": path, "current_path": path},
            "lines": lines,
            "deltas": [],
        }
    )


def test_project_totals_sum_evidence_without_averaging_growth() -> None:
    first = diff(b"a\nb\n", (1, 2), b"a\nb\nc\n", (1, 2, 3))
    second = diff(b"a\n", (1,), b"", ())
    result = sum_line_deltas((change("a.py", first), change("b.py", second)))
    assert isinstance(result, MeasuredLineTotals)
    assert (
        result.baseline_sloc,
        result.current_sloc,
        result.added,
        result.deleted,
        result.net,
    ) == (3, 3, 1, 1, 0)
    assert result.growth.state == "measured"
    assert result.growth.value == 0
    empty = sum_line_deltas(())
    assert isinstance(empty, MeasuredLineTotals)
    assert empty.net == 0
    assert empty.growth.state == "unavailable"


def test_any_unavailable_file_makes_project_line_delta_unavailable() -> None:
    measured = change("a.py", diff(b"x", (1,), b"y", (1,)))
    failed = change("b.py", UnavailableLineDelta.model_validate({"reason": "parse-failed"}))
    result = sum_line_deltas((measured, failed))
    assert isinstance(result, UnavailableLineDelta)
    assert result.reason == "parse-failed"


def test_missing_document_with_failed_evidence_is_unavailable_not_deleted() -> None:
    old, old_evidence = side(b"source", (1,))
    _, failed = side(b"", (), failed=True)
    result = measure_line_delta(old, None, old_evidence, failed)
    assert isinstance(result, UnavailableLineDelta)
    assert result.reason == "parse-failed"
