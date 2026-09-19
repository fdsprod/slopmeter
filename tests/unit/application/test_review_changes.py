"""Stale explanations are derived evidence, not claims trusted from imported JSON."""

from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_clone_reviews import analyze, clone_root as shared_clone_root, record

from slop_measure.application.reviews import apply_reviews
from slop_measure.domain.reports import AnalysisReport
from slop_measure.reporting.terminal import render_snapshot

clone_root = shared_clone_root


def stale_payload(root: Path) -> tuple[dict, dict]:
    report = analyze(root)
    store = record(root.parent / "reviews.json", report)
    source = root / "a.py"
    source.write_bytes(source.read_bytes().replace(b"# note", b"# revised note"))
    annotated = apply_reviews(analyze(root), store)
    payload = annotated.model_dump(mode="json")
    return payload, payload["review_results"][0]


def test_comment_only_change_reports_exact_old_and_new_hash_and_source_path(
    clone_root: Path,
) -> None:
    payload, result = stale_payload(clone_root)
    assert result["state"] == "stale"
    assert len(result["changes"]) == 1
    change = result["changes"][0]
    assert change["group_id"] == result["candidate_group_ids"][0]
    previous = next(
        item["sha256"]
        for item in result["decision"]["anchor"]["source_hashes"]
        if item["path"] == "a.py"
    )
    current = next(
        file["source_sha256"]
        for file in payload["cohorts"][0]["current"]["files"]
        if file["evidence"]["path"] == "a.py"
    )
    assert change["causes"] == [
        {
            "kind": "source-changed",
            "path": "a.py",
            "previous_sha256": previous,
            "current_sha256": current,
        }
    ]
    assert previous != current
    restored = AnalysisReport.model_validate(payload)
    assert AnalysisReport.model_validate_json(restored.model_dump_json()) == restored
    output = (
        render_snapshot(restored, width=180, ascii=True, color=False)
        .split("How to read this report", 1)[0]
        .lower()
    )
    assert "source changed" in output and "a.py" in output


def test_missing_current_hash_explains_unavailable_source_without_inventing_a_hash(
    clone_root: Path,
) -> None:
    report = analyze(clone_root)
    store = record(clone_root.parent / "reviews.json", report)
    payload = report.model_dump(mode="json")
    file = next(
        file
        for file in payload["cohorts"][0]["current"]["files"]
        if file["evidence"]["path"] == "a.py"
    )
    file.pop("source_sha256")
    annotated = apply_reviews(AnalysisReport.model_validate(payload), store)
    result = annotated.model_dump(mode="json")["review_results"][0]
    assert result["state"] == "stale"
    assert result["changes"][0]["causes"] == [{"kind": "source-unavailable", "path": "a.py"}]
    output = render_snapshot(annotated, width=180, ascii=True, color=False).lower()
    assert any(
        "source" in line and "unavailable" in line and "a.py" in line
        for line in output.splitlines()
    )


@pytest.mark.parametrize("kind", ["boundary-policy-changed", "analysis-definition-changed"])
def test_policy_and_analysis_causes_name_only_the_changed_fingerprint(
    clone_root: Path, kind: str
) -> None:
    original = (
        {"boundaries": ({"name": "one", "prefix": "a.py"},)}
        if kind == "boundary-policy-changed"
        else {}
    )
    updated = (
        {"boundaries": ({"name": "two", "prefix": "a.py"},)} if original else {"clone_min_sloc": 1}
    )
    report = analyze(clone_root, **original)
    store = record(clone_root.parent / "reviews.json", report)
    changed = analyze(clone_root, **updated)
    annotated = apply_reviews(changed, store)
    result = annotated.model_dump(mode="json")["review_results"][0]
    causes = result["changes"][0]["causes"]
    assert len(causes) == 1 and causes[0]["kind"] == kind
    anchor_key = "policy_fingerprint" if original else "analysis_fingerprint"
    assert causes[0]["previous_fingerprint"] == getattr(store.decisions[0].anchor, anchor_key)
    assert causes[0]["current_fingerprint"] != causes[0]["previous_fingerprint"]
    assert len(causes[0]["current_fingerprint"]) == 64
    output = (
        render_snapshot(annotated, width=180, ascii=True, color=False)
        .split("How to read this report", 1)[0]
        .lower()
    )
    assert ("boundary policy changed" if original else "analysis definition changed") in output
    assert "declaration" not in output


def test_moved_clone_spans_name_changed_members_alongside_source_change(clone_root: Path) -> None:
    report = analyze(clone_root)
    store = record(clone_root.parent / "reviews.json", report)
    target = clone_root / "a.py"
    target.write_bytes(b"# leading comment\n" + target.read_bytes())
    changed = analyze(clone_root)
    assert changed.clone_groups[0].detail.fingerprint == report.clone_groups[0].detail.fingerprint
    annotated = apply_reviews(changed, store)
    result = annotated.model_dump(mode="json")["review_results"][0]
    causes = result["changes"][0]["causes"]
    clone_cause = next(cause for cause in causes if cause["kind"] == "clone-evidence-changed")
    assert clone_cause == {"kind": "clone-evidence-changed", "fields": ["members"]}
    assert {cause["kind"] for cause in causes} == {"source-changed", "clone-evidence-changed"}
    output = render_snapshot(annotated, width=180, ascii=True, color=False).lower()
    assert "clone evidence changed" in output and "members" in output


def test_unavailable_analysis_definition_has_explicit_cause(clone_root: Path) -> None:
    report = analyze(clone_root)
    store = record(clone_root.parent / "reviews.json", report)
    payload = report.model_dump(mode="json")
    payload["provenance"]["metrics"] = [
        metric
        for metric in payload["provenance"]["metrics"]
        if metric["metric_id"] != "m3.clone-verbosity"
    ]
    annotated = apply_reviews(AnalysisReport.model_validate(payload), store)
    result = annotated.model_dump(mode="json")["review_results"][0]
    assert result["state"] == "stale"
    assert result["changes"][0]["causes"] == [{"kind": "analysis-unavailable"}]
    output = render_snapshot(annotated, width=180, ascii=True, color=False).lower()
    assert any("analysis" in line and "unavailable" in line for line in output.splitlines())


def test_legacy_stale_report_without_explanations_loads_and_omits_empty_projection(
    clone_root: Path,
) -> None:
    payload, result = stale_payload(clone_root)
    result.pop("changes", None)
    restored = AnalysisReport.model_validate(payload)
    review = restored.review_results[0]
    assert review.state == "stale"
    assert review.changes == ()
    assert "changes" not in restored.model_dump(mode="json")["review_results"][0]
    output = render_snapshot(restored, width=180, ascii=True, color=False)
    assert "Change details were not recorded in this report." in output


@pytest.mark.parametrize(
    "tamper",
    [
        "path",
        "previous-hash",
        "current-hash",
        "kind",
        "group-id",
        "empty-causes",
        "duplicate-group",
        "extra-cause",
    ],
)
def test_imported_stale_explanations_cannot_forge_or_omit_owned_causes(
    clone_root: Path, tamper: str
) -> None:
    payload, result = stale_payload(clone_root)
    change = result["changes"][0]
    cause = change["causes"][0]
    if tamper == "path":
        cause["path"] = "b.py"
    elif tamper == "previous-hash":
        cause["previous_sha256"] = "0" * 64
    elif tamper == "current-hash":
        cause["current_sha256"] = "0" * 64
    elif tamper == "kind":
        change["causes"] = [{"kind": "analysis-unavailable"}]
    elif tamper == "group-id":
        change["group_id"] = "unknown"
    elif tamper == "empty-causes":
        change["causes"] = []
    elif tamper == "duplicate-group":
        result["changes"].append(deepcopy(change))
    else:
        change["causes"].append(
            {
                "kind": "boundary-policy-changed",
                "previous_fingerprint": "0" * 64,
                "current_fingerprint": "1" * 64,
            }
        )
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)


def test_imported_populated_changes_must_include_all_derived_causes(clone_root: Path) -> None:
    report = analyze(clone_root)
    store = record(clone_root.parent / "reviews.json", report)
    target = clone_root / "a.py"
    target.write_bytes(b"# leading comment\n" + target.read_bytes())
    payload = apply_reviews(analyze(clone_root), store).model_dump(mode="json")
    change = payload["review_results"][0]["changes"][0]
    assert len(change["causes"]) >= 2
    change["causes"].pop()
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)


@pytest.mark.parametrize("state", ["current", "missing"])
def test_nonstale_review_rejects_changes_projection(clone_root: Path, state: str) -> None:
    report = analyze(clone_root)
    store = record(clone_root.parent / "reviews.json", report)
    if state == "missing":
        (clone_root / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
        report = analyze(clone_root)
    payload = apply_reviews(report, store).model_dump(mode="json")
    result = payload["review_results"][0]
    assert result["state"] == state and "changes" not in result
    result["changes"] = [{"group_id": "invented", "causes": [{"kind": "analysis-unavailable"}]}]
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)
