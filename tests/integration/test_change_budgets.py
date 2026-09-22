"""Explicit advisory budgets count introduced evidence, with opt-in enforcement."""

# ruff: noqa: PLC0415 - defer the new contract imports so every red case can run.

import json
from pathlib import Path

import pytest
from test_change_review import (
    LITERAL_SOURCE,
    request,
    roots as roots,  # noqa: PLC0414 - shared pytest fixture.
    write,
)
from typer.testing import CliRunner

from slop_measure import api
from slop_measure.cli import app
from slop_measure.domain.change_review import ChangeReviewReport


def policy(maximum: int = 0):
    from slop_measure.domain.budgets import BudgetPolicy

    return BudgetPolicy.model_validate(
        {
            "limits": [{"metric": "introduced-patterns", "maximum": maximum}],
        }
    )


def budget_file(tmp_path: Path, maximum: int = 0) -> Path:
    path = tmp_path / "budget.toml"
    path.write_text(
        f'[[limits]]\nmetric="introduced-patterns"\nmaximum={maximum}\n',
        encoding="utf-8",
    )
    return path


def evaluate(report: ChangeReviewReport, maximum: int = 0):
    from slop_measure.application.budgets import evaluate_budget

    return evaluate_budget(report, policy(maximum))


def test_untouched_debt_does_not_fail_a_zero_introduced_budget(roots):
    for root in roots:
        write(root, "existing.py", LITERAL_SOURCE)
    selected = request(roots, languages=("python",))
    report = api.review_change(selected)
    before = report.model_dump_json()

    result = evaluate(report)

    assert result.state == "pass"
    assert result.checks[0].observed == 0
    assert result.checks[0].evidence == ()
    assert result.analysis == report.analysis
    assert report.model_dump_json() == before


def test_introduced_budget_evidence_points_to_current_source_and_cap_equality_passes(roots):
    write(roots[1], "new.py", LITERAL_SOURCE)
    report = api.review_change(request(roots, languages=("python",)))

    exceeded = evaluate(report)

    assert exceeded.state == "exceeded"
    check = exceeded.checks[0]
    assert check.metric == "introduced-patterns"
    assert check.observed == 1 and check.exceeded
    assert check.evidence[0].path.root == "new.py"
    assert check.evidence[0].span.start_line == 2
    assert check.evidence[0].kind
    assert evaluate(report, maximum=1).state == "pass"


@pytest.mark.parametrize("change", ["removed", "changed"])
def test_removal_and_changed_existing_evidence_do_not_count_as_introduced(roots, change):
    write(roots[0], "sample.py", LITERAL_SOURCE)
    if change == "changed":
        write(roots[1], "sample.py", LITERAL_SOURCE.replace("hello", "goodbye"))
    report = api.review_change(request(roots, languages=("python",)))

    result = evaluate(report)

    assert result.state == "pass"
    assert result.checks[0].observed == 0


def test_unresolved_candidates_prevent_a_passing_budget(roots):
    write(roots[0], "sample.py", LITERAL_SOURCE)
    write(roots[1], "sample.py", "def broken(:\n")
    report = api.review_change(request(roots, languages=("python",)))

    result = evaluate(report)

    assert result.state == "incomplete"
    assert result.checks[0].incomplete_reasons
    assert result.checks[0].observed == 0


def test_missing_source_coverage_is_incomplete_even_without_known_findings(roots):
    for root in roots:
        write(root, "broken.py", "def broken(:\n")
    report = api.review_change(request(roots, languages=("python",)))
    assert report.patterns == () and report.limitations

    result = evaluate(report)

    assert result.state == "incomplete"
    assert result.checks[0].incomplete_reasons


def test_explicit_empty_budget_does_not_invent_default_limits(roots):
    from slop_measure.application.budgets import evaluate_budget
    from slop_measure.domain.budgets import BudgetPolicy

    write(roots[1], "new.py", LITERAL_SOURCE)
    report = api.review_change(request(roots, languages=("python",)))
    result = evaluate_budget(report, BudgetPolicy(limits=()))
    assert result.checks == ()
    assert result.state == "pass"


@pytest.mark.parametrize("enforce", [False, True])
@pytest.mark.parametrize("state", ["pass", "exceeded", "incomplete"])
def test_cli_budget_is_advisory_unless_enforcement_is_explicit(roots, tmp_path, enforce, state):
    if state == "exceeded":
        write(roots[1], "new.py", LITERAL_SOURCE)
    elif state == "incomplete":
        write(roots[0], "sample.py", LITERAL_SOURCE)
        write(roots[1], "sample.py", "def broken(:\n")
    else:
        for root in roots:
            write(root, "existing.py", LITERAL_SOURCE)
    path = budget_file(tmp_path)
    args = [
        "changes",
        *map(str, roots),
        "--lang",
        "py",
        "--json",
        "--budget",
        str(path),
    ]
    if enforce:
        args.append("--enforce-budget")

    result = CliRunner().invoke(app, args)

    expected_exit = {"pass": 0, "exceeded": 1, "incomplete": 3}[state] if enforce else 0
    assert result.exit_code == expected_exit, result.output
    wire = json.loads(result.stdout)
    assert set(wire) == {"report", "budget"}
    assert wire["budget"]["state"] == state
    assert wire["report"] == api.review_change(request(roots, languages=("python",))).model_dump(
        mode="json"
    )


def test_no_budget_json_retains_the_existing_report_shape(roots):
    write(roots[1], "sample.py", LITERAL_SOURCE)
    selected = request(roots, languages=("python",))

    result = CliRunner().invoke(app, ["changes", *map(str, roots), "--lang", "py", "--json"])

    assert result.exit_code == 0, result.output
    wire = json.loads(result.stdout)
    assert "budget" not in wire and "report" not in wire
    assert wire == api.review_change(selected).model_dump(mode="json")


def test_enforcement_requires_an_explicit_budget(roots):
    result = CliRunner().invoke(app, ["changes", *map(str, roots), "--enforce-budget"])
    assert result.exit_code == 2
    assert "--budget" in result.output


def test_cli_rejects_an_invalid_budget_without_emitting_a_success_report(roots, tmp_path):
    path = tmp_path / "invalid.toml"
    path.write_text('[[limits]]\nmetric="introduced-patterns"\nmaximum=-1\n', encoding="utf-8")
    result = CliRunner().invoke(
        app,
        ["changes", *map(str, roots), "--json", "--budget", str(path)],
    )
    assert result.exit_code == 2
    assert "maximum" in result.output.lower()
    assert '"state": "pass"' not in result.stdout
