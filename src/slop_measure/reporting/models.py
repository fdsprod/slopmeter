"""Show experimental model evidence and unresolved scope without a score."""

from slop_measure.domain.model_review import ModelReviewReport


def render_models(report: ModelReviewReport) -> str:
    lines = [f"Experimental model review | {report.experiment}", f"Source: {report.source.root}"]
    analyzed = sum(file.state == "analyzed" for file in report.files)
    lines.append(f"Files: {analyzed} analyzed, {len(report.files) - analyzed} failed")
    findings = 0
    unresolved = 0
    for file in report.files:
        if file.state == "failed":
            lines.append(f"  {file.path.root}: failed | {file.diagnostic.message}")
            continue
        for model in file.models:
            location = f"{file.path.root}:{model.span.start_line}"
            if model.state == "unresolved":
                unresolved += 1
                lines.append(f"  {location} {model.name} | unresolved: {model.reason}")
                continue
            for finding in model.findings:
                findings += 1
                lines.append(f"  {location} {model.name} | coupled-state review candidate")
                lines.append(
                    "    Fields: "
                    + ", ".join(
                        f"{field.name} ({field.kind}) at {file.path.root}:{field.span.start_line}"
                        for field in finding.fields
                    )
                )
                lines.append(f"    Repeated predicate: {finding.predicate}")
                validator = finding.validator
                lines.append(
                    f"    Rejects: {validator.symbol} at "
                    f"{file.path.root}:{validator.span.start_line}"
                )
                for consumer in finding.consumers:
                    lines.append(
                        f"    Repeats: {consumer.symbol} at "
                        f"{file.path.root}:{consumer.span.start_line}"
                    )
    lines.append(f"Candidates: {findings}; unresolved model classes: {unresolved}")
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
