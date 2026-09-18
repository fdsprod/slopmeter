"""Snapshot changes compare existing values without fabricated missing-side zeros."""

import pytest

from slop_measure.domain.reports import CohortResult, FileResult
from slop_measure.metrics.deltas import metric_deltas

_RAW_IDS = ("m2.pattern-verbosity", "m3.clone-verbosity", "m4.erosion", "verbosity.combined")
_ALL_IDS = tuple(sorted((*_RAW_IDS, "snapshot.score")))


def payload(value: float = 0.2, *, points: float = 20, project: bool = False) -> dict:
    scope = (
        {"kind": "project", "cohort": "production"}
        if project
        else {"kind": "file", "cohort": "production", "path": "app.py"}
    )
    result = {
        "metrics": [
            {
                "metric_id": name,
                "scope": scope,
                "state": "measured",
                "raw": {
                    "value": value,
                    "numerator": value * 10,
                    "denominator": 10,
                    "unit": "ratio",
                },
            }
            for name in reversed(_RAW_IDS)
        ],
        "score": {
            "state": "measured",
            "points": points,
            "profile_id": "fixed",
            "model_id": "snapshot",
            "band": "test",
            "contributions": [
                {
                    "metric_id": "verbosity.combined",
                    "raw_value": value,
                    "percentile": points,
                    "weight": 1,
                    "points": points,
                }
            ],
        },
    }
    if not project:
        result["evidence"] = {
            "path": "app.py",
            "language": "python",
            "cohort": "production",
            "sloc": 10,
            "sloc_lines": list(range(1, 11)),
            "parse_state": "parsed",
        }
    return result


@pytest.mark.parametrize("project", [False, True])
def test_deltas_are_current_minus_baseline_in_fixed_metric_id_order(project: bool) -> None:
    model = CohortResult if project else FileResult
    before = model.model_validate(payload(0.4, points=70, project=project))
    after = model.model_validate(payload(0.2, points=20, project=project))
    originals = before.model_dump_json(), after.model_dump_json()
    results = metric_deltas(before, after)
    assert tuple(item.metric_id for item in results) == _ALL_IDS
    for item in results:
        assert item.state == "measured"
        assert item.value == pytest.approx(-50 if item.metric_id == "snapshot.score" else -0.2)
        assert item.unit == ("points" if item.metric_id == "snapshot.score" else "ratio")
    assert (before.model_dump_json(), after.model_dump_json()) == originals


@pytest.mark.parametrize("absent", ["baseline", "current"])
def test_added_or_deleted_files_never_receive_fabricated_zero_ratios(absent: str) -> None:
    file = FileResult.model_validate(payload())
    results = metric_deltas(
        None if absent == "baseline" else file, None if absent == "current" else file
    )
    assert tuple(item.metric_id for item in results) == _ALL_IDS
    for item in results:
        assert item.state == "unavailable"
        assert item.reason == f"missing-{absent}"
        assert "value" not in item.model_dump()


def test_missing_raw_metric_names_actual_missing_side() -> None:
    before, after = payload(), payload()
    before["metrics"] = [
        item for item in before["metrics"] if item["metric_id"] != "m2.pattern-verbosity"
    ]
    after["metrics"] = [item for item in after["metrics"] if item["metric_id"] != "m4.erosion"]
    results = {
        item.metric_id: item
        for item in metric_deltas(
            FileResult.model_validate(before), FileResult.model_validate(after)
        )
    }
    assert results["m2.pattern-verbosity"].state == "unavailable"
    assert results["m2.pattern-verbosity"].reason == "missing-baseline"
    assert results["m4.erosion"].state == "unavailable"
    assert results["m4.erosion"].reason == "missing-current"
    assert results["m3.clone-verbosity"].state == "measured"


@pytest.mark.parametrize("side", ["baseline", "current"])
def test_unavailable_input_metric_remains_unavailable_without_blocking_other_deltas(
    side: str,
) -> None:
    before, after = payload(), payload(0.4, points=40)
    selected = before if side == "baseline" else after
    selected["metrics"][0] = {
        "metric_id": "verbosity.combined",
        "state": "unavailable",
        "scope": {"kind": "file", "cohort": "production", "path": "app.py"},
        "reason": "analyzer-failed",
    }
    results = {
        item.metric_id: item
        for item in metric_deltas(
            FileResult.model_validate(before), FileResult.model_validate(after)
        )
    }
    combined = results["verbosity.combined"]
    assert combined.state == "unavailable"
    assert combined.reason == "unavailable-input"
    assert results["m4.erosion"].state == "measured"


def test_different_raw_units_make_only_affected_metric_incompatible() -> None:
    before, after = payload(), payload()
    after["metrics"][0]["raw"]["unit"] = "lines"
    results = metric_deltas(FileResult.model_validate(before), FileResult.model_validate(after))
    combined = next(item for item in results if item.metric_id == "verbosity.combined")
    assert combined.state == "unavailable"
    assert combined.reason == "incompatible-definitions"


@pytest.mark.parametrize("field", ["profile_id", "model_id"])
def test_score_delta_requires_matching_profile_and_model(field: str) -> None:
    before, after = payload(), payload()
    after["score"][field] = "other"
    results = metric_deltas(FileResult.model_validate(before), FileResult.model_validate(after))
    score = next(item for item in results if item.metric_id == "snapshot.score")
    assert score.state == "unavailable"
    assert score.reason == "incompatible-definitions"
    assert all(item.state == "measured" for item in results if item.metric_id != "snapshot.score")


def test_unavailable_score_and_unrelated_metrics_do_not_corrupt_raw_deltas() -> None:
    before, after = payload(), payload()
    before["score"] = {"state": "unavailable", "reason": "calibration-missing"}
    after["metrics"].append(
        {
            "metric_id": "m1.loc-delta",
            "state": "unavailable",
            "scope": {"kind": "file", "cohort": "production", "path": "app.py"},
            "reason": "no-baseline",
        }
    )
    results = metric_deltas(FileResult.model_validate(before), FileResult.model_validate(after))
    assert tuple(item.metric_id for item in results) == _ALL_IDS
    score = next(item for item in results if item.metric_id == "snapshot.score")
    assert score.state == "unavailable"
    assert score.reason == "unavailable-input"
    with pytest.raises(ValueError):
        metric_deltas(None, None)


@pytest.mark.parametrize("field,value", [("language", "other"), ("cohort", "test")])
def test_file_deltas_reject_distinct_populations_even_with_compatible_scores(
    field: str, value: str
) -> None:
    before, after = payload(), payload()
    after["evidence"][field] = value
    if field == "cohort":
        for metric in after["metrics"]:
            metric["scope"]["cohort"] = value
    baseline = FileResult.model_validate(before)
    current = FileResult.model_validate(after)
    with pytest.raises(ValueError):
        metric_deltas(baseline, current)


@pytest.mark.parametrize("reverse", [False, True])
def test_file_and_project_deltas_reject_mixed_scopes_even_without_metrics(reverse: bool) -> None:
    file_payload = payload()
    project_payload = payload(project=True)
    file_payload["metrics"] = []
    project_payload["metrics"] = []
    file = FileResult.model_validate(file_payload)
    project = CohortResult.model_validate(project_payload)
    with pytest.raises(ValueError):
        metric_deltas(project if reverse else file, file if reverse else project)
