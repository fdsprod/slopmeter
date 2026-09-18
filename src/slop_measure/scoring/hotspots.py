"""Order file scores for navigation without affecting project aggregation."""

from slop_measure.domain.reports import FileResult, MeasuredSnapshotScore


def rank_hotspots(files: tuple[FileResult, ...], limit: int = 5) -> tuple[FileResult, ...]:
    """Return highest scores first with stable path ties, including measured zero."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("hotspot limit must be a positive integer")
    measured = tuple(file for file in files if isinstance(file.score, MeasuredSnapshotScore))

    def key(file: FileResult) -> tuple[float, str]:
        assert isinstance(file.score, MeasuredSnapshotScore)  # noqa: S101 - filtered above
        return -file.score.points, file.evidence.path.root

    return tuple(sorted(measured, key=key)[:limit])
