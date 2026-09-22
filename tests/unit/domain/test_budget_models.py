"""Budgets retain their explicit caps and derive outcomes from review evidence."""

# ruff: noqa: PLC0415 - defer the new contract imports so every red case can run.

import pytest
from pydantic import ValidationError


def check_payload(**overrides) -> dict:
    return {
        "metric": "introduced-patterns",
        "maximum": 0,
        "evidence": [
            {
                "path": "sample.py",
                "span": {"start_line": 2, "end_line": 2},
                "kind": "pattern",
            }
        ],
        "incomplete_reasons": [],
        **overrides,
    }


def report_payload(checks: list[dict]) -> dict:
    return {
        "analysis": {
            "kind": "comparison",
            "baseline": {"kind": "directory", "root": "before"},
            "current": {"kind": "directory", "root": "after"},
        },
        "checks": checks,
    }


@pytest.mark.parametrize("maximum", [-1, True, False, 0.5, "1", None])
def test_caps_require_strict_nonnegative_integers(maximum):
    from slop_measure.domain.budgets import BudgetPolicy

    with pytest.raises(ValidationError):
        BudgetPolicy.model_validate(
            {
                "limits": [{"metric": "introduced-patterns", "maximum": maximum}],
            }
        )


def test_policy_accepts_only_the_three_declared_metrics_and_rejects_duplicates():
    from slop_measure.domain.budgets import BudgetPolicy

    metrics = ("introduced-patterns", "added-clone-members", "introduced-errors")
    policy = BudgetPolicy.model_validate(
        {
            "limits": [{"metric": metric, "maximum": 0} for metric in metrics],
        }
    )
    assert isinstance(policy.limits, tuple)
    assert tuple(limit.metric for limit in policy.limits) == metrics
    with pytest.raises(ValidationError):
        BudgetPolicy.model_validate(
            {
                "limits": [{"metric": "score", "maximum": 0}],
            }
        )
    with pytest.raises(ValidationError):
        BudgetPolicy.model_validate(
            {
                "limits": [
                    {"metric": "introduced-patterns", "maximum": 0},
                    {"metric": "introduced-patterns", "maximum": 1},
                ],
            }
        )


@pytest.mark.parametrize("maximum,exceeded", [(0, True), (1, False), (2, False)])
def test_check_counts_evidence_and_exceeds_only_above_the_cap(maximum, exceeded):
    from slop_measure.domain.budgets import BudgetCheck

    check = BudgetCheck.model_validate(check_payload(maximum=maximum))
    assert check.observed == 1
    assert check.exceeded is exceeded
    assert isinstance(check.evidence, tuple)
    assert check.evidence[0].path.root == "sample.py"


@pytest.mark.parametrize(
    "checks,state",
    [
        ([], "pass"),
        ([check_payload(maximum=1)], "pass"),
        ([check_payload()], "exceeded"),
        ([check_payload(evidence=[], incomplete_reasons=["Source unavailable"])], "incomplete"),
        ([check_payload(incomplete_reasons=["Some candidates unresolved"])], "incomplete"),
        (
            [
                check_payload(),
                check_payload(
                    metric="introduced-errors", evidence=[], incomplete_reasons=["Missing"]
                ),
            ],
            "incomplete",
        ),
    ],
)
def test_report_incompleteness_takes_precedence_over_known_exceedance(checks, state):
    from slop_measure.domain.budgets import BudgetReport

    report = BudgetReport.model_validate(report_payload(checks))
    assert report.state == state
    assert BudgetReport.model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize("field,value", [("observed", 0), ("observed", True), ("exceeded", False)])
def test_imported_check_cannot_supply_false_projections(field, value):
    from slop_measure.domain.budgets import BudgetCheck

    wire = BudgetCheck.model_validate(check_payload()).model_dump(mode="json")
    wire[field] = value
    with pytest.raises(ValidationError):
        BudgetCheck.model_validate(wire)


def test_report_cannot_claim_pass_when_its_check_exceeds():
    from slop_measure.domain.budgets import BudgetReport

    wire = BudgetReport.model_validate(report_payload([check_payload()])).model_dump(mode="json")
    wire["state"] = "pass"
    with pytest.raises(ValidationError):
        BudgetReport.model_validate(wire)


def test_policy_and_check_are_frozen_and_empty_policy_has_no_defaults():
    from slop_measure.domain.budgets import BudgetCheck, BudgetPolicy

    policy = BudgetPolicy.model_validate({"limits": []})
    assert policy.limits == ()
    check = BudgetCheck.model_validate(check_payload())
    with pytest.raises(ValidationError):
        check.maximum = 20
    with pytest.raises(ValidationError):
        policy.limits = ()
