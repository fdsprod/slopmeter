"""Command-line navigation through one immutable analysis report."""

import json
import os
import shutil
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from slop_measure.api import compare, scan
from slop_measure.application.catalog import rule_catalog
from slop_measure.application.reviews import apply_reviews, load_review_store, write_clone_review
from slop_measure.config import load_analysis_config
from slop_measure.domain.evidence import DiagnosticSeverity
from slop_measure.domain.reports import AnalysisReport, SourceSide
from slop_measure.domain.requests import ComparisonRequest, SnapshotRequest
from slop_measure.domain.reviews import ReviewDisposition
from slop_measure.domain.source import DirectorySourceReference, GitSourceReference
from slop_measure.errors import InputError, InvalidSource, SelectionError, error_message, exit_code
from slop_measure.reporting import terminal
from slop_measure.reporting.comparison import render_comparison
from slop_measure.reporting.evidence import render_findings, render_rules
from slop_measure.reporting.json import serialize_report
from slop_measure.reporting.queries import query_findings, select_callable, select_file

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
    try:
        "\u2588\u2591\u00b7\u2014\u2514\u2500\u251c\u2502".encode(sys.stdout.encoding or "ascii")
    except (UnicodeEncodeError, LookupError):
        ascii = True
    return _Display(enabled, ascii, verbose, top, shutil.get_terminal_size().columns)


def _overrides(strict: bool | None, languages: list[str] | None) -> dict[str, object]:
    overrides: dict[str, object] = {"strict": strict} if strict is not None else {}
    if languages:
        selectors = [part.strip() for value in languages for part in value.split(",")]
        if any(not selector for selector in selectors):
            raise InputError("--lang requires nonempty language names.")
        overrides["languages"] = frozenset(selectors)
    return overrides


def _scan_report(
    path: Path,
    strict: bool | None,
    revision: str | None = None,
    languages: list[str] | None = None,
) -> AnalysisReport:
    try:
        config = load_analysis_config(path, cli_overrides=_overrides(strict, languages))
        target = (
            DirectorySourceReference(root=path)
            if revision is None
            else GitSourceReference(root=path, revision=revision)
        )
        request = SnapshotRequest(target=target, config=config)
    except (ValueError, OSError) as error:
        _fail(InputError(str(error)))
    return _analyze(request)


def _fail(error: Exception) -> NoReturn:
    typer.echo(error_message(error), err=True)
    raise typer.Exit(exit_code(error)) from error


def _analyze(request: SnapshotRequest | ComparisonRequest) -> AnalysisReport:
    try:
        return scan(request) if isinstance(request, SnapshotRequest) else compare(request)
    except Exception as error:
        _fail(error)


_Directory = Annotated[Path, typer.Argument(exists=True, file_okay=False, resolve_path=True)]
_Json = Annotated[bool, typer.Option("--json", help="Emit the complete JSON report.")]
_Strict = Annotated[bool | None, typer.Option("--strict", help="Stop on analysis errors.")]
_Languages = Annotated[
    list[str] | None,
    typer.Option(
        "--lang",
        "--langs",
        help="Languages or extensions, comma-separated or repeated (py, python).",
    ),
]
_ColorOption = Annotated[_Color, typer.Option("--color", help="Choose auto, always, or never.")]
_NoColor = Annotated[bool, typer.Option("--no-color", help="Disable terminal colors.")]
_Ascii = Annotated[bool, typer.Option("--ascii", help="Use plain bars and tree connectors.")]
_Verbose = Annotated[bool, typer.Option("--verbose", help="Show counts, evidence, and provenance.")]
_Top = Annotated[int | None, typer.Option("--top", min=1, help="Limit terminal file rows.")]
_Root = Annotated[Path, typer.Option("--root", exists=True, file_okay=False, resolve_path=True)]
_Reviews = Annotated[
    Path | None,
    typer.Option("--reviews", help="Read a clone review store without changing scores."),
]
_Revision = Annotated[str | None, typer.Option("--rev", help="Read the current Git revision.")]
_BaselineRoot = Annotated[
    Path | None, typer.Option("--baseline-root", exists=True, file_okay=False, resolve_path=True)
]
_BaselineRevision = Annotated[
    str | None, typer.Option("--baseline-rev", help="Compare with this Git revision.")
]
_Source = Annotated[
    SourceSide, typer.Option("--source", help="Select baseline or current evidence.")
]


def _evidence_report(  # noqa: PLR0913 - source selection and configuration are independent
    root: Path,
    strict: bool | None,
    revision: str | None,
    baseline_root: Path | None,
    baseline_revision: str | None,
    *,
    languages: list[str] | None = None,
) -> AnalysisReport:
    if baseline_root is not None and baseline_revision is not None:
        raise SelectionError("Use only one of --baseline-root and --baseline-rev.")
    if baseline_root is None and baseline_revision is None:
        return _scan_report(root, strict, revision, languages)
    try:
        config = load_analysis_config(root, cli_overrides=_overrides(strict, languages))
        current = (
            DirectorySourceReference(root=root)
            if revision is None
            else GitSourceReference(root=root, revision=revision)
        )
        baseline = (
            DirectorySourceReference(root=baseline_root)
            if baseline_root is not None
            else GitSourceReference(root=root, revision=baseline_revision or "")
        )
        request = ComparisonRequest(baseline=baseline, current=current, config=config)
    except (ValueError, OSError) as error:
        raise SelectionError(str(error)) from error
    return _analyze(request)


def _compare_report(
    baseline: str,
    current: str,
    strict: bool | None,
    repo: Path | None = None,
    languages: list[str] | None = None,
) -> AnalysisReport:
    try:
        if repo is None:
            roots = (Path(baseline).resolve(), Path(current).resolve())
            if not all(root.is_dir() for root in roots):
                raise InvalidSource("Comparison directories must exist.")
            before = DirectorySourceReference(root=roots[0])
            after = DirectorySourceReference(root=roots[1])
        else:
            before = GitSourceReference(root=repo, revision=baseline)
            after = (
                DirectorySourceReference(root=repo)
                if current == "WORKTREE"
                else GitSourceReference(root=repo, revision=current)
            )
        config = load_analysis_config(after.root, cli_overrides=_overrides(strict, languages))
        request = ComparisonRequest(
            baseline=before,
            current=after,
            config=config,
        )
    except (ValueError, OSError) as error:
        _fail(InputError(str(error)))
    return _analyze(request)


@app.command("compare")
# Source selection and terminal controls are independent public options.
def compare_command(  # noqa: PLR0913
    baseline: str,
    current: str,
    *,
    repo: Annotated[
        Path | None, typer.Option("--repo", exists=True, file_okay=False, resolve_path=True)
    ] = None,
    json_output: _Json = False,
    strict: _Strict = None,
    languages: _Languages = None,
    scope: Annotated[
        _Scope, typer.Option(help="Select terminal results; JSON stays complete.")
    ] = _Scope.PRODUCTION,
    color: _ColorOption = _Color.AUTO,
    no_color: _NoColor = False,
    ascii: _Ascii = False,
    verbose: _Verbose = False,
    top: _Top = None,
) -> None:
    """Compare directories, or Git revisions with --repo."""
    display = _display(color, no_color, ascii, verbose, top)
    report = _compare_report(baseline, current, strict, repo, languages)
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
    revision: Annotated[str | None, typer.Option("--rev", help="Read a Git revision.")] = None,
    reviews: _Reviews = None,
    json_output: _Json = False,
    strict: _Strict = None,
    languages: _Languages = None,
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
    report = _review_report(_scan_report(path, strict, revision, languages), reviews)
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
    root_path: _Root = Path("."),
    revision: _Revision = None,
    baseline_root: _BaselineRoot = None,
    baseline_revision: _BaselineRevision = None,
    source: _Source = SourceSide.CURRENT,
    symbol: Annotated[
        str | None, typer.Option("--symbol", help="Exact qualified callable name.")
    ] = None,
    line: Annotated[
        int | None, typer.Option("--line", min=1, help="Callable definition start line.")
    ] = None,
    json_output: _Json = False,
    strict: _Strict = None,
    languages: _Languages = None,
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
        selector_root = (
            baseline_root if source is SourceSide.BASELINE and baseline_root else root_path
        )
        path = _relative_selector(selector_root, file)
        report = _evidence_report(
            root_path, strict, revision, baseline_root, baseline_revision, languages=languages
        )
        selected = select_file(report, path, source=source)
        if symbol is not None:
            select_callable(selected, symbol, line=line)
        output = (
            serialize_report(report)
            if json_output
            else terminal.render_explanation(
                report,
                path,
                source=source,
                symbol=symbol,
                line=line,
                width=display.width,
                color=display.color,
                ascii=display.ascii,
                verbose=display.verbose,
            )
        )
    except SelectionError as error:
        _fail(error)
    typer.echo(output, nl=False, color=display.color)


@app.command("findings")
# Source, evidence filters, and display settings are independent user choices.
def findings_command(  # noqa: PLR0913
    *,
    root_path: _Root = Path("."),
    revision: _Revision = None,
    baseline_root: _BaselineRoot = None,
    baseline_revision: _BaselineRevision = None,
    source: _Source = SourceSide.CURRENT,
    path: Annotated[str | None, typer.Option("--path", help="Exact project-relative path.")] = None,
    metric: Annotated[str | None, typer.Option("--metric", help="m2, m3, m4, or combined.")] = None,
    rule: Annotated[str | None, typer.Option("--rule", help="Exact pattern rule ID.")] = None,
    severity: Annotated[DiagnosticSeverity | None, typer.Option("--severity")] = None,
    reviews: _Reviews = None,
    json_output: _Json = False,
    strict: _Strict = None,
    languages: _Languages = None,
    color: _ColorOption = _Color.AUTO,
    no_color: _NoColor = False,
    ascii: _Ascii = False,
    verbose: _Verbose = False,
    top: _Top = None,
) -> None:
    """List matching patterns, clones, and eroded callables from one source state."""
    display = _display(color, no_color, ascii, verbose, top)
    try:
        report = _evidence_report(
            root_path, strict, revision, baseline_root, baseline_revision, languages=languages
        )
        report = _review_report(report, reviews)
        selection = query_findings(
            report, path=path, metric=metric, rule=rule, severity=severity, source=source
        )
        if json_output:
            payload = {
                "schema_version": report.schema_version,
                "interpretation": report.interpretation.model_dump(mode="json"),
                "analysis": report.analysis.model_dump(mode="json"),
                "provenance": report.provenance.model_dump(mode="json"),
                "selection": selection.model_dump(mode="json"),
                "coverage": [item.model_dump(mode="json") for item in report.coverage],
                "diagnostics": [item.model_dump(mode="json") for item in report.diagnostics],
                "excluded_directories": [
                    item.model_dump(mode="json") for item in report.excluded_directories
                ],
            }
            if report.review_results:
                payload["review_results"] = [
                    item.model_dump(mode="json") for item in report.review_results
                ]
            typer.echo(json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True))
            return
        output = render_findings(
            report,
            selection,
            width=display.width,
            color=display.color,
            ascii=display.ascii,
            verbose=display.verbose,
            top=display.top,
        )
    except SelectionError as error:
        _fail(error)
    typer.echo(output, nl=False, color=display.color)


@app.command("rules")
def rules_command(  # noqa: PLR0913 - independent catalog display options
    *,
    root_path: _Root = Path("."),
    json_output: _Json = False,
    color: _ColorOption = _Color.AUTO,
    no_color: _NoColor = False,
    ascii: _Ascii = False,
    verbose: _Verbose = False,
) -> None:
    """List versioned rule metadata and the configured enabled state."""
    display = _display(color, no_color, ascii, verbose, None)
    try:
        catalog = rule_catalog(load_analysis_config(root_path))
    except (ValueError, OSError) as error:
        _fail(InputError(str(error)))
    if json_output:
        typer.echo(catalog.model_dump_json(indent=2))
        return
    typer.echo(
        render_rules(
            catalog,
            width=display.width,
            color=display.color,
            ascii=display.ascii,
            verbose=display.verbose,
        ),
        nl=False,
        color=display.color,
    )


def _review_report(report: AnalysisReport, store: Path | None) -> AnalysisReport:
    if store is None:
        return report
    try:
        return apply_reviews(report, load_review_store(store))
    except (InputError, ValueError, OSError) as error:
        _fail(InputError(str(error)))


review_app = typer.Typer(
    help="Record and inspect source-bound clone review decisions.", no_args_is_help=True
)
app.add_typer(review_app, name="review")


@review_app.command("set")
def review_set(  # noqa: PLR0913 - explicit review identity, decision, and source selection
    group_id: str,
    *,
    store: Annotated[Path, typer.Option("--store")],
    disposition: Annotated[ReviewDisposition, typer.Option("--disposition")],
    reason: Annotated[str, typer.Option("--reason")],
    root_path: _Root = Path("."),
    next_step: Annotated[str, typer.Option("--next-step")] = "",
    languages: _Languages = None,
) -> None:
    """Save one clone decision after source review; never modify analyzed code."""
    report = _scan_report(root_path, None, languages=languages)
    try:
        write_clone_review(
            store, report, group_id, disposition=disposition, reason=reason, next_step=next_step
        )
    except (InputError, ValueError, OSError) as error:
        _fail(InputError(str(error)))
    typer.echo(
        f"Saved {disposition.value} for {group_id} in {store}. Findings and scores are unchanged."
    )


@review_app.command("show")
def review_show(  # noqa: PLR0913 - report source and independent presentation options
    *,
    store: Annotated[Path, typer.Option("--store")],
    root_path: _Root = Path("."),
    languages: _Languages = None,
    json_output: _Json = False,
    color: _ColorOption = _Color.AUTO,
    no_color: _NoColor = False,
    ascii: _Ascii = False,
    verbose: _Verbose = False,
) -> None:
    """Recheck saved clone decisions against a fresh read-only snapshot."""
    report = _review_report(_scan_report(root_path, None, languages=languages), store)
    display = _display(color, no_color, ascii, verbose, None)
    output = (
        serialize_report(report)
        if json_output
        else terminal.render_snapshot(
            report,
            scope="all",
            width=display.width,
            color=display.color,
            ascii=display.ascii,
            verbose=verbose,
        )
    )
    typer.echo(output, nl=False, color=display.color)


def main() -> None:
    """Run the command-line application."""
    app()
