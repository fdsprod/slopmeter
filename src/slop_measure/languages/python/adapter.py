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
    FailedPatterns,
    FileEvidence,
    FunctionAnalysis,
    LanguageEvidence,
    ParseState,
    PatternAnalysis,
    SourceSpan,
)
from slop_measure.domain.source import SourceDocument
from slop_measure.languages.python.complexity import extract_functions
from slop_measure.languages.python.patterns import (
    PythonParsedUnit,
    PythonProjectContext,
    run_patterns,
    select_rules,
)
from slop_measure.languages.python.rules import RULE_SET_VERSION, RULES
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


def _parse_document(
    document: SourceDocument,
) -> tuple[FileEvidence, Diagnostic | PythonParsedUnit]:
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
    return file, PythonParsedUnit(tree=tree, file=file, source=source)


def _analyze_patterns(
    unit: PythonParsedUnit, context: PythonProjectContext, config: AnalysisConfig
) -> PatternAnalysis:
    try:
        return run_patterns(unit, context, config)
    except Exception as error:
        return FailedPatterns(
            path=unit.file.path,
            diagnostic=Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="python.pattern-error",
                message=str(error) or "Python pattern analysis failed.",
                path=unit.file.path,
            ),
        )


class PythonAdapter:
    """Produce file evidence without importing or executing source documents."""

    language_id = "python"
    extensions = frozenset({".py", ".pyi"})
    capabilities = frozenset(
        {EvidenceCapability.FILES, EvidenceCapability.FUNCTIONS, EvidenceCapability.PATTERNS}
    )
    adapter_version = "python-patterns-1"
    rule_set_version = RULE_SET_VERSION

    def validate_config(self, config: AnalysisConfig) -> None:
        """Reject unknown rule selections before any file analysis."""
        select_rules(RULES, config)

    def analyze(
        self, documents: tuple[SourceDocument, ...], config: AnalysisConfig
    ) -> LanguageEvidence:
        """Return deterministic evidence. The service owns strict failure policy."""
        self.validate_config(config)
        if any(document.language != self.language_id for document in documents):
            raise ValueError("Python adapter requires Python source documents")
        if len({document.path.root for document in documents}) != len(documents):
            raise ValueError("Python adapter cannot analyze duplicate document paths")
        files: list[FileEvidence] = []
        diagnostics: list[Diagnostic] = []
        function_analyses: list[FunctionAnalysis] = []
        pattern_analyses: list[PatternAnalysis] = []
        ordered = tuple(sorted(documents, key=lambda item: item.path.root))
        context = PythonProjectContext(paths=tuple(document.path for document in ordered))
        for document in ordered:
            file, outcome = _parse_document(document)
            files.append(file)
            if isinstance(outcome, Diagnostic):
                diagnostics.append(outcome)
            else:
                function_analyses.append(_analyze_functions(outcome.tree, file))
                pattern_analyses.append(_analyze_patterns(outcome, context, config))
        return LanguageEvidence(
            language=self.language_id,
            capabilities=self.capabilities,
            files=tuple(files),
            function_analyses=tuple(function_analyses),
            pattern_analyses=tuple(pattern_analyses),
            diagnostics=tuple(diagnostics),
        )
