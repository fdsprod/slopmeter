"""Convert Radon complexity into owned evidence with AST source identities."""

import ast
from collections.abc import Iterator

from radon.complexity import cc_visit_ast
from radon.visitors import Function

from slop_measure.domain.evidence import FileEvidence, FunctionEvidence, SourceSpan

type _Callable = ast.FunctionDef | ast.AsyncFunctionDef


def _callables(node: ast.AST, ancestors: tuple[str, ...] = ()) -> Iterator[tuple[_Callable, str]]:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        ancestors = (*ancestors, node.name)
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        yield node, ".".join(ancestors)
    for child in ast.iter_child_nodes(node):
        yield from _callables(child, ancestors)


def _complexity(node: _Callable) -> int:
    # Visit each callable directly: module-level Radon results omit local classes.
    records = [
        record
        for record in cc_visit_ast(node)
        if isinstance(record, Function)
        and record.name == node.name
        and record.lineno == node.lineno
        and record.col_offset == node.col_offset
    ]
    if len(records) != 1:
        raise ValueError("Radon must return one complexity record for each callable")
    return records[0].complexity


def extract_functions(tree: ast.Module, file: FileEvidence) -> tuple[FunctionEvidence, ...]:
    """Extract every lexical callable once, reusing the supplied AST and SLOC."""
    functions: list[FunctionEvidence] = []
    for node, qualified_name in _callables(tree):
        if node.end_lineno is None:
            raise ValueError("callable AST must include its end line")
        span = SourceSpan(start_line=node.lineno, end_line=node.end_lineno)
        functions.append(
            FunctionEvidence(
                path=file.path,
                qualified_name=qualified_name,
                span=span,
                cyclomatic_complexity=_complexity(node),
                sloc_lines=tuple(
                    line for line in file.sloc_lines if span.start_line <= line <= span.end_line
                ),
            )
        )
    return tuple(
        sorted(
            functions,
            key=lambda item: (item.span.start_line, item.span.end_line, item.qualified_name),
        )
    )
