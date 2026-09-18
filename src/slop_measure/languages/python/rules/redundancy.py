"""Redundant expressions with explicit literal guards."""

import ast
from collections.abc import Iterator

from slop_measure.domain.evidence import PatternCategory, SourceSpan
from slop_measure.languages.python.patterns import PythonParsedUnit
from slop_measure.languages.python.rules._shared import builtin_available, rule, span


def _booleans(unit: PythonParsedUnit, positive: bool) -> Iterator[SourceSpan]:
    for node in ast.walk(unit.tree):
        if (
            isinstance(node, ast.IfExp)
            and isinstance(node.body, ast.Constant)
            and isinstance(node.orelse, ast.Constant)
            and node.body.value is positive
            and node.orelse.value is (not positive)
        ):
            yield span(node)


def _literal_fstring(unit: PythonParsedUnit) -> Iterator[SourceSpan]:
    format_specs = {
        node.format_spec for node in ast.walk(unit.tree) if isinstance(node, ast.FormattedValue)
    }
    for node in ast.walk(unit.tree):
        if (
            isinstance(node, ast.JoinedStr)
            and node not in format_specs
            and all(isinstance(value, ast.Constant) for value in node.values)
        ):
            yield span(node)


def _identity_comprehension(unit: PythonParsedUnit) -> Iterator[SourceSpan]:
    for node in ast.walk(unit.tree):
        if not isinstance(node, ast.ListComp) or len(node.generators) != 1:
            continue
        generator = node.generators[0]
        if (
            not generator.is_async
            and not generator.ifs
            and isinstance(generator.target, ast.Name)
            and isinstance(node.elt, ast.Name)
            and generator.target.id == node.elt.id
            and isinstance(generator.iter, ast.List | ast.Tuple)
            and not any(isinstance(item, ast.Starred) for item in generator.iter.elts)
        ):
            yield span(node)


def _literal_container(unit: PythonParsedUnit) -> Iterator[SourceSpan]:
    kinds = {"list": ast.List, "tuple": ast.Tuple, "set": ast.Set, "dict": ast.Dict}
    available = {name for name in kinds if builtin_available(unit.tree, name)}
    for node in ast.walk(unit.tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in available
            and len(node.args) == 1
            and not node.keywords
            and isinstance(node.args[0], kinds[node.func.id])
        ):
            yield span(node)


RULES = (
    rule(
        "boolean-conditional",
        PatternCategory.REDUNDANCY,
        "Replace the boolean conditional with a boolean conversion.",
        lambda unit: _booleans(unit, True),
    ),
    rule(
        "negated-boolean-conditional",
        PatternCategory.REDUNDANCY,
        "The conditional returns the negated truth value.",
        lambda unit: _booleans(unit, False),
    ),
    rule(
        "literal-fstring",
        PatternCategory.REDUNDANCY,
        "Remove the unused f-string prefix.",
        _literal_fstring,
        remediation=(
            "Preserve the decoded string value, including escaped braces, "
            "when using a plain string."
        ),
    ),
    rule(
        "literal-identity-comprehension",
        PatternCategory.REDUNDANCY,
        "The comprehension copies each literal element unchanged.",
        _identity_comprehension,
    ),
    rule(
        "redundant-literal-container",
        PatternCategory.REDUNDANCY,
        "The constructor repeats the literal container type.",
        _literal_container,
    ),
)
