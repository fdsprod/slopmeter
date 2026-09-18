"""Language selection is canonical, explicit, and shared by analysis commands."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.cli import app
from slop_measure.config import load_analysis_config


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    (tmp_path / "a.py").write_text(
        "def f(flag):\n    return True if flag else False\n", encoding="utf-8"
    )
    (tmp_path / "unrelated.ts").write_text("const value = 1;\n", encoding="utf-8")
    (tmp_path / "slop.toml").write_text('calibration_profile = "__raw__"\n', encoding="utf-8")
    return tmp_path


def test_default_languages_are_immutable_and_omitted_from_serialized_config() -> None:
    default = AnalysisConfig()
    assert default.languages == frozenset()
    assert "languages" not in default.model_dump(mode="json")
    assert "languages" not in default.model_dump()
    selected = AnalysisConfig.model_validate({"languages": ["python"]})
    assert selected.languages == frozenset({"python"})
    assert selected.model_dump(mode="json")["languages"] == ["python"]
    assert AnalysisConfig.model_validate_json(selected.model_dump_json()) == selected
    with pytest.raises(ValidationError):
        selected.languages = frozenset()


@pytest.mark.parametrize("command", ["score", "scan", "tree", "compare", "explain", "findings"])
def test_every_analysis_command_accepts_repeated_comma_aliases(project: Path, command: str) -> None:
    if command == "compare":
        arguments = [command, str(project), str(project)]
    elif command == "explain":
        arguments = [command, "a.py", "--root", str(project)]
    elif command == "findings":
        arguments = [command, "--root", str(project)]
    else:
        arguments = [command, str(project)]
    result = CliRunner().invoke(
        app, [*arguments, "--lang", "py,python", "--langs", ".PY", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["provenance"]["config"]["languages"] == ["python"]
    if command != "findings":
        assert all(item["detail"]["language"] != "ts" for item in payload["coverage"])


@pytest.mark.parametrize("language", ["ts", "typescript", "unknown"])
def test_unavailable_languages_fail_with_direct_input_error(project: Path, language: str) -> None:
    result = CliRunner().invoke(app, ["score", str(project), "--lang", language])
    assert result.exit_code == 2
    assert "Invalid analysis input:" in result.output
    assert language in result.output
    assert "Traceback" not in result.output


def test_omitted_cli_language_preserves_file_selection_and_explicit_option_overrides(
    project: Path,
) -> None:
    settings = project / "slop.toml"
    settings.write_text(
        'languages = ["python"]\ncalibration_profile = "__raw__"\n', encoding="utf-8"
    )
    loaded = load_analysis_config(project)
    assert loaded.languages == frozenset({"python"})
    result = CliRunner().invoke(app, ["score", str(project), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["provenance"]["config"]["languages"] == ["python"]
    settings.write_text(
        'languages = ["unsupported"]\ncalibration_profile = "__raw__"\n', encoding="utf-8"
    )
    override = CliRunner().invoke(app, ["score", str(project), "--lang", "py", "--json"])
    assert override.exit_code == 0, override.output
    assert json.loads(override.stdout)["provenance"]["config"]["languages"] == ["python"]


def test_public_api_filter_retains_python_facts_and_omits_unselected_noise(project: Path) -> None:
    config = AnalysisConfig.model_validate(
        {"languages": ["python"], "calibration_profile": "__raw__"}
    )
    report = scan(SnapshotRequest(target=DirectorySourceReference(root=project), config=config))
    assert report.provenance.config.languages == frozenset({"python"})
    assert all(item.detail.language == "python" for item in report.coverage)
    assert [
        file.evidence.path.root for cohort in report.cohorts for file in cohort.current.files
    ] == ["a.py"]
    assert report.findings
