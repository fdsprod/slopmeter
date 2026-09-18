"""Git evidence commands select their requested source side without reading dirty bytes."""

import json

from test_git_comparison import git, history  # noqa: F401
from typer.testing import CliRunner

from slop_measure.cli import app


def test_git_explanation_selects_exact_renamed_side_and_resolved_revisions(history) -> None:  # noqa: F811
    root, base, head, _, _ = history
    runner = CliRunner()
    shared = ["--root", str(root), "--baseline-rev", "baseline", "--rev", "current"]
    baseline = runner.invoke(app, ["explain", "old.py", *shared, "--source", "baseline", "--json"])
    assert baseline.exit_code == 0, baseline.output
    payload = json.loads(baseline.stdout)
    assert payload["analysis"]["baseline"]["revision"] == base
    assert payload["analysis"]["current"]["revision"] == head
    cohort = payload["cohorts"][0]
    assert cohort["baseline"]["files"][0]["evidence"]["path"] == "old.py"
    assert cohort["baseline"]["files"][0]["evidence"]["sloc"] == 14
    assert cohort["current"]["files"][0]["evidence"]["sloc"] == 14
    current = runner.invoke(app, ["explain", "new.py", *shared, "--source", "current", "--json"])
    assert current.exit_code == 0, current.output
    assert json.loads(current.stdout) == payload
    wrong = runner.invoke(app, ["explain", "old.py", *shared, "--source", "current"])
    assert wrong.exit_code == 2
    assert "Traceback" not in wrong.output


def test_git_findings_filters_preserve_baseline_current_ownership_and_checkout(history) -> None:  # noqa: F811
    root, _, _, _, current = history
    path = root / "new.py"
    path.write_text(current + 'VALUE = f"literal"\n', encoding="utf-8")
    git(root, "add", "new.py")
    git(root, "commit", "-m", "Before evidence")
    base = git(root, "rev-parse", "HEAD").decode().strip()
    path.write_text(current + "VALUE = True if flag else False\n", encoding="utf-8")
    git(root, "add", "new.py")
    git(root, "commit", "-m", "After evidence")
    head = git(root, "rev-parse", "HEAD").decode().strip()
    path.write_text("dirty = 1\n", encoding="utf-8")
    status = git(root, "status", "--porcelain=v1", "-z")
    index = (root / ".git/index").read_bytes()
    shared = [
        "findings",
        "--root",
        str(root),
        "--baseline-rev",
        base,
        "--rev",
        head,
        "--path",
        "new.py",
        "--metric",
        "m2",
        "--json",
    ]
    for side, rule in (("baseline", "py.literal-fstring"), ("current", "py.boolean-conditional")):
        result = CliRunner().invoke(app, [*shared, "--source", side, "--rule", rule])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        selected = payload["selection"]
        assert selected["clone_groups"] == selected["functions"] == []
        assert len(selected["patterns"]) == 1
        finding = selected["patterns"][0]
        assert finding["source"] == side
        assert finding["detail"]["rule_id"] == rule
        assert finding["detail"]["path"] == "new.py"
        assert finding["detail"]["span"]["start_line"] == 15
        assert payload["analysis"]["baseline"]["revision"] == base
        assert payload["analysis"]["current"]["revision"] == head
    assert git(root, "status", "--porcelain=v1", "-z") == status
    assert (root / ".git/index").read_bytes() == index
    assert path.read_text(encoding="utf-8") == "dirty = 1\n"
