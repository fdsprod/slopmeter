"""Corpus profiles use complete observations without mixing scope populations."""

from copy import deepcopy

import pytest
from test_report_calibration import report_payload

from slop_measure.domain.reports import AnalysisReport
from slop_measure.scoring.calibration import build_profile


def payload(index: int = 0) -> dict:
    result = report_payload()
    result["analysis"]["current"]["root"] = f"project-{index}"
    return result


def build(values: list[dict], *, minimum: int = 1):
    return build_profile(
        tuple(AnalysisReport.model_validate(value) for value in values),
        profile_id="corpus-1",
        corpus_manifest_hash="a" * 64,
        min_samples=minimum,
    )


def test_complete_file_and_project_observations_are_distinct_and_deterministic() -> None:
    values = [payload(index) for index in range(5)]
    profile = build(values, minimum=5)
    assert profile.model_dump_json() == build(list(reversed(values)), minimum=5).model_dump_json()
    assert profile.profile_id == "corpus-1"
    assert profile.corpus_manifest_hash == "a" * 64
    assert profile.percentile_policy == "strictly-below-zero-floor"
    populations = {item.kind: item for item in profile.populations}
    assert set(populations) == {"file", "project"}
    file = populations["file"]
    assert file.kind == "file"
    assert (file.min_sloc, file.max_sloc) == (1, 21)
    assert all(item.sample_count == 10 for item in file.distributions)
    assert all(item.values == (0.2,) * 5 + (0.4,) * 5 for item in file.distributions)
    assert all(item.values == (0.3,) * 5 for item in populations["project"].distributions)
    model = next(item for item in profile.score_models if item.model_id == "snapshot")
    assert {item.metric_id: item.weight for item in model.inputs} == {
        "verbosity.combined": 0.5,
        "m4.erosion": 0.5,
    }
    assert [(item.label, item.lower) for item in profile.bands] == [
        ("low", 0),
        ("moderate", 40),
        ("high", 70),
    ]


def test_file_band_boundaries_are_half_open() -> None:
    value = payload()
    template = value["cohorts"][0]["current"]["files"][0]
    files = []
    for size in (1, 20, 21, 100, 101, 500, 501):
        file = deepcopy(template)
        path = f"size-{size}.py"
        file["evidence"].update(path=path, sloc=size, sloc_lines=list(range(1, size + 1)))
        for metric in file["metrics"]:
            metric["scope"]["path"] = path
        files.append(file)
    value["cohorts"][0]["current"]["files"] = files
    profile = build([value])
    actual = {
        (item.min_sloc, item.max_sloc): item.distributions[0].sample_count
        for item in profile.populations
        if item.kind == "file"
    }
    assert actual == {(1, 21): 2, (21, 101): 2, (101, 501): 2, (501, None): 1}


@pytest.mark.parametrize(
    "reason, eligible",
    [("no-functions", True), ("analyzer-failed", False), ("unsupported-capability", False)],
)
def test_only_no_functions_can_enter_verbosity_only_model(reason: str, eligible: bool) -> None:
    value = payload()
    current = value["cohorts"][0]["current"]
    for scope in [current, *current["files"]]:
        erosion = next(item for item in scope["metrics"] if item["metric_id"] == "m4.erosion")
        erosion.pop("raw")
        erosion.update(state="unavailable", reason=reason)
        erosion.pop("score", None)
    if not eligible:
        with pytest.raises(ValueError):
            build([value])
        return
    profile = build([value])
    assert all(item.model_id == "verbosity-only" for item in profile.populations)


def test_minimum_counts_complete_model_observations_and_skips_small_populations() -> None:
    values = [payload(index) for index in range(5)]
    current = values[-1]["cohorts"][0]["current"]
    erosion = next(item for item in current["metrics"] if item["metric_id"] == "m4.erosion")
    erosion.pop("raw")
    erosion.pop("score", None)
    erosion.update(state="unavailable", reason="unsupported-capability")
    profile = build(values, minimum=5)
    assert {item.kind for item in profile.populations} == {"file"}


def test_duplicate_source_identity_cannot_inflate_population() -> None:
    with pytest.raises(ValueError):
        build([payload(), payload()])


@pytest.mark.parametrize("change", ["settings", "rules", "normalization", "metric-version"])
def test_incompatible_reports_are_rejected(change: str) -> None:
    first, second = payload(1), payload(2)
    provenance = second["provenance"]
    if change == "settings":
        provenance["config"]["complexity_threshold"] = 99
    elif change == "rules":
        provenance["analyzers"][0]["rule_set_version"] = "changed"
    elif change == "normalization":
        provenance["analyzers"][0]["clone_normalization_version"] = "changed"
    else:
        provenance["metrics"][0]["version"] = "changed"
    with pytest.raises(ValueError):
        build([first, second])


def test_path_policy_and_profile_selector_do_not_change_metric_compatibility() -> None:
    first, second = payload(1), payload(2)
    second["provenance"]["config"].update(
        calibration_profile="__raw__", exclusions=["docs/**"], test_patterns=["testing/**"]
    )
    assert build([first, second]).populations
