"""Hand-counted overlapping pattern findings through API, CLI, and terminal."""

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.cli import app
from slop_measure.domain.reports import SnapshotAnalysis
from slop_measure.domain.source import DirectorySourceIdentity
from slop_measure.reporting.json import serialize_report
from slop_measure.reporting.terminal import render_snapshot


@pytest.fixture
def pattern_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    shutil.copytree(
        Path(__file__).parents[1] / "fixtures" / "patterns", tmp_path, dirs_exist_ok=True
    )
    return tmp_path


def test_overlapping_pattern_fixture_counts_one_line_and_preserves_both_findings(
    pattern_project: Path,
) -> None:
    request = SnapshotRequest(
        target=DirectorySourceReference(root=pattern_project), config=AnalysisConfig()
    )
    report = scan(request)
    production = next(item.current for item in report.cohorts if item.cohort.value == "production")
    metric = production.model_dump(mode="json")["metrics"][1]
    assert metric["raw"] == {"numerator": 1, "denominator": 4, "value": 0.25, "unit": "ratio"}
    assert [
        (
            item.id,
            item.detail.path.root,
            item.detail.rule_id,
            item.detail.span.start_line,
            item.detail.span.end_line,
        )
        for item in report.findings
    ] == [
        ("finding-0001", "overlap.py", "py.boolean-conditional", 1, 1),
        ("finding-0002", "overlap.py", "py.literal-fstring", 1, 1),
    ]
    assert report.provenance.analyzers[0].rule_set_version == "py-patterns-1"
    serialized = serialize_report(report)
    assert serialize_report(scan(request)) == serialized
    cli = CliRunner().invoke(app, ["scan", str(pattern_project), "--json"])
    assert cli.exit_code == 0, cli.output
    assert json.loads(cli.stdout) == json.loads(serialized)


def test_pattern_terminal_matches_handwritten_golden(pattern_project: Path) -> None:
    report = scan(
        SnapshotRequest(
            target=DirectorySourceReference(root=pattern_project), config=AnalysisConfig()
        )
    )
    normalized = report.model_copy(
        update={"analysis": SnapshotAnalysis(current=DirectorySourceIdentity(root=Path("PROJECT")))}
    )
    assert render_snapshot(normalized, width=80, color=False, ascii=True) == (
        Path(__file__).parent / "scan_patterns.txt"
    ).read_text(encoding="utf-8")


def test_disabling_all_fixture_rules_produces_measured_zero(pattern_project: Path) -> None:
    config = AnalysisConfig(
        disabled_rules=frozenset({"py.boolean-conditional", "py.literal-fstring"})
    )
    report = scan(
        SnapshotRequest(target=DirectorySourceReference(root=pattern_project), config=config)
    )
    production = next(item.current for item in report.cohorts if item.cohort.value == "production")
    assert production.model_dump(mode="json")["metrics"][1]["raw"]["value"] == 0
    assert report.findings == ()
