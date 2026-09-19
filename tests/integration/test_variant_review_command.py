"""Variant review exposes finite-case coverage without changing existing analyses."""

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
from slop_measure.application.variants import inspect_variants
from slop_measure.cli import app
from slop_measure.errors import InputError

SOURCE = """from enum import Enum
from typing import Literal

class Mode(Enum):
    ON = "on"
    OFF = "off"

def partial(mode: Mode):
    match mode:
        case Mode.ON:
            return 1

def fallback(mode: Mode):
    match mode:
        case Mode.ON:
            return 1
        case _:
            return 0

def complete(mode: Mode):
    match mode:
        case Mode.ON | Mode.OFF:
            return 1

Choice = Literal["yes", "no"]

def literal(choice: Choice):
    match choice:
        case "yes":
            return True
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    root = tmp_path / "project"
    root.mkdir()
    (root / "variants.py").write_text(SOURCE, encoding="utf-8", newline="\n")
    marker = tmp_path / "executed.txt"
    (root / "no_execution.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n",
        encoding="utf-8",
        newline="\n",
    )
    return root, marker


def request(root: Path, *, strict: bool = False) -> SnapshotRequest:
    return SnapshotRequest(
        target=DirectorySourceReference(root=root), config=AnalysisConfig(strict=strict)
    )


def test_variant_api_owns_exact_case_coverage_locations_and_keeps_other_reports_unchanged(
    project,
) -> None:
    root, marker = project
    ordinary = scan(request(root)).model_dump_json()
    models = inspect_models(request(root)).model_dump_json()
    result = inspect_variants(request(root))
    payload = result.model_dump(mode="json")
    assert payload["schema_version"] == "1" and payload["experiment"] == "py-variant-review-1"
    assert "cohorts" not in payload and "score" not in payload
    assert payload["interpretation"] and isinstance(payload["inventory_coverage"], list)
    file = next(item for item in payload["files"] if item["path"] == "variants.py")
    assert file["state"] == "analyzed" and file["cohort"] == "production"
    assert file["source_sha256"] == hashlib.sha256((root / "variants.py").read_bytes()).hexdigest()
    handlers = {item["symbol"]: item for item in file["handlers"]}
    assert set(handlers) == {"partial", "fallback", "complete", "literal"}
    for name, coverage, missing, line in (
        ("partial", "missing", ["Mode.OFF"], 9),
        ("fallback", "fallback", ["Mode.OFF"], 14),
        ("complete", "exhaustive", [], 21),
        ("literal", "missing", ["'no'"], 28),
    ):
        handler = handlers[name]
        assert handler["state"] == "analyzed"
        assert handler["coverage"] == coverage and handler["unhandled_cases"] == missing
        assert handler["span"]["start_line"] == line
        assert handler["declaration"]["span"]["start_line"] == (25 if name == "literal" else 4)
        for branch in handler["branches"]:
            assert (
                line
                < branch["span"]["start_line"]
                <= branch["span"]["end_line"]
                <= handler["span"]["end_line"]
            )
    assert handlers["fallback"]["branches"][-1]["kind"] == "fallback"
    assert not marker.exists()
    assert inspect_variants(request(root)).model_dump_json() == result.model_dump_json()
    assert scan(request(root)).model_dump_json() == ordinary
    assert inspect_models(request(root)).model_dump_json() == models


def test_variant_terminal_and_json_distinguish_missing_fallback_and_exhaustive(project) -> None:
    root, _ = project
    runner = CliRunner()
    machine = runner.invoke(
        app, ["variants", "--root", str(root), "--lang", "py", "--strict", "--json"]
    )
    assert machine.exit_code == 0, machine.output
    assert json.loads(machine.stdout)["experiment"] == "py-variant-review-1"
    shown = runner.invoke(app, ["variants", "--root", str(root)])
    assert shown.exit_code == 0, shown.output
    text = shown.stdout
    for word in (
        "py-variant-review-1",
        "partial",
        "fallback",
        "complete",
        "missing",
        "exhaustive",
        "Mode.OFF",
        "variants.py",
    ):
        assert word in text
    assert ":9" in text or "line 9" in text.lower()
    assert "no score" in text.lower() or "not scored" in text.lower()
    assert "/100" not in text


def test_variant_parse_failure_is_tagged_and_strict_fails(project) -> None:
    root, _ = project
    (root / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    normal = CliRunner().invoke(app, ["variants", "--root", str(root), "--json"])
    assert normal.exit_code == 0, normal.output
    files = json.loads(normal.stdout)["files"]
    failed = next(item for item in files if item["path"] == "bad.py")
    assert failed["state"] == "failed" and failed["diagnostic"]["path"] == "bad.py"
    assert "handlers" not in failed
    strict = CliRunner().invoke(app, ["variants", "--root", str(root), "--strict", "--json"])
    assert strict.exit_code == 3 and strict.stderr


def test_variant_command_honors_git_ignores_external_config_and_exclusions(project) -> None:
    root, marker = project
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, "init", "--quiet", str(root)], check=True, capture_output=True)  # noqa: S603
    (root / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    for name in ("ignored.py", "excluded.py"):
        (root / name).write_text("def broken(:\n", encoding="utf-8")
    (root / "slop.toml").write_text("[bad", encoding="utf-8")
    config = root.parent / "external.toml"
    config.write_text('exclusions=["excluded.py"]\nstrict=false\nlanguages=[]\n', encoding="utf-8")
    original = config.read_bytes()
    result = CliRunner().invoke(
        app,
        [
            "variants",
            "--root",
            str(root),
            "--config",
            str(config),
            "--lang",
            "py",
            "--strict",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["config"]["strict"] is True and payload["config"]["languages"] == ["python"]
    assert {file["path"] for file in payload["files"]} == {"variants.py", "no_execution.py"}
    assert config.read_bytes() == original and not marker.exists()


def test_variant_rejects_unsupported_languages_and_non_directory_requests(project) -> None:
    root, _ = project
    cli = CliRunner().invoke(app, ["variants", "--root", str(root), "--lang", "ts", "--json"])
    assert cli.exit_code == 2 and "Invalid analysis input:" in cli.stderr
    with pytest.raises(InputError):
        inspect_variants(
            SnapshotRequest(
                target=GitSourceReference(root=root, revision="HEAD"), config=AnalysisConfig()
            )
        )
