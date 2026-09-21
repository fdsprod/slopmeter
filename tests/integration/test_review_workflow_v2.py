"""Saved-report judgments preserve history and bind only relevant review policy."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.application.models import inspect_models
from slop_measure.application.review_workflow import (
    load_review_ledger,
    load_review_report,
    resolve_reviews,
    review_targets,
    write_review,
)
from slop_measure.application.reviews import write_clone_review
from slop_measure.application.variants import inspect_variants
from slop_measure.cli import app
from slop_measure.domain.reviews import ReviewDisposition
from slop_measure.errors import InputError


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    project = tmp_path / "project"
    project.mkdir()
    for name in ("a.py", "b.py"):
        (project / name).write_text(
            "def work(source):\n    value = source + 1\n    return value\n# note\n",
            encoding="utf-8",
        )
    return project


def request(root: Path, **options: object) -> SnapshotRequest:
    return SnapshotRequest(
        target=DirectorySourceReference(root=root),
        config=AnalysisConfig.model_validate(
            {"clone_min_sloc": 2, "calibration_profile": "__raw__", **options}
        ),
    )


def target(report, kind: str):
    return next(
        item
        for item in review_targets(report)
        if item.state == "reviewable" and item.anchor.subject.kind.value == kind
    )


def record(path: Path, report, kind: str = "clone", **options):
    return write_review(
        path,
        report,
        target(report, kind).id,
        actor="reviewer",
        disposition=ReviewDisposition.DEFER,
        reason="Separate change contracts.",
        **options,
    )


def test_snapshot_catalog_exposes_all_evidence_without_threshold_gating(root: Path) -> None:
    report = scan(request(root))
    before = report.model_dump_json()
    catalog = review_targets(report)
    assert {item.anchor.subject.kind.value for item in catalog if item.state == "reviewable"} == {
        "clone",
        "pattern",
        "complexity",
    }
    assert len({item.id for item in catalog}) == len(catalog)
    for item in catalog:
        assert item.state == "reviewable"
        assert item.anchor.subject.locations
        assert item.id.startswith(item.anchor.subject.kind.value + ":")
        assert item.anchor.boundary.state == (
            "relevant" if item.anchor.subject.kind.value == "clone" else "not-applicable"
        )
    assert report.model_dump_json() == before


@pytest.mark.parametrize("kind", ["model", "variant", "derived"])
def test_experimental_catalogs_load_from_saved_reports(root: Path, kind: str) -> None:
    if kind == "model":
        source = (
            "from dataclasses import dataclass\n@dataclass\nclass Item:\n"
            "    enabled: bool\n    value: str | None\n"
        )
        inspector = inspect_models
    elif kind == "variant":
        source = (
            "from typing import Literal\ndef render(value: Literal['yes', 'no']):\n"
            "    match value:\n        case 'yes' | 'no':\n            return 1\n"
        )
        inspector = inspect_variants
    else:
        from slop_measure.application.derived import inspect_derived  # noqa: PLC0415

        source = (
            "def work():\n    items = [1]\n    count = len(items)\n"
            "    items.append(2)\n    return count\n"
        )
        inspector = inspect_derived
    (root / "experiment.py").write_text(source, encoding="utf-8")
    report = inspector(request(root))
    chosen = target(report, kind)
    assert chosen.anchor.subject.locations[0].path.root == "experiment.py"
    saved = root.parent / f"{kind}.json"
    saved.write_text(report.model_dump_json(), encoding="utf-8")
    assert load_review_report(saved) == report
    ledger = record(root.parent / f"{kind}-review.json", report, kind)
    assert resolve_reviews(report, ledger).results[0].state == "current"


def test_events_append_with_explicit_actor_utc_time_and_latest_resolution(root: Path) -> None:
    report = scan(request(root))
    before = report.model_dump_json()
    store = root.parent / "reviews.json"
    first = record(store, report, next_step="Recheck later.")
    second = write_review(
        store,
        report,
        target(report, "clone").id,
        actor="second reviewer",
        disposition=ReviewDisposition.NO_CHANGE,
        reason="Confirmed separate contracts.",
    )
    assert first.schema_version == second.schema_version == "2"
    assert [event.sequence for event in second.events] == [1, 2]
    assert second.events[0] == first.events[0]
    assert second.events[0].decision.next_step == "Recheck later."
    assert second.events[1].actor == "second reviewer"
    assert second.events[0].review_id == second.events[1].review_id
    assert all(event.recorded_at.utcoffset() == timedelta(0) for event in second.events)
    result = resolve_reviews(report, second)
    assert len(result.results) == 1 and result.results[0].event == second.events[-1]
    assert result.events == second.events and result.results[0].state == "current"
    assert load_review_ledger(store) == second and report.model_dump_json() == before


@pytest.mark.parametrize(
    "change,cause",
    [
        ("source", "source-changed"),
        ("boundary", "boundary-policy-changed"),
        ("analysis", "analysis-definition-changed"),
    ],
)
def test_relevant_changes_invalidate_without_changing_target_identity(
    root: Path, change: str, cause: str
) -> None:
    report = scan(request(root))
    ledger = record(root.parent / "reviews.json", report)
    options = {}
    if change == "source":
        path = root / "a.py"
        path.write_text(path.read_text().replace("# note", "# changed"), encoding="utf-8")
    elif change == "boundary":
        options = {"boundaries": [{"name": "separate", "prefix": "a.py"}]}
    else:
        options = {"clone_min_sloc": 1}
    changed = scan(request(root, **options))
    assert target(changed, "clone").id == target(report, "clone").id
    result = resolve_reviews(changed, ledger).results[0]
    assert result.state == "stale"
    assert cause in result.changes[0].causes


def test_unrelated_boundary_keeps_new_review_current_but_legacy_stale(root: Path) -> None:
    report = scan(request(root))
    legacy_path = root.parent / "legacy.json"
    legacy = write_clone_review(
        legacy_path,
        report,
        report.clone_groups[0].id,
        disposition=ReviewDisposition.DEFER,
        reason="Separate contracts.",
    )
    original = legacy_path.read_bytes()
    imported = load_review_ledger(legacy_path)
    assert imported.legacy_decisions == legacy.decisions
    assert legacy_path.read_bytes() == original
    ledger = record(legacy_path, report)
    assert ledger.legacy_decisions == legacy.decisions
    changed = scan(request(root, boundaries=[{"name": "unrelated", "prefix": "elsewhere"}]))
    resolution = resolve_reviews(changed, ledger)
    assert resolution.results[0].state == "current"
    assert resolution.legacy_results[0].state == "stale"


def test_cli_lists_and_shows_saved_report_without_rescan_or_store_write(root: Path) -> None:
    report = scan(request(root))
    saved, store = root.parent / "report.json", root.parent / "reviews.json"
    saved.write_text(report.model_dump_json(), encoding="utf-8")
    ledger = record(store, report)
    before = store.read_bytes()
    (root / "a.py").unlink()
    runner = CliRunner()
    listed = runner.invoke(app, ["review-report", "list", "--report", str(saved), "--json"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.stdout)["targets"]
    shown = runner.invoke(
        app, ["review-report", "show", "--report", str(saved), "--store", str(store), "--json"]
    )
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.stdout) == resolve_reviews(report, ledger).model_dump(mode="json")
    assert store.read_bytes() == before


def test_unknown_target_and_blank_actor_preserve_existing_store(root: Path) -> None:
    report = scan(request(root))
    store = root.parent / "reviews.json"
    record(store, report)
    before = store.read_bytes()
    for target_id, actor in (("missing", "reviewer"), (target(report, "clone").id, " ")):
        with pytest.raises((InputError, ValueError)):
            write_review(
                store,
                report,
                target_id,
                actor=actor,
                disposition=ReviewDisposition.DEFER,
                reason="Reason",
            )
        assert store.read_bytes() == before
