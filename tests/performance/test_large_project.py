"""A fresh-process benchmark records native memory and reproducible source identity."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from slop_measure import __version__
from slop_measure.config import AnalysisConfig

_ROOT = Path(__file__).resolve().parents[2]


def run_benchmark(work: Path, output: Path, *size: str) -> dict:
    process = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(_ROOT / "tools/benchmark.py"),
            "--work-dir",
            str(work),
            "--output",
            str(output),
            *size,
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    return json.loads(output.read_text(encoding="utf-8"))


def test_tiny_benchmark_counts_owned_sloc_and_repeats_source_hash_without_overwriting(
    tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    sentinel = work / "keep.py"
    sentinel.write_bytes(b"raise RuntimeError('existing data must stay untouched')\n")
    original = sentinel.read_bytes()
    runs = []
    for index in range(2):
        result = run_benchmark(
            work, tmp_path / f"result-{index}.json", "--files", "2", "--functions-per-file", "3"
        )
        runs.append(result)
        assert result["schema_version"] == "1.0"
        assert result["tool_version"] == __version__
        assert result["python_version"] and result["platform"]
        assert result["files"] == 2
        assert result["sloc"] == 60
        assert result["diagnostics_count"] == 0
        assert re.fullmatch(r"[0-9a-f]{64}", result["source_sha256"])
        assert isinstance(result["peak_rss_bytes"], int) and result["peak_rss_bytes"] > 0
        assert result["elapsed_seconds"] > 0
        assert result["config"] == AnalysisConfig().model_dump(mode="json")
    assert runs[0]["source_sha256"] == runs[1]["source_sha256"]
    assert sentinel.read_bytes() == original
    children = [path for path in work.iterdir() if path.is_dir()]
    assert len(children) == 2
    assert all(len(tuple(child.rglob("*.py"))) == 2 for child in children)


@pytest.mark.skipif(
    os.environ.get("SLOP_RUN_PERFORMANCE") != "1", reason="Explicit 100k SLOC benchmark"
)
def test_default_benchmark_analyzes_one_hundred_thousand_sloc(tmp_path: Path) -> None:
    result = run_benchmark(tmp_path / "work", tmp_path / "benchmark.json")
    assert result["files"] == 100
    assert result["sloc"] == 100_000
    assert result["diagnostics_count"] == 0
    assert result["elapsed_seconds"] > 0
    assert result["peak_rss_bytes"] > 0


def test_benchmark_owns_its_source_even_inside_parent_git_ignored_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = shutil.which("git")
    assert executable is not None
    monkeypatch.delenv("GIT_CEILING_DIRECTORIES", raising=False)
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(  # noqa: S603
        [executable, "init", "--quiet", str(repository)],
        check=True,
        capture_output=True,
    )
    (repository / ".gitignore").write_text("cache/**\n", encoding="utf-8")
    result = run_benchmark(
        repository / "cache",
        tmp_path / "ignored-parent-result.json",
        "--files",
        "2",
        "--functions-per-file",
        "3",
    )
    assert result["files"] == 2
    assert result["sloc"] == 60
    assert result["diagnostics_count"] == 0
