"""Evidence filters preserve source ownership and complete clone groups."""

from copy import deepcopy

import pytest
from pydantic import ValidationError
from test_queries import report

from slop_measure.domain.evidence import DiagnosticSeverity
from slop_measure.domain.reports import AnalysisReport, SourceSide
from slop_measure.errors import SelectionError
from slop_measure.reporting.queries import (
    change_for_file,
    clones_for_file,
    findings_for_file,
    query_findings,
    select_file,
)


def snapshot() -> AnalysisReport:
    payload = report().model_dump(mode="json")
    payload["cohorts"][0]["current"]["files"][0]["functions"][1]["cyclomatic_complexity"] = 11
    for function in payload["cohorts"][0]["current"]["files"][0]["functions"]:
        function.pop("mass")
        function.pop("sloc")
    payload["findings"].append(
        {
            "id": "third",
            "source": "current",
            "detail": {
                "path": "pkg/app.py",
                "rule_id": "other",
                "category": "redundancy",
                "severity": "info",
                "span": {"start_line": 3, "end_line": 3},
                "message": "Other finding.",
            },
        }
    )
    payload["findings"].reverse()
    payload["clone_groups"] = [
        {
            "id": "clone",
            "source": "current",
            "detail": {
                "language": "python",
                "cohort": "production",
                "normalization_version": "test",
                "fingerprint": "a" * 64,
                "members": [
                    {"path": path, "span": {"start_line": 1, "end_line": 1}, "sloc_lines": [1]}
                    for path in ("pkg/app.py", "pkg/other.py")
                ],
            },
        }
    ]
    return AnalysisReport.model_validate(payload)


def comparison() -> AnalysisReport:
    payload = snapshot().model_dump(mode="json")
    payload["analysis"].update(kind="comparison", baseline={"kind": "directory", "root": "BEFORE"})
    cohort = payload["cohorts"][0]
    cohort["kind"] = "comparison"
    baseline = deepcopy(cohort["current"])
    baseline["files"][0]["evidence"]["path"] = "pkg/old.py"
    for function in baseline["files"][0]["functions"]:
        function["path"] = "pkg/old.py"
    cohort["baseline"] = baseline
    cohort["line_delta"] = {
        "state": "measured",
        "baseline_sloc": 5,
        "current_sloc": 5,
        "added": 0,
        "deleted": 0,
    }
    cohort["changes"] = [
        {
            "pair": {"kind": kind, "baseline_path": old, "current_path": new},
            "lines": {
                "state": "measured",
                "baseline_sloc": sloc,
                "current_sloc": sloc,
                "added_lines": [],
                "deleted_lines": [],
            },
        }
        for kind, old, new, sloc in (
            ("renamed", "pkg/old.py", "pkg/app.py", 4),
            ("unchanged", "pkg/other.py", "pkg/other.py", 1),
        )
    ]
    for name in ("findings", "clone_groups"):
        originals = deepcopy(payload[name])
        for item in originals:
            item["id"] = "baseline-" + item["id"]
            item["source"] = "baseline"
            details = item["detail"]["members"] if name == "clone_groups" else [item["detail"]]
            for detail in details:
                if detail["path"] == "pkg/app.py":
                    detail["path"] = "pkg/old.py"
        payload[name].extend(originals)
    return AnalysisReport.model_validate(payload)


def test_default_selection_is_frozen_complete_and_sorted_with_only_eroded_functions() -> None:
    owned = snapshot()
    selected = query_findings(owned)
    assert [item.id for item in selected.patterns] == ["finding-0001", "third", "finding-0002"]
    assert selected.clone_groups == owned.clone_groups
    assert len(selected.functions) == 1
    erosion = selected.functions[0]
    assert erosion.function is owned.cohorts[0].current.files[0].functions[1]
    assert erosion.source == SourceSide.CURRENT
    assert erosion.language == "python" and erosion.cohort.value == "production"
    assert isinstance(selected.patterns, tuple)
    with pytest.raises(ValidationError):
        selected.patterns = ()


@pytest.mark.parametrize(
    "metric,counts",
    [
        ("m2", (3, 0, 0)),
        ("m2.pattern-verbosity", (3, 0, 0)),
        ("m3", (0, 1, 0)),
        ("m3.clone-verbosity", (0, 1, 0)),
        ("m4", (0, 0, 1)),
        ("m4.erosion", (0, 0, 1)),
        ("combined", (3, 1, 0)),
        ("verbosity.combined", (3, 1, 0)),
    ],
)
def test_metric_family_filters_and_aliases(metric: str, counts: tuple[int, int, int]) -> None:
    result = query_findings(snapshot(), metric=metric)
    assert (len(result.patterns), len(result.clone_groups), len(result.functions)) == counts


def test_path_rule_severity_filters_compose_and_do_not_trim_clone_members() -> None:
    owned = snapshot()
    selected = query_findings(owned, path=r"pkg\app.py", metric="combined")
    assert [item.id for item in selected.patterns] == ["finding-0001", "third"]
    assert selected.clone_groups[0] is owned.clone_groups[0]
    assert len(selected.clone_groups[0].detail.members) == 2
    filtered = query_findings(
        owned, path="pkg/app.py", rule="other", severity=DiagnosticSeverity.INFO
    )
    assert [item.id for item in filtered.patterns] == ["third"]
    assert filtered.clone_groups == filtered.functions == ()
    assert query_findings(owned, metric="m3", rule="example").clone_groups == ()
    missing = query_findings(owned, path="missing.py")
    assert missing.patterns == missing.clone_groups == missing.functions == ()


def test_exact_comparison_side_queries_keep_original_results_findings_groups_and_changes() -> None:
    owned = comparison()
    cohort = owned.cohorts[0]
    assert cohort.kind == "comparison"
    assert select_file(owned, "pkg/old.py", source=SourceSide.BASELINE) is cohort.baseline.files[0]
    assert select_file(owned, "pkg/app.py") is cohort.current.files[0]
    assert change_for_file(owned, "pkg/old.py", source=SourceSide.BASELINE) is cohort.changes[0]
    assert change_for_file(owned, "pkg/app.py", source=SourceSide.CURRENT) is cohort.changes[0]
    assert all(
        item.source is SourceSide.BASELINE
        for item in findings_for_file(owned, "pkg/old.py", source=SourceSide.BASELINE)
    )
    groups = clones_for_file(owned, "pkg/old.py", source=SourceSide.BASELINE)
    assert len(groups) == 1 and groups[0] is owned.clone_groups[1]
    assert len(groups[0].detail.members) == 2
    selected = query_findings(owned, path="pkg/old.py", source=SourceSide.BASELINE)
    assert len(selected.patterns) == 2 and len(selected.functions) == 1
    assert selected.functions[0].function is cohort.baseline.files[0].functions[1]
    for select in (select_file, findings_for_file, clones_for_file, change_for_file):
        with pytest.raises(SelectionError):
            select(owned, "pkg/old.py", source=SourceSide.CURRENT)


def test_invalid_filters_and_snapshot_baseline_queries_are_explicit_errors() -> None:
    owned = snapshot()
    with pytest.raises(SelectionError):
        query_findings(owned, metric="m1")
    with pytest.raises(SelectionError):
        query_findings(owned, path="../app.py")
    with pytest.raises(SelectionError):
        query_findings(owned, source=SourceSide.BASELINE)
    for select in (select_file, findings_for_file, clones_for_file):
        with pytest.raises(SelectionError):
            select(owned, "pkg/app.py", source=SourceSide.BASELINE)
    with pytest.raises(SelectionError):
        change_for_file(owned, "pkg/app.py")
