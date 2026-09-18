"""CLI review commands persist explicit decisions and annotate ordinary reports."""

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.cli import app


@pytest.fixture
def review_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, str]:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    root = tmp_path / "project"
    root.mkdir()
    source = "def work(source):\n    value = source + 1\n    return value\n"
    for name in ("a.py", "b.py"):
        (root / name).write_text(source, encoding="utf-8")
    (root / "slop.toml").write_text(
        'clone_min_sloc = 2\ncalibration_profile = "__raw__"\n', encoding="utf-8"
    )
    report = scan(
        SnapshotRequest(
            target=DirectorySourceReference(root=root),
            config=AnalysisConfig(clone_min_sloc=2, calibration_profile="__raw__"),
        )
    )
    assert len(report.clone_groups) == 1
    return root, tmp_path / "reviews.json", report.clone_groups[0].id


def set_review(root: Path, store: Path, group_id: str):
    result = CliRunner().invoke(
        app,
        [
            "review",
            "set",
            group_id,
            "--root",
            str(root),
            "--store",
            str(store),
            "--disposition",
            "no-change",
            "--reason",
            "Contracts evolve independently.",
            "--next-step",
            "Recheck after contract migration.",
            "--lang",
            "py",
        ],
    )
    assert result.exit_code == 0, result.output
    return result


def test_review_set_show_roundtrip_exposes_complete_report_and_exact_source_hashes(
    review_project,
) -> None:
    root, store, group_id = review_project
    set_review(root, store, group_id)
    stored = store.read_bytes()
    shown = CliRunner().invoke(
        app, ["review", "show", "--root", str(root), "--store", str(store), "--json"]
    )
    assert shown.exit_code == 0, shown.output
    report = json.loads(shown.stdout)
    assert {"cohorts", "clone_groups", "provenance", "interpretation"} <= report.keys()
    result = report["review_results"][0]
    assert result["state"] == "current" and result["group_id"] == group_id
    assert result["decision"]["disposition"] == "no-change"
    assert result["decision"]["reason"] == "Contracts evolve independently."
    for file in report["cohorts"][0]["current"]["files"]:
        assert (
            file["source_sha256"]
            == hashlib.sha256((root / file["evidence"]["path"]).read_bytes()).hexdigest()
        )
    assert store.read_bytes() == stored


@pytest.mark.parametrize("command", ["score", "scan", "tree", "findings"])
def test_reviews_annotate_each_report_without_changing_or_suppressing_evidence(
    review_project, command: str
) -> None:
    root, store, group_id = review_project
    set_review(root, store, group_id)
    before = store.read_bytes()
    runner = CliRunner()
    arguments = [command, "--root", str(root)] if command == "findings" else [command, str(root)]
    raw = runner.invoke(app, [*arguments, "--json"])
    reviewed = runner.invoke(app, [*arguments, "--reviews", str(store), "--json"])
    assert raw.exit_code == reviewed.exit_code == 0, (raw.output, reviewed.output)
    original, annotated = json.loads(raw.stdout), json.loads(reviewed.stdout)
    assert "review_results" not in original
    results = annotated.pop("review_results")
    assert len(results) == 1 and results[0]["state"] == "current"
    assert annotated == original
    assert store.read_bytes() == before


def test_review_rendering_names_current_stale_and_missing_without_suppressing_groups(
    review_project,
) -> None:
    root, store, group_id = review_project
    set_review(root, store, group_id)
    runner = CliRunner()
    args = ["review", "show", "--root", str(root), "--store", str(store), "--ascii", "--no-color"]
    for expected in ("current", "stale", "missing"):
        if expected == "stale":
            target = root / "a.py"
            target.write_text(
                target.read_text(encoding="utf-8") + "# comment only\n", encoding="utf-8"
            )
        elif expected == "missing":
            (root / "b.py").write_text("VALUE = 1\n", encoding="utf-8")
        rendered = runner.invoke(app, args)
        assert rendered.exit_code == 0, rendered.output
        section = rendered.stdout.split("How to read this report", 1)[0].lower()
        assert expected in section
        assert "no-change" in section and "contracts evolve independently." in section
        if expected != "missing":
            assert group_id in rendered.stdout
            assert "Clone verbosity" in rendered.stdout


@pytest.mark.parametrize("problem", ["missing", "malformed"])
def test_explicit_invalid_review_store_fails_without_rewriting_it(
    review_project, problem: str
) -> None:
    root, store, _ = review_project
    if problem == "malformed":
        store.write_bytes(b"not a review store")
    result = CliRunner().invoke(app, ["score", str(root), "--reviews", str(store), "--json"])
    assert result.exit_code == 2
    assert "Invalid analysis input" in result.stderr
    assert result.stdout == ""
    if problem == "malformed":
        assert store.read_bytes() == b"not a review store"
    else:
        assert not store.exists()
