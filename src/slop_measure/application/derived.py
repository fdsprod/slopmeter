"""Read-only experimental derived inspection without metric aggregation."""

from slop_measure import __version__
from slop_measure.domain.derived_review import (
    DerivedFileResult,
    DerivedReviewReport,
    FailedDerivedFile,
)
from slop_measure.domain.evidence import Diagnostic, DiagnosticSeverity
from slop_measure.domain.requests import SnapshotRequest
from slop_measure.domain.source import DirectorySourceReference, SourceDocument
from slop_measure.errors import AnalysisFailure, InputError
from slop_measure.languages.python.adapter import PythonAdapter
from slop_measure.languages.python.derived_review import analyze_derived
from slop_measure.languages.registry import LanguageRegistry
from slop_measure.sources.filesystem import FilesystemSourceProvider


def _inspect(document: SourceDocument) -> DerivedFileResult:
    try:
        return analyze_derived(document)
    except Exception as error:
        return FailedDerivedFile(
            path=document.path,
            cohort=document.cohort,
            source_sha256=document.content_hash,
            diagnostic=Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="python.derived-review-error",
                message=f"Experimental derived analysis failed: {type(error).__name__}",
                path=document.path,
            ),
        )


def inspect_derived(request: SnapshotRequest) -> DerivedReviewReport:
    """Inspect directory source using the narrow stored-count experiment."""
    if not isinstance(request.target, DirectorySourceReference):
        raise InputError("Experimental derived review supports directory sources only.")
    registry = LanguageRegistry((PythonAdapter(),))
    config = request.config.model_copy(
        update={"languages": registry.resolve_languages(request.config.languages)}
    )
    provider = FilesystemSourceProvider(request.target.root, config, registry)
    inventory = provider.inventory()
    files: list[DerivedFileResult] = [_inspect(document) for document in inventory.documents]
    for file in inventory.failed_files:
        diagnostic = next(item for item in inventory.diagnostics if item.path == file.path)
        files.append(FailedDerivedFile(path=file.path, cohort=file.cohort, diagnostic=diagnostic))
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
            raise AnalysisFailure(f"Strict derived review failed: {first.message}")
    return DerivedReviewReport(
        tool_version=__version__,
        source=provider.identity(),
        config=config,
        files=tuple(sorted(files, key=lambda item: item.path.root)),
        inventory_coverage=inventory.coverage,
        diagnostics=diagnostics,
        excluded_directories=inventory.excluded_directories,
    )
