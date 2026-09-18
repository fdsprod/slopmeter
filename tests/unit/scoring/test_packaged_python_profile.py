"""The packaged reference enables traceable calibration through the public API."""

import hashlib
from importlib.resources import files
from pathlib import Path

import pytest

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.domain.metrics import MeasuredMetric, UnavailableMetric
from slop_measure.domain.reports import MeasuredSnapshotScore, UnavailableSnapshotScore
from slop_measure.scoring.profiles import load_profile


def test_packaged_python_profile_records_verified_provenance_and_distinct_populations() -> None:
    profile = load_profile("py-2026.3")
    assert profile is not None
    assert profile.profile_id == "py-2026.3"
    assert profile.language == "python"
    assert profile.rule_set_version == "py-patterns-1"
    versions = {item.metric_id: item.version for item in profile.metric_versions}
    assert versions["m4.erosion"] == "3"
    assert all(version == "1" for name, version in versions.items() if name != "m4.erosion")
    assert profile.clone_normalization_version
    assert {item.metric_id for item in profile.metric_versions} >= {
        "m2.pattern-verbosity",
        "m3.clone-verbosity",
        "verbosity.combined",
        "m4.erosion",
    }
    manifest = (
        files("slop_measure.scoring").joinpath("resources", "py-2026.3.corpus.toml").read_bytes()
    )
    assert profile.corpus_manifest_hash == hashlib.sha256(manifest).hexdigest()
    assert {population.kind for population in profile.populations} == {"file", "project"}
    assert {population.cohort.value for population in profile.populations} == {"production", "test"}
    assert all(
        distribution.sample_count >= 5
        for population in profile.populations
        for distribution in population.distributions
    )
    for cohort in ("production", "test"):
        assert any(
            population.kind == "project" and population.cohort.value == cohort
            for population in profile.populations
        )
        assert any(
            population.kind == "file" and population.cohort.value == cohort
            for population in profile.populations
        )


@pytest.fixture
def python_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    (tmp_path / "app.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
    (tmp_path / "constants.py").write_text("ANSWER = 42\n", encoding="utf-8")
    return tmp_path


def test_default_api_scan_uses_packaged_profile_and_explicit_no_functions_model(
    python_project: Path,
) -> None:
    report = scan(
        SnapshotRequest(
            target=DirectorySourceReference(root=python_project), config=AnalysisConfig()
        )
    )
    result = report.cohorts[0].current
    assert isinstance(result.score, MeasuredSnapshotScore)
    assert result.score.profile_id == "py-2026.3"
    by_path = {file.evidence.path.root: file for file in result.files}
    assert isinstance(by_path["app.py"].score, MeasuredSnapshotScore)
    constant = by_path["constants.py"]
    assert isinstance(constant.score, MeasuredSnapshotScore)
    assert {item.metric_id for item in constant.score.contributions} == {"verbosity.combined"}
    erosion = next(item for item in constant.metrics if item.metric_id == "m4.erosion")
    assert isinstance(erosion, UnavailableMetric)
    assert erosion.reason == "no-functions"
    assert constant.score.model_id != by_path["app.py"].score.model_id


def test_changed_metric_option_keeps_raw_measurements_but_refuses_packaged_score(
    python_project: Path,
) -> None:
    reference = DirectorySourceReference(root=python_project)
    baseline = scan(SnapshotRequest(target=reference, config=AnalysisConfig()))
    changed = scan(SnapshotRequest(target=reference, config=AnalysisConfig(clone_min_sloc=7)))
    result = changed.cohorts[0].current
    assert isinstance(result.score, UnavailableSnapshotScore)
    assert result.score.reason == "calibration-incompatible"
    assert [file.evidence for file in result.files] == [
        file.evidence for file in baseline.cohorts[0].current.files
    ]
    measured = [metric for metric in result.metrics if isinstance(metric, MeasuredMetric)]
    assert {metric.metric_id for metric in measured} >= {"verbosity.combined", "m4.erosion"}
    assert all(metric.score is None for metric in measured)


@pytest.mark.parametrize("profile_id,version", [("py-2026.1", "1"), ("py-2026.2", "2")])
def test_historical_profile_remains_readable_but_cannot_score_new_erosion(
    python_project: Path,
    profile_id: str,
    version: str,
) -> None:
    historical = load_profile(profile_id)
    assert historical is not None
    assert {item.metric_id: item.version for item in historical.metric_versions}[
        "m4.erosion"
    ] == version
    result = scan(
        SnapshotRequest(
            target=DirectorySourceReference(root=python_project),
            config=AnalysisConfig(calibration_profile=profile_id),
        )
    )
    current = result.cohorts[0].current
    assert isinstance(current.score, UnavailableSnapshotScore)
    assert current.score.reason == "calibration-incompatible"
    assert any(isinstance(metric, MeasuredMetric) for metric in current.metrics)
    assert all(
        metric.score is None for metric in current.metrics if isinstance(metric, MeasuredMetric)
    )
