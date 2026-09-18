"""Pattern aggregation preserves successful evidence and isolates M2 failures."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.cli import app
from slop_measure.domain.evidence import LanguageEvidence
from slop_measure.domain.inventory import SourceInventory
from slop_measure.domain.source import DirectorySourceIdentity
from slop_measure.errors import AnalysisFailure, InvalidRuleSelection
from slop_measure.metrics.aggregate import aggregate_snapshot
from slop_measure.reporting.json import serialize_report


def evidence_payload() -> dict:
    files = [
        {
            "path": path,
            "language": "other",
            "cohort": "production",
            "sloc": 2,
            "sloc_lines": (1, 2),
            "parse_state": "parsed",
        }
        for path in ("a.other", "b.other")
    ]
    functions = [
        {
            "state": "analyzed",
            "path": file["path"],
            "functions": [
                {
                    "path": file["path"],
                    "qualified_name": "f",
                    "cyclomatic_complexity": 1,
                    "sloc_lines": (1, 2),
                    "span": {"start_line": 1, "end_line": 2},
                }
            ],
        }
        for file in files
    ]
    patterns = [
        {
            "state": "analyzed",
            "path": file["path"],
            "findings": [
                {
                    "path": file["path"],
                    "rule_id": "example",
                    "category": "redundancy",
                    "severity": "warning",
                    "message": "Redundant source.",
                    "span": {"start_line": 1, "end_line": 1},
                }
            ],
        }
        for file in files
    ]
    return {
        "language": "other",
        "capabilities": ["files", "patterns", "functions"],
        "files": files,
        "function_analyses": functions,
        "pattern_analyses": patterns,
    }


def aggregate(tmp_path: Path, payload: dict):
    return aggregate_snapshot(
        DirectorySourceIdentity(root=tmp_path),
        SourceInventory(),
        (LanguageEvidence.model_validate(payload),),
        AnalysisConfig(),
    )


def test_pattern_aggregation_projects_stable_ids_and_metric_versions(tmp_path: Path) -> None:
    payload = evidence_payload()
    forward = aggregate(tmp_path, payload)
    payload["pattern_analyses"].reverse()
    reverse = aggregate(tmp_path, payload)
    assert serialize_report(forward) == serialize_report(reverse)
    assert [
        (finding.id, finding.detail.path.root, finding.source.value) for finding in forward.findings
    ] == [("finding-0001", "a.other", "current"), ("finding-0002", "b.other", "current")]
    production = next(item.current for item in forward.cohorts if item.cohort.value == "production")
    m2 = production.model_dump(mode="json")["metrics"][1]
    assert m2["raw"]["value"] == 0.5
    assert {(item.metric_id, item.version) for item in forward.provenance.metrics} == {
        ("m2.pattern-verbosity", "1"),
        ("m4.erosion", "2"),
    }


def test_failed_pattern_batch_only_invalidates_m2_and_keeps_other_findings(tmp_path: Path) -> None:
    payload = evidence_payload()
    payload["pattern_analyses"][0] = {
        "state": "failed",
        "path": "a.other",
        "diagnostic": {
            "severity": "error",
            "code": "other.pattern-error",
            "message": "Failed.",
            "path": "a.other",
        },
    }
    report = aggregate(tmp_path, payload)
    assert len(report.diagnostics) == 1
    assert report.diagnostics[0].detail.code == "other.pattern-error"
    assert len(report.findings) == 1
    assert report.findings[0].detail.path.root == "b.other"
    production = next(item.current for item in report.cohorts if item.cohort.value == "production")
    values = production.model_dump(mode="json")
    assert values["metrics"][1]["reason"] == "analyzer-failed"
    assert values["metrics"][1]["diagnostic_id"] == report.diagnostics[0].id
    erosion = next(item for item in values["metrics"] if item["metric_id"] == "m4.erosion")
    assert erosion["raw"]["value"] == 0
    assert values["files"][0]["metrics"][1]["reason"] == "analyzer-failed"
    assert values["files"][1]["metrics"][1]["raw"]["value"] == 0.5


def test_strict_service_notices_embedded_pattern_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    (tmp_path / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    def fail(*args: object, **kwargs: object):
        raise RuntimeError("fixture pattern failure")

    monkeypatch.setattr("slop_measure.languages.python.adapter.run_patterns", fail)
    reference = DirectorySourceReference(root=tmp_path)
    report = scan(SnapshotRequest(target=reference, config=AnalysisConfig()))
    assert len(report.diagnostics) == 1
    assert report.diagnostics[0].detail.code == "python.pattern-error"
    with pytest.raises(AnalysisFailure):
        scan(SnapshotRequest(target=reference, config=AnalysisConfig(strict=True)))


@pytest.mark.parametrize("field", ["enabled_rules", "disabled_rules"])
def test_unknown_rule_is_configuration_failure_in_api_and_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    config = AnalysisConfig.model_validate({field: ["py.unknown"]})
    with pytest.raises(InvalidRuleSelection):
        scan(SnapshotRequest(target=DirectorySourceReference(root=tmp_path), config=config))
    (tmp_path / "slop.toml").write_text(f'{field} = ["py.unknown"]\n', encoding="utf-8")
    assert CliRunner().invoke(app, ["scan", str(tmp_path), "--json"]).exit_code == 2
