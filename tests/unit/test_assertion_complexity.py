"""Assertion syntax remains visible while test-cohort erosion measures control flow."""

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.cli import app
from slop_measure.domain.evidence import FunctionEvidence
from slop_measure.domain.metrics import MeasuredMetric, ProjectMetricScope
from slop_measure.domain.source import Cohort
from slop_measure.metrics.erosion import measure_erosion
from slop_measure.reporting.terminal import render_explanation


def function_payload(**fields: object) -> dict:
    return {
        "path": "app.py",
        "qualified_name": "f",
        "span": {"start_line": 1, "end_line": 4},
        "sloc_lines": [1, 2, 3, 4],
        "cyclomatic_complexity": 16,
        **fields,
    }


def test_assertion_counts_are_known_or_unknown_without_changing_raw_mass() -> None:
    historical = FunctionEvidence.model_validate(function_payload())
    payload = historical.model_dump(mode="json")
    assert "assertion_count" not in payload
    assert payload["control_flow_complexity"] is None
    assert FunctionEvidence.model_validate_json(historical.model_dump_json()) == historical
    known = FunctionEvidence.model_validate(function_payload(assertion_count=15))
    payload = known.model_dump(mode="json")
    assert payload["assertion_count"] == 15 and payload["control_flow_complexity"] == 1
    assert known.mass == 32
    assert FunctionEvidence.model_validate_json(known.model_dump_json()) == known
    for bad in (0, 2, None):
        with pytest.raises(ValidationError):
            FunctionEvidence.model_validate({**payload, "control_flow_complexity": bad})


@pytest.mark.parametrize("count", [-1, 16, 17, True, 1.5, "1"])
def test_assertion_count_rejects_invalid_or_impossible_values(count: object) -> None:
    with pytest.raises(ValidationError):
        FunctionEvidence.model_validate(function_payload(assertion_count=count))


@pytest.mark.parametrize(
    "cohort,expected_numerator,expected_denominator",
    [
        (Cohort.TEST, 0, 2),
        (Cohort.PRODUCTION, 12, 32),
    ],
)
def test_effective_complexity_depends_on_owned_cohort(
    cohort: Cohort, expected_numerator: int, expected_denominator: int
) -> None:
    function = FunctionEvidence.model_validate(function_payload(assertion_count=15))
    result = measure_erosion((function,), ProjectMetricScope(cohort=cohort), 10)
    assert isinstance(result, MeasuredMetric)
    assert result.raw.numerator == expected_numerator
    assert result.raw.denominator == expected_denominator
    assert function.mass == 32


def test_unknown_assertion_count_uses_adapter_complexity_and_real_flow_remains() -> None:
    unknown = FunctionEvidence.model_validate(function_payload())
    mixed = FunctionEvidence.model_validate(
        function_payload(qualified_name="mixed", assertion_count=5)
    )
    result = measure_erosion((unknown, mixed), ProjectMetricScope(cohort=Cohort.TEST), 10)
    assert isinstance(result, MeasuredMetric)
    assert result.raw.numerator == 14  # (16-10)*2 + (11-10)*2
    assert result.raw.denominator == 54  # 16*2 + 11*2


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assertions = "def assertion_only(value):\n" + "    assert value\n" * 15
    branches = "def real_flow(value):\n" + "    if value:\n        value += 1\n" * 11
    (tmp_path / "app.py").write_text(assertions, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text(assertions + branches, encoding="utf-8")
    (tmp_path / "slop.toml").write_text('calibration_profile = "__raw__"\n', encoding="utf-8")
    return tmp_path


def test_python_api_json_preserves_original_and_control_flow_complexities(project: Path) -> None:
    report = scan(
        SnapshotRequest(
            target=DirectorySourceReference(root=project),
            config=AnalysisConfig(calibration_profile="__raw__"),
        )
    )
    payload = report.model_dump(mode="json")
    assert payload["provenance"]["analyzers"][0]["adapter_version"] == "python-complexity-2"
    assert (
        next(
            item for item in payload["provenance"]["metrics"] if item["metric_id"] == "m4.erosion"
        )["version"]
        == "3"
    )
    cohorts = {item["cohort"]: item["current"] for item in payload["cohorts"]}
    test_functions = cohorts["test"]["files"][0]["functions"]
    assert [
        (
            item["qualified_name"],
            item["cyclomatic_complexity"],
            item["assertion_count"],
            item["control_flow_complexity"],
        )
        for item in test_functions
    ] == [
        ("assertion_only", 16, 15, 1),
        ("real_flow", 12, 0, 12),
    ]
    test_metric = next(
        item for item in cohorts["test"]["metrics"] if item["metric_id"] == "m4.erosion"
    )
    assert test_metric["raw"]["numerator"] == pytest.approx(2 * math.sqrt(23))
    assert test_metric["raw"]["denominator"] == pytest.approx(4 + 12 * math.sqrt(23))
    production = next(
        item for item in cohorts["production"]["metrics"] if item["metric_id"] == "m4.erosion"
    )
    assert production["raw"]["value"] == pytest.approx(6 / 16)
    explanation = render_explanation(
        report, "tests/test_app.py", ascii=True, color=False, width=140
    )
    evidence = explanation.split("How to read this report", 1)[0]
    assert "assertions" in evidence.lower() and "control-flow CC" in evidence
    assert "16" in evidence and "15" in evidence


def test_m4_findings_use_test_effective_complexity_but_production_total(project: Path) -> None:
    result = CliRunner().invoke(
        app, ["findings", "--root", str(project), "--metric", "m4", "--json"]
    )
    assert result.exit_code == 0, result.output
    selected = json.loads(result.stdout)["selection"]["functions"]
    assert {(item["cohort"], item["function"]["qualified_name"]) for item in selected} == {
        ("production", "assertion_only"),
        ("test", "real_flow"),
    }


def test_python_count_owns_nested_async_and_methods_without_guessing_unittest_calls(
    project: Path,
) -> None:
    (project / "app.py").write_text(
        "def outer(flag):\n    assert flag\n    async def inner():\n        assert flag\n"
        "        assert flag\n    return inner\n"
        "class Checks:\n    assert True\n    def check(self, flag):\n        assert flag\n"
        "        self.assertEqual(flag, True)\n        self.assertTrue(flag and flag)\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["scan", str(project), "--json"])
    assert result.exit_code == 0, result.output
    cohort = next(
        item for item in json.loads(result.stdout)["cohorts"] if item["cohort"] == "production"
    )
    functions = cohort["current"]["files"][0]["functions"]
    assert {
        (
            item["qualified_name"],
            item["cyclomatic_complexity"],
            item["assertion_count"],
            item["control_flow_complexity"],
        )
        for item in functions
    } == {
        ("outer", 2, 1, 1),
        ("outer.inner", 3, 2, 1),
        ("Checks.check", 3, 1, 2),
    }
