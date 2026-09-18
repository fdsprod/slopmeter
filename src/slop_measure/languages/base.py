"""The language-neutral contract for source analyzers."""

from typing import Protocol

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import EvidenceCapability, LanguageEvidence
from slop_measure.domain.source import SourceDocument


class LanguageAdapter(Protocol):
    """Read source documents and return owned, language-neutral evidence."""

    @property
    def language_id(self) -> str:
        """Return the stable language identifier."""
        ...

    @property
    def extensions(self) -> frozenset[str]:
        """Return the supported file suffixes, each with a leading dot."""
        ...

    @property
    def capabilities(self) -> frozenset[EvidenceCapability]:
        """Return the evidence families this adapter supports."""
        ...

    def analyze(
        self, documents: tuple[SourceDocument, ...], config: AnalysisConfig
    ) -> LanguageEvidence:
        """Analyze source bytes without importing or executing target code."""
        ...
