"""Small abstraction redundancies with explicit local-use and API guards."""

import ast
from collections.abc import Iterator
from itertools import pairwise

from slop_measure.domain.evidence import PatternCategory, SourceSpan
from slop_measure.languages.python.patterns import PythonParsedUnit
from slop_measure.languages.python.rules._shared import (
    ScopeIndex,
    builtin_available,
    has_type_comment,
    rule,
    span,
    suites,
    unique_use,
)


def _real_statement(node: ast.stmt) -> bool:
    return not (
        isinstance(node, ast.Pass)
        or (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and (isinstance(node.value.value, str) or node.value.value is Ellipsis)
        )
    )


def _redundant_pass(unit: PythonParsedUnit) -> Iterator[SourceSpan]:
    for node in ast.walk(unit.tree):
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and any(
            _real_statement(statement) for statement in node.body
        ):
            yield from (
                span(statement) for statement in node.body if isinstance(statement, ast.Pass)
            )


def _object_base(unit: PythonParsedUnit) -> Iterator[SourceSpan]:
    if not builtin_available(unit.tree, "object"):
        return
    for node in ast.walk(unit.tree):
        if (
            isinstance(node, ast.ClassDef)
            and len(node.bases) == 1
            and not node.keywords
            and not node.decorator_list
            and isinstance(node.bases[0], ast.Name)
            and node.bases[0].id == "object"
        ):
            yield span(node.bases[0])


def _default_metaclass(unit: PythonParsedUnit) -> Iterator[SourceSpan]:
    if not builtin_available(unit.tree, "type"):
        return
    for node in ast.walk(unit.tree):
        if (
            isinstance(node, ast.ClassDef)
            and not node.bases
            and not node.decorator_list
            and len(node.keywords) == 1
            and node.keywords[0].arg == "metaclass"
            and isinstance(node.keywords[0].value, ast.Name)
            and node.keywords[0].value.id == "type"
        ):
            yield span(node.keywords[0])


def _plain_forwarder(node: ast.FunctionDef) -> bool:
    arguments = node.args
    if (
        node.decorator_list
        or node.returns
        or node.type_comment
        or node.type_params
        or arguments.posonlyargs
        or arguments.kwonlyargs
        or arguments.vararg
        or arguments.kwarg
        or arguments.defaults
        or arguments.kw_defaults
        or any(arg.annotation for arg in arguments.args)
        or len(node.body) != 1
        or not isinstance(node.body[0], ast.Return)
    ):
        return False
    call = node.body[0].value
    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id != node.name
        and not call.keywords
        and len(call.args) == len(arguments.args)
        and all(
            isinstance(value, ast.Name) and value.id == parameter.arg
            for value, parameter in zip(call.args, arguments.args, strict=True)
        )
    )


def _trivial_wrapper(unit: PythonParsedUnit) -> Iterator[SourceSpan]:
    index = ScopeIndex(unit.tree)
    for body in suites(unit.tree):
        for helper, following in pairwise(body):
            if (
                not isinstance(helper, ast.FunctionDef)
                or not helper.name.startswith("_")
                or not _plain_forwarder(helper)
                or has_type_comment(unit, helper)
            ):
                continue
            owner = index.stable_local(helper, helper.name)
            if owner is None or not unique_use(owner, helper.name):
                continue
            if (
                isinstance(following, ast.Return | ast.Expr | ast.Assign)
                and isinstance(following.value, ast.Call)
                and isinstance(following.value.func, ast.Name)
                and following.value.func.id == helper.name
            ):
                yield span(helper)


def _return_binding(unit: PythonParsedUnit) -> Iterator[SourceSpan]:
    index = ScopeIndex(unit.tree)
    for body in suites(unit.tree):
        for assignment, following in pairwise(body):
            if (
                not isinstance(assignment, ast.Assign)
                or has_type_comment(unit, assignment)
                or len(assignment.targets) != 1
                or not isinstance(assignment.targets[0], ast.Name)
                or not isinstance(following, ast.Return)
                or not isinstance(following.value, ast.Name)
                or following.value.id != assignment.targets[0].id
                or any(
                    isinstance(node, ast.Yield | ast.YieldFrom | ast.Await)
                    for node in ast.walk(assignment.value)
                )
            ):
                continue
            name = assignment.targets[0].id
            owner = index.stable_local(assignment, name)
            if owner is not None and unique_use(owner, name):
                yield span(assignment)


RULES = (
    rule(
        "redundant-pass",
        PatternCategory.ABSTRACTION,
        "This pass is unnecessary beside an existing statement.",
        _redundant_pass,
    ),
    rule(
        "explicit-object-base",
        PatternCategory.ABSTRACTION,
        "Classes already inherit from object by default.",
        _object_base,
    ),
    rule(
        "explicit-default-metaclass",
        PatternCategory.ABSTRACTION,
        "The explicit metaclass repeats the default type.",
        _default_metaclass,
    ),
    rule(
        "trivial-wrapper",
        PatternCategory.ABSTRACTION,
        "This private local wrapper only forwards its arguments once.",
        _trivial_wrapper,
    ),
    rule(
        "single-use-return-binding",
        PatternCategory.ABSTRACTION,
        "This local binding is used only by the following return.",
        _return_binding,
    ),
)
