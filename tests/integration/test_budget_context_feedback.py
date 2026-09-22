"""Incomplete budgets identify their blockers without weakening missing coverage."""

import pytest
from test_change_review import request, roots as shared_roots, write
from test_change_review_families import FALLBACK
from typer.testing import CliRunner

from slop_measure import api
from slop_measure.application.budgets import evaluate_budget
from slop_measure.cli import app
from slop_measure.domain.budgets import BudgetCheck, BudgetPolicy

roots = shared_roots


def evaluate(roots):
    report = api.review_change(request(roots, languages=("python",)))
    policy = BudgetPolicy.model_validate(
        {
            "limits": [
                {"metric": name, "maximum": 0}
                for name in ("introduced-patterns", "added-clone-members", "introduced-errors")
            ]
        }
    )
    return evaluate_budget(report, policy)


def test_unchanged_unsupported_handlers_keep_both_locations_and_only_block_error_budget(roots):
    source = FALLBACK.replace("return []", "return client.default")
    for root in roots:
        write(root, "fetch.py", source)

    result = evaluate(roots)

    checks = {item["metric"]: item for item in result.model_dump(mode="json")["checks"]}
    assert result.state == "incomplete"
    assert checks["introduced-patterns"]["incomplete_details"] == []
    assert checks["added-clone-members"]["incomplete_details"] == []
    error = checks["introduced-errors"]
    assert error["observed"] == 0 and not error["exceeded"]
    details = error["incomplete_details"]
    assert {item["side"] for item in details} == {"baseline", "current"}
    assert all(item["code"] == "unsupported-handler" for item in details)
    assert all(item["scope"] == "source" and item["path"] == "fetch.py" for item in details)
    assert all(item["span"] == {"start_line": 4, "end_line": 5} for item in details)
    assert {item["message"] for item in details} == set(error["incomplete_reasons"])
    assert type(result).model_validate_json(result.model_dump_json()) == result


def test_failed_source_reason_names_actual_current_file_without_inventing_baseline_failure(roots):
    write(roots[0], "broken.py", "value = 1\n")
    write(roots[1], "broken.py", "def broken(:\n")

    result = evaluate(roots)

    for check in result.model_dump(mode="json")["checks"]:
        failures = [
            item for item in check["incomplete_details"] if item["code"] == "analysis-error"
        ]
        assert failures
        assert all(item["side"] == "current" and item["path"] == "broken.py" for item in failures)
        assert all(item["scope"] == "source" for item in failures)
        assert all(item["span"] is None or item["span"]["start_line"] == 1 for item in failures)
    assert result.state == "incomplete"


def test_aggregate_exclusions_have_population_scope_without_fabricated_source_spans(roots):
    report = api.review_change(request(roots, languages=("python",)))
    wire = report.model_dump(mode="json")
    wire["limitations"] = [
        {
            "language": "python",
            "cohort": "production",
            "path": None,
            "reason": "Excluded source counts do not identify counterpart paths",
        }
    ]
    selected = type(report).model_validate(wire)
    policy = BudgetPolicy.model_validate(
        {"limits": [{"metric": "introduced-patterns", "maximum": 0}]}
    )
    result = evaluate_budget(selected, policy)

    assert result.state == "incomplete"
    details = result.model_dump(mode="json")["checks"][0]["incomplete_details"]
    population = [item for item in details if item["scope"] == "population"]
    assert population
    assert all(item["path"] is None and item["span"] is None for item in population)
    assert all(item["code"] == "analysis-limitation" and item["message"] for item in population)


def detail(**overrides):
    return {
        "code": "unsupported-handler",
        "message": "Handler is unresolved",
        "scope": "source",
        "side": "current",
        "path": "fetch.py",
        "span": {"start_line": 4, "end_line": 5},
        **overrides,
    }


def payload(details, reasons=None):
    return {
        "metric": "introduced-errors",
        "maximum": 0,
        "incomplete_details": details,
        "incomplete_reasons": ["Handler is unresolved"] if reasons is None else reasons,
    }


def test_structured_reasons_roundtrip_and_old_text_only_budgets_still_load():
    new = BudgetCheck.model_validate(payload([detail()]))
    assert BudgetCheck.model_validate_json(new.model_dump_json()) == new
    old = payload([], reasons=["Historical missing coverage"])
    old.pop("incomplete_details")
    assert BudgetCheck.model_validate(old).incomplete_reasons == ("Historical missing coverage",)


@pytest.mark.parametrize(
    "changes",
    [
        {"side": None},
        {"path": None},
        {"scope": "population"},
        {"code": "invented"},
    ],
)
def test_source_and_population_blockers_reject_contradictory_locations(changes):
    with pytest.raises(ValueError):
        BudgetCheck.model_validate(payload([detail(**changes)]))


def test_structured_reason_cannot_contradict_compatibility_message():
    with pytest.raises(ValueError):
        BudgetCheck.model_validate(payload([detail()], reasons=["Everything assessed"]))


def test_terminal_budget_names_the_side_path_and_handler_span(roots, tmp_path):
    for root in roots:
        write(root, "fetch.py", FALLBACK.replace("return []", "return client.default"))
    policy_file = tmp_path / "budget.toml"
    policy_file.write_text('[[limits]]\nmetric="introduced-errors"\nmaximum=0\n', encoding="utf-8")

    result = CliRunner().invoke(
        app, ["changes", *map(str, roots), "--lang", "py", "--budget", str(policy_file)]
    )

    assert result.exit_code == 0, result.output
    lines = result.stdout.lower().splitlines()
    for side in ("baseline", "current"):
        assert any(side in line and "fetch.py:4" in line for line in lines)
    assert "incomplete" in result.stdout.lower()
