"""Load packaged calibration profiles and verify their exact corpus manifest."""

import re
from hashlib import sha256
from importlib.resources import files

from slop_measure.domain.scoring import CalibrationProfile


def parse_profile(profile_json: str, *, corpus_manifest: bytes) -> CalibrationProfile:
    """Validate profile schema and the immutable reference corpus identity."""
    profile = CalibrationProfile.model_validate_json(profile_json)
    if sha256(corpus_manifest).hexdigest() != profile.corpus_manifest_hash:
        raise ValueError("calibration corpus manifest hash does not match the profile")
    return profile


def load_profile(profile_id: str) -> CalibrationProfile | None:
    """Read a package-owned identifier without interpreting it as a filesystem path."""
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", profile_id) is None:
        return None
    resource = files("slop_measure.scoring").joinpath("resources")
    path = resource.joinpath(f"{profile_id}.json")
    if not path.is_file():
        return None
    try:
        profile = parse_profile(
            path.read_text(encoding="utf-8"),
            corpus_manifest=resource.joinpath(f"{profile_id}.corpus.toml").read_bytes(),
        )
    except OSError as error:
        raise ValueError("calibration corpus manifest could not be read") from error
    if profile.profile_id != profile_id:
        raise ValueError("calibration profile identifier does not match its resource")
    return profile
