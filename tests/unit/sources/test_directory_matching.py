"""Directory pairs preserve population and exact complete-byte identity."""

import pytest

from slop_measure.domain.evidence import FileEvidence
from slop_measure.domain.source import SourceDocument
from slop_measure.sources.compare import match_files


def document(
    path: str, content: bytes, *, cohort: str = "production", language: str = "python"
) -> SourceDocument:
    return SourceDocument.model_validate(
        {"path": path, "content": content, "cohort": cohort, "language": language}
    )


def pairs(baseline: tuple[SourceDocument, ...], current: tuple[SourceDocument, ...]) -> list[dict]:
    return [pair.model_dump(mode="json") for pair in match_files(baseline, current)]


def test_matching_equal_paths_takes_precedence_over_content_rename_candidates() -> None:
    baseline = (document("a.py", b"old"), document("b.py", b"new"))
    current = (document("a.py", b"new"), document("c.py", b"new"))
    assert pairs(baseline, current) == [
        {"kind": "modified", "baseline_path": "a.py", "current_path": "a.py"},
        {"kind": "renamed", "baseline_path": "b.py", "current_path": "c.py"},
    ]


def test_duplicate_content_renames_pair_lexically_regardless_of_input_order() -> None:
    baseline = (document("z.py", b"same"), document("a.py", b"same"))
    current = (document("y.py", b"same"), document("b.py", b"same"))
    expected = [
        {"kind": "renamed", "baseline_path": "a.py", "current_path": "b.py"},
        {"kind": "renamed", "baseline_path": "z.py", "current_path": "y.py"},
    ]
    assert pairs(baseline, current) == expected
    assert pairs(tuple(reversed(baseline)), tuple(reversed(current))) == expected


@pytest.mark.parametrize("field,value", [("cohort", "test"), ("language", "other")])
def test_path_or_content_never_matches_across_population_boundary(field: str, value: str) -> None:
    old = document("same.py", b"same")
    new = old.model_copy(update={field: value})
    results = pairs((old,), (new,))
    assert {item["kind"] for item in results} == {"added", "deleted"}
    assert len(results) == 2


def test_hash_collision_cannot_pair_different_complete_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(SourceDocument, "content_hash", property(lambda _self: "collision"))
    results = pairs((document("old.py", b"old"),), (document("new.py", b"new"),))
    assert {item["kind"] for item in results} == {"added", "deleted"}


def test_unchanged_requires_identical_bytes_and_matching_paths() -> None:
    same = document("same.py", b"a\n")
    assert pairs((same,), (same,)) == [
        {"kind": "unchanged", "baseline_path": "same.py", "current_path": "same.py"}
    ]
    assert pairs((same,), (document("same.py", b"a\r\n"),))[0]["kind"] == "modified"
    assert {item["kind"] for item in pairs((same,), (document("renamed.py", b"a\r\n"),))} == {
        "added",
        "deleted",
    }
    assert match_files((), ()) == ()


def test_deletions_interleave_with_current_paths_in_stable_display_order() -> None:
    baseline = (document("b.py", b"deleted"), document("z.py", b"changed"))
    current = (document("z.py", b"new"), document("a.py", b"added"))
    assert [item["kind"] for item in pairs(baseline, current)] == ["added", "deleted", "modified"]


def unreadable(path: str) -> FileEvidence:
    return FileEvidence.model_validate(
        {
            "path": path,
            "language": "python",
            "cohort": "production",
            "sloc": 0,
            "sloc_lines": [],
            "parse_state": "failed",
        }
    )


def test_unreadable_equal_paths_are_unresolved_and_unmatched_paths_are_retained() -> None:
    result = match_files(
        (document("same.py", b"known"),),
        (),
        baseline_unreadable=(unreadable("old.py"),),
        current_unreadable=(unreadable("same.py"), unreadable("new.py")),
    )
    assert [pair.model_dump(mode="json") for pair in result] == [
        {"kind": "added", "current_path": "new.py"},
        {"kind": "deleted", "baseline_path": "old.py"},
        {"kind": "unresolved", "baseline_path": "same.py", "current_path": "same.py"},
    ]
    both = match_files(
        (),
        (),
        baseline_unreadable=(unreadable("same.py"),),
        current_unreadable=(unreadable("same.py"),),
    )
    assert both[0].kind == "unresolved"


def test_unreadable_entries_require_failure_and_cannot_duplicate_documents() -> None:
    failure = unreadable("app.py")
    with pytest.raises(ValueError):
        match_files((document("app.py", b"source"),), (), baseline_unreadable=(failure,))
    with pytest.raises(ValueError):
        match_files(
            (), (), current_unreadable=(failure.model_copy(update={"parse_state": "parsed"}),)
        )
