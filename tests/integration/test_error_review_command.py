"""Exception fallback review reports source evidence without executing or scoring it."""

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.application.error_review import inspect_errors
from slop_measure.cli import app
from slop_measure.domain.error_review import ErrorReviewReport
from slop_measure.errors import AnalysisFailure

SOURCE = """def fetch(client):
    try:
        result = client.read()
    except OSError:
        return []
    return result
"""
CONTROLS = """def reraises(client):
    try:
        result = client.read()
    except OSError:
        raise
    return result

def conditional(client, flag):
    try:
        result = client.read()
    except OSError:
        if flag:
            return []
        return None
    return result
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    root = tmp_path / "project"
    root.mkdir()
    (root / "fallback.py").write_text(SOURCE, encoding="utf-8", newline="\n")
    marker = tmp_path / "executed"
    (root / "side_effect.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8"
    )
    return root, marker


def request(root: Path, *, strict: bool = False) -> SnapshotRequest:
    return SnapshotRequest(
        target=DirectorySourceReference(root=root), config=AnalysisConfig(strict=strict)
    )


def test_error_api_is_deterministic_source_bound_read_only_and_score_neutral(project) -> None:
    root, marker = project
    files = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    before = scan(request(root)).model_dump_json()
    report = inspect_errors(request(root))
    assert isinstance(report, ErrorReviewReport)
    wire = report.model_dump(mode="json")
    assert wire["schema_version"] == "1" and wire["experiment"] == "py-error-fallback-1"
    assert not {"score", "cohorts", "provenance"} & wire.keys()
    assert isinstance(wire["inventory_coverage"], list) and wire["interpretation"]
    source = next(item for item in wire["files"] if item["path"] == "fallback.py")
    assert source["cohort"] == "production"
    assert source["source_sha256"] == hashlib.sha256(SOURCE.encode()).hexdigest()
    finding = source["handlers"][0]["findings"][0]
    assert finding["kind"] == "error-as-success" and finding["caught"] == "OSError"
    assert finding["fallback"]["expression"] == "[]"
    assert finding["normal_returns"][0]["expression"] == "result"
    assert ErrorReviewReport.model_validate_json(report.model_dump_json()) == report
    assert report.model_dump_json() == inspect_errors(request(root)).model_dump_json()
    assert before == scan(request(root)).model_dump_json()
    assert files == {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert not marker.exists()


def test_error_cli_json_matches_api_and_plain_output_exposes_evidence_and_limits(project) -> None:
    root, marker = project
    runner = CliRunner()
    result = runner.invoke(app, ["errors", "--root", str(root), "--lang", "py", "--json"])
    assert result.exit_code == 0, result.output
    selected = SnapshotRequest(
        target=DirectorySourceReference(root=root),
        config=AnalysisConfig.model_validate({"languages": ["python"]}),
    )
    wire = inspect_errors(selected).model_dump(mode="json")
    assert json.loads(result.stdout) == wire
    plain = runner.invoke(app, ["errors", "--root", str(root)])
    assert plain.exit_code == 0, plain.output
    text = " ".join(plain.stdout.lower().split())
    for expected in ("fallback.py", "fetch", "oserror", "client.read()", "result", "[]"):
        assert expected in text
    for expected in ("coverage", "assessed", "unresolved", "findings", "review", "score"):
        assert expected in text
    interpretation = " ".join(wire["interpretation"]).lower()
    assert "intentional" in interpretation and "contract" in interpretation
    assert "execut" in interpretation
    assert not marker.exists()


def test_error_cli_external_config_exclusions_and_cohorts(project) -> None:
    root, marker = project
    (root / "slop.toml").write_text("[malformed", encoding="utf-8")
    (root / "excluded.py").write_text("def broken(:\n", encoding="utf-8")
    (root / "test_fallback.py").write_text(SOURCE, encoding="utf-8")
    (root / "generated.py").write_text("# @generated\n" + SOURCE, encoding="utf-8")
    config = root.parent / "external.toml"
    config.write_text('exclusions=["excluded.py"]\nlanguages=[]\nstrict=false\n', encoding="utf-8")
    before = config.read_bytes()
    result = CliRunner().invoke(
        app,
        [
            "errors",
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
    wire = json.loads(result.stdout)
    assert wire["config"]["languages"] == ["python"] and wire["config"]["strict"] is True
    cohorts = {file["path"]: file["cohort"] for file in wire["files"]}
    assert "excluded.py" not in cohorts and "generated.py" not in cohorts
    assert cohorts["fallback.py"] == "production" and cohorts["test_fallback.py"] == "test"
    assert config.read_bytes() == before and not marker.exists()
    assert str(config) not in result.stdout


def test_error_coverage_counts_handlers_and_preserves_failed_files(project) -> None:
    root, _ = project
    (root / "controls.py").write_text(CONTROLS, encoding="utf-8")
    (root / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    wire = inspect_errors(request(root)).model_dump(mode="json")
    summary = wire["summary"]
    assert summary["unit"] == "exception-handlers"
    assert summary["files_analyzed"] == 3 and summary["files_failed"] == 1
    assert summary["encountered"] == 3 and summary["assessed"] == 2
    assert summary["unresolved"] == 1 and summary["findings"] == 1
    assert len(summary["unresolved_reasons"]) == 1
    assert summary["unresolved_reasons"][0]["count"] == 1
    broken = next(item for item in wire["files"] if item["path"] == "broken.py")
    assert broken["state"] == "failed" and "handlers" not in broken
    assert broken["diagnostic"] in wire["diagnostics"]
    with pytest.raises(AnalysisFailure):
        inspect_errors(request(root, strict=True))
    runner = CliRunner()
    ordinary = runner.invoke(app, ["errors", "--root", str(root), "--json"])
    assert ordinary.exit_code == 0, ordinary.output
    assert json.loads(ordinary.stdout)["summary"] == summary
    strict = runner.invoke(app, ["errors", "--root", str(root), "--strict", "--json"])
    assert strict.exit_code == 3 and strict.stderr


@pytest.mark.parametrize(
    "source,assessed", [("pass\n", 0), (CONTROLS.split("def conditional", 1)[0], 1)]
)
def test_empty_handler_inventory_is_distinct_from_assessed_without_findings(
    project, source: str, assessed: int
) -> None:
    root, _ = project
    (root / "fallback.py").write_text(source, encoding="utf-8")
    summary = inspect_errors(request(root)).model_dump(mode="json")["summary"]
    assert summary["unit"] == "exception-handlers"
    assert summary["assessed"] == assessed and summary["encountered"] == assessed
    assert summary["findings"] == 0 and summary["unresolved"] == 0
    result = CliRunner().invoke(app, ["errors", "--root", str(root)])
    assert result.exit_code == 0, result.output
    assert ("nothing assessed" in result.stdout.lower()) is (assessed == 0)


@pytest.mark.parametrize("language", ["unknown", "ts"])
def test_error_cli_rejects_unsupported_languages(project, language: str) -> None:
    root, _ = project
    result = CliRunner().invoke(app, ["errors", "--root", str(root), "--lang", language, "--json"])
    assert result.exit_code == 2 and result.stderr
