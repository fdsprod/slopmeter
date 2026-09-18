"""Decode and parse Python documents into owned file evidence."""

import ast
import io
import tokenize

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import (
    AnalyzedFunctions,
    Diagnostic,
    DiagnosticSeverity,
    EvidenceCapability,
    FailedFunctions,
    FileEvidence,
    FunctionAnalysis,
    LanguageEvidence,
    ParseState,
    SourceSpan,
)
from slop_measure.domain.source import SourceDocument
from slop_measure.languages.python.complexity import extract_functions
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


def _analyze_functions(tree: ast.Module, file: FileEvidence) -> FunctionAnalysis:
    try:
        return AnalyzedFunctions(path=file.path, functions=extract_functions(tree, file))
    except Exception as error:
        return FailedFunctions(
            path=file.path,
            diagnostic=Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="python.complexity-error",
                message=str(error) or "Python complexity analysis failed.",
                path=file.path,
            ),
        )


def _analyze_document(
    document: SourceDocument,
) -> tuple[FileEvidence, Diagnostic | FunctionAnalysis]:
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
    file = FileEvidence(
        path=document.path,
        language=document.language,
        cohort=document.cohort,
        sloc=len(lines),
        sloc_lines=lines,
        parse_state=ParseState.PARSED,
    )
    return file, _analyze_functions(tree, file)


class PythonAdapter:
    """Produce file evidence without importing or executing source documents."""

    language_id = "python"
    extensions = frozenset({".py", ".pyi"})
    capabilities = frozenset({EvidenceCapability.FILES, EvidenceCapability.FUNCTIONS})
    adapter_version = "python-functions-1"

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
        function_analyses: list[FunctionAnalysis] = []
        for document in sorted(documents, key=lambda item: item.path.root):
            file, outcome = _analyze_document(document)
            files.append(file)
            if isinstance(outcome, Diagnostic):
                diagnostics.append(outcome)
            else:
                function_analyses.append(outcome)
        return LanguageEvidence(
            language=self.language_id,
            capabilities=self.capabilities,
            files=tuple(files),
            function_analyses=tuple(function_analyses),
            diagnostics=tuple(diagnostics),
        )
