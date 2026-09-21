"""Callable context and clone evidence remain visible without changing report facts."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.domain.reports import AnalysisReport
from slop_measure.reporting.queries import query_findings
from slop_measure.reporting.terminal import render_explanation, render_snapshot, render_tree


def clone_driven_report() -> AnalysisReport:
    fixture = Path(__file__).parents[2] / "golden" / "scoring_input.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    current = payload["cohorts"][0]["current"]
    for scope in (current, *current["files"]):
        template = scope["metrics"][0]
        scope["metrics"] = []
        for metric_id, value in (
            ("m2.pattern-verbosity", 0),
            ("m3.clone-verbosity", 0.5),
            ("verbosity.combined", 0.5),
            ("m4.erosion", 0),
        ):
            metric = deepcopy(template)
            metric["metric_id"] = metric_id
            metric["raw"].update(value=value, numerator=value * metric["raw"]["denominator"])
            scope["metrics"].append(metric)
        scope["score"] = {
            "state": "measured",
            "points": 50,
            "band": "moderate",
            "profile_id": "clone-reference",
            "model_id": "snapshot",
            "contributions": [
                {
                    "metric_id": "verbosity.combined",
                    "raw_value": 0.5,
                    "percentile": 50,
                    "weight": 1,
                    "points": 50,
                }
            ],
        }
    return AnalysisReport.model_validate(payload)


@pytest.mark.parametrize("width", [38, 140])
@pytest.mark.parametrize("view", ["files", "tree"])
def test_clone_driven_score_keeps_clone_ratio_visible_in_compact_views(
    width: int, view: str
) -> None:
    report = clone_driven_report()
    before = report.model_dump_json()
    if view == "files":
        output = render_snapshot(report, width=width, ascii=True, color=False, top=10)
        section = output.split("Files (", 1)[1]
    else:
        section = render_tree(report, width=width, ascii=True, color=False, top=10)
    section = section.split("How to read this report", 1)[0]
    assert "Clones" in section
    assert "50.0%" in section
    assert "50.0/100" in section
    assert "0.0%" in section
    assert "a.py" in section and "b.py" in section
    assert all(len(line) <= width for line in section.splitlines())
    assert report.model_dump_json() == before


@pytest.fixture
def callable_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AnalysisReport:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    (tmp_path / "tests").mkdir()
    assertion_source = "def check(value):\n" + "    assert value\n" * 11 + "    return value\n"
    for name in ("checks.py", "tests/test_checks.py"):
        (tmp_path / name).write_text(assertion_source, encoding="utf-8")
    branch_source = "def branches(value):\n" + "    if value:\n        value -= 1\n" * 11
    branch_source += "    return value\n"
    (tmp_path / "branches.py").write_text(branch_source, encoding="utf-8")
    (tmp_path / "simple.py").write_text("def simple(value):\n    return value\n", encoding="utf-8")
    (tmp_path / "pattern.py").write_text(
        "def pattern(value):\n    return True if value else False\n", encoding="utf-8"
    )
    return scan(
        SnapshotRequest(
            target=DirectorySourceReference(root=tmp_path),
            config=AnalysisConfig(calibration_profile="__raw__"),
        )
    )


@pytest.mark.parametrize("symbol", [None, "pattern"])
def test_explanation_names_pattern_family_in_findings_header(
    callable_report: AnalysisReport, symbol: str | None
) -> None:
    output = render_explanation(
        callable_report, "pattern.py", symbol=symbol, width=160, ascii=True, color=False
    )
    assert "Pattern findings (1)" in output


@pytest.mark.parametrize(
    "path,effective,basis",
    [
        ("checks.py", 12, "full-cc"),
        ("tests/test_checks.py", 1, "assertion-excluded-cc"),
    ],
)
def test_explanation_distinguishes_full_mass_from_selected_m4_basis(
    callable_report: AnalysisReport, path: str, effective: int, basis: str
) -> None:
    before = callable_report.model_dump_json()
    output = render_explanation(
        callable_report, path, symbol="check", width=240, ascii=True, color=False
    )
    section = output.split("How to read this report", 1)[0]
    assert "full-CC mass" in section
    assert f"M4 basis: {basis}" in section
    assert f"effective CC {effective}" in section
    expected_mass = "43.2666" if effective == 12 else "3.60555"
    expected_excess = "7.2111" if effective == 12 else "0"
    assert f"effective mass {expected_mass}" in section
    assert f"excess mass {expected_excess}" in section
    assert "threshold" in section.lower() and "10" in section
    assert callable_report.model_dump_json() == before


@pytest.mark.parametrize("version", ["1", "2"])
def test_historical_erosion_explanation_uses_full_cc_even_with_assertion_evidence(
    callable_report: AnalysisReport, version: str
) -> None:
    payload = callable_report.model_dump(mode="json")
    for metric in payload["provenance"]["metrics"]:
        if metric["metric_id"] == "m4.erosion":
            metric["version"] = version
    report = AnalysisReport.model_validate(payload)
    output = render_explanation(
        report, "tests/test_checks.py", symbol="check", width=240, ascii=True, color=False
    )
    section = output.split("How to read this report", 1)[0]
    assert "M4 basis: full-cc" in section and "effective CC 12" in section
    if version == "1":
        assert "above-threshold mass" in section or "numerator" in section
        assert "excess mass" not in section
    else:
        assert "excess mass" in section


@pytest.mark.parametrize("version,test_selected", [("1", True), ("2", True), ("3", False)])
def test_erosion_query_uses_report_version_for_test_callable_basis(
    callable_report: AnalysisReport, version: str, test_selected: bool
) -> None:
    payload = callable_report.model_dump(mode="json")
    for metric in payload["provenance"]["metrics"]:
        if metric["metric_id"] == "m4.erosion":
            metric["version"] = version
    report = AnalysisReport.model_validate(payload)
    before = report.model_dump_json()
    selected = query_findings(report, metric="m4")
    paths = {item.function.path.root for item in selected.functions}
    assert ("tests/test_checks.py" in paths) is test_selected
    assert "checks.py" in paths and "branches.py" in paths
    assert "simple.py" not in paths
    assert report.model_dump_json() == before


def test_unknown_metric_version_does_not_guess_callable_basis(
    callable_report: AnalysisReport,
) -> None:
    payload = callable_report.model_dump(mode="json")
    for metric in payload["provenance"]["metrics"]:
        if metric["metric_id"] == "m4.erosion":
            metric["version"] = "future"
    output = render_explanation(
        AnalysisReport.model_validate(payload),
        "checks.py",
        symbol="check",
        width=240,
        ascii=True,
        color=False,
    )
    section = output.split("How to read this report", 1)[0]
    assert "M4 basis unavailable" in section
    assert "effective CC" not in section
    assert "full-CC mass" in section


@pytest.mark.parametrize(
    "path,symbol,expected",
    [
        ("checks.py", "check", True),
        ("tests/test_checks.py", "check", False),
        ("branches.py", "branches", False),
        ("simple.py", "simple", False),
    ],
)
def test_classification_review_hint_requires_assertion_only_threshold_crossing(
    callable_report: AnalysisReport, path: str, symbol: str, expected: bool
) -> None:
    before = callable_report.model_dump_json()
    output = render_explanation(
        callable_report, path, symbol=symbol, width=240, ascii=True, color=False
    )
    section = output.split("How to read this report", 1)[0].lower()
    assert ("classification review" in section) is expected
    if expected:
        assert "production" in section
        assert "effective cc 12" in section
    assert callable_report.model_dump_json() == before


def test_unknown_assertion_count_keeps_full_complexity_and_names_fallback(
    callable_report: AnalysisReport,
) -> None:
    payload = callable_report.model_dump(mode="json")
    for cohort in payload["cohorts"]:
        for file in cohort["current"]["files"]:
            for function in file["functions"]:
                function.pop("assertion_count", None)
                function.pop("control_flow_complexity", None)
    report = AnalysisReport.model_validate(payload)
    output = render_explanation(
        report, "tests/test_checks.py", symbol="check", width=240, ascii=True, color=False
    )
    section = output.split("How to read this report", 1)[0]
    assert "assertion count unavailable" in section.lower()
    assert "effective CC 12" in section and "effective mass 43.2666" in section
    assert "classification review" not in section.lower()
