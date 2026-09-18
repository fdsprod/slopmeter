"""Scores expose reference sample support without claiming domain representativeness."""

from copy import deepcopy

import pytest
from pydantic import ValidationError
from test_calibration_contract import profile_payload
from test_report_calibration import report_payload
from test_snapshot_engine import measured, run_score

from slop_measure.domain.reports import (
    AnalysisReport,
    MeasuredSnapshotScore,
    UnavailableSnapshotScore,
)
from slop_measure.domain.scoring import (
    CalibrationProfile,
    FileReferencePopulation,
    ProjectReferencePopulation,
    RecordedReferenceSupport,
    UnknownReferenceSupport,
)
from slop_measure.reporting.terminal import render_explanation, render_snapshot
from slop_measure.scoring.engine import score_report


def test_reference_support_is_derived_immutable_and_round_trips() -> None:
    support = RecordedReferenceSupport.model_validate(
        {
            "state": "recorded",
            "population": {"kind": "file", "sample_count": 4, "min_sloc": 1, "max_sloc": 100},
        }
    )
    assert support.nominal_percentile_step == 25
    assert support.domain_match == "not-assessed"
    assert RecordedReferenceSupport.model_validate_json(support.model_dump_json()) == support
    with pytest.raises(ValidationError):
        support.population.sample_count = 5
    with pytest.raises((ValidationError, AttributeError)):
        setattr(support, "nominal_percentile_step", 50)  # noqa: B010 - exercise runtime readonly guard
    payload = support.model_dump()
    payload["nominal_percentile_step"] = 50
    with pytest.raises(ValidationError):
        RecordedReferenceSupport.model_validate(payload)
    with pytest.raises(ValidationError):
        RecordedReferenceSupport.model_validate({**support.model_dump(), "domain_match": "matched"})


@pytest.mark.parametrize("count", [0, -1, True, 1.5, "4"])
def test_reference_sample_count_is_a_strict_positive_integer(count: object) -> None:
    for model, extra in (
        (FileReferencePopulation, {"min_sloc": 1, "max_sloc": None}),
        (ProjectReferencePopulation, {}),
    ):
        with pytest.raises(ValidationError):
            model.model_validate({"sample_count": count, **extra})


def test_reference_populations_keep_file_bands_out_of_project_support() -> None:
    project = ProjectReferencePopulation(sample_count=6)
    support = RecordedReferenceSupport(population=project)
    assert support.nominal_percentile_step == pytest.approx(100 / 6)
    with pytest.raises(ValidationError):
        ProjectReferencePopulation.model_validate({"sample_count": 6, "min_sloc": 1})
    for lower, upper in ((0, 10), (10, 10), (10, 9)):
        with pytest.raises(ValidationError):
            FileReferencePopulation.model_validate(
                {"sample_count": 4, "min_sloc": lower, "max_sloc": upper}
            )


def test_legacy_score_support_is_unknown_without_changing_serialized_shape() -> None:
    payload = {
        "points": 25,
        "profile_id": "historical",
        "model_id": "verbosity-only",
        "band": "low",
        "contributions": [
            {
                "metric_id": "verbosity.combined",
                "raw_value": 0.2,
                "percentile": 25,
                "weight": 1,
                "points": 25,
            }
        ],
    }
    score = MeasuredSnapshotScore.model_validate(payload)
    assert isinstance(score.reference_support, UnknownReferenceSupport)
    assert "reference_support" not in score.model_dump()
    assert "reference_support" not in score.model_dump_json()
    schema = MeasuredSnapshotScore.model_json_schema()["properties"]["reference_support"]
    assert schema["discriminator"]["propertyName"] == "state"
    assert set(schema["discriminator"]["mapping"]) == {"recorded", "not-recorded"}


def test_engine_uses_selected_file_and_project_observation_counts() -> None:
    file = measured(run_score(0.3, 0.3))
    project = measured(run_score(0.3, 0.3, project=True))
    assert file.points == 75 and project.points == 33.3
    file_support, project_support = file.reference_support, project.reference_support
    assert isinstance(file_support, RecordedReferenceSupport)
    assert isinstance(project_support, RecordedReferenceSupport)
    assert file_support.population.kind == "file"
    assert (
        file_support.population.sample_count,
        file_support.population.min_sloc,
        file_support.population.max_sloc,
    ) == (4, 1, 100)
    assert file_support.nominal_percentile_step == 25
    assert project_support.population.kind == "project"
    assert project_support.population.sample_count == 3
    assert project_support.nominal_percentile_step == pytest.approx(100 / 3)
    assert file_support.domain_match == project_support.domain_match == "not-assessed"


@pytest.mark.parametrize("has_model", [False, True])
def test_no_functions_without_calibrated_support_has_population_missing_reason(
    has_model: bool,
) -> None:
    payload = profile_payload()
    if not has_model:
        payload["score_models"] = payload["score_models"][:1]
    result = run_score(0.2, "no-functions", payload=payload)
    assert isinstance(result, UnavailableSnapshotScore)
    assert result.reason == "calibration-population-missing"
    failed = run_score(0.2, "analyzer-failed", payload=payload)
    assert isinstance(failed, UnavailableSnapshotScore)
    assert failed.reason == "required-metric-unavailable"


def test_no_functions_reference_count_comes_from_its_own_population() -> None:
    payload = profile_payload()
    population = deepcopy(payload["populations"][0])
    population["model_id"] = "verbosity-only"
    population["distributions"] = [{"metric_id": "verbosity.combined", "values": [0, 0.5]}]
    payload["populations"].append(population)
    support = measured(run_score(0.2, "no-functions", payload=payload)).reference_support
    assert isinstance(support, RecordedReferenceSupport)
    assert support.population.sample_count == 2
    assert support.nominal_percentile_step == 50


def test_terminal_reports_reference_size_granularity_and_unassessed_domain_match() -> None:
    report = score_report(
        AnalysisReport.model_validate(report_payload()),
        CalibrationProfile.model_validate(profile_payload()),
    )
    project = render_snapshot(report, width=180, ascii=True, color=False).lower()
    file = render_explanation(report, "a.py", width=180, ascii=True, color=False).lower()
    assert "3 project observations" in project
    assert "4 file observations" in file
    assert "33.3" in project and "25.0" in file
    for output in (project, file):
        assert "nominal percentile step" in output
        assert "percentile points" in output
        assert "domain match: not assessed" in output
    assert "sloc" in file and "100" in file


def test_legacy_terminal_reference_support_is_explicitly_not_recorded() -> None:
    payload = report_payload()
    score = {
        "state": "measured",
        "points": 25,
        "profile_id": "old",
        "model_id": "snapshot",
        "band": "low",
        "contributions": [
            {
                "metric_id": "verbosity.combined",
                "raw_value": 0.2,
                "percentile": 25,
                "weight": 1,
                "points": 25,
            }
        ],
    }
    payload["cohorts"][0]["current"]["score"] = score
    output = render_snapshot(
        AnalysisReport.model_validate(payload), width=180, ascii=True, color=False
    ).lower()
    assert "reference support not recorded" in output


@pytest.mark.parametrize("rounding", [False, True])
def test_zero_points_with_nonzero_raw_values_distinguishes_rank_from_rounding(
    rounding: bool,
) -> None:
    reference = profile_payload()
    payload = report_payload()
    current = payload["cohorts"][0]["current"]
    for scope in (current, *current["files"]):
        for metric in scope["metrics"]:
            value = 0.0001 if metric["metric_id"] == "m4.erosion" else 0
            metric["raw"].update(value=value, numerator=value * metric["raw"]["denominator"])
    if rounding:
        reference["score_models"][0]["inputs"][1]["transform"] = "severity-weighted"
    else:
        for population in reference["populations"]:
            for distribution in population["distributions"]:
                distribution["values"] = [0.1] * len(distribution["values"])
    report = score_report(
        AnalysisReport.model_validate(payload), CalibrationProfile.model_validate(reference)
    )
    assert measured(report.cohorts[0].current.score).points == 0
    output = render_snapshot(report, width=180, ascii=True, color=False).lower()
    assert "zero points does not mean zero raw evidence" in output
    assert ("rounded to zero" if rounding else "percentile zero") in output
