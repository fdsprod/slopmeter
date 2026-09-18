"""Failures that stop an analysis under the selected policy."""


class AnalysisFailure(RuntimeError):
    """Analysis cannot complete, including an error under strict mode."""


class InvalidSource(ValueError):
    """A source root or revision cannot be resolved for analysis."""


class InvalidRuleSelection(ValueError):
    """Configured rule identifiers do not belong to the selected catalog."""


class SelectionError(ValueError):
    """A report selector is unknown, ambiguous, or outside its source root."""
