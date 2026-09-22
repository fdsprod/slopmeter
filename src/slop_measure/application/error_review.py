"""Inspect exception fallback evidence without metric aggregation."""

from slop_measure import __version__
from slop_measure.domain.error_review import ErrorFileResult, ErrorReviewReport, FailedErrorFile
from slop_measure.domain.evidence import Diagnostic, DiagnosticSeverity
from slop_measure.domain.requests import SnapshotRequest
from slop_measure.domain.source import DirectorySourceReference, SourceDocument
from slop_measure.errors import AnalysisFailure, InputError
from slop_measure.languages.python.adapter import PythonAdapter
from slop_measure.languages.python.error_review import analyze_errors
from slop_measure.languages.registry import LanguageRegistry
from slop_measure.sources.filesystem import FilesystemSourceProvider


def _inspect(document: SourceDocument) -> ErrorFileResult:
    try:
        return analyze_errors(document)
    except Exception as error:
        return FailedErrorFile(
            path=document.path,
            cohort=document.cohort,
            source_sha256=document.content_hash,
            diagnostic=Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="python.error-review-error",
                message=f"Experimental exception analysis failed: {type(error).__name__}",
                path=document.path,
            ),
        )


def inspect_errors(request: SnapshotRequest) -> ErrorReviewReport:
    """Inspect directory source for literal exception fallbacks with return evidence."""
    if not isinstance(request.target, DirectorySourceReference):
        raise InputError("Experimental exception review supports directory sources only.")
    registry = LanguageRegistry((PythonAdapter(),))
    config = request.config.model_copy(
        update={"languages": registry.resolve_languages(request.config.languages)}
    )
    provider = FilesystemSourceProvider(request.target.root, config, registry)
    inventory = provider.inventory()
    files: list[ErrorFileResult] = [_inspect(document) for document in inventory.documents]
    for file in inventory.failed_files:
        diagnostic = next(item for item in inventory.diagnostics if item.path == file.path)
        files.append(FailedErrorFile(path=file.path, cohort=file.cohort, diagnostic=diagnostic))
    diagnostics = tuple(
        dict.fromkeys(
            (*inventory.diagnostics, *(file.diagnostic for file in files if file.state == "failed"))
        )
    )
    if config.strict and diagnostics:
        first = next(
            (item for item in diagnostics if item.severity is DiagnosticSeverity.ERROR), None
        )
        if first is not None:
            raise AnalysisFailure(f"Strict exception review failed: {first.message}")
    return ErrorReviewReport(
        tool_version=__version__,
        source=provider.identity(),
        config=config,
        files=tuple(sorted(files, key=lambda item: item.path.root)),
        inventory_coverage=inventory.coverage,
        diagnostics=diagnostics,
        excluded_directories=inventory.excluded_directories,
    )
