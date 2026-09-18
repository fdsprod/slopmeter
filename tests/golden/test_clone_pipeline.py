"""Hand-counted cross-file clones preserve cohort and failure boundaries."""

from pathlib import Path

import pytest

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.domain.source import ProjectPath
from slop_measure.errors import AnalysisFailure
from slop_measure.reporting.json import serialize_report
from slop_measure.reporting.terminal import render_explanation, render_snapshot

SOURCE = "def work(source):\n    value = source + 1\n    return value\n"


@pytest.fixture
def clone_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    (tmp_path / "a.py").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "b.py").write_text(
        "def other(payload):\n    result = payload + 1\n    return result\n", encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_one.py").write_text(SOURCE, encoding="utf-8")
    return tmp_path


def request(root: Path, *, strict: bool = False) -> SnapshotRequest:
    return SnapshotRequest(
        target=DirectorySourceReference(root=root),
        config=AnalysisConfig(clone_min_sloc=2, strict=strict),
    )


def metrics(result):
    return {item.metric_id: item.model_dump(mode="json") for item in result.metrics}


def test_cross_file_clone_union_and_test_cohort_separation(clone_project: Path) -> None:
    report = scan(request(clone_project))
    production, tests = (
        next(item.current for item in report.cohorts if item.cohort.value == name)
        for name in ("production", "test")
    )
    measured = metrics(production)
    assert measured["m3.clone-verbosity"]["raw"] == {
        "numerator": 4,
        "denominator": 6,
        "value": 4 / 6,
        "unit": "ratio",
    }
    # Return-binding findings overlap the two cloned assignment lines, not new lines.
    assert measured["m2.pattern-verbosity"]["raw"]["numerator"] == 2
    assert measured["verbosity.combined"]["raw"]["numerator"] == 4
    assert measured["m4.erosion"]["state"] == "measured"
    assert production.score.reason.value == "calibration-missing"
    assert metrics(tests)["m3.clone-verbosity"]["raw"]["value"] == 0
    assert len(report.clone_groups) == 1
    group = report.clone_groups[0]
    assert group.source.value == "current"
    assert group.detail.cohort.value == "production"
    assert tuple(member.path.root for member in group.detail.members) == ("a.py", "b.py")
    assert all(member.sloc_lines == (2, 3) for member in group.detail.members)
    for file in production.files:
        assert metrics(file)["m3.clone-verbosity"]["raw"]["value"] == 2 / 3
    assert report.provenance.analyzers[0].clone_normalization_version == "py-clones-1"
    assert serialize_report(report) == serialize_report(scan(request(clone_project)))


def test_clone_failure_invalidates_m3_and_combined_but_not_m2_or_m4(
    clone_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from slop_measure.languages.python.clones import extract_clone_candidates  # noqa: PLC0415

    def extract(unit, config):
        if unit.file.path == ProjectPath("a.py"):
            raise RuntimeError("fixture clone failure")
        return extract_clone_candidates(unit, config)

    monkeypatch.setattr("slop_measure.languages.python.adapter.extract_clone_candidates", extract)
    report = scan(request(clone_project))
    production = next(item.current for item in report.cohorts if item.cohort.value == "production")
    measured = metrics(production)
    for metric_id in ("m3.clone-verbosity", "verbosity.combined"):
        assert measured[metric_id]["state"] == "unavailable"
        assert measured[metric_id]["reason"] == "analyzer-failed"
        assert measured[metric_id]["diagnostic_id"] in {item.id for item in report.diagnostics}
    assert measured["m2.pattern-verbosity"]["state"] == "measured"
    assert measured["m4.erosion"]["state"] == "measured"
    assert report.clone_groups == ()
    assert any(item.detail.code == "python.clone-error" for item in report.diagnostics)
    assert metrics(production.files[1])["m3.clone-verbosity"]["state"] == "measured"
    with pytest.raises(AnalysisFailure):
        scan(request(clone_project, strict=True))


def test_clone_summary_and_explanation_expose_owned_group_members(clone_project: Path) -> None:
    report = scan(request(clone_project))
    summary = render_snapshot(report, ascii=True, color=False, width=100)
    assert "Clone verbosity  66.7%" in summary
    assert "Combined verbosity  66.7%" in summary
    assert "4 / 6 SLOC" in summary
    assert "Clone groups" in summary
    assert report.clone_groups[0].id in summary
    detail = render_explanation(report, "a.py", ascii=True, color=False, width=100)
    assert "Clone groups" in detail
    assert report.clone_groups[0].id in detail
    assert "a.py:2-3" in detail
    assert "b.py:2-3" in detail
    assert "tests/test_one.py" not in detail
    selected = render_explanation(report, "a.py", symbol="work", ascii=True, color=False, width=100)
    assert report.clone_groups[0].id in selected
    assert "b.py:2-3" in selected
