"""Exact calibrated reports from a fixed, hand-checked synthetic population."""

from decimal import Decimal
from pathlib import Path

import pytest

from slop_measure.domain.metrics import MeasuredMetric
from slop_measure.domain.reports import AnalysisReport, MeasuredSnapshotScore
from slop_measure.domain.scoring import CalibrationProfile
from slop_measure.reporting.json import serialize_report
from slop_measure.reporting.terminal import render_explanation, render_snapshot
from slop_measure.scoring.engine import score_report

_GOLDENS = Path(__file__).parent


def inputs() -> tuple[AnalysisReport, CalibrationProfile]:
    return (
        AnalysisReport.model_validate_json(
            (_GOLDENS / "scoring_input.json").read_text(encoding="utf-8")
        ),
        CalibrationProfile.model_validate_json(
            (_GOLDENS / "scoring_reference.json").read_text(encoding="utf-8")
        ),
    )


def test_fixed_population_calibrated_json_and_terminal_match_exact_goldens() -> None:
    raw, profile = inputs()
    result = score_report(raw, profile)
    assert serialize_report(result) == (_GOLDENS / "scoring.json").read_text(encoding="utf-8")
    assert render_snapshot(result, width=80, color=False, ascii=True) == (
        _GOLDENS / "scoring.txt"
    ).read_text(encoding="utf-8")
    assert result.provenance == raw.provenance
    current = result.cohorts[0].current
    # Project .3 has one of three observations strictly below; file .2 has
    # one of four below and .4 has three of four below. No file-score averaging.
    for scope, expected in zip((current, *current.files), (33.3, 25, 75), strict=True):
        score = scope.score
        assert isinstance(score, MeasuredSnapshotScore)
        assert score.points == expected
        assert score.profile_id == profile.profile_id == "synthetic-1"
        assert sum(Decimal(str(part.points)) for part in score.contributions) == Decimal(
            str(expected)
        )
    project_score = current.score
    assert isinstance(project_score, MeasuredSnapshotScore)
    assert {part.metric_id: part.points for part in project_score.contributions} == {
        "verbosity.combined": 20,
        "m4.erosion": 13.3,
    }
    for file in current.files:
        verbosity, erosion = file.metrics
        assert isinstance(verbosity, MeasuredMetric)
        assert isinstance(erosion, MeasuredMetric)
        assert verbosity.raw.denominator == file.evidence.sloc == 10
        assert erosion.raw.denominator == sum(function.mass for function in file.functions)
        assert erosion.raw.numerator == sum(
            function.mass for function in file.functions if function.cyclomatic_complexity > 10
        )
        assert all(
            metric.scope.kind == "file" and metric.scope.path == file.evidence.path
            for metric in file.metrics
        )


@pytest.mark.parametrize("reason", ["calibration-missing", "calibration-incompatible"])
def test_unavailable_project_and_file_explanation_name_calibration_reason(reason: str) -> None:
    raw, profile = inputs()
    reference = (
        None
        if reason == "calibration-missing"
        else profile.model_copy(update={"rule_set_version": "incompatible"})
    )
    report = score_report(raw, reference)
    outputs = (
        render_snapshot(report, width=100, color=False, ascii=True),
        render_explanation(report, "a.py", width=100, color=False, ascii=True),
    )
    for output in outputs:
        assert reason.replace("-", " ") in output.lower().replace("-", " ")
        assert "Combined verbosity" in output
        assert "Erosion" in output
        assert "/100" not in output
