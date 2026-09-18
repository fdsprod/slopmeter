"""Directory comparisons preserve snapshots and reconcile exact source-line change."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, ComparisonRequest, DirectorySourceReference, compare
from slop_measure.cli import app
from slop_measure.errors import AnalysisFailure
from slop_measure.languages.python.adapter import PythonAdapter
from slop_measure.reporting.json import serialize_report
from slop_measure.sources.filesystem import FilesystemSourceProvider


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


def test_comparison_reads_each_inventory_once_and_uses_retained_source_bytes(
    directories,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before, after = directories
    original = FilesystemSourceProvider.inventory
    calls = []

    def inventory(provider):
        result = original(provider)
        calls.append(result)
        # Mutate both roots only after both original inventories have been read.
        if len(calls) == 2:
            for root in directories:
                for path in root.glob("*.py"):
                    path.write_text("changed = 1\n", encoding="utf-8")
        return result

    monkeypatch.setattr(FilesystemSourceProvider, "inventory", inventory)
    report = compare(request(before, after))
    assert len(calls) == 2
    production = next(item for item in report.cohorts if item.cohort.value == "production")
    assert production.kind == "comparison"
    assert production.line_delta.state == "measured"
    assert (
        production.line_delta.added,
        production.line_delta.deleted,
        production.line_delta.net,
    ) == (3, 1, 2)


def test_cli_comparison_missing_input_and_strict_failure_exit_codes(directories) -> None:
    before, after = directories
    missing = CliRunner().invoke(app, ["compare", str(before / "missing"), str(after)])
    assert missing.exit_code == 2
    (after / "bad.py").write_text("x = (\n", encoding="utf-8")
    strict = CliRunner().invoke(app, ["compare", str(before), str(after), "--strict"])
    assert strict.exit_code == 3


def test_production_to_test_move_is_two_owned_changes_with_reconciled_totals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    before, after = tmp_path / "before", tmp_path / "after"
    before.mkdir()
    (after / "tests").mkdir(parents=True)
    source = "def f(flag):\n    return True if flag else False\n"
    (before / "a.py").write_text(source, encoding="utf-8")
    (after / "tests" / "a.py").write_text(source, encoding="utf-8")
    report = compare(request(before, after))
    for cohort in report.cohorts:
        assert cohort.kind == "comparison"
        assert cohort.line_delta.state == "measured"
        assert len(cohort.changes) == 1
        if cohort.cohort.value == "production":
            assert cohort.changes[0].pair.kind == "deleted"
            assert cohort.line_delta.net == -2
            assert not cohort.current.files
        else:
            assert cohort.changes[0].pair.kind == "added"
            assert cohort.line_delta.net == 2
            assert not cohort.baseline.files
    assert {(item.source.value, item.detail.path.root) for item in report.findings} == {
        ("baseline", "a.py"),
        ("current", "tests/a.py"),
    }


def test_empty_baseline_has_measured_m1_but_unavailable_growth_and_ratio_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    before, after = tmp_path / "before", tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (after / "a.py").write_text("x = 1\n", encoding="utf-8")
    report = compare(request(before, after))
    cohort = next(item for item in report.cohorts if item.cohort.value == "production")
    assert cohort.kind == "comparison"
    assert cohort.line_delta.state == "measured"
    assert cohort.line_delta.net == 1
    assert cohort.line_delta.growth.state == "unavailable"
    assert cohort.line_delta.growth.reason == "no-baseline-sloc"
    assert all(item.state == "unavailable" for item in cohort.changes[0].deltas)
    assert all(item.state == "unavailable" for item in cohort.deltas)


def test_clone_failure_does_not_invalidate_comparison_sloc(
    directories,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("fixture clone failure")

    monkeypatch.setattr("slop_measure.languages.python.adapter.extract_clone_candidates", fail)
    report = compare(request(*directories))
    cohort = next(item for item in report.cohorts if item.cohort.value == "production")
    assert cohort.kind == "comparison"
    assert cohort.line_delta.state == "measured"
    assert cohort.line_delta.net == 2
    deltas = {item.metric_id: item for item in cohort.deltas}
    assert deltas["m3.clone-verbosity"].state == "unavailable"
    assert deltas["verbosity.combined"].state == "unavailable"
    assert deltas["m2.pattern-verbosity"].state == "measured"


def test_whole_adapter_failure_preserves_successful_side_without_provenance_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    before, after = tmp_path / "before", tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "a.py").write_text("# fail adapter\nx = 1\n", encoding="utf-8")
    (after / "a.py").write_text("x = 2\n", encoding="utf-8")
    original = PythonAdapter.analyze

    def analyze(adapter, documents, config):
        if any(b"fail adapter" in document.content for document in documents):
            raise RuntimeError("fixture whole-adapter failure")
        return original(adapter, documents, config)

    monkeypatch.setattr(PythonAdapter, "analyze", analyze)
    report = compare(request(before, after))
    cohort = next(item for item in report.cohorts if item.cohort.value == "production")
    assert cohort.kind == "comparison"
    assert cohort.baseline.files[0].evidence.parse_state.value == "failed"
    assert cohort.current.files[0].evidence.parse_state.value == "parsed"
    assert cohort.current.files[0].evidence.sloc == 1
    assert cohort.line_delta.state == "unavailable"
    assert all(item.state == "unavailable" for item in cohort.deltas)
    assert any(
        item.source.value == "baseline" and item.detail.code == "analyzer.failed"
        for item in report.diagnostics
    )
    with pytest.raises(AnalysisFailure):
        compare(request(before, after, strict=True))
