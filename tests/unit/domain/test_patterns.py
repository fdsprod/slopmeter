"""Pattern evidence, explicit outcomes, and report source ownership contracts."""

import pytest
from pydantic import TypeAdapter, ValidationError

from slop_measure.domain.evidence import (
    AnalyzedPatterns,
    FailedPatterns,
    LanguageEvidence,
    PatternAnalysis,
    PatternCategory,
    PatternFinding,
)
from slop_measure.domain.reports import AnalysisReport, ReportFinding, SourceSide


def finding_payload() -> dict:
    return {
        "path": "app.py",
        "rule_id": "redundant-bool",
        "category": "redundancy",
        "severity": "warning",
        "span": {"start_line": 2, "end_line": 3},
        "message": "Redundant boolean conversion.",
        "remediation": "Return the boolean.",
    }


def file_payload() -> dict:
    return {
        "path": "app.py",
        "language": "python",
        "cohort": "production",
        "sloc": 3,
        "sloc_lines": (1, 2, 4),
        "parse_state": "parsed",
    }


def language_payload() -> dict:
    return {
        "language": "python",
        "capabilities": ["files", "patterns"],
        "files": [file_payload()],
        "pattern_analyses": [
            {"state": "analyzed", "path": "app.py", "findings": [finding_payload()]}
        ],
    }


def report_payload() -> dict:
    score = {"state": "unavailable", "reason": "required-metric-unavailable"}
    return {
        "analysis": {"kind": "snapshot", "current": {"kind": "directory", "root": "PROJECT"}},
        "provenance": {"tool_version": "1", "config": {}},
        "cohorts": [
            {
                "kind": "snapshot",
                "language": "python",
                "cohort": "production",
                "current": {
                    "score": score,
                    "files": [{"evidence": file_payload(), "score": score}],
                },
            }
        ],
        "findings": [{"id": "finding-0001", "detail": finding_payload()}],
    }


def test_pattern_categories_are_closed() -> None:
    assert {item.value for item in PatternCategory} == {
        "redundancy",
        "control-flow",
        "defensive",
        "abstraction",
    }
    with pytest.raises(ValueError):
        PatternCategory("style")


@pytest.mark.parametrize("field", ["rule_id", "message", "remediation"])
def test_finding_text_is_trimmed_and_rejects_blank_values(field: str) -> None:
    with pytest.raises(ValidationError):
        PatternFinding.model_validate({**finding_payload(), field: "  "})
    assert (
        getattr(PatternFinding.model_validate({**finding_payload(), field: " text "}), field)
        == "text"
    )


def test_finding_round_trip_immutability_and_optional_remediation() -> None:
    payload = finding_payload()
    del payload["remediation"]
    finding = PatternFinding.model_validate(payload)
    assert finding.remediation is None
    assert PatternFinding.model_validate_json(finding.model_dump_json()) == finding
    with pytest.raises(ValidationError):
        finding.rule_id = "other"
    with pytest.raises(ValidationError):
        PatternFinding.model_validate({**payload, "parser_node": object()})


def test_pattern_outcome_union_has_explicit_discriminator_and_empty_success() -> None:
    adapter = TypeAdapter(PatternAnalysis)
    analyzed = adapter.validate_python({"state": "analyzed", "path": "app.py"})
    assert isinstance(analyzed, AnalyzedPatterns)
    assert analyzed.findings == ()
    schema = adapter.json_schema()
    assert schema["discriminator"]["propertyName"] == "state"
    assert set(schema["discriminator"]["mapping"]) == {"analyzed", "failed"}


@pytest.mark.parametrize(
    "severity,path", [("warning", "app.py"), ("error", "other.py"), ("error", None)]
)
def test_failed_pattern_outcome_requires_same_file_error(severity: str, path: str | None) -> None:
    with pytest.raises(ValidationError):
        FailedPatterns.model_validate(
            {
                "path": "app.py",
                "diagnostic": {
                    "severity": severity,
                    "path": path,
                    "code": "patterns.failed",
                    "message": "Failed.",
                },
            }
        )


def test_language_patterns_are_read_only_projection_of_canonical_outcomes() -> None:
    evidence = LanguageEvidence.model_validate(language_payload())
    assert isinstance(evidence.pattern_analyses, tuple)
    analyzed = evidence.pattern_analyses[0]
    assert isinstance(analyzed, AnalyzedPatterns)
    assert evidence.patterns == analyzed.findings
    assert "patterns" not in evidence.model_dump(mode="json")
    assert "pattern_analyses" in evidence.model_dump(mode="json")
    assert LanguageEvidence.model_validate_json(evidence.model_dump_json()) == evidence
    with pytest.raises((ValidationError, AttributeError)):
        evidence.patterns = ()  # type: ignore[reportAttributeAccessIssue]


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate-outcome",
        "unknown-path",
        "wrong-finding-path",
        "duplicate-finding",
        "no-intersection",
        "no-capability",
        "failed-file",
    ],
)
def test_pattern_outcomes_reconcile_with_parsed_source(change: str) -> None:
    payload = language_payload()
    analyzed = payload["pattern_analyses"][0]
    if change == "missing":
        payload["pattern_analyses"] = []
    elif change == "duplicate-outcome":
        payload["pattern_analyses"] *= 2
    elif change == "unknown-path":
        payload["pattern_analyses"].append({"state": "analyzed", "path": "unknown.py"})
    elif change == "wrong-finding-path":
        analyzed["findings"][0]["path"] = "other.py"
    elif change == "duplicate-finding":
        analyzed["findings"] *= 2
    elif change == "no-intersection":
        analyzed["findings"][0]["span"] = {"start_line": 3, "end_line": 3}
    elif change == "no-capability":
        payload["capabilities"] = ["files"]
    else:
        payload["files"][0].update(parse_state="failed", sloc=0, sloc_lines=())
    with pytest.raises(ValidationError):
        LanguageEvidence.model_validate(payload)


def test_parse_failed_source_requires_no_pattern_outcome() -> None:
    payload = language_payload()
    payload["files"][0].update(parse_state="failed", sloc=0, sloc_lines=())
    payload["pattern_analyses"] = []
    assert LanguageEvidence.model_validate(payload).pattern_analyses == ()


def test_report_finding_defaults_current_and_round_trips() -> None:
    report = AnalysisReport.model_validate(report_payload())
    assert report.findings[0].source is SourceSide.CURRENT
    assert AnalysisReport.model_validate_json(report.model_dump_json()) == report
    with pytest.raises(ValidationError):
        report.findings[0].id = "changed"
    with pytest.raises(ValidationError):
        ReportFinding.model_validate(
            {"id": "finding-1", "detail": finding_payload(), "extra": True}
        )


@pytest.mark.parametrize(
    "change",
    [
        "duplicate-id",
        "duplicate-identity",
        "unknown-path",
        "baseline",
        "failed-file",
        "no-intersection",
    ],
)
def test_report_findings_require_unique_identity_and_parsed_owning_source(change: str) -> None:
    payload = report_payload()
    finding = payload["findings"][0]
    if change == "duplicate-id":
        payload["findings"].append(
            {**finding, "detail": {**finding_payload(), "rule_id": "other-rule"}}
        )
    elif change == "duplicate-identity":
        payload["findings"].append({**finding, "id": "finding-0002"})
    elif change == "unknown-path":
        finding["detail"]["path"] = "other.py"
    elif change == "baseline":
        finding["source"] = "baseline"
    elif change == "failed-file":
        payload["cohorts"][0]["current"]["files"][0]["evidence"].update(
            parse_state="failed", sloc=0, sloc_lines=()
        )
    else:
        finding["detail"]["span"] = {"start_line": 3, "end_line": 3}
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)
