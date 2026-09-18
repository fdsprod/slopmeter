"""Clone groups preserve populations and remove only fully contained duplicates."""

import pytest

from slop_measure.domain.evidence import CloneCandidate, FileEvidence
from slop_measure.metrics.clones import group_clones


def file(path: str, *, language: str = "python", cohort: str = "production") -> FileEvidence:
    return FileEvidence.model_validate(
        dict(
            path=path,
            language=language,
            cohort=cohort,
            parse_state="parsed",
            sloc=8,
            sloc_lines=tuple(range(1, 9)),
        )
    )


def candidate(
    path: str, start: int = 1, end: int = 4, *, syntax: str = "same", version: str = "v1"
) -> CloneCandidate:
    return CloneCandidate.model_validate(
        dict(
            path=path,
            span=dict(start_line=start, end_line=end),
            statement_count=2,
            sloc_lines=tuple(range(start, end + 1)),
            normalization_version=version,
            normalized_tokens=(syntax,),
        )
    )


def test_grouping_partitions_by_language_cohort_version_and_tokens() -> None:
    files = (
        file("a.py"),
        file("b.py"),
        file("test.py", cohort="test"),
        file("other.x", language="other"),
        file("version.py"),
        file("different.py"),
    )
    candidates = (
        *tuple(candidate(item.path.root) for item in files[:4]),
        candidate("version.py", version="v2"),
        candidate("different.py", syntax="different"),
    )
    groups = group_clones(files, candidates)
    assert len(groups) == 1
    assert tuple(member.path.root for member in groups[0].members) == ("a.py", "b.py")
    assert groups[0].language == "python"
    assert groups[0].cohort.value == "production"
    assert groups[0].normalization_version == "v1"


def test_grouping_is_independent_of_input_order() -> None:
    files = (file("b.py"), file("a.py"))
    candidates = (
        candidate("b.py", 5, 8, syntax="second"),
        candidate("a.py"),
        candidate("b.py"),
        candidate("a.py", 5, 8, syntax="second"),
    )
    forward = group_clones(files, candidates)
    reverse = group_clones(tuple(reversed(files)), tuple(reversed(candidates)))
    assert len(forward) == 2
    assert [group.model_dump_json() for group in forward] == [
        group.model_dump_json() for group in reverse
    ]


def test_fully_contained_smaller_group_collapses() -> None:
    files = (file("a.py"), file("b.py"))
    candidates = tuple(
        candidate(item.path.root, start, end, syntax=syntax)
        for item in files
        for start, end, syntax in ((1, 8, "outer"), (2, 4, "inner"))
    )
    groups = group_clones(files, candidates)
    assert len(groups) == 1
    assert all(
        member.span.start_line == 1 and member.span.end_line == 8 for member in groups[0].members
    )


def test_extra_inner_instance_prevents_containment_collapse() -> None:
    files = (file("a.py"), file("b.py"), file("c.py"))
    candidates = tuple(
        candidate(item.path.root, 1, 8, syntax="outer") for item in files[:2]
    ) + tuple(candidate(item.path.root, 2, 4, syntax="inner") for item in files)
    assert sorted(len(group.members) for group in group_clones(files, candidates)) == [2, 3]


def test_partial_overlap_groups_remain_distinct() -> None:
    files = (file("a.py"), file("b.py"))
    candidates = tuple(
        candidate(item.path.root, start, end, syntax=syntax)
        for item in files
        for start, end, syntax in ((1, 4, "first"), (3, 6, "second"))
    )
    assert len(group_clones(files, candidates)) == 2


def test_only_overlapping_self_instances_are_not_a_duplicate() -> None:
    files = (file("a.py"),)
    assert group_clones(files, (candidate("a.py", 1, 4), candidate("a.py", 3, 6))) == ()
    groups = group_clones(files, (candidate("a.py", 1, 3), candidate("a.py", 5, 7)))
    assert len(groups) == 1 and len(groups[0].members) == 2


def test_valid_group_can_also_retain_overlapping_members() -> None:
    groups = group_clones(
        (file("a.py"), file("b.py")),
        (candidate("a.py", 1, 4), candidate("a.py", 3, 6), candidate("b.py", 1, 4)),
    )
    assert len(groups) == 1 and len(groups[0].members) == 3


def test_containment_requires_distinct_enclosing_instances() -> None:
    groups = group_clones(
        (file("a.py"), file("b.py")),
        (
            candidate("a.py", 1, 8, syntax="outer"),
            candidate("b.py", 1, 8, syntax="outer"),
            candidate("a.py", 1, 3, syntax="inner"),
            candidate("a.py", 5, 7, syntax="inner"),
        ),
    )
    assert len(groups) == 2


@pytest.mark.parametrize("change", ["unknown-path", "wrong-lines", "failed-file", "duplicate-file"])
def test_grouping_rejects_contradictory_ownership(change: str) -> None:
    files = (file("a.py"),)
    candidates = (candidate("a.py"),)
    if change == "unknown-path":
        candidates = (candidate("missing.py"),)
    elif change == "wrong-lines":
        candidates = (
            CloneCandidate.model_validate({**candidate("a.py").model_dump(), "sloc_lines": (1, 4)}),
        )
    elif change == "failed-file":
        files = (FileEvidence.model_validate({**files[0].model_dump(), "parse_state": "failed"}),)
    else:
        files *= 2
    with pytest.raises(ValueError):
        group_clones(files, candidates)
