"""Saved-report judgments preserve history and bind only relevant review policy."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
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
            "    def __post_init__(self):\n"
            "        if self.enabled and self.value is None:\n"
            "            raise ValueError('Value required')\n"
            "def first(item: Item):\n"
            "    if item.enabled and item.value is None:\n        return False\n"
            "    return True\n"
            "def second(item: Item):\n"
            "    if item.enabled and item.value is None:\n        return None\n"
            "    return item.value\n"
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
    change_record = result.changes[0]
    assert change_record.candidate == target(changed, "clone")
    assert change_record.target_id == change_record.candidate.id
    with pytest.raises(ValidationError):
        type(change_record).model_validate(
            {**change_record.model_dump(), "target_id": "clone:" + "0" * 64}
        )


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


def test_explicit_rereview_retains_history_when_evidence_changes(root: Path) -> None:
    report = scan(request(root))
    store = root.parent / "reviews.json"
    original = record(store, report)
    for path in root.glob("*.py"):
        path.write_text(path.read_text().replace("+ 1", "+ 2"), encoding="utf-8")
    changed = scan(request(root))
    assert target(changed, "clone").id != target(report, "clone").id
    stale = resolve_reviews(changed, original).results[0]
    assert stale.state == "stale" and "evidence-changed" in stale.changes[0].causes
    updated = record(store, changed, review_id=original.events[0].review_id)
    assert updated.events[0] == original.events[0]
    assert updated.events[1].review_id == original.events[0].review_id
    assert resolve_reviews(changed, updated).results[0].state == "current"
    before = store.read_bytes()
    with pytest.raises((InputError, ValueError)):
        record(store, changed, "complexity", review_id=original.events[0].review_id)
    assert store.read_bytes() == before


def test_absent_evidence_is_missing_not_fixed(root: Path) -> None:
    report = scan(request(root))
    ledger = record(root.parent / "reviews.json", report)
    (root / "b.py").unlink()
    result = resolve_reviews(scan(request(root)), ledger).results[0]
    assert result.state == "missing" and result.reason == "evidence-absent-or-unavailable"


def test_missing_source_hash_is_unavailable_and_cannot_be_recorded(root: Path) -> None:
    report = scan(request(root))
    store = root.parent / "reviews.json"
    ledger = record(store, report)
    payload = report.model_dump(mode="json")
    for cohort in payload["cohorts"]:
        for file in cohort["current"]["files"]:
            file.pop("source_sha256", None)
    legacy_report = type(report).model_validate(payload)
    unavailable = next(
        item for item in review_targets(legacy_report) if item.id == target(report, "clone").id
    )
    assert unavailable.state == "unavailable" and unavailable.reason == "source-hash-unavailable"
    resolution = resolve_reviews(legacy_report, ledger).results[0]
    assert resolution.state == "stale"
    assert "source-unavailable" in resolution.changes[0].causes
    assert resolution.changes[0].candidate == unavailable
    before = store.read_bytes()
    with pytest.raises((InputError, ValueError)):
        write_review(
            store,
            legacy_report,
            unavailable.id,
            actor="reviewer",
            disposition=ReviewDisposition.DEFER,
            reason="Review unavailable evidence.",
        )
    assert store.read_bytes() == before


def test_replace_failure_preserves_store_and_cleans_owned_temporary_files(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os  # noqa: PLC0415

    report = scan(request(root))
    store = root.parent / "reviews.json"
    record(store, report)
    before = store.read_bytes()
    names = {path.name for path in store.parent.iterdir()}

    def fail_replace(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises((InputError, OSError)):
        record(store, report)
    assert store.read_bytes() == before
    assert {path.name for path in store.parent.iterdir()} == names


@pytest.mark.parametrize(
    "contents", ['{"schema_version":"999"}', '{"schema_version":"2","events":"bad"}', "not JSON"]
)
def test_malformed_saved_inputs_are_input_errors(root: Path, contents: str) -> None:
    path = root.parent / "invalid.json"
    path.write_text(contents, encoding="utf-8")
    for load in (load_review_report, load_review_ledger):
        with pytest.raises(InputError):
            load(path)
    runner = CliRunner()
    assert runner.invoke(app, ["review-report", "list", "--report", str(path)]).exit_code == 2


@pytest.mark.parametrize(
    "change", ["sequence-gap", "sequence-bool", "blank-actor", "naive-time", "incompatible-history"]
)
def test_ledger_rejects_forged_history(root: Path, change: str) -> None:
    report = scan(request(root))
    ledger = record(root.parent / "reviews.json", report)
    wire = ledger.model_dump(mode="json")
    if change == "sequence-gap":
        wire["events"][0]["sequence"] = 2
    elif change == "sequence-bool":
        wire["events"][0]["sequence"] = True
    elif change == "blank-actor":
        wire["events"][0]["actor"] = " "
    elif change == "naive-time":
        wire["events"][0]["recorded_at"] = "2026-01-01T12:00:00"
    else:
        second = {**wire["events"][0], "sequence": 2}
        second["decision"] = {
            **second["decision"],
            "anchor": target(report, "complexity").anchor.model_dump(mode="json"),
        }
        wire["events"].append(second)
    with pytest.raises(ValidationError):
        type(ledger).model_validate(wire)


def test_target_id_cannot_be_forged_and_anchor_hashes_cover_exact_subject(root: Path) -> None:
    chosen = target(scan(request(root)), "clone")
    with pytest.raises(ValidationError):
        type(chosen).model_validate({**chosen.model_dump(), "id": "clone:" + "0" * 64})
    anchor = chosen.anchor.model_dump()
    anchor["source_hashes"] = anchor["source_hashes"][:1]
    with pytest.raises(ValidationError):
        type(chosen.anchor).model_validate(anchor)


def test_cli_set_records_explicit_actor_reason_and_followup(root: Path) -> None:
    report = scan(request(root))
    saved, store = root.parent / "report.json", root.parent / "reviews.json"
    saved.write_text(report.model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "review-report",
            "set",
            target(report, "clone").id,
            "--report",
            str(saved),
            "--store",
            str(store),
            "--actor",
            "Ada",
            "--disposition",
            "defer",
            "--reason",
            "Wait for interface change.",
            "--next-step",
            "Review next release.",
        ],
    )
    assert result.exit_code == 0, result.output
    event = load_review_ledger(store).events[0]
    assert event.actor == "Ada" and event.decision.reason == "Wait for interface change."
    assert event.decision.next_step == "Review next release."
    shown = CliRunner().invoke(
        app, ["review-report", "show", "--report", str(saved), "--store", str(store)]
    )
    assert shown.exit_code == 0
    for text in ("Ada", "Wait for interface change.", "Review next release.", "a.py", "b.py"):
        assert text in shown.stdout


def test_foreign_lock_is_not_removed_and_existing_store_is_preserved(root: Path) -> None:
    report = scan(request(root))
    store = root.parent / "reviews.json"
    record(store, report)
    before = store.read_bytes()
    lock = store.with_name(store.name + ".lock")
    lock.write_bytes(b"another writer")
    with pytest.raises((InputError, OSError)):
        record(store, report)
    assert store.read_bytes() == before and lock.read_bytes() == b"another writer"


def test_symlink_store_cannot_redirect_review_writes(root: Path) -> None:
    report = scan(request(root))
    destination = root.parent / "actual.json"
    record(destination, report)
    before = destination.read_bytes()
    link = root.parent / "linked.json"
    try:
        link.symlink_to(destination)
    except OSError:
        pytest.skip("Symlink privileges unavailable")
    with pytest.raises((InputError, OSError)):
        record(link, report)
    assert link.is_symlink() and destination.read_bytes() == before


def test_cli_invalid_write_keeps_store_and_stale_show_includes_exact_changes(root: Path) -> None:
    report = scan(request(root, boundaries=[{"name": "before-policy", "prefix": "a.py"}]))
    store, saved = root.parent / "reviews.json", root.parent / "report.json"
    ledger = record(store, report)
    before = store.read_bytes()
    path = root / "a.py"
    path.write_text(path.read_text().replace("# note", "# different bytes"), encoding="utf-8")
    changed = scan(request(root, boundaries=[{"name": "after-policy", "prefix": "a.py"}]))
    saved.write_text(changed.model_dump_json(), encoding="utf-8")
    runner = CliRunner()
    rejected = runner.invoke(
        app,
        [
            "review-report",
            "set",
            "unknown",
            "--report",
            str(saved),
            "--store",
            str(store),
            "--actor",
            "reviewer",
            "--disposition",
            "defer",
            "--reason",
            "Reason",
        ],
    )
    assert rejected.exit_code == 2 and store.read_bytes() == before
    shown = runner.invoke(
        app, ["review-report", "show", "--report", str(saved), "--store", str(store)]
    )
    assert shown.exit_code == 0, shown.output
    for text in (
        "source-changed",
        "boundary-policy-changed",
        "before-policy",
        "after-policy",
        "a.py",
    ):
        assert text in shown.stdout
    old_hash = next(
        item.sha256
        for item in ledger.events[0].decision.anchor.source_hashes
        if item.path.root == "a.py"
    )
    new_hash = next(
        item.sha256
        for item in target(changed, "clone").anchor.source_hashes
        if item.path.root == "a.py"
    )
    assert old_hash != new_hash
    assert old_hash in shown.stdout and new_hash in shown.stdout
    resolution = resolve_reviews(changed, ledger)
    restored = type(resolution).model_validate_json(resolution.model_dump_json())
    assert restored.results[0].changes[0].candidate == target(changed, "clone")
    assert store.read_bytes() == before
