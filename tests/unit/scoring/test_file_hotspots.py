"""Hotspot ranking uses scored files and stable path ties."""

import pytest

from slop_measure.domain.reports import FileResult
from slop_measure.scoring.hotspots import rank_hotspots


def scored_file(path: str, points: float | None) -> FileResult:
    score = (
        {"state": "unavailable", "reason": "calibration-missing"}
        if points is None
        else {
            "state": "measured",
            "points": points,
            "profile_id": "test",
            "model_id": "snapshot",
            "band": "test",
            "contributions": [
                {
                    "metric_id": "verbosity.combined",
                    "raw_value": 0.1,
                    "percentile": points,
                    "weight": 1,
                    "points": points,
                }
            ],
        }
    )
    return FileResult.model_validate(
        {
            "evidence": {
                "path": path,
                "language": "python",
                "cohort": "production",
                "sloc": 1,
                "sloc_lines": [1],
                "parse_state": "parsed",
            },
            "score": score,
        }
    )


def test_hotspots_sort_by_descending_points_then_path_and_limit_to_five() -> None:
    files = tuple(
        scored_file(path, points)
        for path, points in [
            ("z.py", 40),
            ("missing.py", None),
            ("c.py", 80),
            ("a.py", 80),
            ("b.py", 80),
            ("d.py", 10),
            ("e.py", 5),
            ("f.py", 0),
        ]
    )
    result = rank_hotspots(files)
    assert isinstance(result, tuple)
    assert [file.evidence.path.root for file in result] == ["a.py", "b.py", "c.py", "z.py", "d.py"]
    assert rank_hotspots(tuple(reversed(files))) == result
    assert files[0].evidence.path.root == "z.py"


def test_custom_hotspot_limit_and_zero_scores() -> None:
    files = (scored_file("zero.py", 0), scored_file("high.py", 100))
    assert rank_hotspots(files, limit=1) == (files[1],)
    assert rank_hotspots(files, limit=10) == (files[1], files[0])
    assert rank_hotspots(()) == ()


@pytest.mark.parametrize("limit", [0, -1])
def test_hotspot_limit_must_be_positive(limit: int) -> None:
    with pytest.raises(ValueError):
        rank_hotspots((), limit=limit)
