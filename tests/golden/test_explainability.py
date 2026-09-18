"""Evidence commands filter owned facts without truncating machine-readable results."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure.cli import app


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    (tmp_path / "a.py").write_text(
        'def f(flag):\n    return True if flag else False\n\ndef g():\n    return f"text"\n',
        encoding="utf-8",
    )
    (tmp_path / "b.py").write_text(
        "def high(values):\n    return " + " or ".join(f"values[{n}]" for n in range(11)) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "slop.toml").write_text('calibration_profile = "__raw__"\n', encoding="utf-8")
    return tmp_path


def invoke(*arguments: str):
    return CliRunner().invoke(app, list(arguments))


def test_findings_json_preserves_all_matching_records_despite_top(project: Path) -> None:
    result = invoke("findings", "--root", str(project), "--json", "--top", "1")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "1.0"
    assert payload["analysis"]["kind"] == "snapshot"
    selected = payload["selection"]
    assert len(selected["patterns"]) == 2
    assert selected["clone_groups"] == []
    assert len(selected["functions"]) == 1
    function = selected["functions"][0]
    assert (function["source"], function["language"], function["cohort"]) == (
        "current",
        "python",
        "production",
    )
    assert function["function"]["qualified_name"] == "high"
    assert function["function"]["cyclomatic_complexity"] == 11
    report = invoke("scan", str(project), "--json")
    assert report.exit_code == 0
    original = json.loads(report.stdout)
    assert selected["patterns"] == original["findings"]
    assert payload["provenance"] == original["provenance"]


def test_findings_filters_compose_and_do_not_relabel_native_evidence(project: Path) -> None:
    result = invoke(
        "findings",
        "--root",
        str(project),
        "--path",
        "a.py",
        "--metric",
        "m2",
        "--rule",
        "py.boolean-conditional",
        "--severity",
        "warning",
        "--json",
    )
    assert result.exit_code == 0, result.output
    selected = json.loads(result.stdout)["selection"]
    assert len(selected["patterns"]) == 1
    assert selected["patterns"][0]["detail"]["rule_id"] == "py.boolean-conditional"
    assert selected["clone_groups"] == selected["functions"] == []
    empty = invoke(
        "findings", "--root", str(project), "--metric", "m4", "--severity", "warning", "--json"
    )
    assert empty.exit_code == 0
    assert all(not records for records in json.loads(empty.stdout)["selection"].values())


def test_baseline_deleted_file_explanation_owns_baseline_facts(
    project: Path, tmp_path: Path
) -> None:
    current = tmp_path / "current"
    current.mkdir()
    (current / "slop.toml").write_text('calibration_profile = "__raw__"\n', encoding="utf-8")
    result = invoke(
        "explain",
        "a.py",
        "--root",
        str(current),
        "--baseline-root",
        str(project),
        "--source",
        "baseline",
        "--ascii",
        "--no-color",
    )
    assert result.exit_code == 0, result.output
    assert "a.py" in result.output and "deleted" in result.output.lower()
    assert "py.boolean-conditional" in result.output
    assert "\x1b[" not in result.output
    complete = invoke(
        "explain",
        "a.py",
        "--root",
        str(current),
        "--baseline-root",
        str(project),
        "--source",
        "baseline",
        "--json",
    )
    assert complete.exit_code == 0
    payload = json.loads(complete.stdout)
    assert payload["analysis"]["kind"] == "comparison"
    assert len(payload["findings"]) == 2
    assert all(item["source"] == "baseline" for item in payload["findings"])


@pytest.mark.parametrize(
    "extra",
    [
        ["--source", "baseline"],
        ["--baseline-root", "before", "--baseline-rev", "HEAD"],
    ],
)
def test_invalid_source_selections_fail_directly(project: Path, extra: list[str]) -> None:
    result = invoke("findings", "--root", str(project), *extra)
    assert result.exit_code == 2
    assert "Traceback" not in result.output
    missing = invoke("explain", "missing.py", "--root", str(project))
    assert missing.exit_code == 2


def test_rules_catalog_requires_no_source_analysis_and_exposes_enabled_metadata(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_scan(*args, **kwargs):
        raise AssertionError("rules must not analyze source")

    monkeypatch.setattr("slop_measure.application.service.AnalysisService.scan", fail_scan)
    (project / "slop.toml").write_text(
        'disabled_rules = ["py.boolean-conditional"]\n', encoding="utf-8"
    )
    result = invoke("rules", "--root", str(project), "--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["language"] == "python"
    assert payload["version"] == "py-patterns-1"
    assert len(payload["rules"]) == 20
    selected = next(
        item for item in payload["rules"] if item["metadata"]["rule_id"] == "py.boolean-conditional"
    )
    assert selected["enabled"] is False
    assert selected["metadata"]["category"] == "redundancy"
    assert selected["metadata"]["severity"] == "warning"
    assert selected["metadata"]["message"]
    plain = invoke("rules", "--root", str(project), "--ascii", "--no-color")
    assert plain.exit_code == 0
    assert "py-patterns-1" in plain.output and "disabled" in plain.output.lower()
    assert "\x1b[" not in plain.output
