"""Family projections cannot contradict their source-owned member evidence."""

import pytest
from pydantic import TypeAdapter, ValidationError

from slop_measure.domain.clone_changes import CloneGroupChange, CloneMemberChange
from slop_measure.domain.error_changes import ErrorChange


def clone(path: str) -> dict:
    return {
        "member": {
            "path": path,
            "span": {"start_line": 2, "end_line": 3},
            "sloc_lines": [2, 3],
        },
        "source_sha256": "a" * 64,
    }


def group_payload() -> dict:
    return {
        "language": "python",
        "cohort": "production",
        "normalization_version": "py-clones-1",
        "fingerprint": "b" * 64,
        "members": [
            {"state": "persisted", "baseline": clone("a.py"), "current": clone("a.py")},
            {"state": "introduced", "current": clone("b.py")},
        ],
    }


def test_clone_group_derives_new_relation_from_one_existing_and_one_new_instance() -> None:
    group = CloneGroupChange.model_validate(group_payload())
    assert group.state == "introduced" and group.added == 1 and group.removed == 0
    assert len(group.baseline) == 1 and len(group.current) == 2
    assert CloneGroupChange.model_validate_json(group.model_dump_json()) == group


@pytest.mark.parametrize(
    "field,value",
    [("added", True), ("added", 2), ("removed", 1), ("state", "persisted"), ("baseline", [])],
)
def test_clone_group_rejects_forged_computed_projections(field, value) -> None:
    imported = CloneGroupChange.model_validate(group_payload()).model_dump(mode="json")
    imported[field] = value
    with pytest.raises(ValidationError):
        CloneGroupChange.model_validate(imported)


def test_clone_group_rejects_duplicate_side_ownership() -> None:
    payload = group_payload()
    payload["members"].append({"state": "introduced", "current": clone("a.py")})
    with pytest.raises(ValidationError):
        CloneGroupChange.model_validate(payload)


def test_unresolved_clone_member_retains_known_baseline_without_claiming_removal() -> None:
    payload = group_payload()
    payload["members"][1] = {
        "state": "unresolved",
        "baseline": [clone("b.py")],
        "current": [],
        "reason": "Current file could not be parsed.",
    }
    group = CloneGroupChange.model_validate(payload)
    assert group.state == "unresolved" and group.removed == group.added == 0
    assert len(group.baseline) == 2 and len(group.current) == 1


def test_clone_member_states_are_explicit_and_empty_uncertainty_is_invalid() -> None:
    adapter = TypeAdapter(CloneMemberChange)
    assert set(adapter.json_schema()["discriminator"]["mapping"]) == {
        "introduced",
        "removed",
        "persisted",
        "unresolved",
    }
    with pytest.raises(ValidationError):
        adapter.validate_python({"state": "unresolved", "reason": "Unknown"})


def error_occurrence() -> dict:
    expression = {"span": {"start_line": 5, "end_line": 5}, "expression": "[]"}
    return {
        "path": "fetch.py",
        "language": "python",
        "cohort": "production",
        "source_sha256": "c" * 64,
        "symbol": "fetch",
        "span": {"start_line": 4, "end_line": 5},
        "finding": {
            "kind": "error-as-success",
            "caught": "OSError",
            "protected": {"start_line": 3, "end_line": 3},
            "operations": [
                {"span": {"start_line": 3, "end_line": 3}, "expression": "client.read()"}
            ],
            "fallback": expression,
            "fallback_kind": "empty-list",
            "normal_returns": [{"span": {"start_line": 6, "end_line": 6}, "expression": "result"}],
        },
    }


def test_error_change_union_retains_existing_finding_and_explicit_states() -> None:
    adapter = TypeAdapter(ErrorChange)
    assert set(adapter.json_schema()["discriminator"]["mapping"]) == {
        "introduced",
        "removed",
        "persisted",
        "changed",
        "unresolved",
    }
    changed = adapter.validate_python({"state": "introduced", "current": error_occurrence()})
    assert adapter.validate_json(changed.model_dump_json()) == changed
    assert changed.state == "introduced"
    assert changed.current.finding.fallback_kind == "empty-list"


@pytest.mark.parametrize(
    "payload",
    [
        {"state": "removed", "baseline": error_occurrence(), "current": error_occurrence()},
        {"state": "changed", "baseline": error_occurrence()},
        {"state": "unresolved", "baseline": [], "current": [], "reason": "Unknown"},
        {"state": "unresolved", "baseline": [error_occurrence()], "reason": " "},
    ],
)
def test_error_change_rejects_contradictory_or_empty_evidence(payload) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(ErrorChange).validate_python(payload)
