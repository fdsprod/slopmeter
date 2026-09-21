"""Review coverage describes inventory, uncertainty, and findings independently."""

# Parameter columns keep the three public review contracts visible together.
# ruff: noqa: PLR0913, PLR0917

import copy
import json
import re
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest
from slop_measure.application.derived import inspect_derived
from slop_measure.application.models import inspect_models
from slop_measure.application.variants import inspect_variants
from slop_measure.cli import app

MODEL_SOURCE = """from dataclasses import dataclass
@dataclass
class State:
    active: bool
    value: str | None
    def __post_init__(self):
        if self.active and self.value is None:
            raise ValueError("value required")
def first(item: State):
    if item.active and item.value is None:
        return None
    return item.value
def second(item: State):
    if item.active and item.value is None:
        return None
    return item.value
class Ordinary:
    pass
class AnotherOrdinary:
    pass
"""

VARIANT_SOURCE = """from enum import Enum
class Mode(Enum):
    ON = 1
    OFF = 2
def missing(value: Mode):
    match value:
        case Mode.ON:
            return 1
def fallback(value: Mode):
    match value:
        case _:
            return 0
def complete(value: Mode):
    match value:
        case Mode.ON | Mode.OFF:
            return 1
def untyped(value):
    match value:
        case _:
            return 0
def also_untyped(value):
    match value:
        case _:
            return 0
"""

DERIVED_SOURCE = """def stale():
    items = [1]
    count = len(items)
    items.append(2)
    return count
def current():
    items = [1]
    count = len(items)
    return count
def uncertain(items):
    count = len(items)
    return count
def also_uncertain(items):
    count = len(items)
    return count
"""

CASES = [
    pytest.param(
        "models",
        inspect_models,
        "models",
        "class-declarations",
        MODEL_SOURCE,
        (3, 1, 2, 1),
        id="models",
    ),
    pytest.param(
        "variants",
        inspect_variants,
        "handlers",
        "match-handlers",
        VARIANT_SOURCE,
        (5, 3, 2, 2),
        id="variants",
    ),
    pytest.param(
        "derived",
        inspect_derived,
        "functions",
        "functions",
        DERIVED_SOURCE,
        (4, 2, 2, 1),
        id="derived",
    ),
]


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    return tmp_path


def request(root: Path) -> SnapshotRequest:
    return SnapshotRequest(target=DirectorySourceReference(root=root), config=AnalysisConfig())


def populate(root: Path, source: str) -> None:
    (root / "evidence.py").write_text(source, encoding="utf-8")
    (root / "empty.py").write_text("# no declarations\n", encoding="utf-8")
    # No inventory can be inferred from a file that cannot be parsed.
    (root / "broken.py").write_text("class Hidden:\n    pass\ndef broken(:\n", encoding="utf-8")


@pytest.mark.parametrize("command,inspect,items,unit,source,counts", CASES)
def test_summary_is_derived_from_all_owned_inventory_and_groups_original_reasons(
    project, command, inspect, items, unit, source, counts
) -> None:
    populate(project, source)
    report = inspect(request(project))
    wire = report.model_dump(mode="json")
    reasons = Counter(
        item["reason"]
        for file in wire["files"]
        if file["state"] == "analyzed"
        for item in file[items]
        if item["state"] == "unresolved"
    )
    encountered, assessed, unresolved, findings = counts
    assert wire["summary"] == {
        "unit": unit,
        "files_analyzed": 2,
        "files_failed": 1,
        "encountered": encountered,
        "assessed": assessed,
        "unresolved": unresolved,
        "findings": findings,
        "unresolved_reasons": [
            {"reason": reason, "count": count} for reason, count in sorted(reasons.items())
        ],
    }
    assert len(reasons) == 1 and next(iter(reasons.values())) == 2
    cli = CliRunner().invoke(app, [command, "--root", str(project), "--json"])
    assert cli.exit_code == 0, cli.output
    assert json.loads(cli.stdout)["summary"] == wire["summary"]
    assert type(report).model_validate_json(report.model_dump_json()) == report
    legacy = copy.deepcopy(wire)
    del legacy["summary"]
    assert type(report).model_validate(legacy) == report
    assert type(report).model_validate(legacy).model_dump(mode="json")["summary"] == wire["summary"]


@pytest.mark.parametrize("command,inspect,items,unit,source,counts", CASES)
@pytest.mark.parametrize(
    "field",
    [
        "files_analyzed",
        "files_failed",
        "encountered",
        "assessed",
        "unresolved",
        "findings",
        "unresolved_reasons",
        "unit",
        "null",
    ],
)
def test_supplied_summary_cannot_override_evidence(
    project, command, inspect, items, unit, source, counts, field
) -> None:
    populate(project, source)
    report = inspect(request(project))
    wire = report.model_dump(mode="json")
    assert "summary" in wire
    if field == "null":
        wire["summary"] = None
    elif field == "unresolved_reasons":
        wire["summary"][field][0]["count"] += 1
    elif field == "unit":
        wire["summary"][field] = "functions" if unit != "functions" else "match-handlers"
    else:
        wire["summary"][field] += 1
    with pytest.raises(ValidationError):
        type(report).model_validate(wire)


def assert_count(text: str, label: str, count: int) -> None:
    assert re.search(rf"{label}\s*[:|]?\s*{count}\b", text), text


@pytest.mark.parametrize("command,inspect,items,unit,source,counts", CASES)
def test_terminal_coverage_precedes_details_and_preserves_grouped_reason(
    project, command, inspect, items, unit, source, counts
) -> None:
    populate(project, source)
    result = CliRunner().invoke(app, [command, "--root", str(project)])
    assert result.exit_code == 0, result.output
    text = result.stdout.lower()
    first_detail = min(text.index(name) for name in ("evidence.py", "broken.py"))
    coverage = text[:first_detail]
    assert "coverage" in coverage
    assert_count(coverage, "files analyzed", 2)
    assert_count(coverage, "files failed", 1)
    assert_count(coverage, "encountered " + unit.replace("-", " "), counts[0])
    for label, count in zip(("assessed", "unresolved", "findings"), counts[1:], strict=True):
        assert_count(coverage, label, count)
    assert "nothing assessed" not in coverage
    if command == "models":
        assert "recall" in text or "business model" in text
    wire = inspect(request(project)).model_dump(mode="json")
    reason = next(
        item["reason"]
        for file in wire["files"]
        if file["state"] == "analyzed"
        for item in file[items]
        if item["state"] == "unresolved"
    )
    # A grouped reason must retain its text and count before the per-item evidence.
    normalized = " ".join(coverage.split())
    assert " ".join(reason.lower().split()) in normalized
    assert re.search(
        r"(?:2\s*(?:[x\u00d7:|\u2013-]\s*)?"
        + re.escape(reason.lower())
        + r"|"
        + re.escape(reason.lower())
        + r"\s*[:|]?\s*2\b)",
        normalized,
    )


@pytest.mark.parametrize("command", ["models", "variants", "derived"])
def test_empty_inventory_explicitly_says_nothing_assessed(project, command) -> None:
    (project / "empty.py").write_text("pass\n", encoding="utf-8")
    result = CliRunner().invoke(app, [command, "--root", str(project)])
    assert result.exit_code == 0, result.output
    assert "nothing assessed" in result.stdout.lower()


@pytest.mark.parametrize(
    "command,source",
    [
        (
            "models",
            "from dataclasses import dataclass\n@dataclass\nclass Item:\n    active: bool\n",
        ),
        (
            "variants",
            VARIANT_SOURCE.split("def missing", 1)[0]
            + "def complete(value: Mode):\n    match value:\n"
            + "        case Mode.ON | Mode.OFF:\n            return 1\n",
        ),
        ("derived", "def current():\n    items = [1]\n    count = len(items)\n    return count\n"),
    ],
)
def test_assessed_without_findings_is_distinct_from_nothing_assessed(
    project, command, source
) -> None:
    (project / "evidence.py").write_text(source, encoding="utf-8")
    result = CliRunner().invoke(app, [command, "--root", str(project)])
    assert result.exit_code == 0, result.output
    text = result.stdout.lower()
    assert_count(text, "assessed", 1)
    assert_count(text, "findings", 0)
    assert "nothing assessed" not in text
