"""Failures that stop an analysis under the selected policy."""


class AnalysisFailure(RuntimeError):
    """Analysis cannot complete, including an error under strict mode."""
