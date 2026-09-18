"""Physical Python source-line contracts, independent of parser implementation."""

import ast

import pytest

from slop_measure.languages.python.sloc import classify_sloc


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("", ()),
        ("\n # comment\n\t\n", ()),
        ('"module docs"\n', ()),
        ('(\n "module docs"\n)\nvalue = 1\n', (4,)),
        ('"docs"; value = 1\n', (1,)),
        ('"é"; value = 1\n', (1,)),
        ('value = 1\n"not a docstring"\n', (1, 2)),
        ('b"not a docstring"\n', (1,)),
        ('f"not a docstring"\n', (1,)),
        ("value = (\n # comment\n  1 +\n  2\n)\n", (1, 3, 4, 5)),
        ('value = """first\n\n# literal content\nlast\n"""\n', (1, 3, 4, 5)),
        ('value = 1\n"""bare\ntext\n"""\n', (1, 2, 3, 4)),
        ("# comment\r\nvalue = 'é'\r\n\r\nother = 2", (2, 4)),
        ('def f(): "docs"\n', (1,)),
        ('def f():\n    "docs"; return 1\n', (1, 2)),
        ('class C:\n    ("class docs")\n    value = 1\n', (1, 3)),
        ('async def f():\n    "docs"\n    return 1\n', (1, 3)),
        ('@decorator\ndef f():\n    """docs\n    text\n    """\n    return 1\n', (1, 2, 6)),
        ('if True:\n    "not a docstring"\n', (1, 2)),
        ('"""docs\ntext\n"""; value = 1\n', (3,)),
    ],
)
def test_classification_preserves_exact_code_bearing_lines(
    source: str, expected: tuple[int, ...]
) -> None:
    assert classify_sloc(source, ast.parse(source)) == expected


def test_nested_docstrings_are_removed_without_removing_enclosing_headers() -> None:
    source = """"module docs"
class C:
    "class docs"
    def method(self):
        "method docs"
        def nested():
            "nested docs"
            return 1
        return nested()
"""
    assert classify_sloc(source, ast.parse(source)) == (2, 4, 6, 8, 9)


def test_classifier_reuses_the_supplied_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    source = "value = 1\n"
    tree = ast.parse(source)

    def reject_parse(*args: object, **kwargs: object) -> ast.Module:
        raise AssertionError("the caller already parsed the source")

    monkeypatch.setattr(ast, "parse", reject_parse)
    assert classify_sloc(source, tree) == (1,)


def test_multiline_fstring_semicolon_content_is_a_source_line() -> None:
    source = 'value = f"""first\n;\nlast\n"""\n'
    assert classify_sloc(source, ast.parse(source)) == (1, 2, 3, 4)
