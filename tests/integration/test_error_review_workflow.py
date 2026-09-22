"""Saved exception evidence supports attributed reviews with source and family scope."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.application.derived import inspect_derived
from slop_measure.application.error_review import inspect_errors
from slop_measure.application.models import inspect_models
from slop_measure.application.review_workflow import (
    load_review_ledger,
    load_review_report,
    resolve_reviews,
    review_targets,
    write_review,
)
from slop_measure.application.variants import inspect_variants
from slop_measure.cli import app
from slop_measure.domain.reviews import ReviewDisposition

SOURCE = """def fetch(client):
    try:
        result = client.read()
    except OSError:
        return []
    return result

def reraises(client):
    try:
        result = client.read()
    except OSError:
        raise
    return result

def indirect(client, fallback):
    try:
        result = client.read()
    except OSError:
        return fallback
    return result

def stale():
    items = [1]
    count = len(items)
    items.append(2)
    return count
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    root = tmp_path / "project"
    root.mkdir()
    (root / "fallback.py").write_text(SOURCE, encoding="utf-8")
    return root


def request(root: Path) -> SnapshotRequest:
    return SnapshotRequest(target=DirectorySourceReference(root=root), config=AnalysisConfig())


def record(store: Path, report):
    return write_review(
        store,
        report,
        review_targets(report)[0].id,
        actor="Ada",
        disposition=ReviewDisposition.DEFER,
        reason="Check whether callers distinguish unavailable data from an empty result.",
    )


def save(project: Path, report) -> Path:
    saved = project.parent / "report.json"
    saved.write_text(report.model_dump_json(), encoding="utf-8")
    return saved


def test_error_targets_cover_only_candidates_with_handler_symbol_and_owned_locations(project):
    report = inspect_errors(request(project))
    targets = review_targets(report)
    assert len(targets) == 1
    target = targets[0]
    assert target.state == "reviewable"
    subject = target.anchor.subject
    assert subject.kind.value == "error" and subject.symbol == "fetch"
    assert target.anchor.boundary.state == "not-applicable"
    file = report.files[0]
    assert file.state == "analyzed"
    handler = file.handlers[0]
    assert handler.state == "analyzed"
    finding = handler.findings[0]
    expected_spans = (
        finding.protected,
        finding.fallback.span,
        *(item.span for item in finding.normal_returns),
    )
    assert {(item.span.start_line, item.span.end_line) for item in subject.locations} == {
        (span.start_line, span.end_line) for span in expected_spans
    }
    assert {item.path.root for item in subject.locations} == {"fallback.py"}
    assert target.anchor.source_hashes[0].sha256 == file.source_sha256
    assert review_targets(load_review_report(save(project, report))) == targets


def test_saved_error_review_cli_list_set_show_uses_snapshot_and_preserves_source(project):
    report = inspect_errors(request(project))
    saved, store = save(project, report), project.parent / "reviews.json"
    source = project / "fallback.py"
    original = source.read_bytes()
    runner = CliRunner()
    listed = runner.invoke(app, ["review-report", "list", "--report", str(saved), "--json"])
    assert listed.exit_code == 0, listed.output
    targets = json.loads(listed.stdout)["targets"]
    assert targets == [target.model_dump(mode="json") for target in review_targets(report)]
    result = runner.invoke(
        app,
        [
            "review-report",
            "set",
            targets[0]["id"],
            "--report",
            str(saved),
            "--store",
            str(store),
            "--actor",
            "Ada",
            "--disposition",
            "defer",
            "--reason",
            "Check caller contract.",
            "--next-step",
            "Inspect consumers.",
        ],
    )
    assert result.exit_code == 0, result.output
    ledger = load_review_ledger(store)
    event = ledger.events[0]
    assert event.actor == "Ada" and event.decision.reason == "Check caller contract."
    assert event.decision.next_step == "Inspect consumers."
    assert source.read_bytes() == original
    saved_before, store_before = saved.read_bytes(), store.read_bytes()
    source.unlink()
    shown = runner.invoke(
        app, ["review-report", "show", "--report", str(saved), "--store", str(store), "--json"]
    )
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.stdout) == resolve_reviews(report, ledger).model_dump(mode="json")
    assert json.loads(shown.stdout)["results"][0]["state"] == "current"
    plain = runner.invoke(
        app, ["review-report", "show", "--report", str(saved), "--store", str(store)]
    )
    assert plain.exit_code == 0, plain.output
    for text in ("Ada", "fallback.py", "Check caller contract.", "Inspect consumers."):
        assert text in plain.stdout
    assert saved.read_bytes() == saved_before and store.read_bytes() == store_before


def test_error_review_becomes_stale_only_when_new_source_evidence_is_loaded(project):
    report = inspect_errors(request(project))
    saved, store = save(project, report), project.parent / "reviews.json"
    ledger = record(store, report)
    before = store.read_bytes()
    path = project / "fallback.py"
    path.write_text(SOURCE + "# changed source bytes\n", encoding="utf-8")
    changed = inspect_errors(request(project))
    result = resolve_reviews(changed, ledger).results[0]
    assert result.state == "stale"
    assert "source-changed" in result.changes[0].causes
    assert resolve_reviews(load_review_report(saved), ledger).results[0].state == "current"
    assert store.read_bytes() == before
    path.write_text("pass\n", encoding="utf-8")
    missing = resolve_reviews(inspect_errors(request(project)), ledger).results[0]
    assert missing.state == "missing" and missing.reason == "evidence-absent-or-unavailable"


@pytest.mark.parametrize("inspector", [scan, inspect_models, inspect_variants, inspect_derived])
def test_error_review_is_outside_other_report_families(project, inspector):
    report = inspect_errors(request(project))
    ledger = record(project.parent / "reviews.json", report)
    result = resolve_reviews(inspector(request(project)), ledger).results[0]
    assert result.state == "not-in-selected-report"
    assert result.reason == "review-family-not-in-selected-report"
    assert result.event == ledger.events[0]


def test_existing_review_family_is_outside_error_report(project):
    ledger = record(project.parent / "reviews.json", inspect_derived(request(project)))
    result = resolve_reviews(inspect_errors(request(project)), ledger).results[0]
    assert result.state == "not-in-selected-report"
    assert result.reason == "review-family-not-in-selected-report"


def test_error_filters_select_kind_and_cohort_and_reject_hotspots(project):
    (project / "test_fallback.py").write_text(SOURCE, encoding="utf-8")
    report = inspect_errors(request(project))
    saved = save(project, report)
    before = saved.read_bytes()
    runner = CliRunner()
    args = ["review-report", "list", "--report", str(saved)]
    filtered = runner.invoke(app, [*args, "--kind", "error", "--cohort", "test", "--json"])
    assert filtered.exit_code == 0, filtered.output
    targets = json.loads(filtered.stdout)["targets"]
    assert targets == [
        item.model_dump(mode="json")
        for item in review_targets(report)
        if item.state == "reviewable" and item.anchor.subject.cohort.value == "test"
    ]
    assert len(targets) == 1
    other = runner.invoke(app, [*args, "--kind", "derived", "--json"])
    assert other.exit_code == 0 and json.loads(other.stdout)["targets"] == []
    rejected = runner.invoke(app, [*args, "--hotspots-only", "--json"])
    assert rejected.exit_code == 2 and rejected.stdout == ""
    assert "hotspot" in rejected.output.lower() and "report" in rejected.output.lower()
    assert saved.read_bytes() == before
