"""Owned callable evidence and explicit per-file complexity outcomes."""

import math

import pytest
from pydantic import TypeAdapter, ValidationError

from slop_measure.domain.evidence import (
    AnalyzedFunctions,
    FailedFunctions,
    FunctionAnalysis,
    FunctionEvidence,
    LanguageEvidence,
)
from slop_measure.domain.reports import FileResult


def function_payload() -> dict:
    return {
        "path": "app.py",
        "qualified_name": "calculate",
        "span": {"start_line": 2, "end_line": 5},
        "cyclomatic_complexity": 11,
        "sloc_lines": (2, 4, 5),
    }


def file_payload() -> dict:
    return {
        "path": "app.py",
        "language": "python",
        "cohort": "production",
        "sloc": 4,
        "sloc_lines": (1, 2, 4, 5),
        "parse_state": "parsed",
    }


def language_payload() -> dict:
    return {
        "language": "python",
        "capabilities": ["files", "functions"],
        "files": [file_payload()],
        "function_analyses": [
            {"state": "analyzed", "path": "app.py", "functions": [function_payload()]}
        ],
    }


def test_callable_mass_is_derived_and_json_round_trip_validates_projections() -> None:
    function = FunctionEvidence.model_validate(function_payload())
    assert function.sloc == 3
    assert function.mass == pytest.approx(11 * math.sqrt(3))
    assert function.sloc_lines == (2, 4, 5)
    assert function.model_dump(mode="json")["sloc"] == 3
    assert function.model_dump(mode="json")["mass"] == function.mass
    assert FunctionEvidence.model_validate_json(function.model_dump_json()) == function
    with pytest.raises(ValidationError):
        function.cyclomatic_complexity = 1
    for projection in ("sloc", "mass"):
        with pytest.raises((ValidationError, AttributeError)):
            setattr(function, projection, 8)


@pytest.mark.parametrize(
    "field,value",
    [
        ("cyclomatic_complexity", 0),
        ("cyclomatic_complexity", -1),
        ("cyclomatic_complexity", True),
        ("cyclomatic_complexity", 1.5),
        ("sloc_lines", ()),
        ("sloc_lines", (0, 2)),
        ("sloc_lines", (2, 2)),
        ("sloc_lines", (5, 2)),
        ("sloc_lines", (2, 6)),
        ("sloc_lines", (True, 2)),
        ("sloc_lines", (2, 4.5)),
        ("qualified_name", "  "),
        ("sloc", 4),
        ("mass", 99),
        ("parser_node", object()),
    ],
)
def test_callable_evidence_rejects_invalid_or_contradictory_fields(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        FunctionEvidence.model_validate({**function_payload(), field: value})


def test_callable_name_is_trimmed() -> None:
    assert (
        FunctionEvidence.model_validate(
            {**function_payload(), "qualified_name": " f "}
        ).qualified_name
        == "f"
    )


def test_function_analysis_union_declares_states_and_preserves_empty_success() -> None:
    adapter = TypeAdapter(FunctionAnalysis)
    result = adapter.validate_python({"state": "analyzed", "path": "app.py"})
    assert isinstance(result, AnalyzedFunctions)
    assert result.functions == ()
    schema = adapter.json_schema()
    assert schema["discriminator"]["propertyName"] == "state"
    assert set(schema["discriminator"]["mapping"]) == {"analyzed", "failed"}


@pytest.mark.parametrize("change", ["wrong-path", "warning", "missing-path"])
def test_failed_functions_require_a_same_file_error(change: str) -> None:
    diagnostic = {
        "severity": "error",
        "code": "complexity.failed",
        "message": "Failed.",
        "path": "app.py",
    }
    if change == "wrong-path":
        diagnostic["path"] = "other.py"
    elif change == "warning":
        diagnostic["severity"] = "warning"
    else:
        del diagnostic["path"]
    with pytest.raises(ValidationError):
        FailedFunctions.model_validate({"path": "app.py", "diagnostic": diagnostic})


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "extra-path",
        "no-capability",
        "failed-file",
        "wrong-function-path",
        "duplicate-function",
        "wrong-lines",
    ],
)
def test_language_function_outcomes_reconcile_with_parsed_file_evidence(change: str) -> None:
    payload = language_payload()
    outcome = payload["function_analyses"][0]
    if change == "missing":
        payload["function_analyses"] = []
    elif change == "duplicate":
        payload["function_analyses"] *= 2
    elif change == "extra-path":
        payload["function_analyses"].append(
            {"state": "analyzed", "path": "unknown.py", "functions": []}
        )
    elif change == "no-capability":
        payload["capabilities"] = ["files"]
    elif change == "failed-file":
        payload["files"][0].update(parse_state="failed", sloc=0, sloc_lines=())
    elif change == "wrong-function-path":
        outcome["functions"][0]["path"] = "other.py"
    elif change == "duplicate-function":
        outcome["functions"] *= 2
    else:
        outcome["functions"][0]["sloc_lines"] = (2, 5)
    with pytest.raises(ValidationError):
        LanguageEvidence.model_validate(payload)


def test_language_functions_are_a_read_only_flattened_view_of_canonical_outcomes() -> None:
    evidence = LanguageEvidence.model_validate(language_payload())
    assert isinstance(evidence.function_analyses, tuple)
    outcome = evidence.function_analyses[0]
    assert isinstance(outcome, AnalyzedFunctions)
    assert evidence.functions == outcome.functions
    assert "functions" not in evidence.model_dump(mode="json")
    assert "function_analyses" in evidence.model_dump(mode="json")
    assert LanguageEvidence.model_validate_json(evidence.model_dump_json()) == evidence
    with pytest.raises((ValidationError, AttributeError)):
        evidence.functions = ()  # type: ignore[reportAttributeAccessIssue]


def test_failed_parse_file_needs_no_function_analysis() -> None:
    payload = language_payload()
    payload["files"][0].update(parse_state="failed", sloc=0, sloc_lines=())
    payload["function_analyses"] = []
    assert LanguageEvidence.model_validate(payload).function_analyses == ()


def test_failed_complexity_outcome_is_distinct_from_empty_success() -> None:
    payload = language_payload()
    payload["function_analyses"] = [
        {
            "state": "failed",
            "path": "app.py",
            "diagnostic": {
                "severity": "error",
                "code": "complexity.failed",
                "message": "Failed.",
                "path": "app.py",
            },
        }
    ]
    outcome = LanguageEvidence.model_validate(payload).function_analyses[0]
    assert isinstance(outcome, FailedFunctions)


@pytest.mark.parametrize("change", ["path", "lines", "duplicate"])
def test_report_function_projection_matches_owning_file(change: str) -> None:
    functions = [function_payload()]
    if change == "path":
        functions[0]["path"] = "other.py"
    elif change == "lines":
        functions[0]["sloc_lines"] = (2, 5)
    else:
        functions *= 2
    with pytest.raises(ValidationError):
        FileResult.model_validate(
            {
                "evidence": file_payload(),
                "functions": functions,
                "score": {"state": "unavailable", "reason": "calibration-missing"},
            }
        )


def test_report_preserves_callable_evidence_and_json_round_trip() -> None:
    result = FileResult.model_validate(
        {
            "evidence": file_payload(),
            "functions": [function_payload()],
            "score": {"state": "unavailable", "reason": "calibration-missing"},
        }
    )
    assert isinstance(result.functions, tuple)
    assert result.functions[0].mass == pytest.approx(11 * math.sqrt(3))
    assert FileResult.model_validate_json(result.model_dump_json()) == result
