"""The corpus command verifies cached source and never executes target code."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[3] / "tools" / "calibrate.py"


def git(root: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", "-c", "core.fsmonitor=false", "-C", str(root), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def corpus(tmp_path: Path):
    cache = tmp_path / "cache"
    repo = cache / "sample"
    repo.mkdir(parents=True)
    git(repo, "init")
    git(repo, "config", "user.name", "Corpus test")
    git(repo, "config", "user.email", "corpus@example.invalid")
    (repo / "LICENSE").write_text("MIT fixture license\n", encoding="utf-8")
    (repo / "app.py").write_text(
        f"from pathlib import Path\nPath({str(repo / 'EXECUTED')!r}).write_text('bad')\n"
        "def f(value):\n    return value + 1\n",
        encoding="utf-8",
    )
    git(repo, "add", "LICENSE", "app.py")
    git(repo, "commit", "-m", "fixture")
    revision = git(repo, "rev-parse", "HEAD")
    manifest = tmp_path / "corpus.toml"
    manifest.write_text(
        'schema_version = "1.0"\nprofile_id = "fixture-1"\nlanguage = "python"\n'
        "min_samples = 1\n[settings]\nclone_min_statements = 2\nclone_min_sloc = 6\n"
        "complexity_threshold = 10\nenabled_rules = []\ndisabled_rules = []\n"
        '[[projects]]\nname = "sample"\nrepository = "https://example.invalid/sample.git"\n'
        f'revision = "{revision}"\nlicense = "MIT"\nlicense_file = "LICENSE"\n'
        'tag = "v1"\nrelease_date = "2019-01-01"\nproduction_patterns = ["**/*.py"]\n'
        'test_patterns = ["tests/**/*.py"]\nexclusions = [".git/**"]\n',
        encoding="utf-8",
    )
    return cache, repo, manifest


def invoke(cache: Path, manifest: Path, output: Path, evidence: Path):
    return subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(SCRIPT),
            "--manifest",
            str(manifest),
            "--cache",
            str(cache),
            "--output",
            str(output),
            "--evidence-dir",
            str(evidence),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_runner_is_byte_stable_copies_manifest_and_keeps_auditable_evidence(corpus, tmp_path: Path):
    cache, repo, manifest = corpus
    output, evidence = tmp_path / "profile.json", tmp_path / "evidence"
    result = invoke(cache, manifest, output, evidence)
    assert result.returncode == 0, result.stdout + result.stderr
    first = output.read_bytes()
    profile = json.loads(first)
    assert profile["corpus_manifest_hash"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert (tmp_path / "fixture-1.corpus.toml").read_bytes() == manifest.read_bytes()
    artifacts = {
        str(path.relative_to(evidence)): path.read_bytes()
        for path in evidence.rglob("*")
        if path.is_file()
    }
    assert artifacts
    combined = b"\n".join(artifacts.values())
    assert b"app.py" in combined
    assert hashlib.sha256((repo / "app.py").read_bytes()).hexdigest().encode() in combined
    assert b"production" in combined
    assert b"provenance" in combined
    assert not (repo / "EXECUTED").exists()
    assert git(repo, "status", "--porcelain") == ""
    again = invoke(cache, manifest, output, evidence)
    assert again.returncode == 0, again.stdout + again.stderr
    assert output.read_bytes() == first
    assert artifacts == {
        str(path.relative_to(evidence)): path.read_bytes()
        for path in evidence.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("problem", ["dirty", "revision", "license", "unsafe-name", "duplicate"])
def test_runner_rejects_unverified_source_before_writing_profile(
    corpus, tmp_path: Path, problem: str
):
    cache, repo, manifest = corpus
    text = manifest.read_text(encoding="utf-8")
    if problem == "dirty":
        (repo / "app.py").write_text("changed = 1\n", encoding="utf-8")
    elif problem == "revision":
        text = text.replace(git(repo, "rev-parse", "HEAD"), "0" * 40)
    elif problem == "license":
        text = text.replace('license_file = "LICENSE"', 'license_file = "absent"')
    elif problem == "unsafe-name":
        text = text.replace('name = "sample"', 'name = "../sample"')
    else:
        text += "\n[[projects]]" + text.split("[[projects]]", 1)[1]
    manifest.write_text(text, encoding="utf-8")
    output = tmp_path / "profile.json"
    result = invoke(cache, manifest, output, tmp_path / "evidence")
    assert result.returncode == 2, result.stdout + result.stderr
    assert not output.exists()
    assert result.stderr or result.stdout
    assert "can't open file" not in result.stderr
    assert "Traceback" not in result.stderr
