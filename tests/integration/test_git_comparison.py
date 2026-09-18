"""Git analysis reads immutable objects and leaves checkout state intact."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from slop_measure.api import (
    AnalysisConfig,
    ComparisonRequest,
    DirectorySourceReference,
    GitSourceReference,
    SnapshotRequest,
    compare,
    scan,
)
from slop_measure.reporting.json import serialize_report


def git(root: Path, *args: str) -> bytes:
    executable = shutil.which("git")
    assert executable is not None
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(  # noqa: S603
        [executable, "-c", "core.fsmonitor=false", "-C", str(root), *args],
        check=True,
        capture_output=True,
        env=env,
    ).stdout


@pytest.fixture
def history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Git test")
    git(root, "config", "user.email", "git@example.invalid")
    old = (
        "def work(value):\n"
        + "".join(f"    step_{n} = value + {n}\n" for n in range(12))
        + "    return step_11\n"
    )
    (root / "old.py").write_text(old, encoding="utf-8", newline="\n")
    (root / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "baseline")
    base = git(root, "rev-parse", "HEAD").decode().strip()
    git(root, "tag", "baseline", base)
    git(root, "mv", "old.py", "new.py")
    current = old.replace("return step_11", "return step_10")
    (root / "new.py").write_text(current, encoding="utf-8", newline="\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "renamed and modified")
    head = git(root, "rev-parse", "HEAD").decode().strip()
    git(root, "branch", "current", head)
    (root / "new.py").write_text("dirty = 1\n", encoding="utf-8")
    (root / "untracked.py").write_text("untracked = 1\n", encoding="utf-8")
    (root / "ignored.py").write_text("ignored = 1\n", encoding="utf-8")
    return root, base, head, old, current


def config() -> AnalysisConfig:
    return AnalysisConfig(calibration_profile="__raw__")


@pytest.mark.parametrize("revision", ["current", "HEAD"])
def test_git_scan_resolves_identity_and_ignores_dirty_untracked_and_ignored_files(
    history, revision
):
    root, _, head, _, _ = history
    index = (root / ".git" / "index").read_bytes()
    status = git(root, "status", "--porcelain=v1", "--ignored")
    worktree = {path.name: path.read_bytes() for path in root.glob("*.py")}
    request = SnapshotRequest(
        target=GitSourceReference(root=root, revision=revision), config=config()
    )
    report = scan(request)
    assert report.analysis.current.kind == "git"
    assert report.analysis.current.revision == head
    files = [file for cohort in report.cohorts for file in cohort.current.files]
    assert [file.evidence.path.root for file in files] == ["new.py"]
    assert files[0].evidence.sloc == 14
    assert len(files[0].functions) == 1
    assert serialize_report(report) == serialize_report(scan(request))
    assert (root / ".git" / "index").read_bytes() == index
    assert git(root, "status", "--porcelain=v1", "--ignored") == status
    assert {path.name: path.read_bytes() for path in root.glob("*.py")} == worktree


def test_git_modified_rename_and_directory_snapshots_share_raw_results(history, tmp_path: Path):
    root, base, head, old, current = history
    baseline = GitSourceReference(root=root, revision="baseline")
    now = GitSourceReference(root=root, revision="current")
    report = compare(ComparisonRequest(baseline=baseline, current=now, config=config()))
    assert report.analysis.kind == "comparison"
    assert report.analysis.baseline.kind == report.analysis.current.kind == "git"
    assert report.analysis.baseline.revision == base
    assert report.analysis.current.revision == head
    production = next(c for c in report.cohorts if c.cohort.value == "production")
    assert production.kind == "comparison"
    assert len(production.changes) == 1
    change = production.changes[0]
    assert change.pair.kind == "renamed"
    assert change.pair.baseline_path.root == "old.py"
    assert change.pair.current_path.root == "new.py"
    assert change.lines.state == "measured"
    assert change.lines.added_lines == change.lines.deleted_lines == (14,)
    assert change.lines.net == 0
    for side, text, name in (("baseline", old, "old.py"), ("current", current, "new.py")):
        directory = tmp_path / side
        directory.mkdir()
        (directory / name).write_text(text, encoding="utf-8", newline="\n")
        standalone = scan(
            SnapshotRequest(target=DirectorySourceReference(root=directory), config=config())
        )
        expected = next(c.current for c in standalone.cohorts if c.cohort.value == "production")
        assert (production.baseline if side == "baseline" else production.current) == expected


def test_git_baseline_can_compare_with_current_worktree(history):
    root, _, _, _, _ = history
    report = compare(
        ComparisonRequest(
            baseline=GitSourceReference(root=root, revision="current"),
            current=DirectorySourceReference(root=root),
            config=config(),
        )
    )
    assert report.analysis.kind == "comparison"
    assert report.analysis.baseline.kind == "git"
    assert report.analysis.current.kind == "directory"
    production = next(c for c in report.cohorts if c.cohort.value == "production")
    assert production.kind == "comparison"
    assert {f.evidence.path.root for f in production.current.files} == {"new.py", "untracked.py"}
    assert production.line_delta.state == "measured"
    assert production.line_delta.net == -12
