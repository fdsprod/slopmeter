"""Saved review resolution distinguishes report scope and explicit replacement."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.application.derived import inspect_derived
from slop_measure.application.models import inspect_models
from slop_measure.application.review_workflow import (
    load_review_ledger,
    resolve_reviews,
    review_targets,
    write_review,
)
from slop_measure.application.reviews import load_review_store, write_clone_review
from slop_measure.application.variants import inspect_variants
from slop_measure.cli import app
from slop_measure.domain.reviews import ReviewDisposition
from slop_measure.errors import InputError

INSPECTORS = {
    "score": scan,
    "model": inspect_models,
    "variant": inspect_variants,
    "derived": inspect_derived,
}
KINDS = ("clone", "complexity", "pattern", "model", "variant", "derived")


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    root = tmp_path / "project"
    root.mkdir()
    for name in ("a.py", "b.py"):
        (root / name).write_text(
            "def work(source):\n    value = source + 1\n    return value\n# note\n",
            encoding="utf-8",
        )
    (root / "model.py").write_text(
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
        "    return item.value\n",
        encoding="utf-8",
    )
    (root / "variant.py").write_text(
        "from typing import Literal\nChoice = Literal['yes', 'no']\n"
        "def render(value: Choice):\n"
        "    match value:\n        case 'yes' | 'no':\n            return 1\n",
        encoding="utf-8",
    )
    (root / "derived.py").write_text(
        "def work():\n    items = [1]\n    count = len(items)\n"
        "    items.append(2)\n    return count\n",
        encoding="utf-8",
    )
    return root


def analyze(root: Path, family: str = "score"):
    return INSPECTORS[family](
        SnapshotRequest(
            target=DirectorySourceReference(root=root),
            config=AnalysisConfig(clone_min_sloc=2, calibration_profile="__raw__"),
        )
    )


def chosen(report, kind: str):
    return next(
        item
        for item in review_targets(report)
        if item.state == "reviewable"
        and item.anchor.subject.kind.value == kind
        and (
            kind != "clone"
            or {location.path.root for location in item.anchor.subject.locations}
            == {"a.py", "b.py"}
        )
    )


def record(store: Path, report, kind: str = "clone", **options):
    return write_review(
        store,
        report,
        chosen(report, kind).id,
        actor="reviewer",
        disposition=ReviewDisposition.DEFER,
        reason="Separate contracts.",
        **options,
    )


def legacy_record(store: Path, report):
    group = next(
        group
        for group in report.clone_groups
        if {member.path.root for member in group.detail.members} == {"a.py", "b.py"}
    )
    return write_clone_review(
        store,
        report,
        group.id,
        disposition=ReviewDisposition.NO_CHANGE,
        reason="Original contract review.",
    )


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("selected_family", INSPECTORS)
def test_selected_report_family_controls_native_resolution(
    project: Path, kind: str, selected_family: str
) -> None:
    family = "score" if kind in {"clone", "complexity", "pattern"} else kind
    report = analyze(project, family)
    store = project.parent / "reviews.json"
    ledger = record(store, report, kind)
    before = store.read_bytes()
    selected = analyze(project, selected_family)
    resolution = resolve_reviews(selected, ledger)
    result = resolution.results[0]
    assert result.state == ("current" if family == selected_family else "not-in-selected-report")
    if family != selected_family:
        assert result.reason == "review-family-not-in-selected-report"
    assert result.event == ledger.events[0]
    assert resolution.schema_version == "3" and ledger.schema_version == "2"
    assert resolution.events == ledger.events
    assert type(resolution).model_validate_json(resolution.model_dump_json()) == resolution
    assert store.read_bytes() == before


def test_supersession_is_explicit_preserves_legacy_and_uses_original_link_event(
    project: Path,
) -> None:
    report, store = analyze(project), project.parent / "reviews.json"
    legacy = legacy_record(store, report)
    unlinked = record(store, report)
    assert "supersedes_legacy_id" not in unlinked.events[0].model_dump(mode="json")
    assert resolve_reviews(report, unlinked).legacy_results[0].state == "current"
    legacy_id = legacy.decisions[0].id
    linked = record(
        store, report, review_id=unlinked.events[0].review_id, supersedes_legacy_id=legacy_id
    )
    assert linked.events[1].supersedes_legacy_id == legacy_id
    repeated = record(
        store, report, review_id=linked.events[1].review_id, supersedes_legacy_id=legacy_id
    )
    latest = record(store, report, review_id=linked.events[1].review_id)
    assert latest.legacy_decisions == legacy.decisions
    assert latest.events[:3] == repeated.events and latest.events[:2] == linked.events
    assert "supersedes_legacy_id" not in latest.events[-1].model_dump(mode="json")
    resolution = resolve_reviews(report, latest)
    old = resolution.legacy_results[0]
    assert old.state == "superseded" and old.decision == legacy.decisions[0]
    assert old.review_id == linked.events[1].review_id and old.sequence == 2
    assert resolution.results[0].event == latest.events[-1]
    assert resolution.results[0].state == "current"
    assert load_review_ledger(store) == latest
    assert type(resolution).model_validate_json(resolution.model_dump_json()) == resolution


@pytest.mark.parametrize("replacement_state", ["current", "stale", "missing", "outside"])
def test_superseded_legacy_remains_separate_from_replacement_resolution(
    project: Path, replacement_state: str
) -> None:
    report, store = analyze(project), project.parent / "reviews.json"
    legacy = legacy_record(store, report)
    ledger = record(store, report, supersedes_legacy_id=legacy.decisions[0].id)
    if replacement_state == "stale":
        path = project / "a.py"
        path.write_text(path.read_text() + "# new comment\n", encoding="utf-8")
    elif replacement_state == "missing":
        (project / "b.py").write_text("VALUE = 1\n", encoding="utf-8")
    selected = analyze(project, "model" if replacement_state == "outside" else "score")
    before = store.read_bytes()
    resolution = resolve_reviews(selected, ledger)
    old = resolution.legacy_results[0]
    assert old.state == "superseded" and old.decision == legacy.decisions[0]
    assert old.review_id == ledger.events[0].review_id and old.sequence == 1
    expected = "not-in-selected-report" if replacement_state == "outside" else replacement_state
    assert resolution.results[0].state == expected
    assert store.read_bytes() == before


def test_explicit_supersession_accepts_changed_evidence_for_same_clone_members(
    project: Path,
) -> None:
    report, store = analyze(project), project.parent / "reviews.json"
    legacy = legacy_record(store, report)
    for name in ("a.py", "b.py"):
        path = project / name
        path.write_text(path.read_text().replace("+ 1", "+ 2"), encoding="utf-8")
    changed = analyze(project)
    assert chosen(changed, "clone").id != chosen(report, "clone").id
    ledger = record(store, changed, supersedes_legacy_id=legacy.decisions[0].id)
    resolution = resolve_reviews(changed, ledger)
    assert resolution.legacy_results[0].state == "superseded"
    assert resolution.results[0].state == "current"


@pytest.mark.parametrize("invalid", ["unknown-id", "non-clone", "different-members", "claimed"])
def test_invalid_supersession_does_not_write(project: Path, invalid: str) -> None:
    report, store = analyze(project), project.parent / "reviews.json"
    legacy = legacy_record(store, report)
    legacy_id, kind = legacy.decisions[0].id, "clone"
    if invalid == "unknown-id":
        legacy_id = "unknown-legacy-id"
    elif invalid == "non-clone":
        kind = "complexity"
    elif invalid == "different-members":
        (project / "c.py").write_text((project / "a.py").read_text(), encoding="utf-8")
        report = analyze(project)
    else:
        record(store, report, supersedes_legacy_id=legacy_id)
        for name in ("a.py", "b.py"):
            path = project / name
            path.write_text(path.read_text().replace("+ 1", "+ 2"), encoding="utf-8")
        report = analyze(project)
    before = store.read_bytes()
    if invalid == "different-members":
        target = next(
            item
            for item in review_targets(report)
            if item.anchor.subject.kind.value == "clone"
            and {location.path.root for location in item.anchor.subject.locations}
            == {"a.py", "b.py", "c.py"}
        )
    else:
        target = chosen(report, kind)
    with pytest.raises((InputError, ValueError)):
        write_review(
            store,
            report,
            target.id,
            actor="reviewer",
            disposition=ReviewDisposition.DEFER,
            reason="Explicit new judgment.",
            supersedes_legacy_id=legacy_id,
        )
    assert store.read_bytes() == before


@pytest.mark.parametrize(
    "invalid", ["unknown-id", "non-clone", "different-members", "language", "cohort", "claimed"]
)
def test_ledger_validation_rejects_forged_supersession(project: Path, invalid: str) -> None:
    report, store = analyze(project), project.parent / "reviews.json"
    legacy = legacy_record(store, report)
    ledger = record(store, report)
    wire = ledger.model_dump(mode="json")
    event = wire["events"][0]
    event["supersedes_legacy_id"] = legacy.decisions[0].id
    if invalid == "unknown-id":
        event["supersedes_legacy_id"] = "unknown-legacy-id"
    elif invalid == "non-clone":
        event["decision"]["anchor"] = chosen(report, "complexity").anchor.model_dump(mode="json")
    elif invalid in {"language", "cohort"}:
        event["decision"]["anchor"]["subject"][invalid] = (
            "typescript" if invalid == "language" else "test"
        )
    elif invalid == "different-members":
        (project / "c.py").write_text((project / "a.py").read_text(), encoding="utf-8")
        different = next(
            item
            for item in review_targets(analyze(project))
            if item.anchor.subject.kind.value == "clone"
            and {location.path.root for location in item.anchor.subject.locations}
            == {"a.py", "b.py", "c.py"}
        )
        event["decision"]["anchor"] = different.anchor.model_dump(mode="json")
    else:
        wire["events"].append({**event, "sequence": 2, "review_id": "other-history"})
    unlinked = {
        **wire,
        "events": [
            {key: value for key, value in item.items() if key != "supersedes_legacy_id"}
            for item in wire["events"]
        ],
    }
    type(ledger).model_validate(unlinked)
    with pytest.raises(ValidationError):
        type(ledger).model_validate(wire)
    store.write_text(json.dumps(wire), encoding="utf-8")
    before = store.read_bytes()
    with pytest.raises(InputError):
        load_review_ledger(store)
    assert store.read_bytes() == before


def test_cli_supersedes_records_link_and_retains_legacy_decision(project: Path) -> None:
    report = analyze(project)
    store, saved = project.parent / "reviews.json", project.parent / "score.json"
    legacy = legacy_record(store, report)
    saved.write_text(report.model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "review-report",
            "set",
            chosen(report, "clone").id,
            "--report",
            str(saved),
            "--store",
            str(store),
            "--actor",
            "Ada",
            "--disposition",
            "defer",
            "--reason",
            "New explicit judgment.",
            "--supersedes",
            legacy.decisions[0].id,
        ],
    )
    assert result.exit_code == 0, result.output
    ledger = load_review_ledger(store)
    assert ledger.events[0].supersedes_legacy_id == legacy.decisions[0].id
    assert ledger.legacy_decisions == legacy.decisions


@pytest.mark.parametrize("kind", KINDS)
def test_supported_family_with_no_matching_evidence_remains_missing(
    project: Path, kind: str
) -> None:
    family = "score" if kind in {"clone", "complexity", "pattern"} else kind
    ledger = record(project.parent / "reviews.json", analyze(project, family), kind)
    for path in project.glob("*.py"):
        path.write_text("VALUE = 1\n", encoding="utf-8")
    selected = analyze(project, family)
    assert not [item for item in review_targets(selected) if item.anchor.subject.kind.value == kind]
    result = resolve_reviews(selected, ledger).results[0]
    assert result.state == "missing"
    assert result.reason == "evidence-absent-or-unavailable"


@pytest.mark.parametrize("selected_family", ["model", "variant", "derived"])
def test_legacy_review_outside_analysis_report_retains_decision_and_scope(
    project: Path, selected_family: str
) -> None:
    report = analyze(project)
    store = project.parent / "legacy.json"
    legacy = legacy_record(store, report)
    before = store.read_bytes()
    resolution = resolve_reviews(analyze(project, selected_family), load_review_ledger(store))
    result = resolution.legacy_results[0]
    assert result.state == "not-in-selected-report"
    assert result.reason == "review-family-not-in-selected-report"
    assert result.decision == legacy.decisions[0]
    assert type(resolution).model_validate_json(resolution.model_dump_json()) == resolution
    assert legacy.schema_version == "1" and load_review_store(store) == legacy
    assert resolve_reviews(report, load_review_ledger(store)).legacy_results[0].state == "current"
    assert store.read_bytes() == before


def test_scope_terminal_names_selected_report_and_json_show_does_not_write(project: Path) -> None:
    report = analyze(project)
    store, saved = project.parent / "reviews.json", project.parent / "model.json"
    record(store, report)
    selected = analyze(project, "model")
    saved.write_text(selected.model_dump_json(), encoding="utf-8")
    before = store.read_bytes()
    runner = CliRunner()
    args = ["review-report", "show", "--report", str(saved), "--store", str(store)]
    terminal = runner.invoke(app, args)
    assert terminal.exit_code == 0, terminal.output
    assert "not-in-selected-report" in terminal.stdout
    assert "selected report" in terminal.stdout.lower()
    structured = runner.invoke(app, [*args, "--json"])
    assert structured.exit_code == 0, structured.output
    assert json.loads(structured.stdout)["results"][0]["state"] == "not-in-selected-report"
    assert store.read_bytes() == before
