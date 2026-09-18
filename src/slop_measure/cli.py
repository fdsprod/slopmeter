"""Command-line navigation through one immutable analysis report."""

import os
import shutil
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from slop_measure.api import compare, scan
from slop_measure.config import load_analysis_config
from slop_measure.domain.reports import AnalysisReport
from slop_measure.domain.requests import ComparisonRequest, SnapshotRequest
from slop_measure.domain.source import DirectorySourceReference
from slop_measure.errors import AnalysisFailure, InvalidRuleSelection, SelectionError
from slop_measure.reporting import terminal
from slop_measure.reporting.comparison import render_comparison
from slop_measure.reporting.json import serialize_report
from slop_measure.reporting.queries import select_callable, select_file

_DESCRIPTION = "Measure redundant and structurally eroded source code."
app = typer.Typer(name="slop", help=f"slop.measure - {_DESCRIPTION}", no_args_is_help=True)


@app.callback()
def root() -> None:
    """Initialize the root command."""


class _Scope(StrEnum):
    PRODUCTION = "production"
    TEST = "test"
    ALL = "all"


class _Color(StrEnum):
    AUTO = "auto"
    ALWAYS = "always"
    NEVER = "never"


@dataclass(frozen=True)
class _Display:
    """Resolved terminal settings, independent of analysis configuration."""

    color: bool
    ascii: bool
    verbose: bool
    top: int | None
    width: int


def _display(
    color: _Color, no_color: bool, ascii: bool, verbose: bool, top: int | None
) -> _Display:
    if no_color and color is _Color.ALWAYS:
        raise typer.BadParameter("--color always conflicts with --no-color")
    enabled = not no_color and (
        color is _Color.ALWAYS
        or (color is _Color.AUTO and "NO_COLOR" not in os.environ and sys.stdout.isatty())
    )
    return _Display(enabled, ascii, verbose, top, shutil.get_terminal_size().columns)


def _scan_report(path: Path, strict: bool | None) -> AnalysisReport:
    try:
        overrides = {"strict": strict} if strict is not None else {}
        config = load_analysis_config(path, cli_overrides=overrides)
        request = SnapshotRequest(target=DirectorySourceReference(root=path), config=config)
    except (ValueError, OSError) as error:
        typer.echo(f"Invalid analysis input: {error}", err=True)
        raise typer.Exit(2) from error
    return _analyze(request)


def _analyze(request: SnapshotRequest | ComparisonRequest) -> AnalysisReport:
    try:
        return scan(request) if isinstance(request, SnapshotRequest) else compare(request)
    except InvalidRuleSelection as error:
        typer.echo(f"Invalid analysis input: {error}", err=True)
        raise typer.Exit(2) from error
    except AnalysisFailure as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(3) from error
    except Exception as error:
        typer.echo(f"Analysis failed: {type(error).__name__}", err=True)
        raise typer.Exit(3) from error


_Directory = Annotated[Path, typer.Argument(exists=True, file_okay=False, resolve_path=True)]
_Json = Annotated[bool, typer.Option("--json", help="Emit the complete JSON report.")]
_Strict = Annotated[bool | None, typer.Option("--strict", help="Stop on analysis errors.")]
_ColorOption = Annotated[_Color, typer.Option("--color", help="Choose auto, always, or never.")]
_NoColor = Annotated[bool, typer.Option("--no-color", help="Disable terminal colors.")]
_Ascii = Annotated[bool, typer.Option("--ascii", help="Use plain bars and tree connectors.")]
_Verbose = Annotated[bool, typer.Option("--verbose", help="Show counts, evidence, and provenance.")]
_Top = Annotated[int | None, typer.Option("--top", min=1, help="Limit terminal file rows.")]


def _compare_report(baseline: Path, current: Path, strict: bool | None) -> AnalysisReport:
    try:
        config = load_analysis_config(
            current, cli_overrides={"strict": strict} if strict is not None else {}
        )
        request = ComparisonRequest(
            baseline=DirectorySourceReference(root=baseline),
            current=DirectorySourceReference(root=current),
            config=config,
        )
    except (ValueError, OSError) as error:
        typer.echo(f"Invalid analysis input: {error}", err=True)
        raise typer.Exit(2) from error
    return _analyze(request)


@app.command("compare")
# Source selection and terminal controls are independent public options.
def compare_command(  # noqa: PLR0913
    baseline: _Directory,
    current: _Directory,
    *,
    json_output: _Json = False,
    strict: _Strict = None,
    scope: Annotated[
        _Scope, typer.Option(help="Select terminal results; JSON stays complete.")
    ] = _Scope.PRODUCTION,
    color: _ColorOption = _Color.AUTO,
    no_color: _NoColor = False,
    ascii: _Ascii = False,
    verbose: _Verbose = False,
    top: _Top = None,
) -> None:
    """Compare two directories under the current directory's analysis settings."""
    display = _display(color, no_color, ascii, verbose, top)
    report = _compare_report(baseline, current, strict)
    output = (
        serialize_report(report)
        if json_output
        else render_comparison(
            report,
            scope=scope.value,
            width=display.width,
            color=display.color,
            ascii=display.ascii,
            verbose=display.verbose,
            top=display.top,
        )
    )
    typer.echo(output, nl=False, color=display.color)


@app.command("score")
@app.command("scan")
@app.command("tree")
# Each option controls a distinct user-visible CLI setting.
def scan_command(  # noqa: PLR0913
    context: typer.Context,
    path: _Directory = Path("."),
    *,
    json_output: _Json = False,
    strict: _Strict = None,
    scope: Annotated[
        _Scope, typer.Option(help="Select terminal results; JSON stays complete.")
    ] = _Scope.PRODUCTION,
    color: _ColorOption = _Color.AUTO,
    no_color: _NoColor = False,
    ascii: _Ascii = False,
    verbose: _Verbose = False,
    top: _Top = None,
) -> None:
    """Inspect snapshot measurements and file evidence."""
    display = _display(color, no_color, ascii, verbose, top)
    report = _scan_report(path, strict)
    if json_output:
        typer.echo(serialize_report(report), nl=False)
        return
    renderer = terminal.render_tree if context.command.name == "tree" else terminal.render_snapshot
    output = renderer(
        report,
        scope=scope.value,
        width=display.width,
        color=display.color,
        ascii=display.ascii,
        verbose=display.verbose,
        top=display.top,
    )
    typer.echo(output, nl=False, color=display.color)


def _relative_selector(root: Path, selector: str) -> str:
    try:
        return (
            (root / Path(selector.replace("\\", "/")))
            .resolve()
            .relative_to(root.resolve())
            .as_posix()
        )
    except ValueError as error:
        raise SelectionError("Selected file must be inside the analysis root.") from error


@app.command("explain")
# File selection and terminal options are independent user inputs.
def explain_command(  # noqa: PLR0913
    file: Annotated[str, typer.Argument(help="File inside the analysis root.")],
    *,
    root_path: Annotated[
        Path, typer.Option("--root", exists=True, file_okay=False, resolve_path=True)
    ] = Path("."),
    symbol: Annotated[
        str | None, typer.Option("--symbol", help="Exact qualified callable name.")
    ] = None,
    line: Annotated[
        int | None, typer.Option("--line", min=1, help="Callable definition start line.")
    ] = None,
    json_output: _Json = False,
    strict: _Strict = None,
    color: _ColorOption = _Color.AUTO,
    no_color: _NoColor = False,
    ascii: _Ascii = False,
    verbose: _Verbose = False,
) -> None:
    """Explain one file or callable using its existing source evidence."""
    display = _display(color, no_color, ascii, verbose, None)
    try:
        if line is not None and symbol is None:
            raise SelectionError("--line requires --symbol.")
        path = _relative_selector(root_path, file)
        report = _scan_report(root_path, strict)
        selected = select_file(report, path)
        if symbol is not None:
            select_callable(selected, symbol, line=line)
        output = (
            serialize_report(report)
            if json_output
            else terminal.render_explanation(
                report,
                path,
                symbol=symbol,
                line=line,
                width=display.width,
                color=display.color,
                ascii=display.ascii,
                verbose=display.verbose,
            )
        )
    except SelectionError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    typer.echo(output, nl=False, color=display.color)


def main() -> None:
    """Run the command-line application."""
    app()
