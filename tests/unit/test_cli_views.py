"""Snapshot navigation commands share one report and validate view selectors."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure.cli import app


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text(
        "def f(value):\n    return True if value else False\n"
        "def duplicate():\n    return 1\n"
        "def duplicate():\n    return 2\n",
        encoding="utf-8",
    )
    (tmp_path / "other.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_case.py").write_text("VALUE = 2\n", encoding="utf-8")
    return tmp_path


def test_score_and_scan_json_are_identical_and_view_options_do_not_change_report(
    project: Path,
) -> None:
    runner = CliRunner()
    baseline = runner.invoke(app, ["scan", str(project), "--json"])
    assert baseline.exit_code == 0, baseline.output
    expected = json.loads(baseline.stdout)
    for command in ("score", "scan"):
        actual = runner.invoke(
            app,
            [
                command,
                str(project),
                "--json",
                "--top",
                "1",
                "--scope",
                "test",
                "--ascii",
                "--verbose",
                "--color",
                "never",
            ],
        )
        assert actual.exit_code == 0, actual.output
        assert json.loads(actual.stdout) == expected
    assert expected["provenance"]["config"]["default_hotspot_count"] == 5
    assert sum(len(cohort["current"]["files"]) for cohort in expected["cohorts"]) == 3


@pytest.mark.parametrize("command", ["score", "tree"])
def test_navigation_commands_default_to_current_directory(
    project: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    monkeypatch.chdir(project)
    result = CliRunner().invoke(app, [command, "--ascii", "--no-color"])
    assert result.exit_code == 0, result.output
    assert "app.py" in result.stdout and "other.py" in result.stdout
    assert result.stdout.isascii()
    assert "\x1b[" not in result.stdout


def test_explain_selects_file_and_exact_callable_evidence(project: Path) -> None:
    runner = CliRunner()
    file = runner.invoke(app, ["explain", "src/app.py", "--root", str(project), "--no-color"])
    assert file.exit_code == 0, file.output
    assert "py.boolean-conditional" in file.stdout
    assert "duplicate" in file.stdout
    symbol = runner.invoke(
        app,
        [
            "explain",
            "src/app.py",
            "--root",
            str(project),
            "--symbol",
            "duplicate",
            "--line",
            "5",
            "--no-color",
        ],
    )
    assert symbol.exit_code == 0, symbol.output
    assert "duplicate" in symbol.stdout
    assert "5-6" in symbol.stdout
    assert "CC" in symbol.stdout and "SLOC" in symbol.stdout and "mass" in symbol.stdout.lower()
    assert "py.boolean-conditional" not in symbol.stdout


def test_explain_defaults_root_to_current_directory(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(project)
    result = CliRunner().invoke(app, ["explain", r"src\app.py", "--symbol", "f", "--no-color"])
    assert result.exit_code == 0, result.output
    assert "py.boolean-conditional" in result.stdout


@pytest.mark.parametrize(
    "selector",
    [
        ["missing.py"],
        ["src/app.py", "--symbol", "missing"],
        ["src/app.py", "--symbol", "duplicate"],
        ["src/app.py", "--line", "5"],
        ["src/app.py", "--symbol", "duplicate", "--line", "6"],
        ["../other.py"],
    ],
)
def test_explain_invalid_or_ambiguous_selectors_exit_two(
    project: Path, selector: list[str]
) -> None:
    result = CliRunner().invoke(app, ["explain", *selector, "--root", str(project)])
    assert result.exit_code == 2, result.output


@pytest.mark.parametrize(
    "arguments",
    [["--top", "0"], ["--top", "-1"], ["--color", "invalid"], ["--color", "always", "--no-color"]],
)
def test_invalid_view_options_exit_two(project: Path, arguments: list[str]) -> None:
    result = CliRunner().invoke(app, ["score", str(project), *arguments])
    assert result.exit_code == 2, result.output


def test_explicit_color_always_overrides_no_color_environment(project: Path) -> None:
    result = CliRunner().invoke(
        app, ["score", str(project), "--color", "always"], env={"NO_COLOR": "1"}, color=True
    )
    assert result.exit_code == 0, result.output
    assert "\x1b[" in result.stdout


@pytest.mark.parametrize(
    "arguments,environment",
    [
        (["--color", "auto"], {}),
        (["--color", "auto"], {"NO_COLOR": "1"}),
        (["--color", "never"], {}),
        (["--no-color"], {}),
    ],
)
def test_redirected_auto_and_disabled_color_emit_no_ansi(
    project: Path, arguments: list[str], environment: dict[str, str]
) -> None:
    result = CliRunner().invoke(
        app, ["score", str(project), *arguments], env=environment, color=True
    )
    assert result.exit_code == 0, result.output
    assert "\x1b[" not in result.stdout


@pytest.mark.parametrize("command", ["score", "tree"])
def test_new_commands_share_strict_failure_exit_code(project: Path, command: str) -> None:
    (project / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    result = CliRunner().invoke(app, [command, str(project), "--strict"])
    assert result.exit_code == 3, result.output


def test_explain_uses_snapshot_evidence_without_executing_target(project: Path) -> None:
    target = project / "side_effect.py"
    target.write_text(
        "from pathlib import Path\nPath(__file__).with_name('EXECUTED').write_text('bad')\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["explain", "side_effect.py", "--root", str(project)])
    assert result.exit_code == 0, result.output
    assert not (project / "EXECUTED").exists()
