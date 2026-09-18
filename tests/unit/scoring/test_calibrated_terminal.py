"""Calibrated presentation preserves raw values and visible population ownership."""

from copy import deepcopy

from test_report_calibration import profile, report_payload

from slop_measure.domain.reports import AnalysisReport
from slop_measure.reporting.terminal import render_explanation, render_snapshot
from slop_measure.scoring.engine import score_report


def test_summary_ranks_calibrated_files_but_keeps_raw_percentages() -> None:
    report = score_report(AnalysisReport.model_validate(report_payload()), profile())
    output = render_snapshot(report, ascii=True, color=False, width=120, top=2)
    assert "33.3/100" in output
    assert "lower is better" in output.lower()
    assert "synthetic-1" in output
    assert "low" in output.lower()
    assert "Combined verbosity  30.0%" in output
    assert "Erosion  30.0%" in output
    assert "75.0/100" in output
    assert "25.0/100" in output
    assert output.index("a.py") < output.index("b.py")
    assert "\x1b[" not in output
    explanation = render_explanation(report, "a.py", ascii=True, color=False, width=120)
    assert "75.0/100" in explanation
    assert "synthetic-1" in explanation
    assert "high" in explanation.lower()
    # The file's 75 points are exactly the two weighted contributions.
    assert "45.0" in explanation
    assert "30.0" in explanation


def test_hidden_test_score_cannot_make_production_headline_claim_calibration() -> None:
    scored = score_report(AnalysisReport.model_validate(report_payload()), profile())
    payload = scored.model_dump(mode="json")
    production = payload["cohorts"][0]
    testing = deepcopy(production)
    testing["cohort"] = "test"
    for scope in [testing["current"], *testing["current"]["files"]]:
        for metric in scope["metrics"]:
            metric["scope"]["cohort"] = "test"
    for file in testing["current"]["files"]:
        path = "tests/" + file["evidence"]["path"]
        file["evidence"].update(path=path, cohort="test")
        for metric in file["metrics"]:
            metric["scope"]["path"] = path
    for scope in [production["current"], *production["current"]["files"]]:
        scope["score"] = {"state": "unavailable", "reason": "calibration-missing"}
    payload["cohorts"].append(testing)
    report = AnalysisReport.model_validate(payload)
    output = render_snapshot(report, scope="production", ascii=True, color=False, width=120)
    assert "Score unavailable" in output
    assert "calibrated scores" not in output.lower()
    assert "tests/a.py" not in output


def test_hotspot_omission_counts_use_rendered_scoreable_files() -> None:
    payload = report_payload()
    template = payload["cohorts"][0]["current"]["files"][0]
    unavailable = deepcopy(template)
    unavailable["evidence"]["path"] = "unavailable.py"
    for metric in unavailable["metrics"]:
        metric["scope"]["path"] = "unavailable.py"
        metric.pop("raw")
        metric.pop("score", None)
        metric.update(state="unavailable", reason="unsupported-capability")
    payload["cohorts"][0]["current"]["files"].append(unavailable)
    report = score_report(AnalysisReport.model_validate(payload), profile())
    output = render_snapshot(report, ascii=True, color=False, width=120, top=3)
    assert "a.py" in output and "b.py" in output
    # Either expose the unavailable file explicitly or account for its omitted row.
    assert "unavailable.py" in output or "1 file omitted" in output
