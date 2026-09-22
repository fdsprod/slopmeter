"""Render exception fallback evidence with its scope and interpretation."""

from slop_measure.domain.error_review import ErrorFallbackFinding, ErrorReviewReport
from slop_measure.reporting.experimental_coverage import coverage_lines


def _finding_lines(path: str, finding: ErrorFallbackFinding) -> list[str]:
    lines = [
        f"    Caught: {finding.caught}",
        f"    Protected body: {path}:{finding.protected.start_line}-{finding.protected.end_line}",
    ]
    for operation in finding.operations:
        lines.append(
            f"    Possible operation: {operation.expression} at {path}:{operation.span.start_line}"
        )
    lines.append(
        f"    Fallback ({finding.fallback_kind}): {finding.fallback.expression} "
        f"at {path}:{finding.fallback.span.start_line}"
    )
    for normal in finding.normal_returns:
        lines.append(
            f"    Other return outside handlers: {normal.expression} "
            f"at {path}:{normal.span.start_line}"
        )
    return lines


def render_errors(report: ErrorReviewReport) -> str:
    lines = [
        f"Experimental exception fallback review | {report.experiment}",
        f"Source: {report.source.root}",
        *coverage_lines(report.summary),
    ]
    for file in report.files:
        if file.state == "failed":
            lines.append(f"  {file.path.root}: failed | {file.diagnostic.message}")
            continue
        for handler in file.handlers:
            location = f"{file.path.root}:{handler.span.start_line} {handler.symbol}"
            if handler.state == "unresolved":
                lines.append(f"  {location} | unresolved: {handler.reason}")
                continue
            for finding in handler.findings:
                lines.append(f"  {location} | review candidate: exception fallback")
                lines.extend(_finding_lines(file.path.root, finding))
    for item in report.inventory_coverage:
        lines.append(
            f"  {item.state.value}: {item.file_count} {item.language} files | {item.reason}"
        )
    lines.append(f"Excluded directories: {len(report.excluded_directories)} (contents not counted)")
    for diagnostic in report.diagnostics:
        path = f"{diagnostic.path.root}: " if diagnostic.path else ""
        lines.append(f"  {diagnostic.severity.value}: {path}{diagnostic.message}")
    lines.extend(("", *report.interpretation))
    return "\n".join(lines) + "\n"
