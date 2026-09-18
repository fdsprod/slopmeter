"""Retained observations of Python AST, token positions, and source decoding."""

import ast
import codecs
import io
import tokenize

import pytest


def test_parenthesized_docstring_expression_span_includes_delimiters() -> None:
    source = '(\n    "module docs"\n)\nvalue = 1\n'
    tree = ast.parse(source)
    expression = tree.body[0]
    assert isinstance(expression, ast.Expr)
    # Expr covers parentheses; Constant covers only the literal. Excluding only
    # Constant lines would incorrectly retain the two delimiter-only lines.
    assert ast.get_docstring(tree) == "module docs"
    assert (expression.lineno, expression.end_lineno) == (1, 3)
    assert (expression.value.lineno, expression.value.end_lineno) == (2, 2)


def test_semicolon_docstring_and_code_have_distinct_spans_on_the_same_line() -> None:
    tree = ast.parse('"docs"; value = 1\n')
    # Removing a docstring must not remove the following statement's line.
    assert ast.get_docstring(tree) == "docs"
    assert [(node.lineno, node.col_offset) for node in tree.body] == [(1, 0), (1, 8)]


def test_ast_columns_are_utf8_bytes_but_token_columns_are_characters() -> None:
    source = '"é"; value = 1\n'
    tree = ast.parse(source)
    tokens = tuple(tokenize.generate_tokens(io.StringIO(source).readline))
    name = next(token for token in tokens if token.string == "value")
    # These coordinate systems differ even though both consume a Python str.
    assert tree.body[1].col_offset == 6
    assert name.start == (1, 5)


@pytest.mark.parametrize(
    ("source", "encoding", "text"),
    [
        (b"# coding: latin-1\nname = '\xe9'\n", "iso-8859-1", "name = 'é'"),
        (codecs.BOM_UTF8 + b"value = 1\n", "utf-8-sig", "value = 1"),
    ],
)
def test_detect_encoding_honors_cookie_and_strips_bom(
    source: bytes, encoding: str, text: str
) -> None:
    detected, _ = tokenize.detect_encoding(io.BytesIO(source).readline)
    # detect_encoding names the decoder; the returned prefix is not the full file.
    assert detected == encoding
    decoded = source.decode(detected)
    assert text in decoded
    assert isinstance(ast.parse(decoded), ast.Module)


@pytest.mark.parametrize(
    "source",
    [codecs.BOM_UTF8 + b"# coding: latin-1\n", b"# coding: missing-encoding\n"],
)
def test_invalid_encoding_declarations_raise_syntax_error(source: bytes) -> None:
    # Encoding discovery can raise SyntaxError, not just UnicodeDecodeError.
    with pytest.raises(SyntaxError):
        tokenize.detect_encoding(io.BytesIO(source).readline)


def test_unclosed_statement_raises_token_error_but_ast_raises_syntax_error() -> None:
    source = "value = (\n"
    # Token iteration is lazy: the error occurs while consuming the generator.
    with pytest.raises(tokenize.TokenError):
        tuple(tokenize.generate_tokens(io.StringIO(source).readline))
    with pytest.raises(SyntaxError):
        ast.parse(source)


def test_unterminated_string_raises_a_tokenizer_error() -> None:
    # The supported Python tokenizer raises rather than yielding an error token
    # for an unterminated single-quoted string.
    with pytest.raises(tokenize.TokenError, match="unterminated string"):
        tuple(tokenize.generate_tokens(io.StringIO("value = 'oops\n").readline))
