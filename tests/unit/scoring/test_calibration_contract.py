"""Immutable calibration contracts specified before the scorer exists."""

from copy import deepcopy

import pytest
from pydantic import TypeAdapter, ValidationError

from slop_measure.domain.reports import MeasuredSnapshotScore
from slop_measure.domain.scoring import CalibrationProfile, ReferencePopulation


def profile_payload() -> dict:
    """A small reference whose observations and policies are explicit."""
    return {
        "schema_version": "1.0",
        "profile_id": "synthetic-1",
        "language": "python",
        "rule_set_version": "rules-1",
        "clone_normalization_version": "clones-1",
        "metric_versions": [
            {"metric_id": name, "version": "1"}
            for name in (
                "m2.pattern-verbosity",
                "m3.clone-verbosity",
                "verbosity.combined",
                "m4.erosion",
            )
        ],
        "settings": {
            "clone_min_statements": 2,
            "clone_min_sloc": 6,
            "complexity_threshold": 10,
            "enabled_rules": [],
            "disabled_rules": [],
        },
        "corpus_manifest_hash": "a" * 64,
        "percentile_policy": "strictly-below-zero-floor",
        "score_models": [
            {
                "model_id": "snapshot",
                "eligibility": "all-metrics",
                "inputs": [
                    {"metric_id": "verbosity.combined", "weight": 0.6},
                    {"metric_id": "m4.erosion", "weight": 0.4},
                ],
            },
            {
                "model_id": "verbosity-only",
                "eligibility": "no-functions",
                "inputs": [{"metric_id": "verbosity.combined", "weight": 1}],
            },
        ],
        "populations": [
            {
                "kind": "file",
                "cohort": "production",
                "model_id": "snapshot",
                "min_sloc": 1,
                "max_sloc": 100,
                "distributions": [
                    {"metric_id": name, "values": [0, 0.2, 0.2, 0.8]}
                    for name in ("verbosity.combined", "m4.erosion")
                ],
            },
            {
                "kind": "project",
                "cohort": "production",
                "model_id": "snapshot",
                "distributions": [
                    {"metric_id": name, "values": [0, 0.5, 0.9]}
                    for name in ("verbosity.combined", "m4.erosion")
                ],
            },
        ],
        "bands": [
            {"label": "low", "lower": 0},
            {"label": "moderate", "lower": 40},
            {"label": "high", "lower": 70},
        ],
    }


def test_profile_is_immutable_and_round_trips_without_mutable_collections() -> None:
    profile = CalibrationProfile.model_validate(profile_payload())
    assert isinstance(profile.populations, tuple)
    assert isinstance(profile.score_models, tuple)
    assert isinstance(profile.populations[0].distributions[0].values, tuple)
    assert profile.populations[0].distributions[0].sample_count == 4
    assert CalibrationProfile.model_validate_json(profile.model_dump_json()) == profile
    with pytest.raises(ValidationError):
        profile.profile_id = "changed"


def test_population_union_distinguishes_file_and_project() -> None:
    schema = TypeAdapter(ReferencePopulation).json_schema()
    assert schema["discriminator"]["propertyName"] == "kind"
    assert set(schema["discriminator"]["mapping"]) == {"file", "project"}


@pytest.mark.parametrize("values", [[], [0.5, 0.2], [-0.1], [1.1], [float("nan")]])
def test_distribution_rejects_invalid_reference_observations(values: list[float]) -> None:
    payload = profile_payload()
    payload["populations"][0]["distributions"][0]["values"] = values
    with pytest.raises(ValidationError):
        CalibrationProfile.model_validate(payload)


@pytest.mark.parametrize("weights", [[0.2, 0.4], [-0.1, 1.1], [0, 1], [float("inf"), 0.4]])
def test_model_requires_positive_finite_weights_summing_to_one(weights: list[float]) -> None:
    payload = profile_payload()
    for item, weight in zip(payload["score_models"][0]["inputs"], weights, strict=True):
        item["weight"] = weight
    with pytest.raises(ValidationError):
        CalibrationProfile.model_validate(payload)


@pytest.mark.parametrize(
    "change",
    [
        "double-count",
        "duplicate-input",
        "missing-input",
        "wrong-eligibility",
        "unknown-model",
        "missing-distribution",
        "duplicate-distribution",
        "duplicate-model",
        "overlap",
        "project-band",
        "empty-band",
        "invalid-hash",
        "missing-version",
        "unknown-policy",
    ],
)
def test_profile_rejects_inconsistent_model_population_and_provenance(change: str) -> None:  # noqa: C901, PLR0912
    payload = profile_payload()
    model = payload["score_models"][0]
    population = payload["populations"][0]
    if change == "double-count":
        model["inputs"][0]["metric_id"] = "m2.pattern-verbosity"
    elif change == "duplicate-input":
        model["inputs"][1]["metric_id"] = "verbosity.combined"
    elif change == "missing-input":
        model["inputs"] = [{"metric_id": "verbosity.combined", "weight": 1}]
    elif change == "wrong-eligibility":
        model["eligibility"] = "no-functions"
    elif change == "unknown-model":
        population["model_id"] = "absent"
    elif change == "missing-distribution":
        population["distributions"].pop()
    elif change == "duplicate-distribution":
        population["distributions"][1] = deepcopy(population["distributions"][0])
    elif change == "duplicate-model":
        payload["score_models"].append(deepcopy(model))
    elif change == "overlap":
        payload["populations"].append({**deepcopy(population), "min_sloc": 50})
    elif change == "project-band":
        payload["populations"][1]["min_sloc"] = 1
    elif change == "empty-band":
        population["max_sloc"] = population["min_sloc"]
    elif change == "invalid-hash":
        payload["corpus_manifest_hash"] = "unverified"
    elif change == "missing-version":
        payload["metric_versions"].pop()
    else:
        payload["percentile_policy"] = "midrank"
    with pytest.raises(ValidationError):
        CalibrationProfile.model_validate(payload)


@pytest.mark.parametrize("lowers", [[10, 40, 70], [0, 70, 40], [0, 40, 40], [0, 40, 100]])
def test_bands_start_at_zero_and_increase_below_one_hundred(lowers: list[int]) -> None:
    payload = profile_payload()
    for band, lower in zip(payload["bands"], lowers, strict=True):
        band["lower"] = lower
    with pytest.raises(ValidationError):
        CalibrationProfile.model_validate(payload)


def test_score_requires_exact_contribution_total() -> None:
    payload = {
        "points": 25.1,
        "profile_id": "synthetic-1",
        "model_id": "snapshot",
        "band": "low",
        "contributions": [
            {
                "metric_id": "verbosity.combined",
                "raw_value": 0.2,
                "percentile": 25,
                "weight": 0.6,
                "points": 15,
            },
            {
                "metric_id": "m4.erosion",
                "raw_value": 0.2,
                "percentile": 25,
                "weight": 0.4,
                "points": 10,
            },
        ],
    }
    with pytest.raises(ValidationError):
        MeasuredSnapshotScore.model_validate(payload)
    payload["points"] = 25
    assert MeasuredSnapshotScore.model_validate(payload).points == 25


def test_optional_pattern_and_clone_distributions_do_not_change_model_inputs() -> None:
    payload = profile_payload()
    for population in payload["populations"]:
        values = population["distributions"][0]["values"]
        population["distributions"].extend(
            {"metric_id": name, "values": values}
            for name in ("m2.pattern-verbosity", "m3.clone-verbosity")
        )
    profile = CalibrationProfile.model_validate(payload)
    assert len(profile.populations[0].distributions) == 4
    assert {item.metric_id for item in profile.score_models[0].inputs} == {
        "verbosity.combined",
        "m4.erosion",
    }


def test_population_distributions_must_have_equal_sample_counts() -> None:
    payload = profile_payload()
    payload["populations"][0]["distributions"][0]["values"] = [0, 0.2]
    with pytest.raises(ValidationError):
        CalibrationProfile.model_validate(payload)
