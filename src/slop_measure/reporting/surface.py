"""Render declaration counts and source locations without quality judgments."""

from slop_measure.domain.surface import (
    MeasuredNovelRatio,
    RemovedSymbol,
    SurfaceReviewReport,
    UnresolvedSymbols,
    symbol_sides,
)


def render_surface(report: SurfaceReviewReport) -> str:
    lines = [
        "Source declaration changes | unscored",
        f"Baseline: {report.analysis.baseline.root}",
        f"Current: {report.analysis.current.root}",
        "Files: " + ", ".join(f"{count} {kind}" for kind, count in report.file_summary.items()),
        "Declarations: " + ", ".join(f"{count} {state}" for state, count in report.summary.items()),
    ]
    ratio = report.novel_ratio
    lines.append(
        f"Novel declaration ratio: {ratio.value:.1%} (added / added + modified)"
        if isinstance(ratio, MeasuredNovelRatio)
        else f"Novel declaration ratio unavailable: {ratio.reason}"
    )
    for change in report.symbols:
        if isinstance(change, UnresolvedSymbols):
            lines.append(f"  unresolved: {change.reason}")
            for side, occurrences in symbol_sides(change):
                for item in occurrences:
                    lines.append(
                        f"    {side.value}: {item.path.root}:{item.span.start_line} "
                        f"{item.qualified_name}"
                    )
        else:
            item = change.baseline if isinstance(change, RemovedSymbol) else change.current
            lines.append(
                f"  {change.state}: {item.path.root}:{item.span.start_line} {item.qualified_name}"
            )
    for limitation in report.limitations:
        location = f"{limitation.path.root}: " if limitation.path is not None else ""
        lines.append(f"  unavailable: {location}{limitation.reason}")
    lines.extend(
        (
            "",
            "Counts include nested declarations. Changing a method can also change its class AST.",
            "Formatting and comments do not change declaration AST fingerprints.",
            "Counts describe source syntax, not the required size or quality of the solution.",
        )
    )
    return "\n".join(lines) + "\n"
