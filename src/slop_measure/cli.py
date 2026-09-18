"""Command-line entry point for slop.measure."""

import os
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from slop_measure.api import scan
from slop_measure.config import load_analysis_config
from slop_measure.domain.requests import SnapshotRequest
from slop_measure.domain.source import DirectorySourceReference
from slop_measure.errors import AnalysisFailure
from slop_measure.reporting.json import serialize_report
from slop_measure.reporting.terminal import render_snapshot

_DESCRIPTION = "Measure redundant and structurally eroded source code."

app = typer.Typer(
    name="slop",
    help=f"slop.measure - {_DESCRIPTION}",
    no_args_is_help=True,
)


@app.callback()
def root() -> None:
    """Initialize the root command."""


class _Scope(StrEnum):
    PRODUCTION = "production"
    TEST = "test"
    ALL = "all"


@app.command("scan")
def scan_command(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=False, resolve_path=True)] = Path(
        "."
    ),
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the complete JSON report.")
    ] = False,
    strict: Annotated[
        bool | None, typer.Option("--strict", help="Stop on parse or analyzer errors.")
    ] = None,
    scope: Annotated[
        _Scope, typer.Option(help="Select terminal results; JSON stays complete.")
    ] = _Scope.PRODUCTION,
    no_color: Annotated[bool, typer.Option("--no-color", help="Disable terminal colors.")] = False,
) -> None:
    """Scan a Python directory for raw source coverage and analysis diagnostics."""
    try:
        overrides = {"strict": strict} if strict is not None else {}
        config = load_analysis_config(path, cli_overrides=overrides)
        request = SnapshotRequest(target=DirectorySourceReference(root=path), config=config)
    except (ValueError, OSError) as error:
        typer.echo(f"Invalid analysis input: {error}", err=True)
        raise typer.Exit(2) from error
    try:
        report = scan(request)
    except AnalysisFailure as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(3) from error
    except Exception as error:
        typer.echo(f"Analysis failed: {type(error).__name__}", err=True)
        raise typer.Exit(3) from error
    if json_output:
        typer.echo(serialize_report(report), nl=False)
    else:
        color = not no_color and "NO_COLOR" not in os.environ and sys.stdout.isatty()
        typer.echo(render_snapshot(report, scope=scope.value, color=color), nl=False, color=color)


def main() -> None:
    """Run the command-line application."""
    app()
