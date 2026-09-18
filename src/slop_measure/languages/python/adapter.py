"""Decode and parse Python documents into owned file evidence."""

import ast
import io
import tokenize

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import (
    Diagnostic,
    DiagnosticSeverity,
    EvidenceCapability,
    FileEvidence,
    LanguageEvidence,
    ParseState,
    SourceSpan,
)
from slop_measure.domain.source import SourceDocument
from slop_measure.languages.python.sloc import classify_sloc


def _failed_document(
    document: SourceDocument, error: Exception, code: str
) -> tuple[FileEvidence, Diagnostic]:
    span = None
    if isinstance(error, SyntaxError) and error.lineno is not None and error.lineno > 0:
        span = SourceSpan(
            start_line=error.lineno, end_line=max(error.lineno, error.end_lineno or error.lineno)
        )
    return (
        FileEvidence(
            path=document.path,
            language=document.language,
            cohort=document.cohort,
            sloc=0,
            sloc_lines=(),
            parse_state=ParseState.FAILED,
        ),
        Diagnostic(
            severity=DiagnosticSeverity.ERROR,
            code=code,
            message=str(error),
            path=document.path,
            span=span,
        ),
    )


def _analyze_document(document: SourceDocument) -> tuple[FileEvidence, Diagnostic | None]:
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(document.content).readline)
        source = document.content.decode(encoding)
    except (SyntaxError, UnicodeError, LookupError) as error:
        return _failed_document(document, error, "python.decode-error")
    try:
        tree = ast.parse(source, filename=document.path.root)
    except SyntaxError as error:
        return _failed_document(document, error, "python.parse-error")
    lines = classify_sloc(source, tree)
    return (
        FileEvidence(
            path=document.path,
            language=document.language,
            cohort=document.cohort,
            sloc=len(lines),
            sloc_lines=lines,
            parse_state=ParseState.PARSED,
        ),
        None,
    )


class PythonAdapter:
    """Produce file evidence without importing or executing source documents."""

    language_id = "python"
    extensions = frozenset({".py", ".pyi"})
    capabilities = frozenset({EvidenceCapability.FILES})
    adapter_version = "python-files-1"

    def analyze(
        self, documents: tuple[SourceDocument, ...], config: AnalysisConfig
    ) -> LanguageEvidence:
        """Return deterministic evidence. The service owns strict failure policy."""
        if any(document.language != self.language_id for document in documents):
            raise ValueError("Python adapter requires Python source documents")
        if len({document.path.root for document in documents}) != len(documents):
            raise ValueError("Python adapter cannot analyze duplicate document paths")
        files: list[FileEvidence] = []
        diagnostics: list[Diagnostic] = []
        for document in sorted(documents, key=lambda item: item.path.root):
            file, diagnostic = _analyze_document(document)
            files.append(file)
            if diagnostic is not None:
                diagnostics.append(diagnostic)
        return LanguageEvidence(
            language=self.language_id,
            capabilities=self.capabilities,
            files=tuple(files),
            diagnostics=tuple(diagnostics),
        )
