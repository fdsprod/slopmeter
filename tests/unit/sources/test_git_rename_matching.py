"""Git rename hints pair eligible edited files without crossing source populations."""

import pytest
from test_directory_matching import document

from slop_measure.domain.source import ProjectPath, SourceDocument
from slop_measure.sources.compare import match_files


def hints(*pairs: tuple[str, str]) -> tuple[tuple[ProjectPath, ProjectPath], ...]:
    return tuple((ProjectPath(old), ProjectPath(new)) for old, new in pairs)


def test_known_git_hint_pairs_changed_content_before_exact_content_candidates() -> None:
    old = (document("old.py", b"old"), document("other.py", b"new"))
    new = (document("new.py", b"new"),)
    pairs = match_files(old, new, renames=hints(("old.py", "new.py")))
    assert [pair.model_dump(mode="json") for pair in pairs] == [
        {"kind": "renamed", "baseline_path": "old.py", "current_path": "new.py"},
        {"kind": "deleted", "baseline_path": "other.py"},
    ]


def test_same_path_pairs_take_precedence_over_rename_hints() -> None:
    pairs = match_files(
        (document("a.py", b"old"),),
        (document("a.py", b"changed"), document("b.py", b"other")),
        renames=hints(("a.py", "b.py")),
    )
    assert [pair.kind for pair in pairs] == ["modified", "added"]


def test_absent_or_excluded_hint_endpoints_do_not_create_phantom_changes() -> None:
    old, new = (document("a.py", b"old"),), (document("b.py", b"new"),)
    pairs = match_files(old, new, renames=hints(("excluded.py", "b.py"), ("a.py", "absent.py")))
    assert {pair.kind for pair in pairs} == {"added", "deleted"}


@pytest.mark.parametrize("field,value", [("cohort", "test"), ("language", "other")])
def test_git_rename_hints_cannot_cross_population_boundaries(field: str, value: str) -> None:
    old = document("a.py", b"old")
    new = SourceDocument.model_validate(
        {**document("b.py", b"new").model_dump(exclude={"content_hash"}), field: value}
    )
    pairs = match_files((old,), (new,), renames=hints(("a.py", "b.py")))
    assert {pair.kind for pair in pairs} == {"added", "deleted"}


@pytest.mark.parametrize(
    "renames",
    [
        (("a.py", "b.py"), ("a.py", "c.py")),
        (("a.py", "b.py"), ("d.py", "b.py")),
        (("a.py", "b.py"), ("a.py", "b.py")),
    ],
)
def test_duplicate_hint_endpoints_are_rejected(renames: tuple[tuple[str, str], ...]) -> None:
    with pytest.raises(ValueError):
        match_files((), (), renames=hints(*renames))
