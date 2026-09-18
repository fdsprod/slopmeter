"""Defensive syntax whose extra step has no visible purpose."""

import ast
from collections.abc import Iterator
from itertools import pairwise

from slop_measure.domain.evidence import PatternCategory, SourceSpan
from slop_measure.languages.python.patterns import PythonParsedUnit
from slop_measure.languages.python.rules._shared import (
    ScopeIndex,
    header,
    if_header,
    is_none,
    none_test,
    rule,
    span,
    suites,
)

_GET_ARGUMENT_COUNT = 2


def _reraise(unit: PythonParsedUnit) -> Iterator[SourceSpan]:
    for node in ast.walk(unit.tree):
        if (
            not isinstance(node, ast.Try)
            or len(node.handlers) != 1
            or node.orelse
            or node.finalbody
        ):
            continue
        handler = node.handlers[0]
        if (
            handler.type is None
            and handler.name is None
            and len(handler.body) == 1
            and isinstance(handler.body[0], ast.Raise)
            and handler.body[0].exc is None
            and handler.body[0].cause is None
        ):
            found = header(
                unit, "except", handler.lineno, handler.body[0].lineno, handler.col_offset
            )
            if found is not None:
                yield SourceSpan(
                    start_line=found.start_line, end_line=span(handler.body[0]).end_line
                )


def _empty_finally(unit: PythonParsedUnit) -> Iterator[SourceSpan]:
    for node in ast.walk(unit.tree):
        if (
            isinstance(node, ast.Try | ast.TryStar)
            and len(node.finalbody) == 1
            and isinstance(node.finalbody[0], ast.Pass)
        ):
            last = node.finalbody[0]
            found = header(unit, "finally", node.lineno, last.lineno, node.col_offset)
            if found is not None:
                yield SourceSpan(start_line=found.start_line, end_line=span(last).end_line)


def _none_fallback(unit: PythonParsedUnit) -> Iterator[SourceSpan]:
    index = ScopeIndex(unit.tree)
    for node in ast.walk(unit.tree):
        if (
            not isinstance(node, ast.IfExp)
            or not isinstance(node.body, ast.Name)
            or not is_none(node.orelse)
        ):
            continue
        name = none_test(node.test, ast.IsNot)
        if name is not None and name == node.body.id and index.stable_local(node, name) is not None:
            yield span(node)


def _dict_default(unit: PythonParsedUnit) -> Iterator[SourceSpan]:
    for node in ast.walk(unit.tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Dict)
            and len(node.args) == _GET_ARGUMENT_COUNT
            and not node.keywords
            and not isinstance(node.args[0], ast.Starred)
            and is_none(node.args[1])
        ):
            yield span(node)


def _literal_guard(unit: PythonParsedUnit) -> Iterator[SourceSpan]:
    index = ScopeIndex(unit.tree)
    for body in suites(unit.tree):
        for assignment, guard in pairwise(body):
            if (
                not isinstance(assignment, ast.Assign)
                or len(assignment.targets) != 1
                or not isinstance(assignment.targets[0], ast.Name)
                or not isinstance(assignment.value, ast.Constant)
                or assignment.value.value is None
                or not isinstance(guard, ast.If)
            ):
                continue
            name = assignment.targets[0].id
            if (
                none_test(guard.test, ast.Is) == name
                and index.stable_local(guard, name) is not None
            ):
                found = if_header(unit, guard)
                if found is not None:
                    yield found


RULES = (
    rule(
        "redundant-except-reraise",
        PatternCategory.DEFENSIVE,
        "The handler only raises the same exception again.",
        _reraise,
    ),
    rule(
        "empty-finally",
        PatternCategory.DEFENSIVE,
        "The finally suite performs no cleanup.",
        _empty_finally,
    ),
    rule(
        "redundant-none-fallback",
        PatternCategory.DEFENSIVE,
        "The fallback returns the same local value in both cases.",
        _none_fallback,
    ),
    rule(
        "redundant-dict-get-default",
        PatternCategory.DEFENSIVE,
        "Dictionary get already defaults to None.",
        _dict_default,
    ),
    rule(
        "redundant-literal-none-guard",
        PatternCategory.DEFENSIVE,
        "The immediately assigned literal cannot be None.",
        _literal_guard,
    ),
)
