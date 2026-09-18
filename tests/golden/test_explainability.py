"""Evidence commands filter owned facts without truncating machine-readable results."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, ComparisonRequest, DirectorySourceReference, compare
from slop_measure.cli import app
from slop_measure.domain.reports import SourceSide
from slop_measure.reporting.terminal import render_explanation


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


def test_renamed_baseline_symbol_explanation_shows_both_paths_and_raw_callable_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    before, after = tmp_path / "before", tmp_path / "after"
    before.mkdir()
    after.mkdir()
    source = "def work(value):\n    first = value + 1\n    return first\n"
    (before / "old.py").write_text(source, encoding="utf-8")
    (after / "new.py").write_text(source, encoding="utf-8")
    result = invoke(
        "explain",
        "old.py",
        "--root",
        str(after),
        "--baseline-root",
        str(before),
        "--source",
        "baseline",
        "--symbol",
        "work",
        "--ascii",
        "--no-color",
    )
    assert result.exit_code == 0, result.output
    assert "old.py" in result.output and "new.py" in result.output
    assert "renamed" in result.output.lower()
    assert "CC 1" in result.output and "SLOC 3" in result.output
    assert "mass" in result.output
    assert "symbol score" not in result.output.lower()


def test_baseline_explanation_does_not_leak_same_path_current_diagnostics_or_clones(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    before, after = tmp_path / "before", tmp_path / "after"
    before.mkdir()
    after.mkdir()
    for root in (before, after):
        (root / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
        (root / "b.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
        (root / "bad.py").write_text("x = (\n", encoding="utf-8")
    report = compare(
        ComparisonRequest(
            baseline=DirectorySourceReference(root=before),
            current=DirectorySourceReference(root=after),
            config=AnalysisConfig(calibration_profile="__raw__", clone_min_sloc=2),
        )
    )
    diagnostics = tuple(
        item.model_copy(
            update={
                "detail": item.detail.model_copy(
                    update={
                        "message": "BASELINE-ONLY-ERROR"
                        if item.source is SourceSide.BASELINE
                        else "CURRENT-ONLY-ERROR"
                    }
                )
            }
        )
        for item in report.diagnostics
    )
    report = report.model_copy(update={"diagnostics": diagnostics})
    baseline = render_explanation(
        report, "bad.py", source=SourceSide.BASELINE, ascii=True, color=False
    )
    assert "BASELINE-ONLY-ERROR" in baseline
    assert "CURRENT-ONLY-ERROR" not in baseline
    clones = render_explanation(report, "a.py", source=SourceSide.BASELINE, ascii=True, color=False)
    for group in report.clone_groups:
        if group.source is SourceSide.BASELINE:
            assert group.id in clones
        else:
            assert group.id not in clones
    assert "a.py:1-2" in clones and "b.py:1-2" in clones


def test_direct_evidence_renderers_fit_narrow_ascii_and_keep_selection_immutable(
    project: Path,
) -> None:
    from slop_measure.api import SnapshotRequest, scan  # noqa: PLC0415
    from slop_measure.domain.rules import RuleCatalog  # noqa: PLC0415
    from slop_measure.reporting.evidence import render_findings, render_rules  # noqa: PLC0415
    from slop_measure.reporting.selections import FindingSelection  # noqa: PLC0415

    report = scan(
        SnapshotRequest(
            target=DirectorySourceReference(root=project),
            config=AnalysisConfig(calibration_profile="__raw__"),
        )
    )
    selection = FindingSelection.model_validate(
        {
            "patterns": report.findings,
            "clone_groups": report.clone_groups,
            "functions": [
                {
                    "source": "current",
                    "language": cohort.language,
                    "cohort": cohort.cohort,
                    "function": function,
                }
                for cohort in report.cohorts
                for file in cohort.current.files
                for function in file.functions
                if function.cyclomatic_complexity > 10
            ],
        }
    )
    original = selection.model_dump_json()
    output = render_findings(report, selection, width=38, color=False, ascii=True, top=10)
    assert output.isascii() and "\x1b[" not in output
    assert all(len(line) <= 38 for line in output.splitlines())
    assert "high" in output and "CC 11" in output
    assert "py.boolean-conditional" in output
    limited = render_findings(report, selection, width=38, color=False, ascii=True, top=1)
    assert "omitted" in limited
    assert selection.model_dump_json() == original
    catalog = RuleCatalog.model_validate(
        {
            "language": "python",
            "version": "py-patterns-1",
            "rules": [
                {
                    "metadata": {
                        "rule_id": "py.boolean-conditional",
                        "category": "redundancy",
                        "severity": "warning",
                        "message": "Review a redundant boolean conditional.",
                    },
                    "enabled": False,
                }
            ],
        }
    )
    rules = render_rules(catalog, width=38, color=False, ascii=True)
    assert rules.isascii() and "\x1b[" not in rules
    assert all(len(line) <= 38 for line in rules.splitlines())
    assert "py.boolean-conditional" in rules and "disabled" in rules.lower()
    assert "warning" in rules.lower() and "redundancy" in rules.lower()
