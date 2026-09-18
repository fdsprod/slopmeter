"""Report queries select exact files and callable identities without reanalysis."""

import pytest

from slop_measure.domain.reports import AnalysisReport
from slop_measure.errors import SelectionError
from slop_measure.reporting.queries import findings_for_file, select_callable, select_file


def report() -> AnalysisReport:
    score = {"state": "unavailable", "reason": "required-metric-unavailable"}
    functions = [
        {
            "path": "pkg/app.py",
            "qualified_name": "duplicate",
            "cyclomatic_complexity": 1,
            "span": {"start_line": start, "end_line": start + 1},
            "sloc_lines": (start, start + 1),
        }
        for start in (1, 3)
    ]
    return AnalysisReport.model_validate(
        {
            "analysis": {"kind": "snapshot", "current": {"kind": "directory", "root": "PROJECT"}},
            "provenance": {"tool_version": "1", "config": {}},
            "cohorts": [
                {
                    "kind": "snapshot",
                    "language": "python",
                    "cohort": "production",
                    "current": {
                        "score": score,
                        "files": [
                            {
                                "evidence": {
                                    "path": "pkg/app.py",
                                    "language": "python",
                                    "cohort": "production",
                                    "sloc": 4,
                                    "sloc_lines": (1, 2, 3, 4),
                                    "parse_state": "parsed",
                                },
                                "functions": functions,
                                "score": score,
                            },
                            {
                                "evidence": {
                                    "path": "pkg/other.py",
                                    "language": "python",
                                    "cohort": "production",
                                    "sloc": 1,
                                    "sloc_lines": (1,),
                                    "parse_state": "parsed",
                                },
                                "score": score,
                            },
                        ],
                    },
                }
            ],
            "findings": [
                {
                    "id": f"finding-{index:04}",
                    "detail": {
                        "path": path,
                        "rule_id": "example",
                        "category": "redundancy",
                        "severity": "warning",
                        "span": {"start_line": 1, "end_line": 1},
                        "message": "Review this source.",
                    },
                }
                for index, path in enumerate(("pkg/app.py", "pkg/other.py"), start=1)
            ],
        }
    )


def test_select_file_returns_owned_result_and_normalizes_windows_separators() -> None:
    snapshot = report()
    selected = select_file(snapshot, r"pkg\app.py")
    assert selected is snapshot.cohorts[0].current.files[0]
    assert selected.evidence.path.root == "pkg/app.py"
    assert len(selected.functions) == 2


@pytest.mark.parametrize("path", ["missing.py", "../pkg/app.py", "/pkg/app.py", "C:/pkg/app.py"])
def test_file_selection_rejects_unknown_or_nonproject_paths(path: str) -> None:
    with pytest.raises(SelectionError):
        select_file(report(), path)


def test_findings_query_preserves_owned_findings_for_only_selected_path() -> None:
    snapshot = report()
    findings = findings_for_file(snapshot, r"pkg\app.py")
    assert findings == (snapshot.findings[0],)
    with pytest.raises(SelectionError):
        findings_for_file(snapshot, "missing.py")


def test_callable_selection_requires_exact_name_and_disambiguates_by_start_line() -> None:
    file = select_file(report(), "pkg/app.py")
    assert select_callable(file, "duplicate", line=3) is file.functions[1]
    with pytest.raises(SelectionError, match=r"[Aa]mbigu"):
        select_callable(file, "duplicate")
    with pytest.raises(SelectionError):
        select_callable(file, "duplicate", line=4)
    with pytest.raises(SelectionError):
        select_callable(file, "duplic")


def test_unique_callable_name_needs_no_line_selector() -> None:
    file = select_file(report(), "pkg/app.py")
    unique = file.model_copy(update={"functions": (file.functions[0],)})
    assert select_callable(unique, "duplicate") is unique.functions[0]


def test_callables_do_not_exist_in_a_file_without_function_evidence() -> None:
    with pytest.raises(SelectionError):
        select_callable(select_file(report(), "pkg/other.py"), "missing")
