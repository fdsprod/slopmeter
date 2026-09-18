"""Behavioral tests for snapshot and comparison request contracts."""

import pytest
from pydantic import TypeAdapter, ValidationError

from slop_measure.config import AnalysisConfig
from slop_measure.domain.requests import AnalysisRequest, ComparisonRequest, SnapshotRequest
from slop_measure.domain.source import DirectorySourceReference, GitSourceReference


def test_snapshot_request_preserves_target_and_resolved_config() -> None:
    request = TypeAdapter(AnalysisRequest).validate_python(
        {
            "kind": "snapshot",
            "target": {"kind": "directory", "root": "checkout"},
            "config": {"strict": True},
        }
    )

    assert isinstance(request, SnapshotRequest)
    assert isinstance(request.target, DirectorySourceReference)
    assert request.config.strict is True
    assert request.model_dump(mode="json")["kind"] == "snapshot"


def test_comparison_request_preserves_two_references_and_shared_config() -> None:
    request = TypeAdapter(AnalysisRequest).validate_python(
        {
            "kind": "comparison",
            "baseline": {"kind": "git", "root": "checkout", "revision": "HEAD~1"},
            "current": {"kind": "directory", "root": "checkout"},
            "config": {"complexity_threshold": 12},
        }
    )

    assert isinstance(request, ComparisonRequest)
    assert isinstance(request.baseline, GitSourceReference)
    assert request.baseline.revision == "HEAD~1"
    assert isinstance(request.current, DirectorySourceReference)
    assert request.config.complexity_threshold == 12
    assert set(request.model_dump()) == {"kind", "baseline", "current", "config"}


@pytest.mark.parametrize("missing", ["baseline", "current", "config"])
def test_comparison_requires_both_references_and_config(missing: str) -> None:
    payload = {
        "kind": "comparison",
        "baseline": {"kind": "directory", "root": "before"},
        "current": {"kind": "directory", "root": "after"},
        "config": {},
    }
    del payload[missing]

    with pytest.raises(ValidationError):
        ComparisonRequest.model_validate(payload)


@pytest.mark.parametrize("missing", ["target", "config"])
def test_snapshot_requires_target_and_config(missing: str) -> None:
    payload = {
        "kind": "snapshot",
        "target": {"kind": "directory", "root": "checkout"},
        "config": {},
    }
    del payload[missing]

    with pytest.raises(ValidationError):
        SnapshotRequest.model_validate(payload)


@pytest.mark.parametrize("field", ["baseline", "current", "unexpected"])
def test_snapshot_rejects_comparison_fields_and_unknown_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        SnapshotRequest.model_validate(
            {
                "kind": "snapshot",
                "target": {"kind": "directory", "root": "checkout"},
                "config": {},
                field: {"kind": "directory", "root": "before"},
            }
        )


@pytest.mark.parametrize("field", ["target", "baseline_config", "current_config", "unexpected"])
def test_comparison_rejects_extra_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        ComparisonRequest.model_validate(
            {
                "kind": "comparison",
                "baseline": {"kind": "directory", "root": "before"},
                "current": {"kind": "directory", "root": "after"},
                "config": {},
                field: {},
            }
        )


@pytest.mark.parametrize("kind", [None, "scan", "diff"])
def test_request_union_requires_a_known_discriminator(kind: str | None) -> None:
    payload: dict[str, object] = {
        "target": {"kind": "directory", "root": "checkout"},
        "config": {},
    }
    if kind is not None:
        payload["kind"] = kind

    with pytest.raises(ValidationError):
        TypeAdapter(AnalysisRequest).validate_python(payload)


@pytest.mark.parametrize("kind", ["snapshot", "comparison"])
def test_requests_and_nested_config_are_immutable(kind: str) -> None:
    reference = {"kind": "directory", "root": "checkout"}
    references = (
        {"target": reference}
        if kind == "snapshot"
        else {"baseline": reference, "current": reference}
    )
    request = TypeAdapter(AnalysisRequest).validate_python(
        {"kind": kind, **references, "config": AnalysisConfig()}
    )

    with pytest.raises(ValidationError):
        request.config = AnalysisConfig(strict=True)
    with pytest.raises(ValidationError):
        request.config.strict = True


def test_request_schema_declares_its_discriminator() -> None:
    schema = TypeAdapter(AnalysisRequest).json_schema()

    assert schema["discriminator"]["propertyName"] == "kind"
    assert set(schema["discriminator"]["mapping"]) == {"snapshot", "comparison"}
