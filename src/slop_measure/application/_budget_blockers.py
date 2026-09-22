"""Keep missing assessment locations separate from measured introductions."""

from slop_measure.domain.budgets import (
    BudgetBlocker,
    BudgetMetric,
    PopulationBudgetBlocker,
    SourceBudgetBlocker,
)
from slop_measure.domain.change_review import ChangeReviewReport, UnresolvedPatterns
from slop_measure.domain.clone_changes import UnresolvedCloneMembers
from slop_measure.domain.error_changes import UnresolvedErrors
from slop_measure.domain.error_review import (
    AnalyzedErrorFile,
    FailedErrorFile,
    UnresolvedErrorHandler,
)
from slop_measure.domain.evidence import Diagnostic, DiagnosticSeverity
from slop_measure.domain.reports import SourceSide


def _diagnostic(detail: Diagnostic, side: SourceSide) -> BudgetBlocker:
    if detail.path is not None:
        return SourceBudgetBlocker(
            code="analysis-error",
            message=detail.message,
            side=side,
            path=detail.path,
            span=detail.span,
        )
    return PopulationBudgetBlocker(code="analysis-error", message=detail.message, side=side)


def _pattern_blockers(report: ChangeReviewReport) -> list[BudgetBlocker]:
    return [
        SourceBudgetBlocker(
            code="unresolved-pattern",
            message=change.reason,
            side=side,
            path=item.finding.path,
            span=item.finding.span,
        )
        for change in report.patterns
        if isinstance(change, UnresolvedPatterns)
        for side, occurrences in (
            (SourceSide.BASELINE, change.baseline),
            (SourceSide.CURRENT, change.current),
        )
        for item in occurrences
    ]


def _clone_blockers(report: ChangeReviewReport) -> list[BudgetBlocker]:
    return [
        SourceBudgetBlocker(
            code="unresolved-clone",
            message=change.reason,
            side=side,
            path=item.member.path,
            span=item.member.span,
        )
        for group in report.clones
        for change in group.members
        if isinstance(change, UnresolvedCloneMembers)
        for side, occurrences in (
            (SourceSide.BASELINE, change.baseline),
            (SourceSide.CURRENT, change.current),
        )
        for item in occurrences
    ]


def _error_blockers(report: ChangeReviewReport) -> list[BudgetBlocker]:
    return [
        SourceBudgetBlocker(
            code="unresolved-error",
            message=change.reason,
            side=side,
            path=item.path,
            span=item.span,
        )
        for change in report.errors
        if isinstance(change, UnresolvedErrors)
        for side, occurrences in (
            (SourceSide.BASELINE, change.baseline),
            (SourceSide.CURRENT, change.current),
        )
        for item in occurrences
    ]


def incomplete_details(
    report: ChangeReviewReport, metric: BudgetMetric
) -> tuple[BudgetBlocker, ...]:
    """Unchanged unsupported evidence remains incomplete, with no inferred safety."""
    details: list[BudgetBlocker] = [
        PopulationBudgetBlocker(
            code="analysis-limitation",
            message=f"{item.language}/{item.cohort}: "
            + (f"{item.path.root} (source side unavailable): " if item.path else "")
            + item.reason,
        )
        for item in report.limitations
    ]
    details.extend(
        _diagnostic(item.detail, item.source)
        for item in report.diagnostics
        if item.detail.severity is DiagnosticSeverity.ERROR
    )
    details.extend(
        {
            BudgetMetric.INTRODUCED_PATTERNS: _pattern_blockers,
            BudgetMetric.ADDED_CLONE_MEMBERS: _clone_blockers,
            BudgetMetric.INTRODUCED_ERRORS: _error_blockers,
        }[metric](report)
    )
    if metric is BudgetMetric.INTRODUCED_ERRORS:
        for coverage in report.error_coverage:
            file = coverage.detail
            if isinstance(file, FailedErrorFile):
                details.append(_diagnostic(file.diagnostic, coverage.source))
            elif isinstance(file, AnalyzedErrorFile):
                details.extend(
                    SourceBudgetBlocker(
                        code="unsupported-handler",
                        message=handler.reason,
                        side=coverage.source,
                        path=file.path,
                        span=handler.span,
                    )
                    for handler in file.handlers
                    if isinstance(handler, UnresolvedErrorHandler)
                )
    unique = {item.model_dump_json(): item for item in details}
    return tuple(unique[key] for key in sorted(unique))
