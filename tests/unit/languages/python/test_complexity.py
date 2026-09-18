"""AST callable extraction keeps lexical identity and exact physical source spans."""

import ast

import pytest

from slop_measure.domain.evidence import FileEvidence
from slop_measure.languages.python.complexity import extract_functions


def file(lines: tuple[int, ...]) -> FileEvidence:
    return FileEvidence.model_validate(
        {
            "path": "app.py",
            "language": "python",
            "cohort": "production",
            "sloc": len(lines),
            "sloc_lines": lines,
            "parse_state": "parsed",
        }
    )


def test_extractor_visits_each_lexical_callable_without_class_aggregates() -> None:
    source = (
        "def top(flag):\n"
        "    if flag:\n"
        "        return 1\n"
        "    return 0\n"
        "class Outer:\n"
        "    async def method(self, flag):\n"
        "        def inner(value):\n"
        "            return value\n"
        "        class Local:\n"
        "            def act(self, flag):\n"
        "                if flag:\n"
        "                    return 1\n"
        "                return 0\n"
        "        return inner(flag)\n"
        "def duplicate():\n"
        "    return 1\n"
        "def duplicate():\n"
        "    return 2\n"
    )
    functions = extract_functions(ast.parse(source), file(tuple(range(1, 19))))
    assert isinstance(functions, tuple)
    assert [
        (item.qualified_name, item.span.start_line, item.span.end_line, item.cyclomatic_complexity)
        for item in functions
    ] == [
        ("top", 1, 4, 2),
        ("Outer.method", 6, 14, 1),
        ("Outer.method.inner", 7, 8, 1),
        ("Outer.method.Local.act", 10, 13, 2),
        ("duplicate", 15, 16, 1),
        ("duplicate", 17, 18, 1),
    ]
    assert functions[1].sloc_lines == tuple(range(6, 15))
    assert functions[3].sloc_lines == (10, 11, 12, 13)


def test_ast_span_keeps_closing_punctuation_omits_decorators_and_intersects_sloc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = '@decorate\ndef f(\n    value,\n):\n    "docs"\n    return (\n        value\n    )\n'
    tree = ast.parse(source)

    def unexpected_parse(*args: object, **kwargs: object):
        raise AssertionError("Extractor must reuse the supplied AST")

    monkeypatch.setattr(ast, "parse", unexpected_parse)
    functions = extract_functions(tree, file((1, 2, 3, 4, 6, 7, 8)))

    assert len(functions) == 1
    assert (functions[0].span.start_line, functions[0].span.end_line) == (2, 8)
    assert functions[0].sloc_lines == (2, 3, 4, 6, 7, 8)
    assert functions[0].cyclomatic_complexity == 1


def test_module_without_callables_has_an_empty_result() -> None:
    assert extract_functions(ast.parse("VALUE = 1\n"), file((1,))) == ()
