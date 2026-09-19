"""The experiment has owned outcomes and remains separate from calibrated scans."""

from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from slop_measure.api import (
    AnalysisConfig,
    DirectorySourceReference,
    GitSourceReference,
    SnapshotRequest,
)
from slop_measure.application.models import inspect_models
from slop_measure.domain.model_review import AnalyzedModel, CoupledStateFinding
from slop_measure.errors import InputError


def finding_payload() -> dict:
    return {
        "kind": "coupled-state",
        "predicate": "model.active and model.value is None",
        "fields": [
            {"name": "active", "kind": "boolean", "span": {"start_line": 3, "end_line": 3}},
            {"name": "value", "kind": "nullable", "span": {"start_line": 4, "end_line": 4}},
        ],
        "validator": {"symbol": "State.__post_init__", "span": {"start_line": 6, "end_line": 6}},
        "consumers": [
            {"symbol": "first", "span": {"start_line": 10, "end_line": 10}},
            {"symbol": "second", "span": {"start_line": 15, "end_line": 15}},
        ],
    }


@pytest.mark.parametrize(
    "invalid",
    [
        "one-field",
        "duplicate-field",
        "no-boolean",
        "no-nullable",
        "one-consumer",
        "duplicate-consumer",
    ],
)
def test_finding_rejects_invalid_cross_field_and_consumer_evidence(invalid: str) -> None:
    payload = finding_payload()
    if invalid == "one-field":
        payload["fields"].pop()
    elif invalid == "duplicate-field":
        payload["fields"].append(deepcopy(payload["fields"][0]))
    elif invalid == "no-boolean":
        payload["fields"][0]["kind"] = "nullable"
    elif invalid == "no-nullable":
        payload["fields"][1]["kind"] = "boolean"
    elif invalid == "one-consumer":
        payload["consumers"].pop()
    else:
        payload["consumers"][1]["symbol"] = "first"
    with pytest.raises(ValidationError):
        CoupledStateFinding.model_validate(payload)


def test_model_owns_validator_location_and_rejects_external_span() -> None:
    payload = {
        "state": "analyzed",
        "name": "State",
        "span": {"start_line": 2, "end_line": 8},
        "findings": [finding_payload()],
    }
    model = AnalyzedModel.model_validate(payload)
    assert model.findings[0].validator.span.start_line == 6
    payload["findings"][0]["validator"]["span"] = {"start_line": 20, "end_line": 20}
    with pytest.raises(ValidationError):
        AnalyzedModel.model_validate(payload)


def test_directory_inspection_reports_failed_files_and_coverage_without_calibrated_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    (tmp_path / "good.py").write_text('raise RuntimeError("must not execute")\n', encoding="utf-8")
    (tmp_path / "bad.py").write_text("class Broken(:\n", encoding="utf-8")
    (tmp_path / "skip.py").write_text("class Broken(:\n", encoding="utf-8")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "skip.py").write_text("class Broken(:\n", encoding="utf-8")

    def forbidden_scan(*args, **kwargs):
        raise AssertionError("Experiment must not call calibrated scan")

    monkeypatch.setattr("slop_measure.application.service.AnalysisService.scan", forbidden_scan)
    request = SnapshotRequest(
        target=DirectorySourceReference(root=tmp_path),
        config=AnalysisConfig(exclusions=("vendor/**", "skip.py")),
    )
    report = inspect_models(request)
    payload = report.model_dump(mode="json")
    assert payload["schema_version"] == "1" and payload["experiment"] == "py-coupled-state-1"
    assert payload["source"]["kind"] == "directory"
    assert [file["path"] for file in payload["files"]] == ["bad.py", "good.py"]
    assert [file["state"] for file in payload["files"]] == ["failed", "analyzed"]
    assert payload["inventory_coverage"] and payload["diagnostics"]
    assert payload["excluded_directories"]
    assert payload["interpretation"] and payload["tool_version"]
    assert "score" not in payload and "cohorts" not in payload
    assert type(report).model_validate_json(report.model_dump_json()) == report
    assert inspect_models(request) == report


def test_git_model_inspection_is_explicitly_outside_experiment(tmp_path: Path) -> None:
    request = SnapshotRequest(
        target=GitSourceReference(root=tmp_path, revision="HEAD"), config=AnalysisConfig()
    )
    with pytest.raises(InputError):
        inspect_models(request)
