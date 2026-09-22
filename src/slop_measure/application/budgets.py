"""Apply declared budgets to observed introductions without changing their reports."""

from typing import assert_never

from slop_measure.application._budget_blockers import incomplete_details
from slop_measure.domain.budgets import (
    BudgetCheck,
    BudgetEvidence,
    BudgetMetric,
    BudgetPolicy,
    BudgetReport,
)
from slop_measure.domain.change_review import (
    ChangeReviewReport,
    IntroducedPattern,
)
from slop_measure.domain.clone_changes import IntroducedCloneMember
from slop_measure.domain.error_changes import IntroducedError


def _evidence(report: ChangeReviewReport, metric: BudgetMetric) -> tuple[BudgetEvidence, ...]:
    if metric is BudgetMetric.INTRODUCED_PATTERNS:
        return tuple(
            BudgetEvidence(
                path=item.current.finding.path,
                span=item.current.finding.span,
                kind=item.current.finding.rule_id,
            )
            for item in report.patterns
            if isinstance(item, IntroducedPattern)
        )
    if metric is BudgetMetric.ADDED_CLONE_MEMBERS:
        return tuple(
            BudgetEvidence(
                path=item.current.member.path, span=item.current.member.span, kind="clone"
            )
            for group in report.clones
            for item in group.members
            if isinstance(item, IntroducedCloneMember)
        )
    if metric is BudgetMetric.INTRODUCED_ERRORS:
        return tuple(
            BudgetEvidence(
                path=item.current.path,
                span=item.current.finding.fallback.span,
                kind="error-as-success",
            )
            for item in report.errors
            if isinstance(item, IntroducedError)
        )
    assert_never(metric)


def evaluate_budget(report: ChangeReviewReport, policy: BudgetPolicy) -> BudgetReport:
    """Only explicit caps are evaluated; incomplete assessment cannot establish a pass."""
    return BudgetReport(
        analysis=report.analysis,
        checks=tuple(
            BudgetCheck(
                metric=limit.metric,
                maximum=limit.maximum,
                evidence=_evidence(report, limit.metric),
                incomplete_reasons=tuple(sorted({item.message for item in details})),
                incomplete_details=details,
            )
            for limit in policy.limits
            for details in (incomplete_details(report, limit.metric),)
        ),
    )
