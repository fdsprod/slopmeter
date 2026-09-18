"""Hand-calculated end-to-end callable mass and terminal evidence."""

import json
import math
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
def erosion_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    shutil.copytree(
        Path(__file__).parents[1] / "fixtures" / "erosion", tmp_path, dirs_exist_ok=True
    )
    return tmp_path


def test_erosion_scan_matches_exact_callables_and_mass_totals(erosion_project: Path) -> None:
    request = SnapshotRequest(
        target=DirectorySourceReference(root=erosion_project), config=AnalysisConfig()
    )
    report = scan(request)
    production = next(item.current for item in report.cohorts if item.cohort.value == "production")
    files = production.model_dump(mode="json")["files"]
    assert [(item["evidence"]["path"], item["evidence"]["sloc"]) for item in files] == [
        ("constant.py", 1),
        ("high.py", 2),
        ("low.py", 2),
    ]
    functions = [function for file in files for function in file["functions"]]
    assert [
        (item["path"], item["qualified_name"], item["cyclomatic_complexity"], item["sloc_lines"])
        for item in functions
    ] == [("high.py", "high", 11, [1, 2]), ("low.py", "low", 1, [1, 2])]
    raw = production.model_dump(mode="json")["metrics"][-1]["raw"]
    assert raw == pytest.approx(
        {
            "numerator": 11 * math.sqrt(2),
            "denominator": 12 * math.sqrt(2),
            "value": 11 / 12,
            "unit": "ratio",
        }
    )
    serialized = serialize_report(report)
    assert serialize_report(scan(request)) == serialized
    result = CliRunner().invoke(app, ["scan", str(erosion_project), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == json.loads(serialized)


def test_erosion_terminal_matches_hand_written_evidence_golden(erosion_project: Path) -> None:
    report = scan(
        SnapshotRequest(
            target=DirectorySourceReference(root=erosion_project), config=AnalysisConfig()
        )
    )
    normalized = report.model_copy(
        update={"analysis": SnapshotAnalysis(current=DirectorySourceIdentity(root=Path("PROJECT")))}
    )
    assert render_snapshot(normalized, width=80, color=False) == (
        Path(__file__).parent / "scan_erosion.txt"
    ).read_text(encoding="utf-8")
