"""Present unscored changes and unresolved evidence without inventing a risk score."""

from typing import assert_never

from slop_measure.domain.change_review import (
    ChangedPattern,
    ChangeReviewReport,
    IntroducedPattern,
    PersistedPattern,
    RemovedPattern,
    UnresolvedPatterns,
)
from slop_measure.domain.clone_changes import CloneGroupState
from slop_measure.domain.error_changes import (
    ChangedError,
    IntroducedError,
    PersistedError,
    RemovedError,
    UnresolvedErrors,
)
from slop_measure.domain.state_dispatch import (
    ChangedStateDispatch,
    IntroducedStateDispatch,
    PersistedStateDispatch,
    RemovedStateDispatch,
    UnresolvedStateDispatch,
)
from slop_measure.reporting.comparison import _identity


def _patterns(report: ChangeReviewReport) -> list[str]:
    lines = ["Patterns: " + ", ".join(f"{key} {value}" for key, value in report.summary.items())]
    for change in report.patterns:
        if isinstance(change, PersistedPattern):
            continue
        if isinstance(change, UnresolvedPatterns):
            occurrences = (*change.baseline, *change.current)
            lines.append(f"  unresolved: {change.reason}")
        elif isinstance(change, RemovedPattern):
            occurrences = (change.baseline,)
        elif isinstance(change, IntroducedPattern | ChangedPattern):
            occurrences = (change.current,)
        else:
            assert_never(change)
        for occurrence in occurrences:
            item = occurrence.finding
            lines.append(
                f"  {change.state}: {item.path.root}:{item.span.start_line} {item.rule_id}"
            )
    lines.extend(f"  limitation: {item.reason}" for item in report.limitations)
    return lines


def _clones(report: ChangeReviewReport) -> list[str]:
    lines = [
        f"Clone groups: {len(report.clones)}; added members: {sum(g.added for g in report.clones)}"
    ]
    for group in report.clones:
        if group.state is CloneGroupState.PERSISTED:
            continue
        lines.append(
            f"  {group.state}: {group.fingerprint[:12]} +{group.added} / -{group.removed} members"
            f"; modified {group.modified}"
        )
        if group.baseline_fingerprint and group.current_fingerprint and group.modified:
            lines.append(
                f"    normalization: {group.baseline_fingerprint[:12]}"
                f" -> {group.current_fingerprint[:12]}"
            )
        for occurrence in (*group.baseline, *group.current):
            lines.append(f"    {occurrence.member.path.root}:{occurrence.member.span.start_line}")
    return lines


def _errors(report: ChangeReviewReport) -> list[str]:
    lines = [
        "Exception fallbacks: "
        + ", ".join(f"{key} {value}" for key, value in report.error_summary.items())
    ]
    for error in report.errors:
        if isinstance(error, PersistedError):
            continue
        if isinstance(error, UnresolvedErrors):
            occurrences = (*error.baseline, *error.current)
            lines.append(f"  unresolved: {error.reason}")
        elif isinstance(error, RemovedError):
            occurrences = (error.baseline,)
        elif isinstance(error, IntroducedError | ChangedError):
            occurrences = (error.current,)
        else:
            assert_never(error)
        for item in occurrences:
            lines.append(f"  {error.state}: {item.path.root}:{item.span.start_line} {item.symbol}")
    if report.errors:
        lines.append(
            "Fallbacks are review candidates. Check the caller contract; "
            "an empty result can be intentional."
        )
    return lines


def _state_dispatch(report: ChangeReviewReport) -> list[str]:
    lines = [
        "Literal state-field comparisons: "
        + ", ".join(f"{key} {value}" for key, value in report.state_dispatch_summary.items())
    ]
    for change in report.state_dispatch:
        if isinstance(change, PersistedStateDispatch):
            continue
        if isinstance(change, UnresolvedStateDispatch):
            occurrences = (*change.baseline, *change.current)
            lines.append(f"  unresolved: {change.reason}")
        elif isinstance(change, RemovedStateDispatch):
            occurrences = (change.baseline,)
        elif isinstance(change, IntroducedStateDispatch | ChangedStateDispatch):
            occurrences = (change.current,)
        else:
            assert_never(change)
        for item in occurrences:
            lines.append(
                f"  {change.state}: {item.path.root}:{item.span.start_line} "
                f"{item.subject} {item.operator} {item.values!r} ({item.context})"
            )
    if report.state_dispatch:
        lines.extend(report.state_dispatch_interpretation)
    return lines


def render_change_review(report: ChangeReviewReport) -> str:
    lines = [
        "slop.measure  change review (unscored)",
        f"Baseline: {_identity(report.analysis.baseline)}",
        f"Current: {_identity(report.analysis.current)}",
        *_patterns(report),
        *_clones(report),
        *_errors(report),
        *_state_dispatch(report),
    ]
    return "\n".join(lines) + "\n"
