"""Language adapter contracts and explicit registration."""

from slop_measure.languages.base import LanguageAdapter
from slop_measure.languages.registry import LanguageRegistry

__all__ = ["LanguageAdapter", "LanguageRegistry"]
