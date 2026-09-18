"""Synthetic reference distributions specify calibrated scoring behavior."""

from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import TypeAdapter
from test_calibration_contract import profile_payload

from slop_measure.domain.metrics import MetricResult
from slop_measure.domain.reports import (
    MeasuredSnapshotScore,
    Provenance,
    SnapshotScore,
    UnavailableSnapshotScore,
)
from slop_measure.domain.scoring import CalibrationProfile
from slop_measure.scoring.engine import score_snapshot


def provenance_payload() -> dict:
    profile = profile_payload()
    return {
        "tool_version": "test",
        "config": profile["settings"],
        "analyzers": [
            {
                "language": "python",
                "adapter_version": "test",
                "rule_set_version": "rules-1",
                "clone_normalization_version": "clones-1",
            }
        ],
        "metrics": profile["metric_versions"],
    }


def metrics(
    verbosity: float, erosion: float | str, *, project: bool = False
) -> tuple[MetricResult, ...]:
    scope = (
        {"kind": "project", "cohort": "production"}
        if project
        else {"kind": "file", "cohort": "production", "path": "app.py"}
    )
    values = []
    for name, value in (("verbosity.combined", verbosity), ("m4.erosion", erosion)):
        if isinstance(value, str):
            values.append(
                {"state": "unavailable", "metric_id": name, "scope": scope, "reason": value}
            )
        else:
            values.append(
                {
                    "state": "measured",
                    "metric_id": name,
                    "scope": scope,
                    "raw": {
                        "numerator": value * 100,
                        "denominator": 100,
                        "value": value,
                        "unit": "ratio",
                    },
                }
            )
    return TypeAdapter(tuple[MetricResult, ...]).validate_python(values)


def run_score(
    verbosity: float,
    erosion: float | str,
    *,
    project: bool = False,
    sloc: int = 10,
    payload: dict | None = None,
):
    return score_snapshot(
        metrics(verbosity, erosion, project=project),
        sloc=sloc,
        language="python",
        provenance=Provenance.model_validate(provenance_payload()),
        profile=CalibrationProfile.model_validate(payload or profile_payload()),
    )


@pytest.mark.parametrize(
    "raw,expected", [(0, 0), (0.1, 25), (0.2, 25), (0.3, 75), (0.8, 75), (1, 100)]
)
def test_strictly_below_percentiles_preserve_ties_and_zero_floor(
    raw: float, expected: float
) -> None:
    result = run_score(raw, raw)
    assert isinstance(result, MeasuredSnapshotScore)
    assert result.points == expected
    assert {item.percentile for item in result.contributions} == {expected}
    assert {item.metric_id for item in result.contributions} == {"verbosity.combined", "m4.erosion"}


def measured(result: SnapshotScore) -> MeasuredSnapshotScore:
    assert isinstance(result, MeasuredSnapshotScore)
    return result


def test_file_and_project_use_distinct_reference_populations() -> None:
    assert measured(run_score(0.3, 0.3)).points == 75
    assert measured(run_score(0.3, 0.3, project=True)).points == 33.3


def test_file_sloc_bands_are_half_open() -> None:
    payload = profile_payload()
    second = deepcopy(payload["populations"][0])
    second.update(min_sloc=100, max_sloc=None)
    for distribution in second["distributions"]:
        distribution["values"] = [0, 0.5, 0.9]
    payload["populations"].append(second)
    assert measured(run_score(0.3, 0.3, sloc=99, payload=payload)).points == 75
    assert measured(run_score(0.3, 0.3, sloc=100, payload=payload)).points == 33.3


def test_contribution_tenths_use_largest_remainder_and_sum_exactly() -> None:
    payload = profile_payload()
    for item in payload["score_models"][0]["inputs"]:
        item["weight"] = 0.5
    result = run_score(0.3, 0.3, project=True, payload=payload)
    assert isinstance(result, MeasuredSnapshotScore)
    points = {item.metric_id: Decimal(str(item.points)) for item in result.contributions}
    assert points == {"m4.erosion": Decimal("16.7"), "verbosity.combined": Decimal("16.6")}
    assert sum(points.values()) == Decimal(str(result.points)) == Decimal("33.3")


@pytest.mark.parametrize("raw,band", [(0, "low"), (0.3, "moderate"), (1, "high")])
def test_score_band_labels_come_from_profile(raw: float, band: str) -> None:
    payload = profile_payload()
    payload["bands"] = [
        {"label": "low", "lower": 0},
        {"label": "moderate", "lower": 75},
        {"label": "high", "lower": 90},
    ]
    assert measured(run_score(raw, raw, payload=payload)).band == band


def test_only_no_functions_can_select_explicit_verbosity_model() -> None:
    payload = profile_payload()
    pop = deepcopy(payload["populations"][0])
    pop["model_id"] = "verbosity-only"
    pop["distributions"] = [pop["distributions"][0]]
    payload["populations"].append(pop)
    result = run_score(0.3, "no-functions", payload=payload)
    assert isinstance(result, MeasuredSnapshotScore)
    assert result.model_id == "verbosity-only"
    assert result.points == 75
    assert len(result.contributions) == 1
    failed = run_score(0.3, "analyzer-failed", payload=payload)
    assert isinstance(failed, UnavailableSnapshotScore)
    assert failed.reason == "required-metric-unavailable"


@pytest.mark.parametrize("erosion", ["no-functions", "analyzer-failed", "unsupported-capability"])
def test_missing_erosion_never_redistributes_full_model_weight(erosion: str) -> None:
    result = run_score(0.3, erosion)
    assert isinstance(result, UnavailableSnapshotScore)
    assert result.reason == (
        "calibration-population-missing"
        if erosion == "no-functions"
        else "required-metric-unavailable"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("clone_min_statements", 3),
        ("clone_min_sloc", 7),
        ("complexity_threshold", 11),
        ("enabled_rules", ["PY001"]),
        ("disabled_rules", ["PY001"]),
    ],
)
def test_changed_effective_metric_settings_make_calibration_incompatible(
    field: str, value: object
) -> None:
    context = provenance_payload()
    context["config"][field] = value
    result = score_snapshot(
        metrics(0.3, 0.3),
        sloc=10,
        language="python",
        provenance=Provenance.model_validate(context),
        profile=CalibrationProfile.model_validate(profile_payload()),
    )
    assert isinstance(result, UnavailableSnapshotScore)
    assert result.reason == "calibration-incompatible"


@pytest.mark.parametrize("change", ["language", "rule", "clone", "metric", "missing-metric"])
def test_incompatible_versions_do_not_produce_points(change: str) -> None:
    context = provenance_payload()
    language = "python"
    if change == "language":
        language = "typescript"
    elif change == "rule":
        context["analyzers"][0]["rule_set_version"] = "other"
    elif change == "clone":
        context["analyzers"][0]["clone_normalization_version"] = "other"
    elif change == "metric":
        context["metrics"][0]["version"] = "other"
    else:
        context["metrics"].pop()
    result = score_snapshot(
        metrics(0.3, 0.3),
        sloc=10,
        language=language,
        provenance=Provenance.model_validate(context),
        profile=CalibrationProfile.model_validate(profile_payload()),
    )
    assert isinstance(result, UnavailableSnapshotScore)
    assert result.reason == "calibration-incompatible"


def test_missing_profile_and_no_source_have_explicit_unavailable_states() -> None:
    result = score_snapshot(
        metrics(0, 0),
        sloc=10,
        language="python",
        provenance=Provenance.model_validate(provenance_payload()),
        profile=None,
    )
    assert isinstance(result, UnavailableSnapshotScore)
    assert result.reason == "calibration-missing"
    empty = run_score(0, 0, sloc=0)
    assert isinstance(empty, UnavailableSnapshotScore)
    assert empty.reason == "no-source-lines"


def test_outside_calibrated_sloc_band_has_missing_population() -> None:
    result = run_score(0.3, 0.3, sloc=100)
    assert isinstance(result, UnavailableSnapshotScore)
    assert result.reason == "calibration-population-missing"


def test_pattern_and_clone_raw_metrics_do_not_contribute_again() -> None:
    inputs = metrics(0.2, 0.2)
    extras = tuple(
        inputs[0].model_copy(update={"metric_id": name})
        for name in ("m2.pattern-verbosity", "m3.clone-verbosity")
    )
    result = score_snapshot(
        inputs + extras,
        sloc=10,
        language="python",
        provenance=Provenance.model_validate(provenance_payload()),
        profile=CalibrationProfile.model_validate(profile_payload()),
    )
    assert measured(result).points == 25
    assert len(measured(result).contributions) == 2


def test_absent_required_metric_has_no_score() -> None:
    result = score_snapshot(
        metrics(0.3, 0.3)[:1],
        sloc=10,
        language="python",
        provenance=Provenance.model_validate(provenance_payload()),
        profile=CalibrationProfile.model_validate(profile_payload()),
    )
    assert isinstance(result, UnavailableSnapshotScore)
    assert result.reason == "required-metric-unavailable"
