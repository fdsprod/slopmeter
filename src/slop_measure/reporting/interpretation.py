"""Render the report-owned guide without inferring findings from score values."""

from rich.console import Console

from slop_measure.domain.interpretation import ReportInterpretation


def render_interpretation(console: Console, guide: ReportInterpretation, *, verbose: bool) -> None:
    """Keep a concise interpretation in every view and expand the same owned guide."""
    console.print()
    console.print("How to read this report", style="bold")
    console.print(guide.purpose)
    console.print(guide.score_meaning)
    if verbose:
        for meaning in guide.metric_meanings:
            console.print("  " + meaning)
    for limitation in guide.limitations if verbose else guide.limitations[:2]:
        console.print(limitation)
    if verbose:
        for step in guide.review_steps:
            console.print("  " + step)
    console.print(guide.disposition_template)
    if not verbose:
        console.print("Use --verbose or --json for metric definitions and the full review guide.")
