"""Comparison display keeps size change separate from quality movement."""

import json
from pathlib import Path

import pytest
from test_directory_comparison import directories, request  # noqa: F401
from typer.testing import CliRunner

from slop_measure.api import compare
from slop_measure.cli import app
from slop_measure.domain.reports import AnalysisReport
from slop_measure.reporting.comparison import render_comparison


def test_comparison_terminal_labels_signed_line_totals_and_growth(directories) -> None:  # noqa: F811
    before, after = directories
    report = compare(request(before, after))
    output = render_comparison(report, ascii=True, color=False, width=100, top=10)
    assert "M1 LOC delta" in output
    assert "+3 added" in output
    assert "-1 deleted" in output
    assert "+2 net" in output
    assert "+50.0%" in output
    m1_line = next(line for line in output.splitlines() if "M1 LOC delta" in line)
    assert "worse" not in m1_line and "better" not in m1_line
    assert "old.py" in output and "new.py" in output
    assert "renamed" in output
    assert "\x1b[" not in output
    assert output.isascii()


def test_comparison_terminal_metric_delta_has_explicit_direction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    before, after = tmp_path / "before", tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "a.py").write_text("def f(flag):\n    return flag\n", encoding="utf-8")
    (after / "a.py").write_text(
        "def f(flag):\n    return True if flag else False\n", encoding="utf-8"
    )
    output = render_comparison(compare(request(before, after)), ascii=True, color=False, width=100)
    assert "Pattern verbosity" in output
    assert "worse" in output
    reverse = render_comparison(compare(request(after, before)), ascii=True, color=False, width=100)
    assert "better" in reverse


def test_cli_top_limits_display_but_preserves_complete_json(directories) -> None:  # noqa: F811
    before, after = directories
    for root in directories:
        (root / "slop.toml").write_text('calibration_profile = "__raw__"\n', encoding="utf-8")
    runner = CliRunner()
    small = runner.invoke(app, ["compare", str(before), str(after), "--top", "1", "--json"])
    large = runner.invoke(app, ["compare", str(before), str(after), "--top", "10", "--json"])
    assert small.exit_code == large.exit_code == 0
    first, second = json.loads(small.stdout), json.loads(large.stdout)
    # CLI top may appear in provenance but cannot remove evidence or changes.
    assert first["cohorts"] == second["cohorts"]
    assert len(first["cohorts"][0]["changes"]) == 5
    report = compare(request(before, after))
    text = render_comparison(report, ascii=True, color=False, width=100, top=1)
    assert "omitted" in text
    assert report.cohorts[0].kind == "comparison"
    assert len(report.cohorts[0].changes) == 5


@pytest.mark.parametrize("score_delta", [0, -10])
def test_combined_regression_displays_the_metric_that_ranked_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, score_delta: int
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    before, after = tmp_path / "before", tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "a.py").write_text("def f(flag):\n    return flag\n", encoding="utf-8")
    (after / "a.py").write_text(
        "def f(flag):\n    return True if flag else False\n", encoding="utf-8"
    )
    payload = compare(request(before, after)).model_dump(mode="json")
    cohort = payload["cohorts"][0]
    for side, points in (("baseline", 20), ("current", 20 + score_delta)):
        score = {
            "state": "measured",
            "points": points,
            "profile_id": "synthetic",
            "model_id": "snapshot",
            "band": "test",
            "contributions": [
                {
                    "metric_id": "verbosity.combined",
                    "raw_value": 0.5 if side == "current" else 0,
                    "percentile": points,
                    "weight": 1,
                    "points": points,
                }
            ],
        }
        cohort[side]["score"] = score
        cohort[side]["files"][0]["score"] = score
    for deltas in (cohort["deltas"], cohort["changes"][0]["deltas"]):
        for index, delta in enumerate(deltas):
            if delta["metric_id"] == "snapshot.score":
                deltas[index] = {
                    "state": "measured",
                    "metric_id": "snapshot.score",
                    "value": score_delta,
                    "unit": "points",
                }
    report = AnalysisReport.model_validate(payload)
    output = render_comparison(report, ascii=True, color=False, width=120, top=1)
    row = output.split("a.py | modified", 1)[1]
    assert "combined" in row.lower()
    assert "+50.0" in row
    assert "worse" in row
    assert "better" not in row
