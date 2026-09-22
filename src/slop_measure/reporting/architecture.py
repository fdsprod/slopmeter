"""Render source-located direct architecture evidence."""

from slop_measure.domain.architecture import ArchitectureReport
from slop_measure.reporting.comparison import _identity


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
            f"{edge.importer} -> {edge.imported} | forbidden"
        )
    for component in report.cycles:
        lines.append("  Cycle component: " + ", ".join(component))
    for module, count in report.fan_out.items():
        lines.append(f"  {module} | internal fan-out: {count}")
    for item in report.unresolved:
        lines.append(f"  {item.path.root} | unresolved: {item.reason}")
    for diagnostic in report.diagnostics:
        location = f"{diagnostic.path.root}: " if diagnostic.path else ""
        lines.append(f"  {diagnostic.severity.value}: {location}{diagnostic.message}")
    lines.extend(("", *report.interpretation))
    return "\n".join(lines) + "\n"
