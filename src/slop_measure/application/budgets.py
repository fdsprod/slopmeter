"""Apply declared budgets to observed introductions without changing their reports."""

from typing import assert_never

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
    UnresolvedPatterns,
)
from slop_measure.domain.clone_changes import IntroducedCloneMember, UnresolvedCloneMembers
from slop_measure.domain.error_changes import IntroducedError, UnresolvedErrors
from slop_measure.domain.error_review import (
    AnalyzedErrorFile,
    FailedErrorFile,
    UnresolvedErrorHandler,
)
from slop_measure.domain.evidence import DiagnosticSeverity


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


def _incomplete(report: ChangeReviewReport, metric: BudgetMetric) -> tuple[str, ...]:
    reasons = [item.reason for item in report.limitations]
    reasons.extend(
        item.detail.message
        for item in report.diagnostics
        if item.detail.severity is DiagnosticSeverity.ERROR
    )
    if metric is BudgetMetric.INTRODUCED_PATTERNS:
        reasons.extend(
            item.reason for item in report.patterns if isinstance(item, UnresolvedPatterns)
        )
    elif metric is BudgetMetric.ADDED_CLONE_MEMBERS:
        reasons.extend(
            item.reason
            for group in report.clones
            for item in group.members
            if isinstance(item, UnresolvedCloneMembers)
        )
    elif metric is BudgetMetric.INTRODUCED_ERRORS:
        reasons.extend(item.reason for item in report.errors if isinstance(item, UnresolvedErrors))
        for coverage in report.error_coverage:
            file = coverage.detail
            if isinstance(file, FailedErrorFile):
                reasons.append(file.diagnostic.message)
            elif isinstance(file, AnalyzedErrorFile):
                reasons.extend(
                    handler.reason
                    for handler in file.handlers
                    if isinstance(handler, UnresolvedErrorHandler)
                )
            else:
                assert_never(file)
    else:
        assert_never(metric)
    return tuple(sorted(set(reasons)))


def evaluate_budget(report: ChangeReviewReport, policy: BudgetPolicy) -> BudgetReport:
    """Only explicit caps are evaluated; incomplete assessment cannot establish a pass."""
    return BudgetReport(
        analysis=report.analysis,
        checks=tuple(
            BudgetCheck(
                metric=limit.metric,
                maximum=limit.maximum,
                evidence=_evidence(report, limit.metric),
                incomplete_reasons=_incomplete(report, limit.metric),
            )
            for limit in policy.limits
        ),
    )
