"""Explicit saved-report review operations with an attributed history."""

import json
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from slop_measure.application.review_workflow import (
    load_review_ledger,
    load_review_report,
    resolve_reviews,
    review_targets,
    write_review,
)
from slop_measure.domain.review_workflow import ReviewKind
from slop_measure.domain.reviews import ReviewDisposition
from slop_measure.domain.source import Cohort
from slop_measure.errors import InputError, error_message
from slop_measure.reporting.review_selection import select_review_targets
from slop_measure.reporting.review_workflow import render_review_resolution, render_review_targets

app = typer.Typer(
    help="Retain attributed decisions against saved native reports.", no_args_is_help=True
)
_Report = Annotated[
    Path, typer.Option("--report", help="Saved score/models/variants/derived/errors JSON.")
]
_Store = Annotated[Path, typer.Option("--store", help="One explicit review ledger per project.")]
_Json = Annotated[bool, typer.Option("--json", help="Write complete JSON evidence.")]


def _fail(error: Exception) -> NoReturn:
    typer.echo(error_message(InputError(str(error))), err=True)
    raise typer.Exit(2)


@app.command("list")
def list_targets(
    *,
    report: _Report,
    kind: Annotated[
        list[ReviewKind] | None,
        typer.Option("--kind", help="Select an evidence kind. Repeat to include multiple kinds."),
    ] = None,
    cohort: Annotated[
        Cohort | None, typer.Option("--cohort", help="Select the saved source cohort.")
    ] = None,
    hotspots_only: Annotated[
        bool,
        typer.Option(
            "--hotspots-only", help="Select complexity above the saved M4 threshold and basis."
        ),
    ] = False,
    json_output: _Json = False,
) -> None:
    """List evidence available for review in a saved report; do not scan source."""
    try:
        saved = load_review_report(report)
        targets = select_review_targets(
            saved,
            review_targets(saved),
            kinds=frozenset(kind or ()),
            cohort=cohort,
            hotspots_only=hotspots_only,
        )
    except (ValueError, OSError) as error:
        _fail(error)
    if json_output:
        typer.echo(
            json.dumps(
                {"targets": [item.model_dump(mode="json") for item in targets]},
                indent=2,
                ensure_ascii=True,
            )
        )
    else:
        typer.echo(render_review_targets(targets), nl=False)


@app.command("set")
def set_review(  # noqa: PLR0913 - independent source, identity, attribution, and review text
    target: str,
    *,
    report: _Report,
    store: _Store,
    actor: Annotated[
        str, typer.Option("--actor", help="Explicit reviewer identity; never inferred.")
    ],
    disposition: Annotated[ReviewDisposition, typer.Option("--disposition")],
    reason: Annotated[str, typer.Option("--reason")],
    next_step: Annotated[str, typer.Option("--next-step")] = "",
    review: Annotated[
        str | None, typer.Option("--review", help="Existing compatible history ID.")
    ] = None,
    supersedes: Annotated[
        str | None,
        typer.Option(
            "--supersedes", help="Legacy clone decision ID explicitly replaced by this judgment."
        ),
    ] = None,
) -> None:
    """Append an explicit decision. Preserve earlier decisions and measured facts."""
    try:
        ledger = write_review(
            store,
            load_review_report(report),
            target,
            actor=actor,
            disposition=disposition,
            reason=reason,
            next_step=next_step,
            review_id=review,
            supersedes_legacy_id=supersedes,
        )
    except (ValueError, OSError) as error:
        _fail(error)
    event = ledger.events[-1]
    typer.echo(
        f"Saved {disposition.value} for {event.review_id} in {store}. "
        f"Event {event.sequence}, actor {event.actor}, {event.recorded_at.isoformat()}.\n"
        "This decision uses the saved report. Findings and scores are unchanged."
    )


@app.command("show")
def show_reviews(*, report: _Report, store: _Store, json_output: _Json = False) -> None:
    """Resolve history against a saved report without writing the ledger or rescanning."""
    try:
        result = resolve_reviews(load_review_report(report), load_review_ledger(store))
    except (ValueError, OSError) as error:
        _fail(error)
    typer.echo(
        result.model_dump_json(indent=2) if json_output else render_review_resolution(result),
        nl=json_output,
    )
