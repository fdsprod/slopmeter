"""Structural erosion keeps partial evidence and propagates scoped failures."""

from pathlib import Path

import pytest

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.domain.evidence import LanguageEvidence
from slop_measure.domain.inventory import SourceInventory
from slop_measure.domain.source import DirectorySourceIdentity
from slop_measure.errors import AnalysisFailure
from slop_measure.metrics.aggregate import aggregate_snapshot
from slop_measure.reporting.json import serialize_report


def file(path: str, sloc: int = 2) -> dict:
    return {
        "path": path,
        "language": "python",
        "cohort": "production",
        "sloc": sloc,
        "sloc_lines": list(range(1, sloc + 1)),
        "parse_state": "parsed",
    }


def outcome(path: str, cc: int | None) -> dict:
    functions = (
        []
        if cc is None
        else [
            {
                "path": path,
                "qualified_name": "f",
                "span": {"start_line": 1, "end_line": 2},
                "cyclomatic_complexity": cc,
                "sloc_lines": (1, 2),
            }
        ]
    )
    return {"state": "analyzed", "path": path, "functions": functions}


def aggregate(tmp_path: Path, payload: dict):
    return aggregate_snapshot(
        DirectorySourceIdentity(root=tmp_path),
        SourceInventory(),
        (LanguageEvidence.model_validate(payload),),
        AnalysisConfig(),
    )


def erosion(result: dict) -> dict:
    return next(item for item in result["metrics"] if item["metric_id"] == "m4.erosion")


def test_supported_erosion_projects_callables_and_combines_mass_across_files(
    tmp_path: Path,
) -> None:
    payload = {
        "language": "python",
        "capabilities": ["files", "functions"],
        "files": [file("high.py"), file("low.py"), file("constant.py", 1)],
        "function_analyses": [
            outcome("high.py", 11),
            outcome("low.py", 1),
            outcome("constant.py", None),
        ],
    }
    report = aggregate(tmp_path, payload)
    production = next(item.current for item in report.cohorts if item.cohort.value == "production")
    values = production.model_dump(mode="json")
    metric = next(item for item in values["metrics"] if item["metric_id"] == "m4.erosion")
    assert metric["state"] == "measured"
    assert metric["raw"]["value"] == pytest.approx(1 / 12)
    assert metric["raw"]["numerator"] == pytest.approx(2**0.5)
    assert metric["raw"]["denominator"] == pytest.approx(12 * 2**0.5)
    by_path = {item["evidence"]["path"]: item for item in values["files"]}
    assert erosion(by_path["constant.py"])["reason"] == "no-functions"
    assert by_path["high.py"]["functions"][0]["cyclomatic_complexity"] == 11
    assert erosion(by_path["low.py"])["raw"]["value"] == 0
    assert [(item.metric_id, item.version) for item in report.provenance.metrics] == [
        ("m4.erosion", "3")
    ]


@pytest.mark.parametrize("has_file", [False, True])
def test_supported_empty_callable_population_is_no_functions_even_without_sloc(
    tmp_path: Path, has_file: bool
) -> None:
    payload = {
        "language": "python",
        "capabilities": ["files", "functions"],
        "files": [file("empty.py", 0)] if has_file else [],
        "function_analyses": [outcome("empty.py", None)] if has_file else [],
    }
    report = aggregate(tmp_path, payload)
    for cohort in report.cohorts:
        assert erosion(cohort.current.model_dump(mode="json"))["reason"] == "no-functions"


def test_complexity_failure_only_invalidates_m4_and_flattens_diagnostic_once(
    tmp_path: Path,
) -> None:
    failed = {
        "state": "failed",
        "path": "bad.py",
        "diagnostic": {
            "severity": "error",
            "code": "python.complexity-error",
            "message": "Complexity failed.",
            "path": "bad.py",
        },
    }
    report = aggregate(
        tmp_path,
        {
            "language": "python",
            "capabilities": ["files", "functions"],
            "files": [file("bad.py"), file("good.py")],
            "function_analyses": [failed, outcome("good.py", 1)],
        },
    )
    assert len(report.diagnostics) == 1
    assert report.diagnostics[0].detail.code == "python.complexity-error"
    production = next(item.current for item in report.cohorts if item.cohort.value == "production")
    payload = production.model_dump(mode="json")
    assert [item.get("reason") for item in payload["metrics"]] == [
        "no-baseline",
        "unsupported-capability",
        "unsupported-capability",
        "analyzer-failed",
        "unsupported-capability",
    ]
    assert erosion(payload)["diagnostic_id"] == report.diagnostics[0].id
    assert payload["files"][0]["evidence"]["sloc"] == 2
    assert erosion(payload["files"][0])["reason"] == "analyzer-failed"
    assert erosion(payload["files"][1])["raw"]["value"] == 0


def test_strict_service_notices_embedded_complexity_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    (tmp_path / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    def fail_extract(*args: object, **kwargs: object):
        raise RuntimeError("fixture complexity failure")

    monkeypatch.setattr("slop_measure.languages.python.adapter.extract_functions", fail_extract)
    request = SnapshotRequest(
        target=DirectorySourceReference(root=tmp_path), config=AnalysisConfig()
    )
    report = scan(request)
    assert len(report.diagnostics) == 1
    assert report.diagnostics[0].detail.code == "python.complexity-error"
    with pytest.raises(AnalysisFailure):
        scan(SnapshotRequest(target=request.target, config=AnalysisConfig(strict=True)))


def test_callable_projection_order_is_independent_of_adapter_emission_order(tmp_path: Path) -> None:
    evidence_file = {**file("app.other", 4), "language": "other"}
    functions = [
        {
            "path": "app.other",
            "qualified_name": "first",
            "cyclomatic_complexity": 1,
            "span": {"start_line": 1, "end_line": 2},
            "sloc_lines": (1, 2),
        },
        {
            "path": "app.other",
            "qualified_name": "second",
            "cyclomatic_complexity": 11,
            "span": {"start_line": 3, "end_line": 4},
            "sloc_lines": (3, 4),
        },
    ]
    payload = {
        "language": "other",
        "capabilities": ["files", "functions"],
        "files": [evidence_file],
        "function_analyses": [{"state": "analyzed", "path": "app.other", "functions": functions}],
    }
    forward = aggregate(tmp_path, payload)
    payload["function_analyses"][0]["functions"] = list(reversed(functions))
    reverse = aggregate(tmp_path, payload)

    assert serialize_report(reverse) == serialize_report(forward)
    production = next(item.current for item in reverse.cohorts if item.cohort.value == "production")
    assert [item.qualified_name for item in production.files[0].functions] == ["first", "second"]
