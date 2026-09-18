"""Failures that stop an analysis under the selected policy."""


class AnalysisFailure(RuntimeError):
    """Analysis cannot complete, including an error under strict mode."""


class InputError(ValueError):
    """A public input cannot be used for the requested operation."""


class InvalidSource(InputError):
    """A source root or revision cannot be resolved for analysis."""


class InvalidRuleSelection(InputError):
    """Configured rule identifiers do not belong to the selected catalog."""


class SelectionError(InputError):
    """A report selector is unknown, ambiguous, or outside its source root."""


def exit_code(error: Exception) -> int:
    """Map public input failures to 2 and analysis failures to 3."""
    return 2 if isinstance(error, InputError) else 3


def error_message(error: Exception) -> str:
    """Keep public explanations while omitting unexpected internal details."""
    if isinstance(error, InputError):
        return f"Invalid analysis input: {error}"
    if isinstance(error, AnalysisFailure):
        return str(error)
    return f"Analysis failed: {type(error).__name__}"
