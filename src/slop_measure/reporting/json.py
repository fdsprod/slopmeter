"""Deterministic serialization of the complete report contract."""

import json

from slop_measure.domain.reports import AnalysisReport


def serialize_report(report: AnalysisReport) -> str:
    """Return stable, readable JSON followed by one newline."""
    return json.dumps(report.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
