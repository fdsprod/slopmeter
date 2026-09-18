"""Hand-calculated end-to-end callable mass and terminal evidence."""

import json
import math
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.cli import app
from slop_measure.config import load_analysis_config
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
    monkeypatch.setattr(
        "slop_measure.cli.load_analysis_config",
        lambda root, **kwargs: load_analysis_config(root, **kwargs).model_copy(
            update={"calibration_profile": "__raw__"}
        ),
    )
    return tmp_path


def test_erosion_scan_matches_exact_callables_and_mass_totals(erosion_project: Path) -> None:
    request = SnapshotRequest(
        target=DirectorySourceReference(root=erosion_project),
        config=AnalysisConfig(calibration_profile="__raw__"),
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
    raw = next(
        item
        for item in production.model_dump(mode="json")["metrics"]
        if item["metric_id"] == "m4.erosion"
    )["raw"]
    assert raw == pytest.approx(
        {
            "numerator": math.sqrt(2),
            "denominator": 12 * math.sqrt(2),
            "value": 1 / 12,
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
            target=DirectorySourceReference(root=erosion_project),
            config=AnalysisConfig(calibration_profile="__raw__"),
        )
    )
    normalized = report.model_copy(
        update={"analysis": SnapshotAnalysis(current=DirectorySourceIdentity(root=Path("PROJECT")))}
    )
    assert render_snapshot(normalized, width=80, color=False, ascii=True) == (
        Path(__file__).parent / "scan_erosion.txt"
    ).read_text(encoding="utf-8")


def test_configured_threshold_changes_end_to_end_erosion(erosion_project: Path) -> None:
    reference = DirectorySourceReference(root=erosion_project)
    default = scan(
        SnapshotRequest(target=reference, config=AnalysisConfig(calibration_profile="__raw__"))
    )
    boundary = scan(
        SnapshotRequest(target=reference, config=AnalysisConfig(complexity_threshold=11))
    )
    default_production = next(
        item.current for item in default.cohorts if item.cohort.value == "production"
    )
    boundary_production = next(
        item.current for item in boundary.cohorts if item.cohort.value == "production"
    )
    default_raw = next(
        item
        for item in default_production.model_dump(mode="json")["metrics"]
        if item["metric_id"] == "m4.erosion"
    )["raw"]
    boundary_raw = next(
        item
        for item in boundary_production.model_dump(mode="json")["metrics"]
        if item["metric_id"] == "m4.erosion"
    )["raw"]

    assert default_raw["value"] == pytest.approx(1 / 12)
    assert boundary_raw["value"] == boundary_raw["numerator"] == 0
    assert boundary_raw["denominator"] == default_raw["denominator"]
    assert boundary.provenance.config.complexity_threshold == 11
    assert "callables: 2; eroded: 0; CC threshold: > 11" in render_snapshot(
        boundary, color=False, verbose=True
    )


def write_callable(root: Path, relative_path: str, complexity: int) -> None:
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    expression = " or ".join(f"values[{index}]" for index in range(complexity))
    target.write_text(f"def f(values):\n    return {expression}\n", encoding="utf-8")


def test_hotspots_obey_top_n_and_sort_by_mass_then_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    # Create tied paths in reverse order so discovery order cannot decide the tie.
    for name, complexity in (("b.py", 11), ("z.py", 12), ("a.py", 11)):
        write_callable(tmp_path, name, complexity)
    request = SnapshotRequest(
        target=DirectorySourceReference(root=tmp_path),
        config=AnalysisConfig(calibration_profile="__raw__", default_hotspot_count=2),
    )
    rendered = render_snapshot(scan(request), width=80, color=False, verbose=True)
    hotspots = [line for line in rendered.splitlines() if ": CC " in line]

    assert hotspots == [
        "    z.py:1-2 f: CC 12, SLOC 2, mass 16.9706, assertions 0, control-flow CC 12",
        "    a.py:1-2 f: CC 11, SLOC 2, mass 15.5563, assertions 0, control-flow CC 11",
    ]
    assert "callables: 3; eroded: 3; CC threshold: > 10" in rendered
    assert render_snapshot(scan(request), width=80, color=False, verbose=True) == rendered


def test_production_and_test_erosion_have_independent_mass_totals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    write_callable(tmp_path, "production.py", 11)
    write_callable(tmp_path, "tests/test_simple.py", 1)
    report = scan(
        SnapshotRequest(
            target=DirectorySourceReference(root=tmp_path),
            config=AnalysisConfig(calibration_profile="__raw__"),
        )
    )
    cohorts = {item.cohort.value: item.current.model_dump(mode="json") for item in report.cohorts}
    production = next(
        item for item in cohorts["production"]["metrics"] if item["metric_id"] == "m4.erosion"
    )["raw"]
    tests = next(item for item in cohorts["test"]["metrics"] if item["metric_id"] == "m4.erosion")[
        "raw"
    ]

    assert production["value"] == pytest.approx(1 / 11)
    assert production["numerator"] == pytest.approx(math.sqrt(2))
    assert production["denominator"] == pytest.approx(11 * math.sqrt(2))
    assert tests["value"] == tests["numerator"] == 0
    assert tests["denominator"] == pytest.approx(math.sqrt(2))
    assert [item["evidence"]["path"] for item in cohorts["production"]["files"]] == [
        "production.py"
    ]
    assert [item["evidence"]["path"] for item in cohorts["test"]["files"]] == [
        "tests/test_simple.py"
    ]
