"""Legacy review entry points explain how to use a saved-report ledger safely."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.application.reviews import load_review_store, write_clone_review
from slop_measure.cli import app
from slop_measure.domain.review_workflow import ReviewLedger
from slop_measure.domain.reviews import ReviewDisposition
from slop_measure.errors import InputError


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    root = tmp_path / "project"
    root.mkdir()
    for name in ("a.py", "b.py"):
        (root / name).write_text(
            "def work(source):\n    value = source + 1\n    return value\n", encoding="utf-8"
        )
    (root / "slop.toml").write_text(
        'clone_min_sloc = 2\ncalibration_profile = "__raw__"\n', encoding="utf-8"
    )
    report = scan(
        SnapshotRequest(
            target=DirectorySourceReference(root=root),
            config=AnalysisConfig(clone_min_sloc=2, calibration_profile="__raw__"),
        )
    )
    assert report.clone_groups
    return root, tmp_path / "reviews.json", report


def assert_ledger_guidance(message: str) -> None:
    text = " ".join(message.lower().split())
    for instruction in (
        "review-report show",
        "--report",
        "--store",
        "fresh",
        "saved report",
        "schema-1",
        "copy",
        "score --reviews",
    ):
        assert instruction in text, message


def test_legacy_loader_explains_schema_two_and_preserves_ledger(project):
    _, store, _ = project
    store.write_text(ReviewLedger().model_dump_json(indent=2) + "\n", encoding="utf-8")
    before = store.read_bytes()
    with pytest.raises(InputError) as error:
        load_review_store(store)
    assert_ledger_guidance(str(error.value))
    assert store.read_bytes() == before


def command_args(command: str, root: Path, store: Path, group_id: str) -> list[str]:
    if command == "score":
        return ["score", str(root), "--reviews", str(store), "--json"]
    if command == "findings":
        return ["findings", "--root", str(root), "--reviews", str(store), "--json"]
    if command == "review-show":
        return ["review", "show", "--root", str(root), "--store", str(store), "--json"]
    return [
        "review",
        "set",
        group_id,
        "--root",
        str(root),
        "--store",
        str(store),
        "--disposition",
        "defer",
        "--reason",
        "Check the shared contract.",
    ]


@pytest.mark.parametrize("command", ["score", "findings", "review-show", "review-set"])
def test_legacy_commands_reject_schema_two_with_next_steps_without_writes(project, command):
    root, store, report = project
    store.write_text(ReviewLedger().model_dump_json(indent=2) + "\n", encoding="utf-8")
    before = store.read_bytes()
    paths = set(store.parent.iterdir())
    result = CliRunner().invoke(app, command_args(command, root, store, report.clone_groups[0].id))
    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    assert_ledger_guidance(result.stderr)
    assert store.read_bytes() == before
    assert set(store.parent.iterdir()) == paths


@pytest.mark.parametrize("command", ["score", "findings", "review-show"])
def test_schema_one_loader_and_cli_continue_resolving_existing_decisions(project, command):
    root, store, report = project
    original = write_clone_review(
        store,
        report,
        report.clone_groups[0].id,
        disposition=ReviewDisposition.NO_CHANGE,
        reason="Contracts evolve independently.",
    )
    before = store.read_bytes()
    assert original.schema_version == "1"
    assert load_review_store(store) == original
    result = CliRunner().invoke(app, command_args(command, root, store, report.clone_groups[0].id))
    assert result.exit_code == 0, result.output
    results = json.loads(result.stdout)["review_results"]
    assert len(results) == 1
    assert results[0]["state"] == "current"
    assert results[0]["decision"]["reason"] == "Contracts evolve independently."
    assert store.read_bytes() == before


@pytest.mark.parametrize(
    "contents",
    [b"not JSON", b'{"schema_version":"999"}', b'{"schema_version":"1","decisions":"bad"}'],
    ids=["malformed", "unknown-schema", "invalid-schema-one"],
)
def test_invalid_stores_still_fail_without_rewriting_or_claiming_schema_two(project, contents):
    root, store, _ = project
    store.write_bytes(contents)
    with pytest.raises(InputError):
        load_review_store(store)
    result = CliRunner().invoke(app, ["score", str(root), "--reviews", str(store), "--json"])
    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    assert "Invalid analysis input" in result.stderr
    assert "review-report show" not in result.stderr
    assert store.read_bytes() == contents
