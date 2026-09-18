"""Complete-run clone extraction retains semantics and exact source ownership."""

import ast

import pytest

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import FileEvidence, ParseState
from slop_measure.domain.source import Cohort, ProjectPath
from slop_measure.languages.python.clones import extract_clone_candidates
from slop_measure.languages.python.parsing import NORMALIZATION_VERSION
from slop_measure.languages.python.patterns import PythonParsedUnit
from slop_measure.languages.python.sloc import classify_sloc


def unit(source: str) -> PythonParsedUnit:
    tree = ast.parse(source)
    lines = classify_sloc(source, tree)
    file = FileEvidence(
        path=ProjectPath("app.py"),
        language="python",
        cohort=Cohort.PRODUCTION,
        parse_state=ParseState.PARSED,
        sloc=len(lines),
        sloc_lines=lines,
    )
    return PythonParsedUnit(tree=tree, file=file, source=source)


def candidates(source: str, *, statements: int = 2, sloc: int = 2):
    return extract_clone_candidates(
        unit(source), AnalysisConfig(clone_min_statements=statements, clone_min_sloc=sloc)
    )


def test_version_and_exact_complete_run_ownership() -> None:
    source = "# leading\na = 1\n\n# inside\nb = 2\n"
    result = candidates(source)
    assert NORMALIZATION_VERSION == "py-clones-1"
    assert len(result) == 1
    block = result[0]
    assert block.path == ProjectPath("app.py")
    assert (block.span.start_line, block.span.end_line) == (2, 5)
    assert block.sloc_lines == (2, 5)
    assert block.statement_count == 2
    assert block.normalization_version == NORMALIZATION_VERSION
    assert block.normalized_tokens
    assert len(block.fingerprint) == 64
    assert result == candidates(source)


def test_thresholds_are_inclusive_and_independent() -> None:
    assert len(candidates("a = 1\nb = 2\n")) == 1
    assert candidates("a = 1\nb = 2\n", statements=3) == ()
    assert candidates("a = 1\nb = 2\n", sloc=3) == ()
    assert candidates("a = 1; b = 2\n") == ()
    assert len(candidates("a = 1; b = 2\n", sloc=1)) == 1


def test_imports_and_definitions_split_runs_and_docstrings_are_excluded() -> None:
    source = (
        '"module docs"\na = 1\nb = 2\nimport os\nc = 3\nd = 4\n'
        '@decorate\ndef f(value):\n    "function docs"\n    local = value\n'
        '    return local\nclass C:\n    "class docs"\n    x = 1\n    y = 2\n'
    )
    result = candidates(source)
    assert {(item.span.start_line, item.span.end_line) for item in result} == {
        (2, 3),
        (5, 6),
        (10, 11),
        (14, 15),
    }


def test_nested_suites_count_only_direct_siblings_and_keep_full_run() -> None:
    source = "if flag:\n    a = 1\n    b = 2\nc = 3\nd = 4\n"
    result = candidates(source)
    assert {
        (item.span.start_line, item.span.end_line, item.statement_count) for item in result
    } == {(1, 5, 3), (2, 3, 2)}
    assert len(candidates("a = 1\nb = 2\nc = 3\n")) == 1


def test_callable_parameters_and_local_binding_identity_can_be_renamed() -> None:
    first = candidates("def f(source):\n    local = source\n    return consume(local)\n")[0]
    second = candidates("def g(payload):\n    result = payload\n    return consume(result)\n")[0]
    assert first.normalized_tokens == second.normalized_tokens
    assert first.fingerprint == second.fingerprint


def test_comments_whitespace_crlf_and_unicode_do_not_change_tokens() -> None:
    first = candidates("def f(entrée):\n    résultat = entrée + 1\n    return résultat\n")[0]
    second = candidates(
        "def g(payload):\r\n    result=payload+1 # comment\r\n\r\n    return result\r\n"
    )[0]
    assert first.normalized_tokens == second.normalized_tokens
    assert second.sloc_lines == (2, 4)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("a = 1\nb = a", "x = 1\ny = x"),
        ("class C:\n    a = 1\n    b = a", "class C:\n    x = 1\n    y = x"),
        ("a = 1\nb = a + 2", "a = 1\nb = a - 2"),
        ("a = 1\nb = a", "a = 1.0\nb = a"),
        ("a = 1\nb = a", "a = True\nb = a"),
        ("a = 'red'\nb = a", 'a = "red"\nb = a'),
        ("a = 16\nb = a", "a = 0x10\nb = a"),
        ("a = transform(source)\nb = a", "a = convert(source)\nb = a"),
        ("a = obj.left\nb = a", "a = obj.right\nb = a"),
        ("a = call(mode=1)\nb = a", "a = call(option=1)\nb = a"),
        ('a = f"{source!r}"\nb = a', 'a = f"{source!s}"\nb = a'),
    ],
)
def test_semantic_names_operators_and_literal_spelling_remain_distinct(
    left: str, right: str
) -> None:
    assert candidates(left)[0].normalized_tokens != candidates(right)[0].normalized_tokens


@pytest.mark.parametrize(
    "uncertain",
    [
        "global cache",
        "nonlocal captured",
        "exec(code)",
        "eval(code)",
        "locals()",
        "globals()",
        "vars()",
        "items = [item for item in source]",
        "callback = lambda value: value",
        "check = (value := source)",
    ],
)
def test_uncertain_callable_binding_retains_exact_names(uncertain: str) -> None:
    first = f"def f(source):\n    {uncertain}\n    local = source\n    return local\n"
    second = f"def f(source):\n    {uncertain}\n    result = source\n    return result\n"
    assert candidates(first)[0].normalized_tokens != candidates(second)[0].normalized_tokens


def test_alias_relationships_survive_local_renaming() -> None:
    first = candidates("def f(x, y):\n    a = x\n    b = y\n    return a + b\n")[0]
    second = candidates("def f(x, y):\n    a = x\n    b = y\n    return a + a\n")[0]
    assert first.normalized_tokens != second.normalized_tokens


def test_later_bare_string_is_executable_and_not_a_docstring_separator() -> None:
    result = candidates('a = 1\n"later string"\nb = 2\n', statements=3)
    assert len(result) == 1
    assert result[0].statement_count == 3
    assert result[0].sloc_lines == (1, 2, 3)


def test_explicit_line_continuation_is_formatting_trivia() -> None:
    compact = candidates("a = source + 1\nb = a\n")[0]
    continued = candidates("a = source + \\\n    1\nb = a\n")[0]
    assert compact.normalized_tokens == continued.normalized_tokens
    assert continued.sloc_lines == (1, 2, 3)


def test_match_case_container_is_not_an_executable_sibling_run() -> None:
    result = candidates(
        "match source:\n    case 1:\n        a = 1\n        consume(a)\n"
        "    case 2:\n        b = 2\n        consume(b)\n"
    )
    assert {(item.span.start_line, item.span.end_line) for item in result} == {(3, 4), (6, 7)}
