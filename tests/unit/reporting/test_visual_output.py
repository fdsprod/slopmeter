"""Visual summaries and drill-downs preserve the immutable report's raw facts."""

import re
from pathlib import Path

import pytest

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.domain.reports import AnalysisReport, SnapshotAnalysis
from slop_measure.domain.source import DirectorySourceIdentity
from slop_measure.reporting.terminal import render_explanation, render_snapshot, render_tree


@pytest.fixture
def visual_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AnalysisReport:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    sources = {
        "src/a.py": "def first(flag):\n    return True if flag else False\n",
        "src/b.py": "def high(values):\n    return "
        + " or ".join(f"values[{index}]" for index in range(11))
        + "\n",
        "src/dup.py": 'def repeated():\n    return f"first"\n\n'
        'def repeated():\n    return f"second"\n',
        "tests/test_small.py": "VALUE = 1\n",
    }
    for relative, source in sources.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    report = scan(
        SnapshotRequest(
            target=DirectorySourceReference(root=tmp_path),
            config=AnalysisConfig(calibration_profile="__raw__", default_hotspot_count=1),
        )
    )
    return report.model_copy(
        update={"analysis": SnapshotAnalysis(current=DirectorySourceIdentity(root=Path("PROJECT")))}
    )


def test_summary_labels_raw_percentages_and_keeps_missing_scores_distinct(
    visual_report: AnalysisReport,
) -> None:
    output = render_snapshot(visual_report, width=100, color=False, ascii=True)
    assert "Score unavailable" in output
    assert "raw measurements available" in output
    assert "Pattern verbosity  37.5%" in output
    assert "[########------------]" in output
    assert "Clone verbosity  0.0%" in output
    assert "Combined verbosity  37.5%" in output
    assert "/100" not in output
    assert "scored" not in output.lower()
    assert "m1.loc-delta" not in output
    assert "LOC delta" not in output
    assert "mass" not in output.lower()
    assert "CC threshold" not in output
    assert "\x1b[" not in output


def test_summary_top_limits_files_without_changing_report_or_counts(
    visual_report: AnalysisReport,
) -> None:
    before = visual_report.model_dump_json()
    limited = render_snapshot(visual_report, ascii=True, color=False)
    expanded = render_snapshot(visual_report, ascii=True, color=False, top=3)
    assert "src/a.py" in limited
    assert "src/b.py" not in limited
    assert "src/dup.py" not in limited
    assert "2 files omitted" in limited
    assert expanded.index("src/a.py") < expanded.index("src/b.py") < expanded.index("src/dup.py")
    assert "files omitted" not in expanded
    assert "3 findings" in limited and "3 findings" in expanded
    assert visual_report.model_dump_json() == before


def test_verbose_summary_exposes_owned_mass_threshold_and_versions(
    visual_report: AnalysisReport,
) -> None:
    output = render_snapshot(visual_report, width=140, ascii=True, color=False, verbose=True)
    assert "mass:" in output
    assert "callables: 4; eroded: 1; CC threshold: > 10" in output
    assert "src/b.py:1-2 high: CC 11, SLOC 2, mass 15.5563" in output
    assert "python-clones-1" in output
    assert "py-patterns-1" in output
    assert "Provenance" in output


def test_summary_keeps_cohort_results_separate(visual_report: AnalysisReport) -> None:
    output = render_snapshot(visual_report, scope="all", width=120, ascii=True, top=10)
    production_start = output.index("Production | Python")
    tests_start = output.index("Tests | Python")
    production = output[production_start:tests_start]
    tests = output[tests_start:]
    assert "37.5%" in production
    assert "tests/test_small.py" not in production
    assert "Pattern verbosity  0.0% [--------------------]" in tests
    assert "tests/test_small.py" in tests
    assert "src/a.py" not in tests


@pytest.mark.parametrize("render", [render_snapshot, render_tree])
def test_ascii_narrow_views_fit_without_ansi_or_fake_values(
    visual_report: AnalysisReport, render
) -> None:
    output = render(visual_report, width=38, color=False, ascii=True, top=10)
    assert output.isascii()
    assert "\x1b[" not in output
    assert all(len(line) <= 38 for line in output.splitlines())
    assert "src/a.py" in output or "a.py" in output
    assert "/100" not in output


@pytest.mark.parametrize("width", [40, 140])
def test_explicit_width_is_preserved_for_colored_output_on_dumb_terminals(
    visual_report: AnalysisReport, monkeypatch: pytest.MonkeyPatch, width: int
) -> None:
    monkeypatch.setenv("TERM", "dumb")
    colored = render_snapshot(visual_report, color=True, width=width)
    plain = render_snapshot(visual_report, color=False, width=width)
    assert "\x1b[" in colored
    assert re.sub(r"\x1b\[[0-9;]*m", "", colored) == plain
    assert all(len(line) <= width for line in plain.splitlines())


def test_color_is_optional_and_raw_bars_use_no_severity_thresholds(
    visual_report: AnalysisReport,
) -> None:
    colored = render_snapshot(visual_report, color=True, width=140)
    plain = render_snapshot(visual_report, color=False, width=140)
    assert "\x1b[" in colored
    assert "\x1b[" not in plain
    assert re.sub(r"\x1b\[[0-9;]*m", "", colored) == plain
    raw_rows = "\n".join(
        line for line in colored.splitlines() if "Pattern verbosity" in line or "Erosion  " in line
    )
    assert not re.search(r"\x1b\[(?:[0-9]+;)*(?:31|32|91|92)m", raw_rows)


def test_tree_preserves_hierarchy_and_raw_file_values_without_directory_scores(
    visual_report: AnalysisReport,
) -> None:
    output = render_tree(visual_report, scope="all", width=140, ascii=True, top=10)
    assert "src/" in output and "tests/" in output
    assert "a.py" in output and "b.py" in output and "dup.py" in output
    assert "test_small.py" in output
    assert "50.0%" in output and "9.1%" in output and "0.0%" in output
    assert "|--" in output or "+--" in output or "`--" in output
    for row in output.splitlines():
        if "src/" in row and not any(name in row for name in ("a.py", "b.py", "dup.py")):
            assert "%" not in row and "/100" not in row
    assert "/100" not in output


def test_tree_top_limits_leaves_and_reports_omitted_count(visual_report: AnalysisReport) -> None:
    output = render_tree(visual_report, ascii=True, top=1)
    assert "a.py" in output
    assert "b.py" not in output and "dup.py" not in output
    assert "2 files omitted" in output


def test_explanation_includes_all_file_findings_and_callable_facts(
    visual_report: AnalysisReport,
) -> None:
    output = render_explanation(visual_report, "src/dup.py", width=140, ascii=True)
    assert "src/dup.py" in output
    assert "src/dup.py:1-2" in output and "src/dup.py:4-5" in output
    assert "src/dup.py:2-2" in output and "src/dup.py:5-5" in output
    assert output.count("py.literal-fstring") == 2
    assert "CC 1" in output and "SLOC 2" in output and "mass 1.41421" in output
    assert "src/a.py" not in output
    assert "/100" not in output


def test_symbol_explanation_uses_exact_declaration_and_overlapping_findings(
    visual_report: AnalysisReport,
) -> None:
    output = render_explanation(
        visual_report, "src/dup.py", symbol="repeated", line=4, width=140, ascii=True
    )
    assert "src/dup.py:4-5" in output and "src/dup.py:5-5" in output
    assert "src/dup.py:1-2" not in output and "src/dup.py:2-2" not in output
    assert output.count("py.literal-fstring") == 1
    assert "mass 1.41421" in output
    assert "/100" not in output


def test_explanation_rejects_unknown_or_ambiguous_selectors(visual_report: AnalysisReport) -> None:
    with pytest.raises(ValueError, match=r"(?i)ambiguous"):
        render_explanation(visual_report, "src/dup.py", symbol="repeated")
    with pytest.raises(ValueError):
        render_explanation(visual_report, "src/dup.py", symbol="repeated", line=5)
    with pytest.raises(ValueError):
        render_explanation(visual_report, "unknown.py")


def test_explanation_ascii_narrow_output_preserves_identity(visual_report: AnalysisReport) -> None:
    output = render_explanation(
        visual_report, "src/dup.py", symbol="repeated", line=4, width=38, ascii=True, color=False
    )
    assert output.isascii()
    assert "\x1b[" not in output
    assert all(len(line) <= 38 for line in output.splitlines())
    assert "src/dup.py:4-5" in output
