"""Install built release artifacts into isolated environments and exercise public APIs."""

import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("SLOP_RELEASE_DIST"),
    reason="release artifacts are supplied by the build gate",
)


@pytest.mark.parametrize("pattern", ["*.tar.gz", "*.whl"])
def test_release_archives_exclude_local_state_and_cache_paths(pattern: str) -> None:
    distribution = Path(os.environ["SLOP_RELEASE_DIST"]).resolve()
    artifacts = sorted(distribution.glob(pattern))
    assert len(artifacts) == 1
    artifact = artifacts[0]
    if pattern == "*.whl":
        with zipfile.ZipFile(artifact) as archive:
            names = archive.namelist()
        assert all(
            name.split("/", 1)[0] == "slop_measure" or name.split("/", 1)[0].endswith(".dist-info")
            for name in names
        )
    else:
        with tarfile.open(artifact, "r:gz") as archive:
            names = archive.getnames()
    forbidden = {
        ".claude",
        ".codex",
        ".uv-cache",
        ".tmp",
        ".venv",
        ".pytest_cache",
        ".git",
        "__pycache__",
    }
    offending = [
        name for name in names if forbidden.intersection(name.replace("\\", "/").split("/"))
    ]
    assert not offending, f"Archive includes local state/cache paths: {offending[:10]}"


def run(arguments: list[str], cwd: Path, environment: dict[str, str]) -> str:
    result = subprocess.run(  # noqa: S603 - explicit local build artifacts and tools
        arguments,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"Release command failed ({result.returncode}): {arguments}\n"
        f"{result.stdout}\n{result.stderr}"
    )
    return result.stdout


@pytest.mark.parametrize("kind,pattern", [("wheel", "*.whl"), ("sdist", "*.tar.gz")])
def test_built_distribution_installs_and_runs_outside_checkout(
    tmp_path: Path,
    kind: str,
    pattern: str,
) -> None:
    distribution = Path(os.environ["SLOP_RELEASE_DIST"]).resolve()
    artifacts = sorted(distribution.glob(pattern))
    assert len(artifacts) == 1, f"Expected exactly one {kind}: {artifacts}"
    uv = os.environ.get("SLOP_UV") or shutil.which("uv")
    assert uv is not None, "Set SLOP_UV to the release uv executable"
    uv = str(Path(uv).resolve())
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}
    }
    environment.update(PYTHONNOUSERSITE="1", GIT_CEILING_DIRECTORIES=str(tmp_path.parent))
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    venv = tmp_path / "environment"
    run([uv, "venv", "--python", sys.executable, str(venv)], isolated, environment)
    scripts = venv / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    executable = scripts / ("slop.exe" if os.name == "nt" else "slop")
    install = [uv, "pip", "install", "--python", str(python), str(artifacts[0])]
    if constraint := environment.get("SLOP_RELEASE_CONSTRAINTS"):
        install.extend(["--constraint", str(Path(constraint).resolve())])
    run(install, isolated, environment)
    probe = """
import hashlib, importlib.resources, json, pathlib
import slop_measure
from slop_measure.scoring.profiles import load_profile
profile = load_profile('py-2026.3')
assert profile is not None
resource = importlib.resources.files('slop_measure.scoring').joinpath('resources')
manifest = resource.joinpath('py-2026.3.corpus.toml').read_bytes()
assert hashlib.sha256(manifest).hexdigest() == profile.corpus_manifest_hash
assert resource.joinpath('py-2026.3.json').is_file()
print(json.dumps({
    'module': str(pathlib.Path(slop_measure.__file__).resolve()),
    'profile': profile.profile_id,
}))
"""
    imported = json.loads(run([str(python), "-c", probe], isolated, environment))
    assert Path(imported["module"]).is_relative_to(venv.resolve())
    assert imported["profile"] == "py-2026.3"
    assert "score" in run([str(executable), "--help"], isolated, environment)
    source = isolated / "project"
    source.mkdir()
    (source / "app.py").write_text("def identity(value):\n    return value\n", encoding="utf-8")
    report = json.loads(
        run([str(executable), "score", str(source), "--json"], isolated, environment)
    )
    production = next(
        item["current"] for item in report["cohorts"] if item["cohort"] == "production"
    )
    assert production["score"]["state"] == "measured"
    assert production["score"]["profile_id"] == "py-2026.3"
    assert production["files"][0]["evidence"]["sloc"] == 2
    rules = json.loads(
        run([str(executable), "rules", "--root", str(source), "--json"], isolated, environment)
    )
    assert rules["version"] == "py-patterns-1" and len(rules["rules"]) == 20
