"""Lineage states retain their evidence and reject contradictory imported reports."""

from copy import deepcopy

import pytest
from pydantic import TypeAdapter, ValidationError

from slop_measure.domain.change_review import ChangeReviewReport, PatternChange, PatternOccurrence


def occurrence(path: str = "label.py", line: int = 2) -> dict:
    return {
        "finding": {
            "path": path,
            "rule_id": "py.literal-fstring",
            "category": "redundancy",
            "severity": "warning",
            "span": {"start_line": line, "end_line": line},
            "message": "A literal string does not need interpolation.",
        },
        "language": "python",
        "cohort": "production",
        "source_sha256": "a" * 64,
    }


def payload() -> dict:
    return {
        "analysis": {
            "kind": "comparison",
            "baseline": {"kind": "directory", "root": "before"},
            "current": {"kind": "directory", "root": "after"},
        },
        "provenance": {"tool_version": "0.5.0", "config": {}},
        "patterns": [{"state": "introduced", "current": occurrence()}],
        "limitations": [],
        "coverage": [],
        "diagnostics": [],
        "excluded_directories": [],
    }


def test_pattern_change_union_has_closed_evidence_owned_states() -> None:
    schema = TypeAdapter(PatternChange).json_schema()
    assert schema["discriminator"]["propertyName"] == "state"
    assert set(schema["discriminator"]["mapping"]) == {
        "introduced", "removed", "persisted", "changed", "unresolved"
    }


def test_report_round_trip_preserves_unscored_evidence_and_derived_summary() -> None:
    values = payload()
    values["patterns"].extend(
        [
            {"state": "removed", "baseline": occurrence("removed.py")},
            {
                "state": "persisted",
                "baseline": occurrence("stable.py", 2),
                "current": occurrence("stable.py", 4),
            },
            {
                "state": "changed",
                "baseline": occurrence("changed.py"),
                "current": {**occurrence("changed.py"), "source_sha256": "b" * 64},
            },
            {
                "state": "unresolved",
                "baseline": [occurrence("unknown.py"), occurrence("unknown.py", 5)],
                "current": [],
                "reason": "Current source cannot be parsed.",
            },
        ]
    )
    report = ChangeReviewReport.model_validate(values)
    assert report.schema_version == "1" and report.experiment == "change-review-1"
    assert report.summary == dict.fromkeys(
        ("introduced", "removed", "persisted", "changed", "unresolved"), 1
    )
    assert isinstance(report.patterns, tuple)
    assert ChangeReviewReport.model_validate_json(report.model_dump_json()) == report
    assert "score" not in report.model_dump()


@pytest.mark.parametrize(
    "change",
    [
        {"state": "introduced", "baseline": occurrence(), "current": occurrence()},
        {"state": "removed", "baseline": occurrence(), "current": occurrence()},
        {"state": "persisted", "current": occurrence()},
        {"state": "changed", "baseline": occurrence()},
        {"state": "unresolved", "baseline": [], "current": [], "reason": "Unknown"},
        {"state": "unresolved", "baseline": [occurrence()], "reason": " "},
        {"state": "fixed", "baseline": occurrence()},
    ],
)
def test_contradictory_or_empty_states_cannot_be_imported(change) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(PatternChange).validate_python(change)


@pytest.mark.parametrize("invalid_hash", ["", "a" * 63, "g" * 64])
def test_occurrences_require_complete_source_hashes(invalid_hash) -> None:
    with pytest.raises(ValidationError):
        PatternOccurrence.model_validate({**occurrence(), "source_sha256": invalid_hash})


def test_supplied_summary_must_match_owned_evidence() -> None:
    values = payload()
    report = ChangeReviewReport.model_validate(values)
    imported = report.model_dump(mode="json")
    assert ChangeReviewReport.model_validate(imported) == report
    altered = deepcopy(imported)
    altered["summary"]["introduced"] = 0
    with pytest.raises(ValidationError):
        ChangeReviewReport.model_validate(altered)


@pytest.mark.parametrize("field,value", [("schema_version", "2"), ("score", 42)])
def test_report_rejects_unknown_schema_and_score_fields(field, value) -> None:
    with pytest.raises(ValidationError):
        ChangeReviewReport.model_validate({**payload(), field: value})


def test_occurrence_and_report_are_immutable() -> None:
    report = ChangeReviewReport.model_validate(payload())
    item = PatternOccurrence.model_validate(occurrence())
    with pytest.raises(ValidationError):
        report.patterns = ()
    with pytest.raises(ValidationError):
        item.source_sha256 = "b" * 64
