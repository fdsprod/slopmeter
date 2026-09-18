"""Python adapter behavior through the owned language boundary."""

import ast
import codecs
from pathlib import Path

import pytest

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import (
    AnalyzedFunctions,
    AnalyzedPatterns,
    DiagnosticSeverity,
    EvidenceCapability,
    FailedFunctions,
    FailedPatterns,
    ParseState,
)
from slop_measure.domain.source import Cohort, ProjectPath, SourceDocument
from slop_measure.languages.base import LanguageAdapter
from slop_measure.languages.python.adapter import PythonAdapter


def document(content: bytes, path: str = "src/app.py", language: str = "python") -> SourceDocument:
    return SourceDocument(
        path=ProjectPath(path), content=content, language=language, cohort=Cohort.PRODUCTION
    )


def test_python_adapter_declares_its_exact_capabilities() -> None:
    adapter: LanguageAdapter = PythonAdapter()
    assert adapter.language_id == "python"
    assert adapter.extensions == frozenset({".py", ".pyi"})
    assert adapter.capabilities == frozenset(
        {
            EvidenceCapability.FILES,
            EvidenceCapability.FUNCTIONS,
            EvidenceCapability.PATTERNS,
            EvidenceCapability.CLONES,
        }
    )
    assert PythonAdapter().adapter_version == "python-complexity-2"
    assert PythonAdapter().rule_set_version == "py-patterns-1"


@pytest.mark.parametrize(
    ("content", "lines"),
    [
        (b"", ()),
        (b'"module docs"\n', ()),
        (b"# comment\r\nvalue = 1\r\n", (2,)),
        ("value = 'é'\n".encode(), (1,)),
        (b"# coding: latin-1\nvalue = '\xe9'\n", (2,)),
        (codecs.BOM_UTF8 + b"value = 1\n", (1,)),
        (b"def function(value: int) -> int: ...\n", (1,)),
    ],
)
def test_valid_sources_produce_exact_owned_file_evidence(
    content: bytes, lines: tuple[int, ...]
) -> None:
    result = PythonAdapter().analyze((document(content),), AnalysisConfig())
    assert result.language == "python"
    assert result.capabilities == frozenset(
        {
            EvidenceCapability.FILES,
            EvidenceCapability.FUNCTIONS,
            EvidenceCapability.PATTERNS,
            EvidenceCapability.CLONES,
        }
    )
    assert result.diagnostics == ()
    assert result.patterns == result.clone_candidates == ()
    assert len(result.function_analyses) == 1
    assert isinstance(result.function_analyses[0], AnalyzedFunctions)
    assert len(result.pattern_analyses) == 1
    assert isinstance(result.pattern_analyses[0], AnalyzedPatterns)
    assert len(result.files) == 1
    file = result.files[0]
    assert file.path == ProjectPath("src/app.py")
    assert file.language == "python"
    assert file.cohort is Cohort.PRODUCTION
    assert file.parse_state is ParseState.PARSED
    assert file.sloc_lines == lines
    assert file.sloc == len(lines)
    assert bool(result.functions) == content.startswith(b"def ")


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"value = (\n", "python.parse-error"),
        (b"value = 'oops\n", "python.parse-error"),
        (b"value = '\xff'\n", "python.decode-error"),
        (b"# coding: missing-encoding\n", "python.decode-error"),
        (codecs.BOM_UTF8 + b"# coding: latin-1\n", "python.decode-error"),
    ],
)
def test_bad_source_does_not_prevent_other_files_and_strictness_is_service_owned(
    content: bytes, code: str
) -> None:
    documents = (document(content, "bad.py"), document(b"value = 1\n", "good.py"))
    adapter = PythonAdapter()
    result = adapter.analyze(documents, AnalysisConfig())
    assert result == adapter.analyze(documents, AnalysisConfig(strict=True))
    bad, good = result.files
    assert bad.path == ProjectPath("bad.py")
    assert bad.parse_state is ParseState.FAILED
    assert bad.sloc == 0
    assert bad.sloc_lines == ()
    assert good.parse_state is ParseState.PARSED
    assert good.sloc_lines == (1,)
    assert len(result.diagnostics) == 1
    diagnostic = result.diagnostics[0]
    assert diagnostic.severity is DiagnosticSeverity.ERROR
    assert diagnostic.code == code
    assert diagnostic.path == ProjectPath("bad.py")
    assert diagnostic.message
    assert len(result.function_analyses) == 1
    assert result.function_analyses[0].path == ProjectPath("good.py")
    assert len(result.pattern_analyses) == 1
    assert result.pattern_analyses[0].path == ProjectPath("good.py")


def test_syntax_error_diagnostic_preserves_available_line_location() -> None:
    result = PythonAdapter().analyze((document(b"value = 1\nif :\n    pass\n"),), AnalysisConfig())
    diagnostic = result.diagnostics[0]
    assert diagnostic.span is not None
    assert diagnostic.span.start_line == 2
    assert diagnostic.span.end_line >= diagnostic.span.start_line


def test_adapter_output_is_deterministic_for_document_order() -> None:
    documents = (
        document(b"value = (\n", "z.py"),
        document(b"value = (\n", "a.py"),
        document(b"value = 1\n", "middle.py"),
    )
    adapter = PythonAdapter()
    result = adapter.analyze(documents, AnalysisConfig())
    assert (
        result.model_dump_json()
        == adapter.analyze(tuple(reversed(documents)), AnalysisConfig()).model_dump_json()
    )
    assert tuple(file.path.root for file in result.files) == ("a.py", "middle.py", "z.py")
    assert tuple(item.path.root for item in result.diagnostics if item.path) == ("a.py", "z.py")


def test_empty_inventory_is_valid() -> None:
    result = PythonAdapter().analyze((), AnalysisConfig())
    assert result.files == result.diagnostics == ()


def test_adapter_rejects_wrong_language_and_duplicate_document_paths() -> None:
    adapter = PythonAdapter()
    with pytest.raises(ValueError):
        adapter.analyze((document(b"value = 1", language="typescript"),), AnalysisConfig())
    with pytest.raises(ValueError):
        adapter.analyze((document(b"a = 1"), document(b"b = 2")), AnalysisConfig())


def test_adapter_parses_each_document_once(monkeypatch: pytest.MonkeyPatch) -> None:
    parse = ast.parse
    parsed: list[object] = []

    def observe(source: object, *args: object, **kwargs: object) -> ast.Module:
        parsed.append(source)
        return parse(source, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ast, "parse", observe)
    PythonAdapter().analyze(
        (document(b"value = 1", "a.py"), document(b"value = 2", "b.py")), AnalysisConfig()
    )
    assert len(parsed) == 2


def test_source_code_is_never_executed(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    source = f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n"
    result = PythonAdapter().analyze((document(source.encode()),), AnalysisConfig())
    assert result.files[0].parse_state is ParseState.PARSED
    assert not marker.exists()


def test_complexity_failure_retains_file_sloc_and_other_successful_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from slop_measure.languages.python.complexity import extract_functions  # noqa: PLC0415

    def extract(tree, file):
        if file.path == ProjectPath("bad.py"):
            raise RuntimeError("fixture complexity failure")
        return extract_functions(tree, file)

    monkeypatch.setattr("slop_measure.languages.python.adapter.extract_functions", extract)
    documents = (
        document(b"def f():\n    return 1\n", "bad.py"),
        document(b"def g():\n    return 2\n", "good.py"),
    )
    adapter = PythonAdapter()
    evidence = adapter.analyze(documents, AnalysisConfig())

    assert evidence == adapter.analyze(documents, AnalysisConfig(strict=True))
    assert all(file.parse_state is ParseState.PARSED and file.sloc == 2 for file in evidence.files)
    failed, succeeded = evidence.function_analyses
    assert isinstance(failed, FailedFunctions)
    assert failed.path == ProjectPath("bad.py")
    assert failed.diagnostic.path == failed.path
    assert failed.diagnostic.code == "python.complexity-error"
    assert failed.diagnostic.severity is DiagnosticSeverity.ERROR
    assert isinstance(succeeded, AnalyzedFunctions)
    assert succeeded.functions[0].qualified_name == "g"
    assert evidence.diagnostics == ()


def test_pattern_failure_preserves_sloc_and_complexity_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from slop_measure.languages.python.patterns import run_patterns  # noqa: PLC0415

    def run(unit, context, config):
        if unit.file.path == ProjectPath("bad.py"):
            raise RuntimeError("fixture pattern failure")
        return run_patterns(unit, context, config)

    monkeypatch.setattr("slop_measure.languages.python.adapter.run_patterns", run)
    documents = (
        document(b"def f():\n    return 1\n", "bad.py"),
        document(b"def g():\n    return 2\n", "good.py"),
    )
    adapter = PythonAdapter()
    evidence = adapter.analyze(documents, AnalysisConfig())
    assert evidence == adapter.analyze(documents, AnalysisConfig(strict=True))
    assert all(item.parse_state is ParseState.PARSED and item.sloc == 2 for item in evidence.files)
    assert len(evidence.functions) == 2
    failed, successful = evidence.pattern_analyses
    assert isinstance(failed, FailedPatterns)
    assert failed.diagnostic.code == "python.pattern-error"
    assert failed.diagnostic.path == ProjectPath("bad.py")
    assert isinstance(successful, AnalyzedPatterns)
    assert evidence.diagnostics == ()
