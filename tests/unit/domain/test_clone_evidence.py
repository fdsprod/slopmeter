"""Owned clone outcomes, checked fingerprints, and source-specific group evidence."""

import pytest
from pydantic import TypeAdapter, ValidationError

from slop_measure.domain.evidence import (
    AnalyzedClones,
    CloneAnalysis,
    CloneCandidate,
    CloneGroup,
    CloneMember,
    FailedClones,
    LanguageEvidence,
)
from slop_measure.domain.reports import AnalysisReport, ReportCloneGroup, SourceSide


def candidate_payload(path: str = "a.py") -> dict:
    return {
        "path": path,
        "span": {"start_line": 2, "end_line": 5},
        "statement_count": 2,
        "sloc_lines": (2, 4, 5),
        "normalization_version": "py-clones-1",
        "normalized_tokens": ("assignment", "local:0", "integer:1", "return", "local:0"),
    }


def file_payload(path: str = "a.py") -> dict:
    return {
        "path": path,
        "language": "python",
        "cohort": "production",
        "parse_state": "parsed",
        "sloc": 4,
        "sloc_lines": (1, 2, 4, 5),
    }


def group_payload() -> dict:
    candidate = CloneCandidate.model_validate(candidate_payload())
    return {
        "language": "python",
        "cohort": "production",
        "normalization_version": "py-clones-1",
        "fingerprint": candidate.fingerprint,
        "members": [
            {"path": path, "span": {"start_line": 2, "end_line": 5}, "sloc_lines": (2, 4, 5)}
            for path in ("a.py", "b.py")
        ],
    }


def language_payload() -> dict:
    return {
        "language": "python",
        "capabilities": ["files", "clones"],
        "files": [file_payload()],
        "clone_analyses": [
            {"state": "analyzed", "path": "a.py", "candidates": [candidate_payload()]}
        ],
    }


def report_payload() -> dict:
    score = {"state": "unavailable", "reason": "required-metric-unavailable"}
    return {
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
                        {"evidence": file_payload(path), "score": score}
                        for path in ("a.py", "b.py")
                    ],
                },
            }
        ],
        "clone_groups": [{"id": "clone-0001", "detail": group_payload()}],
    }


def test_candidate_fingerprint_is_stable_checked_projection_with_json_round_trip() -> None:
    candidate = CloneCandidate.model_validate(candidate_payload())
    assert len(candidate.fingerprint) == 64
    int(candidate.fingerprint, 16)
    assert candidate.normalized_tokens == candidate_payload()["normalized_tokens"]
    assert CloneCandidate.model_validate_json(candidate.model_dump_json()) == candidate
    renamed_path = CloneCandidate.model_validate(candidate_payload("other.py"))
    assert renamed_path.fingerprint == candidate.fingerprint
    changed_version = CloneCandidate.model_validate(
        {**candidate_payload(), "normalization_version": "next"}
    )
    assert changed_version.fingerprint != candidate.fingerprint
    changed_tokens = CloneCandidate.model_validate(
        {**candidate_payload(), "normalized_tokens": ("different",)}
    )
    assert changed_tokens.fingerprint != candidate.fingerprint
    with pytest.raises(ValidationError):
        CloneCandidate.model_validate({**candidate_payload(), "fingerprint": "0" * 64})
    with pytest.raises(ValidationError):
        candidate.statement_count = 9


@pytest.mark.parametrize(
    "field,value",
    [
        ("statement_count", 0),
        ("statement_count", True),
        ("statement_count", 1.5),
        ("sloc_lines", ()),
        ("sloc_lines", (0, 2)),
        ("sloc_lines", (2, 2)),
        ("sloc_lines", (5, 2)),
        ("sloc_lines", (2, 6)),
        ("normalized_tokens", ()),
        ("normalized_tokens", (object(),)),
        ("normalization_version", " "),
        ("node", object()),
    ],
)
def test_candidate_rejects_invalid_evidence(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        CloneCandidate.model_validate({**candidate_payload(), field: value})


def test_candidate_allows_one_statement_for_explicit_lower_threshold() -> None:
    assert (
        CloneCandidate.model_validate({**candidate_payload(), "statement_count": 1}).statement_count
        == 1
    )


def test_clone_outcome_union_preserves_empty_success() -> None:
    adapter = TypeAdapter(CloneAnalysis)
    result = adapter.validate_python({"state": "analyzed", "path": "a.py"})
    assert isinstance(result, AnalyzedClones)
    assert result.candidates == ()
    assert adapter.json_schema()["discriminator"]["propertyName"] == "state"
    assert set(adapter.json_schema()["discriminator"]["mapping"]) == {"analyzed", "failed"}


@pytest.mark.parametrize("severity,path", [("warning", "a.py"), ("error", "b.py"), ("error", None)])
def test_failed_clones_require_same_file_error(severity: str, path: str | None) -> None:
    with pytest.raises(ValidationError):
        FailedClones.model_validate(
            {
                "path": "a.py",
                "diagnostic": {
                    "severity": severity,
                    "path": path,
                    "code": "clone.failed",
                    "message": "Failed.",
                },
            }
        )


def test_language_clone_candidates_are_read_only_canonical_outcome_projection() -> None:
    evidence = LanguageEvidence.model_validate(language_payload())
    assert isinstance(evidence.clone_analyses, tuple)
    outcome = evidence.clone_analyses[0]
    assert isinstance(outcome, AnalyzedClones)
    assert evidence.clone_candidates == outcome.candidates
    assert "clone_candidates" not in evidence.model_dump(mode="json")
    assert "clone_analyses" in evidence.model_dump(mode="json")
    assert LanguageEvidence.model_validate_json(evidence.model_dump_json()) == evidence
    with pytest.raises((ValidationError, AttributeError)):
        evidence.clone_candidates = ()  # type: ignore[reportAttributeAccessIssue]


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "unknown-path",
        "candidate-path",
        "wrong-lines",
        "no-capability",
        "failed-file",
    ],
)
def test_clone_outcomes_reconcile_with_parsed_file_ownership(change: str) -> None:
    payload = language_payload()
    if change == "missing":
        payload["clone_analyses"] = []
    elif change == "duplicate":
        payload["clone_analyses"] *= 2
    elif change == "unknown-path":
        payload["clone_analyses"].append({"state": "analyzed", "path": "other.py"})
    elif change == "candidate-path":
        payload["clone_analyses"][0]["candidates"][0]["path"] = "other.py"
    elif change == "wrong-lines":
        payload["clone_analyses"][0]["candidates"][0]["sloc_lines"] = (2, 5)
    elif change == "no-capability":
        payload["capabilities"] = ["files"]
    else:
        payload["files"][0].update(parse_state="failed", sloc=0, sloc_lines=())
    with pytest.raises(ValidationError):
        LanguageEvidence.model_validate(payload)


def test_failed_parse_file_has_no_clone_outcome() -> None:
    payload = language_payload()
    payload["files"][0].update(parse_state="failed", sloc=0, sloc_lines=())
    payload["clone_analyses"] = []
    assert LanguageEvidence.model_validate(payload).clone_analyses == ()


@pytest.mark.parametrize(
    "change", ["one-member", "duplicate-member", "overlap-only", "fingerprint", "lines"]
)
def test_clone_group_requires_real_distinct_instances(change: str) -> None:
    payload = group_payload()
    if change == "one-member":
        payload["members"] = payload["members"][:1]
    elif change == "duplicate-member":
        payload["members"] = [payload["members"][0]] * 2
    elif change == "overlap-only":
        payload["members"][1] = {
            "path": "a.py",
            "span": {"start_line": 4, "end_line": 7},
            "sloc_lines": (4, 5, 7),
        }
    elif change == "fingerprint":
        payload["fingerprint"] = "bad"
    else:
        payload["members"][0]["sloc_lines"] = (2, 6)
    with pytest.raises(ValidationError):
        CloneGroup.model_validate(payload)


def test_group_members_and_report_wrapper_are_immutable_owned_records() -> None:
    group = CloneGroup.model_validate(group_payload())
    assert isinstance(group.members, tuple)
    assert isinstance(group.members[0], CloneMember)
    assert CloneGroup.model_validate_json(group.model_dump_json()) == group
    wrapped = ReportCloneGroup(id="clone-1", detail=group)
    assert wrapped.source is SourceSide.CURRENT
    with pytest.raises(ValidationError):
        wrapped.id = "changed"
    with pytest.raises(ValidationError):
        CloneMember.model_validate({**group_payload()["members"][0], "node": object()})


def test_report_groups_round_trip_with_owned_source_members() -> None:
    report = AnalysisReport.model_validate(report_payload())
    assert len(report.clone_groups) == 1
    assert AnalysisReport.model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize(
    "change",
    [
        "duplicate-id",
        "baseline",
        "unknown-path",
        "language",
        "cohort",
        "wrong-lines",
        "failed-file",
    ],
)
def test_report_clone_groups_validate_source_population_and_exact_sloc(change: str) -> None:
    payload = report_payload()
    group = payload["clone_groups"][0]
    if change == "duplicate-id":
        payload["clone_groups"] *= 2
    elif change == "baseline":
        group["source"] = "baseline"
    elif change == "unknown-path":
        group["detail"]["members"][0]["path"] = "unknown.py"
    elif change in {"language", "cohort"}:
        group["detail"][change] = "other" if change == "language" else "test"
    elif change == "wrong-lines":
        group["detail"]["members"][0]["sloc_lines"] = (2, 5)
    else:
        payload["cohorts"][0]["current"]["files"][0]["evidence"].update(
            parse_state="failed", sloc=0, sloc_lines=()
        )
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)
