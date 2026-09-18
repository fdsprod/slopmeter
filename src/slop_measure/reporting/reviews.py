"""Display saved judgments separately from measured evidence."""

from rich.console import Console

from slop_measure.domain.reviews import CloneReviewResult


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
        elif result.state == "missing":
            console.print("    Evidence absent or unavailable. This is not proof of a fix.")
        else:
            console.print(f"    Matches current group: {result.group_id}")
