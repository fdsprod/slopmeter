"""Saved review resolution distinguishes report scope and explicit replacement."""

import json
from pathlib import Path

import pytest
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
        if item.state == "reviewable" and item.anchor.subject.kind.value == kind
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
    assert result.state == (
        "current" if family == selected_family else "not-in-selected-report"
    )
    if family != selected_family:
        assert result.reason == "review-family-not-in-selected-report"
    assert result.event == ledger.events[0]
    assert resolution.schema_version == "3" and ledger.schema_version == "2"
    assert resolution.events == ledger.events
    assert type(resolution).model_validate_json(resolution.model_dump_json()) == resolution
    assert store.read_bytes() == before


@pytest.mark.parametrize("kind", KINDS)
def test_supported_family_with_no_matching_evidence_remains_missing(
    project: Path, kind: str
) -> None:
    family = "score" if kind in {"clone", "complexity", "pattern"} else kind
    ledger = record(project.parent / "reviews.json", analyze(project, family), kind)
    for path in project.glob("*.py"):
        path.write_text("VALUE = 1\n", encoding="utf-8")
    selected = analyze(project, family)
    assert not [
        item for item in review_targets(selected) if item.anchor.subject.kind.value == kind
    ]
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
