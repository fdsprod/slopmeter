"""Directory comparisons preserve snapshots and reconcile exact source-line change."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, ComparisonRequest, DirectorySourceReference, compare
from slop_measure.cli import app
from slop_measure.errors import AnalysisFailure
from slop_measure.reporting.json import serialize_report


@pytest.fixture
def directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    before, after = tmp_path / "before", tmp_path / "after"
    before.mkdir()
    after.mkdir()
    for name, text in {
        "same.py": "x = 1\n",
        "old.py": "y = 2\n",
        "gone.py": "z = 3\n",
        "edit.py": '"doc"\nx = 1\n',
    }.items():
        (before / name).write_text(text, encoding="utf-8")
    for name, text in {
        "same.py": "x = 1\n",
        "new.py": "y = 2\n",
        "added.py": "q = 4\n",
        "edit.py": 'x = 0\n"doc"\nx = 1\n',
    }.items():
        (after / name).write_text(text, encoding="utf-8")
    return before, after


def request(before: Path, after: Path, *, strict: bool = False) -> ComparisonRequest:
    return ComparisonRequest(
        baseline=DirectorySourceReference(root=before),
        current=DirectorySourceReference(root=after),
        config=AnalysisConfig(calibration_profile="__raw__", strict=strict),
    )


def test_api_comparison_reconciles_rename_add_delete_and_membership_change(directories) -> None:
    before, after = directories
    report = compare(request(before, after))
    assert report.analysis.kind == "comparison"
    cohort = next(item for item in report.cohorts if item.cohort.value == "production")
    assert cohort.kind == "comparison"
    assert len(cohort.baseline.files) == len(cohort.current.files) == 4
    assert {change.pair.kind for change in cohort.changes} == {
        "added",
        "deleted",
        "modified",
        "renamed",
        "unchanged",
    }
    totals = cohort.line_delta
    assert totals.state == "measured"
    assert (
        totals.baseline_sloc,
        totals.current_sloc,
        totals.added,
        totals.deleted,
        totals.net,
    ) == (4, 6, 3, 1, 2)
    assert totals.growth.state == "measured" and totals.growth.value == 0.5
    changed = next(item for item in cohort.changes if item.pair.kind == "modified")
    assert changed.lines.state == "measured"
    assert changed.lines.added_lines == (1, 2)
    renamed = next(item for item in cohort.changes if item.pair.kind == "renamed")
    assert renamed.lines.state == "measured" and renamed.lines.net == 0
    assert all(metric.metric_id == "m1.loc-delta" for metric in cohort.metrics)
    assert serialize_report(report) == serialize_report(compare(request(before, after)))


def test_cli_compare_json_matches_public_api(directories) -> None:
    before, after = directories
    for root in directories:
        (root / "slop.toml").write_text('calibration_profile = "__raw__"\n', encoding="utf-8")
    result = CliRunner().invoke(app, ["compare", str(before), str(after), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == json.loads(
        serialize_report(compare(request(before, after)))
    )


def test_parse_failures_keep_owned_side_diagnostics_and_strict_mode_fails(directories) -> None:
    before, after = directories
    (before / "bad.py").write_text("x = (\n", encoding="utf-8")
    (after / "bad.py").write_text("x = (\n", encoding="utf-8")
    report = compare(request(before, after))
    assert len({item.id for item in report.diagnostics}) == len(report.diagnostics)
    assert {item.source.value for item in report.diagnostics} == {"baseline", "current"}
    cohort = next(item for item in report.cohorts if item.cohort.value == "production")
    assert cohort.kind == "comparison"
    assert cohort.line_delta.state == "unavailable"
    for side in (cohort.baseline, cohort.current):
        failed = next(item for item in side.files if item.evidence.path.root == "bad.py")
        for metric in failed.metrics:
            if metric.state == "unavailable" and metric.diagnostic_id is not None:
                assert metric.diagnostic_id in {item.id for item in report.diagnostics}
    with pytest.raises(AnalysisFailure):
        compare(request(before, after, strict=True))
