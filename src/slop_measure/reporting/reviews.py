"""Display saved judgments separately from measured evidence."""

from typing import assert_never

from rich.console import Console

from slop_measure.domain.reviews import CloneReviewCause, CloneReviewResult


def _cause_text(cause: CloneReviewCause) -> str:
    if cause.kind == "source-changed":
        return f"Source changed: {cause.path.root}"
    if cause.kind == "source-unavailable":
        return f"Source hash unavailable: {cause.path.root}"
    if cause.kind == "clone-evidence-changed":
        return "Clone evidence changed: " + ", ".join(cause.fields)
    if cause.kind == "boundary-policy-changed":
        return "Boundary policy changed."
    if cause.kind == "analysis-definition-changed":
        return "Analysis definition changed."
    if cause.kind == "analysis-unavailable":
        return "Analysis definition unavailable."
    assert_never(cause)


def render_review_results(console: Console, results: tuple[CloneReviewResult, ...]) -> None:
    if not results:
        return
    console.print()
    console.print("Clone reviews (current snapshot; findings and scores unchanged)")
    for result in results:
        decision = result.decision
        console.print(f"  {decision.id} | {result.state} | {decision.disposition.value}")
        console.print(f"    Reason: {decision.reason}")
        if decision.next_step:
            console.print(f"    Next: {decision.next_step}")
        if result.state == "stale":
            console.print("    Re-review required. The previous decision is not current.")
            console.print("    Candidate groups: " + ", ".join(result.candidate_group_ids))
            if not result.changes:
                console.print("    Change details were not recorded in this report.")
            for change in result.changes:
                console.print(f"    Changes for {change.group_id}:")
                for cause in change.causes:
                    console.print(f"      {_cause_text(cause)}")
        elif result.state == "missing":
            console.print("    Evidence absent or unavailable. This is not proof of a fix.")
        else:
            console.print(f"    Matches current group: {result.group_id}")
