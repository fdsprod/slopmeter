"""Direct control-flow redundancies with token-based header spans."""

import ast
from collections.abc import Iterator

from slop_measure.domain.evidence import PatternCategory, SourceSpan
from slop_measure.languages.python.patterns import PythonParsedUnit
from slop_measure.languages.python.rules._shared import header, if_header, rule


def _redundant_else(unit: PythonParsedUnit, terminal: type[ast.stmt]) -> Iterator[SourceSpan]:
    for node in ast.walk(unit.tree):
        if (
            not isinstance(node, ast.If)
            or not node.orelse
            or not node.body
            or not isinstance(node.body[-1], terminal)
            or if_header(unit, node) is None
        ):
            continue
        found = header(
            unit,
            "else",
            node.body[-1].end_lineno or node.body[-1].lineno,
            node.orelse[0].lineno,
            node.col_offset,
        )
        if found is not None:
            yield found


def _merge_nested_if(unit: PythonParsedUnit) -> Iterator[SourceSpan]:
    for node in ast.walk(unit.tree):
        if (
            isinstance(node, ast.If)
            and not node.orelse
            and len(node.body) == 1
            and isinstance(node.body[0], ast.If)
            and not node.body[0].orelse
            and if_header(unit, node) is not None
        ):
            found = if_header(unit, node.body[0])
            if found is not None:
                yield found


RULES = (
    *(
        rule(
            f"redundant-else-after-{name}",
            PatternCategory.CONTROL_FLOW,
            f"The preceding branch exits with {name}; review the else nesting.",
            lambda unit, terminal=terminal: _redundant_else(unit, terminal),
        )
        for name, terminal in (
            ("return", ast.Return),
            ("raise", ast.Raise),
            ("break", ast.Break),
            ("continue", ast.Continue),
        )
    ),
    rule(
        "merge-nested-if",
        PatternCategory.CONTROL_FLOW,
        "The two conditions can share one conditional header.",
        _merge_nested_if,
    ),
)
