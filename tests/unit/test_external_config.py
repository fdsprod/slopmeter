"""Explicit config files replace discovery without changing the analyzed root."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.cli import app
from slop_measure.config import load_analysis_config


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    root = tmp_path / "target"
    root.mkdir()
    (root / "pkg").mkdir()
    source = "def work(value):\n    result = value + 1\n    return result\n"
    for name in ("a.py", "b.py"):
        (root / "pkg" / name).write_text(source, encoding="utf-8", newline="\n")
    (root / "slop.toml").write_text(
        'clone_min_sloc=99\n[[boundaries]]\nname="local"\nprefix="pkg"\n', encoding="utf-8"
    )
    outside = tmp_path / "settings"
    outside.mkdir()
    external = outside / "analysis.toml"
    external.write_text(
        'clone_min_sloc=2\ncalibration_profile="__raw__"\nproduction_patterns=["pkg/**/*.py"]\n'
        '[[boundaries]]\nname="external"\nprefix="pkg"\n',
        encoding="utf-8",
    )
    return root, external


def expected() -> AnalysisConfig:
    return AnalysisConfig.model_validate(
        {
            "clone_min_sloc": 2,
            "calibration_profile": "__raw__",
            "production_patterns": ["pkg/**/*.py"],
            "boundaries": [{"name": "external", "prefix": "pkg"}],
        }
    )


def test_explicit_config_replaces_local_discovery_and_keeps_target_relative_paths(setup) -> None:
    root, external = setup
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    external_before = external.read_bytes()
    config = load_analysis_config(root, config_path=external)
    assert config == expected()
    assert load_analysis_config(root).clone_min_sloc == 99
    explicit = scan(SnapshotRequest(target=DirectorySourceReference(root=root), config=config))
    direct = scan(SnapshotRequest(target=DirectorySourceReference(root=root), config=expected()))
    assert explicit == direct
    assert len(explicit.clone_groups) == 1
    context = explicit.clone_groups[0].model_dump(mode="json")["boundary_context"]
    assert context["relation"] == "within-boundary"
    assert {item["boundary"] for item in context["members"]} == {"external"}
    assert str(external) not in explicit.model_dump_json()
    assert before == {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert external.read_bytes() == external_before


def test_explicit_file_ignores_malformed_local_files_and_cli_overrides_win(setup) -> None:
    root, external = setup
    for name in ("slop.toml", "pyproject.toml"):
        (root / name).write_text("[bad", encoding="utf-8")
    loaded = load_analysis_config(
        root, config_path=external, cli_overrides={"strict": True, "languages": ["python"]}
    )
    assert loaded.strict and loaded.languages == frozenset({"python"})
    assert loaded.clone_min_sloc == 2


def test_external_pyproject_reads_only_tool_slop(setup) -> None:
    root, external = setup
    external = external.with_name("pyproject.toml")
    external.write_text(
        '[project]\nname="unrelated"\nversion="1"\n[tool.slop]\nclone_min_sloc=3\n',
        encoding="utf-8",
    )
    config = load_analysis_config(root, config_path=external)
    assert config == AnalysisConfig(clone_min_sloc=3)


@pytest.mark.parametrize("problem", ["missing", "malformed", "invalid"])
def test_explicit_bad_config_never_falls_back(setup, problem: str) -> None:
    root, external = setup
    if problem == "missing":
        external = external.with_name("missing.toml")
    else:
        external.write_text("[bad" if problem == "malformed" else "unknown=true", encoding="utf-8")
    with pytest.raises((ValueError, OSError)):
        load_analysis_config(root, config_path=external)
    result = CliRunner().invoke(app, ["score", str(root), "--config", str(external), "--json"])
    assert result.exit_code == 2
    assert "Invalid analysis input:" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    "command", ["score", "scan", "tree", "compare", "explain", "findings", "rules"]
)
def test_every_analysis_command_accepts_external_config_at_command_level(
    setup, command: str
) -> None:
    root, external = setup
    if command == "compare":
        args = [command, str(root), str(root)]
    elif command == "explain":
        args = [command, "pkg/a.py", "--root", str(root)]
    elif command in {"findings", "rules"}:
        args = [command, "--root", str(root)]
    else:
        args = [command, str(root)]
    (root / "slop.toml").write_text("[bad", encoding="utf-8")
    result = CliRunner().invoke(app, [*args, "--config", str(external), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    if command != "rules":
        assert payload["provenance"]["config"] == expected().model_dump(mode="json")
        groups = (
            payload["selection"]["clone_groups"]
            if command == "findings"
            else payload["clone_groups"]
        )
        assert groups
    assert str(external) not in result.stdout


def test_external_file_allows_language_and_strict_cli_overrides(setup) -> None:
    root, external = setup
    (root / "pkg" / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    args = ["score", str(root), "--config", str(external), "--lang", "py", "--json"]
    ordinary = CliRunner().invoke(app, args)
    assert ordinary.exit_code == 0, ordinary.output
    assert json.loads(ordinary.stdout)["provenance"]["config"]["languages"] == ["python"]
    strict = CliRunner().invoke(app, [*args, "--strict"])
    assert strict.exit_code == 3, strict.output


def test_review_commands_use_external_config_without_installing_target_config(setup) -> None:
    root, external = setup
    (root / "slop.toml").unlink()
    store = external.parent / "reviews.json"
    runner = CliRunner()
    scanned = runner.invoke(app, ["scan", str(root), "--config", str(external), "--json"])
    assert scanned.exit_code == 0, scanned.output
    group_id = json.loads(scanned.stdout)["clone_groups"][0]["id"]
    source_before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    config_before = external.read_bytes()
    written = runner.invoke(
        app,
        [
            "review",
            "set",
            group_id,
            "--root",
            str(root),
            "--store",
            str(store),
            "--config",
            str(external),
            "--disposition",
            "no-change",
            "--reason",
            "Separate contracts.",
            "--next-step",
            "Recheck contract changes.",
        ],
    )
    assert written.exit_code == 0, written.output
    stored = store.read_bytes()
    shown = runner.invoke(
        app,
        [
            "review",
            "show",
            "--root",
            str(root),
            "--store",
            str(store),
            "--config",
            str(external),
            "--json",
        ],
    )
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.stdout)["review_results"][0]["state"] == "current"
    ordinary = runner.invoke(
        app, ["score", str(root), "--reviews", str(store), "--config", str(external), "--json"]
    )
    assert ordinary.exit_code == 0, ordinary.output
    assert store.read_bytes() == stored and external.read_bytes() == config_before
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == source_before
    assert not (root / "slop.toml").exists()
