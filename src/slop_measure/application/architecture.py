"""Inspect declared direct import boundaries using the existing source providers."""

from slop_measure import __version__
from slop_measure.domain.architecture import (
    ArchitecturePolicy,
    ArchitectureReport,
    FailedArchitectureFile,
)
from slop_measure.domain.evidence import DiagnosticSeverity
from slop_measure.domain.requests import SnapshotRequest
from slop_measure.domain.source import DirectorySourceReference
from slop_measure.errors import AnalysisFailure
from slop_measure.languages.python.adapter import PythonAdapter
from slop_measure.languages.python.imports import analyze_imports
from slop_measure.languages.registry import LanguageRegistry
from slop_measure.sources.filesystem import FilesystemSourceProvider
from slop_measure.sources.git import GitSourceProvider


def inspect_architecture(
    request: SnapshotRequest, policy: ArchitecturePolicy
) -> ArchitectureReport:
    """Return unscored import evidence from a directory or pinned Git revision."""
    registry = LanguageRegistry((PythonAdapter(),))
    config = request.config.model_copy(
        update={"languages": registry.resolve_languages(request.config.languages)}
    )
    provider = (
        FilesystemSourceProvider(request.target.root, config, registry)
        if isinstance(request.target, DirectorySourceReference)
        else GitSourceProvider(request.target.root, request.target.revision, config, registry)
    )
    inventory = provider.inventory()
    files = list(analyze_imports(inventory.documents, policy))
    for file in inventory.failed_files:
        diagnostic = next(item for item in inventory.diagnostics if item.path == file.path)
        files.append(FailedArchitectureFile(path=file.path, diagnostic=diagnostic))
    diagnostics = tuple(
        dict.fromkeys(
            (
                *inventory.diagnostics,
                *(file.diagnostic for file in files if isinstance(file, FailedArchitectureFile)),
            )
        )
    )
    if config.strict:
        first = next(
            (item for item in diagnostics if item.severity is DiagnosticSeverity.ERROR), None
        )
        if first is not None:
            raise AnalysisFailure(f"Strict architecture review failed: {first.message}")
    return ArchitectureReport(
        tool_version=__version__,
        source=provider.identity(),
        config=config,
        policy=policy,
        files=tuple(sorted(files, key=lambda file: file.path.root)),
        diagnostics=diagnostics,
        inventory_coverage=inventory.coverage,
        excluded_directories=inventory.excluded_directories,
    )
