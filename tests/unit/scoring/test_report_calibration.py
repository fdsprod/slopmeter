"""Report calibration projects scores without altering source facts."""

from copy import deepcopy
from decimal import Decimal

import pytest
from test_calibration_contract import profile_payload
from test_snapshot_engine import measured, metrics, provenance_payload

from slop_measure.domain.metrics import MeasuredMetric, UnavailableMetric
from slop_measure.domain.reports import AnalysisReport, UnavailableSnapshotScore
from slop_measure.domain.scoring import CalibrationProfile
from slop_measure.scoring.engine import score_report


def report_payload() -> dict:
    files = []
    for path, value in (("b.py", 0.2), ("a.py", 0.4)):
        raw_metrics = [item.model_dump(mode="json") for item in metrics(value, value)]
        for item in raw_metrics:
            item["scope"]["path"] = path
        files.append(
            {
                "evidence": {
                    "path": path,
                    "language": "python",
                    "cohort": "production",
                    "sloc": 10,
                    "sloc_lines": list(range(1, 11)),
                    "parse_state": "parsed",
                },
                "metrics": raw_metrics,
                "score": {"state": "unavailable", "reason": "calibration-missing"},
            }
        )
    return {
        "analysis": {"kind": "snapshot", "current": {"kind": "directory", "root": "fixture"}},
        "provenance": provenance_payload(),
        "cohorts": [
            {
                "kind": "snapshot",
                "language": "python",
                "cohort": "production",
                "current": {
                    "files": files,
                    "metrics": [
                        item.model_dump(mode="json") for item in metrics(0.3, 0.3, project=True)
                    ],
                    "score": {"state": "unavailable", "reason": "calibration-missing"},
                },
            }
        ],
    }


def profile() -> CalibrationProfile:
    return CalibrationProfile.model_validate(profile_payload())


def test_report_scores_raw_project_aggregate_and_preserves_input_and_order() -> None:
    original = AnalysisReport.model_validate(report_payload())
    original_json = original.model_dump_json()
    result = score_report(original, profile())
    cohort = result.cohorts[0].current
    assert measured(cohort.score).points == 33.3
    assert [measured(file.score).points for file in cohort.files] == [25, 75]
    assert [file.evidence.path.root for file in cohort.files] == ["b.py", "a.py"]
    assert original.model_dump_json() == original_json
    assert result.analysis == original.analysis
    assert result.provenance == original.provenance
    assert result.findings == original.findings
    assert result.diagnostics == original.diagnostics
    assert result.coverage == original.coverage
    for before, after in zip(original.cohorts[0].current.files, cohort.files, strict=True):
        assert before.evidence == after.evidence
        assert before.functions == after.functions
        for old, new in zip(before.metrics, after.metrics, strict=True):
            assert old.model_dump(exclude={"score"}) == new.model_dump(exclude={"score"})
        score = measured(after.score)
        assert sum(Decimal(str(item.points)) for item in score.contributions) == Decimal(
            str(score.points)
        )


def test_individual_metrics_use_optional_distributions_without_double_counting() -> None:
    payload = report_payload()
    reference = profile_payload()
    for population in reference["populations"]:
        size = len(population["distributions"][0]["values"])
        population["distributions"].extend(
            [
                {"metric_id": "m2.pattern-verbosity", "values": [0] * size},
                {"metric_id": "m3.clone-verbosity", "values": [0.9] * size},
            ]
        )
    current = payload["cohorts"][0]["current"]
    for scope in [current, *current["files"]]:
        base = scope["metrics"][0]
        scope["metrics"].extend(
            {**deepcopy(base), "metric_id": name}
            for name in ("m2.pattern-verbosity", "m3.clone-verbosity")
        )
    result = score_report(
        AnalysisReport.model_validate(payload), CalibrationProfile.model_validate(reference)
    )
    cohort = result.cohorts[0].current
    assert measured(cohort.score).points == 33.3
    values = {item.metric_id: item for item in cohort.metrics}
    for name, expected in (
        ("m2.pattern-verbosity", 100),
        ("m3.clone-verbosity", 0),
        ("m4.erosion", 33.3),
        ("verbosity.combined", 33.3),
    ):
        metric = values[name]
        assert isinstance(metric, MeasuredMetric)
        assert metric.score is not None
        assert metric.score.points == expected
        assert metric.score.profile_id == "synthetic-1"
    assert len(measured(cohort.score).contributions) == 2


def test_unavailable_raw_metrics_remain_unscored() -> None:
    payload = report_payload()
    payload["cohorts"][0]["current"]["files"][0]["metrics"][1] = {
        "state": "unavailable",
        "metric_id": "m4.erosion",
        "reason": "analyzer-failed",
        "scope": {"kind": "file", "path": "b.py", "cohort": "production"},
    }
    result = score_report(AnalysisReport.model_validate(payload), profile())
    file = result.cohorts[0].current.files[0]
    assert isinstance(file.metrics[1], UnavailableMetric)
    assert file.metrics[1].reason == "analyzer-failed"
    assert isinstance(file.score, UnavailableSnapshotScore)
    assert file.score.reason == "required-metric-unavailable"


@pytest.mark.parametrize(
    "reason", ["no-source-lines", "required-metric-unavailable", "calibration-missing"]
)
def test_missing_profile_preserves_specific_existing_unavailability(reason: str) -> None:
    payload = report_payload()
    payload["cohorts"][0]["current"]["score"]["reason"] = reason
    original = AnalysisReport.model_validate(payload)
    result = score_report(original, None)
    assert isinstance(result.cohorts[0].current.score, UnavailableSnapshotScore)
    assert result.cohorts[0].current.score.reason == reason
    assert original == result


def test_multiple_cohorts_and_languages_do_not_borrow_python_production_population() -> None:
    payload = report_payload()
    production = payload["cohorts"][0]
    for language, cohort in (("python", "test"), ("other", "production")):
        extra = deepcopy(production)
        extra.update(language=language, cohort=cohort)
        for file in extra["current"]["files"]:
            path = f"{language}/{cohort}/{file['evidence']['path']}"
            file["evidence"].update(language=language, cohort=cohort, path=path)
            for metric in file["metrics"]:
                metric["scope"].update(cohort=cohort, path=path)
        for metric in extra["current"]["metrics"]:
            metric["scope"]["cohort"] = cohort
        payload["cohorts"].append(extra)
    result = score_report(AnalysisReport.model_validate(payload), profile())
    assert measured(result.cohorts[0].current.score).points == 33.3
    for cohort in result.cohorts[1:]:
        assert isinstance(cohort.current.score, UnavailableSnapshotScore)
        assert cohort.current.score.reason == "calibration-incompatible"
        assert all(
            isinstance(file.score, UnavailableSnapshotScore) for file in cohort.current.files
        )
