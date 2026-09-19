"""Variant coverage is derived from owned unconditional branches, never trusted JSON."""

import pytest
from pydantic import ValidationError

from slop_measure.domain.variant_review import AnalyzedVariantHandler


def payload() -> dict:
    return {
        "state": "analyzed",
        "symbol": "render",
        "subject": "value",
        "span": {"start_line": 6, "end_line": 12},
        "declaration": {
            "name": "Color",
            "kind": "enum",
            "span": {"start_line": 2, "end_line": 4},
            "cases": [
                {"name": "Color.RED", "span": {"start_line": 3, "end_line": 3}},
                {"name": "Color.BLUE", "span": {"start_line": 4, "end_line": 4}},
            ],
        },
        "branches": [
            {"kind": "cases", "span": {"start_line": 7, "end_line": 8}, "cases": ["Color.RED"]}
        ],
    }


@pytest.mark.parametrize(
    "mode,expected", [("plain", "missing"), ("fallback", "fallback"), ("complete", "exhaustive")]
)
def test_coverage_and_not_explicitly_covered_names_are_derived_frozen_and_roundtrip(
    mode: str, expected: str
) -> None:
    data = payload()
    if mode == "fallback":
        data["branches"].append({"kind": "fallback", "span": {"start_line": 9, "end_line": 10}})
    elif mode == "complete":
        data["branches"][0]["cases"].append("Color.BLUE")
    handler = AnalyzedVariantHandler.model_validate(data)
    wire = handler.model_dump(mode="json")
    assert wire["coverage"] == expected
    assert wire["not_explicitly_covered"] == ([] if mode == "complete" else ["Color.BLUE"])
    assert AnalyzedVariantHandler.model_validate(wire) == handler
    with pytest.raises(ValidationError):
        handler.subject = "other"


@pytest.mark.parametrize(
    "invalid",
    [
        "duplicate-case",
        "unknown-branch-case",
        "outside-span",
        "empty-explicit",
        "forged-coverage",
        "forged-not-explicitly-covered",
    ],
)
def test_invalid_or_forged_variant_evidence_is_rejected(invalid: str) -> None:
    data = payload()
    if invalid == "duplicate-case":
        data["declaration"]["cases"].append(data["declaration"]["cases"][0])
    elif invalid == "unknown-branch-case":
        data["branches"][0]["cases"] = ["Color.UNKNOWN"]
    elif invalid == "outside-span":
        data["branches"][0]["span"] = {"start_line": 20, "end_line": 21}
    elif invalid == "empty-explicit":
        data["branches"][0]["cases"] = []
    elif invalid == "forged-coverage":
        data["coverage"] = "exhaustive"
    else:
        data["not_explicitly_covered"] = []
    with pytest.raises(ValidationError):
        AnalyzedVariantHandler.model_validate(data)
