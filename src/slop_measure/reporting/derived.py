"""Render the three source locations behind each stored-count review candidate."""

from slop_measure.domain.derived_review import DerivedReviewReport


def render_derived(report: DerivedReviewReport) -> str:
    lines = [
        f"Experimental derived-state review | {report.experiment}",
        f"Source: {report.source.root}",
    ]
    analyzed = sum(file.state == "analyzed" for file in report.files)
    lines.append(f"Files: {analyzed} analyzed, {len(report.files) - analyzed} failed")
    counts = dict.fromkeys(("analyzed", "unresolved", "candidates"), 0)
    for file in report.files:
        if file.state == "failed":
            lines.append(f"  {file.path.root}: failed | {file.diagnostic.message}")
            continue
        for function in file.functions:
            counts[function.state] += 1
            location = f"{file.path.root}:{function.span.start_line} {function.symbol}"
            if function.state == "unresolved":
                lines.append(f"  {location} | unresolved: {function.reason}")
                continue
            for finding in function.findings:
                counts["candidates"] += 1
                lines.extend(
                    (
                        f"  {location} | review candidate: {finding.derived_name}",
                        f"    Derivation: len({finding.source_name}) at "
                        f"{file.path.root}:{finding.derivation.start_line}",
                        f"    Mutation: {finding.source_name}.{finding.mutation_kind} at "
                        f"{file.path.root}:{finding.mutation.start_line}",
                        f"    Read without recomputation: {finding.derived_name} at "
                        f"{file.path.root}:{finding.read.start_line}",
                    )
                )
    lines.append("Functions: " + ", ".join(f"{count} {state}" for state, count in counts.items()))
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
