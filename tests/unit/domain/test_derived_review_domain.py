"""Derived-state review retains ordered evidence and explicit uncertainty."""

import pytest
from pydantic import ValidationError

from slop_measure.domain.derived_review import AnalyzedDerivedFunction, DerivedStateFinding


def finding() -> dict:
    return dict(
        derived_name="count",
        source_name="items",
        mutation_kind="append",
        derivation=dict(start_line=3, end_line=3),
        mutation=dict(start_line=4, end_line=4),
        read=dict(start_line=5, end_line=5),
    )


def test_derived_evidence_is_frozen_owned_and_roundtrips() -> None:
    result = AnalyzedDerivedFunction.model_validate(
        dict(symbol="work", span=dict(start_line=1, end_line=5), findings=[finding()])
    )
    assert result.state == "analyzed" and isinstance(result.findings, tuple)
    assert result.findings[0].kind == "stale-derived-state"
    assert AnalyzedDerivedFunction.model_validate_json(result.model_dump_json()) == result
    with pytest.raises(ValidationError):
        result.symbol = "changed"


@pytest.mark.parametrize(
    "change",
    ["same-name", "blank-name", "wrong-order", "outside-function", "unknown-mutation", "extra"],
)
def test_invalid_derived_evidence_cannot_be_reported(change: str) -> None:
    evidence = finding()
    if change == "same-name":
        evidence["derived_name"] = "items"
    elif change == "blank-name":
        evidence["source_name"] = " "
    elif change == "wrong-order":
        evidence["mutation"] = dict(start_line=2, end_line=2)
    elif change == "outside-function":
        evidence["read"] = dict(start_line=8, end_line=8)
    elif change == "unknown-mutation":
        evidence["mutation_kind"] = "unknown"
    else:
        evidence["runtime_object"] = object()
    with pytest.raises(ValidationError):
        AnalyzedDerivedFunction.model_validate(
            dict(symbol="work", span=dict(start_line=1, end_line=5), findings=[evidence])
        )


def test_same_line_order_is_representable_without_inventing_columns() -> None:
    data = finding()
    for field in ("derivation", "mutation", "read"):
        data[field] = dict(start_line=2, end_line=2)
    assert DerivedStateFinding.model_validate(data).read.start_line == 2
