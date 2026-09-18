"""Aggregation keeps clone identity stable and isolates analysis-family failures."""

from pathlib import Path

import pytest

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import LanguageEvidence
from slop_measure.domain.inventory import SourceInventory
from slop_measure.domain.source import DirectorySourceIdentity
from slop_measure.metrics.aggregate import aggregate_snapshot
from slop_measure.reporting.json import serialize_report


def payload() -> dict:
    files = [
        dict(
            path=f"{prefix}/{name}.other",
            language="other",
            cohort=cohort,
            parse_state="parsed",
            sloc=3,
            sloc_lines=(1, 2, 3),
        )
        for prefix, cohort in (("src", "production"), ("tests", "test"))
        for name in ("a", "b")
    ]
    return dict(
        language="other",
        capabilities=["files", "patterns", "clones"],
        files=files,
        pattern_analyses=[dict(state="analyzed", path=file["path"]) for file in files],
        clone_analyses=[
            dict(
                state="analyzed",
                path=file["path"],
                candidates=[
                    dict(
                        path=file["path"],
                        span=dict(start_line=2, end_line=3),
                        statement_count=2,
                        sloc_lines=(2, 3),
                        normalization_version="other-clones-1",
                        normalized_tokens=("assign", "local:0", "literal:1", "return", "local:0"),
                    )
                ],
            )
            for file in files
        ],
    )


def aggregate(root: Path, data: dict):
    return aggregate_snapshot(
        DirectorySourceIdentity(root=root),
        SourceInventory(),
        (LanguageEvidence.model_validate(data),),
        AnalysisConfig(),
    )


def metrics(result):
    return {metric.metric_id: metric.model_dump(mode="json") for metric in result.metrics}


def test_group_ids_are_stable_under_input_order_and_distinct_between_cohorts(
    tmp_path: Path,
) -> None:
    data = payload()
    forward = aggregate(tmp_path, data)
    for key in ("files", "pattern_analyses", "clone_analyses"):
        data[key].reverse()
    reverse = aggregate(tmp_path, data)
    assert len(forward.clone_groups) == 2
    assert len({group.id for group in forward.clone_groups}) == 2
    assert len({group.detail.fingerprint for group in forward.clone_groups}) == 1
    assert serialize_report(forward) == serialize_report(reverse)


def test_pattern_failure_invalidates_combined_but_preserves_clone_groups(tmp_path: Path) -> None:
    data = payload()
    data["pattern_analyses"][0] = dict(
        state="failed",
        path="src/a.other",
        diagnostic=dict(
            severity="error",
            code="other.pattern-error",
            message="Pattern analysis failed.",
            path="src/a.other",
        ),
    )
    report = aggregate(tmp_path, data)
    production = next(
        cohort.current for cohort in report.cohorts if cohort.cohort.value == "production"
    )
    assert len(report.diagnostics) == 1
    assert len(report.clone_groups) == 2
    for result in (production, production.files[0]):
        values = metrics(result)
        for metric_id in ("m2.pattern-verbosity", "verbosity.combined"):
            assert values[metric_id]["reason"] == "analyzer-failed"
            assert values[metric_id]["diagnostic_id"] == report.diagnostics[0].id
        assert values["m3.clone-verbosity"]["state"] == "measured"
        assert values["m3.clone-verbosity"]["raw"]["value"] == 2 / 3
    assert metrics(production.files[1])["verbosity.combined"]["raw"]["value"] == 2 / 3
    tests = next(cohort.current for cohort in report.cohorts if cohort.cohort.value == "test")
    assert metrics(tests)["verbosity.combined"]["raw"]["value"] == 2 / 3


@pytest.mark.parametrize("missing", ["patterns", "clones", "both"])
def test_combined_requires_both_capabilities(tmp_path: Path, missing: str) -> None:
    data = payload()
    for capability, field in (("patterns", "pattern_analyses"), ("clones", "clone_analyses")):
        if missing in (capability, "both"):
            data["capabilities"].remove(capability)
            data[field] = []
    report = aggregate(tmp_path, data)
    for cohort in report.cohorts:
        for result in (cohort.current, *cohort.current.files):
            combined = metrics(result)["verbosity.combined"]
            assert combined["state"] == "unavailable"
            assert combined["reason"] == "unsupported-capability"
