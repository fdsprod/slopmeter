"""Explicit transforms combine reference rank with raw severity without hiding either."""

from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_calibration_contract import profile_payload
from test_profile_builder import build, payload as corpus_payload
from test_snapshot_engine import measured, run_score

from slop_measure.domain.scoring import (
    CalibrationProfile,
    MetricWeight,
    ScoreContribution,
    ScoreTransform,
)
from slop_measure.scoring.profiles import load_profile


def transformed_profile() -> dict:
    payload = profile_payload()
    for weight in payload["score_models"][0]["inputs"]:
        weight["weight"] = 0.5
        if weight["metric_id"] == "m4.erosion":
            weight["transform"] = "severity-weighted"
    return payload


def test_rank_one_hundred_at_ten_percent_severity_contributes_five_not_fifty() -> None:
    payload = transformed_profile()
    for distribution in payload["populations"][0]["distributions"]:
        distribution["values"] = [0, 0, 0.01, 0.05]
    score = measured(run_score(0, 0.1, payload=payload))
    assert score.points == 5
    contributions = {part.metric_id: part for part in score.contributions}
    erosion = contributions["m4.erosion"]
    assert erosion.percentile == 100
    assert erosion.raw_value == 0.1 and erosion.weight == 0.5
    assert erosion.points == 5
    assert erosion.transform is ScoreTransform.SEVERITY_WEIGHTED
    assert contributions["verbosity.combined"].points == 0
    assert contributions["verbosity.combined"].transform is ScoreTransform.PERCENTILE


def test_mixed_transforms_reconcile_rounded_tenths_without_rounding_input_percentiles() -> None:
    score = measured(run_score(0.3, 0.3, project=True, payload=transformed_profile()))
    points = {part.metric_id: Decimal(str(part.points)) for part in score.contributions}
    assert points == {"verbosity.combined": Decimal("16.7"), "m4.erosion": Decimal("5.0")}
    assert sum(points.values()) == Decimal(str(score.points)) == Decimal("21.7")
    assert all(part.percentile == pytest.approx(100 / 3) for part in score.contributions)
    assert all(part.raw_value == 0.3 for part in score.contributions)


def test_historical_default_transform_keeps_existing_scores_and_wire_shape() -> None:
    payload = profile_payload()
    for weight in payload["score_models"][0]["inputs"]:
        weight["weight"] = 0.5
    score = measured(run_score(0.3, 0.3, project=True, payload=payload))
    assert score.points == 33.3
    assert {part.metric_id: part.points for part in score.contributions} == {
        "m4.erosion": 16.7,
        "verbosity.combined": 16.6,
    }
    assert all(part.transform is ScoreTransform.PERCENTILE for part in score.contributions)
    profile = CalibrationProfile.model_validate(payload)
    assert "transform" not in profile.model_dump_json()
    assert "transform" not in score.model_dump_json()
    assert all("transform" not in part.model_dump() for part in score.contributions)


def test_transform_values_are_closed_and_nondefault_policy_round_trips() -> None:
    assert {item.value for item in ScoreTransform} == {"percentile", "severity-weighted"}
    profile = CalibrationProfile.model_validate(transformed_profile())
    assert '"transform":"severity-weighted"' in profile.model_dump_json()
    assert CalibrationProfile.model_validate_json(profile.model_dump_json()) == profile
    with pytest.raises(ValidationError):
        MetricWeight.model_validate(
            {"metric_id": "m4.erosion", "weight": 0.5, "transform": "unknown"}
        )
    with pytest.raises(ValidationError):
        ScoreContribution.model_validate(
            {
                "metric_id": "m4.erosion",
                "raw_value": 0.1,
                "percentile": 100,
                "weight": 0.5,
                "points": 5,
                "transform": "unknown",
            }
        )


@pytest.mark.parametrize("version,expected", [("1", "percentile"), ("2", "severity-weighted")])
def test_corpus_builder_selects_severity_only_for_version_two_erosion(
    version: str, expected: str
) -> None:
    source = corpus_payload()
    for metric in source["provenance"]["metrics"]:
        if metric["metric_id"] == "m4.erosion":
            metric["version"] = version
    profile = build([source])
    model = next(model for model in profile.score_models if model.model_id == "snapshot")
    transforms = {item.metric_id: item.transform.value for item in model.inputs}
    assert transforms == {"verbosity.combined": "percentile", "m4.erosion": expected}
    assert all(
        item.transform is ScoreTransform.PERCENTILE
        for model in profile.score_models
        if model.eligibility == "no-functions"
        for item in model.inputs
    )


def test_packaged_profiles_preserve_their_versioned_transform_policies() -> None:
    for identifier, expected in (("py-2026.1", "percentile"), ("py-2026.2", "severity-weighted")):
        profile = load_profile(identifier)
        assert profile is not None
        for model in profile.score_models:
            for item in model.inputs:
                assert item.transform.value == (
                    expected if item.metric_id == "m4.erosion" else "percentile"
                )
