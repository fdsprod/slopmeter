"""Persisted decisions annotate exact clone evidence and never erase measurements."""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.application.reviews import apply_reviews, load_review_store, write_clone_review
from slop_measure.domain.reports import AnalysisReport
from slop_measure.domain.reviews import ReviewDisposition, ReviewStore
from slop_measure.errors import InputError


@pytest.fixture
def clone_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    (root / "a.py").write_bytes(
        b"def first(source):\r\n    value = source + 1\r\n    return value\r\n# note\r\n"
    )
    (root / "b.py").write_bytes(
        b"def second(payload):\n    result = payload + 1\n    return result\n"
    )
    return root


def analyze(root: Path, **options: object) -> AnalysisReport:
    return scan(
        SnapshotRequest(
            target=DirectorySourceReference(root=root),
            config=AnalysisConfig.model_validate(
                {
                    "calibration_profile": "__raw__",
                    "clone_min_sloc": 2,
                    **options,
                }
            ),
        )
    )


def record(store_path: Path, report: AnalysisReport) -> ReviewStore:
    assert len(report.clone_groups) == 1
    return write_clone_review(
        store_path,
        report,
        report.clone_groups[0].id,
        disposition=ReviewDisposition.NO_CHANGE,
        reason="The two copies change under separate contracts.",
        next_step="Recheck when either contract changes.",
    )


def facts(report: AnalysisReport) -> dict:
    return report.model_dump(mode="json", exclude={"review_results"})


def test_fresh_source_hashes_cover_exact_bytes_and_legacy_unknown_hash_is_omitted(
    clone_root: Path,
) -> None:
    report = analyze(clone_root)
    for file in report.cohorts[0].current.files:
        expected = hashlib.sha256((clone_root / file.evidence.path.root).read_bytes()).hexdigest()
        assert file.source_sha256 == expected
        payload = file.model_dump(mode="json")
        payload.pop("source_sha256")
        legacy = type(file).model_validate(payload)
        assert legacy.source_sha256 is None
        assert "source_sha256" not in legacy.model_dump(mode="json")
        with pytest.raises(ValidationError):
            type(file).model_validate({**payload, "source_sha256": "not-a-hash"})


def test_roundtrip_current_annotation_is_frozen_complete_and_does_not_change_raw_facts(
    clone_root: Path,
) -> None:
    report = analyze(clone_root)
    before = report.model_dump_json()
    path = clone_root.parent / "reviews.json"
    store = record(path, report)
    assert load_review_store(path) == store
    assert store.schema_version == "1" and len(store.decisions) == 1
    decision = store.decisions[0]
    assert decision.id == report.clone_groups[0].id
    assert decision.anchor.detail == report.clone_groups[0].detail
    assert {item.path.root: item.sha256 for item in decision.anchor.source_hashes} == {
        file.evidence.path.root: file.source_sha256 for file in report.cohorts[0].current.files
    }
    for value in (decision.anchor.policy_fingerprint, decision.anchor.analysis_fingerprint):
        assert len(value) == 64 and set(value) <= set("0123456789abcdef")
    assert str(clone_root) not in path.read_text(encoding="utf-8")
    assert "def first" not in path.read_text(encoding="utf-8")
    with pytest.raises(ValidationError):
        decision.reason = "changed"
    annotated = apply_reviews(report, store)
    assert len(annotated.review_results) == 1
    result = annotated.review_results[0]
    assert result.state == "current" and result.group_id == decision.id
    assert result.decision == decision
    assert facts(annotated) == facts(report)
    assert report.model_dump_json() == before
    assert AnalysisReport.model_validate_json(annotated.model_dump_json()) == annotated
    assert "review_results" not in report.model_dump(mode="json")


def test_repeated_set_upserts_group_decision_without_duplicate_ids(clone_root: Path) -> None:
    report = analyze(clone_root)
    path = clone_root.parent / "reviews.json"
    record(path, report)
    updated = write_clone_review(
        path,
        report,
        report.clone_groups[0].id,
        disposition=ReviewDisposition.DEFER,
        reason="Wait for contract migration.",
    )
    assert len(updated.decisions) == 1
    assert updated.decisions[0].disposition is ReviewDisposition.DEFER
    assert updated.decisions[0].reason == "Wait for contract migration."
    assert load_review_store(path) == updated
    with pytest.raises(ValidationError):
        ReviewStore(decisions=(updated.decisions[0], updated.decisions[0]))


def test_comment_change_is_stale_even_when_clone_detail_and_id_are_identical(
    clone_root: Path,
) -> None:
    report = analyze(clone_root)
    store = record(clone_root.parent / "reviews.json", report)
    target = clone_root / "a.py"
    target.write_bytes(target.read_bytes().replace(b"# note", b"# revised note"))
    changed = analyze(clone_root)
    assert changed.clone_groups == report.clone_groups
    result = apply_reviews(changed, store).review_results[0]
    assert result.state == "stale"
    assert result.candidate_group_ids == (changed.clone_groups[0].id,)
    assert facts(apply_reviews(changed, store)) == facts(changed)


@pytest.mark.parametrize("options", [{"clone_min_sloc": 1}])
def test_analysis_or_boundary_policy_change_requires_revalidation_even_with_same_clones(
    clone_root: Path, options: dict
) -> None:
    report = analyze(clone_root)
    store = record(clone_root.parent / "reviews.json", report)
    changed = analyze(clone_root, **options)
    assert changed.clone_groups == report.clone_groups
    assert apply_reviews(changed, store).review_results[0].state == "stale"


def test_absent_clone_remains_missing_and_is_not_marked_fixed(clone_root: Path) -> None:
    report = analyze(clone_root)
    store = record(clone_root.parent / "reviews.json", report)
    (clone_root / "b.py").write_text("VALUE = 1\n", encoding="utf-8")
    changed = analyze(clone_root)
    assert changed.clone_groups == ()
    result = apply_reviews(changed, store).review_results[0]
    assert result.state == "missing"
    assert result.reason == "evidence-absent-or-unavailable"
    assert result.decision == store.decisions[0]


def test_historical_unknown_source_hash_cannot_record_or_validate_current(clone_root: Path) -> None:
    report = analyze(clone_root)
    store = record(clone_root.parent / "reviews.json", report)
    payload = report.model_dump(mode="json")
    for file in payload["cohorts"][0]["current"]["files"]:
        file.pop("source_sha256")
    historical = AnalysisReport.model_validate(payload)
    target = clone_root.parent / "unknown.json"
    with pytest.raises(InputError):
        record(target, historical)
    assert not target.exists()
    assert apply_reviews(historical, store).review_results[0].state != "current"


@pytest.mark.parametrize("failure", ["blank-reason", "unknown-group", "locked", "malformed-store"])
def test_failed_record_never_overwrites_existing_bytes(clone_root: Path, failure: str) -> None:
    report = analyze(clone_root)
    path = clone_root.parent / "reviews.json"
    record(path, report)
    if failure == "malformed-store":
        path.write_bytes(b'{"schema_version": "1", "decisions": [broken')
    if failure == "locked":
        path.with_name(path.name + ".lock").write_text("another writer", encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(InputError):
        write_clone_review(
            path,
            report,
            "missing-group" if failure == "unknown-group" else report.clone_groups[0].id,
            disposition=ReviewDisposition.ACTIONABLE,
            reason="   " if failure == "blank-reason" else "Consolidate shared behavior.",
        )
    assert path.read_bytes() == before


def test_explicit_missing_or_malformed_store_is_input_error(clone_root: Path) -> None:
    path = clone_root.parent / "reviews.json"
    with pytest.raises(InputError):
        load_review_store(path)
    path.write_text(json.dumps({"schema_version": "future", "decisions": []}), encoding="utf-8")
    with pytest.raises(InputError):
        load_review_store(path)


def test_scan_load_and_apply_do_not_modify_the_store(clone_root: Path) -> None:
    report = analyze(clone_root)
    path = clone_root.parent / "reviews.json"
    record(path, report)
    before = path.read_bytes()
    stat = path.stat()
    fresh = analyze(clone_root)
    annotated = apply_reviews(fresh, load_review_store(path))
    assert annotated.review_results[0].state == "current"
    assert path.read_bytes() == before and path.stat().st_mtime_ns == stat.st_mtime_ns
    assert not path.with_name(path.name + ".lock").exists()


def test_boundary_name_change_makes_review_stale_without_changing_clone_evidence(
    clone_root: Path,
) -> None:
    report = analyze(clone_root, boundaries=({"name": "first", "prefix": "a.py"},))
    store = record(clone_root.parent / "reviews.json", report)
    changed = analyze(clone_root, boundaries=({"name": "renamed", "prefix": "a.py"},))
    assert changed.clone_groups[0].detail == report.clone_groups[0].detail
    result = apply_reviews(changed, store).review_results[0]
    assert result.state == "stale"
    assert result.candidate_group_ids == (changed.clone_groups[0].id,)


@pytest.mark.parametrize(
    "options", [{"calibration_profile": "another-profile"}, {"exclusions": ("unused/**",)}]
)
def test_unrelated_configuration_does_not_expire_raw_clone_review(
    clone_root: Path, options: dict
) -> None:
    report = analyze(clone_root)
    store = record(clone_root.parent / "reviews.json", report)
    changed = analyze(clone_root, **options)
    assert apply_reviews(changed, store).review_results[0].state == "current"


def test_failed_atomic_replacement_preserves_store_and_releases_lock(
    clone_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = analyze(clone_root)
    path = clone_root.parent / "reviews.json"
    record(path, report)
    before = path.read_bytes()

    def fail_replace(*args, **kwargs):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr("os.replace", fail_replace)
    with pytest.raises(InputError):
        write_clone_review(
            path,
            report,
            report.clone_groups[0].id,
            disposition=ReviewDisposition.ACTIONABLE,
            reason="Unify shared behavior.",
        )
    assert path.read_bytes() == before
    assert not path.with_name(path.name + ".lock").exists()
