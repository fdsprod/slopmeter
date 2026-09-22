"""Error evidence owns handler outcomes and derives its coverage counters."""

import pytest
from pydantic import ValidationError

from slop_measure.domain.error_review import (
    AnalyzedErrorFile,
    AnalyzedErrorHandler,
    ErrorExpression,
    ErrorFallbackFinding,
    ErrorReviewReport,
    FailedErrorFile,
    UnresolvedErrorHandler,
)


def expression(text: str, line: int) -> dict:
    return dict(span=dict(start_line=line, end_line=line), expression=text)


def finding() -> dict:
    return dict(
        caught="OSError",
        protected=dict(start_line=3, end_line=4),
        operations=[expression("load()", 3)],
        fallback=expression("[]", 6),
        fallback_kind="empty-list",
        normal_returns=[expression("result", 4)],
    )


def handler() -> dict:
    return dict(
        state="analyzed", symbol="work", span=dict(start_line=5, end_line=6), findings=[finding()]
    )


def report() -> dict:
    failure = dict(
        state="failed",
        path="broken.py",
        cohort="production",
        diagnostic=dict(
            code="parse-error", message="Invalid syntax", severity="error", path="broken.py"
        ),
    )
    unresolved = dict(
        state="unresolved",
        symbol="other",
        span=dict(start_line=10, end_line=12),
        reason="conditional handler control flow",
    )
    return dict(
        tool_version="0.5.0",
        source=dict(kind="directory", root="."),
        config={},
        files=[
            dict(
                state="analyzed",
                path="errors.py",
                cohort="production",
                source_sha256="a" * 64,
                handlers=[handler(), unresolved, {**unresolved, "symbol": "third"}],
            ),
            dict(
                state="analyzed",
                path="empty.py",
                cohort="test",
                source_sha256="b" * 64,
                handlers=[],
            ),
            failure,
        ],
        diagnostics=[failure["diagnostic"]],
    )


def test_owned_error_evidence_is_frozen_and_roundtrips() -> None:
    evidence = AnalyzedErrorHandler.model_validate(handler())
    assert evidence.state == "analyzed" and isinstance(evidence.findings, tuple)
    assert evidence.findings[0].kind == "error-as-success"
    assert isinstance(evidence.findings[0].operations, tuple)
    assert isinstance(evidence.findings[0].normal_returns, tuple)
    assert AnalyzedErrorHandler.model_validate_json(evidence.model_dump_json()) == evidence
    with pytest.raises(ValidationError):
        evidence.symbol = "changed"
    with pytest.raises(ValidationError):
        evidence.findings[0].fallback.expression = "changed"


@pytest.mark.parametrize(
    "model,payload",
    [
        (ErrorExpression, expression("[]", 6)),
        (ErrorFallbackFinding, finding()),
        (AnalyzedErrorHandler, handler()),
        (
            UnresolvedErrorHandler,
            dict(symbol="f", span=dict(start_line=1, end_line=2), reason="dynamic"),
        ),
        (AnalyzedErrorFile, dict(path="x.py", cohort="test", source_sha256="a" * 64, handlers=[])),
        (FailedErrorFile, report()["files"][-1]),
        (ErrorReviewReport, report()),
    ],
)
def test_all_error_evidence_rejects_unknown_fields(model, payload: dict) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({**payload, "invented": True})


@pytest.mark.parametrize(
    "field,value",
    [("caught", " "), ("normal_returns", []), ("fallback_kind", "empty-set"), ("kind", "defect")],
)
def test_incomplete_or_unknown_finding_cannot_be_reported(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ErrorFallbackFinding.model_validate({**finding(), field: value})


@pytest.mark.parametrize("text", ["", " ", "\n\t"])
def test_expression_requires_nonempty_text(text: str) -> None:
    with pytest.raises(ValidationError):
        ErrorExpression.model_validate(expression(text, 1))


def test_possible_operations_can_be_empty_when_the_try_body_has_no_calls() -> None:
    evidence = ErrorFallbackFinding.model_validate({**finding(), "operations": []})
    assert evidence.operations == ()


def test_report_derives_handler_coverage_and_counts_failures_without_inventing_handlers() -> None:
    result = ErrorReviewReport.model_validate(report())
    wire = result.model_dump(mode="json")
    assert wire["schema_version"] == "1" and wire["experiment"] == "py-error-fallback-1"
    assert wire["summary"] == dict(
        unit="exception-handlers",
        files_analyzed=2,
        files_failed=1,
        encountered=3,
        assessed=1,
        unresolved=2,
        findings=1,
        unresolved_reasons=[dict(reason="conditional handler control flow", count=2)],
    )
    assert result.interpretation
    assert ErrorReviewReport.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize(
    "field", ["files_analyzed", "files_failed", "encountered", "assessed", "unresolved", "findings"]
)
def test_supplied_summary_cannot_disagree_with_handler_evidence(field: str) -> None:
    wire = ErrorReviewReport.model_validate(report()).model_dump(mode="json")
    wire["summary"][field] += 1
    with pytest.raises(ValidationError):
        ErrorReviewReport.model_validate(wire)


def test_supplied_summary_cannot_forge_unresolved_reasons() -> None:
    wire = ErrorReviewReport.model_validate(report()).model_dump(mode="json")
    wire["summary"]["unresolved_reasons"][0]["reason"] = "other"
    with pytest.raises(ValidationError):
        ErrorReviewReport.model_validate(wire)


def test_empty_report_has_no_assessed_handlers() -> None:
    data = {**report(), "files": [], "diagnostics": []}
    summary = ErrorReviewReport.model_validate(data).summary
    assert summary.encountered == summary.assessed == summary.findings == 0
    assert summary.files_analyzed == summary.files_failed == 0


@pytest.mark.parametrize("change", ["duplicate-file", "missing-diagnostic"])
def test_report_retains_unique_file_outcomes_and_failed_diagnostics(change: str) -> None:
    data = report()
    if change == "duplicate-file":
        data["files"].append(data["files"][0])
    else:
        data["diagnostics"] = []
    with pytest.raises(ValidationError):
        ErrorReviewReport.model_validate(data)


@pytest.mark.parametrize("change", ["different-path", "warning", "handlers"])
def test_failed_file_requires_its_own_error_and_cannot_claim_handlers(change: str) -> None:
    data = report()["files"][-1]
    if change == "different-path":
        data["diagnostic"]["path"] = "other.py"
    elif change == "warning":
        data["diagnostic"]["severity"] = "warning"
    else:
        data["handlers"] = []
    with pytest.raises(ValidationError):
        FailedErrorFile.model_validate(data)


def test_unresolved_handler_has_reason_and_cannot_claim_findings() -> None:
    data = dict(symbol="work", span=dict(start_line=5, end_line=6), reason="indirect fallback")
    assert UnresolvedErrorHandler.model_validate(data).state == "unresolved"
    with pytest.raises(ValidationError):
        UnresolvedErrorHandler.model_validate({**data, "reason": " "})
    with pytest.raises(ValidationError):
        UnresolvedErrorHandler.model_validate({**data, "findings": []})
