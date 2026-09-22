"""Review filters select saved evidence without changing the measured population."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure.api import (
    AnalysisConfig,
    ComparisonRequest,
    DirectorySourceReference,
    SnapshotRequest,
    compare,
    scan,
)
from slop_measure.application.derived import inspect_derived
from slop_measure.application.models import inspect_models
from slop_measure.application.review_workflow import review_targets, write_review
from slop_measure.application.variants import inspect_variants
from slop_measure.cli import app
from slop_measure.domain.reviews import ReviewDisposition

SOURCE = (
    "def low(value):\n    result = value + 1\n    return result\n"
    "def equal(value):\n    if value:\n        value += 1\n"
    "    if value:\n        value += 1\n    return value\n"
    "def hot(value):\n" + "    if value:\n        value += 1\n" * 3 + "    return value\n"
    "def assertions(value):\n" + "    assert value\n" * 5
)

EXPERIMENTS = [
    (
        "model",
        inspect_models,
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
    ),
    (
        "variant",
        inspect_variants,
        "from typing import Literal\nChoice = Literal['yes', 'no']\n"
        "def complete(value: Choice):\n"
        "    match value:\n        case 'yes' | 'no':\n            return 1\n",
    ),
    (
        "derived",
        inspect_derived,
        "def stale():\n    items = [1]\n    count = len(items)\n"
        "    items.append(2)\n    return count\n",
    ),
]


def request(root: Path) -> SnapshotRequest:
    return SnapshotRequest(
        target=DirectorySourceReference(root=root),
        config=AnalysisConfig(
            complexity_threshold=3, clone_min_sloc=2, calibration_profile="__raw__"
        ),
    )


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    root = tmp_path / "project"
    root.mkdir()
    (root / "tests").mkdir()
    for relative in ("app.py", "copy.py", "tests/test_app.py"):
        (root / relative).write_text(SOURCE, encoding="utf-8")
    return root


def save(root: Path, report) -> Path:
    saved = root.parent / "report.json"
    saved.write_text(report.model_dump_json(), encoding="utf-8")
    return saved


def listed(saved: Path, *options: str) -> list[dict]:
    result = CliRunner().invoke(
        app, ["review-report", "list", "--report", str(saved), *options, "--json"]
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["targets"]


def subject(item: dict) -> dict:
    return item["anchor"]["subject"] if item["state"] == "reviewable" else item["subject"]


def catalog(report) -> list[dict]:
    return [item.model_dump(mode="json") for item in review_targets(report)]


def test_default_list_preserves_complete_catalog_and_labels_reviewable_evidence(project: Path):
    report = scan(request(project))
    saved = save(project, report)
    actual = listed(saved)
    assert actual == catalog(report)
    assert {subject(item)["kind"] for item in actual} == {"clone", "pattern", "complexity"}
    assert any(subject(item)["symbol"] == "low" for item in actual)
    output = CliRunner().invoke(app, ["review-report", "list", "--report", str(saved)])
    assert output.exit_code == 0, output.output
    assert "reviewable evidence" in output.stdout.lower()
    assert "not a finding count" in output.stdout.lower()


@pytest.mark.parametrize("kind", ["clone", "complexity", "pattern", "model", "variant", "derived"])
def test_each_kind_selects_exact_existing_targets(project: Path, kind: str):
    report = scan(request(project))
    assert listed(save(project, report), "--kind", kind) == [
        item for item in catalog(report) if subject(item)["kind"] == kind
    ]


@pytest.mark.parametrize("cohort", ["production", "test"])
def test_kind_union_then_cohort_intersection_deduplicates(project: Path, cohort: str):
    report = scan(request(project))
    assert listed(save(project, report), "--cohort", cohort) == [
        item for item in catalog(report) if subject(item)["cohort"] == cohort
    ]
    actual = listed(
        save(project, report),
        "--kind",
        "complexity",
        "--kind",
        "clone",
        "--kind",
        "complexity",
        "--cohort",
        cohort,
    )
    assert actual == [
        item
        for item in catalog(report)
        if subject(item)["kind"] in {"complexity", "clone"} and subject(item)["cohort"] == cohort
    ]
    assert len({item["id"] for item in actual}) == len(actual)


@pytest.mark.parametrize("version", ["1", "2", "3"])
def test_hotspots_use_report_version_cohort_and_strict_configured_threshold(
    project: Path, version: str
):
    report = scan(request(project))
    payload = report.model_dump(mode="json")
    for metric in payload["provenance"]["metrics"]:
        if metric["metric_id"] == "m4.erosion":
            metric["version"] = version
    owned = type(report).model_validate(payload)
    saved = save(project, owned)
    actual = listed(saved, "--hotspots-only")
    expected = [
        item
        for item in catalog(owned)
        if subject(item)["kind"] == "complexity"
        and (
            subject(item)["symbol"] == "hot"
            or (
                subject(item)["symbol"] == "assertions"
                and (version != "3" or subject(item)["cohort"] == "production")
            )
        )
    ]
    assert actual == expected and actual
    assert listed(saved, "--kind", "clone", "--kind", "complexity", "--hotspots-only") == actual
    assert listed(saved, "--hotspots-only", "--cohort", "test") == [
        item for item in expected if subject(item)["cohort"] == "test"
    ]


@pytest.mark.parametrize("version", [None, "999"])
def test_hotspots_reject_unknown_metric_basis_without_hiding_general_evidence(
    project: Path, version: str | None
):
    report = scan(request(project))
    payload = report.model_dump(mode="json")
    metrics = payload["provenance"]["metrics"]
    if version is None:
        payload["provenance"]["metrics"] = [
            metric for metric in metrics if metric["metric_id"] != "m4.erosion"
        ]
    else:
        for metric in metrics:
            if metric["metric_id"] == "m4.erosion":
                metric["version"] = version
    owned = type(report).model_validate(payload)
    saved = save(project, owned)
    assert listed(saved, "--kind", "complexity", "--cohort", "test") == [
        item
        for item in catalog(owned)
        if subject(item)["kind"] == "complexity" and subject(item)["cohort"] == "test"
    ]
    result = CliRunner().invoke(
        app, ["review-report", "list", "--report", str(saved), "--hotspots-only", "--json"]
    )
    assert result.exit_code == 2, result.output
    assert "m4" in result.output.lower() and "version" in result.output.lower()
    assert result.stdout == ""


def test_missing_source_hash_keeps_owned_hotspot_evidence_visible(project: Path):
    report = scan(request(project))
    payload = report.model_dump(mode="json")
    for cohort in payload["cohorts"]:
        for file in cohort["current"]["files"]:
            file.pop("source_sha256", None)
    owned = type(report).model_validate(payload)
    saved = save(project, owned)
    actual = listed(saved, "--kind", "complexity", "--cohort", "test", "--hotspots-only")
    assert len(actual) == 1
    assert subject(actual[0])["symbol"] == "hot"
    assert actual[0]["state"] == "unavailable"
    assert actual[0]["reason"] == "source-hash-unavailable"


@pytest.mark.parametrize("kind,inspector,source", EXPERIMENTS, ids=["model", "variant", "derived"])
def test_experimental_filters_preserve_catalog_and_reject_hotspots(
    project: Path, kind, inspector, source
):
    (project / "experiment.py").write_text(source, encoding="utf-8")
    (project / "tests/test_experiment.py").write_text(source, encoding="utf-8")
    report = inspector(request(project))
    saved = save(project, report)
    assert listed(saved) == catalog(report)
    actual = listed(saved, "--kind", kind, "--cohort", "test")
    assert actual == [item for item in catalog(report) if subject(item)["cohort"] == "test"]
    assert actual
    if kind == "variant":
        assert {subject(item)["symbol"] for item in actual} == {"complete"}
    result = CliRunner().invoke(
        app, ["review-report", "list", "--report", str(saved), "--hotspots-only", "--json"]
    )
    assert result.exit_code == 2, result.output
    assert "hotspot" in result.output.lower() and "report" in result.output.lower()
    assert result.stdout == ""


@pytest.mark.parametrize(
    "options,explanation",
    [
        (["--kind", "clone", "--hotspots-only"], "complexity"),
        (["--kind", "bogus"], "kind"),
        (["--cohort", "bogus"], "cohort"),
    ],
)
def test_invalid_selections_fail_with_actionable_errors(project: Path, options, explanation):
    saved = save(project, scan(request(project)))
    result = CliRunner().invoke(
        app, ["review-report", "list", "--report", str(saved), *options, "--json"]
    )
    assert result.exit_code == 2, result.output
    assert explanation in result.output.lower()
    assert result.stdout == ""


def test_filtering_saved_comparison_uses_only_current_side_and_preserves_files(project: Path):
    baseline = project.parent / "baseline"
    baseline.mkdir()
    (baseline / "old.py").write_text(SOURCE.replace("hot", "old_hot"), encoding="utf-8")
    report = compare(
        ComparisonRequest(
            baseline=DirectorySourceReference(root=baseline),
            current=DirectorySourceReference(root=project),
            config=request(project).config,
        )
    )
    saved = save(project, report)
    store = project.parent / "reviews.json"
    chosen = next(item for item in review_targets(report) if item.state == "reviewable")
    write_review(
        store,
        report,
        chosen.id,
        actor="Ada",
        disposition=ReviewDisposition.DEFER,
        reason="Check later.",
    )
    before_report, before_store = saved.read_bytes(), store.read_bytes()
    before_model = report.model_dump_json()
    for path in (*project.rglob("*.py"), *baseline.rglob("*.py")):
        path.unlink()
    actual = listed(saved, "--kind", "complexity", "--hotspots-only")
    assert actual
    assert all(subject(item)["symbol"] != "old_hot" for item in actual)
    assert {item["id"] for item in actual} <= {item.id for item in review_targets(report)}
    assert saved.read_bytes() == before_report
    assert store.read_bytes() == before_store
    assert report.model_dump_json() == before_model
