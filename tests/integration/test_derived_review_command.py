"""Derived-state review is separate, source-bound, deterministic, and never executes code."""

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.application.derived import inspect_derived
from slop_measure.cli import app
from slop_measure.errors import AnalysisFailure

SOURCE = (
    "def work():\n    items = [1]\n    count = len(items)\n    items.append(2)\n    return count\n"
)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    root = tmp_path / "project"
    root.mkdir()
    (root / "derived.py").write_text(SOURCE, encoding="utf-8", newline="\n")
    marker = tmp_path / "executed"
    (root / "side_effect.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8"
    )
    return root, marker


def request(root: Path, *, strict: bool = False) -> SnapshotRequest:
    return SnapshotRequest(
        target=DirectorySourceReference(root=root), config=AnalysisConfig(strict=strict)
    )


def test_derived_api_report_is_source_bound_and_does_not_change_snapshot(project) -> None:
    root, marker = project
    original = scan(request(root)).model_dump_json()
    report = inspect_derived(request(root))
    wire = report.model_dump(mode="json")
    assert wire["schema_version"] == "1" and wire["experiment"] == "py-derived-state-1"
    assert wire["interpretation"] and isinstance(wire["inventory_coverage"], list)
    assert "score" not in wire and "cohorts" not in wire
    analyzed = next(item for item in wire["files"] if item["path"] == "derived.py")
    assert analyzed["cohort"] == "production"
    assert analyzed["source_sha256"] == hashlib.sha256(SOURCE.encode()).hexdigest()
    assert analyzed["functions"][0]["findings"][0]["derived_name"] == "count"
    assert type(report).model_validate_json(report.model_dump_json()) == report
    assert report.model_dump_json() == inspect_derived(request(root)).model_dump_json()
    assert original == scan(request(root)).model_dump_json()
    assert not marker.exists()


def test_derived_cli_json_matches_api_and_plain_output_frames_review_candidate(project) -> None:
    root, marker = project
    runner = CliRunner()
    result = runner.invoke(app, ["derived", "--root", str(root), "--lang", "py", "--json"])
    assert result.exit_code == 0, result.output
    selected = SnapshotRequest(
        target=DirectorySourceReference(root=root),
        config=AnalysisConfig.model_validate({"languages": ["python"]}),
    )
    assert json.loads(result.stdout) == inspect_derived(selected).model_dump(mode="json")
    plain = runner.invoke(app, ["derived", "--root", str(root)])
    assert plain.exit_code == 0
    assert "count" in plain.stdout and "items" in plain.stdout
    assert "review" in plain.stdout.lower()
    assert not marker.exists()


def test_derived_parse_failure_remains_visible_and_strict_fails(project) -> None:
    root, _ = project
    (root / "bad.py").write_text("def invalid(:\n", encoding="utf-8")
    report = inspect_derived(request(root))
    wire = report.model_dump(mode="json")
    bad = next(item for item in wire["files"] if item["path"] == "bad.py")
    assert bad["state"] == "failed"
    assert any(item["state"] == "analyzed" for item in wire["files"])
    with pytest.raises(AnalysisFailure):
        inspect_derived(request(root, strict=True))
    runner = CliRunner()
    assert runner.invoke(app, ["derived", "--root", str(root), "--json"]).exit_code == 0
    assert runner.invoke(app, ["derived", "--root", str(root), "--strict"]).exit_code == 3


def test_derived_cli_loads_config_and_rejects_unknown_language(project) -> None:
    root, _ = project
    config = root / "custom.toml"
    config.write_text('exclusions = ["derived.py"]\n', encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(app, ["derived", "--root", str(root), "--config", str(config), "--json"])
    assert result.exit_code == 0, result.output
    assert "derived.py" not in {item["path"] for item in json.loads(result.stdout)["files"]}
    assert runner.invoke(app, ["derived", "--root", str(root), "--lang", "unknown"]).exit_code == 2
