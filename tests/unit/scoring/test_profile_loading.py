"""Profile loading verifies schema and the exact source manifest bytes."""

import hashlib
import json

import pytest
from test_calibration_contract import profile_payload

from slop_measure.scoring.profiles import load_profile, parse_profile


def test_parse_profile_checks_manifest_sha256_and_preserves_policies() -> None:
    manifest = b"corpus = 'synthetic'\n"
    payload = profile_payload()
    payload["corpus_manifest_hash"] = hashlib.sha256(manifest).hexdigest()
    profile = parse_profile(json.dumps(payload), corpus_manifest=manifest)
    assert profile.profile_id == "synthetic-1"
    assert profile.corpus_manifest_hash == hashlib.sha256(manifest).hexdigest()
    assert profile.percentile_policy == "strictly-below-zero-floor"
    with pytest.raises(ValueError):
        parse_profile(json.dumps(payload), corpus_manifest=manifest + b" ")


@pytest.mark.parametrize("change", ["schema", "hash", "unknown-field", "metric-version"])
def test_invalid_profile_metadata_is_rejected(change: str) -> None:
    manifest = b"synthetic"
    payload = profile_payload()
    payload["corpus_manifest_hash"] = hashlib.sha256(manifest).hexdigest()
    if change == "schema":
        payload["schema_version"] = "future"
    elif change == "hash":
        payload["corpus_manifest_hash"] = "z" * 64
    elif change == "unknown-field":
        payload["unexpected"] = True
    else:
        payload["metric_versions"].pop()
    with pytest.raises(ValueError):
        parse_profile(json.dumps(payload), corpus_manifest=manifest)


@pytest.mark.parametrize(
    "identifier",
    ["missing-profile", "../secrets", "..\\secrets", "/absolute", "C:\\private", "py-2026.1.json"],
)
def test_loader_only_accepts_known_packaged_identifiers(identifier: str) -> None:
    assert load_profile(identifier) is None
