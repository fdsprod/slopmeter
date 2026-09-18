"""Git selectors are explicit CLI options with direct source errors."""

import json

import pytest
from test_git_comparison import history  # noqa: F401
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, GitSourceReference, SnapshotRequest, scan
from slop_measure.cli import app
from slop_measure.reporting.json import serialize_report


@pytest.mark.parametrize("command", ["scan", "score", "tree"])
def test_git_snapshot_commands_return_complete_committed_json(history, command):  # noqa: F811
    root, _, head, _, _ = history
    result = CliRunner().invoke(app, [command, str(root), "--rev", "current", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["analysis"]["current"]["revision"] == head
    expected = scan(
        SnapshotRequest(
            target=GitSourceReference(root=root, revision="current"), config=AnalysisConfig()
        )
    )
    assert data == json.loads(serialize_report(expected))


@pytest.mark.parametrize("current,kind", [("current", "git"), ("WORKTREE", "directory")])
def test_compare_repo_disambiguates_refs_and_worktree(history, current, kind):  # noqa: F811
    root, base, _, _, _ = history
    result = CliRunner().invoke(
        app, ["compare", "baseline", current, "--repo", str(root), "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["analysis"]["baseline"]["revision"] == base
    assert data["analysis"]["current"]["kind"] == kind
    assert data["cohorts"]


def test_unknown_git_revision_is_direct_exit_two(history):  # noqa: F811
    root, _, _, _, _ = history
    for args in (
        ["scan", str(root), "--rev", "missing-revision"],
        ["compare", "missing-revision", "current", "--repo", str(root)],
    ):
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 2
        assert "missing-revision" in result.output
        assert "Traceback" not in result.output


def test_git_root_must_be_repository_top_level(history):  # noqa: F811
    root, _, _, _, _ = history
    nested = root / "nested"
    nested.mkdir()
    result = CliRunner().invoke(app, ["scan", str(nested), "--rev", "HEAD"])
    assert result.exit_code == 2
    assert "root" in result.output.lower() or "top" in result.output.lower()
