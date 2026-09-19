"""Render explicit, conditional, and fallback variant coverage for review."""

from slop_measure.domain.variant_review import AnalyzedVariantHandler, VariantReviewReport


def _handler_lines(path: str, handler: AnalyzedVariantHandler) -> list[str]:
    declaration = handler.declaration
    lines = [
        f"  {path}:{handler.span.start_line} {handler.symbol} | {handler.coverage}",
        f"    Declaration: {declaration.name} ({declaration.kind}) "
        f"at {path}:{declaration.span.start_line}",
        "    Declared cases: " + ", ".join(case.name for case in declaration.cases),
    ]
    for branch in handler.branches:
        names = ", ".join(branch.cases) if branch.kind == "cases" else "catch-all"
        condition = "guarded" if branch.conditional else "unconditional"
        lines.append(f"    {names} | {condition} at {path}:{branch.span.start_line}")
    names = ", ".join(handler.not_explicitly_covered) or "none"
    lines.append(f"    Without unconditional explicit coverage: {names}")
    if handler.coverage == "fallback":
        lines.append("    These known cases use a catch-all. Review fallback intent.")
    elif handler.coverage == "missing":
        lines.append("    Review missing cases against the intended partial or complete contract.")
    return lines


def render_variants(report: VariantReviewReport) -> str:
    lines = [f"Experimental variant review | {report.experiment}", f"Source: {report.source.root}"]
    analyzed = sum(file.state == "analyzed" for file in report.files)
    lines.append(f"Files: {analyzed} analyzed, {len(report.files) - analyzed} failed")
    counts = dict.fromkeys(("missing", "fallback", "exhaustive", "unresolved"), 0)
    for file in report.files:
        if file.state == "failed":
            lines.append(f"  {file.path.root}: failed | {file.diagnostic.message}")
            continue
        for handler in file.handlers:
            if handler.state == "unresolved":
                counts["unresolved"] += 1
                lines.append(
                    f"  {file.path.root}:{handler.span.start_line} {handler.symbol} "
                    f"| unresolved: {handler.reason}"
                )
            else:
                counts[handler.coverage] += 1
                lines.extend(_handler_lines(file.path.root, handler))
    lines.append("Handlers: " + ", ".join(f"{count} {state}" for state, count in counts.items()))
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
