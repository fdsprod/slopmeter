"""Annotate import syntax without predicting target execution."""

import ast
from collections import Counter
from typing import Literal

from slop_measure.domain.architecture import ImportContext
from slop_measure.languages.python.rules._shared import bound_names

Guard = Literal["type-checking", "conditional"]


def _typing_bindings(tree: ast.Module) -> dict[str, tuple[str, int]]:
    # A module import is trusted only when no competing binding exists anywhere.
    # This deliberately leaves some harmless shadowing unresolved as conditional.
    bindings = Counter(name for node in ast.walk(tree) for name in bound_names(node))
    if any(
        (isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names))
        or (isinstance(node, ast.Name) and node.id in {"exec", "eval", "globals"})
        for node in ast.walk(tree)
    ):
        return {}
    candidates: dict[str, tuple[str, int]] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "typing":
                    candidates[alias.asname or alias.name] = ("module", node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module == "typing" and not node.level:
            for alias in node.names:
                if alias.name == "TYPE_CHECKING":
                    candidates[alias.asname or alias.name] = ("flag", node.lineno)
    mutated = {
        node.value.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.ctx, (ast.Store, ast.Del))
        and isinstance(node.value, ast.Name)
    }
    return {
        name: value
        for name, value in candidates.items()
        if bindings[name] == 1 and name not in mutated
    }


def _guard(node: ast.If, bindings: dict[str, tuple[str, int]]) -> Guard:
    test = node.test
    if isinstance(test, ast.Name):
        match = bindings.get(test.id)
        if match and match[0] == "flag" and match[1] < node.lineno:
            return "type-checking"
    elif (
        isinstance(test, ast.Attribute)
        and test.attr == "TYPE_CHECKING"
        and isinstance(test.value, ast.Name)
    ):
        match = bindings.get(test.value.id)
        if match and match[0] == "module" and match[1] < node.lineno:
            return "type-checking"
    return "conditional"


def _guarded(context: ImportContext, guard: Guard) -> ImportContext:
    return ImportContext(
        execution=context.execution, guards=tuple(sorted({*context.guards, guard}))
    )


def import_contexts(tree: ast.Module) -> dict[ast.AST, ImportContext]:
    """Separate function-body timing from guards; class bodies keep enclosing timing."""
    bindings = _typing_bindings(tree)
    contexts: dict[ast.AST, ImportContext] = {}
    pending: list[tuple[ast.AST, ImportContext]] = [(tree, ImportContext(execution="eager"))]
    outer_iterators: dict[ast.AST, ImportContext] = {}
    while pending:
        node, context = pending.pop()
        context = outer_iterators.get(node, context)
        contexts[node] = context
        if isinstance(node, ast.GeneratorExp) and node.generators:
            outer_iterators[node.generators[0].iter] = context
        for field, value in ast.iter_fields(node):
            selected = context
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
                and field == "body"
            ):
                selected = ImportContext(execution="deferred", guards=context.guards)
            elif isinstance(node, ast.If) and field in {"body", "orelse"}:
                selected = _guarded(
                    context, _guard(node, bindings) if field == "body" else "conditional"
                )
            elif isinstance(
                node,
                (
                    ast.For,
                    ast.AsyncFor,
                    ast.While,
                    ast.Try,
                    ast.TryStar,
                    ast.With,
                    ast.AsyncWith,
                    ast.Match,
                    ast.ExceptHandler,
                ),
            ):
                selected = _guarded(context, "conditional")
            elif isinstance(node, ast.GeneratorExp):
                selected = ImportContext(execution="deferred", guards=context.guards)
            elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp)):
                selected = _guarded(context, "conditional")
            children = value if isinstance(value, list) else [value]
            pending.extend((child, selected) for child in children if isinstance(child, ast.AST))
    return contexts
