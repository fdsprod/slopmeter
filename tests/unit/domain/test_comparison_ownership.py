"""Comparison envelopes reconcile exact file ownership with project totals."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from slop_measure.domain.reports import AnalysisReport


def result(sloc: int, value: float) -> dict:
    score = {"state": "unavailable", "reason": "calibration-missing"}
    metric = {
        "metric_id": "verbosity.combined",
        "state": "measured",
        "scope": {"kind": "project", "cohort": "production"},
        "raw": {"numerator": value * 100, "denominator": 100, "value": value, "unit": "ratio"},
    }
    file_metric = deepcopy(metric)
    file_metric["scope"].update(kind="file", path="a.py")
    return {
        "score": score,
        "metrics": [metric],
        "files": [
            {
                "evidence": {
                    "path": "a.py",
                    "language": "python",
                    "cohort": "production",
                    "sloc": sloc,
                    "sloc_lines": list(range(1, sloc + 1)),
                    "parse_state": "parsed",
                },
                "score": score,
                "metrics": [file_metric],
            }
        ],
    }


def payload() -> dict:
    delta = {"state": "measured", "metric_id": "verbosity.combined", "value": 0.25, "unit": "ratio"}
    return {
        "analysis": {
            "kind": "comparison",
            "baseline": {"kind": "directory", "root": "before"},
            "current": {"kind": "directory", "root": "after"},
        },
        "provenance": {"tool_version": "test", "config": {}},
        "cohorts": [
            {
                "kind": "comparison",
                "language": "python",
                "cohort": "production",
                "baseline": result(2, 0.25),
                "current": result(3, 0.5),
                "line_delta": {
                    "state": "measured",
                    "baseline_sloc": 2,
                    "current_sloc": 3,
                    "added": 1,
                    "deleted": 0,
                },
                "metrics": [
                    {
                        "state": "measured",
                        "metric_id": "m1.loc-delta",
                        "scope": {"kind": "project", "cohort": "production"},
                        "raw": {"numerator": 1, "denominator": 0, "value": 1, "unit": "lines"},
                    }
                ],
                "deltas": [delta],
                "changes": [
                    {
                        "pair": {
                            "kind": "modified",
                            "baseline_path": "a.py",
                            "current_path": "a.py",
                        },
                        "lines": {
                            "state": "measured",
                            "baseline_sloc": 2,
                            "current_sloc": 3,
                            "added_lines": [3],
                            "deleted_lines": [],
                        },
                        "deltas": [delta],
                    }
                ],
            }
        ],
    }


def test_comparison_roundtrip_keeps_complete_owned_sides_and_growth() -> None:
    report = AnalysisReport.model_validate(payload())
    assert AnalysisReport.model_validate_json(report.model_dump_json()) == report
    cohort = report.cohorts[0]
    assert cohort.kind == "comparison"
    assert cohort.line_delta.state == "measured"
    assert cohort.line_delta.net == 1
    assert cohort.line_delta.growth.state == "measured"
    assert cohort.line_delta.growth.value == 0.5


@pytest.mark.parametrize(
    "problem",
    [
        "missing-pair",
        "duplicate-pair",
        "unknown-path",
        "wrong-line",
        "wrong-file-total",
        "wrong-project-total",
        "wrong-m1",
        "wrong-file-delta",
        "wrong-project-delta",
    ],
)
def test_comparison_rejects_unowned_or_unreconciled_projection(problem: str) -> None:
    value = payload()
    cohort = value["cohorts"][0]
    change = cohort["changes"][0]
    if problem == "missing-pair":
        cohort["changes"] = []
    elif problem == "duplicate-pair":
        cohort["changes"].append(deepcopy(change))
    elif problem == "unknown-path":
        change["pair"].update(baseline_path="unknown.py", current_path="unknown.py")
    elif problem == "wrong-line":
        change["lines"]["added_lines"] = [99]
    elif problem == "wrong-file-total":
        change["lines"].update(baseline_sloc=3, current_sloc=4)
    elif problem == "wrong-project-total":
        cohort["line_delta"].update(baseline_sloc=3, current_sloc=4)
    elif problem == "wrong-m1":
        cohort["metrics"][0]["raw"].update(numerator=2, value=2)
    elif problem == "wrong-file-delta":
        change["deltas"] = [{**change["deltas"][0], "value": 0.1}]
    else:
        cohort["deltas"] = [{**cohort["deltas"][0], "value": 0.1}]
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(value)
