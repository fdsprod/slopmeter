"""Profile loading verifies schema and the exact source manifest bytes."""

import hashlib
import json
from pathlib import Path

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


@pytest.fixture
def packaged_resources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    resources = tmp_path / "resources"
    resources.mkdir()
    manifest = b"corpus = 'synthetic'\n"
    payload = profile_payload()
    payload["corpus_manifest_hash"] = hashlib.sha256(manifest).hexdigest()
    (resources / "synthetic-1.json").write_text(json.dumps(payload), encoding="utf-8")
    (resources / "synthetic-1.corpus.toml").write_bytes(manifest)
    monkeypatch.setattr("slop_measure.scoring.profiles.files", lambda _package: tmp_path)
    return resources


def test_packaged_loader_verifies_profile_and_manifest(packaged_resources: Path) -> None:
    loaded = load_profile("synthetic-1")
    assert loaded is not None
    assert loaded.profile_id == "synthetic-1"
    assert (
        loaded.corpus_manifest_hash
        == hashlib.sha256((packaged_resources / "synthetic-1.corpus.toml").read_bytes()).hexdigest()
    )


@pytest.mark.parametrize(
    "change", ["malformed-json", "missing-manifest", "wrong-id", "tampered-manifest"]
)
def test_corrupt_packaged_profile_raises_instead_of_returning_missing(
    packaged_resources: Path, change: str
) -> None:
    profile_path = packaged_resources / "synthetic-1.json"
    manifest_path = packaged_resources / "synthetic-1.corpus.toml"
    if change == "malformed-json":
        profile_path.write_text("{invalid", encoding="utf-8")
    elif change == "missing-manifest":
        manifest_path.unlink()
    elif change == "wrong-id":
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
        payload["profile_id"] = "other"
        profile_path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        manifest_path.write_bytes(b"changed")
    with pytest.raises(ValueError):
        load_profile("synthetic-1")
