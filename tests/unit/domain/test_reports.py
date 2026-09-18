"""Contracts for immutable report envelopes and source-specific evidence links."""

from copy import deepcopy

import pytest
from pydantic import TypeAdapter, ValidationError

from slop_measure.domain.reports import (
    Analysis,
    AnalysisReport,
    AnalyzerVersion,
    CohortReport,
    CohortResult,
    ComparisonAnalysis,
    ComparisonCohortReport,
    FileResult,
    MeasuredSnapshotScore,
    MetricVersion,
    Provenance,
    ReportCoverage,
    ReportDiagnostic,
    ScoreUnavailableReason,
    SnapshotAnalysis,
    SnapshotCohortReport,
    SnapshotScore,
    SourceSide,
    UnavailableSnapshotScore,
)


def measured_score(points: float = 1) -> dict:
    return {
        "points": points,
        "profile_id": "py-2026.1",
        "model_id": "verbosity-only",
        "band": "low",
        "contributions": [
            {
                "metric_id": "verbosity.combined",
                "raw_value": 0.1,
                "percentile": points,
                "weight": 1,
                "points": points,
            }
        ],
    }


def score() -> dict[str, object]:
    return {"state": "unavailable", "reason": "calibration-missing"}


def metric(*, path: str | None = None, diagnostic_id: str | None = None) -> dict[str, object]:
    scope: dict[str, object] = {"kind": "project", "cohort": "production"}
    if path is not None:
        scope.update(kind="file", path=path)
    return {
        "state": "unavailable",
        "metric_id": "m4.erosion",
        "scope": scope,
        "reason": "parse-failed",
        "diagnostic_id": diagnostic_id,
    }


def file_result(path: str = "src/app.py") -> dict[str, object]:
    return {
        "evidence": {
            "path": path,
            "language": "python",
            "cohort": "production",
            "sloc": 1,
            "sloc_lines": [1],
            "parse_state": "parsed",
        },
        "metrics": [metric(path=path)],
        "score": score(),
    }


def cohort_result() -> dict[str, object]:
    return {"files": [file_result()], "metrics": [metric()], "score": score()}


def report_payload(*, comparison: bool = False) -> dict:
    source = {"kind": "directory", "root": "checkout"}
    analysis = {"kind": "snapshot", "current": source}
    cohort = {
        "kind": "snapshot",
        "language": "python",
        "cohort": "production",
        "current": cohort_result(),
    }
    if comparison:
        analysis.update(kind="comparison", baseline={"kind": "directory", "root": "before"})
        cohort.update(kind="comparison", baseline=cohort_result(), metrics=[metric()])
        for side in ("baseline", "current"):
            cohort[side]["files"][0]["evidence"].update(sloc=0, sloc_lines=[], parse_state="failed")
        cohort["metrics"][0]["metric_id"] = "m1.loc-delta"
        cohort["line_delta"] = {"state": "unavailable", "reason": "parse-failed"}
        cohort["changes"] = [
            {
                "pair": {
                    "kind": "unchanged",
                    "baseline_path": "src/app.py",
                    "current_path": "src/app.py",
                },
                "lines": {"state": "unavailable", "reason": "parse-failed"},
            }
        ]
    return {
        "analysis": analysis,
        "provenance": {"tool_version": "0.1.0", "config": {}},
        "cohorts": [cohort],
        "coverage": [
            {
                "source": "current",
                "detail": {
                    "state": "scored",
                    "cohort": "production",
                    "language": "python",
                    "file_count": 1,
                    "sloc": 1,
                },
            }
        ],
        "diagnostics": [],
    }


def diagnostic(identifier: str = "parse-1", source: str = "current") -> dict:
    return {
        "id": identifier,
        "source": source,
        "detail": {
            "severity": "error",
            "code": "python.parse-error",
            "message": "Source could not be parsed.",
            "path": "src/app.py",
        },
    }


@pytest.mark.parametrize("comparison", [False, True])
def test_report_round_trips_explicit_variants_and_immutable_collections(comparison: bool) -> None:
    report = AnalysisReport.model_validate(report_payload(comparison=comparison))

    assert report.schema_version == "1.0"
    assert isinstance(report.analysis, ComparisonAnalysis if comparison else SnapshotAnalysis)
    assert isinstance(
        report.cohorts[0], ComparisonCohortReport if comparison else SnapshotCohortReport
    )
    assert isinstance(report.cohorts, tuple)
    assert isinstance(report.cohorts[0].current.files, tuple)
    assert isinstance(report.cohorts[0].current.metrics, tuple)
    assert isinstance(report.coverage, tuple)
    assert report.findings == report.clone_groups == report.diagnostics == ()
    assert AnalysisReport.model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize(
    "union,property_name,tags",
    [
        (Analysis, "kind", {"snapshot", "comparison"}),
        (CohortReport, "kind", {"snapshot", "comparison"}),
        (SnapshotScore, "state", {"measured", "unavailable"}),
    ],
)
def test_report_unions_have_explicit_json_discriminators(
    union: object, property_name: str, tags: set[str]
) -> None:
    schema = TypeAdapter(union).json_schema()
    assert schema["discriminator"]["propertyName"] == property_name
    assert set(schema["discriminator"]["mapping"]) == tags


def test_source_sides_and_score_unavailability_reasons_are_closed() -> None:
    assert {side.value for side in SourceSide} == {"current", "baseline"}
    assert {reason.value for reason in ScoreUnavailableReason} == {
        "calibration-missing",
        "calibration-incompatible",
        "no-source-lines",
        "required-metric-unavailable",
    }
    with pytest.raises(ValueError):
        SourceSide("target")
    with pytest.raises(ValueError):
        ScoreUnavailableReason("other")


@pytest.mark.parametrize("points", [-1, 101, float("nan"), float("inf"), float("-inf")])
def test_snapshot_scores_reject_invalid_points(points: float) -> None:
    with pytest.raises(ValidationError):
        MeasuredSnapshotScore.model_validate(measured_score(points))


@pytest.mark.parametrize("points", [0, 100])
def test_snapshot_scores_accept_range_boundaries(points: float) -> None:
    assert MeasuredSnapshotScore.model_validate(measured_score(points)).points == points


def test_unavailable_snapshot_score_cannot_carry_points() -> None:
    with pytest.raises(ValidationError):
        UnavailableSnapshotScore.model_validate({**score(), "points": 0})


@pytest.mark.parametrize(
    "model,payload", [(FileResult, file_result()), (CohortResult, cohort_result())]
)
def test_result_requires_an_explicit_score_state(model: type, payload: dict) -> None:
    values = {key: value for key, value in payload.items() if key != "score"}
    with pytest.raises(ValidationError):
        model.model_validate(values)


def test_snapshot_analysis_forbids_baseline_and_comparison_requires_it() -> None:
    current = {"kind": "directory", "root": "checkout"}
    with pytest.raises(ValidationError):
        SnapshotAnalysis.model_validate({"current": current, "baseline": current})
    with pytest.raises(ValidationError):
        ComparisonAnalysis.model_validate({"current": current})


@pytest.mark.parametrize(
    "field,items",
    [
        ("analyzers", [{"language": "python", "adapter_version": "1"}] * 2),
        ("metrics", [{"metric_id": "m4.erosion", "version": "1"}] * 2),
    ],
)
def test_provenance_rejects_duplicate_version_keys(field: str, items: list) -> None:
    with pytest.raises(ValidationError):
        Provenance.model_validate({"tool_version": "1", "config": {}, field: items})


@pytest.mark.parametrize(
    "model,payload,field",
    [
        (AnalyzerVersion, {"language": "python", "adapter_version": "1"}, "language"),
        (AnalyzerVersion, {"language": "python", "adapter_version": "1"}, "adapter_version"),
        (AnalyzerVersion, {"language": "python", "adapter_version": "1"}, "rule_set_version"),
        (MetricVersion, {"metric_id": "m4.erosion", "version": "1"}, "metric_id"),
        (MetricVersion, {"metric_id": "m4.erosion", "version": "1"}, "version"),
        (Provenance, {"tool_version": "1", "config": {}}, "tool_version"),
        (MeasuredSnapshotScore, measured_score(), "profile_id"),
        (ReportDiagnostic, diagnostic(), "id"),
    ],
)
def test_report_text_is_trimmed_and_nonempty(model: type, payload: dict, field: str) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({**payload, field: "  "})
    value = model.model_validate({**payload, field: " value "})
    assert getattr(value, field) == "value"


@pytest.mark.parametrize("change", ["project-scope", "path", "cohort", "duplicate"])
def test_file_result_rejects_inconsistent_metric_ownership(change: str) -> None:
    payload = file_result()
    values = [metric(path="src/app.py")]
    if change == "project-scope":
        values = [metric()]
    elif change == "path":
        values = [metric(path="other.py")]
    elif change == "cohort":
        values[0]["scope"] = {"kind": "file", "path": "src/app.py", "cohort": "test"}
    else:
        values *= 2
    payload["metrics"] = values
    with pytest.raises(ValidationError):
        FileResult.model_validate(payload)


@pytest.mark.parametrize("change", ["duplicate-files", "duplicate-metrics", "file-scope"])
def test_cohort_result_rejects_duplicate_or_misplaced_evidence(change: str) -> None:
    payload = cohort_result()
    if change == "duplicate-files":
        payload["files"] = [file_result(), file_result()]
    elif change == "duplicate-metrics":
        payload["metrics"] = [metric(), metric()]
    else:
        payload["metrics"] = [metric(path="src/app.py")]
    with pytest.raises(ValidationError):
        CohortResult.model_validate(payload)


@pytest.mark.parametrize("field,value", [("language", "typescript"), ("cohort", "test")])
def test_cohort_report_checks_nested_file_ownership(field: str, value: str) -> None:
    payload = report_payload()
    payload["cohorts"][0][field] = value
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)


@pytest.mark.parametrize("side", ["current", "baseline"])
def test_comparison_cohort_checks_each_project_metric_cohort(side: str) -> None:
    payload = report_payload(comparison=True)
    payload["cohorts"][0][side]["metrics"][0]["scope"]["cohort"] = "test"
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)


@pytest.mark.parametrize("change", ["file-scope", "cohort", "duplicate"])
def test_comparison_metrics_use_unique_project_scopes_owned_by_cohort(change: str) -> None:
    payload = report_payload(comparison=True)
    values = payload["cohorts"][0]["metrics"]
    if change == "file-scope":
        values[0] = metric(path="src/app.py")
    elif change == "cohort":
        values[0]["scope"]["cohort"] = "test"
    else:
        values.append(deepcopy(values[0]))
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)


@pytest.mark.parametrize(
    "change",
    [
        "kind",
        "duplicate-cohort",
        "duplicate-diagnostic",
        "duplicate-coverage",
        "schema",
        "findings",
        "clone_groups",
    ],
)
def test_report_rejects_inconsistent_envelope_members(change: str) -> None:
    payload = report_payload()
    if change == "kind":
        payload["cohorts"] = report_payload(comparison=True)["cohorts"]
    elif change == "duplicate-cohort":
        payload["cohorts"] *= 2
    elif change == "duplicate-diagnostic":
        payload["diagnostics"] = [diagnostic(), diagnostic()]
    elif change == "duplicate-coverage":
        payload["coverage"] *= 2
    elif change == "schema":
        payload["schema_version"] = "2.0"
    else:
        payload[change] = [object()]
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)


@pytest.mark.parametrize("collection", ["coverage", "diagnostics"])
def test_snapshot_forbids_baseline_metadata(collection: str) -> None:
    payload = report_payload()
    if collection == "diagnostics":
        payload[collection] = [diagnostic(source="baseline")]
    else:
        payload[collection][0]["source"] = "baseline"
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)


def test_comparison_keeps_identical_coverage_for_distinct_source_sides() -> None:
    payload = report_payload(comparison=True)
    baseline_coverage = deepcopy(payload["coverage"][0])
    baseline_coverage["source"] = "baseline"
    payload["coverage"].append(baseline_coverage)
    report = AnalysisReport.model_validate(payload)
    assert {coverage.source for coverage in report.coverage} == {
        SourceSide.CURRENT,
        SourceSide.BASELINE,
    }


def test_diagnostic_and_coverage_default_to_current_source() -> None:
    diagnostic_payload = diagnostic()
    del diagnostic_payload["source"]
    coverage_payload = report_payload()["coverage"][0]
    del coverage_payload["source"]
    assert ReportDiagnostic.model_validate(diagnostic_payload).source is SourceSide.CURRENT
    assert ReportCoverage.model_validate(coverage_payload).source is SourceSide.CURRENT


@pytest.mark.parametrize(
    "location,failure",
    [
        ("file", "missing"),
        ("file", "wrong-side"),
        ("project", "missing"),
        ("project", "wrong-side"),
        ("comparison", "missing"),
    ],
)
def test_metric_diagnostic_references_require_valid_ownership(location: str, failure: str) -> None:
    payload = report_payload(comparison=True)
    cohort = payload["cohorts"][0]
    target = (
        cohort["current"]["files"][0]["metrics"][0]
        if location == "file"
        else cohort["current"]["metrics"][0]
        if location == "project"
        else cohort["metrics"][0]
    )
    target["diagnostic_id"] = "parse-1"
    payload["diagnostics"] = [] if failure == "missing" else [diagnostic(source="baseline")]
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)
    payload["diagnostics"] = [diagnostic()]
    assert AnalysisReport.model_validate(payload).diagnostics[0].id == "parse-1"


@pytest.mark.parametrize("source", ["current", "baseline"])
def test_comparison_metric_can_reference_either_source_diagnostic(source: str) -> None:
    payload = report_payload(comparison=True)
    payload["cohorts"][0]["metrics"][0]["diagnostic_id"] = "parse-1"
    payload["diagnostics"] = [diagnostic(source=source)]

    report = AnalysisReport.model_validate(payload)

    assert report.diagnostics[0].source is SourceSide(source)


def test_baseline_file_diagnostic_links_to_baseline_and_checks_path() -> None:
    payload = report_payload(comparison=True)
    payload["cohorts"][0]["baseline"]["files"][0]["metrics"][0]["diagnostic_id"] = "parse-1"
    payload["diagnostics"] = [diagnostic(source="baseline")]
    assert AnalysisReport.model_validate(payload).diagnostics[0].source is SourceSide.BASELINE
    payload["diagnostics"][0]["detail"]["path"] = "other.py"
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)


def test_same_source_file_path_cannot_belong_to_two_cohorts() -> None:
    payload = report_payload()
    second = deepcopy(payload["cohorts"][0])
    second["language"] = "typescript"
    second["current"]["files"][0]["evidence"]["language"] = "typescript"
    payload["cohorts"].append(second)
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)


@pytest.mark.parametrize(
    "model,payload",
    [
        (SnapshotAnalysis, {"current": {"kind": "directory", "root": "."}}),
        (
            ComparisonAnalysis,
            {
                "baseline": {"kind": "directory", "root": "a"},
                "current": {"kind": "directory", "root": "b"},
            },
        ),
        (AnalyzerVersion, {"language": "python", "adapter_version": "1"}),
        (MetricVersion, {"metric_id": "m4.erosion", "version": "1"}),
        (Provenance, {"tool_version": "1", "config": {}}),
        (MeasuredSnapshotScore, measured_score()),
        (UnavailableSnapshotScore, score()),
        (FileResult, file_result()),
        (CohortResult, cohort_result()),
        (SnapshotCohortReport, report_payload()["cohorts"][0]),
        (ComparisonCohortReport, report_payload(comparison=True)["cohorts"][0]),
        (ReportCoverage, report_payload()["coverage"][0]),
        (ReportDiagnostic, diagnostic()),
        (AnalysisReport, report_payload()),
    ],
)
def test_report_models_are_frozen_and_forbid_extra_fields(model: type, payload: dict) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({**payload, "unexpected": True})
    value = model.model_validate(payload)
    field = next(iter(payload))
    with pytest.raises(ValidationError):
        setattr(value, field, payload[field])
