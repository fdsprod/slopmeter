"""Service calibration failures preserve a complete raw analysis."""

from pathlib import Path

import pytest
from test_calibration_contract import profile_payload

from slop_measure.application.service import AnalysisService
from slop_measure.config import AnalysisConfig
from slop_measure.domain.reports import MeasuredSnapshotScore, UnavailableSnapshotScore
from slop_measure.domain.requests import SnapshotRequest
from slop_measure.domain.scoring import CalibrationProfile
from slop_measure.domain.source import DirectorySourceReference


def request(root: Path) -> SnapshotRequest:
    return SnapshotRequest(target=DirectorySourceReference(root=root), config=AnalysisConfig())


def test_service_loads_selected_profile_and_scores_file_and_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    (tmp_path / "app.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
    service = AnalysisService()
    baseline = service.scan(request(tmp_path))
    payload = profile_payload()
    analyzer = baseline.provenance.analyzers[0]
    payload["rule_set_version"] = analyzer.rule_set_version
    payload["clone_normalization_version"] = analyzer.clone_normalization_version
    payload["metric_versions"] = [item.model_dump() for item in baseline.provenance.metrics]
    profile = CalibrationProfile.model_validate(payload)
    selected = []

    def load(identifier: str) -> CalibrationProfile:
        selected.append(identifier)
        return profile

    monkeypatch.setattr("slop_measure.application.service.load_profile", load, raising=False)
    result = service.scan(request(tmp_path))
    assert selected == ["py-2026.3"]
    cohort = result.cohorts[0].current
    assert isinstance(cohort.score, MeasuredSnapshotScore)
    assert isinstance(cohort.files[0].score, MeasuredSnapshotScore)
    assert cohort.files[0].evidence == baseline.cohorts[0].current.files[0].evidence
    assert result.provenance == baseline.provenance


def test_malformed_profile_returns_raw_results_with_incompatible_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    (tmp_path / "app.py").write_text("def answer():\n    return 42\n", encoding="utf-8")

    def broken(_identifier: str) -> CalibrationProfile:
        raise ValueError("manifest hash mismatch")

    monkeypatch.setattr("slop_measure.application.service.load_profile", broken, raising=False)
    result = AnalysisService().scan(request(tmp_path))
    cohort = result.cohorts[0].current
    assert isinstance(cohort.score, UnavailableSnapshotScore)
    assert cohort.score.reason == "calibration-incompatible"
    assert cohort.files[0].evidence.sloc == 2
    assert isinstance(cohort.files[0].score, UnavailableSnapshotScore)
    assert cohort.files[0].score.reason == "calibration-incompatible"
    assert {item.metric_id for item in cohort.metrics} >= {"verbosity.combined", "m4.erosion"}
