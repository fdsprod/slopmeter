"""Experimental model review owns source evidence without changing scored reports."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure.api import (
    AnalysisConfig,
    DirectorySourceReference,
    GitSourceReference,
    SnapshotRequest,
    scan,
)
from slop_measure.application.models import inspect_models
from slop_measure.cli import app

SOURCE = """from dataclasses import dataclass

@dataclass
class Item:
    enabled: bool
    value: str | None

    def __post_init__(self):
        if self.enabled and self.value is None:
            raise ValueError("Enabled items need a value")

def first(item: Item):
    if item.enabled and item.value is None:
        return False
    return True

def second(other: "Item"):
    if other.enabled and other.value is None:
        return None
    return other.value
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    root = tmp_path / "project"
    root.mkdir()
    (root / "model.py").write_text(SOURCE, encoding="utf-8", newline="\n")
    marker = tmp_path / "executed.txt"
    (root / "never_execute.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
        newline="\n",
    )
    return root, marker


def request(root: Path, *, strict: bool = False) -> SnapshotRequest:
    return SnapshotRequest(
        target=DirectorySourceReference(root=root),
        config=AnalysisConfig(calibration_profile="__raw__", strict=strict),
    )


def test_api_experiment_is_distinct_owned_evidence_and_does_not_execute_or_change_scores(
    project,
) -> None:
    root, marker = project
    before = scan(request(root))
    result = inspect_models(request(root))
    payload = result.model_dump(mode="json")
    assert payload["schema_version"] == "1"
    assert payload["experiment"] == "py-coupled-state-1"
    assert payload["source"]["root"] == str(root.resolve())
    assert "score" not in payload and "cohorts" not in payload and "provenance" not in payload
    assert isinstance(payload["inventory_coverage"], list) and payload["interpretation"]
    model_file = next(file for file in payload["files"] if file["path"] == "model.py")
    assert model_file["state"] == "analyzed" and model_file["cohort"] == "production"
    assert (
        model_file["source_sha256"] == hashlib.sha256((root / "model.py").read_bytes()).hexdigest()
    )
    assessment = model_file["models"][0]
    assert assessment["name"] == "Item" and assessment["state"] == "analyzed"
    finding = assessment["findings"][0]
    assert finding["kind"] == "coupled-state"
    assert {(field["name"], field["kind"]) for field in finding["fields"]} == {
        ("enabled", "boolean"),
        ("value", "nullable"),
    }
    assert "model.enabled" in finding["predicate"] and "model.value" in finding["predicate"]
    assert {consumer["symbol"] for consumer in finding["consumers"]} == {"first", "second"}
    assert "__post_init__" in finding["validator"]["symbol"]
    assert not marker.exists()
    assert scan(request(root)) == before
    assert inspect_models(request(root)).model_dump_json() == result.model_dump_json()


def test_command_supports_external_config_language_strict_and_pure_json(project) -> None:
    root, marker = project
    (root / "slop.toml").write_text("[malformed", encoding="utf-8")
    (root / "excluded.py").write_text("def broken(:\n", encoding="utf-8")
    external = root.parent / "external.toml"
    external.write_text(
        'exclusions=["excluded.py"]\nlanguages=[]\nstrict=false\n', encoding="utf-8"
    )
    original = external.read_bytes()
    result = CliRunner().invoke(
        app,
        [
            "models",
            "--root",
            str(root),
            "--config",
            str(external),
            "--lang",
            "py",
            "--strict",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["experiment"] == "py-coupled-state-1"
    assert payload["config"]["languages"] == ["python"] and payload["config"]["strict"] is True
    assert "excluded.py" not in {file["path"] for file in payload["files"]}
    assert str(external) not in result.stdout
    assert external.read_bytes() == original and not marker.exists()


def test_parse_failure_is_explicit_and_strict_cli_fails(project) -> None:
    root, _ = project
    (root / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    args = ["models", "--root", str(root), "--json"]
    ordinary = CliRunner().invoke(app, args)
    assert ordinary.exit_code == 0, ordinary.output
    payload = json.loads(ordinary.stdout)
    broken = next(file for file in payload["files"] if file["path"] == "broken.py")
    assert broken["state"] == "failed" and broken["diagnostic"]
    assert "models" not in broken
    assert any(
        file["state"] == "analyzed" and file["path"] == "model.py" for file in payload["files"]
    )
    strict = CliRunner().invoke(app, [*args, "--strict"])
    assert strict.exit_code == 3 and strict.stderr


def test_experiment_honors_git_ignores_and_generated_markers(project) -> None:
    root, _ = project
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, "init", "--quiet", str(root)], check=True, capture_output=True)  # noqa: S603
    (root / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (root / "ignored.py").write_text(SOURCE, encoding="utf-8")
    (root / "generated.py").write_text("# @generated\n" + SOURCE, encoding="utf-8")
    (root / "test_model.py").write_text(SOURCE, encoding="utf-8")
    report = inspect_models(request(root)).model_dump(mode="json")
    paths = {file["path"] for file in report["files"]}
    assert "ignored.py" not in paths and "generated.py" not in paths
    assert "model.py" in paths and "test_model.py" in paths
    assert (
        next(file for file in report["files"] if file["path"] == "test_model.py")["cohort"]
        == "test"
    )


def test_non_python_selection_and_git_source_fail_explicitly(project) -> None:
    root, _ = project
    cli = CliRunner().invoke(app, ["models", "--root", str(root), "--lang", "ts", "--json"])
    assert cli.exit_code == 2 and "Invalid analysis input:" in cli.stderr
    with pytest.raises(ValueError):
        inspect_models(SnapshotRequest(target=GitSourceReference(root=root, revision="HEAD")))
