"""Render native evidence selections and versioned rule metadata."""

from slop_measure.domain.evidence import DiagnosticSeverity
from slop_measure.domain.reports import AnalysisReport, ReportCloneGroup, ReportFinding
from slop_measure.domain.rules import RuleCatalog
from slop_measure.reporting.interpretation import render_interpretation
from slop_measure.reporting.reviews import render_review_results
from slop_measure.reporting.selections import ErosionFinding, FindingSelection
from slop_measure.reporting.terminal import (
    _callable_basis,
    _callable_row,
    _clone_boundary,
    _provenance,
    _View,
    _view,
)


def _pattern(view: _View, record: ReportFinding) -> None:
    finding = record.detail
    view.console.print(f"  {record.id} | {record.source.value}")
    view.console.print(
        f"  {finding.path.root}:{finding.span.start_line}-{finding.span.end_line} {finding.rule_id}"
    )
    view.console.print(
        f"    {finding.category.value} | {finding.severity.value}: {finding.message}"
    )
    if finding.remediation:
        view.console.print(f"    {finding.remediation}")


def _clone(view: _View, record: ReportCloneGroup) -> None:
    group = record.detail
    view.console.print(
        f"  {record.id} | {record.source.value} | {group.language} | {group.cohort.value}"
    )
    _clone_boundary(view, record)
    for member in group.members:
        view.console.print(
            f"    {member.path.root}:{member.span.start_line}-{member.span.end_line}"
            f" | {len(member.sloc_lines)} SLOC"
        )
    if view.verbose:
        view.console.print(f"    normalization {group.normalization_version}")
        view.console.print(f"    fingerprint {group.fingerprint}")


def _function(view: _View, record: ErosionFinding, report: AnalysisReport) -> None:
    view.console.print(f"  {record.source.value} | {record.language} | {record.cohort.value}")
    _callable_row(view, record.function)
    _callable_basis(view, report, record.cohort, record.function)


# Presentation options match the other report renderers and do not mutate selections.
def render_findings(  # noqa: PLR0913
    report: AnalysisReport,
    selection: FindingSelection,
    *,
    width: int = 80,
    color: bool = False,
    ascii: bool = False,
    verbose: bool = False,
    top: int | None = None,
) -> str:
    """Display selected native records, retaining every member of a displayed clone group."""
    total = len(selection.patterns) + len(selection.clone_groups) + len(selection.functions)
    stream, view = _view(width, color, ascii, verbose, top if top is not None else max(1, total))
    view.console.print("slop.measure  findings", style="bold")
    view.console.print(
        f"{len(selection.patterns)} pattern findings | {len(selection.clone_groups)} clone groups"
        f" | {len(selection.functions)} eroded callables"
    )
    partial = any(item.detail.severity is DiagnosticSeverity.ERROR for item in report.diagnostics)
    directory_count = len(report.excluded_directories)
    directory_noun = "directory" if directory_count == 1 else "directories"
    view.console.print(
        ("Analysis partial" if partial else "No analysis errors reported")
        + f" | {len(report.diagnostics)} diagnostic(s)"
        + f" | {directory_count} excluded {directory_noun} (contents not scanned)"
    )
    remaining = view.limit
    if selection.patterns and remaining:
        view.console.print()
        view.console.print("Pattern findings")
        patterns = sorted(
            selection.patterns,
            key=lambda item: (
                item.source.value,
                item.detail.path.root,
                item.detail.span.start_line,
                item.detail.span.end_line,
                item.detail.rule_id,
                item.id,
            ),
        )[:remaining]
        for pattern in patterns:
            _pattern(view, pattern)
        remaining -= len(patterns)
    if selection.clone_groups and remaining:
        view.console.print()
        view.console.print("Clone groups")
        groups = sorted(selection.clone_groups, key=lambda item: (item.source.value, item.id))[
            :remaining
        ]
        for group in groups:
            _clone(view, group)
        remaining -= len(groups)
    if selection.functions and remaining:
        view.console.print()
        view.console.print(
            f"Eroded callables (CC > {report.provenance.config.complexity_threshold})"
        )
        functions = sorted(
            selection.functions,
            key=lambda item: (
                item.source.value,
                item.function.path.root,
                item.function.span.start_line,
                item.function.span.end_line,
                item.function.qualified_name,
            ),
        )[:remaining]
        for function in functions:
            _function(view, function, report)
        remaining -= len(functions)
    omitted = total - (view.limit - remaining)
    if omitted:
        view.console.print(
            f"{omitted} evidence record" + ("s" if omitted != 1 else "") + " omitted"
        )
    if not total:
        view.console.print("No matching evidence.")
    if verbose:
        _provenance(view, report)
    render_review_results(view.console, report.review_results)
    render_interpretation(view.console, report.interpretation, verbose=verbose)
    return stream.getvalue()


def render_rules(
    catalog: RuleCatalog,
    *,
    width: int = 80,
    color: bool = False,
    ascii: bool = False,
    verbose: bool = False,
) -> str:
    """Show catalog metadata and effective enabled state without source analysis."""
    stream, view = _view(width, color, ascii, verbose, max(1, len(catalog.rules)))
    view.console.print("slop.measure  rules", style="bold")
    view.console.print(f"{catalog.language} | {catalog.version} | {len(catalog.rules)} rules")
    for entry in sorted(catalog.rules, key=lambda item: item.metadata.rule_id):
        rule = entry.metadata
        view.console.print()
        view.console.print(f"{rule.rule_id} | {'enabled' if entry.enabled else 'disabled'}")
        view.console.print(f"  {rule.category.value} | {rule.severity.value}")
        view.console.print(f"  {rule.message}")
        if rule.remediation:
            view.console.print(f"  {rule.remediation}")
    render_interpretation(view.console, catalog.interpretation, verbose=verbose)
    return stream.getvalue()
