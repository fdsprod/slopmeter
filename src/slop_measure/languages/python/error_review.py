"""Source-only evidence for exception handlers that return literal defaults."""

import ast
from collections.abc import Iterable, Iterator
from itertools import takewhile

from slop_measure.domain.error_review import (
    AnalyzedErrorFile,
    AnalyzedErrorHandler,
    ErrorExpression,
    ErrorFallbackFinding,
    ErrorFallbackKind,
    ErrorFileResult,
    ErrorHandler,
    FailedErrorFile,
    UnresolvedErrorHandler,
)
from slop_measure.domain.evidence import Diagnostic, DiagnosticSeverity, SourceSpan
from slop_measure.domain.source import SourceDocument

_Function = ast.FunctionDef | ast.AsyncFunctionDef
_Scope = _Function | ast.ClassDef | ast.Lambda


class _Unresolved(Exception):
    """An unsupported syntax boundary, not a parse failure."""


def _span(node: ast.stmt | ast.expr | ast.ExceptHandler) -> SourceSpan:
    return SourceSpan(start_line=node.lineno, end_line=node.end_lineno or node.lineno)


def _walk_scope(nodes: Iterable[ast.AST], *, handlers: bool = False) -> Iterator[ast.AST]:
    for node in nodes:
        if isinstance(node, _Scope) or (isinstance(node, ast.ExceptHandler) and not handlers):
            continue
        yield node
        yield from _walk_scope(ast.iter_child_nodes(node), handlers=handlers)


def _fallback_kind(value: ast.expr | None) -> ErrorFallbackKind | None:
    if value is None or isinstance(value, ast.Constant):
        return _constant_kind(value.value if value is not None else None)
    if isinstance(value, ast.List) and not value.elts:
        return "empty-list"
    if isinstance(value, ast.Dict) and not value.keys:
        return "empty-dict"
    if isinstance(value, ast.Tuple) and not value.elts:
        return "empty-tuple"
    if (
        isinstance(value, ast.UnaryOp)
        and isinstance(value.op, (ast.UAdd, ast.USub))
        and isinstance(value.operand, ast.Constant)
        and _constant_kind(value.operand.value) == "zero"
    ):
        return "zero"
    return None


def _constant_kind(value: object) -> ErrorFallbackKind | None:
    if value is None:
        return "none"
    if value is False:
        return "false"
    if type(value) in (int, float, complex) and value == 0:
        return "zero"
    if value == "":
        return "empty-string"
    if value == b"":
        return "empty-bytes"
    return None


def _literal(value: ast.expr) -> bool:
    if isinstance(value, ast.Constant):
        return True
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        return all(_literal(item) for item in value.elts)
    if isinstance(value, ast.Dict):
        return all(key is not None and _literal(key) for key in value.keys) and all(
            _literal(item) for item in value.values
        )
    return (
        isinstance(value, ast.UnaryOp)
        and isinstance(value.op, (ast.UAdd, ast.USub))
        and isinstance(value.operand, ast.Constant)
        and type(value.operand.value) in (int, float, complex)
    )


def _exception_name(value: ast.expr) -> bool:
    if isinstance(value, ast.Name):
        return True
    return isinstance(value, ast.Attribute) and _exception_name(value.value)


def _caught(handler: ast.ExceptHandler) -> str:
    value = handler.type
    if value is None:
        return "bare except"
    if _exception_name(value) or (
        isinstance(value, ast.Tuple) and all(_exception_name(item) for item in value.elts)
    ):
        return ast.unparse(value)
    raise _Unresolved("The exception expression is dynamic or unsupported.")


def _return_expression(statement: ast.Return) -> ErrorExpression:
    return ErrorExpression(
        span=_span(statement),
        expression=ast.unparse(statement.value) if statement.value is not None else "None",
    )


def _handler_return(handler: ast.ExceptHandler) -> ast.Return | None:
    for statement in handler.body[:-1]:
        if isinstance(statement, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
            raise _Unresolved("An early exit precedes the end of the handler.")
        _simple_statement(statement)
    final = handler.body[-1]
    if isinstance(final, ast.Return):
        return final
    if not isinstance(final, ast.Raise):
        _simple_statement(final)
    return None


def _simple_statement(statement: ast.stmt) -> None:
    if not isinstance(statement, (ast.Expr, ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Pass)):
        raise _Unresolved(
            "Handler control flow or another statement is outside the supported slice."
        )


def _normal_returns(function: _Function) -> tuple[ErrorExpression, ...]:
    return tuple(
        _return_expression(node)
        for node in _walk_scope(function.body)
        if isinstance(node, ast.Return)
        and node.value is not None
        and _fallback_kind(node.value) is None
    )


def _findings(
    handler: ast.ExceptHandler,
    protected: ast.Try,
    function: _Function,
) -> tuple[ErrorFallbackFinding, ...]:
    caught = _caught(handler)
    statement = _handler_return(handler)
    if statement is None:
        return ()
    kind = _fallback_kind(statement.value)
    if kind is None:
        if statement.value is not None and _literal(statement.value):
            return ()
        raise _Unresolved("An indirect return value cannot establish a literal fallback.")
    normal_returns = _normal_returns(function)
    if not normal_returns:
        return ()
    return (
        ErrorFallbackFinding(
            caught=caught,
            protected=SourceSpan(
                start_line=protected.body[0].lineno,
                end_line=protected.body[-1].end_lineno or protected.body[-1].lineno,
            ),
            operations=tuple(
                ErrorExpression(span=_span(node), expression=ast.unparse(node))
                for node in _walk_scope(protected.body)
                if isinstance(node, ast.Call)
            ),
            fallback=_return_expression(statement),
            fallback_kind=kind,
            normal_returns=normal_returns,
        ),
    )


def _ancestors(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> Iterator[ast.AST]:
    while node in parents:
        node = parents[node]
        yield node


def _context(
    ancestors: tuple[ast.AST, ...],
) -> tuple[ast.Try, _Function]:
    protected = ancestors[0]
    if isinstance(protected, ast.TryStar):
        raise _Unresolved("except* handlers are outside the supported slice.")
    if not isinstance(protected, ast.Try):
        raise _Unresolved("The exception handler has no supported try body.")
    scope = next((node for node in ancestors if isinstance(node, _Scope)), None)
    if not isinstance(scope, _Function):
        raise _Unresolved("Module/class-level exception handlers are outside function analysis.")
    enclosing = takewhile(lambda node: node is not scope, ancestors)
    if any(isinstance(node, (ast.Try, ast.TryStar)) and node.finalbody for node in enclosing):
        raise _Unresolved("An enclosing finally block can replace the observed return.")
    if any(
        isinstance(node, (ast.Yield, ast.YieldFrom))
        for node in _walk_scope(scope.body, handlers=True)
    ):
        raise _Unresolved("Generator function handlers have a different return contract.")
    return protected, scope


def _assess(handler: ast.ExceptHandler, parents: dict[ast.AST, ast.AST]) -> ErrorHandler:
    ancestors = tuple(_ancestors(handler, parents))
    symbol = (
        ".".join(
            node.name for node in reversed(ancestors) if isinstance(node, _Function | ast.ClassDef)
        )
        or "<module>"
    )
    try:
        protected, function = _context(ancestors)
        return AnalyzedErrorHandler(
            symbol=symbol,
            span=_span(handler),
            findings=_findings(handler, protected, function),
        )
    except _Unresolved as error:
        return UnresolvedErrorHandler(symbol=symbol, span=_span(handler), reason=str(error))


def analyze_errors(document: SourceDocument) -> ErrorFileResult:
    """Parse source without executing it and retain every handler's analysis state."""
    if document.language != "python":
        raise ValueError("Python error review requires Python source")
    try:
        tree = ast.parse(document.content, filename=document.path.root)
    except (SyntaxError, UnicodeError, ValueError) as error:
        return FailedErrorFile(
            path=document.path,
            cohort=document.cohort,
            source_sha256=document.content_hash,
            diagnostic=Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="python.error-review-parse-error",
                message=str(error),
                path=document.path,
            ),
        )
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    handlers = sorted(
        (node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)),
        key=lambda node: (node.lineno, node.col_offset),
    )
    return AnalyzedErrorFile(
        path=document.path,
        cohort=document.cohort,
        source_sha256=document.content_hash,
        handlers=tuple(_assess(handler, parents) for handler in handlers),
    )
