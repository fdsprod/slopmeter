"""Independent controls for multiple clone sites and competing correspondence."""

from pathlib import Path
from textwrap import indent

import pytest
from test_modified_clone_continuity import EDITED, ORIGINAL, clone_budget, compare, copies


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    result = tmp_path / "baseline", tmp_path / "current"
    for root in result:
        root.mkdir()
    return result


def two_runs(*, nested: bool, changed: bool) -> str:
    body = "\n".join((EDITED if changed else ORIGINAL).splitlines()[1:]) + "\n"
    first = body.replace("    return remaining\n", "    checkpoint(remaining)\n")
    second = body.replace("producer.produce", "producer.deliver")
    if nested:
        return (
            ORIGINAL.splitlines()[0]
            + "\n    if enabled:\n"
            + indent(first, "    ")
            + "    else:\n"
            + indent(second, "    ")
        )
    return ORIGINAL.splitlines()[0] + "\n" + first + "    import runtime_marker\n" + second


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("changed", [False, True])
def test_distinct_runs_in_one_declaration_keep_their_own_correspondence(roots, nested, changed):
    copies(roots[0], two_runs(nested=nested, changed=False))
    copies(roots[1], two_runs(nested=nested, changed=changed))
    report = compare(roots)
    assert len(report.clones) == 2
    expected = "changed" if changed else "persisted"
    assert {group.state.value for group in report.clones} == {expected}
    assert all(group.added == group.removed == 0 for group in report.clones)
    assert clone_budget(report).state.value == "pass"


def test_two_groups_merging_do_not_get_an_arbitrary_predecessor(roots):
    copies(roots[0], ORIGINAL)
    alternative = ORIGINAL.replace("    record(topic)\n", "    record(topic)\n    audit(payload)\n")
    for index in (2, 3):
        (roots[0] / f"publisher_{index}.py").write_text(alternative, encoding="utf-8")
    copies(roots[1], EDITED)
    report = compare(roots)
    assert any(group.state.value == "unresolved" for group in report.clones)
    assert clone_budget(report).state.value == "incomplete"


def test_duplicate_qualified_declarations_cannot_establish_unique_changed_ownership(roots):
    copies(roots[0], ORIGINAL + "\n" + ORIGINAL)
    copies(roots[1], EDITED + "\n" + EDITED)
    report = compare(roots)
    assert report.clones
    assert all(group.state.value == "unresolved" for group in report.clones)
    assert clone_budget(report).state.value == "incomplete"
