"""Stable entry points for callers that do not use the command line."""

from slop_measure.application.architecture import inspect_architecture
from slop_measure.application.budgets import evaluate_budget
from slop_measure.application.history import analyze_history
from slop_measure.application.service import AnalysisService
from slop_measure.application.surface import review_surface
from slop_measure.config import AnalysisConfig
from slop_measure.domain.change_review import ChangeReviewReport
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
    "analyze_history",
    "compare",
    "evaluate_budget",
    "inspect_architecture",
    "review_change",
    "review_surface",
    "scan",
]


def scan(request: SnapshotRequest) -> AnalysisReport:
    """Return the same complete snapshot report used by the CLI."""
    return AnalysisService().scan(request)


def compare(request: ComparisonRequest) -> AnalysisReport:
    """Compare two source states under one resolved configuration."""
    return AnalysisService().compare(request)


def review_change(request: ComparisonRequest) -> ChangeReviewReport:
    """Review introduced evidence independently of calibrated snapshot scores."""
    return AnalysisService().review_change(request)
