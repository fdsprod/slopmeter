"""Clone extraction failure is isolated from other Python evidence families."""

import pytest
import tree_sitter_python
from tree_sitter import Language, Parser

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import (
    AnalyzedClones,
    DiagnosticSeverity,
    FailedClones,
    ParseState,
)
from slop_measure.domain.source import Cohort, ProjectPath, SourceDocument
from slop_measure.languages.python.adapter import PythonAdapter
from slop_measure.languages.python.clones import extract_clone_candidates
from slop_measure.languages.python.patterns import PythonParsedUnit


def document(path: str, content: bytes) -> SourceDocument:
    return SourceDocument(
        path=ProjectPath(path), content=content, language="python", cohort=Cohort.PRODUCTION
    )


def test_each_parsed_file_has_one_clone_outcome_in_stable_order() -> None:
    documents = (
        document("z.py", b"a = 1\nb = 2\n"),
        document("empty.py", b""),
        document("bad.py", b"value = (\n"),
        document("encoded.py", b"# coding: latin-1\nname = '\xe9'\nother = name\n"),
    )
    config = AnalysisConfig(clone_min_sloc=2)
    result = PythonAdapter().analyze(documents, config)
    assert result == PythonAdapter().analyze(tuple(reversed(documents)), config)
    assert tuple(item.path.root for item in result.clone_analyses) == (
        "empty.py",
        "encoded.py",
        "z.py",
    )
    assert all(isinstance(item, AnalyzedClones) for item in result.clone_analyses)
    assert isinstance(result.clone_analyses[0], AnalyzedClones)
    assert result.clone_analyses[0].candidates == ()
    assert tuple(item.path.root for item in result.clone_candidates) == ("encoded.py", "z.py")
    assert result.clone_candidates[0].sloc_lines == (2, 3)
    assert PythonAdapter().clone_normalization_version == "py-clones-1"


def test_clone_exception_keeps_pattern_function_and_file_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def extract(unit: PythonParsedUnit, config: AnalysisConfig):
        if unit.file.path == ProjectPath("bad.py"):
            raise RuntimeError("fixture clone failure")
        return extract_clone_candidates(unit, config)

    monkeypatch.setattr("slop_measure.languages.python.adapter.extract_clone_candidates", extract)
    documents = (
        document(
            "bad.py", b"def f(flag):\n    value = True if flag else False\n    return value\n"
        ),
        document("good.py", b"a = 1\nb = 2\n"),
    )
    config = AnalysisConfig(clone_min_sloc=2)
    result = PythonAdapter().analyze(documents, config)
    assert result == PythonAdapter().analyze(documents, config.model_copy(update={"strict": True}))
    failed, success = result.clone_analyses
    assert isinstance(failed, FailedClones)
    assert failed.path == failed.diagnostic.path == ProjectPath("bad.py")
    assert failed.diagnostic.code == "python.clone-error"
    assert failed.diagnostic.severity is DiagnosticSeverity.ERROR
    assert isinstance(success, AnalyzedClones)
    assert len(success.candidates) == 1
    assert all(file.parse_state is ParseState.PARSED for file in result.files)
    assert len(result.functions) == 1
    assert result.patterns
    assert result.diagnostics == ()


def test_tree_sitter_recovery_is_a_clone_failure_not_an_empty_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery = Parser(Language(tree_sitter_python.language())).parse(b"value = )\n")
    assert recovery.root_node.has_error
    monkeypatch.setattr(
        "slop_measure.languages.python.clones.parse_python", lambda source: recovery
    )
    result = PythonAdapter().analyze(
        (document("app.py", b"a = 1\nb = 2\n"),), AnalysisConfig(clone_min_sloc=2)
    )
    assert result.files[0].parse_state is ParseState.PARSED
    assert isinstance(result.clone_analyses[0], FailedClones)
    assert result.clone_analyses[0].diagnostic.code == "python.clone-error"
    assert result.clone_candidates == ()


@pytest.mark.parametrize("tail, count", [("a=1;b=2", 1), ("c=3;d=4", 2)])
def test_same_line_runs_do_not_turn_valid_file_into_clone_failure(tail: str, count: int) -> None:
    result = PythonAdapter().analyze(
        (document("app.py", f"a=1;b=2;import os;{tail}\n".encode()),),
        AnalysisConfig(clone_min_sloc=1),
    )
    assert isinstance(result.clone_analyses[0], AnalyzedClones)
    assert len(result.clone_candidates) == count
