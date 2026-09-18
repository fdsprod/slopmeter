"""Comparison states retain exact side-owned line evidence and checked totals."""

import pytest
from pydantic import TypeAdapter, ValidationError

from slop_measure.domain.changes import (
    AddedFile,
    DeletedFile,
    FileChange,
    FilePair,
    MeasuredLineDelta,
    MeasuredLineTotals,
    MeasuredMetricDelta,
    ModifiedFile,
    RenamedFile,
    UnavailableLineDelta,
    UnavailableMetricDelta,
    UnchangedFile,
    UnresolvedFile,
)


def lines() -> dict:
    return {"baseline_sloc": 3, "current_sloc": 4, "added_lines": (4, 7), "deleted_lines": (2,)}


def test_pair_union_has_six_explicit_discriminated_states() -> None:
    adapter = TypeAdapter(FilePair)
    assert set(adapter.json_schema()["discriminator"]["mapping"]) == {
        "added",
        "deleted",
        "modified",
        "renamed",
        "unchanged",
        "unresolved",
    }
    assert isinstance(adapter.validate_python({"kind": "added", "current_path": "a.py"}), AddedFile)
    assert isinstance(
        adapter.validate_python({"kind": "deleted", "baseline_path": "a.py"}), DeletedFile
    )
    for kind, cls in (
        ("modified", ModifiedFile),
        ("unchanged", UnchangedFile),
        ("renamed", RenamedFile),
        ("unresolved", UnresolvedFile),
    ):
        pair = adapter.validate_python(
            {
                "kind": kind,
                "baseline_path": "a.py",
                "current_path": "b.py" if kind == "renamed" else "a.py",
            }
        )
        assert isinstance(pair, cls)


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "added", "baseline_path": "a.py", "current_path": "b.py"},
        {"kind": "deleted", "baseline_path": "a.py", "current_path": "b.py"},
        {"kind": "modified", "baseline_path": "a.py", "current_path": "b.py"},
        {"kind": "unchanged", "baseline_path": "a.py", "current_path": "b.py"},
        {"kind": "renamed", "baseline_path": "a.py", "current_path": "a.py"},
    ],
)
def test_pair_shape_cannot_represent_conflicting_states(payload: dict) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(FilePair).validate_python(payload)


def test_line_delta_round_trips_derived_counts_and_growth() -> None:
    delta = MeasuredLineDelta(**lines())
    assert (delta.added, delta.deleted, delta.net) == (2, 1, 1)
    assert delta.growth.state == "measured"
    assert delta.growth.value == pytest.approx(1 / 3)
    assert MeasuredLineDelta.model_validate_json(delta.model_dump_json()) == delta
    with pytest.raises(ValidationError):
        delta.current_sloc = 8


@pytest.mark.parametrize(
    "field,value",
    [
        ("added_lines", (4, 4)),
        ("added_lines", (7, 4)),
        ("deleted_lines", (0,)),
        ("baseline_sloc", True),
        ("current_sloc", -1),
        ("current_sloc", 5),
        ("added_lines", (True, 7)),
    ],
)
def test_line_evidence_rejects_invalid_membership_or_net_identity(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        MeasuredLineDelta.model_validate({**lines(), field: value})


@pytest.mark.parametrize("field", ["added", "deleted", "net", "growth"])
def test_serialized_derived_line_values_cannot_contradict_authoritative_inputs(field: str) -> None:
    payload = MeasuredLineDelta(**lines()).model_dump(mode="json")
    payload[field] = {"state": "measured", "value": 9} if field == "growth" else 99
    with pytest.raises(ValidationError):
        MeasuredLineDelta.model_validate(payload)


@pytest.mark.parametrize("current", [0, 2])
def test_zero_baseline_has_explicit_unavailable_growth(current: int) -> None:
    delta = MeasuredLineDelta(
        baseline_sloc=0,
        current_sloc=current,
        added_lines=tuple(range(1, current + 1)),
        deleted_lines=(),
    )
    assert delta.growth.model_dump() == {"state": "unavailable", "reason": "no-baseline-sloc"}


def test_project_totals_use_same_net_and_growth_contract() -> None:
    totals = MeasuredLineTotals(baseline_sloc=3, current_sloc=1, added=1, deleted=3)
    assert totals.net == -2
    assert totals.growth.state == "measured"
    assert totals.growth.value == pytest.approx(-2 / 3)
    assert MeasuredLineTotals.model_validate_json(totals.model_dump_json()) == totals
    with pytest.raises(ValidationError):
        MeasuredLineTotals(baseline_sloc=3, current_sloc=1, added=0, deleted=1)


def test_unavailable_and_metric_delta_states_remain_explicit() -> None:
    failed = UnavailableLineDelta(reason="parse-failed")
    assert failed.state == "unavailable"
    assert "net" not in failed.model_dump()
    for reason in (
        "missing-baseline",
        "missing-current",
        "unavailable-input",
        "incompatible-definitions",
    ):
        assert UnavailableMetricDelta(metric_id="m4.erosion", reason=reason).state == "unavailable"
    assert MeasuredMetricDelta(metric_id="m4.erosion", value=-0.5, unit="ratio").value == -0.5
    with pytest.raises(ValidationError):
        MeasuredMetricDelta(metric_id="m4.erosion", value=float("nan"), unit="ratio")


def test_file_change_rejects_duplicate_metric_delta_ids() -> None:
    delta = {"metric_id": "m4.erosion", "value": 0.1, "unit": "ratio"}
    with pytest.raises(ValidationError):
        FileChange(
            pair={"kind": "modified", "baseline_path": "a.py", "current_path": "a.py"},
            lines=lines(),
            deltas=(delta, delta),
        )
