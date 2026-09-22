"""History records observed source rework without predicting future defects."""

from pathlib import Path

import pytest
from test_git_comparison import git


@pytest.fixture
def history_repo(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "History test")
    git(root, "config", "user.email", "history@example.invalid")
    return root


def commit(root, source, day):
    (root / "app.py").write_text(source, encoding="utf-8")
    git(root, "add", ".")
    with pytest.MonkeyPatch.context() as context:
        for key in ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE"):
            context.setenv(key, f"2026-09-{day:02d}T12:00:00+00:00")
        git(root, "commit", "-m", f"source {day}")
    return git(root, "rev-parse", "HEAD").decode().strip()


def analyze(root, start, end, **options):
    from slop_measure.application.history import analyze_history  # noqa: PLC0415
    from slop_measure.domain.history import HistoryRequest  # noqa: PLC0415

    return analyze_history(HistoryRequest(root=root, start=start, end=end, **options))


def test_zero_net_growth_retains_churn_and_recent_origin(history_repo):
    root = history_repo
    start = commit(root, "original = 1\n", 1)
    added = commit(root, "original = 1\nnew_value = 2\n", 2)
    end = commit(root, "original = 1\nnew_value = 3\n", 3)
    index = (root / ".git/index").read_bytes()
    status = git(root, "status", "--porcelain=v1")

    report = analyze(root, start, end)

    assert report.start.revision == start and report.end.revision == end
    assert report.ancestry == "first-parent" and report.traversal.state == "complete"
    assert [step.commit for step in report.steps] == [added, end]
    last = report.steps[-1]
    assert last.added == last.deleted == 1
    assert last.net == 0 and last.churn == 2
    recent = [item for cohort in last.cohorts for item in cohort.rework if item.state == "recent"]
    assert len(recent) == 1
    assert recent[0].introduced_commit == added and recent[0].age_seconds == 86400
    assert recent[0].deleted_line == 2
    assert report.model_dump_json() == analyze(root, start, end).model_dump_json()
    assert (root / ".git/index").read_bytes() == index
    assert git(root, "status", "--porcelain=v1") == status


def test_anchor_line_origin_is_unknown_and_old_additions_are_outside_window(history_repo):
    root = history_repo
    start = commit(root, "original = 1\n", 1)
    commit(root, "original = 2\nnew_value = 3\n", 2)
    end = commit(root, "original = 2\nnew_value = 4\n", 20)

    report = analyze(root, start, end, window_days=14)

    first = [item for cohort in report.steps[0].cohorts for item in cohort.rework]
    assert len(first) == 1 and first[0].state == "unresolved"
    assert first[0].reason == "unknown-introduction"
    last = [item for cohort in report.steps[-1].cohorts for item in cohort.rework]
    assert len(last) == 1 and last[0].state == "outside-window"


def test_commit_limit_is_partial_and_empty_range_is_complete(history_repo):
    root = history_repo
    start = commit(root, "value = 1\n", 1)
    commit(root, "value = 2\n", 2)
    end = commit(root, "value = 3\n", 3)

    limited = analyze(root, start, end, max_commits=1)
    empty = analyze(root, end, end)

    assert limited.traversal.state == "partial" and limited.traversal.reason == "commit-limit"
    assert len(limited.steps) <= 1
    assert empty.traversal.state == "complete" and empty.steps == ()


def test_comment_edits_do_not_count_as_source_churn(history_repo):
    start = commit(history_repo, "value = 1\n# first\n", 1)
    end = commit(history_repo, "value = 1\n# second\n", 2)

    report = analyze(history_repo, start, end)

    assert report.steps[0].churn == 0


def test_missing_revision_is_an_explicit_input_error(history_repo):
    from slop_measure.errors import InvalidSource  # noqa: PLC0415

    end = commit(history_repo, "value = 1\n", 1)
    with pytest.raises(InvalidSource):
        analyze(history_repo, "does-not-exist", end)
