"""Render source-located direct architecture evidence."""

from slop_measure.domain.architecture import ArchitectureReport, ImportContext, UnresolvedImport
from slop_measure.reporting.comparison import _identity


def _context(context: ImportContext) -> str:
    return ", ".join((context.execution, *context.guards))


def render_architecture(report: ArchitectureReport) -> str:
    lines = [
        f"Architecture review | {report.experiment}",
        f"Source: {_identity(report.source)}",
        f"Direct imports: {len(report.edges)} | Violations: {len(report.violations)} | "
        f"Unresolved: {len(report.unresolved)}",
    ]
    for violation in report.violations:
        edge = violation.edge
        lines.append(
            f"  {edge.path.root}:{edge.span.start_line} | "
            f"{edge.importer} -> {edge.imported} | forbidden | {_context(edge.context)}"
        )
    for component in report.cycles:
        lines.append("  Cycle component: " + ", ".join(component))
        for edge in report.edges:
            if edge.importer in component and edge.imported in component:
                lines.append(
                    f"    {edge.path.root}:{edge.span.start_line} | "
                    f"{edge.importer} -> {edge.imported} | {_context(edge.context)}"
                )
    for module, count in report.fan_out.items():
        lines.append(f"  {module} | internal fan-out: {count}")
    for item in report.unresolved:
        context = f" | {_context(item.context)}" if isinstance(item, UnresolvedImport) else ""
        lines.append(f"  {item.path.root} | unresolved: {item.reason}{context}")
    for diagnostic in report.diagnostics:
        location = f"{diagnostic.path.root}: " if diagnostic.path else ""
        lines.append(f"  {diagnostic.severity.value}: {location}{diagnostic.message}")
    lines.extend(("", *report.interpretation))
    return "\n".join(lines) + "\n"
