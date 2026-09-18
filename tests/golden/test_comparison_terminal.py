"""Comparison display keeps size change separate from quality movement."""

import json
from pathlib import Path

from test_directory_comparison import directories, request  # noqa: F401
from typer.testing import CliRunner

from slop_measure.api import compare
from slop_measure.cli import app
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


def test_comparison_terminal_metric_delta_has_explicit_direction(tmp_path: Path) -> None:
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
