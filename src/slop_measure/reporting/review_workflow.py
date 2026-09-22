"""Saved review state, attribution, and precise anchor differences."""

from slop_measure.domain.review_workflow import (
    LegacyReviewResult,
    ReviewAnchor,
    ReviewResolutionReport,
    ReviewSubject,
    ReviewTarget,
    ReviewTargetChange,
)

_SAVED_NOTICE = (
    "This view describes the saved report, not the current checkout. "
    "Generate a fresh report to check current code. Findings and scores are unchanged."
)


def _locations(subject: ReviewSubject) -> str:
    return ", ".join(
        f"{item.path.root}:{item.span.start_line}-{item.span.end_line}"
        for item in subject.locations
    )


def render_review_targets(targets: tuple[ReviewTarget, ...]) -> str:
    lines = [
        f"Saved-report reviewable evidence ({len(targets)})",
        "This is an evidence count, not a finding count, defect count, or hotspot count.",
        _SAVED_NOTICE,
    ]
    for target in targets:
        subject = target.anchor.subject if target.state == "reviewable" else target.subject
        lines.extend(
            (
                f"  {target.id} | {target.state}",
                f"    {subject.kind.value}: {subject.symbol} | {_locations(subject)}",
            )
        )
        if target.state == "unavailable":
            lines.append(f"    Reason: {target.reason}")
    return "\n".join(lines) + "\n"


def _change_lines(previous: ReviewAnchor, change: ReviewTargetChange) -> list[str]:
    lines = [f"    Candidate {change.target_id}: {', '.join(change.causes)}"]
    candidate = change.candidate
    if candidate.state == "unavailable":
        lines.append(f"      Current evidence unavailable: {candidate.reason}")
        return lines
    current = candidate.anchor
    old_hashes = {item.path.root: item.sha256 for item in previous.source_hashes}
    for item in current.source_hashes:
        before = old_hashes.get(item.path.root)
        if before != item.sha256:
            lines.append(f"      Source {item.path.root}: {before} -> {item.sha256}")
    if previous.subject != current.subject:
        lines.extend(
            (
                f"      Previous locations: {_locations(previous.subject)}",
                f"      Current locations: {_locations(current.subject)}",
                f"      Evidence: {previous.subject.evidence_fingerprint} -> "
                f"{current.subject.evidence_fingerprint}",
            )
        )
    if previous.boundary != current.boundary:
        lines.extend(
            (
                f"      Previous ownership: {previous.boundary.model_dump_json()}",
                f"      Current ownership: {current.boundary.model_dump_json()}",
            )
        )
    if previous.analysis_fingerprint != current.analysis_fingerprint:
        lines.append(
            f"      Analysis: {previous.analysis_fingerprint} -> {current.analysis_fingerprint}"
        )
    return lines


def _legacy_lines(result: LegacyReviewResult) -> list[str]:
    lines = [
        f"  Legacy {result.decision.id} | {result.state} | "
        f"{result.decision.disposition.value}: {result.decision.reason}"
    ]
    if result.state == "not-in-selected-report":
        lines.append(
            "    This family is not assessed by the selected report, not absent from source."
        )
    elif result.state == "superseded":
        lines.append(
            f"    Replaced by history {result.review_id} at event {result.sequence}; "
            "check the replacement's current applicability above."
        )
    return lines


def render_review_resolution(report: ReviewResolutionReport) -> str:
    lines = ["Saved-report review decisions", _SAVED_NOTICE]
    for result in report.results:
        event = result.event
        decision = event.decision
        lines.extend(
            (
                f"  {event.review_id} | {result.state} | {decision.disposition.value}",
                f"    {decision.anchor.subject.kind.value}: {decision.anchor.subject.symbol} "
                f"| {_locations(decision.anchor.subject)}",
                f"    Actor: {event.actor} | UTC: {event.recorded_at.isoformat()} "
                f"| Event {event.sequence}",
                f"    Reason: {decision.reason}",
                f"    Next step: {decision.next_step or 'not supplied'}",
            )
        )
        if result.state == "stale":
            for change in result.changes:
                lines.extend(_change_lines(decision.anchor, change))
        elif result.state == "missing":
            lines.append(f"    {result.reason}; missing evidence does not establish a fix.")
        elif result.state == "not-in-selected-report":
            lines.append(
                "    This family is not assessed by the selected report, not absent from source."
            )
    for result in report.legacy_results:
        lines.extend(_legacy_lines(result))
    lines.append(f"History ({len(report.events)} events):")
    for event in report.events:
        lines.append(
            f"  {event.sequence}: {event.review_id} | {event.actor} | "
            f"{event.recorded_at.isoformat()} | {event.decision.disposition.value}: "
            f"{event.decision.reason} | Next: {event.decision.next_step or 'not supplied'}"
        )
        if event.supersedes_legacy_id is not None:
            lines.append(f"    Explicitly supersedes legacy decision {event.supersedes_legacy_id}.")
    return "\n".join(lines) + "\n"
