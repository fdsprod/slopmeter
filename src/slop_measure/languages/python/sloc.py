"""Exact physical Python source lines shared by all evidence families."""

import ast
import io
import tokenize

type _Position = tuple[int, int]
type _Span = tuple[_Position, _Position]

_NON_CODE_TOKENS = frozenset(
    {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
        tokenize.ENCODING,
    }
)


def _docstring_spans(tree: ast.Module, lines: list[str]) -> list[_Span]:
    spans: list[_Span] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not node.body:
            continue
        expression = node.body[0]
        if not (
            isinstance(expression, ast.Expr)
            and isinstance(expression.value, ast.Constant)
            and isinstance(expression.value.value, str)
        ):
            continue
        end_line = expression.end_lineno
        end_column = expression.end_col_offset
        if end_line is None or end_column is None:
            raise ValueError("docstring expression must include its end position")
        # AST columns count UTF-8 bytes. Tokenizer columns count characters.
        start_column = len(
            lines[expression.lineno - 1].encode("utf-8")[: expression.col_offset].decode("utf-8")
        )
        end_column = len(lines[end_line - 1].encode("utf-8")[:end_column].decode("utf-8"))
        spans.append(((expression.lineno, start_column), (end_line, end_column)))
    return sorted(spans)


def classify_sloc(source: str, tree: ast.Module) -> tuple[int, ...]:
    """Return code-bearing lines, excluding comments, blanks, and true docstrings."""
    # Universal newlines keep tokenizer rows aligned with AST rows for every source encoding.
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    lines = source.split("\n")
    docstrings = _docstring_spans(tree, lines)
    docstring_index = 0
    code_lines: set[int] = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in _NON_CODE_TOKENS or token.string == ";":
            continue
        while docstring_index < len(docstrings) and docstrings[docstring_index][1] <= token.start:
            docstring_index += 1
        if docstring_index < len(docstrings):
            start, end = docstrings[docstring_index]
            if start <= token.start and token.end <= end:
                continue
        code_lines.update(
            row for row in range(token.start[0], token.end[0] + 1) if lines[row - 1].strip()
        )
    return tuple(sorted(code_lines))
