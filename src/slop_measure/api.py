"""Stable entry points for callers that do not use the command line."""

from slop_measure.application.service import AnalysisService
from slop_measure.config import AnalysisConfig
from slop_measure.domain.reports import AnalysisReport
from slop_measure.domain.requests import ComparisonRequest, SnapshotRequest
from slop_measure.domain.source import DirectorySourceReference, GitSourceReference

__all__ = [
    "AnalysisConfig",
    "AnalysisReport",
    "ComparisonRequest",
    "DirectorySourceReference",
    "GitSourceReference",
    "SnapshotRequest",
    "compare",
    "scan",
]


def scan(request: SnapshotRequest) -> AnalysisReport:
    """Return the same complete snapshot report used by the CLI."""
    return AnalysisService().scan(request)


def compare(request: ComparisonRequest) -> AnalysisReport:
    """Reserve the comparison entry point until directory comparison is implemented."""
    raise NotImplementedError("Comparison analysis is not available yet")
