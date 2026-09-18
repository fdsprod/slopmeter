"""A non-Python adapter crosses the complete owned evidence and reporting pipeline."""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from slop_measure.application.service import AnalysisService
from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import EvidenceCapability, LanguageEvidence
from slop_measure.domain.metrics import MeasuredMetric
from slop_measure.domain.reports import MeasuredSnapshotScore
from slop_measure.domain.requests import ComparisonRequest, SnapshotRequest
from slop_measure.domain.scoring import CalibrationProfile
from slop_measure.domain.source import DirectorySourceReference, SourceDocument
from slop_measure.languages.registry import LanguageRegistry
from slop_measure.reporting.comparison import render_comparison
from slop_measure.reporting.json import serialize_report
from slop_measure.reporting.terminal import render_snapshot


@dataclass(frozen=True)
class InventedAdapter:
    language_id: str = "invented"
    suffix: str = ".invented"
    reverse: bool = False
    windows_paths: bool = False
    adapter_version = "invented-1"
    rule_set_version = "invented-rules-1"
    clone_normalization_version = "invented-clones-1"
    capabilities = frozenset(EvidenceCapability)

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset({self.suffix})

    def analyze(
        self, documents: tuple[SourceDocument, ...], config: AnalysisConfig
    ) -> LanguageEvidence:
        records: dict[str, list] = {
            key: [] for key in ("files", "pattern_analyses", "function_analyses", "clone_analyses")
        }
        for document in documents:
            path = (
                document.path.root.replace("/", "\\") if self.windows_paths else document.path.root
            )
            changed = document.content.startswith(b"pattern")
            records["files"].append(
                {
                    "path": path,
                    "language": self.language_id,
                    "cohort": document.cohort,
                    "parse_state": "parsed",
                    "sloc": 8,
                    "sloc_lines": list(range(1, 9)),
                }
            )
            findings = (
                [
                    {
                        "path": path,
                        "rule_id": "invented.redundancy",
                        "category": "redundancy",
                        "severity": "warning",
                        "span": {"start_line": 2, "end_line": 2},
                        "message": "Invented redundant statement.",
                    }
                ]
                if changed
                else []
            )
            records["pattern_analyses"].append({"path": path, "findings": findings})
            records["function_analyses"].append(
                {
                    "path": path,
                    "functions": [
                        {
                            "path": path,
                            "qualified_name": "work",
                            "span": {"start_line": 1, "end_line": 8},
                            "cyclomatic_complexity": 11 if changed else 1,
                            "sloc_lines": list(range(1, 9)),
                        }
                    ],
                }
            )
            records["clone_analyses"].append(
                {
                    "path": path,
                    "candidates": [
                        {
                            "path": path,
                            "span": {"start_line": 1, "end_line": 6},
                            "sloc_lines": list(range(1, 7)),
                            "statement_count": 6,
                            "normalization_version": self.clone_normalization_version,
                            "normalized_tokens": ["invented", "clone"],
                        }
                    ],
                }
            )
        for family in ("pattern_analyses", "function_analyses", "clone_analyses"):
            for outcome in records[family]:
                outcome["state"] = "analyzed"
        if self.reverse:
            records = {key: list(reversed(items)) for key, items in records.items()}
        return LanguageEvidence.model_validate(
            {"language": self.language_id, "capabilities": self.capabilities, **records}
        )


def synthetic_profile() -> CalibrationProfile:
    path = Path(__file__).parents[1] / "golden/scoring_reference.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(
        language="invented",
        rule_set_version="invented-rules-1",
        clone_normalization_version="invented-clones-1",
    )
    for metric in payload["metric_versions"]:
        if metric["metric_id"] == "m4.erosion":
            metric["version"] = "3"
    return CalibrationProfile.model_validate(payload)


def write_sources(root: Path, *, changed: bool, suffix: str = ".invented") -> None:
    root.mkdir(parents=True, exist_ok=True)
    for path in (f"z{suffix}", f"pkg/a{suffix}"):
        target = root / path
        target.parent.mkdir(exist_ok=True)
        target.write_bytes((b"pattern\n" if changed else b"plain\n") + b"owned line\n" * 7)


def settings() -> AnalysisConfig:
    return AnalysisConfig(production_patterns=("**/*",), calibration_profile="synthetic-1")


def test_non_python_adapter_supports_raw_metrics_calibration_comparison_and_both_renderers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.setattr(
        "slop_measure.application.service.load_profile", lambda _name: synthetic_profile()
    )
    before, after = tmp_path / "before", tmp_path / "after"
    write_sources(before, changed=False)
    write_sources(after, changed=True)
    service = AnalysisService(LanguageRegistry((InventedAdapter(),)))
    snapshot = service.scan(
        SnapshotRequest(target=DirectorySourceReference(root=after), config=settings())
    )
    assert snapshot.diagnostics == ()
    cohort = snapshot.cohorts[0]
    assert cohort.language == "invented"
    result = cohort.current
    values = {
        metric.metric_id: metric.raw.value
        for metric in result.metrics
        if isinstance(metric, MeasuredMetric)
    }
    assert values == {
        "m2.pattern-verbosity": 1 / 8,
        "m3.clone-verbosity": 6 / 8,
        "verbosity.combined": 6 / 8,
        "m4.erosion": pytest.approx(1 / 11),
    }
    assert isinstance(result.score, MeasuredSnapshotScore)
    assert result.score.points == 53.3
    assert len(snapshot.findings) == 2 and len(snapshot.clone_groups) == 1
    assert "53.3/100" in render_snapshot(snapshot, ascii=True, color=False)
    assert json.loads(serialize_report(snapshot))["cohorts"][0]["language"] == "invented"
    comparison = service.compare(
        ComparisonRequest(
            baseline=DirectorySourceReference(root=before),
            current=DirectorySourceReference(root=after),
            config=settings(),
        )
    )
    changed = comparison.cohorts[0]
    assert changed.kind == "comparison"
    assert changed.line_delta.state == "measured"
    assert (changed.line_delta.added, changed.line_delta.deleted, changed.line_delta.net) == (
        2,
        2,
        0,
    )
    assert {group.source.value for group in comparison.clone_groups} == {"baseline", "current"}
    assert all(finding.source.value == "current" for finding in comparison.findings)
    output = render_comparison(comparison, ascii=True, color=False)
    assert "M1 LOC delta" in output and "worse" in output
    assert json.loads(serialize_report(comparison))["analysis"]["kind"] == "comparison"
